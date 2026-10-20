"""Sampling invariants, frozen-arithmetic parity and deliberate wrong controls."""
import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from numerical_contract import sampling as s
from numerical_contract import coordinates as c


def plane(width,height):
    yy,xx = np.mgrid[:height,:width]
    return (xx+10*yy).astype(np.float32)


class SamplingContractTests(unittest.TestCase):
    def test_integer_load_preserves_uint32_and_signed_zero(self):
        uint = np.array([[0,2**32-1]],np.uint32)
        got = s.load(uint,np.array([[0,0],[1,0]],np.int32))
        self.assertEqual(got.values.dtype,np.dtype(np.uint32))
        np.testing.assert_array_equal(got.values,uint[0])
        zeros = np.array([[0.,-0.]],np.float32)
        got = s.load(zeros,np.array([[0,0],[1,0]]))
        np.testing.assert_array_equal(got.values.view(np.uint32),zeros[0].view(np.uint32))
        with self.assertRaises(TypeError):
            s.load(zeros,[.1,0.])

    def test_load_zero_is_not_unknown_interior_crop(self):
        crop = plane(3,3)
        domain = s.TextureDomain((9,7),crop_origin=(3,2))
        result = s.load(crop,np.array([[-1,0],[2,2],[3,2],[9,6]]),domain=domain)
        np.testing.assert_array_equal(result.supported,[True,False,True,True])
        self.assertEqual(result.values[0],0)
        self.assertTrue(np.isnan(result.values[1]))
        self.assertEqual(result.values[-1],0)
        with self.assertRaises(s.UnsupportedSampleError):
            result.require_supported()

    def test_one_by_one_all_corners_and_outside_clamp(self):
        tex = np.array([[[.1,-2,65504,-0.]]],np.float32)
        uv = np.array([[0,0],[1,0],[0,1],[1,1],[.31,.79],[-3,2],[1e20,-1e20]])
        for mode in ("ideal","source","observed"):
            for sampler in (s.sample_point,s.sample_bilinear):
                result = sampler(tex,uv,mode=mode)
                expected = np.broadcast_to(tex[0,0],result.values.shape)
                np.testing.assert_array_equal(result.values,expected)
                self.assertTrue(np.all(result.supported))
        np.testing.assert_array_equal(s.sample_bilinear(tex,uv).in_bounds,[True,True,True,True,True,False,False])

    def test_all_small_odd_extent_centres_and_corners(self):
        for height in (1,3,5):
            for width in (1,3,7):
                tex = plane(width,height)
                xy = c.pixel_grid((width,height),mode="ideal")
                uv = c.texel_to_uv(xy,(width,height),mode="ideal")
                for sampler in (s.sample_bilinear,s.sample_point):
                    np.testing.assert_allclose(sampler(tex,uv,mode="ideal").values,tex,rtol=0,atol=1e-13)
                corners = np.array([[0,0],[1,0],[0,1],[1,1]])
                np.testing.assert_array_equal(s.sample_bilinear(tex,corners).values,
                                               [tex[0,0],tex[0,-1],tex[-1,0],tex[-1,-1]])

    def test_affine_field_and_wrong_nearest_negative_control(self):
        tex = plane(17,11)
        xy = np.array([[3.25,2.5],[5.125,6.875],[.5,.75]])
        ideal = s.bilinear_texel(tex,xy).values
        np.testing.assert_array_equal(ideal,xy[:,0]+10*xy[:,1])
        nearest = s.sample_point(tex,c.texel_to_uv(xy,(17,11),mode="ideal")).values
        self.assertTrue(np.all(nearest != ideal))

    def test_dynamic_resolution_wrong_uv_scaling_is_detected(self):
        tex = plane(17,11)
        domain = s.TextureDomain((17,11),active_extent=(13,7))
        xy = np.array([[3,2],[3.25,2.5]])
        right = s.sample_bilinear(tex,c.texel_to_uv(xy,(17,11),mode="ideal"),domain=domain).values
        wrong = s.sample_bilinear(tex,c.texel_to_uv(xy,(13,7),mode="ideal"),domain=domain).values
        np.testing.assert_allclose(right,xy[:,0]+10*xy[:,1],atol=1e-13)
        self.assertTrue(np.all(abs(right-wrong)>10))

    def test_active_padding_is_observed_but_not_active(self):
        tex = plane(8,4)
        domain = s.TextureDomain((8,4),active_extent=(5,3))
        result = s.bilinear_texel(tex,np.array([[4,2],[4.25,2],[6,2]]),domain=domain)
        self.assertTrue(np.all(result.supported))
        np.testing.assert_array_equal(result.active_support,[True,False,False])
        with self.assertRaises(s.UnsupportedSampleError):
            result.require_supported(active=True)

    def test_crop_zero_weight_tap_and_positive_weight_absence(self):
        full = plane(9,7)
        crop = full[2:5,3:6].copy()
        domain = s.TextureDomain((9,7),crop_origin=(3,2))
        xy = np.array([[5,4],[5.0001,4],[4.5,3.5],[2.99,3],[5,4.001]])
        result = s.bilinear_texel(crop,xy,domain=domain,mode="ideal")
        np.testing.assert_array_equal(result.supported,[True,False,True,False,False])
        np.testing.assert_array_equal(result.values[result.supported],
                                       s.bilinear_texel(full,xy).values[result.supported])
        self.assertTrue(np.all(np.isnan(result.values[~result.supported])))

    def test_crop_touching_true_allocation_edge_can_clamp(self):
        full = plane(9,7)
        crop = full[4:7,6:9].copy()
        domain = s.TextureDomain((9,7),crop_origin=(6,4))
        result = s.sample_bilinear(crop,np.array([[1,1],[1.5,1.5]]),domain=domain)
        self.assertTrue(np.all(result.supported))
        np.testing.assert_array_equal(result.values,[68,68])

    def test_nonfinite_uv_fails_support_not_plausible_edge(self):
        uv = np.array([[np.nan,.5],[np.inf,.5],[-np.inf,.5]])
        for sampler in (s.sample_point,s.sample_bilinear):
            result = sampler(plane(3,3),uv)
            self.assertFalse(np.any(result.supported))
            self.assertTrue(np.all(np.isnan(result.values)))

    def test_sampler_border_zero_and_invalid_are_explicit_policies(self):
        tex = np.array([[8.]],np.float32)
        corners = np.array([[0,0],[1,0],[0,1],[1,1]],np.float32)
        zeros = s.sample_bilinear(tex,corners,address="zero")
        np.testing.assert_array_equal(zeros.values,[2,2,2,2])
        self.assertTrue(np.all(zeros.supported))
        self.assertFalse(np.any(zeros.active_support))
        invalid = s.sample_bilinear(tex,corners,address="invalid")
        self.assertFalse(np.any(invalid.supported))

    def test_four_tap_stats_preserve_partial_crop_support(self):
        full = plane(16,16)
        crop = full[4:8,4:8]
        domain = s.TextureDomain((16,16),crop_origin=(4,4))
        cells = np.array([[1,1],[2,1]])
        result = s.sample_cell_four_taps(crop,cells,4,domain=domain)
        np.testing.assert_array_equal(result.supported,[True,False])
        self.assertEqual(result.values[0],np.mean(crop))
        self.assertTrue(np.isnan(result.values[1]))

    def test_zero_weight_nan_payload_is_explicitly_ignored(self):
        tex = np.array([[1,np.nan],[np.inf,-np.inf]],np.float32)
        for interp in ("separable_lerp","weighted_sum"):
            result = s.bilinear_texel(tex,np.array([0.,0.]),interpolation=interp)
            self.assertEqual(result.values,1)
            self.assertTrue(result.supported)
        self.assertTrue(np.isnan(s.bilinear_texel(tex,np.array([.5,0])).values))

    def test_constant_fields_separable_identity_and_weighted_arithmetic_control(self):
        rng = np.random.default_rng(2026102001)
        xy = rng.uniform([0,0],[6,4],size=(512,2))
        tex = np.full((5,7,3),[.1,-7.3,21.1],np.float32)
        for mode in ("ideal","source","observed"):
            result = s.bilinear_texel(tex,xy,mode=mode)
            np.testing.assert_array_equal(result.values,np.broadcast_to(tex[0,0],result.values.shape))
        # Float32 weighted source emulation is intentionally not mislabeled
        # an exact API sampler. The invariant catches its roundoff.
        weighted = s.bilinear_texel(tex,xy,mode="source",interpolation="weighted_sum")
        self.assertGreater(np.count_nonzero(weighted.values != tex[0,0]),0)
        np.testing.assert_allclose(weighted.values,np.broadcast_to(tex[0,0],weighted.values.shape),rtol=3e-7,atol=0)

    def test_integer_translation_equivalence_away_from_boundaries(self):
        rng = np.random.default_rng(2026102002)
        original = rng.normal(size=(13,19,4)).astype(np.float32)
        translated = np.zeros((17,25,4),np.float32)
        translated[2:15,3:22] = original
        # Dyadic phases preserve exact float32 coordinate fractions.
        xy = rng.integers([1,1],[16,10],size=(128,2)) + rng.integers(0,8,size=(128,2))/8
        for mode in ("ideal","source","observed"):
            before = s.bilinear_texel(original,xy,mode=mode).values
            after = s.bilinear_texel(translated,xy+[3,2],mode=mode).values
            np.testing.assert_array_equal(before,after)

    def test_independent_lobes_and_channels(self):
        rng = np.random.default_rng(2026102003)
        tex = rng.uniform(-1,1,size=(7,9,2,4)).astype(np.float32)
        xy = rng.uniform([0,0],[8,6],size=(100,2))
        for mode in ("source","observed"):
            all_channels = s.bilinear_texel(tex,xy,mode=mode).values
            for lobe in range(2):
                for channel in range(4):
                    scalar = s.bilinear_texel(tex[:,:,lobe,channel],xy,mode=mode).values
                    np.testing.assert_array_equal(scalar,all_channels[:,lobe,channel])

    def test_fraction_rounding_endpoints_halfway_and_carry(self):
        fractions = np.array([0,.5/256,1.5/256,255.5/256,1],np.float32)
        np.testing.assert_array_equal(s.quantize_fraction(fractions),[0,0,2/256,1,1])
        np.testing.assert_array_equal(s.quantize_fraction(fractions,rounding="nearest_up"),[0,1/256,2/256,1,1])
        # An observed point address immediately below a boundary may snap up.
        tex = np.array([[2,9]],np.float32)
        uv = np.array([[.4999,.5]])
        self.assertEqual(s.sample_point(tex,uv,mode="ideal").values[0],2)
        self.assertEqual(s.sample_point(tex,uv,mode="observed").values[0],9)

    def test_inactive_fraction_option_unused_rounding_does_not_change_result(self):
        tex = plane(5,3)
        xy = np.array([[1.321,.476],[3.07,1.71]])
        a = s.bilinear_texel(tex,xy,mode="source",fraction_bits=None,fraction_rounding="unused-A")
        b = s.bilinear_texel(tex,xy,mode="source",fraction_bits=None,fraction_rounding="unused-B")
        np.testing.assert_array_equal(a.values,b.values)

    def test_phase_sensitive_hard_depth_gate_is_not_hidden_by_mean_error(self):
        # Analytic fixed population: depth = 1 + .04*x, expected depth=1.
        # Quant8 ties at .5 are accepted whereas ideal x>.5 is rejected.
        phase = np.array([.499,.5,.5001,.501,.502],np.float64)
        texture = np.array([[1.,1.04]],np.float32)
        xy = np.column_stack((phase,np.zeros_like(phase)))
        ideal = s.bilinear_texel(texture,xy,mode="ideal").values
        observed = s.bilinear_texel(texture,xy,mode="observed").values
        threshold = np.float64(1.02)
        ideal_gate, observed_gate = ideal <= threshold, observed <= threshold
        self.assertEqual(int(np.count_nonzero(ideal_gate != observed_gate)),2)
        np.testing.assert_array_equal(ideal_gate,[True,True,False,False,False])
        np.testing.assert_array_equal(observed_gate,[True,True,True,True,False])

    def test_four_colour_taps_mean_all16_but_anchor_is_sparse16_of64(self):
        colour = np.zeros((4,4),np.float32)
        for y in range(4):
            for x in range(4):
                colour.fill(0); colour[y,x] = 1
                self.assertEqual(s.sample_cell_four_taps(colour,np.array([0,0]),4).values,1/16)
        anchor = np.zeros((8,8),np.float32)
        counts = []
        for y in range(8):
            for x in range(8):
                anchor.fill(0); anchor[y,x] = 1
                counts.append(float(s.sample_cell_four_taps(anchor,np.array([0,0]),8).values))
        self.assertEqual(counts.count(1/16),16)
        self.assertEqual(counts.count(0),48)
        self.assertEqual(sum(counts),1)

    def test_documented_envelope_contains_named_profiles_and_constant_identity(self):
        rng = np.random.default_rng(2026102004)
        tex = rng.uniform(-10,10,size=(7,11,3)).astype(np.float32)
        uv = rng.uniform(0,1,size=(100,2)).astype(np.float32)
        envelope = s.documented_bilinear_envelope(tex,uv)
        self.assertTrue(np.all(envelope.supported))
        for bits in (8,9,12,16):
            result = s.sample_bilinear(tex,uv,mode="observed",fraction_bits=bits).values
            self.assertTrue(np.all(result >= envelope.lower))
            self.assertTrue(np.all(result <= envelope.upper))
        constant = s.documented_bilinear_envelope(np.full((7,11),.1,np.float32),uv)
        np.testing.assert_array_equal(constant.lower,constant.upper)
        np.testing.assert_array_equal(constant.lower,np.full(100,np.float32(.1)))

    def test_documented_envelope_does_not_invent_crop_data(self):
        domain = s.TextureDomain((9,7),crop_origin=(3,2))
        uv = c.texel_to_uv(np.array([[4,3],[5.2,3]]),(9,7))
        envelope = s.documented_bilinear_envelope(plane(3,3),uv,domain=domain)
        np.testing.assert_array_equal(envelope.supported,[True,False])
        self.assertTrue(np.isnan(envelope.lower[1]))

    def test_float32_lerp_overflow_is_rejected_by_api_envelope(self):
        # A source-expression diagnostic chosen by independent review. This
        # overflow is not rebranded as hardware SampleLevel behavior.
        largest = np.finfo(np.float32).max
        tex = np.array([[largest,-largest]],np.float32)
        uv = np.array([.5,.5])
        modeled = s.sample_bilinear(tex,uv,mode="source").values
        ideal = s.sample_bilinear(tex,uv,mode="ideal").values
        envelope = s.documented_bilinear_envelope(tex,uv)
        self.assertFalse(np.isfinite(modeled))
        self.assertEqual(ideal,0)
        self.assertFalse(bool((modeled >= envelope.lower) & (modeled <= envelope.upper)))

    def test_frozen_weighted_sampler_is_reproduced_exactly(self):
        reference_path = ROOT.parents[1]/"portable"/"colour"/"colour_portable.py"
        spec = importlib.util.spec_from_file_location("_sampling_frozen_reference",reference_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        rng = np.random.default_rng(2026102005)
        for shape in ((9,13),(9,13,4)):
            texture = rng.normal(size=shape).astype(np.float32)
            xy = rng.uniform([-3,-2],[16,11],size=(113,2)).astype(np.float32)
            expected = module.bilinear(texture,xy[:,0],xy[:,1])
            actual = s.bilinear_texel(texture,xy,mode="source",interpolation="weighted_sum").values
            np.testing.assert_array_equal(actual,expected)


if __name__ == "__main__":
    unittest.main()
