"""Inventory original fixtures and reproduce fixed-support recorded controls.

There is no captured uncertainty sidecar. The honest candidate result is local
identity. Alignment/proxy statistics cannot identify a native noise covariance.
All new quality denominators below are fixed from the unchanged selected BASE.
The package's own candidate-normalized CV is retained only as legacy calibration.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import zlib

import numpy as np

CANDIDATE = Path(__file__).resolve().parents[1]
PACKAGE = CANDIDATE.parents[1]
sys.path.insert(0, str(CANDIDATE/"src"))
from glass_candidate import CandidateConfig, shrink_specular


def import_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


glass = import_file("frozen_glass_fixture", PACKAGE/"fixtures/glass/glass_fixture.py")
clips = import_file("frozen_clip_loader", PACKAGE/"fixtures/clips/clip_loader.py")
LUMA = glass.LUMA


def sha_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_array(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def array_description(array):
    result = {"shape": list(array.shape), "dtype": array.dtype.str,
              "bytes": int(array.nbytes), "raw_sha256": sha_array(array)}
    if array.dtype.kind == "f":
        result["nonfinite_components"] = int(np.count_nonzero(~np.isfinite(array)))
    return result


def erode(mask, radius=2):
    h, w = mask.shape
    padded = np.pad(mask, radius, constant_values=False)
    result = np.ones_like(mask)
    for dy in range(2*radius+1):
        for dx in range(2*radius+1):
            result &= padded[dy:dy+h, dx:dx+w]
    return result


def lobe_statistics(array):
    rgb = array[..., :3].astype(np.float32)
    lum = (rgb@LUMA).reshape(-1).astype(np.float64)
    positive = np.maximum(lum, 0)
    n = max(1, int(np.ceil(.01*positive.size)))
    total = float(positive.sum())
    tail = float(np.partition(positive, -n)[-n:].sum())
    return {"pixels": int(lum.size), "all_rgb_zero_fraction": float(np.mean(np.all(rgb == 0, axis=-1))),
            "zero_component_fraction": float(np.mean(rgb == 0)),
            "negative_component_fraction": float(np.mean(rgb < 0)),
            "luma_p50_p90_p99_max": [float(v) for v in np.quantile(lum, [.5, .9, .99, 1])],
            "brightest_one_percent_positive_luma_energy_share": tail/total if total else None,
            "meaning": "observed radiance sparsity/tails; signal and noise are not separated"}


def inventory_clips():
    rows = []
    for path in sorted((PACKAGE/"fixtures/clips").glob("*.npz")):
        arrays, meta = clips.load_clip(path, verify=True)
        count = len(arrays["frame_indices"])
        h, w = arrays["input_depth"].shape[1:]
        changed = np.any(arrays["selected_rr_specular"][..., :3].view(np.uint16) !=
                         arrays["raw_rr_specular"][..., :3].view(np.uint16), axis=-1)
        previous = []
        for t in range(1, count):
            _, _, valid = clips.previous_coordinates(arrays, t)
            previous.append({"frame": int(arrays["frame_indices"][t]), "valid_pixels": int(valid.sum()),
                             "unsupported_pixels": int(valid.size-valid.sum()),
                             "valid_fraction": float(valid.mean())})
        normal = arrays["recovery_original_normal_roughness"]
        row = {"name": path.name, "sha256": sha_file(path), "bytes": path.stat().st_size,
               "metadata_sha256": sha_file(path.with_suffix(".json")),
               "source_capture_uuid": meta["source_capture_uuid"],
               "source_capture_manifest_sha256": meta["source_capture_manifest_sha256"],
               "frames": arrays["frame_indices"].astype(int).tolist(), "extent_width_height": [w, h],
               "crop_origin_render": arrays["crop_origin_render"].astype(int).tolist(),
               "render_extent": arrays["render_extent"].astype(int).tolist(),
               "arrays": {key: array_description(value) for key, value in arrays.items()},
               "partial_history": True, "first_frame_unsupported_previous_pixels": h*w,
               "subsequent_surface_motion_correspondence": previous,
               "surface_motion_is_not_virtual_reflection_transport": True,
               "source_material_codes": np.unique(normal >> np.uint32(30)).astype(int).tolist(),
               "semantic_labels": None, "ground_truth": None, "albedo_present": False,
               "stored_raw_vs_selected_changed_specular_pixels": int(changed.sum()),
               "changed_specular_mask_sha256": sha_array(changed),
               "total_specular_pixels": int(changed.size),
               "diffuse_raw_vs_selected_word_differences": int(np.count_nonzero(
                   arrays["raw_rr_diffuse"].view(np.uint16) != arrays["selected_rr_diffuse"].view(np.uint16))),
               "specular_alpha_raw_vs_selected_word_differences": int(np.count_nonzero(
                   arrays["raw_rr_specular"][..., 3].view(np.uint16) != arrays["selected_rr_specular"][..., 3].view(np.uint16))),
               "lobe_distributions": {key: lobe_statistics(arrays[key]) for key in
                                      ("input_diffuse", "input_specular", "raw_rr_specular", "selected_rr_specular")}}
        rows.append(row)
    return rows


def fixed_metrics(spec, diffuse, baseline_spec, masks):
    base_rgb = baseline_spec+diffuse
    rgb = spec+diffuse
    base = base_rgb@LUMA; lum = rgb@LUMA
    denominator = np.maximum(base.mean(0), np.float32(1e-6))
    hp_denominator = np.maximum(glass.gaussian(base, 2).mean(0), np.float32(1e-6))
    high = lum-glass.gaussian(lum, 2)
    high_deviation = high-high.mean(0)
    temporal_step = np.diff(high, axis=0)
    average = lum.mean(0)
    detail = abs(average-glass.gaussian(average, 1.5))
    rows = {}
    for name, mask in masks.items():
        if not mask.any():
            rows[name] = None
            continue
        rows[name] = {
            "pixels": int(mask.sum()),
            "fine_cv_fixed_base_p50": float(np.median(lum.std(0)[mask]/denominator[mask])),
            "hp_cv_fixed_base_p50": float(np.median(high.std(0)[mask]/hp_denominator[mask])),
            "hp_cv_fixed_base_p90": float(np.quantile(high.std(0)[mask]/hp_denominator[mask], .9)),
            "sparkle_positive_hp_departure_fixed_base_p995": float(np.quantile(
                np.maximum(high_deviation[:, mask], 0)/hp_denominator[mask], .995)),
            "flicker_abs_hp_step_fixed_base_p95": float(np.quantile(abs(temporal_step[:, mask])/hp_denominator[mask], .95)),
            "detail_energy_proxy": float(detail[mask].mean()),
            "mean_pre_remod_composite_luma": float(average[mask].mean()),
            "mean_specular_rgb_l1_change_from_nzr": float(abs(spec-baseline_spec)[:, mask].mean()),
            "noise_truth_available": False,
        }
    return rows


def save_png(path, rgb):
    """Lossless image of numerical results using only stdlib; no font/library dependency."""
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    h, w, channels = rgb.shape
    assert channels == 3
    def chunk(kind, data):
        return struct.pack(">I", len(data))+kind+data+struct.pack(">I", zlib.crc32(kind+data)&0xffffffff)
    raw = b"".join(b"\0"+row.tobytes() for row in rgb)
    path.write_bytes(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))+
                     chunk(b"IDAT", zlib.compress(raw, 9))+chunk(b"IEND", b""))


def recorded_glass(write_images=False):
    folder = PACKAGE/"fixtures/glass"
    manifest = json.loads((folder/"manifest.json").read_text())
    path = folder/"glass_crop.npz"
    assert sha_file(path) == manifest["data_sha256"]
    with np.load(path, allow_pickle=False) as z:
        arrays = {key: z[key] for key in z.files}
    raw = arrays["aligned_raw_spec_rgb"]
    selected = np.bitwise_xor(raw.view(np.uint32), arrays["aligned_selected_spec_rgb_xor"]).view(np.float32)
    diffuse = arrays["aligned_equal_diffuse_rgb"]
    frozen = arrays["common_mask"]
    assert int(frozen.sum()) == 6497
    changed = np.any(raw.view(np.uint32) != selected.view(np.uint32), axis=-1)
    baseline_mean = (selected+diffuse).mean(0)@LUMA
    baseline_detail = abs(baseline_mean-glass.gaussian(baseline_mean, 1.5))
    texture_cut = float(np.quantile(baseline_detail[frozen], .75))
    masks = {"common_glass": frozen, "edge_band_2px": frozen & ~erode(frozen, 2),
             "baseline_high_detail_quartile": frozen & (baseline_detail >= texture_cut)}
    outputs = []
    decisions = []
    for t in range(len(raw)):
        out, diag = shrink_specular(raw[t], selected[t], frozen, None, CandidateConfig(enabled=True))
        outputs.append(out)
        decisions.append({key: value for key, value in diag.items() if not isinstance(value, np.ndarray)})
    candidate = np.stack(outputs)
    controls = {"nzr_selected": selected, "raw_rr": raw,
                "blend_05": raw+np.float32(.5)*(selected-raw),
                "blend_075": raw+np.float32(.75)*(selected-raw),
                "reduce_strength_025": raw+np.float32(.25)*(selected-raw),
                "candidate_missing_sidecar": candidate,
                "candidate_missing_sidecar_plus_blend05": raw+np.float32(.5)*(candidate-raw),
                "spatial_blur_sigma2_null": np.stack([glass.gaussian(selected[..., c], 2) for c in range(3)], axis=-1),
                "freeze_specular_first_frame_null": np.broadcast_to(selected[:1], selected.shape)}
    metrics = {name: fixed_metrics(spec, diffuse, selected, masks) for name, spec in controls.items()}
    identities = {}
    for name, spec in controls.items():
        difference = spec.view(np.uint32) != selected.view(np.uint32)
        actual = np.broadcast_to(changed[..., None], spec.shape)
        scoped = np.broadcast_to(frozen[None, ..., None], spec.shape)
        identities[name] = {"rgb_words_on_base_changed_subset": int(np.count_nonzero(actual & scoped)),
                            "different_rgb_words_on_base_changed_subset": int(np.count_nonzero(difference & actual & scoped)),
                            "max_abs_rgb_error_from_nzr_on_base_changed_subset": float(abs(spec-selected)[actual & scoped].max()),
                            "different_rgb_words_outside_common_mask": int(np.count_nonzero(difference & ~scoped)),
                            "same_diffuse_object_hash": sha_array(diffuse)}
    # Reproduce the frozen package exactly, including its legacy CV convention.
    legacy = glass.metrics(raw+diffuse, selected+diffuse, frozen)
    for name, expected in manifest["fixture_metrics"].items():
        for key, value in expected.items():
            np.testing.assert_allclose(legacy[name][key], value, rtol=3e-6, atol=2e-9)
    assert not np.any(candidate.view(np.uint32) != selected.view(np.uint32))
    image_metadata = None
    if write_images:
        outdir = CANDIDATE/"images"; outdir.mkdir(exist_ok=True)
        index = manifest["frames"].index(55)
        exposure = manifest["display_exposure"]
        for key in ("nzr_selected", "raw_rr", "blend_05"):
            radiance = np.maximum(controls[key][index]+diffuse[index], 0)*exposure
            rgb = (255*(radiance/(1+radiance))**(1/2.2)).astype(np.uint8)
            save_png(outdir/(key+"_frame55.png"), rgb)
        save_png(outdir/"fixed_support.png", np.repeat((frozen*255).astype(np.uint8)[..., None], 3, axis=-1))
        image_metadata = {"frame": 55, "extent_width_height": [192, 160], "exposure": exposure,
                          "tonemap": manifest["display_tonemap"], "display": "pre-remod diagnostic lobe sum; not final game",
                          "all_views_share_crop_aspect_exposure_frame": True}
    return {"name": path.name, "sha256": sha_file(path), "metadata_sha256": sha_file(folder/"manifest.json"),
            "arrays": {key: array_description(a) for key, a in arrays.items()},
            "capture_uuid": manifest["capture_uuid"], "frames": manifest["frames"],
            "extent_width_height": [192, 160], "render_extent": manifest["render_extent"],
            "crop_in_roi_xyxy": manifest["fixture_crop_in_original_roi_xyxy"],
            "source_crop_origin_render": [546, 347], "source_crop_haar_parity_xy": [0, 1],
            "alignment": manifest["alignment"], "geometry_is_unwarped_but_rgb_is_camera_aligned": True,
            "original_alpha_or_input_radiance_present": False,
            "original_normal_material_codes": np.unique(arrays["original_normal_roughness_u32"] >> np.uint32(30)).astype(int).tolist(),
            "history_before_frame46_present": False, "native_uncertainty_sidecar_present": False,
            "full_roi_evidence_only_pixels_not_reexecuted": 8048,
            "no_new_full_roi_diffuse_word_equality_claim": True,
            "fixture_diffuse_rgb_hash": sha_array(diffuse),
            "immutable_masks": {key: {"pixels": int(mask.sum()), "sha256": sha_array(mask)} for key, mask in masks.items()},
            "fixed_denominator_source": "unchanged selected+diffuse temporal mean and sigma2 lowband; max1e-6",
            "baseline_texture_quartile_cut": texture_cut,
            "baseline_changed_mask_sha256": sha_array(changed),
            "legacy_calibration_separate_variable_luma_denominator": legacy,
            "fixed_base_metrics": metrics, "subset_identity_checks": identities,
            "candidate_decisions": decisions, "images": image_metadata,
            "lobe_distributions": {"aligned_raw_rr_specular": lobe_statistics(raw),
                                   "aligned_nzr_specular": lobe_statistics(selected)},
            "conclusion": "Candidate abstains exactly: no measured native improvement; supplied outputs cannot identify error covariance"}


def run(write_images=False):
    portable = {}
    for name in ("anchor", "colour"):
        root = PACKAGE/"portable"/name
        portable[name] = [{"path": str(path.relative_to(PACKAGE)), "sha256": sha_file(path),
                           "arrays": {key: array_description(z[key]) for key in z.files}}
                          for path in sorted(root.rglob("*.npz"))
                          for z in [np.load(path, allow_pickle=False)]]
    return {"schema": "glass-nzr-recorded-evidence-v1", "gpu_executed": False,
            "portable_inventory": portable, "chronological_clips": inventory_clips(),
            "glass": recorded_glass(write_images),
            "missing_roles": ["native internal history/count/moment/support and pre-Glass stage pair",
                              "per-lobe error covariance/effective independent support", "converged same-pose truth",
                              "numerical puddle sequence (historical receipt only)", "final AMD RR/game A/B"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=CANDIDATE/"evidence/recorded.json")
    parser.add_argument("--images", action="store_true")
    args = parser.parse_args()
    result = run(args.images)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"output": args.out.name,
                      "clip_inventory": [{"name": c["name"], "frames": c["frames"],
                                           "nzr_changed_specular_pixels": c["stored_raw_vs_selected_changed_specular_pixels"]}
                                          for c in result["chronological_clips"]],
                      "glass_common_mask": result["glass"]["immutable_masks"]["common_glass"],
                      "glass_fixed_base_metrics": {k: v["common_glass"] for k, v in result["glass"]["fixed_base_metrics"].items()}}, indent=2))


if __name__ == "__main__":
    main()
