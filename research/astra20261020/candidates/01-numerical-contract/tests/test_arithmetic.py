"""Arithmetic staging, conversion domain, lobe isolation and OFF metamorphisms."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from numerical_contract.arithmetic import (apply_anchor_lobes, dot_f32, f32_add, f32_mul,
                                            mad_fused, mad_separate, to_int32, to_uint32)
from numerical_contract.storage import store_fp16


class ArithmeticContracts(unittest.TestCase):
    def test_separate_and_fused_have_a_known_cancellation_witness(self):
        a, b, c = np.float32(1 + 2**-23), np.float32(1 - 2**-23), np.float32(-1)
        self.assertEqual(float(mad_separate(a, b, c)), 0)
        self.assertEqual(float(mad_fused(a, b, c)), -(2**-46))
        for shift in (-80, -30, 0, 30, 80):
            self.assertEqual(float(mad_fused(a * np.float32(2.0**shift), b,
                                             c * np.float32(2.0**shift))), -(2.0**(shift - 46)))

    def test_fused_avoids_intermediate_overflow_and_rounds_subnormal_ties(self):
        largest = np.finfo(np.float32).max
        with np.errstate(over="ignore"):
            self.assertTrue(np.isinf(mad_separate(largest, 2, -largest)))
        self.assertEqual(float(mad_fused(largest, 2, -largest)), float(largest))
        tiny = np.float32(2**-149)
        np.testing.assert_array_equal(mad_fused([tiny, tiny, -tiny], [.5, 1.5, .5], [0, 0, 0]).view(np.uint32),
                                      [0, 2, 0x80000000])
        self.assertTrue(np.isinf(mad_fused(largest, 2, 0)))
        with self.assertRaises(ValueError):
            mad_fused(np.inf, 1, 0)

    def test_fused_signed_zero_contract(self):
        a = np.array([-0.0, -0.0, 0.0, 1.0], np.float32)
        b = np.ones(4, np.float32)
        c = np.array([-0.0, 0.0, -0.0, -1.0], np.float32)
        np.testing.assert_array_equal(mad_fused(a, b, c).view(np.uint32), [0x80000000, 0, 0, 0])

    def test_float32_reduction_does_not_prematurely_store_half(self):
        values = np.full(4, .3, np.float32)
        correct = dot_f32(values, np.ones(4, np.float32))
        mutant = dot_f32(store_fp16(values, rounding="rtz"), np.ones(4, np.float32))
        self.assertEqual(float(correct), float(np.float32(1.2)))
        self.assertNotEqual(float(correct), float(mutant))
        # Higher-precision arithmetic still lacks the required typed store.
        self.assertNotEqual(float(np.sum(values.astype(np.float64))), float(store_fp16(correct, rounding="rtz")))
        self.assertEqual(f32_add([1], [2]).dtype, np.float32)
        self.assertEqual(f32_mul([1], [2]).dtype, np.float32)

    def test_float_to_integer_has_an_explicit_finite_domain(self):
        np.testing.assert_array_equal(to_uint32([0, -0.0, .9999, 1.999, 4294967040]),
                                      [0, 0, 0, 1, 4294967040])
        np.testing.assert_array_equal(to_int32([-1.9, -.9, 1.9, -(2**31), 2147483520]),
                                      [-1, 0, 1, -(2**31), 2147483520])
        for invalid in (-1, 2**32, np.nan, np.inf, -np.inf):
            with self.assertRaises(ValueError):
                to_uint32(invalid)
        for invalid in (2**31, -(2**31) - 256, np.nan, np.inf):
            with self.assertRaises(ValueError):
                to_int32(invalid)

    def test_lobes_and_alpha_are_independent_and_source_sanitized(self):
        d = store_fp16([[2, 3, 4, -0.0], [.5, 1, 2, 12.25]], rounding="rtz")
        s = store_fp16([[.1, .2, .4, 7.5], [4, 8, 16, .25]], rounding="rtz")
        gain = np.array([.75, 1], np.float32)
        dd, ss = apply_anchor_lobes(d, s, gain, rounding="rtz")
        changed_spec = s.copy()
        changed_spec[..., :3] *= 2
        dd2, _ = apply_anchor_lobes(d, changed_spec, gain, rounding="rtz")
        np.testing.assert_array_equal(dd.view(np.uint32), dd2.view(np.uint32))
        np.testing.assert_array_equal(dd[..., 3].view(np.uint32), d[..., 3].view(np.uint32))
        np.testing.assert_array_equal(ss[..., 3].view(np.uint32), s[..., 3].view(np.uint32))
        changed_lane = d.copy()
        changed_lane[..., 0] = 32
        dd3, _ = apply_anchor_lobes(changed_lane, s, gain, rounding="rtz")
        np.testing.assert_array_equal(dd3[..., 1:], dd[..., 1:])
        d[0, :3] = [np.inf, np.nan, -2]
        clean, _ = apply_anchor_lobes(d, s, gain, rounding="rtz")
        np.testing.assert_array_equal(clean[0, :3], 0)
        d[0, 3] = np.nan
        with self.assertRaises(ValueError):
            apply_anchor_lobes(d, s, gain, rounding="rtz")

    def test_inactive_unused_values_do_not_change_exact_bytes(self):
        rng = np.random.default_rng(7217)
        d = store_fp16(rng.uniform(0, 4, (3, 4, 4)), rounding="rtz")
        s = d[::-1].copy()
        d[0, 0, 3] = -0.0
        for unused_gain, unused_rounding in ((None, "not-read"), (np.nan, "invalid"),
                                             (np.ones(100), "rtz")):
            dd, ss = apply_anchor_lobes(d, s, unused_gain, enabled=False, rounding=unused_rounding)
            np.testing.assert_array_equal(dd.view(np.uint32), d.view(np.uint32))
            np.testing.assert_array_equal(ss.view(np.uint32), s.view(np.uint32))
            self.assertFalse(np.shares_memory(dd, d))


if __name__ == "__main__":
    unittest.main()
