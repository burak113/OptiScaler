"""Exact proper-complex quadratic-form variance with oracle noise covariance."""
from pathlib import Path
import hashlib,json
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'tools_tmp/phase_uncertainty_formula_check_20260930/evidence/results.json'
S=np.array([.035,.021*np.exp(.3j),.010*np.exp(-.2j)])
E=float(np.sum(abs(S)**2))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def exact(m,ratio,omega,varying=False,mode='IID'):
    q=np.full(m,E/(3*ratio))
    if varying:q*=np.linspace(.5,1.5,m)
    R=.2*np.eye(3)+.8*np.ones((3,3)) if mode=='channel_correlated' else np.eye(3)
    T=np.sqrt(q[:,None]*q[None,:])*.8**abs(np.arange(m)[:,None]-np.arange(m)[None,:]) if mode=='temporal_AR' else np.diag(q)
    K=np.kron(T,R).astype(complex)
    B=np.zeros((3*m,3*m),complex)
    for j in range(1,m):
        for c in range(3):B[3*(j-1)+c,3*j+c]=1
    H=(np.exp(-1j*omega)*B-np.exp(1j*omega)*B.conj().T)/(2j)
    mu=(np.exp(1j*omega*np.arange(m))[:,None]*S).ravel()
    linear=float(np.real(2*np.vdot(H@mu,K@(H@mu))))
    HK=H@K;quadratic=float(np.real(np.trace(HK@HK)))
    mean=float(np.real(np.vdot(mu,H@mu)+np.trace(H@K)))
    lag_mean=np.vdot(mu,B@mu)+np.trace(B@K)
    return dict(exact_imaginary_mean=mean,exact_imaginary_variance=linear+quadratic,
        exact_linear_variance=linear,exact_quadratic_variance=quadratic,
        lag_mean_real=float(lag_mean.real),lag_mean_imaginary=float(lag_mean.imag),
        phase_of_expected_lag_minus_true_omega=float(np.angle(lag_mean)-omega),
        covariance_positive_minimum_eigenvalue=float(np.linalg.eigvalsh(K).min()),
        Hermitian_H_max_error=float(abs(H-H.conj().T).max()))

def main():
    folder=Path(__file__).resolve().parent;out=folder/'evidence'
    if out.exists():raise ValueError('Preserve covariance model check')
    out.mkdir();source_hash=sha(SOURCE);old=json.loads(SOURCE.read_text())
    report=dict(schema='exact-proper-complex-lag-quadratic-form-oracle-covariance-check-v1',quality_accepted=False,
        native_RR_dispatches=0,conversion_dispatches=0,script_sha256=sha(__file__),
        source_results_path=str(SOURCE),source_results_sha256=source_hash,
        formula='Im(exp(-i omega) C)=z^* H z; H=(exp(-i omega) B-exp(i omega) B^*)/(2i); Var=tr(H K H K)+2 mu^* H K H mu',
        assumptions='Proper complex Gaussian z with deterministic mean mu and known full time/RGB covariance K.',
        oracle_noise_covariance=True,not_pilot_estimator=True,rows=[],counterexamples=[],
        limitation='No claim that actual observed-source K is known, estimable without bias, stationary or Gaussian; no native response or quality acceptance.')
    for group in ('rows','counterexamples'):
        for row in old[group]:
            values=exact(row['m'],row['power_ratio'],row['omega'],row['varying_q'],row['noise_mode'])
            error=abs(row['empirical_imaginary_variance']/values['exact_imaginary_variance']-1)
            agreement=abs(values['exact_imaginary_variance']/row['exact_IID_imaginary_variance']-1)
            report[group].append(dict(m=row['m'],ratio=row['power_ratio'],omega=row['omega'],
                varying_q=row['varying_q'],mode=row['noise_mode'],**values,
                empirical_imaginary_variance=row['empirical_imaginary_variance'],MC_relative_error=float(error),
                MC_relative_error_within_0_06=bool(error<=.06),relative_difference_from_scalar_IID_formula=float(agreement)))
    report['all_50_oracle_covariance_MC_checks_pass']=all(row['MC_relative_error_within_0_06'] for group in ('rows','counterexamples') for row in report[group])
    report['temporal_AR_rotating_model_bias']=exact(32,16,.08,mode='temporal_AR')
    if sha(SOURCE)!=source_hash:raise ValueError('Earlier MC changed')
    (out/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print('all_50_oracle_covariance_MC_checks_pass',report['all_50_oracle_covariance_MC_checks_pass'])
    print('counterexample_fullCov_MC_relerr',[(row['mode'],row['MC_relative_error']) for row in report['counterexamples']])
    print('AR_phase_of_expected_lag_bias',report['temporal_AR_rotating_model_bias']['phase_of_expected_lag_minus_true_omega'])

if __name__=='__main__':main()
