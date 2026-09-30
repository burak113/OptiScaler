"""Freeze future CPU scorer without executing it or any known operator."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
HERE=Path(__file__).resolve().parent;OLD=HERE.parent/'harmonic_response_coefficient_history_feasibility_v2_20260930'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(n,v):
    with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
# Only the unchanged three operator helper definitions are extracted; no tests run.
helpers=(OLD/'selfchecks.py').read_text();prefix=helpers[:helpers.index('def run():')]
(HERE/'frozen_operator_helpers.py').write_text(prefix,encoding='utf-8',newline='\n')
operators=(OLD/'known_operators.py').read_text();oldimport='from selfchecks import descriptor,physical,source_records'
assert operators.count(oldimport)==1
operators=operators.replace(oldimport,'from frozen_operator_helpers import descriptor,physical,source_records')
(HERE/'known_operators.py').write_text(operators,encoding='utf-8',newline='\n')
script=(OLD/'analyze.py').read_text();ops=[]
def change(label,before,after,count=1):
    global script
    assert script.count(before)==count,label;script=script.replace(before,after);ops.append({'label':label,'before':before,'after':after,'occurrences':count})
change('scope','"""One frozen conditioner: saved matching responses plus known operator controls."""','"""Frozen reconstruction endpoint OLS: execute only after separate root law review."""')
change('exact_V2_comparator_loader','def sha(p):',"oldsp=importlib.util.spec_from_file_location('frozen_V2_delta_history',ROOT/'tools_tmp/harmonic_response_coefficient_history_feasibility_v2_20260930/model.py');old_v2=importlib.util.module_from_spec(oldsp);oldsp.loader.exec_module(old_v2)\n\ndef sha(p):")
change('known_V2_comparator_before_truth','    original=B+active[:,None,None,None]*(P-TP);epochs=',"    old_output,old_diag,old_pre=old_v2.make_response_history(raw,P,TP,B,active,ctrl,a['diag'],a['descriptors'],a.get('exposure'))\n    original=B+active[:,None,None,None]*(P-TP);epochs=")
change('known_V2_metric_variant',"('candidate',output)]", "('frozen_V2_delta_history',old_output),('candidate',output)]")
change('native_V2_comparator_before_truth','            original=B+active[:,None,None,None]*(P-TP);assert original.tobytes()',"            old_output,old_diag,old_pre=old_v2.make_response_history(raw,P,TP,B,active,ctrl,hook['source_diagnostics'],hook['descriptors'])\n            original=B+active[:,None,None,None]*(P-TP);assert original.tobytes()")
change('native_V2_metric_variant',"            variants['candidate']=metrics(output,truth,B,row['null_rms'],scene)","            variants['frozen_V2_delta_history']=metrics(old_output,truth,B,row['null_rms'],scene)\n            variants['candidate']=metrics(output,truth,B,row['null_rms'],scene)")
change('distinct_result_schema',"schema='physical-actual-response-coefficient-history-feasibility-v1'", "schema='current-reconstruction-endpoint-OLS16-feasibility-v1'")
change('additional_limit',"'D covariance is endogenous/unknown; source nominal SE is not D confidence or effective independent count.'", "'C/R0 covariance is endogenous/unknown; endpoint IID noise-gain algebra is not confidence. Exact constant/linear invariance only in transported coordinates; acceleration/static reconstruction moving source phase can fail.'")
(HERE/'analyze.py').write_text(script,encoding='utf-8',newline='\n')
save('analysis_implementation_whitelist.json',{'original_analyzer':{'path':str(OLD/'analyze.py'),'sha256':sha(OLD/'analyze.py')},'operations':ops,
 'unchanged_24_known_operator_generator_SHA':sha(OLD/'known_operators.py'),'operator_import_replacement_only':{'before':oldimport,'after':'from frozen_operator_helpers import descriptor,physical,source_records'},
 'helper_extraction':'Exact prefix before def run() from frozenV2selfchecks; definitions only, no model checks or knownoperators invoked.'})
selfcheck=json.loads((HERE/'selfcheck_results.json').read_text());assert selfcheck['status']=='passed' and selfcheck['model_sha256']==sha(HERE/'model.py')
assert not(HERE/'results.json').exists()
pins=json.loads((HERE/'inherited_input_pins.json').read_text());sources={**pins['frozen_V2_sources'],**pins['additional_V2_sources']}
for p,s in sources.items():assert sha(p)==s,p
sources.update({str(p):sha(p)for p in HERE.iterdir()if p.is_file()})
save('preparation_erratum.json',{'status':'before_preCPU_freeze','scope':'own selfcheck preparation only',
 'issue':'Current orthogonal carrier expected array had shape N,H,W,1 while output is RGB. numpy assert_allclose does not broadcast expected operands.',
 'repair':'Explicit broadcast expected addition to output RGB shape; same numeric tolerance3e-16, unchanged model/constants. First script preserved as selfchecks_preparation_broadcast_failure.py.txt.',
 'cohort_known_operator_scores_before_fix':0,'native_GPU_calls':0})
sources[str(HERE/'preparation_erratum.json')]=sha(HERE/'preparation_erratum.json')
save('pre_cpu_freeze.json',{'schema':'endpoint-reconstruction-preCPU-freeze-v1','UTC':datetime.now(timezone.utc).isoformat(),
 'status':'prepared_selfchecked_waiting_root_law_review_NO_SCORING_AUTHORIZED','sources':sources,
 'cohort_or_frozen24_known_operator_outputs_evaluated':False,'native_GPU_calls':0,'model_SHA':sha(HERE/'model.py'),
 'selfchecks_SHA':sha(HERE/'selfcheck_results.json'),'no_quality_scores_computed':True,'quality_accepted':False})
print(json.dumps({'model_SHA':sha(HERE/'model.py'),'freeze_SHA':sha(HERE/'pre_cpu_freeze.json'),'source_count':len(sources),'selfchecks':len(selfcheck['tests'])}))
