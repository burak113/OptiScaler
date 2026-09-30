from pathlib import Path
import json,hashlib
import numpy as np
import model
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def descriptor(freq=(3.23,1.17),chosen=(0,1,2)):
    return dict(frequencies=[list(freq)],chosen=list(chosen),groups=[list(range(1,len(chosen)))],original_groups=[[1,2]])
def physical(desc,h,w):return model.physical_projection(desc,h,w)['Phi']
def source_records(n,desc,theta=0.,used=False):
    return dict(frames=[dict(frame=i,epoch_start=0,atom_frequencies=desc['frequencies'] if desc else [],
        atom_diagnostics=[] if desc is None else [dict(phase_increment=theta,phase_used=used,innovation=False)]) for i in range(n)])
def run():
    n,h,w=48,24,32;rng=np.random.default_rng(417);desc=descriptor();phi=physical(desc,h,w)
    raw=np.full((n,h,w,3),.2);raw+=.012*phi[None,...,:1]
    controls=np.zeros((n,3));controls[0,0]=1;active=np.ones(n,bool)
    beta=np.stack([.005+.001*rng.normal(size=(n,3)),.001+.001*rng.normal(size=(n,3))],axis=1)
    D=np.einsum('hwk,nkc->nhwc',phi,beta);P=raw.copy();TP=P-D;B=np.full_like(raw,.2);diag=source_records(n,desc);descs=[desc]*n
    out,d,C=model.make_response_history(raw,P,TP,B,active,controls,diag,descs)
    # Authoritative C uses B+(P-TP), never reassociates the current control.
    original=B+(P-TP);assert C[0].tobytes()==original[0].tobytes()
    M=model.physical_projection(desc,h,w);currentbeta=np.stack([r['current_beta'] for r in d['frames']]);meanbeta=np.stack([r['mean_beta'] for r in d['frames']])
    ratio=float(np.mean(np.var(meanbeta[-16:],axis=0))/np.mean(np.var(currentbeta[-16:],axis=0)));assert ratio<.2
    raw2=raw.copy();raw2[24:]+=.08;P2=P.copy();P2[24:]+=.08;TP2=TP.copy();TP2[24:]+=.08
    changed,cd,cc=model.make_response_history(raw2,P2,TP2,B,active,controls,diag,descs)
    assert cd['frames'][24]['history_frames']==[24]
    ctrl2=controls.copy();ctrl2[20,0]=1;ctrl2[30:,1]=.25
    _,rd,_=model.make_response_history(raw,P,TP,B,active,ctrl2,diag,descs)
    assert rd['frames'][20]['history_frames']==[20] and rd['frames'][30]['history_frames']==[30]
    changedP=P.copy();changedP[32:]+=.001;changedTP=TP.copy();changedTP[32:]+=.003
    changedraw=raw.copy();changedraw[32:]+=.04
    fo,fd,fc=model.make_response_history(changedraw,changedP,changedTP,B,active,controls,diag,descs)
    assert out[:32].tobytes()==fo[:32].tobytes() and C[:32].tobytes()==fc[:32].tobytes() and d['frames'][:32]==fd['frames'][:32]
    for no in [None,descriptor(chosen=(0,2,1)),dict(frequencies=[[3.23,1.17],[3.23,1.17]],chosen=[0,1,2,3,4],groups=[[1,2],[3,4]],original_groups=[[1,2],[3,4]])]:
        nd=source_records(n,no);noout,nodiag,noC=model.make_response_history(raw,P,TP,B,active,controls,nd,[no]*n)
        T,V,_=model.dc.make_source_dc_innovation_target(raw,controls,np.zeros(n,int));control,_=model.dc.apply_target(original,B,active,T,V,True)
        assert noC.tobytes()==original.tobytes() and noout.tobytes()==control.tobytes()
    # With centered x at even width, Nyquist cos is zero and canonical sine is the real column.
    ny=descriptor((w/2,0),(0,2));nyphi=physical(ny,h,w);assert nyphi.shape[-1]==1
    nyD=.003*nyphi[None];nyD=np.broadcast_to(nyD,raw.shape).copy();nydiag=source_records(n,ny)
    _,nr,_=model.make_response_history(raw,P,P-nyD,B,active,controls,nydiag,[ny]*n)
    assert all(r['theta']==[0.] for r in nr['frames'])
    # Independent joint least squares and shared RGB coordinates.
    Y=(D[7,5:-5,5:-5]-D[7,5:-5,5:-5].mean((0,1))).reshape(-1,3)
    X=M['Phi'][5:-5,5:-5].reshape(-1,2)
    ls=np.linalg.lstsq(X,Y,rcond=None)[0];np.testing.assert_allclose(ls,currentbeta[7],rtol=0,atol=2e-16)
    # Current orthogonal coefficient remains current, with no history filtering.
    other=physical(descriptor((6.17,-2.2)),h,w)[...,0];X=M['Phi'][5:-5,5:-5].reshape(-1,2)
    coef=M['inverse']@other[5:-5,5:-5].ravel();orth=other-np.einsum('hwk,k->hw',M['Phi'],coef)
    orth=orth-orth[5:-5,5:-5].mean();add=rng.normal(0,.0003,n)[:,None,None,None]*orth[None,...,None]
    _,od,oc=model.make_response_history(raw,P,TP-add,B,active,controls,diag,descs)
    np.testing.assert_allclose(oc-C,np.broadcast_to(add,oc.shape),rtol=0,atol=2e-16)
    # Inactive frame does not feed coefficient history, exact baseline bits preserved.
    mask=active.copy();mask[:8]=False
    io,idg,ic=model.make_response_history(raw,P,TP,B,mask,controls,diag,descs)
    assert io[:8].tobytes()==B[:8].tobytes() and idg['frames'][8]['history_frames']==[8]
    # Negative/nonfinite source rejects target; signed D itself is legal.
    badraw=raw.copy();badraw[22,0,0,0]=-.001
    invalid,bd,_=model.make_response_history(badraw,P,TP,B,active,controls,diag,descs)
    assert invalid[22].tobytes()==B[22].tobytes() and bd['frames'][23]['history_frames']==[23]
    badB=B.copy();badB[0,0,0,0]=np.inf
    try:model.make_response_history(raw,P,TP,badB,active,controls,diag,descs)
    except ValueError:pass
    else:raise AssertionError('Invalid baseline was accepted')
    report=dict(status='passed_pre_score_selfchecks',model_sha256=sha(HERE/'model.py'),capture_source_sha256=sha(HERE/'capture_source.py'),
        checks=['inclusive_mean_no_new_activation','source_DC_step_cut','reset_jitter_cut','future_output_state_prefix','no_atom_unsupported_C_control_bitexact','canonical_sine_Nyquist_rank1','joint_RGB_lstsq','current_orthogonal_response_exact','inactive_exact_B_new_epoch','invalid_source_cut_signed_D','invalid_baseline_raises'],
        known_IID_static_coefficient_variance_ratio=ratio,no_native_or_truth_estimator_input=True)
    (HERE/'selfcheck_results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)
if __name__=='__main__':run()
