"""SIMULATED diagnostic-retention checks and source delta verification; CPU only."""
from pathlib import Path
import hashlib,json
from diagnostic_warning_policy_v2 import evaluate,KNOWN_WARNING
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def main():
    tests=[('noAPI_zero_empty',True,[63,63,0,0,0,0,0,1],b'',True),('noAPI_one_exact',True,[63,63,0,0,0,0,1,1],KNOWN_WARNING,True),
        ('record_zero_empty',False,[64,63,1,0,0,0,0,0],b'',True),('noAPI_two_reject',True,[63,63,0,0,0,0,2,1],KNOWN_WARNING*2,False),
        ('noAPI_other_warning_reject',True,[63,63,0,0,0,0,1,1],b'SDK: Other warning\r\n',False),('noAPI_extra_line_reject',True,[63,63,0,0,0,0,1,1],KNOWN_WARNING+b'extra\r\n',False),
        ('noAPI_count_zero_message_reject',True,[63,63,0,0,0,0,0,1],KNOWN_WARNING,False),('record_one_warning_reject',False,[64,63,1,0,0,0,1,0],KNOWN_WARNING,False),
        ('SDK_error_reject',True,[63,63,0,0,0,1,0,1],b'',False),('D3D_warning_reject',True,[63,63,0,0,1,0,0,1],b'',False),('D3D_error_reject',True,[63,63,0,1,0,0,0,1],b'',False)]
    outcomes=[]
    for name,no_api,counts,stderr,expected in tests:
        try:result=evaluate({'no_api_frame':24 if no_api else-1},counts,stderr);admissible=True;error=None
        except AssertionError as e:result=None;admissible=False;error=str(e)
        assert admissible==expected,name
        if result is not None:assert result['quality_accepted']is False and not result['warning_count_is_quality_score']and result['actual_SDK_warning_count']==counts[6]
        outcomes.append({'SIMULATED_case':name,'counts':counts,'stderr_hex':stderr.hex(),'expected_admissible':expected,'actual_admissible':admissible,'result':result,'rejection':error})
    whitelist=json.loads((HERE/'remaining_v2_driver_whitelist.json').read_text());text=Path(whitelist['frozen_V1_driver']['path']).read_text()
    for op in whitelist['operations']:assert text.count(op['before'])==op['occurrences'];text=text.replace(op['before'],op['after'])
    assert text.encode()==(HERE/'run_remaining_native_v2.py').read_bytes()
    for name in('run_remaining_native_v2.py','prepare_remaining_v2.py','analyze_combined_v2.py','diagnostic_warning_policy_v2.py'):compile((HERE/name).read_text(),str(HERE/name),'exec')
    save(HERE/'remaining_v2_CPU_check.json',{'schema':'SIMULATED-post-observation-remaining6-diagnostic-retention-CPU-check-v2','status':'passed','SIMULATED_NOT_NATIVE_EVIDENCE':True,
        'tests':len(tests),'outcomes':outcomes,'driver_whitelist_exact':True,'future_scripts_parse_without_entrypoint_execution':True,
        'new_native_contexts':0,'new_API_RR_recordings':0,'new_queued_RR_dispatches':0,'script_sha256':sha(Path(__file__)),
        'policy_sha256':sha(HERE/'diagnostic_warning_policy_v2.py'),'driver_sha256':sha(HERE/'run_remaining_native_v2.py')})
    print('11 SIMULATED V2 diagnostic retention checks passed; source whitelist exact; no native execution.')
if __name__=='__main__':main()
