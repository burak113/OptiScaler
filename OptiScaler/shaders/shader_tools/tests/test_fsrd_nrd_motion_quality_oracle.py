"""CPU-only independent geometry and metric-sensitivity checks, no RR emulation claim."""
from pathlib import Path
import tempfile
import unittest
import numpy as np

from fsrd_nrd_motion_quality_oracle import (MODES, metrics, pose, project, raster_motion,
                                           sequence, trace, write_sequence, load)


class WorldSurfaceOracle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.values = list(sequence())

    def test_pinhole_primary_points_project_back_to_actual_jittered_sample(self):
        y, x = np.mgrid[:128, :128]
        for value in self.values[::7]:
            p = value['pose']
            uv, z = project(value['current_world'].astype(np.float64), p)
            expected = np.stack((x + .5, y + .5), axis=-1) / 128 - p['jitter'] / 128
            np.testing.assert_allclose(uv, expected, rtol=0, atol=5e-8)
            np.testing.assert_allclose(z, value['common']['depth'], rtol=0, atol=1e-6)
            self.assertTrue((z < -.05).all())

    def test_previous_object_pose_preserves_material_coordinates(self):
        moving_samples = 0
        for value in self.values[1:]:
            mask = value['object'].astype(bool)
            if not mask.any():
                continue
            previous = pose(value['index'] - 1, 128, 128)
            current_local = value['current_world'][mask] - value['pose']['center']
            previous_local = value['previous_world'][mask] - previous['center']
            np.testing.assert_allclose(current_local, previous_local, rtol=0, atol=8e-7)
            if abs(previous['center'][2] - value['pose']['center'][2]) > .02:
                moving_samples += 1
        self.assertGreater(moving_samples, 8)

    def test_same_surface_depth_comes_from_previous_world_and_camera(self):
        for value in self.values[1::5]:
            previous = pose(value['index'] - 1, 128, 128)
            # Direct row dot, independent of either conversion fixture or an old
            # depth image. Stored world-point quantization is explicitly bounded.
            predicted = np.einsum('...i,i->...', value['previous_world'].astype(np.float64) - previous['camera'],
                                  previous['rotation'][2])
            np.testing.assert_allclose(predicted, value['previous_surface_depth'], rtol=0, atol=8e-7)
            packet = value['motion']['surface'].astype(np.float32)
            inside = value['reprojection_valid'].astype(bool)
            delta = predicted - value['common']['depth']
            np.testing.assert_allclose(packet[..., 2][inside], delta[inside], rtol=0, atol=.0005)

    def test_mv_xy_includes_exactly_one_pixel_jitter_delta(self):
        y, x = np.mgrid[:128, :128]
        for value in self.values[1::3]:
            previous = pose(value['index'] - 1, 128, 128)
            expected = value['canonical_motion'].astype(np.float64)
            expected += (previous['jitter'] - value['pose']['jitter']) / 128
            actual = value['motion']['surface'][..., :2].astype(np.float64)
            np.testing.assert_allclose(actual, expected, atol=6e-5, rtol=0)
            # All B candidates keep the identical native half XY/W words.
            for mode in MODES:
                np.testing.assert_array_equal(value['motion'][mode][..., [0, 1, 3]].view('<u2'),
                                              value['motion']['surface'][..., [0, 1, 3]].view('<u2'))

    def test_object_z_rejects_camera_only_shortcut(self):
        maximum, count = 0., 0
        for value in self.values[1:]:
            mask = value['object'].astype(bool) & value['interior'].astype(bool)
            if mask.any():
                delta = np.abs(value['motion']['surface'][..., 2].astype(np.float32) -
                               value['motion']['camera'][..., 2].astype(np.float32))
                maximum = max(maximum, float(delta[mask].max()))
                count += int(np.count_nonzero(delta[mask] > .025))
        self.assertGreater(maximum, .1)
        self.assertGreater(count, 1000)

    def test_legacy_visible_depth_passes_its_own_formula_but_accepts_occluder(self):
        false_accepts, surface_rejections = 0, 0
        for value in self.values[1:]:
            mask = value['reveal_mask'].astype(bool) & value['interior'].astype(bool)
            if not mask.any():
                continue
            depth = value['common']['depth'].astype(np.float32)
            legacy = value['motion']['visible'][..., 2].astype(np.float32)
            surface = value['motion']['surface'][..., 2].astype(np.float32)
            # This is a geometric history-admission counterexample, not a model
            # of private AMD filtering: legacy B predicts the visible occluder.
            # The old surface is observed by an independent analytic ray query,
            # not reconstructed from the legacy B expression being challenged.
            previous_pose = pose(value['index'] - 1, 128, 128)
            old_surface = trace(value['previous_uv'].astype(np.float64), previous_pose)
            previous_visible_depth = np.einsum('...i,i->...', old_surface['point'] - previous_pose['camera'],
                                               previous_pose['rotation'][2])
            self.assertTrue(np.all(np.abs(previous_visible_depth[mask] - depth[mask]) > 3.))
            false_accepts += int(np.count_nonzero(np.abs(previous_visible_depth[mask] - (depth + legacy)[mask]) < .05))
            surface_rejections += int(np.count_nonzero(np.abs(previous_visible_depth[mask] - (depth + surface)[mask]) > 3.))
        self.assertGreater(false_accepts, 1000)
        self.assertEqual(false_accepts, surface_rejections)

    def test_reflected_specular_hit_is_first_positive_plane_intersection(self):
        for value in self.values[::9]:
            p = value['pose']
            point = value['current_world'].astype(np.float64)
            direction = point - p['camera']
            direction /= np.linalg.norm(direction, axis=-1, keepdims=True)
            direction[..., 2] *= -1
            hit = value['common']['spec'][..., 3].astype(np.float64)
            ideal = (3. - point[..., 2]) / direction[..., 2]
            self.assertTrue(np.isfinite(hit).all() and (hit > 0).all())
            np.testing.assert_allclose(hit, ideal, atol=.008, rtol=0)
            self.assertTrue((direction[..., 2] > 0).all())

    def test_reset_outside_and_nonnegative_finite_payload_domains(self):
        first = self.values[0]
        for mode in MODES:
            self.assertTrue((first['motion'][mode][..., 2] == 0).all())
        outside_count = 0
        for value in self.values:
            for array in value['common'].values():
                self.assertTrue(np.isfinite(array).all())
            for signal in ('spec', 'diff'):
                self.assertTrue((value['common'][signal] >= 0).all())
            for mode in MODES:
                self.assertTrue(np.isfinite(value['motion'][mode]).all())
            outside = ~value['reprojection_valid'].astype(bool)
            outside_count += int(outside.sum())
            self.assertTrue((value['motion']['surface'][..., 2][outside] == 0).all())
        self.assertGreater(outside_count, 100)

    def test_reveal_has_current_geometry_and_a_measured_tail_cohort(self):
        support = {age: 0 for age in range(9)}
        for value in self.values:
            age = value['reveal_age']
            np.testing.assert_array_equal(age == 0, value['reveal_mask'].astype(bool))
            for number in support:
                support[number] += int(np.count_nonzero((age == number) & value['interior'].astype(bool)))
        self.assertTrue(all(count > 100 for count in support.values()), support)

    def test_t04_static_physical_motion_is_half_pixel_raster_displacement(self):
        # T04 vector: zero physical motion, previous-current jitter difference of
        # exactly one half pixel. Both source conventions must reach the same
        # raster displacement: the unjittered field is canonical and receives the
        # difference once here, the jittered field already contains it.
        width, height = 64, 48
        canonical = np.zeros(2)
        previous_jitter = np.array([.25, -.125])
        current_jitter = np.array([-.25, .375])  # difference = (0.5, -0.5) px
        unjittered = raster_motion(canonical, previous_jitter, current_jitter, width, height, False)
        jittered_field = canonical + (previous_jitter - current_jitter) / (width, height)
        jittered = raster_motion(jittered_field, previous_jitter, current_jitter, width, height, True)
        np.testing.assert_allclose(unjittered * (width, height), (.5, -.5), rtol=0, atol=1e-12)
        np.testing.assert_allclose(jittered * (width, height), (.5, -.5), rtol=0, atol=1e-12)
        np.testing.assert_array_equal(unjittered, jittered)
        # The jittered path must not add the difference a second time.
        self.assertAlmostEqual(float(jittered[0]), .5 / width, places=12)
        self.assertFalse(np.array_equal(raster_motion(canonical, previous_jitter, current_jitter,
                                                      width, height, True), unjittered))

    def test_metrics_distinguish_perfect_blur_stale_and_chroma(self):
        value = max(self.values, key=lambda v: np.count_nonzero(v['reveal_age'] == 3))
        crop = [16, 16, 96, 96]
        for signal in ('spec', 'diff'):
            truth, age, ghost = value['reference'][signal], value['reveal_age'], value['ghost'][signal]
            perfect = metrics(truth, truth, age, ghost, crop)
            self.assertEqual(perfect['rgb_rmse'], 0)
            self.assertEqual(perfect['detail_gradient_rmse'], 0)
            self.assertAlmostEqual(perfect['gradient_projection_ratio'], 1)
            blur = sum(np.roll(np.roll(truth.astype(np.float64), dy, 0), dx, 1)
                       for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))) / 5
            blurred = metrics(blur, truth, age, ghost, crop)
            self.assertGreater(blurred['detail_gradient_rmse'], 0)
            self.assertLess(blurred['gradient_projection_ratio'], 1)
            stale = truth.copy()
            mask = age <= 16
            stale[mask] = ghost[mask]
            tail = metrics(stale, truth, age, ghost, crop)['reveal_tail']
            self.assertTrue(tail)
            for row in tail.values():
                self.assertAlmostEqual(row['mean_signed_stale_fraction'], 1, places=6)
                self.assertGreater(row['positive_stale_energy'], 0)
            colored = truth.astype(np.float64).copy()
            colored[20:100:4, 20:100:4, 0] += .2
            grains = metrics(colored, truth, age, ghost, crop)
            self.assertGreater(grains['chroma_absolute_p99'], .1)

    def test_generator_is_sealed_deterministic_and_has_no_raw_title_z_guess(self):
        # Smallest legal extent and short valid temporal length keep this CPU
        # serialization test bounded. Native rendering is never launched here.
        import os
        with tempfile.TemporaryDirectory(dir=os.environ.get('TEMP', 'F:/FSRD/tmp')) as temp:
            root = Path(temp)
            a, b = root / 'a', root / 'b'
            one = write_sequence(a, 64, 64, 56)
            two = write_sequence(b, 64, 64, 56)
            self.assertEqual((a / 'sequence.json').read_bytes(), (b / 'sequence.json').read_bytes())
            self.assertEqual(len(one['frames']), len(two['frames']))
            self.assertIn('not yet attested', one['native_title_operand_encoding'])
            frame = one['frames'][21]
            for record in frame['payloads'].values():
                actual = load(a / frame['directory'], record)
                self.assertTrue(np.isfinite(actual).all())
            record = frame['payloads']['motion_surface']
            path = a / frame['directory'] / record['file']
            path.write_bytes(path.read_bytes()[:-1] + b'!')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                load(a / frame['directory'], record)


if __name__ == '__main__':
    unittest.main()
