from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / 'tools_tmp/fsrd_native_gap_cpu_record_control_20260930'
REVIEW = ROOT / 'tools_tmp/fsrd_native_gap_remaining_v2_review_20260930'
TARGET = ROOT / 'tools_tmp/gap_remaining_v2_root_launch_authorization_20260930.json'
PINS = {
    PRODUCER / 'remaining_v2_preparation_completion_manifest.json': 'e2c6a2d5fb90b111e22c534f0cdf9d8a395fdbfcd2014ff327a6209850bca342',
    PRODUCER / 'remaining_v2_registration.json': '8c126e93e85260af70e7ca5e13801c7ed7a0e5bc09e2d38a1f382829e6ff9e79',
    PRODUCER / 'remaining_v2_pre_native_freeze.json': '82209ebfaa0b7ec5cb61dc9e5167633a987b81949eceea6543a4ba3b17687799',
    PRODUCER / 'partial_v1_completion_manifest.json': '82b78b5c6628eae7c44afd23d492b6ccd43f6ab5a47e79142dde9c16c5f1eab2',
    PRODUCER / 'run_remaining_native_v2.py': '36fe9e824e9bec32c92828733484157ef2583f2e43e0626cf0fd6f99d965baac',
    PRODUCER / 'fsrd_rr_gap_control.cpp': '84ca72c54ab173299d7f82056a297b6daf3f4e2ef12c8c0c0691f9748321b8f3',
    PRODUCER / 'fsrd_rr_gap_control.exe': 'e3769339c4089e8c0af46434a949c2ffabbef1ab4b5084e701aae939f5248fc1',
    PRODUCER / 'native_resource_guard.py': 'b70e18d0f13963e0250c371171933429446cf304041c9a16d971e9898d211814',
    REVIEW / 'final_pre_continuation_review.json': '2fcfc4bc92b66ee8e4bb7e21550b52e3bf607de6b94773b2afc2013e2c132853',
    REVIEW / 'completion_ready_manifest.json': '95f2b129f7092d785977d6ffdc86534cdde295c21ddec8dcc1b4fbe4f86449bf',
}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

assert not TARGET.exists(), 'Preserve root authorization'
assert subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT).decode().strip() == 'ffxD-experimental-alpha'
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
assert head == '00e662dce4b4672738a048dea04b8d84e202f72b'
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)
for path, digest in PINS.items():
    assert sha(path) == digest, str(path)
verified = 0
for path in (PRODUCER / 'remaining_v2_preparation_completion_manifest.json', REVIEW / 'completion_ready_manifest.json'):
    document = json.loads(path.read_text())
    for key in ('files', 'external_sources', 'external_frozen_sources', 'external_pins'):
        for row in document.get(key, []):
            source = Path(row['path'])
            assert source.stat().st_size == row['bytes'] and sha(source) == row['sha256'], str(source)
            verified += 1
assert verified >= 241 + 23
old = json.loads((PRODUCER / 'evidence/results.json').read_text())
assert old['status'] == 'failed_preserved' and old['metadata_accepted_native_contexts'] == 1
assert [old[key] for key in ('completed_native_contexts', 'successful_API_RR_recordings',
                           'queued_RR_dispatches', 'discarded_RR_recordings', 'no_API_omissions')] == [2, 127, 126, 1, 1]
payload = {
    'schema': 'root-matched-gap-post-observation-six-only-launch-authorization-v1',
    'branch': 'ffxD-experimental-alpha', 'head': head,
    'scope': 'Only six unattempted original registered cases; old two are not rerun or counted as new',
    'user_authorization': 'Existing request to carefully investigate causes with agents and continue the stain/wave goal',
    'pins': [{'path': str(path), 'sha256': digest} for path, digest in PINS.items()],
    'verified_manifest_references': verified,
    'planned_new_contexts': 6, 'planned_new_successful_API_RR_recordings': 381,
    'planned_new_queued_RR_dispatches': 378, 'planned_new_discarded_API_records': 3,
    'planned_new_no_API_frame_omissions': 3, 'planned_counts_are_measurements': False,
    'warning_rule': 'NoAPI zero or one exact retained frame-index-jump reset warning; record-discard zero; all other diagnostics zero',
    'amended_after_observing_first_no_API_warning': True,
    'original_failed_V1_and_metadata_acceptance_1_unchanged': True,
    'diagnostic_admissibility_is_quality_acceptance': False, 'quality_accepted': False,
    'production_changes': False, 'game_changes': False,
}
with TARGET.open('x', encoding='utf-8', newline='\n') as stream:
    json.dump(payload, stream, indent=2)
    stream.write('\n')
print(json.dumps({'status': 'authorized_frozen_remaining_six_only', 'authorization_sha256': sha(TARGET),
                  'verified_manifest_references': verified}))
