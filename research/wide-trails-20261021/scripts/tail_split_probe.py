"""Research only: sum-preserving radiance tail split before signed AMD RR."""
import sys,json
from pathlib import Path
import numpy as np
sys.path.insert(0,'E:/FSRD/rrlab')
from rrlab.captures import Capture
from rrlab import runner
O=Path(__file__).parent
runner.RUNNER=O/'rrlab_diffuse.exe'
records=[]
for prefix in sys.argv[1:] or ['87ee','c37d','d6d2']:
 c=Capture(prefix)
 base='d16+hook:E:/FSRD/sol_batch/31-material-trails/gpu_old_hook.py' if c.id=='c37d3609' else 'd16+adaptive'
 for threshold in [.02,.08,.32]:
  outputs=[]
  for part in ['core','tail']:
   hook=O/f'tail-{c.id}-{threshold}-{part}.py'
   hook.write_text('''import numpy as np
from rrlab.imgutil import LUMA
def prefilter(c,i,name,a):
 if name!='input_diffuse':return a
 out=a.copy();rgb=a[...,:3]
 ratio=np.minimum(1.,THRESHOLD/np.maximum(rgb@LUMA,1e-10))
 core=rgb*ratio[...,None]
 out[...,:3]=core if PART=='core' else np.maximum(rgb-core,0)
 return out
'''.replace('THRESHOLD',repr(threshold)).replace('PART',repr(part)))
   result=runner.run(c,base+'+hook:'+hook.as_posix(),owner='32-sum-preserving-tail-'+part)
   outputs.append(result.diffuse)
  combined=outputs[0]+outputs[1]
  assert np.isfinite(combined).all()
  np.save(O/f'{c.id}-tail-split-{threshold}.npy',combined.astype('f2'))
  rec=dict(capture=c.uuid,threshold=threshold,tail_fraction=float(outputs[1].sum()/max(combined.sum(),1e-10)))
  records.append(rec);print(json.dumps(rec),flush=True)
  (O/'tail-split.json').write_text(json.dumps(records,indent=2))
