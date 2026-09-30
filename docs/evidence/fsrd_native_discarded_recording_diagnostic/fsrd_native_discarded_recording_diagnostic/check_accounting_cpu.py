"""Four explicitly simulated CPU accounting cases. No executable/GPU/native work."""
from pathlib import Path
import hashlib,json,struct
from native_work_accounting import derive
HERE=Path(__file__).resolve().parent;DEST=HERE/'SIMULATED_accounting_unit_inputs';DEST.mkdir(exist_ok=False)
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def write_indices(p,values):p.write_bytes(struct.pack('<'+str(len(values))+'I',*values))
def run(name,stdout,recorded=None,observed=None,presence=None):
    folder=DEST/name;folder.mkdir();(folder/'stdout.log').write_text(stdout);(folder/'stderr.log').write_text('SIMULATED CPU-only accounting test; no native process.\n')
    if recorded is not None:write_indices(folder/'recorded_frame_indices.bin',recorded)
    if observed is not None:write_indices(folder/'observed_frame_indices.bin',observed)
    if presence is not None:(folder/'output_presence.bin').write_bytes(bytes(presence))
    value=derive(folder,{'child_pid':123,'status':'SIMULATED','returncode':2},{'tag':'SIMULATED_'+name})
    save(folder/'SIMULATED_accounting_result.json',value);return value
footer='provider=SIMULATED\nRR_recordings=64 queued_RR_dispatches=64 discarded_RR_recordings=0 validation_errors=1 validation_warnings=1 sdk_errors=0 sdk_warnings=0\n'
a=run('complete_footer_metadata_failure',footer,list(range(64)),list(range(64)),[1]*64)
assert a['successful_API_RR_recordings_confirmed']==64 and a['queued_RR_dispatches_confirmed_completed']==64
assert a['completed_native_context_final_marker']and not a['metadata_acceptance_evaluated']
assert a['final_stdout_counters']['validation_errors']==1 and a['evidence_disagreements']
b=run('partial_flushed_prefix','provider=SIMULATED\n',list(range(4)),[0,1],[1,1])
assert b['successful_API_RR_recordings_confirmed']==4 and b['queued_RR_dispatches_confirmed_completed']==2
assert not b['completed_native_context_final_marker']and b['incomplete_child_native_work_may_exceed_confirmed_lower_bounds']
c=run('provider_only','provider=SIMULATED\n')
assert c['created_native_context_confirmed']and not c['completed_native_context_final_marker']
assert c['successful_API_RR_recordings_confirmed']==0 and c['incomplete_child_native_work_may_exceed_confirmed_lower_bounds']
d=run('contradictory_footer_artifacts',footer,list(range(40)),list(range(42)),[1]*42)
assert d['successful_API_RR_recordings_confirmed']==64 and d['recording_evidence_counts']['successful_recorded_u32_indices']==40
assert d['evidence_disagreements']and d['queue_evidence_counts']['observed_u32_indices']==42
assert a['planned_counts_are_measurements']is False and d['planned_counts_are_measurements']is False
compile((HERE/'run_native_v2.py').read_text(),str(HERE/'run_native_v2.py'),'exec')
save(HERE/'accounting_cpu_check.json',{'schema':'explicitly-simulated-accounting-CPU-check-v1','status':'passed','SIMULATED_NOT_NATIVE_EVIDENCE':True,
    'cases':4,'actual_native_contexts':0,'actual_API_RR_recordings':0,'actual_queued_RR_dispatches':0,
    'checks':['Final footer/native64 preserved despite debug error and absent raw metadata acceptance',
              'Partial source/observed markers remain confirmed lower bounds with unknown extra work',
              'Provider-only creates confirmed context marker while zero lower bounds never prove no work',
              'Footer/artifact conflicts retain both evidence sets; planned64 never fills counts',
              'V2 executor parses without execution'],
    'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'accounting_module_sha256':hashlib.sha256((HERE/'native_work_accounting.py').read_bytes()).hexdigest()})
print('Four SIMULATED CPU accounting checks passed; zero native/GPU work.')
