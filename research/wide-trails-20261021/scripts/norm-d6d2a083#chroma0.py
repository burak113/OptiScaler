# ae71a133a77ff461a730b518ae434e7dba903124eb32873d003c58f0a1c4a2f2
import numpy as np
from rrlab.captures import f32
x=np.load('E:\\FSRD\\sol_batch\\32-wide-trails\\d6d2a083#chroma0-pre.npy',mmap_mode='r')
base=np.load('E:/FSRD/sol_batch/31-material-trails/gpu-old.npy',mmap_mode='r') if 'd6d2a083#chroma0'=='c37d3609' else None
def prefilter(c,i,name,a):
 if name=='input_diffuse':return x[i].astype('f4')
 return base[1,i].astype('f4') if base is not None else a
def tuning(c,frames,t):
 return np.stack([f32(c.frames[i]['settings']['provider_effective'][:6]) for i in frames]) if 'd6d2a083#chroma0'=='c37d3609' else t
