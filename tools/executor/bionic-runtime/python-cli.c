/* SPDX-License-Identifier: GPL-3.0-only
 * CLI entry point for the official CPython Android shared library.
 * This is an interpreter, not a sandbox. The parent must establish the complete
 * managed policy before executing it. No PRoot, ptrace or custom ELF loader.
 * PYTHONHOME follows CPython's ordinary CLI semantics. An explicit build-time
 * base home also works with -I/-E and subprocess(env={}); it is a deployment
 * input, not a security grant. The parent must admit that runtime separately.
 */
#define _POSIX_C_SOURCE 200809L
#include <Python.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <wchar.h>
#ifndef FOLDGPT_PYTHON_HOME
#error "Build with the actual application Python deployment prefix"
#endif

static int explicit_pycache_prefix(const PyConfig *config) {
    const wchar_t *name = L"pycache_prefix";
    size_t length = wcslen(name);
    for (Py_ssize_t i = 0; i < config->xoptions.length; ++i) {
        const wchar_t *option = config->xoptions.items[i];
        if (wcsncmp(option, name, length) == 0 &&
                (option[length] == L'\0' || option[length] == L'='))
            return 1;
    }
    return 0;
}

int main(int argc, char **argv) {
    char executable[PATH_MAX];
    ssize_t count = readlink("/proc/self/exe", executable, sizeof executable - 1);
    if (count < 0 || (size_t)count == sizeof executable - 1) {
        fprintf(stderr, "Cannot resolve interpreter: %s\n",
                count < 0 ? strerror(errno) : "path too long");
        return 71;
    }
    executable[count] = '\0';
    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    PyStatus status = PyConfig_SetBytesArgv(&config, argc, argv);
    if (!PyStatus_Exception(status))
        status = PyConfig_SetBytesString(&config, &config.executable, executable);
    if (!PyStatus_Exception(status))
        status = PyConfig_SetBytesString(&config, &config.program_name, executable);
    if (!PyStatus_Exception(status)) status = PyConfig_Read(&config);
    if (!PyStatus_Exception(status) && config.home == NULL) {
        /* PyConfig_Read parses -I/-E but does not finish path initialization
         * on modern CPython. Setting home now would otherwise override a
         * permitted PYTHONHOME before getpath has had a chance to read it. */
        const char *home = config.use_environment ? getenv("PYTHONHOME") : NULL;
        if (home == NULL || *home == '\0') home = FOLDGPT_PYTHON_HOME;
        status = PyConfig_SetBytesString(&config, &config.home, home);
    }
    if (!PyStatus_Exception(status) && config.pycache_prefix == NULL &&
            !explicit_pycache_prefix(&config)) {
        /* Read first so CPython applies -X, PYTHONPYCACHEPREFIX and -I/-E.
         * Preserve an explicit empty -X value as well as a configured path.
         * The deployment sibling keeps normal bytecode caching outside the
         * admitted Python tree, even with an empty subprocess environment.
         * It is a writable cache, never part of the trusted runtime inventory. */
        status = PyConfig_SetBytesString(&config, &config.pycache_prefix,
                                        FOLDGPT_PYTHON_HOME "-cache");
    }
    if (!PyStatus_Exception(status)) status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) Py_ExitStatusException(status);
    /* Standard CPython handles -c, -m, script, stdin, flags and sys.executable.
     * Android's _android_support.init_streams retains real standard streams
     * when sys.executable is set, so no replacement logging/IO is needed. */
    return Py_RunMain();
}
