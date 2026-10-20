"""Candidate arithmetic/contracts; quality comparisons live in synthetic.py."""
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from glass_candidate import (CandidateConfig, SupportUncertainty, _blocks,
                             apply_specular, glass_policy, haar_forward,
                             haar_inverse, shrink_specular)


def sidecar(shape, variance=.02, count=64, valid=True):
    return SupportUncertainty(np.full(shape, variance, np.float32),
                              np.full(shape, count, np.float32),
                              np.full(shape, valid, bool), np.ones(shape, bool),
                              np.zeros(shape, np.int32))


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(9142)
        self.raw = np.full((12, 16, 3), 2., np.float32)
        self.selected = self.raw + self.rng.normal(0, .08, self.raw.shape).astype(np.float32)
        self.mask = np.ones(self.raw.shape[:2], bool)
        self.config = CandidateConfig(enabled=True)

    def test_orthonormal_transform_and_inverse(self):
        block = _blocks(self.selected - self.raw)
        transformed = haar_forward(block)
        np.testing.assert_allclose(np.sum(block**2, axis=(2,3)),
                                   np.sum(transformed**2, axis=(2,3)), rtol=3e-6, atol=1e-8)
        np.testing.assert_allclose(haar_inverse(transformed), block, rtol=2e-6, atol=2e-8)

    def test_off_and_missing_sidecar_preserve_raw_bits(self):
        exceptional = self.selected.copy()
        exceptional.view(np.uint32)[0, 0] = [0x80000000, 0x7fc00042, 0x7f800000]
        for config, evidence in [(CandidateConfig(), object()), (self.config, None)]:
            out, _ = shrink_specular(None, exceptional, None, evidence, config)
            np.testing.assert_array_equal(out.view(np.uint32), exceptional.view(np.uint32))

    def test_zero_variance_is_exact(self):
        out, _ = shrink_specular(self.raw, self.selected, self.mask,
                                 sidecar(self.mask.shape, variance=0), self.config)
        np.testing.assert_array_equal(out.view(np.uint32), self.selected.view(np.uint32))

    def test_physical_units_scaling_is_covariant(self):
        evidence=sidecar(self.mask.shape)
        base,_=shrink_specular(self.raw,self.selected,self.mask,evidence,self.config)
        for scale in [16.,256.]:
            scaled_evidence=sidecar(self.mask.shape,variance=.02*scale*scale)
            scaled,_=shrink_specular(self.raw*np.float32(scale),self.selected*np.float32(scale),
                                    self.mask,scaled_evidence,self.config)
            np.testing.assert_array_equal(scaled/np.float32(scale),base)

    def test_synthetic_truth_metrics_separate_motion_from_error(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))
        from synthetic import make_sequence,metrics
        sequence=make_sequence(1000,"independent_gaussian")
        score=metrics(sequence["truth"],sequence)
        for key in ["rgb_rmse","grain_highpass_error_rms","positive_sparkle_error_p995",
                    "absolute_sparkle_error_p995","temporal_error_rms","edge_rgb_rmse"]:
            self.assertEqual(score[key],0.,key)
        for key in ["texture_contrast_gain","text_stroke_contrast_gain","isolated_glint_peak_gain",
                    "light_step_immediate_gain","colour_step_immediate_gain"]:
            self.assertAlmostEqual(score[key],1.,places=6,msg=key)
        self.assertGreater(score["output_temporal_rms_including_true_changes"],0.)

    def test_preserves_block_low_band_and_changes_noise(self):
        out, diag = shrink_specular(self.raw, self.selected, self.mask,
                                    sidecar(self.mask.shape), self.config)
        np.testing.assert_allclose(_blocks(out).sum(axis=2), _blocks(self.selected).sum(axis=2),
                                   rtol=2e-7, atol=2e-6)
        self.assertGreater(diag["changed_pixels"], 0)
        self.assertLess(np.mean((out-self.raw)**2), np.mean((self.selected-self.raw)**2))

    def test_trace_variance_transform_matches_independent_monte_carlo(self):
        # This measures the declared statistical formula, not shader parity.
        rng = np.random.default_rng(40021)
        sigmas = np.array([.02, .05, .11, .03], np.float32)
        noise = rng.normal(size=(120000, 1, 4, 3)).astype(np.float32) * sigmas[None,None,:,None]
        measured = np.mean(np.sum(haar_forward(noise)**2, axis=3), axis=0)[0]
        expected = .25 * float(np.sum(3*sigmas**2))
        np.testing.assert_allclose(measured, expected, rtol=.008)

    def test_wholeblock_range_abstention_preserves_low_light_glint(self):
        raw = np.array([[[10, 10, 10], [0, 0, 0]], [[0, 0, 0], [0, 0, 0]]], np.float32)
        selected = np.array([[[0, 0, 0], [0, 0, 0]], [[0, 0, 0], [0, 0, 0]]], np.float32)
        out, diag = shrink_specular(raw, selected, np.ones((2,2), bool), sidecar((2,2), 1e5), self.config)
        np.testing.assert_array_equal(out, selected)
        self.assertEqual(diag["range_abstain_blocks"], 1)

    def test_low_count_nonfinite_and_unknown_spatial_noise_abstain(self):
        for count in [0, 1, 7.999, np.nan, np.inf]:
            out, _ = shrink_specular(self.raw, self.selected, self.mask,
                                     sidecar(self.mask.shape, count=count), self.config)
            np.testing.assert_array_equal(out.view(np.uint32), self.selected.view(np.uint32))
        evidence = sidecar(self.mask.shape)
        evidence.independent_spatial[:] = False
        out, _ = shrink_specular(self.raw, self.selected, self.mask, evidence, self.config)
        np.testing.assert_array_equal(out, self.selected)

    def test_partial_extent_and_crossed_geometry_abstain(self):
        raw, selected = self.raw[:11,:15], self.selected[:11,:15]
        mask = self.mask[:11,:15]
        evidence = sidecar(mask.shape)
        evidence.surface_id[:, 1::2] = 1
        out, _ = shrink_specular(raw, selected, mask, evidence, self.config)
        np.testing.assert_array_equal(out, selected)
        evidence.surface_id[:] = 0
        out, _ = shrink_specular(raw, selected, mask, evidence, self.config)
        np.testing.assert_array_equal(out[-1], selected[-1])
        np.testing.assert_array_equal(out[:,-1], selected[:,-1])

    def test_diffuse_not_in_api_and_alpha_preserved(self):
        raw = np.concatenate((self.raw, self.rng.random((*self.mask.shape,1), dtype=np.float32)), axis=2)
        raw.view(np.uint32)[0,0,3] = 0x80000000
        selected = np.concatenate((self.selected, np.zeros((*self.mask.shape,1), np.float32)), axis=2)
        diffuse = self.rng.random(raw.shape, dtype=np.float32)
        witness = diffuse.copy()
        out, _ = apply_specular(raw, selected, self.mask, sidecar(self.mask.shape), self.config)
        np.testing.assert_array_equal(out[...,3].view(np.uint32), raw[...,3].view(np.uint32))
        np.testing.assert_array_equal(diffuse.view(np.uint32), witness.view(np.uint32))

    def test_glass_strength_is_nzr_fraction_and_gate_zero_identity(self):
        raw = np.concatenate((self.raw, np.ones((*self.mask.shape,1),np.float32)),axis=2)
        selected = np.concatenate((self.selected, np.zeros((*self.mask.shape,1),np.float32)),axis=2)
        np.testing.assert_array_equal(glass_policy(raw, selected, 2, 0)[...,:3], raw[...,:3])
        np.testing.assert_allclose(glass_policy(raw, selected, 2, 1)[...,:3], selected[...,:3], atol=3e-7)
        np.testing.assert_array_equal(glass_policy(raw, selected, 2, .5, np.zeros(self.mask.shape))[...,:3],
                                      selected[...,:3])
        expected = raw[...,:3] + np.float32(.5)*(selected[...,:3]-raw[...,:3])
        np.testing.assert_array_equal(glass_policy(raw, selected)[...,:3], expected)
        with self.assertRaises(ValueError):
            glass_policy(raw, selected, mode=3)

    def test_explicit_mutant_is_caught(self):
        # Deliberately erase LL alongside high bands. A noise-only metric would
        # like this control; the low-band contract must reject it.
        selected = self.selected + np.float32(.4)
        wrong = self.raw.copy()
        error = np.max(np.abs(_blocks(wrong).sum(axis=2)-_blocks(selected).sum(axis=2)))
        self.assertGreater(error, 1.)

    def test_same_observation_cannot_identify_glint_versus_impulse(self):
        raw = np.ones((2,2,3), np.float32)
        noise_world_truth = raw + np.float32(.005)
        selected = noise_world_truth.copy(); selected[0,0] += .1
        evidence = sidecar((2,2), variance=.02)
        base_changed = np.any(raw.view(np.uint32) != selected.view(np.uint32),axis=2)
        self.assertTrue(np.all(base_changed))
        out, _ = shrink_specular(raw, selected, base_changed, evidence, self.config)
        # World A: this is true small specular detail. World B: the exact same
        # difference is a noise event. Same observable => same output, so any
        # attenuation helps B while losing A. No truth is supplied to the filter.
        loss_a = float(np.linalg.norm(out-selected))
        residual_b = float(np.linalg.norm(out-noise_world_truth))
        self.assertGreater(loss_a, 0)
        self.assertGreater(residual_b, 0)
        self.assertLess(residual_b, float(np.linalg.norm(selected-noise_world_truth)))


if __name__ == "__main__":
    unittest.main()
