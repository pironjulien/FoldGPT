# Fold lifecycle and automatic return

Status: **automatic reopening on unfold is not implemented with the current
application privileges**. The runtime and display remain separate. This note
records the current boundary and the next verifiable integration; it is not a
claim that a background launch has passed.

## Current behavior

`FoldActivity` observes the containing display through the public WindowManager
extension. An inner folding feature permits the Linux surface. On the cover,
the surface is hidden, the official Android client is opened from the visible
Activity, and that display Activity finishes. Its posture listener consequently
closes. `FoldRuntimeService`, in its separate foreground-service process,
continues independently with a partial CPU wake lock until its explicit stop
or runtime termination. The partial wake lock does not turn the screen on.

The service notification's existing tap action opens FoldGPT. Unfolding alone
does not execute that PendingIntent or restore the finished Activity. A
successful fold/return with the same runtime PID does not by itself validate
an active model task or Remote; those are separate checks.

## Changes prepared in this increment

- Require an interactive screen, an unlocked device, a dismissed keyguard,
  and the resumed/focused display Activity before starting Linux or handing
  off to the official Android app.
- Reconsider an already received posture event when window focus returns,
  avoiding a handoff based on a transient screen-off or lock-screen state.
- Keep the existing independent runtime service and its stop behavior.

No wake-screen flag, keyguard dismissal request, overlay, accessibility grant,
background launch permission, new receiver, or hidden API was added. This source
increment has not been installed on the Fold; physical lifecycle testing remains
necessary after the parent's coordinated APK build.

The changed Activity passed a standalone `javac` check against the installed
API 37 SDK, the existing compiled application/library classes, and cached
AndroidX dependencies. Outputs were isolated under ignored
`logs/lifecycle-javac-check`; no Gradle build or APK output was produced. This
checks Java type/API compatibility, not Android lifecycle behavior on hardware.

## Why a persistent listener alone cannot reopen the Activity

Android treats a foreground-service owner as background for Activity launching
unless a documented exception applies. `startActivity`, an explicit self
PendingIntent, or moving the posture listener into the service does not confer
that missing authority. PendingIntent opt-in flags delegate authority already
held by the parties; they are not a privilege grant.

A recently visible Activity can have limited launch allowances, but a short
fold/unfold test during that window is not proof of reliable reopening minutes
later. A task left in Recents also does not promise navigation away from the
current foreground task. The implementation must work outside transient grace
periods and while respecting the keyguard.

The official Android APK was inspected read-only. Its exported MainActivity
uses `singleTop` and permits embedding. These properties do not grant FoldGPT
background launch authority. Putting a foreign Activity over FoldGPT in one
task would additionally require reviewing current cross-UID activity-switch
rules and the official client's cooperation; changing task flags alone is not
a validated fix. No official client file was modified.

Public Android references:

- [Restrictions on starting activities from the background](https://developer.android.com/guide/components/activities/background-starts)
- [Activity security and background launches](https://developer.android.com/guide/components/activities/secure-bal)
- [Android 15 behavior changes for background activities](https://developer.android.com/about/versions/15/behavior-changes-15#background-activity-starts)
- [Activity.setAllowCrossUidActivitySwitchFromBelow](https://developer.android.com/reference/android/app/Activity#setAllowCrossUidActivitySwitchFromBelow(boolean))

The installed API 37 SDK exposes `MODE_BACKGROUND_ACTIVITY_START_ALLOW_IF_VISIBLE`,
`MODE_BACKGROUND_ACTIVITY_START_ALLOW_ALWAYS`, and
`setAllowCrossUidActivitySwitchFromBelow`. Their availability in the SDK does
not mean the application is authorized to use them to take focus.

## Device evidence read during this increment

The active ADB endpoint was Wi-Fi; its serial was independently matched to the
existing development Fold. Read-only package/settings inspection reported:

| Item | Observed value |
| --- | --- |
| Android SDK / release | 37 / 17 |
| FoldGPT target SDK | 37 |
| FoldGPT requested permissions | Notifications, foreground service/special use, internet, wake lock, inherited WRITE_SECURE_SETTINGS, and its internal receiver permission |
| Background-launch / overlay permissions in that list | Neither requested |
| `SYSTEM_ALERT_WINDOW` app-op | `default` |
| Enabled accessibility services | `null` |
| Samsung Modes and Routines package | `com.samsung.android.app.routines` present |
| Official ChatGPT MainActivity manifest | Exported, launchMode 1 (`singleTop`), allowEmbedded true |

No service was started, Activity launched, setting changed or model request sent
to obtain this evidence. The public browser surface was unavailable to this
subtask, so the links above identify the Android contract rather than claiming
a fresh browser retrieval. Current implementation and device rights were read
directly.

## Viable system-owned integration to validate

Samsung Modes and Routines can own the launch when configured with the actual
folding-state trigger and its application-launch action. That is a distinct
OS automation with its own legitimate authority, rather than a fabricated
broadcast from FoldGPT. The package is installed; its exact available trigger,
conditions and launch behavior on this firmware still require UI verification.
No private routine database or undocumented command endpoint was modified.

A product integration must restrict the routine to resuming an existing Linux
session that the user left on folding; unfolding during an unrelated activity
must not unexpectedly cold-start a workspace. It must also ignore unfolding
while locked or screen-off. The current app-launch target does not implement
that resume-only contract, so simply creating a global "open FoldGPT on every
unfold" routine would not complete the requested behavior correctly.

## Required verification after an authorized implementation

1. Start FoldGPT on the inner screen, record the actual runtime PID, and start
   a bounded local task independently of a model request.
2. Fold and leave the official Android app in front. Wait beyond temporary
   foreground-launch allowances, unfold, and confirm the Linux display returns
   with the same task/runtime and no extra interaction.
3. Repeat while locked and screen-off: no screen wake, keyguard dismissal, or
   foreground launch may occur. Unlocking is a separate user action.
4. Stop Linux explicitly, then fold/unfold: no automatic cold start. Also test
   another foreground app, split-screen, rotation, and a destroyed display
   Activity.
5. Separately validate active Codex work and Remote across folding; runtime
   survival alone is insufficient proof of either.

Until these pass, keep automatic reopening listed as unfinished.
