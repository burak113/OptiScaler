"""Independent adversarial checks, authored after preregistration.

No oracle surface identifiers are passed to the reconstruction API. Plane
geometry and immutable source eligibility determine every certificate.
"""
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reconstruction as r


def plane(height=24, width=24, slopes=(0., 0.)):
    yy, xx = np.mgrid[:height, :width]
    x, y = (xx+.5)*.1, (yy+.5)*.1
    sx, sy = slopes
    position = np.stack([x, y, 10.+sx*x+sy*y], -1)
    normal = np.broadcast_to(np.array([-sx, -sy, 1.]), position.shape).copy()
    return r.GeometryField(position, normal, np.ones((height, width), bool),
                           np.ones((height, width), bool))


def local(field, policy=None):
    cells = r.certify_cells(field) if policy is None else r.certify_cells(field, policy)
    return r.local_estimator_support(cells, np.ones_like(cells.valid))


class IndependentReconstructionChallenges(unittest.TestCase):
    def test_constant_sloped_plane_has_exact_constant_gain_and_partial_mass(self):
        field = plane(slopes=(.4, -.2))
        support = local(field)
        self.assertTrue(support.valid.all())
        out = r.reconstruct(np.full(support.valid.shape, .7), support, field)
        np.testing.assert_allclose(out.gain, .7, atol=2e-15)
        # This is supported partial weighting, not fabricated full coverage.
        self.assertLess(out.support_mass[0, 0], 1.)
        self.assertEqual(out.contributor_count[0, 0], 1)
        hard = r.reconstruct(np.full(support.valid.shape, .7), support, field, method="hard")
        self.assertEqual(hard.gain[0, 0], 1.)

    def test_hidden_one_pixel_foreground_cannot_be_certified_from_cell_centre(self):
        field = plane(16, 16)
        field.position[:, 7, 2] = 2.
        support = local(field)
        self.assertFalse(support.valid[:, 0].any())
        self.assertTrue(support.valid[:, 1].all())
        out = r.reconstruct(np.full((2, 2), .6), support, field)
        np.testing.assert_array_equal(out.gain[:, 7], 1.)

    def test_coplanar_moving_strip_requires_independent_eligibility(self):
        field = plane(16, 16)
        protected = np.zeros((16, 16), bool)
        protected[:, 7] = True
        field.eligible[protected] = False
        support = local(field)
        out = r.reconstruct(np.full((2, 2), .6), support, field)
        np.testing.assert_array_equal(out.gain[protected], 1.)
        # Explicitly demonstrate identifiability limit if that source mask is
        # absent: depth and normal alone cannot distinguish coplanar motion.
        field_without_motion = plane(16, 16)
        inadequate = r.reconstruct(np.full((2, 2), .6), local(field_without_motion),
                                   field_without_motion)
        self.assertGreater(float(np.max(1-inadequate.gain[protected])), .39)

    def test_pure_target_cannot_approve_a_mixed_estimator_donor(self):
        field = plane(16, 24)
        field.position[:, 16:, 2] = 2.
        cells = r.certify_cells(field)
        self.assertTrue(cells.valid.all())  # Every cell separately is pure.
        certified = r.certify_estimator_support(cells, np.ones((2, 3)),
            np.ones((2, 3), bool), [(0, 0), (1, 0)])
        self.assertFalse(certified.valid[:, 1].any())
        self.assertTrue(certified.valid[:, 0].all())

    def test_false_estimator_provenance_remains_an_explicit_counterexample(self):
        field = plane(16, 24)
        support = local(field)
        # Centre geometry cannot undo a wrong statistical gain supplied with
        # false provenance. This deliberately bad exact-support declaration is
        # rejected as a production strategy, not hidden in aggregate metrics.
        contaminated = np.full((2, 3), .6)
        out = r.reconstruct(contaminated, support, field)
        expected_correct_gain = .9
        self.assertGreater(np.max(np.abs(out.gain-expected_correct_gain)), .29)

    def test_point_gain_alias_is_separate_from_exact_footprint_reconstruction(self):
        field = plane(16, 16)
        pixel_x = np.arange(16)+.5
        coarse_x = np.array([4., 12.])
        # Open strip 11.5 < x < 12.5 intersects the coarse point x=12 but
        # contains neither adjacent full-resolution texel centre. A point gain
        # is therefore not exact for the estimator's discrete pixel footprint.
        self.assertFalse(np.any(np.abs(pixel_x-12.) < .5))
        point_gain = np.broadcast_to(np.where(np.abs(coarse_x-12.) < .5, 1., .8), (2, 2))
        support = local(field)
        self.assertTrue(support.valid.all())
        mismatched = r.reconstruct(point_gain, support, field)
        self.assertAlmostEqual(float(np.max(np.abs(mismatched.gain-.8))), .2)
        # Derive this gain from known uniform discrete input, not candidate
        # validity: every supplied observed texel is the static background.
        exact_footprint_gain = np.full((2, 2), .8)
        isolated = r.reconstruct(exact_footprint_gain, support, field)
        np.testing.assert_allclose(isolated.gain, .8, rtol=0, atol=1e-15)

    def test_sub_tolerance_parallel_surfaces_are_not_observably_separable(self):
        field = plane(16, 16)
        field.position[:, 7, 2] += .0005
        support = local(field)
        # A tolerance certificate is compatibility, not topology or material
        # truth. Do not tune this case away: retain the observability limit.
        self.assertTrue(support.valid.all())
        out = r.reconstruct(np.full((2, 2), .6), support, field)
        expected_identity_on_distinct_strip = np.ones(16)
        self.assertGreater(np.max(np.abs(out.gain[:, 7]-expected_identity_on_distinct_strip)), .39)

    def test_unknown_query_and_invalid_guides_are_identity(self):
        for kind in ("unknown", "zero_normal", "nan_normal", "nan_position", "zero_depth", "inf_depth"):
            with self.subTest(kind=kind):
                field = plane()
                y, x = 11, 11
                if kind == "unknown": field.observed[y, x] = False
                if kind == "zero_normal": field.normal[y, x] = 0
                if kind == "nan_normal": field.normal[y, x] = np.nan
                if kind == "nan_position": field.position[y, x] = np.nan
                if kind == "zero_depth": field.position[y, x, 2] = 0
                if kind == "inf_depth": field.position[y, x, 2] = np.inf
                support = local(field)
                out = r.reconstruct(np.full((3, 3), .6), support, field)
                self.assertEqual(out.gain[y, x], 1.)
                self.assertEqual(out.support_mass[y, x], 0.)
                self.assertTrue(np.isfinite(out.gain).all())

    def test_all_invalid_gain_and_donor_validity_remain_identity(self):
        field = plane()
        support = local(field)
        for bad_gain in (np.nan, np.inf, -1., 1.01):
            out = r.reconstruct(np.full((3, 3), bad_gain), support, field)
            np.testing.assert_array_equal(out.gain, 1.)
        invalid = r.local_estimator_support(support.cells, np.zeros((3, 3), bool))
        out = r.reconstruct(np.full((3, 3), .6), invalid, field)
        np.testing.assert_array_equal(out.gain, 1.)
        self.assertFalse(out.support_mass.any())

    def test_odd_extent_partial_cells_stay_unknown(self):
        field = plane(19, 27)
        support = local(field)
        self.assertFalse(support.cells.valid[-1].any())
        self.assertFalse(support.cells.valid[:, -1].any())
        self.assertTrue(support.cells.valid[:-1, :-1].all())
        # Unobserved ROI pixels cannot borrow a nearby observed cell.
        field.observed[-2:, :] = False
        out = r.reconstruct(np.full(support.valid.shape, .6), support, field)
        np.testing.assert_array_equal(out.gain[-2:], 1.)

    def test_zero_weight_foreign_donor_is_not_a_contaminating_observation(self):
        field = plane(16, 24)
        field.position[:, 16:, 2] = 2.
        cells = r.certify_cells(field)
        weight = np.ones((2, 3)); weight[:, 2] = 0
        support = r.certify_estimator_support(cells, weight, np.ones((2, 3), bool), [(0, 0), (1, 0)])
        self.assertTrue(support.valid[:, 1].all())
        self.assertFalse(support.valid[:, 2].any())

    def test_nonfinite_weight_is_not_silently_dropped_from_estimator(self):
        field = plane()
        cells = r.certify_cells(field)
        weight = np.ones((3, 3)); weight[1, 1] = np.nan
        support = r.certify_estimator_support(cells, weight, np.ones((3, 3), bool), [(0, 0), (1, 0)])
        self.assertFalse(support.valid[1, 0])
        self.assertFalse(support.valid[1, 1])

    def test_off_and_alpha_payload_are_bitwise_preserved(self):
        field = plane()
        support = local(field)
        off = r.reconstruct(np.full((3, 3), .6), support, field, enabled=False)
        np.testing.assert_array_equal(off.gain, 1.)
        # Include signed zero and a NaN alpha bit-pattern; alpha is raw payload.
        bits = np.arange(24*24*4, dtype=np.uint16).reshape(24, 24, 4)
        bits[..., 3] = np.resize(np.array([0x8000, 0x7e01, 0x3c00], np.uint16), (24, 24))
        rgba = bits.view(np.float16)
        np.testing.assert_array_equal(r.apply_rgba(rgba, off.gain).view(np.uint16), bits)
        on = r.apply_rgba(rgba, np.full((24, 24), .6))
        np.testing.assert_array_equal(on[..., 3].view(np.uint16), bits[..., 3])

    def test_invalid_policy_is_rejected_not_converted_to_valid_support(self):
        kwargs_cases = [
            {"minimum_weight": -1.}, {"minimum_weight": np.nan},
            {"plane_absolute_tolerance": np.inf},
            {"plane_relative_tolerance": -1.},
            {"cell": 0}, {"cell": 2.5},
        ]
        for kwargs in kwargs_cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    r.certify_cells(plane(), r.Policy(**kwargs))


if __name__ == "__main__":
    unittest.main()
