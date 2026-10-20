import sys,json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,'E:/FSRD/rrlab')
from rrlab.captures import Capture
from rrlab.imgutil import LUMA,tonemap
from temporal_wavelet import Filter
O=Path(__file__).parent
for prefix in ['c37d','87ee','22f9','d6d2','f2ef','2405']:
 c=Capture(prefix);f=Filter();a=np.lib.format.open_memmap(O/f'{c.id}-temporal-wavelet.npy',mode='w+',dtype='f2',shape=(c.n,c.H,c.W,3))
 inputs=np.load('E:/FSRD/sol_batch/31-material-trails/gpu-old.npy',mmap_mode='r')[0] if prefix=='c37d' else None
 for i in range(c.n):
  x=c.img(i,'input_diffuse')[...,:3] if inputs is None else inputs[i,...,:3].astype('f4')
  y=c.img(i,'raw_rr_diffuse')[...,:3];a[i],d=f.apply(x,y,c,i)
 a.flush();frame={'c37d':60,'87ee':60,'22f9':50,'2405':185,'d6d2':127,'f2ef':49}[prefix]
 old=c.rgb(frame,'raw');new=a[frame].astype('f4')+c.img(frame,'raw_rr_specular')[...,:3]
 exp=1/max(float(np.quantile(old@LUMA,.75)),1e-10);im=Image.new('RGB',(2*c.W,c.H+28));draw=ImageDraw.Draw(im)
 for j,img in enumerate([old,new]):
  im.paste(Image.fromarray(tonemap(img,exp)),(j*c.W,28));draw.text((j*c.W+5,5),['Captured raw RR','Temporal coarse innovation'][j],fill='white')
 im.save(O/f'temporal-wavelet-{c.id}.png');print(c.id,'done',flush=True)
