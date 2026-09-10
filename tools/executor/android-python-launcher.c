/* Embed the intact official CPython Android runtime in an APK-owned process.
 * This is a trusted interpreter launcher, not a sandbox or command executor.
 */
#define _POSIX_C_SOURCE 200809L
#include <Python.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int bind_stream(const char *name, const char *original, int fd,
                       const char *mode, const char *errors)
{
    PyObject *stream = PyFile_FromFd(fd, name, mode, fd == 0 ? -1 : 1,
                                   "utf-8", errors, NULL, 0);
    if (stream == NULL) return -1;
    int result = PySys_SetObject(name, stream);
    if (result == 0) result = PySys_SetObject(original, stream);
    Py_DECREF(stream);
    return result;
}

int main(int argc, char **argv)
{
    if (argc < 5 || strcmp(argv[1], "--home") != 0 || argv[2][0] != '/' ||
        strcmp(argv[3], "--") != 0 || argv[4][0] == '\0') {
        fprintf(stderr, "Usage: %s --home ABSOLUTE_PREFIX -- SCRIPT [args ...]\n", argv[0]);
        return 64;
    }
    char executable[PATH_MAX];
    ssize_t size = readlink("/proc/self/exe", executable, sizeof executable - 1);
    if (size < 0 || (size_t)size == sizeof executable - 1) {
        fprintf(stderr, "Cannot resolve the APK-owned interpreter: %s\n",
                size < 0 ? strerror(errno) : "executable path too long");
        return 71;
    }
    executable[size] = '\0';

    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.parse_argv = 0;
    config.site_import = 0;
    config.write_bytecode = 0;
    config.install_signal_handlers = 1;
    /* SCRIPT is sys.argv[0]; none of its arguments are parsed as Python flags. */
    PyStatus status = PyConfig_SetBytesArgv(&config, argc - 4, argv + 4);
    if (!PyStatus_Exception(status))
        status = PyConfig_SetBytesString(&config, &config.home, argv[2]);
    if (!PyStatus_Exception(status))
        status = PyConfig_SetBytesString(&config, &config.executable, executable);
    if (!PyStatus_Exception(status))
        status = PyConfig_SetBytesString(&config, &config.program_name, executable);
    if (!PyStatus_Exception(status))
        status = PyConfig_SetBytesString(&config, &config.run_filename, argv[4]);
    if (!PyStatus_Exception(status)) status = Py_InitializeFromConfig(&config);
    if (PyStatus_Exception(status)) {
        fprintf(stderr, "Python initialization failed: %s\n",
                status.err_msg ? status.err_msg : "initialization requested exit");
        int result = PyStatus_IsExit(status) ? status.exitcode : 70;
        PyConfig_Clear(&config);
        return result;
    }
    PyConfig_Clear(&config);

    /* Keep binary .buffer I/O available for RPC. These wrappers do not own the
     * inherited descriptors. No user/site module or environment sets streams.
     */
    if (bind_stream("stdin", "__stdin__", STDIN_FILENO, "r", "surrogateescape") < 0 ||
        bind_stream("stdout", "__stdout__", STDOUT_FILENO, "w", "surrogateescape") < 0 ||
        bind_stream("stderr", "__stderr__", STDERR_FILENO, "w", "backslashreplace") < 0) {
        PyErr_Print();
        (void)Py_FinalizeEx();
        return 74;
    }
    return Py_RunMain();
}
