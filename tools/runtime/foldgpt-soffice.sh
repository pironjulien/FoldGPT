#!/bin/sh
# LibreOffice's actual renderer plus its documented normal-restart protocol.
# oosplash's stat(/proc/version) precheck is incompatible with Android's proc
# permissions. The renderer works with its ordinary app-owned /proc entries.
# EXITHELPER_NORMAL_RESTART=81 comes from LibreOffice desktop/exithelper.h.
# Propagate crashes and signals; never turn them into a successful conversion.
set -u
export SAL_ENABLE_FILE_LOCKING=1
while :; do
    /usr/lib/libreoffice/program/soffice.bin "$@"
    result=$?
    if [ "$result" -ne 81 ]; then
        exit "$result"
    fi
done
