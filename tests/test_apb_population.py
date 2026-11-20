import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_population", ROOT / "scripts/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class PopulationTests(unittest.TestCase):
    def test_existing_population_selects_matching_target_without_promoting_qualification(self):
        result = build.verify_sensor_population("apb-mpu6000-icm42605", "apb-copter", build.lock())
        self.assertFalse(result["hardware_qualified"])

    def test_dual_42605_selects_only_separate_bench_target(self):
        config = build.lock()
        selected = build.verify_sensor_population(
            "apb-dual-icm42605", "apb-dual-icm42605-copter", config)
        self.assertFalse(selected["hardware_qualified"])
        for target in build.lock()["targets"]:
            if target["id"] == "apb-dual-icm42605-copter":
                continue
            with self.subTest(target=target["id"]), self.assertRaises(ValueError):
                build.verify_sensor_population("apb-dual-icm42605", target["id"], build.lock())

    def test_wrong_population_target_and_unknown_population_rejected(self):
        for population,target in [("apb-dual-icm42688","apb-copter"),("guess","apb-copter")]:
            with self.assertRaises(ValueError):build.verify_sensor_population(population,target,build.lock())

    def test_dual_candidate_has_explicit_rotations_and_release_gate(self):
        records=json.loads((ROOT/"qualification/apb-sensor-populations.json").read_text())["populations"]
        dual=records["apb-dual-icm42605"]
        target=next(t for t in build.lock()["targets"] if t["id"] == "apb-dual-icm42605-copter")
        hwdef=(ROOT/"boards"/target["board"]/"hwdef.dat").read_text()
        self.assertEqual(dual["build_targets"],[target["id"]])
        self.assertEqual(dual["ardupilot_candidate_rotations"],
                         ["ROTATION_YAW_180", "ROTATION_YAW_90"])
        self.assertEqual(target["sensor_population"],"apb-dual-icm42605")
        self.assertFalse(target["release_eligible"])
        self.assertFalse(dual["hardware_qualified"])
        self.assertFalse(dual["required_evidence"]["individual_sensor_body_axis_sweep"])
        self.assertIn("undef IMU",hwdef)
        self.assertIn("IMU Invensensev3 SPI:imu1 ROTATION_YAW_180",hwdef)
        self.assertIn("IMU Invensensev3 SPI:imu2 ROTATION_YAW_90",hwdef)

    def test_apb_cli_requires_declared_population_before_build(self):
        result=subprocess.run([sys.executable,str(ROOT/"scripts/build.py"),"build",
                               "/nonexistent/ardupilot","--target","apb-copter"],
                              text=True,capture_output=True)
        self.assertEqual(result.returncode,2)
        self.assertIn("require --sensor-population",result.stderr)

    def test_all_apb_targets_have_one_population_record(self):
        records=json.loads((ROOT/"qualification/apb-sensor-populations.json").read_text())["populations"]
        for target in build.lock()["targets"]:
            if not target["id"].startswith("apb-"):
                continue
            with self.subTest(target=target["id"]):
                matching=[name for name, record in records.items()
                          if target["id"] in record["build_targets"]]
                self.assertEqual(matching,[target["sensor_population"]])


if __name__ == "__main__":unittest.main()
