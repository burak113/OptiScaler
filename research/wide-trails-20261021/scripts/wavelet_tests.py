import sys,json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,'E:/FSRD/rrlab')
from rrlab.captures import Capture
from rrlab.imgutil import LUMA,tonemap
from wavelet_probe import apply
O=Path(__file__).parent
results=[]
# Known truth with low-contrast light-only edge and no guide difference.
# Independent positive heavy-tail noise, texture retained in the baseline.
n=256;yy,xx=np.mgrid[:n,:n];tex=1+.08*np.sin(xx*.8)*np.cos(yy*.8)
truth=np.ones((n,n,3),'f4')*np.array([.014,.012,.010])*tex[...,None]
for phase in [0,7,19,31]:
 edge=128+phase;changed=truth.copy();changed[:,:edge]*=[1.15,.95,.85]
 for strength in [1.,2.]:
  for k in [2,3,4]:
   records=[]
   for seed in range(8):
    rng=np.random.default_rng(seed+723);noise=rng.lognormal(-strength**2/2,strength,truth.shape).astype('f4')
    source=changed*noise
    out,delta=apply(source,truth,k=k)
    # Separate correction of stale colour from harm in unchanged region.
    left=np.s_[:,32:edge-32];right=np.s_[:,edge+16:-16]
    norm=float((truth@LUMA).mean())
    records.append(dict(response=float(np.mean(abs(out[left]-changed[left]))/np.mean(abs(truth[left]-changed[left]))),unchanged=float(np.mean(abs(out[right]-truth[right]))/norm),bias=float((out[right]-truth[right]).mean()/norm)))
   r=dict(phase=phase,noise_sigma=strength,k=k,mean={key:float(np.mean([a[key] for a in records])) for key in records[0]},worst_unchanged=max(a['unchanged'] for a in records));results.append(r)
(O/'wavelet-controls.json').write_text(json.dumps(results,indent=2));print('synthetic',json.dumps(results[:6]),flush=True)
# Application to actual captured raw RR: no additional replay or truth assertion.
for prefix,frame in [('c37d',60),('87ee',60),('22f9',50)]:
 c=Capture(prefix);x=c.img(frame,'input_diffuse')[...,:3];y=c.img(frame,'raw_rr_diffuse')[...,:3];spec=c.img(frame,'raw_rr_specular')[...,:3]
 out,delta=apply(x,y,k=3)
 exp=1/max(float(np.quantile((y+spec)@LUMA,.75)),1e-10);im=Image.new('RGB',(c.W*2,c.H+28));d=ImageDraw.Draw(im)
 for j,a in enumerate([y+spec,out+spec]):
  im.paste(Image.fromarray(tonemap(a,exp)),(j*c.W,28));d.text((j*c.W+5,5),['Captured RR','Multiscale innovation prototype'][j],fill='white')
 im.save(O/f'wavelet-{c.id}.png')
 print(c.id,frame,'change',float(np.mean(abs(out-y))/np.mean(y)),flush=True)
