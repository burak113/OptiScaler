"""Verify source-only proposals against Git blobs, allowing only checkout CRLF.

Original runner byte comparisons confuse core.autocrlf with source changes.
This replacement keeps exact patch/result hashes and never applies to production.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
CANDIDATES = HERE.parent / "candidates"
BASE = "5d7839a930106cf8fe1ba8dbbc6750509e7f26a8"


def same_text(actual, frozen):
    return actual.replace(b"\r\n", b"\n") == frozen.replace(b"\r\n", b"\n")


def main():
    assert same_text(b"a\r\nb\r\n", b"a\nb\n")
    assert not same_text(b"a\r\nc\r\n", b"a\nb\n")
    assert not same_text(b"a\nb \n", b"a\nb\n")
    numerical = CANDIDATES / "01-numerical-contract"
    glass = CANDIDATES / "05-glass-nzr/adapter"
    identity = json.loads((numerical / "adapter/adapter_identity.json").read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("glass_adapter", glass / "validate_adapter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    paths = [identity["source_path"], *module.PROTECTED]
    originals, receipts = {}, {}
    for relative in paths:
        frozen = subprocess.check_output(["git", "show", BASE + ":" + relative], cwd=REPO)
        actual = (REPO / relative).read_bytes()
        assert same_text(actual, frozen), "Production content changed: " + relative
        originals[relative] = frozen
        receipts[relative] = dict(git_blob_sha256=hashlib.sha256(frozen).hexdigest(),
            working_bytes_sha256=hashlib.sha256(actual).hexdigest(), only_checkout_line_endings_differ=actual != frozen)
    assert hashlib.sha256(originals[identity["source_path"]]).hexdigest() == identity["base_source_sha256"]
    with tempfile.TemporaryDirectory(prefix="astra_adapter_") as directory:
        root = Path(directory)
        for relative, data in originals.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for patch in (numerical / "adapter/PRODUCTION.patch", glass / "PRODUCTION.patch"):
            subprocess.run(["git", "-c", "core.autocrlf=false", "apply", "--check", str(patch)], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "-c", "core.autocrlf=false", "apply", str(patch)], cwd=root, check=True, capture_output=True)
        result = (root / identity["source_path"]).read_bytes()
        assert result == (numerical / "adapter/FSRDColourTrackTrack.hlsl").read_bytes()
        assert hashlib.sha256(result).hexdigest() == identity["proposed_source_sha256"]
        assert (root / module.TARGET).read_bytes() == (glass / "GlassNzrCorrection.hlsl").read_bytes()
        for relative in module.PROTECTED:
            assert (root / relative).read_bytes() == originals[relative]
    print(json.dumps(dict(protected_sources=receipts, exact_patch_payloads_verified=True,
                         production_written=False, gpu_executed=False), indent=2))


if __name__ == "__main__":
    main()
