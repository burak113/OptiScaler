import sys,json
from pathlib import Path
import numpy as np
sys.path.insert(0,'E:/FSRD/rrlab')
from rrlab.captures import Capture
from rrlab import runner
from rrlab.fixtures import Step,ChromaStep
from temporal_wavelet import Filter
from slow_gain_probe import process
O=Path(__file__).parent
def run(c,provider,tag='guard-gain'):
 f=Filter(guard=True);coarse=np.lib.format.open_memmap(O/f'{c.id}-{tag}-coarse.npy',mode='w+',dtype='f2',shape=(c.n,c.H,c.W,3));guards=np.lib.format.open_memmap(O/f'{c.id}-{tag}-mask.npy',mode='w+',dtype='u1',shape=(c.n,c.H,c.W))
 inputs=np.load('E:/FSRD/sol_batch/31-material-trails/gpu-old.npy',mmap_mode='r')[0] if c.id=='c37d3609' else None
 for i in range(c.n):
  x=c.img(i,'input_diffuse')[...,:3] if inputs is None else inputs[i,...,:3].astype('f4')
  coarse[i],_=f.apply(x,provider(i),c,i);guards[i]=f.changed
 coarse.flush();guards.flush()
 return process(c,provider,lambda i:coarse[i].astype('f4'),alpha=.25,rotation_limit=3,tag=tag,guards=lambda i:guards[i].astype(bool))
if 'steps' in sys.argv:
 c=Capture('d6d2');records={};box=(32,300,96,556)
 for label,cc in [('control',c),('down',Step(c,48,.5)),('down_endpoint',Step(c,0,.5)),('small',Step(c,48,1.1)),('small_endpoint',Step(c,0,1.1)),('chroma',ChromaStep(c,48)),('chroma_endpoint',ChromaStep(c,0)),('local',Step(c,48,3,box)),('local_endpoint',Step(c,0,3,box))]:
  base=runner.run(cc,'d16+adaptive',owner='32-guard-control').diffuse;result=run(cc,lambda i:base[i],tag='guard-step')
  yy,xx=np.mgrid[:cc.H,:cc.W];inside=(xx>=40)&(xx<88)&(yy>=316)&(yy<540);outside=(xx>=16)&(xx<112)&(yy>=64)&(yy<260)
  records[label]={key:{region:[np.asarray(a[i],dtype='f4')[mask].mean(0).tolist() for i in range(cc.n)] for region,mask in [('all',(xx>=16)&(xx<112)&(yy>=32)&(yy<cc.H-32)),('inside',inside),('outside',outside)]} for key,a in [('old',base),('gain',result)]}
  (O/'guard-steps.json').write_text(json.dumps(records,indent=2));print(label,'done',flush=True)
else:
 for prefix in ['c37d','87ee','22f9','d6d2','f2ef','2405']:
  c=Capture(prefix);run(c,lambda i:c.img(i,'raw_rr_diffuse')[...,:3]);print(c.id,'done',flush=True)
