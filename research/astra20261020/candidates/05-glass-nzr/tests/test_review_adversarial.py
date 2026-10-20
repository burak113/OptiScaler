"""Independent reviewer probes; passing counterexample tests are not acceptance.

Run from the repository root:
    python research/astra20261020/candidates/05-glass-nzr/tests/test_review_adversarial.py
    python research/astra20261020/candidates/05-glass-nzr/tests/test_review_adversarial.py --measurements
    python research/astra20261020/candidates/05-glass-nzr/tests/test_review_adversarial.py --mutation-alpha
    python research/astra20261020/candidates/05-glass-nzr/tests/test_review_adversarial.py --audit-holdout

The --mutation-alpha command intentionally returns 1: it supplies selected alpha
where the native output contract requires byte-preserved raw/current alpha.

The reviewer reproduced a frozen known-bad control before receiving this API.
Seeds and probes below were fixed independently of candidate quality results.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import unittest

import numpy as np

CANDIDATE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CANDIDATE / "src"))
from glass_candidate import (
    CandidateConfig, SupportUncertainty, apply_specular, glass_policy,
    shrink_specular,
)

PHASE_SEEDS = tuple(range(51000, 51128))
CORRELATION_SEEDS = tuple(range(65000, 65128))
ON = CandidateConfig(enabled=True, noise_scale=1.0, min_effective_count=8.0)


def support(shape, *, sigma=0.04):
    """Analytic IID-noise sidecar; no claim that a recorded fixture has it."""
    return SupportUncertainty(
        noise_trace=np.full(shape, 3.0 * sigma * sigma, np.float32),
        effective_count=np.full(shape, 32.0, np.float32),
        valid=np.ones(shape, bool),
        independent_spatial=np.ones(shape, bool),
        surface_id=np.zeros(shape, np.int32),
    )


def simple(shape=(8, 10)):
    rng = np.random.default_rng(81237)
    raw = np.full((*shape, 3), 0.4, np.float32)
    selected = raw + rng.normal(0.0, 0.04, raw.shape).astype(np.float32)
    return raw, selected, np.ones(shape, bool), support(shape)


def bit_equal(a, b):
    return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()


def phase_probe():
    """A constant-energy moving line can flicker solely from 2x2 block phase."""
    shape = (12, 16)
    sigma, amplitude = 0.04, np.float32(0.06)
    raw = np.full((*shape, 3), 0.4, np.float32)
    eligible = np.ones(shape, bool)
    evidence = support(shape, sigma=sigma)
    phase_results = []
    for phase in range(4):
        line = np.zeros(shape, bool)
        line[:, 4 + phase:6 + phase] = True  # Fixed truth mask, before noise/output.
        truth = raw.copy()
        truth[line] += amplitude
        recovered, spills, output_sums = [], [], []
        for seed in PHASE_SEEDS:
            # Same realization for every phase; all 128 seeds are independent.
            noise = np.random.default_rng(seed).normal(0.0, sigma, raw.shape)
            selected = truth + noise.astype(np.float32)
            output, _ = shrink_specular(raw, selected, eligible, evidence, ON)
            recovered.append(float((output - raw)[line].mean()))
            spills.append(float(np.abs(output - truth)[~line].mean()))
            output_sums.append(float((output - selected).sum(dtype=np.float64)))
        phase_results.append({
            "phase": phase,
            "truth_line_amplitude": float(amplitude),
            "mean_recovered_line_amplitude": float(np.mean(recovered)),
            "line_retention": float(np.mean(recovered) / amplitude),
            "mean_off_line_absolute_error": float(np.mean(spills)),
            "max_absolute_whole_image_rgb_sum_delta": float(np.max(np.abs(output_sums))),
        })
    retention = [r["line_retention"] for r in phase_results]
    return {
        "scope": "128 independent synthetic IID-noise realizations per phase; no native/GPU execution",
        "seeds": list(PHASE_SEEDS),
        "noise_sigma_per_rgb_channel": sigma,
        "truth_masks_fixed_before_noise_and_candidate": True,
        "phases": phase_results,
        "peak_to_peak_line_retention": float(max(retention) - min(retention)),
        "counterexample": "Disjoint-block phase modulates moving thin-line contrast despite preserved block sums.",
    }


def correlation_probe():
    """Check an explicit counterexample to diagonal spatial noise covariance."""
    shape = (12, 16)
    sigma = np.float32(0.04)
    raw = np.full((*shape, 3), 0.4, np.float32)
    eligible = np.ones(shape, bool)
    evidence = support(shape, sigma=float(sigma))
    actual_highband_energy = []
    output_energy = []
    honest_identity = True
    for seed in CORRELATION_SEEDS:
        rng = np.random.default_rng(seed)
        amplitude = rng.normal(0.0, sigma, (shape[0] // 2, shape[1] // 2, 3)).astype(np.float32)
        noise = np.empty(raw.shape, np.float32)
        noise[0::2, 0::2] = amplitude
        noise[1::2, 0::2] = amplitude
        noise[0::2, 1::2] = -amplitude
        noise[1::2, 1::2] = -amplitude
        # Marginal per-pixel variance is sigma^2; one Haar coefficient is 2a.
        actual_highband_energy.append(float(np.mean(np.sum((2 * amplitude) ** 2, axis=-1))))
        selected = raw + noise
        output, _ = shrink_specular(raw, selected, eligible, evidence, ON)
        output_energy.append(float(np.mean((output - raw) ** 2)))
        honest, _ = shrink_specular(
            raw, selected, eligible,
            replace(evidence, independent_spatial=np.zeros(shape, bool)), ON,
        )
        honest_identity = honest_identity and bit_equal(honest, selected)
    return {
        "scope": "synthetic coherent alternating noise, intentionally false independence flag versus honest abstention",
        "seeds": list(CORRELATION_SEEDS),
        "supplied_iid_highband_noise_trace": float(3 * sigma * sigma),
        "actual_coherent_highband_energy_mean": float(np.mean(actual_highband_energy)),
        "actual_to_claimed_highband_noise_ratio": float(np.mean(actual_highband_energy) / (3 * sigma * sigma)),
        "output_noise_mse_under_false_independence": float(np.mean(output_energy)),
        "honest_nonindependent_sidecar_bitwise_identity": bool(honest_identity),
        "conclusion": "Per-pixel variance/count alone cannot certify transformed noise energy without spatial covariance assumptions.",
    }


def ambiguous_glint_probe():
    """Two truths have exactly the same finite observables supplied to the API."""
    raw = np.full((4, 4, 3), 0.4, np.float32)
    # Every tap must belong to the adapter's ORIGINAL NZR-changed subset.
    # A uniform true correction puts all taps in that subset without changing
    # the glint's high bands. Neither support nor peak baseline uses output.
    uniform = raw + np.float32(0.005)
    selected = uniform.copy()
    selected[0, 0] += np.float32(0.08)
    evidence = support((4, 4), sigma=0.05)
    eligible = np.any(selected.view(np.uint32) != raw.view(np.uint32), axis=-1)
    assert np.all(eligible)
    output, _ = shrink_specular(raw, selected, eligible, evidence, ON)
    signal_truth = selected.copy()
    noise_truth = uniform.copy()
    return {
        "observations_identical_in_both_worlds": True,
        "all_evaluated_taps_original_base_changed": bool(np.all(eligible)),
        "uniform_true_correction": 0.005,
        "peak_reference": "Known uniform correction, fixed before candidate output",
        "world_signal": "Uniform 0.005 correction plus isolated 0.08 reflection are real; raw RR omitted them.",
        "world_noise": "Uniform 0.005 correction is real; the identical isolated 0.08 reflection is a stochastic outlier.",
        "original_peak_amplitude": float(selected[0, 0, 0] - uniform[0, 0, 0]),
        "output_peak_amplitude": float(output[0, 0, 0] - uniform[0, 0, 0]),
        "signal_world_l1_error": float(np.abs(output - signal_truth).sum()),
        "noise_world_l1_error": float(np.abs(output - noise_truth).sum()),
        "conclusion": "Noise/detail attribution requires evidence or a prior; these observables do not establish universal glint preservation.",
    }


def audit_holdout():
    """Read-only independent aggregation check; never reruns/tunes holdout."""
    path = CANDIDATE / "evidence/synthetic_holdout.json"
    data = path.read_bytes()
    result = json.loads(data)
    rows = result["per_sequence"]
    assert result["split"] == "holdout"
    assert len(rows) == 240 and result["frames_per_sequence"] == 32
    for relative, expected_hash in result["source_sha256"].items():
        assert hashlib.sha256((CANDIDATE / relative).read_bytes()).hexdigest() == expected_hash
    summary = {}
    for model, saved in result["summary"].items():
        cases = [row for row in rows if row["model"] == model]
        assert len(cases) == 48
        assert all(row["mask_hashes"]["evaluation"] == row["mask_hashes"]["actual_nzr_changed"]
                   for row in cases)
        paired = {}
        for control, measures in saved["paired_ratios"].items():
            paired[control] = {}
            for metric, expected in measures.items():
                ratios = np.array([
                    row["metrics"]["candidate_blend05"][metric] /
                    row["metrics"][control][metric] for row in cases
                ], np.float64)
                calculated = float(np.mean(ratios))
                assert calculated == expected["mean_ratio"]
                paired[control][metric] = calculated
        matched_error = max(abs(row["metrics"]["candidate_blend05"]["texture_contrast_gain"] -
                                row["metrics"]["detail_matched_scalar_null"]["texture_contrast_gain"])
                            for row in cases)
        assert matched_error < 2e-8
        accepted = sum(row["candidate_support"]["accepted_blocks"] for row in cases)
        assert accepted == saved["total_accepted_blocks"]
        if model in ("temporal_ar1", "spatial_correlated_honest"):
            assert accepted == 0
            assert all(value == 1.0 for value in paired["blend05"].values())
        summary[model] = {
            "sequences": len(cases),
            "accepted_blocks": accepted,
            "maximum_absolute_texture_match_error": matched_error,
            "mean_detail_matched_scalar_strength": saved["mean_detail_matched_scalar_strength"],
            "independently_recomputed_mean_paired_ratios": paired,
        }
    return {
        "executor": "independent reviewer, read-only audit of root-executed holdout",
        "candidate_or_holdout_reexecuted": False,
        "holdout_sha256": hashlib.sha256(data).hexdigest(),
        "gpu_executed": False,
        "summaries_verified": summary,
        "limitations": [
            "48 held-out noise seeds per model, not 48 unseen scene designs or game captures.",
            "Supplied count 64 is an analytic support annotation, not 64 observed chronological frames; each sequence has 32 frames.",
            "The rho=.85 finite-mean effective count for annotated 64 observations is 5.738462, below the minimum 8; the AR model therefore only tests identity abstention.",
            "Detail matching uses one truth-dependent texture regression coefficient; it does not match glint peaks, every spatial frequency, or native detail.",
            "Quiet-flat positive p99.5 and temporal error retain separate meanings; all-active high-pass tails include blur error.",
            "Raw RR and NZR are declared synthetic current-frame surrogates, not actual provider/reference-history outputs.",
        ],
    }


class IndependentAdversarialTests(unittest.TestCase):
    def test_raw_output_alpha_bits_and_read_only_inputs_are_protected(self):
        raw, selected, eligible, evidence = simple()
        shape = raw.shape[:2]
        raw4 = np.concatenate((raw, np.zeros((*shape, 1), np.float32)), axis=-1)
        selected4 = np.concatenate((selected, np.ones((*shape, 1), np.float32)), axis=-1)
        alpha_words = np.resize(np.array([0x80000000, 0x00000000, 0x7fc00123,
                                         0x3f812345, 0x42f60000], np.uint32), shape)
        raw4[..., 3] = alpha_words.view(np.float32)
        raw_before, selected_before = raw4.tobytes(), selected4.tobytes()
        raw4.flags.writeable = False
        selected4.flags.writeable = False
        for config in (CandidateConfig(), ON):
            output, _ = apply_specular(raw4, selected4, eligible, evidence, config,
                                      mode=2, strength=0.5)
            np.testing.assert_array_equal(output[..., 3].view(np.uint32), alpha_words)
        self.assertEqual(raw4.tobytes(), raw_before)
        self.assertEqual(selected4.tobytes(), selected_before)

    def test_existing_glass_strength_is_nzr_fraction_and_off_keeps_policy(self):
        raw, selected, eligible, evidence = simple()
        shape = raw.shape[:2]
        raw4 = np.concatenate((raw, np.zeros((*shape, 1), np.float32)), axis=-1)
        selected4 = np.concatenate((selected, np.ones((*shape, 1), np.float32)), axis=-1)
        result = glass_policy(raw4, selected4, mode=2, strength=0.25)
        expected = raw + np.float32(0.25) * (selected - raw)
        self.assertTrue(bit_equal(result[..., :3], expected))
        gate = np.resize(np.array([0.0, 0.25, 0.5, 1.0], np.float32), shape)
        baseline = glass_policy(raw4, selected4, mode=2, strength=0.5, gate=gate)
        off, _ = apply_specular(raw4, selected4, eligible, evidence,
                               CandidateConfig(), mode=2, strength=0.5, gate=gate)
        missing, _ = apply_specular(raw4, selected4, eligible, None,
                                   ON, mode=2, strength=0.5, gate=gate)
        self.assertTrue(bit_equal(off, baseline))
        self.assertTrue(bit_equal(missing, baseline))

    def test_off_and_missing_uncertainty_preserve_float_bits(self):
        raw, selected, eligible, evidence = simple()
        selected[0, 0] = np.array([-0.0, np.nan, np.inf], np.float32)
        for config, sidecar in ((CandidateConfig(), evidence), (ON, None)):
            output, _ = shrink_specular(raw, selected, eligible, sidecar, config)
            self.assertTrue(bit_equal(output, selected))

    def test_low_count_newly_visible_invalid_and_reset_abstain(self):
        raw, selected, eligible, evidence = simple()
        invalid_fields = [
            {"effective_count": np.zeros(eligible.shape, np.float32)},
            {"effective_count": np.full(eligible.shape, 7.999, np.float32)},
            {"effective_count": np.full(eligible.shape, np.nan, np.float32)},
            {"effective_count": np.full(eligible.shape, np.inf, np.float32)},
            {"valid": np.zeros(eligible.shape, bool)},
            {"independent_spatial": np.zeros(eligible.shape, bool)},
            {"noise_trace": np.full(eligible.shape, -1.0, np.float32)},
            {"noise_trace": np.full(eligible.shape, np.nan, np.float32)},
            {"noise_trace": np.full(eligible.shape, np.inf, np.float32)},
            {"surface_id": np.full(eligible.shape, -1, np.int32)},
        ]
        for changes in invalid_fields:
            with self.subTest(field=next(iter(changes)), value=str(next(iter(changes.values()))[0, 0])):
                output, _ = shrink_specular(raw, selected, eligible, replace(evidence, **changes), ON)
                self.assertTrue(bit_equal(output, selected))
        # A reset is absent/invalid support, not an invitation to reuse a prior frame.
        shrink_specular(raw, selected, eligible, evidence, ON)
        output, _ = shrink_specular(raw, selected, eligible, None, ON)
        self.assertTrue(bit_equal(output, selected))

    def test_crossed_geometry_and_partial_eligible_blocks_abstain(self):
        raw, selected, eligible, evidence = simple()
        surface = np.indices(eligible.shape).sum(0).astype(np.int32) % 2
        output, _ = shrink_specular(raw, selected, eligible, replace(evidence, surface_id=surface), ON)
        self.assertTrue(bit_equal(output, selected))
        eligible[::2, ::2] = False
        output, _ = shrink_specular(raw, selected, eligible, evidence, ON)
        self.assertTrue(bit_equal(output, selected))

    def test_drs_odd_extent_and_new_view_have_no_stale_border(self):
        for shape in ((9, 11), (1, 7), (7, 1), (13, 5)):
            raw, selected, eligible, evidence = simple(shape)
            output, _ = shrink_specular(raw, selected, eligible, evidence, ON)
            self.assertEqual(output.shape, selected.shape)
            self.assertTrue(bit_equal(output[-1], selected[-1]))
            self.assertTrue(bit_equal(output[:, -1], selected[:, -1]))
            # Fully new view with no provenance is exactly the user's selected input.
            reset, _ = shrink_specular(raw, selected, eligible, None, ON)
            self.assertTrue(bit_equal(reset, selected))

    def test_changed_colour_and_moderate_light_have_current_frame_response(self):
        raw, selected, eligible, evidence = simple()
        before, _ = shrink_specular(raw, selected, eligible, evidence, ON)
        colour_step = np.array([0.025, 0.01, -0.008], np.float32)
        changed, _ = shrink_specular(raw + colour_step, selected + colour_step, eligible, evidence, ON)
        np.testing.assert_allclose(changed - before, np.broadcast_to(colour_step, changed.shape), rtol=0, atol=8e-7)
        scale = np.float32(1.25)
        scaled, _ = shrink_specular(raw * scale, selected * scale, eligible,
                                   replace(evidence, noise_trace=evidence.noise_trace * scale * scale), ON)
        np.testing.assert_allclose(scaled, before * scale, rtol=0, atol=8e-7)

    def test_zero_noise_retains_thin_signal(self):
        raw, selected, eligible, evidence = simple()
        output, _ = shrink_specular(raw, selected, eligible,
                                   replace(evidence, noise_trace=np.zeros(eligible.shape, np.float32)), ON)
        np.testing.assert_allclose(output, selected, rtol=0, atol=2e-7)

    def test_moving_thin_sign_block_phase_counterexample_is_detected(self):
        result = phase_probe()
        # A passing test records a failure mode, not an image-quality approval.
        self.assertGreater(result["peak_to_peak_line_retention"], 0.05)
        self.assertGreater(result["phases"][0]["line_retention"], result["phases"][1]["line_retention"])

    def test_correlated_noise_requires_honest_independence_evidence(self):
        result = correlation_probe()
        self.assertTrue(result["honest_nonindependent_sidecar_bitwise_identity"])
        self.assertGreater(result["actual_to_claimed_highband_noise_ratio"], 3.5)
        self.assertLess(result["actual_to_claimed_highband_noise_ratio"], 4.5)

    def test_identical_observations_cannot_certify_glint_and_sparkle_truth(self):
        result = ambiguous_glint_probe()
        self.assertTrue(result["observations_identical_in_both_worlds"])
        self.assertTrue(result["all_evaluated_taps_original_base_changed"])
        self.assertLess(result["output_peak_amplitude"], result["original_peak_amplitude"])
        self.assertGreater(result["signal_world_l1_error"], 0.0)
        self.assertGreater(result["noise_world_l1_error"], 0.0)


if __name__ == "__main__":
    if sys.argv[1:] == ["--mutation-alpha"]:
        original_apply = apply_specular

        def alpha_mutant(raw_rgba, selected_rgba, *args, **kwargs):
            output, diagnostics = original_apply(raw_rgba, selected_rgba, *args, **kwargs)
            output[..., 3] = selected_rgba[..., 3]
            return output, diagnostics

        apply_specular = alpha_mutant
        suite = unittest.TestSuite([IndependentAdversarialTests(
            "test_raw_output_alpha_bits_and_read_only_inputs_are_protected")])
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(not result.wasSuccessful())
    elif sys.argv[1:] == ["--audit-holdout"]:
        print(json.dumps(audit_holdout(), indent=2, allow_nan=False))
    elif sys.argv[1:] == ["--measurements"]:
        print(json.dumps({
            "executor": "independent reviewer, cloud Linux CPU",
            "gpu_executed": False,
            "block_phase": phase_probe(),
            "spatial_correlation": correlation_probe(),
            "unidentifiable_glint": ambiguous_glint_probe(),
        }, indent=2, allow_nan=False))
    else:
        unittest.main(verbosity=2)
