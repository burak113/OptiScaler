"""Independent adversarial candidate audit, not an implementation mirror.

The known-bad control was rejected in independent_controls.py before this file
was written. These tests never inspect captured/held-out fixture arrays.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import estimator as candidate
from independent_controls import fields


class IndependentAudit(unittest.TestCase):
    def assert_production_abstains(self, output):
        np.testing.assert_array_equal(output["gain"], 1)
        self.assertTrue(output["abstain"].all())
        self.assertTrue(np.isfinite(output["provisional_gain"]).all())
        self.assertTrue((output["provisional_gain"] <= 1).all())
        self.assertTrue((output["provisional_gain"] >= 0).all())

    def test_unknown_cause_abstains_under_independent_adversarial_seeds(self):
        for seed in (271828, 314159):
            rng = np.random.default_rng(seed)
            current = rng.lognormal(0, 1.8, (31, 17))
            old = rng.lognormal(0, 1.8, (31, 17))
            s, r = fields(current, old)
            r[..., 1] = rng.random((31, 17)) > .35
            s[..., 2] = rng.random((31, 17)) > .2
            before_s, before_r = s.copy(), r.copy()
            output = candidate.estimate(s, r, 13)
            self.assert_production_abstains(output)
            np.testing.assert_array_equal(s, before_s)
            np.testing.assert_array_equal(r, before_r)

    def test_observational_twins_light_and_excess_are_indistinguishable(self):
        for step in (1 / 1.4, .8, 1 / 1.1, 1.1, 1.25, 1.4):
            s, r = fields(np.full((23, 19), step), np.ones((23, 19)))
            for k in (0, 4, 21):
                genuine_light = candidate.estimate(s, r, k)
                transient_excess = candidate.estimate(s.copy(), r.copy(), k)
                self.assert_production_abstains(genuine_light)
                for key in ("gain", "provisional_gain", "eligible", "reason"):
                    np.testing.assert_array_equal(genuine_light[key], transient_excess[key])
                self.assertAlmostEqual((step * genuine_light["gain"].mean() - 1) / (step - 1), 1, places=5)

    def test_off_reset_and_empty_history_stop_conditional_output(self):
        s, r = fields(np.full((16, 16), 1.25), np.ones((16, 16)))
        for kwargs in ({"active": False}, {"reset": True}, {"strength": 0}):
            output = candidate.estimate(s, r, 0, **kwargs)
            self.assert_production_abstains(output)
            np.testing.assert_array_equal(output["provisional_gain"], 1)
        r[..., 1] = 0
        output = candidate.estimate(s, r, 0)
        self.assert_production_abstains(output)
        np.testing.assert_array_equal(output["provisional_gain"], 1)

    def test_empty_own_recall_never_borrows_neighbour_cause(self):
        s, r = fields(np.full((25, 25), 1.25), np.ones((25, 25)))
        r[12, 12, 1] = 0
        output = candidate.estimate(s, r, 0)
        self.assertFalse(output["eligible"][12, 12])
        self.assertEqual(output["provisional_gain"][12, 12], 1)
        self.assertGreater(output["unique_pairs"][12, 12], 5)

    def test_clamped_edges_do_not_duplicate_independent_support(self):
        for shape in ((1, 1), (1, 9), (2, 2)):
            s, r = fields(np.full(shape, 1.25), np.ones(shape))
            output = candidate.estimate(s, r, 0)
            self.assert_production_abstains(output)
            self.assertLessEqual(output["unique_pairs"].max(), min(9, np.prod(shape)))
            np.testing.assert_array_equal(output["provisional_gain"], 1)

    def test_strict_frame_guard_straddle_abstains(self):
        s, r = fields(np.full((16, 16), 1.25), np.ones((16, 16)))
        # k=21 uses reject_abs .3, hence frame-ratio threshold .7.
        output = candidate.estimate(s, r, 21, frame_ratio_bounds=(.7 - 1e-6, .7 + 1e-6))
        np.testing.assert_array_equal(output["provisional_gain"], 1)
        self.assertTrue(np.all(output["reason"] & int(candidate.Reason.FRAME_GUARD_AMBIGUOUS)))

    def test_invalid_frame_metadata_cannot_bypass_strict_guard(self):
        s, r = fields(np.full((16, 16), 1.25), np.ones((16, 16)))
        for coverage in (float("nan"), float("inf"), -.1, 1.1):
            with self.subTest(coverage=coverage):
                try:
                    output = candidate.estimate(s, r, 0, frame_ratio_bounds={
                        "lower": .6, "upper": .9, "coverage": coverage})
                except ValueError:
                    continue
                self.assert_production_abstains(output)
                np.testing.assert_array_equal(output["provisional_gain"], 1)
                self.assertFalse(output["eligible"].any())

    def test_nonfinite_and_nonsensical_configuration_is_rejected(self):
        s, r = fields(np.full((16, 16), 1.25), np.ones((16, 16)))
        changes = ({"gain_low": float("nan")}, {"cap_extra": float("nan")},
                   {"dispersion_multiplier": float("nan")}, {"tau": 0.},
                   {"tau": -1.}, {"dispersion_multiplier": -1.},
                   {"frame_min_coverage": -1.}, {"min_pairs": 5.5},
                   {"tap_step": 1.5})
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    candidate.estimate(s, r, 0, config=replace(candidate.DEFAULT_CONFIG, **change))

    def test_dark_cap_and_unbounded_half_domain_abstain(self):
        for value in (0., np.nextafter(np.float16(0), np.float16(1)).item(),
                      2**-17, 16., 32., 65504.):
            s, r = fields(np.full((16, 16), value), np.full((16, 16), value / 1.25))
            output = candidate.estimate(s, r, 0)
            self.assert_production_abstains(output)
            np.testing.assert_array_equal(output["provisional_gain"], 1)

    def test_nonfinite_or_negative_supported_input_never_yields_correction(self):
        for value in (float("nan"), float("inf"), -1., -float("inf")):
            s, r = fields(np.full((16, 16), 1.25), np.ones((16, 16)))
            s[8, 8, 0] = value
            output = candidate.estimate(s, r, 0)
            self.assert_production_abstains(output)
            np.testing.assert_array_equal(output["provisional_gain"], 1)

    def test_alpha_nan_payload_and_signed_zero_are_bitwise_preserved(self):
        rng = np.random.default_rng(271828)
        d = rng.random((17, 29, 4)).astype(np.float16)
        s = rng.random((17, 29, 4)).astype(np.float16)
        # Alpha is payload, not a color; include NaN payloads and signed zero.
        bits = np.resize(np.array([0x0000, 0x8000, 0x7E01, 0xFE55, 0x7C00, 0x3C00], np.uint16), (17, 29))
        d[..., 3] = bits.view(np.float16)
        s[..., 3] = np.flip(bits, axis=0).copy().view(np.float16)
        a, b = candidate.apply_reference(d, s, np.array([[.8, 1], [1, .9]], np.float32))
        np.testing.assert_array_equal(a[..., 3].view(np.uint16), d[..., 3].view(np.uint16))
        np.testing.assert_array_equal(b[..., 3].view(np.uint16), s[..., 3].view(np.uint16))

    def test_grid_abstention_does_not_prove_dynamic_pixel_identity(self):
        full = candidate.bilinear_gain(np.array([[.8, 1]], np.float32), 8, 16)
        dynamic = full[:, 8:]
        self.assertLess(float(dynamic.min()), .99)
        self.assertEqual(float(np.mean(dynamic < 1)), .5)
        # Actual candidate identity has zero interpolation dose everywhere.
        actual = candidate.bilinear_gain(np.ones((1, 2), np.float32), 8, 16)
        np.testing.assert_array_equal(actual, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
