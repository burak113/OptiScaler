"""Inventory ancillary handoff fixtures without tuning the anchor candidate.

Bottle signal values are opened only with --include-bottle after the recorded
candidate-source freeze. Without that option only ZIP/NPY headers, manifests,
hashes and recorded crop provenance are used. All descriptive measurements use
the unchanged entire crop, not a candidate-dependent quality mask.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[2]
CLIPS = PACKAGE / "fixtures" / "clips"
sys.path.insert(0, str(CLIPS))
from clip_loader import load_clip, previous_coordinates  # noqa: E402


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def array_digest(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes(order="C")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def array_headers(path):
    """Read shape/dtype only, without decoding signal values or pickles."""
    result = {}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            assert info.filename.endswith(".npy")
            with archive.open(info) as f:
                version = np.lib.format.read_magic(f)
                if version == (1, 0):
                    shape, fortran, dtype = np.lib.format.read_array_header_1_0(f)
                elif version == (2, 0):
                    shape, fortran, dtype = np.lib.format.read_array_header_2_0(f)
                else:
                    raise ValueError(f"Unexpected NPY version {version}")
            assert not dtype.hasobject
            result[info.filename[:-4]] = {
                "shape": list(shape), "dtype": dtype.str, "fortran_order": bool(fortran),
                "uncompressed_array_bytes": int(np.prod(shape) * dtype.itemsize),
            }
    return result


def roles(key):
    if key in ("input_diffuse", "input_specular"):
        return "native physical pre-provider RGB lobe input; FP16 alpha is original hit distance"
    if key.startswith("raw_rr_"):
        return "captured raw AMD RR lobe output; no ground truth; alpha preserved, semantic unspecified here"
    if key.startswith("selected_rr_"):
        return "captured existing recovery-selected lobe output; no ground truth; alpha preserved"
    if key == "input_motion":
        return "RG: original full-render UV displacement previous-minus-current; B: previous-minus-current linear depth; A: preserved payload"
    if "normal_roughness" in key:
        return "packed R10G10B10A2 uint32: oct normal bits0..19, roughness20..29, material30..31; world normals"
    if key == "input_depth":
        return "original linear scene depth float32; sign retained; world-unit length scale not supplied"
    if key == "provider_controls":
        return "46 original uint32 ABI words per frame; float bit patterns and frame index retained"
    if "origin" in key or "extent" in key:
        return "integer pixels in x,y order; original render/source coordinates"
    if key == "frame_indices":
        return "original capture frame ordinals, chronological and unlooped"
    if key.endswith("_u32"):
        return "original camera/projection/position IEEE754 float32 bit-pattern words"
    return "see source manifest"


def energy_summary(rgba):
    rgb = rgba[..., :3].astype(np.float32)
    # Compute physical luma in float32, avoiding a new FP16 quantization stage.
    luma = np.sum(rgb * np.array([.2126, .7152, .0722], np.float32), axis=-1, dtype=np.float32)
    flat = luma.astype(np.float64).ravel()
    total = float(flat.sum())
    top = max(1, int(np.ceil(flat.size * .01)))
    return {
        "support": "entire original crop, immutable all-pixel denominator",
        "pixel_count": int(flat.size),
        "all_rgb_zero_fraction": float(np.all(rgb == 0, axis=-1).mean()),
        "luma_zero_fraction": float((flat == 0).mean()),
        "mean_luma": float(flat.mean()), "p99_luma": float(np.percentile(flat, 99)),
        "max_luma": float(flat.max()),
        "top_one_percent_luma_energy_fraction": float(np.sort(flat)[-top:].sum() / total) if total else None,
        "energy_concentration_ess": float(total**2 / np.square(flat).sum()) if total else 0.0,
        "ess_is_not_independent_sample_count": True,
        "alpha_dtype": rgba.dtype.str,
        "alpha_raw_sha256": array_digest(rgba[..., 3]),
    }


def clip_inventory(name, read_signal_values):
    path = CLIPS / f"{name}.npz"
    meta_path = path.with_suffix(".json")
    m = read_json(meta_path)
    headers = array_headers(path)
    assert set(headers) == set(m["arrays"])
    for key, header in headers.items():
        assert header["shape"] == m["arrays"][key]["shape"]
        assert header["dtype"] == m["arrays"][key]["dtype"]
        header["declared_raw_sha256"] = m["arrays"][key]["raw_sha256"]
        header["role_and_units"] = roles(key)
    archive_sha = digest(path)
    assert archive_sha == m["archive"]["sha256"]
    crops = [x for x in m["source_files"] if x["field"] == "input_depth"]
    origins = [[x["crop_local_xyxy"][0] + m["source_roi_origin"][0],
                x["crop_local_xyxy"][1] + m["source_roi_origin"][1]] for x in crops]
    frames = m["source_frame_indices"]
    assert [x["frame_index"] for x in crops] == frames
    assert np.all(np.diff(frames) == 1)
    result = {
        "archive": path.relative_to(PACKAGE).as_posix(),
        "archive_sha256": archive_sha, "archive_bytes": path.stat().st_size,
        "manifest_sha256": digest(meta_path),
        "source_capture_uuid": m["source_capture_uuid"],
        "source_capture_manifest_sha256": m["source_capture_manifest_sha256"],
        "source_input_sha256": m["source_input_sha256"],
        "source_input_hash_scope": m["source_input_sha256_scheme"],
        "array_headers": headers,
        "frames": frames, "frame_count": len(frames),
        "render_extent_xy": m["render_extent"], "crop_extent_xy": m["crop_extent"],
        "source_roi_origin_xy": m["source_roi_origin"],
        "source_roi_extent_xy": m["source_roi_extent"],
        "crop_origins_render_xy": origins,
        "crop_moves": len({tuple(p) for p in origins}) > 1,
        "crop_motion_is_not_camera_or_object_motion": True,
        "fixed_pixel_mask_arrays": [key for key in headers if "mask" in key],
        "no_bundled_quality_mask": not any("mask" in key for key in headers),
        "descriptive_denominator": int(np.prod(m["crop_extent"])),
        "ground_truth": False, "missing_albedo": True,
        "partial_history": True, "first_previous_image_available": False,
        "stored_rr_contains_pre_fixture_history": True, "looping_used": False,
        "coordinate_contract": m["coordinate_contract"],
        "material_note": m["material_note"],
        "signal_values_opened": bool(read_signal_values),
    }
    if not read_signal_values:
        result["history_coordinate_support"] = None
        result["per_lobe_statistics"] = None
        result["unavailable_reason"] = "Bottle2405 signal arrays deliberately unopened until held-out release; archive hash and NPY headers verified, origins from published crop provenance."
        return result
    arrays, _ = load_clip(path, verify=True)
    assert arrays["crop_origin_render"].tolist() == origins
    assert arrays["render_extent"].tolist() == m["render_extent"]
    history = []
    width, height = m["crop_extent"]
    for index, frame in enumerate(frames):
        if index == 0:
            history.append({"frame": frame, "available": False, "supported_pixels": 0,
                            "total_pixels": width * height, "supported_fraction": 0.0,
                            "reason": "previous frame absent; current captured MV cannot manufacture an image"})
            continue
        qx, qy, valid = previous_coordinates(arrays, index)
        # Recompute independently to check original render scale + origin deltas.
        yy, xx = np.mgrid[:height, :width]
        mv = arrays["input_motion"][index, ..., :2].astype(np.float64)
        origin_delta = np.asarray(origins[index]) - origins[index - 1]
        np.testing.assert_array_equal(qx, xx + origin_delta[0] + mv[..., 0] * m["render_extent"][0])
        np.testing.assert_array_equal(qy, yy + origin_delta[1] + mv[..., 1] * m["render_extent"][1])
        history.append({"frame": frame, "previous_frame": frames[index-1], "available": True,
                        "supported_pixels": int(valid.sum()), "total_pixels": int(valid.size),
                        "supported_fraction": float(valid.mean()),
                        "unsupported_pixels": int((~valid).sum()),
                        "frozen_coordinate_support_sha256": array_digest(valid),
                        "geometry_validity": "in-crop finite bilinear coordinates only; no depth/normal occlusion or semantic certification"})
    result["history_coordinate_support"] = history
    result["per_lobe_statistics"] = {
        role: {"all_frames": energy_summary(arrays[role]),
               "frames": [{"frame": frame, **energy_summary(arrays[role][i])} for i, frame in enumerate(frames)]}
        for role in ("input_diffuse", "input_specular")
    }
    result["original_array_hash_verification"] = "all 21 array raw hashes/dtypes/shapes matched manifest via unchanged loader"
    return result


def colour_inventory():
    folder = PACKAGE / "portable" / "colour"
    provenance = read_json(folder / "fixtures/provenance.json")
    manifest = read_json(folder / "manifest.json")
    path = folder / "fixtures/soft2_gpu_87ee63.npz"
    headers = array_headers(path)
    assert digest(path) == provenance["fixture_sha256"]
    for key, info in headers.items():
        assert info["shape"] == provenance["arrays"][key]["shape"]
        assert np.dtype(info["dtype"]) == np.dtype(provenance["arrays"][key]["dtype"])
    file_checks = {}
    for relative, expected in manifest["files"].items():
        actual = digest(folder / relative)
        assert actual == expected["sha256"]
        file_checks[relative] = actual
    return {
        "archive": path.relative_to(PACKAGE).as_posix(),
        "archive_sha256": digest(path), "archive_bytes": path.stat().st_size,
        "array_headers": headers, "package_file_hash_checks": file_checks,
        "capture_uuid": provenance["capture"], "frame": provenance["frame"],
        "render_extent_xy": provenance["original_render"], "crop_extent_xy": provenance["size"],
        "crop_origin_render_xy": provenance["roi_origin"],
        "history_grid_xy": provenance["quarter"],
        "scope": provenance["scope"], "history_scope": provenance["history_scope"],
        "target_domain": provenance["target_domain"], "output_domain": provenance["output_domain"],
        "motion_contract": provenance["motion"], "precision_caveat": provenance["precision_caveat"],
        "sampler_caveat": provenance["sampler_caveat"],
        "fixed_pixel_mask_arrays": [], "per_lobe_alpha_available": False,
        "measured_fresh_gpu": False, "raw_six_slice_anchor_keys_available": False,
        "can_validate_anchor_causal_identifiability": False,
        "historical_gpu_result_is_calibration_only": True,
    }


def glass_inventory():
    folder = PACKAGE / "fixtures" / "glass"
    m = read_json(folder / "manifest.json")
    path = folder / m["data_file"]
    assert digest(path) == m["data_sha256"]
    headers = array_headers(path)
    with np.load(path, allow_pickle=False) as z:
        mask = z["common_mask"]
        masks = {key: {"shape": list(z[key].shape), "raw_sha256": array_digest(z[key]),
                       "true_count": int(z[key].sum())} for key in z.files
                 if z[key].dtype == np.dtype(bool)}
    assert int(mask.sum()) == m["fixture_common_mask_pixels"]
    crop = m["fixture_crop_in_original_roi_xyxy"]
    origin = m["original_roi"]["origin"]
    return {
        "archive": path.relative_to(PACKAGE).as_posix(), "archive_sha256": digest(path),
        "archive_bytes": path.stat().st_size, "manifest_sha256": digest(folder / "manifest.json"),
        "array_headers": headers, "capture_uuid": m["capture_uuid"],
        "source_capture_manifest_sha256": m["source_capture_manifest_sha256"],
        "frames": m["frames"], "alignment_reference_frame": m["reference_frame"],
        "crop_origin_render_xy": [crop[0] + origin[0], crop[1] + origin[1]],
        "crop_extent_xy": [crop[2] - crop[0], crop[3] - crop[1]],
        "render_extent_xy": m["render_extent"], "immutable_masks": masks,
        "immutable_common_support_count": int(mask.sum()),
        "separate_full_roi_support_count_not_used_here": m["full_roi_common_mask_pixels_separate_evidence"],
        "alignment_contract": m["alignment"], "geometry_provenance": m["geometry_provenance"],
        "raw_role": "aligned captured raw RR specular RGB float32; not native pre-provider input",
        "selected_role": "aligned captured old NZR specular RGB stored as uint32 XOR against raw bits",
        "diffuse_role": "aligned equal diffuse RGB float32",
        "no_input_lobe_alpha": True, "no_native_anchor_stats_or_ring_keys": True,
        "ground_truth": False, "reference_warning": m["reference_warning"],
        "exposure": m["display_exposure"], "exposure_is_display_only": True,
        "new_quality_metrics_computed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-bottle", action="store_true",
                        help="read bottle signal arrays after the recorded candidate-source freeze")
    args = parser.parse_args()
    release = {"bottle_signal_values_opened": False,
               "bottle_signal_values_unopened_until_root_holdout_release": True}
    if args.include_bottle:
        freeze_path = HERE.parent / "evidence" / "FROZEN_SOURCE.json"
        freeze = read_json(freeze_path)
        release.update({"bottle_signal_values_opened": True,
                        "source_freeze_record": "evidence/FROZEN_SOURCE.json",
                        "source_freeze_sha256": digest(freeze_path),
                        "source_frozen_utc": freeze["frozen_utc"],
                        "method_changes_after_release": "none; enabled existing descriptive inventory only"})
    result = {
        "schema": "anchor_job02_data_inventory_v1", "executor": "mechanism subagent CPU inventory",
        "script_sha256": digest(__file__), "gpu_executed": False,
        "anchor_inventory": "mechanism/results.json separately inventories development22f9; baseline/held-out calibrations are owned by the task runner",
        "holdout_release": release,
        "clips": {name: clip_inventory(name, name != "bottle_track7" or args.include_bottle)
                  for name in ("bottle_track7", "foliage23", "facade16")},
        "colour": colour_inventory(), "glass": glass_inventory(),
        "shared_missing_observables": [
            "albedo for chronological clip RR dispatch reconstruction",
            "raw native anchor six-slice key level/depth textures",
            "original native pre-store 16.16 low/high atomic sums",
            "unseen history before each exported clip/window",
            "independent same-pose illumination/Monte Carlo truth or controlled cause witness",
            "fresh actual native Config-to-provider wiring, RR and final-game output for this candidate",
        ],
    }
    target = HERE / "data_inventory.json"
    target.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    summary = {"output": target.name, "status": "all inventory/hash/coordinate checks passed", "clips": {}}
    for name, clip in result["clips"].items():
        supported = clip["history_coordinate_support"]
        fractions = [f["supported_fraction"] for f in supported[1:]] if supported else []
        summary["clips"][name] = {"extent_xy": clip["crop_extent_xy"],
                                  "frames": [clip["frames"][0], clip["frames"][-1]],
                                  "crop_moves": clip["crop_moves"],
                                  "after_first_min_history_support": min(fractions) if fractions else None,
                                  "after_first_max_history_support": max(fractions) if fractions else None,
                                  "values_opened": clip["signal_values_opened"],
                                  "quality_mask_present": not clip["no_bundled_quality_mask"]}
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
