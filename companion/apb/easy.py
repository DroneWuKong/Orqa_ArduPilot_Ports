#!/usr/bin/env python3
"""One interface for the three APB logging packages. Never flashes or sets FC parameters."""
import argparse
from contextlib import contextmanager, nullcontext
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

PROFILES = {
    "px4": {
        "units": ["orqa-px4-recorder.service"],
        "route": "90-orqa-px4-logging.conf",
        "python": "/usr/bin/python3",
        "check": "recorder.py",
        "settings": "Matching APB PX4 firmware; MAVLink2 UART4 230400; SDLOG_MODE != -1. Compact ULog, not full-rate tuning logs.",
    },
    "ardupilot": {
        "units": ["orqa-ardupilot-archive.service", "orqa-ardupilot-recorder.service"],
        "route": "91-orqa-ardupilot-logging.conf",
        "python": "/opt/orqa-ardupilot-logger/venv/bin/python",
        "check": "recorder.py",
        "settings": "SERIAL4_PROTOCOL=2, SERIAL4_BAUD=230; LOG_BACKEND_TYPE=4 for archive, 6 only for --live; LOG_DISARMED=0 recommended.",
    },
    "betaflight": {
        "units": ["orqa-betaflight-archive.service"],
        "route": None,
        "python": "/opt/orqa-betaflight-logger/venv/bin/python",
        "check": "archive.py",
        "settings": "UART4 MSP 115200; blackbox_device=FLASH. Post-flight offload only; onboard capacity stays finite.",
    },
}
ROUTER = "mavlink-router.service"
SOURCE = Path(__file__).resolve().parent
RESERVE = 256 * 1024 * 1024
ROUTE_DIR = Path("/etc/mavlink-router/config.d")
ROLLBACK_DIR = Path("/var/lib/orqa-logging/rollback")


def run(*args, check=True, timeout=30):
    result = subprocess.run(list(map(str, args)), text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError("Command failed: " + " ".join(map(str, args)) + "\n" +
                           (result.stderr or result.stdout)[-2000:])
    return result


def safe_path(path):
    path = Path(path).absolute()
    if ".." in path.parts:
        raise ValueError("Refusing parent-directory traversal: " + str(path))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Refusing symlinked destination: " + str(path))
    return path


def load(name, source=SOURCE):
    spec = importlib.util.spec_from_file_location("easy_" + name, source / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def family(source=SOURCE):
    name = json.loads((source / "profile.json").read_text())["firmware"]
    if name not in PROFILES:
        raise ValueError("Unknown bundled firmware profile")
    return name


def runtime(name):
    return Path("/usr/local/lib/orqa-" + name)


def selected_units(name, live=False):
    if live and name != "ardupilot":
        raise ValueError("--live applies only to ArduPilot; Betaflight is post-flight offload")
    units = PROFILES[name]["units"]
    return units if name != "ardupilot" or live else units[:1]


def unit_state(unit):
    result = run("systemctl", "show", unit, "--property=LoadState,ActiveState,UnitFileState", check=False)
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if not fields or "LoadState" not in fields:
        raise RuntimeError("Cannot query systemd: " + unit)
    return fields


def busy(state):
    return (state.get("ActiveState") not in ("inactive", "failed", None) or
            state.get("UnitFileState", "").startswith(("enabled", "linked")))


def conflicts(name):
    for other, config in PROFILES.items():
        if other != name:
            for unit in config["units"]:
                state = unit_state(unit)
                if state["LoadState"] != "not-found" and busy(state):
                    raise RuntimeError("Other firmware logger enabled/running: " + unit +
                                       ". Stop it explicitly on the bench first.")
    router = unit_state(ROUTER)
    if name == "betaflight":
        if router["LoadState"] != "not-found" and busy(router):
            raise RuntimeError("UART4 is owned/reserved by mavlink-router. On the bench, stop/disable it before using MSP.")
    elif router.get("ActiveState") != "active":
        raise RuntimeError("Existing mavlink-router must already be active and configured for UART4 230400.")


def check_uart():
    if not stat.S_ISCHR(Path("/dev/ttymxc2").stat().st_mode):
        raise RuntimeError("/dev/ttymxc2 is not a character device")
    return "/dev/ttymxc2 exists; baud and FC settings still need confirmation"


def check_sd(name, source=SOURCE):
    module = load("recorder" if name == "px4" else "storage", source)
    module.card_identity(Path("/sdcard"))
    fs = os.statvfs("/sdcard")
    free = fs.f_bavail * fs.f_frsize
    if fs.f_flag & os.ST_RDONLY or free < RESERVE:
        raise RuntimeError("SD read-only or less than 256 MiB available; export logs, do not format")
    folder = Path("/sdcard") / name
    safe_path(folder)
    return "SD mounted read/write; %d MiB free; logs: %s" % (free // (1024 * 1024), folder)


def check_runtime(name):
    base = runtime(name)
    safe_path(base)
    required = ["easy.py", "profile.json", PROFILES[name]["check"]]
    if name == "ardupilot":
        required += ["archive.py", "link.py", "storage.py"]
    elif name == "betaflight":
        required += ["storage.py"]
    for filename in required:
        path = safe_path(base / filename)
        if not path.is_file():
            raise RuntimeError("Missing " + str(path) + "; run setup from the extracted package")
    python = PROFILES[name]["python"]
    if name != "px4":
        safe_path(Path(python).parents[1])
        imports = "import serial" if name == "betaflight" else "import serial; from pymavlink import mavutil"
        run(python, "-c", imports)
    if name == "px4":
        version = run("/usr/bin/mavlink-routerd", "-V").stdout.strip()
        if not re.search(r"\bv4(?:\b|-)", version):
            raise RuntimeError("PX4 requires the tested mavlink-router v4; found: " + version)
    route = PROFILES[name]["route"]
    if route and not safe_path(ROUTE_DIR / route).is_file():
        raise RuntimeError("Logging endpoint missing; rerun setup")
    return "Installed runtime and dependencies found"


def readiness(name, live=False, source=SOURCE):
    selected_units(name, live)
    checks = []
    for title, probe in (
        ("Runtime", lambda: check_runtime(name)),
        ("UART", check_uart),
        ("SD", lambda: check_sd(name, source)),
        ("Ownership", lambda: conflicts(name) or "No conflicting enabled/running logger"),
    ):
        try:
            checks.append({"check": title, "ok": True, "detail": probe()})
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            checks.append({"check": title, "ok": False, "detail": str(error)})
    return checks


def status(name, live=False, as_json=False, source=SOURCE):
    checks = readiness(name, live, source)
    for unit in PROFILES[name]["units"]:
        try:
            state = unit_state(unit)
            required = unit in selected_units(name, live)
            active = state.get("ActiveState") == "active"
            checks.append({"check": unit, "ok": active or not required,
                           "detail": state.get("ActiveState", "unknown") +
                           ("" if required else " (optional live recorder)")})
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            checks.append({"check": unit, "ok": False, "detail": str(error)})
    report = {"firmware": name, "checks": checks, "fc_settings": PROFILES[name]["settings"],
              "hardware_validated": False,
              "note": "Service health is not proof of log completeness or flight safety. Inspect logs with the matching parser."}
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print("APB logging: " + name)
        for item in checks:
            print(("[OK] " if item["ok"] else "[CHECK] ") + item["check"] + ": " + item["detail"])
        print("FC settings (not changed): " + report["fc_settings"])
        print(report["note"])
    return 0 if all(c["ok"] for c in checks) else 1


def require_bench(bench):
    if not bench:
        raise ValueError("Add --bench only after removing props, disarming and verifying the matching FC settings. Router restart interrupts telemetry.")
    if os.geteuid() != 0:
        raise PermissionError("Run this command with sudo on the APB companion")


@contextmanager
def operation_lock():
    fd = os.open("/run/orqa-apb-setup.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def setup(name, root, source=SOURCE, wheels=None):
    root = safe_path(root)
    if not (source / "install.py").is_file():
        raise ValueError("Run setup from the extracted companion package, not the installed runtime directory")
    installer = load("install", source)
    helper = root / "etc/udev/scripts/orqa-drive-mounting.sh"
    safe_path(helper)
    repair = helper.is_file() and installer.digest(helper) == installer.VENDOR_HASH
    # Preflight the entire install before network, dependency or file writes.
    installer.install(root, source, repair=repair, dry_run=True)
    if root == Path("/") and name != "px4":
        env = safe_path(Path(PROFILES[name]["python"]).parents[1])
        if not env.exists():
            run(sys.executable, "-m", "venv", env, timeout=120)
        elif not (env / "pyvenv.cfg").is_file():
            raise RuntimeError("Refusing unrecognized Python environment: " + str(env))
        command = [PROFILES[name]["python"], "-m", "pip", "--isolated", "install",
                   "--disable-pip-version-check", "-r", source / "requirements.txt"]
        if wheels:
            command += ["--no-index", "--find-links", Path(wheels).resolve(strict=True)]
        print("Installing pinned companion dependencies...", flush=True)
        run(*command, timeout=1200)
    installed = installer.install(root, source, repair=repair)
    print("Installed %d files for %s. %s" % (len(installed), name,
          "Known vendor SD helper repaired; backup retained." if repair else "Existing SD helper preserved."))
    if root != Path("/"):
        print("Staging only: no dependencies installed and no host services touched.")
    else:
        run("systemctl", "daemon-reload")
        print("Setup complete; not started. Run: sudo python3 easy.py start --bench")
    return installed


def start(name, live=False, source=SOURCE):
    checks = readiness(name, live, source)
    failed = [c["check"] + ": " + c["detail"] for c in checks if not c["ok"]]
    if failed:
        raise RuntimeError("Start refused; nothing restarted:\n" + "\n".join(failed))
    # Package config must match installed config; do not restart a customized endpoint.
    route = PROFILES[name]["route"]
    if route:
        target = ROUTE_DIR / route
        expected = json.loads((source / "profile.json").read_text())["route_sha256"]
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Installed router endpoint differs; preserve and review it")
    run("systemctl", "daemon-reload")
    if route:
        print("Restarting the existing router once to load the endpoint (bench only).", flush=True)
        run("systemctl", "restart", ROUTER)
    run("systemctl", "enable", "--now", *selected_units(name, live))
    print("Start requested. 'active' alone does not prove reception; check status and logs.")
    return status(name, live, source=source)


def stop(name):
    units = [u for u in PROFILES[name]["units"] if unit_state(u)["LoadState"] != "not-found"]
    if units:
        run("systemctl", "disable", "--now", *units)
    print("This profile stopped/disabled. Logs, shared SD mount and core router preserved.")


def rollback(name, source=SOURCE):
    route = PROFILES[name]["route"]
    target = ROUTE_DIR / route if route else None
    destination = None
    if target and target.exists():
        safe_path(target)
        expected = json.loads((source / "profile.json").read_text())["route_sha256"]
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError("Customized router endpoint; preserve/review manually before rollback")
        destination = safe_path(ROLLBACK_DIR /
                                (route + "." + str(time.time_ns())))
        if destination.exists():
            raise ValueError("Rollback destination already exists")
    stop(name)
    if destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        target.rename(destination)
        print("Endpoint backed up to " + str(destination))
        if unit_state(ROUTER).get("ActiveState") == "active":
            run("systemctl", "restart", ROUTER)
    print("Deactivated. Captured logs, runtime, dependencies, shared mount repair and FC settings retained.")
    print("To reactivate: setup, then start --bench. Firmware/parameter rollback is separate.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    install = sub.add_parser("setup", help="install dependencies/files; activation is opt-in")
    install.add_argument("--root", type=Path, default=Path("/"), help="offline image staging; never touches host services")
    install.add_argument("--wheels", type=Path, help="offline wheel directory, otherwise use pip index")
    install.add_argument("--activate", action="store_true", help="also start; requires --bench and interrupts router telemetry")
    install.add_argument("--live", action="store_true", help="ArduPilot only; requires LOG_BACKEND_TYPE=6 already set")
    install.add_argument("--bench", action="store_true")
    launch = sub.add_parser("start", help="start/enable; MAVLink profiles restart the existing router")
    launch.add_argument("--live", action="store_true")
    launch.add_argument("--bench", action="store_true")
    state = sub.add_parser("status", help="read-only health checks, not a link/flight qualification")
    state.add_argument("--live", action="store_true")
    state.add_argument("--json", action="store_true")
    journal = sub.add_parser("logs", help="show recent recorder journals")
    journal.add_argument("--follow", action="store_true")
    for action in ("stop", "rollback"):
        command = sub.add_parser(action, help="bench-only deactivation; never deletes captured logs")
        command.add_argument("--bench", action="store_true")
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 10):
            raise RuntimeError("Python 3.10 or newer is required on the APB companion")
        name = family()
        live = getattr(args, "live", False)
        selected_units(name, live)
        staging = args.command == "setup" and safe_path(args.root) != Path("/")
        if staging and (args.activate or args.live or args.wheels):
            raise ValueError("--root staging cannot activate services or install dependencies")
        if args.command == "setup" and args.live and not args.activate:
            raise ValueError("--live requires --activate; setup alone never starts recording")
        mutating = args.command in ("setup", "start", "stop", "rollback")
        if mutating and not staging:
            require_bench(args.bench)
            if args.command == "setup":
                check_uart()
        with operation_lock() if mutating and not staging else nullcontext():
            if args.command == "setup":
                if args.activate:
                    check_sd(name)
                    conflicts(name)
                setup(name, args.root, wheels=args.wheels)
                return start(name, live) if args.activate else 0
            if args.command == "start":
                return start(name, live)
            if args.command == "status":
                return status(name, live, args.json)
            if args.command == "logs":
                command = ["journalctl", "--no-pager", "-n", "60"]
                for unit in PROFILES[name]["units"]:
                    command += ["-u", unit]
                if args.follow:
                    command.append("-f")
                return subprocess.call(command)
            if args.command == "stop":
                stop(name)
            elif args.command == "rollback":
                rollback(name)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print("CHECK: " + str(error), file=sys.stderr)
        print("No firmware/FC parameters changed. If setup partly completed, fix the reported issue and rerun; unknown files are never overwritten.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
