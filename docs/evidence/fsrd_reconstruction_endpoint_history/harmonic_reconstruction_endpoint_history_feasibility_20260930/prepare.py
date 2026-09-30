"""Prepare one distinct reconstruction endpoint law; no cohort/operator scores."""
from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent;OLD=HERE.parent/'harmonic_response_coefficient_history_feasibility_v2_20260930'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(n,v):
    with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
source=(OLD/'model.py').read_text();(HERE/'frozen_V2_model.py.txt').write_bytes((OLD/'model.py').read_bytes())
weights='''def endpoint_weights(n):
    if not 1<=n<=HISTORY:raise ValueError('history count outside1..16')
    if n==1:return np.ones(1)
    t=np.arange(n,dtype=float);centered=t-t.mean()
    return np.ones(n)/n+centered*centered[-1]/np.dot(centered,centered)

'''
ops=[
 ('scope_doc','"""One frozen actual-response coefficient history; no clean/guide input."""','"""Current reconstruction endpoint OLS; saved matching B/P/TP, no clean/guide input."""'),
 ('endpoint_weight_helper','def physical_projection(descriptor,h,w):',weights+'def physical_projection(descriptor,h,w):'),
 ('distinct_API','def make_response_history(', 'def make_reconstruction_endpoint_history('),
 ('fit_current_reconstruction','D=(P[i].astype(float)-TP[i].astype(float));roi=D[MARGIN:-MARGIN,MARGIN:-MARGIN];','R0=C[i].astype(float);roi=R0[MARGIN:-MARGIN,MARGIN:-MARGIN];'),
 ('endpoint_not_mean','chosen=sum(r[\'z\']*np.exp(1j*(psi-r[\'psi\']))[:,None] for r in history)/len(history)',"weights=endpoint_weights(len(history))\n        chosen=sum(weight*r['z']*np.exp(1j*(psi-r['psi']))[:,None] for weight,r in zip(weights,history))"),
 ('diagnostic_reason',"else 'transported_physical_coefficient_mean'", "else 'transported_reconstruction_coefficient_endpoint_OLS'"),
 ('diagnostic_weights',"history_count=len(history),history_frames=[r['frame'] for r in history]", "history_count=len(history),endpoint_weights=weights.tolist(),nominal_IID_weight_square_sum=float(np.dot(weights,weights)),history_frames=[r['frame'] for r in history]"),
 ('distinct_schema',"schema='actual-physical-response-history-v1'","schema='current-reconstruction-endpoint-OLS-v1'"),
 ('diagnostic_scope','history=HISTORY,quality_accepted=False)',"history=HISTORY,polynomial_degree=1,filtered_observable='C=B+active*(P-TP)',quality_accepted=False)"),
]
for label,before,after in ops:
    assert source.count(before)==1,label;source=source.replace(before,after)
source+="\n# Existing analyzer-compatible API; this module is a distinct law.\nmake_response_history=make_reconstruction_endpoint_history\n"
(HERE/'model.py').write_text(source,encoding='utf-8',newline='\n')
save('source_implementation_whitelist.json',{'frozen_V2_model':{'path':str(OLD/'model.py'),'sha256':sha(OLD/'model.py')},'operations':[{'label':a,'before':b,'after':c}for a,b,c in ops],
 'suffix_only':"\n# Existing analyzer-compatible API; this module is a distinct law.\nmake_response_history=make_reconstruction_endpoint_history\n",'new_model_SHA':sha(HERE/'model.py')})
(HERE/'source_authentication.json').write_bytes((OLD/'source_authentication.json').read_bytes())
save('preregistration.json',{'schema':'current-reconstruction-endpoint16-preCPU-preregistration-v1','status':'prepared_no_cohort_or_known_operator_scores',
 'candidate':'canonical_source_phase_transported_current_reconstruction_endpoint_OLS16_then_frozen_source_DC',
 'constants':{'window':16,'degree':1,'source_basis_condition':10000,'margin':5,'source_phase_cuts':'unchanged V2','DC_policy':'unchanged96a1 innovation64'},
 'observable':'C/R0=B+active*(P-TP) in original current composition dtype. Fit float64 interior-centered jointRGB canonical source Phi. Retain C orthogonal residual and shift only its atom beta to endpoint OLS of transported history; n1 uses C bytes directly.',
 'weights':'n1=[1]; otherwise wi=1/n+(ti-tbar)*(n-1-tbar)/sum((t-tbar)^2), ti=0..n-1. Inclusive history after all inherited cuts; negative early weights retained without clipping.',
 'invariants':'sum(w)=1; sum(w*t)=n-1. Constant+linear coefficients preserved in source-phase-transported canonical coordinates. This is not invariance of arbitrary moving raw coefficient sequences.',
 'nominal_noise_gain':'sum(w^2)=2*(2n-1)/(n*(n+1)) n>=2, n1=1; n16=31/136=.22794117647. IID equal-variance algebra only, not confidence or measured covariance.',
 'unchanged_fallback':'V2 invalidP/TP/metadata/phase/fit/reconstruction wholeframe exactB+eligibilityfalse+historycut; n1/noatom/unsupported retains currentC then frozenDC ifeligible. Frozen final DC safe application uses per-invalidpixel atomicRGB baseline fallback, no invented globalstatecut.',
 'report_plan':'After root law review ONLY: six matching saved native rows and all24 unchanged known controls; compare original6native variants, frozenDCinnovation control and exactV2history control. Windows full/mature16/startup8/activation8to16/transition24to40; unchanged relative gates, actualSTD<=1 and absolute5%gain/.05phase separate.',
 'required_control_families':['exact endogenous B/D cancellation','constant and affine reconstruction coefficient','moving source static D','lighting step and slow drift','reset/jitter/exposure','all24 unchanged frozen constructed operators'],
 'counterexamples':['Quiet reconstruction is not proof of clean radiance: true nonlinear detail/motion or stale native history can be hidden by endpoint trend.','Source phase may differ from reconstruction phase; static reconstruction with moving source phase transport may change despite exactcancellation.','Quadratic acceleration/phase errors create endpoint bias; sudden subthreshold coefficient step without sourcecut is smeared or overshoots.','Filtering reconstruction changes nativebaseline atom coefficients as well asD; no native response covariance or independent confidence assumed.','First8baseline and dense/currentorth errors remain; reconstruction noiseless/error-cancellation only exact for preserved coefficient law afterphase/cuts.','Commonbias and RGB/time correlation remain unidentifiable; nominal variance gains do not imply quality.'],
 'forbidden':['cohort/operator score before rootreview','threshold sweep','truth/scene/guide/future estimator input','newP with oldTP','native/GPU/runtime/game changes'],
 'coverage':'Only6matchingnative TP; other7source families+22source adversaries cannot be filled by constructedoperator proxy.','quality_accepted':False})
oldfreeze=json.loads((OLD/'pre_score_freeze.json').read_text())
for p,s in oldfreeze['sources'].items():assert sha(p)==s,p
save('inherited_input_pins.json',{'frozen_V2_sources':oldfreeze['sources'],'additional_V2_sources':{str(OLD/n):sha(OLD/n)for n in ['model.py','known_operators.py','selfchecks.py','analyze.py','results.json','source_authentication.json','preregistration.json','pre_score_freeze.json']},
 'cohort_outputs_not_loaded':True,'known_operator_generator_not_called':True})
print('Prepared model/prereg/whitelist only; no cohort/known-operator evaluation.')
