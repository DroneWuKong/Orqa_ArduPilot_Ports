import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_population", ROOT / "scripts/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class PopulationTests(unittest.TestCase):
    def test_existing_population_selects_matching_target_without_promoting_qualification(self):
        result = build.verify_sensor_population("apb-mpu6000-icm42605", "apb-copter", build.lock())
        self.assertFalse(result["hardware_qualified"])

    def test_dual_42605_cannot_alias_existing_targets(self):
        for target in build.lock()["targets"]:
            with self.subTest(target=target["id"]), self.assertRaises(ValueError):
                build.verify_sensor_population("apb-dual-icm42605", target["id"], build.lock())

    def test_wrong_population_target_and_unknown_population_rejected(self):
        for population,target in [("apb-dual-icm42688","apb-copter"),("guess","apb-copter")]:
            with self.assertRaises(ValueError):build.verify_sensor_population(population,target,build.lock())

    def test_gate_cannot_silently_publish_an_unreviewed_dual_target(self):
        records=json.loads((ROOT/"qualification/apb-sensor-populations.json").read_text())["populations"]
        dual=records["apb-dual-icm42605"]
        self.assertEqual(dual["build_targets"],[])
        self.assertIsNone(dual["ardupilot_candidate_rotations"])
        self.assertFalse(any(dual["required_evidence"].values()))
        self.assertFalse(any("dual-icm42605" in target["id"] for target in build.lock()["targets"]))


if __name__ == "__main__":unittest.main()
