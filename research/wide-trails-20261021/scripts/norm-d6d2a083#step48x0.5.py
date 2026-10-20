# 3c9a7e4946aacb58b1244596ed35b600e1495a648f85cf79ba876e0b410e2d62
import numpy as np
from rrlab.captures import f32
x=np.load('E:\\FSRD\\sol_batch\\32-wide-trails\\d6d2a083#step48x0.5-pre.npy',mmap_mode='r')
base=np.load('E:/FSRD/sol_batch/31-material-trails/gpu-old.npy',mmap_mode='r') if 'd6d2a083#step48x0.5'=='c37d3609' else None
def prefilter(c,i,name,a):
 if name=='input_diffuse':return x[i].astype('f4')
 return base[1,i].astype('f4') if base is not None else a
def tuning(c,frames,t):
 return np.stack([f32(c.frames[i]['settings']['provider_effective'][:6]) for i in frames]) if 'd6d2a083#step48x0.5'=='c37d3609' else t
