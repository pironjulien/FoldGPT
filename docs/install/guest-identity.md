# Guest account contract

The Android runtime reads `/etc/foldgpt-user` inside its Linux root: one explicit
account name followed by LF. `GuestIdentity` verifies a unique nonroot UID, a
matching primary group, `/home/<name>`, `/bin/bash`, and real home directories
before loading the keyring or starting X11. It never creates a missing home.

PRoot's identity, working directory, HOME, USER and LOGNAME use this account.
Android still owns actual files with the app UID. This is installation
consistency checking, not isolation against processes sharing that Android UID.

Fresh provisioning must create the account and home before committing this
selection and validating the inactive root. That coordinator and durable
user-data bindings remain unfinished.

For an existing developer installation, run
`python tools/configure-guest-identity.py --serial DEVICE --user EXISTING_ACCOUNT`
before installing the updated APK. The tool preserves an existing selection;
it does not create accounts or migrate data. APK updates retain the selection.

On 2026-09-06, twenty JVM/POSIX tests passed, including ambiguous and privileged
account refusal and linked selection/home refusal. Debug APK SHA-256
`b772036b572c7798cd5e487b1aef5ff6ab940c6c50ce3aa2d33bd85e836fce67`
was installed over the existing development installation. The client restarted;
CDP reported Adreno 840 through ANGLE/Zink/Turnip with composition and
rasterization enabled. Debug/release contents checks and release vital lint
passed. This is not a fresh-install or complete sandbox qualification.
