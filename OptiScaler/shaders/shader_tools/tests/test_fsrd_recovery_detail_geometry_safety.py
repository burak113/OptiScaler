"""Same original safety fixtures/thresholds with geometry-local observations/DC."""
from pathlib import Path
from types import SimpleNamespace
import argparse
import json
import test_fsrd_recovery_detail_safety as safety
from fsrd_recovery_detail_geometry_reference import GeometryState
from test_fsrd_recovery_detail_replay import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-scripts", type=Path, default=Path("F:/FSRD/recovery_v2/scripts/eval"))
    args = parser.parse_args()
    paths = [Path(__file__), Path(__file__).with_name("fsrd_recovery_detail_geometry_reference.py"),
             Path(safety.__file__)]
    before = {str(path): sha256(path) for path in paths}
    # Reuse unchanged fixture/check source; swap only this process's tested
    # implementation. The original file and failed report stay untouched.
    safety.CPUState = GeometryState
    code = safety.run(SimpleNamespace(mode="cpu", output=args.output, evidence_scripts=args.evidence_scripts))
    path = args.output/"results.json"
    result = json.loads(path.read_text())
    result.update(reference_scope="surface-segment spatial bands + connected-surface DC + current guide veto",
        tested_implementation=before, implementation_source_unchanged=before == {str(p): sha256(p) for p in paths},
        unchanged_safety_fixture_source=str(Path(safety.__file__)), gpu_executed=False)
    path.write_text(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
