#!/usr/bin/env python3
"""Replacement for the SD-only path of Orqa's Scarthgap v1.0.5 helper."""
import fcntl
import os
from pathlib import Path
import re
import subprocess
import sys


def current_source():
    result = subprocess.run(["findmnt", "-rn", "-M", "/sdcard", "-o", "SOURCE"],
                            capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise RuntimeError("cannot inspect mount table")
    return result.stdout.strip()


def handle(event):
    match = re.fullmatch(r"(mmcblk\d+(?:p\d+)?)-(mount|unmount)", event)
    if not match:
        raise ValueError("unexpected SD device/event")
    name, action = match.groups()
    device = "/dev/" + name
    source = current_source()
    if action == "unmount":
        # Device may have disappeared from sysfs. Only unmount its exact mount.
        if source == device:
            subprocess.run(["systemd-umount", "--collect", "/sdcard"], check=True, timeout=15)
        return
    base = re.sub(r"p\d+$", "", name)
    if Path("/sys/class/block", base, "device/type").read_text().strip() != "SD":
        raise ValueError("refusing non-SD device (including eMMC)")
    if source:
        if source != device:
            raise RuntimeError("/sdcard is already occupied by a different device")
        return
    mount = Path("/sdcard")
    if mount.is_symlink():
        raise ValueError("refusing symlinked /sdcard")
    mount.mkdir(exist_ok=True)
    # Synchronous job completion, no success marker or lazy unmount. The
    # recorder fsyncs its log periodically; sync-at-every-write is unnecessary.
    subprocess.run(["systemd-mount", "--collect", "--options=nosuid,nodev,noexec",
                    device, "/sdcard"], check=True, timeout=15)
    if current_source() != device:
        raise RuntimeError("mount command completed without the expected mount")


def main():
    if len(sys.argv) != 2:
        raise ValueError("expected mmcblkN[pN]-mount|unmount")
    with open("/run/orqa-sd-mount.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        handle(sys.argv[1])


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print("Orqa SD: " + str(error), file=sys.stderr)
        raise SystemExit(1)
