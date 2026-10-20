"""Exact integer carries, immutable support, reset, and bounded missing bits."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from numerical_contract.fixedpoint import (FRACTION_SCALE, FrameSums, compose_uint64,
                                           frame_sum_bounds, quantize_u16_16,
                                           reconstruct_float32, uint64_add_words)
from numerical_contract.storage import NonIdentifiableError, fp16_preimage_f32, store_fp16


class FixedPointContracts(unittest.TestCase):
    def test_native_cap16_is_in_physical_units_and_truncation_is_after_float32(self):
        np.testing.assert_array_equal(quantize_u16_16([-1, 0, 2**-17, 2**-16,
                                                     .5, 1, 16, 100]),
                                      [0, 0, 0, 1, 32768, 65536, 1048576, 1048576])
        for nonfinite in (np.nan, np.inf, -np.inf):
            with self.assertRaises(ValueError):
                quantize_u16_16(nonfinite)

    def test_low_word_carry_and_high_word_wrap_boundary(self):
        self.assertEqual(uint64_add_words(0xfffffffe, 5, 3), (1, 6))
        self.assertEqual(uint64_add_words(0xffffffff, 0xffffffff, 1), (0, 0))
        self.assertEqual(uint64_add_words(0xffffffff, 3, 0), (0xffffffff, 3))
        self.assertEqual(compose_uint64(0x89abcdef, 0x12345678), 0x1234567889abcdef)

    def test_invalid_quantized_observation_does_not_leave_partial_state(self):
        frame = FrameSums().add([1], [.5])
        before = frame.to_bytes()
        for invalid in (-1, np.inf, np.nan, 2**32, .5):
            with self.assertRaises(ValueError):
                frame.add_quantized([4, 7], [2, invalid])
            self.assertEqual(frame.to_bytes(), before)

    def test_natural1440p_grid_multiple_wraps_kills_missing_high_mutant(self):
        cells = (2560 // 8) * (1440 // 8)
        current = np.full(cells, 16, np.float32)
        recalled = np.full(cells, 12, np.float32)
        frame = FrameSums().add(current, recalled)
        expected_current, expected_recalled = cells * 16 * 65536, cells * 12 * 65536
        self.assertEqual(frame.current_total, expected_current)
        self.assertEqual(frame.recalled_total, expected_recalled)
        self.assertEqual(frame.count, cells)
        self.assertGreater(int(frame.words[1]), 1)
        self.assertNotEqual(int(frame.words[0]), expected_current)  # missing high word mutant
        self.assertEqual(float(frame.source_ratio()), .75)
        self.assertEqual(float(frame.source_coverage(cells)), 1)

    def test_seeded_adversarial_atomic_order_and_multiple_wraps(self):
        rng = np.random.default_rng(7217)
        increments = rng.integers(0, 2**32, 8192, dtype=np.uint32)
        initial = 0x12345678ffffffed
        expected = (initial + sum(map(int, increments))) & ((1 << 64) - 1)
        for order in (np.arange(increments.size), rng.permutation(increments.size)):
            low, high = initial & 0xffffffff, initial >> 32
            for index in order:
                low, high = uint64_add_words(low, high, increments[index])
            self.assertEqual(compose_uint64(low, high), expected)

    def test_source_float_reconstruction_can_lose_low_bits_but_integer_total_does_not(self):
        total = (1 << 40) + 12345
        lo, hi = total & 0xffffffff, total >> 32
        self.assertEqual(compose_uint64(lo, hi), total)
        rounded = reconstruct_float32(lo, hi)
        self.assertEqual(rounded.dtype, np.float32)
        self.assertNotEqual(int(rounded), total)
        self.assertLessEqual(abs(int(rounded) - total), int(np.spacing(rounded)) // 2)

    def test_source_reconstruction_monotone_at_low_wrap_in_native_cap_count_domain(self):
        # Native count<=2**32-1, cap increment2**20 => total<2**52. These
        # boundaries include the largest reachable high word and exponent changes.
        for high in (0, 1, 3, 15, 255, 1023, 65535, (1 << 19) - 1, (1 << 20) - 2):
            totals = [(high << 32) + low for low in (0xffffff00, 0xffffff7f, 0xffffff80, 0xffffffff)]
            totals += [((high + 1) << 32) + low for low in (0, 1, 127, 128, 255)]
            values = [float(reconstruct_float32(t & 0xffffffff, t >> 32)) for t in totals]
            self.assertTrue(all(a <= b for a, b in zip(values, values[1:])))
            self.assertEqual(values[3], values[4])

    def test_reset_clears32_bytes_and_partial_reset_mutant_is_detected(self):
        frame = FrameSums([1, 2, 3, 4, 5, 0xdeadbeef, 0x12345678, 0xffffffff])
        self.assertEqual(len(frame.to_bytes()), 32)
        clone = FrameSums.from_bytes(frame.to_bytes())
        np.testing.assert_array_equal(clone.words, frame.words)
        clone.words[:4] = 0
        self.assertNotEqual(clone.to_bytes(), bytes(32))
        frame.reset()
        self.assertEqual(frame.to_bytes(), bytes(32))
        self.assertEqual(float(frame.source_ratio()), 1)
        with self.assertRaises(ValueError):
            FrameSums.from_bytes(bytes(16))

    def test_support_count_gate_and_independent_channels_are_preserved(self):
        c = np.array([1, np.nan, 2, np.inf], np.float32)
        r = np.array([.5, np.inf, 1, np.nan], np.float32)
        support = np.array([True, False, True, False])
        saved = support.copy()
        frame = FrameSums().add(c, r, support=support)
        self.assertEqual(frame.current_total, 3 * FRACTION_SCALE)
        self.assertEqual(frame.recalled_total, int(1.5 * FRACTION_SCALE))
        self.assertEqual(frame.count, 2)
        np.testing.assert_array_equal(support, saved)
        c[~support], r[~support] = -20, 1e30
        other = FrameSums().add(c, r, support=support)
        self.assertEqual(other.to_bytes(), frame.to_bytes())
        zero_levels = FrameSums().add([0, 0], [0, 0])
        self.assertEqual(zero_levels.count, 2)
        self.assertEqual(float(zero_levels.source_ratio()), 1)
        wrapped_count = FrameSums([0, 0, 0, 0, 0xffffffff, 0, 0, 0]).add([1], [.5])
        self.assertEqual(wrapped_count.count, 0)
        self.assertEqual(float(wrapped_count.source_ratio()), 1)

    def test_identical_stored_halves_admit_distinct_valid_atomic_results(self):
        for rounding in ("rne", "rtz"):
            bin_ = fp16_preimage_f32(np.array([1], np.float32), rounding=rounding)
            low, high = bin_.lower, bin_.upper
            np.testing.assert_array_equal(store_fp16(low, rounding=rounding), [1])
            np.testing.assert_array_equal(store_fp16(high, rounding=rounding), [1])
            self.assertNotEqual(int(quantize_u16_16(low)[0]), int(quantize_u16_16(high)[0]))
            bounds = frame_sum_bounds([1], [1], [True], rounding=rounding)
            with self.assertRaises(NonIdentifiableError):
                bounds.require_exact_totals()
            self.assertLess(bounds.ratio_interval()[0], 1)
            self.assertGreater(bounds.ratio_interval()[1], 1)

    def test_only_proven_singleton_totals_can_be_returned_as_exact(self):
        bounds = frame_sum_bounds([32, -1], [32, -2], [True, True], rounding="rne")
        self.assertEqual(bounds.require_exact_totals(), (16 * 65536, 16 * 65536, 2))
        self.assertEqual(bounds.ratio_interval(), (1, 1))
        empty = frame_sum_bounds([np.nan], [np.nan], [False])
        self.assertEqual(empty.require_exact_totals(), (0, 0, 0))
        self.assertEqual(empty.ratio_interval(), (1, 1))

    def test_seeded_real_prestore_totals_and_ratio_are_inside_conditional_envelope(self):
        rng = np.random.default_rng(20261020)
        current = rng.uniform(-.5, 32, (31, 29)).astype(np.float32)
        recalled = rng.uniform(-.5, 32, (31, 29)).astype(np.float32)
        support = rng.random(current.shape) > .25
        frame = FrameSums().add(current, recalled, support=support)
        for rounding in ("rne", "rtz"):
            bounds = frame_sum_bounds(store_fp16(current, rounding=rounding),
                                      store_fp16(recalled, rounding=rounding), support,
                                      rounding=rounding)
            self.assertLessEqual(bounds.current_min, frame.current_total)
            self.assertGreaterEqual(bounds.current_max, frame.current_total)
            self.assertLessEqual(bounds.recalled_min, frame.recalled_total)
            self.assertGreaterEqual(bounds.recalled_max, frame.recalled_total)
            lo, hi = bounds.ratio_interval()
            self.assertLessEqual(lo, float(frame.source_ratio()))
            self.assertGreaterEqual(hi, float(frame.source_ratio()))


if __name__ == "__main__":
    unittest.main()
