from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,shlex,struct

ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha')
P=ROOT/'tools_tmp/fsrd_native_discarded_recording_diagnostic_20260930'
OUT=Path(__file__).resolve().parent
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):
    p=Path(p);return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def load(p):return json.loads(Path(p).read_text())
def check(items):
    for item in items:assert identity(item['path'])==item,item['path']
def save(name,v):
    with (OUT/name).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(v,f,indent=2,allow_nan=False);f.write('\n')

reg=load(P/'registration.json');freeze=load(P/'pre_native_freeze.json')
assert reg['status']=='prepared_built_preregistered_NOT_AUTHORIZED_TO_RUN'
assert not (P/'evidence/results.json').exists(), 'This is strictly pre-native review'
assert reg['actual_native_contexts']==reg['actual_successful_API_RR_recordings']==reg['actual_queued_RR_dispatches']==0
assert freeze['actual_native_contexts']==freeze['actual_successful_API_RR_recordings']==freeze['actual_queued_RR_dispatches']==0
check(freeze['files']);check(freeze['external_sources'])
pre_pins=[identity(P/n) for n in ['prepare.py','run_native.py','analyze.py','registration.json','pre_native_freeze.json','fsrd_rr_discard.cpp','fsrd_rr_discard.exe','source_insertion_whitelist.json']]
whitelist=load(P/'source_insertion_whitelist.json')
assert whitelist['original']==reg['original_runner'] and whitelist['new_source']==reg['new_source']
source=Path(whitelist['original']['path']).read_text()
assert source==(P/'original_fsrd_rr_runner.cpp').read_text()
expected_labels={
 'optional_frame_arguments','source_frame_range','presence_and_recording_counters','external_state_snapshot',
 'source_frame_index','recovery_reset_only_at_registered_source_frame','successful_API_record_then_discard_without_submission',
 'executed_dispatch_accounting_after_completed_fence','presence_and_observed_source_frame_mapping_after_actual_readback',
 'close_presence_outputs','separate_recorded_queued_discarded_completion_counts','standard_array_include'
}
assert {r['label'] for r in whitelist['operations'] if r['kind']=='source_replacement'}==expected_labels
assert sum(r['kind']=='absolute_include' for r in whitelist['operations'])==3
for op in whitelist['operations']:
    assert source.count(op['before'])==1
    source=source.replace(op['before'],op['after'])
actual=(P/'fsrd_rr_discard.cpp').read_text();assert source==actual
assert 'dispatch.frameIndex=sourceFrame;' in actual
api_pos=actual.index('ff(api.Dispatch(&context,&dispatch.header),"dispatch RR");')
skip_start=actual.index('if(skipFrame>=0 && sourceFrame==unsigned(skipFrame))',api_pos)
skip_end=actual.index('        for(unsigned i=7;i<9;++i)',skip_start)
skip=actual[skip_start:skip_end]
assert 'hr(cmd->Close(),"close discarded recording");' in skip and 'continue;' in skip
assert 'tex[i].state=externalStatesBeforeRecording[i]' in skip
assert 'presenceOut.write(&absent,1)' in skip
assert 'CopyTextureRegion(' not in skip and 'ExecuteCommandLists(' not in skip and 'queue->Signal(' not in skip and '->Map(' not in skip
assert 'previousSubmittedSourceFrame!=int(sourceFrame)-1 || previousCompletedFence==0' in skip
reset_at=actual.index('hr(alloc->Reset(),"reset allocator");')
assert reset_at<actual.index('externalStatesBeforeRecording{}',reset_at)<api_pos
assert 'previousCompletedFence=frame+1' in actual

old=Path(reg['source_frozen_wave_P']);old_id=load(old/'amd_context_identity.json')
assert old_id['dll_sha256']==reg['dll']['sha256']=='48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
for name,h in old_id['inputs'].items():assert sha(old/name)==h
old_control=(old/'dispatch_controls.bin').read_bytes()
assert sha(old/'dispatch_controls.bin')==old_id['applied_dispatch_sha256'] and len(old_control)==64*184
for i in range(64):
    index,flag,w,h=struct.unpack_from('<4I',old_control,184*i)
    assert index==i and flag in [2,3] and (w,h)==(128,80)
old_rows=[shlex.split(x) for x in (old/'job.txt').read_text().splitlines()]
assert [int(row[2]) for row in old_rows[1:8]]==[1,1,1,1,1,64,64]
expected_order=['round0_'+s for s in ['baseline','discard24','discard24_reset25','fresh_tail25']]+['round1_'+s for s in ['fresh_tail25','discard24_reset25','discard24','baseline']]
assert reg['mode_order']==expected_order
rows=[];api_total=0;queued_total=0;discard_total=0
for c in reg['cases']:
    folder=P/'evidence'/c['tag'];base=c['source_frame_start'];n=c['frames_recorded'];kind=c['kind']
    assert not (folder/'resource_guard.json').exists() and not (folder/'diffuse.bin').exists() and not (folder/'specular.bin').exists()
    tail=kind=='fresh_tail25';skip=24 if kind.startswith('discard') else -1
    reset=25 if kind=='discard24_reset25' else -1
    assert base==(25 if tail else 0) and n==(39 if tail else 64)
    assert c['skip_frame']==skip and c['recovery_reset_frame']==reset
    assert c['command']==[str(P/'fsrd_rr_discard.exe'),str(folder/'job.txt'),str(skip),str(reset),str(base)]
    records=[shlex.split(x) for x in (folder/'job.txt').read_text().splitlines()]
    assert list(map(int,records[0][:8]))==[128,80,n,2,32,0,1,0]
    assert Path(records[0][8])==Path(reg['dll']['path'])
    for i,row in enumerate(records[1:8]):
        p=Path(row[0]);fmt,uploads=map(int,row[1:]);bpp=8 if fmt==10 else 4
        old_bytes=Path(old_rows[i+1][0]).read_bytes();old_uploads=int(old_rows[i+1][2])
        assert fmt==int(old_rows[i+1][1])
        expected=old_bytes[25*128*80*bpp:] if tail and old_uploads==64 else old_bytes
        assert p.read_bytes()==expected
        assert uploads==(39 if tail and old_uploads==64 else old_uploads)
        assert p.stat().st_size==128*80*bpp*uploads
        assert identity(p)=={k:c['inputs'][i][k] for k in ['path','bytes','sha256']}
    controls=bytearray(old_control[25*184:] if tail else old_control)
    if tail:struct.pack_into('<I',controls,4,struct.unpack_from('<I',controls,4)[0]|1)
    if reset>=0:struct.pack_into('<I',controls,(reset-base)*184+4,struct.unpack_from('<I',controls,(reset-base)*184+4)[0]|1)
    assert bytes(controls)==(folder/'expected_applied_dispatch_controls.bin').read_bytes()
    lines=(old/'frame_controls.txt').read_text().splitlines()
    assert (folder/'frame_controls.txt').read_text().splitlines()==(lines[25:] if tail else lines)
    for filename in ['camera.txt']:
        assert (folder/filename).exists()==(old/filename).exists()
        if (old/filename).exists():assert (folder/filename).read_bytes()==(old/filename).read_bytes()
    source_indices=list(range(base,base+n));presence=bytes(f!=skip for f in source_indices)
    observed=[f for f in source_indices if f!=skip]
    assert c['source_frame_indices']==source_indices and c['observed_frame_indices']==observed
    assert c['frames_queued']==len(observed) and c['frames_discarded']==n-len(observed)
    assert (folder/'expected_output_presence.bin').read_bytes()==presence
    assert (folder/'expected_observed_frame_indices.bin').read_bytes()==struct.pack('<'+'I'*len(observed),*observed)
    assert c['expected_raw_lobe_bytes']==len(observed)*128*80*8
    rows.append({'tag':c['tag'],'API_recordings':n,'queued':len(observed),'discarded':n-len(observed),
                 'seven_payloads_and_formats_authenticated':True,'dedup_uploads':[int(r[2]) for r in records[1:8]],
                 'dispatch_frameIndices':source_indices,'observed_frameIndices':observed,
                 'expected_flags':[struct.unpack_from('<I',controls,j*184+4)[0] for j in range(n)],
                 'control_policy':'Original184byte controls, only first-tailRESET or reset25 bit where registered'})
    api_total+=n;queued_total+=len(observed);discard_total+=n-len(observed)
assert (len(rows),api_total,discard_total,queued_total)==(8,462,4,458)
assert reg['planned_native_contexts']==8 and reg['planned_successful_API_RR_recordings']==462 and reg['planned_queued_RR_dispatches']==458
assert reg['guard']['timeout_seconds']==240 and reg['guard']['maximum_working_set_bytes']==2**31 and reg['guard']['minimum_available_memory_bytes']==2**30
check(freeze['files']);check(freeze['external_sources'])
assert pre_pins==[identity(item['path']) for item in pre_pins]
assert not (P/'evidence/results.json').exists()
report={'schema':'independent-discarded-recording-pre-native-review-v1','utc':datetime.now(timezone.utc).isoformat(),
 'status':'prepared_source_review_ready_for_root_separate_authorization','native_has_not_run':True,
 'reviewer_GPU_native_build_calls':0,'quality_accepted':False,'actual_native_contexts':0,'actual_queued_RR_dispatches':0,
 'registration':identity(P/'registration.json'),'freeze':identity(P/'pre_native_freeze.json'),
 'all_frozen_owned_entries_verified':len(freeze['files']),'all_external_source_entries_verified':len(freeze['external_sources']),
 'old_native_manifest_authenticated':identity(old/'amd_context_identity.json'),
 'source_whitelist':identity(P/'source_insertion_whitelist.json'),'source_whitelist_reconstruction_exact':True,
 'case_count':8,'planned_API_recordings':462,'planned_discarded':4,'planned_queued_RR':458,'cases':rows,
 'findings':[
  'Frame24 successful API recording is closed and discarded before output copying, ExecuteCommandLists, Signal and Map. Prior23 normal submission completion is checked. Frame25 allocator/list reset reuses only completed or unsubmitted recording storage.',
  'Nine external Tex.state CPU shadows are restored to pre-record snapshots. Static input uploads remain one and are already on GPU; dynamic uploads consume24 but their copy is discarded, then25 reads the next payload. No one-frame input is incorrectly reinterpreted as39-frame history.',
  'Discarded frame24 has no raw native output; masks and observed source indices distinguish462 recorded from458 queued/readback frames. No zero-filled synthetic readback is represented as a measurement.',
  'Fresh-tail uses absolute SDK frameIndex25..63, exact static or raw-tail payloads, original tail controls and RESET on first25. Its expected applied controls equal reset25 corresponding tail; fresh context history is still different.',
  'Descriptive pair metrics retain submitted-ordinal and common-source-frame alignments separately, with184-byte control/flag matching, preventing a skipped-frame ordinal shift from masquerading as same-input comparison.'
 ],
 'qualifications':[
  'Local SDK headers do not establish discard-safe context rollback. Opaque provider CPU/history state deliberately remains advanced; SDK support and causation are not inferred from differing outputs.',
  'External state restoration does not restore provider-private resource bookkeeping. Internal transition/state failure, if observed, must be retained rather than interpreted as history quality evidence.',
  'RESET flag requests history reset but does not guarantee bit identity to a freshly created context. Prior context variability and balanced repeats remain descriptive controls.',
  'Original eight-case source/prototype/metric schedule remains frozen. FSRD converter/composition/camera CPU-policy effects and real game failure paths are outside this raw native SDK diagnostic.',
  'Source review is pre-native; root separately authorizes execution. Actual resource guards,184-byte consumed controls, presence, lobes and logs still require post-run verification.'
 ],'source_pins_pre_and_post':pre_pins,
 'official_reset_reference':'https://learn.microsoft.com/en-us/windows/win32/api/d3d12/nf-d3d12-id3d12commandallocator-reset'}
save('review.json',report)
save('completion_manifest.json',{'schema':'discarded-recording-pre-native-review-completion-v1','status':report['status'],
 'native_has_not_run':True,'files':[identity(p) for p in sorted(OUT.iterdir()) if p.is_file()]})
print(json.dumps({'review':identity(OUT/'review.json'),'completion_manifest':identity(OUT/'completion_manifest.json')}))
