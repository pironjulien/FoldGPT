/* Transparent stdio <-> private Unix stream transport. No command/policy parser,
 * no TCP listener, and no authentication claim beyond kernel peer UID.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define BUFFER_SIZE 65536
#define CONNECT_TIMEOUT_MS 30000 /* Official environment initialization window. */
struct buffer { unsigned char data[BUFFER_SIZE]; size_t start, end; };
static volatile sig_atomic_t interrupted;
static void on_signal(int number) { interrupted = number; }
static int transient(void) { return errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK; }
static int64_t now_ms(void)
{
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) return -1;
    return (int64_t)value.tv_sec * 1000 + value.tv_nsec / 1000000;
}

static int connect_peer(const char *path, uid_t expected)
{
    struct sockaddr_un address = { .sun_family = AF_UNIX };
    if (path[0] != '/' || strlen(path) >= sizeof address.sun_path) { errno = EINVAL; return -1; }
    memcpy(address.sun_path, path, strlen(path) + 1);
    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    if (fd < 0) return -1;
    if (connect(fd, (struct sockaddr *)&address,
                (socklen_t)(offsetof(struct sockaddr_un, sun_path) + strlen(path) + 1)) != 0) {
        if (errno != EINPROGRESS) goto failure;
        int64_t deadline = now_ms();
        if (deadline < 0) goto failure;
        deadline += CONNECT_TIMEOUT_MS;
        for (;;) {
            int64_t remaining = deadline - now_ms();
            if (interrupted) { errno = EINTR; goto failure; }
            if (remaining <= 0) { errno = ETIMEDOUT; goto failure; }
            struct pollfd event = { .fd = fd, .events = POLLOUT };
            int result = poll(&event, 1, (int)remaining);
            if (result < 0 && errno == EINTR) continue;
            if (result <= 0) { if (result == 0) errno = ETIMEDOUT; goto failure; }
            int error = 0;
            socklen_t length = sizeof error;
            if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &length) != 0) goto failure;
            if (error != 0) { errno = error; goto failure; }
            break;
        }
    }
    struct ucred credentials;
    socklen_t length = sizeof credentials;
    if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &credentials, &length) != 0) goto failure;
    if (length != sizeof credentials || credentials.pid <= 0 || credentials.uid != expected) {
        errno = EACCES;
        goto failure;
    }
    return fd;
failure:;
    int saved = errno;
    close(fd);
    errno = saved;
    return -1;
}

static void compact(struct buffer *buffer)
{
    if (buffer->start == buffer->end) buffer->start = buffer->end = 0;
    else if (buffer->start > 0) {
        memmove(buffer->data, buffer->data + buffer->start, buffer->end - buffer->start);
        buffer->end -= buffer->start;
        buffer->start = 0;
    }
}

static int relay(int peer)
{
    struct buffer to_peer = {0}, to_stdout = {0};
    int input_eof = 0, peer_eof = 0, write_closed = 0;
    while (!interrupted) {
        compact(&to_peer);
        compact(&to_stdout);
        if (input_eof && to_peer.end == 0 && !write_closed) {
            if (shutdown(peer, SHUT_WR) != 0 && errno != ENOTCONN) return -1;
            write_closed = 1;
        }
        if (peer_eof && to_stdout.end == 0) {
            if (!input_eof || to_peer.end != 0) { errno = ECONNRESET; return -1; }
            return 0;
        }
        struct pollfd events[3] = {
            { .fd = !input_eof && !peer_eof && to_peer.end < BUFFER_SIZE ? STDIN_FILENO : -1,
              .events = POLLIN },
            { .fd = to_stdout.end ? STDOUT_FILENO : -1, .events = POLLOUT },
            { .fd = peer, .events = 0 }
        };
        if (!peer_eof && to_stdout.end < BUFFER_SIZE) events[2].events |= POLLIN;
        if (!peer_eof && to_peer.end) events[2].events |= POLLOUT;
        if (!events[2].events) events[2].fd = -1;
        int result = poll(events, 3, -1);
        if (result < 0) { if (errno == EINTR) continue; return -1; }
        if (events[1].revents & (POLLERR | POLLHUP | POLLNVAL)) { errno = EPIPE; return -1; }
        if (events[1].revents & POLLOUT) {
            ssize_t size = write(STDOUT_FILENO, to_stdout.data, to_stdout.end);
            if (size > 0) to_stdout.start = (size_t)size;
            else if (size == 0 || !transient()) { if (size == 0) errno = EIO; return -1; }
        }
        if (events[0].revents & (POLLIN | POLLHUP)) {
            ssize_t size = read(STDIN_FILENO, to_peer.data + to_peer.end, BUFFER_SIZE - to_peer.end);
            if (size > 0) to_peer.end += (size_t)size;
            else if (size == 0) input_eof = 1;
            else if (!transient()) return -1;
        }
        if (events[0].revents & (POLLERR | POLLNVAL)) { errno = EIO; return -1; }
        if (events[2].revents & POLLOUT && to_peer.end) {
            ssize_t size = send(peer, to_peer.data, to_peer.end, MSG_NOSIGNAL);
            if (size > 0) to_peer.start = (size_t)size;
            else if (size == 0 || !transient()) { if (size == 0) errno = EIO; return -1; }
        }
        if (events[2].revents & (POLLIN | POLLHUP) && to_stdout.end < BUFFER_SIZE) {
            ssize_t size = recv(peer, to_stdout.data + to_stdout.end, BUFFER_SIZE - to_stdout.end, 0);
            if (size > 0) to_stdout.end += (size_t)size;
            else if (size == 0) peer_eof = 1;
            else if (!transient()) return -1;
        }
        if (events[2].revents & (POLLERR | POLLNVAL)) { errno = ECONNRESET; return -1; }
    }
    errno = EINTR;
    return -1;
}

int main(int argc, char **argv)
{
    if (argc != 5 || strcmp(argv[1], "--socket") || strcmp(argv[3], "--peer-uid")) {
        fprintf(stderr, "Usage: %s --socket ABSOLUTE_PATH --peer-uid UID\n", argv[0]);
        return 64;
    }
    if (!argv[4][0] || strspn(argv[4], "0123456789") != strlen(argv[4])) return 64;
    char *end = NULL;
    errno = 0;
    unsigned long value = strtoul(argv[4], &end, 10);
    if (errno || *end || value == 0 || value >= INT_MAX) return 64;
    struct sigaction action = {0};
    sigemptyset(&action.sa_mask);
    action.sa_handler = on_signal;
    if (sigaction(SIGTERM, &action, NULL) || sigaction(SIGINT, &action, NULL)) return 71;
    action.sa_handler = SIG_IGN;
    if (sigaction(SIGPIPE, &action, NULL)) return 71;
    int peer = connect_peer(argv[2], (uid_t)value);
    if (peer < 0) { fprintf(stderr, "Private broker authentication/connect failed: %s\n", strerror(errno)); return 77; }
    int input_flags = fcntl(STDIN_FILENO, F_GETFL);
    int output_flags = fcntl(STDOUT_FILENO, F_GETFL);
    int result = -1;
    if (input_flags >= 0 && output_flags >= 0 &&
        fcntl(STDIN_FILENO, F_SETFL, input_flags | O_NONBLOCK) == 0 &&
        fcntl(STDOUT_FILENO, F_SETFL, output_flags | O_NONBLOCK) == 0)
        result = relay(peer);
    int error = errno;
    shutdown(peer, SHUT_RDWR);
    close(peer);
    if (input_flags >= 0) (void)fcntl(STDIN_FILENO, F_SETFL, input_flags);
    if (output_flags >= 0) (void)fcntl(STDOUT_FILENO, F_SETFL, output_flags);
    if (result < 0) {
        fprintf(stderr, "Private broker transport closed: %s\n", strerror(error));
        return interrupted ? 128 + interrupted : 74;
    }
    return 0;
}
