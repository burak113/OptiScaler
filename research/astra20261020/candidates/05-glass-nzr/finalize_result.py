"""Assemble RESULT.json and SHA256SUMS from already executed evidence.

This does not run or tune the candidate. A metadata-only follow-up commit may
record the preceding source/evidence commit with --source-revision <git-sha>.
The manifest excludes its own hash. RESULT excludes itself and the manifest
from its result hashes, avoiding a circular digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

CANDIDATE = Path(__file__).resolve().parent
REPO = CANDIDATE.parents[3]
PACKAGE = CANDIDATE.parents[1]
BASE = "5d7839a930106cf8fe1ba8dbbc6750509e7f26a8"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"),
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files():
    return sorted(p for p in CANDIDATE.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts
                  and p.suffix not in (".pyc", ".pyo"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision", help="Source/evidence commit, before packaging-only updates")
    args = parser.parse_args()
    revision = args.source_revision
    if revision is None and (CANDIDATE/"RESULT.json").exists():
        revision = read(CANDIDATE/"RESULT.json").get("source_revision")
    if revision is not None and not re.fullmatch(r"[0-9a-f]{40}", revision):
        parser.error("source revision must be a full lowercase Git commit SHA")

    registration = read(CANDIDATE/"REGISTRATION.json")
    holdout = read(CANDIDATE/"evidence/synthetic_holdout.json")
    development = read(CANDIDATE/"evidence/synthetic_development.json")
    full = read(CANDIDATE/"evidence/root_full_run/execution.json")
    rerun_path = CANDIDATE/"evidence/root_contract_rerun/execution.json"
    recorded = read(CANDIDATE/"evidence/recorded.json")
    review = read(CANDIDATE/"evidence/reviewer_adversarial_measurements.json")
    causal = read(CANDIDATE/"evidence/causal_probes.json")
    baseline_manifest = read(PACKAGE/"MANIFEST.json")
    code_hashes = {p.relative_to(CANDIDATE).as_posix(): digest(p) for p in files()
                   if p.suffix in (".py", ".hlsl", ".patch")}
    code_digest = hashlib.sha256(json.dumps(code_hashes, sort_keys=True,
                                 separators=(",", ":")).encode("utf-8")).hexdigest()
    all_paths = sorted({p.relative_to(REPO).as_posix() for p in files()} | {
        (CANDIDATE/"RESULT.json").relative_to(REPO).as_posix(),
        (CANDIDATE/"SHA256SUMS").relative_to(REPO).as_posix()})
    summary = {}
    for model, values in holdout["summary"].items():
        summary[model] = {
            "independent_seed_count": values["independent_seed_count"],
            "mean_detail_matched_scalar_strength": values["mean_detail_matched_scalar_strength"],
            "total_accepted_blocks": values["total_accepted_blocks"],
            "paired_candidate_blend05_to_control_ratios": values["paired_ratios"],
            "variant_mean_metrics": {
                variant: {metric: stats["mean"] for metric, stats in metrics.items()}
                for variant, metrics in values["variants"].items()},
        }
    result_hashes = {p.relative_to(CANDIDATE).as_posix(): digest(p) for p in files()
                     if p.name not in ("RESULT.json", "SHA256SUMS")}
    fixture_hashes = {(PACKAGE/entry["path"]).relative_to(REPO).as_posix(): entry["sha256"]
                      for entry in baseline_manifest["files"]
                      if entry["path"].startswith(("fixtures/", "portable/"))}

    result = {
        "schema": "glass-nzr-return-v1",
        "task_id": "05-glass-nzr",
        "base_tag": "astra-handoff-20261020",
        "resolved_tag_commit": BASE,
        "annotated_tag_object": "1f18416f5b99a0f78e147f362ac436ce2116ed22",
        "audited_production_commit": "87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd",
        "source_revision": revision,
        "source_revision_semantics": "Commit containing the measured candidate source and evidence. A later metadata-only commit records this ID and the final checksums; source bytes are pinned below.",
        "source_content_sha256": code_digest,
        "source_sha256": code_hashes,
        "changed_paths": all_paths,
        "change_scope": "Only research/astra20261020/candidates/05-glass-nzr/; production patch is an unapplied artifact. No baseline file is changed.",
        "branch": "astra/05-glass-nzr",
        "pr_target": "sol/26-integration",
        "acceptance_status": "keep_as_research",
        "visual_improvement_adoption": "reject",
        "default_enabled": False,
        "gpu_executed": False,
        "native_test_executed": False,
        "amd_rr_executed": False,
        "game_observed": False,
        "shader_compiled": False,
        "host_integrated": False,
        "performance": {"gpu_ms": None, "game_ms": None, "resident_vram_bytes": None},
        "dependency_versions": {"python": full["python"], "numpy": full["numpy"],
                                "platform": full["platform"], "requirement": "numpy==2.3.5",
                                "dependency_substitution": False},
        "protected_settings": {"diffuse_provider_radiance_scale": 16, "specular_provider_radiance_scale": 256,
                               "radiance_scale_semantics": "Multiply before the provider, restore by division afterward; candidate consumes the original domain",
                               "G2_G3_authority": "unchanged", "temporal_enabled": False,
                               "rr_fallback": True, "diffuse_rr": True, "reflection_history": True,
                               "glass_mode": 2, "glass_strength_nzr_fraction": 0.5},
        "candidate": {"kind": "Stateless, nonoverlapping 2x2 vector-Haar shrinkage of pre-Glass S-R correction",
                      "noise_scale": registration["noise_scale"],
                      "minimum_effective_support": registration["minimum_effective_support"],
                      "missing_uncertainty": "Exact selected-RGB identity before unchanged Glass policy",
                      "noise_assumption": "Supplied residual covariance including S/R cross-covariance and independent spatial errors; no native producer is provided",
                      "local_abstention": "Ineligible, mixed-surface, invalid/low/unknown support, odd border or inadmissible reconstructed RGB",
                      "source_interface": "src/UNCERTAINTY_INTERFACE.md"},
        "seeds": {"development": development["seeds"], "holdout": holdout["seeds"],
                  "noise_models": holdout["noise_models"],
                  "scenario_seed_construction": registration["scenario_seed_construction"],
                  "causal_H1": causal["H1_reference_support"]["seeds"],
                  "independent_phase_and_correlation": "Exact seeds in evidence/reviewer_adversarial_measurements.json",
                  "frames_per_sequence": holdout["frames_per_sequence"],
                  "holdout_sequence_count": len(holdout["per_sequence"]),
                  "holdout_tuning_permitted": False,
                  "generated_data": True,
                  "truth_scope": "Analytic stage surrogates, not actual provider/NZR histories. Count64 is supplied confidence, not 64 observed frames in a 32-frame sequence."},
        "cpu_execution": {
            "one_command": "python -B research/astra20261020/candidates/05-glass-nzr/run_checks.py",
            "baseline_before_changes": read(CANDIDATE/"evidence/runs.json"),
            "full_run": full,
            "final_contract_check": read(rerun_path) if rerun_path.exists() else None,
            "development": {key: development[key] for key in ("executor", "commands", "exit_code", "elapsed_seconds", "source_sha256")},
            "holdout": {key: holdout[key] for key in ("executor", "commands", "command_argv", "exit_code", "elapsed_seconds", "source_sha256")},
            "independent_bad_control_before_candidate": read(CANDIDATE/"evidence/reviewer_controls.json"),
            "independent_review": read(CANDIDATE/"evidence/reviewer_adversarial_runs.json"),
            "negative_control_semantics": "Known rejected soft2 and injected wrong-alpha implementations must exit1. The wrapper passes only when these failures are detected; visual quality is still rejected.",
            "candidate_test_count": 35,
            "baseline_suite_count": 4,
        },
        "fixture_sha256": fixture_hashes,
        "original_package_manifest_sha256": digest(PACKAGE/"MANIFEST.json"),
        "generated_inputs_and_masks": "Per-sequence input/mask hashes in synthetic development/holdout evidence; all recorded masks and array hashes in evidence/recorded.json. Masks are BASE-derived.",
        "measured_comparisons": {
            "holdout_scope": "Means of paired per-seed ratios; sparkle uses immutable quiet-flat mask, separately from all-active high-pass errors. Spatial false-contract model deliberately violates the claimed support assumption.",
            "holdout": summary,
            "recorded_glass": {
                "executor": "cloud Linux CPU root agent reading recorded historical arrays",
                "native_candidate_execution": False,
                "immutable_masks": recorded["glass"]["immutable_masks"],
                "fixed_base_metrics": recorded["glass"]["fixed_base_metrics"],
                "legacy_calibration_separate_variable_luma_denominator": recorded["glass"]["legacy_calibration_separate_variable_luma_denominator"],
                "candidate_missing_sidecar_identity": recorded["glass"]["subset_identity_checks"]["candidate_missing_sidecar"],
                "original_glass_alpha_available": False,
                "full_roi_8048_mask_reexecuted": False,
            },
            "independent_counterexamples": review,
            "causal_probes": causal,
        },
        "rejected_hypotheses": [
            {"claim": "This Haar shrinkage preserves detail generally", "status": "falsified_in_CPU_constructions", "evidence": "128-seed block-phase modulation and indistinguishable genuine-glint/noise worlds; evidence/reviewer_adversarial_measurements.json"},
            {"claim": "Lower high-frequency energy alone means better quality", "status": "falsified_by_controls", "evidence": "Blur loses text/texture/glints; frozen output loses real light/colour response"},
            {"claim": "History count alone determines independent residual uncertainty", "status": "falsified_as_a_general_interpretation", "evidence": "Capped-EMA AR(1) analysis and spatial correlation counterexample; live game covariance remains unknown"},
            {"claim": "Recorded final R/S uniquely identifies noisy reference versus selector versus gain", "status": "not_identifiable", "evidence": "Distinct latent decompositions produce the same output; native intermediate tensors required"},
            {"claim": "Ordinary surface motion validates reflected-feature transport", "status": "falsified_in_known_truth_toy", "evidence": "Moving virtual reflection on a fixed surface; actual game support still unmeasured"},
        ],
        "unresolved_risks": [
            "Cause of the recorded native glass grain remains unidentified without fit/selector/support intermediates.",
            "Required residual covariance, spatial dependence and effective support are unavailable for the recorded glass; honest candidate therefore abstains.",
            "Nonoverlapping Haar phase modulation and true-glint loss are structural rejection reasons, even if future shader parity passes.",
            "RGB alignment, unwarped geometry, crop parity and missing original alpha prevent native equivalence claims from the glass subset.",
            "No provider denoising, exact hardware sampler, full prior history, native encoding or final remodulation was ported.",
            "HLSL compilation, native scheduling/resource lifetime, debug layer, bytewise OFF/diffuse/alpha, GPU cost and final game verdict remain local gates owned by job08.",
        ],
        "required_local_work": {"gpu_request": "GPU_REQUEST.json", "blocked_observables": "BLOCKED_DATA_REQUEST.json",
                                "shader_build_request": "adapter/SHADER_BUILD.json",
                                "performance_comparators": ["preserved native OFF", "existing Glass Blend.5", "same-layout sham", "candidate only after valid support contract"]},
        "result_sha256_excluding_result_and_manifest": result_hashes,
        "checksum_manifest": "SHA256SUMS",
        "snapshot_notes": [
            "Original development all-active tail labels and original generic-API glint witness are retained under explicit prior-version filenames.",
            "Quiet-flat sparkle metric and all-eligible glint witness corrected applicability; candidate source and held-out parameters were not tuned after inspection.",
            "Traceback checkout/Python installation paths are normalized in delivered logs; assertion text, exit codes and recorded timings are preserved.",
            "Re-running experiments updates timing-bearing artifacts; SHA256SUMS describes the published snapshot, not a claim of identical future wall time.",
        ],
    }
    (CANDIDATE/"RESULT.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    (CANDIDATE/"SHA256SUMS").write_text("".join(
        f"{digest(p)}  {p.relative_to(CANDIDATE).as_posix()}\n" for p in files()
        if p.name != "SHA256SUMS"), encoding="utf-8")
    print(json.dumps({"result": "RESULT.json", "source_revision": revision,
                      "candidate_files": len(files()), "source_content_sha256": code_digest}))


if __name__ == "__main__":
    main()
