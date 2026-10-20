"""Portable contract tests. --mutate-ignore-crop must fail, not pass."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import support_tracer as st


class Coordinates(unittest.TestCase):
    def test_crop_origin_cancels_physical_motion(self):
        motion=np.zeros((5,7,4));motion[...,:2]=[-.02,-.01]
        qx,qy,ok=st.previous_coordinates(motion,[12,21],[10,20],[100,100])
        yy,xx=np.mgrid[:5,:7]
        np.testing.assert_allclose(qx,xx,atol=1e-12)
        np.testing.assert_allclose(qy,yy,atol=1e-12)
        self.assertEqual(int(ok.sum()),24)

    def test_exact_frozen_helper_equivalence(self):
        rng=np.random.default_rng(142)
        a={"input_motion":rng.normal(0,.003,(2,7,9,4)).astype(np.float16),
           "crop_origin_render":np.array([[11,21],[13,22]]),"render_extent":np.array([1505,847])}
        expected=st._clip.previous_coordinates(a,1)
        actual=st.previous_coordinates(a['input_motion'][1],a['crop_origin_render'][1],a['crop_origin_render'][0],a['render_extent'])
        for left,right in zip(actual,expected): np.testing.assert_array_equal(left,right)

    def test_no_clamp_wrap_or_nonfinite_history(self):
        image=np.arange(20.).reshape(4,5)
        x=np.array([[-.001,0,3.999,4,np.nan,np.inf]])
        y=np.array([[1,1,1,1,1,1]])
        values,valid=st.sample_previous(image,x,y)
        np.testing.assert_array_equal(valid,[[False,True,True,False,False,False]])
        self.assertTrue(np.isnan(values[~valid]).all())
        self.assertEqual(values[0,1],5)

    def test_explicit_convention_rejects_implicit_conversion(self):
        with self.assertRaises(ValueError):
            st.previous_coordinates(np.zeros((4,4,4)),[0,0],[0,0],[4,4],convention=st.CoordinateConvention(units='crop_pixels'))
        with self.assertRaises(ValueError):
            st.previous_coordinates(np.zeros((4,4,4)),[0,0],[0,0],[0,4])

    def test_mixed_extents_and_sentinel_dz_are_not_clamped(self):
        motion=np.zeros((5,7,4),np.float16);motion[...,2]=-65504
        qx,qy,ok=st.previous_coordinates(motion,[0,0],[0,0],[100,100],previous_shape=(4,6))
        self.assertEqual(ok.sum(),15)
        np.testing.assert_array_equal(qx,np.broadcast_to(np.arange(7),(5,7)))


class Tracing(unittest.TestCase):
    def test_first_frame_and_gap_have_no_history(self):
        data=np.ones((3,4,5,4),np.float16)
        stages={'raw':data,'selected':data.copy()}
        rows=list(st.trace_stages(stages,np.zeros((3,4,5,4)),np.zeros((3,2)),[100,100],[180,181,183],{'raw':.1,'selected':.1}))
        self.assertFalse(rows[0]['has_previous'])
        self.assertTrue(rows[1]['has_previous'])
        self.assertFalse(rows[2]['has_previous'])
        self.assertFalse(rows[0]['coordinate_valid'].any())
        self.assertTrue(np.isnan(rows[2]['stages']['raw']['transported_previous_support']).all())
        self.assertEqual(rows[1]['stages']['raw']['history_valid'].sum(),12)

    def test_unknown_nonfinite_sample_not_asserted_absent(self):
        stages={'raw':np.ones((2,4,4),float)}
        stages['raw'][0,1,1]=np.nan
        rows=list(st.trace_stages(stages,np.zeros((2,4,4,4)),np.zeros((2,2)),[100,100],[0,1],{'raw':.1}))
        self.assertFalse(rows[1]['stages']['raw']['history_valid'][1,1])
        self.assertTrue(np.isnan(rows[1]['stages']['raw']['transported_previous_support'][1,1]))

    def test_unlooped_chronology_and_fixed_threshold_required(self):
        a=np.ones((2,4,4))
        with self.assertRaises(ValueError):
            list(st.trace_stages({'raw':a},np.zeros((2,4,4,4)),np.zeros((2,2)),[100,100],[2,1],{'raw':.1}))
        with self.assertRaises(ValueError):
            list(st.trace_stages({'raw':a},np.zeros((2,4,4,4)),np.zeros((2,2)),[100,100],[1,2],{}))

    def test_identity_preserves_every_bit_and_ownership(self):
        bits=np.array([0,0x8000,0x7e03,0x7c00,0x3c00,0xfc00,0x0001,0x4000],np.uint16)
        value=bits.view(np.float16).reshape(1,2,4)
        copied=st.abstain_identity(value)
        self.assertEqual(copied.tobytes(),value.tobytes())
        self.assertFalse(np.shares_memory(value,copied))

    def test_nonfinite_untrusted_or_missing_authority_abstains(self):
        valid={"evidence_domain":"analytic_synthetic","independent_geometry":True,
               "known_support":True,"guide_authority":True,"geometry_error_px":0.,
               "raw_offsupport_fraction":0.,"rr_offsupport_fraction":0.,
               "selected_offsupport_fraction":0.,"raw_support_fraction":1.,"virtual_error_px":None}
        self.assertEqual(st.diagnose(valid)["diagnosis"],"no_detected_support_error")
        self.assertFalse(st.diagnose(valid)["virtual_correspondence_observable"])
        for key,value in (("geometry_error_px",np.nan),("geometry_error_px",-1),
                          ("raw_support_fraction",1.1),("raw_offsupport_fraction",None),
                          ("virtual_error_px",np.inf),("guide_authority",None),
                          ("evidence_domain","game_capture")):
            malformed=dict(valid);malformed[key]=value
            self.assertEqual(st.diagnose(malformed)["diagnosis"],"non_identifiable")

    def test_missing_authority_never_edits_image_or_blames_motion(self):
        result=st.diagnose({'geometry_error_px':100,'raw_offsupport_fraction':.8})
        self.assertEqual(result['diagnosis'],'non_identifiable')
        self.assertEqual(result['production_action'],'identity')


class ShapeMetrics(unittest.TestCase):
    def test_level_only_darkening_is_not_shape_repair(self):
        truth=np.zeros((4,12,18));truth[:,3:9,7:10]=1
        mask=truth>0;centres=np.tile([8,6],(4,1));velocity=np.tile([1,0],(4,1))
        base=st.metric_sequence(truth,truth,mask,centres,velocity)['summary']
        dark=st.metric_sequence(truth*.2,truth,mask,centres,velocity)['summary']
        shift=st.metric_sequence(np.roll(truth,2,axis=2),truth,mask,centres,velocity)['summary']
        self.assertAlmostEqual(base['level_matched_shape_iou'],dark['level_matched_shape_iou'])
        self.assertAlmostEqual(dark['level_ratio'],.2)
        self.assertIsNone(dark['occupancy_lag_px'])
        self.assertEqual(dark['level_matched_occupancy_lag_px'],0.)
        self.assertLess(shift['level_matched_shape_iou'],base['level_matched_shape_iou'])
        self.assertNotEqual(shift['occupancy_lag_px'],0)

    def test_empty_sequence_or_evaluation_universe_rejected(self):
        for a,mask in ((np.zeros((0,4,4)),np.zeros((0,4,4),bool)),
                       (np.zeros((2,4,4)),np.zeros((2,4,4),bool))):
            with self.assertRaises(ValueError):
                st.metric_sequence(a,a,mask,np.zeros((len(a),2)),np.zeros((len(a),2)),universe=mask)

    def test_unobserved_disocclusion_is_not_inferred_from_local_footprints(self):
        a=np.zeros((2,8,8));a[:,2:5,2:5]=1
        metrics=st.metric_sequence(a,a,a>0,np.zeros((2,2)),np.ones((2,2)))['summary']
        self.assertIsNone(metrics['disocclusion_leakage'])

    def test_seed_bootstrap_is_deterministic(self):
        left=st.confidence_interval([1.,2.,3.,4.]);right=st.confidence_interval([1.,2.,3.,4.])
        self.assertEqual(left,right)
        self.assertEqual(left['independent_seeds'],4)
        self.assertLessEqual(left['ci95'][0],left['mean'])
        self.assertGreaterEqual(left['ci95'][1],left['mean'])


if __name__=='__main__':
    if '--mutate-ignore-crop' in sys.argv:
        sys.argv.remove('--mutate-ignore-crop')
        original=st.previous_coordinates
        def mutated(motion_uv,current_origin,previous_origin,render_extent,previous_shape=None,convention=st.CoordinateConvention()):
            return original(motion_uv,[0,0],[0,0],render_extent,previous_shape,convention)
        st.previous_coordinates=mutated
    unittest.main(verbosity=2)
