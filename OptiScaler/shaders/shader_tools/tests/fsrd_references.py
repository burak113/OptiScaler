"""Optional, immutable historical DXIL packages. Never search local build folders."""
from pathlib import Path
import hashlib
import json
import os

MANIFEST = Path(__file__).with_name('reference_hashes.json')


def reference(name):
    packages = json.loads(MANIFEST.read_text(encoding='utf-8'))['packages']
    expected = packages[name]  # Unknown names are a test-author error, not a skip.
    root = os.environ.get('FSRD_REFERENCE_ROOT')
    if not root:
        print(f'SKIP reference {name}: FSRD_REFERENCE_ROOT not supplied', flush=True)
        return None
    directory = Path(root).resolve()/name/'precompile'
    if not directory.is_dir():
        print(f'SKIP reference {name}: package missing at {directory}', flush=True)
        return None
    # A present but damaged/partial package is an error, never a successful skip.
    for relative, digest in expected.items():
        path = directory/relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f'Reference integrity failure: {path}')
    print(f'Verified reference {name}: {len(expected)} SHA-256 hashes', flush=True)
    return directory


def require_reference(name):
    directory = reference(name)
    if directory is None:
        raise SystemExit(77)  # The suite runner reports SKIPPED, not PASSED.
    return directory
