/* SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once

#include <errno.h>
#include <linux/dma-buf.h>
#include <stdint.h>
#include <sys/ioctl.h>

enum {
    LORIE_FD_SYNC_UNKNOWN,
    LORIE_FD_SYNC_SHARED_MEMORY,
    LORIE_FD_SYNC_DMA_BUF,
};

/* Bracket CPU mmap accesses, in addition to the existing producer/consumer
 * fences. Plain ashmem/memfd objects do not implement DMA-BUF ioctls. Cache
 * that distinction only on ENOTTY; never swallow a DMA-BUF exporter failure.
 * The state belongs to one owned descriptor and must be reset if it changes.
 * Returns zero or a positive errno, like LorieBuffer_lock/unlock.
 */
static inline int lorieDmaBufCpuSync(int fd, uint64_t flags, int8_t *kind) {
    if (*kind == LORIE_FD_SYNC_SHARED_MEMORY)
        return 0;

    struct dma_buf_sync sync = { .flags = flags };
    int result;
    do {
        result = ioctl(fd, DMA_BUF_IOCTL_SYNC, &sync);
    } while (result < 0 && (errno == EINTR || errno == EAGAIN));

    if (result == 0) {
        *kind = LORIE_FD_SYNC_DMA_BUF;
        return 0;
    }

    int error = errno;
    if (error == ENOTTY && *kind == LORIE_FD_SYNC_UNKNOWN) {
        *kind = LORIE_FD_SYNC_SHARED_MEMORY;
        return 0;
    }
    return error;
}
