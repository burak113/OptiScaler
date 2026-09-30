"""Compact diagnostic numbers in matched variance units; no estimator."""
from pathlib import Path
import hashlib,json
import numpy as np

folder=Path(__file__).resolve().parent;p=folder/'results_v2.json';r=json.loads(p.read_text())
summary=dict(schema='response-noise-diagnostic-summary-v2',quality_accepted=False,
    results_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),analysis_sha256=r['script_sha256'],
    source_files_unchanged=all(x['source_files_unchanged'] for x in r['rows']),rows=[])
for row in r['rows']:
    d=row['diagnostic'];e=d['observable_energy'];s=d.get('pilot_support');cov=d['pilot_response_non_dc_covariance']
    entry=dict(study=row['study'],scene=row['scene'],sigma=row.get('sigma'),
        oracle_uses_clean_truth=row.get('oracle_uses_clean_truth',False),provenance=row['provenance'],
        energies=e,pilot_response_dc_covariance=d['pilot_response_dc_covariance'],
        pilot_response_non_dc_covariance=cov,dc_spatial_coupling=d['dc_to_native_spatial_coupling'],
        pilot_support=s,pilot_variation_bands=d['spatial_variation_spectrum']['pilot']['bands'],
        mean_conservation_error=d['current_dc_identity_max_error'],
        scored_baseline_temporal_std=d['score_only']['baseline']['residual_temporal_std'],
        scored_current_dc_temporal_std=d['score_only']['current_dc_candidate']['residual_temporal_std'],
        pilot_non_dc_variance_over_delta=cov['variance_a']/e['delta']['non_dc_temporal_rms']**2 if e['delta']['non_dc_temporal_rms'] else None)
    if s:
        n=6144 if row['study']!='response_temporal_spectral_alpha_holdout' else 10240
        history=1 if row['study']=='response_spectral_primary' else 16
        nominal=s['sigma_mean']/np.sqrt(history)*np.sqrt(2*(s['retained_mean']-1)/n)
        entry['nominal_iid_retained_mode_noise_rms']=float(nominal)
        entry['pilot_measured_over_nominal_mode_noise']=e['pilot']['non_dc_temporal_rms']/nominal
        entry['nominal_warning']='Approximate fixed-support iid mean-noise scale, not a bound; selection, edge weights and covariance violate calibration; reset warmup has fewer samples.'
    summary['rows'].append(entry)
out=folder/'summary.json'
if out.exists():raise ValueError('Preserve summary')
out.write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
print('SHA',summary['results_sha256'],summary['analysis_sha256'])
for x in summary['rows']:
    print(x['study'],x['scene'],x['sigma'],'NOMINAL',x.get('nominal_iid_retained_mode_noise_rms'),
        'RATIO',x.get('pilot_measured_over_nominal_mode_noise'),'P_VAR_OVER_DELTA',x['pilot_non_dc_variance_over_delta'])
