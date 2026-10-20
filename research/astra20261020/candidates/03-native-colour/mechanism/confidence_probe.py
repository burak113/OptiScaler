"""Untuned development-only variance-confidence ablation; never production code.

Run after reading CONFIDENCE_PROBE.md. This module leaves native_colour.py and
all reviewer seeds/files unchanged. Only standard library and NumPy are used.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import native_colour as nc

SEEDS = (17, 41, 73)
HEIGHT, WIDTH, FRAMES = 24, 32, 24
CFG = nc.Config(enabled=True)
NOISE = {
    "moderate": {"zero_probability": .15, "channel_sigma": .12,
                 "common_sigma": .35, "rare_probability_nonzero": 0.0},
    "sparse_coloured_tail": {"zero_probability": .60, "channel_sigma": .30,
                             "common_sigma": .50, "rare_probability_nonzero": .03},
}


def jacobian(rgb):
    rgb = np.asarray(rgb, np.float64)
    w = nc.LUMA.astype(np.float64)
    eps = float(nc.CHROMA_EPS)
    y = rgb @ w
    denominators = rgb + eps*y[..., None]
    denominators = np.where(denominators > 0, denominators, 1.0)
    channel = np.eye(3) + eps*w[None]
    return np.stack([channel[0]/denominators[..., 0, None] - channel[1]/denominators[..., 1, None],
                     channel[2]/denominators[..., 2, None] - channel[1]/denominators[..., 1, None]], -2)


def confidence_output(source, raw, original_output, diagnostic, depth, normal, roughness):
    """Keep full six-dimensional paired covariance; do not discard zeros/tails."""
    src, rr = source[..., :3], raw[..., :3]
    joint = np.concatenate([src, rr], -1)
    moments = (joint[..., :, None] * joint[..., None, :]).reshape(HEIGHT, WIDTH, 36)
    valid = np.ones(depth.shape, bool)  # generator creates valid finite RGB/guides
    moments_mean, _, n_eff, _ = nc._support_means(moments, rr, depth, normal, roughness, valid, CFG)
    means = np.concatenate([diagnostic["source_mean"], diagnostic["colour_mean"]], -1).astype(np.float64)
    covariance = moments_mean.reshape(HEIGHT, WIDTH, 6, 6).astype(np.float64)
    covariance -= means[..., :, None] * means[..., None, :]
    np.divide(covariance, (n_eff - 1)[..., None, None], out=covariance,
              where=(n_eff > 1)[..., None, None])
    covariance = np.where((n_eff > 1)[..., None, None], covariance, 0)
    a = np.concatenate([jacobian(diagnostic["source_mean"]), -jacobian(diagnostic["colour_mean"])], -1)
    trace = np.einsum("...ik,...kl,...il->...", a, covariance, a)
    negative_trace = trace < 0
    variance = np.maximum(trace, 0)
    delta = (nc.opponent_encode(diagnostic["source_mean"]) -
             nc.opponent_encode(diagnostic["colour_mean"])).astype(np.float64)
    power = np.sum(delta*delta, axis=-1)
    denominator = power + variance
    q = np.zeros(depth.shape, np.float64)
    np.divide(power, denominator, out=q, where=denominator > 0)
    q = np.where(diagnostic["supported"] & (n_eff > 1), q, 0)
    amount = diagnostic["confidence"].astype(np.float64)*q
    change = diagnostic["log_delta"].astype(np.float64)*amount[..., None]
    gain = np.stack([np.exp(change[..., 0]), np.ones_like(amount), np.exp(change[..., 1])], -1)
    corrected = rr.astype(np.float64)*gain
    w = nc.LUMA.astype(np.float64)
    corrected *= ((rr.astype(np.float64)@w)/(corrected@w))[..., None]
    output = raw.copy()
    write = diagnostic["eligible"] & diagnostic["supported"] & (amount > 0) & np.any(change != 0, -1)
    output[..., :3][write] = corrected[write].astype(np.float32)
    assert np.array_equal(nc.rgba_words(output)[..., 3], nc.rgba_words(raw)[..., 3])
    return output, {"q": q, "variance": variance, "negative_trace": negative_trace,
                    "negative_trace_min": float(min(float(trace.min()), 0.0)),
                    "n_eff": n_eff}


def histories(scenario, scale):
    base = np.array([.30, .40, .20], np.float32)
    base *= scale/nc.luminance(base)
    uv0 = nc.opponent_encode(base)
    truth_uv = np.broadcast_to(uv0, (FRAMES, 2)).copy()
    if scenario == "true_colour_change":
        truth_uv[12:] += [.16, -.12]
    if scenario == "null":
        rr_uv = truth_uv.copy()
    elif scenario == "persistent_bias":
        rr_uv = truth_uv + [.12, -.08]
    elif scenario == "true_colour_change":
        rr_uv = truth_uv.copy()
        for t in range(12, FRAMES):
            rr_uv[t] = .8*rr_uv[t-1] + .2*truth_uv[t]
    else:
        raise ValueError(scenario)
    return nc.opponent_inverse(truth_uv, scale), nc.opponent_inverse(rr_uv, scale)


def noise_factors(seed, name):
    rng = np.random.default_rng(seed)
    cfg = NOISE[name]
    shape = (FRAMES, HEIGHT, WIDTH)
    live = rng.random(shape) >= cfg["zero_probability"]
    channel_sigma, common_sigma = cfg["channel_sigma"], cfg["common_sigma"]
    factors = np.exp(rng.normal(0, channel_sigma, shape+(3,)) - .5*channel_sigma**2)
    factors *= np.exp(rng.normal(0, common_sigma, shape+(1,)) - .5*common_sigma**2)
    p = cfg["rare_probability_nonzero"]
    if p:
        rare = rng.random(shape) < p
        tail = np.array([10.0, .2, 3.0])
        ordinary = (1-p*tail)/(1-p)
        factors *= np.where(rare[..., None], tail, ordinary)
    factors *= live[..., None]/(1-cfg["zero_probability"])
    return factors.astype(np.float32)


def metrics(outputs, raw, truth, mask):
    rgb = np.asarray(outputs, np.float32)[..., :3]
    target = np.broadcast_to(truth[:, None, None], rgb.shape)
    fixed_y = nc.luminance(target)
    residual = (rgb-target)/fixed_y[..., None]
    high = residual - .25*(np.roll(residual, 1, 1)+np.roll(residual, -1, 1)+
                            np.roll(residual, 1, 2)+np.roll(residual, -1, 2))
    temporal_hf = np.sqrt(np.sum(np.var(high, axis=0, dtype=np.float64), axis=-1))
    error = np.sqrt(np.mean(residual*residual, -1))
    desired = nc.opponent_encode(target)-nc.opponent_encode(raw[..., :3])
    applied = nc.opponent_encode(rgb)-nc.opponent_encode(raw[..., :3])
    direction_energy = float(np.sum(desired[:, mask]*desired[:, mask], dtype=np.float64))
    numerator = float(np.sum(applied[:, mask]*desired[:, mask], dtype=np.float64))
    return {"truth_chroma_rmse": float(np.sqrt(np.mean(residual[:, mask]**2, dtype=np.float64))),
            "truth_chroma_error_p99": float(np.quantile(error[:, mask], .99)),
            "truth_chroma_error_max": float(np.max(error[:, mask])),
            "temporal_chroma_hf_p90": float(np.quantile(temporal_hf[mask], .90)),
            "correction_dose": numerator/direction_energy if direction_energy > 1e-10 else None,
            "dose_numerator": numerator, "dose_direction_energy": direction_energy}


def run_scene(seed, name, scenario, scale):
    truth, rr_values = histories(scenario, scale)
    factors = noise_factors(seed, name)
    depth = np.full((HEIGHT, WIDTH), 10.0, np.float32)
    normal = np.zeros((HEIGHT, WIDTH, 3), np.float32); normal[..., 2] = 1
    rough = np.full((HEIGHT, WIDTH), .4, np.float32)
    authority = np.ones((HEIGHT, WIDTH), bool)
    mask = np.zeros((HEIGHT, WIDTH), bool); mask[3:-3, 3:-3] = True
    model = nc.NativeColourModel(CFG)
    raw_stack, original, probe = [], [], []
    confidence, variance, neff, neg = [], [], [], []
    for t in range(FRAMES):
        source = np.ones((HEIGHT, WIDTH, 4), np.float32)
        source[..., :3] = factors[t]*truth[t]
        raw = np.ones_like(source); raw[..., :3] = rr_values[t]
        output, diagnostic = model.frame(source, raw, raw, depth, normal, roughness=rough,
                                         authority=authority, frame_id=t)
        modified, qdiag = confidence_output(source, raw, output, diagnostic, depth, normal, rough)
        raw_stack.append(raw); original.append(output); probe.append(modified)
        confidence.append(float(qdiag["q"][mask].mean()))
        variance.append(float(qdiag["variance"][mask].mean()))
        neff.append(float(qdiag["n_eff"][mask].mean()))
        neg.append(int(qdiag["negative_trace"][mask].sum()))
    raw_stack = np.asarray(raw_stack)
    original_metrics = metrics(original, raw_stack, truth, mask)
    probe_metrics = metrics(probe, raw_stack, truth, mask)
    return {"seed": seed, "noise": name, "signal": scenario, "scale": scale,
            "frames": list(range(FRAMES)), "evaluation_pixels_per_frame": int(mask.sum()),
            "base_mask_sha256": hashlib.sha256(mask.tobytes()).hexdigest(),
            "source_factors_sha256": hashlib.sha256(factors.tobytes()).hexdigest(),
            "source_zero_fraction": float(np.mean(np.sum(factors, -1) == 0)),
            "original_log": original_metrics, "variance_confidence": probe_metrics,
            "hf_ratio_to_original": probe_metrics["temporal_chroma_hf_p90"] /
                                    original_metrics["temporal_chroma_hf_p90"],
            "dose_retention_to_original": (probe_metrics["correction_dose"] /
                                           original_metrics["correction_dose"]
                                           if original_metrics["correction_dose"] is not None
                                           and original_metrics["correction_dose"] > 0 else None),
            "mean_q": float(np.mean(confidence)), "per_frame_mean_q": confidence,
            "per_frame_mean_delta_variance": variance, "mean_effective_samples": float(np.mean(neff)),
            "negative_variance_trace_count": int(sum(neg)),
            "alpha_word_mismatch_count": 0,
            "source_noise_is_independent_between_frames_and_pixels": True}


def paired_identity_control():
    rng = np.random.default_rng(SEEDS[0])
    source = np.ones((HEIGHT, WIDTH, 4), np.float32)
    source[..., :3] = rng.lognormal(-1, .2, (HEIGHT, WIDTH, 3)).astype(np.float32)
    raw = source.copy()
    depth = np.full((HEIGHT, WIDTH), 10, np.float32)
    normal = np.zeros((HEIGHT, WIDTH, 3), np.float32); normal[..., 2] = 1
    rough = np.full((HEIGHT, WIDTH), .4, np.float32)
    output, diag = nc.NativeColourModel(CFG).frame(source, raw, raw, depth, normal,
                    roughness=rough, authority=np.ones(depth.shape, bool))
    probe, qdiag = confidence_output(source, raw, output, diag, depth, normal, rough)
    mismatch = int(np.count_nonzero(nc.rgba_words(probe) != nc.rgba_words(raw)))
    assert mismatch == 0
    max_variance = float(qdiag["variance"].max())
    assert max_variance < 1e-9
    return {"word_mismatches": mismatch, "paired_delta_variance_max": max_variance,
            "interpretation": "paired source/RR covariance cancels identical stochastic observations"}


def summarize(rows):
    summary = []
    for name in NOISE:
        selected = [r for r in rows if r["noise"] == name]
        null = [r["hf_ratio_to_original"] for r in selected if r["signal"] == "null"]
        bias = [r["dose_retention_to_original"] for r in selected if r["signal"] == "persistent_bias"]
        change = [r["dose_retention_to_original"] for r in selected if r["signal"] == "true_colour_change"]
        valid_bias = [x for x in bias if x is not None]
        valid_change = [x for x in change if x is not None]
        good = (max(null) <= .8 and len(valid_bias) == len(bias) and len(valid_change) == len(change)
                and min(valid_bias) >= .9 and min(valid_change) >= .9)
        summary.append({"noise": name, "null_hf_ratio_median": float(np.median(null)),
                        "null_hf_ratio_worst": float(max(null)),
                        "bias_dose_retention_median": float(np.median(valid_bias)) if valid_bias else None,
                        "bias_dose_retention_worst": float(min(valid_bias)) if valid_bias else None,
                        "change_dose_retention_median": float(np.median(valid_change)) if valid_change else None,
                        "change_dose_retention_worst": float(min(valid_change)) if valid_change else None,
                        "bias_original_nonpositive_dose_cases": len(bias)-len(valid_bias),
                        "change_original_nonpositive_dose_cases": len(change)-len(valid_change),
                        "original_change_dose_median": float(np.median([r["original_log"]["correction_dose"]
                                                        for r in selected if r["signal"] == "true_colour_change"])),
                        "probe_change_dose_median": float(np.median([r["variance_confidence"]["correction_dose"]
                                                        for r in selected if r["signal"] == "true_colour_change"])),
                        "fixed_development_gate_pass": bool(good)})
    return summary


def main():
    start = time.perf_counter()
    source_hash = hashlib.sha256((HERE.parent/"native_colour.py").read_bytes()).hexdigest()
    protocol_hash = hashlib.sha256((HERE/"CONFIDENCE_PROBE.md").read_bytes()).hexdigest()
    rows = [run_scene(seed, name, scenario, scale)
            for seed in SEEDS for name in NOISE
            for scenario in ("null", "persistent_bias", "true_colour_change")
            for scale in (.2, .015)]
    result = {"schema": "native-colour-confidence-probe-v1", "executor": "mechanism subagent; NumPy CPU",
              "gpu_executed": False, "native_source_sha256": source_hash,
              "frozen_protocol_sha256": protocol_hash, "seeds": list(SEEDS),
              "native_config_unchanged": asdict(CFG), "noise_parameters": NOISE,
              "covariance_multiplier": 1.0, "parameter_search_performed": False,
              "native_file_modified": False, "mask_origin": "fixed radius-three interior before candidate",
              "numpy_version": np.__version__, "rows": rows,
              "paired_identity": paired_identity_control(), "summary": summarize(rows),
              "elapsed_seconds": time.perf_counter()-start,
              "limitations": ["Delta-method approximation can fail for heavy tails and small channel means.",
                              "Effective independent-sample count is not calibrated for real spatial correlation.",
                              "RR-dependent weights make support conditional and can bias the covariance estimate.",
                              "Synthetic RR is clean here; paired covariance closure is tested separately.",
                              "No strength renormalization: lost correction dose is reported explicitly.",
                              "Float32 scope; this ablation has no shader, host adapter or native/GPU acceptance."]}
    assert source_hash == hashlib.sha256((HERE.parent/"native_colour.py").read_bytes()).hexdigest()
    (HERE/"confidence_results.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"summary": result["summary"], "paired_identity": result["paired_identity"],
                      "elapsed_seconds": result["elapsed_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
