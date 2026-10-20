"""Executable contracts for the original-input capture diagnostics, not GPU tests."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("job07_capture_analysis", HERE/"analyze_captures.py")
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


def tiny_capture():
    packed = np.uint32(512 | (512 << 10) | (511 << 20) | (2 << 30))
    return {
        "input_depth": np.full((2,8,8), 5, dtype=np.float32),
        "recovery_original_normal_roughness": np.full((2,8,8),packed,dtype=np.uint32),
        "input_motion": np.zeros((2,8,8,4),dtype=np.float16),
        "render_extent": np.array([32,32],dtype=np.int32),
        "crop_origin_render": np.array([[10,1],[10,4]],dtype=np.int32),
    }


class CapturedContracts(unittest.TestCase):
    def test_source_oct_axes_and_material_roughness_are_separate(self):
        # R10/G10 center cannot represent .5 exactly; allow its known <=.003 error.
        points = [(1023,512,(1,0,0)),(0,512,(-1,0,0)),
                  (512,1023,(0,1,0)),(512,0,(0,-1,0)),
                  (512,512,(0,0,1)),(1023,1023,(0,0,-1))]
        for r,g,truth in points:
            for category in range(4):
                words = np.array([r | (g<<10) | (731<<20) | (category<<30)],dtype=np.uint32)
                before=words.copy()
                normal,roughness,material=capture.decode_packed(words)
                np.testing.assert_allclose(normal[0],truth,atol=.003,rtol=0)
                self.assertAlmostEqual(float(roughness[0]),731/1023,places=6)
                self.assertEqual(int(material[0]),category)
                np.testing.assert_array_equal(words,before)

    def test_moving_crop_is_not_motion_and_wrong_scale_is_detected(self):
        a=tiny_capture()
        a['input_motion'][1,...,1]=np.float16(-3/32)
        masks=capture.build_masks(a)
        self.assertEqual(int(masks['available_pair'][0].sum()),0)
        self.assertEqual(int(masks['available_pair'][1].sum()),16)
        self.assertEqual(int(masks['stable_guide_pair'][1].sum()),16)
        # Explicit wrong-convention mutant: use crop rather than original render extent.
        wrong={k:v.copy() for k,v in a.items()}
        wrong['render_extent'][:]=8
        altered=capture.build_masks(wrong)
        self.assertLess(int(altered['available_pair'][1].sum()),16)

    def test_invalid_coordinates_are_not_clamped_or_wrapped(self):
        a=tiny_capture()
        a['input_motion'][1,...,0]=np.float16(4)
        masks=capture.build_masks(a)
        self.assertEqual(int(masks['available_pair'].sum()),0)
        self.assertEqual(int(masks['stable_guide_pair'].sum()),0)

    def test_material_or_depth_disagreement_not_called_stable(self):
        a=tiny_capture()
        a['input_motion'][1,...,1]=np.float16(-3/32)
        a['recovery_original_normal_roughness'][1] ^= np.uint32(1<<30)
        self.assertEqual(int(capture.build_masks(a)['stable_guide_pair'].sum()),0)
        a=tiny_capture()
        a['input_motion'][1,...,1]=np.float16(-3/32)
        a['input_motion'][1,...,2]=np.float16(30000)
        self.assertEqual(int(capture.build_masks(a)['stable_guide_pair'].sum()),0)

    def test_frozen_masks_detect_changed_denominator(self):
        a=tiny_capture()
        a['input_motion'][1,...,1]=np.float16(-3/32)
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)
            meta={'archive':{'sha256':'f'*64}}
            masks,_=capture.freeze_or_check_masks('test',a,meta,output,create=True)
            capture.freeze_or_check_masks('test',a,meta,output)
            masks['core'][1,3,3]=False
            np.savez_compressed(output/'base_masks/test.npz',**masks)
            with self.assertRaisesRegex(AssertionError,'immutable BASE mask changed'):
                capture.freeze_or_check_masks('test',a,meta,output)

    def test_actual_frozen_support_and_source_hashes(self):
        for name in capture.CLIPS:
            a,meta=capture.LOADER.load_clip(capture.PACKAGE/'fixtures/clips'/(name+'.npz'))
            before={k:capture.sha_array(v) for k,v in a.items()}
            masks,_=capture.freeze_or_check_masks(name,a,meta,HERE/'evidence')
            self.assertFalse(masks['available_pair'][0].any())
            self.assertFalse(np.any(masks['stable_guide_pair'] & ~masks['available_pair']))
            self.assertEqual(before,{k:capture.sha_array(v) for k,v in a.items()})

    def test_glass_provider_geometry_is_separate_from_aligned_rgb(self):
        result=capture.glass_geometry_control(HERE/'evidence',use_candidate=True)
        self.assertFalse(result['aligned_glass_mask_used_for_unwarped_geometry'])
        self.assertFalse(result['aligned_rgb_paired_with_unwarped_guide_pixels'])
        self.assertFalse(result['physical_input_D_S_and_hit_distance_alpha_present'])
        self.assertTrue(result['all_source_arrays_bitwise_unchanged'])
        self.assertTrue(result['diagnostic']['unsupported_identity_exact'])
        self.assertEqual(result['diagnostic']['outside_available_pair_support_count'],0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
