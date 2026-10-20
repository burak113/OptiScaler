"""Checks with frozen captured bytes; never infer real object ground truth."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import recorded_analysis as r
import support_tracer as st


class RecordedContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a, cls.meta = r.loader.load_clip(r.PACKAGE / "fixtures/clips/bottle_track7.npz")
        cls.masks, cls.contract = r.freeze_contract(cls.a, "bottle_track7")

    def test_raw_selected_equality_has_explicit_mask_scope(self):
        self.assertEqual(self.contract["pixels_per_frame"], [9275,9430,9560,9864,8730,5479,3114])
        self.assertEqual(self.contract["total_pixels"], 55452)
        for lobe in ("diffuse", "specular"):
            masked = r.bit_difference(self.a["raw_rr_"+lobe], self.a["selected_rr_"+lobe], self.masks)
            self.assertEqual(masked["different_words"], 0)
            self.assertEqual(masked["compared_words"], 221808)
        full = r.bit_difference(self.a["raw_rr_specular"], self.a["selected_rr_specular"])
        self.assertEqual(full["different_words"], 456)
        self.assertEqual(full["different_alpha_words"], 0)

    def test_alpha_is_not_radiance_and_input_is_unmodified(self):
        x = np.array([[[1, 2, 3, 2000]]], dtype=np.float16)
        before = x.tobytes()
        expected = np.float32(1*.2126 + 2*.7152 + 3*.0722)
        self.assertAlmostEqual(float(r.luma(x).item()), float(expected), places=6)
        self.assertEqual(x.tobytes(), before)

    def test_real_moving_support_has_observed_previous_crop(self):
        for t in range(1, 7):
            x, y, valid = r.variant_coordinates(self.a, t, "original_1x")
            self.assertTrue(valid[self.masks[t]].all())
            a, b, c = r.loader.previous_coordinates(self.a, t)
            self.assertTrue(np.array_equal(x, a) and np.array_equal(y, b) and np.array_equal(valid, c))
        with self.assertRaises(ValueError):
            r.variant_coordinates(self.a, 0, "original_1x")

    def test_real_origin_omission_is_detectable(self):
        t = 4
        x, y, valid = r.variant_coordinates(self.a, t, "original_1x")
        bad_x, bad_y, bad_valid = r.variant_coordinates(self.a, t, "omit_crop_origin")
        np.testing.assert_allclose(y-bad_y, 112.0)
        self.assertGreater(int(np.count_nonzero(self.masks[t] & ~bad_valid)), 0)

    def test_frozen_masks_do_not_follow_output_or_threshold(self):
        a = {k: v.copy() for k, v in self.a.items()}
        a["selected_rr_specular"][..., :3] = 0
        modified, contract = r.freeze_contract(a, "bottle_track7")
        self.assertEqual(r.array_sha(modified), self.contract["sha256"])
        self.assertFalse(modified.flags.writeable)
        self.assertEqual(tuple(contract["thresholds_native_luma"]), (0, .0001, .001, .01))

    def test_explicit_reset_break_invalidates_comparison_only(self):
        stage=np.ones((3,4,5),np.float32)
        before=stage.tobytes()
        rows=list(st.trace_stages({"input":stage},np.zeros((3,4,5,4)),np.zeros((3,2)),
                  [100,100],[10,11,12],{"input":.1},comparison_breaks=np.array([False,True,False])))
        self.assertFalse(rows[1]["has_previous"])
        self.assertTrue(rows[1]["comparison_break"])
        self.assertTrue(np.isnan(rows[1]["stages"]["input"]["transported_previous_support"]).all())
        self.assertTrue(rows[2]["has_previous"])
        self.assertEqual(stage.tobytes(),before)

    def test_fractional_render_extent_is_not_silently_truncated(self):
        with self.assertRaises(ValueError):
            st.previous_coordinates(np.zeros((4,5,4)),[0,0],[0,0],[1505.5,847])


if __name__ == "__main__":
    unittest.main()
