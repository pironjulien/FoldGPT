/*
 * libquiet_xext.so - Silence missing XFree86-VidModeExtension error log flood.
 *
 * Intercepts XMissingExtension(Display *dpy, const char *ext_name) called by
 * libXext when Chromium / Mesa GLX calls glXGetMscRateOML on displays lacking
 * XFree86-VidModeExtension (such as Xlorie).
 */

int XMissingExtension(void *dpy, const char *ext_name) {
    (void)dpy;
    (void)ext_name;
    return 0;
}
