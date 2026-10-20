"""Read-only prepared-guide control from the glass crop, in original coordinates.

The fixture's original_* geometry means UNWARPED provider inputs; manifest source
paths are input_normal_roughness, not recovery_original_normal_roughness. Aligned
RGB/common masks are never indexed as though they shared these coordinates.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "src"))
from foliage_guides import GuideFrame, observe_guides


def sha(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def main():
    start = time.perf_counter()
    directory = PACKAGE / "fixtures" / "glass"
    meta = json.loads((directory / "manifest.json").read_text())
    path = directory / meta["data_file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == meta["data_sha256"]
    with np.load(path, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    hashes = {key: sha(array) for key, array in arrays.items()}
    for array in arrays.values():
        array.setflags(write=False)
    depth = arrays["original_depth_f32"]
    count, h, w = depth.shape
    # This fixed unwarped crop mask is not a semantic glass mask. It is built
    # from original data before any candidate result is evaluated.
    core = np.isfinite(depth) & (depth > 0)
    core[:, :6] = False
    core[:, -6:] = False
    core[:, :, :6] = False
    core[:, :, -6:] = False
    mask_path = HERE / "glass_unwarped_base_mask.npz"
    if mask_path.exists():
        with np.load(mask_path, allow_pickle=False) as prior:
            assert np.array_equal(prior["unwarped_core"], core)
    else:
        np.savez_compressed(mask_path, unwarped_core=core)
    origin = tuple(meta["original_roi"]["origin"][i] + meta["fixture_crop_in_original_roi_xyxy"][i] for i in (0, 1))
    extent = tuple(meta["render_extent"])
    previous = None
    outputs = []
    for t, frame_id in enumerate(meta["frames"]):
        frame = GuideFrame(arrays["original_normal_roughness_u32"][t], depth[t],
                           arrays["original_motion_rgba_f16"][t], frame_id, origin,
                           extent, depth_is_positive_linear=True, reset=(t == 0))
        outputs.append(observe_guides(frame, previous, enabled=True))
        previous = frame
    supported = np.stack([x.temporal_supported for x in outputs])
    multipliers = np.stack([x.experimental_history_multiplier for x in outputs])
    dispersion = np.stack([x.angular_dispersion for x in outputs])
    assert not supported[0].any()
    assert np.all(multipliers[~supported] == 1)
    assert hashes == {key: sha(array) for key, array in arrays.items()}
    result = {
        "executor": "/root/skeptic", "gpu_executed": False,
        "stage": "Captured prepared-guide CPU observation; no image reconstruction or filtering",
        "source_archive_sha256": meta["data_sha256"],
        "frames": meta["frames"], "crop_origin_render_xy": origin,
        "extent_wh": [w, h], "render_extent_wh": extent,
        "guide_authority": "unwarped input_normal_roughness provider capture; pre-Flat original recovery guide absent here",
        "depth_admission": "positive bridge linear-depth numerical comparison only; raw validity/sanitization class absent",
        "mask": {"coordinate_space": "unwarped source crop", "semantic_glass_mask": False,
                 "definition": "6-pixel rectangular halo excluded; original finite positive depth",
                 "count": int(core.sum()), "per_frame_count": core.sum(axis=(1, 2)).tolist(),
                 "sha256": sha(core)},
        "aligned_mask_used_for_unwarped_guides": False,
        "all_source_arrays_bitwise_unchanged": True,
        "source_array_sha256": hashes,
        "temporal_comparable_fraction_on_fixed_core": float(supported[core].mean()),
        "first_frame_comparable_count": int(supported[0].sum()),
        "unsupported_identity_exact": bool(np.all(multipliers[~supported] == 1)),
        "mean_angular_dispersion_on_fixed_core": float(dispersion[core].mean()),
        "mean_experimental_multiplier_on_fixed_core": float(multipliers[core].mean()),
        "captured_glass_output_quality_improvement": None,
        "limitation": "Aligned RGB/masks and unwarped prepared guides are distinct grids; this control does not validate the proposed original-guide adapter or glass history quality",
        "elapsed_seconds": time.perf_counter() - start,
    }
    (HERE / "glass_prepared_control.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: result[key] for key in ("all_source_arrays_bitwise_unchanged", "temporal_comparable_fraction_on_fixed_core", "mean_angular_dispersion_on_fixed_core", "mean_experimental_multiplier_on_fixed_core", "elapsed_seconds")}, indent=2))


if __name__ == "__main__":
    main()
