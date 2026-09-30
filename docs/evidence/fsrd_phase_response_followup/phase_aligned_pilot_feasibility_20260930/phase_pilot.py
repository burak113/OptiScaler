"""Preregistered source-only past-phase pilot; CPU feasibility, not native quality."""
import numpy as np

def make_phase_aligned_pilot(raw,controls):
 c=np.asarray(raw,float);ctrl=np.asarray(controls,float)
 if c.ndim!=4 or c.shape[-1]!=3 or not len(c) or min(c.shape[1:3])<8:raise ValueError('N,H,W,RGB >=8 required')
 if not np.isfinite(c).all() or np.any(c<0) or np.any(c>65504):raise ValueError('Valid source radiance required')
 if ctrl.shape!=(len(c),3) or not np.isfinite(ctrl).all() or not np.isin(ctrl[:,0],[0,1]).all():raise ValueError('reset,jitter controls required')
 nframes,h,w,_=c.shape;n=h*w;end=-1 if w%2==0 else None
 out=c.copy();active=np.zeros(nframes,bool);past=[];sigmas=[];records=[];epoch=0
 boundary=[0]+([w//2] if w%2==0 else [])
 for i,frame in enumerate(c):
  reset=bool(ctrl[i,0]);jitter=bool(i and not np.array_equal(ctrl[i,1:],ctrl[i-1,1:]))
  if reset or jitter:past.clear();sigmas.clear();epoch=i
  current=np.fft.rfft2(frame,axes=(0,1))/n
  sigma=max(float(np.median(abs(current[:,1:end,:])))*np.sqrt(n/np.log(2)),np.finfo(float).eps*max(1.,float(frame.max())))
  m=len(past);theta=np.zeros(current.shape[:2]);qualified=np.zeros_like(theta,bool);coherence=np.zeros_like(theta);power_ratio=np.zeros_like(theta)
  if m>=8:
   old=np.stack(past);a=old[1:];b=old[:-1];q=np.asarray(sigmas)**2/n
   A=np.mean(np.sum(abs(a)**2,-1),0);B=np.mean(np.sum(abs(b)**2,-1),0)
   qa=3*np.mean(q[1:]);qb=3*np.mean(q[:-1]);C=np.sum(np.sum(a*np.conj(b),-1),0)
   coherence=np.divide(abs(C),(m-1)*np.sqrt(A*B),out=np.zeros_like(A),where=(A*B)>0)
   power_ratio=np.minimum(np.maximum(A-qa,0)/qa,np.maximum(B-qb,0)/qb)
   qualified=(power_ratio>16)&(coherence>=.8);theta=np.where(qualified,np.angle(C),0.)
   # Boundary x-columns represent conjugate y-pairs. Enforce real-source
   # symmetry; only one member defines phase, both must qualify.
   for x in boundary:
    theta[0,x]=0;qualified[0,x]=False
    for y in range(1,(h+1)//2):
     j=(-y)%h;ok=bool(qualified[y,x] and qualified[j,x]);qualified[y,x]=qualified[j,x]=ok
     t=theta[y,x] if ok else 0.;theta[y,x]=t;theta[j,x]=-t
    if h%2==0:theta[h//2,x]=0;qualified[h//2,x]=False
  theta[0,0]=0;qualified[0,0]=False
  innovation=np.zeros_like(theta,bool)
  if m:
   aligned=[f*np.exp(1j*theta*(m-j))[...,None] for j,f in enumerate(past)]
   previous=sum(aligned)/m;prior_var=sum(s*s for s in sigmas)/(m*m)
   limit=3*np.sqrt(sigma*sigma+prior_var)/np.sqrt(n)
   innovation=np.any(abs(current-previous)>limit,-1)
   mean=(sum(aligned)+current)/(m+1);mean_sigma=np.sqrt(sum(s*s for s in sigmas)+sigma*sigma)/(m+1)
  else:mean=current.copy();mean_sigma=sigma;limit=None
  innovation[0,0]=False;selected=np.where(innovation[...,None],current,mean);selected[0,0]=current[0,0]
  selected_sigma=np.where(innovation,sigma,mean_sigma)
  keep=np.max(abs(selected),-1)>4*selected_sigma/np.sqrt(n);keep[0,0]=True
  prediction=np.fft.irfft2(selected*keep[...,None]*n,s=(h,w),axes=(0,1))
  valid=bool(np.isfinite(prediction).all() and prediction.min()>=0 and prediction.max()<=65504)
  if valid:out[i]=prediction;active[i]=True
  records.append(dict(frame=i,active=valid,epoch_start=epoch,reset=reset,jitter_changed=jitter,preceding_observations=m,total_observations=m+1,
   nominal_iid_pixel_sigma=sigma,nominal_mean_pixel_sigma=float(mean_sigma),innovation_nominal_threshold=limit,
   phase_qualified_frequencies=int(qualified.sum()),retained_frequencies=int(keep.sum()),
   retained_phase_qualified_frequencies=int((keep&qualified).sum()),retained_innovation_frequencies=int((keep&innovation).sum()),
   max_qualified_phase_increment=float(abs(theta[qualified]).max()) if qualified.any() else None,
   minimum_qualified_coherence=float(coherence[qualified].min()) if qualified.any() else None,
   minimum_qualified_power_ratio=float(power_ratio[qualified].min()) if qualified.any() else None,
   prediction_min=float(prediction.min()),prediction_max=float(prediction.max()),
   phase_estimator_uses_current=False,current_DC=True,effective_independent_pixels=None,
   reason='accepted' if valid else 'invalid_unclamped_prediction_raw_fallback'))
  past.append(current);sigmas.append(sigma)
  if len(past)>=64:past.pop(0);sigmas.pop(0)
 return out,active,dict(schema='phase-aligned-source-only-pilot-feasibility-v1',history=64,frames=records,quality_accepted=False,no_clean_truth_input=True,guide_inputs=False,native_measured=False,
  phase_parameter_uncertainty_in_nominal_variance=False,effective_independent_pixels=None,
  limitations=['Spatial/temporal iid and periodic correspondence assumed, not proven','Phase estimator uncertainty omitted from nominal innovation/support variance',
   'Slow amplitude/phase acceleration and low-SNR modes can lag or spuriously innovate','Shared source bias remains unidentifiable','Current DC noise and hard-support churn remain','No native response or game quality acceptance'])
