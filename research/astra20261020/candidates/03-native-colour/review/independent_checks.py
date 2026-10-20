"""Independent analytic scenes, bit oracles, and metrics for native colour.

This code does not import or reuse the candidate's math. Denominators and masks
are constructed from the untouched BASE inputs before any candidate is invoked.
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parent
PACKAGE = CANDIDATE.parents[1]
sys.path.insert(0, str(CANDIDATE))
sys.path.insert(0, str(PACKAGE / "portable" / "colour"))

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)


def luma(rgb):
    return np.asarray(rgb, np.float64)[..., :3] @ LUMA


def chroma(rgb):
    rgb = np.asarray(rgb, np.float64)[..., :3]
    return rgb - luma(rgb)[..., None]


def at_luma(rgb, value=0.3):
    rgb = np.asarray(rgb, np.float64)
    return rgb * (value / luma(rgb))[..., None]


def words(rgba):
    value = np.asarray(rgba)
    if value.dtype == np.float16:
        return value.view(np.uint16)
    if value.dtype == np.float32:
        return value.view(np.uint32)
    raise TypeError("Word oracle only covers native float16/float32 arrays")


def unchanged(a, b, mask=None):
    aw, bw = words(a), words(b)
    if mask is not None:
        aw, bw = aw[mask], bw[mask]
    return bool(np.array_equal(aw, bw))


def original_eligibility(raw, selected, authority, active_extent=None):
    h, w = raw.shape[:2]
    mask = np.all(words(raw) == words(selected), axis=-1) & authority
    if active_extent is not None:
        aw, ah = active_extent
        active = np.zeros((h, w), bool)
        active[:ah, :aw] = True
        mask &= active
    return mask


def assert_word_contract(output, raw, selected, authority, *, active_extent=None, off=False):
    assert output.dtype == selected.dtype, "native output dtype changed"
    assert output.shape == selected.shape, "native output extent changed"
    assert np.array_equal(words(output)[..., 3], words(selected)[..., 3]), "alpha words changed"
    eligible = original_eligibility(raw, selected, authority, active_extent)
    assert unchanged(output, selected, ~eligible), "protected RGBA words changed"
    if off:
        assert unchanged(output, selected), "OFF output changed"


def rgba(rgb, alpha=0, dtype=np.float16):
    rgb = np.asarray(rgb)
    out = np.empty(rgb.shape[:-1] + (4,), dtype=dtype)
    out[..., :3] = rgb
    out[..., 3] = alpha
    return out


def normal_oct(normal):
    normal = np.asarray(normal, np.float32)
    unit_l1 = normal / np.maximum(np.abs(normal).sum(-1, keepdims=True), 1e-20)
    uv = unit_l1[..., :2]
    folded = (1 - np.abs(uv[..., ::-1])) * np.where(uv >= 0, 1, -1)
    return (np.where((unit_l1[..., 2] < 0)[..., None], folded, uv) * 0.5 + 0.5).astype(np.float32)


def basic_scene(h=17, w=23, dtype=np.float16):
    source_rgb = np.broadcast_to(at_luma([.40, .30, .26]), (h, w, 3))
    raw_rgb = np.broadcast_to(at_luma([.28, .36, .31]), (h, w, 3))
    source, raw = rgba(source_rgb, dtype=dtype), rgba(raw_rgb, dtype=dtype)
    depth = np.full((h, w), 10, np.float32)
    normals = np.zeros((h, w, 3), np.float32)
    normals[..., 2] = 1
    roughness = np.full((h, w), .35, np.float32)
    authority = np.ones((h, w), bool)
    return source, raw, raw.copy(), depth, normals, roughness, authority


def call_model(model, scene, **kwargs):
    source, raw, selected, depth, normals, roughness, authority = scene
    return model.frame(source, raw, selected, depth, normals,
                       roughness=roughness, authority=authority, **kwargs)


def local_half_envelope(raw):
    value = np.asarray(raw[..., :3], np.float16)
    up = np.nextafter(value, np.float16(np.inf)).astype(np.float64)
    down = np.nextafter(value, np.float16(-np.inf)).astype(np.float64)
    step = np.maximum(up - value.astype(np.float64), value.astype(np.float64) - down)
    # Two independently stored half outputs may differ by one adjacent step each.
    return 2 * step.sum(-1) / np.maximum(luma(raw), 1e-20)


def colour_pair(name, level):
    pair = ([[.8, .08, .12], [.08, .12, .8]] if name == "red_blue"
            else [[.08, .8, .12], [.6, .06, .5]])
    return at_luma(pair, level)


def edge_scene(pair="red_blue", kind="normal", phase=0, angle=0, level=.3,
               thin_width=None, movement=0, h=40, w=64):
    yy, xx = np.indices((h, w), dtype=np.float64)
    theta = np.deg2rad(angle)
    distance = ((xx - w / 2) * np.cos(theta) + (yy - h / 2) * np.sin(theta)
                - phase - movement)
    left = distance < 0 if thin_width is None else np.abs(distance) < thin_width / 2
    a, b = colour_pair(pair, level)
    truth = np.where(left[..., None], a, b)
    raw_rgb = truth.copy()
    biased = at_luma(a * np.exp([.12, -.08, .08]), level)
    raw_rgb[left] = biased
    source, raw = rgba(truth), rgba(raw_rgb)
    selected = raw.copy()
    # Exclude an immutable protected stripe and an explicit-authority stripe.
    protected = (xx == 3)
    words(selected)[protected, 3] ^= np.uint16(1)
    authority = xx != 4
    depth = np.full((h, w), 10, np.float32)
    normals = np.zeros((h, w, 3), np.float32)
    normals[..., 2] = 1
    roughness = np.full((h, w), .2, np.float32)
    if kind == "depth":
        depth[~left] = 20
    elif kind == "normal":
        normals[~left] = [.8, 0, .6]
    elif kind == "roughness":
        roughness[~left] = .8
    elif kind != "same_guides":
        raise ValueError(kind)
    eligible = original_eligibility(raw, selected, authority)
    inner = (xx >= 8) & (xx < w - 8) & (yy >= 8) & (yy < h - 8)
    if thin_width is None:
        band = (~left) & (distance < 4) & inner & eligible
        correction_mask = left & (distance < -6) & inner & eligible
    else:
        band = (~left) & (np.abs(distance) < thin_width / 2 + 4) & inner & eligible
        correction_mask = left & inner & eligible
    meta = {"truth": truth, "left": left, "band": band,
            "correction_mask": correction_mask, "eligible": eligible,
            "base_denominator": luma(raw), "half_envelope": local_half_envelope(raw)}
    return (source, raw, selected, depth, normals, roughness, authority), meta


def edge_metrics(output, scene, meta):
    _, raw, selected, _, _, _, authority = scene
    assert_word_contract(output, raw, selected, authority)
    band, mask = meta["band"], meta["correction_mask"]
    delta = np.abs(np.asarray(output[..., :3], np.float64) - raw[..., :3]).sum(-1)
    delta /= meta["base_denominator"]
    original_error = np.linalg.norm(chroma(raw) - chroma(meta["truth"]), axis=-1)
    candidate_error = np.linalg.norm(chroma(output) - chroma(meta["truth"]), axis=-1)
    baseline = float(original_error[mask].mean()) if mask.any() else 0.0
    correction = (1 - float(candidate_error[mask].mean()) / baseline) if baseline > 1e-12 else None
    return {
        "unchanged_side_max_contamination": float(delta[band].max()) if band.any() else None,
        "unchanged_side_mean_contamination": float(delta[band].mean()) if band.any() else None,
        "max_contamination_above_storage_envelope": float((delta - meta["half_envelope"])[band].max()) if band.any() else None,
        "interior_correction_fraction": correction,
        "eligible_fraction": float(meta["eligible"].mean()),
        "luma_relative_error_max": float((np.abs(luma(output) - luma(selected)) / meta["base_denominator"]).max()),
        "boundary_pixels": int(band.sum()),
        "correction_pixels": int(mask.sum()),
    }
