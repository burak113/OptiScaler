"""Actual AMD RR distance vs resampling experiment, without production Floor edits.

Same-footprint planes at z=2 and z=20 isolate guide scale. Enlarging noisy
pixels does NOT provide new ray samples; independently sampled high resolution
is a separate upper-bound control. All reported outputs use the base grid.
"""
from pathlib import Path
import argparse, hashlib, json, os, subprocess, time
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import probe_fsrd_real_rr as rr
from fsrd_toolchain import compile_cpp

W, H = 192, 128
VARIANTS = ('far', 'near_scaled', 'near_depth_only', 'up_bilinear', 'up_nearest', 'native_high')

def down(a):
    n,h,w,c=a.shape
    return a.reshape(n,h//2,2,w//2,2,c).mean((2,4))

def resize(a, scale=2, nearest=False):
    if nearest: return np.repeat(np.repeat(a,scale,axis=1),scale,axis=2)
    return np.stack([np.stack([np.asarray(Image.fromarray(f[...,k]).resize(
        (f.shape[1]*scale,f.shape[0]*scale),Image.Resampling.BILINEAR))
        for k in range(3)],axis=-1) for f in a])

def pattern():
    s=2
    im=Image.new('RGB',(W*s,H*s),(65,75,90));d=ImageDraw.Draw(im)
    for text,y,size,col in [('SCREEN RGB',8,18,(205,175,115)),('Small text 0123',35,12,(140,210,185)),
                            ('Fine RGB 789',55,8,(200,125,210))]:
        d.text((12*s,y*s),text,font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',size*s),fill=col)
    for i,width in enumerate((1,2,4)):
        for x in range(12+i*60,60+i*60):
            d.rectangle((x*s,80*s,(x+1)*s-1,96*s-1),fill=(170,100,200) if ((x-12-i*60)//width)%2 else (65,75,90))
    a=np.asarray(im,dtype=np.float32)/255
    y,x=np.indices((H*s,W*s),dtype=np.float32)
    a += np.exp(-((x/s-140)**2+(y/s-25)**2)/180)[...,None]*np.array([.12,.1,.07],np.float32)
    return a

def sequence(n,scene,seed):
    moving=scene.startswith('untracked')
    base=pattern()
    if scene.startswith('smooth'):
        y,x=np.indices((H*2,W*2),dtype=np.float32);x/=2;y/=2
        base=np.broadcast_to(np.array([.18,.2,.23],np.float32),(H*2,W*2,3)).copy()
        base+=np.exp(-((x-60)**2+(y-30)**2)/160)[...,None]*np.array([.5,.45,.4],np.float32)
        base+=np.exp(-((y-72-.12*x)**2)/20)[...,None]*np.array([.13,.025,.18],np.float32)
    high=np.stack([np.roll(base,2*f if moving else 0,axis=1) for f in range(n)])
    low=down(high)
    def add(a,rng,coarse):
        z=rng.normal(0,.035,a.shape).astype(np.float32)
        if coarse:
            z=sum(np.roll(np.roll(z,dy,axis=1),dx,axis=2) for dy in (-1,0,1) for dx in (-1,0,1))/3
        return a if scene.endswith('clean') else np.maximum(a+z,0)
    low_raw=add(low,np.random.default_rng(seed),scene.endswith('coarse'))
    high_raw=add(high,np.random.default_rng(seed+10000),False)
    return low,low_raw,high,high_raw

def metrics(output,truth,raw,moving):
    n=len(output);start=n//2
    def align(a):
        return np.stack([np.roll(f,-i if moving else 0,axis=1) for i,f in enumerate(a)])
    out,clean,inp=map(align,(output,truth,raw))
    e=(out-clean)[start:,4:-4,4:-4];ein=(inp-clean)[start:,4:-4,4:-4]
    q=(out-clean)[start:,108:122,16:176]
    mean=out[start:].mean(0);target=clean[start:].mean(0)
    def gain(y0,y1,x0,x1):
        a=target[y0:y1,x0:x1].astype(float);b=mean[y0:y1,x0:x1].astype(float)
        a-=a.mean((0,1),keepdims=True);b-=b.mean((0,1),keepdims=True)
        return float(np.sum(a*b)/max(np.sum(a*a),1e-15))
    return dict(rmse=float(np.sqrt(np.mean(e*e))),input_rmse=float(np.sqrt(np.mean(ein*ein))),
        error_flicker=float(np.sqrt(np.mean(np.diff(e,axis=0)**2))),
        quiet_rmse=float(np.sqrt(np.mean(q*q))),quiet_temporal_std=float(np.sqrt(np.mean(np.var(q,axis=0)))),
        quiet_bias=float(q.mean()),text_gain=gain(8,68,10,182),
        stripe_gain=[gain(81,95,12+i*60,60+i*60) for i in range(3)])

def run_case(out,exe,scene,seed,signal,variant,seq,n,roughness):
    clean,raw,high,high_raw=seq
    enlarged=variant.startswith('up_') or variant=='native_high'
    rr.W,rr.H=(W*2,H*2) if enlarged else (W,H)
    observed=resize(raw,nearest=variant=='up_nearest') if variant.startswith('up_') else high_raw if enlarged else raw
    truth=high if enlarged else clean
    depth=2. if variant.startswith('near_') else 20.
    hit=2. if variant=='near_scaled' else 20.
    folder=out/f'{scene}_{seed}_{signal}_{variant}'
    case=dict(signal=signal,albedo='flat',path='demod',roughness=roughness,
              motion='untracked' if scene.startswith('untracked') else 'static',hit=hit)
    job,path,_,_,demod,factor,skip,albedo=rr.prepare_case(folder,case,n,inputs=(truth,observed))
    rr.write_texture(folder/'depth.bin',np.full((rr.H,rr.W),depth,np.float32),41)
    p=subprocess.run([str(exe),str(job)],capture_output=True,text=True)
    (folder/'runner.log').write_text(p.stdout+p.stderr,encoding='utf-8')
    if p.returncode: raise RuntimeError(p.stdout+p.stderr)
    for field in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'):
        if field+'=0' not in p.stdout: raise RuntimeError(p.stdout+p.stderr)
    result=np.fromfile(path,dtype='<f2').astype(np.float32).reshape(n,rr.H,rr.W,4)[...,:3]*factor+skip
    if not np.isfinite(result).all() or np.any(result<0): raise RuntimeError('Invalid RR output')
    if enlarged: result=down(result)
    m=metrics(result,clean,raw,scene.startswith('untracked'))
    # The native-high input has four independent samples per base pixel.
    m['effective_input_rmse']=metrics(down(observed) if enlarged else observed,clean,raw,scene.startswith('untracked'))['rmse']
    np.savez_compressed(folder/'preview.npz',clean=clean[-1],noisy=raw[-1],result=result[-1],mean=result[n//2:].mean(0))
    # Preserve jobs/logs/metrics and previews, not gigabytes of generated scratch.
    for f in folder.glob('*.bin'): f.unlink()
    return dict(scene=scene,seed=seed,signal=signal,variant=variant,depth=depth,hit=hit,metrics=m,log=p.stdout.strip())

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--frames',type=int,default=32);ap.add_argument('--pilot',action='store_true')
    ap.add_argument('--scenes',default='static_fine,untracked_fine,static_coarse,static_clean,untracked_clean')
    ap.add_argument('--roughness',type=float,default=.1)
    args=ap.parse_args();out=args.output.resolve()
    if out.drive.upper()!='F:' or args.frames<8: raise ValueError('F: output and >=8 frames required')
    out.mkdir(parents=True,exist_ok=False);temp=out/'temp';temp.mkdir()
    os.environ.update(TEMP=str(temp),TMP=str(temp),FSRD_VS_ROOT='F:/VisualStudio')
    exe=out/'fsrd_rr_runner.exe';compile_cpp(rr.HERE/'fsrd_rr_runner.cpp',exe,('d3d12.lib','dxgi.lib'))
    report=dict(frames=args.frames,base_size=[W,H],roughness=args.roughness,albedo=128/255,
        dll=str(rr.DLL),dll_sha256=hashlib.sha256(rr.DLL.read_bytes()).hexdigest(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        runner_sha256=hashlib.sha256((rr.HERE/'fsrd_rr_runner.cpp').read_bytes()).hexdigest(),
        limitations=['Synthetic full-frame plane, no game capture or boundary occlusions.',
        'Stationary camera and zero jitter. Untracked video moves 1 base pixel/frame; geometric motion correctly remains zero.',
        'Near planes retain screen footprint by scaling their world dimensions. Scaled variant also scales reflection distance.',
        '2x variants retain FOV/aspect/depth; all output comparisons use area downsampling to base grid.',
        'Native high is an independent high-sampling control, NOT obtainable by enlarging an existing frame.',
        'Native high uses white noise; coarse-noise scene is not a matched noise-spectrum native-high comparison.',
        'No Floor, Skip detail restoration, upscaler or frame generation. RR direct diffuse and indirect specular are isolated.'],results=[])
    scenes=['static_fine'] if args.pilot else args.scenes.split(',')
    if any(s not in ('static_fine','untracked_fine','static_coarse','static_clean','untracked_clean','smooth_fine') for s in scenes):
        raise ValueError('Unknown scene')
    for scene in scenes:
        for seed in ([7123] if args.pilot or scene.endswith('clean') else [7123,9907]):
            seq=sequence(args.frames,scene,seed)
            for signal in ('dd','is'):
                for variant in VARIANTS:
                    row=run_case(out,exe,scene,seed,signal,variant,seq,args.frames,args.roughness)
                    report['results'].append(row)
                    (out/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                    print(scene,seed,signal,variant,json.dumps(row['metrics']),flush=True)
    print('DONE',len(report['results'])*args.frames,'actual AMD dispatches',flush=True)

if __name__=='__main__':main()
