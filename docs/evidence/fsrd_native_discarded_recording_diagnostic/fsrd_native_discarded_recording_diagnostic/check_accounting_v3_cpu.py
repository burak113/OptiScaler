"""Explicitly SIMULATED accounting checks. Never launch a native/GPU process."""
from pathlib import Path
import hashlib,json,struct
from native_work_accounting_v3 import derive
HERE=Path(__file__).resolve().parent
DEST=HERE/'SIMULATED_accounting_v3_unit_inputs'
DEST.mkdir(exist_ok=False)
REG=json.loads((HERE/'registration.json').read_text())
BASE=next(c for c in REG['cases'] if c['tag']=='round0_baseline')
DROP=next(c for c in REG['cases'] if c['tag']=='round0_discard24')
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def write_indices(p,values):p.write_bytes(struct.pack('<'+str(len(values))+'I',*values))
def footer(recorded=64,queued=64,discarded=0,errors=0,warnings=0):
    return f'provider=SIMULATED\nRR_recordings={recorded} queued_RR_dispatches={queued} discarded_RR_recordings={discarded} validation_errors={errors} validation_warnings={warnings} sdk_errors=0 sdk_warnings=0\n'
def run(name,stdout,recorded=None,observed=None,presence=None,case=BASE):
    folder=DEST/name;folder.mkdir()
    (folder/'stdout.log').write_text(stdout,encoding='utf-8',newline='\n')
    (folder/'stderr.log').write_text('SIMULATED CPU-only accounting fixture; no native process.\n',encoding='utf-8',newline='\n')
    if recorded is not None:write_indices(folder/'recorded_frame_indices.bin',recorded)
    if observed is not None:write_indices(folder/'observed_frame_indices.bin',observed)
    if presence is not None:(folder/'output_presence.bin').write_bytes(bytes(presence))
    params={**case,'tag':'SIMULATED_'+name}
    value=derive(folder,{'child_pid':123,'status':'SIMULATED_NOT_NATIVE','returncode':2},params)
    save(folder/'SIMULATED_accounting_result.json',value)
    return value
results={}
results['complete_footer_validation_and_metadata_rejection']=a=run('complete_footer_validation_and_metadata_rejection',footer(errors=1,warnings=1),list(range(64)),list(range(64)),[1]*64)
assert a['successful_API_RR_recordings_confirmed']==64 and a['queued_RR_dispatches_confirmed_completed']==64
assert a['final_CPP_footer_valid']and a['completed_native_context_final_marker']and not a['totals_unknown']
assert a['final_stdout_counters']['validation_errors']==1 and a['final_stdout_counters']['validation_warnings']==1
assert not a['metadata_acceptance_evaluated']and a['observed_output_frames_confirmed']==0
assert a['raw_lobes']['diffuse.bin']['present']is False and a['evidence_disagreements']
results['footer64_conflicting65_indices']=b=run('footer64_conflicting65_indices',footer(),list(range(65)),list(range(64)),[1]*64)
assert b['successful_API_RR_recordings_confirmed']==64 and b['queued_RR_dispatches_confirmed_completed']==64
assert b['recording_evidence_counts']['successful_recorded_u32_indices']==65
assert not b['artifact_validity']['successful_recorded_indices']
assert b['semantically_valid_artifact_lower_bounds']['successful_API_RR_recordings']==0
assert b['counter_authority']=='valid_bounded_final_CPP_footer_under_pinned_source'
assert b['unified_count_status']=='authoritative_footer_with_metadata_conflicts'
assert 'recorded_indices_not_registered_prefix'in b['evidence_disagreements']
assert 'successful_record_indices_vs_final_stdout'in b['evidence_disagreements']
results['no_footer_partial_prefix']=c=run('no_footer_partial_prefix','provider=SIMULATED\n',list(range(4)),[0,1],[1,1])
assert c['successful_API_RR_recordings_confirmed']==4 and c['queued_RR_dispatches_confirmed_completed']==2
assert not c['final_CPP_footer_valid']and c['totals_unknown']and c['incomplete_child_native_work_may_exceed_confirmed_lower_bounds']
assert c['counter_authority']=='semantically_valid_artifact_lower_bounds_totals_unknown'
assert c['observed_output_frames_confirmed']==0 and not c['completed_native_context_final_marker']
results['no_footer_provider_only']=d=run('no_footer_provider_only','provider=SIMULATED\n')
assert d['created_native_context_confirmed']and d['totals_unknown']and not d['completed_native_context_final_marker']
assert d['successful_API_RR_recordings_confirmed']==0 and d['queued_RR_dispatches_confirmed_completed']==0
assert d['incomplete_child_native_work_may_exceed_confirmed_lower_bounds']
results['invalid65_footer_valid_partial_artifacts']=e=run('invalid65_footer_valid_partial_artifacts',footer(65,65),[0,1,2],[0,1],[1,1])
assert not e['final_CPP_footer_valid']and e['totals_unknown']
assert e['final_stdout_counters']['successful_API_RR_recordings']==65
assert e['successful_API_RR_recordings_confirmed']==3 and e['queued_RR_dispatches_confirmed_completed']==2
assert 'final_CPP_footer_out_of_bounds_or_recording_partition_invalid'in e['evidence_disagreements']
results['discard24_footer64_63_1']=f=run('discard24_footer64_63_1',footer(64,63,1),list(range(64)),DROP['observed_frame_indices'],DROP['output_presence_mask'],case=DROP)
assert f['final_CPP_footer_valid']and f['successful_API_RR_recordings_confirmed']==64
assert f['queued_RR_dispatches_confirmed_completed']==63 and f['discarded_API_RR_recordings_confirmed']==1
assert f['presence']['zeros']==1 and f['observed_indices']['values']==[i for i in range(64)if i!=24]
assert f['artifact_validity']['successful_recorded_indices']and f['artifact_validity']['observed_indices']and f['artifact_validity']['presence']
for v in results.values():assert not v['planned_counts_are_measurements']and not v['metadata_acceptance_evaluated']
for p in DEST.rglob('*'):assert p.name not in('diffuse.bin','specular.bin','resource_guard.json')
for name in('run_native_v3.py','native_work_accounting_v3.py'):compile((HERE/name).read_text(),str(HERE/name),'exec')
save(HERE/'accounting_v3_cpu_check.json',{'schema':'explicitly-simulated-accounting-CPU-check-v3','status':'passed','SIMULATED_NOT_NATIVE_EVIDENCE':True,
    'cases':len(results),'actual_native_contexts':0,'actual_API_RR_recordings':0,'actual_queued_RR_dispatches':0,
    'checks':['Authoritative footer64 retained despite validation errors and absent raw readback acceptance',
              '65-index artifact conflicts retained and rejected while valid footer64 remains exact64',
              'No-footer prefix gives API4/queued2 lower bounds and unknown totals',
              'Provider-only gives created-context marker but zero work lower bounds and unknown totals',
              'Out-of-capacity footer65 rejected; valid prefix API3/queued2 remains only lower bounds',
              'Discard24 shape retains exact valid footer64/63/1, source24 absent mask and63 observed markers',
              'No raw lobe, guard, GPU, native process, or actual native evidence fabricated',
              'V3 executor/module parse without executing their entry points'],
    'simulated_results':{k:{'successful_API_RR_recordings_confirmed':v['successful_API_RR_recordings_confirmed'],
        'queued_RR_dispatches_confirmed_completed':v['queued_RR_dispatches_confirmed_completed'],
        'discarded_API_RR_recordings_confirmed':v['discarded_API_RR_recordings_confirmed'],
        'counter_authority':v['counter_authority'],'totals_unknown':v['totals_unknown']}for k,v in results.items()},
    'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'accounting_module_sha256':hashlib.sha256((HERE/'native_work_accounting_v3.py').read_bytes()).hexdigest(),
    'registration_sha256':hashlib.sha256((HERE/'registration.json').read_bytes()).hexdigest()})
print('Six SIMULATED V3 CPU accounting checks passed; zero native/GPU work.')
