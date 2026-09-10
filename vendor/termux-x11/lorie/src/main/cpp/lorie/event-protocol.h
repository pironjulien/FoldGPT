#pragma once

#include <stddef.h>
#include <stdint.h>

// Display names end up in the server's 1024-byte, NUL-terminated RandR buffer.
#define LORIE_MAX_SCREEN_NAME_BYTES 1023u
// Supported clipboard transport capacity. Android's shared 1 MiB Binder
// transaction buffer motivates the bound; UTF-16 can expand to three UTF-8
// bytes per code unit. Actual Android clipboard acceptance also depends on
// parcel overhead and other transactions and is not guaranteed by this cap.
#define LORIE_MAX_CLIPBOARD_BYTES (3u * (1024u * 1024u / 2u))

typedef enum {
    EVENT_UNKNOWN = 0,
    EVENT_SHARED_SERVER_STATE,
    EVENT_ADD_BUFFER,
    EVENT_REMOVE_BUFFER,
    EVENT_SCREEN_SIZE,
    EVENT_TOUCH,
    EVENT_MOUSE,
    EVENT_KEY,
    EVENT_STYLUS,
    EVENT_STYLUS_ENABLE,
    EVENT_UNICODE,
    EVENT_CLIPBOARD_ENABLE,
    EVENT_CLIPBOARD_ANNOUNCE,
    EVENT_CLIPBOARD_REQUEST,
    EVENT_CLIPBOARD_SEND,
    EVENT_WINDOW_FOCUS_CHANGED,
    EVENT_RENDERER_WAKEUP_COND,
    EVENT_GPU_COPY_DONE,
    EVENT_LOCK_KEYS_STATE,
    EVENT_SYNC,
    EVENT_SYNC_REPLY,
} eventType;

typedef union {
    uint8_t type;
    struct {
        uint8_t t;
        uint16_t width, height, framerate;
        size_t name_size;
        char *name;
    } screenSize;
    struct {
        uint8_t t;
        unsigned long id;
    } removeBuffer;
    struct {
        uint8_t t;
        uint16_t type, id, x, y;
    } touch;
    struct {
        uint8_t t;
        float x, y;
        uint8_t detail, down, relative;
    } mouse;
    struct {
        uint8_t t;
        uint16_t key;
        uint8_t state;
    } key;
    struct {
        uint8_t t;
        float x, y;
        uint16_t pressure;
        int8_t tilt_x, tilt_y;
        int16_t orientation;
        uint8_t buttons, eraser, mouse;
    } stylus;
    struct {
        uint8_t t, enable;
    } stylusEnable;
    struct {
        uint8_t t;
        uint32_t code;
    } unicode;
    struct {
        uint8_t t;
        uint8_t enable;
    } clipboardEnable;
    struct {
        uint8_t t;
        uint32_t count;
    } clipboardSend;
    struct {
        uint8_t t;
        uint8_t state; // bit0 = Caps Lock, bit1 = Num Lock, bit2 = Scroll Lock
    } lockKeysState;
    struct {
        uint8_t t;
        uint32_t serial;
    } sync;
} lorieEvent;

