import sys,json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,'E:/FSRD/rrlab')
from rrlab.captures import Capture
from rrlab.imgutil import LUMA,tonemap
from consensus_probe import Filter,target
O=Path(__file__).parent;records=[]
for prefix in ['c37d','87ee','22f9','2405','d6d2','f2ef']:
 c=Capture(prefix);f=Filter();seq=[];a=np.lib.format.open_memmap(O/f'{c.id}-consensus.npy',mode='w+',dtype='f2',shape=(c.n,c.H,c.W,3))
 for i in range(c.n):
  x=c.img(i,'input_diffuse')[...,:3];y=c.img(i,'raw_rr_diffuse')[...,:3]
  a[i],r=f.apply(x,y);seq.append(r)
 a.flush();records.append(dict(capture=c.id,frames=seq))
 frame={'c37d':60,'87ee':60,'22f9':50,'2405':185,'d6d2':127,'f2ef':49}[prefix]
 old=c.rgb(frame,'raw');new=a[frame].astype('f4')+c.img(frame,'raw_rr_specular')[...,:3]
 exp=1/max(float(np.quantile(old@LUMA,.75)),1e-10);im=Image.new('RGB',(2*c.W,c.H+28));d=ImageDraw.Draw(im)
 for j,img in enumerate([old,new]):
  im.paste(Image.fromarray(tonemap(img,exp)),(j*c.W,28));d.text((j*c.W+5,5),['Captured raw RR','Coherent drift prototype'][j],fill='white')
 im.save(O/f'consensus-{c.id}.png');print(c.id,frame,seq[frame],flush=True)
(O/'consensus.json').write_text(json.dumps(records,indent=2))
# Ground-truth controls: global diffuse bias plus a protected correct-colour patch;
# local-only true light change; static heavy-tail noise. Multiple noise realizations.
n=256;y,x=np.mgrid[:n,:n];truth=np.ones((n,n,3),'f4')*np.array([.014,.012,.010])
results=[]
for mode in ['static','global_chroma','global_level','local_light','protected_neon']:
 rows=[]
 for seed in range(12):
  rng=np.random.default_rng(seed+736);f=Filter();desired=truth.copy();rr=truth.copy()
  if mode=='global_chroma':rr*=np.array([1.18,.95,1.06])
  if mode=='global_level':rr*=1.15
  if mode=='local_light':desired[64:192,64:192]*=[1.2,.9,.8]
  if mode=='protected_neon':
   rr*=np.array([1.18,.95,1.06]);desired[100:120]=[.04,.002,.003];rr[100:120]=desired[100:120]
  for i in range(32):
   inp=desired*rng.lognormal(-2,2,desired.shape).astype('f4');out,_=f.apply(inp,rr)
  norm=float((desired@LUMA).mean());outside=np.ones((n,n),bool);outside[64:192,64:192]=False
  rows.append({'error':float(abs(out-desired).mean()/norm),'baseline_error':float(abs(rr-desired).mean()/norm),'outside':float(abs(out[outside]-rr[outside]).mean()/norm),'protected':float(abs(out[100:120]-desired[100:120]).mean()/norm)})
 r={'mode':mode,'averages':{k:float(np.mean([x[k] for x in rows])) for k in rows[0]},'max_outside':max(x['outside'] for x in rows)};results.append(r);print(json.dumps(r),flush=True)
(O/'consensus-controls.json').write_text(json.dumps(results,indent=2))
