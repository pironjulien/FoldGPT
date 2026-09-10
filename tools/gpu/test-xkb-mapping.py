#!/usr/bin/env python3
"""Exercise the production dynamic-key allocator with isolated X server objects.

Run with Linux Python and a host C compiler (including WSL). This validates map
ownership, notification order and held-key lifetime; a real X11 client/device
test is still required to verify text delivery and client mapping caches.
"""

import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "vendor/termux-x11/lorie/src/main/cpp/lorie/InputXKB.c"
LIST_HEADER = ROOT / "vendor/termux-x11/lorie/src/main/cpp/xserver/include"

HARNESS = r'''
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define HAVE_TYPEOF 1
#include "list.h"
#define unused __attribute__((unused))
typedef int Bool;
typedef unsigned char KeyCode;
typedef unsigned long KeySym;
#define TRUE 1
#define FALSE 0
#define NoSymbol 0
#define Success 0
#define BadAlloc 11
#define KEYBOARD_OR_FLOAT 0
#define KEY_PROCESSED 0
#define XkbOneLevelIndex 0
#define XkbAlphabeticIndex 2
#define XkbGroup1Mask 1
#define XkbKeyNamesMask 1
#define XkbKeySymsMask 2
#define XkbNKN_KeycodesMask 1
typedef struct { char name[4]; } Name;
typedef struct { Name *keys; } Names;
typedef struct {
    unsigned int changed;
    unsigned char first_key_sym, num_key_syms;
} MapChanges;
typedef struct {
    MapChanges map;
    struct { int changed, first_key, num_keys; } names;
} XkbChangesRec, *XkbChangesPtr;
typedef struct { int placeholder; } XkbEventCauseRec;
typedef struct {
    unsigned char deviceID, oldDeviceID, minKeyCode, oldMinKeyCode;
    unsigned char maxKeyCode, oldMaxKeyCode, requestMajor, requestMinor;
    unsigned short changed;
} xkbNewKeyboardNotify;
#define XkbSetCauseUnknown(cause) ((void)(cause))
typedef struct {
    KeyCode min_key_code, max_key_code;
    unsigned char groups[256], widths[256];
    KeySym syms[256][2];
    Names *names;
    Bool failAllocation;
} XkbDescRec, *XkbDescPtr;
typedef struct { XkbDescPtr desc; } XkbInfo;
typedef struct { XkbInfo *xkbInfo; } KeyClass;
typedef struct Device { KeyClass *key; Bool down[256]; int id; } Device, *DeviceIntPtr;
#define XkbKeycodeInRange(x,k) ((k)>=(x)->min_key_code && (k)<=(x)->max_key_code)
#define XkbKeyNumGroups(x,k) ((x)->groups[k])
#define XkbKeySymsPtr(x,k) ((x)->syms[k])
static DeviceIntPtr masterDevice, lorieKeyboard;
static DeviceIntPtr GetMaster(unused DeviceIntPtr d, unused int kind) { return masterDevice; }
static Bool key_is_down(DeviceIntPtr d, int key, unused int kind) { return d->down[key]; }
static int XkbChangeTypesOfKey(XkbDescPtr x, int key, int groups, unused int mask,
                               int *types, unused MapChanges *changes) {
    if (x->failAllocation) return BadAlloc;
    x->groups[key] = groups;
    x->widths[key] = types[0] == XkbOneLevelIndex ? 1 : 2;
    return Success;
}
static void XkbConvertCase(KeySym sym, KeySym *lower, KeySym *upper) {
    *lower = *upper = sym;
    if (sym >= 0xe0 && sym <= 0xfe && sym != 0xf7) *upper = sym - 32;
}
static int notifications;
static int keyboardNotifications;
static KeyCode expectedKey;
static KeySym expectedSymbol;
static Bool allowPartial;
static void XkbSendNotification(DeviceIntPtr dev, XkbChangesPtr changes,
                                unused XkbEventCauseRec *cause) {
    assert(changes->map.changed & XkbKeySymsMask);
    assert(changes->map.num_key_syms == 1);
    assert(changes->map.first_key_sym == expectedKey);
    assert(dev->key->xkbInfo->desc->syms[expectedKey][0] == expectedSymbol);
    if (!allowPartial) {
        /* No client sees a notification until both device maps are current. */
        assert(lorieKeyboard->key->xkbInfo->desc->syms[expectedKey][0] == expectedSymbol);
        assert(masterDevice->key->xkbInfo->desc->syms[expectedKey][0] == expectedSymbol);
    }
    notifications++;
}
static void XkbSendNewKeyboardNotify(DeviceIntPtr dev, xkbNewKeyboardNotify *event) {
    XkbDescPtr map = dev->key->xkbInfo->desc;
    assert(!allowPartial);
    assert(event->deviceID == dev->id && event->oldDeviceID == dev->id);
    assert(event->minKeyCode == map->min_key_code && event->oldMinKeyCode == map->min_key_code);
    assert(event->maxKeyCode == map->max_key_code && event->oldMaxKeyCode == map->max_key_code);
    assert(event->changed == XkbNKN_KeycodesMask);
    assert(event->requestMajor == 0 && event->requestMinor == 0);
    assert(lorieKeyboard->key->xkbInfo->desc->syms[expectedKey][0] == expectedSymbol);
    assert(masterDevice->key->xkbInfo->desc->syms[expectedKey][0] == expectedSymbol);
    /* The map updates must already have been published for legacy clients. */
    assert(notifications > keyboardNotifications);
    keyboardNotifications++;
}
typedef struct { KeySym keysym; KeyCode keycode; struct xorg_list entry; } AddedKeySym;
static struct xorg_list addedKeysyms = { &addedKeysyms, &addedKeysyms };
static KeySym pressedKeys[256];

/* PRODUCTION_ALLOCATOR */

/* Model XKB lookup, then exercise the unmodified production dispatch decision. */
static KeyCode lorieKeysymToKeycode(KeySym sym, unsigned state, unsigned *newState) {
    XkbDescPtr map = masterDevice->key->xkbInfo->desc;
    if (newState) *newState = state;
    for (unsigned key = map->min_key_code; key <= map->max_key_code; key++)
        if (map->groups[key] && map->syms[key][0] == sym) return key;
    return 0;
}
static struct { KeySym a, b; } altKeysym[] = {{0, 0}};
#define LogMessageVerb(...) ((void)0)
static KeyCode resolvedKey;
static void resolve(KeySym keysym) {
    size_t i;
    unsigned state = 0, new_state;
    KeyCode keycode;
    resolvedKey = 0;
    /* PRODUCTION_LOOKUP_DECISION */
    resolvedKey = keycode;
}

static XkbDescRec maps[2];
static Name names[2][256];
static Names nameTables[2];
static XkbInfo infos[2];
static KeyClass keys[2];
static Device devices[2];
static void reset(void) {
    while (!xorg_list_is_empty(&addedKeysyms)) {
        AddedKeySym *item = xorg_list_first_entry(&addedKeysyms, AddedKeySym, entry);
        xorg_list_del(&item->entry);
        free(item);
    }
    memset(maps, 0, sizeof(maps));
    memset(names, 0, sizeof(names));
    memset(devices, 0, sizeof(devices));
    memset(pressedKeys, 0, sizeof(pressedKeys));
    for (int i = 0; i < 2; i++) {
        maps[i].min_key_code = 8;
        maps[i].max_key_code = 255;
        nameTables[i].keys = names[i];
        maps[i].names = &nameTables[i];
        infos[i].desc = &maps[i];
        keys[i].xkbInfo = &infos[i];
        devices[i].key = &keys[i];
        devices[i].id = i + 3;
    }
    masterDevice = &devices[0];
    lorieKeyboard = &devices[1];
    notifications = 0;
    keyboardNotifications = 0;
    allowPartial = FALSE;
}
static KeyCode add(KeySym sym, KeyCode expected) {
    expectedKey = expected;
    expectedSymbol = sym;
    KeyCode key = lorieAddKeysym(sym, 0);
    assert(key == expected);
    return key;
}
int main(void) {
    reset();
    add(0xe9, 255); add(0x1002014, 254); add(0x101f642, 253);
    assert(notifications == 6);
    assert(keyboardNotifications == 6);
    assert(maps[0].widths[255] == 2 && maps[1].widths[255] == 2);
    assert(maps[0].widths[254] == 1 && maps[1].widths[254] == 1);
    assert(maps[1].syms[255][1] == 0xc9);
    /* A known symbol uses its current key; no layout notifications are emitted. */
    resolve(0xe9);
    assert(resolvedKey == 255 && notifications == 6 && keyboardNotifications == 6);
    expectedKey = 252; expectedSymbol = 0xeb;
    resolve(0xeb);
    assert(resolvedKey == 252 && notifications == 8 && keyboardNotifications == 8);
    resolve(0xeb);
    assert(resolvedKey == 252 && notifications == 8 && keyboardNotifications == 8);

    reset(); /* Never overwrite a source-only or master-only real mapping. */
    maps[1].groups[255] = 1; maps[1].syms[255][0] = 'a';
    maps[0].groups[254] = 1; maps[0].syms[254][0] = 'b';
    add(0xe9, 253);
    assert(maps[1].syms[255][0] == 'a' && maps[0].syms[254][0] == 'b');

    reset(); /* The float/master alias must not publish twice. */
    lorieKeyboard = masterDevice;
    add(0xe9, 255);
    assert(notifications == 1);
    assert(keyboardNotifications == 1);

    reset(); /* Exhaust the map and preserve all variants of a held key. */
    maps[0].max_key_code = maps[1].max_key_code = 10;
    add(0xe9, 10); add(0xea, 9); add(0xeb, 8);
    pressedKeys[10] = 0xe9; devices[0].down[9] = TRUE;
    add(0xec, 8);
    devices[1].down[8] = TRUE;
    assert(lorieAddKeysym(0xed, 0) == 0);
    assert(keyboardNotifications == 8);
    pressedKeys[10] = NoSymbol;
    add(0xed, 10);

    reset(); /* Another client replacing a source map invalidates ownership. */
    maps[0].max_key_code = maps[1].max_key_code = 8;
    add(0xe9, 8);
    maps[1].syms[8][0] = 'x';
    assert(lorieAddKeysym(0xea, 0) == 0);
    assert(keyboardNotifications == 2);
    assert(maps[1].syms[8][0] == 'x');

    reset(); /* Allocation failures must never produce a usable key. */
    maps[1].failAllocation = TRUE;
    assert(lorieAddKeysym(0xe9, 0) == 0 && notifications == 0);
    assert(keyboardNotifications == 0);
    resolve(0xe9);
    assert(resolvedKey == 0 && notifications == 0 && keyboardNotifications == 0);
    reset(); maps[0].failAllocation = TRUE;
    expectedKey = 255; expectedSymbol = 0xe9; allowPartial = TRUE;
    assert(lorieAddKeysym(0xe9, 0) == 0 && notifications == 1);
    assert(keyboardNotifications == 0);
    reset();
    puts("XKB allocator: master/source maps, MapNotify and NewKeyboardNotify ordering, key lifetime, ownership and allocation failures passed");
}
'''


def main():
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index("static void saveAddedKeysym(")
    end = source.index("/*\n * lorieKeysymKeyboardEvent()", start)
    harness = HARNESS.replace("/* PRODUCTION_ALLOCATOR */", source[start:end])
    event = source.index("void lorieKeysymKeyboardEvent(KeySym keysym, int down) {")
    decision_start = source.index("    keycode = lorieKeysymToKeycode", event)
    decision_end = source.index("    /*\n     * X11 generally", decision_start)
    harness = harness.replace("/* PRODUCTION_LOOKUP_DECISION */",
                              source[decision_start:decision_end])
    output = ROOT / "work/xkb-mapping-test"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=output) as build:
        c_file = Path(build) / "allocator.c"
        binary = Path(build) / "allocator"
        c_file.write_text(harness, encoding="utf-8")
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-Wall", "-Wextra",
                        "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-I", str(LIST_HEADER), str(c_file), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
