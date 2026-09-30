"""Independent direct-history arithmetic and proper complex coefficient check."""
from pathlib import Path
import hashlib,importlib.util,sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
SOURCE=ROOT/'tools_tmp/harmonic_response_dc_innovation_feasibility_20260930/model.py'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 if (HERE/'review.json').exists():raise ValueError('Preserve review')
 assert sha(SOURCE)=='96a1becba58d02e3aa20178be6d205e9aa87d9c9dd283318d5dc118efd4a0ac0'
 spec=importlib.util.spec_from_file_location('dc_under_review',SOURCE);model=importlib.util.module_from_spec(spec);spec.loader.exec_module(model)
 rng=np.random.default_rng(4913);n,h,w=80,16,19
 raw=(.3+rng.normal(0,.008,(n,h,w,3))).astype('f4');raw[40:]+=np.array([.02,-.01,.03],dtype='f4')
 ctrl=np.zeros((n,3));ctrl[0,0]=1
 got,valid,diag=model.make_source_dc_innovation_target(raw,ctrl)
 # No model helper/no state recursion reused: direct suffixes since independently detected last event.
 expected=[];records=[];epoch=0;direct_error=0.;explicit_complex_error=0.
 for i in range(n):
  roi=raw[i,5:-5,5:-5].astype(float);H,W=roi.shape[:2];M=H*W;mean=roi.mean((0,1));z=roi-mean
  xx=np.arange(W);yy=np.arange(H);kxs=range(1,(W+1)//2)
  coefficients=[]
  for ky in range(H):
   for kx in kxs:
    phase=np.exp(-2j*np.pi*(ky*yy[:,None]/H+kx*xx[None,:]/W))
    coefficients.append(np.einsum('xyc,xy->c',z,phase)/M)
  coefficients=np.array(coefficients)
  ff=np.fft.rfft2(z,axes=(0,1))/M;end=-1 if W%2==0 else None
  explicit_complex_error=max(explicit_complex_error,float(np.max(abs(coefficients-ff[:,1:end,:].reshape(-1,3)))))
  sigma=np.maximum(np.median(abs(coefficients),axis=0)*np.sqrt(M/np.log(2)),np.finfo(float).eps*max(1.,float(abs(roi).max())))
  q=sigma*sigma/M
  start=max(epoch,i-63);past=records[start:i];innovation=False
  if past:
   prior=np.mean([r[0]for r in past],axis=0);pq=sum(r[1]for r in past)/len(past)**2
   innovation=bool(np.any(abs(mean-prior)>3*np.sqrt(q+pq)))
  if innovation:epoch=i;past=[]
  target=(sum(r[0]for r in past)+mean)/(len(past)+1)
  tq=(sum(r[1]for r in past)+q)/(len(past)+1)**2
  expected.append(target);records.append((mean,q))
  d=diag['frames'][i]
  assert d['innovation']==innovation and d['dc_epoch']==epoch and d['history_used_including_current']==len(past)+1
  direct_error=max(direct_error,float(np.max(abs(np.array(d['target_q_RGB'])-tq))))
 np.testing.assert_allclose(got,np.array(expected),rtol=0,atol=1e-15);assert valid.all()
 assert explicit_complex_error<1e-16 and direct_error<1e-16
 result={'schema':'source-DC-innovation-root-independent-microcheck-v1','status':'passed_arithmetic_not_quality',
 'quality_accepted':False,'new_native_contexts':0,'model_sha256':sha(SOURCE),'script_sha256':sha(HERE/'review.py'),
 'direct_mean_target_max_error':float(np.max(abs(got-expected))),'direct_target_q_max_error':direct_error,
 'explicit_complex_vs_rFFT_max_error':explicit_complex_error,'shape':[n,h,w],
 'limitations':['Plug-in IID variance not empirical confidence','Independent arithmetic supports only tested validity branch; producer broader checks retained']}
 (HERE/'review.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
