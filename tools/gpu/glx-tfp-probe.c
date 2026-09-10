/* Texture-from-pixmap test using only a private X pixmap and GLX pbuffer. */
#include <GL/gl.h>
#include <GL/glx.h>
#include <GL/glxext.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    setbuf(stdout, NULL);
    Display *display = XOpenDisplay(NULL);
    if (!display) return 1;
    const char *extensions = glXQueryExtensionsString(display, DefaultScreen(display));
    if (!extensions || !strstr(extensions, "GLX_EXT_texture_from_pixmap")) {
        fprintf(stderr, "GLX_EXT_texture_from_pixmap unavailable\n"); return 1;
    }
    const int attrs[] = {GLX_X_RENDERABLE, True, GLX_DRAWABLE_TYPE, GLX_PIXMAP_BIT | GLX_PBUFFER_BIT,
        GLX_RENDER_TYPE, GLX_RGBA_BIT, GLX_BIND_TO_TEXTURE_RGB_EXT, True,
        GLX_BIND_TO_TEXTURE_TARGETS_EXT, GLX_TEXTURE_2D_BIT_EXT,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8, None};
    int count = 0;
    GLXFBConfig *configs = glXChooseFBConfig(display, DefaultScreen(display), attrs, &count);
    GLXFBConfig config = NULL;
    for (int i = 0; configs && i < count; i++) {
        XVisualInfo *visual = glXGetVisualFromFBConfig(display, configs[i]);
        if (visual && visual->depth == DefaultDepth(display, DefaultScreen(display))) config = configs[i];
        if (visual) XFree(visual);
        if (config) break;
    }
    if (!config) { fprintf(stderr, "No matching texture-from-pixmap configuration\n"); return 1; }
    const int size[] = {GLX_PBUFFER_WIDTH, 64, GLX_PBUFFER_HEIGHT, 64, None};
    GLXPbuffer buffer = glXCreatePbuffer(display, config, size);
    GLXContext context = glXCreateNewContext(display, config, GLX_RGBA_TYPE, NULL, True);
    if (!buffer || !context || !glXMakeContextCurrent(display, buffer, buffer, context)) return 1;
    const char *renderer = (const char *)glGetString(GL_RENDERER);
    printf("renderer=%s\n", renderer ? renderer : "unknown");
    if (!renderer || !strstr(renderer, "zink") || !strstr(renderer, "Adreno")) return 1;
    Pixmap pixmap = XCreatePixmap(display, DefaultRootWindow(display), 64, 64,
                                  DefaultDepth(display, DefaultScreen(display)));
    GC graphics = XCreateGC(display, pixmap, 0, NULL);
    const int pix_attrs[] = {GLX_TEXTURE_TARGET_EXT, GLX_TEXTURE_2D_EXT,
        GLX_TEXTURE_FORMAT_EXT, GLX_TEXTURE_FORMAT_RGB_EXT, None};
    GLXPixmap texture_pixmap = glXCreatePixmap(display, config, pixmap, pix_attrs);
    PFNGLXBINDTEXIMAGEEXTPROC bind = (PFNGLXBINDTEXIMAGEEXTPROC)glXGetProcAddressARB((const GLubyte *)"glXBindTexImageEXT");
    PFNGLXRELEASETEXIMAGEEXTPROC release = (PFNGLXRELEASETEXIMAGEEXTPROC)glXGetProcAddressARB((const GLubyte *)"glXReleaseTexImageEXT");
    if (!bind || !release) return 1;
    GLuint texture;
    glGenTextures(1, &texture);
    glBindTexture(GL_TEXTURE_2D, texture);
    for (int frame = 0; frame < 2; frame++) {
        XSetForeground(display, graphics, frame == 0 ? 0x00ff00 : 0xff0000);
        XFillRectangle(display, pixmap, graphics, 0, 0, 64, 64);
        XSync(display, False);
        bind(display, texture_pixmap, GLX_FRONT_LEFT_EXT, NULL);
        unsigned char pixels[64 * 64 * 4] = {0};
        glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
        GLenum error = glGetError();
        if (error) { fprintf(stderr, "Texture-from-pixmap GL error: 0x%x\n", error); return 1; }
        for (unsigned i = 0; i < sizeof(pixels); i++) {
            unsigned channel = i % 4;
            unsigned char expected = channel == 3 || channel == (frame == 0 ? 1u : 0u) ? 255 : 0;
            if (pixels[i] != expected) {
                fprintf(stderr, "TFP mismatch frame=%d byte=%u expected=%u actual=%u first-pixel=%u,%u,%u,%u\n",
                    frame, i, expected, pixels[i], pixels[0], pixels[1], pixels[2], pixels[3]);
                return 1;
            }
        }
        release(display, texture_pixmap, GLX_FRONT_LEFT_EXT);
    }
    puts("PASS: X11 pixmap initial pixels and update sampled through Zink texture-from-pixmap");
    glDeleteTextures(1, &texture);
    glXDestroyPixmap(display, texture_pixmap);
    XFreeGC(display, graphics);
    XFreePixmap(display, pixmap);
    glXMakeContextCurrent(display, None, None, NULL);
    glXDestroyContext(display, context);
    glXDestroyPbuffer(display, buffer);
    XFree(configs);
    XCloseDisplay(display);
    return 0;
}
