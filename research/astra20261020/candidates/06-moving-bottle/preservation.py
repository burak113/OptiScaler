"""Check the diagnostic identity on available native/glass data, not on a GPU."""
import json
from pathlib import Path
import numpy as np

from recorded_analysis import PACKAGE, HERE, loader, array_sha
from support_tracer import abstain_identity


def check(name, value):
    before = array_sha(value)
    output = abstain_identity(value)
    words = np.frombuffer(value.tobytes(), dtype=np.uint8)
    changed = int(np.count_nonzero(words != np.frombuffer(output.tobytes(), dtype=np.uint8)))
    if changed or output.dtype != value.dtype or output.shape != value.shape or array_sha(value) != before:
        raise AssertionError("Identity failed: " + name)
    return {"name": name, "dtype": value.dtype.str, "shape": list(value.shape),
            "bytes_compared": int(value.nbytes), "changed_bytes": changed,
            "input_sha256": before, "output_sha256": array_sha(output), "input_unchanged": True}


def run(out):
    rows=[]
    for name in ("bottle_track7", "foliage23", "facade16"):
        a,_=loader.load_clip(PACKAGE/"fixtures/clips"/(name+".npz"))
        for role in ("selected_rr_diffuse", "selected_rr_specular"):
            rows.append(check(name+"/"+role,a[role]))
    with np.load(PACKAGE/"fixtures/glass/glass_crop.npz",allow_pickle=False) as z:
        raw=z["aligned_raw_spec_rgb"]
        selected=np.bitwise_xor(raw.view("<u4"),z["aligned_selected_spec_rgb_xor"]).view("<f4")
        rows.append(check("glass/aligned_selected_spec_rgb",selected))
        rows.append(check("glass/aligned_equal_diffuse_rgb",z["aligned_equal_diffuse_rgb"]))
    result={"schema":"astra.job06.identity_preservation.v1", "rows":rows,
        "total_bytes_compared":sum(row["bytes_compared"] for row in rows),
        "changed_bytes":sum(row["changed_bytes"] for row in rows),
        "scope":"CPU diagnostic copy identity on stored tensors; no native runtime shader/host execution",
        "water_control":"No complete chronological water/puddle fixture is bundled; historical receipt is not a rerun. Identity by construction has no pixel transform, but actual native water acceptance remains local.",
        "performance_ms":None,"gpu_executed":False}
    Path(out).write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    return result


if __name__=="__main__":
    result=run(HERE/"evidence/preservation.json")
    print(json.dumps({k:result[k] for k in ("total_bytes_compared","changed_bytes","gpu_executed")}))
