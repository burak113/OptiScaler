"""Explicit observable operators; their clean reference is scorer-only."""
import numpy as np
from selfchecks import descriptor,physical,source_records
def cases():
    n,h,w=64,32,48;rng=np.random.default_rng(628013);ctrl=np.zeros((n,3));ctrl[0,0]=1;active=np.ones(n,bool);active[:8]=False
    desc=descriptor((4.23,2.17));phi=physical(desc,h,w);phase=np.arange(n)*.12
    commonnoise=rng.normal(0,.001,(n,2,3));truth_static=np.broadcast_to(.2+.012*phi[None,...,:1],(n,h,w,3)).copy()
    def produce(name,source,truth,cleanD,observedD,theta=0.,used=False,controls=None,metadata=None,exposure=None,desc_override=desc,validB=True):
        P=source.copy();TP=P-observedD;B=truth-cleanD
        diag=source_records(n,desc_override,theta,used) if metadata is None else metadata
        return dict(name=name,raw=source,P=P,TP=TP,B=B,active=active.copy(),controls=ctrl.copy() if controls is None else controls,
            diag=diag,descriptors=[desc_override]*n,exposure=exposure,truth=truth,label='known_constructed_operator_only_no_native_coverage',validB=validB)
    shape=(n,h,w,3);zero=np.zeros(shape);staticD=np.broadcast_to(.004*phi[None,...,:1],shape).copy()
    noisyD=staticD+np.einsum('hwk,nkc->nhwc',phi,commonnoise)
    yield produce('static_offgrid_atom_with_coefficient_noise',truth_static,truth_static,staticD,noisyD)
    weak=np.broadcast_to(.2+.0008*phi[None,...,:1],shape).copy();weakD=np.broadcast_to(.0004*phi[None,...,:1],shape).copy()
    yield produce('weak_detail_startup_and_real_coefficient',weak,weak,weakD,weakD+np.einsum('hwk,nkc->nhwc',phi,commonnoise*.1))
    moving=np.stack([.2+2*np.real(.006*np.exp(1j*t))*phi[...,0]-2*np.imag(.006*np.exp(1j*t))*phi[...,1] for t in phase]);moving=np.repeat(moving[...,None],3,-1)
    movingD=np.stack([2*np.real(.002*np.exp(1j*t))*phi[...,0]-2*np.imag(.002*np.exp(1j*t))*phi[...,1] for t in phase]);movingD=np.repeat(movingD[...,None],3,-1)
    yield produce('shared_constant_speed_source_response_phase',moving,moving,movingD,movingD+np.einsum('hwk,nkc->nhwc',phi,commonnoise),.12,True)
    amplitude=np.linspace(1.,1.5,n)[:,None,None,None]*np.array([1.,.7,1.3]);chromaticD=movingD*amplitude
    yield produce('moving_phase_slow_RGB_response_amplitude',moving,moving,chromaticD,chromaticD,.12,True)
    ramp=(.003+.0001*np.arange(n))[:,None,None,None]*phi[None,...,:1];ramp=np.broadcast_to(ramp,shape).copy()
    yield produce('static_source_true_D_ramp_unobservable',truth_static,truth_static,ramp,ramp)
    yield produce('moving_source_static_guide_fixed_response',moving,moving,staticD,staticD,.12,True)
    step=truth_static.copy();step[32:]*=np.array([1.4,1.2,1.6]);Dstep=staticD.copy();Dstep[32:]*=np.array([1.4,1.2,1.6])
    yield produce('chromatic_illumination_step',step,step,Dstep,Dstep)
    drift=truth_static.copy();drift*=1+.0003*np.arange(n)[:,None,None,None];Dd=staticD*(1+.001*np.arange(n)[:,None,None,None])
    yield produce('subthreshold_illumination_drift',drift,drift,Dd,Dd)
    acc=.0015*np.arange(n)**2
    src=np.stack([.2+.012*(np.cos(t)*phi[...,0]-np.sin(t)*phi[...,1]) for t in acc]);src=np.repeat(src[...,None],3,-1)
    Da=(src-.2)/3;ad=source_records(n,desc,.0,False)
    for i,r in enumerate(ad['frames']):r['atom_diagnostics'][0].update(phase_used=i>=16,phase_increment=0. if i<16 else .003*(i-8))
    yield produce('acceleration_past_phase_model_lag',src,src,Da,Da,metadata=ad)
    disco=truth_static.copy();disco[32:]=.2-.012*phi[...,0][None,...,None];Ds=staticD.copy();Ds[32:]=-staticD[32:]
    sd=source_records(n,desc);sd['frames'][32]['atom_diagnostics'][0]['innovation']=True
    yield produce('source_disocclusion_innovation_cut',disco,disco,Ds,Ds,metadata=sd)
    md=source_records(n,desc)
    for i in range(32,n):md['frames'][i]['atom_diagnostics'][0].update(phase_used=True,phase_increment=.08)
    yield produce('phase_qualification_toggle_cut',truth_static,truth_static,staticD,noisyD,metadata=md)
    c=ctrl.copy();c[20,0]=1;c[40:,1:]=[.25,.125];ex=np.ones(n);ex[56:]=2
    yield produce('reset_jitter_exposure_cut',truth_static,truth_static,staticD,noisyD,controls=c,exposure=ex)
    rgb=np.repeat(commonnoise[...,:1],3,-1)
    yield produce('RGB_common_response_noise',truth_static,truth_static,staticD,staticD+np.einsum('hwk,nkc->nhwc',phi,rgb))
    yield produce('colored_RGB_response_noise',truth_static,truth_static,staticD,staticD+np.einsum('hwk,nkc->nhwc',phi,commonnoise*np.array([.5,1.,2.])))
    ar=commonnoise.copy()
    for i in range(1,n):ar[i]=.8*ar[i-1]+.6*commonnoise[i]
    yield produce('temporal_AR_response_noise',truth_static,truth_static,staticD,staticD+np.einsum('hwk,nkc->nhwc',phi,ar))
    yield produce('persistent_shared_D_bias',truth_static,truth_static,staticD,staticD+.002*phi[None,...,:1])
    # Current D noise exactly cancels baseline error: smoothing destroys the cancellation.
    cancellation=produce('endogenous_B_D_exact_cancellation',truth_static,truth_static,noisyD,noisyD)
    yield cancellation
    other=physical(descriptor((9.17,-3.2)),h,w)[...,0];orth=other-phi@(np.linalg.lstsq(phi[5:-5,5:-5].reshape(-1,2),other[5:-5,5:-5].ravel(),rcond=None)[0]);orth-=orth[5:-5,5:-5].mean()
    dense=staticD+rng.normal(0,.001,n)[:,None,None,None]*orth[None,...,None]
    yield produce('instantaneous_orthogonal_dense_response',truth_static,truth_static,dense,dense)
    yield produce('no_atom_dense_current_response',truth_static,truth_static,dense,dense,desc_override=None)
    ny=descriptor((w/2,0),(0,2));nyphi=physical(ny,h,w)[...,0];ns=np.broadcast_to(.2+.008*nyphi[None,...,None],shape).copy();nD=np.broadcast_to(.003*nyphi[None,...,None],shape).copy()
    yield produce('canonical_Nyquist_real_coefficient',ns,ns,nD,nD+rng.normal(0,.001,n)[:,None,None,None]*nyphi[None,...,None],desc_override=ny)
    signedD=noisyD.copy();signedD[25,0,0]=-.3
    signed=produce('signed_D_invalid_TP_or_output',truth_static,truth_static,staticD,signedD);yield signed
    near=truth_static.copy();near[28,...,0]=1e-5
    yield produce('nearzero_source_exact_B_cut',near,truth_static,staticD,staticD)
    invalid=produce('invalid_metadata_cut',truth_static,truth_static,staticD,noisyD);invalid['controls'][30,1]=np.nan;yield invalid
    close=dict(frequencies=[[4.23,2.17],[4.23,2.17]],chosen=[0,1,2,3,4],groups=[[1,2],[3,4]],original_groups=[[1,2],[3,4]])
    jd=source_records(n,desc)
    for r in jd['frames']:r['atom_frequencies']=close['frequencies'];r['atom_diagnostics']*=2
    yield produce('joint_rank_loss_unsupported_current_C',truth_static,truth_static,staticD,noisyD,metadata=jd,desc_override=close)
