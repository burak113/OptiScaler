"""Controlled real AMD RR 1.2 albedo/roughness experiments, independent of Floor.

The guide-only intervention deliberately keeps the supplied RR signal unchanged.
The demod-remod intervention changes factorisation consistently and closes the
unrepresentable share via Skip, as the production single-channel conversion does.
Neither intervention proves which buffers Cyberpunk actually publishes.
"""
from pathlib import Path
import argparse, hashlib, json, os, subprocess, sys, time
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
sys.path.insert(0,str(HERE.parent))
from fsrd_toolchain import compile_cpp

W,H=256,192
DLL=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'

def rgba(x,alpha=0):
    a=np.asarray(x,dtype=np.float32)
    if a.ndim==2: a=np.repeat(a[...,None],3,axis=-1)
    return np.concatenate([a,np.full((*a.shape[:-1],1),alpha,dtype=np.float32)],axis=-1)

def pattern():
    im=Image.new('RGB',(W,H),(70,85,100)); d=ImageDraw.Draw(im)
    for text,y,size,col in [('FLOOR RR',8,32,(200,190,130)),('Video TEXT 0123',53,19,(200,140,200)),('small RGB letters',82,13,(130,190,200))]:
        f=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',size)
        d.text((12,y),text,font=f,fill=col)
    for i,width in enumerate((1,2,4,8)):
        x0=12+i*61
        for x in range(x0,x0+48):
            d.line((x,108,x,135),fill=(180,130,170) if ((x-x0)//width)%2 else (65,85,105))
    # Quiet ROI supplies noise measurement without conflating blur with variance.
    d.rectangle((12,148,243,179),fill=(100,100,100))
    return np.asarray(im,dtype=np.float32)/255.

def sequence(n,motion,noise_kind='fine',seed=91021):
    base=pattern()
    clean=np.stack([np.roll(base,f if motion!='static' else 0,axis=1) for f in range(n)])
    rng=np.random.default_rng(seed)
    if noise_kind=='none': noise=np.zeros_like(clean)
    else:
        z=rng.normal(size=clean.shape).astype(np.float32)
        if noise_kind=='coarse':
            for axis in (1,2):
                z=sum(np.roll(z,k,axis=axis) for k in range(-3,4))/np.sqrt(7.)
        # Positive reflected-light term (mean .15), independent of the screen texture.
        noise=.15*(np.exp(.65*z-.5*.65**2)-1)
    return clean,np.maximum(clean+noise,0)

def write_texture(path,a,fmt=10):
    a=np.asarray(a)
    if fmt==10: a=a.astype('<f2')
    elif fmt==41: a=a.astype('<f4')
    elif fmt==28: a=np.round(np.clip(a,0,1)*255).astype('u1')
    elif fmt==24: a=a.astype('<u4')
    a.tofile(path)
    return path,fmt,(a.shape[0] if a.ndim==4 else 1)

def guides(n,kind,clean,noisy=None):
    if kind=='pattern': a=np.round(clean*255)/255.
    elif kind=='flat': a=np.full_like(clean,128/255.)
    elif kind=='white': a=np.ones_like(clean)
    elif kind=='black': a=np.zeros_like(clean)
    elif kind=='dark': a=np.full_like(clean,1/255.)
    elif kind=='wrong': a=np.roll(np.round(clean*255)/255.,17,axis=2)
    elif kind=='noisy':
        if noisy is None: raise ValueError('noisy pseudo-albedo requires observed radiance')
        a=np.round(np.clip(noisy,.008,1)*255)/255.
    else: raise ValueError(kind)
    return a

def prepare_case(folder,case,n,*,inputs=None,albedo_override=None):
    folder.mkdir(parents=True,exist_ok=True)
    clean,noisy=inputs if inputs is not None else sequence(n,case['motion'],case.get('noise','fine'),case.get('seed',91021))
    a=guides(n,case['albedo'],clean,noisy) if albedo_override is None else albedo_override
    if a.shape != noisy.shape or not np.all(np.isfinite(a)) or np.any(a<0) or np.any(a>1):
        raise ValueError('Albedo must be a finite [0,1] RGB sequence matching the input')
    factor=a if case['path']=='demod' else np.ones_like(a)
    signal=noisy/np.maximum(factor,.008)
    # Match actual half storage before closing the unmapped residual.
    signal=signal.astype(np.float16).astype(np.float32)
    skip=np.maximum(noisy-signal*factor,0) if case['path']=='demod' else np.zeros_like(noisy)
    raw=rgba(signal,case.get('hit',20.))
    static=lambda x: x[0] if np.array_equal(x,np.broadcast_to(x[0],x.shape)) else x
    entries=[]
    entries.append(write_texture(folder/'depth.bin',np.full((H,W),10,np.float32),41))
    mv=np.zeros((H,W,4),np.float32)
    if case['motion']=='tracked': mv[...,0]=-1/W
    entries.append(write_texture(folder/'motion.bin',mv))
    # Octahedral normal for N=(0,0,-1), toward a camera looking down positive Z.
    packed=(1023|(1023<<10)|(int(round(case['roughness']*1023))<<20)|(case.get('material',0)<<30))
    entries.append(write_texture(folder/'normal.bin',np.full((H,W),packed,dtype=np.uint32),24))
    is_diff=case['signal'] in ('dd','id')
    zero=np.zeros((H,W,4),np.float32)
    alb=static(rgba(a))
    entries.append(write_texture(folder/'spec_albedo.bin',zero if is_diff else alb,28))
    entries.append(write_texture(folder/'diff_albedo.bin',alb if is_diff else zero,28))
    entries.append(write_texture(folder/'diff_signal.bin',raw if is_diff else zero))
    entries.append(write_texture(folder/'spec_signal.bin',zero if is_diff else raw))
    flags={'dd':(2,0),'id':(16,0),'ds':(0,4),'is':(0,32)}
    df,sf=flags[case['signal']]
    output_d,output_s=folder/'output_diff.bin',folder/'output_spec.bin'
    lines=[f'{W} {H} {n} {df} {sf} {int(case.get("reset",False))} {case.get("tuning",1)} {int(case.get("passthrough",False))} "{DLL.as_posix()}"']
    lines += [f'"{p.as_posix()}" {fmt} {count}' for p,fmt,count in entries]
    lines += [f'"{output_d.as_posix()}" "{output_s.as_posix()}"']
    job=folder/'job.txt'; job.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return job,output_d if is_diff else output_s,clean,noisy,signal,factor,skip,a

def metrics(out,raw_out,clean,noisy,signal,motion):
    n=len(out); start=n//2
    def align(a):
        if motion=='static': return a
        return np.stack([np.roll(a[f],-f,axis=1) for f in range(n)])
    y,truth,inp=map(align,(out,clean,noisy))
    e=y[start:]-truth[start:]; ein=inp[start:]-truth[start:]
    quiet=(slice(None),slice(151,177),slice(24,224),slice(None))
    structure=(slice(6,137),slice(24,224),slice(None))
    mean=y[start:].mean(0); target=truth[start:].mean(0)
    def gain(box):
        t=target[box].astype(float); z=mean[box].astype(float)
        t-=t.mean((0,1),keepdims=True); z-=z.mean((0,1),keepdims=True)
        return float(np.sum(t*z)/max(np.sum(t*t),1e-15))
    qerr=e[quiet]; qin=ein[quiet]
    input_rmse=float(np.sqrt(np.mean(ein*ein)))
    qin_rms=float(np.sqrt(np.mean(qin*qin)))
    qin_std=float(np.sqrt(np.mean(np.var(qin,axis=0))))
    result={
        'finite':bool(np.isfinite(out).all() and np.isfinite(raw_out).all()),
        'input_rmse':input_rmse,'output_rmse':float(np.sqrt(np.mean(e*e))),
        'quiet_error_ratio':float(np.sqrt(np.mean(qerr*qerr))/qin_rms) if qin_rms>1e-10 else None,
        'quiet_temporal_std_ratio':float(np.sqrt(np.mean(np.var(qerr,axis=0)))/qin_std) if qin_std>1e-10 else None,
        'quiet_output_rmse':float(np.sqrt(np.mean(qerr*qerr))),
        'structure_contrast_ratio':gain(structure),
        'raw_change_rms':float(np.sqrt(np.mean((raw_out[start:]-signal[start:])**2))),
        'raw_unchanged_fraction':float(np.mean(np.max(np.abs(raw_out[start:]-signal[start:]),axis=-1)<1e-6)),
        'quiet_bias_rgb':qerr.mean((0,1,2)).tolist(),
        'output_input_rmse_ratio':float(np.sqrt(np.mean(e*e))/input_rmse) if input_rmse>1e-10 else None,
        'mean_structure_rmse':float(np.sqrt(np.mean((mean[structure]-target[structure])**2))),
    }
    result['stripe_contrast_ratios']=[gain((slice(110,133),slice(12+i*61,12+i*61+48),slice(None))) for i in range(4)]
    return result

def cases(suite):
    base=dict(signal='dd',albedo='flat',path='guide',roughness=.1,motion='static')
    if suite=='smoke': return [base,dict(base,passthrough=True)]
    if suite=='adversarial':
        result=[]
        for sig in ('dd','is'):
            for a in ('noisy','wrong'):
                for motion in ('static','untracked'):
                    result.append(dict(base,signal=sig,albedo=a,path='demod',motion=motion))
            result.append(dict(base,signal=sig,hit=-1.))
            for r in (1/1023,2/1023):
                result.append(dict(base,signal=sig,roughness=r,reset=True))
        return result
    if suite=='causal':
        result=[]
        for sig in ('dd','is'):
            for r in (1/1023,2/1023):
                result.append(dict(base,signal=sig,roughness=r))
            for r in (0.,.1):
                for a in ('pattern','flat'):
                    for motion in ('static','untracked','tracked'):
                        result.append(dict(base,signal=sig,roughness=r,albedo=a,path='demod',motion=motion))
            result.append(dict(base,signal=sig,roughness=0.,reset=True))
            result.append(dict(base,signal=sig,passthrough=True))
            for a in ('pattern','flat'):
                result.append(dict(base,signal=sig,albedo=a,path='demod',seed=17331))
                result.append(dict(base,signal=sig,albedo=a,path='demod',noise='none'))
        return result
    result=[]
    for sig in ('dd','is'):
        for r in (0.,.1):
            for motion in ('static','untracked'):
                for a in ('pattern','flat','white','black'):
                    result.append(dict(base,signal=sig,roughness=r,motion=motion,albedo=a))
    for sig in ('dd','is'):
        for a in ('pattern','flat','white','black','dark'):
            result.append(dict(base,signal=sig,albedo=a,path='demod'))
    for sig in ('dd','is','id','ds'):
        result.append(dict(base,signal=sig,noise='none'))
    for sig in ('dd','is'):
        result.extend([dict(base,signal=sig,motion='tracked'),dict(base,signal=sig,reset=True),dict(base,signal=sig,noise='coarse'),dict(base,signal=sig,albedo='wrong'),dict(base,signal=sig,material=1),dict(base,signal=sig,tuning=0)])
    return result

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,required=True); ap.add_argument('--suite',choices=['smoke','full','causal','adversarial'],default='smoke'); ap.add_argument('--frames',type=int,default=48); ap.add_argument('--no-build',action='store_true'); args=ap.parse_args()
    if args.frames<4: raise ValueError('At least four frames are required')
    out=args.output.resolve()
    if out.drive.upper()!='F:': raise RuntimeError('Experiments must remain on F:')
    out.mkdir(parents=True,exist_ok=True)
    temp=out/'temp'; temp.mkdir(exist_ok=True)
    os.environ.update(TEMP=str(temp),TMP=str(temp),FSRD_VS_ROOT=r'F:\VisualStudio')
    exe=out/'fsrd_rr_runner.exe'
    if not args.no_build: compile_cpp(HERE/'fsrd_rr_runner.cpp',exe,('d3d12.lib','dxgi.lib'))
    results=[]
    for i,c in enumerate(cases(args.suite)):
        name=f'{i:03d}_{c["signal"]}_{c["path"]}_{c["albedo"]}_r{c["roughness"]}_{c["motion"]}'
        folder=out/name
        job,output,clean,noisy,signal,factor,skip,albedo=prepare_case(folder,c,args.frames)
        t=time.monotonic()
        p=subprocess.run([str(exe),str(job)],cwd=folder,capture_output=True,text=True)
        (folder/'runner.log').write_text(p.stdout+p.stderr,encoding='utf-8')
        if p.returncode: print(p.stdout+p.stderr,flush=True); raise RuntimeError(f'{name} failed {p.returncode}')
        raw=np.fromfile(output,dtype='<f2').astype(np.float32).reshape(args.frames,H,W,4)[...,:3]
        reconstructed=raw*factor+skip
        m=metrics(reconstructed,raw,clean,noisy,signal,c['motion'])
        if not m['finite']: raise RuntimeError(f'{name}: nonfinite output')
        np.savez_compressed(folder/'preview.npz',clean=clean[-1],noisy=noisy[-1],result=reconstructed[-1],mean_result=reconstructed[args.frames//2:].mean(0),albedo=albedo[-1])
        results.append(dict(name=name,case=c,metrics=m,seconds=time.monotonic()-t,log=p.stdout.strip()))
        (out/'results.json').write_text(json.dumps({'dll':str(DLL),'dll_sha256':hashlib.sha256(DLL.read_bytes()).hexdigest(),'dimensions':[W,H],'frames':args.frames,'results':results},indent=2),encoding='utf-8')
        print(name,json.dumps(m),flush=True)

if __name__=='__main__': main()
