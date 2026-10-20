"""Frozen independent control: detail destruction cannot win on flicker alone."""
import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "review" / "blind_calibration.py"
spec = importlib.util.spec_from_file_location("blind_calibration", MODULE_PATH)
calibration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calibration)


class TestBlindControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = calibration.run()

    def test_fixed_denominators(self):
        for case in self.results["cases"]:
            for region, base in case["exact_normals"].items():
                changed = case["flat_normals"][region]
                self.assertEqual(base["pixels"], changed["pixels"])
                self.assertEqual(base["detail_denominator"], changed["detail_denominator"])

    def test_negative_control_and_noise_only_mutation(self):
        for case in self.results["cases"]:
            self.assertTrue(calibration.accept_image_claim(case["exact_normals"], case["exact_normals"])[0])
            self.assertFalse(case["flat_accepted"])
            self.assertTrue(case["noise_only_scorer_mutant_accepted"])
            self.assertLess(case["ratios"]["all"]["flicker_rms"], 1.0)
            self.assertLess(case["ratios"]["all"]["detail_transfer"], 0.95)


if __name__ == "__main__":
    unittest.main()
