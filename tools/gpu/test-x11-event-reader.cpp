#include "event-reader.h"
#include <assert.h>
#include <dirent.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <thread>
#include <vector>

using Result = LorieEventReader::Result;
static_assert(sizeof(lorieEvent) == 24, "Android ARM64 event ABI changed");
static_assert(offsetof(lorieEvent, screenSize.name_size) == 8, "event ABI changed");
static_assert(offsetof(lorieEvent, clipboardSend.count) == 4, "event ABI changed");

struct SocketPair {
    int fd[2];
    SocketPair() { assert(socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, fd) == 0); }
    ~SocketPair() { close(fd[0]); close(fd[1]); }
};

static void sendBytes(int fd, const void* data, size_t size) {
    const char* bytes = (const char*) data;
    while (size) {
        ssize_t count = send(fd, bytes, size, MSG_NOSIGNAL);
        if (count < 0 && errno == EINTR) continue;
        assert(count > 0);
        bytes += count;
        size -= (size_t) count;
    }
}

static Result next(LorieEventReader& reader, int fd) {
    LorieEventReader::Budget budget;
    return reader.next(fd, budget);
}

static void sendRights(int socket, const void* data, size_t size, unsigned count, char marker = '!') {
    int source = open("/dev/null", O_RDONLY | O_CLOEXEC);
    assert(source >= 0);
    std::vector<int> descriptors(count, source);
    std::vector<char> controls(CMSG_SPACE(count * sizeof(int)));
    struct iovec iov = { (void*) (data ? data : &marker), data ? size : 1 };
    struct msghdr msg{};
    msg.msg_iov = &iov;
    msg.msg_iovlen = 1;
    msg.msg_control = controls.data();
    msg.msg_controllen = controls.size();
    struct cmsghdr* header = CMSG_FIRSTHDR(&msg);
    header->cmsg_level = SOL_SOCKET;
    header->cmsg_type = SCM_RIGHTS;
    header->cmsg_len = CMSG_LEN(count * sizeof(int));
    memcpy(CMSG_DATA(header), descriptors.data(), count * sizeof(int));
    assert(sendmsg(socket, &msg, MSG_NOSIGNAL) == (ssize_t) iov.iov_len);
    close(source);
}

static unsigned openFds() {
    DIR* directory = opendir("/proc/self/fd");
    assert(directory);
    unsigned count = 0;
    while (readdir(directory)) ++count;
    closedir(directory);
    return count;
}

static void fragmentedHeaderAndOrder() {
    SocketPair sockets;
    LorieEventReader reader;
    assert(!(fcntl(sockets.fd[0], F_GETFL) & O_NONBLOCK));
    assert(next(reader, sockets.fd[0]) == Result::WouldBlock); // socket itself remains blocking
    lorieEvent unicode{};
    unicode.unicode.t = EVENT_UNICODE;
    unicode.unicode.code = 0x1f642;
    for (size_t i = 0; i < sizeof(unicode); ++i) {
        sendBytes(sockets.fd[1], (char*) &unicode + i, 1);
        assert(next(reader, sockets.fd[0]) == (i + 1 == sizeof(unicode) ? Result::Frame : Result::WouldBlock));
    }
    assert(reader.event.unicode.code == 0x1f642);
    reader.reset();
    lorieEvent events[3]{};
    events[0].key.t = EVENT_KEY;
    events[0].key.key = 36;
    events[1].type = EVENT_GPU_COPY_DONE;
    events[2].sync.t = EVENT_SYNC;
    events[2].sync.serial = 0xabcdef01;
    sendBytes(sockets.fd[1], events, sizeof(events));
    shutdown(sockets.fd[1], SHUT_WR);
    for (const auto& event : events) {
        assert(next(reader, sockets.fd[0]) == Result::Frame);
        assert(!memcmp(&reader.event, &event, sizeof(event)));
        reader.reset();
    }
    assert(next(reader, sockets.fd[0]) == Result::Closed);
}

static void fragmentedBodiesAndFollowingFrame() {
    for (unsigned type : {EVENT_SCREEN_SIZE, EVENT_CLIPBOARD_SEND}) {
        SocketPair sockets;
        LorieEventReader reader;
        lorieEvent event{};
        event.type = type;
        const char body[] = "\xc3\xa9\xe2\x80\x94\xf0\x9f\x99\x82";
        if (type == EVENT_SCREEN_SIZE) event.screenSize.name_size = sizeof(body) - 1;
        else event.clipboardSend.count = sizeof(body) - 1;
        sendBytes(sockets.fd[1], &event, sizeof(event));
        assert(next(reader, sockets.fd[0]) == Result::WouldBlock);
        for (size_t i = 0; i < sizeof(body) - 2; ++i) {
            sendBytes(sockets.fd[1], body + i, 1);
            assert(next(reader, sockets.fd[0]) == Result::WouldBlock);
        }
        lorieEvent following{};
        following.type = EVENT_KEY;
        following.key.key = 38;
        std::vector<char> final(1 + sizeof(following));
        final[0] = body[sizeof(body) - 2];
        memcpy(final.data() + 1, &following, sizeof(following));
        sendBytes(sockets.fd[1], final.data(), final.size());
        assert(next(reader, sockets.fd[0]) == Result::Frame);
        char* payload = reader.takePayload();
        assert(!memcmp(payload, body, sizeof(body))); // exact UTF-8 and terminator
        reader.reset();
        assert(!memcmp(payload, body, sizeof(body))); // ownership survives reset
        free(payload);
        assert(next(reader, sockets.fd[0]) == Result::Frame);
        assert(reader.event.key.key == 38);
    }
}

static void emptyBodiesAndLimits() {
    for (unsigned type : {EVENT_SCREEN_SIZE, EVENT_CLIPBOARD_SEND}) {
        for (bool over : {false, true}) {
            SocketPair sockets;
            LorieEventReader reader;
            lorieEvent event{};
            event.type = type;
            if (type == EVENT_SCREEN_SIZE)
                event.screenSize.name_size = over ? SIZE_MAX : 0;
            else
                event.clipboardSend.count = over ? UINT32_MAX : 0;
            sendBytes(sockets.fd[1], &event, sizeof(event));
            assert(next(reader, sockets.fd[0]) == (over ? Result::Error : Result::Frame));
            if (over) assert(reader.error == EMSGSIZE);
            else {
                char* payload = reader.takePayload();
                assert(type == EVENT_SCREEN_SIZE ? payload == nullptr : payload && !payload[0]);
                free(payload);
            }
        }
    }
    SocketPair sockets;
    LorieEventReader reader;
    lorieEvent wrong{};
    wrong.type = EVENT_ADD_BUFFER; // server-to-client frame: cannot be skipped safely
    sendBytes(sockets.fd[1], &wrong, sizeof(wrong));
    assert(next(reader, sockets.fd[0]) == Result::Error);
    assert(reader.error == EPROTO);
}

static void exactBoundsAndIndependentConnections() {
    SocketPair sockets;
    LorieEventReader reader;
    lorieEvent event{};
    event.type = EVENT_SCREEN_SIZE;
    event.screenSize.name_size = LORIE_MAX_SCREEN_NAME_BYTES;
    std::vector<char> name(event.screenSize.name_size, 'n');
    sendBytes(sockets.fd[1], &event, sizeof(event));
    sendBytes(sockets.fd[1], name.data(), name.size());
    assert(next(reader, sockets.fd[0]) == Result::Frame);
    char* received = reader.takePayload();
    assert(!memcmp(received, name.data(), name.size()) && !received[name.size()]);
    free(received);
    reader.reset();
    event.screenSize.name_size = LORIE_MAX_SCREEN_NAME_BYTES + 1;
    sendBytes(sockets.fd[1], &event, sizeof(event));
    assert(next(reader, sockets.fd[0]) == Result::Error && reader.error == EMSGSIZE);
    event = {};
    event.type = EVENT_CLIPBOARD_SEND;
    event.clipboardSend.count = LORIE_MAX_CLIPBOARD_BYTES + 1;
    sendBytes(sockets.fd[1], &event, sizeof(event));
    assert(next(reader, sockets.fd[0]) == Result::Error && reader.error == EMSGSIZE);

    event.clipboardSend.count = 16;
    sendBytes(sockets.fd[1], &event, sizeof(event));
    sendBytes(sockets.fd[1], "pending", 7);
    assert(next(reader, sockets.fd[0]) == Result::WouldBlock);
    SocketPair replacement;
    LorieEventReader reconnected;
    event = {};
    event.type = EVENT_UNICODE;
    event.unicode.code = 0xe9;
    sendBytes(replacement.fd[1], &event, sizeof(event));
    assert(next(reconnected, replacement.fd[0]) == Result::Frame);
    assert(reconnected.event.unicode.code == 0xe9);
    reader.reset(); // disconnect discards old incomplete payload, without affecting new state
    assert(reconnected.event.unicode.code == 0xe9);
}

static void incompleteEofEveryBoundary() {
    const char body[] = "screen";
    lorieEvent event{};
    event.screenSize.t = EVENT_SCREEN_SIZE;
    event.screenSize.name_size = sizeof(body) - 1;
    std::vector<char> frame(sizeof(event) + sizeof(body) - 1);
    memcpy(frame.data(), &event, sizeof(event));
    memcpy(frame.data() + sizeof(event), body, sizeof(body) - 1);
    for (size_t length = 1; length < frame.size(); ++length) {
        SocketPair sockets;
        LorieEventReader reader;
        sendBytes(sockets.fd[1], frame.data(), length);
        assert(next(reader, sockets.fd[0]) == Result::WouldBlock);
        shutdown(sockets.fd[1], SHUT_WR);
        assert(next(reader, sockets.fd[0]) == Result::Error);
        assert(reader.error == EPROTO);
    }
    SocketPair sockets;
    LorieEventReader reader;
    event = {};
    event.type = EVENT_RENDERER_WAKEUP_COND;
    sendBytes(sockets.fd[1], &event, sizeof(event));
    assert(next(reader, sockets.fd[0]) == Result::WouldBlock);
    shutdown(sockets.fd[1], SHUT_WR);
    assert(next(reader, sockets.fd[0]) == Result::Error);
}

static void descriptorsAndCleanup() {
    for (unsigned rights : {1, 2, 8}) {
        SocketPair sockets;
        unsigned baseline = openFds();
        {
            LorieEventReader reader;
            lorieEvent event{};
            event.type = EVENT_RENDERER_WAKEUP_COND;
            sendBytes(sockets.fd[1], &event, sizeof(event));
            assert(next(reader, sockets.fd[0]) == Result::WouldBlock);
            sendRights(sockets.fd[1], nullptr, 0, rights);
            lorieEvent nextEvent{};
            nextEvent.sync.t = EVENT_SYNC;
            nextEvent.sync.serial = 16;
            sendBytes(sockets.fd[1], &nextEvent, sizeof(nextEvent));
            assert(next(reader, sockets.fd[0]) == (rights == 1 ? Result::Frame : Result::Error));
            if (rights == 1) {
                int fd = reader.takeDescriptor();
                assert(fd >= 0 && (fcntl(fd, F_GETFD) & FD_CLOEXEC));
                reader.reset();
                assert(fcntl(fd, F_GETFD) >= 0);
                close(fd);
                assert(next(reader, sockets.fd[0]) == Result::Frame);
                assert(reader.event.sync.serial == 16);
            }
        }
        assert(openFds() == baseline);
    }
    // Destruction owns an untaken descriptor, and invalid/missing/misplaced
    // rights are rejected without leaks or consuming the next event as a header.
    for (unsigned mode = 0; mode < 5; ++mode) {
        SocketPair sockets;
        unsigned baseline = openFds();
        {
            LorieEventReader reader;
            lorieEvent event{};
            event.type = mode == 3 ? EVENT_UNICODE : EVENT_RENDERER_WAKEUP_COND;
            if (mode == 3) sendRights(sockets.fd[1], &event, sizeof(event), 1);
            else {
                sendBytes(sockets.fd[1], &event, sizeof(event));
                if (mode == 2) sendBytes(sockets.fd[1], "!", 1);
                else sendRights(sockets.fd[1], nullptr, 0, 1, mode == 1 ? '?' : '!');
            }
            assert(next(reader, sockets.fd[0]) == (mode == 0 || mode == 4 ? Result::Frame : Result::Error));
            if (mode == 4) reader.reset();
        }
        assert(openFds() == baseline);
    }
}

static void budgetAndMaximumBody() {
    SocketPair sockets;
    LorieEventReader reader;
    lorieEvent event{};
    event.type = EVENT_CLIPBOARD_SEND;
    event.clipboardSend.count = LORIE_MAX_CLIPBOARD_BYTES;
    std::vector<char> payload(event.clipboardSend.count);
    for (size_t i = 0; i < payload.size(); ++i) payload[i] = 'a' + i % 26;
    std::thread producer([&] {
        sendBytes(sockets.fd[1], &event, sizeof(event));
        sendBytes(sockets.fd[1], payload.data(), payload.size());
    });
    unsigned yielded = 0;
    while (true) {
        LorieEventReader::Budget budget;
        Result result = reader.next(sockets.fd[0], budget);
        assert(budget.bytes <= 64u * 1024u && budget.calls <= 256);
        if (result == Result::Frame) break;
        if (result == Result::Yield) {
            assert(!budget.bytes || !budget.calls);
            ++yielded;
        } else {
            assert(result == Result::WouldBlock);
            struct pollfd wait{ sockets.fd[0], POLLIN, 0 };
            assert(poll(&wait, 1, 1000) == 1);
        }
    }
    producer.join();
    assert(yielded);
    char* received = reader.takePayload();
    assert(!memcmp(received, payload.data(), payload.size()));
    assert(!received[payload.size()]);
    free(received);
    reader.reset();
    event = {};
    event.type = EVENT_UNICODE;
    sendBytes(sockets.fd[1], &event, sizeof(event));
    for (size_t i = 0; i < sizeof(event); ++i) {
        LorieEventReader::Budget budget;
        budget.bytes = budget.calls = 1;
        assert(reader.next(sockets.fd[0], budget) == (i + 1 == sizeof(event) ? Result::Frame : Result::Yield));
    }
}

int main() {
    alarm(20); // A blocking regression must fail, not hang the host test runner.
    fragmentedHeaderAndOrder();
    fragmentedBodiesAndFollowingFrame();
    emptyBodiesAndLimits();
    exactBoundsAndIndependentConnections();
    incompleteEofEveryBoundary();
    descriptorsAndCleanup();
    budgetAndMaximumBody();
    puts("PASS: exact framing, ordering, partial/empty/max bodies, budgets, EOF, SCM_RIGHTS ownership and rejection");
}
