"""Separate analytic operators; not original24 controls or SDK surrogates."""
import numpy as np
from model import source_mean,mirror,antithetic,domain
def run():
    rng=np.random.default_rng(417081);O=.3+rng.normal(0,.01,(32,8,10,3));controls=np.zeros((32,3));controls[0,0]=1
    P,active,diag=source_mean(O,controls);M=mirror(O,P)
    checks=[]
    E=antithetic(P,O,M);err=float(abs(E-O).max());assert err<2e-16
    checks.append(dict(name='identity_T_E_equals_O_no_noise_benefit',max_error=err,output_is_O_roundoff_only=True))
    a=np.array([.4,1.3,-.5]);b=np.array([.2,-.1,.03]);E=antithetic(P,a*O+b,a*M+b);expected=P+a*(O-P);err=float(abs(E-expected).max());assert err<3e-16
    checks.append(dict(name='explicit_affine_T_cancels_offset_retains_odd_response',max_error=err,negative_slope_math_only=True))
    Q=antithetic(P,O*O,M*M);expected=P+2*P*(O-P);err=float(abs(Q-expected).max());assert err<3e-16
    checks.append(dict(name='explicit_quadratic_only_even_about_estimated_P',max_error=err,no_quality_claim=True))
    assert P[:8].tobytes()==O[:8].tobytes()and not active[:8].any()and active[8:].all()
    assert np.allclose(P[8],O[:9].mean(0),atol=0,rtol=0)
    changed=O.copy();changed[17:]*=2;PP,aa,dd=source_mean(changed,controls)
    assert PP[:17].tobytes()==P[:17].tobytes()and dd['frames'][:17]==diag['frames'][:17]
    cc=controls.copy();cc[16,0]=1;RP,ra,rd=source_mean(O,cc);assert RP[16:24].tobytes()==O[16:24].tobytes()and not ra[16:24].any()
    suffix,sa,sd=source_mean(O[16:],cc[16:]);assert RP[16:].tobytes()==suffix.tobytes()and np.array_equal(ra[16:],sa)
    jj=controls.copy();jj[16:,1:]=[.25,.125];JP,ja,jd=source_mean(O,jj);assert JP[16:24].tobytes()==O[16:24].tobytes()
    ex=np.ones(32);ex[16:]=2;EP,ea,ed=source_mean(O,controls,ex);assert EP[16:24].tobytes()==O[16:24].tobytes()
    bad=O.copy();bad[10,0,0,0]=np.nan;bad[11,0,0,1]=np.inf;BP,ba,bd=source_mean(bad,controls);assert BP[10:12].tobytes()==bad[10:12].tobytes()and not ba[10:12].any()
    bc=controls.copy();bc[10,1]=np.nan;CP,ca,cd=source_mean(O,bc);assert CP[10].tobytes()==O[10].tobytes()and not ca[10]
    burst=np.full((32,8,10,3),.01);burst[20]=1;SP,_,_=source_mean(burst,controls);SM=mirror(burst,SP);d=domain(SM);assert d['negative_finite_channel_elements']==240 and not d['native_radiance_domain_met']
    checks.extend([dict(name='current_inclusive_first8_warmup_history_fed',passed=True),dict(name='future_source_prefix_output_and_state_equal',passed=True),dict(name='reset_suffix_and_jitter_exposure_cut',passed=True),dict(name='invalid_source_nan_inf_bits_and_metadata_exact_raw_clear',passed=True),dict(name='mirror_negative_burst_no_clip_domain_unmet',domain=d)])
    return dict(status='PASSED_SEPARATE_CPU_ALGEBRA_AND_CAUSAL_DOMAIN_SELFCHECKS',checks=checks,actual_GPU_native_build_scores=0,quality_accepted=False)
