#!/usr/bin/env python3
"""Manual prerelease publisher: accept only verified artifacts for current main."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True).strip()


def verify(folder, config, revision):
    expected = {t["id"]: t for t in config["targets"]}
    manifests = list(folder.rglob("*.manifest.json"))
    if len(manifests) != len(expected):
        raise ValueError("Incomplete build matrix")
    seen = set()
    assets = []
    for path in manifests:
        data = json.loads(path.read_text())
        target = data["target"]["id"]
        if target not in expected or target in seen or data["target"] != expected[target]:
            raise ValueError("Unexpected or duplicate target")
        seen.add(target)
        if data["port_revision"] != revision or data["port_worktree_dirty"] or data["hardware_validated"]:
            raise ValueError("Dirty, mismatched or incorrectly qualified build")
        if data["upstream"] != config:
            raise ValueError("Upstream pin mismatch")
        suffixes = {".bin", ".elf", ".hex" if config["kind"] == "betaflight" else ".apj"}
        if set(data["artifacts"]) != {target + suffix for suffix in suffixes}:
            raise ValueError("Unexpected firmware filenames")
        for name, sha in data["artifacts"].items():
            artifact = path.parent / name
            if artifact.is_symlink() or hashlib.sha256(artifact.read_bytes()).hexdigest() != sha:
                raise ValueError("Artifact checksum mismatch")
            assets.append(artifact)
        assets.append(path)
    return assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=int)
    parser.add_argument("tag")
    args = parser.parse_args()
    if not re.fullmatch(r"v\d+\.\d+\.\d+-rc\d+", args.tag):
        parser.error("Use a new vX.Y.Z-rcN prerelease tag")
    repo = os.environ["GITHUB_REPOSITORY"]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    run = json.loads(gh("api", f"repos/{repo}/actions/runs/{args.run_id}"))
    if (run["head_sha"] != revision or run["conclusion"] != "success"
            or run["head_branch"] != "main" or run["event"] != "push"
            or run["path"] != ".github/workflows/build.yml"):
        raise ValueError("Select a successful main push build for this exact commit")
    config = json.loads((ROOT / "upstream.lock.json").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        gh("run", "download", str(args.run_id), "--repo", repo,
           "--pattern", "firmware-*", "--dir", str(folder))
        assets = verify(folder, config, revision)
        sums = folder / "SHA256SUMS"
        sums.write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
                               for p in sorted(assets)))
        source = folder / "port-source.tar.gz"
        subprocess.run(["git", "archive", "--format=tar.gz", "--output", str(source), revision], check=True)
        with sums.open("a") as out:
            out.write(f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {source.name}\n")
        gh("release", "create", args.tag, *map(str, assets), str(sums), str(source),
           "--repo", repo, "--target", revision, "--prerelease",
           "--title", "Orqa firmware " + args.tag,
           "--notes", "Hardware-unvalidated bench-test firmware. Never flash a mismatched board or sensor variant.\n\n"
           f"Verified build: https://github.com/{repo}/actions/runs/{args.run_id}\n\n"
           "See repository README for flash offsets, source reproduction, rollback and remaining hardware tests.")
        print(f"https://github.com/{repo}/releases/tag/{args.tag}")


if __name__ == "__main__":
    main()
