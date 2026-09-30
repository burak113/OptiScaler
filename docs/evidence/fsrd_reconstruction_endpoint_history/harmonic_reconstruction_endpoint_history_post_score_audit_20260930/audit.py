"""Independent saved-array score audit; no estimator/analyzer/model execution."""
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from collections import Counter
import ast,hashlib,json,os,sys,time
sys.dont_write_bytecode=True
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];TOOLS=ROOT/'tools_tmp'
END=TOOLS/'harmonic_reconstruction_endpoint_history_feasibility_20260930'
OLD=TOOLS/'harmonic_response_coefficient_history_feasibility_v2_20260930'
DC=TOOLS/'harmonic_response_dc_innovation_feasibility_20260930'
TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests'
EXPECTED_RESULT='225848939eb620a3b712ead68dffdef4e23fd952b2865e9e98445df9b9ede93e'
EXPECTED_MANIFEST='058aac716bf0ba5e0f7f6504054364e3cb2a24dcb8d4e63e8705405518c0000a'
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb')as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def ident(p):p=Path(p);return dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p))
def digest(a):return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(name,v):
    with(HERE/name).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def verify_identity(x):
    actual=ident(x['path']);assert all(actual[k]==x[k]for k in('bytes','sha256')),x['path']
def check_equal(a,b,label):
    assert a==b,label
def compact(m):
    ratio=m['actual_STD_ratio_to_control'];gain=not m['absolute_gain_failing_frames'];phase=not m['absolute_phase_failing_frames']
    return dict(relative_effective=m['relative_gate']['effective_success'],relative_failures=m['relative_gate']['failures'],
        STD=m['score']['residual_temporal_std'],STD_ratio_to_B=ratio,strict_STD_le1=None if ratio is None else ratio<=1,
        absolute_GAIN=gain,absolute_PHASE=phase,absolute_GAIN_AND_PHASE=gain and phase,
        gain_min=m['absolute_gain_min'],gain_max=m['absolute_gain_max'],phase_max=m['absolute_phase_max'],
        gain_failing_frames=m['absolute_gain_failing_frames'],phase_failing_frames=m['absolute_phase_failing_frames'],
        rmse=m['score']['rmse'],broad_tone_rms=m['score']['broad_tone_rms'],bias_rgb=m['score']['bias_rgb'],invalid_pixel_fraction=m['invalid_pixel_fraction'])
def main():
    started=time.monotonic();assert not(HERE/'audit.json').exists()
    assert sha(END/'results.json')==EXPECTED_RESULT and sha(END/'completion_manifest.json')==EXPECTED_MANIFEST
    result=read(END/'results.json');manifest=read(END/'completion_manifest.json');freeze=read(END/'pre_cpu_freeze.json')
    assert len(freeze['sources'])==61
    source_before=[ident(p)for p in freeze['sources']]
    for p,s in freeze['sources'].items():assert sha(p)==s,p
    for x in manifest['files']+manifest['external_authorization_and_review']:verify_identity(x)
    assert all(Path(x['path'])!=END/'completion_manifest.json'for x in manifest['files']) and manifest['self_entry_excluded']
    corrected=read(END/'preparation_completion_manifest_corrected.json')
    for x in corrected['files']+corrected['external_source_files']:verify_identity(x)
    assert sha(END/'preparation_completion_manifest_corrected.json')=='6979acdd171d29b7fa60c766b33a1ad44a3285c3e786c28e26c4d3fa1d71f52e'
    assert sha(TOOLS/'endpoint_root_cpu_authorization_20260930.json')=='45dda69927abfad7e5875f13104a4792575fea476bbfb29fc5e275bb3da9c2f3'
    assert sha(TOOLS/'harmonic_reconstruction_endpoint_history_law_review_20260930/review.json')=='0b6b29d5ff0c21288e08f81f84e88d05d7c0cf6a2c0eb75a71a61afb38401c32'
    assert (END/'pre_cpu_freeze.json').read_bytes()==(END/'pre_score_freeze.json').read_bytes()
    save('preregistration.json',dict(schema='independent-endpoint-post-score-saved-array-audit-v1',UTC=datetime.now(timezone.utc).isoformat(),
        chronology='Post-score forensic audit. Producer outcomes were already reported; this is not a blind new feasibility experiment.',
        scope='Recompute full and mature16 quality metrics from six already-saved candidate, frozenDC, V2 and six original comparator arrays against already-saved truth. Authenticate24 named constructed-operator input digests and comparator JSON metrics; do not generate operators or run any estimator/model/analyzer.',
        gate_policy='Exact frozen scorer and wrapper AST nodes, no threshold changes. Relative gates, strict actualSTD<=1, gain and phase failures kept separate. None on absent spatial truth mode is not an invented measurement.',
        no_native_GPU_build_suite=True,source_before=source_before,result=ident(END/'results.json'),completion_manifest=ident(END/'completion_manifest.json')))
    # Execute only exact scorer function/constant AST nodes, never analyzer imports or main.
    selections=[(TESTS/'fsrd_alpha_common.py','LUMA','assign'),(TESTS/'probe_fsrd_additive_split.py','blur','function'),
        (TESTS/'probe_fsrd_statistical_resolve.py','score','function'),(TESTS/'probe_fsrd_statistical_resolve.py','acceptance','function'),
        (TOOLS/'factorized_pilot_feasibility_20260930/analyze.py','moments','function'),
        (TOOLS/'phase_aligned_pilot_feasibility_20260930/analyze.py','detail','function'),(END/'analyze.py','metrics','function')]
    ns={'np':np,'WINDOWS':[('full',slice(None)),('mature',slice(-16,None))]};extraction=[]
    for p,name,kind in selections:
        text=p.read_text(encoding='utf-8-sig');tree=ast.parse(text)
        node=next(n for n in tree.body if (kind=='function'and isinstance(n,ast.FunctionDef)and n.name==name)or(kind=='assign'and isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id==name for t in n.targets)))
        extraction.append(dict(source=ident(p),name=name,kind=kind,exact_source_segment_sha256=hashlib.sha256(ast.get_source_segment(text,node).encode()).hexdigest(),AST_sha256=hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()))
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),ns)
    ref=SimpleNamespace(score=ns['score'],acceptance=ns['acceptance']);ns['ref']=ref;ns['helper']=SimpleNamespace(moments=ns['moments']);ns['cpu']=SimpleNamespace(first=SimpleNamespace(detail=ns['detail']),ref=ref)
    save('frozen_scorer_ast_extraction.json',dict(nodes=extraction,model_or_analyzer_modules_imported=0,window_selection='full and mature only; metrics AST function body unchanged, WINDOWS bounds match frozen values'))
    scorer_before={x['source']['path']:x['source']for x in extraction}
    previous=read(OLD/'results.json');pn={r['scene']:r for r in previous['native_rows']};pk={r['name']:r for r in previous['known_operator_rows']}
    dc_report=read(DC/'results.json');dcn={r['scene']:r for r in dc_report['saved_native_rows']}
    assert len(result['native_rows'])==6 and len(result['known_operator_rows'])==24
    inpkeys=('source_SHA','P_SHA','TP_SHA','baseline_SHA','controls_SHA','truth_scoring_only_SHA')
    native=[];recomputed=[];checks=Counter()
    for row in result['native_rows']:
        scene=row['scene'];oldrow=pn[scene]
        folder=TOOLS/('native_continuous_harmonic_fresh_retry_20260930'if scene=='material'else'native_continuous_harmonic_remaining_20260930')/'evidence'
        path=folder/scene/'sequences.npz';controls=folder/scene/'observed/frame_controls.txt';source_report=folder/'results.json'
        assert sha(path)==row['sequences_sha256']and sha(source_report)==row['source_report_sha256']
        for k in inpkeys+('sequences_sha256','source_report_sha256'):check_equal(row[k],oldrow[k],(scene,k));checks['native_input_record_equalities']+=1
        source=read(source_report);sr=next(x for x in source['rows']if x['scene']==scene)
        with np.load(path,allow_pickle=False)as z,np.load(END/f'{scene}_outputs.npz',allow_pickle=False)as new,np.load(OLD/f'{scene}_outputs.npz',allow_pickle=False)as old:
            B=z['baseline'];truth=z['clean_reference'];active=z['active'];ctrl=np.loadtxt(controls,ndmin=2)
            for key,name in [('observed','source_SHA'),('pilot','P_SHA'),('pilot_response','TP_SHA'),('baseline','baseline_SHA'),('clean_reference','truth_scoring_only_SHA')]:assert digest(z[key])==row[name]
            assert digest(ctrl)==row['controls_SHA']
            output=new['candidate'];pre=new['preDC'];control=new['frozen_DC_control'];oldoutput=old['candidate']
            assert output.shape==B.shape and str(output.dtype)==str(B.dtype)
            assert digest(output)==row['candidate_SHA']and digest(pre)==row['preDC_SHA']
            assert digest(oldoutput)==oldrow['candidate_SHA']
            assert output[:8].tobytes()==B[:8].tobytes()and output[~active].tobytes()==B[~active].tobytes()
            assert output.shape==(64,80,128,3)
            assert np.all(np.isfinite(output)&(output>=0)&(output<=65504))
            assert np.array_equal(control,old['frozen_DC_control'])
            assert row['diagnostics']['application']['atomic_fallback_pixel_fraction']==0
            assert all(x['fallback_pixel_fraction']==0 for x in row['diagnostics']['application']['frames'])
            variants={name:z[name]for name in sr['variants']};assert len(variants)==6
            variants.update(frozen_DC_innovation_safe=control,frozen_V2_delta_history=oldoutput,candidate=output)
            metrics={}
            for name,value in variants.items():
                m=ns['metrics'](value,truth,B,sr['null_rms'],scene);metrics[name]=m
                for w in('full','mature'):check_equal(m[w],row['variants'][name][w],(scene,name,w));checks['recomputed_native_metric_dicts']+=1
                recomputed.append(dict(scene=scene,variant=name,full=m['full'],mature=m['mature']))
            for name in variants:
                if name=='candidate':continue
                predecessor='candidate'if name=='frozen_V2_delta_history'else name
                for w in row['variants'][name]:check_equal(row['variants'][name][w],oldrow['variants'][predecessor][w],(scene,name,w,'previous'));checks['native_comparator_metric_dicts_equal_previous_V2']+=1
            for name in sr['variants']:
                for w in dcn[scene]['variants'][name]:check_equal(row['variants'][name][w],dcn[scene]['variants'][name][w],(scene,name,w,'previousDC'));checks['native_original6_metric_dicts_equal_previous_DC']+=1
            for w in dcn[scene]['variants']['new_final_DC_innovation_safe']:check_equal(row['variants']['frozen_DC_innovation_safe'][w],dcn[scene]['variants']['new_final_DC_innovation_safe'][w],(scene,'DC',w));checks['native_DC_metric_dicts_equal_previous_DC']+=1
            n=dict(scene=scene,source_npz=ident(path),saved_candidate_npz=ident(END/f'{scene}_outputs.npz'),saved_V2_npz=ident(OLD/f'{scene}_outputs.npz'),
                candidate_digest=digest(output),preDC_digest=digest(pre),frozen_DC_digest=digest(control),first8_exact_B=True,inactive_exact_B=True,
                shape=list(output.shape),dtype=str(output.dtype),finite_native_RGB_range=True,atomic_fallback_pixel_fraction=0,
                full={v:compact(m['full'])for v,m in metrics.items()},mature={v:compact(m['mature'])for v,m in metrics.items()})
            for w in('full','mature'):
                for v in('frozen_DC_innovation_safe','frozen_V2_delta_history'):
                    den=n[w][v]['STD'];n[w]['candidate']['STD_ratio_to_'+v]=n[w]['candidate']['STD']/den if den else None
            native.append(n)
        print('saved-array score verified',scene,flush=True)
    # Known candidate outputs were not saved. Authenticate reports/generator source;
    # no constructed operator or model rerun to manufacture missing arrays.
    whitelist=read(END/'analysis_implementation_whitelist.json')
    oldops=(OLD/'known_operators.py').read_text();change=whitelist['operator_import_replacement_only']
    assert sha(OLD/'known_operators.py')==whitelist['unchanged_24_known_operator_generator_SHA']
    assert oldops.replace(change['before'],change['after'])==(END/'known_operators.py').read_text()
    assert [r['name']for r in result['known_operator_rows']]==[r['name']for r in previous['known_operator_rows']]
    known=[]
    for row in result['known_operator_rows']:
        old=pk[row['name']]
        for k in inpkeys:check_equal(row[k],old[k],(row['name'],k));checks['known_operator_input_digest_equalities']+=1
        for name in('original_current_D','frozen_DC_innovation_safe','frozen_V2_delta_history'):
            prevname='candidate'if name=='frozen_V2_delta_history'else name
            for w in row['variants'][name]:check_equal(row['variants'][name][w],old['variants'][prevname][w],(row['name'],name,w));checks['known_comparator_metric_dicts_equal_previous']+=1
        known.append(dict(name=row['name'],inputs={k:row[k]for k in inpkeys},first8_exact_B_reported=row['first8_exact_B'],
            windows={w:{v:compact(row['variants'][v][w])for v in row['variants']}for w in('full','mature')},
            qualification='Candidate known-operator values are frozen report evidence only; no saved candidate array exists for independent numeric rescoring. All comparator metrics and input records match previous reports.'))
    counts={}
    for v in('frozen_DC_innovation_safe','frozen_V2_delta_history','candidate'):
        counts[v]={}
        for w in('full','mature'):
            ms=[r[w][v]for r in native]
            counts[v][w]=dict(rows=6,relative_effective=sum(m['relative_effective']for m in ms),strict_STD_le1=sum(m['strict_STD_le1']is True for m in ms),
                absolute_GAIN=sum(m['absolute_GAIN']for m in ms),absolute_PHASE=sum(m['absolute_PHASE']for m in ms),absolute_GAIN_AND_PHASE=sum(m['absolute_GAIN_AND_PHASE']for m in ms),
                relative_AND_strict_STD_AND_GAIN_AND_PHASE=sum(m['relative_effective']and m['strict_STD_le1']is True and m['absolute_GAIN_AND_PHASE']for m in ms))
    compact=read(END/'compact_report.json')
    for v in counts:
        for w in counts[v]:
            for k,pkey in [('relative_effective','relative_effective'),('strict_STD_le1','strict_STD_le1'),('absolute_GAIN','absolute_gain_pass'),('absolute_PHASE','absolute_phase_pass'),('absolute_GAIN_AND_PHASE','absolute_gain_AND_phase'),('relative_AND_strict_STD_AND_GAIN_AND_PHASE','relative_AND_STRICT_STD_AND_gain_AND_phase')]:check_equal(counts[v][w][k],compact['counts'][v][w][pkey],(v,w,k))
    source_after=[ident(p)for p in freeze['sources']];assert source_before==source_after
    for x in manifest['files']+manifest['external_authorization_and_review']:verify_identity(x)
    for p,x in scorer_before.items():assert ident(p)==x
    save('independently_recomputed_native_metrics.json',dict(schema='exact-frozen-full-and-mature-native-saved-array-metrics-v1',rows=recomputed))
    audit=dict(schema='endpoint-post-score-independent-CPU-audit-v1',status='passed_frozen_evidence_and_saved_array_score_audit_no_quality_acceptance',
        UTC=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-started,producer_result=ident(END/'results.json'),producer_completion=ident(END/'completion_manifest.json'),
        completion_records_verified=len(manifest['files']),external_authorization_review_records_verified=len(manifest['external_authorization_and_review']),completion_self_excluded=True,
        corrected_preparation_records_verified=len(corrected['files']),corrected_external_source_records_verified=len(corrected['external_source_files']),
        source_pin_count=61,before_after61_exact=True,scorer_nodes=extraction,scorer_dependencies_before_after_exact=True,
        checks=dict(checks),six_native_rows=native,known24_report_records=known,counts=counts,
        qualification=['Post-score audit, not a blind candidate trial. No estimator/model or analyzer execution, no native/GPU/build.',
            'All six saved native candidate outputs, preDC digests, unchanged inputs, first8 exactB, finite native RGB and zero fallback are directly verified.',
            '108 native metric dictionaries independently recomputed: nine saved-array variants across six scenes and full/mature windows. Comparator JSON metrics authenticate all five original windows.',
            '24 known candidate outputs were not saved; their candidate metrics are reported evidence, not independently rescored arrays. No additional operator generation is authorized or performed.',
            'Relative gates allow 5 percent plus1e-4 slack and are not strict noise-reduction proof. Gain and phase remain separate; None on an absent clean-reference mode is not a measured pass.',
            'Other7source+22source adversaries lack matching native TP. Six posthoc saved response rows and constructed controls do not establish runtime/game quality or stain/wave solution.'],
        CPU_saved_array_metric_dicts=checks['recomputed_native_metric_dicts'],CPU_model_calls=0,CPU_analyzer_runs=0,constructed_operator_generator_calls=0,native_contexts=0,native_API_dispatches=0,GPU_jobs=0,builds=0,quality_accepted=False)
    save('audit.json',audit)
    save('post_audit_external_freeze.json',dict(before=source_before,after=source_after,all61_exact=True,producer_completion=ident(END/'completion_manifest.json')))
    print(json.dumps(dict(audit=ident(HERE/'audit.json'),counts=counts['candidate'],checks=dict(checks))),flush=True)
if __name__=='__main__':main()
