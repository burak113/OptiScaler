from pathlib import Path
import sys
import unittest

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE/"experiments"))
from recorded import PACKAGE, clips, erode, fixed_metrics, glass, recorded_glass


class RecordedContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = recorded_glass(False)

    def test_captured_calibration_and_true_mask_scope(self):
        self.assertEqual(self.result["immutable_masks"]["common_glass"]["pixels"], 6497)
        self.assertEqual(self.result["full_roi_evidence_only_pixels_not_reexecuted"], 8048)
        self.assertEqual(self.result["source_crop_haar_parity_xy"], [0, 1])
        self.assertFalse(self.result["native_uncertainty_sidecar_present"])
        self.assertFalse(self.result["original_alpha_or_input_radiance_present"])

    def test_real_candidate_abstains_on_changed_subset_not_mostly_unchanged_image(self):
        row = self.result["subset_identity_checks"]["candidate_missing_sidecar"]
        self.assertGreater(row["rgb_words_on_base_changed_subset"], 300000)
        self.assertEqual(row["different_rgb_words_on_base_changed_subset"], 0)
        self.assertEqual(row["different_rgb_words_outside_common_mask"], 0)
        metrics = self.result["fixed_base_metrics"]
        self.assertEqual(metrics["candidate_missing_sidecar"], metrics["nzr_selected"])
        self.assertEqual(metrics["candidate_missing_sidecar_plus_blend05"], metrics["blend_05"])

    def test_blur_and_freeze_cannot_be_accepted_from_noise_score(self):
        rows = self.result["fixed_base_metrics"]
        nzr = rows["nzr_selected"]["common_glass"]
        blur = rows["spatial_blur_sigma2_null"]["common_glass"]
        freeze = rows["freeze_specular_first_frame_null"]["common_glass"]
        self.assertLess(blur["hp_cv_fixed_base_p50"], nzr["hp_cv_fixed_base_p50"])
        self.assertLess(blur["detail_energy_proxy"], .6*nzr["detail_energy_proxy"])
        self.assertGreater(freeze["mean_specular_rgb_l1_change_from_nzr"], 0)
        self.assertFalse(nzr["noise_truth_available"])

    def test_fixed_denominator_is_not_recomputed_from_variant(self):
        # A 2x brightness scale must also double absolute noise on the same BASE.
        base = np.ones((4, 7, 8, 3), np.float32)
        base[:, :, :, :] *= np.array([.8, 1.2, .9, 1.1], np.float32)[:, None, None, None]
        zeros = np.zeros_like(base); mask = np.ones((7, 8), bool)
        a = fixed_metrics(base, zeros, base, {"test": mask})["test"]
        b = fixed_metrics(2*base, zeros, base, {"test": mask})["test"]
        self.assertAlmostEqual(b["fine_cv_fixed_base_p50"], 2*a["fine_cv_fixed_base_p50"], places=6)

    def test_moving_crop_provenance_is_applied_and_first_history_absent(self):
        arrays, _ = clips.load_clip(PACKAGE/"fixtures/clips/bottle_track7.npz")
        with self.assertRaises(ValueError):
            clips.previous_coordinates(arrays, 0)
        qx, qy, valid = clips.previous_coordinates(arrays, 1)
        yy, xx = np.mgrid[:256, :128]
        delta = arrays["crop_origin_render"][1]-arrays["crop_origin_render"][0]
        expected_y = yy+int(delta[1])+arrays["input_motion"][1, ..., 1].astype(float)*847
        np.testing.assert_array_equal(qy, expected_y)
        self.assertEqual(int(delta[1]), 16)
        _, sampled_valid = clips.sample_previous(arrays["input_depth"][0], qx, qy)
        np.testing.assert_array_equal(valid, sampled_valid)


if __name__ == "__main__":
    unittest.main()
