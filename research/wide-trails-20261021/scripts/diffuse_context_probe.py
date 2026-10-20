import sys,json,hashlib
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,'E:/FSRD/rrlab')
from rrlab.captures import Capture
from rrlab import runner
from rrlab.imgutil import LUMA,tonemap
O=Path(__file__).parent
standard=runner.RUNNER
records=[]
for prefix in sys.argv[1:] or ['c37d','87ee','d6d2']:
 c=Capture(prefix)
 variant='d16+hook:E:/FSRD/sol_batch/31-material-trails/gpu_old_hook.py' if c.id=='c37d3609' else 'd16+adaptive'
 runner.RUNNER=standard
 a=runner.run(c,variant,owner='32-context-joint')
 runner.RUNNER=O/'rrlab_diffuse.exe'
 b=runner.run(c,variant,owner='32-context-diffuse-only')
 x,y=a.diffuse,b.diffuse
 assert np.isfinite(x).all() and np.isfinite(y).all()
 np.save(O/f'{c.id}-joint-replay.npy',x.astype('f2'))
 np.save(O/f'{c.id}-diffuse-only.npy',y.astype('f2'))
 rel=np.abs(y-x).sum()/np.maximum(abs(x).sum(),1e-12)
 rec={'capture':c.uuid,'variant':variant,'relative_L1_to_joint':float(rel),'bit_equal':bool(np.array_equal(x,y)), 'joint_meta':a.meta,'diffuse_meta':b.meta,'runner_sha256':hashlib.sha256(runner.RUNNER.read_bytes()).hexdigest()}
 records.append(rec);print(json.dumps(rec),flush=True)
 exposure=1/max(float(np.quantile(a.frame(c.n-1)@LUMA,.75)),1e-10)
 image=Image.new('RGB',(c.W*2,c.H+28));draw=ImageDraw.Draw(image)
 for k,(name,im) in enumerate([('Joint context',a.frame(c.n-1)),('Diffuse-only context + original specular',y[-1]+a.specular[-1])]):
  image.paste(Image.fromarray(tonemap(im,exposure)),(k*c.W,28));draw.text((k*c.W+4,5),name,fill='white')
 image.save(O/f'diffuse-context-{c.id}.png')
 (O/'diffuse-context.json').write_text(json.dumps(records,indent=2))
runner.RUNNER=standard
