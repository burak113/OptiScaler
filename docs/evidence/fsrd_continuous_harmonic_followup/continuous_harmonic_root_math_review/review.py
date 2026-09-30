"""Independent physical OLS and variable-projection gradient checks."""
from pathlib import Path
import hashlib
import importlib.util
import json
import inspect
import numpy as np

ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha')
HERE=Path(__file__).resolve().parent
MODULE=ROOT/'tools_tmp/source_continuous_harmonic_feasibility_20260930/harmonic_pilot.py'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
spec=importlib.util.spec_from_file_location('root_reviewed_harmonic_pilot',MODULE)
pilot=importlib.util.module_from_spec(spec);spec.loader.exec_module(pilot)

def physical(freqs,h,w):
    yy,xx=np.indices((h,w),dtype=float)
    coordinates=np.stack(((xx-(w-1)/2)/w,(yy-(h-1)/2)/h),axis=-1)
    columns=[np.ones((h,w))]
    for freq in freqs:
        z=np.exp(2j*np.pi*np.sum(coordinates*freq,axis=-1))
        columns.extend((z.real-z.real.mean(),z.imag-z.imag.mean()))
    return np.stack(columns,axis=-1)

def main():
    original_sha=sha(MODULE)
    rng=np.random.default_rng(383173)
    h,w=14,20;nf=8;freqs=np.array([[3.17,1.42],[6.37,-2.15]])
    x=physical(freqs,h,w);mask=pilot.mask_for(h,w)
    beta=rng.normal(0,.03,(nf,len(x[0,0]),3));beta[:,0]=[.3,.4,.5]
    observed=np.einsum('hwk,nkc->nhwc',x,beta)+rng.normal(0,.012,(nf,h,w,3))
    model=pilot.fit_model(freqs.tolist(),observed,mask)
    assert model is not None and model['chosen']==list(range(5))
    xt=x[mask];y=observed[:,mask,:].transpose(1,0,2).reshape(mask.sum(),-1)
    independent_beta=np.linalg.lstsq(xt,y,rcond=None)[0]
    independent_gamma=np.linalg.inv(xt.T@xt)
    beta_error=float(np.max(abs(model['beta']-independent_beta)))
    gamma_error=float(np.max(abs(model['gamma']-independent_gamma)))
    basis_error=float(np.max(abs(model['full']-x)))
    assert beta_error<3e-14 and gamma_error<3e-14 and basis_error<3e-14
    current=observed[0].copy()
    fitted,atom=pilot.current_fit(model,current,mask)
    current_beta=np.linalg.lstsq(xt,current[mask],rcond=None)[0]
    expected_atom=x[...,1:]@current_beta[1:]
    current_error=float(np.max(abs(atom-expected_atom)))
    atom_dc=float(np.max(abs(atom.mean((0,1)))))
    assert current_error<3e-14 and atom_dc<3e-14
    changed=current.copy();changed[~mask]+=rng.normal(0,100,(int((~mask).sum()),3))
    altered_beta,altered_atom=pilot.current_fit(model,changed,mask)
    assert np.array_equal(fitted,altered_beta) and np.array_equal(atom,altered_atom)
    # Different full-source sigma can change validation cost; this verifies only
    # conditional current OLS, not an independent acceptance test.
    gradients=[]
    for atom_index in range(2):
        for axis in range(2):
            step=1e-5
            plus=freqs.copy();minus=freqs.copy();plus[atom_index,axis]+=step;minus[atom_index,axis]-=step
            xp=physical(plus,h,w);xm=physical(minus,h,w)
            dx=(xp-xm)/(2*step)
            derivative=dx[mask]@independent_beta
            residual=y-xt@independent_beta
            analytic=-2*float(np.sum(derivative*residual))
            def RSS(design):
                design=design[mask];b=np.linalg.lstsq(design,y,rcond=None)[0]
                return float(np.sum((y-design@b)**2))
            fd=(RSS(xp)-RSS(xm))/(2*step)
            error=abs(analytic-fd)
            assert error<2e-8
            gradients.append({'atom':atom_index,'axis':axis,'profile_RSS_gradient':fd,'analytic_gradient':analytic,'absolute_error':error})
    parameters=list(inspect.signature(pilot.make_continuous_harmonic_pilot).parameters)
    assert parameters==['raw','controls','exposure']
    assert sha(MODULE)==original_sha
    result={'schema':'continuous-harmonic-root-physical-math-review-v1',
        'status':'passed_independent_microchecks_not_quality','quality_accepted':False,'native_measured':False,
        'prototype_sha256':original_sha,'review_script_sha256':sha(Path(__file__)),
        'seed':383173,'shape':[nf,h,w,3],'known_oracle_values_only_in_algebra_check':True,
        'physical_basis_max_error':basis_error,'OLS_beta_max_error':beta_error,'Gamma_max_error':gamma_error,
        'current_atom_max_error':current_error,'current_atom_DC_max_error':atom_dc,
        'changing_validation_pixels_does_not_change_current_conditional_fit':True,
        'profile_RSS_gradients':gradients,'estimator_API_parameters':parameters,
        'limitations':['These checks validate physical coordinates and conditional OLS/gradient algebra',
            'Frequency search, heldout acceptance and final-pilot quality not accepted by this check',
            'Full-source sigma enters heldout acceptance and secondslot reuses the heldout partition']}
    (HERE/'review.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
