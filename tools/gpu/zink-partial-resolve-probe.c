/* Defined-content GLES3 regression probe for partial MSAA resolves/invalidation.
 * No sample from an invalidated region is read before a clear or opaque draw
 * has defined every sample in that region. Use --host-reference only to allow
 * software rendering; the default requires the real Zink/Adreno device path.
 */
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { W = 704, H = 928 };
typedef struct { int x, y, w, h; } Rect;
static const Rect full = {0, 0, W, H};
static const Rect a = {0, 232, 641, 149};
static const Rect b = {0, 500, 641, 149};
static const Rect overlap = {0, 314, 641, 149};
static const Rect c = {8, 8, 80, 40};
static const unsigned char black[4] = {0, 0, 0, 255};
static const unsigned char green[4] = {0, 255, 0, 255};
static const unsigned char blue[4] = {0, 0, 255, 255};
static const unsigned char yellow[4] = {255, 255, 0, 255};
static const unsigned char white[4] = {255, 255, 255, 255};
static unsigned char expected[W * H * 4], actual[W * H * 4];
static GLuint ms, dst, program;
static GLint color_uniform, clip_uniform;
static unsigned cases;

static void fail(const char *message) { fprintf(stderr, "FAIL: %s\n", message); exit(1); }
static void check_gl(const char *where) {
    GLenum error = glGetError();
    if (error != GL_NO_ERROR) {
        fprintf(stderr, "FAIL: GL error 0x%x at %s\n", error, where); exit(1);
    }
}
static GLuint shader(GLenum type, const char *source) {
    GLuint object = glCreateShader(type);
    glShaderSource(object, 1, &source, NULL); glCompileShader(object);
    GLint ok; glGetShaderiv(object, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[4096]; glGetShaderInfoLog(object, sizeof(log), NULL, log); fail(log); }
    return object;
}
static void initialize_program(void) {
    const char *vs = "#version 300 es\n"
        "void main() { vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);"
        "gl_Position=vec4(p*2.0-1.0,0.0,1.0); }";
    const char *fs = "#version 300 es\nprecision highp float;"
        "uniform vec4 color; uniform vec4 clip; out vec4 frag; void main(){"
        "if(any(lessThan(gl_FragCoord.xy,clip.xy))||any(greaterThanEqual(gl_FragCoord.xy,clip.zw)))discard;"
        "frag=color;}";
    GLuint v = shader(GL_VERTEX_SHADER, vs), f = shader(GL_FRAGMENT_SHADER, fs);
    program = glCreateProgram(); glAttachShader(program, v); glAttachShader(program, f);
    glLinkProgram(program); GLint ok; glGetProgramiv(program, GL_LINK_STATUS, &ok);
    if (!ok) fail("program link");
    glDeleteShader(v); glDeleteShader(f); glUseProgram(program);
    color_uniform = glGetUniformLocation(program, "color");
    clip_uniform = glGetUniformLocation(program, "clip");
}
static void bind_ms(void) { glBindFramebuffer(GL_FRAMEBUFFER, ms); }
static void scissor(Rect r) { glEnable(GL_SCISSOR_TEST); glScissor(r.x, r.y, r.w, r.h); }
static void clear_color(Rect r, const unsigned char rgba[4]) {
    scissor(r); glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glClearColor(rgba[0]/255.f, rgba[1]/255.f, rgba[2]/255.f, rgba[3]/255.f);
    glClear(GL_COLOR_BUFFER_BIT);
}
static void draw(Rect r, const unsigned char rgba[4]) {
    scissor(r); glUniform4f(color_uniform, rgba[0]/255.f, rgba[1]/255.f, rgba[2]/255.f, rgba[3]/255.f);
    glUniform4f(clip_uniform, (float)r.x, (float)r.y, (float)(r.x+r.w), (float)(r.y+r.h));
    glDrawArrays(GL_TRIANGLES, 0, 3);
}
static void paint_expected(Rect r, const unsigned char rgba[4]) {
    for (int y = r.y; y < r.y+r.h; y++)
        for (int x = r.x; x < r.x+r.w; x++)
            memcpy(expected + 4*(y*W+x), rgba, 4);
}
static void resolve(Rect r) {
    glDisable(GL_SCISSOR_TEST);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, ms); glBindFramebuffer(GL_DRAW_FRAMEBUFFER, dst);
    glBlitFramebuffer(r.x, r.y, r.x+r.w, r.y+r.h,
                      r.x, r.y, r.x+r.w, r.y+r.h, GL_COLOR_BUFFER_BIT, GL_NEAREST);
    check_gl("resolve");
}
static void invalidate_ms_color(void) {
    const GLenum attachment = GL_COLOR_ATTACHMENT0;
    glBindFramebuffer(GL_READ_FRAMEBUFFER, ms);
    glInvalidateFramebuffer(GL_READ_FRAMEBUFFER, 1, &attachment);
}
static void clear_stencil(Rect r) {
    scissor(r); glStencilMask(255); glClearStencil(1); glClear(GL_STENCIL_BUFFER_BIT);
}
static void stencil_draw(Rect r, const unsigned char rgba[4]) {
    clear_stencil(r);
    glEnable(GL_STENCIL_TEST); glStencilFunc(GL_EQUAL, 1, 255);
    glStencilOp(GL_KEEP, GL_KEEP, GL_KEEP); glStencilMask(0);
    for (int draw_index=0; draw_index<9; draw_index++) draw(r, rgba);
    glDisable(GL_STENCIL_TEST); glStencilMask(255);
}
static void init_case(void) {
    glDisable(GL_STENCIL_TEST); glDisable(GL_BLEND); glDisable(GL_DITHER);
    glDisable(GL_DEPTH_TEST); glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glBindFramebuffer(GL_FRAMEBUFFER, dst); clear_color(full, black); paint_expected(full, black);
    bind_ms(); clear_color(full, blue); clear_stencil(full);
}
static void verify(const char *name, int iteration) {
    glBindFramebuffer(GL_READ_FRAMEBUFFER, dst);
    glReadPixels(0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE, actual);
    check_gl(name);
    unsigned wrong = 0; int first = -1;
    for (int i = 0; i < W*H; i++) {
        if (memcmp(actual + 4*i, expected + 4*i, 4)) {
            if (first < 0) first = i;
            wrong++;
        }
    }
    if (wrong) {
        int i = first * 4;
        fprintf(stderr, "FAIL: %s iteration=%d wrong=%u first=(%d,%d) actual=%u,%u,%u,%u expected=%u,%u,%u,%u\n",
                name, iteration, wrong, first%W, first/W, actual[i], actual[i+1], actual[i+2], actual[i+3],
                expected[i], expected[i+1], expected[i+2], expected[i+3]);
        const char *path = getenv("FOLDGPU_PROBE_PPM");
        if (path) {
            FILE *fp = fopen(path, "wb");
            if (fp) { fprintf(fp, "P6\n%d %d\n255\n", W, H);
                for (int y=H-1; y>=0; y--) for(int x=0;x<W;x++) fwrite(actual+4*(y*W+x),1,3,fp);
                fclose(fp); }
        }
        exit(1);
    }
    cases++;
    printf("PASS: %s iteration=%d\n", name, iteration);
}
static void make_framebuffers(void) {
    GLuint color, stencil, single;
    glGenFramebuffers(1, &ms); glBindFramebuffer(GL_FRAMEBUFFER, ms);
    glGenRenderbuffers(1, &color); glBindRenderbuffer(GL_RENDERBUFFER, color);
    glRenderbufferStorageMultisample(GL_RENDERBUFFER, 4, GL_RGBA8, W, H);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, color);
    glGenRenderbuffers(1, &stencil); glBindRenderbuffer(GL_RENDERBUFFER, stencil);
    glRenderbufferStorageMultisample(GL_RENDERBUFFER, 4, GL_STENCIL_INDEX8, W, H);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_STENCIL_ATTACHMENT, GL_RENDERBUFFER, stencil);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) fail("MSAA framebuffer incomplete");
    glGenFramebuffers(1, &dst); glBindFramebuffer(GL_FRAMEBUFFER, dst);
    glGenRenderbuffers(1, &single); glBindRenderbuffer(GL_RENDERBUFFER, single);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, W, H);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, single);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) fail("resolve framebuffer incomplete");
    check_gl("framebuffer setup");
}
int main(int argc, char **argv) {
    int host = argc == 2 && !strcmp(argv[1], "--host-reference");
    if (argc > 1 && !host) fail("only optional argument is --host-reference");
    EGLDisplay display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    EGLint major, minor;
    if (display == EGL_NO_DISPLAY || !eglInitialize(display, &major, &minor)) fail("eglInitialize");
    if (!eglBindAPI(EGL_OPENGL_ES_API)) fail("eglBindAPI");
    const EGLint cfg[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE};
    EGLConfig config; EGLint count;
    if (!eglChooseConfig(display, cfg, &config, 1, &count) || count != 1) fail("EGL ES3 pbuffer configuration");
    const EGLint size[] = {EGL_WIDTH, 1, EGL_HEIGHT, 1, EGL_NONE};
    EGLSurface surface = eglCreatePbufferSurface(display, config, size);
    const EGLint version[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
    EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, version);
    if (surface == EGL_NO_SURFACE || context == EGL_NO_CONTEXT || !eglMakeCurrent(display,surface,surface,context)) fail("ES3 context");
    const char *renderer = (const char *)glGetString(GL_RENDERER);
    printf("renderer=%s version=%s host_reference=%d\n", renderer, glGetString(GL_VERSION), host);
    if (!host && (!strstr(renderer, "zink") || !strstr(renderer, "Adreno"))) fail("real Zink/Adreno required (host reference must be explicit)");
    glViewport(0, 0, W, H); initialize_program(); make_framebuffers();
    for (int i=0; i<4; i++) {
        /* All invalidated samples are redefined in B before its resolve.
         * Destination contents outside each resolve must remain untouched. */
        init_case(); draw(a, green); resolve(a); paint_expected(a, green); invalidate_ms_color();
        bind_ms(); clear_color(b, blue); stencil_draw(b, yellow); resolve(b); paint_expected(b, yellow); invalidate_ms_color();
        verify("invalidate-partial-redefine-disjoint", i);

        init_case(); draw(a, green); resolve(a); paint_expected(a, green); invalidate_ms_color();
        bind_ms(); clear_color(overlap, blue); stencil_draw(overlap, yellow); resolve(overlap); paint_expected(overlap, yellow); invalidate_ms_color();
        verify("invalidate-partial-redefine-overlap", i);

        /* First command of the next renderpass is an opaque draw. This must
         * use the new TC metadata, even though the preceding pass invalidates.
         * Stencil is already defined everywhere; no deferred clear precedes it.
         * The API temporarily binds dst for blit, but Mesa blit does not emit
         * set_framebuffer_state. Returning to ms therefore retains the same
         * Gallium framebuffer for the next draw. */
        init_case(); draw(a, green); resolve(a); paint_expected(a, green); invalidate_ms_color();
        bind_ms(); draw(overlap, blue); stencil_draw(overlap, yellow);
        resolve(overlap); paint_expected(overlap, yellow); invalidate_ms_color();
        verify("invalidate-first-draw-overlap", i);

        /* After the invalidate, the entire MSAA image is defined by an opaque
         * draw. A later renderpass split must load those valid color samples. */
        init_case(); draw(a, green); resolve(a); invalidate_ms_color();
        bind_ms(); draw(full, blue); glFlush(); stencil_draw(b, yellow); glFlush(); draw(c, white);
        resolve(full); paint_expected(full, blue); paint_expected(b, yellow); paint_expected(c, white);
        verify("invalidate-full-draw-flush-stencil", i);

        /* Clear after partial resolve must not inherit the old renderArea. */
        init_case(); draw(a, green); resolve(a); invalidate_ms_color();
        bind_ms(); clear_color(full, blue); stencil_draw(b, yellow); glFlush(); draw(c, white);
        resolve(full); paint_expected(full, blue); paint_expected(b, yellow); paint_expected(c, white);
        verify("invalidate-full-clear-flush-stencil", i);

        /* No invalidate: source pixels outside later draws must be preserved. */
        init_case(); draw(a, green); resolve(a);
        bind_ms(); stencil_draw(b, yellow); glFlush(); draw(c, white); resolve(full);
        paint_expected(full, blue); paint_expected(a, green); paint_expected(b, yellow); paint_expected(c, white);
        verify("preserve-msaa-after-partial-resolve", i);
    }
    printf("PASS: %u defined-content cases; every RGBA8 pixel matched\n", cases);
    eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroyContext(display, context); eglDestroySurface(display, surface); eglTerminate(display);
    return 0;
}
