"""Reporting only; no estimator/threshold changes."""
from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
r=json.loads((HERE/'results.json').read_text())
def compact(q,key):
    z=q['result'];m=z['metrics'];c=m['continuous_harmonic64'];d=z['diagnostics']
    result=dict(family=q[key],candidate_active_fraction=c['active_fraction'],candidate_invalid_pixel_fraction=c['invalid_pixel_fraction'],
        candidate_invalid_fraction_before_FP16=c['invalid_pixel_fraction_before_FP16'],CPU_wall_seconds=z['CPU_wall_seconds'],
        mask_sha256=d['mask_sha256'],source_sha256=z['source_sha256'],controls_array_sha256=z['controls_array_sha256'],
        counts=d['total_counts'],raw_fallback_frames=z['unsupported_raw_fallback_frames_exact'],
        selection_events=[dict(frame=f['frame'],epoch_start=f['epoch_start'],selection=f['selection'],frequencies=f['atom_frequencies']) for f in d['frames'] if f['selection'] is not None],
        fallback_reasons=[dict(frame=f['frame'],reason=f['reason']) for f in d['frames'] if f['raw_passthrough']],windows={})
    for window in ('full','mature','startup_first8','activation8to16'):
        win=c[window]
        if win.get('unscorable_nonfinite'):result['windows'][window]=win;continue
        score=win['score'];entry=dict(RMSE=score['rmse'],STD=score['residual_temporal_std'],broad_tone_RMS=score['broad_tone_rms'],bias_RGB=score['bias_rgb'],
            ring_width=score['ring_width'],absolute_gain_min=win['absolute_gain_min'],absolute_gain_max=win['absolute_gain_max'],absolute_phase_max=win['absolute_phase_max'],
            absolute_gain_failing_frames=win['absolute_gain_failing_frames'],absolute_phase_failing_frames=win['absolute_phase_failing_frames'],
            absolute_detail_pass=win['per_frame_absolute_detail_pass'])
        for name in ('raw_source','frozen_hard64','frozen_significant64'):
            if name not in m:continue
            old=m[name][window]
            if old.get('unscorable_nonfinite'):continue
            old_std=old['score']['residual_temporal_std'];entry['STD_ratio_to_'+name]=score['residual_temporal_std']/old_std if old_std else None
            entry['strict_noise_no_regression_vs_'+name]=score['residual_temporal_std']<=old_std
            if window in ('full','mature') and name!='raw_source':entry['relative_gate_vs_'+name]=win['source_only_relative_gate_against_'+name]
        result['windows'][window]=entry
    return result
rows=[compact(q,'scene') for q in r['rows']];adversaries=[compact(q,'family') for q in r['counterexamples']]
def counts(items):
    out={}
    for w in ('full','mature'):
        withgate=[q for q in items if 'relative_gate_vs_frozen_significant64' in q['windows'][w]]
        out[w]=dict(compared_count=len(withgate),relative_nonregression_count=sum(q['windows'][w]['relative_gate_vs_frozen_significant64']['nonregression'] for q in withgate),
            effective_count=sum(q['windows'][w]['relative_gate_vs_frozen_significant64']['effective_success'] for q in withgate),
            absolute_detail_pass_count=sum(q['windows'][w].get('absolute_detail_pass',False) for q in items),
            strict_noise_no_regression_count=sum(q['windows'][w].get('strict_noise_no_regression_vs_frozen_significant64',False) for q in withgate))
    out['effective_both']=sum(all(q['windows'][w].get('relative_gate_vs_frozen_significant64',{}).get('effective_success',False) for w in ('full','mature')) for q in items)
    return out
out=dict(schema='continuous-harmonic-CPU-compact-v2',status='completed_source_feasibility_not_solution',quality_accepted=False,native_measured=False,
    result_sha256=sha(HERE/'results.json'),pre_score_freeze=r['pre_score_freeze'],selfchecks=r['selfchecks'],family_counts=counts(rows),adversary_counts=counts(adversaries),
    rows=rows,counterexamples=adversaries,limitations=['CPU source only; source-score relative gates are not native counterfactual quality',
    'First8 raw inactive and later atom/residual activation are explicit fullsequence failure sources',
    'Absolute everyframe gain and dominant targetFFT phase plus waveform RMSE are reported; these do not separately resolve every dense/close physical component',
    'Conditional fixed-frequency linear SE excludes selected/random frequency uncertainty, colored/shared covariance, carrier/projection and heldout reuse',
    'Shared source bias remains unidentifiable and must remain a failing quality case',
    'Actual invalid source may FP16-round into finite range; both precast and FP16 validity recorded and rawfallback bitidentity preserved',
    'No changed-source/native response substitution, runtime cost claim, general/game solution or threshold sweeps'])
if (HERE/'compact_report.json').exists():raise ValueError('Preserve compact')
(HERE/'compact_report.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
print('compactSHA',sha(HERE/'compact_report.json'));print('familycounts',out['family_counts']);print('adversarycounts',out['adversary_counts'])
for q in rows+adversaries:
    f=q['windows']['full'];m=q['windows']['mature'];print(q['family'],'matureSTD',m.get('STD'),'ratioSIG',m.get('STD_ratio_to_frozen_significant64'),
        'fullABS',f.get('absolute_gain_min'),f.get('absolute_gain_max'),f.get('absolute_phase_max'),
        'matureABS',m.get('absolute_gain_min'),m.get('absolute_gain_max'),m.get('absolute_phase_max'),
        'fullgate',f.get('relative_gate_vs_frozen_significant64'),'maturegate',m.get('relative_gate_vs_frozen_significant64'))
if __name__=='__main__':pass
