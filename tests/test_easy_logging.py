"""Host-only tests: all service/network/device operations are mocked or staged."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / "companion/apb"
spec = importlib.util.spec_from_file_location("easy_tested", SOURCE / "easy.py")
easy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(easy)
FAMILY = easy.family(SOURCE)


class EasyTests(unittest.TestCase):
    def test_profile_is_known(self):
        self.assertIn(FAMILY, easy.PROFILES)

    def test_route_digest_matches_bundle(self):
        route = easy.PROFILES[FAMILY]["route"]
        if route:
            expected = json.loads((SOURCE / "profile.json").read_text())["route_sha256"]
            self.assertEqual(hashlib.sha256((SOURCE / route).read_bytes()).hexdigest(), expected)

    def test_archive_is_ardupilot_default(self):
        self.assertEqual(easy.selected_units("ardupilot"), ["orqa-ardupilot-archive.service"])

    def test_live_adds_recorder_not_replaces_archive(self):
        self.assertEqual(len(easy.selected_units("ardupilot", True)), 2)

    def test_live_not_available_for_betaflight(self):
        for name in ("betaflight", "px4"):
            with self.assertRaises(ValueError):
                easy.selected_units(name, True)

    def test_unknown_profile_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "profile.json").write_text('{"firmware":"unknown"}')
            with self.assertRaises(ValueError):
                easy.family(path)

    def test_bench_required(self):
        with self.assertRaises(ValueError):
            easy.require_bench(False)

    def test_root_required_for_bench_actions(self):
        with patch.object(easy.os, "geteuid", return_value=1000), self.assertRaises(PermissionError):
            easy.require_bench(True)

    def test_stopping_does_not_require_uart_present(self):
        with patch.object(easy.os, "geteuid", return_value=0), patch.object(easy, "check_uart") as uart:
            easy.require_bench(True)
            uart.assert_not_called()

    def test_staging_and_repeat_install_do_not_run_commands(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(easy, "run") as run:
            root = Path(directory)
            paths = easy.setup(FAMILY, root, SOURCE)
            easy.setup(FAMILY, root, SOURCE)
            self.assertTrue(paths)
            self.assertTrue((root / ("usr/local/lib/orqa-" + FAMILY) / "profile.json").is_file())
            run.assert_not_called()

    def test_staging_preserves_existing_mount_helper(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(easy, "run") as run:
            root = Path(directory)
            helper = root / "etc/udev/scripts/orqa-drive-mounting.sh"
            helper.parent.mkdir(parents=True)
            helper.write_text("existing customized mount implementation")
            easy.setup(FAMILY, root, SOURCE)
            self.assertEqual(helper.read_text(), "existing customized mount implementation")
            run.assert_not_called()

    def test_preflight_preserves_custom_runtime_before_commands(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(easy, "run") as run:
            root = Path(directory)
            target = root / ("usr/local/lib/orqa-" + FAMILY) / easy.PROFILES[FAMILY]["check"]
            target.parent.mkdir(parents=True)
            target.write_text("custom")
            with self.assertRaises(ValueError):
                easy.setup(FAMILY, root, SOURCE)
            self.assertEqual(target.read_text(), "custom")
            self.assertFalse((target.parent / "easy.py").exists())
            run.assert_not_called()

    def test_symlink_root_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "link").symlink_to(path, target_is_directory=True)
            with self.assertRaises(ValueError):
                easy.setup(FAMILY, path / "link", SOURCE)

    def test_symlink_helper_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root / "etc/udev/scripts/orqa-drive-mounting.sh"
            helper.parent.mkdir(parents=True)
            helper.symlink_to(root / "absent")
            with self.assertRaises(ValueError):
                easy.setup(FAMILY, root, SOURCE)

    def test_dry_run_does_not_create_destination(self):
        installer = easy.load("install", SOURCE)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "new"
            files = installer.install(root, SOURCE, repair=False, dry_run=True)
            self.assertTrue(files)
            self.assertFalse(root.exists())

    def test_staging_cannot_activate(self):
        with patch.object(easy, "setup") as setup, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(easy.main(["setup", "--root", "/tmp/staged", "--activate"]), 1)
            setup.assert_not_called()

    def test_start_without_bench_has_no_commands(self):
        with patch.object(easy, "run") as run, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(easy.main(["start"]), 1)
            run.assert_not_called()

    def test_setup_live_cannot_silently_do_nothing(self):
        with patch.object(easy, "family", return_value="ardupilot"), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(easy.main(["setup", "--live"]), 1)

    def test_setup_activate_no_sd_does_not_install(self):
        with patch.object(easy, "require_bench"), patch.object(easy, "check_uart"), \
             patch.object(easy, "operation_lock", return_value=contextlib.nullcontext()), \
             patch.object(easy, "check_sd", side_effect=RuntimeError("no SD")), \
             patch.object(easy, "setup") as setup, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(easy.main(["setup", "--bench", "--activate"]), 1)
            setup.assert_not_called()

    def test_unit_query_failure_not_mistaken_for_inactive(self):
        with patch.object(easy, "run", return_value=Mock(stdout="", returncode=1)), self.assertRaises(RuntimeError):
            easy.unit_state("some.service")

    def test_disabled_active_unit_is_still_busy(self):
        self.assertTrue(easy.busy({"ActiveState": "active", "UnitFileState": "disabled"}))

    def test_enabled_failed_unit_is_still_busy(self):
        self.assertTrue(easy.busy({"ActiveState": "failed", "UnitFileState": "enabled"}))

    def test_other_profile_blocks_start_even_if_only_enabled(self):
        with patch.object(easy, "unit_state", return_value={
                "LoadState": "loaded", "ActiveState": "inactive", "UnitFileState": "enabled"}):
            with self.assertRaises(RuntimeError):
                easy.conflicts("betaflight")

    def test_betaflight_rejects_enabled_router(self):
        def state(unit):
            return ({"LoadState": "loaded", "ActiveState": "inactive", "UnitFileState": "enabled"}
                    if unit == easy.ROUTER else {"LoadState": "not-found"})
        with patch.object(easy, "unit_state", side_effect=state), self.assertRaises(RuntimeError):
            easy.conflicts("betaflight")

    def test_mavlink_requires_existing_router(self):
        with patch.object(easy, "unit_state", return_value={"LoadState": "not-found"}), self.assertRaises(RuntimeError):
            easy.conflicts("ardupilot")

    def test_failed_preflight_never_restarts_anything(self):
        with patch.object(easy, "readiness", return_value=[{"check": "SD", "ok": False, "detail": "missing"}]), \
             patch.object(easy, "run") as run, self.assertRaises(RuntimeError):
            easy.start(FAMILY, source=SOURCE)
        run.assert_not_called()

    def test_betaflight_start_never_restarts_router(self):
        with patch.object(easy, "readiness", return_value=[]), patch.object(easy, "status", return_value=0), \
             patch.object(easy, "run") as run:
            self.assertEqual(easy.start("betaflight", source=SOURCE), 0)
            commands = [c.args for c in run.call_args_list]
            self.assertNotIn(("systemctl", "restart", easy.ROUTER), commands)
            self.assertIn(("systemctl", "enable", "--now", "orqa-betaflight-archive.service"), commands)

    def test_stop_only_own_units_no_router_or_logs(self):
        with patch.object(easy, "unit_state", return_value={"LoadState": "loaded"}), patch.object(easy, "run") as run:
            easy.stop("ardupilot")
            run.assert_called_once_with("systemctl", "disable", "--now",
                                        "orqa-ardupilot-archive.service", "orqa-ardupilot-recorder.service")

    def test_betaflight_rollback_never_touches_router(self):
        with patch.object(easy, "stop") as stop, patch.object(easy, "run") as run:
            easy.rollback("betaflight", SOURCE)
            stop.assert_called_once_with("betaflight")
            run.assert_not_called()

    def test_status_is_read_only_and_not_hardware_qualification(self):
        checks = [{"check": "SD", "ok": True, "detail": "mock SD"}]
        with patch.object(easy, "readiness", return_value=checks), \
             patch.object(easy, "unit_state", return_value={"LoadState": "loaded", "ActiveState": "active"}), \
             patch.object(easy, "run") as run, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(easy.status("ardupilot", as_json=True), 0)
            report = json.loads(out.getvalue())
            self.assertFalse(report["hardware_validated"])
            self.assertIn("not proof", report["note"])
            run.assert_not_called()

    def test_status_reports_failure_with_nonzero_exit(self):
        with patch.object(easy, "readiness", return_value=[{"check": "SD", "ok": False, "detail": "missing"}]), \
             patch.object(easy, "unit_state", return_value={"ActiveState": "inactive"}), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(easy.status("betaflight"), 1)

    def test_readiness_reports_all_checks_not_only_first_failure(self):
        with patch.object(easy, "check_runtime", side_effect=RuntimeError("missing")), \
             patch.object(easy, "check_uart", side_effect=FileNotFoundError("no UART")), \
             patch.object(easy, "check_sd", side_effect=RuntimeError("no SD")), \
             patch.object(easy, "conflicts", side_effect=RuntimeError("busy")):
            checks = easy.readiness(FAMILY)
            self.assertEqual(len(checks), 4)
            self.assertTrue(all(not c["ok"] for c in checks))

    def test_subprocess_failure_is_visible(self):
        with patch.object(easy.subprocess, "run", return_value=Mock(returncode=1, stderr="failure", stdout="")):
            with self.assertRaisesRegex(RuntimeError, "failure"):
                easy.run("systemctl", "restart", "test.service")

    def test_logs_only_calls_journal(self):
        with patch.object(easy.subprocess, "call", return_value=0) as call:
            self.assertEqual(easy.main(["logs"]), 0)
            command = call.call_args.args[0]
            self.assertEqual(command[0], "journalctl")
            self.assertNotIn("-f", command)



    def test_parent_traversal_cannot_bypass_staging_guard(self):
        with patch.object(easy, "setup") as setup, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(easy.main(["setup", "--root", "/tmp/.."]), 1)
            setup.assert_not_called()

    def test_mavlink_start_checks_endpoint_before_any_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = root / "91-orqa-ardupilot-logging.conf"
            route.write_text("custom")
            (root / "profile.json").write_text('{"route_sha256":"expected"}')
            with patch.object(easy, "ROUTE_DIR", root), patch.object(easy, "readiness", return_value=[]), \
                 patch.object(easy, "run") as run, self.assertRaises(RuntimeError):
                easy.start("ardupilot", source=root)
            run.assert_not_called()

    def test_mavlink_start_restarts_router_once_before_enabling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = root / "91-orqa-ardupilot-logging.conf"
            route.write_text("verified endpoint")
            (root / "profile.json").write_text(json.dumps({
                "route_sha256": hashlib.sha256(route.read_bytes()).hexdigest()}))
            with patch.object(easy, "ROUTE_DIR", root), patch.object(easy, "readiness", return_value=[]), \
                 patch.object(easy, "status", return_value=0), patch.object(easy, "run") as run:
                easy.start("ardupilot", source=root)
                self.assertEqual([c.args for c in run.call_args_list], [
                    ("systemctl", "daemon-reload"), ("systemctl", "restart", easy.ROUTER),
                    ("systemctl", "enable", "--now", "orqa-ardupilot-archive.service")])

    def test_router_failure_does_not_enable_recorder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = root / "91-orqa-ardupilot-logging.conf"
            route.write_text("verified")
            (root / "profile.json").write_text(json.dumps({
                "route_sha256": hashlib.sha256(route.read_bytes()).hexdigest()}))
            with patch.object(easy, "ROUTE_DIR", root), patch.object(easy, "readiness", return_value=[]), \
                 patch.object(easy, "run", side_effect=[Mock(), RuntimeError("router failed")]) as run, \
                 self.assertRaises(RuntimeError):
                easy.start("ardupilot", source=root)
            self.assertEqual(run.call_count, 2)

    def test_custom_endpoint_rollback_refused_before_stopping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "91-orqa-ardupilot-logging.conf").write_text("custom")
            (root / "profile.json").write_text('{"route_sha256":"expected"}')
            with patch.object(easy, "ROUTE_DIR", root), patch.object(easy, "stop") as stop, \
                 self.assertRaises(ValueError):
                easy.rollback("ardupilot", source=root)
            stop.assert_not_called()

    def test_rollback_moves_only_endpoint_and_retains_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = root / "91-orqa-ardupilot-logging.conf"
            route.write_text("verified")
            (root / "valuable.bin").write_text("keep log")
            (root / "profile.json").write_text(json.dumps({
                "route_sha256": hashlib.sha256(route.read_bytes()).hexdigest()}))
            with patch.object(easy, "ROUTE_DIR", root), patch.object(easy, "ROLLBACK_DIR", root / "backup"), \
                 patch.object(easy, "stop") as stop, patch.object(easy, "run") as run, \
                 patch.object(easy, "unit_state", return_value={"ActiveState": "active"}):
                easy.rollback("ardupilot", source=root)
                stop.assert_called_once_with("ardupilot")
                run.assert_called_once_with("systemctl", "restart", easy.ROUTER)
            self.assertFalse(route.exists())
            self.assertEqual(next((root / "backup").iterdir()).read_text(), "verified")
            self.assertEqual((root / "valuable.bin").read_text(), "keep log")

    def test_actual_setup_dependencies_are_isolated_and_pinned(self):
        installer = Mock(VENDOR_HASH="not vendor", install=Mock(return_value=["staged"]))
        with patch.object(easy, "load", return_value=installer), patch.object(easy, "run") as run:
            easy.setup("ardupilot", Path("/"), SOURCE)
            first = installer.install.call_args_list[0]
            self.assertTrue(first.kwargs["dry_run"])
            commands = [c.args for c in run.call_args_list]
            pip = next(c for c in commands if "pip" in c)
            self.assertIn("--isolated", pip)
            self.assertIn(SOURCE / "requirements.txt", pip)
            self.assertNotIn("--break-system-packages", pip)
            self.assertEqual(commands[-1], ("systemctl", "daemon-reload"))

    def test_unknown_venv_is_not_overwritten(self):
        installer = Mock(VENDOR_HASH="not vendor", install=Mock(return_value=["staged"]))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = dict(easy.PROFILES["ardupilot"], python=str(root / "bin/python"))
            with patch.dict(easy.PROFILES, {"ardupilot": config}), \
                 patch.object(easy, "load", return_value=installer), patch.object(easy, "run") as run, \
                 self.assertRaises(RuntimeError):
                easy.setup("ardupilot", Path("/"), SOURCE)
            self.assertEqual(installer.install.call_count, 1)  # dry run only
            run.assert_not_called()

if __name__ == "__main__":
    unittest.main()
