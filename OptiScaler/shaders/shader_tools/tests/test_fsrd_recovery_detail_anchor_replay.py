"""CPU-only paired-detail experiment against the unchanged published M3 gate.

Read saved actual AMD RR pairs; launch no GPU replay. The original score,
capture-bound checks and raw-truth functions are loaded as AST definitions,
without executing old modules' environment changes or GPU imports. A byte-for-
byte JSON metric parity check precedes candidate evaluation. All writes stay
under this checkout's tools_tmp; evidence roots are read-only.
"""
from pathlib import Path
from types import SimpleNamespace
import argparse
import ast
import gc
import hashlib
import itertools
import json
import os
import shutil
import time
import zipfile
import numpy as np
from fsrd_recovery_detail_anchor_reference import BinaryWitnessMoments as PairedBandMoments, AnchorObservations as GeometryObservations, apply_controls

ROOT = Path(__file__).resolve().parents[4]
SCORE_BANDS = ((3, 6), (6, 12), (12, 24), (24, 40))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(2**20), b""):
            digest.update(block)
    return digest.hexdigest()


def checked_output(path):
    path = Path(path).resolve()
    path.relative_to((ROOT/"tools_tmp").resolve())
    path.mkdir(parents=True, exist_ok=True)
    return path


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def definitions(path, names, namespace):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), str(path))
    nodes = []
    found = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            declared = {node.name}
        elif isinstance(node, ast.Assign):
            declared = {target.id for target in node.targets if isinstance(target, ast.Name)}
        else:
            continue
        if declared & set(names):
            nodes.append(node)
            found |= declared & set(names)
    if found != set(names):
        raise RuntimeError("Missing source definition: "+str(set(names)-found))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)


def original_gate(scripts):
    namespace = dict(np=np, Path=Path, json=json, os=os)
    loaders = Path("F:/FSRD/newcaps/e17lib.py")
    normals = Path("F:/FSRD/halfres/hr.py")
    definitions(loaders, ("R", "CAP", "man", "h16", "u8", "f32", "box"), namespace)
    definitions(normals, ("decode_normals",), namespace)
    definitions(scripts/"common.py", ("CAPS", "LUMA", "Capture", "blur"), namespace)
    definitions(scripts/"lobes.py", ("BANDS", "band", "mapping", "warp", "static_ranges",
                "truth_for_runs", "score", "neutral_correction"), namespace)
    # The candidate may use partial same-surface taps, while scoring remains
    # literally the original four-band source function.
    partial = dict(namespace)
    definitions(scripts/"reprojection_improved.py", ("mapping",), partial)
    namespace["partial_mapping"] = partial["mapping"]
    namespace["source_hashes"] = {str(path): sha256(path) for path in
        (loaders, normals, scripts/"common.py", scripts/"lobes.py", scripts/"reprojection_improved.py")}
    return SimpleNamespace(**namespace)


def extract(path, keys, destination):
    destination.mkdir(parents=True, exist_ok=True)
    fingerprint = dict(path=str(path.resolve()), sha256=sha256(path))
    marker = destination/"source.json"
    reuse = marker.is_file() and json.loads(marker.read_text()) == fingerprint
    arrays = {}
    with zipfile.ZipFile(path) as archive:
        for key in keys:
            target = destination/(key+".npy")
            if not reuse or not target.is_file():
                with archive.open(key+".npy") as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, 2**20)
            arrays[key] = np.load(target, mmap_mode="r", allow_pickle=False)
    save(marker, fingerprint)
    return arrays, fingerprint


def checks_for(measured, baseline):
    checks = []
    for now, off in zip(measured, baseline):
        per_band = {name: now["bands"][name]["error"] < off["bands"][name]["error"]
                    for name in now["bands"]}
        checks.append(dict(frames=now["frames"], all_bands_improve=all(per_band.values()),
            per_band_improves=per_band, aggregate_improves=now["band_error"] < off["band_error"],
            stability=now["low_frequency_deviation"] <= 1.1*off["low_frequency_deviation"],
            lf_ratio=now["low_frequency_deviation"]/max(off["low_frequency_deviation"], 1e-20)))
    return checks


def evaluate(args, name, repeat, gate):
    started = time.monotonic()
    capture = gate.Capture(name)
    evidence = args.evidence/"eval"/capture.id/f"repeat{repeat}"
    root = checked_output(args.output/name/f"repeat{repeat}")
    cache = checked_output(args.cache/capture.id/f"repeat{repeat}")
    p, input_identity = extract(evidence/"rr_inputs.npz", ("U", "V", "qs8", "qd8", "packed", "depth", "motion"), cache/"inputs")
    rr, rr_identity = extract(evidence/"rr_only/replay.npz", ("output", "spec", "diffuse"), cache/"rr")
    old, old_identity = extract(evidence/"pedestal/replay.npz", ("output",), cache/"old")
    arrays = [*p.values(), *rr.values(), *old.values()]
    for array in arrays:
        if array.shape[:3] != (capture.n, capture.H, capture.W):
            raise ValueError("Published capture/cache extent mismatch")
    runs, speeds = gate.static_ranges(capture, p)
    truth = gate.truth_for_runs(capture, runs)
    baseline = gate.score(lambda f: np.asarray(rr["output"][f, ..., :3], np.float32),
                          runs, truth, capture.H, capture.W)
    old_metrics = gate.score(lambda f: np.asarray(old["output"][f, ..., :3], np.float32),
                             runs, truth, capture.H, capture.W)
    original_path = evidence/"M3_metrics.json"
    original = json.loads(original_path.read_text(encoding="utf-8"))
    parity = (baseline == original["baselines"]["all through RR, no recovery"] and
              old_metrics == original["baselines"]["Floor pedestal (old)"] and
              [[run[0], run[-1]] for run in runs] == original["static_runs"])
    save(root/"baseline_parity.json", dict(passed=parity, measured=baseline, old=old_metrics,
         original=str(original_path), original_sha256=sha256(original_path)))
    if not parity:
        raise AssertionError("Original baseline/truth metric parity failed; no candidate is scored")
    frames = sorted(set(itertools.chain.from_iterable(runs)))
    slots = {frame: index for index, frame in enumerate(frames)}
    candidates = []
    for response, k, strengths, group in itertools.product(args.responses, args.ks,
            args.strengths, ("multiband", "broad")):
        key = f"a{response:g}_k{k:g}_s{strengths[0]:g}_d{strengths[1]:g}_{group}_{args.confidence}_{args.domain}_anchor{args.anchor:g}_mix{args.mix:g}"
        if args.candidates and key not in args.candidates:
            continue
        path = root/(key+".npy")
        spool = np.lib.format.open_memmap(path, mode="w+", dtype=np.float16,
                shape=(len(frames), capture.H, capture.W, 3))
        candidates.append(dict(id=key, response=response, k=k, strengths=strengths,
                               group=group, spool=spool, control_counters=[], active_sum=0., dc_max=0., stored_dc_max=0.))
    if not candidates:
        raise ValueError("No matching candidate in the declared grid")
    # Moments for different bands are independent. The reduced run checks exact
    # output metric parity against its completed full-grid haze record below.
    broad_only = all(candidate["group"] == "broad" for candidate in candidates)
    bands = ((3, 40),) if broad_only else (*SCORE_BANDS, (3, 40))
    responses = sorted({candidate["response"] for candidate in candidates})
    states = {(response, lobe): PairedBandMoments((capture.H, capture.W), len(bands), response)
              for response in responses for lobe in ("specular", "diffuse")}
    previous_available = {lobe: np.zeros((capture.H, capture.W, 3), bool) for lobe in ("specular", "diffuse")}
    geometry_counts = []
    mapping = gate.partial_mapping if args.mapping == "partial" else gate.mapping
    for frame in range(max(frames)+1):
        taps, reuse, normal = mapping(p, frame, capture)
        geometry = GeometryObservations(p["depth"][frame], normal)
        geometry_counts.append(geometry.count)
        prepared = {}
        for lobe, source_key, rr_key, guide_key in (("specular", "U", "spec", "qs8"),
                                                    ("diffuse", "V", "diffuse", "qd8")):
            delta = np.asarray(p[source_key][frame, ..., :3], np.float32)-np.asarray(rr[rr_key][frame, ..., :3], np.float32)
            guide = np.asarray(p[guide_key][frame, ..., :3], np.float32)/255.
            available = np.isfinite(guide) & (guide > 0)
            changed = np.any(available != previous_available[lobe], axis=-1)
            lobe_reuse = reuse & geometry.valid & ~changed
            previous_available[lobe] = available
            if args.domain == "radiance":
                delta *= guide
            observed = np.stack([geometry.band(delta, *pair) for pair in bands])
            for response in responses:
                state = states[response, lobe]
                _, noise = state.update(observed, taps, lobe_reuse)
                prepared[response, lobe] = (state, noise, guide, available, np.asarray(rr[rr_key][frame, ..., :3], np.float32)*guide)
        if frame in slots:
            base = np.asarray(rr["output"][frame, ..., :3], np.float32)
            for candidate in candidates:
                correction = np.zeros_like(base)
                for lobe, strength in zip(("specular", "diffuse"), candidate["strengths"]):
                    if strength <= 0:
                        continue
                    state, noise, guide, available, current_rr = prepared[candidate["response"], lobe]
                    supported = state.correction(noise, reuse, candidate["k"], args.confidence, args.minimum_count)
                    raw = (supported[:4].sum(0) if candidate["group"] == "multiband"
                           else supported[0 if broad_only else 4])
                    if args.domain == "demodulated":
                        raw = raw*guide
                    raw *= strength
                    control_noise = noise[0::2][:4].sum(0) if candidate["group"] == "multiband" else noise[0 if broad_only else 8]
                    counters = {}
                    raw = apply_controls(raw, current_rr, geometry, control_noise, args.anchor, args.mix, args.luma, args.chroma, counters)
                    candidate["control_counters"].append(dict(frame=frame, lobe=lobe, **counters))
                    mask = np.isfinite(raw) & (abs(raw) > 0) & available
                    addition, _ = geometry.neutral(raw, mask, base)
                    correction += addition
                negative = correction < 0
                scale = min(1., float(np.min(base[negative]/-correction[negative]))) if negative.any() else 1.
                correction *= max(0., scale)
                correction = geometry.project_residual(correction, np.isfinite(correction) & (correction != 0), base)
                stored = (base+correction).astype(np.float16)
                candidate["spool"][slots[frame]] = stored
                candidate["active_sum"] += float(np.mean(np.any(abs(correction) > 1e-7, axis=-1)))
                candidate["dc_max"] = max(candidate["dc_max"], float(abs(correction.sum((0, 1), dtype=np.float64)).max()))
                candidate["stored_dc_max"] = max(candidate["stored_dc_max"], float(abs((stored.astype(np.float32)-base).sum((0, 1), dtype=np.float64)).max()))
        if frame % 16 == 0:
            print(json.dumps(dict(capture=name, repeat=repeat, frame=frame,
                                  candidates=len(candidates), seconds=time.monotonic()-started)), flush=True)
    rows = []
    for candidate in candidates:
        spool = candidate.pop("spool")
        spool.flush()
        measured = gate.score(lambda f: np.asarray(spool[slots[f]], np.float32), runs,
                              truth, capture.H, capture.W)
        checks = checks_for(measured, baseline)
        spool._mmap.close()
        rows.append(dict(**candidate, runs=measured, checks=checks,
            passed=all(row["all_bands_improve"] and row["stability"] for row in checks)))
    if args.parity_with:
        parity_source = json.loads(args.parity_with.read_text(encoding="utf-8"))
        if parity_source["capture"] == name and parity_source["repeat"] == repeat:
            full_grid = {row["id"]: row for row in parity_source["candidates"]}
            for row in rows:
                if row["runs"] != full_grid[row["id"]]["runs"] or row["checks"] != full_grid[row["id"]]["checks"]:
                    save(root/"candidate_parity_failure.json", dict(candidate=row, full_grid=full_grid[row["id"]]))
                    raise AssertionError("Pruned estimator output changed: "+row["id"])
    result = dict(capture=name, capture_id=capture.id, repeat=repeat, published_frames=capture.n,
        publication=capture.publication, static_runs=[[run[0], run[-1]] for run in runs],
        baseline_parity="exact original JSON metric equality", baselines=baseline,
        source_files=dict(inputs=input_identity, rr=rr_identity, old=old_identity),
        gate_sources=gate.source_hashes, script_sha256=sha256(__file__),
        reference_sha256=sha256(Path(__file__).with_name("fsrd_recovery_detail_reference.py")),
        configuration=dict(domain=args.domain, confidence=args.confidence, mapping=args.mapping,
                           minimum_effective_count=args.minimum_count, anchor=args.anchor, mix=args.mix, luma=args.luma, chroma=args.chroma, geometry_component_counts=geometry_counts,
                           geometry_operator="original global band + binary same-surface witness + anchor/mix + residual-corrected surface DC",
                           current_veto="positive current guide; change restarts lobe population; runtime Skip/current-source certificate remains pending"),
        limitations="CPU binary/anchor prototype; GPU connected-component labeling/cost and production routing unavailable; no runtime/GPU acceptance",
        candidates=rows, seconds=time.monotonic()-started)
    save(root/"metrics.json", result)
    print(json.dumps(dict(capture=name, repeat=repeat, complete=True,
              local_survivors=[row["id"] for row in rows if row["passed"]], seconds=result["seconds"])), flush=True)
    for array in arrays:
        array._mmap.close()
    gc.collect()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", nargs="+", default=["haze"], choices=("haze", "water1", "water2", "reveal1"))
    parser.add_argument("--repeat", type=int, nargs="+", default=[0])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, default=Path("E:/FSRD/recovery_v2"))
    parser.add_argument("--evidence-scripts", type=Path, default=Path("F:/FSRD/recovery_v2/scripts/eval"))
    parser.add_argument("--responses", type=float, nargs="+", default=[.03, .1])
    parser.add_argument("--ks", type=float, nargs="+", default=[2., 3.])
    parser.add_argument("--confidence", choices=("hard", "soft", "rgb_soft"), default="soft")
    parser.add_argument("--domain", choices=("radiance", "demodulated"), default="radiance")
    parser.add_argument("--mapping", choices=("all", "partial"), default="partial")
    parser.add_argument("--minimum-count", type=float, default=8.)
    parser.add_argument("--anchor", type=float, default=4.)
    parser.add_argument("--mix", type=float, default=1.)
    parser.add_argument("--luma", type=float, default=1.)
    parser.add_argument("--chroma", type=float, default=1.)
    parser.add_argument("--candidates", nargs="+", help="Retest declared full-grid candidate IDs")
    parser.add_argument("--cache", type=Path, help="Project-local shared read-evidence cache")
    parser.add_argument("--parity-with", type=Path, help="Require exact selected/full-grid metric parity on matching capture/repeat")
    args = parser.parse_args()
    args.strengths = ((0., 1.), (1., 0.), (.25, 1.), (1., 1.))
    args.output = checked_output(args.output)
    args.cache = checked_output(args.cache or args.output/"cache")
    source_paths = {"script": Path(__file__), "reference":
                    Path(__file__).with_name("fsrd_recovery_detail_reference.py"), "geometry":
                    Path(__file__).with_name("fsrd_recovery_detail_geometry_reference.py"), "witness":
                    Path(__file__).with_name("fsrd_recovery_detail_surface_witness_reference.py"), "anchor":
                    Path(__file__).with_name("fsrd_recovery_detail_anchor_reference.py")}
    source_start = {name: sha256(path) for name, path in source_paths.items()}
    for name, path in source_paths.items():
        shutil.copyfile(path, args.output/(name+"_at_start.py"))
    save(args.output/"source_sha_at_start.json", source_start)
    print(json.dumps(dict(pid=os.getpid(), captures=args.capture, repeats=args.repeat,
                          candidates=args.candidates or "bounded 32-setting grid")), flush=True)
    gate = original_gate(args.evidence_scripts)
    GeometryObservations.global_band = staticmethod(gate.band)
    results = [evaluate(args, capture, repeat, gate) for repeat in args.repeat for capture in args.capture]
    source_finish = {name: sha256(path) for name, path in source_paths.items()}
    save(args.output/"source_sha_at_finish.json", dict(start=source_start,
         finish=source_finish, unchanged=source_start == source_finish))
    if source_start != source_finish:
        raise AssertionError("Estimator sources changed during the running replay; results are unaccepted")
    shared = set(row["id"] for row in results[0]["candidates"] if row["passed"])
    for result in results[1:]:
        shared &= {row["id"] for row in result["candidates"] if row["passed"]}
    complete = set(args.capture) == {"haze", "water1", "water2", "reveal1"} and set(args.repeat) == {0, 1}
    save(args.output/"summary.json", dict(complete=complete, passed=complete and bool(shared),
          local_survivors=sorted(shared), total_records=sum(len(result["static_runs"]) for result in results),
          results=[str(args.output/result["capture"]/f"repeat{result['repeat']}"/"metrics.json") for result in results]))
    return 0 if not complete or shared else 1


if __name__ == "__main__":
    raise SystemExit(main())
