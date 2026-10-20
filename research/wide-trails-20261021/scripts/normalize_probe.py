import sys,json,hashlib
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,'E:/FSRD/rrlab')
from rrlab.captures import Capture,f32
from rrlab import runner
from rrlab.imgutil import gaussian,LUMA,tonemap
O=Path(__file__).parent
def blur(rgb,s):return gaussian(rgb.transpose(2,0,1),s).transpose(1,2,0)

def run(prefix):
 c=prefix if isinstance(prefix,Capture) else Capture(prefix);prepared=np.lib.format.open_memmap(O/f'{c.id}-pre.npy',mode='w+',dtype='f2',shape=(c.n,c.H,c.W,4))
 factors=np.lib.format.open_memmap(O/f'{c.id}-factor.npy',mode='w+',dtype='f2',shape=(c.n,c.H,c.W,3))
 if c.id=='c37d3609':source=np.load('E:/FSRD/sol_batch/31-material-trails/gpu-old.npy',mmap_mode='r')[0]
 else:source=None
 for i in range(c.n):
  a=c.img(i,'input_diffuse') if source is None else source[i].astype('f4')
  b=blur(a[...,:3],32)
  # New representation: smooth illumination is removed and immediately restored
  # around RR. Noise/lighting detail are NOT replaced by this broad estimate.
  f=np.clip(b/.02,.125,8)
  a=a.copy();a[...,:3]/=f;prepared[i]=a;factors[i]=f
 prepared.flush();factors.flush()
 data=O/f'{c.id}-pre.npy';digest=hashlib.sha256(data.read_bytes()).hexdigest()
 hook=O/f'norm-{c.id}.py'
 hook.write_text(f'''# {digest}
import numpy as np
from rrlab.captures import f32
x=np.load({str(data)!r},mmap_mode='r')
base=np.load('E:/FSRD/sol_batch/31-material-trails/gpu-old.npy',mmap_mode='r') if {c.id!r}=='c37d3609' else None
def prefilter(c,i,name,a):
 if name=='input_diffuse':return x[i].astype('f4')
 return base[1,i].astype('f4') if base is not None else a
def tuning(c,frames,t):
 return np.stack([f32(c.frames[i]['settings']['provider_effective'][:6]) for i in frames]) if {c.id!r}=='c37d3609' else t
''')
 base='d16+hook:E:/FSRD/sol_batch/31-material-trails/gpu_old_hook.py' if c.id=='c37d3609' else 'd16+adaptive'
 a=runner.run(c,base,owner='32-normalize-base');b=runner.run(c,'d16+adaptive+hook:'+hook.as_posix(),owner='32-normalize')
 result=np.lib.format.open_memmap(O/f'{c.id}-normalized.npy',mode='w+',dtype='f2',shape=(c.n,c.H,c.W,3))
 d=b.diffuse
 for i in range(c.n):result[i]=d[i]*factors[i].astype('f4')
 result.flush();del d
 exp=1/max(float(np.quantile(c.rgb(c.n-1)@LUMA,.75)),1e-10)
 im=Image.new('RGB',(c.W*2,c.H+28));dr=ImageDraw.Draw(im)
 for j,x in enumerate([a.frame(c.n-1),result[-1].astype('f4')+b.specular[-1]]):
  im.paste(Image.fromarray(tonemap(x,exp)),(j*c.W,28));dr.text((j*c.W+5,5),['Existing RR','Illumination-normalized RR'][j],fill='white')
 im.save(O/f'normalize-{c.id}.png')
 print(c.id,'done',flush=True)
 return c,a,b,result
if __name__=='__main__':
 for prefix in sys.argv[1:] or ['c37d3609','87ee','d6d2']:run(prefix)
