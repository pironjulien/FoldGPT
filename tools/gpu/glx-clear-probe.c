/* Offscreen GLX pbuffer: clear + rasterized triangles through Zink on Adreno. */
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    Display *display = XOpenDisplay(NULL);
    if (!display) { fprintf(stderr, "Cannot connect to the existing X display\n"); return 1; }
    const int attributes[] = {GLX_X_RENDERABLE, True, GLX_DRAWABLE_TYPE, GLX_PBUFFER_BIT,
        GLX_RENDER_TYPE, GLX_RGBA_BIT, GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8,
        GLX_BLUE_SIZE, 8, GLX_ALPHA_SIZE, 8, None};
    int count = 0;
    GLXFBConfig *configs = glXChooseFBConfig(display, DefaultScreen(display), attributes, &count);
    if (!configs || count < 1) { fprintf(stderr, "No GLX pbuffer configuration\n"); return 1; }
    GLXContext context = glXCreateNewContext(display, configs[0], GLX_RGBA_TYPE, NULL, True);
    if (!context) { fprintf(stderr, "No direct GLX context\n"); return 1; }
    const int size[] = {GLX_PBUFFER_WIDTH, 64, GLX_PBUFFER_HEIGHT, 64, None};
    GLXPbuffer buffer = glXCreatePbuffer(display, configs[0], size);
    if (!buffer || !glXMakeContextCurrent(display, buffer, buffer, context)) {
        fprintf(stderr, "Cannot make the offscreen GLX context current\n"); return 1;
    }
    const char *renderer = (const char *)glGetString(GL_RENDERER);
    printf("OpenGL renderer=%s version=%s direct=%d\n", renderer ? renderer : "unavailable", glGetString(GL_VERSION), glXIsDirect(display, context));
    if (!renderer || !strstr(renderer, "zink") || !strstr(renderer, "Adreno")) {
        fprintf(stderr, "Refusing non-Zink/Adreno rendering as hardware proof\n"); return 1;
    }
    glViewport(0, 0, 64, 64);
    glClearColor(0, 1, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    unsigned char pixels[64 * 64 * 4];
    glReadPixels(0, 0, 64, 64, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    if (glGetError() != GL_NO_ERROR) { fprintf(stderr, "Offscreen OpenGL operation failed\n"); return 1; }
    const unsigned char expected[] = {0, 255, 0, 255};
    for (unsigned i = 0; i < sizeof(pixels); i++) if (pixels[i] != expected[i % 4]) {
        fprintf(stderr, "OpenGL readback mismatch at byte %u\n", i); return 1;
    }
    /* Mesa translates compatibility vertex/color state into real shaders.
     * This second result cannot be satisfied by clear/transfer commands alone. */
    glColor4f(1, 0, 0, 1);
    glBegin(GL_TRIANGLES);
    glVertex2f(-1, -1); glVertex2f(1, -1); glVertex2f(1, 1);
    glVertex2f(-1, -1); glVertex2f(1, 1); glVertex2f(-1, 1);
    glEnd();
    glReadPixels(0, 0, 64, 64, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    if (glGetError() != GL_NO_ERROR) { fprintf(stderr, "Offscreen triangle operation failed\n"); return 1; }
    const unsigned char drawn[] = {255, 0, 0, 255};
    for (unsigned i = 0; i < sizeof(pixels); i++) if (pixels[i] != drawn[i % 4]) {
        fprintf(stderr, "OpenGL triangle readback mismatch at byte %u\n", i); return 1;
    }
    puts("PASS: offscreen Zink/Adreno clear and rasterized triangle pixels verified");
    glXMakeContextCurrent(display, None, None, NULL);
    glXDestroyPbuffer(display, buffer);
    glXDestroyContext(display, context);
    XFree(configs);
    XCloseDisplay(display);
    return 0;
}
