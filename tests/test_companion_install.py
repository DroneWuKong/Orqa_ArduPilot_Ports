import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

COMPANION = Path(__file__).resolve().parents[1] / "companion/apb"
sys.path.insert(0, str(COMPANION))
import install as installer
import mount_sd as mount


class InstallTests(unittest.TestCase):
    def test_unknown_mount_helper_preserved_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "etc/udev/scripts/orqa-drive-mounting.sh"
            target.parent.mkdir(parents=True)
            target.write_text("custom")
            with self.assertRaises(ValueError):
                installer.install(root, COMPANION, True)
            self.assertEqual(target.read_text(), "custom")
            self.assertFalse((root / "usr").exists())

    def test_repeat_install_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "etc/udev/scripts/orqa-drive-mounting.sh"
            target.parent.mkdir(parents=True)
            target.write_text("vendor fixture")
            with patch.object(installer, "VENDOR_HASH", installer.digest(target)):
                installer.install(root, COMPANION, True)
                installer.install(root, COMPANION, True)
            self.assertEqual(target.with_name(target.name + ".pre-orqa-logging").read_text(), "vendor fixture")

    def test_install_without_mount_repair_keeps_existing_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "etc/udev/scripts/orqa-drive-mounting.sh"
            target.parent.mkdir(parents=True)
            target.write_text("existing PX4 repair")
            installer.install(root, COMPANION)
            self.assertEqual(target.read_text(), "existing PX4 repair")

    def test_custom_runtime_file_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / ("usr/local/lib/orqa-" + installer.FAMILY) / "archive.py"
            target.parent.mkdir(parents=True)
            target.write_text("custom")
            with self.assertRaises(ValueError):
                installer.install(root, COMPANION)
            self.assertEqual(target.read_text(), "custom")
            self.assertFalse((target.parent / "storage.py").exists())

    def test_symlink_root_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "alias").symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                installer.install(root / "alias", COMPANION)


class MountTests(unittest.TestCase):
    def test_device_injection_rejected(self):
        with self.assertRaises(ValueError):
            mount.handle("sda1-mount; rm")

    def test_emmc_never_mounted(self):
        with patch.object(mount, "current_source", return_value=""), \
             patch.object(Path, "read_text", return_value="MMC\n"), \
             patch.object(mount.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                mount.handle("mmcblk0p1-mount")
            run.assert_not_called()

    def test_unmount_only_matching_device(self):
        with patch.object(mount, "current_source", return_value="/dev/mmcblk1p1"), \
             patch.object(mount.subprocess, "run") as run:
            mount.handle("mmcblk0p1-unmount")
            run.assert_not_called()
            mount.handle("mmcblk1p1-unmount")
            self.assertEqual(run.call_args[0][0], ["systemd-umount", "--collect", "/sdcard"])

    def test_mount_waits_for_success(self):
        with patch.object(mount, "current_source", side_effect=["", "/dev/mmcblk1p1"]), \
             patch.object(Path, "read_text", return_value="SD\n"), \
             patch.object(Path, "is_symlink", return_value=False), \
             patch.object(Path, "mkdir"), patch.object(mount.subprocess, "run") as run:
            mount.handle("mmcblk1p1-mount")
            self.assertNotIn("--no-block", run.call_args[0][0])
            self.assertTrue(run.call_args[1]["check"])

    def test_mount_failure_not_success(self):
        with patch.object(mount, "current_source", side_effect=["", ""]), \
             patch.object(Path, "read_text", return_value="SD\n"), \
             patch.object(Path, "is_symlink", return_value=False), \
             patch.object(Path, "mkdir"), patch.object(mount.subprocess, "run"):
            with self.assertRaises(RuntimeError):
                mount.handle("mmcblk1p1-mount")


if __name__ == "__main__":
    unittest.main()
