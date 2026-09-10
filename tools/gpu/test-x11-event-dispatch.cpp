#include "event-reader.h"
#include <algorithm>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string>
#include <vector>

template<class A, class B> static auto max(A a, B b) { return a > b ? a : b; }
template<class A, class B> static auto min(A a, B b) { return a < b ? a : b; }
#define TRUE 1
#define FALSE 0
#define X_NOTIFY_READ 1
#define X_NOTIFY_ERROR 4
#define ANDROID_LOG_DEBUG 0
#define POINTER_ABSOLUTE 1
#define POINTER_DESKTOP 2
#define POINTER_NORAW 4
#define POINTER_RELATIVE 8
#define POINTER_ACCELERATE 16
#define POINTER_SCREEN 32
#define MotionNotify 6
#define ButtonPress 4
#define ButtonRelease 5
#define KeyPress 2
#define KeyRelease 3
#define log(...) ((void) 0)
static void __android_log_print(int, const char*, const char*, ...) {}
struct ValuatorMask {};
static void valuator_mask_zero(ValuatorMask*) {}
static void valuator_mask_set_double(ValuatorMask*, int, double) {}
using DeviceIntPtr = void*;
static DeviceIntPtr lorieMouse = (void*) 1, loriePen = (void*) 2,
                    lorieEraser = (void*) 3, lorieKeyboard = (void*) 4;
static struct { float width = 100, height = 100; } screen;
static auto* pScreenPtr = &screen;
struct LorieBuffer { int placeholder; };
static int registeredBuffers;
static LorieBuffer* LorieBufferList_first(int*) { return nullptr; }
static void LorieBuffer_removeFromList(LorieBuffer*) {}
static int conn_fd = -1;
static unsigned removed = 0;
static void RemoveNotifyFd(int fd) { assert(fd >= 0); ++removed; }
static std::vector<std::string> observed, queuedInput;
static void mieqProcessInputEvents() {
    observed.insert(observed.end(), queuedInput.begin(), queuedInput.end());
    queuedInput.clear();
}
static void lorieEnableClipboardSync(int enabled) { observed.push_back(enabled ? "clipboard-on" : "clipboard-off"); }
static void lorieConfigureNotify(int, int, int, size_t, char* name) { observed.push_back(std::string("screen:") + (name ? name : "")); }
static void handleTouchEvent(lorieEvent*) { queuedInput.push_back("touch"); }
static void lorieSetCursorVisible(int) {}
static void QueuePointerEvents(DeviceIntPtr, int, int, int, ValuatorMask*) { queuedInput.push_back("pointer"); }
static void QueueKeyboardEvents(DeviceIntPtr, int type, int key) { queuedInput.push_back(std::string(type == KeyPress ? "key-down:" : "key-up:") + std::to_string(key)); }
static void lorieSetStylusEnabled(int) { observed.push_back("stylus-enable"); }
static int ucs2keysym(long value) { return (int) value; }
static void lorieKeysymKeyboardEvent(int code, int down) {
    mieqProcessInputEvents();
    queuedInput.push_back(std::string(down ? "unicode-down:" : "unicode-up:") + std::to_string(code));
}
static void lorieHandleClipboardAnnounce() { observed.push_back("clipboard-announce"); }
static void lorieHandleClipboardData(const char* data) { observed.push_back(std::string("clipboard:") + data); free((void*) data); }
static void lorieSetRendererWakeupCond(int fd) { close(fd); observed.push_back("renderer"); }
static void lorieRecheckGpuCopies() { observed.push_back("gpu"); }
static void lorieSendSyncReply(uint32_t serial) { observed.push_back("sync:" + std::to_string(serial)); }
static void lorieSyncLockKeysState(uint8_t state) { observed.push_back("locks:" + std::to_string(state)); }
#include "dispatcher-under-test.inc"

static void sendEvent(int fd, lorieEvent event, const char* body = nullptr) {
    assert(write(fd, &event, sizeof(event)) == (ssize_t) sizeof(event));
    if (body) assert(write(fd, body, strlen(body)) == (ssize_t) strlen(body));
}

int main() {
    int sockets[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0);
    conn_fd = sockets[0];
    connectionReader = LorieEventReader::create();
    assert(connectionReader);
    auto* reader = connectionReader;
    lorieEvent event{};
    event.key.t = EVENT_KEY; event.key.key = 38; event.key.state = 1;
    sendEvent(sockets[1], event);
    event = {}; event.screenSize.t = EVENT_SCREEN_SIZE; event.screenSize.name_size = 4;
    sendEvent(sockets[1], event, "Fold");
    event = {}; event.lockKeysState.t = EVENT_LOCK_KEYS_STATE; event.lockKeysState.state = 1;
    sendEvent(sockets[1], event);
    event = {}; event.unicode.t = EVENT_UNICODE; event.unicode.code = 233;
    sendEvent(sockets[1], event);
    event = {}; event.type = EVENT_TOUCH;
    sendEvent(sockets[1], event);
    event = {}; event.clipboardSend.t = EVENT_CLIPBOARD_SEND; event.clipboardSend.count = 3;
    sendEvent(sockets[1], event, "all");
    event = {}; event.sync.t = EVENT_SYNC; event.sync.serial = 18;
    sendEvent(sockets[1], event);
    event = {}; event.key.t = EVENT_KEY; event.key.key = 38;
    sendEvent(sockets[1], event);
    handleLorieEvents(sockets[0], X_NOTIFY_READ, reader);
    assert((observed == std::vector<std::string>{"key-down:38", "screen:Fold", "locks:1", "unicode-down:233", "unicode-up:233", "touch", "clipboard:all", "sync:18"}));
    assert((queuedInput == std::vector<std::string>{"key-up:38"})); // after the marker

    observed.clear(); queuedInput.clear();
    event = {}; event.clipboardSend.t = EVENT_CLIPBOARD_SEND; event.clipboardSend.count = 4;
    sendEvent(sockets[1], event, "pa");
    handleLorieEvents(sockets[0], X_NOTIFY_READ, reader);
    assert(observed.empty());
    assert(write(sockets[1], "ss", 2) == 2);
    event = {}; event.sync.t = EVENT_SYNC; event.sync.serial = 19;
    sendEvent(sockets[1], event);
    shutdown(sockets[1], SHUT_WR);
    // HUP must still dispatch the complete preceding body and sync marker, then
    // release the connection exactly once. No successful partial clipboard.
    handleLorieEvents(sockets[0], X_NOTIFY_READ | X_NOTIFY_ERROR, reader);
    assert((observed == std::vector<std::string>{"clipboard:pass", "sync:19", "clipboard-off"}));
    assert(conn_fd == -1 && connectionReader == nullptr && removed == 1);
    close(sockets[1]);
    puts("PASS: production dispatcher preserves key/mutation/touch/clipboard/sync order, defers partial body, drains HUP, cleans EOF");
}
