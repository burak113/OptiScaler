"""Compact immutable-study summary, not additional estimator selection."""
from pathlib import Path
import hashlib,json
import numpy as np

folder=Path(__file__).resolve().parent
source=folder/'results.json'
report=json.loads(source.read_text())
safe_names=[n for n in report['rows'][0]['variants'] if n.endswith('_safe')]
summary=dict(schema='normalized-response-transfer-offline-summary-v1',quality_accepted=False,
    results_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),script_sha256=report['script_sha256'],
    self_checks=report['self_checks'],source_files_unchanged=all(r['source_files_unchanged'] for r in report['rows']),
    counts={},rows=[])
for study in dict.fromkeys(r['study'] for r in report['rows']):
    selected=[r for r in report['rows'] if r['study']==study]
    summary['counts'][study]={n:dict(total=len(selected),
        full=sum(r['variants'][n]['full_gate']['effective_success'] for r in selected),
        mature=sum(r['variants'][n]['mature_gate']['effective_success'] for r in selected),
        both=sum(r['variants'][n]['full_gate']['effective_success'] and r['variants'][n]['mature_gate']['effective_success'] for r in selected))
        for n in safe_names}
for row in report['rows']:
    variants={}
    for name,v in row['variants'].items():
        values={}
        for window in ('full','mature'):
            m=v[window];phase=[p for p in m['phase_error_radians'] if p is not None]
            gain=[g for g in m['contrast_gain'] if g is not None]
            values[window]=dict(rmse=m['rmse'],residual_temporal_std=m['residual_temporal_std'],bias_rgb=m['bias_rgb'],
                broad_tone_rms=m['broad_tone_rms'],ring_width=m['ring_width'],gain_mean=float(np.mean(gain)) if gain else None,
                gain_min=min(gain) if gain else None,gain_max=max(gain) if gain else None,phase_max=max(phase) if phase else None,
                gate=v[window+'_gate'])
        variants[name]=dict(**values,activity=v['activity'],invalid_pixel_fraction=v['invalid_pixel_fraction'],
            denominator_guard_pixel_fraction=v['denominator_guard_pixel_fraction'],radiance_fallback_pixel_fraction=v['baseline_fallback_pixel_fraction'],
            contour_gate=v['contour']['gate'] if v['contour'] else None)
    summary['rows'].append(dict(study=row['study'],scene=row['scene'],provenance=row['provenance'],
        baseline_std_mature=row['baseline_mature']['residual_temporal_std'],variants=variants))
output=folder/'summary.json'
if output.exists():raise ValueError('Preserve prior summary')
output.write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
print(json.dumps(summary['counts'],indent=2))
print('SOURCE_UNCHANGED',summary['source_files_unchanged'],'RESULT_SHA',summary['results_sha256'],'SCRIPT_SHA',summary['script_sha256'])
