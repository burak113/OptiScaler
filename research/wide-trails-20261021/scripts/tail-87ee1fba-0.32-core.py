import numpy as np
from rrlab.imgutil import LUMA
def prefilter(c,i,name,a):
 if name!='input_diffuse':return a
 out=a.copy();rgb=a[...,:3]
 ratio=np.minimum(1.,0.32/np.maximum(rgb@LUMA,1e-10))
 core=rgb*ratio[...,None]
 out[...,:3]=core if 'core'=='core' else np.maximum(rgb-core,0)
 return out
