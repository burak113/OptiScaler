"""Same crop, fixed shared exposure, no denoising or candidate-specific normalization."""
import sys
import os
import json
import numpy as np
from PIL import Image, ImageDraw
from parity_replay import WORK, OUT, Cap, LUMA

cid=sys.argv[1] if len(sys.argv)>1 else 'f2ef375f'
prefix=cid+'_'+os.environ['FSRD_VIS_TAG'] if os.environ.get('FSRD_VIS_TAG') else cid
variants=sys.argv[2:] or ['native','gpu_16_256']
labels={'native':'Native / D256 S256','gpu_256_256':'Shared pass / D256 S256',
        'gpu_16_256':'Candidate / D16 S256','common_1':'Synthetic D=S (not game combined path)'}
c=Cap(cid)
frames=list(range(34,c.n)) if cid.startswith('f2ef') else list(range(c.n-24,c.n))
ref=frames[len(frames)//2]
xywh=(280,120,192,256) if c.W==512 else (12,160,104,300)
x,y,w,h=xywh
base=c.rgb(ref,'raw')
mask=np.abs(c.img(ref,'input_depth',np.float32,1))<500
exposure=.18/np.median((base@LUMA)[mask])
tm=lambda a: np.uint8(np.clip(np.maximum(a*exposure,0)/(1+np.maximum(a*exposure,0)),0,1)**(1/2.2)*255)
seq={}
for v in variants:
    d=np.load(WORK/f'{cid}_{v}_d.npy',mmap_mode='r')
    s=np.load(WORK/f'{cid}_{v}_s.npy',mmap_mode='r')
    seq[v]=[]
    for t in frames:
        ad=c.img(t,'input_diffuse_albedo',np.uint8)[...,:3]/255.
        ass=c.img(t,'input_specular_albedo',np.uint8)[...,:3]/255.
        a=d[t].astype(np.float32)*ad+s[t].astype(np.float32)*ass
        if t!=ref:
            a,_=c.warp(ref,t,a)
        seq[v].append(a)
    seq[v]=np.array(seq[v],np.float32)
panels=[]
for t in range(len(frames)):
    im=Image.new('RGB',(len(variants)*(w*2+8),h*2+30),(18,20,24))
    for k,v in enumerate(variants):
        tile=Image.fromarray(tm(seq[v][t,y:y+h,x:x+w])).resize((w*2,h*2),Image.Resampling.NEAREST)
        im.paste(tile,(k*(w*2+8),30))
        ImageDraw.Draw(im).text((k*(w*2+8)+5,7),f'{labels.get(v,v)} / f{frames[t]}',fill='white')
    panels.append(im)
panels[len(panels)//2].save(OUT/f'{prefix}_same_frame.png')
panels[0].save(OUT/f'{prefix}_comparison.gif',save_all=True,append_images=panels[1:],duration=100,loop=0)
mean=Image.new('RGB',(len(variants)*(w*2+8),h*2+30),(18,20,24))
for k,v in enumerate(variants):
    tile=Image.fromarray(tm(seq[v].mean(0)[y:y+h,x:x+w])).resize((w*2,h*2),Image.Resampling.NEAREST)
    mean.paste(tile,(k*(w*2+8),30));ImageDraw.Draw(mean).text((k*(w*2+8)+5,7),labels.get(v,v)+' / temporal mean',fill='white')
mean.save(OUT/f'{prefix}_mean.png')
(OUT/f'{prefix}_visualization.json').write_text(json.dumps({'frames':frames,'reference':ref,'crop_xywh':xywh,
    'exposure':float(exposure),'display':'shared Reinhard then gamma 1/2.2; 2x nearest; camera aligned',
    'variants':variants,'labels':{v:labels.get(v,v) for v in variants},'display_fps':10,
    'display_fps_scope':'inspection playback only; not measured in-game FPS'},indent=2))
print(OUT/f'{prefix}_same_frame.png')
