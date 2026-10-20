"""Hash the package data actually available, without implying access to originals."""
import json
from pathlib import Path
import numpy as np
from recorded_analysis import PACKAGE, HERE, sha_file


def run(out):
    entries=[]
    for directory in ("portable/anchor", "portable/colour", "fixtures/clips", "fixtures/glass"):
        for path in sorted((PACKAGE/directory).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            row={"path": path.relative_to(PACKAGE).as_posix(), "bytes": path.stat().st_size, "sha256": sha_file(path)}
            if path.suffix == ".npz":
                with np.load(path, allow_pickle=False) as z:
                    row["arrays"]={k:{"shape": list(z[k].shape), "dtype": z[k].dtype.str} for k in z.files}
            entries.append(row)
    result={"schema":"astra.job06.available_data.v1", "files":entries,
        "not_available":["full original captures", "pre-start RR/internal histories", "raw six-slice anchor key textures", "final remod/composition metadata", "converged same-pose truth", "final same-crop game video", "Windows/AMD RR execution"],
        "units_and_provenance":"See DATA_CONTRACT.md and each adjacent manifest; hashes establish identity, not correctness.",
        "independent_capture_count":4, "independent_noise_samples_in_a_single_recorded_frame":False}
    Path(out).write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    return result


if __name__=="__main__":
    out=HERE/"evidence/inventory.json";out.parent.mkdir(parents=True,exist_ok=True)
    print(json.dumps({"files":len(run(out)["files"])}))
