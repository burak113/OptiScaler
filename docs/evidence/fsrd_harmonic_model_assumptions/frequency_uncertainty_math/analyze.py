"""Read-only local oracle uncertainty; not a source estimator."""
from pathlib import Path
import hashlib
import json
import numpy as np

HERE=Path(__file__).resolve().parent
SIGMA=np.array([.012,.010,.014])

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def basis(freqs,h=30,w=40):
    yy,xx=np.indices((h,w),dtype=float)
    coord=np.stack(((xx-(w-1)/2)/w,(yy-(h-1)/2)/h),axis=-1).reshape(-1,2)
    columns=[np.ones(h*w)]
    derivatives=[]
    for freq in freqs:
        phase=2*np.pi*(coord@freq)
        c,s=np.cos(phase),np.sin(phase)
        columns.extend((c-c.mean(),s-s.mean()))
        dc=-2*np.pi*s[:,None]*coord
        ds=2*np.pi*c[:,None]*coord
        derivatives.append(np.stack((dc-dc.mean(0),ds-ds.mean(0)),axis=1))
    return np.stack(columns,axis=1),derivatives

def rank_columns(x):
    keep=[]
    for j in range(x.shape[1]):
        trial=x[:,keep+[j]]
        sv=np.linalg.svd(trial,compute_uv=False)
        if sv[-1] >64*np.finfo(float).eps*sv[0]:keep.append(j)
    return keep

def field_derivative(derivatives,beta):
    # beta shape physical full columns x RGB; frequencies ordered fx,fy peratom.
    return np.concatenate([np.einsum('naf,ar->nrf',d,beta[1+2*k:3+2*k]) for k,d in enumerate(derivatives)],axis=2)

def check_derivative():
    freqs=np.array([[2.37,1.19],[5.43,-2.21]])
    x,ds=basis(freqs,8,12)
    beta=np.array([[.3,.4,.5],[.05,.02,.04],[-.02,.04,.01],[.04,.03,.05],[.01,.02,-.03]])
    analytic=field_derivative(ds,beta)
    maximum=0.
    for k in range(2):
        for q in range(2):
            plus=freqs.copy(); minus=freqs.copy()
            plus[k,q]+=1e-5;minus[k,q]-=1e-5
            numerical=(basis(plus,8,12)[0]@beta-basis(minus,8,12)[0]@beta)/(2e-5)
            maximum=max(maximum,float(np.max(abs(numerical-analytic[:,:,2*k+q]))))
    assert maximum<2e-10
    return maximum

def evaluate(name,freqs,amplitude=1):
    x,ds=basis(np.array(freqs,float))
    mask=np.random.default_rng(718315).random(len(x))<.8
    keep=rank_columns(x[mask])
    design=x[mask][:,keep]
    gram=design.T@design
    gamma=np.linalg.inv(gram)
    projector=design@gamma@design.T
    beta=np.zeros((x.shape[1],3));beta[0]=[.3,.4,.5]
    for k in range(len(freqs)):
        beta[1+2*k]=amplitude*np.array([.05,.035,.042])/(k+1)
        beta[2+2*k]=amplitude*np.array([-.018,.027,.011])/(k+1)
    # Omitted numerical columns have no physically observable coefficient.
    for j in range(x.shape[1]):
        if j not in keep:beta[j]=0
    df=field_derivative(ds,beta)
    fisher=np.zeros((2*len(freqs),2*len(freqs)))
    for channel in range(3):
        train=df[mask,channel]
        residual=train-projector@train
        fisher+=8*(residual.T@residual)/(SIGMA[channel]**2)
    eigen=np.linalg.eigvalsh(fisher)
    conditional_energy=0.;pair_checks=[]
    atom_design=x[:,keep].copy();atom_design[:,keep.index(0)]=0
    for channel in range(3):
        conditional_energy+=SIGMA[channel]**2*np.sum((atom_design@gamma)*atom_design)
    for atom in range(len(freqs)):
        if 1+2*atom in keep and 2+2*atom in keep:
            indices=[keep.index(1+2*atom),keep.index(2+2*atom)]
            pair=gamma[np.ix_(indices,indices)]
            # z=(beta_cos-i beta_sin)/2; circular envelope real cov q/2 I.
            lam=float(np.linalg.eigvalsh(pair)[-1])
            cov=pair*np.array([[1,-1],[-1,1]])/4
            envelope=np.eye(2)*lam/4
            minimum=float(np.linalg.eigvalsh(envelope-cov)[0])
            assert minimum>-1e-15
            pair_checks.append({'atom':atom,'envelope_minus_cov_min_eigen_sigma1':minimum})
    record={'case':name,'true_oracle_frequency':freqs,'train_pixels':int(mask.sum()),
            'physical_columns_retained':keep,'training_Gram_condition':float(np.linalg.cond(gram)),
            'nominal_conditional_current_atom_RMS':float(np.sqrt(conditional_energy/(len(x)*3))),
            'frequency_information_eigenvalues':eigen.tolist(),'conditional_pair_envelope_checks':pair_checks}
    if eigen[-1]<=0 or eigen[0]<1e-12*max(1.,eigen[-1]):
        record.update(frequency_information_status='singular_nonregular_no_inverse',frequency_uncertainty_is_zero=False)
        return record
    covf=np.linalg.inv(fisher)
    propagated=0.
    for channel in range(3):
        # Current beta refits at perturbed learned frequency. Intercept is nuisance,
        # omitted in the predicted atom; global mean is held by the residual.
        sensitivity=df[:,channel]-atom_design@gamma@design.T@df[mask,channel]
        propagated+=np.sum((sensitivity@covf)*sensitivity)
    record.update(frequency_information_status='invertible_local_oracle',
            nominal_past8_frequency_SE_bins=np.sqrt(np.diag(covf)).tolist(),
            nominal_extra_current_atom_RMS_from_frequency=float(np.sqrt(propagated/(len(x)*3))),
            omitted_frequency_variance_over_conditional=float(propagated/conditional_energy),
            total_local_RMS_over_conditional=float(np.sqrt(1+propagated/conditional_energy)))
    return record

def schur_selfcheck():
    freqs=np.array([[2.37,1.19]])
    x,ds=basis(freqs,8,12);beta=np.array([[.3,.4,.5],[.05,.03,.04],[-.02,.04,.01]])
    df=field_derivative(ds,beta)
    # Two pastframes, each with its own RGB nuisance beta; shared frequencies.
    size=2*3*x.shape[1]+2
    joint=np.zeros((2*len(x)*3,size));cursor=0
    for frame in range(2):
        for channel in range(3):
            rows=slice(cursor,cursor+len(x));cursor+=len(x)
            cols=slice((frame*3+channel)*x.shape[1],(frame*3+channel+1)*x.shape[1])
            joint[rows,cols]=x/SIGMA[channel]
            joint[rows,-2:]=df[:,channel]/SIGMA[channel]
    inv=np.linalg.inv(joint.T@joint)
    gamma=np.linalg.inv(x.T@x)
    schur=np.zeros((2,2))
    for channel in range(3):
        projected=df[:,channel]-x@gamma@x.T@df[:,channel]
        schur+=2*projected.T@projected/SIGMA[channel]**2
    relative=float(np.max(abs(inv[-2:,-2:]-np.linalg.inv(schur)))/np.max(abs(inv[-2:,-2:])))
    assert relative<2e-12
    return relative

def main():
    freeze=json.loads((HERE/'pre_measurement_freeze.json').read_text())
    assert all(sha(HERE/k)==v for k,v in freeze['sources'].items())
    checks={'derivative_max_error':check_derivative(),'joint_inverse_Schur_relative_error':schur_selfcheck()}
    rows=[evaluate('one_offgrid',[[2.37,1.19]]),
          evaluate('two_offgrid',[[3.1,1.],[5.43,-2.21]]),
          evaluate('two_close',[[3.1,1.],[3.35,1.15]]),
          evaluate('near_DC',[[1.03,.05]]),
          evaluate('weak_one_offgrid',[[2.37,1.19]],.1),
          evaluate('one_Nyquist',[[20.,0.]])]
    assert all(sha(HERE/k)==v for k,v in freeze['sources'].items())
    results={'schema':'harmonic-frequency-local-oracle-math-v1',
             'status':'completed_math_not_estimator_or_quality', 'quality_accepted':False,
             'prototype_changed':False,'native_measured':False,'pre_measurement_freeze':freeze,
             'selfchecks':checks,'rows':rows}
    (HERE/'results.json').write_text(json.dumps(results,indent=2,allow_nan=False)+'\n')
    print(json.dumps(results,indent=2))

if __name__=='__main__':main()
