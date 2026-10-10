"""Recovery v2 OFF DXIL identity and ON empty-chain production composition."""
from pathlib import Path
import hashlib
import json
import os
import sys
import argparse
import subprocess


def audit_legacy_shaders(snapshot, initial_backup, output):
    """Report inherited snapshot drift separately, without changing its gate."""
    root = Path(__file__).resolve().parents[4]
    precompile = root/"OptiScaler/shaders/fsrd_preprocess/precompile"
    initial_head = "8b46ea6a498e139b75edda273e0340fde813c1f5"
    expected = json.loads((snapshot/"dxil_sha256.json").read_text())
    rows = []
    for name, snapshot_hash in expected.items():
        if name.startswith("FSRDStructureTransfer"):
            continue  # Same retired artifact exclusion as the existing gate.
        current_hash = hashlib.sha256((precompile/name).read_bytes()).hexdigest()
        initial_file = initial_backup/"OptiScaler/shaders/fsrd_preprocess/precompile"/name
        if initial_file.is_file():
            initial_bytes = initial_file.read_bytes()
            initial_source = str(initial_file)
        else:
            initial_bytes = subprocess.check_output(["git", "show",
                f"{initial_head}:OptiScaler/shaders/fsrd_preprocess/precompile/{name}"], cwd=root)
            initial_source = "unchanged tracked file at recorded initial HEAD "+initial_head
        initial_hash = hashlib.sha256(initial_bytes).hexdigest()
        rows.append(dict(shader=name, snapshot_sha256=snapshot_hash,
            initial_sha256=initial_hash, current_sha256=current_hash,
            initial_source=initial_source, snapshot_gate=current_hash == snapshot_hash,
            unchanged_since_task_start=current_hash == initial_hash,
            inherited_snapshot_mismatch=initial_hash != snapshot_hash))
    result = dict(snapshot_gate_passed=all(row["snapshot_gate"] for row in rows),
                  unchanged_since_task_start=all(row["unchanged_since_task_start"] for row in rows),
                  rows=rows)
    output = output.resolve()
    output.relative_to((root/"tools_tmp").resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(dict(snapshot_gate_passed=result["snapshot_gate_passed"],
        unchanged_since_task_start=result["unchanged_since_task_start"],
        inherited_mismatches=[row["shader"] for row in rows if row["inherited_snapshot_mismatch"]])), flush=True)
    return not result["snapshot_gate_passed"]


def main():
    import numpy as np
    import fsrd_alpha_common as a
    import run_fsrd_gpu_tests as t
    snapshot = Path(os.environ.get("FSRD_RECOVERY_V2_SNAPSHOT", "E:/FSRD/recovery_v2/snapshot"))
    old = snapshot / "precompile"
    hashes = json.loads((snapshot / "dxil_sha256.json").read_text())
    for name, digest in hashes.items():
        if name.startswith("FSRDStructureTransfer"):
            continue
        t.check("v2 OFF unchanged legacy DXIL: " + name,
                hashlib.sha256((t.PRE/name).read_bytes()).hexdigest() == digest)
    rng = np.random.default_rng(626)
    with a.GPUWorker(t.OUT/"worker"):
        for W,H in ((17,13),(64,64)):
            raw = a.rgba(rng.uniform(.02,4,(H,W,3)).astype(np.float32),.625)
            alb = a.rgba(rng.uniform(.1,.8,(H,W,3)).astype(np.float32))
            overrides = dict(Flags=(1<<1)|(1<<4)|(1<<5)|1,FloorDetailPreservation=0,RecoveryMask=0)
            current = a.convert(raw,alb,alb,overrides=overrides)
            frozen = a.convert(raw,alb,alb,overrides=overrides,directory=old)
            t.check(f"empty-chain conversion is byte identical {W}x{H}",
                    all(np.array_equal(x,y,equal_nan=True) for x,y in zip(current,frozen)))
            new_color = a.compose(current,detail=0)
            old_color = a.compose(frozen,detail=0,directory=old)
            t.check(f"empty-chain composition is byte identical {W}x{H}",
                    np.array_equal(new_color,old_color,equal_nan=True))
    host = (t.ROOT/"OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp").read_text()
    t.check("empty chain returns composition resource without copying",
            "m_recoveryOutputIndex < 0 ? m_compositionOutput.Get()" in host)
    t.OUT.mkdir(parents=True,exist_ok=True)
    (t.OUT/"results.json").write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings),indent=2))
    failures = sum(not x["passed"] for x in t.checks)
    print(f"recovery v2: {failures} failures",flush=True)
    return bool(failures)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-only", action="store_true", help="CPU SHA audit; retains original snapshot pass/fail")
    parser.add_argument("--snapshot", type=Path, default=Path(os.environ.get("FSRD_RECOVERY_V2_SNAPSHOT", "E:/FSRD/recovery_v2/snapshot")))
    parser.add_argument("--initial-backup", type=Path, default=Path(__file__).resolve().parents[4]/"tools_tmp/team_20261010/initial_files")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[4]/"tools_tmp/team_20261010/recovery_legacy_identity.json")
    args = parser.parse_args()
    sys.exit(audit_legacy_shaders(args.snapshot, args.initial_backup, args.output) if args.audit_only else main())
