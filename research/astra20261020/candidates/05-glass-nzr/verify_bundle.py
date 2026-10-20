"""Check the delivered snapshot's checksums, strict JSON and local links.

Run before regenerating experiments; timing-bearing evidence changes on rerun.
This validates artifact integrity, not visual quality or a GPU implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

CANDIDATE = Path(__file__).resolve().parent
REPO = CANDIDATE.parents[3]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strict(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-uncommitted", action="store_true", help="Packaging bootstrap only")
    args = parser.parse_args()
    actual = {p.relative_to(CANDIDATE).as_posix(): p for p in CANDIDATE.rglob("*")
              if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo")}
    listed = {}
    for line in (CANDIDATE/"SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        assert name not in listed and name != "SHA256SUMS", name
        assert name in actual and digest(actual[name]) == expected, name
        listed[name] = expected
    assert set(listed) == set(actual)-{"SHA256SUMS"}, "Manifest must cover every delivered file"
    json_count = 0
    for name, path in actual.items():
        if path.suffix == ".json":
            strict(path)
            json_count += 1
        elif path.suffix == ".md":
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                target = target.split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                assert (path.parent/target).resolve().exists(), f"Broken link in {name}: {target}"
    result = strict(CANDIDATE/"RESULT.json")
    assert result["gpu_executed"] is False and result["acceptance_status"] == "keep_as_research"
    assert result["visual_improvement_adoption"] == "reject"
    if not args.allow_uncommitted:
        assert re.fullmatch(r"[0-9a-f]{40}", result["source_revision"] or ""), "Missing source commit"
    assert set(result["changed_paths"]) == {p.relative_to(REPO).as_posix() for p in actual.values()}
    for name, expected in result["source_sha256"].items():
        assert digest(CANDIDATE/name) == expected, name
    for name, expected in result["result_sha256_excluding_result_and_manifest"].items():
        assert digest(CANDIDATE/name) == expected, name
    for name, expected in result["fixture_sha256"].items():
        assert digest(REPO/name) == expected, name
    holdout = strict(CANDIDATE/"evidence/synthetic_holdout.json")
    for name, expected in holdout["source_sha256"].items():
        assert digest(CANDIDATE/name) == expected, f"Held-out source changed: {name}"
    audit = strict(CANDIDATE/"evidence/reviewer_holdout_audit.json")
    assert audit["holdout_sha256"] == digest(CANDIDATE/"evidence/synthetic_holdout.json")
    for relative in ("evidence/root_full_run/execution.json", "evidence/root_contract_rerun/execution.json"):
        if not (CANDIDATE/relative).exists():
            continue
        for run in strict(CANDIDATE/relative)["runs"]:
            assert digest(CANDIDATE/run["log"]) == run["log_sha256"], run["log"]
            assert run["exit_code"] == run["expected_exit_code"], run["command"]
    print(json.dumps({"status": "verified", "manifest_files": len(listed), "strict_json_files": json_count,
                      "source_revision": result["source_revision"], "gpu_executed": False}))


if __name__ == "__main__":
    main()
