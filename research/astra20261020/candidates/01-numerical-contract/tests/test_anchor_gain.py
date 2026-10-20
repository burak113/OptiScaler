"""Actual Gain store boundary, policy preservation and recorded-frame diagnostics."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from numerical_contract.anchor_gain import (GainParameters, anchor_gain,
                                             anchor_gain_unstored, replay_calibration)
from numerical_contract.storage import store_fp16


def uniform_grid(current=1, recalled_level=.85, extent=(8, 8)):
    s = np.zeros((*extent, 4), np.float32)
    r = np.zeros_like(s)
    s[..., 0], s[..., 1], s[..., 2] = current, 10, 1
    r[..., 0], r[..., 1], r[..., 3] = recalled_level, 1, 1
    return store_fp16(s), store_fp16(r)


class AnchorGainContracts(unittest.TestCase):
    def test_uniform_local_statistics_and_ratio_match_source(self):
        s, r = uniform_grid()
        result = anchor_gain_unstored(s, r, 0, .85, frame_count=64, frame_measured=True)
        np.testing.assert_array_equal(result.numerator, r[..., 0] * np.float32(9))
        np.testing.assert_array_equal(result.denominator, 9)
        np.testing.assert_array_equal(result.coverage, 9)
        np.testing.assert_array_equal(result.gain, r[..., 0])
        self.assertFalse(result.frame_rejected)
        self.assertFalse(result.local_rejected.any())

    def test_actual_store_is_after_gain_not_a_second_store_of_frozen_rne(self):
        s, r = uniform_grid(recalled_level=.8)
        raw = np.array([anchor_gain_unstored(s, r, k, .8, frame_count=64, frame_measured=True).gain[0, 0]
                        for k in range(26)], np.float32)
        rne, rtz = store_fp16(raw, rounding="rne"), store_fp16(raw, rounding="rtz")
        mutant = store_fp16(rne, rounding="rtz")
        self.assertGreater(int(np.count_nonzero(rne != rtz)), 0)
        self.assertGreater(int(np.count_nonzero(mutant != rtz)), 0)
        for rounding in ("rne", "rtz"):
            actual = anchor_gain(s, r, 3, .8, frame_count=64, frame_measured=True, rounding=rounding)
            np.testing.assert_array_equal(actual, store_fp16(raw[3], rounding=rounding))

    def test_native_and_combined_preserve_existing_fallback_and_local_gate_policies(self):
        s, r = uniform_grid(recalled_level=.8, extent=(16, 16))
        for dy in (-3, 0, 3):
            for dx in (-3, 0, 3):
                r[8 + dy, 8 + dx, 1] = 0
        count = int(np.count_nonzero(r[..., 1]))
        native = anchor_gain_unstored(s, r, 0, .8, frame_count=count, frame_measured=True, policy="native")
        combined = anchor_gain_unstored(s, r, 0, .8, frame_count=count, frame_measured=True, policy="combined")
        self.assertEqual(float(native.gain[8, 8]), 1)
        self.assertTrue(native.native_local_blocked[8, 8])
        self.assertLess(float(combined.gain[8, 8]), .81)
        # A static centre with neighbouring recall is enough in the audited native
        # policy; adding a centre-recall requirement would be a policy mutation.
        r[5, 5, 1] = 1
        native2 = anchor_gain_unstored(s, r, 0, .8, frame_count=count + 1, frame_measured=True)
        self.assertLess(float(native2.gain[8, 8]), 1)

    def test_zero_strength_identity_and_unused_fields_are_invariant(self):
        s, r = uniform_grid()
        base = anchor_gain_unstored(s, r, 0, .85, frame_count=64, frame_measured=True)
        s[..., 1], s[..., 3], r[..., 2] = np.nan, np.inf, np.nan
        unused = replace(GainParameters(), fallback_a_unused=np.nan)
        other = anchor_gain_unstored(s, r, 0, .85, frame_count=64, frame_measured=True, params=unused)
        np.testing.assert_array_equal(other.gain, base.gain)
        for policy in ("native", "combined"):
            off = anchor_gain_unstored(s, r, 0, .85, frame_count=64, frame_measured=True,
                                       params=replace(unused, strength=0), policy=policy)
            np.testing.assert_array_equal(off.gain, 1)
        combined_unused = replace(unused, native_local_gate=np.nan)
        a = anchor_gain_unstored(s, r, 0, .85, frame_count=64, frame_measured=True, policy="combined")
        b = anchor_gain_unstored(s, r, 0, .85, frame_count=64, frame_measured=True,
                                 params=combined_unused, policy="combined")
        np.testing.assert_array_equal(a.gain, b.gain)

    def test_unmeasured_ratio_is_unused_and_count_is_explicit(self):
        s, r = uniform_grid()
        r[..., 1] = 0
        for unused in (None, np.nan, -np.inf):
            result = anchor_gain_unstored(s, r, 0, unused, frame_count=0, frame_measured=False)
            self.assertEqual(float(result.frame_ratio), 1)
            np.testing.assert_array_equal(result.gain, 1)
        for kwargs in ({"frame_count": 0, "frame_measured": True},
                       {"frame_count": 65, "frame_measured": True},
                       {"frame_count": 10, "frame_measured": None}):
            with self.assertRaises(ValueError):
                anchor_gain_unstored(s, r, 0, 1, **kwargs)

    def test_large_light_is_rejected_but_known_moderate_light_bias_is_preserved(self):
        large_s, prior = uniform_grid(current=2, recalled_level=1)
        large = anchor_gain_unstored(large_s, prior, 0, .5, frame_count=64, frame_measured=True)
        self.assertTrue(large.frame_rejected)
        np.testing.assert_array_equal(large.gain, 1)
        moderate_s, prior = uniform_grid(current=1.25, recalled_level=1)
        moderate = anchor_gain(moderate_s, prior, 0, .8, frame_count=64, frame_measured=True, rounding="rtz")
        # Passing this test reproduces the known policy defect. It approves no
        # image-quality change and does not claim the1.25x light step is noise.
        self.assertLess(float(np.max(moderate * np.float32(1.25))), 1.001)


class RecordedGainDiagnostics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calibration = replay_calibration()

    def test_fixed_populations_include_every133_combined_and7_native_frame(self):
        result = self.calibration
        self.assertEqual(result["frame_counts"], {"combined": 133, "native": 7})
        self.assertEqual(len(result["frames"]), 140 * 2 * 2)
        for row in result["summary"]:
            self.assertEqual(row["population"], 416720 if row["policy"] == "combined" else 26256)
        self.assertFalse(result["gpu_executed"])
        self.assertTrue(result["native_gain_invariant_across_rne_and_rtz_field_ratio_bounds"])
        self.assertEqual(len(result["rtz_residual_cells"]), 17)
        for residual in result["rtz_residual_cells"]:
            self.assertEqual(len(residual["taps"]), 9)
            self.assertEqual(set(residual["source_models"]), {"source_exp_f32", "dxil_exp2_f32"})

    def test_dominant_store_gap_and_remaining_counterexample_are_both_diagnosed(self):
        rows = {(r["policy"], r["exp_mode"], r["rounding"]): r for r in self.calibration["summary"]}
        # Exact fixed-fixture diagnostic counts, not enlarged acceptance tolerances.
        # The17 remaining combined discrepancies deliberately prevent an exact-
        # reconstruction claim even though both p99 values fall to zero with RTZ.
        for exp_mode in ("source_exp_f32", "dxil_exp2_f32"):
            for policy, rne_count, rtz_count in (("combined", 77036, 17), ("native", 3675, 0)):
                rne, rtz = rows[policy, exp_mode, "rne"], rows[policy, exp_mode, "rtz"]
                self.assertEqual(rne["nonzero_count"], rne_count)
                self.assertEqual(rtz["nonzero_count"], rtz_count)
                self.assertEqual(rne["predicted_below_gpu_count"], 0)
                self.assertEqual(rtz["p99_abs"], 0)
        self.assertFalse(self.calibration["store_only_explanation_complete"])


if __name__ == "__main__":
    unittest.main()
