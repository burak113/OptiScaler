"""Production DXIL: graduated modulation, recovery ownership, noise and history.

Synthetic RR inputs isolate the composition contracts; this does not certify
AMD RR or Cyberpunk image quality. Metrics are against independently known truth.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_zero_rough_screen import chain_cb
from test_fsrd_panel_recovery import blur


def run():
    t.build_runner()
    w,h=43,35
    y,x=np.indices((h,w)); roi=(slice(6,-6),slice(6,-6))
    zero=t.rgba(w,h,(0,0,0)); z=np.full((h,w),10,np.float32)
    raw=t.rgba(w,h,(.4,.7,.9)); raw[...,:3]*=(1+.1*np.sin(x*.7))[...,None]
    spec=t.rgba(w,h,(.1,.3,.5)); diff=t.rgba(w,h,(.5,.2,.1))
    spec[x<w//2,:3]*=.2
    pedestal=raw.copy(); pedestal[...,:3]*=.5; pedestal[...,3]=0
    norm=t.rgba(w,h,(0,0,1)); rough=np.full((h,w),.4,np.float32)
    reference=raw.copy(); reference[...,3]=0
    conv=chain_cb(w,h,(1<<1)|(1<<7)); conv['RecoveryMask']=0
    ci=[raw,z,zero,norm,rough,z,diff,spec,zero,pedestal,zero,zero,zero,zero,z,zero,reference]
    formats=[10,10,10,24,28,28,10,10]
    comp=dict(DstTexSize=[w,h,1/w,1/h],DetailPreservation=0,RecoveryMask=7)
    original=None
    for ss,ds in [(1,1),(0,1),(1,0),(0,0),(.25,.75),(.5,.5),(.75,.25)]:
        mods=dict(SpecularAlbedoDemodulation=ss,DiffuseAlbedoModulation=ds)
        p=t.dispatch('FSRDInputConv',dict(conv,**mods),ci,formats,(w,h))
        if original is None:original=p
        # Albedo alpha carries signal-routing diagnostics, not material RGB.
        t.check(f'guides remain original {ss}/{ds}',
                all(np.array_equal(p[i],original[i]) for i in [2,3,7]) and
                all(np.array_equal(p[i][...,:3],original[i][...,:3]) for i in [4,5]))
        out=t.dispatch('FSRDOutputComp',dict(comp,**mods),[p[0],p[4],p[1],p[5],p[6],p[3],p[7],z],[10],(w,h))[0]
        err=float(np.max(np.abs(out[...,:3]-raw[...,:3])))
        t.check(f'paired arithmetic preserves energy {ss}/{ds}',err<.002,max_error=err)
        if ss==0 and ds==0:
            t.check('zero modulation removes pedestal from Skip',np.max(abs(p[6][...,:3]))<1e-5)

    n=t.rgba(w,h,(.5,.5,.4),0); mv=t.rgba(w,h,(0,0,0),1)
    a=t.rgba(w,h,(.5,.5,.5)); target=t.rgba(w,h,(.4,.4,.4),0)
    for c,phase in enumerate((0,1.3,2.4)):
        target[...,c]+=.13*np.sin(.7*x+phase)+.1*np.cos(.45*y+phase)
    rr=blur(target,2)
    values=dict(DstTexSize=[w,h,1/w,1/h],DetailPreservation=1,WriteHistory=1,
                SpecularAlbedoDemodulation=0,DiffuseAlbedoModulation=0,
                FloorHandoverAnchorClamp=4,FloorHandoverCorrelationMix=1)
    def dispatch(mask=6,method=6,ref=target,history=None,changes=None,extra=None):
        cb=dict(values,RecoveryMask=mask,SpatialTemporalMask=method,HistoryValid=int(history is not None));cb.update(extra or {})
        inputs=[zero,a,rr,a,zero,n,ref,z,mv,
                t.rgba(w,h,(-1,-1,-1),-1) if history is None else history[1],
                np.zeros((h,w,4),np.uint32) if history is None else history[2]]
        for i,v in (changes or {}).items():inputs[i]=v
        return t.dispatch('FSRDOutputComp',cb,inputs,[10,10,3],(w,h))
    base=dispatch(mask=0)[0]
    for mask in range(8):
        for method in (0,mask):
            off=dispatch(mask,method,extra=dict(DetailPreservation=0))
            t.check(f'zero master no recovery {mask}/{method}',np.array_equal(off[0],base))
    # Both paths have complementary shares and cannot double their correction.
    for method in (0,6):
        all_=dispatch(6,method)[0]; s=dispatch(2,method)[0]; d=dispatch(4,method)[0]
        err=float(np.max(abs(s[...,:3]+d[...,:3]-base[...,:3]-all_[...,:3])))
        t.check(f'lobe weights partition recovery method={method}',err<.001,max_error=err)
        for strength in (.25,.5,.75):
            out=dispatch(6,method,extra=dict(DetailPreservation=strength))[0]
            err=float(np.max(abs(out[...,:3]-(base[...,:3]+strength*(all_[...,:3]-base[...,:3])))))
            t.check(f'linear master {method}/{strength}',err<.001,max_error=err)
    flat=n.copy();flat[...,3]=1/3
    for method in (0,7):
        all_=dispatch(7,method,changes={5:flat})
        flat_only=dispatch(1,method,changes={5:flat})
        t.check(f'flat selection owns pixel method={method}',np.array_equal(all_[0],flat_only[0]))
    mixed=dispatch(6,2)[0]; sa=dispatch(4,0)[0]; sf=dispatch(2,2)[0]
    t.check('independent mixed algorithms combine only their shares',
            np.max(abs(mixed[...,:3]-(sa[...,:3]+sf[...,:3]-base[...,:3])))<.001)
    for mode in (0,6):
        out=dispatch(6,mode)[0]
        before=float(np.mean((rr[roi][...,:3]-target[roi][...,:3])**2))
        after=float(np.mean((out[roi][...,:3]-target[roi][...,:3])**2))
        t.check(f'clean blurred pattern recovered method={mode}',after<before,rr_mse=before,recovered_mse=after)
    # Held-out random grain, known clean target, sequential real GPU history.
    # The Light Anchor Mix keeps no temporal state: a dispatch carrying the
    # previous frame's history must reproduce the history-free result exactly,
    # and must still reject (never re-read) that history under every break.
    rng=np.random.default_rng(74631); history=None; errors=[]; raw_errors=[]
    for frame in range(16):
        ref=target.copy();ref[...,:3]+=rng.normal(0,.045,(h,w,3));ref[...,3]=.045
        current=dispatch(ref=ref)
        history=dispatch(ref=ref,history=history)
        t.check(f'frame {frame} independent of carried history',np.array_equal(current[0],history[0]))
        if frame>=4:
            errors.append(float(np.mean((history[0][roi][...,:3]-target[roi][...,:3])**2)))
            raw_errors.append(float(np.mean((ref[roi][...,:3]-target[roi][...,:3])**2)))
    t.check('recovery grain reduction',np.mean(errors)<np.mean(raw_errors)*.65,
            filtered_mse=float(np.mean(errors)),raw_mse=float(np.mean(raw_errors)))
    # Every rejection must exactly reproduce this frame's history-free result.
    for label,changes,extra in [
        ('reset',{},dict(HistoryValid=0)),('disocclusion',{7:z+8},{}),
        ('invalid motion',{8:zero},{}),('offscreen',{8:t.rgba(w,h,(2,0,0),1)},{}),
        ('normal',{5:t.rgba(w,h,(0,0,.4),0)},{}),
        ('albedo',{3:t.rgba(w,h,(.1,.1,.1))},{}),
        ('routed',{6:t.rgba(w,h,(.2,.4,.6),-1)},{}),
        ('animation',{6:t.rgba(w,h,(2,1,3),.005)},{}),
    ]:
        fresh=dispatch(changes=changes,extra=extra);old=dispatch(history=history,changes=changes,extra=extra)
        t.check('filter ignores rejected history '+label,np.array_equal(fresh[0],old[0]))
    # A clean two-colour edge should not bleed across its radiance discontinuity.
    edge=t.rgba(w,h,(.1,.3,.8),0);edge[:,w//2:,:3]=(.8,.3,.1)
    out=dispatch(ref=edge,changes={2:blur(edge,2)})[0]
    t.check('clean sharp coloured edge retained',np.max(abs(out[...,:3]-edge[...,:3]))<.001)
    # Recovery is not a licence to reintroduce grain when RR already has the detail.
    ref=target.copy();ref[...,:3]+=rng.normal(0,.045,(h,w,3));ref[...,3]=.045
    sharp=dispatch(ref=ref,changes={2:target})
    error=float(np.mean((sharp[0][roi][...,:3]-target[roi][...,:3])**2))
    t.check('already sharp RR protected from residual reference grain',error<.0001,mse=error)
    # Motion sign and jitter equivalence for colour history, including a partial group.
    ref=np.roll(target,1,axis=1);shifted=np.roll(rr,1,axis=1)
    old=dispatch(ref=target);motion=mv.copy();motion[...,0]=-1/w
    mapped=dispatch(ref=ref,history=old,changes={2:shifted,8:motion})
    jittered=dispatch(ref=ref,history=old,changes={2:shifted},extra=dict(HistoryJitterDelta=[-1,0]))
    t.check('filter ignores motion and jitter mapping',np.array_equal(mapped[0],jittered[0]))
    # Sliders actually disconnect the two independent contrast recovery contributions.
    for key,view in [('ChromaRecovery',22),('LumaRecovery',23)]:
        out=dispatch(6,0,extra={key:0,'Flags':(1<<16)|(view<<17)})[0]
        t.check(key+' zero disables diagnostic correction',np.max(abs(out[...,:3]-.5))<.001)
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings),indent=2))
    assert all(c['passed'] for c in t.checks),'recovery controls regression'

if __name__=='__main__':run()
