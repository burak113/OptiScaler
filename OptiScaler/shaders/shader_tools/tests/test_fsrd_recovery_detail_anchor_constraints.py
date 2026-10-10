"""Exact previous surface constraints with the new binary/anchor implementation."""
from pathlib import Path
import json
import test_fsrd_recovery_detail_surface_constraints as constraints
from fsrd_recovery_detail_anchor_reference import AnchorState, AnchorObservations
from test_fsrd_recovery_detail_replay import sha256


if __name__ == "__main__":
    paths = [Path(__file__), Path(constraints.__file__),
             Path(__file__).with_name("fsrd_recovery_detail_anchor_reference.py")]
    before = {str(p): sha256(p) for p in paths}
    constraints.GeometryState = AnchorState
    constraints.GeometryObservations = AnchorObservations
    code = constraints.main()
    import sys
    output = Path(sys.argv[sys.argv.index("--output")+1])
    path = output/"results.json"
    result = json.loads(path.read_text())
    result.update(implementation="binary local witness/anchor4/mix1 + surface DC residual compensation",
        implementation_source_start=before,
        implementation_source_finish={str(p): sha256(p) for p in paths})
    path.write_text(json.dumps(result, indent=2))
    raise SystemExit(code)
