"""Held-out correctness oracles authored independently of candidate tuning."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "review"))
from independent_checks import (assert_word_contract, basic_scene, call_model,
                                original_eligibility, unchanged, words)
from native_colour import Config, NativeColourModel


class NativeAdversarialContracts(unittest.TestCase):
    def test_known_bad_was_reproduced_before_candidate_review(self):
        result = json.loads((ROOT / "review" / "known_bad_receipt.json").read_text())
        self.assertTrue(result["known_bad_reproduced"])
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["worse_cases_of_32"], 6)

    def test_original_half_words_alpha_payloads_and_signed_zero(self):
        scene = list(basic_scene())
        source, raw, selected, _, _, _, authority = scene
        payloads = np.array([0x0000, 0x8000, 0x0001, 0x3c00, 0x7c00,
                             0xfc00, 0x7e01, 0x7d55, 0xfe11], np.uint16)
        words(raw)[..., 3] = np.resize(payloads, raw.shape[:2])
        words(source)[..., 3] = np.resize(payloads[::-1], raw.shape[:2])
        selected[...] = raw
        words(selected)[2, 2, 0] ^= 1
        words(selected)[2, 3, 3] ^= 1
        words(raw)[2, 4, 0] = 0x0000
        words(selected)[2, 4, 0] = 0x8000
        words(selected)[2, 5, 3] = 0x7e12
        authority[4, 4] = False
        snapshots = [x.copy() for x in (source, raw, selected)]
        output, _ = call_model(NativeColourModel(Config(enabled=True)), scene)
        assert_word_contract(output, raw, selected, authority)
        for array, snapshot in zip((source, raw, selected), snapshots):
            self.assertTrue(unchanged(array, snapshot), "candidate mutated an input")
        zero_alpha = words(raw)[..., 3] == 0
        eligible = original_eligibility(raw, selected, authority)
        self.assertGreater(int(np.any(words(output) != words(selected), axis=-1)[zero_alpha & eligible].sum()), 0,
                           "native alpha=0 incorrectly disabled the lobe")

    def test_float32_protected_nan_payload_words(self):
        scene = list(basic_scene(dtype=np.float32))
        source, raw, selected, _, _, _, authority = scene
        words(raw)[..., 3] = np.uint32(0x7fc00021)
        words(selected)[..., 3] = words(raw)[..., 3]
        words(selected)[1, 1, 3] = np.uint32(0x7fc00022)
        words(raw)[1, 2, 0] = 0
        words(selected)[1, 2, 0] = np.uint32(0x80000000)
        output, _ = call_model(NativeColourModel(Config(enabled=True)), scene)
        assert_word_contract(output, raw, selected, authority)

    def test_default_off_override_off_active_extent_and_authority(self):
        scene = basic_scene()
        output, _ = call_model(NativeColourModel(Config()), scene)
        assert_word_contract(output, scene[1], scene[2], scene[-1], off=True)
        output, _ = call_model(NativeColourModel(Config(enabled=True)), scene, enabled=False)
        assert_word_contract(output, scene[1], scene[2], scene[-1], off=True)
        output, _ = call_model(NativeColourModel(Config(enabled=True)), scene, active_extent=(13, 9))
        assert_word_contract(output, scene[1], scene[2], scene[-1], active_extent=(13, 9))
        no_authority = list(scene)
        no_authority[-1] = np.zeros_like(scene[-1])
        output, _ = call_model(NativeColourModel(Config(enabled=True)), no_authority)
        self.assertTrue(unchanged(output, scene[2]))

    def test_missing_authority_fails_closed(self):
        source, raw, selected, depth, normals, roughness, _ = basic_scene()
        try:
            output, _ = NativeColourModel(Config(enabled=True)).frame(
                source, raw, selected, depth, normals, roughness=roughness)
        except (ValueError, TypeError):
            return
        self.assertTrue(unchanged(output, selected))

    def test_invalid_geometry_and_negative_rgb_are_unchanged(self):
        scene = list(basic_scene())
        _, raw, selected, depth, normals, _, authority = scene
        depth[2, 2], depth[2, 3], depth[2, 4] = 0, np.nan, np.inf
        normals[3, 2] = [0, 0, 0]
        normals[3, 3] = [np.nan, 0, 1]
        raw[4, 2, 0] = selected[4, 2, 0] = -.2
        mask = np.zeros(depth.shape, bool)
        mask[2, 2:5] = True
        mask[3, 2:4] = True
        mask[4, 2] = True
        output, _ = call_model(NativeColourModel(Config(enabled=True)), scene)
        self.assertTrue(unchanged(output, selected, mask))
        valid = ~mask
        self.assertTrue(np.isfinite(output[valid, :3]).all())
        assert_word_contract(output, raw, selected, authority)

    def test_stateless_reset_crop_and_order_are_explicit(self):
        scene = basic_scene()
        model = NativeColourModel(Config(enabled=True))
        one, _ = call_model(model, scene, frame_id=51, crop_origin=(100, 200), render_extent=(1505, 847))
        two, _ = call_model(model, scene, frame_id=52, crop_origin=(104, 201), render_extent=(1505, 847), reset=True)
        fresh, _ = call_model(NativeColourModel(Config(enabled=True)), scene)
        self.assertTrue(unchanged(one, two))
        self.assertTrue(unchanged(two, fresh))

    def test_exposure_scale_invariance_before_half_storage(self):
        scene = basic_scene(dtype=np.float32)
        reference, _ = call_model(NativeColourModel(Config(enabled=True)), scene)
        for scale in (2.0 ** -12, 2.0 ** 12):
            scaled = [v.copy() for v in scene]
            for rgba in scaled[:3]:
                rgba[..., :3] *= scale
            output, _ = call_model(NativeColourModel(Config(enabled=True)), scaled)
            np.testing.assert_allclose(output[..., :3] / scale, reference[..., :3], rtol=2e-5, atol=2e-6)

    def test_protected_gate_and_forced_on_mutations_are_killed(self):
        scene = list(basic_scene())
        words(scene[2])[4, 4, 3] ^= 1
        model = NativeColourModel(Config(enabled=True))
        # Mutation: compare selected with itself instead of original raw RR.
        broken_scene = list(scene)
        broken_scene[1] = scene[2].copy()
        broken, _ = call_model(model, broken_scene)
        with self.assertRaisesRegex(AssertionError, "protected RGBA"):
            assert_word_contract(broken, scene[1], scene[2], scene[-1])
        # Mutation: ignore OFF and always execute the enabled pass.
        forced_on, _ = call_model(model, scene, enabled=True)
        with self.assertRaisesRegex(AssertionError, "OFF output"):
            assert_word_contract(forced_on, scene[1], scene[2], scene[-1], off=True)


if __name__ == "__main__":
    unittest.main()
