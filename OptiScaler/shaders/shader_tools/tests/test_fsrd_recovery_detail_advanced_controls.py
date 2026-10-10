"""The unchanged six targeted control checks with bounded-control alternatives."""
from pathlib import Path
import functools
import json
import sys
import test_fsrd_recovery_detail_anchor_controls as controls
from fsrd_recovery_detail_advanced_reference import apply_controls
from test_fsrd_recovery_detail_replay import sha256


if __name__ == "__main__":
    index = sys.argv.index("--control-model") if "--control-model" in sys.argv else None
    model = sys.argv[index+1] if index is not None else "advanced"
    if model not in ("ray", "advanced"):
        raise ValueError(model)
    if index is not None:
        del sys.argv[index:index+2]
    paths = [Path(__file__), Path(controls.__file__),
             Path(__file__).with_name("fsrd_recovery_detail_advanced_reference.py")]
    before = {str(p): sha256(p) for p in paths}
    controls.apply_controls = functools.partial(apply_controls, control_model=model)
    code = controls.main()
    after = {str(p): sha256(p) for p in paths}
    output = Path(sys.argv[sys.argv.index("--output")+1])
    path = output/"results.json"
    result = json.loads(path.read_text())
    result.update(control_model=model, implementation_source_start=before,
                  implementation_source_finish=after, implementation_source_unchanged=before == after)
    path.write_text(json.dumps(result, indent=2)+"\n")
    raise SystemExit(code or int(before != after))
