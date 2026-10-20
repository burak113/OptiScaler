"""Read-only, origin-aware diagnostics of the frozen chronological fixtures.

Recorded radiance occupancy is a support PROXY, never a semantic silhouette or
converged truth. All masks, physical thresholds, exposures and denominators are
fixed from BASE before any intervention. No original array is overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from support_tracer import trace_stages

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("frozen_clip_loader", PACKAGE / "fixtures/clips/clip_loader.py")
loader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(loader)
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)
# Fixed before inspecting an intervention: native pre-remod luma, not display.
THRESHOLDS = (0.0, 0.0001, 0.001, 0.01)
WARP_VARIANTS = ("original_1x", "mv_0.5x", "mv_1.5x", "reversed_mv", "crop_extent_scale", "omit_crop_origin")


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def array_sha(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def luma(rgba):
    """Alpha is excluded from RGB arithmetic, and never modified/discarded in input."""
    return rgba[..., :3].astype(np.float32) @ LUMA


def moving_mask(motion, render_extent):
    mv = motion[..., :2].astype(np.float64) * np.asarray(render_extent, np.float64)
    speed = np.hypot(mv[..., 0], mv[..., 1]) > 12.0
    return sliding_window_view(np.pad(speed, 2, constant_values=False), (5, 5)).all(axis=(-1, -2))


def decode_normal(packed):
    """Native R10G10B10A2 oct normal, as FSRDPreprocessCommon.hlsli."""
    packed = np.asarray(packed, np.uint32)
    x = (packed & 1023).astype(np.float64) / 1023.0 * 2 - 1
    y = ((packed >> 10) & 1023).astype(np.float64) / 1023.0 * 2 - 1
    z = 1 - np.abs(x) - np.abs(y)
    fold = np.maximum(-z, 0)
    x += np.where(x >= 0, -fold, fold)
    y += np.where(y >= 0, -fold, fold)
    n = np.stack((x, y, z), axis=-1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def finite_stats(values):
    values = np.asarray(values, np.float64)
    values = values[np.isfinite(values)]
    if not len(values):
        return {"count": 0, "mean": None, "p50": None, "p90": None, "max": None}
    return {"count": int(values.size), "mean": float(values.mean()),
            "p50": float(np.median(values)), "p90": float(np.quantile(values, .9)),
            "max": float(values.max())}


def highpass3(image):
    x = np.pad(np.asarray(image, np.float64), ((1, 1), (1, 1)), mode="edge")
    smooth = sum(x[y:y+image.shape[0], z:z+image.shape[1]] for y in range(3) for z in range(3)) / 9
    return image - smooth


def variant_coordinates(a, t, variant):
    if t <= 0:
        raise ValueError("First observed frame has no previous fixture history")
    if variant == "original_1x":
        return loader.previous_coordinates(a, t)
    if variant not in WARP_VARIANTS:
        raise ValueError("Unknown diagnostic coordinate intervention")
    h, w = a["input_depth"].shape[1:]
    yy, xx = np.mgrid[:h, :w]
    origin_delta = a["crop_origin_render"][t].astype(float) - a["crop_origin_render"][t-1]
    motion = a["input_motion"][t, ..., :2].astype(np.float64)
    extent = a["render_extent"].astype(float)
    factor = {"mv_0.5x": .5, "mv_1.5x": 1.5, "reversed_mv": -1}.get(variant, 1)
    if variant == "crop_extent_scale":
        extent = np.array([w, h], float)
    if variant == "omit_crop_origin":
        origin_delta = np.zeros(2)
    qx = xx + origin_delta[0] + motion[..., 0] * extent[0] * factor
    qy = yy + origin_delta[1] + motion[..., 1] * extent[1] * factor
    valid = np.isfinite(qx) & np.isfinite(qy) & (qx >= 0) & (qx < w-1) & (qy >= 0) & (qy < h-1)
    return qx, qy, valid


def freeze_contract(a, fixture_id):
    n, h, w = a["input_depth"].shape
    if fixture_id == "bottle_track7":
        masks = np.stack([moving_mask(m, a["render_extent"]) for m in a["input_motion"]])
        definition = "BASE original motion speed >12 full-render pixels/frame, eroded by 2 pixels; bottle PLUS hand/arm, not object truth"
    else:
        mask = np.zeros((h, w), bool)
        mask[2:-2, 2:-2] = True
        masks = np.repeat(mask[None], n, axis=0)
        definition = "BASE fixed full crop interior excluding two-pixel border; NOT semantic foliage/facade truth"
    masks.setflags(write=False)
    exposure = {}
    for lobe in ("diffuse", "specular"):
        # One common BASE-derived exposure for all chronological frames/stages.
        y = luma(a["selected_rr_" + lobe])
        exposure[lobe] = float(.8 / max(float(np.quantile(y, .99)), 1e-6))
    return masks, {"definition": definition, "sha256": array_sha(masks),
                   "pixels_per_frame": masks.sum(axis=(1, 2)).astype(int).tolist(),
                   "total_pixels": int(masks.sum()), "thresholds_native_luma": list(THRESHOLDS),
                   "exposure": exposure, "exposure_definition": ".8 / p99 of all BASE selected-RR luma pixels across supplied sequence, fixed for every stage/frame",
                   "candidate_dependent_mask": False, "frame_looping": False}


def bit_difference(a, b, mask=None):
    if a.dtype != b.dtype or a.shape != b.shape:
        raise ValueError("Bit comparison requires equal dtype and extent")
    if mask is not None:
        a, b = a[mask], b[mask]
    word = np.dtype("<u2") if a.dtype.itemsize == 2 else np.dtype("<u4")
    aa, bb = np.ascontiguousarray(a).view(word), np.ascontiguousarray(b).view(word)
    return {"compared_words": int(aa.size), "different_words": int(np.count_nonzero(aa != bb)),
            "different_rgb_words": int(np.count_nonzero(aa[..., :3] != bb[..., :3])),
            "different_alpha_words": int(np.count_nonzero(aa[..., 3] != bb[..., 3]))}


def analyze_clip(name):
    a, meta = loader.load_clip(PACKAGE / "fixtures/clips" / (name + ".npz"), verify=True)
    original_hashes = {k: array_sha(v) for k, v in a.items()}
    for v in a.values():
        v.setflags(write=False)
    masks, contract = freeze_contract(a, name)
    normals = decode_normal(a["recovery_original_normal_roughness"])
    named_stages = {k: a[k] for k in ("input_diffuse", "input_specular", "raw_rr_diffuse", "raw_rr_specular", "selected_rr_diffuse", "selected_rr_specular")}
    traced = list(trace_stages(named_stages, a["input_motion"], a["crop_origin_render"],
                              a["render_extent"], a["frame_indices"], {k: .001 for k in named_stages},
                              comparison_breaks=(a["provider_controls"][:, 45] & 1) != 0))
    frames = []
    all_coordinate_rows = {k: {"normal": [], "depth": [], "radiance": [], "invalid": 0, "denominator": 0,
                              "pair_common_normal": [], "pair_common_depth": [], "pair_common_radiance": []} for k in WARP_VARIANTS}
    for t, frame in enumerate(a["frame_indices"]):
        mask = masks[t]
        row = {"frame": int(frame), "crop_origin_render": a["crop_origin_render"][t].tolist(),
               "fixed_pixels": int(mask.sum()), "lobes": {}, "coordinate_diagnostics": {},
               "first_history_unknown": t == 0}
        row["provider_reset_flag"] = bool(a["provider_controls"][t, 45] & 1)
        row["provider_frame_index"] = int(a["provider_controls"][t, 44])
        row["named_support_trace"] = {}
        for stage, trace in traced[t]["stages"].items():
            coverage = trace["transported_previous_support"]
            usable = mask & trace["history_valid"]
            row["named_support_trace"][stage] = {
                "threshold_native_luma": .001, "fixed_denominator": int(mask.sum()),
                "current_bright_pixels": int(np.count_nonzero(mask & trace["current_support"])),
                "current_nonfinite_unknown_pixels": int(np.count_nonzero(mask & ~trace["current_finite"])),
                "history_unknown_pixels": int(np.count_nonzero(mask & ~trace["history_valid"])),
                "transported_coverage_sum": float(coverage[usable].sum()),
                "mixed_bilinear_support_pixels": int(np.count_nonzero(usable & (coverage > 0) & (coverage < 1))),
                "previous_majority_current_dark_pixels": int(np.count_nonzero(usable & (coverage > .5) & ~trace["current_support"])),
                "operator": "threshold prior radiance, then bilinear transport binary coverage; distinct from thresholding bilinearly transported radiance"}
        for lobe in ("diffuse", "specular"):
            inp = a["input_" + lobe][t]
            raw = a["raw_rr_" + lobe][t]
            selected = a["selected_rr_" + lobe][t]
            lp = {"raw_vs_selected_full_crop": bit_difference(raw, selected),
                  "raw_vs_selected_fixed_mask": bit_difference(raw, selected, mask),
                  "input_hit_distance": finite_stats(inp[..., 3][mask]),
                  "hit_distance_zero_fraction": float(np.mean(inp[..., 3][mask] == 0)),
                  "stages": {}}
            for stage, rgba in (("input", inp), ("raw_rr", raw), ("selected_rr", selected)):
                y = luma(rgba)
                lp["stages"][stage] = {"luma": finite_stats(y[mask]),
                    "zero_rgb_fraction": float(np.mean(np.all(rgba[..., :3][mask] == 0, axis=-1))),
                    "support_fraction": {str(th): float(np.mean(y[mask] > th)) for th in THRESHOLDS},
                    "mean_abs_highpass3": float(np.mean(np.abs(highpass3(y)[mask])))}
            if t:
                qx, qy, valid = loader.previous_coordinates(a, t)
                previous, _ = loader.sample_previous(luma(a["input_" + lobe][t-1]), qx, qy)
                # These are thresholded radiance-support disagreements, not measured object shape.
                cur = luma(inp)
                comparison = mask & valid
                lp["transported_raw_support"] = {"fixed_denominator": int(mask.sum()),
                    "operator": "bilinear prior radiance then threshold; not equal to binary-support coverage transport in named_support_trace",
                    "observed_denominator": int(comparison.sum()), "unknown_pixels": int(np.count_nonzero(mask & ~valid)),
                    "thresholds": {str(th): {
                        "current_bright_previous_dark_pixels": int(np.count_nonzero(comparison & (cur > th) & (previous <= th))),
                        "previous_bright_current_dark_pixels": int(np.count_nonzero(comparison & (previous > th) & (cur <= th))),
                        "both_bright_pixels": int(np.count_nonzero(comparison & (previous > th) & (cur > th)))
                    } for th in THRESHOLDS}}
                ys, _ = loader.sample_previous(luma(a["selected_rr_" + lobe][t-1]), qx, qy)
                lp["temporal_difference_proxy"] = finite_stats(np.abs(luma(selected)[comparison] - ys[comparison]))
                lp["temporal_proxy_warning"] = "Contains actual object/light changes; not independently measured flicker/noise. Unknown pixels reported separately."
            row["lobes"][lobe] = lp
        if t:
            # Freeze the comparison intersection before observing either score.
            # The full fixed-mask scores below still penalize unknown support.
            pair_common = mask & variant_coordinates(a, t, "original_1x")[2] & variant_coordinates(a, t, "mv_1.5x")[2]
            row["fixed_common_1x_1p5x_pixels"] = int(pair_common.sum())
            for variant in WARP_VARIANTS:
                qx, qy, valid = variant_coordinates(a, t, variant)
                prev_n, _ = loader.sample_previous(normals[t-1], qx, qy)
                length = np.linalg.norm(prev_n, axis=-1)
                valid_n = valid & np.isfinite(length) & (length > 1e-8)
                dot = np.sum(normals[t] * prev_n, axis=-1) / np.maximum(length, 1e-8)
                normal_error = np.full(mask.shape, 180.0)
                normal_error[valid_n] = np.degrees(np.arccos(np.clip(dot[valid_n], -1, 1)))
                prev_d, _ = loader.sample_previous(a["input_depth"][t-1], qx, qy)
                dz = a["input_motion"][t, ..., 2].astype(np.float64)
                # G3 can encode history rejection in B. It is not geometric depth.
                depth_mask = mask & (np.abs(dz) < 65504) & np.isfinite(dz)
                expected = a["input_depth"][t].astype(np.float64) + dz
                depth_error = np.ones(mask.shape)
                good_depth = valid & (np.abs(expected) > 1e-6)
                depth_error[good_depth] = np.minimum(1., np.abs(prev_d[good_depth] - expected[good_depth]) / np.abs(expected[good_depth]))
                cur_y = luma(a["input_specular"][t])
                prev_y, _ = loader.sample_previous(luma(a["input_specular"][t-1]), qx, qy)
                # Symmetric [0,1] scalar proxy; a wrong coordinate may minimize it.
                radiance_error = np.ones(mask.shape)
                radiance_error[valid] = np.minimum(1., np.abs(prev_y[valid] - cur_y[valid]) / np.maximum(np.abs(prev_y[valid]) + np.abs(cur_y[valid]), 1e-6))
                row["coordinate_diagnostics"][variant] = {
                    "fixed_denominator": int(mask.sum()), "unsupported_pixels": int(np.count_nonzero(mask & ~valid)),
                    "normal_angle_deg_invalid_penalty_180": finite_stats(normal_error[mask]),
                    "relative_depth_error_clipped_1_invalid_penalty_1": finite_stats(depth_error[depth_mask]),
                    "g3_depth_sentinel_excluded": int(np.count_nonzero(mask & ~depth_mask)),
                    "specular_luma_symmetric_error_invalid_penalty_1": finite_stats(radiance_error[mask])}
                agg = all_coordinate_rows[variant]
                agg["normal"].append(normal_error[mask]); agg["depth"].append(depth_error[depth_mask]); agg["radiance"].append(radiance_error[mask])
                agg["invalid"] += int(np.count_nonzero(mask & ~valid)); agg["denominator"] += int(mask.sum())
                if variant in ("original_1x", "mv_1.5x"):
                    agg["pair_common_normal"].append(normal_error[pair_common])
                    agg["pair_common_depth"].append(depth_error[pair_common & depth_mask])
                    agg["pair_common_radiance"].append(radiance_error[pair_common])
        frames.append(row)
    coordinates = {}
    for variant, item in all_coordinate_rows.items():
        coordinates[variant] = {"fixed_denominator": item["denominator"], "unsupported_pixels": item["invalid"],
            "normal_angle_deg": finite_stats(np.concatenate(item["normal"])),
            "relative_depth_error": finite_stats(np.concatenate(item["depth"])),
            "specular_luma_symmetric_error": finite_stats(np.concatenate(item["radiance"]))}
        if item["pair_common_normal"]:
            coordinates[variant]["fixed_common_1x_1p5x"] = {
                "normal_angle_deg": finite_stats(np.concatenate(item["pair_common_normal"])),
                "relative_depth_error": finite_stats(np.concatenate(item["pair_common_depth"])),
                "specular_luma_symmetric_error": finite_stats(np.concatenate(item["pair_common_radiance"]))}
    totals = {lobe: {"full_crop": bit_difference(a["raw_rr_"+lobe], a["selected_rr_"+lobe]),
                      "fixed_mask": bit_difference(a["raw_rr_"+lobe], a["selected_rr_"+lobe], masks)} for lobe in ("diffuse", "specular")}
    assert original_hashes == {k: array_sha(v) for k, v in a.items()}, "Evidence was modified"
    result = {"fixture": name, "scope": "recorded GPU tensors analyzed on CPU; no AMD RR execution",
        "capture_uuid": meta["source_capture_uuid"], "source_manifest_sha256": meta["source_capture_manifest_sha256"],
        "archive_sha256": meta["archive"]["sha256"], "render_extent": a["render_extent"].tolist(),
        "crop_extent": meta["crop_extent"], "frame_indices": a["frame_indices"].tolist(),
        "crop_origins_render": a["crop_origin_render"].tolist(), "contract": contract,
        "array_inventory": {k: {"dtype": v.dtype.str, "shape": list(v.shape), "sha256": original_hashes[k]} for k,v in a.items()},
        "raw_selected_bit_comparison": totals, "coordinate_aggregate": coordinates, "frames": frames,
        "controls_word_counts": [int(a["provider_controls"].shape[1])] * len(frames),
        "g3_sentinel_pixels_full_clip": int(np.count_nonzero(np.abs(a["input_motion"][..., 2].astype(float)) >= 65504)),
        "limits": ["Motion-derived mask includes hand/arm; there is no independently labeled bottle silhouette.",
          "Radiance support disagreement includes stochastic missing samples and changing reflectance/illumination.",
          "Normal/depth residual is a geometric proxy with mixed coverage and true normal rotation; it is not oracle correspondence error.",
          "Original and prepared normal guides are separate. Depth-B may contain G3 rejection sentinels.",
          "Unknown crop/startup history is not clamped or looped. Recorded RR contains earlier unobserved context.",
          "Final composition/remod, upstream exposure, provider internal state and exact settings are not fully observed.",
          "Pixels and neighboring frames are not independent captures; no real-data confidence interval is claimed."],
        "input_arrays_unmodified": True}
    return result, masks


def run(out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    clips, masks = {}, {}
    for name in ("bottle_track7", "foliage23", "facade16"):
        clips[name], masks[name] = analyze_clip(name)
    np.savez_compressed(out / "fixed_base_masks.npz", **masks)
    result = {"schema": "astra.job06.recorded_support.v1", "candidate": "diagnostic abstention; image identity",
        "gpu_executed": False, "ground_truth_available": False,
        "warp_variants_are_diagnostics_not_fixes": True, "clips": clips,
        "fixed_masks_archive_sha256": sha_file(out / "fixed_base_masks.npz"),
        "real_bottle_shape_metrics": {"silhouette_lag": None, "true_shape_iou": None, "true_disocclusion_leakage": None},
        "shape_metric_unavailability_reason": "No independently measured object silhouette, same-pose converged light or object trajectory; speed mask contains arm/hand."}
    path = out / "recorded_analysis.json"
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=HERE / "evidence")
    result = run(ap.parse_args().out)
    bottle = result["clips"]["bottle_track7"]
    print(json.dumps({"recorded_bottle": bottle["raw_selected_bit_comparison"],
                      "fixed_mask": bottle["contract"], "geometry": bottle["coordinate_aggregate"]}, indent=2, allow_nan=False))
