"""Compact source-only feasibility and counterexample evidence."""
from pathlib import Path
import hashlib,json

folder=Path(__file__).resolve().parent
source=folder/'results.json';counter=folder/'adversaries.json'
r=json.loads(source.read_text());a=json.loads(counter.read_text())
report=dict(schema='factorized-source-pilot-summary-v1',quality_accepted=False,native_measured=False,
    results_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),adversaries_sha256=hashlib.sha256(counter.read_bytes()).hexdigest(),
    prototype_sha256=r['prototype_sha256'],self_checks=r['self_checks'],
    authenticated_all_rows=all(x['source_files_unchanged'] and x['authenticated_observed_truth_controls_exact_match'] for x in r['rows']),rows=[],counterexamples=[])
def compact(metrics):
    out={}
    for name,v in metrics.items():
        windows={}
        for window in ('full','mature'):
            m=v[window];s=m['score']
            windows[window]=dict(rmse=s['rmse'],residual_temporal_std=s['residual_temporal_std'],bias_rgb=s['bias_rgb'],
                broad_tone_rms=s['broad_tone_rms'],gain_min=m['absolute_gain_min'],gain_mean=m['absolute_gain_mean'],
                gain_max=m['absolute_gain_max'],phase_max=m['absolute_phase_max'],detail_within_5_percent_all_frames=m['detail_within_5_percent_all_frames'])
        out[name]=dict(active_fraction=v['active_fraction'],**windows)
    return out
for x in r['rows']:
    report['rows'].append(dict(scene=x['scene'],provenance=x['provenance'],regenerated_guide_rgb_sha256=x['regenerated_guide_rgb_sha256'],
        metrics=compact(x['metrics'])))
for x in a['rows']:report['counterexamples'].append(dict(family=x['family'],metrics=compact(x['metrics'])))
path=folder/'summary.json'
if path.exists():raise ValueError('Preserve previous summary')
path.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
print(report['results_sha256'],report['adversaries_sha256'],report['prototype_sha256'])
