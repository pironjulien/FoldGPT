#include <atomic>
#include <cassert>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <linux/input-event-codes.h>
#include <mutex>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>
#include <vector>
#include "event-protocol.h"

// Instrument only syscall outcomes/scheduling. All successful bytes and fd
// transfers still use a real AF_UNIX/SOCK_STREAM socketpair.
static std::atomic<int> injectMode{0}, calls{0};
static std::mutex gateMutex;
static std::condition_variable gate;
static bool headerPaused = false, releaseHeader = false;
static ssize_t testSend(int fd, const void* bytes, size_t size, int flags) {
    ++calls;
    assert(flags & MSG_NOSIGNAL);
    int mode = injectMode.load();
    if (mode == 1) { errno = EINTR; return -1; }
    if (mode == 2) return send(fd, bytes, size / 2, flags);
    if (mode == 3) return 0;
    if (mode == 4 && size == sizeof(lorieEvent) &&
        static_cast<const lorieEvent*>(bytes)->type == EVENT_CLIPBOARD_SEND) {
        ssize_t sent = send(fd, bytes, size, flags);
        std::unique_lock<std::mutex> lock(gateMutex);
        headerPaused = true;
        gate.notify_all();
        gate.wait(lock, [] { return releaseHeader; });
        return sent;
    }
    if (mode == 7) {
        std::unique_lock<std::mutex> lock(gateMutex);
        headerPaused = true;
        gate.notify_all();
        gate.wait(lock, [] { return releaseHeader; });
    }
    // Force legacy send loops through real partial writes.
    if (mode == 5 && size > 7)
        size = 7;
    if (mode == 6 && injectMode.exchange(0) == 6) {
        errno = EINTR;
        return -1;
    }
    return send(fd, bytes, size, flags);
}
#define send testSend
#include "client-writer.h"
#undef send

static int readCalls = 0;
static bool interruptRead = false;
static ssize_t testRead(int fd, void* bytes, size_t size) {
    ++readCalls;
    if (interruptRead) {
        interruptRead = false;
        errno = EINTR;
        return -1;
    }
    // Real reads split across syscall boundaries even when all bytes are ready.
    return read(fd, bytes, size > 3 ? 3 : size);
}
#define read testRead
#include "clipboard-reader.h"
#undef read

#define __unused __attribute__((unused))
using JNIEnv = void;
using jobject = void*;
using jlong = int64_t;
using jint = int32_t;
using jboolean = uint8_t;
struct LorieViewResources {
    int connFd = -1;
    LorieClientWriter writer{connFd};
    bool destroyed = false;
    int disconnected = 0;
    void connect(int fd) { writer.replace(fd); ++disconnected; }
};
static int64_t lastInputTimestampMs = 0;
static int64_t nowMs() { return 1618; }
#include "checked-input-under-test.inc"

static void receive(int fd, void* data, size_t size) {
    assert(recv(fd, data, size, MSG_WAITALL) == static_cast<ssize_t>(size));
}

static void checkedInput() {
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    LorieViewResources resource;
    resource.writer.replace(pair[0]);
    auto ptr = reinterpret_cast<jlong>(&resource);
    auto invoke = [&](int code, bool unicode, bool down = true) {
        return sendInputEventChecked(nullptr, nullptr, ptr, code, unicode, down);
    };
    int assertions = 0;
    assert(sendInputEventChecked(nullptr, nullptr, 0, 65, true, true) == -1); ++assertions;
    for (int code : {-1, 0x110000, 0xD800, 0xDFFF}) {
        int before = calls;
        assert(invoke(code, true) == -1 && calls == before); ++assertions;
    }
    for (int code : {-1, 0, 304, 999999}) {
        int before = calls;
        assert(invoke(code, false) == -1 && calls == before); ++assertions;
    }
    resource.destroyed = true;
    assert(invoke(65, true) == -1);
    resource.destroyed = false; ++assertions;
    lorieEvent frame = {};
    for (int code : {0, 65, 0xE9, 0x1F642, 0x10FFFF}) {
        assert(invoke(code, true) == 1);
        receive(pair[1], &frame, sizeof(frame));
        assert(frame.type == EVENT_UNICODE && frame.unicode.code == static_cast<uint32_t>(code)); ++assertions;
    }
    assert(invoke(29, false, true) == 1);
    receive(pair[1], &frame, sizeof(frame));
    assert(frame.type == EVENT_KEY && frame.key.key == KEY_A + 8 && frame.key.state); ++assertions;
    assert(invoke(29, false, false) == 1);
    receive(pair[1], &frame, sizeof(frame));
    assert(!frame.key.state); ++assertions;
    injectMode = 1;
    assert(invoke(65, true) == 0 && resource.connFd == pair[0]); ++assertions;
    injectMode = 0;
    int size = 1024;
    assert(setsockopt(pair[0], SOL_SOCKET, SO_SNDBUF, &size, sizeof(size)) == 0);
    while (invoke(65, true) == 1) {}
    assert(errno == EAGAIN || errno == EWOULDBLOCK);
    assert(resource.connFd == pair[0]); ++assertions;
    while (recv(pair[1], &frame, sizeof(frame), MSG_DONTWAIT) > 0) {}
    assert(invoke(66, true) == 1);
    receive(pair[1], &frame, sizeof(frame));
    assert(frame.unicode.code == 66); ++assertions;
    injectMode = 2;
    assert(invoke(65, true) == -1);
    assert(resource.connFd == -1 && resource.disconnected == 1); ++assertions;
    assert(recv(pair[1], &frame, sizeof(frame), MSG_WAITALL) == sizeof(frame) / 2);
    assert(recv(pair[1], &frame, sizeof(frame), 0) == 0);
    close(pair[1]); ++assertions;
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    resource.writer.replace(pair[0]);
    injectMode = 0;
    close(pair[1]);
    assert(invoke(65, true) == -1 && resource.connFd == -1); ++assertions;
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    resource.writer.replace(pair[0]);
    injectMode = 3;
    assert(invoke(65, true) == -1 && resource.connFd == -1);
    close(pair[1]); ++assertions;
    assert(lastInputTimestampMs == 1618); ++assertions;
    injectMode = 0;
    printf("checked JNI: %d cases passed (real frames/EAGAIN/retry/peer close; injected EINTR/partial/zero)\n", assertions);
}

static void pausedBodyWithGpu() {
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    LorieViewResources resource;
    resource.writer.replace(pair[0]);
    const char body[] = "clipboard body remains contiguous";
    lorieEvent clipboard = {}, gpu = {}, frame = {};
    clipboard.clipboardSend.t = EVENT_CLIPBOARD_SEND;
    clipboard.clipboardSend.count = sizeof(body);
    gpu.type = EVENT_GPU_COPY_DONE;
    injectMode = 4;
    std::thread producer([&] { assert(resource.writer.sendFrame(&clipboard, sizeof(clipboard), body, sizeof(body))); });
    {
        std::unique_lock<std::mutex> lock(gateMutex);
        gate.wait(lock, [] { return headerPaused; });
    }
    std::thread renderer([&] { assert(resource.writer.sendFrame(&gpu, sizeof(gpu))); });
    // The clipboard producer deliberately owns the mutex indefinitely here.
    // A checked JNI call must return zero without waiting or sending anything.
    int before = calls;
    assert(sendInputEventChecked(nullptr, nullptr, reinterpret_cast<jlong>(&resource), 0x1F642, true, true) == 0);
    assert(calls == before);
    {
        std::lock_guard<std::mutex> lock(gateMutex);
        releaseHeader = true;
    }
    gate.notify_all();
    producer.join();
    renderer.join();
    injectMode = 0;
    receive(pair[1], &frame, sizeof(frame));
    assert(frame.type == EVENT_CLIPBOARD_SEND && frame.clipboardSend.count == sizeof(body));
    char received[sizeof(body)];
    receive(pair[1], received, sizeof(received));
    assert(memcmp(received, body, sizeof(body)) == 0);
    receive(pair[1], &frame, sizeof(frame));
    assert(frame.type == EVENT_GPU_COPY_DONE);
    assert(sendInputEventChecked(nullptr, nullptr, reinterpret_cast<jlong>(&resource), 0x1F642, true, true) == 1);
    receive(pair[1], &frame, sizeof(frame));
    assert(frame.type == EVENT_UNICODE && frame.unicode.code == 0x1F642);
    resource.writer.replace(-1);
    close(pair[1]);
    puts("paused clipboard header/body + concurrent GPU: checked JNI returns retry without waiting; frames intact");
}

static void concurrentFrames() {
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    int fd = -1;
    LorieClientWriter writer(fd);
    writer.replace(pair[0]);
    int descriptor = open("/dev/null", O_RDONLY | O_CLOEXEC);
    assert(descriptor >= 0);
    constexpr int count = 256;
    std::thread consumer([&] {
        int counts[5] = {};
        for (int i = 0; i < 5 * count; ++i) {
            lorieEvent frame = {};
            receive(pair[1], &frame, sizeof(frame));
            if (frame.type == EVENT_CLIPBOARD_SEND || frame.type == EVENT_SCREEN_SIZE) {
                bool clipboard = frame.type == EVENT_CLIPBOARD_SEND;
                size_t size = clipboard ? frame.clipboardSend.count : frame.screenSize.name_size;
                assert(size == (clipboard ? 4096 : 1023));
                std::vector<char> body(size);
                receive(pair[1], body.data(), size);
                for (char c : body) assert(c == (clipboard ? 'c' : 's'));
                ++counts[clipboard ? 0 : 1];
            } else if (frame.type == EVENT_RENDERER_WAKEUP_COND) {
                char token;
                iovec iov = { &token, 1 };
                alignas(cmsghdr) char control[CMSG_SPACE(sizeof(int))] = {};
                msghdr message = {};
                message.msg_iov = &iov; message.msg_iovlen = 1;
                message.msg_control = control; message.msg_controllen = sizeof(control);
                assert(recvmsg(pair[1], &message, MSG_CMSG_CLOEXEC) == 1 && token == '!');
                cmsghdr* cmsg = CMSG_FIRSTHDR(&message);
                assert(cmsg && cmsg->cmsg_type == SCM_RIGHTS && !(message.msg_flags & MSG_CTRUNC));
                int received;
                memcpy(&received, CMSG_DATA(cmsg), sizeof(received));
                assert(fcntl(received, F_GETFD) & FD_CLOEXEC);
                char value;
                assert(read(received, &value, 1) == 0);
                close(received);
                ++counts[2];
            } else if (frame.type == EVENT_GPU_COPY_DONE) {
                ++counts[3];
            } else {
                assert(frame.type == EVENT_UNICODE && frame.unicode.code == 0x1F642);
                ++counts[4];
            }
        }
        for (int value : counts) assert(value == count);
    });
    auto writeBody = [&](bool clipboard) {
        std::vector<char> body(clipboard ? 4096 : 1023, clipboard ? 'c' : 's');
        lorieEvent event = {};
        if (clipboard) {
            event.clipboardSend.t = EVENT_CLIPBOARD_SEND;
            event.clipboardSend.count = body.size();
        } else {
            event.screenSize.t = EVENT_SCREEN_SIZE;
            event.screenSize.name_size = body.size();
        }
        for (int i = 0; i < count; ++i) assert(writer.sendFrame(&event, sizeof(event), body.data(), body.size()));
    };
    std::thread clipboard([&] { writeBody(true); });
    std::thread screen([&] { writeBody(false); });
    std::thread rights([&] {
        lorieEvent event = {}; event.type = EVENT_RENDERER_WAKEUP_COND;
        for (int i = 0; i < count; ++i) assert(writer.sendFrame(&event, sizeof(event), nullptr, 0, descriptor));
    });
    std::thread gpu([&] {
        lorieEvent event = {}; event.type = EVENT_GPU_COPY_DONE;
        for (int i = 0; i < count; ++i) assert(writer.sendFrame(&event, sizeof(event)));
    });
    std::thread unicode([&] {
        lorieEvent event = {}; event.unicode.t = EVENT_UNICODE; event.unicode.code = 0x1F642;
        for (int i = 0; i < count;) {
            int sent = writer.sendChecked(&event, sizeof(event));
            assert(sent >= 0);
            if (sent) ++i;
            else std::this_thread::yield();
        }
    });
    clipboard.join(); screen.join(); rights.join(); gpu.join(); unicode.join(); consumer.join();
    writer.replace(-1);
    close(pair[1]); close(descriptor);
    puts("1280 concurrent clipboard/screen-name/SCM_RIGHTS/GPU/checked-Unicode frames decoded intact");
}

static void lifecycleAndLegacyErrors() {
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    int fd = -1;
    LorieClientWriter writer(fd);
    writer.replace(pair[0]);
    lorieEvent event = {}, frame = {};
    event.type = EVENT_GPU_COPY_DONE;
    injectMode = 5;
    assert(writer.sendFrame(&event, sizeof(event)));
    receive(pair[1], &frame, sizeof(frame));
    assert(memcmp(&frame, &event, sizeof(frame)) == 0);
    injectMode = 6;
    assert(writer.sendFrame(&event, sizeof(event)));
    receive(pair[1], &frame, sizeof(frame));
    assert(frame.type == EVENT_GPU_COPY_DONE);
    // Force descriptor replacement while a producer owns the writer mutex.
    // Peer EOF proves shutdown ran before the replacement waits for that mutex.
    int size = 1024;
    assert(setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &size, sizeof(size)) == 0);
    while (writer.sendChecked(&event, sizeof(event)) == 1) {}
    headerPaused = releaseHeader = false;
    injectMode = 7;
    std::thread renderer([&] { assert(!writer.sendFrame(&event, sizeof(event))); });
    {
        std::unique_lock<std::mutex> lock(gateMutex);
        gate.wait(lock, [] { return headerPaused; });
    }
    std::thread replacer([&] { writer.replace(-1); });
    while (recv(pair[1], &frame, sizeof(frame), 0) > 0) {}
    {
        std::lock_guard<std::mutex> lock(gateMutex);
        releaseHeader = true;
    }
    gate.notify_all();
    renderer.join();
    replacer.join();
    injectMode = 0;
    close(pair[1]);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    writer.replace(pair[0]);
    assert(writer.sendChecked(&event, sizeof(event)) == 1);
    receive(pair[1], &frame, sizeof(frame));
    assert(frame.type == EVENT_GPU_COPY_DONE);
    // Fatal body failure poisons the stream before another producer can enter.
    injectMode = 3;
    assert(!writer.sendFrame(&event, sizeof(event)));
    injectMode = 0;
    assert(writer.sendChecked(&event, sizeof(event)) == -1);
    assert(recv(pair[1], &frame, sizeof(frame), 0) == 0);
    writer.replace(-1);
    close(pair[1]);
    puts("legacy partial/EINTR retries, shutdown during writer ownership, reconnect and fatal-stream exclusion passed");
}

static void returnClipboardFraming() {
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    lorieEvent sync = {}, received = {};
    sync.sync.t = EVENT_SYNC_REPLY;
    sync.sync.serial = 0x12345678;
    // A real UTF-8 body contains both embedded NUL and a supplementary code point.
    const char body[] = {'c', '\0', 'x', '\xF0', '\x9F', '\x99', '\x82'};
    assert(send(pair[0], body, sizeof(body), MSG_NOSIGNAL) == sizeof(body));
    assert(send(pair[0], &sync, sizeof(sync), MSG_NOSIGNAL) == sizeof(sync));
    LorieClipboardData clipboard;
    interruptRead = true;
    assert(clipboard.readFrom(pair[1], sizeof(body)));
    assert(readCalls == 4 && memcmp(clipboard.bytes, body, sizeof(body)) == 0);
    assert(clipboard.bytes[sizeof(body)] == '\0');
    receive(pair[1], &received, sizeof(received));
    assert(memcmp(&received, &sync, sizeof(sync)) == 0);
    // Empty clipboard is meaningful and does not consume the next reply.
    assert(send(pair[0], &sync, sizeof(sync), MSG_NOSIGNAL) == sizeof(sync));
    int before = readCalls;
    assert(clipboard.readFrom(pair[1], 0));
    assert(readCalls == before && clipboard.bytes && clipboard.bytes[0] == '\0');
    receive(pair[1], &received, sizeof(received));
    assert(memcmp(&received, &sync, sizeof(sync)) == 0);
    // Oversize fails before allocating or reading even a header byte.
    assert(send(pair[0], &sync, sizeof(sync), MSG_NOSIGNAL) == sizeof(sync));
    assert(!clipboard.readFrom(pair[1], static_cast<size_t>(LORIE_MAX_CLIPBOARD_BYTES) + 1));
    assert(errno == EMSGSIZE && !clipboard.bytes && readCalls == before);
    receive(pair[1], &received, sizeof(received));
    assert(memcmp(&received, &sync, sizeof(sync)) == 0);
    // EOF in a body fails instead of exposing uninitialized/truncated text.
    assert(send(pair[0], body, 2, MSG_NOSIGNAL) == 2);
    shutdown(pair[0], SHUT_WR);
    assert(!clipboard.readFrom(pair[1], sizeof(body)) && errno == ECONNRESET);
    close(pair[0]); close(pair[1]);
    puts("return clipboard: exact body + next sync preserved, partial/EINTR, embedded NUL, empty, oversize and truncated EOF passed");
}

int main() {
    checkedInput();
    pausedBodyWithGpu();
    concurrentFrames();
    lifecycleAndLegacyErrors();
    returnClipboardFraming();
}
