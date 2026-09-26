"""Causal full-radiance RR routing experiment; actual Floor and AMD RR DXIL.

Forced routes are experimental upper bounds, not a surface classifier.
"""
from pathlib import Path
import sys, os, json, subprocess, hashlib
import numpy as np
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[4]
HERE=ROOT/'OptiScaler/shaders/shader_tools/tests'
sys.path.insert(0,str(HERE))
os.environ['FSRD_GPU_TEST_OUTPUT']=str(ROOT/'tools_tmp/tv_grain/gpu')
os.environ['FSRD_VS_ROOT']='F:/VisualStudio'
os.environ['TEMP']=os.environ['TMP']=str(ROOT/'tools_tmp/tv_grain/temp')
Path(os.environ['TEMP']).mkdir(parents=True,exist_ok=True)
import run_fsrd_gpu_tests as t
import probe_fsrd_real_rr as r
from test_fsrd_zero_rough_screen import chain_cb
from fsrd_toolchain import compile_cpp

def rr_run(folder,packed,z):
    folder.mkdir(parents=True,exist_ok=True)
    frames=len(packed);h,w=z.shape
    arr=lambda i:np.stack([p[i] for p in packed])
    normal=arr(3);v=np.rint(np.clip(normal,0,1)*[1023,1023,1023,3]).astype(np.uint32)
    pn=v[...,0]|(v[...,1]<<10)|(v[...,2]<<20)|(v[...,3]<<30)
    entries=[]
    for name,a,fmt in [('depth',z,41),('motion',arr(2),10),('normal',pn,24),
                       ('sa',arr(4),28),('da',arr(5),28),('d',arr(1),10),('s',arr(0),10)]:
        # Integer packed normals are a 3D frame sequence, unlike float4 textures.
        count=1 if name=='depth' else frames
        path,_,_=r.write_texture(folder/(name+'.bin'),a,fmt)
        entries.append((path,fmt,count))
    od,ospec=folder/'out_d.bin',folder/'out_s.bin'
    lines=[f'{w} {h} {frames} 2 32 0 1 0 "{r.DLL.as_posix()}"']
    lines += [f'"{p.as_posix()}" {fmt} {n}' for p,fmt,n in entries]
    lines += [f'"{od.as_posix()}" "{ospec.as_posix()}"']
    job=folder/'job.txt';job.write_text('\n'.join(lines)+'\n')
    p=subprocess.run([str(RR_EXE),str(job)],capture_output=True,text=True)
    (folder/'runner.log').write_text(p.stdout+p.stderr)
    if p.returncode:raise RuntimeError(p.stdout+p.stderr)
    for field in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'):
        if field+'=0' not in p.stdout: raise RuntimeError('RR validation: '+p.stdout+p.stderr)
    print(p.stdout.splitlines()[-1],flush=True)
    outputs=[np.fromfile(path,dtype='<f2').astype(np.float32).reshape(frames,h,w,4) for path in (od,ospec)]
    for path in folder.glob('*.bin'):path.unlink()
    return outputs

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--scene',choices=['flat','smooth','text'],default='smooth');ap.add_argument('--frames',type=int,default=24)
    ap.add_argument('--routes',default='current')
    ap.add_argument('--composition-baseline',type=Path,help='Frozen composition shader for paired actual-RR readback A/B')
    args=ap.parse_args();out=args.output.resolve()
    if out.drive.upper()!='F:': raise ValueError('Keep experiment outputs on F:')
    if args.frames<4: raise ValueError('At least four frames are required')
    out.mkdir(parents=True,exist_ok=False)
    t.OUT=out/'gpu';t.OUT.mkdir();t.runner=t.OUT/'fsrd_gpu_runner.exe';t.build_runner()
    RR_EXE=out/'fsrd_rr_runner.exe';compile_cpp(HERE/'fsrd_rr_runner.cpp',RR_EXE,('d3d12.lib','dxgi.lib'))
    w,h=128,96;y,x=np.indices((h,w),dtype=np.float32);n=args.frames
    z=np.full((h,w),10,np.float32);normal=t.rgba(w,h,(0,0,-1));zero=t.rgba(w,h,(0,0,0))
    diffuse=t.rgba(w,h,(.7,.7,.7));spec=t.rgba(w,h,(.04,.04,.04));rough=np.zeros((h,w),np.float32)
    im=Image.new('RGB',(w,h));draw=ImageDraw.Draw(im);font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',16)
    draw.text((12,38),'RGB 12 TV',font=font,fill=(130,55,170))
    pattern=np.asarray(im,dtype=np.float32)/255
    modes=args.routes.split(',')
    if any(k not in ('current','rr_full','rr_threshold','rr_zero') for k in modes):
        raise ValueError('Unknown route; rr_auto/rr_force production experiments were retired')
    paths={k:[] for k in modes};clean_frames=[];raw_frames=[]
    rng=np.random.default_rng(228101)
    for f in range(n):
        xx=x-f*.12
        clean=t.rgba(w,h,(.06,.075,.09))
        if args.scene!='flat':
            clean[...,:3]+=np.exp(-((xx-35)**2+(y-25)**2)/200)[...,None]*np.array([.5,.45,.4])
            clean[...,:3]+=np.exp(-((y-65-.05*xx)**2)/50)[...,None]*np.array([.1,.03,.13])
        if args.scene=='text':clean[...,:3]+=np.roll(pattern,f//3,axis=1)
        raw=clean.copy();raw[...,:3]=np.maximum(raw[...,:3]+rng.normal(0,.006,(h,w,3)),0)
        base,d,g,ref=t.seed(raw,z,normal,diffuse);base=t.filter_floor(base,d,g,diffuse)
        for mode in paths:
            floor=base if mode=='current' else zero
            # The actual RR runner enables INDIRECT_SPECULAR (32). Packing must
            # publish the matching positive reflection ray length; -1 would
            # turn this into a missing-input test instead of a production test.
            cb=chain_cb(w,h,(1<<1)|(1<<7)|(1<<5)|(1<<4))
            p=t.dispatch('FSRDInputConv',cb,
                [raw,d,zero,normal,rough,z,diffuse,spec,zero,floor,zero,zero,zero,zero,z,zero,ref],
                [10,10,10,24,28,28,10,10],(w,h))
            if mode in ('rr_full','rr_threshold','rr_zero'):p[7][...,3]=-1
            if mode=='rr_threshold':p[3][...,2]=2/1023
            if mode=='rr_zero':p[3][...,2]=0
            paths[mode].append(p)
        clean_frames.append(clean[...,:3]);raw_frames.append(raw[...,:3])
        if f%8==0:print('prepared',f,flush=True)
    clean_frames=np.array(clean_frames);raw_frames=np.array(raw_frames);rows=[]
    for mode,packed in paths.items():
        diffuse_rr,spec_rr=rr_run(out/mode,packed,z);final=[];old_final=[]
        for f,p in enumerate(packed):
            composed=t.dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],
                'DetailPreservation':1.0,'NoiseSuppression':.75},
                [spec_rr[f],p[4],diffuse_rr[f],p[5],p[6],p[3],p[7],z],[10],(w,h))[0]
            final.append(composed[...,:3])
            if args.composition_baseline:
                old=t.dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],
                    'DetailPreservation':1.0,'NoiseSuppression':.75,
                    'FloorHandoverAnchorClamp':4,'FloorHandoverCorrelationMix':1},
                    [spec_rr[f],p[4],diffuse_rr[f],p[5],p[6],p[3],p[7],z],[10],(w,h),
                    directory=args.composition_baseline)[0]
                old_final.append(old[...,:3])
        final=np.array(final)
        if not np.all(np.isfinite(final)):raise RuntimeError('Nonfinite composition')
        e=(final-clean_frames)[n//2:,8:-8,8:-8]
        row=dict(mode=mode,rmse=float(np.sqrt(np.mean(e*e))),
            temporal=float(np.sqrt(np.mean(np.diff(e,axis=0)**2))),bias=float(np.mean(e)),
            mean_skip=float(np.mean([p[6][...,:3] for p in packed])),
            selected=float(np.mean([p[3][...,3]>.16 for p in packed])),
            rr_only_fraction=float(np.mean([p[6][...,3]<=-1 for p in packed])),
            route_flip_fraction=float(np.mean(np.diff(np.array([p[6][...,3]<=-1 for p in packed]),axis=0))),
            mean_route_weight=float(np.mean([np.clip(-p[6][...,3],0,1) for p in packed])),
            route_weight_frame_delta=float(np.mean(np.abs(np.diff(np.array([np.clip(-p[6][...,3],0,1) for p in packed]),axis=0)))),
            roughness=float(np.mean([p[3][...,2] for p in packed])))
        if old_final:
            old_error=(np.array(old_final)-clean_frames)[n//2:,8:-8,8:-8]
            row.update(old_rmse=float(np.sqrt(np.mean(old_error**2))),
                       old_temporal=float(np.sqrt(np.mean(np.diff(old_error,axis=0)**2))))
        rows.append(row);print(json.dumps(row),flush=True)
        np.savez_compressed(out/(mode+'.npz'),clean=clean_frames,raw=raw_frames,final=final,
                            old_final=np.array(old_final))
    (out/'results.json').write_text(json.dumps(dict(scene=args.scene,frames=n,rows=rows,
        dll_sha256=hashlib.sha256(r.DLL.read_bytes()).hexdigest(),
        shader_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in t.PRE.glob('*_Shader.cso')},
        limitations='Actual Floor and AMD RR; no game capture. Optional legacy forced routes are test-only upper bounds. Automatic/forced production routing has been retired. The paired composition comparison uses identical RR readbacks. Synthetic error and temporal proxies do not establish in-game quality.',
        dispatches=t.timings),indent=2))
