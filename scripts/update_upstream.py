#!/usr/bin/env python3
"""Propose stable upstream revisions. Never merges or publishes firmware."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True).strip()


def stable_version(tag, kind):
    pattern = r"(\d+)\.(\d+)\.(\d+)" if kind == "betaflight" else r"Copter-(\d+)\.(\d+)\.(\d+)"
    match = re.fullmatch(pattern, tag)
    return tuple(map(int, match.groups())) if match else None


def choose(releases, kind, current):
    candidates = [r for r in releases if not r.get("draft") and not r.get("prerelease")
                  and stable_version(r["tag_name"], kind)]
    if kind == "ardupilot":
        plane = {r["tag_name"] for r in releases if not r.get("draft") and not r.get("prerelease")}
        candidates = [r for r in candidates if r["tag_name"].replace("Copter-", "Plane-") in plane]
    candidates.sort(key=lambda r: stable_version(r["tag_name"], kind), reverse=True)
    if candidates and stable_version(candidates[0]["tag_name"], kind) > stable_version(current, kind):
        return candidates[0]["tag_name"]
    return None


def resolve(repository, tag):
    obj = json.loads(gh("api", f"repos/{repository}/git/ref/tags/{tag}"))["object"]
    for _ in range(5):
        if obj["type"] == "commit":
            if not re.fullmatch("[0-9a-f]{40}", obj["sha"]):
                raise ValueError("Invalid commit")
            return obj["sha"]
        if obj["type"] != "tag":
            break
        obj = json.loads(gh("api", f"repos/{repository}/git/tags/{obj['sha']}"))["object"]
    raise ValueError("Cannot resolve tag to a commit")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--propose", action="store_true")
    args = parser.parse_args()
    path = ROOT / "upstream.lock.json"
    config = json.loads(path.read_text())
    releases = json.loads(gh("api", f"repos/{config['repository']}/releases?per_page=100"))
    tag = choose(releases, config["kind"], config["tag"])
    if not tag:
        print("No newer matching stable release")
        return
    revision = resolve(config["repository"], tag)
    if config["kind"] == "ardupilot" and resolve(config["repository"], tag.replace("Copter-", "Plane-")) != revision:
        raise ValueError("Copter and Plane tags differ; manual split-release review required")
    print(f"Candidate: {tag} {revision}")
    if not args.propose:
        return
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = "automation/upstream-" + revision[:12]
    existing = json.loads(gh("pr", "list", "--repo", repo, "--head", branch,
                             "--state", "all", "--json", "number"))
    if existing:
        print("Already proposed; preserve review/closure and existing branch")
        return
    if subprocess.check_output(["git", "status", "--porcelain"], text=True).strip():
        raise ValueError("Updater requires a clean checkout")
    subprocess.run(["git", "switch", "-c", branch], check=True)
    config.update(tag=tag, revision=revision)
    path.write_text(json.dumps(config, indent=2) + "\n")
    subprocess.run(["git", "add", "upstream.lock.json"], check=True)
    subprocess.run(["git", "-c", "user.name=orqa-update-bot", "-c",
                    "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                    "commit", "-m", "Upstream: propose " + tag], check=True)
    subprocess.run(["git", "push", "origin", "HEAD:" + branch], check=True)
    url = gh("pr", "create", "--repo", repo, "--base", "main", "--head", branch,
             "--title", "Upstream: " + tag,
             "--body", "Automated stable-release proposal. No auto-merge or release.\n\n"
             "Review upstream changes, patch applicability, board defaults, compiler compatibility "
             "and all build manifests. Software checks do not establish hardware qualification.\n\n"
             f"Upstream: https://github.com/{config['repository']}/commit/{revision}\n\n"
             "AI-assisted repository tooling; human review required.")
    # Token-created PRs do not trigger pull_request workflows. Dispatch explicitly.
    gh("workflow", "run", "build.yml", "--repo", repo, "--ref", branch)
    print(url)


if __name__ == "__main__":
    main()
