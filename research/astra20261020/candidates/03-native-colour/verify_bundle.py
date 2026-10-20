"""Read-only verification of the delivered, self-excluding SHA-256 manifest.

Run before regenerating experiment receipts. Generated timings and figures may
change on another machine; their original delivered bytes are what this checks.
No dependencies beyond the Python standard library are required.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
MANIFEST = "SHA256SUMS.json"


def strict_json(path):
    def invalid(value):
        raise ValueError(f"Non-JSON numeric literal: {value}")
    return json.loads(path.read_text(), parse_constant=invalid)


def delivered_files():
    return {p.relative_to(HERE).as_posix() for p in HERE.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
            and p.suffix != ".pyc" and p.name != MANIFEST}


def main():
    manifest = strict_json(HERE / MANIFEST)
    seen = set()
    for row in manifest["files"]:
        name = row["path"]
        path = HERE / name
        if name in seen or name == MANIFEST or path.is_symlink():
            raise AssertionError("Duplicate, self-hash or symlink in manifest: " + name)
        if not path.resolve().is_relative_to(HERE):
            raise AssertionError("Escaping manifest path: " + name)
        data = path.read_bytes()
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise AssertionError("Delivered file differs: " + name)
        seen.add(name)
    if seen != delivered_files():
        raise AssertionError("Manifest file coverage differs: " + repr(sorted(seen ^ delivered_files())))
    result = strict_json(HERE / "RESULT.json")
    print(json.dumps({"verified_files": len(seen),
                      "source_revision": result["source_revision"],
                      "quality_accepted": result["quality_accepted"],
                      "recommendation": result["acceptance_status"],
                      "gpu_executed": result["gpu_executed"]}, sort_keys=True))


if __name__ == "__main__":
    main()
