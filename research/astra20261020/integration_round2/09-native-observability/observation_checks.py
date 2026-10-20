#!/usr/bin/env python3
"""Compile real portable observation contracts; replay immutable fixture samples.

This is a CPU execution receipt. It is neither a Windows host build nor a GPU
capture test. All generated files go under --output; original evidence is read
only, in its existing order, without looping histories or replacing BASE masks.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
RESEARCH = ROOT / "research/astra20261020"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def float_literal(value) -> str:
    # Hex literals preserve exactly the captured/promoted binary value.
    return float(value).hex() + "f"


def generate_cases(output: Path):
    decoder_path = RESEARCH / "candidates/07-foliage-guides/src/foliage_guides.py"
    loader_path = RESEARCH / "fixtures/clips/clip_loader.py"
    masks_path = RESEARCH / "candidates/06-moving-bottle/evidence/fixed_base_masks.npz"
    fixture_paths = [RESEARCH / f"fixtures/clips/{name}.npz" for name in ("bottle_track7", "foliage23")]
    immutable_paths = [decoder_path, loader_path, masks_path, *fixture_paths]
    initial_hashes = {str(path.relative_to(ROOT)): sha(path) for path in immutable_paths}
    decoder = module(decoder_path, "astra09_frozen_job07")
    loader = module(loader_path, "astra09_frozen_clips")
    rows, inventory = [], []
    with np.load(masks_path, allow_pickle=False) as masks:
        for capture, path in enumerate(fixture_paths, 1):
            with np.load(path, allow_pickle=False) as source:
                arrays = {name: source[name] for name in source.files}
            frames = arrays["frame_indices"]
            if not np.all(np.diff(frames) > 0):
                raise AssertionError("Original sequence is not strictly chronological")
            mask = masks[path.stem]
            if mask.shape != arrays["input_depth"].shape:
                raise AssertionError("Original BASE mask/clip extent mismatch")
            render = arrays["render_extent"]
            observations = []
            for index, frame in enumerate(frames):
                # Pick one location from each existing BASE mask. Selection
                # never consults selected/candidate radiance or a tuned score.
                finite = np.isfinite(arrays["input_motion"][index, ..., :2]).all(axis=-1)
                candidates = np.argwhere(mask[index] & finite)
                if not len(candidates):
                    raise AssertionError("No finite BASE fixture probe available")
                y, x = map(int, candidates[len(candidates)//2])
                normal_word = arrays["recovery_original_normal_roughness"][index, y, x]
                normal, roughness, category = decoder.unpack_normal_roughness(np.array([normal_word], np.uint32))
                current = arrays["crop_origin_render"][index]
                previous = arrays["crop_origin_render"][index-1] if index else current
                motion = arrays["input_motion"][index, y, x, :2].astype(np.float32)
                if index:
                    qx, qy, _ = loader.previous_coordinates(arrays, index)
                    expected = [float(qx[y, x]), float(qy[y, x])]
                else:
                    expected = [0.0, 0.0]
                raw = arrays["raw_rr_diffuse"][index, y, x].view(np.uint16)
                selected = arrays["selected_rr_diffuse"][index, y, x].view(np.uint16)
                ints = [capture, int(frame), x, y, *map(int, current), *map(int, previous),
                        *map(int, render), int(normal_word)]
                floats = [*motion, *normal[0], roughness[0]]
                row = ", ".join(map(str, ints)) + ", " + ", ".join(map(float_literal, floats))
                row += f", {int(category[0])}, {expected[0].hex()}, {expected[1].hex()}, " + ("true" if index == 0 else "false")
                row += ", {{" + ", ".join(map(str, map(int, raw))) + "}}, {{" + ", ".join(map(str, map(int, selected))) + "}}"
                rows.append("    {" + row + "},")
                observations.append({"frame": int(frame), "probe_xy": [x,y],
                                     "base_mask_count": int(mask[index].sum()),
                                     "authority": "unknown_missing_original_host_selection_witness"})
            inventory.append({"fixture": str(path.relative_to(ROOT)), "frames": observations,
                              "chronology": "single_pass_original_order", "initial_history": "unavailable"})
    header = output / "observation_frozen_cases.h"
    header.write_text("// Generated read-only probes of unchanged frozen evidence.\n"
                      "const FrozenCase frozenCases[] = {\n" + "\n".join(rows) + "\n};\n", encoding="utf-8")
    return immutable_paths, initial_hashes, inventory, header


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/tmp/astra09-observation"))
    parser.add_argument("--compiler", default=shutil.which("c++") or shutil.which("g++") or "c++")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    immutable_paths, original_hashes, inventory, generated = generate_cases(output)
    compiler = args.compiler
    binary = output / "observation_tests"
    command = [compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O2",
               "-DOBSERVATION_HAS_FROZEN_CASES", "-I", str(ROOT), "-I", str(output),
               str(HERE / "observation_tests.cpp"), "-o", str(binary)]
    runs = []

    def run(label, command, expected=0):
        begin = time.monotonic()
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        log = output / (label + ".txt")
        log.write_text(completed.stdout + completed.stderr, encoding="utf-8")
        detected = completed.returncode == expected
        if expected != 0:
            detected = detected and "FAIL:" in completed.stderr
        runs.append({"name": label, "command": command, "exit_status": completed.returncode,
                     "expected_status": expected, "accepted": detected,
                     "elapsed_seconds": time.monotonic()-begin, "log_sha256": sha(log)})
        print(label, "PASS" if detected else "FAIL", completed.returncode, flush=True)
        return detected

    compile_ok = run("compile", command)
    if compile_ok:
        run("contracts_and_frozen_probes", [str(binary)])
        for mutant in ("authority", "origin", "carry", "normal"):
            run("reject_broken_" + mutant, [str(binary), mutant], expected=1)
    after_hashes = {str(path.relative_to(ROOT)): sha(path) for path in immutable_paths}
    preserved = original_hashes == after_hashes
    compiler_info = subprocess.run([compiler, "--version"], capture_output=True, text=True, encoding="utf-8")
    sources = [ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDNrdObservationContract.h",
               HERE / "observation_tests.cpp", Path(__file__)]
    receipt = {"schema": "fsrd.native_observations.cpu_receipt.v1", "platform": platform.platform(),
               "python": sys.version, "numpy": np.__version__, "compiler": compiler_info.stdout.splitlines()[0],
               "windows_host_built": False, "gpu_executed": False,
               "source_hashes": {str(p.relative_to(ROOT)): sha(p) for p in sources},
               "frozen_source_hashes": original_hashes, "frozen_evidence_unchanged": preserved,
               "generated_cases_sha256": sha(generated), "fixture_inventory": inventory,
               "runs": runs, "passed": compile_ok and preserved and all(row["accepted"] for row in runs)}
    (output / "observation_execution.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
