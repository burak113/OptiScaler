from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / 'tools_tmp/fsrd_native_gap_cpu_record_control_20260930'
REVIEW = ROOT / 'tools_tmp/fsrd_native_gap_cpu_record_control_review_20260930'
TARGET = ROOT / 'tools_tmp/gap_root_launch_authorization_20260930.json'
PINS = {
    PRODUCER / 'preparation_completion_manifest.json': '19b63ab8f27ceaa6a03632b29414afc654a273a47e5636f7f30f079de8d04317',
    PRODUCER / 'registration.json': '013d235048694e20650ae1ce4f779428c0b80422b3ee165b3e2c2289ecefd3ed',
    PRODUCER / 'pre_native_freeze.json': 'aed2ca795adf7a04f3a1404f9622bc89cd56f845b09cb358ea92d27e1bd4528f',
    PRODUCER / 'run_native.py': 'f0d0f2e2669ddf3a07fa44b008858ef5c679194acc4245cb2dde53f8201debef',
    PRODUCER / 'fsrd_rr_gap_control.cpp': '84ca72c54ab173299d7f82056a297b6daf3f4e2ef12c8c0c0691f9748321b8f3',
    PRODUCER / 'fsrd_rr_gap_control.exe': 'e3769339c4089e8c0af46434a949c2ffabbef1ab4b5084e701aae939f5248fc1',
    PRODUCER / 'native_resource_guard.py': 'b70e18d0f13963e0250c371171933429446cf304041c9a16d971e9898d211814',
    REVIEW / 'final_pre_native_review.json': '450a55e22db99a80fd882c9f3a90635729c5e07ef81185fda6915f7e94710220',
    REVIEW / 'completion_ready_manifest.json': '1acb148c4492657abcfcfe44530245c2d69616225903d82bd80b77a78d899a3b',
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
for document in (PRODUCER / 'preparation_completion_manifest.json', REVIEW / 'completion_ready_manifest.json'):
    payload = json.loads(document.read_text())
    for key in ('files', 'external_sources', 'external_frozen_sources', 'external_pins'):
        for row in payload.get(key, []):
            path = Path(row['path'])
            assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], str(path)
            verified += 1
assert verified >= 199 + 23
payload = {
    'schema': 'root-matched-GPU-gap-bounded-native-launch-authorization-v1',
    'branch': 'ffxD-experimental-alpha', 'head': head,
    'scope': 'Only the frozen eight matched-gap native diagnostic children; no production or game changes',
    'user_authorization': 'Existing request to investigate causes carefully with agents and continue the stain/wave goal',
    'pins': [{'path': str(path), 'sha256': digest} for path, digest in PINS.items()],
    'verified_manifest_references': verified,
    'planned_contexts': 8, 'planned_successful_API_RR_recordings': 508,
    'planned_queued_RR_dispatches': 504, 'planned_discarded_API_records': 4,
    'planned_no_API_frame_omissions': 4, 'planned_counts_are_measurements': False,
    'prior_H2_counts_are_new_work': False, 'quality_accepted': False,
    'SDK_discard_or_RESET_fresh_identity_guaranteed': False,
}
with TARGET.open('x', encoding='utf-8', newline='\n') as stream:
    json.dump(payload, stream, indent=2)
    stream.write('\n')
print(json.dumps({'status': 'authorized_frozen_eight_only', 'authorization_sha256': sha(TARGET),
                  'verified_manifest_references': verified}))
