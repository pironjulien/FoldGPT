#pragma once

#include "event-protocol.h"
#include <errno.h>
#include <new>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

// One decoder per connection, called only by the X server thread. A successful
// frame owns its payload/descriptor until explicitly taken or reset. Nothing is
// dispatched until the whole header, body, and SCM_RIGHTS marker is present.
class LorieEventReader {
public:
    enum class Result { Frame, WouldBlock, Yield, Closed, Error };
    // Limit dispatcher work, not accepted frame length. SetNotifyFd is level
    // triggered, so unread bytes trigger another turn without a timer or sleep.
    struct Budget {
        size_t bytes = 64u * 1024u;
        unsigned calls = 256;
    };

    lorieEvent event{};
    int error = 0;
    const char* errorMessage = nullptr;

    LorieEventReader() = default;
    LorieEventReader(const LorieEventReader&) = delete;
    LorieEventReader& operator=(const LorieEventReader&) = delete;
    ~LorieEventReader() { reset(); }

    // Xlorie links without a C++ runtime, like LorieViewResources. Keep
    // allocation fallible using libc and initialize through placement new.
    static LorieEventReader* create() {
        void* storage = malloc(sizeof(LorieEventReader));
        return storage ? new (storage) LorieEventReader : nullptr;
    }

    static void destroy(LorieEventReader* reader) {
        if (reader) {
            reader->~LorieEventReader();
            free(reader);
        }
    }

    char* takePayload() {
        char* result = payload;
        payload = nullptr;
        return result;
    }

    int takeDescriptor() {
        int result = descriptor;
        descriptor = -1;
        return result;
    }

    void reset() {
        free(payload);
        payload = nullptr;
        if (descriptor >= 0)
            close(descriptor);
        descriptor = -1;
        event = {};
        headerBytes = payloadBytes = payloadSize = 0;
        headerComplete = wantsDescriptor = descriptorComplete = false;
    }

    Result next(int fd, Budget& budget) {
        while (true) {
            void* target;
            size_t remaining;
            bool receivingDescriptor = false;
            if (headerBytes < sizeof(event)) {
                target = (char*) &event + headerBytes;
                remaining = sizeof(event) - headerBytes;
            } else {
                if (!headerComplete) {
                    switch (event.type) {
                        case EVENT_SCREEN_SIZE:
                            payloadSize = event.screenSize.name_size;
                            if (payloadSize > LORIE_MAX_SCREEN_NAME_BYTES)
                                return fail(EMSGSIZE, "screen name exceeds the RandR buffer limit");
                            break;
                        case EVENT_CLIPBOARD_SEND:
                            payloadSize = event.clipboardSend.count;
                            if (payloadSize > LORIE_MAX_CLIPBOARD_BYTES)
                                return fail(EMSGSIZE, "clipboard exceeds the Android UTF-8 transfer limit");
                            break;
                        case EVENT_RENDERER_WAKEUP_COND:
                            wantsDescriptor = true;
                            break;
                        case EVENT_TOUCH:
                        case EVENT_MOUSE:
                        case EVENT_KEY:
                        case EVENT_STYLUS:
                        case EVENT_STYLUS_ENABLE:
                        case EVENT_UNICODE:
                        case EVENT_CLIPBOARD_ENABLE:
                        case EVENT_CLIPBOARD_ANNOUNCE:
                        case EVENT_GPU_COPY_DONE:
                        case EVENT_LOCK_KEYS_STATE:
                        case EVENT_SYNC:
                            break;
                        default:
                            return fail(EPROTO, "unexpected event type on the server connection");
                    }
                    if (payloadSize || event.type == EVENT_CLIPBOARD_SEND) {
                        payload = (char*) malloc(payloadSize + 1);
                        if (!payload)
                            return fail(ENOMEM, "cannot allocate event payload");
                        payload[payloadSize] = '\0';
                    }
                    headerComplete = true;
                }
                if (payloadBytes < payloadSize) {
                    target = payload + payloadBytes;
                    remaining = payloadSize - payloadBytes;
                } else if (wantsDescriptor && !descriptorComplete) {
                    target = &descriptorMarker;
                    remaining = 1;
                    receivingDescriptor = true;
                } else {
                    return Result::Frame;
                }
            }

            if (!budget.bytes || !budget.calls)
                return Result::Yield;
            if (remaining > budget.bytes)
                remaining = budget.bytes;
            struct iovec iov = { target, remaining };
            // A malformed message may fit two fds in this aligned buffer. Walk
            // all received rights and close every unclaimed descriptor, including
            // on MSG_CTRUNC. The kernel closes any rights that did not fit.
            union {
                struct cmsghdr align;
                char bytes[CMSG_SPACE(sizeof(int))];
            } control{};
            struct msghdr message{};
            message.msg_iov = &iov;
            message.msg_iovlen = 1;
            message.msg_control = control.bytes;
            message.msg_controllen = sizeof(control.bytes);
            --budget.calls;
            ssize_t count = recvmsg(fd, &message, MSG_DONTWAIT | MSG_CMSG_CLOEXEC);
            if (count < 0) {
                if (errno == EINTR)
                    continue;
                if (errno == EAGAIN || errno == EWOULDBLOCK)
                    return Result::WouldBlock;
                return fail(errno, "receiving event frame failed");
            }
            if (!count) {
                if (!headerBytes)
                    return Result::Closed;
                return fail(EPROTO, "connection ended inside an event frame");
            }
            budget.bytes -= (size_t) count;
            bool invalidControl = (message.msg_flags & (MSG_CTRUNC | MSG_TRUNC)) != 0;
            unsigned rights = 0;
            for (struct cmsghdr* cmsg = CMSG_FIRSTHDR(&message); cmsg;
                 cmsg = CMSG_NXTHDR(&message, cmsg)) {
                if (cmsg->cmsg_level != SOL_SOCKET || cmsg->cmsg_type != SCM_RIGHTS ||
                    cmsg->cmsg_len < CMSG_LEN(0)) {
                    invalidControl = true;
                    continue;
                }
                size_t size = cmsg->cmsg_len - CMSG_LEN(0);
                if (size % sizeof(int))
                    invalidControl = true;
                for (size_t offset = 0; offset + sizeof(int) <= size; offset += sizeof(int)) {
                    int received;
                    memcpy(&received, (char*) CMSG_DATA(cmsg) + offset, sizeof(received));
                    ++rights;
                    if (receivingDescriptor && rights == 1)
                        descriptor = received;
                    else
                        close(received);
                }
            }
            if (invalidControl || (receivingDescriptor ? rights != 1 : rights != 0))
                return fail(EPROTO, "missing, extra, or misplaced event descriptors");
            if (receivingDescriptor) {
                if (descriptorMarker != '!')
                    return fail(EPROTO, "invalid event descriptor marker");
                descriptorComplete = true;
            } else if (headerBytes < sizeof(event)) {
                headerBytes += (size_t) count;
            } else {
                payloadBytes += (size_t) count;
            }
        }
    }

private:
    size_t headerBytes = 0, payloadBytes = 0, payloadSize = 0;
    char* payload = nullptr;
    int descriptor = -1;
    char descriptorMarker = 0;
    bool headerComplete = false, wantsDescriptor = false, descriptorComplete = false;

    Result fail(int number, const char* message) {
        reset();
        error = number;
        errorMessage = message;
        return Result::Error;
    }
};
