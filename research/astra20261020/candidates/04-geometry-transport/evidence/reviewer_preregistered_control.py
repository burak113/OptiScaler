"""Independent, preregistered falsifiers; these do not import candidate code.

The tests assert that a deliberately wrong control violates a numerical
invariant. Passing is evidence of sensitivity, not acceptance of that control.
"""
from __future__ import annotations

import unittest
import numpy as np


def known_bad_grid_identity():
    """Exact ideal-linear analogue of shared Apply, not a D3D sampler claim."""
    width, cell = 16, 8
    pixel = np.arange(width, dtype=np.float64)
    coarse = np.array([0.6, 1.0])
    coord = (pixel + 0.5) / cell - 0.5
    lo = np.floor(coord).astype(np.int64)
    frac = coord - lo
    # Clamping here deliberately reproduces the bad baseline, not valid history.
    gain = coarse[np.clip(lo, 0, 1)] * (1-frac) + coarse[np.clip(lo+1, 0, 1)] * frac
    protected = pixel >= 8
    return {
        "width": width, "cell_size": cell,
        "coarse_gain": coarse.tolist(),
        "protected_pixel_mask": protected.tolist(),
        "full_pixel_gain": gain.tolist(),
        "coarse_moving_cell_gain": float(coarse[1]),
        "protected_max_abs_spill": float(np.max(np.abs(gain[protected] - 1))),
        "protected_mean_abs_spill": float(np.mean(np.abs(gain[protected] - 1))),
        "protected_affected_count": int(np.count_nonzero(gain[protected] != 1)),
    }


class PreregisteredMutantSensitivity(unittest.TestCase):
    def test_grid_identity_does_not_imply_full_pixel_identity(self):
        bad = known_bad_grid_identity()
        self.assertEqual(bad["coarse_moving_cell_gain"], 1.0)
        self.assertAlmostEqual(bad["protected_max_abs_spill"], 0.175)
        self.assertEqual(bad["protected_affected_count"], 4)

    def test_missing_and_double_jitter_fail_signed_phase(self):
        # Convention: add current raster jitter to unproject; subtract old jitter
        # after projection. This is an explicitly chosen mathematical oracle.
        p = np.array([13., 5.])
        current_jitter = np.array([.25, -.375])
        previous_jitter = np.array([-.375, .125])
        delta = current_jitter - previous_jitter
        expected = p + delta
        missing = p.copy()
        double = p + 2*delta
        self.assertGreater(np.linalg.norm(missing-expected), .5)
        self.assertGreater(np.linalg.norm(double-expected), .5)
        np.testing.assert_allclose(missing-expected, -delta)
        np.testing.assert_allclose(double-expected, delta)

    def test_reversed_mv_fails_known_translation(self):
        p = np.array([18., 9.])
        previous = p + np.array([-3., 2.])
        wrong = p - np.array([-3., 2.])
        self.assertGreater(np.linalg.norm(wrong-previous), 7.)

    def test_roi_render_scale_and_crop_origin_are_not_interchangeable(self):
        p = np.array([4., 2.])
        mv = np.array([.01, -.02])
        render = np.array([1920., 1080.])
        roi = np.array([128., 64.])
        current_origin, previous_origin = np.array([300., 200.]), np.array([302., 197.])
        expected = p + current_origin + mv*render - previous_origin
        wrong = p + current_origin + mv*roi - previous_origin
        self.assertGreater(np.linalg.norm(expected-wrong), 25.)
        self.assertGreater(np.linalg.norm(expected-(p+mv*render)), 3.)

    def test_transposed_column_transform_fails_rigid_location(self):
        # Row-major ndarray storage does NOT alter column-vector mathematics.
        matrix = np.eye(4)
        matrix[:3, 3] = [2., -1., .5]
        p = np.array([1., 2., 4., 1.])
        expected = np.array([3., 1., 4.5, 1.])
        np.testing.assert_allclose(matrix @ p, expected)
        self.assertGreater(np.linalg.norm(matrix.T @ p-expected), 2.)

    def test_native_absolute_depth_cannot_be_compared_to_signed_rh_depth(self):
        view_z = -4.
        stored_key_depth = abs(view_z)
        correct_relative_error = abs(stored_key_depth-abs(view_z))/stored_key_depth
        mutant_relative_error = abs(stored_key_depth-view_z)/stored_key_depth
        self.assertEqual(correct_relative_error, 0.)
        self.assertEqual(mutant_relative_error, 2.)

    def test_active_and_allocation_extent_are_not_same_coordinate_system(self):
        p = np.array([16., 8.])
        active = np.array([17., 9.])
        allocation = np.array([24., 16.])
        correct_uv = (p+.5)/active
        wrong_uv = (p+.5)/allocation
        error_in_active_pixels = (wrong_uv-correct_uv)*active
        self.assertGreater(np.linalg.norm(error_in_active_pixels), 6.)

    def test_out_of_domain_clamp_manufactures_history(self):
        x = np.array([-1.25, -.01, 0., 4., 4.01, 5.])
        valid = (x >= 0.) & (x <= 4.)
        clamped = np.clip(x, 0., 4.)
        mutant_valid = (clamped >= 0.) & (clamped <= 4.)
        self.assertEqual(int(np.count_nonzero(mutant_valid & ~valid)), 4)


if __name__ == "__main__":
    unittest.main()
