#!/usr/bin/env python3
"""Pinned, non-flashing firmware builder. Standard library plus pyelftools."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=None, capture=False):
    return subprocess.run(list(map(str, args)), cwd=cwd, check=True,
                          text=True, stdout=subprocess.PIPE if capture else None).stdout


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def lock():
    return json.loads((ROOT / "upstream.lock.json").read_text())


def verify_revision(source, config):
    if run("git", "rev-parse", "HEAD", cwd=source, capture=True).strip() != config["revision"]:
        raise ValueError("Source revision mismatch; use a fresh source directory")
    if run("git", "rev-parse", "--show-toplevel", cwd=source, capture=True).strip() != str(source):
        raise ValueError("Pass the source repository root")


def prepare(source, config):
    if not source.exists():
        run("git", "clone", "--depth", "1", "--branch", config["tag"],
            "https://github.com/" + config["repository"] + ".git", source)
    verify_revision(source, config)
    if config["kind"] == "ardupilot":
        modules = ["modules/ChibiOS", "modules/waf", "modules/mavlink",
                   "modules/DroneCAN", "modules/gtest", "modules/littlefs", "modules/lwip",
                   "modules/CrashDebug"]
    else:
        modules = ["src/config", "lib/modules/dronecan/libcanard"]
    run("git", "submodule", "update", "--init", "--recursive", "--depth", "1", *modules, cwd=source)
    pending = []
    for patch in sorted((ROOT / "patches").glob("*.patch")):
        result = subprocess.run(["git", "apply", "--check", str(patch)], cwd=source, capture_output=True)
        if result.returncode:
            # Identical installation is safe; any other conflict needs review.
            run("git", "apply", "--reverse", "--check", patch, cwd=source, capture=True)
        else:
            pending.append(patch)
    copies = []
    if config["kind"] == "ardupilot":
        for incoming in (ROOT / "boards").rglob("*"):
            if not incoming.is_file():
                continue
            dest = source / "libraries/AP_HAL_ChibiOS/hwdef" / incoming.relative_to(ROOT / "boards")
            if dest.is_symlink() or any(p.is_symlink() for p in dest.parents):
                raise ValueError("Refusing symlinked overlay destination")
            if dest.exists() and dest.read_bytes() != incoming.read_bytes():
                raise ValueError("Preserve existing board edits before installation: " + str(dest))
            copies.append((incoming, dest))
    for patch in pending:
        run("git", "apply", patch, cwd=source)
    for incoming, dest in copies:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(incoming, dest)


def toolchain(destination, config):
    tc = config["toolchain"]
    dest = destination / tc["directory"]
    if dest.exists():
        raise ValueError("Toolchain destination already exists; reuse its bin directory explicitly")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination) as tmp:
        archive = Path(tmp) / "toolchain.tar"
        with urllib.request.urlopen(tc["url"], timeout=120) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
        if digest(archive) != tc["sha256"]:
            raise ValueError("Toolchain SHA256 mismatch")
        run("tar", "-xf", archive, "-C", destination)
    version = run(dest / "bin/arm-none-eabi-gcc", "-dumpfullversion", capture=True).strip()
    if version != tc["version"]:
        raise ValueError("Toolchain version mismatch")
    print("Add to PATH: " + str(dest / "bin"))


def validate_image(data, target):
    capacity = target["flash_end"] - target["flash_start"]
    if len(data) < 256 or len(data) > capacity:
        raise ValueError("Empty, truncated or oversized firmware")
    stack, reset = struct.unpack_from("<II", data)
    ranges = [(0x20000000, 0x20020000)]
    if target["flash_end"] == 0x08100000:  # STM32F405 CCM stack
        ranges.append((0x10000000, 0x10010000))
    else:  # STM32H743 DTCM / AXI SRAM / D2 SRAM
        ranges.extend([(0x24000000, 0x24080000), (0x30000000, 0x30048000)])
    if stack % 8 or not any(start < stack <= end for start, end in ranges):
        raise ValueError("Invalid initial stack pointer")
    if not reset & 1 or not target["flash_start"] <= (reset & ~1) < target["flash_end"]:
        raise ValueError("Invalid reset vector / wrong flash offset")


def check_elf(elf, target):
    from elftools.elf.elffile import ELFFile
    with elf.open("rb") as stream:
        image = ELFFile(stream)
        segments = [s for s in image.iter_segments() if s["p_type"] == "PT_LOAD" and s["p_filesz"]
                    and 0x08000000 <= s["p_paddr"] < 0x09000000]
        if not segments or min(s["p_paddr"] for s in segments) != target["flash_start"]:
            raise ValueError("ELF linked at wrong flash address")
        end = max(s["p_paddr"] + s["p_filesz"] for s in segments)
        if end > target["flash_end"]:
            raise ValueError("ELF exceeds physical flash")
        return {"flash_end_used": end, "physical_flash_free": target["flash_end"] - end}


def collect(source, target, config, out):
    if out.exists() and any(out.iterdir()):
        raise ValueError("Artifact directory must be empty; do not mix builds")
    out.mkdir(parents=True, exist_ok=True)
    if config["kind"] == "betaflight":
        base = source / "obj"
        candidates = list((base / "main").glob("*.elf"))
        if len(candidates) != 1:
            raise ValueError("Expected one freshly built ELF")
        elf = candidates[0]
        binary = elf.with_suffix(".bin")
        if not binary.exists():
            run("arm-none-eabi-objcopy", "-O", "binary", elf, binary)
        hexes = list(base.glob("*.hex"))
        if len(hexes) != 1:
            raise ValueError("Expected one freshly built HEX")
        with tempfile.TemporaryDirectory() as tmp:
            decoded = Path(tmp) / "hex.bin"
            run("arm-none-eabi-objcopy", "-I", "ihex", "-O", "binary", hexes[0], decoded)
            if decoded.read_bytes() != binary.read_bytes():
                raise ValueError("HEX and ELF binary disagree")
        if target["board"].encode() not in binary.read_bytes():
            raise ValueError("Board identity missing from binary")
        originals = [elf, binary, hexes[0]]
    else:
        base = source / "build" / target["board"] / "bin"
        name = "ardu" + target["vehicle"]
        elf, binary, bundle = base / name, base / (name + ".bin"), base / (name + ".apj")
        apj = json.loads(bundle.read_text())
        raw = zlib.decompress(base64.b64decode(apj["image"]))
        if apj["board_id"] != target["board_id"] or apj["image_size"] != len(raw):
            raise ValueError("APJ board ID or image size mismatch")
        if raw != binary.read_bytes():
            raise ValueError("APJ and binary disagree")
        originals = [binary, bundle, elf]
    data = binary.read_bytes()
    validate_image(data, target)
    budget = check_elf(elf, target)
    hashes = {}
    for original in originals:
        suffix = ".elf" if original == elf else original.suffix
        dest = out / (target["id"] + suffix)
        shutil.copy2(original, dest)
        hashes[dest.name] = digest(dest)
    inputs = {}
    for folder in ("boards", "configs", "patches", "scripts"):
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                inputs[str(path.relative_to(ROOT))] = digest(path)
    inputs["upstream.lock.json"] = digest(ROOT / "upstream.lock.json")
    manifest = {
        "target": target, "upstream": config, "inputs": inputs, "artifacts": hashes,
        "port_revision": run("git", "rev-parse", "HEAD", cwd=ROOT, capture=True).strip(),
        "port_worktree_dirty": bool(run("git", "status", "--porcelain", cwd=ROOT, capture=True).strip()),
        "source_diff_sha256": hashlib.sha256(run("git", "diff", "HEAD", cwd=source, capture=True).encode()).hexdigest(),
        "submodules": run("git", "submodule", "status", "--recursive", cwd=source, capture=True).splitlines(),
        "compiler": run("arm-none-eabi-gcc", "--version", capture=True).splitlines()[0],
        "hardware_validated": False, "budget": budget,
    }
    path = out / (target["id"] + ".manifest.json")
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    hashes[path.name] = digest(path)
    (out / "SHA256SUMS").write_text("".join(f"{sha}  {name}\n" for name, sha in sorted(hashes.items())))
    print(json.dumps({"target": target["id"], "result": "PASS", **budget}))


def build(source, target, config, jobs):
    verify_revision(source, config)
    version = run("arm-none-eabi-gcc", "-dumpfullversion", capture=True).strip()
    if version != config["toolchain"]["version"]:
        raise ValueError("Wrong compiler version: " + version)
    if config["kind"] == "betaflight":
        # A fresh object directory is mandatory across sensor-population variants.
        # Never silently remove someone else's previous build.
        if (source / "obj").exists():
            raise ValueError("Use a fresh checkout per target; obj already exists")
        flags = "-D" + target["define"] if target["define"] else ""
        run("make", "-j" + str(jobs), "CONFIG=" + target["board"],
            "BETAFLIGHT_CONFIG=" + str(ROOT), "EXTRA_FLAGS=" + flags, cwd=source)
    else:
        run("./waf", "configure", "--board", target["board"], cwd=source)
        run("./waf", target["vehicle"], "-j" + str(jobs), cwd=source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "toolchain", "build", "collect"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--target")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    config = lock()
    directory = args.directory.resolve()
    target = next((t for t in config["targets"] if t["id"] == args.target), None)
    if args.action in ("build", "collect") and target is None:
        parser.error("Select a target from upstream.lock.json")
    if args.action == "prepare":
        prepare(directory, config)
    elif args.action == "toolchain":
        toolchain(directory, config)
    elif args.action == "build":
        build(directory, target, config, args.jobs)
    else:
        collect(directory, target, config, args.output.resolve())


if __name__ == "__main__":
    main()
