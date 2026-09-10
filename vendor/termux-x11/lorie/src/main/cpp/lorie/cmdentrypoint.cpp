#pragma clang diagnostic ignored "-Wunknown-pragmas"
#pragma clang diagnostic ignored "-Wmissing-prototypes"
#pragma ide diagnostic ignored "bugprone-reserved-identifier"
#pragma ide diagnostic ignored "OCUnusedMacroInspection"
#pragma ide diagnostic ignored "EndlessLoop"
#define __USE_GNU
#ifdef HAVE_DIX_CONFIG_H
#include <dix-config.h>
#endif
#include <jni.h>
#include <android/log.h>
#include <android/native_window_jni.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/prctl.h>
#include <libgen.h>
#include <cerrno>
#include <new>
extern "C" {
#include <globals.h>
#define class lorie_reserved_class
#define public lorie_reserved_public
#include <xkbsrv.h>
#include <inpututils.h>
#include <randrstr.h>
#include <mi.h>
#undef class
#undef public
}
#include <linux/in.h>
#include <arpa/inet.h>
#include <poll.h>
#include "lorie.h"
#include "event-reader.h"

#define log(prio, ...) __android_log_print(ANDROID_LOG_ ## prio, "LorieNative", __VA_ARGS__)

static int argc = 0;
static char** argv = nullptr;
__LIBC_HIDDEN__ volatile int conn_fd = -1;
extern DeviceIntPtr lorieMouse, lorieTouch, lorieKeyboard, loriePen, lorieEraser;
extern ScreenPtr pScreenPtr;
extern "C" int ucs2keysym(long ucs);
extern "C" void lorieKeysymKeyboardEvent(KeySym keysym, int down);

char *xtrans_unix_path_x11 = nullptr;
char *xtrans_unix_dir_x11 = nullptr;

struct xorg_list registeredBuffers;

static JNIEnv* serverEnv = nullptr;
static jobject thiz = nullptr;
static jmethodID sendBroadcast = nullptr;
static jmethodID sendBroadcastDelayed = nullptr;

static jboolean start(JNIEnv *env, jobject self, jobjectArray args) {
    pthread_t t;
    JavaVM* vm = nullptr;

    thiz = env->NewGlobalRef(self);
    if (!thiz)
        FatalError("Failed to create a global reference for the CmdEntryPoint instance");
    sendBroadcast = env->GetMethodID(env->GetObjectClass(self), "sendBroadcast", "()V");
    sendBroadcastDelayed = env->GetMethodID(env->GetObjectClass(self), "sendBroadcastDelayed", "()V");
    auto detectTracer = []() -> Bool {
        FILE *fp;
        char line[256];
        int pid = 0;

        fp = fopen("/proc/self/status", "r");
        if (!fp)
            return TRUE;

        while (fgets(line, sizeof(line), fp)) {
            if (strncmp(line, "TracerPid:", 10) == 0) {
                pid = (int) strtol(line + 10, nullptr, 10);
                break;
            }
        }

        if (pid != 0)
            log(INFO, "Tracer detected");

        fclose(fp);
        return pid != 0;
    };
    // execv's argv array is a bit incompatible with Java's String[], so we do some converting here...
    argc = env->GetArrayLength(args) + 1; // Leading executable path
    argv = (char**) calloc(argc, sizeof(char*));

    argv[0] = (char*) "Xlorie";
    for(int i=1; i<argc; i++) {
        auto js = (jstring) env->GetObjectArrayElement(args, i - 1);
        const char *pjc = env->GetStringUTFChars(js, JNI_FALSE);
        argv[i] = (char *) calloc(strlen(pjc) + 1, sizeof(char)); //Extra char for the terminating NULL
        strcpy((char *) argv[i], pjc);
        env->ReleaseStringUTFChars(js, pjc);
    }

    {
        cpu_set_t mask;
        long num_cpus = sysconf(_SC_NPROCESSORS_ONLN);

        for (int i = num_cpus/2; i < num_cpus; i++)
            CPU_SET(i, &mask);

        if (sched_setaffinity(0, sizeof(cpu_set_t), &mask) == -1)
            log(ERROR, "Failed to set process affinity: %s", strerror(errno));
    }

    if (getenv("TERMUX_X11_DEBUG") && !fork()) {
        // Printing logs of local logcat.
        char pid[32] = {0};
        prctl(PR_SET_PDEATHSIG, SIGTERM);
        sprintf(pid, "%d", getppid());
        execlp("logcat", "logcat", "--pid", pid, nullptr);
    }

    // No matter what tracer is attached.
    // In the case of gdb or lldb LD_PRELOAD is already set.
    // In the case of proot or proot-distro libtermux-exec in LD_PRELOAD will break linking.
    if (access("/data/data/com.termux/files/usr/lib/libtermux-exec.so", F_OK) == 0 && !detectTracer()
            && !getenv("XSTARTUP_LD_PRELOAD"))
        setenv("LD_PRELOAD", "/data/data/com.termux/files/usr/lib/libtermux-exec.so", 1);

    // adb sets TMPDIR to /data/local/tmp which is pretty useless.
    if (!strcmp("/data/local/tmp", getenv("TMPDIR") ?: ""))
        unsetenv("TMPDIR");

    if (!getenv("TMPDIR")) {
        if (access("/tmp", F_OK) == 0)
            setenv("TMPDIR", "/tmp", 1);
        else if (access("/data/data/com.termux/files/usr/tmp", F_OK) == 0)
            setenv("TMPDIR", "/data/data/com.termux/files/usr/tmp", 1);
    }

    if (!getenv("TMPDIR")) {
        char* error = (char*) "$TMPDIR is not set. Normally it is pointing to /tmp of a container.";
        log(ERROR, "%s", error);
        dprintf(2, "%s\n", error);
        return JNI_FALSE;
    }

    {
        char* tmp = getenv("TMPDIR");
        char cwd[1024] = {0};

        if (!getcwd(cwd, sizeof(cwd)) || access(cwd, F_OK) != 0)
            chdir(tmp);
        asprintf(&xtrans_unix_path_x11, "%s/.X11-unix/X", tmp);
        asprintf(&xtrans_unix_dir_x11, "%s/.X11-unix/", tmp);
    }

    log(VERBOSE, "Using TMPDIR=\"%s\"", getenv("TMPDIR"));

    {
        const char *root_dir = dirname(getenv("TMPDIR"));
        const char* pathes[] = {
                "/etc/X11/fonts", "/usr/share/fonts/X11", "/share/fonts", nullptr
        };
        for (int i=0; pathes[i]; i++) {
            char current_path[1024] = {0};
            snprintf(current_path, sizeof(current_path), "%s%s", root_dir, pathes[i]);
            if (access(current_path, F_OK) == 0) {
                char default_font_path[4096] = {0};
                snprintf(default_font_path, sizeof(default_font_path),
                         "%s/misc,%s/TTF,%s/OTF,%s/Type1,%s/100dpi,%s/75dpi",
                         current_path, current_path, current_path, current_path, current_path, current_path);
                defaultFontPath = strdup(default_font_path);
                break;
            }
        }
    }

    if (!getenv("XKB_CONFIG_ROOT")) {
        // chroot case
        const char *root_dir = dirname(getenv("TMPDIR"));
        char current_path[1024] = {0};
        snprintf(current_path, sizeof(current_path), "%s/usr/share/X11/xkb", root_dir);
        if (access(current_path, F_OK) == 0)
            setenv("XKB_CONFIG_ROOT", current_path, 1);
    }

    if (!getenv("XKB_CONFIG_ROOT")) {
        // proot case
        if (access("/usr/share/xkeyboard-config-2", F_OK) == 0)
            setenv("XKB_CONFIG_ROOT", "/usr/share/xkeyboard-config-2", 1);
        else if (access("/usr/share/X11/xkb", F_OK) == 0)
            setenv("XKB_CONFIG_ROOT", "/usr/share/X11/xkb", 1);
        // Termux case
        else if (access("/data/data/com.termux/files/usr/share/xkeyboard-config-2", F_OK) == 0)
            setenv("XKB_CONFIG_ROOT", "/data/data/com.termux/files/usr/share/xkeyboard-config-2", 1);
        else if (access("/data/data/com.termux/files/usr/share/X11/xkb", F_OK) == 0)
            setenv("XKB_CONFIG_ROOT", "/data/data/com.termux/files/usr/share/X11/xkb", 1);
    }

    if (!getenv("XKB_CONFIG_ROOT")) {
        char* error = (char*) "$XKB_CONFIG_ROOT is not set. Normally it is pointing to /usr/share/X11/xkb of a container.";
        log(ERROR, "%s", error);
        dprintf(2, "%s\n", error);
        return JNI_FALSE;
    }

    XkbBaseDirectory = getenv("XKB_CONFIG_ROOT");
    if (access(XkbBaseDirectory, F_OK) != 0) {
        log(ERROR, "%s is unaccessible: %s\n", XkbBaseDirectory, strerror(errno));
        printf("%s is unaccessible: %s\n", XkbBaseDirectory, strerror(errno));
        return JNI_FALSE;
    }

    env->GetJavaVM(&vm);

    AChoreographer *choreographer = AChoreographer_getInstance();
    // Trigger it first time
    AChoreographer_postFrameCallback(choreographer, (AChoreographer_frameCallback) lorieChoreographerFrameCallback, choreographer);

    xorg_list_init(&registeredBuffers);
    pthread_create(&t, nullptr, +[](void* cookie) -> void* {
        if (((JavaVM*) cookie)->AttachCurrentThread(&serverEnv, nullptr) != JNI_OK)
            FatalError("Failed to attach the X server thread to the JVM");
        exit(dix_main(argc, (char**) argv, (char*[]) { nullptr }));
    }, vm);
    return JNI_TRUE;
}

static void handleTouchEvent(lorieEvent* e) {
    ValuatorMask mask;
    double x = max(min((float) e->touch.x, pScreenPtr->width), 0);
    double y = max(min((float) e->touch.y, pScreenPtr->height), 0);
    valuator_mask_zero(&mask);
    DDXTouchPointInfoPtr touch = TouchFindByDDXID(lorieTouch, e->touch.id, FALSE);

    // Avoid duplicating events
    if (touch && touch->active) {
        double oldx = 0, oldy = 0;
        if (e->touch.type == XI_TouchUpdate &&
            valuator_mask_fetch_double(touch->valuators, 0, &oldx) &&
            valuator_mask_fetch_double(touch->valuators, 1, &oldy) &&
            oldx == x && oldy == y)
            goto end;
    }

    // Sometimes activity part does not send XI_TouchBegin and sends only XI_TouchUpdate.
    if (e->touch.type == XI_TouchUpdate && (!touch || !touch->active))
        e->touch.type = XI_TouchBegin;

    if (e->touch.type == XI_TouchEnd && (!touch || !touch->active))
        goto end;

    valuator_mask_set_double(&mask, 0, x * 0xFFFF / (float) pScreenPtr->width);
    valuator_mask_set_double(&mask, 1, y * 0xFFFF / (float) pScreenPtr->height);
    QueueTouchEvents(lorieTouch, e->touch.type, e->touch.id, 0, &mask);
    lorieSetCursorVisible(FALSE);

    end:
    return;
}

static LorieEventReader* connectionReader = nullptr;

static void closeLorieConnection(int fd, LorieEventReader* reader) {
    RemoveNotifyFd(fd);
    close(fd);
    LorieEventReader::destroy(reader);
    if (fd == conn_fd) {
        LorieBuffer* buf;
        conn_fd = -1;
        connectionReader = nullptr;
        lorieEnableClipboardSync(FALSE);
        while ((buf = LorieBufferList_first(&registeredBuffers)))
            LorieBuffer_removeFromList(buf);
    }
}

void handleLorieEvents(int fd, int ready, void* data) {
    auto* reader = (LorieEventReader*) data;
    LorieEventReader::Budget budget;
    while (true) {
        auto result = reader->next(fd, budget);
        if (result == LorieEventReader::Result::Yield)
            return;
        if (result == LorieEventReader::Result::WouldBlock && !(ready & X_NOTIFY_ERROR))
            return;
        if (result != LorieEventReader::Result::Frame) {
            if (result == LorieEventReader::Result::Error)
                log(ERROR, "Lorie connection: %s: %s", reader->errorMessage, strerror(reader->error));
            // Drain complete frames before honoring HUP; recvmsg reports EOF even
            // when the poller only reports readability. Destruction frees partial
            // payloads and any descriptor the dispatcher has not taken.
            closeLorieConnection(fd, reader);
            return;
        }
        ValuatorMask mask;
        valuator_mask_zero(&mask);
        lorieEvent e = reader->event;
        // Server mutations and sync replies must follow earlier queued input.
        // Raw device events can remain batched in mieq until a mutation/barrier;
        // Unicode's XKB implementation also drains its own press/release sequence.
        switch (e.type) {
            case EVENT_TOUCH:
            case EVENT_MOUSE:
            case EVENT_KEY:
            case EVENT_STYLUS:
                break;
            default:
                mieqProcessInputEvents();
                break;
        }
        switch(e.type) {
            case EVENT_SCREEN_SIZE: {
                char* name = reader->takePayload();
                lorieConfigureNotify(e.screenSize.width, e.screenSize.height,
                                     e.screenSize.framerate, e.screenSize.name_size, name);
                free(name);
                break;
            }
            case EVENT_TOUCH:
                handleTouchEvent(&e);
                break;
            case EVENT_STYLUS: {
                static int buttons_prev = 0;
                uint32_t released, pressed, diff;
                DeviceIntPtr device = e.stylus.mouse ? lorieMouse : (e.stylus.eraser ? lorieEraser : loriePen);
                if (!device) {
                    __android_log_print(ANDROID_LOG_DEBUG, "LorieNative", "got stylus event but device is not requested\n");
                    break;
                }
                __android_log_print(ANDROID_LOG_DEBUG, "LorieNative", "got stylus event %f %f %d %d %d %d %s\n", e.stylus.x, e.stylus.y, e.stylus.pressure, e.stylus.tilt_x, e.stylus.tilt_y, e.stylus.orientation,
                                    device == lorieMouse ? "lorieMouse" : (device == loriePen ? "loriePen" : "lorieEraser"));

                valuator_mask_set_double(&mask, 0, max(min(e.stylus.x, pScreenPtr->width), 0));
                valuator_mask_set_double(&mask, 1, max(min(e.stylus.y, pScreenPtr->height), 0));
                if (device != lorieMouse) {
                    valuator_mask_set_double(&mask, 2, e.stylus.pressure);
                    valuator_mask_set_double(&mask, 3, e.stylus.tilt_x);
                    valuator_mask_set_double(&mask, 4, e.stylus.tilt_y);
                    valuator_mask_set_double(&mask, 5, e.stylus.orientation);
                }
                QueuePointerEvents(device, MotionNotify, 0, POINTER_ABSOLUTE | POINTER_DESKTOP | (device == lorieMouse ? POINTER_NORAW : 0), &mask);

                diff = buttons_prev ^ e.stylus.buttons;
                released = diff & ~e.stylus.buttons;
                pressed = diff & e.stylus.buttons;

                for (int i=0; i<3; i++) {
                    if (released & 0x1) {
                        QueuePointerEvents(device, ButtonRelease, i + 1, POINTER_RELATIVE, nullptr);
                        __android_log_print(ANDROID_LOG_DEBUG, "LorieNative", "sending %d press", i+1);
                    }
                    if (pressed & 0x1) {
                        QueuePointerEvents(device, ButtonPress, i + 1, POINTER_RELATIVE, nullptr);
                        __android_log_print(ANDROID_LOG_DEBUG, "LorieNative", "sending %d release", i+1);
                    }
                    released >>= 1;
                    pressed >>= 1;
                }
                buttons_prev = e.stylus.buttons;

                break;
            }
            case EVENT_STYLUS_ENABLE: {
                lorieSetStylusEnabled(e.stylusEnable.enable);
                break;
            }
            case EVENT_MOUSE: {
                int flags;
                lorieSetCursorVisible(TRUE);
                switch(e.mouse.detail) {
                    case 0: // BUTTON_UNDEFINED
                        flags = (e.mouse.relative) ? POINTER_RELATIVE | POINTER_ACCELERATE : POINTER_ABSOLUTE | POINTER_SCREEN | POINTER_NORAW;
                        if (!e.mouse.relative) {
                            e.mouse.x = max(0, min(e.mouse.x, pScreenPtr->width));
                            e.mouse.y = max(0, min(e.mouse.y, pScreenPtr->height));
                        }
                        valuator_mask_set_double(&mask, 0, (double) e.mouse.x);
                        valuator_mask_set_double(&mask, 1, (double) e.mouse.y);
                        QueuePointerEvents(lorieMouse, MotionNotify, 0, flags, &mask);
                        break;
                    case 1: // BUTTON_LEFT
                    case 2: // BUTTON_MIDDLE
                    case 3: // BUTTON_RIGHT
                        QueuePointerEvents(lorieMouse, e.mouse.down ? ButtonPress : ButtonRelease, e.mouse.detail, POINTER_RELATIVE, nullptr);
                        break;
                    case 4: // BUTTON_SCROLL
                        if (e.mouse.x != 0.0f) {
                            valuator_mask_zero(&mask);
                            valuator_mask_set_double(&mask, 2, (double) e.mouse.x / 120);
                            QueuePointerEvents(lorieMouse, MotionNotify, 0, POINTER_RELATIVE, &mask);
                        }
                        if (e.mouse.y != 0.0f) {
                            valuator_mask_zero(&mask);
                            valuator_mask_set_double(&mask, 3, (double) e.mouse.y / 120);
                            QueuePointerEvents(lorieMouse, MotionNotify, 0, POINTER_RELATIVE, &mask);
                        }
                        break;
                }
                break;
            }
            case EVENT_KEY:
                QueueKeyboardEvents(lorieKeyboard, e.key.state ? KeyPress : KeyRelease, e.key.key);
                break;
            case EVENT_UNICODE: {
                int ks = ucs2keysym((long) e.unicode.code);
                lorieKeysymKeyboardEvent(ks, TRUE);
                lorieKeysymKeyboardEvent(ks, FALSE);
                break;
            }
            case EVENT_CLIPBOARD_ENABLE:
                lorieEnableClipboardSync(e.clipboardEnable.enable);
                break;
            case EVENT_CLIPBOARD_ANNOUNCE:
                lorieHandleClipboardAnnounce();
                break;
            case EVENT_CLIPBOARD_SEND:
                // Clipboard takes ownership of the complete NUL-terminated data.
                lorieHandleClipboardData(reader->takePayload());
                break;
            case EVENT_RENDERER_WAKEUP_COND: {
                int wakeupFd = reader->takeDescriptor();
                if (wakeupFd >= 0)
                    lorieSetRendererWakeupCond(wakeupFd);
                break;
            }
            case EVENT_GPU_COPY_DONE:
                lorieRecheckGpuCopies();
                break;
            case EVENT_SYNC:
                // All preceding server actions have run and mieq was drained
                // before this marker. Later socket frames cannot enter the reply.
                lorieSendSyncReply(e.sync.serial);
                break;
            case EVENT_LOCK_KEYS_STATE:
                lorieSyncLockKeysState(e.lockKeysState.state);
                break;
        }

        reader->reset();
    }
}

void lorieSendClipboardData(const char* data) {
    if (data && conn_fd != -1) {
        size_t len = strlen(data);
        lorieEvent e = { .clipboardSend = { .t = EVENT_CLIPBOARD_SEND, .count = (uint32_t) len } };
        write(conn_fd, &e, sizeof(e));
        write(conn_fd, data, len);
    }
}

void lorieSendSyncReply(uint32_t serial) {
    if (conn_fd != -1) {
        lorieEvent e = { .sync = { .t = EVENT_SYNC_REPLY, .serial = serial } };
        write(conn_fd, &e, sizeof(e));
    }
}

void lorieRequestClipboard(void) {
    if (conn_fd != -1) {
        lorieEvent e = { .type = EVENT_CLIPBOARD_REQUEST };
        write(conn_fd, &e, sizeof(e));
    }
}

bool lorieConnectionAlive(void) {
    if (conn_fd == -1)
        return false;

    // Check if socket is closed or has errors.
    struct pollfd p = { .fd = conn_fd, .events = POLLIN | POLLHUP | POLLERR | POLLRDHUP };
    return !(poll(&p, 1, 0) == 1 && (p.revents & (POLLERR | POLLNVAL | POLLRDHUP | POLLHUP)));
}

void lorieSendSharedServerState(int memfd) {
    if (conn_fd != -1) {
        lorieEvent e = { .type = EVENT_SHARED_SERVER_STATE };
        write(conn_fd, &e, sizeof(e));
        ancil_send_fd(conn_fd, memfd);
    }
}

void lorieRegisterBuffer(LorieBuffer* buffer) {
    unsigned long id = LorieBuffer_description(buffer)->id;
    if (conn_fd == -1 || LorieBufferList_findById(&registeredBuffers, id))
        return; // Already registered

    if (conn_fd != -1 && buffer) {
        lorieEvent e = { .type = EVENT_ADD_BUFFER };
        write(conn_fd, &e, sizeof(e));
        LorieBuffer_sendHandleToUnixSocket(buffer, conn_fd);
        LorieBuffer_addToList(buffer, &registeredBuffers);
        const LorieBuffer_Desc* desc = LorieBuffer_description(buffer);
        log(INFO, "Sent shared buffer width %d stride %d height %d format %d type %d id %llu", desc->width, desc->stride, desc->height, desc->format, desc->type, desc->id);
    }
}

void lorieUnregisterBuffer(LorieBuffer* buffer) {
    unsigned long id;
    if (!buffer || (!LorieBufferList_findById(&registeredBuffers, (id = LorieBuffer_description(buffer)->id))))
        return;  // Not exist or not registered so no need to unregister

    if (conn_fd != -1 && buffer) {
        lorieEvent e = { .removeBuffer = { .t = EVENT_REMOVE_BUFFER, .id = id } };
        write(conn_fd, &e, sizeof(e));
        LorieBuffer_removeFromList(buffer);
    }
}

extern "C" void DDXNotifyFocusChanged(void) {
    if (conn_fd != -1) {
        lorieEvent e = { .type = EVENT_WINDOW_FOCUS_CHANGED };
        write(conn_fd, &e, sizeof(e));
    }
}

static jobject getXConnection(JNIEnv *env, __unused jobject cls) {
    int client[2];
    jclass ParcelFileDescriptorClass = env->FindClass("android/os/ParcelFileDescriptor");
    jmethodID adoptFd = env->GetStaticMethodID(ParcelFileDescriptorClass, "adoptFd", "(I)Landroid/os/ParcelFileDescriptor;");
    if (socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, client) < 0) {
        log(ERROR, "Failed to create the Lorie connection: %s", strerror(errno));
        return nullptr;
    }
    QueueWorkProc(+[](__unused ClientPtr pClient, void *closure) -> Bool {
        // This socket carries server operations as well as raw input. In particular,
        // Unicode input changes XKB mappings, sends MapNotify, and dispatches the
        // resulting key events. All three must run on the server thread so client
        // GetMap requests cannot observe a partially changed map or race its output.
        // Keep the complete socket stream on the server dispatcher so raw keys
        // cannot overtake Unicode input deferred separately through QueueWorkProc.
        int fd = (int) (int64_t) closure;
        auto* reader = LorieEventReader::create();
        if (!reader || !SetNotifyFd(fd, handleLorieEvents, X_NOTIFY_READ, reader)) {
            log(ERROR, "Failed to register the Lorie connection on the server thread");
            LorieEventReader::destroy(reader);
            close(fd);
            return TRUE;
        }
        // Reconnection cannot retain a partial frame or leave an old callback
        // able to clear the new connection's global state on its eventual EOF.
        if (conn_fd != -1) {
            mieqProcessInputEvents();
            closeLorieConnection(conn_fd, connectionReader);
        }
        conn_fd = fd;
        connectionReader = reader;
        lorieActivityConnected();
        return TRUE;
    }, nullptr, (void*) (int64_t) client[1]);
    lorieWakeServer();

    return env->CallStaticObjectMethod(ParcelFileDescriptorClass, adoptFd, client[0]);
}

static jobject getLogcatOutput(JNIEnv *env, __unused jobject cls) {
    jclass ParcelFileDescriptorClass = env->FindClass("android/os/ParcelFileDescriptor");
    jmethodID adoptFd = env->GetStaticMethodID(ParcelFileDescriptorClass, "adoptFd", "(I)Landroid/os/ParcelFileDescriptor;");
    const char *debug = getenv("TERMUX_X11_DEBUG");
    if (debug && !strcmp(debug, "1")) {
        pthread_t t;
        int p[2];
        pipe(p);
        fchmod(p[1], 0777);
        pthread_create(&t, nullptr, +[](void *arg) -> void* {
            char buffer[4096];
            size_t len;
            while((len = read((int) (int64_t) arg, buffer, 4096)) >=0)
                write(2, buffer, len);
            close((int) (int64_t) arg);
            return nullptr;
        }, (void*) (uint64_t) p[0]);
        return env->CallStaticObjectMethod(ParcelFileDescriptorClass, adoptFd, p[1]);
    }
    return nullptr;
}

void lorieListenForKnocks(void) {
    struct sockaddr_in address = { .sin_family = AF_INET, .sin_port = htons(PORT), .sin_addr = { .s_addr = INADDR_ANY } };
    int fd, reuse = 1;

    // Even in the case if it will fail for some reason everything will work fine
    // But connection will be delayed a bit

    if ((fd = socket(AF_INET, SOCK_STREAM, 0)) < 0) {
        log(ERROR, "Failed to create the knock-listening socket: %s", strerror(errno));
        serverEnv->CallVoidMethod(thiz, sendBroadcastDelayed);
        return;
    }

    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, &reuse, sizeof(reuse));

    if (bind(fd, (struct sockaddr *) &address, sizeof(address)) < 0) {
        log(ERROR, "Failed to bind the knock-listening socket to port %d: %s", PORT, strerror(errno));
        close(fd);
        serverEnv->CallVoidMethod(thiz, sendBroadcastDelayed);
        return;
    }

    if (listen(fd, 5) < 0) {
        log(ERROR, "Failed to listen on the knock-listening socket: %s", strerror(errno));
        close(fd);
        serverEnv->CallVoidMethod(thiz, sendBroadcastDelayed);
        return;
    }

    SetNotifyFd(fd, +[](int fd, int ready, __unused void *data) {
        struct sockaddr_in address;
        socklen_t addrlen = sizeof(address);
        uint8_t buffer[512] = {0};
        int client, count;

        if (ready & X_NOTIFY_ERROR) {
            RemoveNotifyFd(fd);
            close(fd);
            return;
        }

        if ((client = accept(fd, (struct sockaddr *) &address, &addrlen)) < 0) {
            log(ERROR, "Failed to accept a connection on the knock-listening socket: %s", strerror(errno));
            return;
        }

        if ((count = read(client, buffer, sizeof(buffer))) > 0 && !memcmp(buffer, MAGIC, min(count, sizeof(MAGIC)))) {
            log(DEBUG, "New client connection!\n");
            serverEnv->CallVoidMethod(thiz, sendBroadcast);
        }
        close(client);
    }, X_NOTIFY_READ, NULL);

    serverEnv->CallVoidMethod(thiz, sendBroadcastDelayed);
}

void registerCmdEntryPointNatives(JNIEnv *env) {
    static JNINativeMethod methods[] = {
            {"start", "([Ljava/lang/String;)Z", (void *) &start},
            {"getXConnection", "()Landroid/os/ParcelFileDescriptor;", (void *) &getXConnection},
            {"getLogcatOutput", "()Landroid/os/ParcelFileDescriptor;", (void *) &getLogcatOutput},
            {"connected", "()Z", (void *) +[]() -> jboolean { return conn_fd != -1; }}, // @CriticalNative
    };
    jclass cls = env->FindClass("com/termux/x11/CmdEntryPoint");
    env->RegisterNatives(cls, methods, sizeof(methods)/sizeof(methods[0]));
}

void abort(void) {
    _exit(134);
}

void exit(int code) {
    _exit(code);
}
