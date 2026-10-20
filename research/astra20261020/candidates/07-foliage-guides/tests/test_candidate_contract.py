"""Meaningful contract tests plus an explicit crop-clamping mutant kill.

Normal run: python -m unittest discover -s <candidate>/tests -p 'test_candidate*.py'
Expected failing mutant: python <this-file> --mutant-clamp-history
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import foliage_guides as fg
from synthetic_scene import SceneConfig,generate_scene,identical_observations
from proxy_metrics import run_proxy,paired_light_response,gradient_transfer
from transport_discriminator import run_discriminator


def frame(h=7,w=9,*,frame_id=10,depth=12.0,category=0,origin=(0,0),extent=None):
    n=np.zeros((h,w,3),np.float32);n[...,2]=1
    return fg.GuideFrame(fg.pack_normal_roughness(n,.4,category),np.full((h,w),depth,np.float32),
                         np.zeros((h,w,4),np.float16),frame_id,origin,extent or (w,h),True)


class CandidateContract(unittest.TestCase):
    def test_oct_cardinal_and_oblique_decode_and_codes(self):
        normals=fg.normalize(np.array([[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1],
                                      [.2,.3,.9],[-.7,.2,-.5]],np.float32))
        for code in range(4):
            packed=fg.pack_normal_roughness(normals,.37,code)
            decoded,rough,category=fg.unpack_normal_roughness(packed)
            angle=np.degrees(np.arccos(np.clip(np.sum(normals*decoded,axis=-1),-1,1)))
            self.assertLess(float(angle.max()),.3)
            self.assertTrue(np.all(category==code))
            self.assertTrue(np.all(np.abs(rough-.37)<=.5/1023))

    def test_off_identity_and_input_bytes(self):
        a=frame();b=replace(a,frame_id=11)
        before=[x.tobytes() for x in (a.packed_normal_roughness,a.depth,a.motion,b.packed_normal_roughness)]
        for enabled in (False,True):
            o=fg.observe_guides(b,a,enabled=enabled)
            self.assertTrue(np.all(o.experimental_history_multiplier==1))
            if not enabled:self.assertFalse(np.any(o.flags))
        after=[x.tobytes() for x in (a.packed_normal_roughness,a.depth,a.motion,b.packed_normal_roughness)]
        self.assertEqual(before,after)

    def test_outside_crop_never_manufactures_history(self):
        a=frame();b=replace(a,frame_id=11)
        b.motion[...,:2]=np.array([2,0],np.float16)
        o=fg.observe_guides(b,a,enabled=True)
        self.assertFalse(np.any(o.temporal_supported))
        self.assertTrue(np.all(o.experimental_history_multiplier==1))
        self.assertFalse(np.any(o.flags & int(fg.SupportFlag.IN_PREVIOUS_CROP)))

    def test_crop_origin_changes_previous_local_coordinate(self):
        a=frame(h=6,w=8,origin=(10,20),extent=(100,80));b=frame(h=6,w=8,frame_id=11,origin=(11,20),extent=(100,80))
        # q=current+1: two columns, not one, lack a complete previous footprint.
        o=fg.observe_guides(b,a,enabled=True)
        self.assertTrue(np.all(o.temporal_supported[:-1,:-2]))
        self.assertFalse(np.any(o.temporal_supported[:,-2:]))
        self.assertFalse(np.any(o.temporal_supported[-1]))

    def test_numpy_metadata_does_not_promote_transport_arithmetic(self):
        uv=np.full((4,5,2),.0037,np.float32)
        a,valid_a=fg.bilinear_coordinates(4,5,uv,(1505,847),(11,13),(9,12),(20,20))
        b,valid_b=fg.bilinear_coordinates(4,5,uv,(np.int32(1505),np.int32(847)),
                                        (np.int32(11),np.int32(13)),(np.int32(9),np.int32(12)),(20,20))
        np.testing.assert_array_equal(valid_a,valid_b)
        for ta,tb in zip(a,b):
            np.testing.assert_array_equal(ta[2],tb[2])
            self.assertEqual(ta[2].dtype,np.float32)

    def test_depth_delta_sign_and_material_equality(self):
        a=frame(depth=13);b=frame(frame_id=11,depth=12)
        b.motion[...,2]=1
        good=fg.observe_guides(b,a,enabled=True)
        self.assertTrue(np.all(good.temporal_supported[:-1,:-1]))
        b.motion[...,2]=-1
        self.assertFalse(np.any(fg.observe_guides(b,a,enabled=True).temporal_supported))
        b.motion[...,2]=1
        wrong_category=frame(depth=13,category=1)
        self.assertFalse(np.any(fg.observe_guides(b,wrong_category,enabled=True).temporal_supported))

    def test_four_taps_and_invalid_data(self):
        a=frame();b=frame(frame_id=11)
        a.depth[2,2]=np.nan
        o=fg.observe_guides(b,a,enabled=True)
        # Even zero-weight neighbour taps are required by the conservative ABI.
        self.assertFalse(o.temporal_supported[1,1])
        b.motion[3,3,0]=np.inf
        self.assertFalse(fg.observe_guides(b,a,enabled=True).temporal_supported[3,3])

    def test_unknown_depth_reset_and_nonconsecutive_identity(self):
        a=frame();b=frame(frame_id=11)
        for current,previous in [(replace(b,depth_is_positive_linear=False),a),
                                 (replace(b,reset=True),a),(replace(b,frame_id=12),a),(b,None)]:
            o=fg.observe_guides(current,previous,enabled=True)
            self.assertFalse(np.any(o.temporal_supported))
            self.assertTrue(np.all(o.experimental_history_multiplier==1))

    def test_extreme_span_finite_and_predicted_depth_invalid(self):
        a=frame(depth=1e-20);b=frame(frame_id=11,depth=1e-20)
        b.depth[1,1]=3e38
        o=fg.observe_guides(b,a,enabled=True)
        self.assertTrue(np.all(np.isfinite(o.relative_depth_span)))
        c=frame(frame_id=11,depth=1e-10);p=frame(depth=1e-10)
        motion=c.motion.astype(np.float32);motion[...,2]=-2e-10
        self.assertFalse(np.any(fg.observe_guides(replace(c,motion=motion),p,enabled=True).temporal_supported))

    def test_guide_only_identifiability_collision(self):
        c=identical_observations()
        self.assertGreater(float(np.abs(c["plane_radiance"]-c["mixture_radiance"]).max()),.1)
        o=fg.observe_guides(c["frames"][1],c["frames"][0],enabled=True)
        self.assertTrue(np.all(o.experimental_history_multiplier[o.temporal_supported]>.9999))
        self.assertEqual(c["frames"][0].packed_normal_roughness.tobytes(),c["frames"][1].packed_normal_roughness.tobytes())

    def test_sanitized_depth_is_not_proven_physical_validity(self):
        # The same numeric inputs could represent a real plane or invalid raw
        # geometry sanitized upstream. There is no raw-validity channel here.
        p=frame(depth=.02);c=frame(depth=.02,frame_id=11)
        physical_unknown=fg.observe_guides(c,p,enabled=True)
        physical_known=fg.observe_guides(c,p,enabled=True)
        self.assertTrue(np.array_equal(physical_unknown.flags,physical_known.flags))
        self.assertTrue(np.any(physical_unknown.temporal_supported))
        # This explicit collision is a limitation test, not a validation claim.

    def test_crop_clamp_mutant_is_killed(self):
        proc=subprocess.run([sys.executable,str(Path(__file__).resolve()),"--mutant-clamp-history"],
                            capture_output=True,text=True,check=False)
        self.assertNotEqual(proc.returncode,0)
        self.assertIn("FAIL",proc.stderr)


class SyntheticContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=SceneConfig(width=24,height=16,frames=6)
        cls.scene=generate_scene(cls.config)

    def test_coverage_decomposition_and_alpha_preservation(self):
        s=self.scene
        np.testing.assert_array_equal(s.coverage.sum(axis=-1),np.ones(s.coverage.shape[:-1],np.float32))
        np.testing.assert_allclose(np.sum(s.coverage[...,None]*s.layer_truth,axis=-2),s.truth,rtol=1e-6,atol=1e-7)
        expected=s.diffuse_rgba[...,:3].astype(np.float32)+s.specular_rgba[...,:3].astype(np.float32)
        np.testing.assert_array_equal(expected,s.observed)
        output=run_proxy(s,"diagnostic_identity")
        np.testing.assert_array_equal(output.rgb,s.observed)
        self.assertTrue(np.all(s.diffuse_rgba[...,3]==np.float16(3.25)))
        self.assertTrue(np.all(s.specular_rgba[...,3]==np.float16(7.5)))
        self.assertFalse(s.masks["interior"].flags.writeable)
        self.assertFalse(s.frames[0].packed_normal_roughness.flags.writeable)

    def test_observation_intervention_keeps_lighting_rng_fixed(self):
        c=self.config
        a=self.scene;b=generate_scene(replace(c,guide_rule="stochastic_sample"))
        np.testing.assert_array_equal(a.observed,b.observed)
        np.testing.assert_array_equal(a.truth,b.truth)
        np.testing.assert_array_equal(a.coverage,b.coverage)
        self.assertTrue(any(not np.array_equal(x.packed_normal_roughness,y.packed_normal_roughness) for x,y in zip(a.frames,b.frames)))

    def test_noise_correlation_changes_only_lighting_family(self):
        a=self.scene;b=generate_scene(replace(self.config,noise_rho=.95))
        np.testing.assert_array_equal(a.coverage,b.coverage)
        np.testing.assert_array_equal(a.truth,b.truth)
        for x,y in zip(a.frames,b.frames):
            np.testing.assert_array_equal(x.packed_normal_roughness,y.packed_normal_roughness)
            np.testing.assert_array_equal(x.motion,y.motion)
        self.assertFalse(np.array_equal(a.observed,b.observed))

    def test_exact_guide_is_real_sample_normal_before_quantization(self):
        s=self.scene
        # The source normal is unit length, and a disclosed oct quantization is
        # the sole difference between stored and full-precision observed guide.
        np.testing.assert_allclose(np.linalg.norm(s.exact_dominant_normal,axis=-1),1,rtol=1e-6,atol=1e-6)
        q=np.stack([fg.unpack_normal_roughness(f.packed_normal_roughness)[0] for f in s.frames])
        error=np.degrees(np.arccos(np.clip(np.sum(q*s.exact_dominant_normal,axis=-1),-1,1)))
        self.assertLess(float(error.max()),.3)

    def test_moderate_light_response_has_correct_raw_identity(self):
        c=replace(self.config,noise_strength=0,sparse_probability=0,light_step=1.1)
        stepped=generate_scene(c);same=generate_scene(replace(c,light_step=1.0))
        ratio=paired_light_response(stepped,run_proxy(stepped,"raw_half_inputs"),same,run_proxy(same,"raw_half_inputs"))
        self.assertAlmostEqual(ratio,1,delta=.005)

    def test_rigid_texture_detail_rotation_is_equivalent(self):
        y,x=np.indices((10,12))
        a=np.broadcast_to(((x%2)*.8+.1)[None],(3,10,12));mask=np.ones(a.shape,bool)
        self.assertAlmostEqual(gradient_transfer(a,a,mask),1)
        self.assertAlmostEqual(gradient_transfer(a.transpose(0,2,1),a.transpose(0,2,1),mask.transpose(0,2,1)),1)
        self.assertEqual(gradient_transfer(a,np.ones_like(a)*.5,mask),0)

    def test_single_motion_cannot_transport_two_layers(self):
        r=run_discriminator()
        self.assertLess(r["normalized_rgb_rmse"]["oracle_per_layer_motion"],1e-6)
        self.assertGreater(r["normalized_rgb_rmse"]["dominant_layer_motion"],.1)
        self.assertLess(r["maximum_observable_temporal_innovation"],1e-6)


if __name__=="__main__":
    if "--mutant-clamp-history" in sys.argv:
        original=fg.bilinear_coordinates
        def mutant(*args,**kwargs):
            taps,inside=original(*args,**kwargs)
            return taps,np.ones_like(inside)
        fg.bilinear_coordinates=mutant
        suite=unittest.TestSuite([CandidateContract("test_outside_crop_never_manufactures_history")])
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(0 if result.wasSuccessful() else 1)
    unittest.main()
