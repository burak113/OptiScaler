"""Analytic and source-shape tests; no captured images are retuned here."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from numerical_contract import coordinates as c


class CoordinateContractTests(unittest.TestCase):
    def test_floor_grid_extent_and_small_resources(self):
        self.assertEqual(c.grid_extent((1505,847),4), (376,211))
        self.assertEqual(c.grid_extent((1505,847),8), (188,105))
        self.assertEqual(c.grid_extent((1,3),8), (1,1))
        for bad in ((0,1), (-1,3)):
            with self.assertRaises(ValueError):
                c.grid_extent(bad,4)

    def test_exact_power_two_centre_roundtrip(self):
        for mode in ("ideal", "source", "observed"):
            xy = c.pixel_grid((16,8), mode=mode)
            np.testing.assert_array_equal(c.uv_to_texel(c.texel_to_uv(xy,(16,8),mode=mode),
                                                        (16,8),mode=mode), xy)

    def test_odd_extent_centre_roundtrip_has_explicit_float32_tolerance(self):
        xy = c.pixel_grid((17,11), mode="source")
        actual = c.uv_to_texel(c.texel_to_uv(xy,(17,11)), (17,11))
        np.testing.assert_allclose(actual,xy,atol=2e-6,rtol=0)

    def test_reciprocal_is_named_instead_of_assumed_equal(self):
        xy = c.pixel_grid((17,11))
        direct = c.texel_to_uv(xy,(17,11),method="divide")
        reciprocal = c.texel_to_uv(xy,(17,11),method="reciprocal_multiply")
        self.assertTrue(np.any(direct != reciprocal))
        np.testing.assert_allclose(direct,reciprocal,atol=2*np.finfo(np.float32).eps,rtol=0)

    def test_active_allocation_uv_mapping(self):
        xy = np.array([[3,2],[12,6]])
        active_uv = c.texel_to_uv(xy,(13,7),mode="ideal")
        allocation_uv = c.active_uv_to_allocation_uv(active_uv,(13,7),(17,11),mode="ideal")
        np.testing.assert_allclose(c.uv_to_texel(allocation_uv,(17,11),mode="ideal"),xy,atol=1e-14)
        with self.assertRaises(ValueError):
            c.active_uv_to_allocation_uv(active_uv,(13,7),(10,9))

    def test_gain_apply_uses_grid_extent_ratio_not_cell_divisor_on_odd_size(self):
        p = np.array([8,6],np.float32)
        actual = c.full_pixel_to_grid_texel(p,(9,7),(2,1),mode="ideal")
        expected = (p.astype(np.float64)+.5)*np.array([2/9,1/7])-.5
        # Algebraically equivalent float64 orderings may differ by one ULP.
        np.testing.assert_allclose(actual,expected,rtol=0,atol=np.finfo(np.float64).eps)
        wrong = (p+.5)/4-.5
        self.assertGreater(float(np.max(abs(actual-wrong))), .2)

    def test_motion_uses_original_render_extent(self):
        uv = np.array([1/1505,-2/847],np.float64)
        np.testing.assert_allclose(c.motion_uv_to_pixels(uv,(1505,847),mode="ideal"),[1,-2],atol=1e-15)
        wrong = c.motion_uv_to_pixels(uv,(512,512),mode="ideal")
        self.assertGreater(float(np.max(abs(wrong-[1,-2]))),.5)

    def test_crop_translation_is_separate_from_scene_motion(self):
        p = np.array([[4,5],[10,9]],np.float64)
        prev = c.reproject_crop(p,np.zeros_like(p),current_origin=(100,20),previous_origin=(97,22),mode="ideal")
        np.testing.assert_array_equal(prev,p+[3,-2])
        np.testing.assert_array_equal(prev+[97,22],p+[100,20])

    def test_track_plus_sign_and_cell_units(self):
        p = np.array([2,3],np.float32)
        uv = c.colour_track_previous_uv(p,np.array([8,-4]),(10,10))
        np.testing.assert_allclose(uv,[.45,.25],rtol=0,atol=1e-7)

    def test_box_taps_are_edge_coordinates(self):
        colour = c.cell_tap_uv(np.array([1,2]),4,(16,16),mode="ideal")*16
        anchor = c.cell_tap_uv(np.array([1,2]),8,(32,32),mode="ideal")*32
        np.testing.assert_array_equal(colour,[[5,9],[7,9],[5,11],[7,11]])
        np.testing.assert_array_equal(anchor,[[10,18],[14,18],[10,22],[14,22]])

    def test_anchor_edge_centre_roundtrip_diagnostic(self):
        # P00=P11=1, P02=P12=0, P32=1; no model fit is involved.
        p = np.array([[4,4],[756,420]],np.float64)
        v = c.anchor_view_position(p,3,(1505,847),[1,1,0,0],1,mode="ideal")
        clip = np.column_stack((v,np.full(len(p),3)))
        edge = c.project_to_edge_pixels(clip,(1505,847),mode="ideal")
        closed = c.project_to_texel_indices(clip,(1505,847),mode="ideal")
        np.testing.assert_allclose(edge,p+.5,rtol=0,atol=2e-13)
        np.testing.assert_allclose(closed,p,rtol=0,atol=2e-13)
        self.assertTrue(np.all(np.linalg.norm(edge-p,axis=-1)>.7))

    def test_anchor_projection_rejects_undefined_divisors(self):
        with self.assertRaises(ValueError):
            c.anchor_view_position([0,0],1,(4,4),[0,1,0,0],1)
        with self.assertRaises(ValueError):
            c.project_to_edge_pixels([1,1,1,0],(4,4))
        with self.assertRaises(ValueError):
            c.project_to_edge_pixels([np.nan,1,1,1],(4,4))


if __name__ == "__main__":
    unittest.main()
