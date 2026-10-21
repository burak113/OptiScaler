"""Metrology tests: known errors must not become an apparent quality win."""
from __future__ import annotations

import unittest

import numpy as np

from experiment import (
    PROTOCOL, ic, nc, dose, match_dose, array_hash, make_sequence,
    evaluate_variant, metrics, aligned_temporal_rms, paired_bootstrap,
)
from run_quality import assert_mask_snapshot, identical_observation_twins, known_bad_controls


class QualityMetrologyTests(unittest.TestCase):
    def test_identity_cannot_match_nonzero_dose(self):
        scene = ic.basic_scene(12, 16)
        source, raw, selected, *_, authority = scene
        self.assertEqual(dose(selected, raw, source, authority), 0)
        out, result = match_dose(raw, selected, selected, source, authority, authority, .8)
        self.assertIsNone(out)
        self.assertFalse(result["matched"])

    def test_dose_matching_measures_stored_output_and_keeps_alpha(self):
        scene = ic.basic_scene(16, 24)
        source, raw, selected, *_, authority = scene
        # Stay inside the frozen max-log-delta budget. The generic basic_scene
        # has a much larger colour change and cannot reach this requested dose.
        source[..., :3] = ic.at_luma(raw[..., :3].astype(float) * np.exp([.10,-.04,.06]), ic.luma(raw))
        selected.view(np.uint16)[..., 3] = np.uint16(0x7e23)
        raw.view(np.uint16)[..., 3] = np.uint16(0x7e23)
        selected.view(np.uint16)[3, 4, 3] ^= np.uint16(1)
        output, _ = ic.call_model(nc.NativeColourModel(nc.Config(enabled=True, support_prior=0)), scene)
        eligible = ic.original_eligibility(raw, selected, authority)
        mask = eligible.copy()
        mask[:3] = mask[-3:] = False
        mask[:, :3] = mask[:, -3:] = False
        matched, result = match_dose(raw, selected, output, source, eligible, mask, .5)
        self.assertTrue(result["matched"])
        self.assertAlmostEqual(result["achieved"], dose(matched, raw, source, mask), places=13)
        self.assertLessEqual(abs(result["achieved"]-.5), .003)
        ic.assert_word_contract(matched, raw, selected, authority)

    def test_false_independence_cannot_be_hidden_by_pooled_lobes(self):
        # Bootstrap operates on explicit per-seed paired observations; reported
        # count cannot silently become pixel count or double by pooled lobe scale.
        result = paired_bootstrap(np.array([.8, .9, 1.0, 1.1]))
        self.assertEqual(result["count"], 4)
        self.assertAlmostEqual(result["mean"], .95)
        self.assertLessEqual(result["bootstrap95_mean"][0], .95)
        self.assertGreaterEqual(result["bootstrap95_mean"][1], .95)

    def test_masks_are_baseline_frozen_and_mutation_is_detected(self):
        data = make_sequence(PROTOCOL["calibration_seeds"][0], "independent", .3)
        before = {k: array_hash(v) for k,v in data["masks"].items()}
        with self.assertRaises(ValueError):
            data["masks"]["quiet"][...] = False
        fake = dict(data)
        fake["masks"] = dict(data["masks"])
        fake["masks"]["quiet"] = data["masks"]["quiet"].copy()
        fake["masks"]["quiet"][0, 10, 10] ^= True
        with self.assertRaises(AssertionError):
            assert_mask_snapshot(fake, before)

    def test_moving_crop_alignment_does_not_call_static_error_flicker(self):
        # Fixed world error has no temporal difference even when crop origin moves.
        yy, xx = np.indices((12, 18))
        world = np.stack((xx, yy, xx+yy), -1).astype(float)
        origins = [(0,0), (1,0), (3,1)]
        errors = np.stack([world[y:y+8,x:x+10] for x,y in origins])
        masks = np.ones(errors.shape[:-1], bool)
        self.assertEqual(aligned_temporal_rms(errors, masks, origins, (10,8)), 0)
        errors[1] += 1
        self.assertGreater(aligned_temporal_rms(errors, masks, origins, (10,8)), 0)

    def test_full_native_word_protection_in_padded_noise_sequence(self):
        data = make_sequence(PROTOCOL["calibration_seeds"][0], "rare_chromatic_tail", .045)
        before = {key: array_hash(data[key]) for key in ("source", "raw", "selected", "authority")}
        value = evaluate_variant(data, "original_log")
        for key in before:
            self.assertEqual(before[key], array_hash(data[key]))
        self.assertTrue(np.any(value.view(np.uint16)[..., :3] != data["selected"].view(np.uint16)[..., :3]))
        self.assertTrue(np.array_equal(value.view(np.uint16)[..., 3], data["selected"].view(np.uint16)[..., 3]))
        m = metrics(value, data)
        self.assertGreater(m["quiet_pixel_frames"], 0)
        self.assertGreater(m["thin_pixel_frames"], 0)
        self.assertGreater(m["glint_pixel_frames"], 0)

    def test_identical_observation_twins_have_incompatible_truths(self):
        result = identical_observation_twins()
        for row in result["rows"]:
            self.assertGreater(row["at_least_one_world_error_lower_bound"], 0)
            for method in row["methods"].values():
                self.assertTrue(method["outputs_byte_identical"])
                self.assertGreaterEqual(method["max_world_error"] + 1e-12,
                                        row["at_least_one_world_error_lower_bound"])

    def test_known_bad_nulls_are_actually_rejected(self):
        controls = known_bad_controls()
        self.assertTrue(controls["controls_pass"])
        self.assertTrue(controls["candidate_derived_mask_mutant_rejected"])
        self.assertEqual(controls["frozen_output_step_response"], 0)
        self.assertLess(controls["blur_thin_detail_contrast_ratio"], .95)


if __name__ == "__main__":
    unittest.main()
