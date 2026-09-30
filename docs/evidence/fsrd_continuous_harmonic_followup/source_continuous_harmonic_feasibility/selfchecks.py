"""Pre-score mathematical/causal/byte selfchecks. No dataset scene scores."""
from pathlib import Path
import importlib.util,inspect,json
import numpy as np
import harmonic_pilot as p
HERE=Path(__file__).resolve().parent

def main():
    spec=importlib.util.spec_from_file_location('frozen_for_selfcheck',p.FROZEN);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    rng=np.random.default_rng(274301);h,w=24,32;y,x=np.indices((h,w));basis=.025*np.cos(2*np.pi*(3.23*x/w+2.17*y/h))
    raw=(.25+basis[None,...,None]+rng.normal(0,.004,(36,h,w,3))).astype('f4');ctrl=np.zeros((36,3));ctrl[0,0]=1;ctrl[22,0]=1;ctrl[29:,1:]=[.25,.125]
    direct,da,dd=old.make_significant_phase_pilot(raw,ctrl);g=p.stream(h,w)
    values=[];act=[];records=[]
    for frame,control in zip(raw,ctrl):v,a,d=g.send((frame.astype(float),control));values.append(v);act.append(a);records.append(d)
    np.testing.assert_array_equal(np.stack(values),direct);np.testing.assert_array_equal(act,da);assert records==dd['frames']
    output,active,diag=p.make_continuous_harmonic_pilot(raw,ctrl)
    future=raw.copy();future[18:]+=.12;q,qa,qd=p.make_continuous_harmonic_pilot(future,ctrl)
    np.testing.assert_array_equal(output[:18],q[:18]);np.testing.assert_array_equal(active[:18],qa[:18]);assert diag['frames'][:18]==qd['frames'][:18]
    assert len(inspect.signature(p.make_continuous_harmonic_pilot).parameters)==3
    for first in (0,22,29):
        end=min(first+8,len(raw));np.testing.assert_array_equal(output[first:end],raw[first:end]);assert not active[first:end].any()
    selected=[r for r in diag['frames'] if r['selection'] is not None]
    assert selected and selected[0]['frame']==8
    assert len(selected[0]['atom_frequencies'])>=1
    assert selected[0]['atom_diagnostics'][0]['prior_count']==0 and selected[0]['residual_prior_observations']==0
    assert all(len(r['atom_frequencies'])<=2 for r in diag['frames'])
    for r in selected:
        assert r['selection']['counts']['objective_attempts']<=136 and r['selection']['counts']['GN_trial_attempts']<=64
    good=active;np.testing.assert_allclose(output[good].astype(float).mean((1,2)),raw[good].astype(float).mean((1,2)),atol=2e-8,rtol=0)
    training=p.mask_for(h,w);assert np.array_equal(training,p.mask_for(h,w))
    covariance=[]
    for freq in ([w/2,0],[0,h/2],[w/2,h/2],[3.23,2.17]):
        model=p.fit_model([freq],raw[:8].astype(float),training);assert model is not None
        group=model['groups'][0];rank=len(group);assert rank==(1 if freq in ([w/2,0],[0,h/2],[w/2,h/2]) else 2)
        X=model['Xt'];np.testing.assert_allclose(model['gamma']@(X.T@X),np.eye(X.shape[1]),atol=2e-14,rtol=0)
        sig=.012;G=model['gamma'][np.ix_(group,group)]
        if rank==2:
            D=np.diag([.5,-.5]);cov=sig*sig*D@G@D;qenv=sig*sig*np.linalg.eigvalsh(G).max()/2
            assert np.linalg.eigvalsh(qenv*np.eye(2)/2-cov).min()>-1e-20
        else:
            z=np.array([.02,.015,.01]);past=[z.copy() for _ in range(12)];qvar=sig*sig*G[0,0]
            pred,d=p.predict_atom(z,qvar,past,[qvar]*12,rank);assert not d['phase_used'] and d['phase_increment']==0
            np.testing.assert_allclose(pred,z,atol=1e-17,rtol=0)
        covariance.append(dict(frequency=freq,rank=rank,nominal_covariance_matrix=(sig*sig*G).tolist()))
    assert p.fit_model([[3.23,2.17],[3.23000001,2.17000001]],raw[:8].astype(float),training) is None
    invalid={}
    for reason in ('negative','nearzero','NaNpayload','overflow','metadata','exposure'):
        r=raw[:14].copy();cc=ctrl[:14].copy();exposure=None
        if reason=='negative':r[9,2,2,0]=-1
        if reason=='nearzero':r[9,...,0]=1e-5
        if reason=='NaNpayload':r.view('u4')[9,2,2,0]=0x7fc12345;r.view('u4')[9,1,1,0]=0x80000000
        if reason=='overflow':r[9,2,2,0]=65505
        if reason=='metadata':cc[9,0]=.25
        if reason=='exposure':exposure=np.ones(14);exposure[9:]=2
        value,aa,d=p.make_continuous_harmonic_pilot(r,cc,exposure)
        assert value.dtype==r.dtype;np.testing.assert_array_equal(value[9].view('u4'),r[9].view('u4'));assert not aa[9]
        assert d['frames'][10]['epoch_start']==10;np.testing.assert_array_equal(value[10:],r[10:])
        invalid[reason]=True
    original=p.select_model
    def broken(*args):raise p.BudgetFailure('forced_budget_check')
    p.select_model=broken
    try:
        value,aa,d=p.make_continuous_harmonic_pilot(raw[:12],ctrl[:12]);np.testing.assert_array_equal(value[8],raw[8]);assert not aa[8] and d['frames'][9]['epoch_start']==9
    finally:p.select_model=original
    def badfit(*args):return None,dict(objective_attempts=1,factorization_attempts=1,successful_linear_matrix_refits=0,linear_scalar_RHS=0,GN_solve_attempts=0,GN_trial_attempts=0,backtracking_trials=0),[],'invalid_training_fit'
    p.select_model=badfit
    try:
        value,aa,d=p.make_continuous_harmonic_pilot(raw[:12],ctrl[:12]);np.testing.assert_array_equal(value[8],raw[8]);assert not aa[8] and d['frames'][9]['epoch_start']==9
    finally:p.select_model=original
    constant=np.full((16,h,w,3),.2,dtype='f4');value,aa,d=p.make_continuous_harmonic_pilot(constant,ctrl[:16])
    assert all(not r['atom_frequencies'] for r in d['frames']);assert d['frames'][8]['no_atom_prior_observations']==8
    np.testing.assert_array_equal(value[:8],constant[:8]);np.testing.assert_allclose(value,constant,atol=1e-7,rtol=0)
    assert d['exposure_unknown'] and diag['total_counts']['background_FFT_steps']==len(raw)
    result=dict(status='passed_pre_score_selfchecks',frozen_stepper_batch_P_active_diagnostics_bitexact=True,
        future_prefix_P_active_frequency_state_decisions_exact=True,raw_warmup_reset_jitter_exact=True,
        no_atom_history_includes_first8=True,accepted_atom_and_residual_histories_start_at_frame8=True,
        rank_aware_Nyquist_phase0_and_covariance=covariance,rank_illcondition_rejection=True,
        invalid_raw_dtype_payload_bits_preserved=invalid,forced_budget_and_invalid_fit_exact_raw_epoch_cut=True,
        current_DC_numeric_closure=True,source_guides_truth_not_in_API=True,mask_sha256=diag['mask_sha256'],source_sigma_IID_only=True,
        prototype_sha256=p.sha(HERE/'harmonic_pilot.py'),selfcheck_sha256=p.sha(__file__),frozen_source_sha256=p.FROZEN_SHA,
        stream_adapter_sha256=diag['stream_adapter_sha256'])
    (HERE/'selfcheck_results.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    (HERE/'frozen_stream_adapter.py').write_text(p.STEPPER_SOURCE)
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
