"""Verify every delivered byte against MANIFEST.json and frozen input blobs."""
import argparse
import hashlib
import json
from pathlib import Path

from run_checks import HERE, BASE, frozen_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output and (args.output.resolve() == HERE or HERE in args.output.resolve().parents):
        parser.error('write verification output outside the immutable delivered package')
    manifest = json.loads((HERE/'MANIFEST.json').read_text(encoding='utf-8'))
    assert manifest['base_commit'] == BASE
    actual = {p.relative_to(HERE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(HERE.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.name != 'MANIFEST.json'}
    assert actual == manifest['files'], 'delivery inventory/hash mismatch'
    frozen = frozen_snapshot()
    result = dict(passed=True, delivered_files=len(actual),
        manifest_sha256=hashlib.sha256((HERE/'MANIFEST.json').read_bytes()).hexdigest(),
        frozen_tag_files_checked=len(frozen), frozen_tag_files_unchanged=True,
        quality_accepted=False, gpu_executed=False)
    serialized = json.dumps(result,indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(serialized,encoding='utf-8')
    print(serialized,end='')


if __name__ == '__main__':
    main()
