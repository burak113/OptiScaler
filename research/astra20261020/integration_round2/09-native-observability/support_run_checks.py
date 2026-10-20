"""Compile/run the actual portable C++ support contract and immutable fixture checks.

No DLL/HLSL build or GPU execution is performed. Deliberately broken C++ producer
must exit 1 with assertion failures; that expected rejection is recorded separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
HEADER = ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDNrdSupportContract.h"
SOURCE = HERE / "support_contract_test.cpp"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, output, name, expected=0):
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    (output / (name + ".log")).write_text(result.stdout, encoding="utf-8")
    row = {"name": name, "command": list(map(str, command)), "status": result.returncode,
           "expected_status": expected, "elapsed_seconds": time.monotonic()-started,
           "log": name + ".log", "passed": result.returncode == expected}
    if expected == 1:
        row["passed"] &= "FAIL far +3 donor contaminates pure recipient" in result.stdout
        row["meaning"] = "expected rejection of deliberately broken implementation"
    return row


def frozen_fixtures():
    rows = []
    folder = ROOT / "research/astra20261020/portable/anchor/fixtures/native_policy"
    for path in sorted(folder.glob("*.npz")):
        before = digest(path)
        with np.load(path, allow_pickle=False) as archive:
            arrays = {key: archive[key] for key in archive.files}
        frames = arrays["frames"]
        assert np.all(np.diff(frames) > 0), "fixture chronology must remain strictly increasing"
        mask = arrays["fixed_mask"]
        assert mask.dtype == np.bool_, "keep original BASE mask unchanged"
        stats, recall, gain = arrays["stats"], arrays["recalled"], arrays["gain"]
        assert stats.shape == recall.shape and stats.shape[:-1] == gain.shape == mask.shape
        changed_without_own_recall = 0
        baseline_mask_count = 0
        # One chronological traversal, no history bootstrap/loop/reweighting.
        per_frame = []
        for index, frame in enumerate(frames):
            baseline_mask_count += int(mask[index].sum())
            missing = recall[index, ..., 1] < .5
            count = int(((gain[index] < 1) & missing).sum())
            changed_without_own_recall += count
            per_frame.append({"frame": int(frame), "baseline_mask_count": int(mask[index].sum()),
                              "changed_centres_without_own_recall": count})
        assert changed_without_own_recall > 0, "retained native counterexample must not vanish"
        # Recalled textures do not contain the raw six-slice ring, pixel geometry,
        # key generation, full sampling footprint or fence publication witnesses.
        assert "keyLevel" not in arrays and "keyDepth" not in arrays
        assert before == digest(path), "frozen source was changed"
        rows.append({"path": str(path.relative_to(ROOT)), "sha256": before,
                     "frames": frames.tolist(), "baseline_mask_count": baseline_mask_count,
                     "baseline_mask_sha256": hashlib.sha256(mask.tobytes(order="C")).hexdigest(),
                     "changed_centres_without_own_recall": changed_without_own_recall,
                     "native_support": "invalid: full donor and recalled-key provenance unavailable",
                     "per_frame": per_frame})
    assert len(rows) == 3
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("write execution receipts outside the source tree")
    output.mkdir(parents=True, exist_ok=True)
    compiler = shutil.which(os.environ.get("CXX", "g++"))
    if not compiler:
        raise RuntimeError("a C++17 compiler is required; source inspection is not a compile")
    binary = output / ("support_contract_test.exe" if os.name == "nt" else "support_contract_test")
    commands = [[compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
                 "-I", str(ROOT), str(SOURCE), "-o", str(binary)],
                [str(binary)], [str(binary), "--mutant-current-cell-only"]]
    rows = []
    for command, name, expected in zip(commands, ("compile", "support", "reject_current_cell_only"), (0,0,1)):
        row = run(command, output, name, expected)
        rows.append(row)
        if not row["passed"]:
            break
    fixtures = frozen_fixtures()
    receipt = {"scope": "Linux/portable C++ support contracts and read-only frozen CPU fixtures; no GPU or Windows DLL build",
               "platform": platform.platform(), "python": sys.version, "numpy": np.__version__,
               "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in (HEADER,SOURCE,Path(__file__).resolve())},
               "runs": rows, "fixtures": fixtures,
               "passed": len(rows) == 3 and all(row["passed"] for row in rows)}
    if binary.exists():
        receipt["executable_sha256"] = digest(binary)
    (output / "support_execution.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"passed":receipt["passed"],"runs":len(rows),"frozen_fixtures":len(fixtures),
                      "receipt":str(output/"support_execution.json")}))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
