"""Falsify native-MV jitter alignment directly against raw depth, without RR."""
import sys
import json
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).with_name('reference')))
from capture_adapter import Cap, controls

c=Cap(sys.argv[1] if len(sys.argv)>1 else 'f2ef375f')
fr=range(35,c.n) if c.dir.name.startswith('f2ef') else range(max(1,c.n-24),c.n)
rows=[]
xx,yy=np.meshgrid(np.arange(c.W),np.arange(c.H))
for t in fr:
    cur=c.img(t,'input_depth',np.float32,1).astype(np.float64)
    prev=c.img(t-1,'input_depth',np.float32,1)
    mv=c.img(t,'input_motion').astype(np.float64)
    j=np.frombuffer(controls(c,t),np.float32)[3:5].copy()
    jp=np.frombuffer(controls(c,t-1),np.float32)[3:5].copy()
    dj=jp-j
    gx,gy=np.gradient(np.log(np.abs(cur)+1e-6))
    mask=(np.abs(cur)>0)&(np.abs(cur)<500)&(np.hypot(gx,gy)<.01)
    mask[:16]=False;mask[-16:]=False;mask[:,:16]=False;mask[:,-16:]=False
    record={'frame':t,'jitter_delta':dj.tolist(),'errors':{}}
    for k in (-2,-1,0,1,2):
        qx=xx+mv[...,0]*c.RW+k*dj[0]
        qy=yy+mv[...,1]*c.RH+k*dj[1]
        value,valid=c.sample(prev,qx,qy)
        err=np.abs(value-(cur+mv[...,2]))/np.maximum(np.abs(cur),1e-6)
        keep=mask&valid
        record['errors'][k]=float(np.mean(np.minimum(err[keep],.01)))
    rows.append(record)
print(c.dir.name,'depth reprojection mean clipped relative error (smaller better)')
for k in (-2,-1,0,1,2):
    a=[row['errors'][k] for row in rows]
    print(k,'mean',float(np.mean(a)),'per-pair wins',sum(min(row['errors'],key=row['errors'].get)==k for row in rows))
Path('E:/FSRD/sol_batch/21-input-parity/'+c.dir.name[:8]+'_registration.json').write_text(json.dumps(rows,indent=2))
