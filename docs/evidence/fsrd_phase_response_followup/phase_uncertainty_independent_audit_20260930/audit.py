"""Independent IID lag variance and weighted-age derivative checks, CPU only."""
from pathlib import Path
import hashlib,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
CASE=ROOT/'tools_tmp/phase_uncertainty_formula_check_20260930';RP=CASE/'evidence/results.json'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
before={p:sha(p) for p in (RP,CASE/'check.py',CASE/'preregistration.md')};r=json.loads(RP.read_text())
assert before[RP]=='bf1fd20e5412ea6629769ecda4cd521405cd4a04cc3c18ac5197122c3d793df8'
assert r['source_sha256']==before[CASE/'check.py'] and r['preregistration_sha256']==before[CASE/'preregistration.md']
assert r['status']=='completed_model_check_not_quality_solution' and r['native_RR_dispatches']==r['conversion_dispatches']==0 and len(r['rows'])==48 and len(r['counterexamples'])==2
S=np.array([.035,.021*np.exp(.3j),.010*np.exp(-.2j)]);energy=float(sum(abs(S)**2))
for row in r['rows']:
 m=row['m'];q=np.full(m,energy/(3*row['power_ratio']))
 if row['varying_q']:q*=np.linspace(.5,1.5,m)
 v=.5*energy*(q[0]+q[-1])+.5*3*sum(q[1:]*q[:-1])
 np.testing.assert_allclose(v,row['exact_IID_imaginary_variance'],rtol=1e-15)
 np.testing.assert_allclose(v/((m-1)*energy)**2,row['true_linearized_angle_variance'],rtol=1e-15)
 assert row['trials']==16384 and row['noise_mode']=='IID' and row['formula_IID_assumptions_satisfied']
 assert row['relative_imaginary_variance_error']<=.06 and row['maximum_exact_derivative_finite_difference_relative_error']<=1e-7
 assert row['exact_variance_MC_gate_pass'] and row['exact_derivative_gate_pass']
assert r['all_48_IID_formula_and_derivative_checks_pass']
# Seed/model constants below were fixed before this independent simulation.
rng=np.random.default_rng(831199);trials=8192;rows=[];closure_max=0.;derivative_max=0.;wrong_substitution=[]
for m in (8,32,64):
 for omega in (0,.08):
  for varying in (False,True):
   q=np.full(m,energy/(3*16))
   if varying:q*=np.linspace(.5,1.5,m)
   time=np.arange(m);clean=np.exp(1j*omega*time[:,None])*S;eps=(rng.normal(size=(trials,m,3))+1j*rng.normal(size=(trials,m,3)))*np.sqrt(q[None,:,None]/2)
   F=clean+eps;C=np.sum(F[:,1:]*np.conj(F[:,:-1]),axis=(1,2));eta=eps*np.exp(-1j*omega*time)[None,:,None]
   linear=np.sum((eta[:,-1]-eta[:,0])*np.conj(S),-1)
   quadratic=np.sum(eta[:,1:]*np.conj(eta[:,:-1]),(1,2))
   actual=(C*np.exp(-1j*omega)).imag;closure=float(np.max(abs(actual-(linear+quadratic).imag)));closure_max=max(closure_max,closure);assert closure<1e-16
   nominal=.5*energy*(q[0]+q[-1])+.5*3*sum(q[1:]*q[:-1]);empirical=float(np.var(actual,ddof=1));error=abs(empirical/nominal-1);assert error<.06
   rows.append(dict(m=m,omega=omega,varying_q=varying,trials=trials,nominal_imag_variance=nominal,independent_empirical_imag_variance=empirical,relative_error=error,exact_endpoint_plus_quadratic_closure_max=closure))
# Derivative checked on general varying-amplitude/channel coefficients, not
# only the special coherent model where mean-age substitution happens to work.
for m in (8,16,64):
 for inclusive in (False,True):
  count=m+int(inclusive);age=m-np.arange(count);f=rng.normal(size=(count,3))+1j*rng.normal(size=(count,3));theta=.13;step=1e-6
  def mean(t):return np.mean(f*np.exp(1j*t*age[:,None]),axis=0)
  derivative=1j*np.mean(age[:,None]*f*np.exp(1j*theta*age[:,None]),axis=0)
  numerical=(mean(theta+step)-mean(theta-step))/(2*step);relative=float(np.max(abs(numerical-derivative))/np.max(abs(derivative)));derivative_max=max(derivative_max,relative);assert relative<1e-7
  substitute=1j*age.mean()*mean(theta);wrong_substitution.append(dict(m=m,current_inclusive=inclusive,exact_finite_difference_relative_error=relative,mean_age_substitution_absolute_max_error=float(np.max(abs(substitute-derivative)))))
assert all(sha(p)==v for p,v in before.items())
out=dict(schema='independent-nominal-phase-uncertainty-algebra-audit-v1',analysis_sha256=sha(__file__),source_report_sha256=before[RP],source_generator_sha256=before[CASE/'check.py'],source_preregistration_sha256=before[CASE/'preregistration.md'],all_original_evidence_unchanged=True,new_GPU_native_calls=0,quality_accepted=False,
 verified_root_IID_rows=48,verified_root_trials_per_case=16384,independent_seed=831199,independent_trials_per_case=8192,independent_rows=rows,weighted_age_derivative_checks=wrong_substitution,
 exact_endpoint_plus_quadratic_closure_max=closure_max,maximum_weighted_age_derivative_relative_error=derivative_max,
 proof=['Write eta_j=epsilon_j exp(-i omega j). Rotated lag C has deterministic real L*E, linear term sum_j,c(S_c conj(eta_(j-1,c))+eta_(j,c)conj(S_c)), and quadratic adjacent eta products.',
 'Imaginary linear term telescopes exactly to Im(sum_c (eta_last-eta_first)conj(S_c)); circular independent endpoints contribute E*(q_first+q_last)/2.',
 'Adjacent quadratic products have imaginary variance3*q_j*q_(j-1)/2. Distinct product covariance is0 under zero-mean circular independent time/channel noise, including neighboring products with unmatched endpoints.',
 'Linear/quadratic covariance is0 because zero-mean Gaussian third moments vanish. Adding terms yields exact imaginary variance for this constant coherent-amplitude IID model, not an exact finite-sample angle variance.',
 'For any deterministic observed coefficient sequence, dG/dtheta=i*mean(age_j*F_j*exp(i theta age_j)) exactly. Current-inclusive mean includes age0; current coefficient contributes0 to derivative.',
 'Cauchy/Minkowski bounds a first-order sum of errors with fixed RMS magnitudes without independence, but plug-in random derivative/SE, selection and nonlinear angle remain outside that proof.'],
 root_counterexamples=[dict(mode=x['noise_mode'],empirical_to_IID_imag_variance=x['empirical_imaginary_variance']/x['exact_IID_imaginary_variance']) for x in r['counterexamples']],
 qualifications=['S,omega,q are oracle algebra-model inputs only; never available-source pilot inputs.',
 'Dense material, cross-channel correlation, temporal correlation, acceleration and amplitude drift break nominal assumptions. Correlation can increase or decrease variance; no direction assumed.',
 'Plug-in debiased energy and observed |C| are not guaranteed conservative estimates. Phase selection abs(theta)>3SE is nominal, not exact confidence.',
 'Mean-age*mean coefficient is invalid for general observations. Use actual complex weighted-age derivative for both past prediction and current-inclusive mean.',
 'A coefficient-wise first-order uncertainty term is diagnostic model accounting, not a nonlinear finite-sample upper bound or proof of an effective independent count.'],
 conclusion='Endpoint variance and actual weighted-age derivative are mathematically justified under explicitly narrow models. A distinct source-only nominal-significance feasibility test is justified, but no native/production/game acceptance follows.')
p=HERE/'audit.json';assert not p.exists();p.write_text(json.dumps(out,indent=2)+'\n');print('audit_sha256',sha(p));print('maxclosure',closure_max,'maxderivative',derivative_max,'maxMC',max(x['relative_error'] for x in rows))
