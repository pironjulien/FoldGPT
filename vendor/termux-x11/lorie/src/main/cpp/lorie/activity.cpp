#include <cstdio>
#include <cstdlib>
#include <unistd.h>
#include <cstring>
#include <pthread.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/mman.h>
#include <cerrno>
#include <jni.h>
#include <android/looper.h>
#include <cwchar>
#include <cstdint>
#include <linux/in.h>
#include <arpa/inet.h>
#include <poll.h>
#include <new>
#include "lorie.h"
#include "client-writer.h"
#include "clipboard-reader.h"

#pragma clang diagnostic ignored "-Wunknown-pragmas"
#pragma ide diagnostic ignored "cppcoreguidelines-narrowing-conversions"
#pragma ide diagnostic ignored "ConstantFunctionResult"
#define log(prio, ...) __android_log_print(ANDROID_LOG_ ## prio, "LorieNative", __VA_ARGS__)
// `r` must be a LorieViewResources* — the connection fd is per-instance state, not a process global.
#define sendEvent(r, ...) do { if (r) { lorieEvent e = { __VA_ARGS__ }; (r)->writer.sendFrame(&e, sizeof(e)); } } while (0)

bool lorieDebugEnabled = false;

// Timestamp of the last real input reaching the X session, from any source. Read/written only
// from the Android main thread via JNI.
static volatile int64_t lastInputTimestampMs = 0;

static int64_t nowMs() {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t) ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static struct {
    jclass self;
    jmethodID clientConnectedStateChanged, resetIme;
} MainActivity = {nullptr};

static struct {
    jclass self;
    jmethodID forName;
    jmethodID decode;
} Charset = {nullptr};

static struct {
    jclass self;
    jmethodID toString;
} CharBuffer = {nullptr};

// Bundles the native state belonging to the current LorieView instance so it can be released
// as a unit when that instance is torn down, instead of leaking as scattered process globals.
struct LorieViewResources {
    Renderer renderer;
    JNIEnv* env = nullptr;    // GUI-thread JNIEnv. Must be used only in GUI thread.
    jobject thiz = nullptr;   // global ref to the owning LorieView
    jobject activity = nullptr; // global ref to the owning MainActivity
    int connFd = -1; // Replaced on the main thread; renderer access is under writer's mutex.
    LorieClientWriter writer{connFd};
    bool destroyed = true;

    LorieViewResources(JNIEnv* callerEnv, jobject view);
    ~LorieViewResources();
    void connect(jint fd);
    int xcallback(int fd, int events);
};

static jclass FindClassOrDie(JNIEnv *env, const char* name) {
    jclass clazz = env->FindClass(name);
    if (!clazz) {
        char buffer[1024] = {0};
        sprintf(buffer, "class %s not found", name);
        log(ERROR, "%s", buffer);
        env->FatalError(buffer);
        return nullptr;
    }

    return (jclass) env->NewGlobalRef(clazz);
}

static jmethodID FindMethodOrDie(JNIEnv *env, jclass clazz, const char* name, const char* signature, jboolean isStatic) {
    jmethodID method = isStatic ? env->GetStaticMethodID(clazz, name, signature) : env->GetMethodID(clazz, name, signature);
    if (!method) {
        char buffer[1024] = {0};
        sprintf(buffer, "method %s %s not found", name, signature);
        log(ERROR, "%s", buffer);
        env->FatalError(buffer);
        return nullptr;
    }

    return method;
}

// @CriticalNative: no implicit JNIEnv*/jclass, unlike the @FastNative entries below.
static jboolean requestConnection(__unused jlong ptr) {
#define check(cond, fmt, ...) if ((cond)) do { __android_log_print(ANDROID_LOG_ERROR, "requestConnection", fmt, ## __VA_ARGS__); goto end; } while (0)
    bool sent = JNI_FALSE;
    // We do not want to block GUI thread for a long time so we will set timeout to 20 msec.
    struct sockaddr_in server = { .sin_family = AF_INET, .sin_port = htons(PORT) };
    server.sin_addr.s_addr = inet_addr("127.0.0.1");
    int so_error, sock = socket(AF_INET, SOCK_STREAM, 0);
    check(sock < 0, "Could not create socket: %s", strerror(errno));
    check(fcntl(sock, F_SETFL, O_NONBLOCK) < 0, "failed to set socket non-block: %s", strerror(errno));
    int r;
    r = connect(sock, (struct sockaddr *)&server, sizeof(server));
    check(r < 0 && errno != EINPROGRESS, "failed to connect socket: %s", strerror(errno));
    if (r < 0 && errno == EINPROGRESS) {
        // Connection is in progress; use poll to wait for it
        struct pollfd pfd = { .fd = sock, .events = POLLOUT };
        r = poll(&pfd, 1, 20);  // timeout set to 50ms
        if (!r) goto end;
        // check(!r, "Connection timed out after 20ms."); // We do not want to flood logcat with this message
        check(r < 0, "poll failed: %s", strerror(errno));
        socklen_t len = sizeof(so_error);
        check(getsockopt(sock, SOL_SOCKET, SO_ERROR, &so_error, &len) < 0, "getsockopt failed: %s", strerror(errno));
        if (so_error == ECONNREFUSED) goto end; // Regular situation which happens often if server is not started. No need to spam logcat with this.
        check(so_error != 0, "Connection failed: %s", strerror(so_error));

        check(write(sock, MAGIC, sizeof(MAGIC)) < 0, "failed to send message: %s", strerror(errno));
        sent = JNI_TRUE;
        goto end;
    }

    check(1, "something went wrong: %s, %s", strerror(errno), strerror(r));

    end: if (sock >= 0) close(sock);
    return sent;
#undef errorReturn
}

static jlong nativeInit(JNIEnv *env, jobject thiz) {
    if (!Charset.self) {
        // Init clipboard-related JNI stuff
        Charset.self = FindClassOrDie(env, "java/nio/charset/Charset");
        Charset.forName = FindMethodOrDie(env, Charset.self, "forName", "(Ljava/lang/String;)Ljava/nio/charset/Charset;", JNI_TRUE);
        Charset.decode = FindMethodOrDie(env, Charset.self, "decode", "(Ljava/nio/ByteBuffer;)Ljava/nio/CharBuffer;", JNI_FALSE);

        CharBuffer.self = FindClassOrDie(env,  "java/nio/CharBuffer");
        CharBuffer.toString = FindMethodOrDie(env, CharBuffer.self, "toString", "()Ljava/lang/String;", JNI_FALSE);

        MainActivity.self = FindClassOrDie(env,  "com/termux/x11/MainActivity");
        MainActivity.clientConnectedStateChanged = FindMethodOrDie(env, MainActivity.self, "clientConnectedStateChanged", "()V", JNI_FALSE);
        MainActivity.resetIme = FindMethodOrDie(env, env->GetObjectClass(thiz), "resetIme", "()V", JNI_FALSE);
    }

    return (jlong) (intptr_t) new (malloc(sizeof(LorieViewResources))) LorieViewResources(env, thiz);
}

LorieViewResources::LorieViewResources(JNIEnv *callerEnv, jobject view) {
    JavaVM* vm;
    destroyed = false;
    renderer.clientWriter = &writer; // Set before init starts the renderer thread.
    renderer.init(callerEnv, view);

    callerEnv->GetJavaVM(&vm);
    vm->AttachCurrentThread(&env, nullptr);
    thiz = env->NewGlobalRef(view);

    jfieldID activityField = env->GetFieldID(env->GetObjectClass(view), "activity", "Lcom/termux/x11/MainActivity;");
    jobject a = env->GetObjectField(view, activityField);
    if (a)
        activity = env->NewGlobalRef(a);

    connect(-1);
}

LorieViewResources::~LorieViewResources() {
    destroyed = true;

    if (connFd != -1) {
        ALooper_removeFd(ALooper_forThread(), connFd);
        writer.replace(-1);
    }

    renderer.destroy();

    if (thiz) {
        env->DeleteGlobalRef(thiz);
        thiz = nullptr;
    }

    if (activity) {
        env->DeleteGlobalRef(activity);
        activity = nullptr;
    }
}

int LorieViewResources::xcallback(int fd, int events) {
    if (events & (ALOOPER_EVENT_ERROR | ALOOPER_EVENT_HANGUP)) {
        if (activity)
            env->CallVoidMethod(activity, MainActivity.clientConnectedStateChanged);

        ALooper_removeFd(ALooper_forThread(), fd);
        writer.replace(-1);
        renderer.setSharedState(nullptr);
        renderer.removeAllBuffers();
        log(DEBUG, "disconnected");
        return 1;
    }

    if (connFd != -1) {
        lorieEvent e = {0};

        again:
        if (read(connFd, &e, sizeof(e)) == sizeof(e)) {
            switch(e.type) {
                case EVENT_CLIPBOARD_SEND: {
                    LorieClipboardData clipboard;
                    if (!clipboard.readFrom(connFd, e.clipboardSend.count)) {
                        log(ERROR, "Failed to receive clipboard (%u bytes): %s",
                            e.clipboardSend.count, strerror(errno));
                        connect(-1);
                        if (activity)
                            env->CallVoidMethod(activity, MainActivity.clientConnectedStateChanged);
                        return 1;
                    }
                    if (env->PushLocalFrame(8) < 0)
                        return 1;
                    jmethodID id = env->GetMethodID(env->GetObjectClass(thiz), "setClipboardText","(Ljava/lang/String;)V");
                    jobject bb = env->NewDirectByteBuffer(clipboard.bytes, e.clipboardSend.count);
                    jobject charset = env->CallStaticObjectMethod(Charset.self, Charset.forName, env->NewStringUTF("UTF-8"));
                    jobject cb = env->CallObjectMethod(charset, Charset.decode, bb);
                    env->DeleteLocalRef(bb);

                    auto str = (jstring) env->CallObjectMethod(cb, CharBuffer.toString);
                    env->CallVoidMethod(thiz, id, str);
                    env->PopLocalFrame(nullptr);
                    break;
                }
                case EVENT_CLIPBOARD_REQUEST: {
                    env->CallVoidMethod(thiz, env->GetMethodID(env->GetObjectClass(thiz), "requestClipboard", "()V"));
                    break;
                }
                case EVENT_SHARED_SERVER_STATE: {
                    struct lorie_shared_server_state* state = nullptr;
                    int stateFd = ancil_recv_fd(connFd);

                    if (stateFd < 0)
                        break;

                    state = (struct lorie_shared_server_state*) mmap(nullptr, sizeof(*state), PROT_READ|PROT_WRITE, MAP_SHARED, stateFd, 0);
                    if (!state || state == MAP_FAILED) {
                        log(ERROR, "Failed to map server state: %s", strerror(errno));
                        state = nullptr;
                    }

                    renderer.setSharedState(state);

                    close(stateFd); // Closing file descriptor does not unmmap shared memory fragment.
                    break;
                }
                case EVENT_ADD_BUFFER: {
                    static LorieBuffer* buffer = nullptr;
                    const LorieBuffer_Desc* desc;
                    LorieBuffer_recvHandleFromUnixSocket(connFd, &buffer);
                    desc = LorieBuffer_description(buffer);
                    log(INFO, "Received shared buffer width %d stride %d height %d format %d type %d id %llu", desc->width, desc->stride, desc->height, desc->format, desc->type, desc->id);
                    renderer.addBuffer(buffer);
                    break;
                }
                case EVENT_REMOVE_BUFFER: {
                    renderer.removeBuffer(e.removeBuffer.id);
                    break;
                }
                case EVENT_WINDOW_FOCUS_CHANGED: {
                    env->CallVoidMethod(thiz, MainActivity.resetIme);
                    break;
                }
                case EVENT_SYNC_REPLY: {
                    jmethodID id = env->GetMethodID(env->GetObjectClass(thiz), "onSyncReply", "(I)V");
                    env->CallVoidMethod(thiz, id, (jint) e.sync.serial);
                    break;
                }
            }
        }

        int n;
        if (ioctl(connFd, FIONREAD, &n) >= 0 && n > sizeof(e))
            goto again;
    }

    return 1;
}

void LorieViewResources::connect(jint fd) {
    if (connFd != -1) {
        ALooper_removeFd(ALooper_forThread(), connFd);
        writer.replace(-1);
        renderer.setSharedState(nullptr);
        renderer.removeAllBuffers();
        log(DEBUG, "disconnected");
    }

    writer.replace(fd);
    if (connFd != -1) {
        ALooper_addFd(ALooper_forThread(), fd, 0, ALOOPER_EVENT_INPUT | ALOOPER_EVENT_ERROR | ALOOPER_EVENT_HANGUP,
                      +[](int fd, int events, void* data) -> int { return ((LorieViewResources*) data)->xcallback(fd, events); }, this);

        // Give the X server our renderer wakeup cond var fd, resent on every reconnect.
        lorieEvent e = { .type = EVENT_RENDERER_WAKEUP_COND };
        writer.sendFrame(&e, sizeof(e), nullptr, 0, renderer.getWakeupCondFd());

        log(DEBUG, "XCB connection is successfull");
    }
}

static void startLogcat(JNIEnv *env, __unused jclass clazz, __unused jlong ptr, jint fd) {
    log(DEBUG, "Starting logcat with output to given fd");
    lorieDebugEnabled = true;

    switch(fork()) {
        case -1:
            log(ERROR, "fork: %s", strerror(errno));
            return;
        case 0:
            dup2(fd, 1);
            dup2(fd, 2);
            prctl(PR_SET_PDEATHSIG, SIGTERM);
            char buf[64] = {0};
            sprintf(buf, "--pid=%d", getppid());
            execl("/system/bin/logcat", "logcat", buf, NULL);
            log(ERROR, "exec logcat: %s", strerror(errno));
            env->FatalError("Exiting");
    }
}

static void sendTextEvent(JNIEnv *env, __unused jobject thiz, jlong ptr, jbyteArray text) {
    lastInputTimestampMs = nowMs();
    auto* r = (LorieViewResources*) ptr;
    if (r && r->connFd != -1 && text) {
        jsize length = env->GetArrayLength(text);
        if (!length)
            return;
        jbyte *str = env->GetByteArrayElements(text, nullptr);
        if (!str)
            return;
        char *p = (char*) str;
        const char *end = p + length;
        mbstate_t mbstate = { 0 };

        while (p < end && *p) {
            wchar_t wc;
            size_t len = mbrtowc(&wc, p, (size_t) (end - p), &mbstate);

            if (len == (size_t)-1 || len == (size_t)-2) {
                log(ERROR, "Invalid UTF-8 sequence encountered");
                break;
            }

            if (len == 0)
                break;

            lorieEvent e = { .unicode = { .t = EVENT_UNICODE, .code = (uint32_t) wc } };
            if (!r->writer.sendFrame(&e, sizeof(e)))
                break;
            p += len;
            if (p - (char*) str >= length)
                break;
            usleep(2500);
        }

        env->ReleaseByteArrayElements(text, str, JNI_ABORT);
    }
}

// Called on the Android main thread. One event, no sleeps and no blocking writes.
// Retrying is safe only when send reports that no bytes entered the stream.
static jint sendInputEventChecked(__unused JNIEnv *env, __unused jobject thiz,
                                 jlong ptr, jint code, jboolean unicode, jboolean down) {
    auto* r = (LorieViewResources*) ptr;
    if (!r || r->destroyed || r->connFd == -1)
        return -1;

    lorieEvent event = {};
    if (unicode) {
        if (code < 0 || code > 0x10FFFF || (code >= 0xD800 && code <= 0xDFFF))
            return -1;
        event.unicode.t = EVENT_UNICODE;
        event.unicode.code = (uint32_t) code;
    } else {
        if (code < 0 || (size_t) code >= sizeof(android_to_linux_keycode) / sizeof(android_to_linux_keycode[0]))
            return -1;
        int mapped = android_to_linux_keycode[code];
        if (mapped <= 0 || mapped > UINT16_MAX - 8)
            return -1;
        event.key.t = EVENT_KEY;
        event.key.key = (uint16_t) (mapped + 8);
        event.key.state = down;
    }

    int result = r->writer.sendChecked(&event, sizeof(event));
    if (result == 1) {
        lastInputTimestampMs = nowMs();
        return 1;
    }
    if (result == 0)
        return 0;
    // A short write leaves a partial frame. No later input may continue that stream.
    // Disconnect on fatal socket failures too, so a stale fd cannot appear connected.
    r->connect(-1);
    return -1;
}

extern char* __progname;

JNIEXPORT jint JNI_OnLoad(JavaVM *vm, __unused void *reserved) {
    JNIEnv* env;

    if (!strcmp(__progname, "com.termux.x11")) {
        // Redirects stderr to logcat.
        pthread_create([]{ static pthread_t t; return &t; }(), nullptr, +[](__unused void* cookie) -> void* {
            FILE *fp;
            int p[2];
            size_t len;
            char *line = nullptr;
            pipe(p);

            fp = fdopen(p[0], "r");

            dup2(p[1], 2);
            dup2(p[1], 1);
            while ((getline(&line, &len, fp)) != -1) {
                log(DEBUG, "%s%s", line, (line[len - 1] == '\n') ? "" : "\n");
            }

            return nullptr;
        }, nullptr);
    }

    static JNINativeMethod methods[] = {
            {"nativeInit", "()J", (void *)&nativeInit},
            {"nativeDestroy", "(J)V", (void *) +[](__unused JNIEnv *env, __unused jobject thiz, jlong ptr) {
                auto* r = (LorieViewResources*) ptr;
                if (!r) return;
                r->~LorieViewResources();
                free(r);
            }},
            {"surfaceChanged", "(JLandroid/view/Surface;)V", (void *) +[](JNIEnv *env, __unused jobject thiz, jlong ptr, jobject sfc) {
                auto* r = (LorieViewResources*) ptr;
                if (!r || r->destroyed) return;
                r->renderer.setWindow(env, sfc);
            }},
            {"setViewport", "(JIIIIIII)V", (void *) +[](__unused JNIEnv *env, __unused jobject thiz, jlong ptr, jint x, jint y, jint w, jint h, jint ew, jint eh, jint hidden) {
                auto* r = (LorieViewResources*) ptr;
                if (!r || r->destroyed) return;
                r->renderer.setViewport(x, y, w, h, ew, eh, hidden);
            }},
            {"setRendererZoom", "(JI)V", (void *) +[](__unused JNIEnv *env, __unused jobject thiz, jlong ptr, jint percent) {
                auto* r = (LorieViewResources*) ptr;
                if (!r || r->destroyed) return;
                r->renderer.setZoom(percent);
            }},
            {"setZoomAnchor", "(JFFFF)V", (void *) +[](__unused JNIEnv *env, __unused jobject thiz, jlong ptr, jfloat sourceX, jfloat sourceY, jfloat fracX, jfloat fracY) {
                auto* r = (LorieViewResources*) ptr;
                if (!r || r->destroyed) return;
                r->renderer.setZoomAnchor(sourceX, sourceY, fracX, fracY);
            }},
            {"clearZoomAnchor", "(J)V", (void *) +[](__unused JNIEnv *env, __unused jobject thiz, jlong ptr) {
                auto* r = (LorieViewResources*) ptr;
                if (!r || r->destroyed) return;
                r->renderer.clearZoomAnchor();
            }},
            {"getCursorPosition", "(J)J", (void *) +[](__unused JNIEnv *env, __unused jobject thiz, jlong ptr) -> jlong {
                auto* r = (LorieViewResources*) ptr;
                if (!r || r->destroyed || !r->renderer.state) return 0;
                return ((jlong) r->renderer.state->cursor.x << 32) | (jlong) r->renderer.state->cursor.y;
            }},
            {"sendSync", "(JI)V", (void *) +[](__unused JNIEnv *env, __unused jobject thiz, jlong ptr, jint serial) {
                auto* r = (LorieViewResources*) ptr;
                sendEvent(r, .sync = { .t = EVENT_SYNC, .serial = (uint32_t) serial });
            }},
            {"setFiltering", "(JI)V", (void *) +[](__unused JNIEnv* env, __unused jobject self, jlong ptr, jint filtering) {
                auto* r = (LorieViewResources*) ptr;
                if (!r || r->destroyed) return;
                r->renderer.setFiltering(filtering);
            }},
            {"connect", "(JI)V", (void *) +[](__unused JNIEnv* env, __unused jclass clazz, jlong ptr, jint fd) {
                auto* r = (LorieViewResources*) ptr;
                if (!r) return;
                r->connect(fd);
            }},
            // @CriticalNative: no implicit JNIEnv*/jclass, unlike the @FastNative entries below.
            {"connected", "(J)Z", (void *) +[](jlong ptr) -> jboolean {
                auto* r = (LorieViewResources*) ptr;
                return r && r->connFd != -1;
            }},
            {"startLogcat", "(JI)V", (void *)&startLogcat},
            {"setClipboardSyncEnabled", "(JZZ)V", (void *) +[](__unused JNIEnv* env, __unused jobject cls, jlong ptr, jboolean enable, __unused jboolean ignored) {
                auto* r = (LorieViewResources*) ptr;
                sendEvent(r, .clipboardEnable = { .t = EVENT_CLIPBOARD_ENABLE, .enable = enable });
            }},
            {"sendClipboardAnnounce", "(J)V", (void *) +[](__unused JNIEnv *env, __unused jobject thiz, jlong ptr) {
                auto* r = (LorieViewResources*) ptr;
                sendEvent(r, .type = EVENT_CLIPBOARD_ANNOUNCE);
            }},
            {"sendClipboardEvent", "(J[B)V", (void *) +[](JNIEnv *env, __unused jobject thiz, jlong ptr, jbyteArray text) {
                auto* r = (LorieViewResources*) ptr;
                if (r && r->connFd != -1 && text) {
                    jsize length = env->GetArrayLength(text);
                    if ((size_t) length > LORIE_MAX_CLIPBOARD_BYTES) {
                        env->ThrowNew(env->FindClass("java/lang/IllegalArgumentException"),
                                      "Clipboard exceeds the Lorie transport size limit");
                        return;
                    }
                    jbyte* str = env->GetByteArrayElements(text, nullptr);
                    if (!str)
                        return;
                    lorieEvent e = { .clipboardSend = { .t = EVENT_CLIPBOARD_SEND, .count = (uint32_t) length } };
                    r->writer.sendFrame(&e, sizeof(e), str, (size_t) length);
                    env->ReleaseByteArrayElements(text, str, JNI_ABORT);
                }
            }},
            {"sendWindowChange", "(JIIILjava/lang/String;)V", (void *) +[](__unused JNIEnv* env, __unused jobject cls, jlong ptr, jint width, jint height, jint framerate, jstring jname) {
                auto* r = (LorieViewResources*) ptr;
                if (r && r->connFd != -1) {
                    bool hasName = jname && width > 0 && height > 0;
                    const char *name = hasName ? env->GetStringUTFChars(jname, JNI_FALSE) : nullptr;
                    if (hasName && !name)
                        return;
                    size_t nameSize = name ? strlen(name) : 0;
                    if (nameSize > LORIE_MAX_SCREEN_NAME_BYTES) {
                        env->ReleaseStringUTFChars(jname, name);
                        env->ThrowNew(env->FindClass("java/lang/IllegalArgumentException"),
                                      "Display name exceeds the Lorie transport size limit");
                        return;
                    }
                    lorieEvent e = { .screenSize = { .t = EVENT_SCREEN_SIZE, .width = (uint16_t) width, .height = (uint16_t) height, .framerate = (uint16_t) framerate, .name_size = nameSize } };
                    r->writer.sendFrame(&e, sizeof(e), name, nameSize);
                    if (name) {
                        env->ReleaseStringUTFChars(jname, name);
                    }
                }
            }},
            {"sendMouseEvent", "(JFFIZZ)V", (void *) +[](JNIEnv* env, __unused jobject cls, jlong ptr, jfloat x, jfloat y, jint which_button, jboolean button_down, jboolean relative) {
                lastInputTimestampMs = nowMs();
                auto* r = (LorieViewResources*) ptr;
                if (r && r->connFd != -1) {
                    if (which_button > 0)
                        env->CallVoidMethod(r->thiz, MainActivity.resetIme);
                    sendEvent(r, .mouse = { .t = EVENT_MOUSE, .x = x, .y = y, .detail = (uint8_t) which_button, .down = button_down, .relative = relative });
                }
            }},
            {"sendTouchEvent", "(JIIII)V", (void *) +[](__unused JNIEnv* env, __unused jobject cls, jlong ptr, jint action, jint id, jint x, jint y) {
                lastInputTimestampMs = nowMs();
                auto* r = (LorieViewResources*) ptr;
                if (action != -1)
                    sendEvent(r, .touch = { .t = EVENT_TOUCH, .type = (uint16_t) action, .id = (uint16_t) id, .x = (uint16_t) x, .y = (uint16_t) y });
            }},
            {"sendStylusEvent", "(JFFIIIIIZZ)V", (void *) +[](JNIEnv *env, __unused jobject thiz, jlong ptr, jfloat x, jfloat y, jint pressure, jint tilt_x, jint tilt_y, jint orientation, jint buttons, jboolean eraser, jboolean mouse) {
                lastInputTimestampMs = nowMs();
                auto* r = (LorieViewResources*) ptr;
                if (r && r->connFd != -1) {
                    env->CallVoidMethod(r->thiz, MainActivity.resetIme);
                    sendEvent(r, .stylus = { .t = EVENT_STYLUS, .x = x, .y = y, .pressure = (uint16_t) pressure, .tilt_x = (int8_t) tilt_x, .tilt_y = (int8_t) tilt_y, .orientation = (int16_t) orientation, .buttons = (uint8_t) buttons, .eraser = eraser, .mouse = mouse });
                }
            }},
            {"requestStylusEnabled", "(JZ)V", (void *) +[](__unused JNIEnv *env, __unused jobject thiz, jlong ptr, jboolean enabled) {
                auto* r = (LorieViewResources*) ptr;
                sendEvent(r, .stylusEnable = { .t = EVENT_STYLUS_ENABLE, .enable = enabled });
            }},
            {"sendLockKeysState", "(JI)V", (void *) +[](__unused JNIEnv *env, __unused jobject thiz, jlong ptr, jint state) {
                auto* r = (LorieViewResources*) ptr;
                sendEvent(r, .lockKeysState = { .t = EVENT_LOCK_KEYS_STATE, .state = (uint8_t) state });
            }},
            {"sendKeyEvent", "(JIIZ)Z", (void *) +[](__unused JNIEnv* env, __unused jobject cls, jlong ptr, jint scan_code, jint key_code, jboolean key_down) -> jboolean {
                lastInputTimestampMs = nowMs();
                auto* r = (LorieViewResources*) ptr;
                if (r && r->connFd != -1) {
                    int code = (scan_code) ?: android_to_linux_keycode[key_code];
                    sendEvent(r, .key = { .t = EVENT_KEY, .key = (uint16_t) (code + 8), .state = key_down });
                }
                return true;
            }},
            {"sendTextEvent", "(J[B)V", (void *)&sendTextEvent},
            {"sendInputEventChecked", "(JIZZ)I", (void *)&sendInputEventChecked},
            {"requestConnection", "(J)Z", (void *)&requestConnection},
            {"getLastInputTimestamp", "()J", (void *) +[](__unused JNIEnv* env, __unused jclass clazz) -> jlong {
                return (jlong) lastInputTimestampMs;
            }},
            {"markUserActivity", "()V", (void *) +[](__unused JNIEnv* env, __unused jclass clazz) {
                lastInputTimestampMs = nowMs();
            }},
    };
    vm->AttachCurrentThread(&env, nullptr);
    jclass cls = env->FindClass("com/termux/x11/LorieView");
    env->RegisterNatives(cls, methods, sizeof(methods)/sizeof(methods[0]));

    registerCmdEntryPointNatives(env);

    return JNI_VERSION_1_6;
}
