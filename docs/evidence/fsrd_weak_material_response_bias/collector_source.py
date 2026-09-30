from pathlib import Path
import hashlib
import json
import shutil

ROOT=Path(__file__).resolve().parents[1]
TMP=ROOT/'tools_tmp'

def sha(path):
    d=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            d.update(block)
    return d.hexdigest()

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def verify_records(rows):
    for row in rows:
        p=Path(row['path'])
        if not p.is_absolute():p=ROOT/p
        assert sha(p)==row['sha256'],str(p)
        if 'bytes' in row:assert p.stat().st_size==row['bytes'],str(p)

PINS={
 'harmonic_reconstruction_endpoint_history_feasibility_20260930/completion_manifest.json':'058aac716bf0ba5e0f7f6504054364e3cb2a24dcb8d4e63e8705405518c0000a',
 'harmonic_reconstruction_endpoint_history_law_review_20260930/review.json':'0b6b29d5ff0c21288e08f81f84e88d05d7c0cf6a2c0eb75a71a61afb38401c32',
 'harmonic_reconstruction_endpoint_history_post_score_audit_20260930/completion_manifest.json':'6a67c432a560c381f7b1f31283fb79b3faeaefcb0f318b619b7c0c74db024806',
 'fsrd_weak_material_response_bias_diagnosis_20260930/completion_manifest_final.json':'ba93078cfec27fda146148e6c0cde9e1b113a02459f0e65df491a595789e2b06',
}
for relative,digest in PINS.items():assert sha(TMP/relative)==digest,relative
ep=TMP/'harmonic_reconstruction_endpoint_history_feasibility_20260930'
prod=read(ep/'completion_manifest.json');assert prod['self_entry_excluded'] and prod['CPU_analyzer_runs']==1 and prod['native_GPU_calls']==0
verify_records(prod['files']+prod['external_authorization_and_review'])
corrected=read(ep/'preparation_completion_manifest_corrected.json')
assert corrected['self_entry_excluded'] and len(corrected['files'])==21 and len(corrected['external_source_files'])==61
verify_records(corrected['files']+corrected['external_source_files'])
law=read(TMP/'harmonic_reconstruction_endpoint_history_law_review_20260930/review.json');assert not law['blocking_findings'];verify_records(law['pins'])
audit=read(TMP/'harmonic_reconstruction_endpoint_history_post_score_audit_20260930/completion_manifest.json')
assert audit['self_entry_excluded'] and audit['native_API_dispatches']==audit['GPU_jobs']==audit['CPU_model_calls']==audit['CPU_analyzer_runs']==0
verify_records(audit['files']+audit['external_pins'])
weak=read(TMP/'fsrd_weak_material_response_bias_diagnosis_20260930/completion_manifest_final.json')
assert weak['self_entry_excluded'] and weak['native_GPU_calls']==0 and not weak['producer_files_modified']
verify_records(weak['files']+weak['external_source_pins'])
assert sha(ep/'results.json')=='225848939eb620a3b712ead68dffdef4e23fd952b2865e9e98445df9b9ede93e'
results=read(ep/'results.json');assert len(results['native_rows'])==6 and len(results['known_operator_rows'])==24 and not results['quality_accepted']

def archive(name,packages,root_files,qualifications):
    dest=ROOT/'docs/evidence'/name
    assert not dest.exists(),'Preserve archive'
    dest.mkdir(parents=True)
    copied=[];external=[]
    def collect(source,relative):
        item=dict(source=str(source),bytes=source.stat().st_size,sha256=sha(source))
        if source.suffix.lower() in ('.npz','.npy','.exe','.dll','.obj','.cso','.binlog'):
            external.append(item);return
        target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        assert sha(target)==item['sha256']
        item['archive']=relative.as_posix();copied.append(item)
    for package in packages:
        folder=TMP/package
        for p in sorted(folder.rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts:collect(p,Path(package)/p.relative_to(folder))
    for filename in root_files:collect(TMP/filename,Path('root')/filename)
    collect(Path(__file__),Path('collector_source.py'))
    manifest=dict(schema='frozen-CPU-feasibility-and-diagnosis-archive-v1',branch='ffxD-experimental-alpha',
        collection_head='3b5b0b4b14f7fdab20e9297a388f2c4cfec88712',copied_file_count=len(copied),copied_files=copied,
        external_payload_count=len(external),external_payloads=external,quality_accepted=False,
        new_native_contexts=0,new_API_RR_recordings=0,new_GPU_jobs=0,runtime_change=False,game_run=False,
        current_total_contexts=398,current_total_API_RR_recordings=21050,current_total_queued_RR=21042,
        current_total_recorded_only_discards=8,current_separate_no_API_omissions=4,
        qualifications=qualifications)
    (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (dest/'.gitattributes').write_text('* -text\n')
    print(json.dumps(dict(archive=name,copied_files=len(copied),external_payloads=len(external),manifest_sha256=sha(dest/'manifest.json'))))

archive('fsrd_reconstruction_endpoint_history',[
 'harmonic_reconstruction_endpoint_history_feasibility_20260930',
 'harmonic_reconstruction_endpoint_history_law_review_20260930',
 'harmonic_reconstruction_endpoint_history_post_score_audit_20260930'],
 ['authorize_endpoint_cpu_scores_20260930.py','endpoint_root_cpu_authorization_20260930.json'],[
 'One frozen candidate, one CPU scorer run; same six saved responses and24 constructed controls, no new native.',
 'Full combined acceptance0/6, mature5/6; weak noise/gain failure and known sharedbias/phase/constant-speed failures preserved.',
 'Original preparation empty self-entry preserved; separately corrected seal verified before scoring.',
 'Independent108 full/mature dictionaries exact from saved six candidate arrays; known24 candidate arrays unsaved, authenticated report/input/comparators only.',
 'Other7sourcefamilies+22adversaries still lack matching native TP coverage; no current-alpha game acceptance.'])
archive('fsrd_weak_material_response_bias',['fsrd_weak_material_response_bias_diagnosis_20260930'],[],[
 'Allsix clean_reference arrays are exact constructed raw fixture targets, not SDK clean responses.',
 'Measured P error, B-minus-TP and endpoint shifts locate coefficient bias algebraically; no opaque native cause identification.',
 'Diagnostic SVD/dot roundoff assertion failure preserved; only local diagnostic tolerance repaired, no score/model change.',
 'Actual clean converter/native response remains unmeasured; raw FP16 quantization cannot replace SDK demodulated signal inputs.'])
