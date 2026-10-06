"""Two-signal AMD RR experiment: broad guide patches versus fine texture contrast.

Synthetic, not a capture/replay of Cyberpunk. Both signal lobes are derived from
one image exactly as in the integration; no claim that this recovers true lobes.
"""
from pathlib import Path
import argparse, json, os, subprocess, hashlib
import numpy as np
import probe_fsrd_real_rr as rr
from fsrd_toolchain import compile_cpp

W,H=192,128
LUMA=np.array([.2126,.7152,.0722],np.float32)

def quant(a): return np.rint(np.clip(a,0,1)*255)/255

def fixture(n,scene,seed):
    y,x=np.indices((H,W),dtype=np.float32)
    patch=.5+.5*np.tanh(3*np.sin(x/25+np.sin(y/27)))
    envelope=.035+.36*patch
    frames=[];albedos=[]
    for f in range(n):
        phase=f*.22 if 'moving' in scene else 0
        if 'fine' in scene:
            wave=1+.23*np.sin(x*1.7+y*.73+phase)+.12*np.sin(x*.81-y*1.31-phase)
        elif 'slow' in scene:
            wave=1+.23*np.sin(x*.22+y*.09+phase)+.12*np.sin(x*.16-y*.25-phase)
        else:
            wave=1+.23*np.sin(x*1.05+y*.31+phase)+.12*np.sin(x*.41-y*.67-phase)
        colour=np.array([.24,.31,.36],np.float32)
        clean=wave[...,None]*colour
        # The clean radiance has no broad patches; only the supplied reflectance does.
        # Matched fixture carries wave detail in albedo. Mismatch keeps it out.
        a=envelope[...,None]*np.ones(3,np.float32)
        if 'mismatch' not in scene: a=a*wave[...,None]
        if 'bright' in scene: a=a*1.7
        if 'colour' in scene:
            a=a*np.stack((.7+.2*np.sin(x/9), .8+.15*np.cos(y/11),np.ones_like(x)),axis=-1)
            clean*=np.stack((.8+.2*np.sin(x/9),.85+.15*np.cos(y/11),np.ones_like(x)),axis=-1)
        frames.append(clean);albedos.append(a)
    truth=np.asarray(frames,np.float32)
    noise=np.random.default_rng(seed).normal(0,.025,truth.shape).astype(np.float32)
    if 'clean' in scene: noise*=0
    if 'dim' in scene: truth*=.05;noise*=.05
    if 'hdr' in scene: truth*=8;noise*=8
    raw=np.maximum(truth+noise,0).astype(np.float16).astype(np.float32)
    total=np.asarray(albedos,np.float32)
    return truth,raw,quant(total*.2),quant(total*.8),patch

def factor(raw,diff,spec,variant):
    total=diff+spec
    fraction=spec/np.maximum(total,.008)
    validity=np.clip((total-.004)/.004,0,1);validity=validity**2*(3-2*validity)
    cs=raw*fraction*validity;cd=raw-cs
    if variant=='normalize':
        diff=quant(diff/np.maximum(total,1e-6));spec=quant(spec/np.maximum(total,1e-6))
    elif variant.startswith(('local','wide')):
        wide=variant.startswith('wide')
        target=float(variant[4:] if wide else variant[5:])
        lum=total@LUMA
        # Nine guide-only taps. No colour/radiance filtering.
        r=4 if wide else 2
        pad=np.pad(lum,((0,0),(r,r),(r,r)),mode='edge')
        mean=sum(pad[:,r+dy:r+dy+H,r+dx:r+dx+W] for dy in (-r,0,r) for dx in (-r,0,r))/9
        gain=np.clip(target/np.maximum(mean,1e-6),.25,4)
        gain=np.minimum(gain,1/np.maximum(np.maximum(diff,spec).max(-1),1e-6))
        diff=quant(diff*gain[...,None]);spec=quant(spec*gain[...,None])
    elif variant.startswith('toe'):
        k=float(variant[3:])
        luminance=total@LUMA
        # Common RGB gain, smooth toe, max 2x. Higher sums approach baseline.
        gain=np.minimum(np.sqrt(luminance*luminance+k*k)/np.maximum(luminance,1e-6),2)
        gain=np.minimum(gain,1/np.maximum(np.maximum(diff,spec).max(-1),1e-6))
        diff=quant(diff*gain[...,None]);spec=quant(spec*gain[...,None])
    elif variant.startswith('boost'):
        gain=np.minimum(float(variant[5:]),1/np.maximum(np.maximum(diff,spec).max(-1),1e-6))
        diff=quant(diff*gain[...,None]);spec=quant(spec*gain[...,None])
    elif variant.startswith('scale'):
        gain=float(variant[5:])
        diff=quant(diff*gain);spec=quant(spec*gain)
    fd=np.ones_like(diff) if variant=='bypass' else diff
    fs=np.ones_like(spec) if variant=='bypass' else spec
    if variant.startswith('radiance'):
        gain=float(variant[8:]);fd=fd*gain;fs=fs*gain
    if variant.startswith('spec'):
        fs=fs*float(variant[4:])
    ds=np.minimum(cd/np.maximum(fd,.008),65504).astype(np.float16).astype(np.float32)
    ss=np.minimum(cs/np.maximum(fs,.008),65504).astype(np.float16).astype(np.float32)
    skip=np.maximum(raw-ds*fd-ss*fs,0)
    return diff,spec,ds,ss,fd,fs,skip

def metrics(out,truth,patch):
    err=(out-truth)[len(out)//2:,4:-4,4:-4]
    avg=err.mean(0)
    # Spatial low-pass of error, never of output alone: blur cannot masquerade as noise reduction.
    low=sum(np.roll(np.roll(avg,dy,axis=0),dx,axis=1) for dy in range(-4,5) for dx in range(-4,5))/81
    gains=[]
    for mask in (patch<.15,patch>.85):
        mask=mask[4:-4,4:-4]
        a=truth[len(out)//2:,4:-4,4:-4][:,mask];b=out[len(out)//2:,4:-4,4:-4][:,mask]
        a=a-a.mean(axis=1,keepdims=True);b=b-b.mean(axis=1,keepdims=True)
        gains.append(float(np.sum(a*b)/np.sum(a*a)))
    return dict(rmse=float(np.sqrt(np.mean(err**2))),patch_error=float(np.sqrt(np.mean(low**2))),
                detail_gain=gains,contrast_gap=abs(gains[0]-gains[1]),
                flicker=float(np.sqrt(np.mean(np.diff(err,axis=0)**2))),bias_rgb=err.mean((0,1,2)).tolist())

def production_factor(root,raw,d,s,variant,signal):
    import run_fsrd_gpu_tests as t
    from test_fsrd_zero_rough_screen import chain_cb
    if variant not in ('baseline','spec4'): raise ValueError('Production modes: baseline/spec4')
    t.OUT=root/'conversion';t.OUT.mkdir(exist_ok=True)
    if not getattr(t,'_balance_runner_built',False):
        t.runner=root.parent/'production_gpu_runner.exe'
        t.build_runner();t._balance_runner_built=True
    zero=t.rgba(W,H,(0,0,0));depth=np.full((H,W),10,np.float32)
    normal=t.rgba(W,H,(0,0,1));rough=np.full((H,W),.15,np.float32)
    cb=chain_cb(W,H,(1<<1)|((1<<5) if signal=='indirect' else 0))
    cb['AlbedoExperimentFlags']=4 if variant=='spec4' else 0
    packed=[]
    for i in range(len(raw)):
        c=rr.rgba(raw[i]);da=rr.rgba(d[i]);sa=rr.rgba(s[i])
        p=t.dispatch('FSRDInputConv',cb,[c,depth,zero,normal,rough,depth,da,sa,zero,
                     zero,zero,zero,zero,zero,depth,zero,c],[10,10,10,24,28,28,10,10],(W,H))
        packed.append(p)
    arrays=[np.stack([p[j] for p in packed]) for j in range(8)]
    s=arrays[4][...,:3];d=arrays[5][...,:3]
    fs=s*(4 if variant=='spec4' and signal=='indirect' else 1)
    aux=dict(normal=arrays[3][0],motion=arrays[2],spec=arrays[0],diff=arrays[1],packed=packed,depth=depth)
    return (d,s,arrays[1][...,:3],arrays[0][...,:3],d,fs,arrays[6][...,:3]),aux

def run_case(root,exe,n,scene,seed,variant,signal,production=False):
    folder=root/f'{scene}_{seed}_{signal}_{variant}';folder.mkdir(exist_ok=True)
    truth,raw,d,s,patch=fixture(n,scene,seed)
    aux=None
    if production:
        (d,s,ds,ss,fd,fs,skip),aux=production_factor(folder,raw,d,s,variant,signal)
    else:
        d,s,ds,ss,fd,fs,skip=factor(raw,d,s,variant)
    static=lambda a:a[0] if np.array_equal(a,np.broadcast_to(a[0],a.shape)) else a
    packed=1023|(1023<<10)|(int(round(.15*1023))<<20)
    normalbits=np.full((H,W),packed,np.uint32)
    if aux is not None:
        u=np.rint(np.clip(aux['normal'],0,1)*[1023,1023,1023,3]).astype(np.uint32)
        normalbits=u[...,0]|(u[...,1]<<10)|(u[...,2]<<20)|(u[...,3]<<30)
    entries=[rr.write_texture(folder/'depth.bin',np.full((H,W),10,np.float32),41),
             rr.write_texture(folder/'motion.bin',static(aux['motion']) if aux else np.zeros((H,W,4),np.float32)),
             rr.write_texture(folder/'normal.bin',normalbits,24),
             rr.write_texture(folder/'spec_albedo.bin',static(rr.rgba(s)),28),
             rr.write_texture(folder/'diff_albedo.bin',static(rr.rgba(d)),28),
             rr.write_texture(folder/'diff_signal.bin',aux['diff'] if aux else rr.rgba(ds,65504)),
             rr.write_texture(folder/'spec_signal.bin',aux['spec'] if aux else rr.rgba(ss,20))]
    od,ospec=folder/'output_diff.bin',folder/'output_spec.bin'
    lines=[f'{W} {H} {n} 2 {4 if signal=="direct" else 32} 0 1 0 "{rr.DLL.as_posix()}"']
    lines += [f'"{p.as_posix()}" {fmt} {count}' for p,fmt,count in entries]
    lines += [f'"{od.as_posix()}" "{ospec.as_posix()}"']
    job=folder/'job.txt';job.write_text('\n'.join(lines)+'\n')
    proc=subprocess.run([str(exe),str(job)],capture_output=True,text=True)
    (folder/'runner.log').write_text(proc.stdout+proc.stderr)
    if proc.returncode:raise RuntimeError(proc.stdout+proc.stderr)
    for field in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'):
        if field+'=0' not in proc.stdout:raise RuntimeError(proc.stdout+proc.stderr)
    read=lambda p:np.fromfile(p,dtype='<f2').astype(np.float32).reshape(n,H,W,4)[...,:3]
    out=read(od)*fd+read(ospec)*fs+skip
    if aux is not None:
        import run_fsrd_gpu_tests as t
        p=aux['packed'][-1]
        cc={'DstTexSize':[W,H,1/W,1/H],'Flags':(1<<3) if signal=='indirect' else 0,
            'AlbedoExperimentFlags':4 if variant=='spec4' else 0,'DetailPreservation':0}
        composed=t.dispatch('FSRDOutputComp',cc,[rr.rgba(read(ospec)[-1]),p[4],rr.rgba(read(od)[-1]),p[5],
                          p[6],p[3],p[7],aux['depth']],[10],(W,H))[0][...,:3]
        difference=float(np.max(np.abs(composed-out[-1])))
        if difference>.001:raise RuntimeError(f'GPU composition mismatch {difference}')
        (folder/'production.json').write_text(json.dumps(dict(composition_max_error=difference,
               dispatches=t.timings,quality_path='Production DXIL conversion -> real AMD RR -> production composition (last frame)')))
    if not np.isfinite(out).all():raise RuntimeError('Nonfinite RR output')
    m=metrics(out,truth,patch)
    np.savez_compressed(folder/'preview.npz',clean=truth[-1],noisy=raw[-1],result=out[-1],mean=out[n//2:].mean(0))
    # Delete only explicitly generated scratch files in this case directory.
    for p,_,_ in entries: p.unlink()
    od.unlink();ospec.unlink()
    return dict(scene=scene,seed=seed,signal=signal,variant=variant,metrics=m,log=proc.stdout.strip())

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--frames',type=int,default=32);ap.add_argument('--scenes',default='static,static_clean,moving,mismatch')
    ap.add_argument('--variants',default='baseline,normalize,bypass,toe0.04,toe0.08,toe0.16,scale2')
    ap.add_argument('--signals',default='direct');ap.add_argument('--seed',type=int,default=842)
    ap.add_argument('--production',action='store_true',help='Execute production conversion DXIL for every frame; validate final-frame composition')
    args=ap.parse_args();root=args.output.resolve();root.mkdir(parents=True,exist_ok=True)
    if root.drive.upper()!='F:':raise ValueError('F: outputs only')
    tmp=root/'temp';tmp.mkdir(exist_ok=True);os.environ.update(TEMP=str(tmp),TMP=str(tmp))
    exe=root/'fsrd_rr_runner.exe'
    if not exe.exists():compile_cpp(rr.HERE/'fsrd_rr_runner.cpp',exe,('d3d12.lib','dxgi.lib'))
    report=dict(dll=str(rr.DLL),dll_sha256=hashlib.sha256(rr.DLL.read_bytes()).hexdigest(),frames=args.frames,
                size=[W,H],production=args.production,
                limitations='Synthetic full-frame plane; no game capture, no Floor, no upscaler, no occlusions. '+
                ('Production conversion DXIL every frame and composition DXIL final frame.' if args.production else 'CPU factorisation; production DXIL validated separately.'),results=[])
    for scene in args.scenes.split(','):
        for sig in args.signals.split(','):
            for v in args.variants.split(','):
                r=run_case(root,exe,args.frames,scene,args.seed,v,sig,args.production);report['results'].append(r)
                (root/'results.json').write_text(json.dumps(report,indent=2))
                print(scene,sig,v,json.dumps(r['metrics']),flush=True)
if __name__=='__main__':main()
