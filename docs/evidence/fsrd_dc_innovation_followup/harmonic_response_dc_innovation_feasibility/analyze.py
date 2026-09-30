"""Frozen source feasibility and saved matching-response postcompose, no GPU."""
from pathlib import Path
import sys,importlib.util,json,hashlib,time
import numpy as np
from model import make_source_dc_innovation_target,apply_target
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];SRC=ROOT/'tools_tmp/source_continuous_harmonic_feasibility_20260930'
sys.path.insert(0,str(SRC))
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
cpu=load('fixed_harmonic_source_score',SRC/'analyze.py');harmonic=load('fixed_harmonic_P',SRC/'harmonic_pilot.py')
from adversary_generator import adversaries
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(a):return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
WINDOWS=[('full',slice(None)),('mature',slice(-16,None)),('startup_first8',slice(0,8)),('activation8to16',slice(8,16))]
def metrics(value,truth,baseline,null,scene):
    out={}
    for window,sl in WINDOWS:
        invalid=~np.all(np.isfinite(value[sl])&(value[sl]>=0)&(value[sl]<=65504),axis=-1)
        if not np.isfinite(value[sl]).all():out[window]=dict(unscorable_nonfinite=True,invalid_pixel_fraction=float(invalid.mean()));continue
        m=cpu.first.detail(value[sl],truth[sl]);b=cpu.first.detail(baseline[sl],truth[sl]);activity=float(np.mean(abs(value[sl]-baseline[sl])>1e-5))
        m['relative_gate']=cpu.ref.acceptance(m['score'],b['score'],activity,null,scene)
        base_std=b['score']['residual_temporal_std'];m['actual_STD_ratio_to_control']=m['score']['residual_temporal_std']/base_std if base_std else None
        error=value[sl,5:-5,5:-5].astype(float)-truth[sl,5:-5,5:-5].astype(float)
        m['mean_temporal_variance']=float(np.mean(np.var(error,axis=0)));m['invalid_pixel_fraction']=float(invalid.mean());out[window]=m
    return out
def target_metrics(target,valid,truth):
    cleanDC=truth[:,5:-5,5:-5].mean((1,2),dtype=float);out={}
    for name,sl in WINDOWS:
        okay=valid[sl];errors=target[sl][okay]-cleanDC[sl][okay]
        out[name]=dict(valid_frames=int(okay.sum()),excluded_invalid_frames=int((~okay).sum()),RMSE=None if not len(errors) else float(np.sqrt(np.mean(errors**2))),
                      bias_RGB=None if not len(errors) else errors.mean(0).tolist(),temporal_STD_RGB=None if not len(errors) else errors.std(0).tolist())
    return out
def source_row(scene,raw,truth,controls,exposure=None):
    P,active,diag=harmonic.make_continuous_harmonic_pilot(raw,controls,exposure);P=P.astype('f2').astype('f4')
    epochs=np.array([r['epoch_start'] for r in diag['frames']]);T,V,D=make_source_dc_innovation_target(raw,controls,epochs,exposure)
    new,A=apply_target(P,raw,active,T,V,False)
    with np.errstate(invalid='ignore',over='ignore'):new=new.astype('f2').astype('f4')
    safe_error=None
    try:
        safe,AD=apply_target(P,raw,active,T,V,True);safe=safe.astype('f2').astype('f4')
    except ValueError as exc:safe=None;AD=None;safe_error=str(exc)
    variants={'unchanged_frozen_P':metrics(P,truth,P,0,scene),'source_proxy_DC_innovation':metrics(new,truth,P,0,scene)}
    if safe is not None:variants['source_proxy_DC_innovation_safe']=metrics(safe,truth,P,0,scene)
    assert new[~active].tobytes()==P[~active].tobytes()
    return dict(source_SHA=digest(raw),truth_scoring_only_SHA=digest(truth),controls_SHA=digest(controls),source_epoch_SHA=digest(epochs),exposure_SHA=None if exposure is None else digest(exposure),
        fixed_P_SHA=digest(P),target_SHA=digest(T),target_valid_SHA=digest(V),target_diagnostics=D,target_metrics=target_metrics(T,V,truth),variants=variants,
        application_diagnostics=A,safe_application_diagnostics=AD,safe_error=safe_error,
        label='CPU_source_proxy_not_native_output',first8_pilot_inactive_no_new_activation=True)
def main():
    if (HERE/'results.json').exists():raise ValueError('Preserve result')
    freeze=read(HERE/'pre_score_freeze.json');assert all(sha(p)==s for p,s in freeze['sources'].items())
    check=read(HERE/'selfcheck_results.json');assert check['status']=='passed_pre_score_selfchecks' and check['model_sha256']==sha(HERE/'model.py')
    report=dict(status='running',quality_accepted=False,new_P_prototype=False,new_native_dispatches=0,source_proxy_not_native_coverage=True,pre_score_freeze=freeze,selfchecks=check,source_rows=[],adversaries=[],saved_native_rows=[])
    evidence=cpu.ref.EVIDENCE/'response_temporal_spectral_alpha_holdout';old=read(evidence/'results.json');fixture,hashes=cpu.helper.snapshot_fixture(evidence,old)
    report['authenticated_fixture_sources']=hashes
    for row in old['rows']:
        scene=row['scene'];raw,data=cpu.helper.regenerate(scene,old,fixture);path=evidence/scene/'sequences.npz'
        with np.load(path) as z:assert raw.tobytes()==z['observed'].tobytes() and data['truth'].tobytes()==z['clean_reference'].tobytes()
        controls=cpu.ref.controls_from_native(evidence/scene/'observed/frame_controls.txt',len(raw));np.testing.assert_array_equal(controls,data['controls'])
        result=source_row(scene,raw,data['truth'],controls);report['source_rows'].append(dict(scene=scene,sequences_sha256=sha(path),result=result))
        print('source',scene,result['variants']['source_proxy_DC_innovation']['mature']['actual_STD_ratio_to_control'],flush=True)
    for a in adversaries():
        result=source_row(a['family'],a['raw'],a['truth'],a['controls'],a['exposure']);report['adversaries'].append(dict(scene=a['family'],result=result))
        print('adversary',a['family'],result['variants']['source_proxy_DC_innovation']['mature'].get('actual_STD_ratio_to_control'),flush=True)
    audit=read(ROOT/'tools_tmp/native_continuous_harmonic_independent_audit_20260930/audit.json')
    for oldrow in audit['rows']:
        scene=oldrow['scene'];base=ROOT/'tools_tmp'/('native_continuous_harmonic_fresh_retry_20260930' if scene=='material' else 'native_continuous_harmonic_remaining_20260930')/'evidence'
        native=read(base/'results.json');row=next(r for r in native['rows'] if r['scene']==scene);path=base/scene/'sequences.npz';assert sha(path)==oldrow['sequences_sha256']==row['sequences_sha256']
        with np.load(path) as z:
            raw=z['observed'];truth=z['clean_reference'];B=z['baseline'];P=z['pilot'];TP=z['pilot_response'];active=z['active'];C=z['harmonic']
            assert C.tobytes()==(B+active[:,None,None,None]*(P-TP)).tobytes()
            controls=cpu.ref.controls_from_native(base/scene/'observed/frame_controls.txt',len(raw));epochs=np.array([r['epoch_start'] for r in row['pilot_diagnostics']['frames']])
            T,V,D=make_source_dc_innovation_target(raw,controls,epochs);new,A=apply_target(C,B,active,T,V,False);safe,AD=apply_target(C,B,active,T,V,True)
            assert new[~active].tobytes()==B[~active].tobytes() and safe[~active].tobytes()==B[~active].tobytes()
            variants={name:metrics(z[name],truth,B,row['null_rms'],scene) for name in row['variants']}
            variants['new_final_DC_innovation']=metrics(new,truth,B,row['null_rms'],scene);variants['new_final_DC_innovation_safe']=metrics(safe,truth,B,row['null_rms'],scene)
            # P/TP/C remain unchanged and no alternate pilot response is read.
            result=dict(scene=scene,label='posthoc_saved_matching_native_response_no_new_native',sequences_sha256=sha(path),source_native_report_sha256=sha(base/'results.json'),
                fixed_P_SHA=digest(P),matching_TP_SHA=digest(TP),baseline_SHA=digest(B),controls_SHA=digest(controls),source_epoch_SHA=digest(epochs),
                target_SHA=digest(T),target_valid_SHA=digest(V),target_diagnostics=D,target_metrics=target_metrics(T,V,truth),variants=variants,
                application_diagnostics=A,safe_application_diagnostics=AD,existing_baseline_metrics=row['baseline_metrics'],first8_inactive_exact_baseline=True)
            report['saved_native_rows'].append(result)
        print('native_saved',scene,variants['new_final_DC_innovation_safe']['mature']['actual_STD_ratio_to_control'],flush=True)
    assert len(report['source_rows'])==13 and len(report['adversaries'])==22 and len(report['saved_native_rows'])==6
    assert all(sha(p)==s for p,s in freeze['sources'].items())
    report['status']='completed_CPU_source_and_saved_response_feasibility_not_solution'
    report['limitations']=['Source13+22 proxy cannot fill native coverage; saved actual matching response coverage6 only.',
        'Nominal IID plug-in uncertainty, sourceadaptivity and unknown RGB/spatial/time covariance are not confidence.',
        'Current-mean artifact and illumination can be observationally identical; innovation selects both. Slow changes can lag.',
        'Uniform DC offsets cannot repair prior nonDC detail/startup failures; atomic fallback changes spatial field.',
        'All failures preserved; relative tolerance allowance is not strict STD/absolute-detail acceptance.']
    (HERE/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print('results SHA',sha(HERE/'results.json'),flush=True)
if __name__=='__main__':main()
