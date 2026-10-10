"""Unchanged surface constraints, including the strict2e-7 DC bound."""
from pathlib import Path
import json
import sys
import test_fsrd_recovery_detail_surface_constraints as constraints
from fsrd_recovery_detail_advanced_reference import AdvancedState, RayState, AnchorObservations
from test_fsrd_recovery_detail_replay import sha256


if __name__ == "__main__":
    index = sys.argv.index("--control-model") if "--control-model" in sys.argv else None
    model = sys.argv[index+1] if index is not None else "advanced"
    if model not in ("ray", "advanced"):
        raise ValueError(model)
    if index is not None:
        del sys.argv[index:index+2]
    paths = [Path(__file__), Path(constraints.__file__), *[Path(__file__).with_name(n) for n in (
        "fsrd_recovery_detail_anchor_reference.py", "fsrd_recovery_detail_advanced_reference.py")]]
    before = {str(p): sha256(p) for p in paths}
    constraints.GeometryState = RayState if model == "ray" else AdvancedState
    constraints.GeometryObservations = AnchorObservations
    code = constraints.main()
    after = {str(p): sha256(p) for p in paths}
    output = Path(sys.argv[sys.argv.index("--output")+1])
    path = output/"results.json"
    result = json.loads(path.read_text())
    result.update(implementation="binary witness + signed-ray bounded controls + compensated surface DC",
        control_model=model, implementation_source_start=before,
        implementation_source_finish=after, implementation_source_unchanged=before == after)
    path.write_text(json.dumps(result, indent=2)+"\n")
    raise SystemExit(code or int(before != after))
