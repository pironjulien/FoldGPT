/* SPDX-License-Identifier: GPL-3.0-only
 * Independently compile against host and NDK UAPI, and emit host observations.
 * These are ABI constants, not tunable resource/security policy values.
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <linux/memfd.h>
#include <stdio.h>
#include <sys/mman.h>
_Static_assert(MFD_CLOEXEC==0x0001U,"MFD_CLOEXEC ABI");
_Static_assert(MFD_ALLOW_SEALING==0x0002U,"MFD_ALLOW_SEALING ABI");
_Static_assert(F_ADD_SEALS==1024+9,"F_ADD_SEALS ABI");
_Static_assert(F_GET_SEALS==1024+10,"F_GET_SEALS ABI");
_Static_assert(F_SEAL_SEAL==0x0001,"F_SEAL_SEAL ABI");
_Static_assert(F_SEAL_SHRINK==0x0002,"F_SEAL_SHRINK ABI");
_Static_assert(F_SEAL_GROW==0x0004,"F_SEAL_GROW ABI");
_Static_assert(F_SEAL_WRITE==0x0008,"F_SEAL_WRITE ABI");
int main(void) {
    int (*create)(const char *,unsigned)=memfd_create;
    (void)create;
    printf("{\"MFD_CLOEXEC\":%u,\"MFD_ALLOW_SEALING\":%u,\"F_ADD_SEALS\":%d,\"F_GET_SEALS\":%d,\"F_SEAL_SEAL\":%d,\"F_SEAL_SHRINK\":%d,\"F_SEAL_GROW\":%d,\"F_SEAL_WRITE\":%d}\n",
        MFD_CLOEXEC,MFD_ALLOW_SEALING,F_ADD_SEALS,F_GET_SEALS,F_SEAL_SEAL,F_SEAL_SHRINK,F_SEAL_GROW,F_SEAL_WRITE);
    return 0;
}
