"""Payload closure is exact; geometric similarity does not imply byte identity."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from numerical_contract.encoding import (angular_error_degrees, octahedral_decode,
                                          octahedral_encode, pack_normal11,
                                          pack_normal16_old, unpack_normal11,
                                          unpack_normal16_old)
from numerical_contract.storage import store_fp16


class EncodingContracts(unittest.TestCase):
    def test_all2048_codes_close_before_and_after_each_half_store(self):
        codes = np.arange(2048, dtype=np.float32)
        uv = unpack_normal11(codes)
        np.testing.assert_array_equal(pack_normal11(uv), codes)
        for rounding in ("rne", "rtz"):
            with self.subTest(rounding=rounding):
                stored = store_fp16(codes, rounding=rounding)
                np.testing.assert_array_equal(stored, codes)
                np.testing.assert_array_equal(pack_normal11(unpack_normal11(stored)), codes)
        normal = octahedral_decode(uv)
        self.assertTrue(np.isfinite(normal).all())
        np.testing.assert_allclose(np.linalg.norm(normal.astype(np.float64), axis=-1), 1,
                                   rtol=0, atol=1.5e-7)

    def test_distinct_south_pole_codes_must_not_be_collapsed_for_byte_closure(self):
        codes = np.array([0, 31, 2016, 2047], np.float32)
        normal = octahedral_decode(unpack_normal11(codes))
        np.testing.assert_array_equal(normal, np.tile([0, 0, -1], (4, 1)))
        canonical = pack_normal11(octahedral_encode(normal))
        np.testing.assert_array_equal(canonical, 0)
        self.assertEqual(int(np.count_nonzero(canonical != codes)), 3)
        np.testing.assert_array_equal(pack_normal11(unpack_normal11(codes)), codes)

    def test_fold_axes_hemisphere_boundaries_and_zero_vectors(self):
        eps = np.float32(2**-15)
        normal = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0],
                           [0, 0, 1], [0, 0, -1], [1, 1, eps], [1, 1, -eps],
                           [-1, 1, eps], [-1, 1, -eps], [-0.0, 0, -1]], np.float32)
        encoded = octahedral_encode(normal)
        decoded = octahedral_decode(encoded)
        self.assertLess(float(angular_error_degrees(normal, decoded).max()), .001)
        self.assertLess(float(angular_error_degrees(normal,
                           octahedral_decode(unpack_normal11(pack_normal11(encoded)))).max()), 8)
        for invalid in ([0, 0, 0], [np.nan, 1, 0], [np.inf, 0, 1]):
            with self.assertRaises(ValueError):
                octahedral_encode(invalid)
            self.assertTrue(np.isnan(octahedral_encode(invalid, degenerate="nan")).all())

    def test_seeded_normal_field_has_bounded_quantization_and_channel_order(self):
        rng = np.random.default_rng(20261020)
        n = rng.normal(size=(12000, 3)).astype(np.float32)
        uv = octahedral_encode(n)
        packed = pack_normal11(uv)
        decoded = octahedral_decode(unpack_normal11(packed))
        # A conservative bound fixed before inspecting this holdout, not a
        # threshold picked from the maximum of the sample.
        self.assertLess(float(angular_error_degrees(n, decoded).max()), 8)
        # The X/Y bit depths and stride are not interchangeable.
        np.testing.assert_array_equal(pack_normal11([[1, 0], [0, 1], [1, 1], [-5, 4]]),
                                      [2016, 31, 2047, 31])

    def test_old_normalized16_mutant_loses_payloads_exhaustively(self):
        codes = np.arange(65536, dtype=np.float32)
        uv = np.stack([np.floor(codes / 256), codes % 256], -1) / np.float32(255)
        payload = pack_normal16_old(uv)
        for rounding, failures in (("rne", 58367), ("rtz", 59383)):
            stored = store_fp16(payload, rounding=rounding)
            restored = np.floor(stored * np.float32(65535) + np.float32(.5))
            self.assertEqual(int(np.count_nonzero(restored != codes)), failures)
            old_normals = octahedral_decode(unpack_normal16_old(stored))
            original_normals = octahedral_decode(uv)
            angle = angular_error_degrees(original_normals, old_normals)
            self.assertGreater(float(angle.max()), 5)

    def test_rejects_invalid_payloads_instead_of_inventing_guides(self):
        for p in (-1, 2048, .5, np.nan, np.inf):
            with self.assertRaises(ValueError):
                unpack_normal11(p)
        for uv in ([np.nan, 0], [np.inf, 0]):
            with self.assertRaises(ValueError):
                pack_normal11(uv)
        for uv in ([-1, 0], [0, 2], [np.nan, 0]):
            with self.assertRaises(ValueError):
                octahedral_decode(uv)


if __name__ == "__main__":
    unittest.main()
