"""Full/mature absolute limits and both frozen benchmarks, source CPU only."""
from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
r=json.loads((HERE/'results.json').read_text());rows=[]
for row in r['rows']+r['counterexamples']:
 name=row.get('scene',row.get('family'));rr=row['result'];a=rr['metrics']['nominal_significant_phase_history64'];diag=rr['significant_diagnostics']['frames'];benchmarks={}
 for base in ('frozen_hard_history64','first_phase_history64'):
  b=rr['metrics'][base];benchmarks[base]={}
  for win in ('full','mature'):
   gate=a[win]['source_only_relative_gate_against_'+base]
   benchmarks[base][win]=dict(relative_source_failures=gate['failures'],relative_source_nonregression=gate['nonregression'],relative_source_effective=gate['effective_success'],STD_baseline=b[win]['score']['residual_temporal_std'],STD_candidate=a[win]['score']['residual_temporal_std'],STD_change_fraction=a[win]['STD_ratio_to_'+base]-1)
 rows.append(dict(name=name,is_old_fixture='scene' in row,active_fraction=a['active_fraction'],invalid_pixel_fraction=a['invalid_pixel_fraction'],benchmarks=benchmarks,
  full_absolute_gain_range=[a['full']['absolute_gain_min'],a['full']['absolute_gain_max']],full_absolute_phase_max=a['full']['absolute_phase_max'],
  full_absolute_gain_failing_frames=a['full']['absolute_gain_failing_frames'],full_absolute_phase_failing_frames=a['full']['absolute_phase_failing_frames'],
  mature_absolute_gain_range=[a['mature']['absolute_gain_min'],a['mature']['absolute_gain_max']],mature_absolute_phase_max=a['mature']['absolute_phase_max'],
  full_bias_rgb=a['full']['score']['bias_rgb'],full_RMSE=a['full']['score']['rmse'],mature_RMSE=a['mature']['score']['rmse'],
  first8_source_metrics=a['startup_first8'],final_phase_used_count=diag[-1]['nominal_3SE_used_phase_frequencies'],final_phase_coherence_power_count=diag[-1]['phase_power_coherence_qualified_frequencies'],final_mean_variance_inflation=diag[-1]['max_nominal_mean_variance_inflation']))
old=[x for x in rows if x['is_old_fixture']];counts={}
for base in ('frozen_hard_history64','first_phase_history64'):
 counts[base]={win:dict(nonregression=sum(x['benchmarks'][base][win]['relative_source_nonregression'] for x in old),effective=sum(x['benchmarks'][base][win]['relative_source_effective'] for x in old)) for win in ('full','mature')}
report=dict(schema='nominal-significant-phase-compact-source-feasibility-v1',quality_accepted=False,native_measured=False,native_response_reused=False,game_run=False,
 frozen_results_sha256=sha(HERE/'results.json'),preregistration_sha256=r['preregistration_sha256'],prototype_sha256=r['prototype_sha256'],analysis_sha256=r['script_sha256'],summary_script_sha256=sha(__file__),selfchecks=r['self_checks'],families=13,adversaries=8,relative_source_counts=counts,rows=rows,
 conclusions=['Nominal3SE suppresses much of the previous stationary phase-noise harm: material/wave mature STD falls versus firstphase, but material remains2.4% above frozenhard and wave matches frozenhard. Static source noise floor is not reduced.',
 'Movinglight mature source STD drops6.4% versus frozenhard but full early_or_transition_frame fails. Distinct fresh native response could measure resulting response, not infer game/general success from source metrics.',
 'Slow constantphase mature source STD drops40.6% but first8 contain absolute phase failures. Phase acceleration has more early phase failures and maximum.09167rad despite mature relative gates passing.',
 'Weak material startup gain.9373 and weak Nyquist .921..1.428 remain; pooled colored RGB source residual floor and temporal AR violate nominalIID assumptions.',
 'Shared persistent source bias remains; absence of gain/phase on constant truth is not acceptance.',
 'Against oldhard selected-support/currentORmean differs; against firstphase both share selectedsupport. No old native response was reused or substituted.',
 'Per-frequency plug-in Cauchy inflation is nominal first-order accounting, not a nonlinear confidence bound. No production/runtime implementation or final quality acceptance.'])
p=HERE/'compact_report.json';assert not p.exists();p.write_text(json.dumps(report,indent=2)+'\n');print('compact_report_sha256',sha(p));print(counts)
