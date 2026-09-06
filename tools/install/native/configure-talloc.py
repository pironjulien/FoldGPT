"""Compile/link-only feature checks for talloc 2.4.3 against the Android NDK.

No target program is executed, and no runtime test result is fabricated. The
one runtime semantic contract (Bionic's C99 vsnprintf) is identified separately.
All test sources, compiler diagnostics and results are retained in the build.
"""
import argparse
import json
from pathlib import Path
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--cc", required=True)
p.add_argument("--out", type=Path, required=True)
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=False)
results = {}
definitions = {"TALLOC_BUILD_VERSION_MAJOR": 2, "TALLOC_BUILD_VERSION_MINOR": 4,
               "TALLOC_BUILD_VERSION_RELEASE": 3}
base = [a.cc, "-D_GNU_SOURCE", "-D__STDC_WANT_LIB_EXT1__=1", "-Werror", "-std=gnu11"]


def check(macro, source):
    path = a.out / (macro + ".c")
    path.write_text(source + "\n")
    command = base + [str(path), "-o", str(a.out / (macro + ".elf"))]
    r = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (a.out / (macro + ".log")).write_text(r.stdout)
    results[macro] = {"compile_link": r.returncode == 0, "command": command}
    if r.returncode == 0:
        definitions[macro] = 1


headers = ["unistd.h", "string.h", "strings.h", "sys/types.h", "sys/sysmacros.h",
           "stdint.h", "inttypes.h", "stdbool.h", "limits.h", "sys/param.h", "malloc.h",
           "sys/auxv.h", "dlfcn.h", "linux/types.h"]
for h in headers:
    check("HAVE_" + h.upper().replace("/", "_").replace(".", "_"), f"#include <{h}>\nint main(void) {{ return 0; }}")
includes = "".join(f"#include <{h}>\n" for h in headers + ["stdio.h", "stdlib.h", "stddef.h", "stdarg.h", "errno.h", "time.h", "sys/time.h", "sys/socket.h", "syslog.h", "grp.h", "ifaddrs.h", "arpa/inet.h", "netdb.h", "poll.h", "utime.h"])
functions = "strerror strdup memmove memmem memalign mktime timegm utime utimes strlcpy strlcat strndup strnlen setenv unsetenv seteuid setegid chown chroot link readlink symlink getifaddrs freeifaddrs get_current_dir_name clock_gettime asprintf vasprintf snprintf vsnprintf dprintf vdprintf vsyslog syslog strsep strtok_r strtoll strtoull strcasestr dup2 ftruncate pread pwrite realpath usleep socketpair connect gethostbyname inet_aton inet_ntoa inet_ntop inet_pton initgroups setlinebuf dlopen dlsym dlclose dlerror poll mkdtemp getauxval".split()
for name in functions:
    check("HAVE_" + name.upper(), includes + f"static __typeof__(&{name}) volatile reference = &{name};\nint main(void) {{ return reference == 0; }}")
for macro, typename in {"HAVE_BOOL": "bool", "HAVE_INTPTR_T": "intptr_t", "HAVE_UINTPTR_T": "uintptr_t", "HAVE_PTRDIFF_T": "ptrdiff_t"}.items():
    check(macro, includes + f"_Static_assert(sizeof({typename}) > 0, \"type\"); int main(void) {{ return 0; }}")
check("HAVE_ERRNO_DECL", includes + "int main(void) { return errno; }")
check("HAVE_DECL_EWOULDBLOCK", includes + "int main(void) { return EWOULDBLOCK; }")
check("HAVE_DECL_ENVIRON", includes + "int main(void) { return environ == 0; }")
check("HAVE_SETENV_DECL", includes + "int main(void) { return setenv(\"a\",\"b\",0); }")
check("HAVE_VOLATILE", "int main(void) { volatile int value = 0; return value; }")
check("HAVE_FUNCTION_MACRO", "int main(void) { return __FUNCTION__[0]; }")
check("HAVE_VA_COPY", includes + "static void f(int n, ...) { va_list a,b; va_start(a,n); va_copy(b,a); va_end(b); va_end(a); } int main(void) { f(0); return 0; }")
for macro, attribute in (("HAVE_CONSTRUCTOR_ATTRIBUTE", "constructor"), ("HAVE_VISIBILITY_ATTR", "visibility")):
    check(macro, f"#if !__has_attribute({attribute})\n#error Required compiler attribute unavailable\n#endif\nint main(void) {{ return 0; }}")
check("STDC_HEADERS", "#include <stdlib.h>\n#include <stddef.h>\nint main(void) { return sizeof(size_t)==0; }")

required = ["HAVE_SYS_AUXV_H", "HAVE_GETAUXVAL", "HAVE_CONSTRUCTOR_ATTRIBUTE", "HAVE_VISIBILITY_ATTR",
            "HAVE_BOOL", "HAVE_INTPTR_T", "HAVE_UINTPTR_T", "HAVE_PTRDIFF_T", "HAVE_VA_COPY",
            "HAVE_MEMMOVE", "HAVE_STRDUP", "HAVE_STRNDUP", "HAVE_SNPRINTF", "HAVE_VSNPRINTF", "HAVE_ERRNO_DECL"]
for macro in required:
    if macro not in definitions:
        raise SystemExit(f"Required NDK compile/link feature unavailable: {macro}; see its retained log")

# Android API 30's Bionic snprintf/vsnprintf implement C99 return semantics.
# This is an Android libc interface contract, NOT a target-runtime test pass.
definitions["HAVE_C99_VSNPRINTF"] = 1
results["HAVE_C99_VSNPRINTF"] = {"platform_contract": "Android API 30 Bionic C99 snprintf/vsnprintf semantics", "runtime_tested": False}
(a.out / "config.h").write_text("/* Generated from NDK compile/link checks and the recorded Bionic contract. */\n" + "".join(f"#define {k} {v}\n" for k,v in sorted(definitions.items())))
(a.out / "feature-checks.json").write_text(json.dumps(results, indent=2) + "\n")
print(f"talloc: {sum('compile_link' in r and r['compile_link'] for r in results.values())} compile/link checks passed; zero target programs executed")
