"""Post-observation amendment: prepare six never-attempted original cases only."""
from pathlib import Path
from datetime import datetime,timezone
import difflib,hashlib,json
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def verify(records):
    for r in records:
        p=Path(r['path']);assert p.stat().st_size==r['bytes']and sha(p)==r['sha256'],str(p)
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def main():
    assert not(HERE/'remaining_v2_registration.json').exists(),'Preserve amendment'
    original=json.loads((HERE/'registration.json').read_text());prep=json.loads((HERE/'preparation_completion_manifest.json').read_text());verify(prep['files']);verify(prep['external_sources'])
    partial=json.loads((HERE/'partial_v1_completion_manifest.json').read_text());verify(partial['files'])
    results=json.loads((HERE/'evidence/results.json').read_text());assert results['status']=='failed_preserved'and list(results['cases'])==original['mode_order'][:2]
    remaining=original['cases'][2:];assert len(remaining)==6
    for c in remaining:
        f=HERE/'evidence'/c['tag']
        for name in('resource_guard.json','stdout.log','stderr.log','diffuse.bin','specular.bin','dispatch_controls.bin','queued_dispatch_controls.bin','native_work_accounting.json','recorded_frame_indices.bin','observed_frame_indices.bin','omitted_API_frame_indices.bin','output_presence.bin'):
            assert not(f/name).exists(),'Already attempted remainingcase '+str(f/name)
    text=(HERE/'run_native.py').read_text();changes=[]
    def replace(before,after,label,count=1):
        nonlocal text
        assert text.count(before)==count,label;text=text.replace(before,after);changes.append({'label':label,'before':before,'after':after,'occurrences':count})
    replace('"""Future guarded sequential executor. Preparation never passes --execute-native."""','"""Post-observation V2: only six unattempted cases; new root authorization required."""','V2_scope')
    replace('from native_work_accounting import derive','from native_work_accounting import derive\nfrom diagnostic_warning_policy_v2 import evaluate as evaluate_diagnostics','exact_warning_policy')
    replace("if sys.argv[1:]!=['--execute-native']:raise RuntimeError('Preparation only: root authorization after independent prelaunch review is required before --execute-native.')",
        "if sys.argv[1:]!=['--execute-remaining-native']:raise RuntimeError('Post-observation preparation only: new root authorization after V2 review is required for only six unattempted cases.')",'new_explicit_gate')
    replace("    reg=json.loads((HERE/'registration.json').read_text());freeze=json.loads((HERE/'pre_native_freeze.json').read_text())",
'''    original_reg=json.loads((HERE/'registration.json').read_text());freeze=json.loads((HERE/'pre_native_freeze.json').read_text())
    amendment=json.loads((HERE/'remaining_v2_registration.json').read_text())
    assert amendment['status']=='prepared_post_observation_NOT_AUTHORIZED_TO_RUN'
    assert amendment['remaining_case_tags']==original_reg['mode_order'][2:]
    reg={**original_reg,'cases':[c for c in original_reg['cases']if c['tag']in amendment['remaining_case_tags']]}
    assert len(reg['cases'])==6 and[c['tag']for c in reg['cases']]==amendment['remaining_case_tags']
    supplement=json.loads((HERE/'remaining_v2_pre_native_freeze.json').read_text())
    partial=json.loads((HERE/'partial_v1_completion_manifest.json').read_text())''','original_commands_remaining_subset')
    replace("check(freeze['files']);check(freeze['external_sources'])","check(freeze['files']);check(freeze['external_sources']);check(supplement['files']);check(partial['files'])",'all_original_and_V2_pins_preserved',3)
    replace("target=HERE/'evidence/results.json'","target=HERE/'evidence/remaining_v2_results.json'",'unique_results_target')
    replace("'schema':'matched-gap-CPU-record-actual-native-stage-evidence-v1'","'schema':'matched-gap-six-remaining-post-observation-native-stage-evidence-v2'",'distinct_actual_evidence_schema')
    replace("'prior_H2_reference_contexts':8,'prior_H2_reference_contexts_count_as_new':False,",
        "'prior_H2_reference_contexts':8,'prior_H2_reference_contexts_count_as_new':False,\n        'previous_V1_completed_contexts_reference_only':2,'previous_V1_results_sha256':sha(HERE/'evidence/results.json'),\n        'post_observation_amendment_sha256':sha(HERE/'remaining_v2_registration.json'),'only6remaining_contexts_counted_here':True,",'prior2_not_new_counts')
    replace("            assert counts[3:7]==[0,0,0,0],'ordinary D3D12/SDK diagnostics';assert'debug_layer=1'in log",
        "            info['diagnostic_warning_admissibility']=evaluate_diagnostics(c,counts,(folder/'stderr.log').read_bytes())\n            checkpoint();assert'debug_layer=1'in log",'bounded_diagnostic_retention_only')
    replace("            assert(folder/'stderr.log').stat().st_size==0\n","",'retain_actual_known_warning_bytes')
    replace("==[8,508,504,4,4,8]","==[6,381,378,3,3,6]",'remaining6_expected_counts')
    replace("completed_matched_gap_CPU_record_diagnostic_not_solution","completed_matched_gap_CPU_record_remaining_V2_diagnostic_not_solution",'remaining_only_completion_status')
    with(HERE/'run_remaining_native_v2.py').open('x',encoding='utf-8',newline='\n')as f:f.write(text)
    compile(text,str(HERE/'run_remaining_native_v2.py'),'exec')
    save(HERE/'remaining_v2_driver_whitelist.json',{'frozen_V1_driver':identity(HERE/'run_native.py'),'new_V2_driver':identity(HERE/'run_remaining_native_v2.py'),'operations':changes})
    with(HERE/'remaining_v2_driver.diff').open('x',encoding='utf-8',newline='\n')as f:f.write(''.join(difflib.unified_diff((HERE/'run_native.py').read_text().splitlines(keepends=True),text.splitlines(keepends=True),fromfile='frozen_V1_driver',tofile='remaining6_post_observation_V2')))
    assert[sum(c[k]for c in remaining)for k in('frames_recorded','frames_queued','frames_discarded','frames_omitted_API')]==[381,378,3,3]
    registration={'schema':'matched-gap-six-remaining-post-observation-diagnostic-retention-amendment-v2','UTC':datetime.now(timezone.utc).isoformat(),
        'status':'prepared_post_observation_NOT_AUTHORIZED_TO_RUN','post_observation':True,
        'chronology':'V1 completed two fresh contexts before metadata rejection of noAPI24 due one SDK frame-index gap reset warning. This amendment was made after observing that warning/output; it does not alter original acceptance or reinterpret it as preregistered. Root approved preparation of six unattempted original cases and bounded diagnostic retention, not their execution.',
        'original_registration':identity(HERE/'registration.json'),'original_pre_native_freeze':identity(HERE/'pre_native_freeze.json'),'original_results_failed_preserved':identity(HERE/'evidence/results.json'),
        'original_execution_console':identity(HERE/'execution_console.log'),'original_first2_inspection':identity(HERE/'partial_v1_inspection.json'),'original_first2_completion_manifest':identity(HERE/'partial_v1_completion_manifest.json'),
        'original_V1_actual_counts':{'contexts':2,'successful_API_RR_recordings':127,'queued_RR_dispatches':126,'SDK_record_discards':1,'no_API_omissions':1,'metadata_accepted_contexts':1,'SDK_warnings':1},
        'remaining_case_tags':[c['tag']for c in remaining],'commands':[c['command']for c in remaining],
        'planned_new_native_contexts':6,'planned_new_API_RR_recordings':381,'planned_new_queued_RR_dispatches':378,'planned_new_SDK_record_discards':3,'planned_new_no_API_omissions':3,
        'actual_new_native_contexts':0,'actual_new_API_RR_recordings':0,'actual_new_queued_RR_dispatches':0,
        'new_executor':identity(HERE/'run_remaining_native_v2.py'),'exact_warning_policy':identity(HERE/'diagnostic_warning_policy_v2.py'),
        'diagnostic_admissibility':'Record-discard requires zero SDK warnings. noAPI allows0or1 only exactstderr ASCII bytes SDK: Frame index jump detected. Resetting... followed by CRLF if1; otherwise empty. All D3D12 errors/warnings and SDK errors zero. Any other message/count rejected after actual work accounting. Actual warning counts/bytes retained; never a quality score/pass.',
        'unchanged':['C++','EXE','DLL/headers','all7inputs percase','original case commands/controls/sourceframes','guard','V3 stage accounting'],
        'analysis_plan':'After new6 actual completion, write new merged CPU report/all28pairs2alignments2lobes from actual old2 plusactualnew6, preserving original acceptedfalse on noAPI first2. Count old2 andnew6 separately; onlythen combined8 ifactuallycompleted. OldH2eight remain references only.',
        'causal_qualification':'API presence can change SDK frame-gap reset behavior. Equal queued184controls/inputs do not prove equal opaque effective history. Warning reset is an observed mediator; no universal autoRESET/quality/gamecause claim.',
        'guard_policy':'Unchanged240sec/2GiB/free1GiB/0.2 guard; sequential onlyowned child; no otherprocess kills.',
        'quality_accepted':False,'production_changes':False,'game_run':False,
        'requires_before_any_native':'SolHigh boundedV2 review and new root authorization for exactlysix unattempted cases. No automatic GPU retry.'}
    save(HERE/'remaining_v2_registration.json',registration)
    files=sorted(p for p in HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts)
    save(HERE/'remaining_v2_pre_native_freeze.json',{'schema':'post-observation-remaining6-V2-before-new-native-freeze-v1','UTC':datetime.now(timezone.utc).isoformat(),'files':[identity(p)for p in files],
        'actual_new_native_contexts':0,'actual_new_API_RR_recordings':0,'original_V1_completed_contexts_reference_only':2})
    print(json.dumps({'registration':identity(HERE/'remaining_v2_registration.json'),'freeze':identity(HERE/'remaining_v2_pre_native_freeze.json'),'new_driver':identity(HERE/'run_remaining_native_v2.py'),'actual_new_native_contexts':0}),flush=True)
if __name__=='__main__':main()
