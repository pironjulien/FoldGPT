/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Deterministic arithmetic/error tests. These are NOT device measurements. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <time.h>

static struct timespec samples[3];
static int sample_index, fail_index;
static int sample_clock(clockid_t clock, struct timespec *out)
{
    assert(clock == (sample_index == 1 ? CLOCK_BOOTTIME : CLOCK_REALTIME));
    if (sample_index == fail_index) {
        errno = ENOSYS;
        return -1;
    }
    assert(sample_index < 3);
    *out = samples[sample_index++];
    return 0;
}
#define clock_gettime sample_clock
#include "boot-time.h"
#undef clock_gettime

static int count;
static void check(struct timespec a, struct timespec b, struct timespec c,
                  int fail, int error, time_t expected)
{
    time_t out = -7;
    samples[0] = a; samples[1] = b; samples[2] = c;
    sample_index = 0; fail_index = fail; errno = 0;
    int rc = procps_boot_time_from_clocks(&out);
    if (error) {
        assert(rc == -1 && errno == error && out == -7);
    } else {
        assert(rc == 0 && out == expected);
    }
    ++count;
}
#define T(s,n) ((struct timespec){(s),(n)})
int main(void)
{
    check(T(1700000000,500000000),T(100,100000000),T(1700000000,500010000),-1,0,1699999900);
    check(T(1700000000,100000000),T(100,900000000),T(1700000000,100010000),-1,0,1699999899);
    /* Suspend advances realtime and boottime together: mapping is unchanged. */
    check(T(1700003600,500000000),T(3700,100000000),T(1700003600,500010000),-1,0,1699999900);
    /* A completed wall-clock adjustment moves the mapping, as kernel btime does. */
    check(T(1700000120,500000000),T(100,100000000),T(1700000120,500010000),-1,0,1700000020);
    check(T(0,900000000),T(0,500000000),T(0,900001000),-1,0,0);
    check(T(5000000000LL,500000000),T(100,100000000),T(5000000000LL,500010000),-1,0,4999999900LL);
    check(T(1700000000,100000000),T(100,900000000),T(1700000001,100000000),-1,EAGAIN,0);
    check(T(1700000000,100000000),T(100,100005000),T(1700000000,100010000),-1,EAGAIN,0);
    check(T(1700000000,100000000),T(100,100000000),T(1699999999,900000000),-1,ERANGE,0);
    check(T(99,900000000),T(100,100000000),T(100,200000000),-1,ERANGE,0);
    check(T(100,0),T(100,1),T(100,2),-1,ERANGE,0);
    check(T(1700000000,1000000000),T(100,0),T(1700000000,1000000000),-1,ERANGE,0);
    check(T(1700000000,0),T(100,-1),T(1700000000,0),-1,ERANGE,0);
    check(T(-1,0),T(0,0),T(0,0),-1,ERANGE,0);
    for (int i = 0; i < 3; ++i)
        check(T(1700000000,500000000),T(100,100000000),T(1700000000,500010000),i,ENOSYS,0);
    printf("clock arithmetic and failure cases: %d PASS\n", count);
    return 0;
}
