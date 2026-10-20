"""Source-shaped Anchor Gain arithmetic up to the actual typed output store.

This is a numerical calibration model of the audited policy, not a new policy.
Inputs are already stored Stats/Recall fields. Key capture/reprojection, GPU
execution and RR output are not simulated. The unrounded gain is retained so
RNE/RTZ comparisons occur at the actual output store instead of after another
model has already discarded its low bits.
"""
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np

from .arithmetic import f32, f32_add, f32_div, f32_mul, f32_sub
from .fixedpoint import frame_sum_bounds
from .storage import fp16_preimage_f32, store_fp16


@dataclass(frozen=True)
class GainParameters:
    """Read fields of source Params/Params2/Params3/Params4, without policy edits."""
    band_a: float = .18
    band_tau: float = 10
    cap_extra: float = .05
    cap_hard: float = .30
    strength: float = 1
    fallback_a_unused: float = .15
    tap_step: float = 3
    coverage_taps: float = 2.7
    reject_mult: float = 1.8
    reject_abs: float = .30
    gain_low: float = .80
    native_local_gate: float = 1


@dataclass(frozen=True)
class GainResult:
    gain: np.ndarray
    numerator: np.ndarray
    denominator: np.ndarray
    coverage: np.ndarray
    model_excess: np.float32
    reject_threshold: np.float32
    frame_ratio: np.float32
    frame_coverage: np.float32
    fallback: np.float32
    frame_rejected: bool
    local_measurable: np.ndarray
    local_rejected: np.ndarray
    native_local_blocked: np.ndarray
    exp_mode: str

    def stored(self, rounding):
        return store_fp16(self.gain, rounding=rounding)


def _model_excess(k, params, exp_mode):
    argument = f32_div(-np.maximum(f32(k), np.float32(0)),
                       np.maximum(f32(params.band_tau), np.float32(1e-3)))
    if exp_mode == "source_exp_f32":
        exponential = np.exp(argument).astype(np.float32)
    elif exp_mode == "dxil_exp2_f32":
        # Both pinned Gain headers lower exp(x) to Exp(x * log2(e)); DXIL Exp
        # is base2. Constant0x3FF7154760000000 in the listing denotes this f32.
        # NumPy exp2 is still not a claim about the device instruction's accuracy.
        exponential = np.exp2(f32_mul(argument, np.float32(1.4426950408889634))).astype(np.float32)
    else:
        raise ValueError("exp_mode must be 'source_exp_f32' or 'dxil_exp2_f32'")
    return np.float32(f32_mul(params.band_a, exponential))


def anchor_gain_unstored(stats, recalled, k, frame_ratio, *, frame_count,
                         frame_measured, policy="native", params=None,
                         exp_mode="source_exp_f32"):
    """Compute the current Gain observable with explicit float32 staging.

    ``frame_count`` and ``frame_measured`` are supplied observations/assumptions;
    they are not silently reconstructed from rounded levels. ``frame_ratio`` is
    the source float ratio (exact counter-derived or explicitly bounded), and is
    ignored when the frame is unmeasured. Native uncertainty must be tested at
    its possible endpoints by the caller. All intermediate arrays are returned.

    This models Gain, not the pass's key-ring side effect. Unused depth/slice
    lanes and fallback_a_unused never enter the current Gain expression.
    """
    if policy not in ("native", "combined"):
        raise ValueError("policy must be 'native' or 'combined'")
    s, r = f32(stats), f32(recalled)
    if s.ndim != 3 or s.shape[-1] != 4 or s.shape != r.shape or min(s.shape[:2]) < 1:
        raise ValueError("expected equal nonempty HxWx4 Stats/Recall grids")
    if not np.isfinite(s[..., [0, 2]]).all() or not np.isfinite(r[..., [0, 1, 3]]).all():
        raise ValueError("used Gain input lanes must be finite")
    if not np.isfinite(k):
        raise ValueError("motion-window age must be finite")
    count = int(frame_count)
    if count != frame_count or not 0 <= count <= min(s.shape[0] * s.shape[1], (1 << 32) - 1):
        raise ValueError("frame_count must fit the source cell population")
    if not isinstance(frame_measured, (bool, np.bool_)):
        raise ValueError("frame_measured must be an explicit bool")
    if frame_measured and count == 0:
        raise ValueError("a zero-count frame cannot be measured")
    p = GainParameters() if params is None else params
    used = [p.band_a, p.band_tau, p.cap_extra, p.cap_hard, p.strength, p.tap_step,
            p.coverage_taps, p.reject_mult, p.reject_abs, p.gain_low]
    if policy == "native":
        used.append(p.native_local_gate)
    if not np.isfinite(used).all() or not 0 <= p.gain_low <= 1:
        raise ValueError("used Gain constants must be finite and gain_low in [0,1]")
    if frame_measured:
        if not np.isfinite(frame_ratio) or frame_ratio < 0:
            raise ValueError("measured frame ratio must be finite and nonnegative")
        ratio = np.float32(np.minimum(f32(frame_ratio), np.float32(4)))
    else:
        ratio = np.float32(1)
    step = int(f32_add(np.clip(f32(p.tap_step), 1, 4), .5))
    h, w = s.shape[:2]
    numerator = np.zeros((h, w), np.float32)
    denominator = np.zeros_like(numerator)
    coverage = np.zeros_like(numerator)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            ix = np.ix_(np.clip(np.arange(h) + dy * step, 0, h - 1),
                        np.clip(np.arange(w) + dx * step, 0, w - 1))
            tapped_stats, tapped_recalled = s[ix], r[ix]
            weight = f32_mul(tapped_recalled[..., 1], tapped_recalled[..., 3])
            numerator = f32_add(numerator, f32_mul(tapped_recalled[..., 0], weight))
            denominator = f32_add(denominator, f32_mul(tapped_stats[..., 0], weight))
            coverage = f32_add(coverage, weight)
    model_excess = _model_excess(k, p, exp_mode)
    threshold = np.float32(np.maximum(f32_mul(p.reject_mult, model_excess), f32(p.reject_abs)))
    cells = np.maximum(f32_mul(f32(w), f32(h)), np.float32(1))
    frame_coverage = np.float32(f32_div(f32(count), cells))
    frame_rejected = bool(frame_measured and frame_coverage >= np.float32(.15)
                          and f32_sub(1, ratio) > threshold)
    fallback = np.float32(1)
    if policy == "combined" and frame_measured and frame_coverage >= np.float32(.15):
        fallback = np.float32(np.minimum(ratio, np.float32(1)))
    native_local_blocked = np.zeros((h, w), bool)
    if policy == "native" and f32(p.native_local_gate) > np.float32(.5):
        native_local_blocked = (s[..., 2] < np.float32(.5)) | (coverage < np.float32(.5))
    local_measurable = (coverage >= np.float32(.5)) & (denominator > np.float32(1e-9))
    measured = np.full((h, w), fallback, np.float32)
    np.divide(numerator, denominator, out=measured, where=local_measurable)
    local_rejected = local_measurable & (f32_sub(1, measured) > threshold)
    blend = np.clip(f32_div(coverage, np.maximum(f32(p.coverage_taps), np.float32(1e-3))), 0, 1)
    gain = f32_add(f32_mul(blend, measured), f32_mul(f32_sub(1, blend), fallback))
    cap = np.minimum(f32_add(model_excess, p.cap_extra), f32(p.cap_hard))
    gain = np.clip(gain, f32(p.gain_low), np.float32(1))
    gain = np.maximum(gain, f32_sub(1, cap))
    gain = f32_add(1, f32_mul(np.clip(f32(p.strength), 0, 1), f32_sub(gain, 1)))
    # These branches return literal1 before strength/cap in the source.
    gain = np.where(frame_rejected | native_local_blocked | local_rejected,
                    np.float32(1), gain).astype(np.float32)
    return GainResult(gain, numerator, denominator, coverage, model_excess, threshold,
                      ratio, frame_coverage, fallback, frame_rejected, local_measurable,
                      local_rejected, native_local_blocked, exp_mode)


def anchor_gain(*args, rounding="rne", **kwargs):
    """Apply one output store to anchor_gain_unstored, returning expanded FP16."""
    return anchor_gain_unstored(*args, **kwargs).stored(rounding)


def _error_metrics(predicted, actual):
    error = np.asarray(predicted, np.float64) - np.asarray(actual, np.float64)
    absolute = np.abs(error)
    half_distance = np.abs(np.asarray(predicted, np.float16).view(np.uint16).astype(np.int32)
                           - np.asarray(actual, np.float16).view(np.uint16).astype(np.int32))
    return {
        "population": int(error.size), "nonzero_count": int(np.count_nonzero(error)),
        "predicted_above_gpu_count": int(np.count_nonzero(error > 0)),
        "predicted_below_gpu_count": int(np.count_nonzero(error < 0)),
        "max_abs": float(absolute.max(initial=0)),
        "p50_abs": float(np.percentile(absolute, 50)),
        "p90_abs": float(np.percentile(absolute, 90)),
        "p99_abs": float(np.percentile(absolute, 99)),
        "max_half_steps": int(half_distance.max(initial=0)),
        "identity_classification_mismatches": int(np.count_nonzero((predicted == 1) != (actual == 1))),
    }


def replay_calibration(anchor_root=None):
    """Replay every bundled recorded Gain frame, both stores and two exp models.

    This is CPU evaluation of recorded GPU fields, never new GPU execution. The
    population is each fixture's complete immutable grid, including identity
    cells. Native frame ratios remain conditional stored-field estimates.
    """
    root = (Path(__file__).resolve().parents[3] / "portable" / "anchor"
            if anchor_root is None else Path(anchor_root))
    manifest = json.loads((root / "fixtures" / "manifest.json").read_text(encoding="utf-8"))
    rows, groups = [], {}
    examples = []
    rtz_residuals = {}
    actual_frame_counts = {"combined": 0, "native": 0}
    native_bound_invariance = []
    for group in manifest["groups"]:
        policy = "combined" if group["id"] == "combined" else "native"
        for capture in group["captures"]:
            with np.load(root / capture["file"], allow_pickle=False) as data:
                for j, frame in enumerate(data["frames"]):
                    actual_frame_counts[policy] += 1
                    stats, recalled = data["stats"][j], data["recalled"][j]
                    actual = data["gain"][j].astype(np.float32)
                    fixed_mask = data["fixed_mask"][j]
                    ratio_bounds = []
                    if policy == "combined":
                        atoms = data["counters"][j]
                        count = int(atoms[2])
                        measured = bool(atoms[0] > 0 and count > 0)
                        ratio = float(f32_div(f32(atoms[1]), f32(atoms[0]))) if measured else 1.0
                        ratio_kind = "source_float32_division_of_exact_exported_uint32_counters"
                    else:
                        bounds = frame_sum_bounds(stats[..., 0], recalled[..., 0], fixed_mask, rounding="rne")
                        if bounds.current_min == 0 and bounds.current_max > 0 and bounds.count:
                            raise ValueError("native measured state is not identifiable for this fixture")
                        count = bounds.count
                        measured = bool(bounds.current_min > 0 and count > 0)
                        ratio = bounds.as_dict()["source_ratio_estimate"]
                        ratio_kind = "bounded_stored_field_estimate_conditional_on_rne_stats_store"
                        ratio_bounds = [frame_sum_bounds(stats[..., 0], recalled[..., 0], fixed_mask,
                                                         rounding=mode) for mode in ("rne", "rtz")]
                    for exp_mode in ("source_exp_f32", "dxil_exp2_f32"):
                        result = anchor_gain_unstored(stats, recalled, int(data["k"][j]), ratio,
                                                      frame_count=count, frame_measured=measured,
                                                      policy=policy, exp_mode=exp_mode)
                        guard_invariant = None
                        if policy == "native":
                            guard_invariant = True
                            for interval in ratio_bounds:
                                possible_measured = bool(interval.count and interval.current_min > 0)
                                if interval.current_min == 0 and interval.current_max > 0 and interval.count:
                                    guard_invariant = False
                                for endpoint in interval.ratio_interval():
                                    extreme = anchor_gain_unstored(stats, recalled, int(data["k"][j]), endpoint,
                                                                  frame_count=interval.count,
                                                                  frame_measured=possible_measured,
                                                                  policy=policy, exp_mode=exp_mode)
                                    guard_invariant &= (extreme.frame_rejected == result.frame_rejected and
                                                        np.array_equal(extreme.gain, result.gain))
                            # Native ratio enters only one monotone guard; its
                            # equal endpoint decisions certify the whole interval.
                            native_bound_invariance.append(bool(guard_invariant))
                        for rounding in ("rne", "rtz"):
                            predicted = result.stored(rounding)
                            metric = _error_metrics(predicted, actual)
                            row = {"capture": capture["capture"], "frame": int(frame), "policy": policy,
                                   "rounding": rounding, "exp_mode": exp_mode, "frame_ratio": ratio,
                                   "frame_ratio_kind": ratio_kind, "frame_rejected": result.frame_rejected,
                                   "ratio_guard_invariant_across_rne_and_rtz_field_bounds": guard_invariant,
                                   **metric}
                            rows.append(row)
                            key = (policy, exp_mode, rounding)
                            pair = groups.setdefault(key, [[], []])
                            pair[0].append(predicted.ravel())
                            pair[1].append(actual.ravel())
                            if rounding == "rtz" and metric["nonzero_count"]:
                                for y, x in np.argwhere(predicted != actual):
                                    y, x = int(y), int(x)
                                    residual_key = (policy, capture["capture"], int(frame), y, x)
                                    if residual_key not in rtz_residuals:
                                        preimage = fp16_preimage_f32(actual[y, x], rounding="rtz")
                                        taps = []
                                        for dy in (-1, 0, 1):
                                            for dx in (-1, 0, 1):
                                                qy = int(np.clip(y + 3 * dy, 0, stats.shape[0] - 1))
                                                qx = int(np.clip(x + 3 * dx, 0, stats.shape[1] - 1))
                                                taps.append({"grid_xy": [qx, qy],
                                                             "stats": stats[qy, qx].astype(np.float32).tolist(),
                                                             "recalled": recalled[qy, qx].astype(np.float32).tolist()})
                                        rtz_residuals[residual_key] = {
                                            "capture": capture["capture"], "frame": int(frame), "policy": policy,
                                            "grid_xy": [x, y], "grid_size_wh": [stats.shape[1], stats.shape[0]],
                                            "k": int(data["k"][j]), "frame_count": count,
                                            "frame_measured": measured, "frame_ratio": ratio,
                                            "frame_ratio_kind": ratio_kind,
                                            "exact_combined_counters_u32": data["counters"][j].tolist() if policy == "combined" else None,
                                            "recorded_gpu": float(actual[y, x]),
                                            "recorded_gpu_rtz_preimage_f32": [float(preimage.lower), float(preimage.upper)],
                                            "tap_order": "dy then dx from -1 to1, step3, clamp to complete grid",
                                            "taps": taps, "source_models": {},
                                        }
                                    rtz_residuals[residual_key]["source_models"][exp_mode] = {
                                        "gain_unstored_f32": float(result.gain[y, x]),
                                        "predicted_rtz": float(predicted[y, x]),
                                        "numerator": float(result.numerator[y, x]),
                                        "denominator": float(result.denominator[y, x]),
                                        "coverage": float(result.coverage[y, x]),
                                        "model_excess": float(result.model_excess),
                                        "reject_threshold": float(result.reject_threshold),
                                        "frame_rejected": result.frame_rejected,
                                        "local_rejected": bool(result.local_rejected[y, x]),
                                        "native_local_blocked": bool(result.native_local_blocked[y, x]),
                                    }
                            if metric["nonzero_count"] and len(examples) < 16:
                                y, x = np.argwhere(predicted != actual)[0]
                                preimage = fp16_preimage_f32(actual[y, x], rounding=rounding)
                                examples.append({"capture": capture["capture"], "frame": int(frame),
                                                 "policy": policy, "exp_mode": exp_mode, "rounding": rounding,
                                                 "grid_xy": [int(x), int(y)],
                                                 "gain_unstored_f32": float(result.gain[y, x]),
                                                 "predicted": float(predicted[y, x]), "recorded_gpu": float(actual[y, x]),
                                                 "gpu_payload_preimage_f32": [float(preimage.lower), float(preimage.upper)],
                                                 "numerator": float(result.numerator[y, x]),
                                                 "denominator": float(result.denominator[y, x]),
                                                 "coverage": float(result.coverage[y, x])})
    summary = [{"policy": p, "exp_mode": e, "rounding": r,
                **_error_metrics(np.concatenate(v[0]), np.concatenate(v[1]))}
               for (p, e, r), v in groups.items()]
    return {
        "executor": "CPU source-shaped model against packaged recorded GPU Gain fields",
        "gpu_executed": False, "frame_counts": actual_frame_counts,
        "fixed_population": "all stored grid cells in chronological fixture order; no output-derived mask",
        "native_ratio_limit": "conditional estimate; exact pre-store native atomics absent",
        "native_gain_invariant_across_rne_and_rtz_field_ratio_bounds": all(native_bound_invariance),
        "summary": summary, "frames": rows, "mismatch_examples": examples,
        "rtz_residual_cells": list(rtz_residuals.values()),
        "store_only_explanation_complete": all(any(x["nonzero_count"] == 0 for x in summary if x["policy"] == policy)
                                               for policy in actual_frame_counts),
        "remaining_arithmetic_assumptions": ["DXC fast-math contraction/reassociation",
                                              "device Exp/exp2 accuracy", "division/reciprocal lowering",
                                              "native pre-store atomics not exported"],
    }


if __name__ == "__main__":
    print(json.dumps(replay_calibration(), indent=2, allow_nan=False))
