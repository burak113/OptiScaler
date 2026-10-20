"""Independent review contracts specified before reading candidate results.

These expectations follow analytic coordinates and the package data contract;
they are not copied from the candidate implementation.
"""
from pathlib import Path
import sys
import unittest

import numpy as np

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from support_tracer import abstain_identity, previous_coordinates, sample_previous


class IndependentCoordinateContracts(unittest.TestCase):
    def test_physical_backward_motion_and_moving_crop_cancel(self):
        mv = np.zeros((7, 9, 4), dtype=np.float64)
        mv[..., :2] = [-8/1024, -4/512]
        qx, qy, valid = previous_coordinates(
            mv, (108, 204), (100, 200), (1024, 512))
        yy, xx = np.mgrid[:7, :9]
        np.testing.assert_array_equal(qx, xx)
        np.testing.assert_array_equal(qy, yy)
        expected = (xx < 8) & (yy < 6)
        np.testing.assert_array_equal(valid, expected)

    def test_displacement_uses_full_render_extent_not_crop(self):
        mv = np.zeros((7, 9, 4), dtype=np.float64)
        mv[..., :2] = [-1/1024, 2/512]
        qx, qy, valid = previous_coordinates(
            mv, (100, 200), (100, 200), (1024, 512))
        yy, xx = np.mgrid[:7, :9]
        np.testing.assert_array_equal(qx, xx-1)
        np.testing.assert_array_equal(qy, yy+2)
        expected = (xx >= 1) & (yy < 4)
        np.testing.assert_array_equal(valid, expected)

    def test_different_previous_extent_is_not_current_extent(self):
        mv = np.zeros((7, 9, 4), dtype=np.float64)
        qx, qy, valid = previous_coordinates(
            mv, (0, 0), (0, 0), (1024, 512), previous_shape=(5, 6))
        yy, xx = np.mgrid[:7, :9]
        np.testing.assert_array_equal(valid, (xx < 5) & (yy < 4))

    def test_outside_and_nonfinite_samples_are_unknown(self):
        image = np.arange(30, dtype=np.float32).reshape(5, 6)
        qx = np.array([[-.01, 5., np.nan, np.inf, 1.5]])
        qy = np.array([[2., 2., 2., 2., 2.5]])
        sampled, valid = sample_previous(image, qx, qy)
        np.testing.assert_array_equal(valid, [[False, False, False, False, True]])
        self.assertTrue(np.isnan(sampled[~valid]).all())
        self.assertEqual(float(sampled[0, 4]), 16.5)

    def test_bilinear_ramp_matches_analytic_value(self):
        yy, xx = np.mgrid[:11, :17]
        image = 3*xx + 7*yy + 11
        qx = np.array([[.25, 3.75, 14.125]])
        qy = np.array([[1.5, 8.125, 5.875]])
        sampled, valid = sample_previous(image, qx, qy)
        self.assertTrue(valid.all())
        np.testing.assert_allclose(sampled, 3*qx+7*qy+11, rtol=0, atol=0)


class IndependentPreservationContracts(unittest.TestCase):
    def test_identity_preserves_fp16_words_and_alpha(self):
        # Signed zero, smallest positive/negative subnormal, and max finite.
        words = np.array([
            [0x8000, 0x0001, 0x3c00, 0x7bff],
            [0x0000, 0x8001, 0x3800, 0x0400],
        ], dtype=np.uint16).reshape(1, 2, 4)
        selected = words.view(np.float16)
        before = selected.tobytes()
        result = abstain_identity(selected)
        self.assertEqual(selected.tobytes(), before)
        self.assertEqual(result.dtype, selected.dtype)
        self.assertEqual(result.shape, selected.shape)
        self.assertEqual(result.tobytes(), before)


if __name__ == '__main__':
    unittest.main()
