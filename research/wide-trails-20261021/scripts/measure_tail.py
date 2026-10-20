import sys,json
from pathlib import Path
import numpy as np
sys.path.insert(0,'E:/FSRD/rrlab')
from rrlab.captures import Capture
from rrlab.imgutil import gaussian,LUMA
O=Path(__file__).parent;records=[]
for prefix,first,last in [('c37d',54,61),('87ee',50,64),('d6d2',104,128)]:
 c=Capture(prefix);ref=(first+last)//2;stacks=[];names=['input','raw','joint-replay','diffuse-only','tail-split-0.02','tail-split-0.08','tail-split-0.32']
 names=[n for n in names if n in ['input','raw'] or (O/f'{c.id}-{n}.npy').exists()]
 inputs=np.load('E:/FSRD/sol_batch/31-material-trails/gpu-old.npy',mmap_mode='r')[0] if prefix=='c37d' else None
 for name in names:
  data=np.load(O/f'{c.id}-{name}.npy',mmap_mode='r') if name not in ['input','raw'] else None
  aligned=[]
  for i in range(first,last):
   if data is not None:a=data[i].astype('f4')
   elif name=='input':a=c.img(i,'input_diffuse')[...,:3] if inputs is None else inputs[i,...,:3].astype('f4')
   else:a=c.img(i,'raw_rr_diffuse')[...,:3]
   aligned.append(c.warp(ref,i,a)[0])
  stacks.append(np.stack(aligned))
 yy,xx=np.mgrid[:c.H,:c.W];m=(yy>32)&(yy<c.H-32)&(xx>24)&(xx<c.W-24)
 truth=stacks[0].mean(0);normalizer=(truth@LUMA)[m].mean();r={}
 for name,a in zip(names,stacks):
  mean=a.mean(0);rgb=a[:,m].mean(1);lum=a@LUMA;level=lum[:,m].mean(1)
  low=gaussian(lum/normalizer,16);fine=(lum-gaussian(lum,1.5))/normalizer
  chroma=a/np.maximum(lum[...,None],normalizer*.05)
  chlow=np.stack([gaussian(chroma[...,i],16) for i in range(3)],-1)
  error=gaussian((mean-truth).transpose(2,0,1),16).transpose(1,2,0)
  detail=mean-gaussian(mean.transpose(2,0,1),1.5).transpose(1,2,0)
  r[name]={'level_to_input':float(level.mean()/normalizer),'red_share':float(rgb.mean(0)[0]/rgb.mean(0).sum()),'low_band_error':float(abs(error[m]).mean()/normalizer),
   'low_2nd_diff':float(abs(np.diff(low,n=2,axis=0))[:,m].mean()),'fine_2nd_diff':float(abs(np.diff(fine,n=2,axis=0))[:,m].mean()),'chroma_low_2nd_diff':float(abs(np.diff(chlow,n=2,axis=0))[:,m].mean()),'detail':float(abs(detail[m]).mean())}
 records.append({'capture':c.id,'frames':[first,last],'result':r});print(json.dumps(records[-1]),flush=True)
(O/'tail-metrics.json').write_text(json.dumps(records,indent=2))
