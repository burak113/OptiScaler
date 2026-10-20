"""Replay only CPU post-selection proposals on immutable chronological native clips.

No AMD dispatch, source filtering feedback, synthesized missing history, or game
remodulation occurs. Native B4/soft2 are explicitly CPU counterfactual adapters.
Quality proxies have immutable BASE support/denominators and are not truth.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PACKAGE / "portable/colour"))
import colour_portable as cp
from inventory import (array_hash, decode_guides, frozen_support, load_clip,
                       luminance, previous_coordinates, same_words, sample_previous, sha256)
from native_colour import Config, NativeColourModel


def smooth(rgb: np.ndarray, sigma: float) -> np.ndarray:
    return np.moveaxis(cp.gaussian(np.moveaxis(np.asarray(rgb, np.float32), -1, 0), sigma), 0, -1)


def chroma(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb[..., :3], np.float32)
    return rgb - luminance(rgb)[..., None]


def chroma_normalized(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb[..., :3], np.float32)
    return rgb / np.maximum(luminance(rgb), np.float32(1e-6))[..., None]


def hp_chroma(rgb: np.ndarray) -> np.ndarray:
    cc = chroma(rgb)
    return cc - smooth(cc, 2.0)


def quantiles(values: np.ndarray) -> dict:
    v = np.asarray(values).ravel()
    if not v.size:
        return {"count": 0, "mean": None, "p50": None, "p90": None, "p99": None, "max": None}
    if not np.isfinite(v).all():
        raise AssertionError("A metric became nonfinite; do not silently drop samples")
    return {"count": int(v.size), "mean": float(v.mean()),
            **{f"p{q}": float(np.percentile(v, q)) for q in (50, 90, 99)}, "max": float(v.max())}


def temporal_samples(arrays: dict, stack: np.ndarray, support: np.ndarray, denominator: np.ndarray,
                     geometry: tuple[np.ndarray, np.ndarray]) -> tuple[np.ndarray, list, dict]:
    normal, _ = geometry
    all_values, frame_rows, mask_hashes = [], [], []
    spatial = np.stack([hp_chroma(frame) for frame in stack])
    for t in range(1, len(stack)):
        qx, qy, valid = previous_coordinates(arrays, t)
        prior, _ = sample_previous(spatial[t - 1], qx, qy)
        prior_z, _ = sample_previous(arrays["input_depth"][t - 1], qx, qy)
        prior_n, _ = sample_previous(normal[t - 1], qx, qy)
        prior_mask, _ = sample_previous(support[t - 1].astype(np.float32), qx, qy)
        prior_den, _ = sample_previous(denominator[t - 1], qx, qy)
        expected_z = arrays["input_depth"][t].astype(np.float64) + arrays["input_motion"][t, ..., 2].astype(np.float64)
        # Original geometry only: all candidates share identical accepted pairs.
        valid &= support[t] & (prior_mask >= 1.0 - 1e-12)
        valid &= np.abs(prior_z - expected_z) <= 0.02 * np.maximum(np.abs(expected_z), 1e-3)
        valid &= np.signbit(prior_z) == np.signbit(expected_z)
        prior_norm = np.linalg.norm(prior_n, axis=-1)
        normalized_prior_n = prior_n / np.maximum(prior_norm[..., None], 1e-12)
        valid &= np.sum(normalized_prior_n * normal[t], axis=-1) >= 0.9
        norm = np.maximum(0.5 * (denominator[t] + prior_den), 1e-6)
        residual = np.linalg.norm(spatial[t] - prior, axis=-1) / (math.sqrt(2.0) * norm)
        values = residual[valid]
        all_values.append(values)
        frame_rows.append({"frame": int(arrays["frame_indices"][t]), **quantiles(values)})
        mask_hashes.append(array_hash(valid))
    return np.concatenate(all_values) if all_values else np.empty(0), frame_rows, {
        "first_frame_excluded": int(arrays["frame_indices"][0]),
        "pair_mask_sha256_by_frame": mask_hashes,
        "ideal_cpu_sampler": True, "dynamic_surface_truth_available": False}


def measure(arrays: dict, lobe: str, output: np.ndarray, support: dict,
            geometry: tuple[np.ndarray, np.ndarray]) -> dict:
    raw, selected = arrays[f"raw_rr_{lobe}"], arrays[f"selected_rr_{lobe}"]
    source = arrays[f"input_{lobe}"]
    den = support["denominator"]
    t, h, w = den.shape
    interior = np.zeros((t, h, w), bool)
    # Candidate radius3 + widest metric radius9. See measurement_audit.json;
    # original3px results remain archived. Larger B4/soft2 are crop-limited.
    interior[:, 12:h-12, 12:w-12] = True
    diff = output[..., :3].astype(np.float32) - selected[..., :3].astype(np.float32)
    ydiff_abs = np.abs(luminance(output) - luminance(selected))
    ydiff = ydiff_abs / den
    correction_hp, output_detail, base_detail, proxy_error = [], [], [], []
    for i in range(t):
        delta = chroma(diff[i])
        correction_hp.append(np.linalg.norm(delta - smooth(delta, 2.0), axis=-1) / den[i])
        output_detail.append(np.linalg.norm(output[i, ..., :3].astype(np.float32) - smooth(output[i, ..., :3], 1.5), axis=-1) / den[i])
        base_detail.append(np.linalg.norm(selected[i, ..., :3].astype(np.float32) - smooth(selected[i, ..., :3], 1.5), axis=-1) / den[i])
        proxy_error.append(np.linalg.norm(chroma_normalized(smooth(output[i, ..., :3], 3.0)) -
                                          chroma_normalized(smooth(source[i, ..., :3], 3.0)), axis=-1))
    correction_hp, output_detail, base_detail, proxy_error = map(np.stack, (correction_hp, output_detail, base_detail, proxy_error))
    subsets = {}
    for subset in ("base", "eligible", "protected"):
        mask = support[subset] & interior
        values, frames, pairing = temporal_samples(arrays, output, mask, den, geometry)
        base_energy = float(np.sum(base_detail[mask], dtype=np.float64))
        selected_words = selected.view(np.uint16)
        output_words = output.view(np.uint16)
        subsets[subset] = {
            "pixels_including_all_frames": int(mask.sum()), "mask_sha256": array_hash(mask),
            "temporal_chroma_hf": quantiles(values), "temporal_chroma_hf_by_frame": frames,
            "pairing": pairing,
            "injected_correction_chroma_hf": quantiles(correction_hp[mask]),
            "physical_lobe_luma_error_relative_to_base_den": quantiles(ydiff[mask]),
            "physical_lobe_luma_error_absolute": quantiles(ydiff_abs[mask]),
            "input_proxy_low_band_chroma_distance": quantiles(proxy_error[mask]),
            "spatial_detail_energy_ratio_to_selected": float(output_detail[mask].sum(dtype=np.float64) / base_energy) if base_energy else None,
            "changed_rgba_words": int(np.count_nonzero(output_words[mask] != selected_words[mask])),
        }
    protected = ~same_words(raw, selected)
    return {
        "subsets": subsets,
        "protected_rgba_changed_words_full_crop": int(np.count_nonzero(output.view(np.uint16)[protected] != selected.view(np.uint16)[protected])),
        "alpha_changed_words_full_crop": int(np.count_nonzero(output[..., 3].view(np.uint16) != selected[..., 3].view(np.uint16))),
        "full_crop_output_sha256": array_hash(output),
        "full_crop_changed_pixel_fraction": float(np.mean(~same_words(output, selected))),
        "finite_output_rgb": bool(np.isfinite(output[..., :3]).all()),
    }


def run_clip(name: str, plots: bool) -> dict:
    arrays, meta = load_clip(PACKAGE / "fixtures/clips" / (name + ".npz"), verify=True)
    original = arrays["recovery_original_normal_roughness"]
    normal, roughness = decode_guides(original)
    octahedral = np.stack([(original & 1023), (original >> 10) & 1023], -1).astype(np.float32) / 1023.0
    frame_count, height, width = arrays["input_depth"].shape
    report = {"clip": name, "capture_uuid": meta["source_capture_uuid"],
              "frames": arrays["frame_indices"].tolist(), "extent_wh": [width, height],
              "fixture_sha256": meta["archive"]["sha256"],
              "scope": "CPU post-selection experiment on stored native lobes; no fresh AMD RR; no final remod",
              "quality_mask_halo_pixels": 12,
              "B4_soft2_additional_scope_limit": "Wider support and modeled history are crop-limited; no full-support native baseline comparison claimed",
              "chronological_once": True, "stateless_candidate": True, "lobes": {}}
    for lobe in ("diffuse", "specular"):
        start = time.monotonic()
        raw, selected, source = (arrays[f"{role}_{lobe}"] for role in ("raw_rr", "selected_rr", "input"))
        support = frozen_support(arrays, lobe)
        models = {key: NativeColourModel(Config(enabled=True, representation=key)) for key in ("log", "linear")}
        b4, soft = cp.baseline_model(), cp.rejected_soft2_model()
        stacks = {"selected": selected.copy(), "B4_native_cpu": [], "soft2_native_cpu_rejected": [], "log": [], "linear": []}
        diagnostics = {"log": [], "linear": []}
        for i, frame in enumerate(arrays["frame_indices"]):
            motion = arrays["input_motion"][i].astype(np.float32)
            motion[..., :2] *= arrays["render_extent"].astype(np.float32)
            if i:
                motion[..., :2] += (arrays["crop_origin_render"][i] - arrays["crop_origin_render"][i - 1]).astype(np.float32)
            args = (source[i, ..., :3], raw[i, ..., :3], arrays["input_depth"][i], octahedral[i], motion)
            bout, _ = b4.frame(*args)
            _, data = soft.frame(*args)
            sout = cp.rejected_soft2_apply(args[1], args[2], args[3], data)
            for key, rgb in (("B4_native_cpu", bout), ("soft2_native_cpu_rejected", sout)):
                out = selected[i].copy()
                # Exact source-word mask, obtained before these adapted outputs.
                out[..., :3][support["eligible"][i]] = rgb.astype(np.float16)[support["eligible"][i]]
                stacks[key].append(out)
            for key, model in models.items():
                out, diag = model.frame(source[i], raw[i], selected[i], arrays["input_depth"][i], normal[i],
                                       motion_px=motion, roughness=roughness[i], authority=np.ones((height, width), bool),
                                       render_extent=tuple(arrays["render_extent"]), crop_origin=tuple(arrays["crop_origin_render"][i]),
                                       frame_id=int(frame), reset=(i == 0))
                stacks[key].append(out)
                diagnostics[key].append({"frame": int(frame),
                    "eligible_pixels": int(diag["eligible"].sum()), "supported_pixels": int(diag["supported"].sum()),
                    "eligible_supported_pixels": int((diag["eligible"] & diag["supported"]).sum()),
                    "changed_pixels": int(diag["changed"].sum()),
                    "confidence_on_eligible": quantiles(diag["confidence"][support["eligible"][i]]),
                    "effective_samples_on_eligible": quantiles(diag["effective_samples"][support["eligible"][i]])})
        stacks = {key: np.asarray(value) for key, value in stacks.items()}
        outputs = {key: measure(arrays, lobe, value, support, (normal, roughness)) for key, value in stacks.items()}
        for key, measurement in outputs.items():
            if measurement["protected_rgba_changed_words_full_crop"] or measurement["alpha_changed_words_full_crop"]:
                raise AssertionError(f"{name}/{lobe}/{key}: protected-word contract failure")
        report["lobes"][lobe] = {"frozen_support": {k: array_hash(v) for k, v in support.items()},
                                   "outputs": outputs, "candidate_diagnostics": diagnostics,
                                   "elapsed_cpu_seconds": time.monotonic() - start}
        if plots:
            render_plots(name, lobe, arrays, stacks, outputs, support)
        selected_metric = outputs["selected"]["subsets"]["eligible"]["temporal_chroma_hf"]["p90"]
        print(json.dumps({"clip": name, "lobe": lobe, "selected_temporal_hf_p90": selected_metric,
                          "variants": {key: {"temporal_hf_p90": val["subsets"]["eligible"]["temporal_chroma_hf"]["p90"],
                                              "injected_hf_p99": val["subsets"]["eligible"]["injected_correction_chroma_hf"]["p99"]}
                                       for key, val in outputs.items() if key != "selected"}}), flush=True)
    return report


def render_plots(name, lobe, arrays, stacks, outputs, support):
    # Plotting is optional; the CPU experiment and metrics need only NumPy.
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/native-colour-matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    selected = stacks["selected"]
    baseline_q = float(np.percentile(luminance(selected), 99))
    exposure = 1.0 / max(baseline_q, 1e-6)
    frame_indices = [0, len(selected) - 1]
    columns = ["selected", "B4_native_cpu", "soft2_native_cpu_rejected", "log", "linear"]
    h, w = selected.shape[1:3]
    fig, axes = plt.subplots(2, 5, figsize=(15, max(4, 5.6 * h / w)), squeeze=False)
    for row, i in enumerate(frame_indices):
        for col, key in enumerate(columns):
            rgb = np.maximum(stacks[key][i, ..., :3].astype(np.float32), 0) * exposure
            image = (rgb / (1 + rgb)) ** (1 / 2.2)
            axes[row, col].imshow(image, interpolation="nearest", aspect="equal")
            axes[row, col].set_title(key.replace("_", " "), fontsize=9)
            axes[row, col].set_xticks([]); axes[row, col].set_yticks([])
            if col == 0:
                axes[row, col].set_ylabel(f"original frame {int(arrays['frame_indices'][i])}")
    fig.suptitle(f"{name} / {lobe}: physical pre-remod RGB, identical BASE exposure {exposure:.4g}\nCPU proposals on recorded RR; no final-game image or truth", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(HERE / "evidence" / f"{name}_{lobe}_panels.png", dpi=130)
    plt.close(fig)
    fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    for key in columns:
        frames = outputs[key]["subsets"]["eligible"]["temporal_chroma_hf_by_frame"]
        axes[0].plot([r["frame"] for r in frames], [r["p90"] for r in frames], label=key, marker=".")
        scores = []
        for i, frame in enumerate(stacks[key]):
            mask = support["eligible"][i].copy()
            mask[:12] = False; mask[-12:] = False
            mask[:, :12] = False; mask[:, -12:] = False
            delta = np.linalg.norm(hp_chroma(frame) - hp_chroma(selected[i]), axis=-1) / support["denominator"][i]
            scores.append(float(np.percentile(delta[mask], 99)) if mask.any() else 0)
        axes[1].plot(arrays["frame_indices"], scores, label=key, marker=".")
    axes[0].set_ylabel("paired chroma-HF p90\nfixed BASE denominator")
    axes[1].set_ylabel("injected chroma-HF p99\nfixed BASE denominator")
    axes[1].set_xlabel("Original capture frame (unlooped)")
    axes[0].legend(fontsize=8, ncol=2)
    for ax in axes:
        ax.grid(alpha=0.25)
        ax.set_ylim(bottom=0)
    fig.suptitle(f"{name} / {lobe}: observed residuals, not noise ground truth")
    fig.tight_layout()
    fig.savefig(HERE / "evidence" / f"{name}_{lobe}_time.png", dpi=140)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plots", action="store_true", help="Requires matplotlib; metrics do not")
    args = parser.parse_args()
    result = {"schema": "native-colour-captured-evaluation-v1", "executor": "cloud_cpu",
              "gpu_executed": False, "fresh_rr_executed": False,
              "protocol_sha256": sha256(HERE / "evidence/clip_evaluation_protocol.json"),
              "source_sha256": sha256(HERE / "native_colour.py"),
              "scope": "Proxy-only chronological CPU post-selection; truth, final albedo remod and display absent",
              "reports": [run_clip(name, args.plots) for name in ("bottle_track7", "foliage23", "facade16")],
              "glass_not_applied": "Aligned glass subset lacks original native RGBA alpha and noisy D/S inputs; not repurposed as equivalent native data"}
    (HERE / "evidence/clip_results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
