import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def compact(metrics):
    result = {"active_fraction": metrics["active_fraction"]}
    for window in ("full", "mature"):
        item = metrics[window]
        result[window] = {key: item[key] for key in item if key != "score"}
        result[window].update({key: item["score"][key] for key in (
            "rmse", "bias_rgb", "broad_tone_rms", "residual_temporal_std")})
    return result

source = json.loads((ROOT / "results.json").read_text())
result = {
    "schema": "physical-beta-history-feasibility-compact-v1",
    "quality_accepted": False,
    "native_measured": False,
    "native_response_reused": False,
    "results_sha256": sha(ROOT / "results.json"),
    "preregistration_sha256": source["preregistration_sha256"],
    "prototype_sha256": source["prototype_sha256"],
    "script_sha256": source["script_sha256"],
    "self_checks": source["self_checks"],
    "all_original_source_control_report_hashes_unchanged": all(row["source_files_unchanged"] for row in source["rows"]),
    "all_13_authenticated_fixtures_exact": all(row["authenticated_fixture_exact_match"] for row in source["rows"]),
    "rows": [{"scene": row["scene"], "provenance": row["provenance"], **compact(row["metrics"])} for row in source["rows"]],
    "counterexamples": [{"family": row["family"], **compact(row["metrics"])} for row in source["counterexamples"]],
    "conclusions": [
        "Material mature source-pilot temporal noise is lower; mature weak-checker absolute gain remains within five percent in this fixture.",
        "Weak-checker full-sequence gain still falls to 0.693; raw inactive startup and reset frames retain source noise.",
        "Rank-zero wave, moving-light and noisy-guide families are exact raw/inactive: no correction or wave solution.",
        "Slow true amplitude drift is averaged into approximately 0.925 mature gain: three-SE innovation is insufficient for this adversary.",
        "Persistent guide/source-shared spatial bias remains approximately 0.0119 RMSE despite almost zero temporal variation.",
        "Source-pilot CPU feasibility only. No new native response, runtime implementation or general/game quality acceptance."
    ],
    "limitations": source["limitations"]
}
(ROOT / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps({"summary_sha256": sha(ROOT / "summary.json"), "rows": len(result["rows"]), "counterexamples": len(result["counterexamples"])}))
