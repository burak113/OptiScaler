"""Inventory immutable native fixtures without changing arrays or inventing history.

Run from any directory. Dependencies: Python 3.11+ and NumPy 2.3.5.
All NPZ loads reject pickle; file and evaluation-support hashes are reported.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[1]
sys.path.insert(0, str(PACKAGE / "fixtures" / "clips"))
from clip_loader import load_clip, previous_coordinates, sample_previous

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def array_hash(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def luminance(rgb: np.ndarray) -> np.ndarray:
    return np.sum(np.asarray(rgb[..., :3], np.float32) * LUMA, axis=-1, dtype=np.float32)


def same_words(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if a.shape != b.shape or a.dtype != b.dtype:
        raise ValueError("Exact storage equality requires matching shape and dtype")
    word = {2: np.uint16, 4: np.uint32}[a.dtype.itemsize]
    return np.all(a.view(word) == b.view(word), axis=-1)


def decode_guides(packed: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """R10G10B10A2: octahedral RG normals, B roughness; no semantic A guess."""
    p = np.asarray(packed, np.uint32)
    o = np.stack([(p & 1023), ((p >> 10) & 1023)], axis=-1).astype(np.float32) / 1023.0
    xy = 2.0 * o - 1.0
    n = np.concatenate([xy, (1.0 - np.abs(xy).sum(-1))[..., None]], axis=-1)
    fold = np.maximum(-n[..., 2], 0)
    n[..., :2] += np.where(n[..., :2] >= 0, -fold[..., None], fold[..., None])
    n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), np.finfo(np.float32).tiny)
    roughness = ((p >> 20) & 1023).astype(np.float32) / 1023.0
    return n, roughness


def frozen_support(arrays: dict, lobe: str) -> dict[str, np.ndarray]:
    raw, selected = (arrays[f"{role}_rr_{lobe}"] for role in ("raw", "selected"))
    finite = np.isfinite(raw[..., :3]).all(-1) & np.isfinite(selected[..., :3]).all(-1)
    depth = arrays["input_depth"]
    # This numerical mask is frozen from BASE, never called on corrected output.
    base = finite & np.isfinite(depth) & (np.abs(depth) > 0)
    eligible = same_words(raw, selected)
    den = np.maximum(luminance(raw), np.float32(1e-6))
    return {"base": base, "eligible": base & eligible,
            "protected": base & ~eligible, "denominator": den}


def signal_stats(rgba: np.ndarray) -> dict:
    rgb = rgba[..., :3].astype(np.float32)
    y = luminance(rgb).astype(np.float64).ravel()
    positive = np.maximum(y, 0)
    top_count = max(1, int(np.ceil(positive.size * 0.01)))
    top = np.partition(positive, positive.size - top_count)[-top_count:]
    total = float(positive.sum())
    return {
        "pixels": int(y.size), "zero_rgb_fraction": float(np.mean(np.all(rgb == 0, axis=-1))),
        "any_negative_rgb_fraction": float(np.mean(np.any(rgb < 0, axis=-1))),
        "nonfinite_rgb_elements": int(np.count_nonzero(~np.isfinite(rgb))),
        "alpha_zero_fraction": float(np.mean(rgba[..., 3] == 0)),
        "luminance_quantiles_physical": {str(q): float(np.percentile(y, q)) for q in (0, 50, 90, 99, 99.9, 100)},
        "top_1_percent_positive_luminance_energy_fraction": float(top.sum() / total) if total else None,
    }


def clip_inventory(path: Path) -> dict:
    a, meta = load_clip(path, verify=True)
    t, h, w = a["input_depth"].shape
    result = {
        "path": str(path.relative_to(PACKAGE)), "sha256": sha256(path),
        "metadata_sha256": sha256(path.with_suffix(".json")),
        "capture_uuid": meta["source_capture_uuid"],
        "original_manifest_sha256": meta["source_capture_manifest_sha256"],
        "frames": a["frame_indices"].tolist(), "extent_wh": [w, h],
        "render_extent_wh": a["render_extent"].tolist(),
        "crop_origins_render_xy": a["crop_origin_render"].tolist(),
        "arrays": {k: {"dtype": v.dtype.str, "shape": list(v.shape), "raw_sha256": array_hash(v)} for k, v in a.items()},
        "partial_history": True, "rr_has_pre_fixture_history": True,
        "final_game_output_available": False, "albedo_available": False,
        "first_previous_frame_available": False, "lobes": {},
        "material_codes": np.unique(a["recovery_original_normal_roughness"] >> 30).tolist(),
        "provider_vs_original_guide_different_fraction": float(np.mean(a["input_normal_roughness"] != a["recovery_original_normal_roughness"])),
        "history_in_bounds_fraction_by_frame": [0.0] + [float(previous_coordinates(a, i)[2].mean()) for i in range(1, t)],
    }
    for lobe in ("diffuse", "specular"):
        raw, selected = a[f"raw_rr_{lobe}"], a[f"selected_rr_{lobe}"]
        masks = frozen_support(a, lobe)
        row = {
            "signals": {role: signal_stats(a[f"{role}_{lobe}"]) for role in ("input", "raw_rr", "selected_rr")},
            "raw_selected_rgba_equal_fraction": float(same_words(raw, selected).mean()),
            "raw_selected_alpha_word_differences": int(np.count_nonzero(raw[..., 3].view(np.uint16) != selected[..., 3].view(np.uint16))),
            "frozen_support": {k: {"sha256": array_hash(v), "pixels": int(v.sum()) if v.dtype == bool else None} for k, v in masks.items()},
        }
        # Origin-aware observed correlation is a descriptive statistic, not a noise label.
        pairs = []
        for i in range(1, t):
            qx, qy, inside = previous_coordinates(a, i)
            prev, _ = sample_previous(luminance(a[f"input_{lobe}"][i - 1]), qx, qy)
            cur = luminance(a[f"input_{lobe}"][i]).astype(np.float64)
            mask = inside & np.isfinite(prev) & masks["base"][i]
            x, y = prev[mask], cur[mask]
            corr = float(np.corrcoef(x, y)[0, 1]) if x.size > 2 and x.std() > 0 and y.std() > 0 else None
            pairs.append({"frame": int(a["frame_indices"][i]), "pixels": int(mask.sum()),
                          "observed_input_luma_correlation": corr,
                          "occlusion_checked": False})
        row["chronological_input_pairs"] = pairs
        result["lobes"][lobe] = row
    return result


def main() -> int:
    paths = [PACKAGE / "fixtures/clips" / (name + ".npz") for name in ("bottle_track7", "foliage23", "facade16")]
    colour = PACKAGE / "portable/colour/fixtures/soft2_gpu_87ee63.npz"
    glass = PACKAGE / "fixtures/glass/glass_crop.npz"
    archive_inventory = []
    for path in sorted((PACKAGE / "portable/anchor/fixtures").rglob("*.npz")) + [colour, glass]:
        with np.load(path, allow_pickle=False) as archive:
            fields = {k: {"shape": list(archive[k].shape), "dtype": archive[k].dtype.str} for k in archive.files}
        archive_inventory.append({"path": str(path.relative_to(PACKAGE)), "sha256": sha256(path),
                                  "bytes": path.stat().st_size, "arrays": fields})
    result = {
        "schema": "native-colour-inventory-v1", "executor": "cloud_cpu",
        "units": {"radiance": "float16 RGBA physical linear pre-remod D/S; alpha is opaque hit-distance/signal data",
                  "depth": "float32 signed linear depth in original captured units",
                  "motion": "float16 RGBA; RG full-render UV previous-minus-current; B previous-minus-current depth",
                  "guides": "uint32 R10G10B10A2: oct RG, linear roughness B, nonsemantic material A",
                  "controls": "46 original uint32 words, no reinterpretation as a new chronology"},
        "frozen_mask_rule": "finite original RR/selected RGB and finite nonzero original depth; split by original RGBA word equality",
        "frozen_denominator_rule": "max(float32 dot(original raw RR RGB, Rec709 luma),1e-6), per lobe and frame",
        "clips": [clip_inventory(p) for p in paths], "other_archives": archive_inventory,
        "colour_scope": "Only frame63, combined D+S physical sum, CPU-warmed C8 history; not native or temporal GPU replay",
        "glass_scope": "Aligned RGB float32 plus selected XOR, no native alpha/raw-input lobes in this subset; RGBA contract cannot be tested here",
        "anchor_scope": "Stored shader fields and recalled keys, no raw history ring or new GPU execution",
    }
    out = HERE / "evidence/inventory.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    for clip in result["clips"]:
        for lobe, row in clip["lobes"].items():
            stats = row["signals"]["input"]
            print(json.dumps({"clip": Path(clip["path"]).stem, "lobe": lobe,
                              "zero_rgb_fraction": stats["zero_rgb_fraction"],
                              "top1_energy": stats["top_1_percent_positive_luminance_energy_fraction"],
                              "eligible_rgba_equal_fraction": row["raw_selected_rgba_equal_fraction"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
