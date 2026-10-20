"""Meaningful CPU contract checks; no claim of GPU execution or causal proof."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import estimator as E


def fields(current=1.25, reference=1., size=(16, 16)):
    s = np.zeros((*size, 4), np.float32)
    r = s.copy()
    s[..., 0], s[..., 1], s[..., 2] = current, 1., 1.
    r[..., 0], r[..., 1], r[..., 3] = reference, 1., 1.
    return s, r


class EstimatorContract(unittest.TestCase):
    def test_production_abstention_is_exact_and_input_is_immutable(self):
        rng = np.random.default_rng(20261021)
        s, r = fields()
        s[..., 0] *= rng.lognormal(0., .8, s.shape[:2])
        saved = s.copy(), r.copy()
        for k in (0, 7, 25):
            out = E.estimate(s, r, k)
            np.testing.assert_array_equal(out["gain"], 1.)
            self.assertTrue(out["abstain"].all())
            self.assertTrue(np.all(out["reason"] & E.Reason.MISSING_INDEPENDENT_CAUSE))
        np.testing.assert_array_equal(s, saved[0])
        np.testing.assert_array_equal(r, saved[1])

    def test_identity_off_reset_and_nonbrightening(self):
        s, r = fields(1., 1.)
        np.testing.assert_array_equal(E.estimate(s, r, 0)["provisional_gain"], 1.)
        s, r = fields()
        for kwargs in ({"active": False}, {"reset": True}, {"strength": 0.}):
            out = E.estimate(s, r, 0, **kwargs)
            np.testing.assert_array_equal(out["provisional_gain"], 1.)
        g = E.estimate(s, r, 0)["provisional_gain"]
        self.assertLess(g[8, 8], 1.)
        self.assertTrue(np.all((g >= .8) & (g <= 1.)))

    def test_light_excess_twins_and_bidirectional_tradeoff(self):
        for step in (.5, .8, 1. / 1.1, 1.1, 1.25, 1.4, 2.):
            s, r = fields(step, 1.)
            # Same numerical inputs are two different causal labels, not two
            # statistically independent captured experiments.
            light = E.estimate(s, r, 0)
            excess = E.estimate(s.copy(), r.copy(), 0)
            np.testing.assert_array_equal(light["gain"], excess["gain"])
            np.testing.assert_array_equal(light["provisional_gain"], excess["provisional_gain"])
            if 1. < step <= 1.4:
                self.assertLess(light["provisional_gain"][8, 8], 1.)
            else:
                np.testing.assert_array_equal(light["provisional_gain"], 1.)

    def test_center_and_unique_support_not_clamped_tap_count(self):
        s, r = fields()
        a = E.estimate(s, r, 0)
        self.assertEqual(a["unique_pairs"][0, 0], 4)
        self.assertEqual(a["unique_pairs"][8, 8], 9)
        self.assertFalse(a["eligible"][0, 0])
        r[8, 8, 1] = 0.
        b = E.estimate(s, r, 0)
        self.assertFalse(b["eligible"][8, 8])
        self.assertEqual(b["provisional_gain"][8, 8], 1.)
        s[7, 7, 2] = 0.
        self.assertEqual(E.estimate(s, r, 0)["provisional_gain"][7, 7], 1.)

    def test_strict_frame_guard_uses_entire_interval(self):
        s, r = fields()
        boundary = 1. - max(.18 * 1.8, .30)
        ambiguous = E.estimate(s, r, 0, frame_ratio_bounds=(boundary - 1e-4, boundary + 1e-4))
        self.assertTrue(np.all(ambiguous["reason"] & E.Reason.FRAME_GUARD_AMBIGUOUS))
        np.testing.assert_array_equal(ambiguous["provisional_gain"], 1.)
        rejected = E.estimate(s, r, 0, frame_ratio_bounds=(.60, .61))
        self.assertTrue(np.all(rejected["reason"] & E.Reason.FRAME_CHANGE_REJECTED))
        accepted = E.estimate(s, r, 0, frame_ratio_bounds=(.8, .81))
        self.assertTrue(accepted["eligible"][8, 8])

    def test_rounding_interval_contains_random_prestore_atomic_ratios(self):
        rng = np.random.default_rng(602)
        s, r = fields()
        # Already stored FP16 values across dark thresholds and physical cap.
        s[..., 0] = np.exp(rng.uniform(np.log(2. ** -22), np.log(20.), (16, 16))).astype(np.float16)
        r[..., 0] = np.exp(rng.uniform(np.log(2. ** -22), np.log(20.), (16, 16))).astype(np.float16)
        fi = E.frame_interval(s, r)
        self.assertFalse(fi["exact"])
        xlo, xhi, _ = E.half_interval(s[..., 0])
        ylo, yhi, _ = E.half_interval(r[..., 0])
        for _ in range(100):
            x = rng.uniform(xlo, xhi)
            y = rng.uniform(ylo, yhi)
            ratio = E._qsum(y, E.DEFAULT_CONFIG) / E._qsum(x, E.DEFAULT_CONFIG)
            self.assertLessEqual(fi["lower"], ratio)
            self.assertGreaterEqual(fi["upper"], ratio)

    def test_physical_scale_darkness_and_cap_are_not_rescaled(self):
        for level in (0., 2. ** -26, 2. ** -20, 2. ** -17, 2. ** -16,
                      2. ** -14, .01, 1., 15.99, 16., 32.):
            s, r = fields(1.25 * level, level)
            out = E.estimate(s, r, 0)
            self.assertTrue(np.isfinite(out["provisional_gain"]).all())
            json.dumps(out["frame_ratio"], allow_nan=False)
            if level < 2. ** -16:
                self.assertIsNone(out["frame_ratio"]["upper"])
                np.testing.assert_array_equal(out["provisional_gain"], 1.)
            if level >= 15.99:
                np.testing.assert_array_equal(out["provisional_gain"], 1.)
                self.assertTrue(out["reason"][8, 8] & E.Reason.CAP_DOMAIN)
        s, r = fields(32., 16.)
        self.assertEqual(E.frame_interval(s, r)["central"], 1.)
        self.assertNotEqual(E.frame_interval(s, r)["central"], 16. / 32.)

    def test_bad_input_and_metadata_never_make_a_diagnostic_nan(self):
        for bad in (np.nan, np.inf, -1., 65504.):
            s, r = fields()
            s[8, 8, 0] = bad
            out = E.estimate(s, r, 0)
            np.testing.assert_array_equal(out["provisional_gain"], 1.)
            self.assertTrue(np.isfinite(out["log_lower"]).all())
            json.dumps(out["frame_ratio"], allow_nan=False)
        s, r = fields()
        for coverage in (np.nan, -1., 1.1):
            out = E.estimate(s, r, 0, frame_ratio_bounds={"lower": .6, "upper": .9, "coverage": coverage})
            np.testing.assert_array_equal(out["provisional_gain"], 1.)
            json.dumps(out["frame_ratio"], allow_nan=False)
        with self.assertRaises(ValueError):
            E.estimate(s, r, 0, frame_ratio_bounds={"lower": .8, "upper": .9, "invalid": False})
        for config in (replace(E.DEFAULT_CONFIG, gain_low=np.nan),
                       replace(E.DEFAULT_CONFIG, tau=-1.),
                       replace(E.DEFAULT_CONFIG, dispersion_multiplier=np.nan),
                       replace(E.DEFAULT_CONFIG, physical_cap=4096.)):
            with self.assertRaises(ValueError):
                E.estimate(s, r, 0, config=config)

    def test_alpha_payload_bits_and_physical_lobes(self):
        rng = np.random.default_rng(17)
        d = rng.uniform(0., .1, (16, 16, 4)).astype(np.float16)
        s = rng.uniform(0., .1, (16, 16, 4)).astype(np.float16)
        # Include signed zero, NaN payload and infinities as opaque alpha data.
        d.view(np.uint16)[..., 3] = np.resize(np.array([0, 0x8000, 0x7e11, 0xfc00], np.uint16), (16, 16))
        s.view(np.uint16)[..., 3] = rng.integers(0, 65536, (16, 16), np.uint16)
        da, sa = E.apply_reference(d, s, np.full((2, 2), .875, np.float32))
        np.testing.assert_array_equal(da.view(np.uint16)[..., 3], d.view(np.uint16)[..., 3])
        np.testing.assert_array_equal(sa.view(np.uint16)[..., 3], s.view(np.uint16)[..., 3])
        np.testing.assert_array_equal(da[..., :3], (d[..., :3].astype(np.float32) * .875).astype(np.float16))
        np.testing.assert_array_equal(sa[..., :3], (s[..., :3].astype(np.float32) * .875).astype(np.float16))
        off_d, off_s = E.apply_reference(d, s, np.ones((2, 2), np.float32))
        np.testing.assert_array_equal(off_d.view(np.uint16), d.view(np.uint16))
        np.testing.assert_array_equal(off_s.view(np.uint16), s.view(np.uint16))

    def test_grid_identity_does_not_prove_pixel_identity(self):
        g = np.full((4, 4), .8, np.float32)
        g[1, 1] = 1.
        pixels = E.bilinear_gain(g, 32, 32)
        self.assertLess(pixels[12, 12], 1.)
        self.assertEqual(g[1, 1], 1.)
        np.testing.assert_array_equal(E.bilinear_gain(np.ones((4, 4)), 32, 32), 1.)


if __name__ == "__main__":
    unittest.main(verbosity=2)
