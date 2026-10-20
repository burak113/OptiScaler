"""CPU multiscale innovation prototype. No shipping code, no quality claim."""
import numpy as np

def split(x):
 a,b,c,d=x[0::2,0::2],x[0::2,1::2],x[1::2,0::2],x[1::2,1::2]
 return [(a+b+c+d)*.25,(a-b+c-d)*.25,(a+b-c-d)*.25,(a-b-c+d)*.25]
def merge(a,b,c,d):
 out=np.empty((a.shape[0]*2,a.shape[1]*2,a.shape[2]),'f4')
 out[0::2,0::2]=a+b+c+d;out[0::2,1::2]=a-b+c-d
 out[1::2,0::2]=a+b-c-d;out[1::2,1::2]=a-b-c+d
 return out
def shrink(d,v,k):return np.sign(d)*np.maximum(abs(d)-k*np.sqrt(np.maximum(v,0)),0)
def correction(residual,variance,levels=6,k=3,min_level=4):
 stack=[];a=residual;v=variance
 for level in range(levels):
  a,b,c,d=split(a);v=split(v)[0]*.25
  stack.append(tuple(shrink(t,v,k) if level+1>=min_level else np.zeros_like(t) for t in (b,c,d)))
 a=shrink(a,v,k)
 for b,c,d in reversed(stack):a=merge(a,b,c,d)
 return a
def estimate_variance(x,block=8):
 h,w,_=x.shape;tiles=x.reshape(h//block,block,w//block,block,3)
 # Within-block scene variation conservatively increases uncertainty.
 v=np.maximum((tiles*tiles).mean((1,3))-tiles.mean((1,3))**2,0)
 return np.repeat(np.repeat(v,block,0),block,1)
def apply(x,y,k=3,levels=6,phases=(0,16,32,48)):
 v=estimate_variance(x);delta=np.zeros_like(y)
 for phase in phases:
  r=np.roll(x-y,(phase,phase),(0,1));vv=np.roll(v,(phase,phase),(0,1))
  d=correction(r,vv,levels,k);delta+=np.roll(d,(-phase,-phase),(0,1))/len(phases)
 # Clamping is explicitly measured for bias in controls.
 return np.maximum(y+delta,0),delta
