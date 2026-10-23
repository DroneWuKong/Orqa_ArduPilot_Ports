"""SD-only durable storage. No formatting, automatic deletion or rootfs fallback."""
import fcntl
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid


class NotReady(RuntimeError):
    pass


def mount_record(text, path):
    result = None
    for line in text.splitlines():
        left, right = line.split(" - ", 1)
        fields, extra = left.split(), right.split()
        name = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[4])
        if name == str(path):
            if "rw" not in fields[5].split(",") or "rw" not in extra[2].split(","):
                raise NotReady("SD mount is read-only")
            result = (fields[0], fields[2])
    if result is None:
        raise NotReady("SD is not mounted; refusing root filesystem fallback")
    return result


def card_identity(path):
    path = Path(path)
    if not path.is_absolute() or path == Path("/") or path.resolve() != path or path.is_symlink():
        raise NotReady("use a dedicated absolute SD mount without symlinks")
    identity = mount_record(Path("/proc/self/mountinfo").read_text(), path)
    device = Path("/sys/dev/block", identity[1]).resolve(strict=True)
    if (device / "partition").exists():
        device = device.parent
    if (device / "device/type").read_text().strip() != "SD":
        raise NotReady("mounted device is not SD; eMMC/root rejected")
    return identity


def check_space(fd, reserve, upcoming=0):
    fs = os.fstatvfs(fd)
    if fs.f_flag & os.ST_RDONLY:
        raise NotReady("SD became read-only")
    if fs.f_bavail * fs.f_frsize < reserve + upcoming:
        raise NotReady("SD space below reserve; existing logs will not be deleted")


def rename_new(directory, source, destination):
    # Linux renameat2(RENAME_NOREPLACE) supports FAT/exFAT without hard links.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(directory, os.fsencode(source), directory, os.fsencode(destination), 1):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


class Store:
    def __init__(self, mount, family, role, reserve=256*1024*1024):
        if family not in ("ardupilot", "betaflight") or role not in ("archive", "live") or reserve < 0:
            raise ValueError("invalid storage settings")
        self.mount, self.reserve = Path(mount), reserve
        self.fd = self.lock = None
        self.identity = card_identity(self.mount)
        parent = os.open(self.mount, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            stat = os.fstat(parent)
            if f"{os.major(stat.st_dev)}:{os.minor(stat.st_dev)}" != self.identity[1]:
                raise NotReady("SD changed during open")
            check_space(parent, reserve)
            try:
                os.mkdir(family, 0o750, dir_fd=parent)
            except FileExistsError:
                pass
            self.fd = os.open(family, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            if os.fstat(self.fd).st_dev != stat.st_dev:
                raise NotReady("log directory is on another filesystem")
            self.lock = os.open("." + role + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                                0o600, dir_fd=self.fd)
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.check()
        except BaseException:
            self.close()
            raise
        finally:
            os.close(parent)

    def check(self, upcoming=0):
        if card_identity(self.mount) != self.identity:
            raise NotReady("SD removed or replaced")
        check_space(self.fd, self.reserve, upcoming)

    def new(self, kind):
        self.check()
        if kind not in ("dataflash", "blackbox", "stream"):
            raise ValueError("unknown capture type")
        name = f"{kind}-{time.time_ns()}-{uuid.uuid4().hex}.partial"
        fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o640, dir_fd=self.fd)
        os.fsync(self.fd)
        return Capture(self, fd, name)

    def close(self):
        for field in ("lock", "fd"):
            fd = getattr(self, field, None)
            if fd is not None:
                os.close(fd)
                setattr(self, field, None)

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()


class Capture:
    def __init__(self, store, fd, name):
        self.store, self.fd, self.name = store, fd, name
        self.size = 0
        self.hash = hashlib.sha256()

    def append(self, data):
        self.store.check(len(data))
        view = memoryview(data)
        while view:
            count = os.write(self.fd, view)
            if count <= 0:
                raise OSError("short SD write")
            view = view[count:]
        self.hash.update(data)
        self.size += len(data)

    def sync(self):
        self.store.check()
        os.fsync(self.fd)

    def finish(self, extension, metadata):
        if extension not in ("bin", "bbl", "stream.bin"):
            raise ValueError("invalid log extension")
        self.sync()
        sha = self.hash.hexdigest()
        # Capture IDs remain unique, including identical logs and clock resets.
        final = self.name.removesuffix(".partial") + "." + extension
        receipt = dict(metadata, bytes=self.size, sha256=sha, file=final,
                       hardware_validated=False, captured_unix_ns=time.time_ns())
        meta_name = final + ".json"
        meta_stage = meta_name + ".partial"
        meta = os.open(meta_stage, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                       0o640, dir_fd=self.store.fd)
        try:
            with os.fdopen(meta, "w") as out:
                json.dump(receipt, out, indent=2, sort_keys=True)
                out.write("\n")
                out.flush()
                os.fsync(out.fileno())
            # Publish the receipt LAST. A crash/failure must never publish a
            # complete receipt for missing or unrelated bytes.
            rename_new(self.store.fd, self.name, final)
            os.fsync(self.store.fd)
            rename_new(self.store.fd, meta_stage, meta_name)
            os.fsync(self.store.fd)
        finally:
            self.close()
        return receipt

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        # Errors retain the partial file; it is never labeled complete.
        self.close()
