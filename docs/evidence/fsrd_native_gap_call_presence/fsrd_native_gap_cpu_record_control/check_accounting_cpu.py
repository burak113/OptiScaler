"""Explicit SIMULATED CPU stage checks. No raw output or native job fabricated."""
from pathlib import Path
import hashlib,json,struct
from native_work_accounting import derive
HERE=Path(__file__).resolve().parent;DEST=HERE/'SIMULATED_accounting_unit_inputs';DEST.mkdir(exist_ok=False)
REG=json.loads((HERE/'registration.json').read_text());NOAPI=next(c for c in REG['cases']if c['tag']=='round0_no_api24');RECORD=next(c for c in REG['cases']if c['tag']=='round0_record_discard24')
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def footer(api,queued,discard,omitted,errors=0):return f'provider=SIMULATED\nRR_recordings={api} queued_RR_dispatches={queued} discarded_RR_recordings={discard} validation_errors={errors} validation_warnings=0 sdk_errors=0 sdk_warnings=0 no_API_omissions={omitted}\n'
def run(name,case,stdout,recorded=None,observed=None,presence=None,omitted=None):
    folder=DEST/name;folder.mkdir();(folder/'stdout.log').write_text(stdout,encoding='utf-8',newline='\n');(folder/'stderr.log').write_text('SIMULATED CPU-only metadata; no native process.\n',encoding='utf-8',newline='\n')
    for filename,values in(('recorded_frame_indices.bin',recorded),('observed_frame_indices.bin',observed),('omitted_API_frame_indices.bin',omitted)):
        if values is not None:(folder/filename).write_bytes(struct.pack('<'+str(len(values))+'I',*values))
    if presence is not None:(folder/'output_presence.bin').write_bytes(bytes(presence))
    v=derive(folder,{'child_pid':123,'status':'SIMULATED_NOT_NATIVE','returncode':2},{**case,'tag':'SIMULATED_'+name})
    save(folder/'SIMULATED_accounting_result.json',v);return v
results={}
results['noAPI_footer_validation_metadata_reject']=a=run('noAPI_footer_validation_metadata_reject',NOAPI,footer(63,63,0,1,errors=1),NOAPI['source_frame_indices'],NOAPI['observed_frame_indices'],NOAPI['output_presence_mask'],[24])
assert[a[k]for k in('successful_API_RR_recordings_confirmed','queued_RR_dispatches_confirmed_completed','discarded_API_RR_recordings_confirmed','no_API_omissions_confirmed')]==[63,63,0,1]
assert not a['totals_unknown']and a['completed_native_context_final_marker']and a['final_stdout_counters']['validation_errors']==1
assert a['observed_output_frames_confirmed']==0 and not a['metadata_acceptance_evaluated']and a['evidence_disagreements']
results['record_discard_footer']=b=run('record_discard_footer',RECORD,footer(64,63,1,0),RECORD['source_frame_indices'],RECORD['observed_frame_indices'],RECORD['output_presence_mask'],[])
assert[b[k]for k in('successful_API_RR_recordings_confirmed','queued_RR_dispatches_confirmed_completed','discarded_API_RR_recordings_confirmed','no_API_omissions_confirmed')]==[64,63,1,0]
assert not b['totals_unknown']and b['semantically_valid_artifact_lower_bounds']['discarded_RR_recordings']==1
results['noAPI_footer63_conflicting64_API_indices']=c=run('noAPI_footer63_conflicting64_API_indices',NOAPI,footer(63,63,0,1),list(range(64)),NOAPI['observed_frame_indices'],NOAPI['output_presence_mask'],[24])
assert c['successful_API_RR_recordings_confirmed']==63 and c['recording_evidence_counts']['successful_recorded_u32_indices']==64
assert not c['artifact_validity']['successful_recorded_indices']and c['discarded_API_RR_recordings_confirmed']==0 and c['no_API_omissions_confirmed']==1
assert c['counter_authority']=='valid_bounded_final_CPP_footer_under_pinned_source'and c['evidence_disagreements']
prefix=list(range(24))+[25];presence=[1]*24+[0,1]
results['no_footer_noAPI_partial_after25']=d=run('no_footer_noAPI_partial_after25',NOAPI,'provider=SIMULATED\n',prefix,prefix,presence,[24])
assert[d[k]for k in('successful_API_RR_recordings_confirmed','queued_RR_dispatches_confirmed_completed','discarded_API_RR_recordings_confirmed','no_API_omissions_confirmed')]==[25,25,0,1]
assert d['totals_unknown']and not d['completed_native_context_final_marker']and d['incomplete_child_native_work_may_exceed_confirmed_lower_bounds']
results['no_footer_record_discard_partial_after25']=e=run('no_footer_record_discard_partial_after25',RECORD,'provider=SIMULATED\n',list(range(26)),prefix,presence,[])
assert[e[k]for k in('successful_API_RR_recordings_confirmed','queued_RR_dispatches_confirmed_completed','discarded_API_RR_recordings_confirmed','no_API_omissions_confirmed')]==[26,25,1,0]
assert e['totals_unknown']and e['semantically_valid_artifact_lower_bounds']['discarded_RR_recordings']==1
results['invalid_overcapacity_footer_valid_prefix']=f=run('invalid_overcapacity_footer_valid_prefix',NOAPI,footer(64,64,0,0),[0,1,2,3],[0,1],[1,1],[])
assert not f['final_CPP_footer_valid']and f['totals_unknown']and f['successful_API_RR_recordings_confirmed']==4 and f['queued_RR_dispatches_confirmed_completed']==2
assert f['discarded_API_RR_recordings_confirmed']==0 and f['no_API_omissions_confirmed']==0 and f['final_stdout_counters']['successful_API_RR_recordings']==64
results['provider_only_unknown']=g=run('provider_only_unknown',NOAPI,'provider=SIMULATED\n')
assert g['created_native_context_confirmed']and g['totals_unknown']and g['successful_API_RR_recordings_confirmed']==0 and g['incomplete_child_native_work_may_exceed_confirmed_lower_bounds']
results['omission_footer1_conflicting2_indices']=h=run('omission_footer1_conflicting2_indices',NOAPI,footer(63,63,0,1),NOAPI['source_frame_indices'],NOAPI['observed_frame_indices'],NOAPI['output_presence_mask'],[24,24])
assert h['no_API_omissions_confirmed']==1 and h['omitted_API_frame_indices']['whole_u32_records']==2 and not h['artifact_validity']['omitted_API_indices']
assert 'omitted_API_indices_not_registered_prefix'in h['evidence_disagreements']and h['omission_counter_authority']=='valid_bounded_final_CPP_footer_under_pinned_source'
for v in results.values():assert not v['planned_counts_are_measurements']and not v['metadata_acceptance_evaluated']
for p in DEST.rglob('*'):assert p.name not in('diffuse.bin','specular.bin','resource_guard.json')
save(HERE/'accounting_cpu_check.json',{'schema':'explicitly-SIMULATED-matched-gap-stage-accounting-CPU-check-v1','status':'passed','SIMULATED_NOT_NATIVE_EVIDENCE':True,
    'cases':len(results),'actual_native_contexts':0,'actual_API_RR_recordings':0,'actual_queued_RR_dispatches':0,'actual_no_API_omissions':0,
    'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'wrapper_sha256':hashlib.sha256((HERE/'native_work_accounting.py').read_bytes()).hexdigest(),
    'results':{k:{'API':v['successful_API_RR_recordings_confirmed'],'queued':v['queued_RR_dispatches_confirmed_completed'],'SDKdiscard':v['discarded_API_RR_recordings_confirmed'],
        'noAPIomit':v['no_API_omissions_confirmed'],'totals_unknown':v['totals_unknown'],'authority':v['counter_authority']}for k,v in results.items()},
    'qualification':'All fixture stdout/index/presence bytes explicitly simulated and outside nativecase evidence. Missing raw lobes intentionally reject metadata and never fabricate an observed zero. These are checks of accounting only; not native measurements.'})
print('Eight SIMULATED CPU stage accounting checks passed; zero native/GPU work.')
