"""Observable response noise decomposition, offline diagnostic, no estimator.

Clean reference is accessed only for scoring. The separate clean oracle pilot
is explicitly privileged evidence, never an available source-only predictor.
"""
from pathlib import Path
import importlib.util,json
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
REFERENCE=ROOT/'tools_tmp/delta_history_offline_20260930/analyze.py'
spec=importlib.util.spec_from_file_location('reference',REFERENCE)
ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(ref)
SCENES=('material','wave','reset')


def centered(a):return a-a.mean(0,keepdims=True)


def energies(a):
    a=np.asarray(a,float);dc=a.mean((1,2));shape=a-dc[:,None,None,:]
    variance=float(np.mean(centered(a)**2));dv=float(np.mean(centered(dc)**2));sv=float(np.mean(centered(shape)**2))
    assert abs(variance-dv-sv)<1e-12
    ft=np.fft.rfft(centered(a),axis=0)
    power=np.sum(abs(ft)**2,axis=(1,2,3));power[1:-1]*=2
    bands=dict(low_1_2=float(power[1:3].sum()),higher=float(power[3:].sum()))
    total=sum(bands.values())
    return dict(total_temporal_rms=float(np.sqrt(variance)),dc_temporal_rms=float(np.sqrt(dv)),
        non_dc_temporal_rms=float(np.sqrt(sv)),dc_variance_fraction=dv/variance if variance else 0,
        dc_std_rgb=dc.std(0).tolist(),mean_rgb=dc.mean(0).tolist(),
        temporal_energy_low_1_2_fraction=bands['low_1_2']/total if total else 0)


def covariance(a,b):
    a=centered(a);b=centered(b);va=float(np.mean(a*a));vb=float(np.mean(b*b));co=float(np.mean(a*b))
    beta=co/va if va>1e-30 else 0
    return dict(variance_a=va,variance_b=vb,covariance=co,
        correlation=co/np.sqrt(va*vb) if va*vb>1e-30 else None,
        b_on_a_gain=beta,variance_b_orthogonal_to_a=max(0.,vb-beta*co))


def dc_spatial_coupling(p,tp):
    """Current pilot mean explains spatial TP variation? Descriptive, not causal."""
    x=p.mean((1,2));y=tp-tp.mean((1,2),keepdims=True)
    y=y.reshape(len(y),-1);yc=centered(y);xc=centered(x)
    total=float(np.mean(yc*yc))
    predicted=xc@np.linalg.lstsq(xc,yc,rcond=None)[0]
    explained=float(np.mean(predicted*predicted))
    age=np.linspace(-1,1,len(x))[:,None]
    timefit=age@np.linalg.lstsq(age,yc,rcond=None)[0]
    age_x=xc-age@np.linalg.lstsq(age,xc,rcond=None)[0]
    residual=yc-timefit
    extra=age_x@np.linalg.lstsq(age_x,residual,rcond=None)[0]
    residual_energy=float(np.mean(residual**2))
    # Leave-one-out fits include intercept and age. The 16-frame sample is small;
    # negative predictive R² is retained, without choosing a best predictor.
    basic=np.c_[np.ones(len(x)),age];augmented=np.c_[basic,x]
    errors={}
    for name,design in (('age',basic),('age_dc',augmented)):
        pred=np.empty_like(y)
        for i in range(len(x)):
            mask=np.arange(len(x))!=i
            pred[i]=design[i]@np.linalg.lstsq(design[mask],y[mask],rcond=None)[0]
        errors[name]=float(np.mean((y-pred)**2))
    return dict(in_sample_dc_explained_fraction=explained/total if total else 0,
        after_age_partial_dc_explained_fraction=float(np.mean(extra**2))/residual_energy if residual_energy else 0,
        explained_spatial_rms=float(np.sqrt(explained)),pilot_dc_rms=float(np.sqrt(np.mean(xc**2))),
        loo_age_prediction_mse=errors['age'],loo_age_dc_prediction_mse=errors['age_dc'],
        loo_dc_improvement_over_age=1-errors['age_dc']/errors['age'] if errors['age'] else None,
        caution='Small-window same-data projection; response history and common inputs confound causal attribution')


def spatial_spectrum(a):
    a=centered(np.asarray(a,float));h,w=a.shape[1:3]
    ft=np.fft.rfft2(a,axes=(1,2))/(h*w)
    energy=np.mean(np.mean(abs(ft)**2,axis=-1),axis=0)
    weight=np.full(energy.shape,2.);weight[:,0]=1
    if w%2==0:weight[:,-1]=1
    energy*=weight;energy[0,0]=0
    spatial=a-a.mean((1,2),keepdims=True)
    np.testing.assert_allclose(energy.sum(),np.mean(spatial**2),rtol=1e-12,atol=1e-24)
    y=np.fft.fftfreq(h)[:,None];x=np.fft.rfftfreq(w)[None,:];radius=np.sqrt(x*x+y*y)
    total=float(energy.sum());bands={}
    for name,mask in (('low_radius_le_1_16',radius<=1/16),('mid_le_1_4',(radius>1/16)&(radius<=1/4)),('high_gt_1_4',radius>1/4)):
        bands[name]=float(energy[mask].sum()/total) if total else 0
    indices=np.argsort(energy.ravel())[-8:][::-1]
    modes=[dict(ky=int(i//energy.shape[1]),kx=int(i%energy.shape[1]),variance_fraction=float(energy.ravel()[i]/total) if total else 0) for i in indices]
    return dict(non_dc_variance=total,bands=bands,top_variation_modes=modes)


def support(raw,controls,diagnostics,pilot):
    """Reconstruct frozen source-only support using recorded thresholds."""
    h,w=raw.shape[1:3];n=h*w;past=[];masks=[];innov=[];reconstruction=[]
    temporal=diagnostics['schema'].startswith('fsrd-temporal')
    for i,current_raw in enumerate(raw):
        if controls[i,0] or (i and not np.array_equal(controls[i,1:],controls[i-1,1:])):past=[]
        current=np.fft.rfft2(current_raw,axes=(0,1))/n;record=diagnostics['frames'][i]
        if temporal:
            mean=(sum(past)+current)/(len(past)+1)
            keep=np.any(abs(current)>record['coefficient_threshold'],axis=-1)|np.any(abs(mean)>record['mean_coefficient_threshold'],axis=-1)
            innovation=np.any(abs(current-sum(past)/len(past))>record['innovation_threshold'],axis=-1) if past else np.zeros(keep.shape,bool)
            innovation[0,0]=False;selected=np.where(innovation[...,None],current,mean);selected[0,0]=current[0,0]
        else:
            keep=np.any(abs(current)>record['coefficient_threshold'],axis=-1);innovation=np.zeros(keep.shape,bool);selected=current
        keep[0,0]=True;masks.append(keep);innov.append(innovation&keep)
        prediction=np.fft.irfft2(selected*keep[...,None]*n,s=(h,w),axes=(0,1)).astype(np.float16).astype(np.float32)
        reconstruction.append(float(abs(prediction-pilot[i]).max()))
        assert keep.sum()==record['retained_frequencies']
        if temporal:
            assert (innovation&keep).sum()==record['current_innovation_frequencies']
            past.append(current)
            if len(past)>=16:past.pop(0)
    masks=np.stack(masks[-16:]);innov=np.stack(innov[-16:]);retained=masks.sum((1,2));churn=np.mean(masks[1:]!=masks[:-1],axis=(1,2))
    records=diagnostics['frames'][-16:]
    return dict(retained_min=int(retained.min()),retained_max=int(retained.max()),retained_mean=float(retained.mean()),
        changing_support_fraction=float(np.mean(np.any(masks,axis=0)!=np.all(masks,axis=0))),
        adjacent_support_churn_fraction=float(churn.mean()),current_innovation_retained_mean=float(innov.sum((1,2)).mean()),
        sigma_mean=float(np.mean([r['nominal_iid_pixel_sigma'] for r in records])),
        threshold_mean=float(np.mean([r['coefficient_threshold'] for r in records])),
        mean_threshold_mean=float(np.mean([r.get('mean_coefficient_threshold',r['coefficient_threshold']) for r in records])),
        exact_fp16_pilot_reconstruction=max(reconstruction)==0,reconstruction_max_delta=max(reconstruction),
        interpretation='Changing support and spectral variation are observable; false-support classification requires unavailable truth')


def analyze_arrays(a,pilot_name='pilot'):
    p=a[pilot_name][-16:].astype(float);tp=a['pilot_response'][-16:].astype(float);b=a['baseline'][-16:].astype(float)
    observed=a['observed'][-16:].astype(float);delta=p-tp
    arrays=dict(observed=observed,pilot=p,pilot_response=tp,baseline=b,delta=delta)
    dc_cov=covariance(p.mean((1,2)),tp.mean((1,2)))
    pn=p-p.mean((1,2),keepdims=True);tn=tp-tp.mean((1,2),keepdims=True)
    non_dc_cov=covariance(pn,tn)
    candidate=b+delta
    current_dc=candidate-candidate.mean((1,2),keepdims=True)+observed.mean((1,2),keepdims=True)
    expected_delta=non_dc_cov['variance_a']+non_dc_cov['variance_b']-2*non_dc_cov['covariance']
    measured=energies(delta)['non_dc_temporal_rms']**2
    assert abs(expected_delta-measured)<1e-12
    return dict(mature_frames=16,observable_energy={k:energies(v) for k,v in arrays.items()},
        pilot_response_dc_covariance=dc_cov,pilot_response_non_dc_covariance=non_dc_cov,
        dc_to_native_spatial_coupling=dc_spatial_coupling(p,tp),
        spatial_variation_spectrum={k:spatial_spectrum(v) for k,v in arrays.items() if k!='observed'},
        score_only=dict(baseline=ref.score(b,a['clean_reference'][-16:],None),
            additive_candidate=ref.score(candidate,a['clean_reference'][-16:],None),
            current_dc_candidate=ref.score(current_dc,a['clean_reference'][-16:],None)),
        current_dc_identity_max_error=float(abs(current_dc.mean((1,2))-observed.mean((1,2))).max()))


def main():
    output=Path(__file__).with_name('results_v2.json')
    if output.exists():raise ValueError('Preserve prior diagnostic')
    report=dict(schema='observable-response-noise-attribution-offline-v2',status='running',quality_accepted=False,
        estimator_implemented=False,native_rerun=False,scenes=list(SCENES),window=16,
        script_sha256=ref.digest(__file__),metric_source_sha256=ref.digest(ref.TESTS/'probe_fsrd_statistical_resolve.py'),
        correction='v1 spatial variation variance summed RGB; v2 averages RGB, matching covariance/energy units. Fractions and conclusions unchanged.',
        limitations=['Post-hoc decomposition of previously frozen studies.',
            'Observable covariance and same-window regressions are associations, not causal interventions.',
            'Native response depends on the entire previous pilot stream; uncorrelated current residual is not independent noise.',
            'Low temporal spectrum energy can be settling or true motion; source support churn does not establish false support.',
            'Clean reference is read only in score calls; privileged clean oracle pilot is separately labeled.'],rows=[])
    for study in ref.STUDIES:
        folder=ref.EVIDENCE/study;rp=folder/'results.json';rh=ref.digest(rp);original=json.loads(rp.read_text())
        for row in original['rows']:
            if row['scene'] not in SCENES:continue
            sp=folder/row['scene']/'sequences.npz';cp=folder/row['scene']/'observed/frame_controls.txt';sh=ref.digest(sp);ch=ref.digest(cp)
            with np.load(sp) as a:
                result=analyze_arrays(a);controls=ref.controls_from_native(cp,len(a['pilot']))
                result['pilot_support']=support(a['observed'].astype(float),controls,row['pilot_diagnostics'],a['pilot'])
            unchanged=ref.digest(rp)==rh and ref.digest(sp)==sh and ref.digest(cp)==ch
            assert unchanged
            report['rows'].append(dict(study=study,scene=row['scene'],split_strength=original.get('split_strength',0),
                provenance=dict(native_report_sha256=rh,native_sequences_sha256=sh,native_controls_sha256=ch),
                source_files_unchanged=unchanged,diagnostic=result))
            print(study,row['scene'],result['observable_energy'],flush=True)
    oracle=ROOT/'tools_tmp/reassessment_oracle_primary';rp=oracle/'results.json';rh=ref.digest(rp)
    for sigma in (0.0,0.012):
        folder=oracle/('material_sigma_'+str(sigma));sp=folder/'sequences.npz';cp=folder/'observed/frame_controls.txt'
        if not sp.exists():continue
        sh=ref.digest(sp);ch=ref.digest(cp)
        with np.load(sp) as a:result=analyze_arrays(a,'oracle_pilot')
        unchanged=ref.digest(rp)==rh and ref.digest(sp)==sh and ref.digest(cp)==ch;assert unchanged
        report['rows'].append(dict(study='reassessment_oracle_primary',scene='material',sigma=sigma,
            oracle_uses_clean_truth=True,source_only_available=False,source_files_unchanged=unchanged,
            provenance=dict(native_report_sha256=rh,native_sequences_sha256=sh,native_controls_sha256=ch),diagnostic=result))
    report['status']='completed_diagnostic_not_solution'
    output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':main()
