from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
r=json.loads((HERE/'results.json').read_text())
def row(item,key):
    data=item['result']; m=data['metrics']; c=m['DC_normalized_significant64']; old=m['frozen_significant64']
    result=dict(family=item[key],activity=c['active_fraction'],invalid_fraction=c['invalid_pixel_fraction'],
        candidate_mature_STD=c['mature']['score']['residual_temporal_std'],significant_mature_STD=old['mature']['score']['residual_temporal_std'],
        mature_STD_ratio=c['mature']['STD_ratio_to_frozen_significant64'],innovation_counts=data['innovation_counts'],windows={})
    for name in ('full','mature','startup_first8'):
        win=c[name]; result['windows'][name]=dict(RMSE=win['score']['rmse'],STD=win['score']['residual_temporal_std'],
            absolute_gain_min=win['absolute_gain_min'],absolute_gain_max=win['absolute_gain_max'],absolute_phase_max=win['absolute_phase_max'],
            absolute_gain_failing_frames=win['absolute_gain_failing_frames'],absolute_phase_failing_frames=win['absolute_phase_failing_frames'],
            absolute_detail_pass=win['per_frame_absolute_detail_pass'],RGB_bias=win['score']['bias_rgb'],
            relative_gate_vs_significant=win.get('source_only_relative_gate_against_frozen_significant64'),
            relative_gate_vs_hard=win.get('source_only_relative_gate_against_frozen_hard64'))
    return result
out=dict(schema='DC-normalized-source-feasibility-compact-v1',source_result_sha256=sha(HERE/'results.json'),
    freeze=r['pre_score_freeze'],selfchecks=r['selfchecks'],quality_accepted=False,native_measured=False,
    source_family_count=len(r['rows']),adversary_count=len(r['counterexamples']),rows=[row(q,'scene') for q in r['rows']],counterexamples=[row(q,'family') for q in r['counterexamples']],
    scope='CPU source only; normalized-source estimator never consumes truth, guides or prior native pilot response',
    qualifications=['Relative gate/effective is against another source pilot with null0; no native acceptance',
        'Frozen analyzer uses full sequence activity for both full and mature relative gates, as prior source benchmark did; absolute per-frame detail independent of this activity',
        'Mature frame indices in metric lists are local0..15; full frame indices0..63',
        'Hard64 vs significant differences include currentORmean-support vs selected-support; significant is closest control',
        'Source nominal IID covariance, random ratios and estimated phase uncertainty are assumptions, not confidence',
        'DC normalization did not improve static material/wave noise floor; shared bias remains unidentifiable'])
if (HERE/'compact_report.json').exists():raise ValueError('Preserve report')
(HERE/'compact_report.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
print('result',out['source_result_sha256']);print('compact',sha(HERE/'compact_report.json'))
for group in ('rows','counterexamples'):
    for q in out[group]:
        f=q['windows']['full'];ma=q['windows']['mature']
        print(q['family'], 'STD_ratio',q['mature_STD_ratio'], 'full_abs',f['absolute_gain_min'],f['absolute_gain_max'],f['absolute_phase_max'],
            'full_gate',f['relative_gate_vs_significant'],'mature_gate',ma['relative_gate_vs_significant'])
