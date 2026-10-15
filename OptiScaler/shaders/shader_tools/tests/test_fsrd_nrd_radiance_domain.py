"""CPU loss/identity controls for the new radiance-domain preparation only."""
import unittest
import numpy as np
from fsrd_nrd_radiance_domain_replay import DEFAULT_REPLAY, canonical_metrics, normalize_output, scale_signal, source_module
from fsrd_nrd_radiance_unit_source import V3_SCALES, convert_signal


class RadianceScaleContracts(unittest.TestCase):
    def test_all_alpha_words_are_preserved_for_every_scale(self):
        source = np.ones((256, 256, 4), '<f2')
        source[..., 1] = 2
        source[..., 2] = 3
        source.view(np.uint16)[..., 3] = np.arange(65536, dtype=np.uint16).reshape(256, 256)
        before = source.tobytes()
        for scale in (.25, 1, 4, 16, 64, 256):
            result, stats = scale_signal(source, scale)
            self.assertEqual(source.tobytes(), before)
            self.assertTrue(np.array_equal(source.view(np.uint16)[..., 3], result.view(np.uint16)[..., 3]))
            self.assertTrue(np.array_equal(result[..., :3].astype(np.float32) / scale, source[..., :3]))
            self.assertEqual(stats['inverse_roundtrip_mismatches'], 0)

    def test_overflow_is_rejected_without_clipping(self):
        source = np.ones((1, 1, 4), '<f2')
        source[0, 0, 0] = 65504
        with self.assertRaisesRegex(AssertionError, 'overflow'):
            scale_signal(source, 4)

    def test_nonzero_to_zero_underflow_rejects_whole_candidate(self):
        source = np.ones((1, 1, 4), '<f2')
        source.view(np.uint16)[0, 0, 0] = 1
        with self.assertRaisesRegex(AssertionError, 'underflow'):
            scale_signal(source, .25)

    def test_lossy_nonzero_subnormal_is_rejected(self):
        source = np.ones((1, 1, 4), '<f2')
        source.view(np.uint16)[0, 0, 0] = 5
        with self.assertRaisesRegex(AssertionError, 'restores exactly'):
            scale_signal(source, .25)

    def test_exact_nonzero_subnormal_is_admitted_and_disclosed(self):
        source = np.ones((1, 1, 4), '<f2')
        source[0, 0, 0] = 2**-13
        result, stats = scale_signal(source, .25)
        self.assertEqual(float(result[0, 0, 0]), 2**-15)
        self.assertEqual(stats['exact_nonzero_subnormal_components'], 1)

    def test_unknown_scale_and_invalid_rgb_fail_closed(self):
        source = np.ones((1, 1, 4), '<f2')
        with self.assertRaises(AssertionError):
            scale_signal(source, 3)
        for invalid in (np.nan, np.inf, -1):
            source[0, 0, 0] = invalid
            with self.assertRaisesRegex(AssertionError, 'finite nonnegative'):
                scale_signal(source, 1)

    def test_actual_output_inverse_precedes_metrics_and_keeps_alpha(self):
        source = np.array([[[.125, 2, 12, 1000], [4, .25, 1, 13]]], '<f2')
        for scale in (.25, 1, 4, 16, 64, 256):
            raw, _ = scale_signal(source, scale)
            normalized = normalize_output(raw, scale)
            self.assertEqual(normalized.dtype, np.dtype(np.float64))
            self.assertTrue(np.array_equal(normalized, source.astype(np.float64)))

    def test_v3_first_quantization_is_disclosed_then_every_upscale_is_exact(self):
        source = np.ones((1, 4, 4), '<f2')
        source.view(np.uint16)[0, :, 0] = [1, 5, 65, 0x2001]
        source.view(np.uint16)[0, :, 3] = [0x7e21, 0x8000, 0x3c00, 0x7c00]
        before = source.tobytes()
        unit, stats = convert_signal(source)
        expected = (source[..., :3].astype(np.float64) / 64).astype(np.float16)
        self.assertTrue(np.array_equal(unit.view(np.uint16)[..., :3], expected.view(np.uint16)))
        self.assertGreater(stats['changed_rgb_components'], 0)
        self.assertGreater(stats['nonzero_to_zero_components'], 0)
        self.assertGreater(stats['max_absolute_v1_unit_roundtrip_error'], 0)
        self.assertEqual(source.tobytes(), before)
        for scale in V3_SCALES:
            scaled, _ = scale_signal(unit, scale)
            self.assertTrue(np.array_equal(scaled[..., :3].astype(np.float32) / scale, unit[..., :3]))
            self.assertTrue(np.array_equal(scaled.view(np.uint16)[..., 3], source.view(np.uint16)[..., 3]))

    def test_unchanged_oracle_reveal_support_uses_common_units(self):
        replay = source_module(DEFAULT_REPLAY, '_radiance_unit_support_oracle')
        output = np.full((2, 2, 3), .001, np.float64)
        reference = np.zeros((2, 2, 3), np.float64)
        ghost = np.full((2, 2, 3), .004, np.float64)
        age = np.zeros((2, 2), np.uint8)
        crop = [0, 0, 2, 2]
        original = canonical_metrics(replay, output, reference, age, ghost, crop, 1)
        wrong_units = replay.metrics(output / 64, reference / 64, age, ghost / 64, crop)
        corrected = canonical_metrics(replay, output / 64, reference / 64, age, ghost / 64, crop, 64)
        self.assertEqual(original['reveal_tail']['0']['pixels'], 4)
        self.assertNotIn('0', wrong_units['reveal_tail'])
        self.assertEqual(corrected, original)


if __name__ == '__main__':
    unittest.main()
