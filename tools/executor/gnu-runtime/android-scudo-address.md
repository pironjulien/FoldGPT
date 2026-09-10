# Android GNU address-space derivation

## Direct failure evidence

The actual Fold GNU project stopped with Scudo's request for `8650752KB`, exactly
`33 * 2^28 = 8,858,370,048` bytes. The earlier `34 * 2^28` fixture budget included
that allocator reservation and 256MiB headroom, and was verified for a static
fixture. A dynamic PRoot process also loads the Android framework dependency
closure, Bionic's CFI shadow and randomized library guard gaps.

The separate same-UID `trace-android-address.py` diagnostic executes only the
installed strict PRoot `--version`, with explicit address/descriptor ceilings.
It observes native `mmap` arguments/results and procfs maps/status. It does not
run a GNU guest command or alter executor confinement.

`downloads/gnu-runtime/scudo-address-trace-initial.json` records:

- UID10412, one thread, 10,717 native syscalls observed;
- 3,336,417,280 bytes already mapped before Scudo initialization;
- a preceding `mmap(2147483647, PROT_NONE, MAP_NORESERVE)` for CFI shadow;
- Scudo `mmap(8858370048, PROT_NONE, MAP_NORESERVE)` returning `-ENOMEM`;
- declared RLIMIT_AS9,126,805,504 bytes, native process exit `-SIGABRT`.

The existing limit therefore could not contain the actual allocator plus native
loader mappings. This is virtual address space, including PROT_NONE mappings;
it is not a request for8GiB of resident RAM.

## Primary source mechanism

The actual device reports Android17, SDK37, OneUI90000. The inspected AOSP
Bionic source documents the mechanism and constants; the native syscall/maps
observations above verify those effects on this specific build.

- [Scudo primary64 documentation and reserve](https://github.com/llvm/llvm-project/blob/main/compiler-rt/lib/scudo/standalone/primary64.h#L33)
  states `NumClasses * 2^RegionSizeLog`. The existing exact NDK ELF/DWARF
  verification in `native-runner-scudo-check.py` derives33 classes and log28;
  the dynamic process's observed mmap request independently matches exactly.
- [Bionic CFI shadow geometry](https://github.com/aosp-mirror/platform_bionic/blob/main/libc/private/CFIShadow.h#L25)
  uses library alignment18 bits, LP64 maximum target0xffffffffffff and
  shadow size `maxTarget >> 17`, rounded to2GiB by the kernel page size.
- [CFI MapShadow](https://github.com/aosp-mirror/platform_bionic/blob/main/linker/linker_cfi.cpp#L155)
  calls PROT_NONE/MAP_NORESERVE mmap when the first CFI library is loaded.
- [Bionic ReserveWithAlignmentPadding](https://github.com/aosp-mirror/platform_bionic/blob/main/linker/linker_phdr.cpp#L571)
  retains randomized gaps of2MiB times1..31 when a library spans a2MiB
  boundary. Those gaps preserve address randomization; they must be budgeted.

Inspected file blob hashes: `primary64.h`d5dde33d672dc6a15bf068749d4501006320a659,
`CFIShadow.h`b40c063106acc00d5e65da3b9a2256b73d25238d,
`linker_cfi.cpp`92ec53e67a92a40c9430e35b20434e87c53e9371,
`linker_phdr.cpp`5967e2d48a29cbbaca8f87a2be42361ab43decd5.

## Declared budget

`gnu_runtime_address.py` computes the native ELF load spans from the complete
actual dependency closure. It supports the observed ARM64/4KiB geometry and
refuses unknown alignment/page layouts, missing dependencies, changed files or
an insufficient inherited/supported address ceiling.

For libraries no larger than the256KiB library alignment, first/last addresses
occupy a single256KiB aligned interval and cannot straddle a2MiB gap boundary.
The remaining libraries conservatively get the maximum31*2MiB retained gap.
An explicit2MiB ELF alignment is also treated as eligible. The computation does
not depend on a random sample's actual gaps.

| Component | Derived bytes on the Fold |
| --- | ---: |
| Observed Scudo33*256MiB reserve | 8,858,370,048 |
| Documented CFI shadow, page rounded | 2,147,483,648 |
|294 actual native ELF load spans |112,029,696 |
|72 gap-eligible libraries *31*2MiB maximum |4,680,843,264 |
| Transient reservation alignment envelope,2*2MiB |4,194,304 |
| Existing workload address headroom,256MiB |268,435,456 |
| **Explicit total** | **16,071,356,416** |

The transient envelope bounds `align_up(size+gap,2MiB)+2MiB-page` beyond the
final span+gap while a library is being reserved. It is a capacity allowance,
not a claim that those transient bytes remain mapped. The total stays below
the existing16GiB manifest ceiling. Neither the294-file count,72 eligible
libraries nor the final total is embedded in the implementation.

The helper returns a proposed explicit `addressSpaceBytes` for the trusted
runtime profile; it never silently raises a limit supplied to the native
runner. The report must retain the computed components. Scudo, CFI, ASLR,
filesystem/network policies and the static fixture contract remain unchanged.

## Observed success and limits

`scudo-derived-admission.json` records the actual helper result under UID10412.
At the calculated ceiling, `scudo-address-trace-derived.json` records a real
PRoot version exit0, successful Scudo mmap and14,766 syscall observations.
Immediately after reservation, VmSize was12,062,572KiB and RSS22,840KiB.
`scudo-address-derived.txt` independently records the same native version probe
without ptrace: exit0, expected version bytes and empty stderr.

These observations prove the diagnosed native loader/allocator startup at the
derived ceiling. They do not prove managed GNU project execution, Android
seccomp compatibility or normal phone routing. Those need the full Android
suite after the explicit budget is integrated. Runtime/toolchain/platform
geometry changes require a new manifest and verification; a capacity failure
must remain visible rather than disabling security features.
