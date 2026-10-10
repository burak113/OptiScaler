"""Rescore saved CPU candidate outputs against the predeclared dark grain gate.

Launches no GPU, modifies no candidate or original M3 source, preserves every
per-scale success/failure. The baseline threshold is written before reading
the candidate image array for that capture/repeat.
"""
from pathlib import Path
import argparse
import gc
import json
import numpy as np
from fsrd_recovery_detail_grain_metrics import score_dark, checks_dark, SPECIFICATION
from test_fsrd_recovery_detail_replay import original_gate, extract, checked_output, save, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture", nargs="+", default=["haze", "water1", "water2", "reveal1"])
    parser.add_argument("--repeat", nargs="+", type=int, default=[0, 1])
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--candidate", help="Fixed candidate ID when the saved report contains a grid")
    args = parser.parse_args()
    args.output = checked_output(args.output)
    args.cache = checked_output(args.cache)
    paths = [Path(__file__), Path(__file__).with_name("fsrd_recovery_detail_grain_metrics.py")]
    before = {str(p): sha256(p) for p in paths}
    save(args.output/"specification_at_start.json", dict(specification=SPECIFICATION,
         source_sha_at_start=before, additive_original_m3_gate=True))
    gate = original_gate(Path("F:/FSRD/recovery_v2/scripts/eval"))
    records = []
    for repeat in args.repeat:
        for name in args.capture:
            capture = gate.Capture(name)
            root = checked_output(args.output/name/f"repeat{repeat}")
            source_root = args.cpu_output/name/f"repeat{repeat}"
            metrics_path = source_root/"metrics.json"
            original = json.loads(metrics_path.read_text())
            evidence = Path("E:/FSRD/recovery_v2/eval")/capture.id/f"repeat{repeat}"
            inputs, input_identity = extract(evidence/"rr_inputs.npz", ("motion",),
                                             args.cache/capture.id/f"repeat{repeat}"/"inputs")
            rr, rr_identity = extract(evidence/"rr_only/replay.npz", ("output",),
                                     args.cache/capture.id/f"repeat{repeat}"/"rr")
            if (original["source_files"]["inputs"] != input_identity or
                original["source_files"]["rr"] != rr_identity):
                raise AssertionError("Candidate and actual RR input fingerprints differ")
            runs, _ = gate.static_ranges(capture, inputs)
            truth = gate.truth_for_runs(capture, runs)
            baseline_m3 = gate.score(lambda f: np.asarray(rr["output"][f, ..., :3], np.float32),
                                     runs, truth, capture.H, capture.W)
            if original["baselines"] != baseline_m3:
                raise AssertionError("Exact original M3/raw truth parity failed")
            baseline = score_dark(lambda f: np.asarray(rr["output"][f, ..., :3], np.float32),
                                  runs, truth, capture.H, capture.W, gate.blur)
            save(root/"thresholds_before_candidate.json", dict(baseline=baseline,
                rule=SPECIFICATION["threshold"], raw_truth_source=gate.source_hashes,
                original_m3_parity=True, source_metrics_sha256=sha256(metrics_path)))
            candidates = [c for c in original["candidates"] if not args.candidate or c["id"] == args.candidate]
            if not candidates:
                raise ValueError("Fixed candidate missing")
            frame_ids = sorted(set(f for frames in runs for f in frames))
            slots = {f: i for i, f in enumerate(frame_ids)}
            rows = []
            for candidate in candidates:
                candidate_path = source_root/(candidate["id"]+".npy")
                array = np.load(candidate_path, mmap_mode="r", allow_pickle=False)
                if array.shape != (len(frame_ids), capture.H, capture.W, 3):
                    raise AssertionError("Candidate extent/static frame count changed")
                measured = score_dark(lambda f: np.asarray(array[slots[f]], np.float32), runs, truth,
                                      capture.H, capture.W, gate.blur)
                checks = checks_dark(measured, baseline)
                rows.append(dict(id=candidate["id"], runs=measured, checks=checks,
                    dark_grain_passed=all(c["passed"] for c in checks),
                    original_m3_passed=candidate["passed"], source=str(candidate_path),
                    source_sha256=sha256(candidate_path)))
                array._mmap.close()
            report = dict(capture=name, repeat=repeat, static_runs=[[f[0], f[-1]] for f in runs],
                baseline=baseline, candidates=rows, original_m3_criteria_changed=False,
                source_metrics=str(metrics_path), source_metrics_sha256=sha256(metrics_path),
                specification=SPECIFICATION, input_identity=input_identity, rr_identity=rr_identity)
            save(root/"metrics.json", report)
            records.append(report)
            print(json.dumps(dict(capture=name, repeat=repeat,
                passing=[c["id"] for c in rows if c["dark_grain_passed"]],
                checks=[c["checks"] for c in rows])), flush=True)
            for array in [*inputs.values(), *rr.values()]:
                array._mmap.close()
            gc.collect()
    common = {c["id"] for c in records[0]["candidates"] if c["original_m3_passed"] and c["dark_grain_passed"]}
    for record in records[1:]:
        common &= {c["id"] for c in record["candidates"] if c["original_m3_passed"] and c["dark_grain_passed"]}
    after = {str(p): sha256(p) for p in paths}
    if before != after:
        raise AssertionError("Metric source changed during replay")
    complete = set(args.capture) == {"haze", "water1", "water2", "reveal1"} and set(args.repeat) == {0, 1}
    result = dict(complete=complete, passed=complete and bool(common), shared_survivors=sorted(common),
        total_records=sum(len(r["static_runs"]) for r in records), source_start=before, source_finish=after,
        gpu_executed=False, production_enabled=False,
        records=[str(args.output/r["capture"]/f"repeat{r['repeat']}"/"metrics.json") for r in records])
    save(args.output/"summary.json", result)
    return int(complete and not common)


if __name__ == "__main__":
    raise SystemExit(main())
