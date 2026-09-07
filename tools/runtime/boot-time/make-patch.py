"""Generate the reviewable patch against the exact authenticated Debian source.

Refuses unknown output.c; never edits the source input directory.
"""
import argparse
import difflib
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OLD = '''static unsigned int boot_time(void)
{
    static unsigned int boot_time = 0;
    struct stat_info *stat_info = NULL;
    if (boot_time == 0) {
        if (procps_stat_new(&stat_info) < 0)
             xerrx(EXIT_FAILURE, _("Unable to get system boot time"));
        boot_time = STAT_GET(stat_info, STAT_SYS_TIME_OF_BOOT, ul_int);
        procps_stat_unref(&stat_info);
    }
    return boot_time;
}
'''
NEW = '''static time_t boot_time(void)
{
    static time_t cached_boot_time;
    static int have_boot_time;
    struct stat_info *stat_info = NULL;
    int rc;

    if (have_boot_time)
        return cached_boot_time;
    rc = procps_stat_new(&stat_info);
    if (rc == 0) {
        struct stat_result *result = procps_stat_get(stat_info, STAT_SYS_TIME_OF_BOOT);
        if (result) {
            cached_boot_time = result->result.ul_int;
            have_boot_time = 1;
        } else {
            rc = -errno;
        }
        procps_stat_unref(&stat_info);
    }
    if (!have_boot_time && (rc == -EACCES || rc == -EPERM || rc == -ENOENT)) {
        if (procps_boot_time_from_clocks(&cached_boot_time) == 0)
            have_boot_time = 1;
    }
    if (!have_boot_time)
        xerrx(EXIT_FAILURE, _("Unable to get system boot time"));
    return cached_boot_time;
}
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    args = parser.parse_args()
    source = args.source
    output = (source/"src/ps/output.c").read_text()
    expected = (ROOT/"output-source.sha256").read_text().strip()
    if hashlib.sha256(output.encode()).hexdigest() != expected:
        raise ValueError("Unknown procps output.c; audit this version first")
    if output.count(OLD) != 1:
        raise ValueError("boot_time source differs")
    patched = output.replace('#include "common.h"', '#include "common.h"\n#include "boot-time.h"').replace(OLD,NEW)
    makefile = (source/"Makefile.am").read_text()
    marker = "src_ps_pscommand_SOURCES =  \\\n"
    if makefile.count(marker) != 1:
        raise ValueError("Unknown ps build declaration")
    new_makefile = makefile.replace(marker,marker+"\tsrc/ps/boot-time.h \\\n")
    patch = "".join(difflib.unified_diff(makefile.splitlines(True),new_makefile.splitlines(True),fromfile="a/Makefile.am",tofile="b/Makefile.am"))
    patch += "".join(difflib.unified_diff(output.splitlines(True),patched.splitlines(True),fromfile="a/src/ps/output.c",tofile="b/src/ps/output.c"))
    patch += "".join(difflib.unified_diff([], (ROOT/"boot-time.h").read_text().splitlines(True),fromfile="/dev/null",tofile="b/src/ps/boot-time.h"))
    (ROOT/"procps-4.0.4-9-boot-time.patch").write_text(patch,newline="\n")

if __name__ == "__main__":
    main()
