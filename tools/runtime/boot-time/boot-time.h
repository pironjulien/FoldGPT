/* SPDX-License-Identifier: GPL-2.0-or-later */
/* FoldGPT addition to procps-ng ps; does not emulate procfs. */
#ifndef PROCPS_PS_BOOT_TIME_H
#define PROCPS_PS_BOOT_TIME_H

#include <errno.h>
#include <time.h>

/* /proc/PID/stat starttime and CLOCK_BOOTTIME both include suspend time.
 * Bracket that clock with realtime reads. Only accept an unambiguous whole
 * epoch second, which is the precision exposed by /proc/stat btime and ps.
 * A wall-clock step or a long deschedule can make this sample ambiguous;
 * return an error rather than inventing a timestamp or hiding the failure.
 * This is the current wall-clock mapping, not a historical clock-change log.
 */
static int procps_boot_time_from_clocks(time_t *result)
{
    struct timespec before, uptime, after;
    time_t lower, upper;

    if (clock_gettime(CLOCK_REALTIME, &before) < 0
        || clock_gettime(CLOCK_BOOTTIME, &uptime) < 0
        || clock_gettime(CLOCK_REALTIME, &after) < 0)
        return -1;
    if (before.tv_sec < 0 || uptime.tv_sec < 0 || after.tv_sec < 0
        || before.tv_nsec < 0 || before.tv_nsec >= 1000000000L
        || uptime.tv_nsec < 0 || uptime.tv_nsec >= 1000000000L
        || after.tv_nsec < 0 || after.tv_nsec >= 1000000000L) {
        errno = ERANGE;
        return -1;
    }
    if (before.tv_sec < uptime.tv_sec
        || (before.tv_sec == uptime.tv_sec && before.tv_nsec < uptime.tv_nsec)
        || after.tv_sec < before.tv_sec
        || (after.tv_sec == before.tv_sec && after.tv_nsec < before.tv_nsec)) {
        errno = ERANGE;
        return -1;
    }
    lower = before.tv_sec - uptime.tv_sec;
    upper = after.tv_sec - uptime.tv_sec;
    if (before.tv_nsec < uptime.tv_nsec)
        --lower;
    if (after.tv_nsec < uptime.tv_nsec)
        --upper;
    if (lower != upper) {
        errno = EAGAIN;
        return -1;
    }
    *result = lower;
    return 0;
}
#endif
