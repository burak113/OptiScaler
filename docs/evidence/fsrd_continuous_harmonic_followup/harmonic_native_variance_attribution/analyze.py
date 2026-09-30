"""Exact saved-array variance identities; no estimator or native rerun."""
from pathlib import Path
import hashlib,json
import numpy as np

ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha');HERE=Path(__file__).resolve().parent
FIRST=ROOT/'tools_tmp/native_continuous_harmonic_fresh_retry_20260930/evidence'
REST=ROOT/'tools_tmp/native_continuous_harmonic_remaining_20260930/evidence'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def temporal(a):return a-a.mean(axis=0,keepdims=True)
def covariance(components):
    x=np.stack([temporal(a) for a in components])
    matrix=np.einsum('itxyc,jtxyc->ij',x,x,optimize=True)/np.prod(x.shape[1:])
    total=temporal(sum(components));actual=float(np.mean(total**2))
    error=abs(actual-float(matrix.sum()))
    assert error<1e-16
    return {'names':['baseline_error','actual_pilot_correction','actual_current_DC_constraint','actual_RGB_fallback'],
        'temporal_covariance_matrix':matrix.tolist(),'total_temporal_variance':actual,
        'covariance_sum_identity_error':error}
def STD(a):return float(np.std(a,axis=0).mean())

def main():
    initial_path=FIRST/'results.json';rest_path=REST/'results.json'
    initial=json.loads(initial_path.read_text());remaining=json.loads(rest_path.read_text())
    assert initial['status']=='failed_preserved' and initial['error']=="'absolute_detail_pass'"
    assert initial['completed_native_contexts']==3 and len(initial['rows'])==1
    assert remaining['status']=='completed_native_diagnostic_not_solution'
    assert remaining['completed_native_contexts']==15 and len(remaining['rows'])==5
    reports=[(FIRST,row) for row in initial['rows']]+[(REST,row) for row in remaining['rows']]
    pins={str(initial_path):sha(initial_path),str(rest_path):sha(rest_path)}
    results={'schema':'harmonic-native-saved-array-variance-attribution-v1','status':'running',
        'quality_accepted':False,'native_rerun':False,'new_pilot_created':False,'source_pins':pins,
        'fixed_selected_candidate':'harmonic_dc_current_safe','rows':[],
        'limitations':['Temporal residual variance contains deterministic appearance error as well as noise',
            'Covariance terms are descriptive identities, not isolated intervention causes',
            'Mean pixel STD differs from square root of mean temporal variance',
            'Actual recorded correction/DC/fallback differences include FP32 rounding',
            'Truth used only to decompose scored residual, never estimator input or tuning']}
    for folder,row in reports:
        path=folder/row['scene']/'sequences.npz';pins[str(path)]=sha(path)
        assert pins[str(path)]==row['sequences_sha256']
        with np.load(path) as saved:
            a={k:saved[k].astype(float) for k in ('observed','pilot','pilot_response','baseline','clean_reference',
                'harmonic','harmonic_dc','harmonic_dc_current','harmonic_safe','harmonic_dc_safe','harmonic_dc_current_safe')}
            active=saved['active'].copy()
        observed=a['observed'];p=a['pilot'];tp=a['pilot_response'];b=a['baseline'];truth=a['clean_reference']
        d=a['harmonic']-b;k=a['harmonic_dc_current']-a['harmonic'];fallback=a['harmonic_dc_current_safe']-a['harmonic_dc_current']
        components=[b-truth,d,k,fallback]
        np.testing.assert_allclose(sum(components),a['harmonic_dc_current_safe']-truth,rtol=0,atol=2e-16)
        exactD=active[:,None,None,None]*(p-tp)
        rounding=float(np.max(abs(d-exactD)))
        windows={}
        for name,sl in [('full',slice(None)),('mature',slice(-16,None))]:
            roi=[v[sl,5:-5,5:-5] for v in components]
            dc=[v.mean((1,2),keepdims=True) for v in roi]
            nonDC=[v-v.mean((1,2),keepdims=True) for v in roi]
            total=covariance(roi);dc_record=covariance(dc);nonDC_record=covariance(nonDC)
            assert abs(total['total_temporal_variance']-dc_record['total_temporal_variance']-nonDC_record['total_temporal_variance'])<1e-16
            pp=(active[:,None,None,None]*(p-truth))[sl,5:-5,5:-5]
            tt=(active[:,None,None,None]*(tp-truth))[sl,5:-5,5:-5]
            xp=temporal(pp);xt=temporal(tt)
            vp=float(np.mean(xp*xp));vt=float(np.mean(xt*xt));cov=float(np.mean(xp*xt));vd=float(np.mean((xp-xt)**2))
            assert abs(vd-vp-vt+2*cov)<1e-16
            variants={}
            for variant in ('harmonic','harmonic_dc','harmonic_dc_current','harmonic_safe','harmonic_dc_safe','harmonic_dc_current_safe'):
                error=(a[variant]-truth)[sl,5:-5,5:-5]
                std=STD(error);native_std=row['variants'][variant]['metrics'][name]['score']['residual_temporal_std']
                assert abs(std-native_std)<2e-8
                variants[variant]={'mean_pixel_temporal_STD_float64':std,'reported_mean_pixel_temporal_STD_float32':native_std,
                    'ratio_to_baseline':std/STD(roi[0]),'reported_absolute_gain_min':row['variants'][variant]['metrics'][name]['absolute_gain_min'],
                    'reported_absolute_gain_max':row['variants'][variant]['metrics'][name]['absolute_gain_max'],
                    'reported_absolute_phase_max':row['variants'][variant]['metrics'][name]['absolute_phase_max']}
            windows[name]={'total':total,'spatial_DC':dc_record,'spatial_nonDC':nonDC_record,
                'baseline_mean_pixel_temporal_STD':STD(roi[0]),'selected_mean_pixel_temporal_STD':STD(sum(roi)),
                'ideal_active_P_minus_TP':{'pilot_error_temporal_variance':vp,'response_error_temporal_variance':vt,
                    'pilot_response_error_covariance':cov,'correction_temporal_variance':vd},'all_registered_variants':variants}
        results['rows'].append({'scene':row['scene'],'ideal_to_actual_FP32_correction_max_difference':rounding,
            'fallback_max_magnitude':float(np.max(abs(fallback))),'windows':windows})
    assert all(sha(Path(p))==digest for p,digest in pins.items())
    results['status']='completed_descriptive_variance_identity_not_solution'
    results['script_sha256']=sha(Path(__file__))
    (HERE/'results.json').write_text(json.dumps(results,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':results['status'],'rows':len(results['rows']),
        'result_sha256':sha(HERE/'results.json')},indent=2))

if __name__=='__main__':main()
