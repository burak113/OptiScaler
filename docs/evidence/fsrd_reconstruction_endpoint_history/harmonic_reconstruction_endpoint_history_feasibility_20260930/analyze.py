"""Frozen reconstruction endpoint OLS: execute only after separate root law review."""
from pathlib import Path
import sys,importlib.util,json,hashlib,time
import numpy as np
from model import make_response_history,dc
from known_operators import cases
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];SRC=ROOT/'tools_tmp/source_continuous_harmonic_feasibility_20260930'
sys.path.insert(0,str(SRC))
spec=importlib.util.spec_from_file_location('frozen_harmonic_score_only',SRC/'analyze.py');cpu=importlib.util.module_from_spec(spec);spec.loader.exec_module(cpu)
oldsp=importlib.util.spec_from_file_location('frozen_V2_delta_history',ROOT/'tools_tmp/harmonic_response_coefficient_history_feasibility_v2_20260930/model.py');old_v2=importlib.util.module_from_spec(oldsp);oldsp.loader.exec_module(old_v2)

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(a):return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
WINDOWS=[('full',slice(None)),('mature',slice(-16,None)),('startup_first8',slice(0,8)),('activation8to16',slice(8,16)),('transition24to40',slice(24,40))]
def metrics(value,truth,baseline,null,scene):
    out={}
    for window,sl in WINDOWS:
        invalid=~np.all(np.isfinite(value[sl])&(value[sl]>=0)&(value[sl]<=65504),axis=-1)
        if not np.isfinite(value[sl]).all():out[window]=dict(unscorable_nonfinite=True,invalid_pixel_fraction=float(invalid.mean()));continue
        m=cpu.first.detail(value[sl],truth[sl]);b=cpu.first.detail(baseline[sl],truth[sl]);activity=float(np.mean(abs(value[sl]-baseline[sl])>1e-5))
        m['relative_gate']=cpu.ref.acceptance(m['score'],b['score'],activity,null,scene)
        bs=b['score']['residual_temporal_std'];m['actual_STD_ratio_to_control']=m['score']['residual_temporal_std']/bs if bs else None
        error=value[sl,5:-5,5:-5].astype(float)-truth[sl,5:-5,5:-5].astype(float)
        m['mean_temporal_variance']=float(np.mean(np.var(error,axis=0)));m['invalid_pixel_fraction']=float(invalid.mean());out[window]=m
    return out
def run_case(a):
    raw,P,TP,B,active,ctrl=(a[k] for k in ('raw','P','TP','B','active','controls'))
    output,diag,preDC=make_response_history(raw,P,TP,B,active,ctrl,a['diag'],a['descriptors'],a.get('exposure'))
    old_output,old_diag,old_pre=old_v2.make_response_history(raw,P,TP,B,active,ctrl,a['diag'],a['descriptors'],a.get('exposure'))
    original=B+active[:,None,None,None]*(P-TP);epochs=np.asarray([r['epoch_start'] for r in a['diag']['frames']])
    T,V,_=dc.make_source_dc_innovation_target(raw,ctrl,epochs,a.get('exposure'));control,cd=dc.apply_target(original,B,active,T,V,True)
    scored={name:metrics(v,a['truth'],B,0,a['name']) for name,v in [('original_current_D',original),('frozen_DC_innovation_safe',control),('frozen_V2_delta_history',old_output),('candidate',output)]}
    assert output[~active].tobytes()==B[~active].tobytes()
    return dict(name=a['name'],label=a['label'],source_SHA=digest(raw),P_SHA=digest(P),TP_SHA=digest(TP),baseline_SHA=digest(B),controls_SHA=digest(ctrl),
        truth_scoring_only_SHA=digest(a['truth']),diagnostics=diag,variants=scored,unchanged_inputs=True,first8_exact_B=output[:8].tobytes()==B[:8].tobytes(),
        preDC_output_SHA=digest(preDC),candidate_SHA=digest(output),frozen_DC_control_SHA=digest(control))
def main():
    if (HERE/'results.json').exists():raise ValueError('Preserve result')
    freeze=read(HERE/'pre_score_freeze.json');assert all(sha(p)==s for p,s in freeze['sources'].items())
    auth=read(HERE/'source_authentication.json');assert auth['status']=='passed_source_hook_authentication_before_scores'
    assert read(HERE/'selfcheck_results.json')['model_sha256']==sha(HERE/'model.py')
    report=dict(schema='current-reconstruction-endpoint-OLS16-feasibility-v1',status='running',pre_score_freeze=freeze,
        quality_accepted=False,new_P_or_TP=False,new_native_dispatches=0,native_rows=[],known_operator_rows=[],other7_and22_native_coverage_absent=True)
    old=read(ROOT/'tools_tmp/harmonic_response_dc_innovation_feasibility_20260930/results.json');old_rows={r['scene']:r for r in old['saved_native_rows']}
    for hook in auth['rows']:
        scene=hook['scene'];folder=ROOT/'tools_tmp'/('native_continuous_harmonic_fresh_retry_20260930' if scene=='material' else 'native_continuous_harmonic_remaining_20260930')/'evidence'
        path=folder/scene/'sequences.npz';rp=folder/'results.json';row=next(r for r in read(rp)['rows'] if r['scene']==scene)
        assert sha(path)==hook['NPZ_sha256'] and sha(rp)==hook['source_report_SHA']
        with np.load(path) as z:
            raw,P,TP,B,active=(z[k].copy() for k in ('observed','pilot','pilot_response','baseline','active'))
            ctrl=np.loadtxt(folder/scene/'observed/frame_controls.txt',ndmin=2)
            output,diag,preDC=make_response_history(raw,P,TP,B,active,ctrl,hook['source_diagnostics'],hook['descriptors'])
            old_output,old_diag,old_pre=old_v2.make_response_history(raw,P,TP,B,active,ctrl,hook['source_diagnostics'],hook['descriptors'])
            original=B+active[:,None,None,None]*(P-TP);assert original.tobytes()==z['harmonic'].tobytes()
            epochs=np.asarray([r['epoch_start'] for r in hook['source_diagnostics']['frames']]);T,V,_=dc.make_source_dc_innovation_target(raw,ctrl,epochs)
            control,cd=dc.apply_target(original,B,active,T,V,True)
            # Truth first enters here, after all estimator outputs have been constructed.
            truth=z['clean_reference'];variants={name:metrics(z[name],truth,B,row['null_rms'],scene) for name in row['variants']}
            for name,m in variants.items():
                for window in ('full','mature','startup_first8','activation8to16'):assert m[window]==old_rows[scene]['variants'][name][window]
            variants['frozen_DC_innovation_safe']=metrics(control,truth,B,row['null_rms'],scene)
            for window in ('full','mature','startup_first8','activation8to16'):assert variants['frozen_DC_innovation_safe'][window]==old_rows[scene]['variants']['new_final_DC_innovation_safe'][window]
            variants['frozen_V2_delta_history']=metrics(old_output,truth,B,row['null_rms'],scene)
            variants['candidate']=metrics(output,truth,B,row['null_rms'],scene)
            assert output[~active].tobytes()==B[~active].tobytes()
            report['native_rows'].append(dict(scene=scene,label='posthoc_matching_saved_native_responses_no_new_native',sequences_sha256=sha(path),
                source_report_sha256=sha(rp),source_SHA=digest(raw),P_SHA=digest(P),TP_SHA=digest(TP),baseline_SHA=digest(B),controls_SHA=digest(ctrl),
                truth_scoring_only_SHA=digest(truth),diagnostics=diag,variants=variants,all_original6_and_frozen_DC_metrics_exact=True,
                first8_inactive_exact_B=output[:8].tobytes()==B[:8].tobytes(),candidate_SHA=digest(output),preDC_SHA=digest(preDC)))
            np.savez_compressed(HERE/(scene+'_outputs.npz'),candidate=output,preDC=preDC,frozen_DC_control=control)
        print('native_saved',scene,'STD mature',variants['candidate']['mature']['actual_STD_ratio_to_control'],'full abs',variants['candidate']['full']['detail_within_5_percent_all_frames'],flush=True)
    for known in cases():
        scored=run_case(known);report['known_operator_rows'].append(scored)
        print('known_operator',known['name'],'STD mature',scored['variants']['candidate']['mature']['actual_STD_ratio_to_control'],flush=True)
    assert len(report['native_rows'])==6
    assert all(sha(p)==s for p,s in freeze['sources'].items())
    report['status']='completed_saved_response_and_known_operator_feasibility_not_solution'
    report['limitations']=['Single posthoc saved matching response operator; no new native or new pilot.',
        'Source phase can differ from true correction phase. Static-source D drift is unidentifiable and can lag.',
        'C/R0 covariance is endogenous/unknown; endpoint IID noise-gain algebra is not confidence. Exact constant/linear invariance only in transported coordinates; acceleration/static reconstruction moving source phase can fail.',
        'First8 baseline and dense/weak source failures remain. Other7+22 matching native response coverage absent.',
        'Relative STD allowance1e-4 is not strict noise reduction. Preserve full/mature absolute and actual STD failures.']
    (HERE/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print('results SHA',sha(HERE/'results.json'),flush=True)
if __name__=='__main__':main()
