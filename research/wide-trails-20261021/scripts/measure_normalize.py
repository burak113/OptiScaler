import sys,json
from pathlib import Path
import numpy as np
sys.path.insert(0,'E:/FSRD/rrlab')
from rrlab.captures import Capture
from rrlab import runner
from rrlab.imgutil import gaussian,LUMA
from rrlab.fixtures import Step,ChromaStep
from normalize_probe import run
O=Path(__file__).parent
def metric(c,first,last):
 base='d16+hook:E:/FSRD/sol_batch/31-material-trails/gpu_old_hook.py' if c.id=='c37d3609' else 'd16+adaptive'
 old=runner.run(c,base,owner='32-metrics').diffuse
 new=np.load(O/f'{c.id}-normalized.npy',mmap_mode='r')
 ref=(first+last)//2
 actual_inputs=np.load('E:/FSRD/sol_batch/31-material-trails/gpu-old.npy',mmap_mode='r')[0] if c.id=='c37d3609' else None
 stacks=[]
 for source in [None,old,new]:
  aligned=[]
  for i in range(first,last):
   a=(c.img(i,'input_diffuse')[...,:3] if actual_inputs is None else actual_inputs[i,...,:3].astype('f4')) if source is None else source[i].astype('f4')
   aligned.append(c.warp(ref,i,a)[0])
  stacks.append(np.stack(aligned))
 yy,xx=np.mgrid[:c.H,:c.W];m=(yy>32)&(yy<c.H-32)&(xx>24)&(xx<c.W-24)
 # Camera-aligned, fixed interior support, no changed-input masks.
 target=stacks[0].mean(0);result={}
 for name,a in zip(['input','old','normalized'],stacks):
  mean=a.mean(0);rgb=a[:,m].mean(1);luma=a@LUMA
  # Normalise global drift only for the residual flicker measure. Quote energy separately.
  level=luma[:,m].mean(1);unit=luma/level[:,None,None]
  fine=unit-gaussian(unit,1.5)
  low=gaussian(unit,16)
  norm=(target@LUMA)[m].mean()
  e=gaussian((mean-target).transpose(2,0,1),16).transpose(1,2,0)
  hp=mean-gaussian(mean.transpose(2,0,1),1.5).transpose(1,2,0)
  result[name]=dict(mean_rgb=rgb.mean(0).tolist(),red_share=float(rgb.mean(0)[0]/rgb.mean(0).sum()),level_to_input=float(level.mean()/norm),low_band_error=float(abs(e[m]).mean()/norm),detrended_fine_std=float(np.std(fine,axis=0)[m].mean()),detrended_low_std=float(np.std(low,axis=0)[m].mean()),detail=float(abs(hp[m]).mean()))
 return {'capture':c.id,'window':[first,last],'scope':'late captured input mean is a diagnostic target, NOT ground truth; fixed interior mask','result':result}

if len(sys.argv)>1 and sys.argv[1]=='steps':
 c=Capture('d6d2');records={}
 for label,obj in [('control',c),('step_down',Step(c,48,.5)),('down_endpoint',Step(c,0,.5)),('step_small',Step(c,48,1.1)),('small_endpoint',Step(c,0,1.1)),('chroma',ChromaStep(c,48)),('chroma_endpoint',ChromaStep(c,0))]:
  cc,old,raw,new=run(obj);means={}
  for key,a in [('old',old.diffuse),('normalized',new)]:means[key]=[np.asarray(a[i],dtype='f4')[32:-32,16:-16].mean((0,1)).tolist() for i in range(c.n)]
  records[label]=means;(O/'normalize-steps.json').write_text(json.dumps(records,indent=2));print('step',label,flush=True)
else:
 results=[]
 for prefix,first,last in [('c37d',54,61),('87ee',50,64),('d6d2',104,128)]:
  r=metric(Capture(prefix),first,last);results.append(r);print(json.dumps(r),flush=True)
 (O/'normalize-metrics.json').write_text(json.dumps(results,indent=2))
