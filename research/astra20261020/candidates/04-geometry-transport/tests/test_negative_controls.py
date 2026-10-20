"""Independent, preregistered falsifiers; these do not import candidate code.

The tests assert that a deliberately wrong control violates a numerical
invariant. Passing is evidence of sensitivity, not acceptance of that control.
"""
from __future__ import annotations

import unittest
from pathlib import Path
import sys
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


class PublicAPIIndependentFalsifiers(unittest.TestCase):
    """Challenge candidate APIs against the preregistered independent oracles."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import transport
        import history
        cls.t, cls.history = transport, history

    def test_public_projection_rejects_missing_and_double_raster_shift(self):
        t = self.t
        extent = (80, 48)
        proj = t.perspective_col(extent, fov_y_degrees=90)
        p = np.array([13.5, 7.5])
        current_shift, old_shift = np.array([.25, -.375]), np.array([-.375, .125])
        # API defines positive projected displacement; sample jitter is its
        # negative. Derive the oracle using that declared convention.
        expected = p + old_shift-current_shift
        outputs = []
        for factor in (1., 0., 2.):
            current = t.Camera(np.eye(4), proj, extent, raster_shift_px=tuple(current_shift*factor))
            old = t.Camera(np.eye(4), proj, extent, raster_shift_px=tuple(old_shift*factor))
            world, valid = t.unproject_pixels(p, 4., current)
            self.assertTrue(valid)
            projected = t.project_world(world, old)
            self.assertTrue(projected.valid)
            outputs.append(projected.pixel_xy)
        np.testing.assert_allclose(outputs[0], expected, atol=1e-13)
        for mutant in outputs[1:]:
            self.assertGreater(np.linalg.norm(mutant-expected), .5)

    def test_public_motion_reversal_roi_and_allocation_mutants(self):
        t = self.t
        render, roi = np.array([1920, 1080]), np.array([128, 64])
        allocation = np.array([2048, 1152])
        now = t.RasterDomain(tuple(render), tuple(allocation), (300, 200), tuple(roi))
        old = t.RasterDomain(tuple(render), tuple(allocation), (302, 197), tuple(roi))
        p, mv = np.array([4.5, 2.5]), np.array([.01, -.02])
        expected = p + np.array([300, 200]) + mv*render - np.array([302, 197])
        np.testing.assert_allclose(t.motion_to_previous(p, mv, now, old), expected, atol=1e-12)
        reversed_mv = t.motion_to_previous(p, -mv, now, old)
        roi_scaled = t.motion_to_previous(p, mv*roi/render, now, old)
        allocation_scaled = t.motion_to_previous(p, mv*allocation/render, now, old)
        self.assertGreater(np.linalg.norm(reversed_mv-expected), 50.)
        self.assertGreater(np.linalg.norm(roi_scaled-expected), 25.)
        self.assertGreater(np.linalg.norm(allocation_scaled-expected), 1.)

    def test_public_transposed_transform_fails_known_camera_translation(self):
        t = self.t
        extent = (80, 48)
        proj = t.perspective_col(extent, fov_y_degrees=90)
        view = np.eye(4); view[0, 3] = -1.
        point = np.array([0., 0., 4.])
        good = t.project_world(point, t.Camera(view, proj, extent))
        # f_y=24 pixels at 90 degrees; x shift is -(24/4) = -6 px.
        np.testing.assert_allclose(good.pixel_xy, [34., 24.], atol=1e-12)
        bad = t.project_world(point, t.Camera(view.T, proj, extent))
        self.assertGreater(np.linalg.norm(bad.pixel_xy-good.pixel_xy), 5.)
        # Physical C/F memory layout does not transpose mathematical content.
        memory_copy = t.project_world(point, t.Camera(np.asfortranarray(view), proj, extent))
        np.testing.assert_array_equal(memory_copy.pixel_xy, good.pixel_xy)

    def test_public_native_abs_depth_and_extra_phase_have_separate_oracles(self):
        t = self.t
        extent, centre = (80, 48), np.array([12., 20.])
        for handedness, sign in (("LH", 1.), ("RH", -1.)):
            proj = t.perspective_col(extent, handedness=handedness)
            camera = t.Camera(np.eye(4), proj, extent, handedness)
            view = t.native_shader_view_position(centre, sign*4., proj, extent)
            legacy = t.project_world(view, camera)
            np.testing.assert_allclose(legacy.pixel_xy-centre, [.5, .5], atol=1e-12)
            self.assertEqual(float(t.native_key_depth(sign*4)), 4.)
            self.assertTrue(t.native_recall_depth_match(4., 4., sign))
        self.assertFalse(t.native_recall_depth_match(-4., 4., -1.))

    def test_public_partial_crop_does_not_clamp_unknown_taps(self):
        t = self.t
        image = np.arange(15, dtype=float).reshape(3, 5)
        q = np.array([[.25, 1.5], [.5, 1.5], [4.5, 1.5], [4.75, 1.5], [-1., 1.5]])
        real = t.bilinear_sample(image, q)
        np.testing.assert_array_equal(real.valid, [False, True, True, False, False])
        self.assertTrue(np.all(real.coverage[[0, 3, 4]] < 1.))
        clamp_mutant = t.bilinear_sample(image, np.clip(q, [.5, .5], [4.5, 2.5]))
        self.assertEqual(np.count_nonzero(clamp_mutant.valid & ~real.valid), 3)

    def test_transport_unknown_mask_and_nonfinite_tolerances_fail_closed(self):
        t = self.t
        with self.assertRaises(ValueError):
            t.bilinear_sample(np.ones((1, 1)), np.array([.5, .5]), np.array([[np.nan]]))
        with self.assertRaises(ValueError):
            t.correspondence_support(1., 100., [0, 0, 1], [0, 0, 1], True, depth_relative=np.inf)
        with self.assertRaises(ValueError):
            t.correspondence_support(1., 1., [0, 0, 1], [0, 0, 1], np.nan)

    def test_reset_does_not_release_physical_inflight_slot(self):
        model = self.history.HistoryModel(ring_size=1)
        model.begin_frame(1, (8, 8))
        token = model.schedule_capture({"camera": "old"})
        model.submit(token, 1)
        model.begin_frame(2, (8, 8), explicit_reset=True)
        self.assertFalse(model.valid_keys())
        with self.assertRaises(RuntimeError):
            model.schedule_capture({"camera": "new"})
        model.complete(1)
        newer = model.schedule_capture({"camera": "new"})
        self.assertNotEqual(newer, token)


if __name__ == "__main__":
    unittest.main()
