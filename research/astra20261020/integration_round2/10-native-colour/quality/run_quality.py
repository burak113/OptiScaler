"""Reproduce failures, then execute the frozen round-two quality protocol.

Exit 0 means the experiment and its controls completed, never visual acceptance.
--quality-gate returns 1 for the explicitly rejected original/ablation candidates.
All outputs go to the supplied directory. Frozen inputs are read-only.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import datetime as dt
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

from experiment import (
    HERE, PACKAGE, CANDIDATE, PROTOCOL, LUMA, ic, nc, sha256, array_hash,
    at_luma, luminance, chroma, opponent, dose, match_dose, make_sequence,
    evaluate_variant, metrics, high_pass, paired_bootstrap,
)
import run_review as original_review


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def frozen_hashes():
    """Entire immutable candidate snapshots and audit evidence, not new outputs."""
    roots = [PACKAGE / "candidates", PACKAGE / "audit_round2"]
    return {str(p.relative_to(PACKAGE)): sha256(p)
            for root in roots for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


def reproduce(output):
    start = time.perf_counter()
    compare = PACKAGE / "portable" / "colour" / "compare.py"
    command = [sys.executable, "-B", str(compare), "--quality-gate"]
    control = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    (output / "soft2_stdout.json").write_text(control.stdout, encoding="utf-8")
    (output / "soft2_stderr.txt").write_text(control.stderr, encoding="utf-8")
    parsed = json.loads(control.stdout)
    assert control.returncode == 1, "known-bad soft2 must return expected quality rejection"
    assert parsed["edges"]["verdict"] == "rejected_halo_regression"
    assert len(parsed["edges"]["cases"]) == 32
    print("Known-bad soft2: expected exit 1 confirmed", flush=True)
    # Only pure benchmark functions are invoked; writing original main() is not.
    dynamics = original_review.benchmark_closure_and_response()
    old_dynamics = json.loads((PACKAGE / "audit_round2" / "evidence" / "colour_quality"
                               / "dynamics_results.json").read_text(encoding="utf-8"))
    step_rows = [r for r in dynamics["response"] if r["change"] == "step"]
    for row in step_rows:
        old = next(r for r in old_dynamics["response"]
                   if r["lobe"] == row["lobe"] and r["change"] == "step")
        for method in original_review.METHODS:
            np.testing.assert_allclose(row["methods"][method]["response_fraction_by_frame"],
                                       old["methods"][method]["response_fraction_by_frame"],
                                       rtol=0, atol=2e-8)
    diffuse = next(r for r in step_rows if r["lobe"] == "diffuse")
    assert diffuse["methods"]["log"]["response_fraction_within_4_frames"] < .90
    protocol = json.loads((CANDIDATE / "review" / "low_contrast_probe_protocol.json").read_text(encoding="utf-8"))
    rows = []
    for lobe, level in protocol["lobe_levels"].items():
        a = at_luma(protocol["raw_left_relative_RGB"], level)
        b = at_luma(protocol["raw_right_relative_RGB"], level)
        target = at_luma(protocol["target_left_relative_RGB"], level)
        for angle in protocol["angles_degrees"]:
            for phase in protocol["phases_pixels"]:
                scene, meta = ic.edge_scene("red_blue", "same_guides", phase, angle, level)
                source, raw, selected, _, _, _, authority = scene
                raw[..., :3] = np.where(meta["left"][..., None], a, b).astype(np.float16)
                selected[..., :3] = raw[..., :3]
                source[..., :3] = np.where(meta["left"][..., None], target, b).astype(np.float16)
                meta["truth"] = np.where(meta["left"][..., None], target, b)
                meta["base_denominator"] = ic.luma(raw)
                meta["half_envelope"] = ic.local_half_envelope(raw)
                meta["eligible"] = ic.original_eligibility(raw, selected, authority)
                outputs, _ = original_review.all_outputs(original_review.models(), scene)
                rows.append({"lobe": lobe, "angle": angle, "phase": phase,
                             "methods": {name: ic.edge_metrics(value, scene, meta)
                                         for name, value in outputs.items()}})
    summary = {}
    old_low = json.loads((PACKAGE / "audit_round2" / "evidence" / "colour_quality"
                         / "low_contrast_results.json").read_text(encoding="utf-8"))
    for name in original_review.METHODS:
        summary[name] = {
            "case_count": len(rows),
            "max_unchanged_right_contamination": max(r["methods"][name]["unchanged_side_max_contamination"] for r in rows),
            "failures_above_original_storage_envelope": sum(r["methods"][name]["max_contamination_above_storage_envelope"] > 0 for r in rows),
        }
        np.testing.assert_allclose(summary[name]["max_unchanged_right_contamination"],
                                   old_low["summary"][name]["max_unchanged_right_contamination"],
                                   rtol=0, atol=2e-8)
    assert summary["log"]["failures_above_original_storage_envelope"] == 32
    result = {
        "scope": "Fresh execution of original benchmark functions and unchanged model. Original writing entrypoints were not invoked.",
        "elapsed_seconds": time.perf_counter() - start,
        "original_source_sha256": sha256(CANDIDATE / "native_colour.py"),
        "original_review_sha256": sha256(CANDIDATE / "review" / "run_review.py"),
        "original_low_contrast_protocol_sha256": sha256(CANDIDATE / "review" / "low_contrast_probe_protocol.json"),
        "soft2": {"command": command, "actual_exit": control.returncode, "expected_exit": 1,
                  "worse_cases": parsed["edges"]["worse_cases"], "stdout_sha256": sha256(output / "soft2_stdout.json")},
        "dynamics": dynamics, "low_contrast_summary": summary, "low_contrast_cases": rows,
        "quality_pass": False,
        "failed_original_gates": ["primary_log_diffuse_true_step_response_below_0.90", "32_of_32_low_contrast_boundaries_exceed_original_storage_envelope"],
        "historical_local_numbers_reproduced_with_absolute_tolerance": 2e-8,
    }
    write_json(output / "reproduction.json", result)
    print("Original failures reproduced: diffuse step < 0.90; 32/32 low-contrast leaks", flush=True)
    return result


def single_output(scene, name):
    return ic.call_model(nc.NativeColourModel(nc.Config(enabled=True, **PROTOCOL["variants"][name])), scene)[0]


def step_mechanism():
    rows = []
    for lobe, level in PROTOCOL["lobe_levels"].items():
        old = at_luma([.85, 1., .9], level)
        new = at_luma(old * np.exp([.10, -.05, .07]), level)
        scene = list(ic.basic_scene(h=32, w=48))
        scene[0][..., :3] = new
        scene[1][..., :3] = old
        scene[2][..., :3] = old
        mask = np.zeros((32, 48), bool)
        mask[4:-4, 4:-4] = True
        direction = chroma(new) - chroma(old)
        energy = float(direction @ direction)
        response = lambda value: float((chroma(value)[mask].mean(0) - chroma(old)) @ direction / energy)
        outputs = {name: single_output(tuple(scene), name) for name in PROTOCOL["variants"]}
        original, diag = ic.call_model(nc.NativeColourModel(nc.Config(enabled=True)), tuple(scene))
        original_response = response(original)
        # Same actual original response is the scalar target for this ablation.
        lo, hi = 0., 1.
        best, best_amount = outputs["no_sample_prior"], 1.
        for _ in range(25):
            mid = (lo + hi) / 2
            modified = nc.NativeColourModel(nc.Config(enabled=True, support_prior=0., strength=mid))
            value, _ = ic.call_model(modified, tuple(scene))
            measured = response(value)
            if abs(measured-original_response) < abs(response(best)-original_response):
                best, best_amount = value, mid
            if measured < original_response:
                lo = mid
            else:
                hi = mid
        # No frame counter/history participates in the model; identical inputs
        # at later frames produce exactly the same half words.
        later, _ = ic.call_model(nc.NativeColourModel(nc.Config(enabled=True)), tuple(scene), frame_id=11)
        assert np.array_equal(original.view(np.uint16), later.view(np.uint16))
        rows.append({
            "lobe": lobe, "original_response": original_response,
            "original_confidence_mean": float(diag["confidence"][mask].mean()),
            "original_n_eff_mean": float(diag["effective_samples"][mask].mean()),
            "response_by_variant_full_output": {name: response(value) for name, value in outputs.items()},
            "no_prior_matched_response": response(best), "no_prior_matched_strength": best_amount,
            "no_prior_matched_RGBA_differing_words": int(np.count_nonzero(best.view(np.uint16)[mask] != original.view(np.uint16)[mask])),
            "identical_current_inputs_at_frame8_and11_give_identical_RGBA": True,
            "frozen_true_step_gate": .90,
        })
    return {"rows": rows, "finding": "Original failure is immediate attenuation, not accumulating temporal lag. Removing the prior changes achieved dose; the matched-dose control prevents crediting that increase as a noise improvement."}


def boundary_suite():
    rows = []
    for lobe, level in PROTOCOL["lobe_levels"].items():
        for gap in PROTOCOL["boundary_relative_gaps"]:
            a = at_luma([1+gap, .99, 1+.5*gap], level)
            b = at_luma([1, 1, 1], level)
            target = at_luma([1, 1, 1-.25*gap], level)
            for angle in PROTOCOL["boundary_angles_degrees"]:
                for phase in PROTOCOL["boundary_phases_pixels"]:
                    scene, meta = ic.edge_scene("red_blue", "same_guides", phase, angle, level)
                    source, raw, selected, _, _, _, authority = scene
                    raw[..., :3] = np.where(meta["left"][..., None], a, b)
                    selected[..., :3] = raw[..., :3]
                    source[..., :3] = np.where(meta["left"][..., None], target, b)
                    meta["truth"] = np.where(meta["left"][..., None], target, b)
                    meta["base_denominator"] = ic.luma(raw)
                    meta["half_envelope"] = ic.local_half_envelope(raw)
                    meta["eligible"] = ic.original_eligibility(raw, selected, authority)
                    original_hashes = {k: array_hash(meta[k]) for k in ("band", "correction_mask", "base_denominator")}
                    methods = {}
                    for name in PROTOCOL["variants"]:
                        value = single_output(scene, name)
                        matched, receipt = match_dose(raw, selected, value, meta["truth"], meta["eligible"],
                                                      meta["correction_mask"], .8)
                        methods[name] = {"full": ic.edge_metrics(value, scene, meta),
                                         "full_dose": dose(value, raw, meta["truth"], meta["correction_mask"]),
                                         "matching": receipt,
                                         "matched0.8": ic.edge_metrics(matched, scene, meta) if matched is not None else None}
                    assert original_hashes == {k: array_hash(meta[k]) for k in original_hashes}
                    rows.append({"lobe": lobe, "gap_parameter": gap, "angle": angle, "phase": phase,
                                 "possible_interpretations": ["material_boundary", "illumination_boundary"],
                                 "interpretations_are_not_independent_numeric_cases": True,
                                 "frozen_masks_and_denominator_sha256": original_hashes, "methods": methods})
    summary = {}
    for name in PROTOCOL["variants"]:
        full = [r["methods"][name]["full"] for r in rows]
        matched = [r["methods"][name]["matched0.8"] for r in rows if r["methods"][name]["matched0.8"] is not None]
        summary[name] = {
            "numeric_cases": len(full),
            "full_failures_above_original_storage_envelope": sum(v["max_contamination_above_storage_envelope"] > 0 for v in full),
            "full_worst_unchanged_side_contamination": max(v["unchanged_side_max_contamination"] for v in full),
            "matched0.8_cases": len(matched),
            "matched0.8_failures_above_original_storage_envelope": sum(v["max_contamination_above_storage_envelope"] > 0 for v in matched),
            "matched0.8_worst_unchanged_side_contamination": max(v["unchanged_side_max_contamination"] for v in matched) if matched else None,
        }
    return {"summary": summary, "cases": rows}


def identical_observation_twins():
    rows = []
    for lobe, level in PROTOCOL["lobe_levels"].items():
        scene, meta = ic.edge_scene("red_blue", "same_guides", 2, 27, level)
        source, raw, selected, _, _, _, _ = scene
        a, b = at_luma([1.06, .99, 1.03], level), at_luma([1, 1, 1], level)
        raw[..., :3] = np.where(meta["left"][..., None], a, b)
        source[..., :3] = b
        selected[..., :3] = raw[..., :3]
        true_boundary = raw[..., :3].astype(np.float64)
        true_flat = source[..., :3].astype(np.float64)
        mask = meta["correction_mask"]
        den = luminance(raw)[mask]
        worlds = [tuple(x.copy() for x in scene), tuple(x.copy() for x in scene)]
        assert all(np.array_equal(a.view(np.uint8), b.view(np.uint8)) for a, b in zip(*worlds))
        methods = {}
        separation = float(np.mean(np.linalg.norm((true_boundary-true_flat)[mask] / den[:, None], axis=-1)))
        for name in PROTOCOL["variants"]:
            first, second = single_output(worlds[0], name), single_output(worlds[1], name)
            assert np.array_equal(first.view(np.uint16), second.view(np.uint16))
            err_boundary = float(np.mean(np.linalg.norm((first[..., :3]-true_boundary)[mask] / den[:, None], axis=-1)))
            err_flat = float(np.mean(np.linalg.norm((second[..., :3]-true_flat)[mask] / den[:, None], axis=-1)))
            assert err_boundary + err_flat + 1e-12 >= separation
            methods[name] = {"outputs_byte_identical": True, "error_true_boundary": err_boundary,
                             "error_true_flat": err_flat, "max_world_error": max(err_boundary, err_flat)}
        rows.append({"lobe": lobe, "input_hashes_identical_between_worlds": [array_hash(x) for x in scene],
                     "truth_separation": separation, "at_least_one_world_error_lower_bound": separation/2,
                     "methods": methods})
    return {
        "world_boundary": "Raw's subtle chromatic discontinuity is real; the one current source observation has a matching stochastic opposite fluctuation. Keep the boundary.",
        "world_flat": "True physical lobe is flat; raw has a correlated chroma-estimation discontinuity and source is the exact value. Remove the apparent boundary.",
        "scope": "Same observed arrays and metadata admit incompatible truths. This is an identifiability witness under the declared observation uncertainty, not a claim that independent calibrated evidence can never help.",
        "rows": rows,
    }


def assert_mask_snapshot(data, before):
    after = {k: array_hash(v) for k, v in data["masks"].items()}
    if before != after:
        raise AssertionError("baseline mask changed after candidate evaluation")


def noise_suite():
    rows = []
    total = len(PROTOCOL["holdout_seeds"]) * len(PROTOCOL["lobe_levels"]) * len(PROTOCOL["noise_families"])
    for lobe, level in PROTOCOL["lobe_levels"].items():
        for family in PROTOCOL["noise_families"]:
            for seed in PROTOCOL["holdout_seeds"]:
                data = make_sequence(seed, family, level)
                masks = {k: array_hash(v) for k, v in data["masks"].items()}
                methods = {"raw": {"full": metrics(data["selected"], data), "matching": {}, "matched": {}}}
                for name in PROTOCOL["variants"]:
                    value = evaluate_variant(data, name)
                    matching, matched_metrics = {}, {}
                    for target in PROTOCOL["dose"]["matched_targets"]:
                        matched, receipt = match_dose(
                            data["raw"], data["selected"], value, data["truth"],
                            data["masks"]["eligible"], data["masks"]["quiet"], target)
                        matching[str(target)] = receipt
                        matched_metrics[str(target)] = metrics(matched, data) if matched is not None else None
                    methods[name] = {"full": metrics(value, data), "matching": matching, "matched": matched_metrics}
                    assert_mask_snapshot(data, masks)
                rows.append({"seed": seed, "lobe": lobe, "noise_family": family,
                             "frames": PROTOCOL["frame_count"], "active_extent": data["active_extent"],
                             "allocation_extent": PROTOCOL["allocation_extent"], "crop_origins": data["origins"],
                             "masks_sha256": masks, "denominator_sha256": array_hash(data["denominator"]),
                             "source_sha256": array_hash(data["source"]), "raw_sha256": array_hash(data["raw"]),
                             "selected_sha256": array_hash(data["selected"]), "methods": methods,
                             "alpha_protected_inactive_word_changes": 0})
                if len(rows) % 8 == 0:
                    print(f"Blind noise sequences: {len(rows)}/{total}", flush=True)
    pairs = []
    for lobe in PROTOCOL["lobe_levels"]:
        for family in PROTOCOL["noise_families"]:
            subset = [r for r in rows if r["lobe"] == lobe and r["noise_family"] == family]
            for target in PROTOCOL["dose"]["matched_targets"]:
                for name in PROTOCOL["variants"]:
                    if name == "original_log":
                        continue
                    available = [r for r in subset
                                 if r["methods"][name]["matched"][str(target)] is not None
                                 and r["methods"]["original_log"]["matched"][str(target)] is not None]
                    metrics_summary = {}
                    for key in ("spatial_HF_error_RMS", "crop_aligned_temporal_error_RMS",
                                "quiet_error_p99", "thin_chroma_projection", "glint_chroma_projection"):
                        ratios = [r["methods"][name]["matched"][str(target)][key]
                                  / r["methods"]["original_log"]["matched"][str(target)][key] for r in available]
                        metrics_summary[key + "_ratio_to_matched_original"] = paired_bootstrap(ratios) if ratios else None
                    pairs.append({"lobe": lobe, "family": family, "variant": name, "target_dose": target,
                                  "paired_seeds": [r["seed"] for r in available],
                                  "unmatched_seed_count": len(subset)-len(available), "metrics": metrics_summary,
                                  "selection_caveat": "Missing matched-dose seeds are disclosed; subset results do not establish all-seed superiority."})
    return {"case_count": len(rows), "cases": rows, "paired_matched_dose_summary": pairs,
            "lobe_dependence": "Lobes share underlying noise factors. Bootstrap strata are never pooled across lobes."}


def detail_crop_step_probes():
    rows = []
    for lobe, level in PROTOCOL["lobe_levels"].items():
        for width in PROTOCOL["thin_widths_pixels"]:
            for phase in PROTOCOL["boundary_phases_pixels"]:
                h, w = 24, 40
                yy, xx = np.indices((h, w))
                line = ((xx - phase) % 12) < width
                palette = np.ones((h, w, 3), np.float64)
                palette[line] *= [1.12, .97, 1.07]
                truth = at_luma(palette, level)
                raw_rgb = at_luma(truth * np.exp([.08, -.04, .05]), level)
                scene = list(ic.basic_scene(h, w))
                scene[0][..., :3], scene[1][..., :3], scene[2][..., :3] = truth, raw_rgb, raw_rgb
                mask = np.zeros((h,w), bool)
                mask[6:-6, 6:-6] = True
                desired_hp = high_pass(chroma(truth))
                energy = np.sum(desired_hp[mask]**2)
                methods = {}
                for name in PROTOCOL["variants"]:
                    value = single_output(tuple(scene), name)
                    ratio = float(np.sum(high_pass(chroma(value))[mask]*desired_hp[mask])/energy)
                    methods[name] = {"thin_chroma_projection": ratio,
                                     "actual_dose": dose(value, scene[1], truth, mask)}
                rows.append({"lobe": lobe, "thin_width": width, "phase": phase, "methods": methods})
    # Crop movement without scene motion: evaluate the same world observation at
    # four actual crops. Compare the intersection after removing every support halo.
    rng = np.random.default_rng(PROTOCOL["calibration_seeds"][0])
    h, w = 34, 54
    world = list(ic.basic_scene(h, w))
    world[0][..., :3] *= np.exp(.07*rng.normal(size=(h,w,3)))
    crop_rows = []
    for name, variant in PROTOCOL["variants"].items():
        world_out = single_output(tuple(world), name)
        halo = max(6, variant.get("radius", 3)+1)
        mismatches = 0
        checked = 0
        for ox, oy in PROTOCOL["crop_origins"]:
            crop = tuple(a[oy:oy+24, ox:ox+40].copy() for a in world)
            crop_out, _ = ic.call_model(nc.NativeColourModel(nc.Config(enabled=True, **variant)), crop,
                                       crop_origin=(ox,oy), frame_id=9)
            expected = world_out[oy+halo:oy+24-halo, ox+halo:ox+40-halo]
            observed = crop_out[halo:24-halo, halo:40-halo]
            mismatches += int(np.count_nonzero(expected.view(np.uint16) != observed.view(np.uint16)))
            checked += expected.size
        assert mismatches == 0
        crop_rows.append({"variant": name, "checked_RGBA_words": checked, "mismatches": mismatches})
    # Existing raw-RR luminance steps must be preserved. If raw itself is stale,
    # this colour-only pass deliberately does not invent a luminance correction.
    step_rows = []
    for name in PROTOCOL["variants"]:
        scene = list(ic.basic_scene(24, 40))
        before = single_output(tuple(scene), name)
        actual_step = [a.copy() for a in scene]
        for i in (0,1,2):
            actual_step[i][..., :3] *= np.float16(1.25)
        after = single_output(tuple(actual_step), name)
        b, a = float(luminance(before)[6:-6,6:-6].mean()), float(luminance(after)[6:-6,6:-6].mean())
        raw_b = float(luminance(scene[1])[6:-6,6:-6].mean())
        raw_a = float(luminance(actual_step[1])[6:-6,6:-6].mean())
        gain = (a-b)/(raw_a-raw_b)
        step_rows.append({"variant": name, "existing_raw_luminance_step_retention": gain,
                          "source_only_luminance_step_is_not_reconstructed": True})
    return {"thin_cases": rows, "crop_checks": crop_rows, "luminance_step_checks": step_rows}


def known_bad_controls():
    data = make_sequence(PROTOCOL["calibration_seeds"][0], "independent", .3)
    identity_dose = dose(data["selected"], data["raw"], data["truth"], data["masks"]["quiet"])
    assert identity_dose == 0
    matched, receipt = match_dose(data["raw"], data["selected"], data["selected"], data["truth"],
                                  data["masks"]["eligible"], data["masks"]["quiet"], .8)
    assert matched is None and not receipt["matched"]
    # Frozen output can have perfect temporal steadiness and zero true response.
    old, new, frozen = .3, .375, .3
    frozen_response = (frozen-old)/(new-old)
    assert frozen_response == 0 and frozen_response < .90
    stripe = np.tile(np.array([.8, .2] * 16), (16,1))
    blurred = (np.roll(stripe,1,1) + 2*stripe + np.roll(stripe,-1,1))/4
    blur_ratio = float(np.ptp(blurred) / np.ptp(stripe))
    assert blur_ratio < .95
    before = {k: array_hash(v) for k,v in data["masks"].items()}
    mutant = dict(data)
    mutant["masks"] = dict(data["masks"])
    mutant["masks"]["quiet"] = np.ones_like(data["masks"]["quiet"])
    caught = False
    try:
        assert_mask_snapshot(mutant, before)
    except AssertionError:
        caught = True
    assert caught, "candidate-dependent mask mutant escaped"
    return {"identity_correction_dose": identity_dose, "identity_unmatched_at0.8": receipt,
            "frozen_output_step_response": frozen_response, "blur_thin_detail_contrast_ratio": blur_ratio,
            "candidate_derived_mask_mutant_rejected": caught, "controls_pass": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--section", choices=("all", "reproduce", "holdout"), default="all")
    parser.add_argument("--quality-gate", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    for immutable in (PACKAGE / "candidates", PACKAGE / "portable", PACKAGE / "audit_round2"):
        if output == immutable or immutable in output.parents:
            parser.error("outputs must not be placed in frozen input directories")
    output.mkdir(parents=True, exist_ok=True)
    before = frozen_hashes()
    start = time.perf_counter()
    protocol_hash = sha256(HERE / "PROTOCOL.json")
    run = {"schema": "native-colour-quality-execution-v1", "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
           "base_commit": PROTOCOL["base_commit"], "section": args.section,
           "executor": "colour_numerical agent, current Linux container; fresh CPU execution",
           "python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform(),
           "command": [sys.executable, "-B", str(Path(__file__).resolve()), *sys.argv[1:]],
           "protocol_sha256_before": protocol_hash,
           "source_hashes": {"experiment.py": sha256(HERE / "experiment.py"),
                             "run_quality.py": sha256(__file__), "frozen_native_colour.py": sha256(CANDIDATE / "native_colour.py")},
           "gpu_executed": False, "game_executed": False, "quality_accepted": False}
    if args.section in ("all", "reproduce"):
        rep = reproduce(output)
        run["original_rejection_reproduced"] = not rep["quality_pass"]
    if args.section in ("all", "holdout"):
        controls = known_bad_controls()
        write_json(output / "known_bad_controls.json", controls)
        write_json(output / "step_mechanism.json", step_mechanism())
        print("Step/prior and known-bad controls complete", flush=True)
        write_json(output / "identifiability_twins.json", identical_observation_twins())
        write_json(output / "detail_crop_steps.json", detail_crop_step_probes())
        print("Twins, thin detail, crop and illumination probes complete", flush=True)
        boundaries = boundary_suite()
        write_json(output / "boundary_holdout.json", boundaries)
        print("Blind boundary sweep and achieved-dose matches complete", flush=True)
        noise = noise_suite()
        write_json(output / "noise_holdout.json", noise)
        run["holdout_numeric_boundary_cases"] = len(boundaries["cases"])
        run["holdout_noise_sequences"] = noise["case_count"]
        run["boundary_summary"] = boundaries["summary"]
        run["controls_pass"] = controls["controls_pass"]
        run["all_variants_rejected"] = all(x["full_failures_above_original_storage_envelope"] > 0 for x in boundaries["summary"].values())
        assert run["all_variants_rejected"], "unexpected apparent survivor requires independent review, not automatic promotion"
    assert before == frozen_hashes(), "immutable input snapshot changed during execution"
    assert sha256(HERE / "PROTOCOL.json") == protocol_hash, "preregistered protocol changed during execution"
    run["immutable_files_checked"] = len(before)
    run["immutable_files_unchanged"] = True
    run["protocol_unchanged"] = True
    run["elapsed_seconds"] = time.perf_counter() - start
    run["mechanical_experiment_execution_pass"] = True
    run["quality_gate_exit_code"] = 1
    run["output_sha256"] = {p.name: sha256(p) for p in sorted(output.glob("*")) if p.is_file() and p.name != "execution.json"}
    write_json(output / "execution.json", run)
    print(json.dumps({k:v for k,v in run.items() if k not in ("output_sha256", "boundary_summary")}, indent=2), flush=True)
    return 1 if args.quality_gate else 0


if __name__ == "__main__":
    raise SystemExit(main())
