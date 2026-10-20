"""Orientation-independent detail scoring, added by the skeptical reviewer."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from proxy_metrics import ProxyOutput, metrics


def metric_fixture(direction):
    yy, xx = np.indices((8, 10))
    if direction == "x":
        pattern = (xx % 2) * 2 - 1
    elif direction == "y":
        pattern = (yy % 2) * 2 - 1
    elif direction == "xy":
        pattern = ((xx + yy) % 2) * 2 - 1
    else:
        pattern = np.zeros_like(xx)
    truth = np.broadcast_to((.4 + .2 * pattern)[None, ..., None], (4, 8, 10, 3)).astype(np.float32).copy()
    mask = np.ones(truth.shape[:3], bool)
    scene = SimpleNamespace(truth=truth, masks={"interior": mask, "edge": mask,
                            "rigid_background": mask, "mixed_coverage": np.zeros_like(mask),
                            "motion_change": np.zeros_like(mask)})
    zero = np.zeros(truth.shape[:3], np.float32)
    return scene, zero


class TestSymmetricDetailMetric(unittest.TestCase):
    def test_rotated_truth_identity_and_destroyed_detail(self):
        for direction in ("x", "y", "xy"):
            with self.subTest(direction=direction):
                scene, zero = metric_fixture(direction)
                identity = metrics(scene, ProxyOutput(scene.truth.copy(), zero, zero, zero))
                self.assertAlmostEqual(identity["detail_gradient_transfer"], 1, places=6)
                self.assertAlmostEqual(identity["rigid_detail_gradient_transfer"], 1, places=6)
                flattened = metrics(scene, ProxyOutput(np.full_like(scene.truth, .4), zero, zero, zero))
                self.assertAlmostEqual(flattened["detail_gradient_transfer"], 0, places=6)
                self.assertFalse(flattened["detail_loss_gate_pass"])

    def test_flat_truth_detail_is_unavailable(self):
        scene, zero = metric_fixture("flat")
        identity = metrics(scene, ProxyOutput(scene.truth.copy(), zero, zero, zero))
        self.assertIsNone(identity["detail_gradient_transfer"])
        self.assertIsNone(identity["rigid_detail_gradient_transfer"])
        self.assertNotEqual(identity["detail_loss_gate_pass"], True)


if __name__ == "__main__":
    unittest.main()
