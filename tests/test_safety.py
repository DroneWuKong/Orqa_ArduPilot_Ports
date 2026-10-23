import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build = module("build")
update = module("update_upstream")


class UpdateTests(unittest.TestCase):
    def release(self, tag, **kw):
        return dict(tag_name=tag, draft=False, prerelease=False, **kw)

    def test_numeric_order_not_lexical(self):
        self.assertEqual(update.choose([self.release("4.9.0"), self.release("4.10.0")], "betaflight", "4.8.0"), "4.10.0")

    def test_reject_candidate_tags(self):
        for tag in ["4.8.0-RC1", "nightly", "master", "4.8.0; touch x"]:
            self.assertIsNone(update.stable_version(tag, "betaflight"))

    def test_no_downgrade(self):
        self.assertIsNone(update.choose([self.release("4.7.0")], "betaflight", "4.8.0"))

    def test_unchanged(self):
        self.assertIsNone(update.choose([self.release("4.8.0")], "betaflight", "4.8.0"))

    def test_no_drafts_or_prereleases(self):
        for flag in ["draft", "prerelease"]:
            release = self.release("4.9.0")
            release[flag] = True
            self.assertIsNone(update.choose([release], "betaflight", "4.8.0"))

    def test_ardupilot_requires_both_vehicles(self):
        self.assertIsNone(update.choose([self.release("Copter-4.8.0")], "ardupilot", "Copter-4.7.2"))
        self.assertEqual(update.choose([self.release("Copter-4.8.0"), self.release("Plane-4.8.0")],
                                       "ardupilot", "Copter-4.7.2"), "Copter-4.8.0")

    def test_annotated_tag(self):
        replies = [json.dumps({"object": {"type": "tag", "sha": "a"*40}}),
                   json.dumps({"object": {"type": "commit", "sha": "b"*40}})]
        with patch.object(update, "gh", side_effect=replies):
            self.assertEqual(update.resolve("test/repo", "1.2.3"), "b"*40)


class ImageTests(unittest.TestCase):
    target = {"flash_start": 0x08060000, "flash_end": 0x08200000}

    def data(self, stack=0x20010000, reset=0x08060101):
        return struct.pack("<II", stack, reset) + bytes(248)

    def test_valid_vector(self):
        build.validate_image(self.data(), self.target)

    def test_wrong_link_address(self):
        with self.assertRaises(ValueError):
            build.validate_image(self.data(reset=0x08000101), self.target)

    def test_thumb_bit_required(self):
        with self.assertRaises(ValueError):
            build.validate_image(self.data(reset=0x08060100), self.target)

    def test_invalid_stack(self):
        with self.assertRaises(ValueError):
            build.validate_image(self.data(stack=0x08001000), self.target)

    def test_empty_or_oversize(self):
        for raw in [b"", bytes(12), bytes(0x200000)]:
            with self.assertRaises(ValueError):
                build.validate_image(raw, self.target)

    def test_wrong_source_revision(self):
        with patch.object(build, "run", return_value="a"*40):
            with self.assertRaises(ValueError):
                build.verify_revision(Path("/tmp/source"), {"revision": "b"*40})

    def test_nonempty_artifacts_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "old.bin").touch()
            with self.assertRaises(ValueError):
                build.collect(Path("/unused"), {}, {}, out)


class BoardTests(unittest.TestCase):
    def test_target_ids_unique(self):
        config = build.lock()
        ids = [t["id"] for t in config["targets"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertRegex(config["revision"], "^[a-f0-9]{40}$")
        self.assertRegex(config["toolchain"]["sha256"], "^[a-f0-9]{64}$")

    def test_board_regressions(self):
        if build.lock()["kind"] == "betaflight":
            h7 = (ROOT / "configs/ORQA/ORQA_H743/config.h").read_text()
            apb = (ROOT / "configs/ORQA/ORQA_APB/config.h").read_text()
            f4 = (ROOT / "configs/ORQA/ORQA_F405/config.h").read_text()
            for text in (h7, apb):
                self.assertRegex(text, r"#define USB_DETECT_PIN\s+PE2")
                self.assertNotIn("#define UART8_TX_PIN", text)
                self.assertNotIn("#define LED1_PIN                        PA11", text)
            self.assertNotIn("#define USE_SDCARD", apb)
            self.assertNotIn("#define SERVO3_PIN", apb)
            self.assertRegex(apb, r"#define UART4_TX_PIN\s+PC10")
            self.assertRegex(apb, r"#define UART4_RX_PIN\s+PC11")
            self.assertIn("ORQA_APB_IMU_ICM42688P", apb)
            self.assertRegex(f4, r"#define FLASH_SPI_INSTANCE\s+SPI3")
            self.assertRegex(f4, r"#define MAX7456_SPI_INSTANCE\s+SPI2")
            self.assertIn("ORQA_F405_IMU_ICM42688P", f4)
        else:
            apb = (ROOT / "boards/OrqaAPB/hwdef.dat").read_text()
            later = (ROOT / "boards/OrqaAPB-ICM42688/hwdef.dat").read_text()
            self.assertIn("APJ_BOARD_ID AP_HW_ORQAAPB_FACTORY", apb)
            self.assertNotIn("SDMMC", apb)
            self.assertIn("Backend_Type::BLOCK", apb)
            self.assertNotIn("Backend_Type::FILESYSTEM", apb)
            self.assertIn("DEFAULT_SERIAL4_BAUD 230", apb)
            self.assertIn("IMU Invensense SPI:imu1 ROTATION_PITCH_180", apb)
            self.assertIn("AP_BOOTLOADER_FLASHING_ENABLED 0", apb)
            self.assertIn("undef IMU", later)
            self.assertIn("ROTATION_ROLL_180_YAW_90", later)
            diff = (ROOT / "patches/0001-f405-single-imu-and-adc-docs.patch").read_text()
            self.assertIn("-SPIDEV imu2", diff)
            self.assertIn("+IMU Invensensev3 SPI:imu1", diff)
            self.assertIn("+- BATT_VOLT_PIN 11", diff)
            self.assertIn("+- BATT_CURR_PIN 13", diff)


if __name__ == "__main__":
    unittest.main()
