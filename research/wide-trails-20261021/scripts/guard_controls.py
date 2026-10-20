import sys,json
from pathlib import Path
import numpy as np
sys.path.insert(0,'E:/FSRD/rrlab')
from rrlab.imgutil import gaussian,LUMA
from temporal_wavelet import Filter
O=Path(__file__).parent
size=128;y,x=np.mgrid[:size,:size];texture=1+.08*np.sin(x*.8)*np.cos(y*.8)
truth=texture[...,None]*np.array([.014,.012,.01],'f4');records=[]
for phase in [0,7,17]:
 for kind in ['static','chromatic_bias','white_bias','local_new_light','protected_detail']:
  rows=[]
  for seed in range(6):
   rng=np.random.default_rng(seed+822);f=Filter(guard=True);gain=np.zeros_like(truth);errors=[];outside=[];flicker=[];previous=None
   for i in range(40):
    target=truth.copy();rr=truth.copy();cut=size//2+phase
    if kind=='chromatic_bias':rr*=np.array([1.18,.95,1.06])
    if kind=='white_bias':rr*=1.15
    if kind=='protected_detail':
     rr*=np.array([1.18,.95,1.06]);rr[:,cut:cut+7]=target[:,cut:cut+7]
    if kind=='local_new_light' and i>=16:
     target[:,:cut]*=np.array([1.15,.97,.85]);rr=target.copy() # RR already correct: filter must not undo it.
    inp=target*rng.lognormal(-2,2,target.shape).astype('f4')
    coarse,_=f.apply(inp,rr,i=i)
    den=gaussian(rr.transpose(2,0,1),24).transpose(1,2,0)
    desired=np.clip((coarse-rr)/np.maximum(den,1e-6),-.3,.3)
    if i>=2:gain+=.25*(desired-gain)
    gain[f.changed]=0;out=rr*(1+gain)
    if i>=16:
     norm=float((target@LUMA).mean());errors.append(float(abs(out-target).mean()/norm))
     outside.append(float(abs(out[:,cut+8:]-rr[:,cut+8:]).mean()/norm))
     if previous is not None:flicker.append(float(abs(out-previous).mean()/norm))
    previous=out
   rows.append(dict(error=float(np.mean(errors)),outside=float(np.max(outside)),flicker=float(np.mean(flicker))))
  r=dict(phase=phase,case=kind,mean={k:float(np.mean([a[k] for a in rows])) for k in rows[0]},max_outside=max(a['outside'] for a in rows));records.append(r);print(json.dumps(r),flush=True)
(O/'guard-controls.json').write_text(json.dumps(records,indent=2))
