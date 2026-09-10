/* A short-lived, unfocused X11 window tests real GPU presentation and readback. */
#define _GNU_SOURCE
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/Xrandr.h>
#include <stdio.h>
#include <string.h>
#include <signal.h>
#include <ucontext.h>
#include <dlfcn.h>
#include <unistd.h>
#include <stdlib.h>
#include <stdbool.h>
#include <poll.h>
#include <time.h>
#include <xcb/xcb.h>
#include <xcb/present.h>

/* Diagnostic only: record the fault, then preserve the fatal signal outcome. */
static void fault(int number, siginfo_t *info, void *context) {
    const ucontext_t *state = context;
    void *pc = (void *)state->uc_mcontext.pc;
    Dl_info location = {0};
    dladdr(pc, &location);
    fprintf(stderr, "FAULT signal=%d code=%d address=%p pc=%p module=%s offset=%lx\n", number, info->si_code,
        info->si_addr, pc, location.dli_fname ? location.dli_fname : "unknown",
        (unsigned long)pc - (unsigned long)location.dli_fbase);
    void *lr = (void *)state->uc_mcontext.regs[30];
    dladdr(lr, &location);
    fprintf(stderr, "CALLER lr=%p module=%s offset=%lx\n", lr,
        location.dli_fname ? location.dli_fname : "unknown", (unsigned long)lr - (unsigned long)location.dli_fbase);
    signal(number, SIG_DFL);
    raise(number);
}

int main(void) {
    setbuf(stdout, NULL);
    struct sigaction diagnostic = {.sa_sigaction = fault, .sa_flags = SA_SIGINFO | SA_RESETHAND};
    sigemptyset(&diagnostic.sa_mask);
    sigaction(SIGBUS, &diagnostic, NULL);
    sigaction(SIGSEGV, &diagnostic, NULL);
    Display *display = XOpenDisplay(NULL);
    if (!display) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    const int attrs[] = {GLX_X_RENDERABLE, True, GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE, GLX_RGBA_BIT, GLX_DOUBLEBUFFER, True,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8, None};
    int count;
    GLXFBConfig *configs = glXChooseFBConfig(display, DefaultScreen(display), attrs, &count);
    if (!configs || !count) { fprintf(stderr, "No GLX window configuration\n"); return 1; }
    XVisualInfo *visual = glXGetVisualFromFBConfig(display, configs[0]);
    if (!visual) return 1;
    Colormap colormap = XCreateColormap(display, RootWindow(display, visual->screen), visual->visual, AllocNone);
    XSetWindowAttributes settings = {.colormap = colormap, .override_redirect = True};
    Window window = XCreateWindow(display, RootWindow(display, visual->screen), 0, 0, 64, 64,
        0, visual->depth, InputOutput, visual->visual, CWColormap | CWOverrideRedirect, &settings);
    XStoreName(display, window, "FoldGPT bounded GPU presentation probe");
    XSync(display, False);
    /* Observe real Present completion on a separate connection so Mesa retains
     * ownership of its own X11 event queue. A swap is asynchronous with vblank. */
    xcb_connection_t *observer = xcb_connect(NULL, NULL);
    if (xcb_connection_has_error(observer)) return 1;
    xcb_present_query_version_reply_t *present_version = xcb_present_query_version_reply(observer,
        xcb_present_query_version(observer, 1, 2), NULL);
    if (!present_version) return 1;
    free(present_version);
    uint32_t event_id = xcb_generate_id(observer);
    xcb_generic_error_t *event_error = xcb_request_check(observer,
        xcb_present_select_input_checked(observer, event_id, window, XCB_PRESENT_EVENT_MASK_COMPLETE_NOTIFY));
    if (event_error) { fprintf(stderr, "Present observer registration failed\n"); free(event_error); return 1; }
    GLXWindow drawable = glXCreateWindow(display, configs[0], window, NULL);
    GLXContext context = glXCreateNewContext(display, configs[0], GLX_RGBA_TYPE, NULL, True);
    if (!context || !drawable) { fprintf(stderr, "GLX context/window creation failed\n"); return 1; }
    XMapRaised(display, window);
    XSync(display, False);
    puts("stage=window-mapped");
    if (!glXMakeContextCurrent(display, drawable, drawable, context)) return 1;
    const char *renderer = (const char *)glGetString(GL_RENDERER);
    printf("renderer=%s\n", renderer ? renderer : "unavailable");
    if (!renderer || !strstr(renderer, "zink") || !strstr(renderer, "Adreno")) return 1;
    PFNGLXGETMSCRATEOMLPROC get_rate = (PFNGLXGETMSCRATEOMLPROC)
        glXGetProcAddressARB((const GLubyte *)"glXGetMscRateOML");
    int32_t numerator = 0, denominator = 0;
    if (!get_rate || !get_rate(display, drawable, &numerator, &denominator) ||
        numerator <= 0 || denominator <= 0) {
        fprintf(stderr, "GLX refresh-rate query failed\n"); return 1;
    }
    XRRScreenResources *resources = XRRGetScreenResourcesCurrent(display,
        RootWindow(display, visual->screen));
    if (!resources) return 1;
    unsigned active = 0;
    for (int c = 0; c < resources->ncrtc; c++) {
        XRRCrtcInfo *crtc = XRRGetCrtcInfo(display, resources, resources->crtcs[c]);
        if (!crtc) return 1;
        if (crtc->mode) {
            bool matched = false;
            for (int m = 0; m < resources->nmode; m++) {
                const XRRModeInfo *mode = &resources->modes[m];
                if (mode->id != crtc->mode) continue;
                uint64_t n = mode->dotClock, d = (uint64_t)mode->hTotal * mode->vTotal;
                if (mode->modeFlags & RR_Interlace) n *= 2;
                if (mode->modeFlags & RR_DoubleScan) d *= 2;
                matched = n && d && (uint64_t)numerator * d == n * denominator;
                break;
            }
            if (!matched) { fprintf(stderr, "GLX/RandR rate mismatch\n"); return 1; }
            active++;
        }
        XRRFreeCrtcInfo(crtc);
    }
    XRRFreeScreenResources(resources);
    if (!active) return 1;
    printf("PASS: GLX rate %d/%d matches %u active RandR mode(s); not measured FPS\n",
        numerator, denominator, active);
    glViewport(0, 0, 64, 64);
    glClearColor(0, 1, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glFinish();
    if (glGetError() != GL_NO_ERROR) return 1;
    puts("stage=GPU-draw-completed");
    glXSwapBuffers(display, drawable);
    puts("stage=swap-returned");
    glFinish();
    XSync(display, False);
    puts("stage=X-server-synchronized");
    bool presented = false;
    struct timespec start, current;
    clock_gettime(CLOCK_MONOTONIC, &start);
    do {
        xcb_generic_event_t *event;
        while ((event = xcb_poll_for_event(observer))) {
            if ((event->response_type & 0x7f) == XCB_GE_GENERIC) {
                const xcb_present_complete_notify_event_t *complete = (const void *)event;
                if (complete->event_type == XCB_PRESENT_COMPLETE_NOTIFY && complete->event == event_id &&
                    complete->window == window && complete->kind == XCB_PRESENT_COMPLETE_KIND_PIXMAP) presented = true;
            }
            free(event);
        }
        if (presented) break;
        clock_gettime(CLOCK_MONOTONIC, &current);
        int remaining = 5000 - (int)((current.tv_sec - start.tv_sec) * 1000 +
            (current.tv_nsec - start.tv_nsec) / 1000000);
        if (remaining <= 0) break;
        struct pollfd ready = {.fd = xcb_get_file_descriptor(observer), .events = POLLIN};
        if (poll(&ready, 1, remaining) <= 0) break;
    } while (!presented);
    if (!presented) { fprintf(stderr, "Timed out waiting for X11 Present completion\n"); return 1; }
    puts("stage=Present-completion-received");
    XImage *image = XGetImage(display, window, 0, 0, 64, 64, AllPlanes, ZPixmap);
    if (!image) { fprintf(stderr, "X-server image readback failed\n"); return 1; }
    const unsigned long expected = image->green_mask;
    const unsigned long mask = image->red_mask | image->green_mask | image->blue_mask;
    for (int y = 0; y < 64; y++) for (int x = 0; x < 64; x++) {
        unsigned long pixel = XGetPixel(image, x, y) & mask;
        if (pixel != expected) {
            fprintf(stderr, "Presentation pixel mismatch at %d,%d: %lx != %lx\n", x, y, pixel, expected);
            return 1;
        }
    }
    puts("PASS: GPU buffer presented through X11; all window pixels verified");
    XDestroyImage(image);
    glXMakeContextCurrent(display, None, None, NULL);
    glXDestroyContext(display, context);
    glXDestroyWindow(display, drawable);
    XDestroyWindow(display, window);
    XFreeColormap(display, colormap);
    XFree(visual);
    XFree(configs);
    xcb_disconnect(observer);
    XCloseDisplay(display);
    return 0;
}
