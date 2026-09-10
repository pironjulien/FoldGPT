/* Defined-content GLES3 probes for consecutive partial resolves and retained
 * stencil outside a color resolve rectangle. Every source sample read is
 * initialized; only color is invalidated, after its final relevant resolve.
 * No screenshot/readback/flush is inserted between consecutive resolves except
 * in the explicitly named control. Readback compares every destination pixel.
 *
 * Default requires native Zink/Adreno; --host-reference explicitly permits a
 * desktop reference. --size WIDTH HEIGHT changes integer framebuffer geometry.
 * FOLDGPU_PROBE_PPM_PREFIX writes failed frames as PREFIX-case-iteration.ppm.
 */
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { int x, y, w, h; } Rect;
static int width = 704, height = 928;
static Rect full, a, b;
static unsigned char *expected, *actual;
static const unsigned char black[4] = {0, 0, 0, 255};
static const unsigned char green[4] = {0, 255, 0, 255};
static const unsigned char blue[4] = {0, 0, 255, 255};
static const unsigned char yellow[4] = {255, 255, 0, 255};
static GLuint ms, dst, program;
static GLint color_uniform;
static unsigned cases, failures;

static void fail(const char *message) {
    fprintf(stderr, "ERROR: %s\n", message); exit(2);
}
static void check_gl(const char *where) {
    GLenum error = glGetError();
    if (error != GL_NO_ERROR) {
        fprintf(stderr, "ERROR: GL 0x%x at %s\n", error, where); exit(2);
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
        "void main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);"
        "gl_Position=vec4(p*2.0-1.0,0.0,1.0);}";
    const char *fs = "#version 300 es\nprecision highp float;"
        "uniform vec4 color;out vec4 frag;void main(){frag=color;}";
    GLuint v = shader(GL_VERTEX_SHADER, vs), f = shader(GL_FRAGMENT_SHADER, fs);
    program = glCreateProgram(); glAttachShader(program, v); glAttachShader(program, f);
    glLinkProgram(program); GLint ok; glGetProgramiv(program, GL_LINK_STATUS, &ok);
    if (!ok) fail("program link");
    glDeleteShader(v); glDeleteShader(f); glUseProgram(program);
    color_uniform = glGetUniformLocation(program, "color");
}
static void scissor(Rect r) {
    glEnable(GL_SCISSOR_TEST); glScissor(r.x, r.y, r.w, r.h);
}
static void clear_color(Rect r, const unsigned char rgba[4]) {
    scissor(r); glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glClearColor(rgba[0]/255.f, rgba[1]/255.f, rgba[2]/255.f, rgba[3]/255.f);
    glClear(GL_COLOR_BUFFER_BIT);
}
static void draw(Rect r, const unsigned char rgba[4]) {
    scissor(r);
    glUniform4f(color_uniform, rgba[0]/255.f, rgba[1]/255.f, rgba[2]/255.f, rgba[3]/255.f);
    glDrawArrays(GL_TRIANGLES, 0, 3);
}
static void paint_expected(Rect r, const unsigned char rgba[4]) {
    for (int y = r.y; y < r.y+r.h; y++)
        for (int x = r.x; x < r.x+r.w; x++)
            memcpy(expected + 4*((size_t)y*width+x), rgba, 4);
}
static void resolve(Rect r) {
    glDisable(GL_SCISSOR_TEST);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, ms);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, dst);
    glBlitFramebuffer(r.x, r.y, r.x+r.w, r.y+r.h,
                      r.x, r.y, r.x+r.w, r.y+r.h, GL_COLOR_BUFFER_BIT, GL_NEAREST);
}
static void invalidate_ms_color(void) {
    const GLenum attachment = GL_COLOR_ATTACHMENT0;
    glBindFramebuffer(GL_READ_FRAMEBUFFER, ms);
    glInvalidateFramebuffer(GL_READ_FRAMEBUFFER, 1, &attachment);
}
static void initialize_case(void) {
    glDisable(GL_STENCIL_TEST); glDisable(GL_BLEND); glDisable(GL_DITHER);
    glDisable(GL_DEPTH_TEST); glDisable(GL_SAMPLE_COVERAGE);
    glDisable(GL_SAMPLE_ALPHA_TO_COVERAGE);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glStencilMask(255); glStencilFunc(GL_ALWAYS, 0, 255);
    glStencilOp(GL_KEEP, GL_KEEP, GL_KEEP);
    glBindFramebuffer(GL_FRAMEBUFFER, dst);
    clear_color(full, black); paint_expected(full, black);
    glBindFramebuffer(GL_FRAMEBUFFER, ms); clear_color(full, blue);
    scissor(full); glClearStencil(0); glClear(GL_STENCIL_BUFFER_BIT);
    /* Establish known stored contents before the narrowly tested pass. */
    glFlush(); check_gl("case initialization");
}
static void verify(const char *name, int iteration) {
    glBindFramebuffer(GL_READ_FRAMEBUFFER, dst);
    glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, actual);
    check_gl(name);
    size_t wrong = 0, first = 0, pixels = (size_t)width*height;
    for (size_t i = 0; i < pixels; i++) {
        if (memcmp(actual+4*i, expected+4*i, 4)) {
            if (!wrong) first = i;
            wrong++;
        }
    }
    cases++;
    if (!wrong) {
        printf("PASS: %s iteration=%d pixels=%zu\n", name, iteration, pixels); return;
    }
    failures++;
    size_t p = 4*first;
    printf("FAIL: %s iteration=%d wrong=%zu first=(%zu,%zu) actual=%u,%u,%u,%u expected=%u,%u,%u,%u\n",
           name, iteration, wrong, first%width, first/width,
           actual[p], actual[p+1], actual[p+2], actual[p+3],
           expected[p], expected[p+1], expected[p+2], expected[p+3]);
    const char *prefix = getenv("FOLDGPU_PROBE_PPM_PREFIX");
    if (prefix) {
        char path[4096];
        int length = snprintf(path, sizeof(path), "%s-%s-%d.ppm", prefix, name, iteration);
        if (length < 0 || (size_t)length >= sizeof(path)) fail("PPM path too long");
        FILE *fp = fopen(path, "wb"); if (!fp) fail("open failure PPM");
        fprintf(fp, "P6\n%d %d\n255\n", width, height);
        for (int y=height-1; y>=0; y--)
            for (int x=0; x<width; x++)
                if (fwrite(actual+4*((size_t)y*width+x), 1, 3, fp) != 3) fail("write failure PPM");
        if (fclose(fp)) fail("close failure PPM");
    }
}
static void consecutive_resolves(int invalidate, int split, int iteration) {
    initialize_case(); draw(a, green); draw(b, yellow);
    resolve(a);
    if (split) glFlush();
    resolve(b);
    if (invalidate) invalidate_ms_color();
    paint_expected(a, green); paint_expected(b, yellow);
    const char *name = split ? "consecutive-partial-flush-control" :
        (invalidate ? "consecutive-partial-final-invalidate" : "consecutive-partial-preserve-source");
    verify(name, iteration);
}
static void retained_stencil(int full_resolve, int iteration) {
    initialize_case();
    /* A and B are disjoint. Write B's stencil with a real draw, then use that
     * preserved mask in the next pass. No stencil clear can hide its loss. */
    glEnable(GL_STENCIL_TEST); glStencilMask(255);
    glStencilFunc(GL_ALWAYS, 1, 255); glStencilOp(GL_KEEP, GL_KEEP, GL_REPLACE);
    glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE); draw(b, black);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE); glDisable(GL_STENCIL_TEST);
    draw(a, green); resolve(full_resolve ? full : a); invalidate_ms_color();
    glBindFramebuffer(GL_FRAMEBUFFER, ms);
    /* All invalidated color samples are defined again before any read. */
    clear_color(full, blue);
    glEnable(GL_STENCIL_TEST); glStencilMask(0);
    glStencilFunc(GL_EQUAL, 1, 255); glStencilOp(GL_KEEP, GL_KEEP, GL_KEEP);
    draw(full, yellow); glDisable(GL_STENCIL_TEST); glStencilMask(255);
    resolve(full); paint_expected(full, blue); paint_expected(b, yellow);
    verify(full_resolve ? "retained-stencil-full-resolve-control" : "retained-stencil-outside-partial-color-resolve", iteration);
}
static void make_framebuffers(void) {
    GLuint color, stencil, single;
    glGenFramebuffers(1, &ms); glBindFramebuffer(GL_FRAMEBUFFER, ms);
    glGenRenderbuffers(1, &color); glBindRenderbuffer(GL_RENDERBUFFER, color);
    glRenderbufferStorageMultisample(GL_RENDERBUFFER, 4, GL_RGBA8, width, height);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, color);
    glGenRenderbuffers(1, &stencil); glBindRenderbuffer(GL_RENDERBUFFER, stencil);
    glRenderbufferStorageMultisample(GL_RENDERBUFFER, 4, GL_STENCIL_INDEX8, width, height);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_STENCIL_ATTACHMENT, GL_RENDERBUFFER, stencil);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) fail("MSAA framebuffer incomplete");
    glGenFramebuffers(1, &dst); glBindFramebuffer(GL_FRAMEBUFFER, dst);
    glGenRenderbuffers(1, &single); glBindRenderbuffer(GL_RENDERBUFFER, single);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, width, height);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, single);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) fail("resolve framebuffer incomplete");
    check_gl("framebuffer setup");
}
static int dimension(const char *text) {
    char *end; errno=0; long result=strtol(text, &end, 10);
    if (errno || !*text || *end || result<64 || result>8192) fail("dimensions must be integers from 64 to 8192");
    return (int)result;
}
int main(int argc, char **argv) {
    int host = 0;
    for (int i=1; i<argc; i++) {
        if (!strcmp(argv[i], "--host-reference")) host=1;
        else if (!strcmp(argv[i], "--size") && i+2<argc) {
            width=dimension(argv[++i]); height=dimension(argv[++i]);
        } else fail("usage: probe [--host-reference] [--size WIDTH HEIGHT]");
    }
    full=(Rect){0,0,width,height};
    /* Interior, deliberately unaligned bounds exercise retained tile edges. */
    a=(Rect){1,height/4,width-width/11-1,height/7};
    b=(Rect){3,height/2+1,width-width/13-3,height/7};
    size_t bytes=(size_t)width*height*4;
    expected=malloc(bytes); actual=malloc(bytes);
    if (!expected || !actual) fail("pixel allocation");
    EGLDisplay display=eglGetDisplay(EGL_DEFAULT_DISPLAY);
    EGLint major,minor;
    if (display==EGL_NO_DISPLAY || !eglInitialize(display,&major,&minor)) fail("eglInitialize");
    if (!eglBindAPI(EGL_OPENGL_ES_API)) fail("eglBindAPI");
    const EGLint cfg[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT,
        EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_NONE};
    EGLConfig config; EGLint count;
    if (!eglChooseConfig(display,cfg,&config,1,&count) || count!=1) fail("ES3 pbuffer configuration");
    const EGLint size[]={EGL_WIDTH,1,EGL_HEIGHT,1,EGL_NONE};
    EGLSurface surface=eglCreatePbufferSurface(display,config,size);
    const EGLint version[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};
    EGLContext context=eglCreateContext(display,config,EGL_NO_CONTEXT,version);
    if (surface==EGL_NO_SURFACE || context==EGL_NO_CONTEXT || !eglMakeCurrent(display,surface,surface,context)) fail("ES3 context");
    const char *renderer=(const char *)glGetString(GL_RENDERER);
    if (!renderer) fail("missing renderer");
    printf("renderer=%s version=%s host_reference=%d size=%dx%d A=%d,%d,%d,%d B=%d,%d,%d,%d\n",
           renderer,glGetString(GL_VERSION),host,width,height,a.x,a.y,a.w,a.h,b.x,b.y,b.w,b.h);
    if (!host && (!strstr(renderer,"zink") || !strstr(renderer,"Adreno"))) fail("real Zink/Adreno required; host reference must be explicit");
    glViewport(0,0,width,height); initialize_program(); make_framebuffers();
    for (int i=0; i<4; i++) {
        consecutive_resolves(0,0,i);
        consecutive_resolves(1,0,i);
        consecutive_resolves(0,1,i);
        retained_stencil(0,i);
        retained_stencil(1,i);
    }
    printf("RESULT: cases=%u passed=%u failed=%u; each destination RGBA8 pixel compared\n",cases,cases-failures,failures);
    eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);
    eglDestroyContext(display,context); eglDestroySurface(display,surface); eglTerminate(display);
    free(expected); free(actual); return failures ? 1 : 0;
}
