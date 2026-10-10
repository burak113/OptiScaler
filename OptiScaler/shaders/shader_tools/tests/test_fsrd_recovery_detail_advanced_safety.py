"""Run unchanged original safety checks on an isolated bounded-control model."""
from pathlib import Path
from types import SimpleNamespace
import argparse
import json
import test_fsrd_recovery_detail_safety as safety
from fsrd_recovery_detail_advanced_reference import AdvancedState, RayState
from test_fsrd_recovery_detail_replay import sha256, checked_output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--control-model", choices=("ray", "advanced"), default="advanced")
    parser.add_argument("--evidence-scripts", type=Path, default=Path("F:/FSRD/recovery_v2/scripts/eval"))
    args = parser.parse_args()
    args.output = checked_output(args.output)
    paths = [Path(__file__), Path(safety.__file__), *[Path(__file__).with_name(n) for n in (
        "fsrd_recovery_detail_reference.py", "fsrd_recovery_detail_geometry_reference.py",
        "fsrd_recovery_detail_surface_witness_reference.py", "fsrd_recovery_detail_anchor_reference.py",
        "fsrd_recovery_detail_advanced_reference.py")]]
    before = {str(p): sha256(p) for p in paths}
    safety.CPUState = RayState if args.control_model == "ray" else AdvancedState
    code = safety.run(SimpleNamespace(mode="cpu", output=args.output, evidence_scripts=args.evidence_scripts))
    after = {str(p): sha256(p) for p in paths}
    report_path = args.output/"results.json"
    result = json.loads(report_path.read_text())
    result.update(control_model=args.control_model, implementation_source_start=before,
                  implementation_source_finish=after, implementation_source_unchanged=before == after,
                  gpu_executed=False, unchanged_fixture_source=str(Path(safety.__file__)))
    report_path.write_text(json.dumps(result, indent=2)+"\n")
    return code or int(before != after)


if __name__ == "__main__":
    raise SystemExit(main())
