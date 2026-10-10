"""Actual RecoveryDetail GPU outputs, unchanged 12-record M3 and CPU equivalence.

Run only after receiving the serialized GPU slot. RR itself is not rerun: read
the published actual AMD RR pairs. Gate definitions/truth are unchanged.
"""
from pathlib import Path
import argparse
import gc
import itertools
import json
import os
import time
import numpy as np
from fsrd_recovery_detail_gpu import Dispatcher, DetailState, PRE, PREFIX, SCHEMAS
from fsrd_recovery_detail_reference import PairedBandMoments
from test_fsrd_recovery_detail_replay import original_gate, extract, checked_output, save, sha256, checks_for


def evaluate(args, name, repeat, gate, dispatcher):
    start = time.monotonic()
    capture = gate.Capture(name)
    evidence = args.evidence / "eval" / capture.id / f"repeat{repeat}"
    root = checked_output(args.output / name / f"repeat{repeat}")
    cache = checked_output(args.cache / capture.id / f"repeat{repeat}")
    p, input_identity = extract(evidence / "rr_inputs.npz",
        ("U", "V", "qs8", "qd8", "packed", "depth", "motion"), cache / "inputs")
    rr, rr_identity = extract(evidence / "rr_only/replay.npz", ("output", "spec", "diffuse"), cache / "rr")
    old, old_identity = extract(evidence / "pedestal/replay.npz", ("output",), cache / "old")
    arrays = [*p.values(), *rr.values(), *old.values()]
    if any(array.shape[:3] != (capture.n, capture.H, capture.W) for array in arrays):
        raise ValueError("Published capture extent mismatch")
    runs, _ = gate.static_ranges(capture, p)
    truth = gate.truth_for_runs(capture, runs)
    baseline = gate.score(lambda f: np.asarray(rr["output"][f, ..., :3], np.float32), runs, truth, capture.H, capture.W)
    old_metrics = gate.score(lambda f: np.asarray(old["output"][f, ..., :3], np.float32), runs, truth, capture.H, capture.W)
    original_path = evidence / "M3_metrics.json"
    original = json.loads(original_path.read_text())
    parity = (baseline == original["baselines"]["all through RR, no recovery"] and
              old_metrics == original["baselines"]["Floor pedestal (old)"] and
              [[run[0], run[-1]] for run in runs] == original["static_runs"])
    save(root / "baseline_parity.json", dict(passed=parity, original=str(original_path),
        original_sha256=sha256(original_path), measured=baseline, old=old_metrics))
    if not parity:
        raise AssertionError("Original metric parity failed before GPU candidate evaluation")
    published_cpu = json.loads((args.cpu_reference / name / f"repeat{repeat}" / "metrics.json").read_text())
    cpu_candidate = published_cpu["candidates"][0]
    if (not cpu_candidate["passed"] or cpu_candidate["id"] != "a0.1_k2_s1_d1_broad_soft_radiance" or
        published_cpu["baselines"] != baseline or
        published_cpu["source_files"]["inputs"] != input_identity or
        published_cpu["source_files"]["rr"] != rr_identity):
        raise AssertionError("CPU accepted profile/input identity mismatch")
    frames = sorted(set(itertools.chain.from_iterable(runs)))
    slots = {frame: index for index, frame in enumerate(frames)}
    gpu_spool = np.lib.format.open_memmap(root / "actual_gpu_output.npy", mode="w+", dtype=np.float16,
        shape=(len(frames), capture.H, capture.W, 3))
    cpu_spool = np.lib.format.open_memmap(root / "matched_cpu_output.npy", mode="w+", dtype=np.float16,
        shape=gpu_spool.shape)
    gpu = DetailState(dispatcher, capture.W, capture.H, .1)
    states = {lobe: PairedBandMoments((capture.H, capture.W), 1, .1) for lobe in ("specular", "diffuse")}
    differences = []
    for frame in range(max(frames)+1):
        taps, reuse, _ = gate.partial_mapping(p, frame, capture)
        base = np.asarray(rr["output"][frame, ..., :3], np.float32)
        addition = np.zeros_like(base)
        for lobe, source_key, rr_key, guide_key in (("specular", "U", "spec", "qs8"),
                                                   ("diffuse", "V", "diffuse", "qd8")):
            observation = (np.asarray(p[source_key][frame, ..., :3], np.float32) -
                           np.asarray(rr[rr_key][frame, ..., :3], np.float32)) * \
                          (np.asarray(p[guide_key][frame, ..., :3], np.float32) / 255.)
            state = states[lobe]
            _, noise = state.update(gate.band(observation, 3, 40)[None], taps, reuse)
            raw = state.correction(noise, reuse, 2., "soft", 8.)[0]
            value, _ = gate.neutral_correction(raw, np.isfinite(raw) & (abs(raw) > 0), base)
            addition += value
        negative = addition < 0
        scale = min(1., float(np.min(base[negative] / -addition[negative]))) if negative.any() else 1.
        addition *= max(0., scale)
        cpu = (base + addition).astype(np.float16)
        jitter = np.asarray(capture.frame(max(0, frame-1))["controls"]["jitter"], np.float32) - \
                 np.asarray(capture.frame(frame)["controls"]["jitter"], np.float32)
        actual = gpu.step([p["U"][frame], p["V"][frame]], [rr["spec"][frame], rr["diffuse"][frame]],
            [p["qs8"][frame], p["qd8"][frame]], rr["output"][frame], p["depth"][frame],
            p["packed"][frame], p["motion"][frame], reset=bool(capture.frame(frame).get("reset", False)),
            jitter=jitter.tolist())
        stored_rgb = actual[..., :3].astype(np.float16)
        diff = abs(stored_rgb.astype(np.float32)-cpu.astype(np.float32))
        ulp_up = abs(np.nextafter(cpu, np.float16(np.inf)).astype(np.float32)-cpu.astype(np.float32))
        ulp_down = abs(np.nextafter(cpu, np.float16(-np.inf)).astype(np.float32)-cpu.astype(np.float32))
        # Declared before the run: two stored FP16 ULPs plus 2e-6 absolute floor.
        # This does not replace M3: actual GPU outputs must independently pass it.
        within = diff <= 2*np.maximum(ulp_up, ulp_down) + 2e-6
        moment_errors = {}
        for lobe in states:
            reference = states[lobe]
            mean, variance, meta = gpu.history[lobe]
            errors = dict(mean_max=float(abs(mean[..., :3]-reference.mean[0]).max()),
                variance_max=float(abs(variance[..., :3]-reference.variance[0]).max()),
                mass_max=float(abs(mean[..., 3]-reference.mass).max()),
                q_max=float(abs(variance[..., 3]-reference.q).max()),
                age_max=float(abs(meta[..., 3]-reference.age).max()))
            errors["passed"] = (errors["mean_max"] <= 2e-5*max(1., float(abs(reference.mean).max())) and
                errors["variance_max"] <= 2e-5*max(1., float(abs(reference.variance).max())) and
                errors["mass_max"] <= 1e-5 and errors["q_max"] <= 1e-5 and errors["age_max"] <= 3e-4)
            moment_errors[lobe] = errors
        row = dict(frame=frame, maximum_stored_abs=float(diff.max()), rms_stored=float(np.sqrt(np.mean(diff**2))),
            changed_channels=int(np.count_nonzero(diff)), outside_declared_ulp_bound=int(np.count_nonzero(~within)),
            alpha_exact=bool(np.array_equal(actual[..., 3], np.asarray(rr["output"][frame, ..., 3], np.float32))),
            moments=moment_errors, minimum_stored_rgb=float(actual[..., :3].min()),
            lobe_scales=gpu.last["lobe_scales"][0, 0, :2].tolist(), sum_scale=float(gpu.last["sum_scale"][0, 0, 0]))
        row["passed"] = not row["outside_declared_ulp_bound"] and row["alpha_exact"] and \
                         all(value["passed"] for value in moment_errors.values())
        differences.append(row)
        if frame in slots:
            gpu_spool[slots[frame]] = stored_rgb
            cpu_spool[slots[frame]] = cpu
        if frame % 16 == 0:
            save(root / "equivalence_progress.json", differences)
            print(json.dumps(dict(capture=name, repeat=repeat, frame=frame, difference=row, seconds=time.monotonic()-start)), flush=True)
    gpu_spool.flush(); cpu_spool.flush()
    gpu_metrics = gate.score(lambda f: np.asarray(gpu_spool[slots[f]], np.float32), runs, truth, capture.H, capture.W)
    cpu_metrics = gate.score(lambda f: np.asarray(cpu_spool[slots[f]], np.float32), runs, truth, capture.H, capture.W)
    gpu_checks = checks_for(gpu_metrics, baseline)
    cpu_exact = cpu_metrics == cpu_candidate["runs"]
    result = dict(capture=name, capture_id=capture.id, repeat=repeat,
        static_runs=[[run[0], run[-1]] for run in runs], baselines=baseline,
        baseline_parity=parity, cpu_rerun_exact_metric_parity=cpu_exact,
        sources=dict(inputs=input_identity, rr=rr_identity, old=old_identity, gate=gate.source_hashes),
        profile="a0.1_k2_s1_d1_broad_soft_radiance", runs=gpu_metrics, checks=gpu_checks,
        m3_passed=all(row["all_bands_improve"] and row["stability"] for row in gpu_checks),
        numerical_equivalence_passed=all(row["passed"] for row in differences),
        numerical_limits=dict(stored="2 FP16 ULP + 2e-6", moments="2e-5 absolute/relative floor1",
                              mass_q=1e-5, age=3e-4), frame_differences=differences,
        seconds=time.monotonic()-start, runtime_enabled=False)
    result["passed"] = result["m3_passed"] and result["numerical_equivalence_passed"] and cpu_exact
    save(root / "metrics.json", result)
    gpu_spool._mmap.close(); cpu_spool._mmap.close()
    for array in arrays:
        array._mmap.close()
    gc.collect()
    print(json.dumps(dict(capture=name, repeat=repeat, m3=result["m3_passed"],
                         equivalence=result["numerical_equivalence_passed"], cpu_exact=cpu_exact)), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", nargs="+", choices=("haze", "water1", "water2", "reveal1"),
                        default=["haze", "water1", "water2", "reveal1"])
    parser.add_argument("--repeat", nargs="+", type=int, choices=(0, 1), default=[0, 1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--cpu-reference", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, default=Path("E:/FSRD/recovery_v2"))
    parser.add_argument("--evidence-scripts", type=Path, default=Path("F:/FSRD/recovery_v2/scripts/eval"))
    args = parser.parse_args()
    args.output = checked_output(args.output)
    args.cache = checked_output(args.cache)
    sources = [Path(__file__), Path(__file__).with_name("fsrd_recovery_detail_gpu.py"),
               Path(__file__).with_name("fsrd_recovery_detail_reference.py"),
               Path(__file__).with_name("test_fsrd_recovery_detail_replay.py")]
    start = {str(path): sha256(path) for path in sources}
    save(args.output / "source_at_start.json", start)
    os.environ.setdefault("FSRD_GPU_TEST_OUTPUT", str(args.output / "shared_runner_initial"))
    dispatcher = Dispatcher(args.output / "jobs")
    gate = original_gate(args.evidence_scripts)
    results = []
    try:
        results = [evaluate(args, name, repeat, gate, dispatcher) for repeat in args.repeat for name in args.capture]
    finally:
        dispatcher.close()
    finish = {str(path): sha256(path) for path in sources}
    unchanged = start == finish
    complete = set(args.capture) == {"haze", "water1", "water2", "reveal1"} and set(args.repeat) == {0, 1}
    result = dict(complete=complete, passed=complete and unchanged and all(row["passed"] for row in results),
        source_unchanged=unchanged, start=start, finish=finish,
        records=sum(len(row["runs"]) for row in results),
        m3_passed_records=sum(sum(c["all_bands_improve"] and c["stability"] for c in row["checks"]) for row in results),
        results=[dict(capture=row["capture"], repeat=row["repeat"], m3=row["m3_passed"],
                      equivalence=row["numerical_equivalence_passed"], cpu_exact=row["cpu_rerun_exact_metric_parity"]) for row in results],
        independent_boundary_black_clean_cost_gates_pending=True, production_enabled=False)
    save(args.output / "summary.json", result)
    return 0 if not complete or result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
