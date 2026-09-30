"""Read-only review and analytic one-pulse DC leverage adversary, no GPU."""
from pathlib import Path
import hashlib,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
aff=ROOT/'tools_tmp/response_affine_spectrum_offline_20260930';transfer=ROOT/'tools_tmp/response_transfer_offline_20260930'
sources=[aff/'analyze.py',aff/'results.json',transfer/'analyze.py',transfer/'results.json',transfer/'summary.json'];before={p:sha(p) for p in sources}
r=json.loads((aff/'results.json').read_text());counts={}
for study in sorted({row['study'] for row in r['rows']}):
 rows=[row for row in r['rows'] if row['study']==study];counts[study]={}
 for name in ('affine_pilot_dc_current_safe','affine_pilot_age_dc_current_safe'):
  counts[study][name]=dict(total=len(rows),effective_full_and_mature=sum(row['variants'][name]['full_gate']['effective_success'] and row['variants'][name]['mature_gate']['effective_success'] for row in rows))
# Fixed m16, min8 passed, constant pilot at artifact mode kA, one DC jump.
# D has a coincident arbitrary response-noise impulse at kA, not a stable DC law.
# Current-inclusive fit cannot distinguish this sample from a genuine DC artifact.
m=16;w=np.array([.2126,.7152,.0722]);n=128*80;sigma=.012;q=sigma*sigma/n
dc_noise=float(np.sum(w*w)*q);ridge=4*dc_noise;dc_jump=.05
v=dc_jump*dc_jump*(m-1)/(m*m)
leverage=1/m+(m-1)/m*v/(v+ridge)
assert leverage>.99 and 1/m==.0625
out=dict(schema='observable-globalDC-response-concept-review-v1',analysis_sha256=sha(__file__),source_sha256={str(p):v for p,v in before.items()},prior_affine_counts=counts,
 new_GPU_native_calls=0,quality_accepted=False,root_prototype_not_yet_reviewed=True,
 sound_scope=['Adding a real globalDC feature can model same-frequency D artifacts even when pilot P_k is0. It extends the previous diagonal complex-affine model with an observable nonlocal regressor.',
 'A stationary linear response map conditioned on source illumination can be a useful hypothesis; no causal identification or unknown-native-covariance proof follows.',
 'Keep previous affine pilot control and exact reset/jitter/inactive epochs. No old native response substitution when a new source pilot changes.'],
 conceptual_risks=['Current-inclusive fit target D=P-TP includes the same P predictor; correlation is partly algebraic and not evidence of a true response transfer.',
 'GlobalDC and local P_k can be nearly collinear on slowly moving/illumination-correlated material, leaving coefficients unidentifiable. Ridge chooses a decomposition rather than identifying its cause.',
 'A new DC impulse is high leverage: one same-frame response error can train a full spatial artifact map through one real feature, since gamma is free complex perfrequency/channel.',
 'Luminance DC noise variance sum(w²)q assumes RGB independent, equal sigma and spatialIID. RGB covariance changes it to wT K w; temporal/native response history correlation remains unknown.',
 'Native response can depend on lagged illumination, nonlinear thresholds or private state; current globalDC cannot generally condition those histories.',
 'Warmup m<8 rawdelta followed by fitted delta can create a new transition. No-future alone does not establish independent prediction or smoothing quality.',
 'Complex normal equations must use conjugation with the realDC feature and perfeature ridge units; a complex coefficient on DC is valid but self-conjugate boundary outputs must remain real-compatible.'],
 proposed_observable_adversary=dict(name='one_DC_pulse_with_independent_nonlocal_response_impulse',history=16,minimum_count=8,source_size=[128,80],source_sigma=.012,luma_weights=w.tolist(),
  construction='P_t=.2 constantRGB for t0..14; P_15=.25 constantRGB. At nonDC kA=(4,0), all P_kA=0. D_kA=0 before15; at15 D_kA=eta (arbitrary complex response-noise impulse). TP=P-D, eta small enough for positive RGB. Optional genuine moving wave at distinct kD=(3,0) with D_kD=.2P_kD is scored for absolute gain/phase while DC pulse stays same.',
  filter_inputs_only='P,TP,observable source nominal variance,reset/jitter/activity. No cleantruth or scene label enters estimator.',
  causal_ambiguity='One same-frame impulse correlated with a unique DC jump is observationally identical, on the fit window, to a real DC-induced nonlocal response. Preserve both labels as diagnostic constructions; do not infer causal gamma.',
  globalDC_nominal_noise_variance=dc_noise,globalDC_ridge=ridge,centered_DC_variance=v,analytic_current_prediction_fraction_of_impulse=leverage,
  old_affine_constant_P_prediction_fraction_of_impulse=1/m,expected_check='Report large current response-noise retention vs old affine16mean, plus per-frame moving-detail gain/phase. Do not reject or tune threshold based on true scene label.'),
 recommended_positive_control='Spread DC variation over16 observations with exactly D_kA=gamma*(DC-DCmean), P_kA=0, no response noise. This validates intended nonlocal feature recovery; keep singlepulse noise adversary beside it.',
 conclusion='Hypothesis is coherent as a posthoc conditional predictor, but current-inclusive DC leverage creates a concrete response-noise-copying failure. Measure both controlled nonlocal response and moving detail; no production/native/game claim.')
assert all(sha(p)==v for p,v in before.items());out['all_prior_evidence_unchanged']=True
p=HERE/'concept_review.json';assert not p.exists();p.write_text(json.dumps(out,indent=2)+'\n');print('concept_review_sha256',sha(p),'DCpulse_impulse_retention',leverage)
