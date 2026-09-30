"""Verify a nominal lag-phase formula without pretending it is game confidence."""
from pathlib import Path
import hashlib,json
import numpy as np

SEED=950411;TRIALS=16384;BATCH=256
S=np.array([.035,.021*np.exp(.3j),.010*np.exp(-.2j)])
ENERGY=float(np.sum(abs(S)**2))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def measure(rng,m,ratio,omega,varying=False,mode='IID'):
    q=np.full(m,ENERGY/(3*ratio))
    if varying:q*=np.linspace(.5,1.5,m)
    angles=[];imag=[];plugin_var=[];mean_errors=[];bounds=[];derivative_errors=[];substitution_errors=[];selected=[]
    lag_phase=np.exp(-1j*omega);time=np.arange(m);age=m-time
    truth=S*np.exp(1j*omega*m);clean=np.exp(1j*omega*time)[:,None]*S
    true_var=ENERGY*(q[0]+q[-1])/2+3*np.sum(q[1:]*q[:-1])/2
    true_angle_var=true_var/((m-1)*ENERGY)**2
    for offset in range(0,TRIALS,BATCH):
        count=min(BATCH,TRIALS-offset)
        noise=(rng.normal(size=(count,m,3))+1j*rng.normal(size=(count,m,3)))*np.sqrt(q[None,:,None]/2)
        if mode=='channel_correlated':
            common=(rng.normal(size=(count,m,1))+1j*rng.normal(size=(count,m,1)))*np.sqrt(q[None,:,None]/2)
            noise=np.sqrt(.2)*noise+np.sqrt(.8)*common
        elif mode=='temporal_AR':
            for j in range(1,m):noise[:,j]=.8*noise[:,j-1]+.6*noise[:,j]
        f=clean[None,:,:]+noise
        c=np.sum(f[:,1:]*np.conj(f[:,:-1]),axis=(1,2))
        theta=np.angle(c);angle=np.angle(c*lag_phase)
        A=np.mean(np.sum(abs(f[:,1:])**2,axis=-1),axis=1)
        B=np.mean(np.sum(abs(f[:,:-1])**2,axis=-1),axis=1)
        energy=np.maximum((A+B-3*np.mean(q[1:])-3*np.mean(q[:-1]))/2,0)
        variance=energy*(q[0]+q[-1])/2+3*np.sum(q[1:]*q[:-1])/2
        phase_var=variance/abs(c)**2
        rotation=np.exp(1j*theta[:,None]*age[None,:])
        predicted=np.mean(f*rotation[...,None],axis=1)
        derivative=1j*np.mean(f*(age[None,:]*rotation)[...,None],axis=1)
        delta=1e-6
        upper=np.mean(f*np.exp(1j*(theta[:,None]+delta)*age[None,:])[...,None],axis=1)
        lower=np.mean(f*np.exp(1j*(theta[:,None]-delta)*age[None,:])[...,None],axis=1)
        finite=(upper-lower)/(2*delta)
        relative=np.max(abs(finite-derivative),axis=1)/np.maximum(np.max(abs(derivative),axis=1),1e-30)
        substitute=1j*float(age.mean())*predicted
        base_variance=float(q.sum())/(m*m)
        nominal_upper=(np.sqrt(base_variance)+abs(derivative)*np.sqrt(phase_var[:,None]))**2
        angles.extend(angle.tolist());imag.extend(np.imag(c*lag_phase).tolist());plugin_var.extend(phase_var.tolist())
        mean_errors.extend(np.mean(abs(predicted-truth[None,:])**2,axis=1).tolist())
        bounds.extend(nominal_upper.mean(axis=1).tolist());derivative_errors.extend(relative.tolist())
        substitution_errors.extend(np.mean(abs(derivative-substitute)**2,axis=1).tolist())
        selected.extend((abs(theta)>3*np.sqrt(phase_var)).tolist())
    empirical_imag=float(np.var(imag,ddof=1));empirical_angle=float(np.var(angles,ddof=1))
    return dict(m=m,power_ratio=ratio,omega=omega,varying_q=varying,noise_mode=mode,trials=TRIALS,
        exact_IID_imaginary_variance=float(true_var),empirical_imaginary_variance=empirical_imag,
        relative_imaginary_variance_error=float(abs(empirical_imag/true_var-1)),
        true_linearized_angle_variance=float(true_angle_var),empirical_angle_variance=empirical_angle,
        mean_plugin_angle_variance=float(np.mean(plugin_var)),nominal_3SE_nonzero_phase_fraction=float(np.mean(selected)),
        empirical_predicted_mean_MSE=float(np.mean(mean_errors)),mean_first_order_nominal_Cauchy_upper=float(np.mean(bounds)),
        maximum_exact_derivative_finite_difference_relative_error=float(np.max(derivative_errors)),
        mean_age_substitution_derivative_RMS_error=float(np.sqrt(np.mean(substitution_errors))),
        formula_IID_assumptions_satisfied=mode=='IID')

def main():
    folder=Path(__file__).resolve().parent;out=folder/'evidence'
    if out.exists():raise ValueError('Preserve phase uncertainty model check')
    out.mkdir();rng=np.random.default_rng(SEED)
    report=dict(schema='nominal-lag-phase-uncertainty-independent-model-check-v1',status='running',quality_accepted=False,
        native_RR_dispatches=0,conversion_dispatches=0,source_sha256=sha(__file__),
        preregistration_sha256=sha(folder/'preregistration.md'),numpy_version=np.__version__,seed=SEED,
        trials_per_case=TRIALS,batch=BATCH,rows=[],counterexamples=[],
        qualification='Oracle constant-amplitude circular-IID simulation validates algebra, not a radiance estimator or exact confidence bound.')
    def save():(out/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    save()
    for m in (8,16,32,64):
        for ratio in (16,64,1000):
            for omega in (0,.08):
                for varying in (False,True):
                    row=measure(rng,m,ratio,omega,varying)
                    row['exact_variance_MC_gate_pass']=row['relative_imaginary_variance_error']<=.06
                    row['exact_derivative_gate_pass']=row['maximum_exact_derivative_finite_difference_relative_error']<=1e-7
                    report['rows'].append(row);save()
        print('completed_phase_formula_m',m,flush=True)
    for mode in ('channel_correlated','temporal_AR'):
        report['counterexamples'].append(measure(rng,32,16,0,mode=mode));save()
    report['all_48_IID_formula_and_derivative_checks_pass']=all(row['exact_variance_MC_gate_pass'] and row['exact_derivative_gate_pass'] for row in report['rows'])
    report['status']='completed_model_check_not_quality_solution';save()
    print('all_48_IID_formula_and_derivative_checks_pass',report['all_48_IID_formula_and_derivative_checks_pass'],flush=True)
    print('max_MC_relative_error',max(row['relative_imaginary_variance_error'] for row in report['rows']),flush=True)
    print('counterexample_empirical_to_nominal_imag_var',[(row['noise_mode'],row['empirical_imaginary_variance']/row['exact_IID_imaginary_variance']) for row in report['counterexamples']],flush=True)

if __name__=='__main__':main()
