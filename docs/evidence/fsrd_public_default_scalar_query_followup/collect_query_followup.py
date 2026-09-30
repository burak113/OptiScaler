"""CPU-only query evidence copy; no probe, device, GPU, build or score invocation."""
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path('F:/OptiRevelations/OptiScaler-ffxD-alpha')
DEST = ROOT / 'docs/evidence/fsrd_public_default_scalar_query_followup'
OLD = ROOT / 'docs/evidence/fsrd_clean_response_stage_partition'
POST = ROOT / 'tools_tmp/fsrd_sdk_default_scalar_query_postrun_review_20261001'
PREP = ROOT / 'tools_tmp/fsrd_sdk_default_scalar_query_preparation_20260930'
PRE = ROOT / 'tools_tmp/fsrd_sdk_default_scalar_query_prelaunch_review_20260930'

def identity(p):
    p = Path(p)
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return {'path': str(p), 'bytes': p.stat().st_size, 'sha256': h.hexdigest()}

def verify(r):
    a = identity(r['path'])
    assert (a['bytes'], a['sha256']) == (r['bytes'], r['sha256']), (r, a)
    return a

def key(p):
    return str(Path(p).resolve()).casefold()

def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))

def write_new(p, value):
    with Path(p).open('x', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')

post_manifest = identity(POST / 'completion_manifest.json')
assert post_manifest['sha256'] == '609dbef57ca419418568d9b4ff81fdf4d5572fa8713f33078af6898424d637bc'
assert identity(POST / 'review.json')['sha256'] == 'cfe3660e3b0d6f253aeedd131be321bb2f6161305754e9166ed88cceb6194da6'
m = load(post_manifest['path'])
trusted = {}
for r in m['owned'] + m['external_records']:
    trusted[key(r['path'])] = r
for inc in m['inheritance']:
    verify(trusted[key(inc['manifest'])])
    child = load(inc['manifest'])
    for field in inc['record_keys']:
        for r in child[field]:
            old = trusted.setdefault(key(r['path']), r)
            assert (old['bytes'], old['sha256']) == (r['bytes'], r['sha256'])
trusted[key(post_manifest['path'])] = post_manifest

old_before = load(DEST / 'prior_archive_before.json')
assert old_before['existing_archive_manifest_sha256'] == '6e2e0ef8fc0ffc97f4a4acfaee5381f15ffadaa65e6e7a3c04b62f0b627279d6'
verify(old_before['historical_stage_document'])
assert old_before['historical_stage_document']['sha256'] == '9cf05417b76e5138c0fa543b5903f4147f2fd099fd88feebfc278aacc5a3e74a'
def verify_old_archive():
    now = sorted(str(p.relative_to(OLD)).replace('\\', '/') for p in OLD.rglob('*') if p.is_file())
    assert now == sorted(r['path'] for r in old_before['existing_archive_files'])
    for r in old_before['existing_archive_files']:
        verify({**r, 'path': str(OLD / r['path'])})
verify_old_archive()

copies, external = {}, {}
for base in [PREP, PRE, POST]:
    for p in sorted(base.iterdir()):
        if not p.is_file():
            continue
        r = trusted[key(p)]
        verify(r)
        if p.suffix.casefold() in {'.exe', '.obj'} or p.name in {
            'CPU_checks.json', 'independent_checks.json', 'pins_before.json', 'pins_after.json'}:
            external[key(p)] = {**r, 'purpose': 'Binary or expanded CPU/source pin evidence; retained at sealed original path.'}
        else:
            copies[key(p)] = r
for p in sorted((PREP / 'planned_query').iterdir()):
    assert p.is_file()
    r = trusted[key(p)]
    verify(r)
    copies[key(p)] = r
for r in m['external_records']:
    p = Path(r['path'])
    if p.parent == ROOT / 'tools_tmp':
        copies[key(p)] = r
# Provider/public headers and original compiler provenance remain external, pinned once.
for r in trusted.values():
    if key(r['path']) not in copies and key(r['path']) not in external:
        external[key(r['path'])] = {**r, 'purpose': 'Required original source/header/provider/compile identity referenced by the inherited query preparation and reviews.'}

for r in copies.values():
    target = (DEST / Path(r['path']).relative_to(ROOT / 'tools_tmp')).resolve()
    assert target.is_relative_to(DEST.resolve()) and not target.exists()
for n in ['external_references.json', 'copy_proof.json', 'manifest.json']:
    assert not (DEST / n).exists()

records = []
for r in sorted(copies.values(), key=lambda q: q['path']):
    verify(r)
    target = DEST / Path(r['path']).relative_to(ROOT / 'tools_tmp')
    target.parent.mkdir(parents=True, exist_ok=True)
    with Path(r['path']).open('rb') as src, target.open('xb') as dst:
        for b in iter(lambda: src.read(1024 * 1024), b''):
            dst.write(b)
    a = identity(target)
    assert (a['bytes'], a['sha256']) == (r['bytes'], r['sha256'])
    records.append({'archive_relative_path': str(target.relative_to(DEST)).replace('\\', '/'),
                    'bytes': a['bytes'], 'sha256': a['sha256'], 'source': r})
for r in list(copies.values()) + list(external.values()):
    verify(r)
verify_old_archive()

review = load(POST / 'review.json')
assert review['status'] == 'PASSED_PUBLIC_DEFAULT_SCALAR_QUERY_EVIDENCE_REVIEW'
assert review['blocking_findings'] == []
bits = list(struct.unpack('<6I', (PREP / 'planned_query/query_values.bin').read_bytes()))
assert bits == [r['actual_default_float32_bits'] for r in review['observed_default_values']]
assert review['actual_counts'] == {
    'create_entry': 1, 'create_returned': 1, 'created': 1,
    'query_entry': 6, 'query_returned': 6, 'query_ok': 6,
    'destroy_entry': 1, 'destroy_returned': 1, 'destroyed': 1,
    'rr_dispatch': 0, 'configure': 0, 'owned_execute': 0}

write_new(DEST / 'external_references.json', {
    'status': 'PINNED_QUERY_EXTERNAL_BINARIES_AND_EXPANDED_SOURCE_EVIDENCE',
    'records': sorted(external.values(), key=lambda r: r['path']),
    'inheritance': m['inheritance'],
    'scope': 'Copied compact manifests carry full original paths. Full source/compile checks need the external binary/header/large pin records; no SDK invocation is performed by this collector.'})
write_new(DEST / 'copy_proof.json', {
    'status': 'ALL_QUERY_COPIES_SOURCE_IDENTITIES_AND_PRIOR_ARCHIVE_BYTES_VERIFIED',
    'copied_count': len(records), 'copied_bytes': sum(r['bytes'] for r in records),
    'external_count': len(external),
    'prior_archive_file_count': len(old_before['existing_archive_files']),
    'prior_archive_all_bytes_unchanged': True,
    'prior_archive_manifest': identity(OLD / 'manifest.json'),
    'historical_stage_document': old_before['historical_stage_document'],
    'historical_document_identity_resolution': 'The prior archive authored-record path denotes the pre-followup live document version; its original bytes are preserved at historical_stage_document_before_query_followup.md in this separate archive. Original archive seal/snapshots were not rewritten.',
    'actual_new_SDK_GPU_native_build_scorer': 0,
    'overwrite_delete_stage_commit': 0,
    'measured_original_query_contexts': 1, 'successful_original_public_queries': 6,
    'default_vector_RR_image_test_measured': False})
authored = [identity(DEST / n) for n in [
    'collect_query_followup.py', 'historical_stage_document_before_query_followup.md',
    'prior_archive_before.json', 'external_references.json', 'copy_proof.json']]
authored += [identity(ROOT / 'docs' / n) for n in [
    'fsrd_clean_material_response_stage_partition.md', 'fsrd_public_default_scalar_query_followup.md']]
write_new(DEST / 'manifest.json', {
    'status': 'SEALED_PUBLIC_DEFAULT_SCALAR_QUERY_DOCUMENTATION_FOLLOWUP',
    'copied_records': records, 'authored_records': authored, 'self_entry_excluded': True,
    'copied_count': len(records), 'copied_bytes': sum(r['bytes'] for r in records),
    'original_query_postreview_manifest': post_manifest,
    'actual_original_query_counts': review['actual_counts'],
    'measured_values': review['observed_default_values'],
    'cumulative_contexts': {'RR_workload_contexts': 414, 'query_only_contexts': 1, 'completed_SDK_contexts': 415,
                            'RR_API': 22074, 'queued_completed_RR': 22066, 'recorded_only_discards': 8, 'no_API_omissions': 4},
    'actual_new_SDK_GPU_native_build_scorer': 0,
    'quality_accepted': False, 'default_vector_image_test_measured': False})
print(json.dumps({'manifest': identity(DEST / 'manifest.json'),
                  'copy_proof': identity(DEST / 'copy_proof.json'),
                  'copied_count': len(records), 'copied_bytes': sum(r['bytes'] for r in records),
                  'external_count': len(external), 'authored_count': len(authored)}, indent=2))
