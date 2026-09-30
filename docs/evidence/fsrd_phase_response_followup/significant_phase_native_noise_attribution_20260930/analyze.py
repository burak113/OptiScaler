"""Posthoc exact temporal variance identities; no estimator or GPU work."""
from pathlib import Path
import hashlib, importlib.util, json
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'tools_tmp/native_significant_phase_initial_20260930/evidence'
PRIOR = ROOT/'tools_tmp/response_noise_attribution_20260930/analyze.py'
spec = importlib.util.spec_from_file_location('prior_attribution', PRIOR)
prior = importlib.util.module_from_spec(spec); spec.loader.exec_module(prior)

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def identity(a, b, sign=1):
    ac=prior.centered(np.asarray(a,float)); bc=prior.centered(np.asarray(b,float))
    va=float(np.mean(ac**2)); vb=float(np.mean(bc**2)); cov=float(np.mean(ac*bc))
    measured=float(np.mean((ac+sign*bc)**2)); predicted=va+vb+2*sign*cov
    np.testing.assert_allclose(measured,predicted,rtol=1e-12,atol=1e-22)
    return dict(variance_a=va,variance_b=vb,covariance=cov,measured_variance=measured,
                predicted_variance=predicted,identity_absolute_error=abs(measured-predicted),
                correlation=cov/np.sqrt(va*vb) if va*vb>0 else None)

def main():
    dest=Path(__file__).with_name('results.json')
    if dest.exists(): raise ValueError('Preserve previous evidence')
    rp=SOURCE/'results.json'; rh=sha(rp); source=json.loads(rp.read_text())
    assert source['status']=='completed_research_not_solution' and source['amd_completed_sequences']==18
    report=dict(schema='significant-phase-native-noise-attribution-v1',status='running',
        script_sha256=sha(__file__),reference_sha256=sha(PRIOR),source_report_sha256=rh,
        quality_accepted=False,native_rerun=False,estimator_implemented=False,rows=[],
        limitations=['Posthoc association on six frozen synthetic cases; not a causal intervention.',
          'No raw GPU converter or composition payload retained in this native package.',
          'Temporal RMS is sqrt(mean variance); existing gate reports mean(pixel STD). These are different units.',
          'Clean reference enters residual scoring/decomposition only; no estimator is defined.',
          'Native response variation includes settling and source history; orthogonality is not independence.'])
    for row in source['rows']:
        pth=SOURCE/row['scene']/'sequences.npz'; sh=sha(pth)
        with np.load(pth) as a:
            p=a['pilot'].astype(float); tp=a['pilot_response'].astype(float)
            b=a['baseline'].astype(float); truth=a['clean_reference'].astype(float)
            active=a['active'].astype(float)[:,None,None,None]
            d=active*(p-tp); c=a['significant_phase'].astype(float)
            np.testing.assert_allclose(c,b+d,rtol=0,atol=1e-8)
            windows={}
            for label,sl in [('full',slice(None)),('mature',slice(-16,None)),('early8',slice(0,8))]:
                ps=p[sl,5:-5,5:-5]; ts=tp[sl,5:-5,5:-5]; bs=b[sl,5:-5,5:-5]
                ds=d[sl,5:-5,5:-5]; es=bs-truth[sl,5:-5,5:-5]
                pshape=ps-ps.mean((1,2),keepdims=True); tshape=ts-ts.mean((1,2),keepdims=True)
                windows[label]=dict(pilot_response_difference=identity(ps,ts,-1),
                    non_dc_difference=identity(pshape,tshape,-1),baseline_residual_plus_correction=identity(es,ds),
                    energies={name:prior.energies(v) for name,v in [('pilot',ps),('native_pilot_response',ts),('correction',ds),('baseline_residual',es)]},
                    dc_to_spatial_response_association=prior.dc_spatial_coupling(ps,ts),
                    score_mean_pixel_std_baseline=float(np.std(es,axis=0).mean()),
                    score_mean_pixel_std_candidate=float(np.std(es+ds,axis=0).mean()))
            report['rows'].append(dict(scene=row['scene'],sequences_sha256=sh,source_files_unchanged=sha(pth)==sh,
                null_rms=row['null_rms'],windows=windows))
            m=windows['mature']; print(row['scene'],dict(std_baseline=m['score_mean_pixel_std_baseline'],
                std_candidate=m['score_mean_pixel_std_candidate'],correction_non_dc_rms=m['energies']['correction']['non_dc_temporal_rms'],
                dc_fraction=m['energies']['correction']['dc_variance_fraction'],
                p_tp_correlation=m['non_dc_difference']['correlation']),flush=True)
    assert sha(rp)==rh
    report['status']='completed_diagnostic_not_solution'
    dest.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')

if __name__=='__main__':main()
