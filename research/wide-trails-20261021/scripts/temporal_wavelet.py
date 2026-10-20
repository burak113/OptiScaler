import numpy as np
from wavelet_probe import estimate_variance,correction
class Filter:
 def __init__(self,alpha=.3,k=3,guard=False):self.mean=None;self.var=None;self.alpha=alpha;self.k=k;self.i=-1;self.guard=guard;self.changed=None
 def apply(self,x,y,c=None,i=0):
  h,w,_=x.shape;pad=((0,(-h)%64),(0,(-w)%64),(0,0));xx=np.pad(x,pad,mode='edge')
  vx=estimate_variance(xx)[:h,:w]
  self.changed=np.zeros((h,w),bool)
  if self.mean is None:m=x.copy();v=vx.copy()
  else:
   ok=np.ones((h,w),bool);m=self.mean;v=self.var
   if c is not None:
    m,ok=c.warp(i,self.i,m);v,_=c.warp(i,self.i,v)
    prevz,_=c.warp(i,self.i,abs(c.depth(self.i)));z=abs(c.depth(i));ok&=abs(prevz-z)<np.maximum(z*.02,1e-4)
    if c.motion()[0][i]>3:ok[:]=False
   if self.guard:
    from rrlab.imgutil import gaussian
    blur=lambda z:gaussian(z.transpose(2,0,1),16).transpose(1,2,0)
    now=blur(x);previous=blur(m);variance=blur(vx+v)*2/(4*np.pi*16**2)
    difference=abs(now-previous)
    self.changed=np.any((difference>3.5*np.sqrt(np.maximum(variance,1e-12)))&(difference>np.maximum(now,previous)*.075),axis=-1)&ok
    ok&=~self.changed
   a=self.alpha;m=np.where(ok[...,None],m*(1-a)+x*a,x)
   v=np.where(ok[...,None],v*(1-a)**2+vx*a*a,vx)
  self.mean=m.astype('f4');self.var=v.astype('f4');self.i=i
  r=np.pad(m-y,pad,mode='edge');v=np.pad(v,pad,mode='edge')*2 # conservative correlation allowance
  delta=np.zeros_like(r)
  for phase in (0,16,32,48):
   d=correction(np.roll(r,(phase,phase),(0,1)),np.roll(v,(phase,phase),(0,1)),6,self.k,4)
   delta+=np.roll(d,(-phase,-phase),(0,1))*.25
  return np.maximum(y+delta[:h,:w],0),delta[:h,:w]
