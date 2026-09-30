from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'docs/evidence/fsrd_native_gap_call_presence'
PACKAGES = ['fsrd_native_gap_cpu_record_control', 'fsrd_native_gap_cpu_record_control_review',
            'fsrd_native_gap_warning_observation_audit', 'fsrd_native_gap_remaining_v2_review',
            'fsrd_native_gap_full_post_native_audit', 'fsrd_outer_failure_policy_review']
PINS = {
    'fsrd_native_gap_cpu_record_control/combined_execution_completion_manifest.json': 'f37e8decd8e039aea9c0da1df90a79947ace81b5c6503b5be4bb0401d14fcca3',
    'fsrd_native_gap_cpu_record_control_review/completion_ready_manifest.json': '1acb148c4492657abcfcfe44530245c2d69616225903d82bd80b77a78d899a3b',
    'fsrd_native_gap_warning_observation_audit/completion_manifest.json': 'e7588fa5a50b334d4579d5a8037f073f63649ae98f28cd1f171cca9df522aa18',
    'fsrd_native_gap_remaining_v2_review/completion_ready_manifest.json': '95f2b129f7092d785977d6ffdc86534cdde295c21ddec8dcc1b4fbe4f86449bf',
    'fsrd_native_gap_full_post_native_audit/completion_manifest.json': 'd5b9ade9392cb46b4866ff87d40cdf4de91e2f486605bd191f968e11eeccc0f4',
    'fsrd_outer_failure_policy_review/review.json': '2f2187e33db20de5624cfc428d701eecb5406e9eef03be98bdacdd2eee0501f0',
}

def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def verify_identities(value):
    if isinstance(value, dict):
        if all(key in value for key in ('path', 'bytes', 'sha256')):
            path = Path(value['path'])
            if not path.is_absolute():
                path = ROOT / path
            assert path.stat().st_size == value['bytes'] and sha(path) == value['sha256'], str(path)
        for child in value.values():
            verify_identities(child)
    elif isinstance(value, list):
        for child in value:
            verify_identities(child)

assert not DEST.exists(), 'Preserve completed archive'
for relative, digest in PINS.items():
    name, filename = relative.split('/', 1)
    path = ROOT / 'tools_tmp' / (name + '_20260930') / filename
    assert sha(path) == digest, relative
    verify_identities(json.loads(path.read_text()))
producer = ROOT / 'tools_tmp/fsrd_native_gap_cpu_record_control_20260930'
old = json.loads((producer / 'evidence/results.json').read_text())
remaining = json.loads((producer / 'evidence/remaining_v2_results.json').read_text())
keys = ('completed_native_contexts', 'successful_API_RR_recordings', 'queued_RR_dispatches',
        'discarded_RR_recordings', 'no_API_omissions')
assert old['status'] == 'failed_preserved' and old['metadata_accepted_native_contexts'] == 1
assert [old[key] for key in keys] == [2, 127, 126, 1, 1]
assert [remaining[key] for key in keys] == [6, 381, 378, 3, 3]
assert remaining['metadata_accepted_native_contexts'] == 6
assert sum(row['native_work_accounting']['final_stdout_counters']['sdk_warnings']
           for stage in (old, remaining) for row in stage['cases'].values()) == 2
DEST.mkdir(parents=True)
copied = []
external = []

def collect(source, relative):
    item = {'source': str(source), 'bytes': source.stat().st_size, 'sha256': sha(source)}
    raw_buffer = source.suffix.lower() == '.bin' and (
        source.name in ('diffuse.bin', 'specular.bin') or source.name.startswith('input'))
    if raw_buffer or source.suffix.lower() in ('.exe', '.obj', '.dll', '.cso', '.npz', '.npy'):
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
# Preserve every pre-policy production source used by the failure-path review.
policy = json.loads((ROOT / 'tools_tmp/fsrd_outer_failure_policy_review_20260930/review.json').read_text())
assert policy['head'] == '00e662dce4b4672738a048dea04b8d84e202f72b'
for row in policy['source_pins']:
    relative = Path(row['path'])
    assert not relative.is_absolute() and '..' not in relative.parts
    source = ROOT / relative
    assert sha(source) == row['sha256'], row['path']
    collect(source, Path('outer_failure_pre_policy_source_snapshot') / relative)
for name in ('authorize_gap_native_20260930.py', 'gap_root_launch_authorization_20260930.json',
             'authorize_gap_remaining_v2_native_20260930.py', 'gap_remaining_v2_root_launch_authorization_20260930.json',
             'fsrd_gap_primary_doc_check_20260930.json'):
    collect(ROOT / 'tools_tmp' / name, Path('root') / name)
collect(Path(__file__), Path('collector_source.py'))
manifest = {
    'schema': 'native-gap-call-presence-archive-v1', 'branch': 'ffxD-experimental-alpha',
    'base_commit': '00e662dce4b4672738a048dea04b8d84e202f72b',
    'quality_accepted': False, 'runtime_implemented': False, 'game_run': False,
    'new_native_contexts': 8, 'successful_API_RR_recordings': 508, 'queued_RR_dispatches': 504,
    'discarded_RR_recordings': 4, 'no_API_omissions': 4, 'actual_SDK_warnings': 2,
    'original_V1_stage': {'completed_contexts': 2, 'successful_API_RR_recordings': 127, 'queued_RR': 126,
                         'SDK_discards': 1, 'no_API_omissions': 1, 'metadata_accepted': 1, 'status': 'failed_preserved'},
    'remaining_V2_stage': {'completed_contexts': 6, 'successful_API_RR_recordings': 381, 'queued_RR': 378,
                          'SDK_discards': 3, 'no_API_omissions': 3, 'diagnostic_accepted': 6},
    'completed_total_contexts': 398, 'completed_total_successful_API_RR_recordings': 21050,
    'completed_total_queued_RR_dispatches': 21042, 'completed_total_discarded_RR_recordings': 8,
    'completed_total_no_API_omissions_in_these_diagnostics': 4,
    'pre_policy_source_snapshots': len(policy['source_pins']),
    'copied_file_count': len(copied), 'copied_files': copied,
    'external_payload_count': len(external), 'external_payloads': external,
    'limits': ['V2 diagnostic warning allowance is post-observation, original V1 rejection preserved',
               'Same applied flags can accompany different effective SDK history',
               'Warning lacks frame number; gap/reset association is qualified inference',
               'Pinned synthetic wave/static camera/jitter does not establish title scheduling or stain cause',
               'Earlier H2 reference contexts are not counted as new work'],
}
(DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
(DEST / '.gitattributes').write_text('* -text\n')
print(json.dumps({'copied_files': len(copied), 'external_payloads': len(external),
                  'manifest_sha256': sha(DEST / 'manifest.json')}))
