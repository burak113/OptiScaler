from pathlib import Path
import json,hashlib,inspect
import numpy as np
from model import make_source_dc_innovation_target,apply_target
HERE=Path(__file__).resolve().parent
def main():
    rng=np.random.default_rng(97201);raw=(.2+rng.normal(0,.012,(80,30,40,3))).astype('f4');ctrl=np.zeros((80,3));ctrl[0,0]=1
    T,V,D=make_source_dc_innovation_target(raw,ctrl);changed=raw.copy();changed[50:]+=.1;cc=ctrl.copy();cc[50:,1:]=[.25,.125]
    U,W,E=make_source_dc_innovation_target(changed,cc)
    np.testing.assert_array_equal(T[:50],U[:50]);assert D['frames'][:50]==E['frames'][:50]
    assert max(r.get('history_used_including_current',0) for r in D['frames'])<=64
    reset=ctrl.copy();reset[15,0]=1;reset[25:,1:]=[.25,0];epochs=np.zeros(80);epochs[35:]=35;ex=np.ones(80);ex[45:]=2
    U,W,E=make_source_dc_innovation_target(raw,reset,epochs,ex)
    for i in (0,15,25,35,45):np.testing.assert_allclose(U[i],raw[i,5:-5,5:-5].mean((0,1),dtype=float),atol=0);assert E['frames'][i]['preceding_observations']==0
    step=raw.copy();step[32:]+=np.array([.1,.02,0]);U,W,E=make_source_dc_innovation_target(step,ctrl,np.zeros(80))
    assert E['frames'][32]['innovation'] and E['frames'][32]['dc_epoch']==32
    assert E['frames'][33]['preceding_observations']==1 and E['frames'][33]['dc_epoch']==32
    impulse=raw.copy();impulse[32]+=.1;U,W,E=make_source_dc_innovation_target(impulse,ctrl)
    assert E['frames'][32]['innovation'] and E['frames'][33]['innovation']
    # Exact flat source needs no fictional independent confidence estimate.
    constant=np.full_like(raw,.2);U,W,E=make_source_dc_innovation_target(constant,ctrl);np.testing.assert_array_equal(U,np.repeat(U[:1],80,0))
    bad=raw.copy();bad[12,1,1,0]=-.01;bad[20,1,1,1]=np.nan;bad[30,1,1,2]=65505;bad[40,:,:,0]=1e-5
    U,W,E=make_source_dc_innovation_target(bad,ctrl)
    for i in (12,20,30,40):assert not W[i];assert E['frames'][i+1]['preceding_observations']==0
    invalid_epoch=np.zeros(80);invalid_epoch[25]=26;U,W,E=make_source_dc_innovation_target(raw,ctrl,invalid_epoch);assert not W[25] and E['frames'][26]['preceding_observations']==0
    a=np.ones(80,bool);a[:8]=False;b=raw.copy();candidate=raw+.01
    result,A=apply_target(candidate,b,a,T,V,True);assert result[:8].tobytes()==b[:8].tobytes()
    expected=np.array([c-c.mean((0,1),dtype=float) for c in candidate[8:]])
    got=np.array([c-c.mean((0,1),dtype=float) for c in result[8:]])
    np.testing.assert_allclose(got,expected,atol=3e-8)
    candidate[15,0,0]=[-.01,.1,.2];result,A=apply_target(candidate,b,a,T,V,True);assert result[15,0,0].tobytes()==b[15,0,0].tobytes()
    broken=b.copy();broken[0,0,0,0]=-1
    try:apply_target(candidate,broken,a,T,V,True)
    except ValueError:pass
    else:raise AssertionError('baseline invalid accepted')
    assert list(inspect.signature(make_source_dc_innovation_target).parameters)==['raw','controls','epoch_start_by_frame','exposure']
    r=dict(status='passed_pre_score_selfchecks',source_only_API=True,no_future_target_and_state=True,source_epoch_distinct_DC_epoch=True,
           step_and_impulse_current_history_cut=True,reset_jitter_exposure_and_epoch=True,history64=True,first8_inactive_exact_baseline=True,
           invalid_source_nearzero_and_metadata_cuts=True,nonDC_uniform_offset_algebra=True,atomic_RGB_exact_fallback=True,
           uncertainty='Nominal IID plug-in only',model_sha256=hashlib.sha256((HERE/'model.py').read_bytes()).hexdigest())
    (HERE/'selfcheck_results.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
if __name__=='__main__':main()
