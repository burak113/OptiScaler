"""Wide, coherent diffuse drift only. Pure CPU experiment; never modifies source."""
import numpy as np
L=np.array([.2126,.7152,.0722],'f4')
def target(x,y,block=32):
 h,w,_=x.shape;hh=h//block*block;ww=w//block*block
 def means(a):return a[:hh,:ww].reshape(hh//block,block,ww//block,block,3).mean((1,3)).reshape(-1,3)
 a,b=means(x),means(y);la=a@L;lb=b@L
 valid=(la>1e-7)&(lb>1e-7)&np.isfinite(a).all(-1)&np.isfinite(b).all(-1)
 a,b,la,lb=a[valid],b[valid],la[valid],lb[valid]
 if len(a)<8:return np.zeros(3,'f4'),0.,{'valid':int(len(a))}
 # No sample clipping: each tile is a paired energy measurement.
 c=np.log(np.maximum(a/la[:,None],.02)/np.maximum(b/lb[:,None],.02))
 q=np.quantile(c,[.2,.5,.8],axis=0);median=q[1]
 # At least80% of cells must support the sign; unrelated local lights do not qualify.
 support=np.where(median>0,q[0],-q[2]);confidence=np.clip((support-.015)/.04,0,1)
 chroma=np.clip(median,-.25,.25)*confidence
 lev=np.quantile(np.log(la/lb),[.2,.5,.8]);level=float(np.clip(lev[1],-.2,0)*np.clip((-lev[2]-.025)/.05,0,1))
 return chroma,level,{'valid':len(a),'quantiles':q.tolist(),'level_quantiles':lev.tolist(),'confidence':confidence.tolist()}
class Filter:
 def __init__(self):self.c=np.zeros(3,'f4');self.l=0.
 def apply(self,x,y):
  c,l,info=target(x,y);self.c+=(c-self.c)*.35;self.l+=(l-self.l)*.35
  out=y*np.exp(self.c);out*=((y@L)/np.maximum(out@L,1e-12))[...,None]
  out*=np.exp(self.l)
  return out,dict(info,chroma=self.c.tolist(),level=self.l)
