"""Summarize one completed frozen CPU run without changing model or metrics."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent;OLD=ROOT/'harmonic_response_coefficient_history_feasibility_v2_20260930'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ident(p):p=Path(p);return dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p))
def read(p):return json.loads(Path(p).read_text())
def save(n,v):
    encoded=(json.dumps(v,indent=2,allow_nan=False)+'\n').encode('utf-8')
    with(HERE/n).open('xb')as f:f.write(encoded)
result=read(HERE/'results.json');assert sha(HERE/'results.json')=='225848939eb620a3b712ead68dffdef4e23fd952b2865e9e98445df9b9ede93e'
assert result['status']=='completed_saved_response_and_known_operator_feasibility_not_solution' and len(result['native_rows'])==6 and len(result['known_operator_rows'])==24
old=read(OLD/'results.json');previous_native={r['scene']:r for r in old['native_rows']};previous_known={r['name']:r for r in old['known_operator_rows']}
freeze=read(HERE/'pre_cpu_freeze.json');assert len(freeze['sources'])==61
for p,s in freeze['sources'].items():assert sha(p)==s,p
auth=ROOT/'endpoint_root_cpu_authorization_20260930.json';review=ROOT/'harmonic_reconstruction_endpoint_history_law_review_20260930/review.json'
assert sha(auth)=='45dda69927abfad7e5875f13104a4792575fea476bbfb29fc5e275bb3da9c2f3'
assert sha(review)=='0b6b29d5ff0c21288e08f81f84e88d05d7c0cf6a2c0eb75a71a61afb38401c32'
windows=['full','mature','startup_first8','activation8to16','transition24to40'];offset=dict(full=0,mature=48,startup_first8=0,activation8to16=8,transition24to40=24)
variants=['frozen_DC_innovation_safe','frozen_V2_delta_history','candidate']
counts={v:{w:dict(rows=0,relative_effective=0,strict_STD_le1=0,absolute_gain_pass=0,absolute_phase_pass=0,absolute_gain_AND_phase=0,relative_AND_STRICT_STD_AND_gain_AND_phase=0)for w in windows}for v in variants}
def compact(m,w):
    gainfail=m['absolute_gain_failing_frames'];phasefail=m['absolute_phase_failing_frames'];ratio=m['actual_STD_ratio_to_control']
    gp=not gainfail;pp=not phasefail
    assert m['per_frame_absolute_detail_pass']==(gp and pp)
    return dict(relative_effective=m['relative_gate']['effective_success'],relative_failures=m['relative_gate']['failures'],relative_activity=m['relative_gate']['active'],
        STD=m['score']['residual_temporal_std'],STD_ratio_to_B=ratio,strict_STD_le1=None if ratio is None else ratio<=1,
        absolute_gain_pass=gp,absolute_phase_pass=pp,absolute_gain_AND_phase=gp and pp,gain_min=m['absolute_gain_min'],gain_max=m['absolute_gain_max'],phase_max=m['absolute_phase_max'],
        gain_failing_global_frames=[offset[w]+i for i in gainfail],phase_failing_global_frames=[offset[w]+i for i in phasefail],
        phase_or_gain_None_qualification='None on absent clean-reference spatial mode is not an invented phase/gain measurement.',
        invalid_pixel_fraction=m['invalid_pixel_fraction'],mean_temporal_variance=m['mean_temporal_variance'],broad_tone_rms=m['score']['broad_tone_rms'],bias_rgb=m['score']['bias_rgb'])
rows=[]
for r in result['native_rows']:
    previous=previous_native[r['scene']]
    for k in ['sequences_sha256','source_report_sha256','source_SHA','P_SHA','TP_SHA','baseline_SHA','controls_SHA','truth_scoring_only_SHA']:assert r[k]==previous[k],(r['scene'],k)
    for w in windows:assert r['variants']['frozen_V2_delta_history'][w]==previous['variants']['candidate'][w],(r['scene'],w)
    a={w:{v:compact(r['variants'][v][w],w)for v in variants}for w in windows}
    for w in windows:
        for v in variants:
            c=counts[v][w];m=a[w][v];c['rows']+=1;c['relative_effective']+=int(m['relative_effective']);c['strict_STD_le1']+=int(m['strict_STD_le1']is True)
            c['absolute_gain_pass']+=int(m['absolute_gain_pass']);c['absolute_phase_pass']+=int(m['absolute_phase_pass']);c['absolute_gain_AND_phase']+=int(m['absolute_gain_AND_phase'])
            c['relative_AND_STRICT_STD_AND_gain_AND_phase']+=int(m['relative_effective'] and m['strict_STD_le1']is True and m['absolute_gain_AND_phase'])
        cm=a[w]['candidate']
        for v in variants[:2]:
            denom=a[w][v]['STD'];cm['STD_ratio_to_'+v]=cm['STD']/denom if denom else None
    diag=r['diagnostics'];fallback=diag['application'];reason_counts={}
    for f in diag['frames']:reason_counts[f['reason']]=reason_counts.get(f['reason'],0)+1
    rows.append(dict(scene=r['scene'],windows=a,first8_exactB=r['first8_inactive_exact_B'],fallback_pixel_fraction=fallback['atomic_fallback_pixel_fraction'],
        DC_ineligible_frames=[i for i,b in enumerate(diag['application_eligible'])if not b],reason_counts=reason_counts,candidate_SHA=r['candidate_SHA']))
known=[]
for r in result['known_operator_rows']:
    previous=previous_known[r['name']]
    for k in ['source_SHA','P_SHA','TP_SHA','baseline_SHA','controls_SHA','truth_scoring_only_SHA']:assert r[k]==previous[k],(r['name'],k)
    for w in windows:assert r['variants']['frozen_V2_delta_history'][w]==previous['variants']['candidate'][w],(r['name'],w)
    known.append(dict(name=r['name'],windows={w:{v:compact(r['variants'][v][w],w)for v in variants}for w in windows},
        first8_exact_B=r['first8_exact_B'],fallback_pixel_fraction=r['diagnostics']['application']['atomic_fallback_pixel_fraction'],
        eligibility=r['diagnostics']['application_eligible']))
report=dict(schema='endpoint-reconstruction16-completed-CPU-summary-v1',UTC=datetime.now(timezone.utc).isoformat(),
 status='completed_single_frozen_CPU_candidate_failed_general_feasibility',quality_accepted=False,new_native_contexts=0,new_P_or_TP=False,
 result_identity=ident(HERE/'results.json'),model_identity=ident(HERE/'model.py'),preCPU_freeze_identity=ident(HERE/'pre_cpu_freeze.json'),
 corrected_preparation_manifest_identity=ident(HERE/'preparation_completion_manifest_corrected.json'),root_authorization=ident(auth),independent_law_review=ident(review),
 all61_frozen_source_SHA_equal=True,all6native_and24known_inputs_byte_identified_to_previous=True,all_V2_control_metrics_exact_all5windows=True,
 counts=counts,native_rows=rows,known_operator_rows=known,
 limitations=['Endpoint law preserves constant/linear coefficients only in source-phase-transported coordinates. Quiet reconstruction can be wrong or contain stale native response; no source-only truth guard.',
  'Negative endpoint weights and curvature/acceleration can produce bias or overshoot. DC and wholeRGB atomic fallback remain frozen.',
  'First8 exactB remains, full failures cannot be erased by mature improvement. Dense current orth errors, phase mismatch/commonbias/correlation remain.',
  'Six matching saved native responses only; other7source+22source adversaries lack matchingTP. Known24 are constructed operators, not native coverage.',
  'Relative gates with1e-4 STD slack cannot establish strict noise reduction; gain and phase are evaluated separately.',
  'No fresh native replay, runtime/game acceptance or stain/wave solution established.'])
save('compact_report.json',report)
# Assemble identities before opening manifest, excluding the manifest itself.
files=[ident(p)for p in sorted(HERE.rglob('*'))if p.is_file()]
save('completion_manifest.json',dict(schema='endpoint-reconstruction-single-CPU-run-completion-v1',files=files,external_authorization_and_review=[ident(auth),ident(review)],
 self_entry_excluded=True,source_law_changed=False,CPU_analyzer_runs=1,native_GPU_calls=0,quality_accepted=False))
print(json.dumps(dict(compact=ident(HERE/'compact_report.json'),manifest=ident(HERE/'completion_manifest.json'),candidate_counts=counts['candidate'],native_STD=[dict(scene=r['scene'],STD_mature_ratio_B=r['windows']['mature']['candidate']['STD_ratio_to_B'])for r in rows])))
