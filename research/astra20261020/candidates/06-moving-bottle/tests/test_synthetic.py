"""Tests discriminate mechanisms instead of asserting a denoising win."""
from pathlib import Path
import sys
import unittest
from dataclasses import replace
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from synthetic_scenes import SceneConfig, make_scene, intervene
from synthetic_experiments import observations, TRAIN, HOLDOUT, TRAIN_SEEDS, HOLDOUT_SEEDS, fixed_geometry_masks
from support_tracer import diagnose, abstain_identity, metric_sequence


class SyntheticContracts(unittest.TestCase):
    def test_delayed_source_vs_clean_source_wrong_motion(self):
        delayed=observations(make_scene(TRAIN,100,'source_delay'))
        wrong=observations(make_scene(TRAIN,100,'mv_bias'))
        self.assertLess(delayed['geometry_error_px'],1e-4)
        self.assertGreater(delayed['raw_offsupport_fraction'],.12)
        self.assertGreater(wrong['geometry_error_px'],.45)
        self.assertEqual(wrong['raw_offsupport_fraction'],0)
        self.assertEqual(diagnose(delayed)['diagnosis'],'source_support_error')
        self.assertEqual(diagnose(wrong)['diagnosis'],'transport_error')

    def test_sparse_correct_motion_is_not_motion_failure(self):
        obs=observations(make_scene(TRAIN,101,'sparse_source'))
        self.assertLess(obs['geometry_error_px'],1e-4)
        self.assertLess(obs['raw_support_fraction'],.65)
        self.assertEqual(diagnose(obs)['diagnosis'],'sparse_source_no_motion_blame')

    def test_stage_swap_localizes_synthetic_tail(self):
        provider=make_scene(TRAIN,100,'provider_tail')
        selected=make_scene(TRAIN,100,'selected_tail')
        self.assertEqual(diagnose(observations(provider))['diagnosis'],'provider_stage_tail')
        self.assertEqual(diagnose(observations(selected))['diagnosis'],'selected_stage_tail')
        changed=intervene(selected,'observe_raw_instead_selected')
        self.assertEqual(observations(changed)['selected_offsupport_fraction'],0)
        np.testing.assert_array_equal(changed['raw'],selected['raw'])
        np.testing.assert_array_equal(changed['motion'],selected['motion'])

    def test_oracle_motion_does_not_repair_delayed_input(self):
        scene=make_scene(TRAIN,100,'source_delay')
        changed=intervene(scene,'oracle_motion')
        self.assertEqual(observations(scene)['raw_offsupport_fraction'],observations(changed)['raw_offsupport_fraction'])
        np.testing.assert_array_equal(scene['raw'],changed['raw'])

    def test_oracle_support_does_not_repair_wrong_motion(self):
        scene=make_scene(TRAIN,100,'mv_bias')
        changed=intervene(scene,'oracle_support')
        self.assertEqual(observations(scene)['geometry_error_px'],observations(changed)['geometry_error_px'])
        np.testing.assert_array_equal(scene['motion'],changed['motion'])

    def test_virtual_motion_is_not_surface_motion_or_generic_depth(self):
        scene=make_scene(TRAIN,100,'virtual_mismatch')
        obs=observations(scene)
        self.assertLess(obs['geometry_error_px'],1e-4)
        self.assertGreater(obs['virtual_error_px'],.45)
        self.assertEqual(diagnose(obs)['diagnosis'],'virtual_correspondence_error')
        zero=make_scene(replace(TRAIN,hit_distance=0),100,'zero_hit_distance')
        self.assertIsNone(observations(zero)['virtual_error_px'])

    def test_partial_reentry_mask_and_unseen_noise_holdout(self):
        self.assertNotEqual(TRAIN.trajectory,HOLDOUT.trajectory)
        self.assertNotEqual(TRAIN.noise_family,HOLDOUT.noise_family)
        self.assertFalse(set(TRAIN_SEEDS)&set(HOLDOUT_SEEDS))
        scene=make_scene(HOLDOUT,900,'clean')
        counts=scene['truth_mask'].sum((1,2))
        self.assertEqual(counts.min(),0)
        self.assertGreater(counts[-1],0)
        masks=fixed_geometry_masks(scene)
        self.assertFalse(masks[0].any())
        self.assertTrue(np.all(masks.sum((1,2))<=counts))

    def test_crop_only_motion_cannot_manufacture_disocclusion(self):
        scene=make_scene(replace(TRAIN,trajectory='static',rotating=False,camera='static',moving_crop=True),100,'clean')
        self.assertFalse(scene['disocclusion_mask'].any())
        # The old local-index subtraction falsely reports exposed pixels here.
        local_false=~scene['truth_mask'][1:] & scene['truth_mask'][:-1]
        self.assertTrue(local_false.any())
        result=metric_sequence(scene['selected'],scene['truth'],scene['truth_mask'],scene['centres_local'],scene['velocity'],disocclusion_mask=scene['disocclusion_mask'])
        self.assertEqual(result['summary']['disocclusion_leakage'],0.)
        moving=make_scene(TRAIN,100,'selected_tail')
        self.assertTrue(moving['disocclusion_mask'].any())
        measured=metric_sequence(moving['selected'],moving['truth'],moving['truth_mask'],moving['centres_local'],moving['velocity'],disocclusion_mask=moving['disocclusion_mask'])
        self.assertGreater(measured['summary']['disocclusion_leakage'],0.)

    def test_camera_only_static_opaque_and_combined_controls(self):
        for config in (replace(TRAIN,trajectory='static',rotating=False,opaque=True),
                       replace(TRAIN,trajectory='static',rotating=False,camera='moving'),
                       replace(TRAIN,camera='moving')):
            obs=observations(make_scene(config,100,'clean'))
            self.assertLess(obs['geometry_error_px'],1e-4)
            self.assertEqual(diagnose(obs)['diagnosis'],'no_detected_support_error')

    def test_thin_structure_must_abstain_when_erosion_has_no_support(self):
        scene=make_scene(replace(TRAIN,thin=True,rotating=False),100,'clean')
        self.assertEqual(fixed_geometry_masks(scene).sum(),0)
        self.assertEqual(diagnose(observations(scene))['diagnosis'],'non_identifiable')

    def test_wrong_guide_or_missing_witness_cannot_be_motion_proof(self):
        for cause in ('wrong_guide','missing_geometry'):
            self.assertEqual(diagnose(observations(make_scene(TRAIN,100,cause)))['diagnosis'],'non_identifiable')

    def test_no_change_in_light_step_alpha_and_static_text(self):
        for step in (1.1,1.25,1.4):
            scene=make_scene(replace(TRAIN,trajectory='static',rotating=False,moving_crop=False,light_step=step),100,'clean')
            full=scene['selected']+scene['background']
            output=abstain_identity(full)
            self.assertEqual(output.tobytes(),full.tobytes())
            self.assertEqual(abstain_identity(scene['alpha']).tobytes(),scene['alpha'].tobytes())
            np.testing.assert_array_equal(scene['truth_mask'],np.broadcast_to(scene['truth_mask'][0],scene['truth_mask'].shape))
            m=scene['detail_mask']
            np.testing.assert_array_equal(output[m],full[m])
            self.assertTrue(np.all(scene['light'][len(scene['light'])//2:]==np.float32(step)))

    def test_intervention_never_reexecutes_unavailable_provider(self):
        scene=make_scene(TRAIN,100,'mv_bias')
        changed=intervene(scene,'oracle_motion')
        self.assertGreater(observations(scene)['geometry_error_px'],.45)
        self.assertLess(observations(changed)['geometry_error_px'],1e-4)
        np.testing.assert_array_equal(changed['selected'],scene['selected'])


if __name__=='__main__': unittest.main(verbosity=2)
