"""Analytic invariants: these do not assume shader/GPU execution."""
import sys
import unittest
from pathlib import Path
import json
import tempfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transport import (Camera, RasterDomain, Plane, perspective_col, view_from_pose,
                       project_world, unproject_pixels, pixel_centres, surface_motion,
                       motion_to_previous, bilinear_sample, correspondence_support,
                       visibility_order, native_shader_view_position, native_key_depth,
                       native_recall_depth_match, construct_virtual_point,
                       mirror_virtual_point, render_planes)


def camera(extent=(137, 131), *, handedness="LH", position=(0, 0, 0), yaw=0, pitch=0,
           raster_shift=(0, 0), pixel_aspect=1.0):
    return Camera(view_from_pose(position, yaw, pitch), perspective_col(extent, handedness=handedness,
                  pixel_aspect=pixel_aspect), extent, handedness, raster_shift)


class ProjectionTests(unittest.TestCase):
    def test_roundtrip_signed_handedness_odd_extent_jitter_aspect_pose(self):
        for hand, sign in (("LH", 1), ("RH", -1)):
            for extent in ((137, 131), (83, 29), (1, 7), (31, 32)):
                for aspect in (1.0, 1.3):
                    cam = camera(extent, handedness=hand, position=(1.2, -.3, .8), yaw=11,
                                 pitch=-4, raster_shift=(.31, -.21), pixel_aspect=aspect)
                    xy = pixel_centres(extent)[::max(1, extent[1]//5), ::max(1, extent[0]//7)]
                    z = sign*(2.0 + .003*xy[..., 0]+.005*xy[..., 1])
                    world, valid = unproject_pixels(xy, z, cam)
                    result = project_world(world, cam)
                    self.assertTrue(np.all(valid & result.valid))
                    np.testing.assert_allclose(result.pixel_xy, xy, atol=2e-12)
                    np.testing.assert_allclose(result.view_depth, z, atol=2e-12)

    def test_camera_translation_matches_analytic_parallax(self):
        extent = (91, 57)
        current = camera(extent, position=(.4, 0, 0))
        previous = camera(extent)
        world = np.array([[0, 0, 2], [0, 0, 8]])
        motion, known = surface_motion(world, world, current, previous)
        expected_dx = .4*current.projection_col[0, 0]/(2*world[:, 2])
        np.testing.assert_allclose(motion[:, 0], expected_dx, atol=1e-14)
        np.testing.assert_allclose(motion[:, 1], 0, atol=1e-14)
        self.assertTrue(np.all(known))
        self.assertAlmostEqual(motion[0, 0]/motion[1, 0], 4)

    def test_camera_rotation_has_known_centre_phase(self):
        extent = (101, 71)
        current = camera(extent, yaw=10)
        previous = camera(extent)
        world, valid = unproject_pixels(np.array([50.5, 35.5]), 4., current)
        old = project_world(world, previous)
        expected_x = (1+previous.projection_col[0, 0]*np.tan(np.deg2rad(10)))*extent[0]/2
        self.assertTrue(valid and old.valid)
        self.assertAlmostEqual(old.pixel_xy[0], expected_x, places=11)
        self.assertAlmostEqual(old.pixel_xy[1], 35.5, places=11)

    def test_column_math_is_independent_of_numpy_memory_storage(self):
        cam = camera(position=(.7, .2, .1), yaw=7)
        f_camera = Camera(np.asfortranarray(cam.view_col), np.asfortranarray(cam.projection_col), cam.active_extent)
        world = np.array([[.3, .8, 8]])
        np.testing.assert_array_equal(project_world(world, cam).pixel_xy, project_world(world, f_camera).pixel_xy)
        # Mathematical transpose changes the transform. It is not a C/F storage conversion.
        wrong = Camera(cam.view_col.T, cam.projection_col, cam.active_extent)
        self.assertGreater(np.linalg.norm(project_world(world, wrong).pixel_xy-project_world(world, cam).pixel_xy), 1.)

    def test_behind_camera_zero_depth_and_sky_have_no_unprojection_support(self):
        for hand, sign in (("LH", 1), ("RH", -1)):
            cam = camera(handedness=hand)
            _, valid = unproject_pixels(np.array([[10.5, 20.5]]*3), np.array([0., -sign, np.inf]), cam)
            self.assertFalse(np.any(valid))

    def test_native_half_pixel_witness_is_not_clean_roundtrip(self):
        for hand, sign in (("LH", 1), ("RH", -1)):
            cam = camera(handedness=hand)
            centres = np.array([[4., 4.], [12., 20.], [100., 124.]])
            native = native_shader_view_position(centres, sign*np.array([2., 4., 8.]), cam.projection_col, cam.active_extent)
            out = project_world(native, cam)
            np.testing.assert_allclose(out.pixel_xy-centres, .5, atol=2e-14)
            clean, valid = unproject_pixels(centres, native[:, 2], cam)
            np.testing.assert_allclose(project_world(clean, cam).pixel_xy, centres, atol=2e-14)
            self.assertTrue(np.all(valid))

    def test_native_absolute_key_depth_for_both_handednesses(self):
        for sign in (-1, 1):
            z = sign*np.array([.2, 2., 30.])
            stored = native_key_depth(z)
            clip_w = sign*z
            self.assertTrue(np.all(native_recall_depth_match(stored, clip_w, sign)))
            if sign < 0:
                self.assertFalse(np.any(native_recall_depth_match(z, clip_w, sign)))
        self.assertFalse(bool(native_recall_depth_match(0, 0, 1)))
        # Preserve the frozen shader's tolerance-floor edge behavior: this is
        # arithmetic parity, not endorsement of zero-depth correspondence.
        self.assertTrue(bool(native_recall_depth_match(0., 1.1e-6, 1.)))


class DomainTests(unittest.TestCase):
    def test_moving_crop_preserves_original_render_motion(self):
        current = RasterDomain((1920, 1080), (2048, 1152), (904, 300), (128, 256))
        previous = RasterDomain((1920, 1080), (2048, 1152), (900, 299), (128, 256))
        points = np.array([[3.5, 4.5], [127.5, 255.5]])
        motion = np.array([[-1/1920, 2/1080], [-1/1920, 2/1080]])
        expected = points+(3, 3)
        got = motion_to_previous(points, motion, current, previous)
        np.testing.assert_allclose(got, expected, atol=1e-12)
        self.assertTrue(previous.observed_point(got)[0])
        self.assertFalse(previous.observed_point(got)[1])
        # Allocation UV is appropriate for the source SRV but not for motion normalization.
        np.testing.assert_allclose(current.allocation_uv(points), (points+(904, 300))/(2048, 1152))

    def test_drs_uses_active_uv_endpoints_and_no_crop_extent_scaling(self):
        current = RasterDomain((137, 131), (256, 256), (11, 17), (83, 61))
        previous = RasterDomain((101, 87), (256, 256), (4, 9), (91, 71))
        local = np.array([[40.5, 25.5]])
        displacement = np.array([[.125, -.25]])
        expected = (((local+(11, 17))/(137, 131))+displacement)*(101, 87)-(4, 9)
        np.testing.assert_allclose(motion_to_previous(local, displacement, current, previous), expected)

    def test_raster_shift_applied_exactly_once_for_unjittered_mv(self):
        dom = RasterDomain((77, 51))
        p = np.array([[20.5, 30.5]])
        cur_shift, old_shift = np.array([.3, -.2]), np.array([-.1, .4])
        got = motion_to_previous(p, np.zeros_like(p), dom, dom, cur_shift, old_shift, False)
        np.testing.assert_allclose(got, p-cur_shift+old_shift)
        shifted_mv = (old_shift-cur_shift)/(77, 51)
        np.testing.assert_allclose(motion_to_previous(p, shifted_mv, dom, dom), got)

    def test_partial_bilinear_support_never_clamps_or_renormalizes(self):
        image = np.arange(12, dtype=float).reshape(3, 4)
        xy = np.array([[.5, .5], [3.5, 2.5], [.1, 1.5], [4.1, 1.5], [1.75, 1.25]])
        sampled = bilinear_sample(image, xy)
        np.testing.assert_array_equal(sampled.valid, [True, True, False, False, True])
        np.testing.assert_allclose(sampled.values, [0, 11, 0, 0, 4.25])
        self.assertLess(sampled.coverage[2], 1)
        self.assertLess(sampled.coverage[3], 1)
        known = np.ones((3, 4), bool)
        known[1, 1] = False
        self.assertFalse(bool(bilinear_sample(image, np.array([1.75, 1.25]), known).valid))

    def test_nonfinite_samples_cannot_become_valid(self):
        image = np.ones((3, 4, 3))
        image[1, 1, 0] = np.nan
        result = bilinear_sample(image, np.array([[1.5, 1.5], [np.nan, 1.5], [3.5, 2.5]]))
        np.testing.assert_array_equal(result.valid, [False, False, True])
        self.assertTrue(np.all(np.isfinite(result.values)))


class AnalyticSceneTests(unittest.TestCase):
    def test_constant_sloped_and_intersecting_planes_have_analytic_depth(self):
        cam = camera((83, 57))
        constant = render_planes(cam, [Plane((0, 0, 1), -8, 1)])
        np.testing.assert_allclose(constant["depth"], 8)
        slope = render_planes(cam, [Plane((.2, 0, 1), -5, 2)])
        p = slope["world"]
        np.testing.assert_allclose(.2*p[..., 0]+p[..., 2], 5, atol=2e-14)
        # Two planes intersect at x=0 and swap exact nearest-surface ordering.
        scene = render_planes(cam, [Plane((.2, 0, 1), -5, 1), Plane((-.2, 0, 1), -5, 2)])
        self.assertTrue(np.all(scene["surface_id"][:, :41] == 2))
        self.assertTrue(np.all(scene["surface_id"][:, 42:] == 1))

    def test_one_pixel_strip_moves_over_wall_with_true_disocclusion(self):
        extent = (81, 55)
        cam = camera(extent)
        focal_x = cam.projection_col[0, 0]*extent[0]/2
        half_width = 2./focal_x/2
        wall = Plane((0, 0, 1), -8, 1)
        old = Plane((0, 0, 1), -2, 2, (-half_width, -100, 1.9), (half_width, 100, 2.1))
        shift = 3*2./focal_x
        new = Plane((0, 0, 1), -2, 2, (shift-half_width, -100, 1.9), (shift+half_width, 100, 2.1))
        previous = render_planes(cam, [wall, old])
        current = render_planes(cam, [wall, new])
        self.assertEqual(np.count_nonzero(previous["surface_id"] == 2), extent[1])
        self.assertEqual(np.count_nonzero(current["surface_id"] == 2), extent[1])
        disoccluded = (previous["surface_id"] == 2) & (current["surface_id"] == 1)
        self.assertEqual(np.count_nonzero(disoccluded), extent[1])
        order = visibility_order(np.abs(current["depth"]), np.abs(previous["depth"]), True)
        self.assertTrue(np.all(order[disoccluded] == 2))  # old foreground occludes the new wall's correspondence
        support = correspondence_support(np.abs(current["depth"]), np.abs(previous["depth"]),
                                         current["normal"], previous["normal"], True)
        self.assertFalse(np.any(support[disoccluded]))
        # Moving surface requires object motion, not a static-camera-only transport.
        point = np.array([shift, 0, 2.])
        moved, valid = surface_motion(point, point-(shift, 0, 0), cam, cam)
        np.testing.assert_allclose(moved*extent, [-3., 0.], atol=1e-13)
        self.assertTrue(valid)

    def test_object_enters_and_leaves_partial_crop_unknown_surroundings(self):
        domain = RasterDomain((101, 77), (128, 128), (30, 20), (19, 15))
        local = np.array([[.5, 7.5], [18.5, 7.5], [9.5, 7.5]])
        previous = motion_to_previous(local, np.array([[-3/101, 0], [3/101, 0], [0, 0]]), domain, domain)
        sample = bilinear_sample(np.ones((15, 19)), previous)
        np.testing.assert_array_equal(sample.valid, [False, False, True])
        self.assertEqual(int(np.count_nonzero(~sample.valid)), 2)

    def test_normal_and_depth_guides_are_independent_and_invalid_rejects(self):
        normal = np.array([[0, 0, 1], [0, 0, 1], [0, 0, 0], [np.nan, 0, 1], [0, 0, 1]])
        prev = np.array([[0, 0, 1], [1, 0, 0], [0, 0, 1], [0, 0, 1], [0, 0, 1]])
        valid = correspondence_support(np.array([2, 2, 2, 2, 0]), 2., normal, prev, True)
        np.testing.assert_array_equal(valid, [True, False, False, False, False])

    def test_planar_mirror_virtual_transport_differs_from_surface_transport(self):
        current = camera((101, 71), position=(.4, 0, 0))
        previous = camera((101, 71))
        real = np.array([1., 0., 2.])
        virtual = mirror_virtual_point(real, (0, 0, 1), (0, 0, 5))
        np.testing.assert_array_equal(virtual, [1, 0, 8])
        origin = np.array([.4, 0, 0])
        surface = origin+(virtual-origin)*(5/8)
        hit_distance = np.linalg.norm(real-surface)
        reconstructed, usable = construct_virtual_point(surface, surface-origin, hit_distance,
                                                         observation_role="reflection_distance")
        np.testing.assert_allclose(reconstructed, virtual, atol=1e-14)
        self.assertTrue(usable)
        surface_mv, _ = surface_motion(surface, surface, current, previous)
        virtual_mv, _ = surface_motion(virtual, virtual, current, previous)
        self.assertGreater(np.linalg.norm((surface_mv-virtual_mv)*current.active_extent), 1.)
        self.assertAlmostEqual(surface_mv[0]/virtual_mv[0], 8/5)
        for role in ("surface_property", "diffuse_hit_distance", "missing"):
            _, usable = construct_virtual_point(surface, surface-origin, hit_distance, observation_role=role)
            self.assertFalse(usable)
        _, usable = construct_virtual_point(surface, surface-origin, np.nan, observation_role="reflection_distance")
        self.assertFalse(usable)


class ExperimentReceiptTests(unittest.TestCase):
    def test_reproducible_metrics_have_exact_support_and_independent_correspondence(self):
        from transport_experiment import run
        with tempfile.TemporaryDirectory() as directory:
            result = run(directory)
            saved = json.loads((Path(directory)/"transport_metrics.json").read_text())
        self.assertEqual(saved, result)
        self.assertEqual(result["correspondence"]["true_correspondence_error_px"]["count"], 2464)
        self.assertLess(result["correspondence"]["true_correspondence_error_px"]["max"], 1e-11)
        self.assertEqual(result["phase_sweep"]["roundtrip_error_px"]["count"], 4096)
        self.assertLess(result["phase_sweep"]["roundtrip_error_px"]["max"], 1e-11)
        support = result["analytic_support"]
        self.assertEqual(support["baseline_pixel_denominator"], 4455)
        self.assertEqual(support["genuine_disocclusion_pixel_count"], 55)
        self.assertEqual(support["accepted_pixel_count"], 4400)
        self.assertEqual(support["depth_normal_support_purity"], 1.)
        self.assertEqual(support["occlusion_leakage_count"], 0)
        self.assertEqual(support["invalid_to_valid_count"], 0)
        self.assertTrue(result["history_trajectory"]["physical_slot_reuse_blocked_after_reset"])
        self.assertFalse(result["history_trajectory"]["old_epoch_completion_resurrected_history"])
        self.assertTrue(result["history_trajectory"]["all_published_keys_have_matching_camera_frame"])
        self.assertAlmostEqual(result["virtual_transport"]["surface_to_virtual_parallax_ratio"], 1.6)
        self.assertFalse(result["gpu_executed"])


if __name__ == "__main__":
    unittest.main()
