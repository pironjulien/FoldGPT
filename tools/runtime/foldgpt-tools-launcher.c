/* APK-owned entrypoint for app-private scripts; Android never executes a
 * writable script as an ELF. No privileges or resident process are added. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

extern char **environ;

int main(int argc, char **argv) {
    static const char *names[] = {"foldgpt", "git", "make", "node", "npm", "npx",
                                  "gcc", "g++", "diff", "tar", "gzip", "xz",
                                  "workspace-node", "workspace-python3", "pnpm", "pdftoppm", "pdftotext",
                                  "pdfinfo", "libreoffice", "soffice", "heif-convert", "JxrDecApp"};
    const char *name = strrchr(argv[0], '/');
    name = name ? name + 1 : argv[0];
    int known = 0;
    for (size_t i = 0; i < sizeof names / sizeof names[0]; ++i)
        if (strcmp(name, names[i]) == 0) known = 1;
    if (!known || getuid() == 0) {
        fputs("foldgpt: use an installed command under the ordinary application UID\n", stderr);
        return 64;
    }
    char executable[PATH_MAX], python[PATH_MAX], script[PATH_MAX];
    ssize_t n = readlink("/proc/self/exe", executable, sizeof executable - 1);
    if (n < 0 || (size_t)n >= sizeof executable - 1) return 71;
    executable[n] = '\0';
    char *slash = strrchr(executable, '/');
    if (!slash || strncmp(executable, "/data/app/", 10) != 0) return 71;
    *slash = '\0';
    int size = snprintf(python, sizeof python, "%s/libfoldgpt_python_cli.so", executable);
    if (size < 0 || (size_t)size >= sizeof python) return 71;
    /* Android's per-user UID range is 100000; package identity is fixed by APK. */
    size = snprintf(script, sizeof script,
        "/data/user/%u/app.foldgpt/files/foldgpt-tools/foldgpt_tools.py", (unsigned)getuid() / 100000);
    if (size < 0 || (size_t)size >= sizeof script) return 71;
    char **arguments = calloc((size_t)argc + 6, sizeof *arguments);
    if (!arguments) return 71;
    int next = 0;
    arguments[next++] = python;
    arguments[next++] = "-I";
    arguments[next++] = "-B";
    arguments[next++] = script;
    if (strcmp(name, "foldgpt") != 0) arguments[next++] = (char *)name;
    for (int i = 1; i < argc; ++i) arguments[next++] = argv[i];
    arguments[next] = NULL;
    execve(python, arguments, environ);
    int error = errno;
    fprintf(stderr, "foldgpt: cannot start native Python: %s\n", strerror(error));
    free(arguments);
    return error == ENOENT ? 127 : 126;
}
