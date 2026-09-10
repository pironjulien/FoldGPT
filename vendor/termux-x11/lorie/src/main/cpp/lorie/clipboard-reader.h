#pragma once

#include "event-protocol.h"
#include <cerrno>
#include <cstdlib>
#include <unistd.h>

// The activity's existing server-event dispatcher reads one clipboard body
// synchronously. Own its bounded storage and consume exactly its wire length;
// the local NUL terminator is never read from the socket.
class LorieClipboardData {
public:
    char* bytes = nullptr;

    ~LorieClipboardData() { free(bytes); }
    LorieClipboardData() = default;
    LorieClipboardData(const LorieClipboardData&) = delete;
    LorieClipboardData& operator=(const LorieClipboardData&) = delete;

    bool readFrom(int fd, size_t count) {
        free(bytes);
        bytes = nullptr;
        if (count > LORIE_MAX_CLIPBOARD_BYTES) {
            errno = EMSGSIZE;
            return false;
        }
        bytes = static_cast<char*>(malloc(count + 1));
        if (!bytes) {
            errno = ENOMEM;
            return false;
        }
        size_t offset = 0;
        while (offset < count) {
            ssize_t received = read(fd, bytes + offset, count - offset);
            if (received > 0)
                offset += static_cast<size_t>(received);
            else if (received < 0 && errno == EINTR)
                continue;
            else {
                if (received == 0)
                    errno = ECONNRESET;
                return false;
            }
        }
        bytes[count] = '\0';
        return true;
    }
};
