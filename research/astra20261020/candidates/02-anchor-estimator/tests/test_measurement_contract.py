"""Measurement-risk checks: immutable denominators, gap scope and real-light area."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metrics import sequence_metrics, response_metrics
from experiments import make_sequence


class MeasurementContract(unittest.TestCase):
    def test_one_sided_energy_identity_and_fixed_mask_not_gain_mask(self):
        x = np.ones((2, 3, 4))
        x[:, 1, 1] = 8
        g = np.ones_like(x); g[:, 1, 1] = .8
        m = np.ones_like(x, bool); before = m.copy()
        r = sequence_metrics(x, g, m, [7, 8], [0, 1], truth=x)
        self.assertEqual(r["base_mask_samples"], 24)
        self.assertAlmostEqual(r["global_energy_drift"], -r["correction_dose"], places=15)
        self.assertAlmostEqual(r["correction_dose"], 3.2 / 38, places=12)
        np.testing.assert_array_equal(m, before)
        # A changed-mask mutant gives a different dose and fails the contract.
        mutant = sequence_metrics(x, g, g < 1., [7, 8], [0, 1], truth=x)
        self.assertNotEqual(mutant["correction_dose"], r["correction_dose"])

    def test_sparse_capture_frames_are_not_temporal_adjacent_samples(self):
        x = np.ones((3, 3, 4)); g = np.ones_like(x)
        g[1] = .8; g[2] = .9
        r = sequence_metrics(x, g, np.ones_like(x, bool), [41, 44, 45], [0, 2, 3])
        self.assertEqual(r["adjacent_original_frame_pairs"], 1)
        self.assertEqual(r["gaps_not_interpolated"], 1)
        self.assertEqual(r["temporal_denominator"], 12)
        self.assertAlmostEqual(r["gain_delta_rms"], .1)

    def test_step_area_and_latency_are_relative_to_step_not_total_brightness(self):
        base = np.ones((2, 2)); truth = np.ones((4, 2, 2))
        truth[1:] = 1.25
        out = truth.copy(); out[1] = 1.; out[2] = 1.125
        r = response_metrics(truth, out, base, np.ones_like(truth, bool), onset=1, window=3)
        self.assertAlmostEqual(r["response_area_ratio"], .5)
        self.assertEqual(r["sustained_90pct_latency_frames"], 2)
        self.assertEqual(r["sustained_95pct_latency_frames"], 2)

    def test_moving_crop_light_background_denominator_excludes_all_original_foreground(self):
        seq = make_sequence("moving_object_light")
        background = seq["static"].all(axis=0)
        self.assertGreater(int(background.sum()), 0)
        self.assertFalse(np.any(background[None] & ~seq["static"]))
        r = response_metrics(seq["truth"], seq["truth"], seq["base_truth"],
            np.broadcast_to(background, seq["truth"].shape))
        self.assertAlmostEqual(r["response_area_ratio"], 1.)


if __name__ == "__main__":
    unittest.main()
