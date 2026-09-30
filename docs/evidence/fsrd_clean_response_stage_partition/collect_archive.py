"""One-shot, CPU-only byte copy from sealed evidence; never overwrites targets."""
import hashlib
import json
from pathlib import Path

ROOT = Path('F:/OptiRevelations/OptiScaler-ffxD-alpha')
DEST = ROOT / 'docs/evidence/fsrd_clean_response_stage_partition'
PLAN = ROOT / 'tools_tmp/fsrd_clean_response_archive_plan_20260930.json'
PLAN_SHA = '25b409ba99d40b7cbd7cf11f3ead8e56b2592f3296f85d4d3140d74910fd54ee'
LATEST = ROOT / 'tools_tmp/fsrd_clean_specular_hit_alpha_composition_postrun_review_20260930/completion_manifest.json'
LATEST_SHA = 'dd375620aecf1a45d947975e9afd5ce422ab1ecb22562199e6bff9b97f16e894'
POST = LATEST.parent
PRE = ROOT / 'tools_tmp/fsrd_clean_specular_hit_alpha_composition_prelaunch_review_20260930'
PRODUCER = ROOT / 'tools_tmp/fsrd_clean_specular_hit_alpha_composition_preparation_20260930'

def identity(path):
    path = Path(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': h.hexdigest()}

def verify(rec):
    actual = identity(rec['path'])
    assert actual['bytes'] == rec['bytes'] and actual['sha256'] == rec['sha256'], (rec, actual)
    return actual

def key(path):
    return str(Path(path).resolve()).casefold()

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write_new(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')

assert identity(PLAN)['sha256'] == PLAN_SHA
assert identity(LATEST)['sha256'] == LATEST_SHA
plan = load(PLAN)
latest = load(LATEST)
assert len(plan['files']) == 235 and sum(r['bytes'] for r in plan['files']) == 3263846
trusted = {}
for rec in latest['files'] + latest['external_sources']:
    trusted[key(rec['path'])] = rec
for m in latest['inherited_source_manifests']:
    verify(m)
    data = load(m['path'])
    for field in m['records_keys']:
        for rec in data[field]:
            old = trusted.setdefault(key(rec['path']), rec)
            assert (old['bytes'], old['sha256']) == (rec['bytes'], rec['sha256'])

copies = {}
external = {}
excluded = []

def copy_record(rec, relative=None):
    source = Path(rec['path']).resolve()
    relative = relative or str(source.relative_to(ROOT / 'tools_tmp'))
    target = (DEST / relative).resolve()
    assert target.is_relative_to(DEST.resolve()) and target != DEST.resolve(), str(target)
    assert source != target
    old = copies.setdefault(key(target), {'source': rec, 'target': str(target)})
    assert old['source']['sha256'] == rec['sha256']

def add_copy(path):
    rec = trusted[key(path)]
    verify(rec)
    copy_record(rec)

def add_external(rec, purpose):
    rec = verify(rec)
    old = external.setdefault(key(rec['path']), {**rec, 'purpose': []})
    assert (old['bytes'], old['sha256']) == (rec['bytes'], rec['sha256'])
    if purpose not in old['purpose']:
        old['purpose'].append(purpose)

for rec in plan['files']:
    verify(rec)
    if 'fsrd_batch_clean_findings_draft_20260930' in rec['path']:
        excluded.append({**rec, 'reason': 'Historical pending-result narrative; original retained, final findings use completed reviews.'})
        continue
    target = ROOT / rec['proposed_archive_relative_path']
    copy_record(rec, str(target.relative_to(DEST)))
for rec in plan['external_large_manifest_or_results']:
    add_external(rec, 'Original proposal external evidence; needed with full raw/source manifests for reproduction.')
add_external(identity(PLAN), 'Authenticated root proposal, 235 source records; two historical draft records excluded from publication.')
add_external(identity(LATEST), 'Final complete source/output/postreview manifest; expand files, external_sources and inherited_source_manifests.')
for m in latest['inherited_source_manifests']:
    add_external(m, 'Required original inherited manifest; expand its records_keys and preserve original path for script resolution.')

# Latest 3-trace preparation and one-line analyzer amendment. No binary/raw-tree copying.
for p in sorted(PRODUCER.iterdir()):
    if not p.is_file():
        continue
    if p.suffix.casefold() in {'.exe', '.npz'} or p.name in {
        'composition_metrics.json', 'execution_results.json', 'registration.json',
        'pre_execution_freeze.json', 'completion_manifest.json', 'graph_and_lobe_mapping.json'}:
        add_external(trusted[key(p)], 'Latest 3-trace full data/payload/source graph or binary; required for exact replay and metrics.')
    else:
        add_copy(p)
for sub in ['frozen_metric_sources', 'frozen_shader']:
    for p in sorted((PRODUCER / sub).iterdir()):
        if p.suffix.casefold() == '.cso':
            add_external(trusted[key(p)], 'Actual historical composition shader binary; no new compile provenance asserted.')
        else:
            add_copy(p)
for p in sorted(PRE.iterdir()):
    if p.is_file():
        if p.name == 'completion_manifest.json':
            add_external(trusted[key(p)], 'Latest bounded prelaunch review full inherited source manifest.')
        else:
            add_copy(p)
for p in sorted(POST.iterdir()):
    if p.is_file() and p.name != 'completion_manifest.json':
        if p.name == 'metric_reproduction.json':
            add_external(trusted[key(p)], 'Independently reproduced full 9 values x 2 references x 4 windows and pair dictionaries.')
        else:
            add_copy(p)

# Twelve representative actual jobs: startup, first A0 divergence, mature onset and last frame.
# All 192 jobs and 576 raw outputs remain authenticated by the full external manifest.
for frame in [0, 39, 48, 63]:
    for arm in ['A0_r0', 'A10_r0', 'A0_r1']:
        for name in ['job.txt', 'resource_guard.json', 'stdout.log', 'stderr.log']:
            add_copy(PRODUCER / 'planned_jobs' / f'{frame:02}' / arm / name)

auth = ROOT / 'tools_tmp/fsrd_specular_hit_alpha_composition_v2_root_authorization_20260930.json'
receipt = ROOT / 'tools_tmp/fsrd_specular_hit_alpha_composition_root_tool_observations_20260930.json'
add_copy(auth)
assert trusted[key(receipt)]['sha256'] == '6471737109cb29f7c8cbb99f98710f92b0f4b48da366e20d1babacfe3e64841f'
add_external(trusted[key(receipt)], 'Full actual root tool receipt; driver/once V2 CPU analysis chronology and source observations.')

# Validate the complete destination scope before the first copy. Fresh targets only.
for item in copies.values():
    assert not Path(item['target']).exists(), item['target']
for name in ['external_references.json', 'copy_proof.json', 'manifest.json']:
    assert not (DEST / name).exists(), name

records = []
for item in sorted(copies.values(), key=lambda r: r['target']):
    rec = item['source']
    verify(rec)
    target = Path(item['target'])
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation; never overwrite an existing artifact.
    with Path(rec['path']).open('rb') as src, target.open('xb') as dst:
        for block in iter(lambda: src.read(1024 * 1024), b''):
            dst.write(block)
    out = identity(target)
    assert (out['bytes'], out['sha256']) == (rec['bytes'], rec['sha256'])
    records.append({'archive_relative_path': str(target.relative_to(DEST)).replace('\\', '/'),
                    'bytes': out['bytes'], 'sha256': out['sha256'], 'source': rec})

# Verify each copied source again: originals have not been changed by archival work.
for item in copies.values():
    verify(item['source'])
for rec in external.values():
    verify(rec)
write_new(DEST / 'external_references.json', {
    'status': 'PINNED_EXTERNAL_REQUIRED_REPRODUCTION_INPUTS_NOT_COPIED',
    'records': sorted(external.values(), key=lambda r: r['path']),
    'raw_buffer_resolution': 'Original full manifests carry each job input/output, helper EXE/CSO, native raw lobes, 184-byte controls, NPZ and source identity. Expand the specified record keys; original machine paths are required. This compact archive is not a standalone complete replay.',
    'latest_manifest_expansion': latest['inherited_source_manifests'],
    'representative_latest_job_frames': [0, 39, 48, 63],
    'latest_actual_job_log_scope': '12 of 192 actual jobs; 48 small job/guard/log files copied. All remaining raw buffers/jobs/logs retained externally; no 576-output-tree copy.',
    'publication_exclusions': excluded,
    'future_query': 'Design/compile only at this archive boundary: actual queries=0, query contexts=0, measured numeric default values absent.'})
write_new(DEST / 'copy_proof.json', {
    'status': 'ALL_COPIED_BYTES_AND_ORIGINAL_POSTCOPY_IDENTITIES_EQUAL',
    'source_proposal': identity(PLAN),
    'proposal_count': 235, 'proposal_bytes': 3263846,
    'publication_excluded_draft_count': len(excluded),
    'copied_source_count': len(records), 'copied_bytes': sum(r['bytes'] for r in records),
    'external_reference_count': len(external), 'destination_scope': str(DEST.resolve()),
    'overwrites': 0, 'moves_or_deletes': 0,
    'actual_new_GPU_native_build_scorer': 0, 'git_stage_commit_push': 0,
    'new_manifest_self_entry_excluded': True})
authored = [identity(DEST / n) for n in ['collect_archive.py', 'external_references.json', 'copy_proof.json']]
authored.append(identity(ROOT / 'docs/fsrd_clean_material_response_stage_partition.md'))
write_new(DEST / 'manifest.json', {
    'status': 'SEALED_COMPACT_CLEAN_RESPONSE_STAGE_PARTITION_ARCHIVE',
    'copied_records': records, 'authored_records': authored,
    'copied_source_count': len(records), 'copied_bytes': sum(r['bytes'] for r in records),
    'external_reference_index': identity(DEST / 'external_references.json'),
    'self_entry_excluded': True,
    'source_branch_at_preparation': 'ffxD-experimental-alpha',
    'source_HEAD_at_preparation': '50e376ce8c99739efbd9a86055dbe4995d50155e',
    'quality_accepted': False, 'goal_resolved': False,
    'actual_new_GPU_native_build_scorer': 0,
    'native_cumulative': {'contexts': 414, 'successful_API_RR': 22074, 'queued_completed_RR': 22066, 'recorded_only_discards': 8, 'no_API_omissions_separate': 4},
    'clean_stage_pipeline': {'helpers': 516, 'explicit_Dispatch': 516, 'opaque_SDK_shader_count': None}})
print(json.dumps({'manifest': identity(DEST / 'manifest.json'), 'copy_proof': identity(DEST / 'copy_proof.json'),
                  'copied_source_count': len(records), 'copied_bytes': sum(r['bytes'] for r in records),
                  'external_reference_count': len(external), 'authored_records': len(authored)}, indent=2))
