# PC test environment and Samsung fidelity

7 September 2026. Research and host preparation only. No virtual device was
created or started and no phone command was executed for this preparation.

## What is established locally

The PC has an Intel i7-14700K, 33,558,859,776 bytes of physical memory and Android
Emulator 37.1.11. `emulator -accel-check` reports WHPX installed and usable. This
is the relevant acceleration check; the separate CIM virtualization flag is
false despite the running Windows hypervisor and must not override this result.

The SDK catalog provides Android 17 images for x86_64 and ARM64, including
`system-images;android-37.0;google_apis;x86_64`. The latter image, revision 6, and
side-by-side command-line tools 23.0 were installed on the PC. Older tools remain
present. Package installation is recorded in
`downloads/runtime/android-lab-sdk-install.log`. No existing AVD was changed.
The catalog also has generic foldable profiles; these do not establish Samsung
firmware, kernel or hardware emulation.

After the user's clarification that Samsung kernel fidelity is required, no
generic foldable AVD was created as a purported Fold replacement. The image is
only a possible base for ordinary Android API/lifecycle regression work.

## Fidelity required for the present failure

| Layer | Required comparison | What a generic Android image cannot prove |
| --- | --- | --- |
| Application behavior | Target API 37, inherited Zygote filter, installed native executable paths, app UID/SELinux domain | Samsung-specific SELinux additions and One UI process management |
| Native architecture | AArch64 ABI and ptrace/seccomp argument handling | An x86_64 run or native-bridge translation is not an ARM64 kernel test |
| Kernel isolation | USER_NS and PID_NS absent; Landlock ABI 6; relevant seccomp behavior | A virtual device with namespaces enabled may accept operations the Fold must refuse |
| Vendor kernel | Exact Samsung source/backports and configuration | Matching Linux version numbers does not reproduce vendor patches or the unexplained reboots |
| Hardware | Snapdragon platform, KGSL/Adreno, firmware and device security | A generic virtual GPU and board cannot qualify hardware-specific behavior |
| UI | Fold/unfold, dimensions, IME transitions, density | A visual Samsung skin is not One UI or a Samsung kernel |

An independently compiled test kernel on the PC can deliberately omit the same
namespace options. This is a proposed way to exercise the missing-feature case,
not a completed reproduction of the Fold. Reproducing ABI 6 and ARM64 behavior
also requires the corresponding source/build/architecture; hiding a capability
only from a probe would be an invalid test. A custom test kernel belongs only
in the disposable PC laboratory, never on the user's phone.

## One UI and source limitations

There is no Samsung One UI AVD image among the locally queried Android SDK
packages. This is not an exhaustive proof that no third-party port exists.
Installing a vendor firmware system partition into a generic virtual board does
not recreate its boot chain, vendor drivers, HALs or kernel behavior.

Samsung's exact OSRC source portal was opened earlier in the integrated browser
and returned its maintenance page. Exact source and backport availability remain
unresolved. A later request to open the Samsung developer emulator-skin page was
queued by Codex; its page contents were not retrieved and are not used as newly
verified evidence in this report. The known distinction between visual emulator
skins and remote physical-device testing must be checked against Samsung's
current offerings before selecting a service or claiming a model is available.

No Samsung account, remote phone reservation, upload of project code, root
operation, One UI firmware download or phone modification was performed.
