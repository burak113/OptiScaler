"""Report counterevidence: turn energy tail, dark-specular level, replay coverage."""
import json
import numpy as np
from parity_replay import Cap,LUMA,WORK,OUT

result={}
for cid in ('d6d2a083','8ab8afe7','daa6','cb550300','06fadf38'):
    c=Cap(cid)
    angles=c.rotation()
    result[cid]={'frames':c.n,'max_rotation_deg':float(angles.max()),
                 'still_under_0_1_deg_frames':int((angles<.1).sum()),
                 'source':'native bridge; no final game compositor or upscaler in replay'}
    if cid in ('d6d2a083','cb550300'):
        z=np.abs(c.img(c.n-1,'input_depth',np.float32,1))
        mask=(z>0)&(z<500);mask[:12]=False;mask[-12:]=False;mask[:,:12]=False;mask[:,-12:]=False
        levels={}
        for v in ('native','ds_16_256'):
            a=np.load(WORK/f'{cid}_{v}_s.npy',mmap_mode='r')[-24:].astype(np.float32)@LUMA
            levels[v]={'specular_mean':float(a[:,mask].mean()),
                       'specular_median':float(np.median(a[:,mask])),
                       'specular_zero_fraction':float((a[:,mask]==0).mean())}
        result[cid]['dark_specular_probe']=levels

c=Cap('06fadf38');ref=c.n-3;last=max(i for i,r in enumerate(c.rotation()) if r>3)
frames=list(range(last+1,c.n));data={};mask=np.abs(c.img(ref,'input_depth',np.float32,1))<500
mask[:12]=False;mask[-12:]=False;mask[:,:12]=False;mask[:,-12:]=False
for variant in ('native','ds_16_256','ds_1_256','asinhD_0.01','asinhD_0.1'):
    if not (WORK/f'06fadf38_{variant}_d.npy').exists():continue
    d=np.load(WORK/f'06fadf38_{variant}_d.npy',mmap_mode='r')
    s=np.load(WORK/f'06fadf38_{variant}_s.npy',mmap_mode='r')
    seq=[]
    for t in frames:
        value=d[t].astype(np.float32)+s[t].astype(np.float32)
        if t!=ref:
            value,valid=c.warp(ref,t,value);mask &= valid
        seq.append(value)
    data[variant]=seq
turn={'last_turn_frame':last,'valid_pixels':int(mask.sum()),'curves':{},
      'scope':'cropped replay; unavailable off-ROI history prevents a full in-game ghosting verdict'}
for name,seq in data.items():
    l=np.array([float((a@LUMA)[mask].mean()) for a in seq])
    settled=float(l[-8:].mean())
    turn['curves'][name]={str(t-last):float(value/settled-1) for t,value in zip(frames,l)}
    print(name,'post-turn relative excess %', {k:round(v*100,3) for k,v in turn['curves'][name].items() if int(k) in (1,2,4,8,16,24)})
result['turn_energy']=turn
(OUT/'limitations.json').write_text(json.dumps(result,indent=2))
for cid,row in result.items():
    if 'max_rotation_deg' in row:print(cid,row)
