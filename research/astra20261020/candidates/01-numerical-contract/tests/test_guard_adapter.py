"""Independent preservation/falsifier tests for the proposed finite-depth guard.

These tests own no production code or candidate implementation. All-finite
FP16 resource inputs and finite-F32 overflow interventions are distinct cases.
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from numerical_contract import guards


class UnusedPoison:
    def __array__(self, dtype=None, copy=None):
        raise AssertionError("inactive option read an unused resource")


class GuardAdapterReviewTests(unittest.TestCase):
    def test_actual_r16_infinite_expected_falsifier(self):
        # These are actual half payloads, not a finite-F32 overflow fiction.
        current = np.array([0x7c00,0xfc00,0x3c00,0x3c00,0x3c00,0x7e00],np.uint16).view(np.float16).astype(np.float32)
        motion = np.array([0x0000,0x0000,0x7c00,0x0000,0x0000,0x0000],np.uint16).view(np.float16).astype(np.float32)
        history = np.array([0x3c00,0xbc00,0x3c00,0x3c00,0x4000,0x3c00],np.uint16).view(np.float16).astype(np.float32)
        uv = np.full((6,2),.5,np.float32)
        original = guards.colour_history_valid(history,current,motion,uv)
        guarded = guards.colour_history_valid_finite(history,current,motion,uv)
        np.testing.assert_array_equal(original,[True,True,True,True,False,False])
        np.testing.assert_array_equal(guarded,[False,False,False,True,False,False])

    def test_exhaustive_finite_half_population_is_preserved(self):
        payloads = np.arange(65536,dtype=np.uint16).view(np.float16).astype(np.float32)
        current = payloads[np.isfinite(payloads)]
        self.assertEqual(current.size,63488)
        uv = np.full(current.shape+(2,),.5,np.float32)
        for motion_value in (0.,2**-10,-2**-10,65504.):
            motion = np.full_like(current,motion_value)
            self.assertTrue(np.all(np.isfinite(current+motion)))
            source = guards.colour_history_valid(current,current,motion,uv)
            candidate = guards.colour_history_valid_finite(current,current,motion,uv)
            np.testing.assert_array_equal(candidate,source)

    def test_seeded_finite_half_and_sampled_history_preservation(self):
        rng = np.random.default_rng(2026102031)
        half = np.arange(65536,dtype=np.uint16).view(np.float16).astype(np.float32)
        finite_half = half[np.isfinite(half)]
        current = rng.choice(finite_half,4096)
        motion = rng.choice(finite_half,4096)
        # SampleLevel may return float32 interpolation between half texels.
        endpoints = rng.choice(finite_half,(4096,2)).astype(np.float64)
        phase = rng.integers(0,257,4096)/256
        history = ((1-phase)*endpoints[:,0]+phase*endpoints[:,1]).astype(np.float32)
        uv = rng.uniform(-.125,1.125,size=(4096,2)).astype(np.float32)
        self.assertTrue(np.all(np.isfinite(current+motion)))
        np.testing.assert_array_equal(
            guards.colour_history_valid_finite(history,current,motion,uv),
            guards.colour_history_valid(history,current,motion,uv))

    def test_inclusive_host_tolerance_and_signed_depth_are_preserved(self):
        # float32(.02)*50 is exactly 1, so <= versus < is distinguishable
        # at the actual host tolerance using half-representable depths.
        current = np.array([50,50,50,-50,-50,-50],np.float32)
        history = np.array([np.nextafter(np.float32(51),np.float32(0)),51,
                            np.nextafter(np.float32(51),np.float32(np.inf)),
                            np.nextafter(np.float32(-51),np.float32(0)),-51,
                            np.nextafter(np.float32(-51),np.float32(-np.inf))],np.float32)
        motion = np.zeros_like(current)
        uv = np.full((6,2),.5,np.float32)
        expected = [True,True,False,True,True,False]
        np.testing.assert_array_equal(guards.colour_history_valid(history,current,motion,uv),expected)
        np.testing.assert_array_equal(guards.colour_history_valid_finite(history,current,motion,uv),expected)
        wrong_strict = abs(history-current) < np.float32(.02)*abs(current)
        self.assertFalse(bool(wrong_strict[1]))
        self.assertFalse(bool(wrong_strict[4]))

    def test_inactive_history_does_not_read_unused_inputs(self):
        current = np.array([0,1,-1,np.inf,np.nan],np.float32)
        for predicate in (guards.colour_history_valid,guards.colour_history_valid_finite):
            result = predicate(UnusedPoison(),current,UnusedPoison(),UnusedPoison(),history_enabled=False)
            np.testing.assert_array_equal(result,np.zeros(current.shape,bool))

    def test_finite_float32_overflow_is_explicitly_arithmetic_only(self):
        # Not attainable from two finite production R16 stored inputs.
        largest = np.finfo(np.float32).max
        current = np.array([largest,-largest],np.float32)
        motion = current.copy()
        history = np.array([1,-1],np.float32)
        uv = np.full((2,2),.5,np.float32)
        with np.errstate(over="ignore",invalid="ignore"):
            np.testing.assert_array_equal(guards.colour_history_valid(history,current,motion,uv),[True,True])
            np.testing.assert_array_equal(guards.colour_history_valid_finite(history,current,motion,uv),[False,False])
            # Double precision removes the overflow, but is not HLSL parity.
            np.testing.assert_array_equal(guards.colour_history_valid(history,current,motion,uv,dtype=np.float64),[False,False])

    def test_nonfinite_history_and_viewport_remain_invalid(self):
        current = np.ones(6,np.float32)
        history = np.array([np.inf,-np.inf,np.nan,1,1,0],np.float32)
        motion = np.zeros(6,np.float32)
        uv = np.array([[.5,.5],[.5,.5],[.5,.5],[-1e-6,.5],[.5,1.000001],[.5,.5]],np.float32)
        for predicate in (guards.colour_history_valid,guards.colour_history_valid_finite):
            self.assertFalse(np.any(predicate(history,current,motion,uv)))

    def test_current_source_authority_still_ignores_unused_gain(self):
        colour = np.array([[.25,.5,1,-0.]],np.float32)
        actual = guards.colour_apply_pixel(colour,UnusedPoison(),np.array([0],np.float32))
        np.testing.assert_array_equal(actual.view(np.uint32),colour.view(np.uint32))

    def test_gpu_inputs_are_json_safe_and_multiple_wraps_are_exact(self):
        spec = importlib.util.spec_from_file_location("_guard_review_gpu_inputs",ROOT/"gpu_inputs.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        summary,arrays = module.microcases()
        json.dumps(summary,allow_nan=False)
        for row in summary["sum_cases"]:
            total = row["expected_count"]*row["expected_increment"]
            words = row["expected_words"]
            self.assertEqual(words[0]+(words[1]<<32),total)
            self.assertEqual(words[2]+(words[3]<<32),total)
            self.assertEqual(words[4],row["expected_count"])
            self.assertEqual(words[5:],[0,0,0])
            self.assertEqual(bytes.fromhex(row["expected_32_bytes_hex"]),np.array(words,dtype="<u4").tobytes())
        self.assertGreater(summary["sum_cases"][-1]["low_word_wraps"],1)
        self.assertEqual(len(bytes.fromhex(summary["reset_expected_32_bytes_hex"])),32)
        self.assertEqual(arrays["depth_texture"].dtype,np.dtype(np.float16))
        self.assertTrue(np.all(np.isfinite(arrays["depth_texture"])))
        self.assertEqual(summary["phase_sweep"]["samples"],arrays["phase_uv"].shape[0])


if __name__ == "__main__":
    unittest.main()
