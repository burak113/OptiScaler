"""Production DXIL decision history: rejection, reprojection and stability.

History is carried between real GPU dispatches (including packed UINT metadata).
RR inputs are synthetic; this is not a test of the AMD model or game motion.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur


def run():
    t.OUT=t.OUT.parent/'composition_temporal';t.OUT.mkdir(parents=True,exist_ok=True)
    t.build_runner()
    w,h=41,33;y,x=np.indices((h,w));roi=(slice(5,-5),slice(5,-5))
    target=t.rgba(w,h,(.45,.45,.45),.008)
    for c,phase in enumerate((0,1.3,2.5)):
        target[...,c]+=.12*np.sin(.36*x+.17*y+phase)+.07*np.cos(.43*y+phase)
    rr=blur(target,2);rr[...,:3]=.45+.75*(rr[...,:3]-.45)
    zero=t.rgba(w,h,(0,0,0));a=t.rgba(w,h,(1,1,1))
    n=t.rgba(w,h,(.5,.5,.1),1/3);z=np.full((h,w),10,np.float32)
    motion=t.rgba(w,h,(0,0,0),1)
    values=dict(DstTexSize=[w,h,1/w,1/h],DetailPreservation=1.0,
                FloorHandoverAnchorClamp=4,FloorHandoverCorrelationMix=1,WriteHistory=1)

    def dispatch(ref=target,history=None,changes=None,cb=None,rr_image=rr):
        v=dict(values,HistoryValid=int(history is not None));v.update(cb or {})
        inputs=[zero,a,rr_image,a,zero,n,ref,z,motion,
                history[1] if history is not None else t.rgba(w,h,(-1,-1,-1),-1),
                history[2] if history is not None else np.zeros((h,w,4),np.uint32)]
        for k,value in (changes or {}).items():inputs[k]=value
        return t.dispatch('FSRDOutputComp',v,inputs,[10,10,3],(w,h))

    first=dispatch()
    t.check('history metadata uses UINT storage',first[2].dtype==np.uint32)
    t.check('first frame writes finite decisions and valid metadata',
            np.all(np.isfinite(first[1])) and np.all((first[2][...,1]&0x80000000)!=0))
    # Force a different bounded history to make every rejection observable.
    synthetic=[q.copy() for q in first];synthetic[1]=np.clip(first[1]+.10,0,1)
    reused=dispatch(history=synthetic)
    t.check('accepted stable surface reuses bounded decisions',
            np.max(np.abs(reused[1]-first[1]))>.01 and np.max(np.abs(reused[1]-first[1]))<=.063)
    invalid=motion.copy();invalid[...,3]=0
    bad_depth=z+8;bad_n=n.copy();bad_n[...,:2]=0
    bad_material=n.copy();bad_material[...,3]=0
    bad_rough=n.copy();bad_rough[...,2]=.7
    cut=target.copy();cut[...,:3]=cut[...,2::-1]*.3
    routed=target.copy();routed[...,3]=-1
    for label,changes,v in [
        ('reset',{},dict(HistoryValid=0)),
        ('invalid motion',{8:invalid},{}),
        ('disocclusion',{7:bad_depth},{}),
        ('normal change',{5:bad_n},{}),
        ('material change',{5:bad_material},{}),
        ('roughness change',{5:bad_rough},{}),
        ('albedo change',{3:t.rgba(w,h,(.2,.2,.2))},{}),
        ('animation cut',{6:cut},{}),
        ('explicit routing',{6:routed},{}),
        ('offscreen motion',{8:t.rgba(w,h,(2,2,0),1)},{}),
        ('detail disabled',{},dict(DetailPreservation=0))]:
        spatial=dispatch(changes=changes,cb=v)
        temporal=dispatch(history=synthetic,changes=changes,cb=v)
        t.check(label+' rejects stale colour influence',np.array_equal(spatial[0],temporal[0]))
        if label!='detail disabled':
            t.check(label+' rejects stale decisions',np.array_equal(spatial[1],temporal[1]))
    # Canonical UV motion is previous-current; jitter delta restores raster coordinates.
    # Shift the complete reference/RR and geometry, and compare two equivalent mappings.
    ref=np.roll(target,1,axis=1);rr_shift=np.roll(rr,1,axis=1)
    mv=motion.copy();mv[...,0]=-1/w
    mapped=dispatch(ref,synthetic,{8:mv},rr_image=rr_shift)
    jittered=dispatch(ref,synthetic,cb=dict(HistoryJitterDelta=[-1,0]),rr_image=rr_shift)
    t.check('canonical motion and raster jitter give identical reprojection',
            np.array_equal(mapped[0],jittered[0]) and np.array_equal(mapped[1],jittered[1]))
    t.check('offscreen first column cannot reuse history',
            np.array_equal(mapped[0][:,0],dispatch(ref,rr_image=rr_shift)[0][:,0]))
    # Motion-Z predicts previous signed view depth, including negative view Z.
    for sign in (1,-1):
        old=dispatch(changes={7:z*sign})
        old[1]=np.clip(old[1]+.1,0,1)
        mv=motion.copy();mv[...,2]=-sign
        current=dispatch(history=old,changes={7:(z+1)*sign,8:mv})
        reset=dispatch(changes={7:(z+1)*sign,8:mv})
        t.check(f'depth delta preserves valid reprojection sign={sign}',
                np.max(np.abs(current[1]-reset[1]))>.01)
    # Actual sequential history, not repeated filtering of an artificial previous weight.
    history=None;spatial=[];temporal=[];spatial_images=[];temporal_images=[]
    for frame in range(18):
        ref=target.copy();ref[...,:3]*=1+(.010 if frame%2 else -.010)
        one=dispatch(ref);two=dispatch(ref,history)
        history=two
        spatial.append(one[1][roi]);temporal.append(two[1][roi])
        spatial_images.append(one[0][roi][...,:3]);temporal_images.append(two[0][roi][...,:3])
    sv=float(np.mean(np.var(np.stack(spatial[4:]),axis=0)))
    tv=float(np.mean(np.var(np.stack(temporal[4:]),axis=0)))
    t.check('static decision variance reduced',sv>0 and tv<sv*.9,spatial=sv,temporal=tv)
    se=float(np.sqrt(np.mean((np.stack(spatial_images)-target[roi][...,:3])**2)))
    te=float(np.sqrt(np.mean((np.stack(temporal_images)-target[roi][...,:3])**2)))
    t.check('decision stabilization preserves synthetic reconstruction error',te<=se+.0005,spatial_rmse=se,temporal_rmse=te)
    # Zero-history replay exactly preserves the spatial path and already-correct RR.
    sharp=dispatch(rr_image=target)
    sharp_history=dispatch(history=sharp,rr_image=target)
    t.check('already sharp RR unchanged by temporal helpers',np.array_equal(sharp[0],sharp_history[0]))
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings),indent=2))
    assert all(c['passed'] for c in t.checks),'composition temporal regression'


if __name__=='__main__':run()
