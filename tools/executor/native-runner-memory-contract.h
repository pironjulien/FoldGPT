/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FOLDGPT_NATIVE_RUNNER_MEMORY_CONTRACT_H
#define FOLDGPT_NATIVE_RUNNER_MEMORY_CONTRACT_H
#include <stdint.h>

/* NDK r29's statically linked Android Scudo primary64 allocator has 33 size
 * classes and RegionSizeLog=28. The exact existing ARM64 ELF's DWARF and
 * SizeClassAllocator64::init disassembly independently confirm the temporary
 * address reservation (33 * 256 MiB), not committed/resident RAM.
 * Keep the former fixture's 256 MiB as separately named address-space headroom.
 * A different allocator/runtime needs its own measured manifest; the runner
 * never adds a hidden allowance to a caller's declared RLIMIT_AS.
 */
#define NR_SCUDO_PRIMARY_RESERVATION_BYTES (UINT64_C(33) << 28)
#define NR_FIXTURE_ADDRESS_HEADROOM_BYTES (UINT64_C(1) << 28)
#define NR_ANDROID_FIXTURE_ADDRESS_SPACE_BYTES \
  (NR_SCUDO_PRIMARY_RESERVATION_BYTES + NR_FIXTURE_ADDRESS_HEADROOM_BYTES)
#ifdef __ANDROID__
#define NR_FIXTURE_ALLOCATOR_RESERVATION_BYTES NR_SCUDO_PRIMARY_RESERVATION_BYTES
#define NR_FIXTURE_ADDRESS_SPACE_BYTES NR_ANDROID_FIXTURE_ADDRESS_SPACE_BYTES
#else
#define NR_FIXTURE_ALLOCATOR_RESERVATION_BYTES UINT64_C(0)
#define NR_FIXTURE_ADDRESS_SPACE_BYTES NR_FIXTURE_ADDRESS_HEADROOM_BYTES
#endif
/* Smallest binary-sized supported ceiling containing that 8.5 GiB envelope.
 * This is only a manifest validation maximum, never an implicit/default limit. */
#define NR_MAX_ADDRESS_SPACE_BYTES (UINT64_C(1) << 34)
#endif
