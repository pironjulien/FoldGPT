#pragma once

#include <cerrno>
#include <cstring>
#include <pthread.h>
#include <sys/socket.h>
#include <unistd.h>

// Every producer on a LorieView's stream shares this writer. The mutex covers
// the complete frame, including a variable body or the SCM_RIGHTS token, and
// descriptor replacement. Only the Android main thread replaces the fd.
class LorieClientWriter {
    int& fd_;
    pthread_mutex_t mutex_ = PTHREAD_MUTEX_INITIALIZER;
    bool failed_ = false;

    void failLocked() {
        failed_ = true;
        // A truncated frame must never be followed by another event. Shutdown
        // also wakes the main-thread looper so it can release renderer state.
        if (fd_ != -1)
            shutdown(fd_, SHUT_RDWR);
    }

    bool sendBytesLocked(const void* data, size_t size) {
        auto* bytes = static_cast<const char*>(data);
        while (size) {
            ssize_t sent = send(fd_, bytes, size, MSG_NOSIGNAL);
            if (sent > 0) {
                bytes += sent;
                size -= static_cast<size_t>(sent);
            } else if (sent < 0 && errno == EINTR) {
                continue;
            } else {
                failLocked();
                return false;
            }
        }
        return true;
    }

    bool sendDescriptorLocked(int descriptor) {
        char token = '!'; // Existing ancil_send_fd wire format.
        iovec iov = { &token, sizeof(token) };
        alignas(cmsghdr) char control[CMSG_SPACE(sizeof(int))] = {};
        msghdr message = {};
        message.msg_iov = &iov;
        message.msg_iovlen = 1;
        message.msg_control = control;
        message.msg_controllen = sizeof(control);
        cmsghdr* cmsg = CMSG_FIRSTHDR(&message);
        cmsg->cmsg_level = SOL_SOCKET;
        cmsg->cmsg_type = SCM_RIGHTS;
        cmsg->cmsg_len = CMSG_LEN(sizeof(int));
        memcpy(CMSG_DATA(cmsg), &descriptor, sizeof(descriptor));
        ssize_t sent;
        do {
            sent = sendmsg(fd_, &message, MSG_NOSIGNAL);
        } while (sent < 0 && errno == EINTR);
        if (sent == sizeof(token))
            return true;
        failLocked();
        return false;
    }

public:
    explicit LorieClientWriter(int& fd) : fd_(fd) {}
    ~LorieClientWriter() { pthread_mutex_destroy(&mutex_); }
    LorieClientWriter(const LorieClientWriter&) = delete;
    LorieClientWriter& operator=(const LorieClientWriter&) = delete;

    // Main-thread lifecycle operation. Wake a blocked background send before
    // waiting for its lock; it cannot retain a descriptor that gets reused.
    void replace(int fd) {
        if (fd_ != -1)
            shutdown(fd_, SHUT_RDWR);
        pthread_mutex_lock(&mutex_);
        if (fd_ != -1)
            close(fd_);
        fd_ = fd;
        failed_ = false;
        pthread_mutex_unlock(&mutex_);
    }

    bool sendFrame(const void* header, size_t headerSize,
                   const void* body = nullptr, size_t bodySize = 0,
                   int descriptor = -1) {
        pthread_mutex_lock(&mutex_);
        bool sent = fd_ != -1 && !failed_;
        if (sent)
            sent = sendBytesLocked(header, headerSize) &&
                   sendBytesLocked(body, bodySize) &&
                   (descriptor == -1 || sendDescriptorLocked(descriptor));
        pthread_mutex_unlock(&mutex_);
        return sent;
    }

    // One nonblocking attempt, with no mutex wait. Zero means no bytes entered
    // the stream; callers may retry the same event. A partial frame is fatal.
    int sendChecked(const void* event, size_t size) {
        int locked = pthread_mutex_trylock(&mutex_);
        if (locked != 0)
            return locked == EBUSY ? 0 : -1;
        int result = -1;
        if (fd_ != -1 && !failed_) {
            ssize_t sent = send(fd_, event, size, MSG_DONTWAIT | MSG_NOSIGNAL);
            if (sent == static_cast<ssize_t>(size))
                result = 1;
            else if (sent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR))
                result = 0;
            else
                failLocked();
        }
        pthread_mutex_unlock(&mutex_);
        return result;
    }
};
