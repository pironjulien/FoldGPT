# Validation snapshot — 2026-09-06

Candidate patch:
`352f2150398f57c870306f8407b8325e0405fa3934992ae7edc9d1c3d097df64`.

Final evidence directory:
`downloads/runtime-boot-time/foldgpt-procps-boot-xYbwmecK`.

Report SHA-256:
`b34492c648f0dfa7a65375c91b94d282b9b1ac8591ce5c7e66eef4bdd087d083`.

- GNU ps original/patched builds and test processes ran as UID 65534 on
  WSL2 Linux 6.18.33.2, x86_64.
- Six actual process-sampling checks passed, including reproduction of the
  original error under kernel Landlock `EACCES` and corrected dates matching
  unrestricted kernel `btime` for the same parent and child.
- Seventeen deterministic time arithmetic/error checks passed with ASan and
  UBSan. These include suspend arithmetic and clock-error injection; they are
  explicitly not measurements of an actual suspend or time adjustment.
- A separate native Windows read rehashed 44 exported artifacts/test sources;
  all matched the report, and each recorded source matched the repository
  source at validation time.
- Android was inspected read-only for the underlying permission/clock
  availability. The patch was not cross-built, installed, or tested there.

Prior attempts were not successful validation: `JzPrz0fR` stopped because the
local build lacked Autoconf; `tYhkF4fi` built successfully but its initial
Landlock fixture omitted proc-directory enumeration, so ps failed before the
target boot-time code. The fixture was corrected to allow `READ_DIR` on the
real `/proc` while continuing to prove `READ_FILE` refusal on `/proc/stat`.
`hEhWfyKm` then passed; `xYbwmecK` additionally froze and independently exported
the exact test sources. The production candidate patch has the SHA above.

No global Git operation, official client modification, APK change or runtime
activation was performed by this subtask. The phone sampler error remains
open until ARM64 integration and new device evidence qualify it.
