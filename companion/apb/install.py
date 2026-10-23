#!/usr/bin/env python3
"""Stage companion files without installing dependencies or restarting services."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

FAMILY = "ardupilot"
VENDOR_HASH = "501cf034fb6afb04f4fb8036139ab9b131d005c19863d522c95a76d8616452f6"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_path(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlinked installation destination: " + str(path))


def install(root, source, repair=False, dry_run=False):
    root, source = Path(root).absolute(), Path(source).resolve()
    safe_path(root)
    files = {}
    for path in source.iterdir():
        if path.suffix == ".py" and path.name not in ("install.py", "mount_sd.py"):
            files[path] = root / f"usr/local/lib/orqa-{FAMILY}" / path.name
        elif path.suffix == ".service":
            files[path] = root / "etc/systemd/system" / path.name
        elif path.name == "profile.json":
            files[path] = root / f"usr/local/lib/orqa-{FAMILY}" / path.name
        elif path.suffix == ".conf":
            files[path] = root / "etc/mavlink-router/config.d" / path.name
    helper = root / "etc/udev/scripts/orqa-drive-mounting.sh"
    backup = helper.with_name(helper.name + ".pre-orqa-logging")
    if repair:
        files[source / "mount_sd.py"] = root / "usr/local/lib/orqa-logging/mount_sd.py"
        files[source / "orqa-drive-mounting.sh"] = helper
        safe_path(backup)
        if backup.exists() and digest(backup) != VENDOR_HASH:
            raise ValueError("unrecognized vendor helper backup")
        if not helper.exists():
            raise ValueError("inspected vendor helper is missing")
        if not backup.exists() and digest(helper) != VENDOR_HASH:
            raise ValueError("unknown mount helper; keep an existing PX4 repair or review manually")
    for incoming, dest in files.items():
        safe_path(dest)
        if dest.exists() and digest(dest) != digest(incoming):
            if not (repair and dest == helper and digest(dest) == VENDOR_HASH):
                raise ValueError("preserve/review existing file: " + str(dest))
    if dry_run:
        return sorted(str(dest) for dest in files.values())
    if repair and not backup.exists():
        shutil.copy2(helper, backup)
    for incoming, dest in files.items():
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as temporary:
            temporary.write(incoming.read_bytes())
            temporary.flush()
            os.fsync(temporary.fileno())
            stage = Path(temporary.name)
        stage.chmod(0o755 if incoming.suffix == ".sh" else 0o644)
        stage.replace(dest)
    return sorted(str(dest) for dest in files.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--repair-vendor-mount", action="store_true")
    args = parser.parse_args()
    for path in install(args.root, Path(__file__).resolve().parent, args.repair_vendor_mount):
        print(path)
    print("Installed. No service, FC setting, media content or dependency was changed; follow README activation steps.")
