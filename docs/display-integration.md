# Embedded display UI

`FoldActivity` now extends the application-owned
`com.termux.x11.FoldDisplayActivity`, which inherits the embedded X11 activity.
No upstream/vendor file is replaced or patched. The Java superclass and normal
Android resource overlays make the change reproducible in a clean application
build while preserving existing vendor changes.

The intermediary uses the same Java package to override the upstream
package-private `buildNotification()` method. Its `@Override` intentionally
makes changes to that integration point fail at compile time. The existing
notification manager lifecycle, notification ID and preference-selected display
actions remain upstream-owned.

The display notification now identifies FoldGPT and uses a monochrome icon and
the dedicated `foldgpt.display.v1` channel, with low initial importance, no sound
and no bubbles. Creating a separate display channel avoids reusing the old
high-importance channel's stored defaults. Android continues to honor user
notification preferences; no channel, notification permission or error is
deleted. The foreground runtime notification is separate and unchanged.

The disconnected screen retains the actual disconnection signal and all three
controls. It shows the FoldGPT icon and labels instead of the upstream X logo.
Help explains the embedded display and how to distinguish closing its window
from stopping the runtime. It no longer sends the user to instructions to
install or launch a separate Termux server. No delayed hide, fake connected
state or error-dialog suppression is added.

Application resources name the display settings, notification controls and
optional accessibility service consistently. The advanced key configuration
description remains functional and includes a valid JSON example. All original
input, accessibility, invalid-resolution and permission checks still run.
Upstream package/class identifiers and legal provenance remain unchanged.

This UI change does not establish that the old Termux/Termux:X11 applications
can be uninstalled; that requires checking the installed runtime's actual
dependencies and retaining any private data separately. It does not install an
APK or activate the new rootfs transaction by itself.

Validation: Android resource XML, AAPT2 and the full Gradle APK build pass.
The installed notification uses the dedicated display channel, importance 2,
no sound and SILENT/ONLY_ALERT_ONCE flags. The separate legacy packages are
now uninstalled for user 0 with their data retained; FoldGPT restarted without
them. See `verification-2026-09-06.md` for the exact scope.
