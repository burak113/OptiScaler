"""Read-only frozen-model imports and independent matched-dose metrology.

This is synthetic research. All variants are rejected diagnostic ablations,
not native runtime implementations or producers of support certificates.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[2]
CANDIDATE = PACKAGE / "candidates" / "03-native-colour"
sys.path.insert(0, str(CANDIDATE / "review"))
sys.path.insert(0, str(CANDIDATE))
import independent_checks as ic  # noqa: E402
import native_colour as nc  # noqa: E402

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float64)
PROTOCOL = json.loads((HERE / "PROTOCOL.json").read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def array_hash(value):
    a = np.ascontiguousarray(value)
    return hashlib.sha256(a.dtype.str.encode() + str(a.shape).encode() + a.tobytes()).hexdigest()


def luminance(rgb):
    return np.asarray(rgb, np.float64)[..., :3] @ LUMA


def at_luma(rgb, y):
    a = np.asarray(rgb, np.float64)
    return a * (np.asarray(y) / luminance(a))[..., None]


def chroma(rgb):
    a = np.asarray(rgb, np.float64)[..., :3]
    return a - luminance(a)[..., None]


def opponent(rgb):
    """Independent float64 metric coordinates, not candidate diagnostics."""
    a = np.asarray(rgb, np.float64)[..., :3]
    y = luminance(a)
    if not np.all(np.isfinite(a)) or np.any(a < 0) or np.any(y <= 0):
        raise ValueError("metric requires finite nonnegative RGB and positive luma")
    c = a / y[..., None] + 1e-4
    return np.log(c[..., (0, 2)] / c[..., 1, None])


def dose(output, raw, truth, mask):
    """Signed achieved correction; zero/negative values are not a win."""
    if np.asarray(mask).dtype != np.bool_ or not np.any(mask):
        raise ValueError("a nonempty frozen boolean mask is required")
    wanted = opponent(truth) - opponent(raw)
    applied = opponent(output) - opponent(raw)
    energy = float(np.sum(wanted[mask] ** 2, dtype=np.float64))
    if energy <= 1e-12:
        return None
    return float(np.sum(applied[mask] * wanted[mask], dtype=np.float64) / energy)


def attenuate_output(raw, full, eligible, amount):
    """Evaluation-only whole-sequence scalar; preserve original selected words.

    raw here is the original selected output, including its protected words.
    Inputs are already native half arrays; this does not implement a new pass.
    """
    if not 0 <= amount <= 1:
        raise ValueError("no correction extrapolation is permitted")
    result = raw.copy()
    changed = eligible & np.any(raw.view(np.uint16)[..., :3] != full.view(np.uint16)[..., :3], -1)
    if amount == 0:
        return result
    if amount == 1:
        return full.copy()
    value = (raw[..., :3].astype(np.float32)
             + np.float32(amount) * (full[..., :3].astype(np.float32) - raw[..., :3].astype(np.float32)))
    # Independent explicit finite half RTZ, including the selected storage step.
    stored = value.astype(np.float16)
    overshoot = np.abs(stored.astype(np.float32)) > np.abs(value)
    stored = np.where(overshoot, np.nextafter(stored, np.float16(0)), stored)
    result[..., :3][changed] = stored[changed]
    return result


def match_dose(raw, selected, full, truth, eligible, mask, target, tolerance=0.003):
    """One oracle evaluation scalar, never per-pixel tuning or shader input.

    No extrapolation is allowed. A variant failing to reach the declared dose is
    explicitly unmatched. Bisection includes FP16 storage; the actual dose is
    retained rather than replacing it with the requested target.
    """
    full_dose = dose(full, raw, truth, mask)
    if full_dose is None or full_dose < target - tolerance:
        return None, {"matched": False, "target": target, "full_dose": full_dose,
                      "reason": "full_output_does_not_reach_target", "amount": None}
    lo, hi = 0.0, 1.0
    best = full.copy()
    achieved, best_amount = full_dose, 1.0
    for _ in range(22):
        mid = (lo + hi) * 0.5
        value = attenuate_output(selected, full, eligible, mid)
        current = dose(value, raw, truth, mask)
        if current is None:
            raise AssertionError("nonzero desired direction disappeared")
        if abs(current - target) < abs(achieved - target):
            best, achieved, best_amount = value, current, mid
        if current < target:
            lo = mid
        else:
            hi = mid
    matched = abs(achieved - target) <= tolerance
    return (best if matched else None), {
        "matched": matched, "target": target, "achieved": achieved,
        "full_dose": full_dose, "amount": best_amount,
        "reason": "matched_including_half_storage" if matched else "quantized_target_unreachable",
        "oracle_evaluation_scalar_not_runtime_parameter": True,
    }


def high_pass(a):
    a = np.asarray(a, np.float64)
    return a - 0.25 * (np.roll(a, 1, -3) + np.roll(a, -1, -3)
                       + np.roll(a, 1, -2) + np.roll(a, -1, -2))


def frozen_masks(raw, selected, authority, *, active_extent, crop_origins):
    """Only original arrays/coordinates enter masks; output is read-only."""
    frames, h, w = raw.shape[:3]
    aw, ah = active_extent
    yy, xx = np.indices((h, w))
    active = (xx < aw) & (yy < ah)
    eligible = np.all(raw.view(np.uint16) == selected.view(np.uint16), -1) & authority & active
    interior = (xx >= 6) & (xx < aw - 6) & (yy >= 6) & (yy < ah - 6)
    quiet, detail, glint = [], [], []
    for frame in range(frames):
        ox, oy = crop_origins[frame]
        gx, gy = xx + ox, yy + oy
        lines = ((gx % 17) == 7) | ((gx % 17) == 8)
        near_lines = np.minimum((gx - 7) % 17, (8 - gx) % 17) <= 3
        gl = ((gx - 19) ** 2 + (gy - 12) ** 2 <= 1) | ((gx - 33) ** 2 + (gy - 17) ** 2 <= 1)
        near_gl = ((gx - 19) ** 2 + (gy - 12) ** 2 <= 16) | ((gx - 33) ** 2 + (gy - 17) ** 2 <= 16)
        quiet.append(eligible[frame] & interior & ~near_lines & ~near_gl)
        detail.append(eligible[frame] & interior & lines & ~near_gl)
        glint.append(eligible[frame] & active & gl)
    masks = {"eligible": eligible, "quiet": np.stack(quiet),
             "detail": np.stack(detail), "glint": np.stack(glint),
             "interior": eligible & interior}
    for value in masks.values():
        value.flags.writeable = False
    return masks


def make_sequence(seed, family, level):
    """Analytic world-space field; moving crop is not a motion-vector history."""
    frames = PROTOCOL["frame_count"]
    aw, ah = PROTOCOL["active_extent"]
    w, h = PROTOCOL["allocation_extent"]
    world_h, world_w = ah + 8, aw + 8
    yy, xx = np.indices((world_h, world_w))
    palette = np.zeros((world_h, world_w, 3), np.float64) + np.array([0.86, 1.0, 0.92])
    fine = 0.025 * np.sin(xx * 2 * np.pi / 6) + 0.012 * np.sin(yy * 2 * np.pi / 7)
    fine += 0.06 * (((xx % 17) == 7) | ((xx % 17) == 8))
    palette[..., 0] += fine
    palette[..., 1] -= fine * LUMA[0] / LUMA[1]
    glints = (((xx - 19) ** 2 + (yy - 12) ** 2 <= 1)
              | ((xx - 33) ** 2 + (yy - 17) ** 2 <= 1))
    base_truth = at_luma(palette, level * (1 + 2.5 * glints))
    rng = np.random.default_rng(seed)
    rr_rng = np.random.default_rng(seed + 900001)
    source_state = np.zeros_like(base_truth)
    rr_state = np.zeros_like(base_truth)
    sources, raws, selecteds, truths, origins = [], [], [], [], []
    authority = np.ones((frames, h, w), bool)
    alpha = np.where((np.indices((h, w)).sum(0) % 3) == 0, np.uint16(0x8000), np.uint16(0x7e23))
    for frame in range(frames):
        origin = PROTOCOL["crop_origins"][frame % len(PROTOCOL["crop_origins"]) ]
        ox, oy = origin
        origins.append(origin)
        truth_world = base_truth * (1.25 if frame >= frames // 2 else 1.0)
        if family == "independent":
            sigma = 0.20
            factor = np.exp(sigma * rng.normal(size=base_truth.shape) - 0.5 * sigma**2)
        elif family == "sparse_tail":
            p, sigma = 0.18, 0.25
            factor = (rng.random((world_h, world_w, 1)) < p) / p
            factor = factor * np.exp(sigma * rng.normal(size=base_truth.shape) - 0.5 * sigma**2)
        elif family == "rare_chromatic_tail":
            p = 0.012
            tail = np.array([12.0, 2.0, 7.0])
            ordinary = (1 - p * tail) / (1 - p)
            factor = np.where(rng.random((world_h, world_w, 1)) < p, tail, ordinary)
        elif family == "spatial_temporal_correlated":
            rho, sigma = 0.85, 0.25
            innovation = rng.normal(size=(world_h, 1, 3))
            source_state = rho * source_state + np.sqrt(1 - rho * rho) * innovation
            variance = 1 - rho ** (2 * (frame + 1))
            factor = np.exp(sigma * source_state - 0.5 * sigma * sigma * variance)
        else:
            raise ValueError(family)
        raw_world = at_luma(truth_world * np.exp([0.11, -0.06, 0.07]), luminance(truth_world))
        if family == "spatial_temporal_correlated":
            rr_state = 0.8 * rr_state + 0.6 * rr_rng.normal(size=(1, world_w, 3))
            residual = np.exp(0.025 * rr_state)
        else:
            residual = np.exp(0.006 * rr_rng.normal(size=base_truth.shape))
        raw_world = at_luma(raw_world * residual, luminance(raw_world))
        source = np.zeros((h, w, 4), np.float16)
        raw = np.zeros_like(source)
        # Defined inactive allocations; selected padding is opaque storage.
        source.view(np.uint16)[...] = np.uint16(0x3555)
        raw.view(np.uint16)[...] = np.uint16(0x3666)
        source[:ah, :aw, :3] = (truth_world * factor)[oy:oy + ah, ox:ox + aw]
        raw[:ah, :aw, :3] = raw_world[oy:oy + ah, ox:ox + aw]
        source.view(np.uint16)[..., 3] = alpha
        raw.view(np.uint16)[..., 3] = alpha
        selected = raw.copy()
        selected.view(np.uint16)[:, 2, 3] ^= np.uint16(1)
        authority[frame, :, 3] = False
        truth = np.empty((h, w, 3), np.float64)
        truth[...] = raw[..., :3].astype(np.float64)
        truth[:ah, :aw] = truth_world[oy:oy + ah, ox:ox + aw]
        sources.append(source)
        raws.append(raw)
        selecteds.append(selected)
        truths.append(truth)
    raw, selected = np.stack(raws), np.stack(selecteds)
    masks = frozen_masks(raw, selected, authority, active_extent=(aw, ah), crop_origins=origins)
    normals = np.zeros((h, w, 3), np.float32)
    normals[..., 2] = 1
    return {
        "source": np.stack(sources), "raw": raw, "selected": selected,
        "truth": np.stack(truths), "authority": authority,
        "depth": np.full((h, w), 10, np.float32), "normal": normals,
        "roughness": np.full((h, w), 0.2, np.float32),
        "masks": masks, "origins": origins, "active_extent": (aw, ah),
        "denominator": luminance(raw),
        "seed": seed, "family": family,
    }


def evaluate_variant(data, name):
    cfg = nc.Config(enabled=True, **PROTOCOL["variants"][name])
    model = nc.NativeColourModel(cfg)
    outputs = []
    for t in range(len(data["raw"])):
        out, _ = model.frame(
            data["source"][t], data["raw"][t], data["selected"][t],
            data["depth"], data["normal"], roughness=data["roughness"],
            authority=data["authority"][t], active_extent=data["active_extent"],
            crop_origin=tuple(data["origins"][t]), frame_id=t)
        ic.assert_word_contract(out, data["raw"][t], data["selected"][t],
                                data["authority"][t], active_extent=data["active_extent"])
        outputs.append(out)
    return np.stack(outputs)


def aligned_temporal_rms(error, mask, origins, active_extent):
    """Compare identical world texels after analytic crop alignment."""
    aw, ah = active_extent
    ww = aw + max(p[0] for p in origins)
    wh = ah + max(p[1] for p in origins)
    previous = previous_mask = None
    total = 0.0
    count = 0
    for t, (ox, oy) in enumerate(origins):
        world = np.zeros((wh, ww, 3), np.float64)
        world_mask = np.zeros((wh, ww), bool)
        world[oy:oy + ah, ox:ox + aw] = error[t, :ah, :aw]
        world_mask[oy:oy + ah, ox:ox + aw] = mask[t, :ah, :aw]
        if previous is not None:
            common = previous_mask & world_mask
            total += float(np.sum((world[common] - previous[common])**2))
            count += int(common.sum()) * 3
        previous, previous_mask = world, world_mask
    return float(np.sqrt(total / count)) if count else None


def metrics(output, data):
    raw, truth, masks = data["raw"], data["truth"], data["masks"]
    den = data["denominator"]
    residual = (chroma(output) - chroma(truth)) / den[..., None]
    hp = high_pass(residual)
    quiet, detail, glint = (masks[k] for k in ("quiet", "detail", "glint"))
    if not all(np.any(m) for m in (quiet, detail, glint)):
        raise AssertionError("stimulus masks must be nonempty")
    truth_hp = high_pass(chroma(truth) / den[..., None])
    output_hp = high_pass(chroma(output) / den[..., None])
    def projection(mask):
        e = float(np.sum(truth_hp[mask]**2))
        return float(np.sum(output_hp[mask] * truth_hp[mask]) / e) if e else None
    return {
        "achieved_correction_dose": dose(output, raw, truth, quiet),
        "spatial_HF_error_RMS": float(np.sqrt(np.mean(hp[quiet]**2))),
        "crop_aligned_temporal_error_RMS": aligned_temporal_rms(
            residual, quiet, data["origins"], data["active_extent"]),
        "quiet_error_p99": float(np.quantile(np.linalg.norm(residual[quiet], axis=-1), .99)),
        "thin_chroma_projection": projection(detail),
        "glint_chroma_projection": projection(glint),
        "glint_luma_peak_ratio": float(np.max(luminance(output)[glint]) / np.max(luminance(raw)[glint])),
        "luma_relative_change_max": float(np.max(np.abs(luminance(output) - luminance(raw)) / den)),
        "quiet_pixel_frames": int(quiet.sum()), "thin_pixel_frames": int(detail.sum()),
        "glint_pixel_frames": int(glint.sum()),
    }


def paired_bootstrap(values, seed=98731, repetitions=2048):
    values = np.asarray(values, np.float64)
    if values.ndim != 1 or not np.all(np.isfinite(values)) or not len(values):
        raise ValueError("finite per-seed values required")
    rng = np.random.default_rng(seed)
    samples = values[rng.integers(0, len(values), (repetitions, len(values)))].mean(-1)
    return {"count": len(values), "mean": float(values.mean()), "min": float(values.min()),
            "max": float(values.max()), "bootstrap95_mean": [float(x) for x in np.quantile(samples, [.025, .975])],
            "bootstrap_seed": seed, "bootstrap_resamples": repetitions}
