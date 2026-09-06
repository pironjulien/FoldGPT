/* SPDX-License-Identifier: GPL-3.0-or-later
 * Exercise the same cache-sync helper as libXlorie on real Android exporters.
 * This is a CPU/cache API test; Vulkan/Present probes separately test GPU work.
 */
#define _GNU_SOURCE
#include <android/sharedmem.h>
#include <fcntl.h>
#include <linux/dma-heap.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include "dmabuf_sync.h"

#define REQUIRE(test) do { if (!(test)) { fprintf(stderr, "FAIL: %s (errno=%d: %s)\n", #test, errno, strerror(errno)); return 1; } } while (0)

static int exercise(const char *name, int fd, size_t size, int expectedKind) {
    REQUIRE(fd >= 0);
    struct stat status;
    struct statfs filesystem;
    int statResult = fstat(fd, &status), statError = statResult < 0 ? errno : 0;
    int statfsResult = fstatfs(fd, &filesystem), statfsError = statfsResult < 0 ? errno : 0;
    printf("INFO: %s mode=%#o fstat_errno=%d filesystem=%#lx fstatfs_errno=%d\n", name,
           statResult == 0 ? (unsigned)status.st_mode : 0, statError,
           statfsResult == 0 ? (unsigned long)filesystem.f_type : 0, statfsError);
    int secondFd = dup(fd);
    REQUIRE(secondFd >= 0);
    unsigned char *first = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    unsigned char *second = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, secondFd, 0);
    REQUIRE(first != MAP_FAILED && second != MAP_FAILED);
    int8_t firstKind = LORIE_FD_SYNC_UNKNOWN, secondKind = LORIE_FD_SYNC_UNKNOWN;
    int exporterError = 0;
    if (expectedKind == LORIE_FD_SYNC_DMA_BUF) {
        struct dma_buf_sync invalidSync = { .flags = UINT64_MAX };
        REQUIRE(ioctl(fd, DMA_BUF_IOCTL_SYNC, &invalidSync) < 0);
        exporterError = errno;
        REQUIRE(lorieDmaBufCpuSync(fd, invalidSync.flags, &firstKind) == exporterError);
        REQUIRE(firstKind == LORIE_FD_SYNC_UNKNOWN);
    }
    for (unsigned frame = 0; frame < 16; frame++) {
        REQUIRE(lorieDmaBufCpuSync(fd, DMA_BUF_SYNC_START | DMA_BUF_SYNC_RW, &firstKind) == 0);
        for (size_t i = 0; i < size; i++)
            first[i] = (unsigned char)(i * 31 + frame);
        REQUIRE(lorieDmaBufCpuSync(fd, DMA_BUF_SYNC_END | DMA_BUF_SYNC_RW, &firstKind) == 0);
        REQUIRE(firstKind == expectedKind);
        REQUIRE(lorieDmaBufCpuSync(secondFd, DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ, &secondKind) == 0);
        for (size_t i = 0; i < size; i++)
            REQUIRE(second[i] == (unsigned char)(i * 31 + frame));
        REQUIRE(lorieDmaBufCpuSync(secondFd, DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ, &secondKind) == 0);
        REQUIRE(secondKind == expectedKind);
    }
    if (expectedKind == LORIE_FD_SYNC_DMA_BUF) {
        REQUIRE(lorieDmaBufCpuSync(fd, UINT64_MAX, &firstKind) == exporterError);
        REQUIRE(firstKind == LORIE_FD_SYNC_DMA_BUF);
        printf("PASS: %s exporter errno=%d preserved before and after identification\n", name, exporterError);
    }
    munmap(second, size);
    munmap(first, size);
    close(secondFd);
    close(fd);
    printf("PASS: %s identified as %s, 16 CPU sync/write/read cycles verified\n", name,
           expectedKind == LORIE_FD_SYNC_DMA_BUF ? "DMA-BUF" : "ordinary shared memory");
    return 0;
}

int main(void) {
    char context[256] = {0};
    int contextFd = open("/proc/self/attr/current", O_RDONLY | O_CLOEXEC);
    ssize_t contextLength = contextFd >= 0 ? read(contextFd, context, sizeof(context) - 1) : -1;
    if (contextFd >= 0)
        close(contextFd);
    if (contextLength > 0)
        context[strcspn(context, "\n")] = '\0';
    printf("INFO: uid=%u gid=%u selinux=%s\n", (unsigned)getuid(), (unsigned)getgid(),
           contextLength > 0 ? context : "unavailable");
    const size_t size = (size_t)sysconf(_SC_PAGESIZE);
    int8_t invalidKind = LORIE_FD_SYNC_UNKNOWN;
    REQUIRE(lorieDmaBufCpuSync(-1, DMA_BUF_SYNC_START | DMA_BUF_SYNC_RW, &invalidKind) == EBADF);
    REQUIRE(invalidKind == LORIE_FD_SYNC_UNKNOWN);
    puts("PASS: invalid descriptor error preserved");

    // A device returning ENOTTY must not be mistaken for ordinary memory.
    int unsuitable = open("/dev/null", O_RDWR | O_CLOEXEC);
    REQUIRE(unsuitable >= 0);
    int8_t unsuitableKind = LORIE_FD_SYNC_UNKNOWN;
    REQUIRE(lorieDmaBufCpuSync(unsuitable, DMA_BUF_SYNC_START | DMA_BUF_SYNC_RW, &unsuitableKind) != 0);
    REQUIRE(unsuitableKind == LORIE_FD_SYNC_UNKNOWN);
    close(unsuitable);
    puts("PASS: unsupported descriptor error preserved");

    int fd = ASharedMemory_create("FoldGPT sync probe", size);
    REQUIRE(exercise("ASharedMemory", fd, size, LORIE_FD_SYNC_SHARED_MEMORY) == 0);
    fd = memfd_create("FoldGPT sync probe", MFD_CLOEXEC);
    REQUIRE(fd >= 0 && ftruncate(fd, (off_t)size) == 0);
    REQUIRE(exercise("memfd", fd, size, LORIE_FD_SYNC_SHARED_MEMORY) == 0);

    int heap = open("/dev/dma_heap/system", O_RDONLY | O_CLOEXEC);
    REQUIRE(heap >= 0);
    struct dma_heap_allocation_data allocation = { .len = size, .fd_flags = O_RDWR | O_CLOEXEC };
    REQUIRE(ioctl(heap, DMA_HEAP_IOCTL_ALLOC, &allocation) == 0);
    close(heap);
    REQUIRE(exercise("system DMA heap", (int)allocation.fd, size, LORIE_FD_SYNC_DMA_BUF) == 0);
    return 0;
}
