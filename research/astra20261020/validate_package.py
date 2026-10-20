"""Verify the frozen export's hashes, NPZ readability and repository-local links."""
from pathlib import Path
import hashlib
import json
import re
import numpy as np

ROOT = Path(__file__).resolve().parent


def main():
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    count = 0
    arrays = 0
    for entry in manifest["files"]:
        path = (ROOT / entry["path"]).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise AssertionError(f"Missing or escaping path: {entry['path']}")
        data = path.read_bytes()
        assert len(data) == entry["bytes"], entry["path"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["path"]
        count += 1
        if path.suffix == ".npz":
            with np.load(path, allow_pickle=False) as z:
                for key in z.files:
                    assert not z[key].dtype.hasobject, (path.name, key)
                    arrays += 1
    # Historical plain-text reports deliberately preserve local-only references.
    for path in ROOT.rglob("*.md"):
        for target in re.findall(r"\]\(([^)\n]+)\)", path.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("#"):
                continue
            target = target.split("#", 1)[0]
            assert (path.parent / target).exists(), f"Broken link: {path.relative_to(ROOT)} -> {target}"
    print(f"Verified {count} frozen files, {arrays} safe NPZ arrays and Markdown links.")


if __name__ == "__main__":
    main()
