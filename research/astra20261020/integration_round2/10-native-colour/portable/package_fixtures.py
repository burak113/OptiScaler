"""Create a deterministic, verified ZIP of synthetic native transport fixtures.

ZIP_STORED removes compressor-version variability. No GPU result is fabricated:
expected outputs come from the delivered CPU model and carry that provenance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

from fixtures import CASES, make_case, write_fixtures
from verify_output import verify


def package(output, manifest_path):
    output, manifest_path = Path(output).resolve(), Path(manifest_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    checks = {name: verify(make_case(name), make_case(name)['packed']['expected_output']) for name in CASES}
    with tempfile.TemporaryDirectory(prefix='astra10-fixtures-') as temporary:
        directory = Path(temporary)
        generated = write_fixtures(directory)
        files = {}
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
            for path in sorted(directory.rglob('*')):
                if not path.is_file():
                    continue
                relative = path.relative_to(directory).as_posix()
                data = path.read_bytes()
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
                files[relative] = hashlib.sha256(data).hexdigest()
    result = dict(schema='astra10-native-fixture-archive-v1',
        archive_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        archive_bytes=output.stat().st_size, archive_format='ZIP_STORED; fixed timestamps and permissions',
        generated_by='portable/package_fixtures.py and the CPU packed_model.py',
        cases=len(CASES), compiler_or_gpu_executed=False, quality_accepted=False,
        fixture_manifest=generated, invariant_checks=checks, files=files)
    manifest_path.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    result = package(args.output, args.manifest)
    print(json.dumps({key:result[key] for key in ('cases','archive_bytes','archive_sha256','compiler_or_gpu_executed')}))


if __name__ == '__main__':
    main()
