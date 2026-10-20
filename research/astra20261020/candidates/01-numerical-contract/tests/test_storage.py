"""FP16 edge, exhaustive-payload, and pre-store identifiability checks."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from numerical_contract.storage import fp16_bits, fp16_preimage_f32, sanitize_radiance, store_fp16


class StorageContracts(unittest.TestCase):
    def test_rne_halfway_parity_and_rtz_signed_magnitudes(self):
        v = np.array([1 + 2**-11, 1 + 3 * 2**-11,
                      -1 - 2**-11, -1 - 3 * 2**-11], np.float32)
        np.testing.assert_array_equal(fp16_bits(v, rounding="rne"), [0x3c00, 0x3c02, 0xbc00, 0xbc02])
        np.testing.assert_array_equal(fp16_bits(v, rounding="rtz"), [0x3c00, 0x3c01, 0xbc00, 0xbc01])

    def test_signed_zero_subnormal_and_flush_are_separate_policies(self):
        minimum = np.float32(2**-24)
        midpoint = np.float32(2**-25)
        v = np.array([0, midpoint, np.nextafter(midpoint, np.float32(np.inf)),
                      minimum, minimum * np.float32(1.5)], np.float32)
        for sign in (1, -1):
            signed = v * np.float32(sign)
            sign_bits = 0 if sign == 1 else 0x8000
            np.testing.assert_array_equal(fp16_bits(signed, rounding="rne"),
                                          np.array([0, 0, 1, 1, 2], np.uint16) | sign_bits)
            np.testing.assert_array_equal(fp16_bits(signed, rounding="rtz"),
                                          np.array([0, 0, 0, 1, 1], np.uint16) | sign_bits)
            np.testing.assert_array_equal(fp16_bits(signed, subnormals="flush"), sign_bits)

    def test_overflow_finite_saturation_and_source_sanitizer(self):
        v = np.array([65504, 65519, 65520, 70000, np.finfo(np.float32).max], np.float32)
        np.testing.assert_array_equal(fp16_bits(v, rounding="rtz"), 0x7bff)
        np.testing.assert_array_equal(fp16_bits(-v, rounding="rtz"), 0xfbff)
        np.testing.assert_array_equal(fp16_bits(v, rounding="rne"), [0x7bff, 0x7bff, 0x7c00, 0x7c00, 0x7c00])
        np.testing.assert_array_equal(fp16_bits(v, overflow="saturate"), 0x7bff)
        np.testing.assert_array_equal(fp16_bits([np.inf, -np.inf], overflow="saturate"), [0x7c00, 0xfc00])
        sanitized = sanitize_radiance([-1, 70000, np.inf, -np.inf, np.nan, .3])
        np.testing.assert_array_equal(sanitized, np.array([0, 65500, 0, 0, 0, .3], np.float32))
        self.assertEqual(float(store_fp16(sanitized[1], rounding="rtz")), 65472)
        self.assertEqual(float(store_fp16(sanitized[1], rounding="rne")), 65504)

    def test_canonical_nan_is_a_declared_model_and_not_a_claim_of_gpu_payload(self):
        data = np.array([0x7f800001, 0xffdabcde, 0x7fc00000], np.uint32).view(np.float32)
        for rounding in ("rne", "rtz"):
            np.testing.assert_array_equal(fp16_bits(data, rounding=rounding), [0x7e00, 0xfe00, 0x7e00])
            self.assertTrue(np.isnan(store_fp16(data, rounding=rounding)).all())

    def test_float32_input_staging_is_explicit(self):
        # Float64 is just above a half midpoint but its float32 value is the tie.
        v = np.float64(1 + 2**-11 + 2**-30)
        self.assertGreater(v, float(np.float32(v)))
        self.assertEqual(int(fp16_bits(v, rounding="rne")), 0x3c00)

    def test_every_finite_payload_and_preimage_endpoint(self):
        bits = np.arange(65536, dtype=np.uint16)
        bits = bits[(bits & 0x7c00) != 0x7c00]
        self.assertEqual(bits.size, 63488)
        v = bits.view(np.float16).astype(np.float32)
        for rounding in ("rne", "rtz"):
            with self.subTest(rounding=rounding):
                np.testing.assert_array_equal(fp16_bits(v, rounding=rounding), bits)
                bound = fp16_preimage_f32(v, rounding=rounding)
                np.testing.assert_array_equal(fp16_bits(bound.lower, rounding=rounding), bits)
                np.testing.assert_array_equal(fp16_bits(bound.upper, rounding=rounding), bits)
                self.assertTrue(bound.contains(bound.lower).all())
                self.assertTrue(bound.contains(bound.upper).all())
                with np.errstate(over="ignore"):
                    outside_lo = np.nextafter(bound.lower, np.float32(-np.inf))
                    outside_hi = np.nextafter(bound.upper, np.float32(np.inf))
                self.assertFalse(np.any(fp16_bits(outside_lo, rounding=rounding) == bits))
                self.assertFalse(np.any(fp16_bits(outside_hi, rounding=rounding) == bits))

    def test_preimage_distinguishes_zero_sign_and_tie_ownership(self):
        positive_zero = fp16_preimage_f32(np.float32(0), rounding="rne")
        negative_zero = fp16_preimage_f32(np.float32(-0.0), rounding="rne")
        self.assertFalse(bool(positive_zero.contains(np.float32(-0.0))))
        self.assertFalse(bool(negative_zero.contains(np.float32(0.0))))
        even = fp16_preimage_f32(np.float32(1), rounding="rne")
        odd_value = np.array(0x3c01, np.uint16).view(np.float16).astype(np.float32)
        odd = fp16_preimage_f32(odd_value, rounding="rne")
        self.assertEqual(float(even.upper), 1 + 2**-11)
        self.assertEqual(float(odd.lower), float(np.nextafter(even.upper, np.float32(np.inf))))

    def test_seeded_float32_bit_population_is_contained_and_rtz_never_overshoots(self):
        rng = np.random.default_rng(20261020)
        raw = rng.integers(0, 2**32, size=50000, dtype=np.uint32)
        v = raw.view(np.float32)
        v = v[np.isfinite(v)]
        q = store_fp16(v, rounding="rtz")
        self.assertTrue(np.all(np.abs(q) <= np.abs(v)))
        np.testing.assert_array_equal(np.signbit(q), np.signbit(v))
        np.testing.assert_array_equal(fp16_bits(q, rounding="rtz"), fp16_bits(v, rounding="rtz"))
        for rounding in ("rne", "rtz"):
            q = store_fp16(v, rounding=rounding)
            finite = np.isfinite(q)
            self.assertTrue(fp16_preimage_f32(q[finite], rounding=rounding).contains(v[finite]).all())

    def test_unestablished_preimages_and_modes_are_rejected(self):
        for invalid in (.3, np.inf, -np.inf, np.nan):
            with self.assertRaises(ValueError):
                fp16_preimage_f32(invalid)
        for kwargs in ({"rounding": "device"}, {"overflow": "magic"}, {"subnormals": "auto"}):
            with self.assertRaises(ValueError):
                fp16_bits([1], **kwargs)


if __name__ == "__main__":
    unittest.main()
