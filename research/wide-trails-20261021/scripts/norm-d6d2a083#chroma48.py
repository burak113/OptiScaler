# 9675b4b87362e2190ad95b8cd3072c2ac96cba4ee85477a232ad3aafb98733c5
import numpy as np
from rrlab.captures import f32
x=np.load('E:\\FSRD\\sol_batch\\32-wide-trails\\d6d2a083#chroma48-pre.npy',mmap_mode='r')
base=np.load('E:/FSRD/sol_batch/31-material-trails/gpu-old.npy',mmap_mode='r') if 'd6d2a083#chroma48'=='c37d3609' else None
def prefilter(c,i,name,a):
 if name=='input_diffuse':return x[i].astype('f4')
 return base[1,i].astype('f4') if base is not None else a
def tuning(c,frames,t):
 return np.stack([f32(c.frames[i]['settings']['provider_effective'][:6]) for i in frames]) if 'd6d2a083#chroma48'=='c37d3609' else t
