"""Compact independent native scope and actual-noise/detail limits."""
from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
a=json.loads((HERE/'audit.json').read_text());selected='significant_phase_dc_current_safe';rows=[]
for row in a['rows']:
 v=row['variants'][selected];rows.append(dict(scene=row['scene'],full_gate=v['full_gate'],mature_gate=v['mature_gate'],
  actual_full_STD=v['actual_full_STD'],baseline_full_STD=v['baseline_full_STD'],actual_mature_STD=v['actual_mature_STD'],baseline_mature_STD=v['baseline_mature_STD'],actual_mature_STD_change_fraction=v['actual_mature_STD']/v['baseline_mature_STD']-1,
  full_absolute_gain_range=v['full_gain_range'],mature_absolute_gain_range=v['mature_gain_range'],full_absolute_gain_failing_frames=v['full_absolute_gain_failing_frames'],full_absolute_phase_failing_frames=v['full_absolute_phase_failing_frames'],full_absolute_phase_max=v['full_absolute_phase_max'],mature_absolute_phase_max=v['mature_absolute_phase_max'],
  full_RGB_bias=v['full_RGB_bias'],baseline_full_RMSE=v['baseline_full_RMSE'],full_RMSE=v['full_RMSE'],baseline_mature_RMSE=v['baseline_mature_RMSE'],mature_RMSE=v['mature_RMSE'],
  null_full_rms=row['null_rms'],null_mature_rms=row['mature_null_rms'],activity=v['activity'],fallback_fraction=v['baseline_fallback_fraction'],invalid_RGB_pixel_fraction=v['invalid_RGB_pixel_fraction']))
report=dict(schema='fresh-native-significant-phase-independent-compact-v1',summary_script_sha256=sha(__file__),audit_sha256=sha(HERE/'audit.json'),final_results_sha256=a['final_results_sha256'],selected_variant=selected,quality_accepted=False,game_run=False,native_contexts=18,native_RR_dispatches=1152,new_GPU_native_calls=0,
 effective_full=sum(row['full_gate']['effective_success'] for row in rows),effective_mature=sum(row['mature_gate']['effective_success'] for row in rows),effective_full_and_mature=sum(row['full_gate']['effective_success'] and row['mature_gate']['effective_success'] for row in rows),
 all_frame_gain_and_phase_pass_scenes=[row['scene'] for row in rows if not row['full_absolute_gain_failing_frames'] and not row['full_absolute_phase_failing_frames']],rows=rows,
 conclusions=['Fresh source/null/pilot responses measured18 contexts1152 dispatches with pinned runner/provider; all7 native input hashes, applied184-byte controls, raw outputs/logs/guards and source-counterfactual contracts verified.',
 'Stored P source/reference/control and six correction/DC/fallback variants regenerated exactly without GPU or old response substitution. Source estimator and native response metadata scopes remain distinct.',
 'Selected correction effective3/6 full,3/6 mature, but only movinglight and lightingstep pass both. Weak mature relative pass still has absolute gain below.95 and almost doubled mature noise.',
 'Material mature STD increases126.4%, wave90.7%, reset202.2%. RMSE improvement does not rescue these noise failures.',
 'This is initial6-family evidence, not full13/shared-bias/historic-geometry/runtime/game acceptance. General stain/wave solution remains unaccepted.',
 'Actual converter/composition CB/input/output byte snapshots were deleted by standard worker; retained job/CSO identities and native raw bytes do not independently redecode composed response. This provenance gap is explicit, no original outputs changed.'])
p=HERE/'compact_report.json';assert not p.exists();p.write_text(json.dumps(report,indent=2)+'\n');print('compact_report_sha256',sha(p));print(report['effective_full'],report['effective_mature'],report['effective_full_and_mature'])
