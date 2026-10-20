import sys,json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,'E:/FSRD/rrlab')
from rrlab.captures import Capture
from rrlab.imgutil import gaussian,tonemap,LUMA
O=Path(__file__).parent
windows={'c37d':(54,61),'87ee':(54,64),'22f9':(45,53),'2405':(180,193),'d6d2':(104,128),'06fad':(50,66)}
records=[]
for prefix,(first,last) in windows.items():
 c=Capture(prefix);ref=(first+last)//2;means={};valid=np.ones((c.H,c.W),bool)
 yy,xx=np.mgrid[:c.H,:c.W];valid&=(xx>40)&(xx<c.W-40)&(yy>40)&(yy<c.H-40)
 for lobe in ['diffuse','specular']:
  for kind,role in [('in','input_'),('raw','raw_rr_'),('selected','selected_rr_')]:
   samples=[]
   for i in range(first,last):
    a=c.img(i,role+lobe)[...,:3];a,ok=c.warp(ref,i,a);valid&=ok;samples.append(a)
   means[kind+'_'+lobe]=np.mean(samples,axis=0)
 r={'capture':c.id,'window':[first,last],'scope':'camera-aligned late-window means; no converged truth, moving objects not aligned','lobes':{}}
 for lobe in ['diffuse','specular']:
  inp,raw,sel=[means[k+'_'+lobe] for k in ['in','raw','selected']]
  vals=[x[valid].mean(0) for x in [inp,raw,sel]]
  r['lobes'][lobe]={'mean_rgb':[x.tolist() for x in vals],'raw_to_input_luma':float((vals[1]@LUMA)/(vals[0]@LUMA)),'selected_to_input_luma':float((vals[2]@LUMA)/(vals[0]@LUMA)),'red_share':[float(x[0]/x.sum()) for x in vals]}
 exposure=1/max(float(np.quantile((means['in_diffuse']+means['in_specular'])@LUMA,.75)),1e-9)
 im=Image.new('RGB',(c.W*3,c.H+28));d=ImageDraw.Draw(im)
 for j,k in enumerate(['in','raw','selected']):
  im.paste(Image.fromarray(tonemap(means[k+'_diffuse']+means[k+'_specular'],exposure)),(j*c.W,28));d.text((j*c.W+5,5),f'{c.id} mean {first}:{last} {k}',fill='white')
 im.save(O/f'stages-{c.id}.png');records.append(r);print(json.dumps(r),flush=True)
(O/'stages.json').write_text(json.dumps(records,indent=2))
