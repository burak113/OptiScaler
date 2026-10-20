"""Read-only captured-guide diagnostics with immutable BASE-derived support.

This does not execute RR, infer semantic labels, or provide converged truth.
Run --freeze-masks before candidate evaluation; later runs verify those masks.
Only NumPy and the frozen clip loader are required.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent.parent
BASE_COMMIT = "5d7839a930106cf8fe1ba8dbbc6750509e7f26a8"
CLIPS = ("foliage23", "facade16", "bottle_track7")
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
NORMAL_COS_15 = float(np.cos(np.deg2rad(15.0)))
MASK_POLICY = {
    "version": 1,
    "base_commit": BASE_COMMIT,
    "labels": "Fixed clip regions, not semantic foliage/bottle/facade labels",
    "core": "Two-pixel image border excluded; original finite positive depth",
    "available_pair": "core AND four previous bilinear taps inside previous crop; t0 false",
    "depth_edge": "core AND any 4-connected original depth jump >2% of current magnitude",
    "normal_edge": "core AND any 4-connected original normal dot <cos(15 degrees)",
    "high_motion": "original full-render motion magnitude >12 pixels, square erosion radius2",
    "stable_guide_pair": "available_pair; all four previous original normal dots >.99; all depths within2% of current depth+MV.B; identical categories",
    "sampling": "continuous NumPy bilinear; explicitly not a D3D sampler-parity claim",
    "first_previous_frame": "absent; no sequence looping or invented history",
}


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha_array(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def load_frozen_module():
    path = PACKAGE / "fixtures/clips/clip_loader.py"
    spec = importlib.util.spec_from_file_location("frozen_clip_loader_job07", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LOADER = load_frozen_module()


def decode_packed(words):
    """Source-matched oct decoding; leave the original uint32 input untouched."""
    words = np.asarray(words, dtype=np.uint32)
    uv = np.stack((words & 1023, (words >> 10) & 1023), axis=-1).astype(np.float32) / np.float32(1023)
    xy = np.float32(2) * (uv - np.float32(.5))
    n = np.concatenate((xy, (np.float32(1) - np.abs(xy).sum(axis=-1))[..., None]), axis=-1)
    t = np.maximum(-n[..., 2], np.float32(0))
    n[..., :2] += np.where(n[..., :2] >= 0, -t[..., None], t[..., None])
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    roughness = ((words >> 20) & 1023).astype(np.float32) / np.float32(1023)
    categories = (words >> 30).astype(np.uint8)
    return n, roughness, categories


def erode(mask, radius):
    padded = np.pad(mask, ((0, 0), (radius, radius), (radius, radius)), constant_values=False)
    result = np.ones_like(mask)
    h, w = mask.shape[-2:]
    for dy in range(2 * radius + 1):
        for dx in range(2 * radius + 1):
            result &= padded[:, dy:dy+h, dx:dx+w]
    return result


def build_masks(a):
    depth = a["input_depth"]
    frames, h, w = depth.shape
    core = np.isfinite(depth) & (depth > 0)
    core[:, :2] = core[:, -2:] = False
    core[:, :, :2] = core[:, :, -2:] = False
    normals, _, material = decode_packed(a["recovery_original_normal_roughness"])
    normal_edge = np.zeros_like(core)
    depth_edge = np.zeros_like(core)
    for axis in (1, 2):
        for offset in (-1, 1):
            other_depth = np.roll(depth, offset, axis=axis)
            other_normal = np.roll(normals, offset, axis=axis)
            depth_edge |= np.abs(other_depth-depth) > np.float32(.02)*np.maximum(np.abs(depth), np.float32(1e-6))
            normal_edge |= np.sum(other_normal*normals, axis=-1) < NORMAL_COS_15
    normal_edge &= core
    depth_edge &= core
    available = np.zeros_like(core)
    stable = np.zeros_like(core)
    for t in range(1, frames):
        qx, qy, valid = LOADER.previous_coordinates(a, t)
        available[t] = core[t] & valid
        # Mask out invalid locations before integer conversion; no wrapped history.
        x = np.floor(np.where(valid, qx, 0)).astype(np.int64)
        y = np.floor(np.where(valid, qy, 0)).astype(np.int64)
        predicted_depth = depth[t].astype(np.float64) + a["input_motion"][t, ..., 2].astype(np.float64)
        compatible = valid & np.isfinite(predicted_depth) & (predicted_depth > 0)
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            ndot = np.sum(normals[t] * normals[t-1, y+dy, x+dx], axis=-1)
            prev_depth = depth[t-1, y+dy, x+dx]
            compatible &= (ndot > .99) & (material[t] == material[t-1, y+dy, x+dx])
            compatible &= np.abs(prev_depth-predicted_depth) <= .02*np.maximum(np.abs(predicted_depth), 1e-6)
        stable[t] = compatible & core[t]
    speed = np.linalg.norm(a["input_motion"][..., :2].astype(np.float64) * a["render_extent"], axis=-1)
    return {"core": core, "available_pair": available, "depth_edge": depth_edge,
            "normal_edge": normal_edge, "high_motion": erode(speed > 12, 2) & core,
            "stable_guide_pair": stable}


def freeze_or_check_masks(name, a, meta, output_dir, create=False):
    mask_dir = output_dir / "base_masks"
    mask_dir.mkdir(parents=True, exist_ok=True)
    masks = build_masks(a)
    path = mask_dir / (name + ".npz")
    info_path = mask_dir / (name + ".json")
    info = {"policy": MASK_POLICY, "fixture": name,
            "source_archive_sha256": meta["archive"]["sha256"],
            "arrays": {k: {"count": int(v.sum()), "shape": list(v.shape), "dtype": str(v.dtype),
                           "per_frame_count": v.sum(axis=(1, 2)).tolist(), "sha256": sha_array(v)} for k, v in masks.items()}}
    if not path.exists():
        if not create:
            raise RuntimeError("Freeze original masks before candidate evaluation: --freeze-masks")
        np.savez_compressed(path, **masks)
        info_path.write_text(json.dumps(info, indent=2, allow_nan=False) + "\n")
    else:
        with np.load(path, allow_pickle=False) as z:
            assert set(z.files) == set(masks), name
            for k, v in masks.items():
                assert np.array_equal(z[k], v), (name, k, "immutable BASE mask changed")
        assert json.loads(info_path.read_text()) == info, "BASE mask policy/provenance changed"
    return masks, info


def percentiles(values):
    values = np.asarray(values)
    values = values[np.isfinite(values)]
    if not values.size:
        return {"count": 0, "mean": None, "p50": None, "p90": None, "p99": None, "max": None}
    p50, p90, p99 = np.percentile(values, [50, 90, 99])
    return {"count": int(values.size), "mean": float(values.mean()),
            "p50": float(p50), "p90": float(p90), "p99": float(p99), "max": float(values.max())}


def corr(x, y):
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask].astype(np.float64), y[mask].astype(np.float64)
    if x.size < 3 or np.std(x) < 1e-12 or np.std(y) < 1e-12:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def luma_rgba(a):
    return np.sum(a[..., :3].astype(np.float32) * LUMA, axis=-1, dtype=np.float32)


def analyze_clip(name, a, meta, masks, use_candidate=False):
    frames, h, w = a["input_depth"].shape
    original = a["recovery_original_normal_roughness"]
    prepared = a["input_normal_roughness"]
    n, roughness, mat = decode_packed(original)
    pn, pr, pm = decode_packed(prepared)
    pair = masks["available_pair"]
    angle = np.full((frames, h, w), np.nan)
    for t in range(1, frames):
        qx, qy, valid = LOADER.previous_coordinates(a, t)
        # Compare against nearest original sample so no averaged normal becomes a label.
        x = np.rint(np.where(valid, qx, 0)).astype(np.int64)
        y = np.rint(np.where(valid, qy, 0)).astype(np.int64)
        dot = np.sum(n[t] * n[t-1, y, x], axis=-1)
        angle[t] = np.where(valid, np.rad2deg(np.arccos(np.clip(dot, -1, 1))), np.nan)
    source_array_hashes = {k: sha_array(v) for k, v in a.items()}
    result = {
        "fixture": name, "capture_uuid": meta["source_capture_uuid"],
        "source_archive_sha256": meta["archive"]["sha256"],
        "source_manifest_sha256": meta["source_capture_manifest_sha256"],
        "stage": "Captured native inputs + recorded raw/selected RR; CPU diagnostics only",
        "ground_truth": False, "semantic_labels": False, "gpu_executed": False,
        "frame_indices": a["frame_indices"].tolist(), "extent_wh": [w, h],
        "render_extent_wh": a["render_extent"].tolist(),
        "crop_origins_xy": a["crop_origin_render"].tolist(),
        "timing": "Frame ordinals only. recording_qpc/frame durations absent; no Hz or per-second claims.",
        "partial_history": True, "stored_rr_has_pre_fixture_history": True,
        "source_formats": {k: {"dtype": str(v.dtype), "shape": list(v.shape)} for k, v in a.items()},
        "unsupported_history": {"first_frame_pixels": h*w,
            "later_outside_previous_crop_pixels": int(sum(h*w-int(LOADER.previous_coordinates(a,t)[2].sum()) for t in range(1,frames))),
            "available_pair_pixels": int(pair.sum()), "available_core_pair_fraction": float(pair.sum()/masks["core"][1:].sum())},
        "guide_words": {"total_pixels": int(original.size),
            "normal20_changed": int(np.count_nonzero((original & 0xfffff) != (prepared & 0xfffff))),
            "roughness10_changed": int(np.count_nonzero(((original >> 20) & 1023) != ((prepared >> 20) & 1023))),
            "category2_changed": int(np.count_nonzero(mat != pm)),
            "original_categories_in_this_tile": np.unique(mat).tolist(),
            "prepared_categories_in_this_tile": np.unique(pm).tolist(),
            "roughness_abs_delta": percentiles(np.abs(pr-roughness)),
            "original_depth": percentiles(a["input_depth"])},
        "original_normal_temporal_angle_degrees": percentiles(angle[pair]),
        "fixed_masks": {k: {"count": int(v.sum()), "sha256": sha_array(v)} for k,v in masks.items()},
        "signals": {},
    }
    for role in ("input_diffuse", "input_specular", "raw_rr_diffuse", "raw_rr_specular", "selected_rr_diffuse", "selected_rr_specular"):
        lum = luma_rgba(a[role])
        core = masks["core"]
        values = lum[core].astype(np.float64)
        mean = float(values.mean())
        positive = np.maximum(values, 0)
        count_top = max(1, int(np.ceil(positive.size * .01)))
        tail_fraction = float(np.partition(positive, -count_top)[-count_top:].sum()/max(positive.sum(), 1e-30))
        delta = np.full(lum.shape, np.nan)
        for t in range(1, frames):
            qx, qy, _ = LOADER.previous_coordinates(a, t)
            warped, _ = LOADER.sample_previous(lum[t-1], qx, qy)
            delta[t] = lum[t].astype(np.float64) - warped
        scale = max(abs(mean), 1e-8)
        abs_delta = np.abs(delta)/scale
        # Pure frame-to-frame/spatial observation metrics, not isolated noise estimates.
        hp = lum.astype(np.float64) - (np.roll(lum,1,axis=1)+np.roll(lum,-1,axis=1)+np.roll(lum,1,axis=2)+np.roll(lum,-1,axis=2))/4
        bins = {}
        for lo, hi in ((0,1),(1,5),(5,15),(15,181)):
            fixed = pair & (angle >= lo) & (angle < hi)
            bins[f"normal_angle_{lo}_{hi}"] = percentiles(abs_delta[fixed])
        result["signals"][role] = {
            "unit": "captured linear lobe units (not display RGB); input alpha is unmodified hit distance",
            "luma": percentiles(values), "exact_zero_rgb_fraction": float(np.mean(np.all(a[role][core, :3] == 0,axis=-1))),
            "negative_rgb_fraction": float(np.mean(np.any(a[role][core, :3] < 0,axis=-1))),
            "top_one_percent_positive_luma_energy_fraction": tail_fraction,
            "base_mean_normalizer": mean,
            "spatial_highpass_rms_over_base_mean_proxy": float(np.sqrt(np.mean(hp[core]**2))/scale),
            "motion_compensated_abs_delta_over_base_mean": percentiles(abs_delta[pair]),
            "stable_guide_abs_delta_over_base_mean": percentiles(abs_delta[masks["stable_guide_pair"]]),
            "angle_abs_delta_pearson_descriptive": corr(angle[pair], abs_delta[pair]),
            "crop_index_lag_one_delta_pearson_descriptive": corr(delta[1:-1][pair[1:-1]&pair[2:]],delta[2:][pair[1:-1]&pair[2:]]),
            "lag_one_correlation_scope": "Eulerian local crop indices, not advected material points; moving crop changes their world correspondence. Not an estimator of Monte Carlo noise correlation.",
            "angle_bins": bins,
            "interpretation": "Variation mixes lighting, stochastic samples, reprojection, motion, and geometry; no causal noise/flicker attribution or converged truth. Clamped depth is observed; absent raw validity prevents physical correspondence certification.",
        }
    result["raw_selected_equal"] = {lobe: bool(np.array_equal(a["raw_rr_"+lobe].view(np.uint16),a["selected_rr_"+lobe].view(np.uint16))) for lobe in ("diffuse","specular")}
    if use_candidate:
        sys.path.insert(0, str(HERE / "src"))
        from foliage_guides import GuideFrame, observe_guides
        previous = None
        sidecars = []
        for t in range(frames):
            frame = GuideFrame(packed_normal_roughness=original[t], depth=a["input_depth"][t],
                motion=a["input_motion"][t], frame_id=int(a["frame_indices"][t]),
                crop_origin=tuple(int(v) for v in a["crop_origin_render"][t]),
                render_extent=tuple(int(v) for v in a["render_extent"]),
                depth_is_positive_linear=True, reset=(t==0))
            sidecars.append(observe_guides(frame, previous=previous, enabled=True))
            previous = frame
        # Access is finalized alongside the candidate API; outputs stay separate from source tensors.
        candidate_result = {}
        for attr in ("angular_dispersion", "relative_depth_span", "temporal_innovation", "temporal_supported", "experimental_history_multiplier"):
            value = np.stack([getattr(o,attr) for o in sidecars])
            if value.dtype == bool:
                candidate_result[attr] = {"core_fraction": float(value[masks["core"]].mean()),
                                          "pair_fraction": float(value[pair].mean()),
                                          "outside_available_pair_true_count": int(np.count_nonzero(value & ~pair & masks["core"]))}
            else:
                candidate_result[attr] = percentiles(value[pair])
        supported = np.stack([o.temporal_supported for o in sidecars]) & pair
        candidate_result["temporal_value_sentinels"] = "Unsupported innovation is initialized to0 and multiplier to1. These are identity/sentinel values, not measured agreement. Fixed-pair primary statistics retain every BASE pixel."
        candidate_result["conditional_comparable_observations"] = {
            "scope": "Descriptive diagnostic distribution only; not an output-quality denominator or candidate-derived foliage mask",
            "count": int(supported.sum()),
            "base_pair_count": int(pair.sum()),
            "temporal_innovation": percentiles(np.stack([o.temporal_innovation for o in sidecars])[supported]),
            "experimental_history_multiplier": percentiles(np.stack([o.experimental_history_multiplier for o in sidecars])[supported]),
        }
        candidate_result["stage"] = "CPU observable diagnostic sidecar; no lighting/normal/depth/material modification"
        candidate_result["captured_output_quality_improvement"] = None
        result["candidate_diagnostic"] = candidate_result
    assert source_array_hashes == {k:sha_array(v) for k,v in a.items()}, "Captured source/alpha words modified"
    result["all_source_arrays_bitwise_unchanged"] = True
    result["source_array_sha256"] = source_array_hashes
    return result


def inventory_other_fixtures():
    entries = []
    for directory in ("portable/anchor", "portable/colour", "fixtures/glass"):
        files = sorted((PACKAGE/directory).rglob("*.npz"))
        for path in files:
            with np.load(path, allow_pickle=False) as z:
                entries.append({"path":path.relative_to(PACKAGE).as_posix(), "sha256":sha_file(path),
                    "bytes":path.stat().st_size,
                    "arrays":{k:{"shape":list(z[k].shape),"dtype":str(z[k].dtype)} for k in z.files}})
    return entries


def glass_geometry_control(output_dir, create_masks=False, use_candidate=False):
    """Use the unwarped provider-guide rectangle, never the aligned glass mask."""
    path = PACKAGE/"fixtures/glass/glass_crop.npz"
    meta = json.loads(path.with_name("manifest.json").read_text())
    assert sha_file(path) == meta["data_sha256"], "glass archive mismatch"
    with np.load(path, allow_pickle=False) as z:
        source = {k:z[k] for k in z.files}
    before = {k:sha_array(v) for k,v in source.items()}
    crop = meta["fixture_crop_in_original_roi_xyxy"]
    origin = np.array(meta["original_roi"]["origin"]) + np.array(crop[:2])
    frames = len(meta["frames"])
    # This alias is only the BASE guide input expected by the common mask code.
    # In glass it is recorded provider input, not pre-Flat-Albedo original truth.
    a = {"input_depth":source["original_depth_f32"],
         "input_motion":source["original_motion_rgba_f16"],
         "recovery_original_normal_roughness":source["original_normal_roughness_u32"],
         "render_extent":np.array(meta["render_extent"],dtype=np.int32),
         "crop_origin_render":np.broadcast_to(origin,(frames,2)).copy()}
    mask_meta = {"archive":{"sha256":meta["data_sha256"]}}
    masks,info = freeze_or_check_masks("glass_unwarped_provider",a,mask_meta,output_dir,create=create_masks)
    report = {
        "stage":"CPU diagnostic on unwarped captured provider geometry only",
        "normal_source_authority":"original_normal_roughness_u32 refers to frames/*/input_normal_roughness; provider/prepared guide, not recovery_original pre-Flat guide",
        "source_archive_sha256":meta["data_sha256"], "frames":meta["frames"],
        "crop_extent_wh":[crop[2]-crop[0],crop[3]-crop[1]],"crop_origin_xy":origin.tolist(),
        "render_extent_wh":meta["render_extent"],"fixed_masks":info["arrays"],
        "aligned_glass_mask_used_for_unwarped_geometry":False,
        "aligned_rgb_paired_with_unwarped_guide_pixels":False,
        "physical_input_D_S_and_hit_distance_alpha_present":False,
        "image_quality_change":None,"gpu_executed":False,
        "interpretation":"Independent geometry/identity control only. Camera-aligned RGB/common_mask cannot be indexed onto these unwarped guide pixels. No glass causal or active RR-quality claim."
    }
    if use_candidate:
        sys.path.insert(0,str(HERE/"src"))
        from foliage_guides import GuideFrame, observe_guides
        previous = None
        observations = []
        for t in range(frames):
            frame = GuideFrame(a["recovery_original_normal_roughness"][t],a["input_depth"][t],a["input_motion"][t],
                               int(meta["frames"][t]),tuple(origin),tuple(meta["render_extent"]),True,t==0)
            observations.append(observe_guides(frame,previous,enabled=True))
            previous = frame
        supported = np.stack([o.temporal_supported for o in observations])
        multiplier = np.stack([o.experimental_history_multiplier for o in observations])
        innovation = np.stack([o.temporal_innovation for o in observations])
        pair = masks["available_pair"]
        report["diagnostic"] = {
            "base_pair_pixels":int(pair.sum()), "comparable_pair_pixels":int(np.count_nonzero(pair&supported)),
            "comparable_pair_fraction":float(supported[pair].mean()),
            "conditional_supported_innovation":percentiles(innovation[pair&supported]),
            "fixed_pair_multiplier":percentiles(multiplier[pair]),
            "outside_available_pair_support_count":int(np.count_nonzero(supported&~pair&masks["core"])),
            "unsupported_identity_exact":bool(np.all(multiplier[~supported]==1)),
            "sentinel_semantics":"innovation0 / multiplier1 when unsupported are not measured normal agreement"
        }
    assert before == {k:sha_array(v) for k,v in source.items()}, "glass original arrays changed"
    report["all_source_arrays_bitwise_unchanged"] = True
    report["source_array_sha256"] = before
    print("glass_unwarped_provider", "immutable BASE support", {k:v["count"] for k,v in info["arrays"].items()})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-masks", action="store_true")
    parser.add_argument("--with-candidate", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=HERE/"evidence")
    parser.add_argument("--executor", default="CPU / NumPy; see execution receipt")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    clips = []
    for name in CLIPS:
        arrays, meta = LOADER.load_clip(PACKAGE/"fixtures/clips"/(name+".npz"))
        masks, info = freeze_or_check_masks(name, arrays, meta, args.output_dir, create=args.freeze_masks)
        if not args.freeze_masks:
            clips.append(analyze_clip(name, arrays, meta, masks, use_candidate=args.with_candidate))
        print(name, "immutable BASE support", {k:v["count"] for k,v in info["arrays"].items()})
    glass = glass_geometry_control(args.output_dir,create_masks=args.freeze_masks,use_candidate=args.with_candidate and not args.freeze_masks)
    if not args.freeze_masks:
        report = {"schema":"job07.captured_diagnostics.v1", "base_commit":BASE_COMMIT,
            "executor":args.executor, "mask_policy":MASK_POLICY, "gpu_executed":False,
            "clips":clips, "glass_geometry_control":glass, "other_fixture_inventory":inventory_other_fixtures(),
            "missing_observables":["sample-level coverage/layer identities", "unclamped raw view depth and validity byte", "albedo/material source witnesses", "frame timestamps", "same-pose converged reference", "per-layer motion", "unmodified original pre-G3 motion for sentinel comparison", "final game display/RR rerun"]}
        filename = "captured_with_candidate.json" if args.with_candidate else "captured_baseline.json"
        (args.output_dir/filename).write_text(json.dumps(report, indent=2,allow_nan=False)+"\n")
        print("Wrote", filename)


if __name__ == "__main__":
    main()
