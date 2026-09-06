"""Read KGSL device properties using the same public uAPI as Mesa Turnip.

Run on the host with --serial. Does not create a GPU context or submit commands.
"""
import argparse
from pathlib import Path
import subprocess
import sys

GUEST_CODE = r'''
import ctypes as c
import os
import time

if c.sizeof(c.c_void_p) != 8:
    raise SystemExit("This probe expects the verified ARM64 guest")

class DeviceInfo(c.Structure):
    _fields_ = [("device_id", c.c_uint), ("chip_id", c.c_uint),
                ("mmu_enabled", c.c_uint), ("gmem_gpubaseaddr", c.c_ulong),
                ("gpu_id", c.c_uint), ("gmem_sizebytes", c.c_size_t)]

class Property(c.Structure):
    _fields_ = [("type", c.c_uint), ("value", c.c_void_p), ("sizebytes", c.c_size_t)]

class Counter(c.Structure):
    _fields_ = [("groupid", c.c_uint), ("countable", c.c_uint), ("value", c.c_uint64)]

class CounterRead(c.Structure):
    _fields_ = [("reads", c.c_void_p), ("count", c.c_uint), ("pad", c.c_uint * 2)]

libc = c.CDLL(None, use_errno=True)
libc.ioctl.argtypes = [c.c_int, c.c_ulong, c.c_void_p]
libc.ioctl.restype = c.c_int
request = (3 << 30) | (c.sizeof(Property) << 16) | (0x09 << 8) | 0x02
fd = os.open("/dev/kgsl-3d0", os.O_RDWR | os.O_CLOEXEC)
failed = False
try:
    for name, prop_id, value in [
        ("DEVICE_INFO", 0x01, DeviceInfo()),
        ("UCHE_GMEM_VADDR", 0x13, c.c_uint64()),
        ("HIGHEST_BANK_BIT", 0x17, c.c_uint32()),
        ("UBWC_MODE", 0x1B, c.c_uint32()),
    ]:
        prop = Property(prop_id, c.addressof(value), c.sizeof(value))
        result = libc.ioctl(fd, request, c.byref(prop))
        if result:
            failed = True
            error = c.get_errno()
            print(name, "FAILED", error, os.strerror(error))
        elif isinstance(value, DeviceInfo):
            print(name, "chip_id=" + hex(value.chip_id), "gpu_id=" + str(value.gpu_id),
                  "gmem_sizebytes=" + str(value.gmem_sizebytes))
        else:
            print(name, hex(value.value))
    counter = Counter(0x1B, 0, 0)  # Public KGSL_PERFCOUNTER_GROUP_ALWAYSON.
    counters = CounterRead(c.addressof(counter), 1, (c.c_uint * 2)())
    read_request = (3 << 30) | (c.sizeof(CounterRead) << 16) | (0x09 << 8) | 0x3B
    for sample in range(2):
        before = time.monotonic_ns()
        result = libc.ioctl(fd, read_request, c.byref(counters))
        after = time.monotonic_ns()
        if result:
            error = c.get_errno()
            print("ALWAYSON_COUNTER", "FAILED", error, os.strerror(error))
            failed = True
            break
        print("ALWAYSON_COUNTER", "sample=" + str(sample), "ticks=" + str(counter.value),
              "cpu_before_ns=" + str(before), "cpu_after_ns=" + str(after))
finally:
    os.close(fd)
raise SystemExit(1 if failed else 0)
'''

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    args = parser.parse_args()
    helper = Path(__file__).resolve().parents[1] / "device-shell.py"
    raise SystemExit(subprocess.call([sys.executable, str(helper), "--serial", args.serial,
                                     "/usr/bin/python3", "-c", GUEST_CODE]))
