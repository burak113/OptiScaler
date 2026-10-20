# 9d297971983e31fad6bcd53fc99288cfb06ab8428d39ecd86cc06b92e8a8f8ae
import numpy as np
from rrlab.captures import f32
x=np.load('E:\\FSRD\\sol_batch\\32-wide-trails\\87ee1fba-pre.npy',mmap_mode='r')
base=np.load('E:/FSRD/sol_batch/31-material-trails/gpu-old.npy',mmap_mode='r') if '87ee1fba'=='c37d3609' else None
def prefilter(c,i,name,a):
 if name=='input_diffuse':return x[i].astype('f4')
 return base[1,i].astype('f4') if base is not None else a
def tuning(c,frames,t):
 return np.stack([f32(c.frames[i]['settings']['provider_effective'][:6]) for i in frames]) if '87ee1fba'=='c37d3609' else t
