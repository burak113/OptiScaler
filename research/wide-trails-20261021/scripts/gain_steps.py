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
c=Capture('d6d2');records={}
box=(32,300,96,556)
cases=[('control',c),('down',Step(c,48,.5)),('down_endpoint',Step(c,0,.5)),('small',Step(c,48,1.1)),('small_endpoint',Step(c,0,1.1)),('chroma',ChromaStep(c,48)),('chroma_endpoint',ChromaStep(c,0)),('local',Step(c,48,3,box)),('local_endpoint',Step(c,0,3,box))]
for label,cc in cases:
 old=runner.run(cc,'d16+adaptive',owner='32-gain-controls');y=old.diffuse
 f=Filter();coarse=np.lib.format.open_memmap(O/f'{cc.id}-step-coarse.npy',mode='w+',dtype='f2',shape=y.shape)
 for i in range(cc.n):coarse[i],_=f.apply(cc.img(i,'input_diffuse')[...,:3],y[i],cc,i)
 coarse.flush()
 new=process(cc,lambda i:y[i],lambda i:coarse[i].astype('f4'),alpha=.25,rotation_limit=3,tag='gain-step')
 yy,xx=np.mgrid[:cc.H,:cc.W];inside=(xx>=40)&(xx<88)&(yy>=316)&(yy<540);outside=(xx>=16)&(xx<112)&(yy>=64)&(yy<260)
 means={}
 for key,a in [('old',y),('gain',new)]:
  means[key]={region:[np.asarray(a[i],dtype='f4')[mask].mean(0).tolist() for i in range(cc.n)] for region,mask in [('all',(xx>=16)&(xx<112)&(yy>=32)&(yy<cc.H-32)),('inside',inside),('outside',outside)]}
 records[label]=means;(O/'gain-steps.json').write_text(json.dumps(records,indent=2));print(label,'done',flush=True)
