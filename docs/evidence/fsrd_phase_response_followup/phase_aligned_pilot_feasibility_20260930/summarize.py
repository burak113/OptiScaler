"""Compact honest summary of frozen CPU source-only feasibility."""
from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
r=json.loads((HERE/'results.json').read_text());rows=[]
for row in r['rows']+r['counterexamples']:
 name=row.get('scene',row.get('family'));result=row['result'];a=result['metrics']['phase_aligned_history64'];b=result['metrics']['frozen_hard_history64']
 rows.append(dict(name=name,is_old_fixture='scene' in row,active_fraction=a['active_fraction'],
  full_relative_source_failures=a['full']['source_only_relative_gate_against_old_hard']['failures'],mature_relative_source_failures=a['mature']['source_only_relative_gate_against_old_hard']['failures'],
  full_relative_source_effective_success=a['full']['source_only_relative_gate_against_old_hard']['effective_success'],mature_relative_source_effective_success=a['mature']['source_only_relative_gate_against_old_hard']['effective_success'],
  full_absolute_gain_range=[a['full']['absolute_gain_min'],a['full']['absolute_gain_max']],full_absolute_phase_max=a['full']['absolute_phase_max'],
  full_absolute_gain_failing_frames=a['full']['absolute_gain_failing_frames'],full_absolute_phase_failing_frames=a['full']['absolute_phase_failing_frames'],
  mature_absolute_gain_range=[a['mature']['absolute_gain_min'],a['mature']['absolute_gain_max']],mature_absolute_phase_max=a['mature']['absolute_phase_max'],
  mature_STD_old=b['mature']['score']['residual_temporal_std'],mature_STD_phase=a['mature']['score']['residual_temporal_std'],
  mature_STD_change_fraction=a['mature']['score']['residual_temporal_std']/b['mature']['score']['residual_temporal_std']-1,
  full_bias_rgb=a['full']['score']['bias_rgb'],full_RMSE=a['full']['score']['rmse'],mature_RMSE=a['mature']['score']['rmse'],
  final_phase_qualified_frequency_count=result['phase_diagnostics']['frames'][-1]['phase_qualified_frequencies'],
  final_max_qualified_phase_increment=result['phase_diagnostics']['frames'][-1]['max_qualified_phase_increment']))
old=[x for x in rows if x['is_old_fixture']]
summary=dict(schema='phase-aligned-source-pilot-compact-summary-v1',quality_accepted=False,native_recommended_from_this_evidence=False,native_measured=False,native_response_reused=False,
 frozen_results_sha256=sha(HERE/'results.json'),preregistration_sha256=r['preregistration_sha256'],prototype_sha256=r['prototype_sha256'],analysis_sha256=r['script_sha256'],summary_script_sha256=sha(__file__),selfchecks=r['self_checks'],
 old_families=13,counterexamples=len(r['counterexamples']),
 relative_source_nonregression_full=sum(not x['full_relative_source_failures'] for x in old),relative_source_nonregression_mature=sum(not x['mature_relative_source_failures'] for x in old),
 relative_source_effective_full=sum(x['full_relative_source_effective_success'] for x in old),relative_source_effective_mature=sum(x['mature_relative_source_effective_success'] for x in old),rows=rows,
 conclusions=['Source phase alignment reduces slow constant-phase mature STD by about41%, but early absolute phase exceeds.05rad. Acceleration fails full relative phase and absolute early phase.',
  'Static material/wave mature source STD increases by about25%/22%; no source noise-floor solution and native testing not justified by these results.',
  'Weak material loses6.27% contrast at startup and weak Nyquist counterexample has broad absolute gain failures despite relative gates passing.',
  'Persistent correlated source bias remains even when its source-pilot temporal noise is low; flat truth has no meaningful true phase/gain gate.',
  'Colored RGB noise leaves a high residual floor; pooled nominal noise assumptions are not universally valid.',
  'Relative gates allow additive1e-4 STD tolerance and are not absolute detail/noise acceptance. New pilot native response was not computed or substituted.',
  'Old hard pilot has current-OR-mean support while preregistered phase candidate uses selected-coefficient support. This comparison is feasibility, not an isolated causal phase-only ablation. Small qualified static theta is observed, but its sole responsibility for noise increase is not proven.'])
p=HERE/'compact_report.json';assert not p.exists();p.write_text(json.dumps(summary,indent=2)+'\n');print('compact_report_sha256',sha(p));print('counts',summary['relative_source_nonregression_full'],summary['relative_source_nonregression_mature'],summary['relative_source_effective_full'],summary['relative_source_effective_mature'])
