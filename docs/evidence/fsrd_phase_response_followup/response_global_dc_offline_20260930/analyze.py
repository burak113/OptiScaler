"""Frozen posthoc comparison of observable same-frequency/DC response fits."""
from pathlib import Path
import hashlib,importlib.util,json
import numpy as np
from model import calibrate
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'tools_tmp/native_significant_phase_initial_20260930/evidence'
PRIOR=ROOT/'tools_tmp/response_affine_spectrum_offline_20260930/analyze.py'
spec=importlib.util.spec_from_file_location('prior_affine',PRIOR)
prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
ref=prior.reference

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def self_checks():
    rng=np.random.default_rng(59301);shape=(40,8,8,3)
    p=.2+rng.normal(0,.003,shape);r=.85*p+.004;ctrl=np.zeros((40,3));ctrl[0,0]=1
    active=np.ones(40,bool)
    a,j=calibrate(p,r,p,ctrl,active);pc=p.copy();rc=r.copy();pc[25:]+=.1;rc[25:]*=2
    b,_=calibrate(pc,rc,pc,ctrl,active);np.testing.assert_array_equal(a[:25],b[:25])
    assert max(v['count'] for v in j)==16
    cc=ctrl.copy();cc[12,0]=1;cc[24:,1]=.25
    a,j=calibrate(p,r,p,cc,active)
    for index in (0,12,24):np.testing.assert_array_equal(a[index],p[index]-r[index]);assert j[index]['count']==1
    aa=active.copy();aa[30]=False;a,j=calibrate(p,r,p,ctrl,aa)
    assert not a[30].any();np.testing.assert_array_equal(a[31],p[31]-r[31])
    y,x=np.indices((8,8));f=np.arange(40)[:,None,None]
    dc=.2+.02*np.sin(.7*np.arange(40))
    wave=.03*np.cos(2*np.pi*x/8+.8*f)
    pp=np.repeat((dc[:,None,None]+wave)[...,None],3,axis=-1)
    artifact=.06*dc[:,None,None,None]*np.cos(2*np.pi*y/8)[None,...,None]
    delta=np.repeat(.12*wave[...,None]+artifact,3,axis=-1)
    rr=pp-delta
    a,j=calibrate(pp,rr,pp,ctrl,active)
    np.testing.assert_allclose(a[8:],delta[8:],rtol=0,atol=1e-12)
    # Orthogonal k_y artifact cannot be explained by the original k_x feature.
    control,_=prior.calibrate(pp,rr,pp,ctrl,active)
    assert np.max(abs(control[8:]-delta[8:]))>1e-5
    fixed=np.full(shape,.2)+.03*np.cos(2*np.pi*x/8+.8*f)[...,None]
    rr=.8*fixed+.003
    a,_=calibrate(fixed,rr,fixed,ctrl,active);control,_=prior.calibrate(fixed,rr,fixed,ctrl,active)
    np.testing.assert_allclose(a,control,rtol=0,atol=1e-12)
    pp=np.full(shape,.2);rr=np.full(shape,.18)
    a,_=calibrate(pp,rr,pp,ctrl,active);np.testing.assert_allclose(a,pp-rr,rtol=0,atol=1e-15)
    return dict(no_future=True,history16=True,reset_jitter_inactive=True,nonlocal_dc_artifact_with_rotating_detail=True,
                constant_dc_matches_reference=True,constant_rank_deficiency_finite=True)

def absolute_gates(measured):
    gain=measured['contrast_gain'];phase=measured['phase_error_radians']
    return dict(gain_failed_frames=[i for i,v in enumerate(gain) if v is not None and not .95<=v<=1.05],
                phase_failed_frames=[i for i,v in enumerate(phase) if v is not None and v>.05])

def main():
    dest=Path(__file__).with_name('results.json')
    if dest.exists():raise ValueError('Preserve previous evidence')
    rp=SOURCE/'results.json';rh=sha(rp);source=json.loads(rp.read_text());assert source['status']=='completed_research_not_solution'
    report=dict(schema='response-global-dc-conditioned-offline-v1',status='running',quality_accepted=False,
        native_rerun=False,game_run=False,runtime_implemented=False,posthoc=True,
        source_report_sha256=rh,script_sha256=sha(__file__),model_sha256=sha(Path(__file__).with_name('model.py')),
        preregistration_sha256=sha(Path(__file__).with_name('preregistration.md')),prior_sha256=sha(PRIOR),
        self_checks=self_checks(),rows=[],limitations=[
          'Posthoc six initial synthetic cases; not holdout/game acceptance.',
          'Current-inclusive endogenous fit and nominal IID ridge are not statistical confidence.',
          'Global DC can induce nonlocal artifacts but need not identify nonlinear/native settling response.',
          'Truth is used by scores only; persistent shared source bias remains unidentifiable.',
          'No new P is substituted into an old native T(P). No GPU rerun.',
          'No age term, motion reprojection or runtime implementation.'])
    for row in source['rows']:
        scene=row['scene'];sp=SOURCE/scene/'sequences.npz';sh=sha(sp)
        cp=SOURCE/scene/'observed/frame_controls.txt';ch=sha(cp)
        with np.load(sp) as a:
            controls=ref.controls_from_native(cp,len(a['pilot']));variants={};diagnostics={}
            for label,fn in [('affine_control',prior.calibrate),('global_dc',calibrate)]:
                delta,records=fn(a['pilot'],a['pilot_response'],a['observed'],controls,a['active'])
                value=a['baseline']+delta
                dc=ref.dc_conservation(value,a['observed'],a['active'],controls,1,[v['epoch'] for v in records])
                safe,fraction=ref.radiance_fallback(dc,a['baseline'])
                for suffix,v,fallback in [('',value,0),('_dc_current',dc,0),('_dc_current_safe',safe,fraction)]:
                    measured=ref.evaluate(v,a['baseline'],a['clean_reference'],scene,a['active'],row['null_rms'],fallback)
                    for window in ('full','mature'):
                        measured[window+'_absolute_gain_phase']=absolute_gates(measured[window])
                        measured[window+'_std_ratio']=measured[window]['residual_temporal_std']/row['baseline_'+window]['residual_temporal_std']
                    variants[label+suffix]=measured
                diagnostics[label]=records
        assert sha(sp)==sh and sha(cp)==ch and sha(rp)==rh
        report['rows'].append(dict(scene=scene,sequences_sha256=sh,controls_sha256=ch,source_files_unchanged=True,
            variants=variants,diagnostics=diagnostics,baseline_full=row['baseline_full'],baseline_mature=row['baseline_mature'],null_rms=row['null_rms']))
        print(scene,{k:dict(full=v['full_gate']['failures'],mature=v['mature_gate']['failures'],mature_std_ratio=v['mature_std_ratio']) for k,v in variants.items() if k.endswith('_safe')},flush=True)
    report['status']='completed_posthoc_falsification_not_solution'
    dest.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')

if __name__=='__main__':main()
