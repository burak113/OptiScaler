"""V6 review regressions: colour, low contrast, surface leakage, and RR noise reuse."""
import json
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur


def run():
    t.OUT=t.OUT.parent/'screen_review';t.OUT.mkdir(parents=True,exist_ok=True);t.build_runner()
    w,h=65,49; y,x=np.indices((h,w)); rng=np.random.default_rng(12077)
    z=np.full((h,w),10,np.float32); n=t.rgba(w,h,(.5,.5,.1),1/3); a=t.rgba(w,h,(1,1,1))
    mask=((x%9<2)&(y>5)&(y<h-5))|((y==h//2)&(x>4)&(x<w-5))
    crop=(slice(5,-5),slice(5,-5),slice(0,3))
    for label,back,ink in (
        ('low contrast',(.5,.5,.5),(.45,.45,.45)),
        ('equal luminance',(.7,.2,.2),(.2,.3486432,.2))):
        c=t.rgba(w,h,back);c[mask,:3]=ink
        ref=t.seed(c)[3]; rr=blur(np.roll(c,2,axis=1),6)
        out=t.compose(rr,ref,z,n,a,anchor=0,mix=0)
        contrast=float(np.linalg.norm(np.array(back)-ink))
        error=float(np.mean(np.linalg.norm(out[mask,:3]-c[mask,:3],axis=1))/contrast)
        t.check(label+' moving strokes recover (anchor/mix off)',error<.05,relative_stroke_error=error)
    # Identical left-half data must not borrow structure confidence across depth.
    clean=t.rgba(w,h,(.35,.35,.35)); noisy=clean.copy()
    noisy[...,:3]+=rng.normal(0,.055,noisy[...,:3].shape)
    isolated=t.seed(noisy)[3]; bounded=isolated.copy()
    bounded[:,w//2:,:3]=np.where((x[:,w//2:]%2)[...,None]==0,0,2)
    bounded[:,w//2:,3]=0
    zz=z.copy(); zz[:,w//2:]=30
    control=isolated.copy(); control[:,w//2:,3]=-1
    o1=t.compose(clean,bounded,zz,n,a);o0=t.compose(clean,control,zz,n,a)
    strip=(slice(5,-5),slice(w//2-4,w//2),slice(0,3))
    err=float(np.max(np.abs(o1[strip]-o0[strip])))
    t.check('other surface cannot lend detail confidence',err<.001,max_error=err)
    # RR already knows the sharp clean signal: adopting noisy current texture is a regression.
    clean=t.rgba(w,h,(.6,.6,.6));clean[mask,:3]=(.1,.15,.2)
    current=clean.copy();current[...,:3]+=rng.normal(0,.035,current[...,:3].shape)
    ref=t.seed(current)[3];out=t.compose(clean,ref,z,n,a)
    before=float(np.sqrt(np.mean((current[crop]-clean[crop])**2)))
    after=float(np.sqrt(np.mean((out[crop]-clean[crop])**2)))
    t.check('sharp clean RR lighting does not regain reference grain',after<before*.35,
            input_rms=before,output_rms=after)
    # Moving glyphs with independently added grain: both blur and noise must fall.
    current=clean.copy();current[...,:3]+=rng.normal(0,.025,current[...,:3].shape)
    ref=t.seed(current)[3];stale=blur(np.roll(clean,2,axis=1),6)
    out=t.compose(stale,ref,z,n,a,anchor=0,mix=0)
    input_error=float(np.sqrt(np.mean((current[crop]-clean[crop])**2)))
    output_error=float(np.sqrt(np.mean((out[crop]-clean[crop])**2)))
    t.check('moving noisy glyphs reduce grain and recover content (anchor/mix off)',output_error<input_error*.7,
            input_rms=input_error,output_rms=output_error)
    background=np.roll(mask,2,axis=1)&~mask
    target_contrast=float(np.mean(clean[background,0])-np.mean(clean[mask,0]))
    output_contrast=float(np.mean(out[background,0])-np.mean(out[mask,0]))
    t.check('moving noisy glyphs preserve 95 percent contrast (anchor/mix off)',
            abs(output_contrast-target_contrast)<abs(target_contrast)*.05,
            target=target_contrast,output=output_contrast)
    unsuppressed=t.compose(stale,ref,z,n,a,noise=0,anchor=0,mix=0)
    unfiltered_error=float(np.sqrt(np.mean((unsuppressed[crop]-clean[crop])**2)))
    t.check('noise control acts on zero rough screen grain',output_error<unfiltered_error*.8,
            suppression_zero_rms=unfiltered_error,suppression_default_rms=output_error)
    # Clean current pixels at the image edge are real content, not an excluded margin.
    texture=t.rgba(w,h,(0,0,0))
    for ch,phase in enumerate((0,1.7,3.1)):
        texture[...,ch]=.5+.22*np.sin(x*.7+y*.3+phase)+.12*np.cos(y*.9-x*.4+phase)
    ref=t.seed(texture)[3];out=t.compose(texture,ref,z,n,a)
    err=float(np.max(np.abs(out[...,:3]-texture[...,:3])))
    t.check('sharp colour at resource border remains intact',err<.034,max_error=err)
    (t.OUT/'results.json').write_text(json.dumps({'checks':t.checks,'dispatches':t.timings},indent=2))
    assert all(c['passed'] for c in t.checks),'screen review regressions'


if __name__=='__main__':run()
