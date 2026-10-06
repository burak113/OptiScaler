"""Independent numerical and rejection contracts for the experimental DXIL."""
from pathlib import Path
import argparse,json,os
import numpy as np
from probe_fsrd_detail_consensus import GPU,register
import probe_fsrd_real_rr as rr

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);args=ap.parse_args()
    out=args.output.resolve()
    if out.drive.upper()!='F:':raise ValueError('F: output required')
    out.mkdir(parents=True,exist_ok=True);(out/'temp').mkdir(exist_ok=True)
    os.environ.update(TEMP=str(out/'temp'),TMP=str(out/'temp'),FSRD_VS_ROOT='F:/VisualStudio')
    gpu=GPU(out);checks=[]
    def check(label,condition,**values):
        checks.append(dict(name=label,passed=bool(condition),**values))
        print('PASS' if condition else 'FAIL',label,values,flush=True)
    rng=np.random.default_rng(30771)
    # These do not compare a duplicated filter: zero rejection has the independent
    # orthonormal-transform invariant of returning the observed arithmetic mean.
    for w,h in ((3,7),(17,13),(32,24)):
        frames=[rr.rgba(rng.uniform(.01,2,(h,w,3)).astype(np.float32)) for _ in range(4)]
        base=rng.uniform(.01,2,(h,w,3)).astype(np.float32)
        result=gpu.reconstruct(frames,base,rejection=0)
        expected=np.mean([a[...,:3] for a in frames],axis=0)
        error=float(np.max(abs(result-expected)))
        check(f'zero rejection restores four-observation mean {w}x{h}',error<5e-6,error=error)
    for level in (0.,1e-5,.4,12000.):
        c=np.empty((17,19,3),np.float32);c[:]=(level,level*.5,level*.25)
        result=gpu.reconstruct([rr.rgba(c)]*4,c*.3)
        error=float(np.max(abs(result-c)))
        check(f'constant colour {level}',error<max(level*2e-6,1e-7),error=error)
    c=rng.uniform(.01,.8,(25,33,3)).astype(np.float32)
    for strength in (1.,4.):
        result=gpu.reconstruct([rr.rgba(c)]*4,np.full_like(c,.3),rejection=strength)
        error=float(np.sqrt(np.mean((result-c)**2)))
        check(f'identical noise-free RGB content survives rejection {strength}',error<1e-5,rmse=error)
    # Unavailable frames must not enter moments; one valid old observation remains.
    one=rr.rgba(c);invalid=rr.rgba(np.full_like(c,50000),-1)
    result=gpu.reconstruct([one,one,invalid,invalid],np.full_like(c,.3))
    check('invalid history cannot lend HDR radiance',np.max(abs(result-c))<2e-5,max_error=float(np.max(abs(result-c))))
    # Signed detail is essential: a dark glyph against a bright clean base survives.
    base=np.full((32,48,3),.8,np.float32);glyph=base.copy();glyph[5:26,19:22]=.05
    result=gpu.reconstruct([rr.rgba(glyph)]*4,base)
    check('negative text detail survives until final radiance',np.max(abs(result-glyph))<1e-5)
    # Raw detail may only bypass the seed once another observation supports it.
    base=np.full((32,48,3),.4,np.float32);plain=rr.rgba(base)
    flash=plain.copy();flash[11:14,17:20,:3]=(1000,200,20)
    for old in (False,True):
        observations=[plain,flash,plain,plain] if old else [flash,plain,plain,plain]
        result=gpu.reconstruct(observations,base,fallback=plain)
        error=float(np.max(abs(result-base)))
        check('isolated flash rejected '+('in history' if old else 'in current'),error<.003,max_error=error)
    result=gpu.reconstruct([flash],base,fallback=plain)
    check('startup uses protected reference fallback',np.max(abs(result-base))<1e-5)
    # History rejection must not blur the already cleaned reference a second time.
    # Different current/raw and fallback values prove the fallback is really used.
    result=gpu.reconstruct([rr.rgba(np.full_like(glyph,.6))],np.full_like(glyph,.8),
                           fallback=rr.rgba(glyph),correlation_aware=True)
    check('startup retains cleaned reference glyph without second shrink',np.max(abs(result-glyph))<1e-5)
    invalid=rr.rgba(np.full_like(glyph,50000),-1)
    result=gpu.reconstruct([rr.rgba(np.full_like(glyph,.6)),invalid,invalid,invalid],
                           np.full_like(glyph,.8),fallback=rr.rgba(glyph),correlation_aware=True)
    check('rejected history retains cleaned reference glyph',np.max(abs(result-glyph))<1e-5)
    result=gpu.reconstruct([rr.rgba(glyph)]*4,np.full_like(glyph,.8),correlation_aware=True)
    check('dependence guard preserves identical clean glyph',np.max(abs(result-glyph))<1e-5)
    correlations={}
    for rho in (0.,.9):
        z=rng.normal(0,.08,(4,192,256,3)).astype(np.float32)
        for f in range(1,4):z[f]=rho*z[f-1]+np.sqrt(1-rho*rho)*z[f]
        frames=[rr.rgba(.4+z[f]) for f in range(4)]
        base=rr.rgba(np.full((192,256,3),.4,np.float32));zero=np.zeros_like(base)
        args=((256,192),(256,192),(0,0),2.,2)
        coef,var=gpu.dispatch('Forward',frames+[base,zero],*args)
        filtered,diagnostic=gpu.dispatch('Filter',[coef,var,zero,zero,base,zero],*args)
        correlations[rho]=float(np.median(diagnostic[16:-16,16:-16,3]))
    check('observed dependence distinguishes independent and AR noise',
          correlations[0]<.2 and correlations[.9]>.4,measured_median_correlation=correlations)
    # Check real DCT coefficients against the analytical basis and sample variance,
    # separately from end-to-end reconstruction. The DC variance has known scale.
    frames=[rr.rgba(np.full((8,8,3),v,np.float32)) for v in (.1,.2,.3,.4)]
    zero=np.zeros_like(frames[0]);base=zero.copy();base[...,:3]=.5
    coef,var=gpu.dispatch('Forward',frames+[base,zero],(8,8),(8,8),(0,0),2.,False)
    check('signed DC coefficient',np.max(abs(coef[0,0,:3]+2))<2e-6,value=coef[0,0,:3].tolist())
    expected=float(np.var([.1,.2,.3,.4],ddof=1)/4*64)
    check('coefficient variance of mean',np.max(abs(var[0,0,:3]-expected))<2e-6,value=float(var[0,0,0]),expected=expected)
    clean=rr.pattern()
    for shift in (-3,0,3):
        current=np.roll(clean,shift,axis=1)
        aligned,stats=register(current,clean)
        crop=(slice(28,-28),slice(28,-28))
        accepted=aligned[crop][...,3]>=0
        error=float(np.sqrt(np.mean((aligned[crop][...,:3][accepted]-current[crop][accepted])**2)))
        check(f'content registration measured shift {shift}',error<.025 and stats['accepted_fraction']>.5,rmse=error,**stats)
    black=np.zeros_like(clean);white=np.ones_like(clean)
    _,stats=register(white,black)
    check('solid scene cut rejects all history',stats['accepted_fraction']==0,**stats)
    # Texture cut with almost unchanged DC is harder than an exposure cut.
    cut=np.roll(clean,(39,73),axis=(0,1))
    aligned,stats=register(cut,clean)
    error=np.mean(abs(cut-clean),axis=-1)
    changed=error>.1
    fraction=float(np.mean(aligned[...,3][changed]>=0))
    check('changed texture regions reject stale content',fraction<.1,accepted_changed_fraction=fraction,**stats)
    local=clean.copy();local[15:96,16:136]=cut[15:96,16:136]
    aligned,stats=register(local,clean)
    changed=np.mean(abs(local-clean),axis=-1)>.1
    fraction=float(np.mean(aligned[...,3][changed]>=0))
    check('partial texture change rejects stale regions',fraction<.1,accepted_changed_fraction=fraction,**stats)
    report=dict(checks=checks,shader_hashes=gpu.hashes,dispatches=gpu.logs)
    (out/'results.json').write_text(json.dumps(report,indent=2))
    gpu.close()
    if not all(x['passed'] for x in checks):raise SystemExit(1)

if __name__=='__main__':main()
