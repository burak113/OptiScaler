"""Independent, precommitted controls. Does not import the candidate library.

These are falsifiers, not an alternative production algorithm. A PASS means the
specified wrong model was detected. Synthetic observations are not GPU results.
"""
from __future__ import annotations

import json
import hashlib
import importlib.util
from pathlib import Path
import sys
import numpy as np


def finite_rtz_oracle(value):
    """Small independent finite-input oracle using NumPy's nearest conversion.

    Its domain here is finite binary32; NaN payload policies are not asserted.
    """
    x = np.asarray(value, dtype=np.float32)
    if not np.all(np.isfinite(x)):
        raise ValueError("the blinded oracle deliberately accepts only finite input")
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        nearest = x.astype(np.float16)
    rounded = nearest.astype(np.float32)
    overshot = np.abs(rounded) > np.abs(x)
    toward_zero = np.nextafter(nearest, np.float16(0)).astype(np.float32)
    return np.where(overshot, toward_zero, rounded).astype(np.float32)


def controls():
    codes = np.arange(65536, dtype=np.float32)
    restored = np.floor(finite_rtz_oracle(codes / np.float32(65535))
                        * np.float32(65535) + np.float32(.5)).astype(np.int64)
    mismatched = restored != codes
    # A legal cap16 accumulation that naturally wraps the low word 64 times.
    count, increment = 262145, 16 * 65536
    exact = count * increment
    # Four source-shaped accumulator terms; only the actual output is FP16.
    correct = np.float32(1)
    premature = np.float32(1)
    for _ in range(3):
        correct = np.float32(correct + np.float32(2**-11))
        premature = finite_rtz_oracle(np.float32(premature + np.float32(2**-11)))
    correct_output = finite_rtz_oracle(np.float32(correct / 4))
    mutant_output = finite_rtz_oracle(np.float32(premature / 4))
    # Same exported half value, different source-valid native atomic increments.
    preimages = np.array([1, 1 + 2**-11], dtype=np.float32)
    stored = finite_rtz_oracle(preimages)
    increments = np.trunc(preimages * np.float32(65536)).astype(np.uint32)
    result = {
        "implementation_owner": "independent_skeptic",
        "executor": "calling local CPU process; see enclosing run record",
        "evidence_kind": "synthetic CPU controls, no GPU execution",
        "old_normal_packing": {
            "population": 65536,
            "bad_count": int(np.count_nonzero(mismatched)),
            "first_bad_codes": codes[mismatched][:8].astype(int).tolist(),
            "max_code_error": int(np.abs(restored - codes).max()),
        },
        "new_11bit_payload_identity": bool(np.array_equal(
            np.arange(2048, dtype=np.float32),
            finite_rtz_oracle(np.arange(2048, dtype=np.float32)))),
        "missing_high_word": {
            "count": count, "increment": increment, "exact": exact,
            "low": exact & 0xFFFFFFFF, "high": exact >> 32,
            "mutant_error": exact - (exact & 0xFFFFFFFF),
        },
        "premature_rounding": {
            "terms": [1, 2**-11, 2**-11, 2**-11],
            "correct_final_store": float(correct_output),
            "wrong_per_add_store": float(mutant_output),
        },
        "nonidentifiability": {
            "preimages": preimages.tolist(), "same_half_export": stored.tolist(),
            "valid_16_16_results": increments.astype(int).tolist(),
            "exact_reconstruction_possible": False,
        },
    }
    assert result["old_normal_packing"]["bad_count"] == 59383
    assert result["new_11bit_payload_identity"]
    assert result["missing_high_word"]["high"] == 64
    assert correct_output != mutant_output
    assert stored[0] == stored[1] and increments[0] != increments[1]
    return result


def overlap_recovery(*, return_arrays=False):
    """Check actual frame/crop identity before using original lobe low bits.

    Independently loads the frozen model, not the coordinator's calibration
    runner. The fixed rectangle comes from capture geometry, never output error.
    This observation refines the nonidentifiability claim: original low bits are
    available in the matching foliage rectangle, not the full colour tensor.
    With ``return_arrays=True`` return ``(summary, known_mask, recovered)``;
    ``recovered`` contains exact observed sums only where known_mask is true,
    and the original rounded colour tensor everywhere else.
    """
    package = Path(__file__).resolve().parents[2]
    colour = package / "portable/colour"
    provenance = json.loads((colour / "fixtures/provenance.json").read_text())
    foliage_manifest = json.loads((package / "fixtures/clips/foliage23.json").read_text())
    facade_manifest = json.loads((package / "fixtures/clips/facade16.json").read_text())
    if provenance["capture"] != foliage_manifest["source_capture_uuid"]:
        raise AssertionError("same frame number is insufficient: capture identity must match")
    name = "_independent_frozen_colour_overlap"
    spec = importlib.util.spec_from_file_location(name, colour / "colour_portable.py")
    model_module = importlib.util.module_from_spec(spec)
    sys.modules[name] = model_module
    spec.loader.exec_module(model_module)

    def sha(value):
        return hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()

    def compare(actual, expected):
        error = np.abs(actual.astype(np.float64) - expected.astype(np.float64))
        return {"elements": int(error.size), "changed": int(np.count_nonzero(error)),
                "max_abs": float(np.max(error)), "p99_abs": float(np.percentile(error, 99)),
                "exact": bool(np.array_equal(actual, expected))}

    with np.load(colour / "fixtures/soft2_gpu_87ee63.npz", allow_pickle=False) as f, \
            np.load(package / "fixtures/clips/foliage23.npz", allow_pickle=False) as clip:
        frame = int(provenance["frame"])
        j = int(np.flatnonzero(clip["frame_indices"] == frame)[0])
        np.testing.assert_array_equal(clip["render_extent"], provenance["original_render"])
        local_origin = clip["crop_origin_render"][j] - np.asarray(provenance["roi_origin"])
        x, y = map(int, local_origin)
        h, w = clip["input_depth"].shape[1:]
        region = (slice(y, y + h), slice(x, x + w))
        fixed_support = np.zeros(f["rr_rgb"].shape[:2], dtype=bool)
        fixed_support[region] = True
        raw_sum = (clip["raw_rr_diffuse"][j, ..., :3].astype(np.float32)
                   + clip["raw_rr_specular"][j, ..., :3].astype(np.float32)).astype(np.float32)
        input_sum = (clip["input_diffuse"][j, ..., :3].astype(np.float32)
                     + clip["input_specular"][j, ..., :3].astype(np.float32)).astype(np.float32)
        observed_matches = {
            "rounded_rr_lobe_sum": compare(finite_rtz_oracle(raw_sum), f["rr_rgb"][region]),
            "rounded_input_lobe_sum": compare(finite_rtz_oracle(input_sum), f["input_rgb"][region]),
            "depth": compare(clip["input_depth"][j], f["depth"][region]),
            "prepared_normal_words": compare(clip["input_normal_roughness"][j], f["normals_u32"][region]),
        }
        if not all(match["exact"] for match in observed_matches.values()):
            raise AssertionError("frame/crop/stage byte comparisons failed; do not infer recovered low bits")
        args = [f[k] for k in ("input_rgb", "rr_rgb", "depth", "normals_oct", "motion_px")]
        model = model_module.rejected_soft2_model()
        model.hist = f["prev_history"].copy()
        _, data = model.frame(*args)
        frozen_output = model_module.rejected_soft2_apply(args[1], args[2], args[3], data)
        recovered = f["rr_rgb"].copy()
        recovered[region] = raw_sum
        recovered_output = model_module.rejected_soft2_apply(recovered, args[2], args[3], data)
        np.testing.assert_array_equal(recovered_output[region], f["expected_soft2"][region])
        # Stronger H4 witness: actual known subset retained, unknown other pixels
        # use explicit possible half lobe pairs (h,0) and (h,delta).
        base = f["rr_rgb"]
        following = np.nextafter(base.astype(np.float16), np.float16(np.inf)).astype(np.float32)
        delta = (following - base) * np.float32(.5)
        delta = np.where(np.isfinite(delta) & (delta >= np.float32(2**-24)), delta, np.float32(0))
        np.testing.assert_array_equal(delta, delta.astype(np.float16).astype(np.float32))
        other = (base + delta).astype(np.float32)
        other[region] = raw_sum
        np.testing.assert_array_equal(finite_rtz_oracle(other), base)
        np.testing.assert_array_equal(finite_rtz_oracle(recovered), base)
        alternative_output = model_module.rejected_soft2_apply(other, args[2], args[3], data)
        summary = {
            "implementation_owner": "independent_skeptic",
            "executor": "calling local CPU process; see enclosing run record",
            "evidence_kind": "CPU reconstruction from actual stored lobe observations and synthetic witnesses",
            "gpu_executed": False,
            "capture": provenance["capture"], "frame": frame,
            "crop_render_xy": clip["crop_origin_render"][j].tolist(),
            "colour_local_crop_xywh": [x, y, w, h],
            "fixed_observed_pixels": int(fixed_support.sum()),
            "full_colour_pixels": int(fixed_support.size),
            "fixed_support_sha256": sha(fixed_support),
            "same_frame_stage_comparisons": observed_matches,
            "original_vs_prepared_normal_differences": int(np.count_nonzero(
                clip["recovery_original_normal_roughness"][j] != f["normals_u32"][region])),
            "prestore_sum_differs_from_exported_lanes": int(np.count_nonzero(raw_sum != base[region])),
            "restored_prestore_sum_sha256": sha(raw_sum),
            "baseline_vs_expected_on_observed_support": compare(frozen_output[region], f["expected_soft2"][region]),
            "restored_vs_expected_on_observed_support": compare(recovered_output[region], f["expected_soft2"][region]),
            "restoration_changes_whole_output": compare(recovered_output, frozen_output),
            "admissible_hypothetical_half_lobe_witness": {
                "first_recipe": "exported half h + zero half; replace observed rectangle by actual D+S",
                "second_recipe": "h + half-exact half-ULP delta (or zero below half-subnormal); retain actual observed D+S",
                "same_exported_colour": True,
                "output_difference": compare(alternative_output, recovered_output),
                "observed_rectangle_output_difference": compare(alternative_output[region], recovered_output[region]),
                "scope": "possible inputs for rounded colour fixture plus verified original foliage subset; not recovered original off-crop lobes",
            },
            "facade_recovery_rejected": {
                "capture": facade_manifest["source_capture_uuid"],
                "reason": "different capture and no frame63; numerical crop-origin equality does not establish provenance",
            },
            "glass_direct_copy_rejected": {
                "reason": "RGB is bilinearly aligned to reference54; original unwarped RGB lobes are not exported there",
            },
        }
        return (summary, fixed_support.copy(), recovered.copy()) if return_arrays else summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recover-overlap", action="store_true")
    options = parser.parse_args()
    print(json.dumps(overlap_recovery() if options.recover_overlap else controls(),
                     indent=2, allow_nan=False))
