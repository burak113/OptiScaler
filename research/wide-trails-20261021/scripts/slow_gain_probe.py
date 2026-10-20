import sys,json
from pathlib import Path
import numpy as np
sys.path.insert(0,'E:/FSRD/rrlab')
from rrlab.captures import Capture
from rrlab.imgutil import gaussian
O=Path(__file__).parent

def process(c,provider,coarse,alpha=.1,rotation_limit=.1,tag='slow-gain',guards=None):
 out=np.lib.format.open_memmap(O/f'{c.id}-{tag}.npy',mode='w+',dtype='f2',shape=(c.n,c.H,c.W,3))
 gain=np.zeros((c.H,c.W,3),'f4');rot,tr=c.motion();still=0
 for i in range(c.n):
  y=provider(i);candidate=coarse(i)
  den=gaussian(y.transpose(2,0,1),24).transpose(1,2,0)
  target=np.clip((candidate-y)/np.maximum(den,1e-6),-.3,.3)
  if i:
   gain,ok=c.warp(i,i-1,gain);prevz,_=c.warp(i,i-1,abs(c.depth(i-1)))
   z=abs(c.depth(i));ok&=abs(prevz-z)<np.maximum(z*.02,1e-4);gain[~ok]=0
  moving=rot[i]>rotation_limit or tr[i]>.0015
  still=0 if moving else still+1
  if moving:gain[:]=0
  elif still>=3:gain+=alpha*(target-gain)
  if guards is not None:gain[guards(i)]=0
  out[i]=np.maximum(y*(1+gain),0)
 out.flush();return out

if __name__=='__main__':
 for prefix in ['c37d','87ee','22f9','d6d2','f2ef','2405']:
  c=Capture(prefix);coarse=np.load(O/f'{c.id}-temporal-wavelet.npy',mmap_mode='r')
  opts=dict(alpha=.25,rotation_limit=3,tag='fast-gain') if 'fast' in sys.argv else {}
  process(c,lambda i:c.img(i,'raw_rr_diffuse')[...,:3],lambda i:coarse[i].astype('f4'),**opts)
  print(c.id,'done',flush=True)
