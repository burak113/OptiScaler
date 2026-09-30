from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'docs/evidence/fsrd_native_discarded_recording_diagnostic'
PACKAGES = [
    'fsrd_native_discarded_recording_diagnostic',
    'fsrd_native_discarded_recording_review',
    'fsrd_native_discarded_recording_post_native_audit',
    'fsrd_native_discarded_recording_visual',
]
PINS = {
    'fsrd_native_discarded_recording_diagnostic/execution_completion_manifest.json':
        '8baca7561be8e9569bb222182aa85ee2a61bd518989f7fa17a955af588ba68d8',
    'fsrd_native_discarded_recording_review/completion_ready_manifest.json':
        '7148e5393a4754bf882037036bf7aec8e59fa1c447b1ca49e65d6d1d6276c63f',
    'fsrd_native_discarded_recording_review/producer_final_seal_review.json':
        '541234c2a26e34f540e4d64959509cc84ccdb168cc2ce858c7f806b4a728e40b',
    'fsrd_native_discarded_recording_post_native_audit/completion_manifest.json':
        'c4f21c47d6a223a34ead253ec2cc29ef7161014ca16c21147eacc444f24ff841',
    'fsrd_native_discarded_recording_visual/completion_manifest.json':
        'e17898b4f309899ba932e663e0d6224b5a76b950e11fa80c32f0c8eb138d5b80',
}

def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

assert not DEST.exists(), 'Preserve completed archive'
for relative, digest in PINS.items():
    name, filename = relative.split('/', 1)
    path = ROOT / 'tools_tmp' / (name + '_20260930') / filename
    assert sha(path) == digest, relative
    document = json.loads(path.read_text())
    for key in ('files', 'external_frozen_sources', 'review_external_files'):
        for row in document.get(key, []):
            source = Path(row['path'])
            assert source.stat().st_size == row['bytes'] and sha(source) == row['sha256'], str(source)

producer = json.loads((ROOT / 'tools_tmp/fsrd_native_discarded_recording_diagnostic_20260930/evidence/results.json').read_text())
assert (producer['completed_native_contexts'], producer['successful_API_RR_recordings'],
        producer['queued_RR_dispatches'], producer['discarded_RR_recordings']) == (8, 462, 458, 4)
assert all(row['guard']['status'] == 'completed' and
           all(row['native_work_accounting']['final_stdout_counters'][key] == 0
               for key in ('validation_errors', 'validation_warnings', 'sdk_errors', 'sdk_warnings'))
           for row in producer['cases'].values())
DEST.mkdir(parents=True)
copied = []
external = []

def collect(source, relative):
    item = {'source': str(source), 'bytes': source.stat().st_size, 'sha256': sha(source)}
    large_buffer = source.suffix.lower() == '.bin' and (
        source.name in ('diffuse.bin', 'specular.bin') or source.name.startswith('input'))
    if large_buffer or source.suffix.lower() in ('.exe', '.obj', '.dll', '.cso', '.npz', '.npy'):
        item['retained_external_payload'] = True
        external.append(item)
        return
    target = DEST / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    assert sha(target) == item['sha256']
    item['archive'] = relative.as_posix()
    copied.append(item)

for name in PACKAGES:
    folder = ROOT / 'tools_tmp' / (name + '_20260930')
    for source in sorted(folder.rglob('*')):
        if source.is_file() and '__pycache__' not in source.parts:
            collect(source, Path(name) / source.relative_to(folder))
collect(ROOT / 'tools_tmp/h2_root_launch_authorization_20260930.json', Path('root_launch_authorization.json'))
collect(Path(__file__), Path('collector_source.py'))
manifest = {
    'schema': 'native-discarded-recording-archive-v1', 'branch': 'ffxD-experimental-alpha',
    'base_commit': '73743433d96524eefa6f1fcef0fc8a98ec033d66',
    'quality_accepted': False, 'runtime_implemented': False, 'game_run': False,
    'new_native_contexts': 8, 'successful_API_RR_recordings': 462,
    'queued_RR_dispatches': 458, 'discarded_RR_recordings': 4,
    'completed_total_contexts': 390, 'completed_total_successful_API_RR_recordings': 20542,
    'completed_total_queued_RR_dispatches': 20538, 'completed_total_discarded_RR_recordings': 4,
    'copied_file_count': len(copied), 'copied_files': copied,
    'external_payload_count': len(external), 'external_payloads': external,
    'limits': [
        'Missing GPU24 and successful SDK record24 effects not isolated in this batch',
        'RESET/fresh-tail exactness measured in this cohort, not a universal guarantee',
        'No game/current-alpha capture or image-quality/truth claim',
        'No-API frame24 preparation is outside this completed evidence package',
        'Prelaunch and post-native audit chronology retained separately',
    ],
}
(DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
(DEST / '.gitattributes').write_text('* -text\n')
print(json.dumps({'copied_files': len(copied), 'external_payloads': len(external),
                  'manifest_sha256': sha(DEST / 'manifest.json')}))
