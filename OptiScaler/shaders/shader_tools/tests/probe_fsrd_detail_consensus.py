"""Offline, causal four-observation carrier reconstruction and real AMD RR probe.

Production Floor Zero Noise supplies the base. Observed-only integer block search
registers at most three earlier images on the CPU. Actual experimental DXIL then
transforms, rejects uncertain coefficients and reconstructs the carrier. No clean
target, known motion, known noise sigma or RR output enters that computation.

This is a planar content-registration experiment, not an in-game temporal feature.
Engine motion, surface-history validation and subrect lifecycle are not implemented
here. A passing synthetic result cannot authorize production integration by itself.
"""
from pathlib import Path
import argparse, hashlib, json, os, struct, subprocess
import numpy as np
from PIL import Image, ImageDraw
import probe_fsrd_real_rr as rr

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]

def box(x,r):
    pad=((r,r),(r,r))+((0,0),)*(x.ndim-2)
    a=np.pad(x,pad,mode='edge').astype(np.float64)
    a=np.pad(a,((1,0),(1,0))+((0,0),)*(x.ndim-2)).cumsum(0).cumsum(1)
    n=2*r+1
    return ((a[n:,n:]-a[:-n,n:]-a[n:,:-n]+a[:-n,:-n])/(n*n)).astype(np.float32)

def shifted(x,dy,dx):
    h,w=x.shape[:2]
    yy=np.clip(np.arange(h)+dy,0,h-1)
    xx=np.clip(np.arange(w)+dx,0,w-1)
    return x[yy[:,None],xx[None,:]]

def register(current,previous,radius=4,sample_previous=None):
    """Local RGB content search; no ground-truth or engine-motion input."""
    h,w=current.shape[:2]
    # Pilot suppresses fine grain during matching only; colour samples stay sharp.
    a=box(current,1); b=box(previous,1)
    af=a-box(a,2); bf=b-box(b,2)
    ys=np.arange(8,h,16);xs=np.arange(8,w,16)
    if len(ys)==0:ys=np.array([h//2])
    if len(xs)==0:xs=np.array([w//2])
    pick=lambda z:z[ys[:,None],xs[None,:]]
    best=np.full((len(ys),len(xs)),np.inf,np.float32)
    dybest=np.zeros_like(best,dtype=int);dxbest=np.zeros_like(best,dtype=int)
    order=sorted(((dy,dx) for dy in range(-radius,radius+1) for dx in range(-radius,radius+1)),key=lambda v:v[0]*v[0]+v[1]*v[1])
    for dy,dx in order:
        delta=af-shifted(bf,dy,dx)
        dc=box(a-shifted(b,dy,dx),12)
        score=pick(box(np.mean(delta*delta,axis=-1),12)+.04*np.mean(dc*dc,axis=-1))
        better=score<best*.99-1e-10
        best=np.where(better,score,best)
        dybest=np.where(better,dy,dybest);dxbest=np.where(better,dx,dxbest)
    ytile=np.minimum(np.arange(h)//16,len(ys)-1)
    xtile=np.minimum(np.arange(w)//16,len(xs)-1)
    dy=dybest[ytile[:,None],xtile[None,:]]
    dx=dxbest[ytile[:,None],xtile[None,:]]
    y,x=np.indices((h,w));qy=y+dy;qx=x+dx
    inside=(qy>=0)&(qy<h)&(qx>=0)&(qx<w)
    aligned=previous[np.clip(qy,0,h-1),np.clip(qx,0,w-1)]
    aligned_pilot=box(aligned,1)
    old_feature=aligned_pilot-box(aligned_pilot,2)
    covariance=box(np.mean(af*old_feature,axis=-1),12)
    energy=box(np.mean(af*af+old_feature*old_feature,axis=-1),12)
    agreement=2*covariance/np.maximum(energy,1e-12)
    floor=float(np.quantile(best,.25))
    dc=np.sqrt(np.mean(box(a-aligned_pilot,12)**2,axis=-1))
    spread=np.sqrt(np.maximum(box(np.mean(a*a+aligned_pilot*aligned_pilot,axis=-1),12)-
        np.mean(box(a,12)**2+box(aligned_pilot,12)**2,axis=-1),0))
    score=best[ytile[:,None],xtile[None,:]]
    accepted=((score<=max(floor*2.5,1e-8))|(agreement>.7)) & (dc<=.012+.45*spread) & inside
    # A wholesale texture replacement must not establish its own permissive
    # noise floor. Low aggregate structural agreement invalidates this image.
    # Featureless noisy frames can also be rejected: the spatial fallback is
    # deliberately safer than transporting an unverifiable texture history.
    cut=bool(float(np.mean(agreement))<.15 and float(np.median(best))>1e-8)
    if cut:accepted[:]=False
    samples=previous if sample_previous is None else sample_previous
    result=rr.rgba(samples[np.clip(qy,0,h-1),np.clip(qx,0,w-1)])
    result[...,3]=np.where(accepted,0,-1)
    return result,dict(accepted_fraction=float(accepted.mean()),mean_dx=float(dx.mean()),mean_dy=float(dy.mean()),
                      score_floor=floor,mean_agreement=float(agreement.mean()),texture_cut=cut)

def dataset(label,n,root,cache=None):
    """Cached production readbacks are allowed only with matching provenance."""
    import run_fsrd_gpu_tests as t
    import fsrd_stage_probe as p
    from probe_fsrd_floor_carrier import reference_sequence,audit_shaders
    from test_fsrd_zero_noise_debug import inputs_for
    source=(cache or root)/'sources'/label
    if cache is None:source.mkdir(parents=True,exist_ok=True)
    motion='untracked' if 'untracked' in label else 'static'
    noise='none' if label=='clean_static' else ('coarse' if 'coarse' in label else 'fine')
    if label=='local_animation':
        clean,observed=rr.sequence(n,'static','fine',seed=17331)
        delta=observed-clean
        for f in range(n):clean[f,:,:128]=np.roll(clean[f,:,:128],f,axis=1)
        observed=np.maximum(clean+delta,0)
    elif label=='texture_cut':
        clean,observed=rr.sequence(n,'static','fine',seed=17331)
        delta=observed-clean
        clean[n//2:]=np.roll(clean[n//2:],(39,73),axis=(1,2))
        observed=np.maximum(clean+delta,0)
    elif label=='coarse_correlated':
        clean,_=rr.sequence(n,'static','none')
        rng=np.random.default_rng(17331);z=rng.normal(size=clean.shape).astype(np.float32)
        for axis in (1,2):z=sum(np.roll(z,k,axis=axis) for k in range(-3,4))/np.sqrt(7.)
        for f in range(1,n):z[f]=.9*z[f-1]+np.sqrt(1-.9**2)*z[f]
        observed=np.maximum(clean+.15*(np.exp(.65*z-.5*.65**2)-1),0)
    else:
        clean,observed=rr.sequence(n,motion,noise,seed=87133 if label=='coarse_untracked' else 91021)
    shader_hashes={s:hashlib.sha256((t.PRE/(s+'_Shader.cso')).read_bytes()).hexdigest()
                  for s in ('FSRDFloorSeed','FSRDFloor','FSRDOutputComp','FSRDFloorZeroNoise')}
    provenance=dict(observed_sha256=hashlib.sha256(observed.tobytes()).hexdigest(),shader_hashes=shader_hashes,n=n)
    if (source/'provenance.json').exists() and json.loads((source/'provenance.json').read_text())==provenance:
        with np.load(source/'arrays.npz') as data:
            return clean,observed,data['seed'],data['reference'],data['base'],motion
    if cache is not None:raise RuntimeError('Missing or stale read-only source cache: '+str(source))
    # Independently compile the production extraction sources. The Zero Noise
    # bytecode is audited here too; no stale generated shader can supply the base.
    audit_shaders(t.PRE,source)
    dxc=Path(os.environ.get('FSRD_DXC','C:/Program Files (x86)/Windows Kits/10/bin/10.0.26100.0/x64/dxc.exe'))
    compiled=source/'zero_audit.cso'
    proc=subprocess.run([str(dxc),'-T','cs_6_2','-E','CSMain','-enable-16bit-types','-O3','-Qstrip_debug','-Qstrip_reflect',
        '-Fo',str(compiled),str(t.PRE/'FSRDFloorZeroNoise.hlsl')],capture_output=True,text=True)
    if proc.returncode or compiled.read_bytes()!=(t.PRE/'FSRDFloorZeroNoise_Shader.cso').read_bytes():
        raise RuntimeError('Zero Noise shader provenance failed: '+proc.stdout+proc.stderr)
    refs=reference_sequence(t,p,observed,source)
    base=[]
    for f,seed in enumerate(refs['seed']):
        values,inputs=inputs_for(rr.rgba(seed))
        base.append(p.dispatch(values,inputs,'zero_noise')[...,:3])
    base=np.stack(base)
    np.savez_compressed(source/'arrays.npz',seed=refs['seed'],reference=refs['reference'],base=base)
    np.savez_compressed(source/'inputs.npz',clean=clean,observed=observed)
    (source/'provenance.json').write_text(json.dumps(provenance,indent=2))
    return clean,observed,refs['seed'],refs['reference'],base,motion

class GPU:
    def __init__(self,out):
        self.out=out;self.jobs=out/'work';self.jobs.mkdir(exist_ok=True)
        self.exe=out/'fsrd_gpu_runner.exe';self.logs=[]
        rr.compile_cpp(HERE/'fsrd_gpu_runner.cpp',self.exe,('d3d12.lib','dxgi.lib'))
        self.hashes={}
        dxc=Path(os.environ.get('FSRD_DXC','C:/Program Files (x86)/Windows Kits/10/bin/10.0.26100.0/x64/dxc.exe'))
        for entry in ('Forward','Filter','Inverse'):
            dest=out/(entry+'.cso')
            p=subprocess.run([str(dxc),'-T','cs_6_2','-E',entry,'-O3','-Qstrip_debug','-Qstrip_reflect',
                '-Fo',str(dest),str(HERE/'fsrd_detail_consensus.hlsl')],capture_output=True,text=True)
            (out/(entry+'.log')).write_text(p.stdout+p.stderr)
            if p.returncode:raise RuntimeError(p.stdout+p.stderr)
            self.hashes[entry]=hashlib.sha256(dest.read_bytes()).hexdigest()
        self.stderr=(out/'gpu_worker.log').open('w')
        self.worker=subprocess.Popen([str(self.exe),'--server'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                     stderr=self.stderr,text=True,bufsize=1)
    def close(self):
        if getattr(self,'worker',None) is not None:
            self.worker.stdin.close()
            self.worker.wait(timeout=30)
            self.worker=None
            self.stderr.close()
    def __del__(self):
        if getattr(self,'worker',None) is not None:
            try:self.close()
            except Exception:self.worker.kill()
    def dispatch(self,entry,inputs,size,source_size,shift,rejection,spatial):
        w,h=size
        cb=self.jobs/'cb.bin';cb.write_bytes(struct.pack('<4I2ifI',*source_size,w,h,*shift,rejection,int(spatial)))
        records=[f'"{(self.out/(entry+".cso")).as_posix()}" "{cb.as_posix()}" {w} {h} 6 2 1']
        for i,a in enumerate(inputs):
            path=self.jobs/f'in{i}.bin';np.asarray(a,dtype='<f4').tofile(path)
            records.append(f'"{path.as_posix()}" {a.shape[1]} {a.shape[0]} 2')
        for i in range(2):records.append(f'"{(self.jobs/f"out{i}.bin").as_posix()}" {w} {h} 2')
        job=self.jobs/'job.txt';job.write_text('\n'.join(records)+'\n')
        self.worker.stdin.write(str(job)+'\n');self.worker.stdin.flush()
        lines=[]
        while True:
            line=self.worker.stdout.readline()
            if not line:raise RuntimeError('GPU worker ended unexpectedly; see gpu_worker.log')
            if line.startswith('job_complete='):
                code=int(line.split('=')[1]);break
            lines.append(line)
        log=''.join(lines)
        self.logs.append(dict(stage=entry,log=log.strip()))
        if code or 'validation_errors=0 validation_warnings=0' not in log or 'debug_layer=1' not in log:
            raise RuntimeError(log+'; see gpu_worker.log')
        result=[np.fromfile(self.jobs/f'out{i}.bin',dtype='<f4').reshape(h,w,4).copy() for i in range(2)]
        if any(not np.isfinite(v).all() for v in result):raise RuntimeError('Nonfinite experimental output')
        return result
    def reconstruct(self,frames,base,rejection=2.,spatial=False,fallback=None,correlation_aware=False):
        if not 1<=len(frames)<=4 or not np.isfinite(base).all() or np.any(base<0):raise ValueError('Invalid current base or history count')
        if any(a.shape!=(*base.shape[:2],4) or not np.isfinite(a).all() for a in frames):raise ValueError('Invalid observed frame')
        if not np.isfinite(rejection) or rejection<0:raise ValueError('Invalid rejection')
        h,w=base.shape[:2]; gw=((w+11)//8)*8;gh=((h+11)//8)*8
        zero=np.zeros((h,w,4),np.float32)
        fallback=frames[0] if fallback is None else fallback
        empty=zero.copy();empty[...,3]=-1
        observed=list(frames[:1] if spatial else frames)+[empty]*4
        final=np.zeros((h,w,3),np.float64);mass=np.zeros((h,w,1),np.float32)
        for shift in ((0,0),(-4,0),(0,-4),(-4,-4)):
            flags=int(spatial)|(2 if correlation_aware else 0)
            args=((gw,gh),(w,h),shift,rejection,flags)
            coef,var=self.dispatch('Forward',observed[:4]+[rr.rgba(base),fallback],*args)
            filtered,_=self.dispatch('Filter',[coef,var,zero,zero,rr.rgba(base),zero],*args)
            output,_=self.dispatch('Inverse',[filtered,var,zero,zero,rr.rgba(base),zero],*args)
            sx,sy=shift
            final+=output[-sy:h-sy,-sx:w-sx,:3]
            mass+=1
        return (final/mass).astype(np.float32)

def run_rr(exe,folder,clean,observed,carrier,motion,signal):
    n=len(clean)
    albedo=np.round(np.clip(carrier,.008,1)*255)/255.
    case=dict(signal=signal,albedo='candidate',path='demod',roughness=.1,material=1,motion=motion)
    job,result,_,_,raw,factor,skip,_=rr.prepare_case(folder,case,n,inputs=(clean,observed),albedo_override=albedo)
    p=subprocess.run([str(exe),str(job)],cwd=folder,capture_output=True,text=True)
    (folder/'runner.log').write_text(p.stdout+p.stderr)
    if p.returncode or f'dispatches={n} validation_errors=0 validation_warnings=0 sdk_errors=0 sdk_warnings=0' not in p.stdout:
        raise RuntimeError(p.stdout+p.stderr)
    denoised=np.fromfile(result,dtype='<f2').astype(np.float32).reshape(n,rr.H,rr.W,4)[...,:3]
    final=denoised*factor+skip
    if not np.isfinite(final).all() or np.min(final)<0:raise RuntimeError('Invalid RR radiance')
    closure=float(np.max(np.abs(raw*factor+skip-observed)))
    if closure>.003:raise RuntimeError('Quantized demod/remod mismatch')
    np.savez_compressed(folder/'preview.npz',carrier=carrier[-1],albedo=albedo[-1],result=final[-1],clean=clean[-1],noisy=observed[-1])
    return dict(metrics=rr.metrics(final,denoised,clean,observed,raw,motion),identity_max_error=closure,log=p.stdout.strip())

def main():
    raise SystemExit('Archived experiment: requires the retired Zero Noise shader snapshot; unavailable in production.')
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--frames',type=int,default=32)
    ap.add_argument('--datasets',nargs='+',default=['fine_static','fine_untracked','coarse_static','clean_static'])
    ap.add_argument('--reuse',action='store_true')
    ap.add_argument('--source-cache',type=Path,help='Reuse verified production readbacks from an earlier experiment root')
    ap.add_argument('--skip-spatial',action='store_true',help='Omit the rejected single-observation candidate from this ablation')
    ap.add_argument('--correlation-aware',action='store_true',help='Test observed temporal-dependence uncertainty inflation')
    args=ap.parse_args();out=args.output.resolve()
    if out.drive.upper()!='F:' or not 4<=args.frames<=64:raise ValueError('F: output and 4..64 frames required')
    out.mkdir(parents=True,exist_ok=True);temp=out/'temp';temp.mkdir(exist_ok=True)
    os.environ.update(TEMP=str(temp),TMP=str(temp),FSRD_VS_ROOT='F:/VisualStudio',FSRD_GPU_TEST_OUTPUT=str(out/'production_dispatches'))
    import run_fsrd_gpu_tests as t
    t.build_runner()
    gpu=GPU(out)
    snapshots=out/'source_snapshot';snapshots.mkdir(exist_ok=True)
    for name in ('probe_fsrd_detail_consensus.py','fsrd_detail_consensus.hlsl','fsrd_gpu_runner.cpp'):
        (snapshots/name).write_bytes((HERE/name).read_bytes())
    rr_exe=out/'fsrd_rr_runner.exe';rr.compile_cpp(HERE/'fsrd_rr_runner.cpp',rr_exe,('d3d12.lib','dxgi.lib'))
    report=dict(frames=args.frames,shader_hashes=gpu.hashes,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                rr_sha256=hashlib.sha256(rr.DLL.read_bytes()).hexdigest(),
                source_root=str((args.source_cache or out).resolve()),skip_spatial=args.skip_spatial,
                correlation_aware=args.correlation_aware,datasets=[])
    for label in args.datasets:
        d=out/label;d.mkdir(exist_ok=True)
        clean,observed,seed,reference,base,motion=dataset(label,args.frames,out,args.source_cache)
        provenance=dict(input=hashlib.sha256(observed.tobytes()).hexdigest(),base=hashlib.sha256(base.tobytes()).hexdigest(),
            shader_hashes=gpu.hashes,source_sha256=report['source_sha256'],frames=args.frames,
            correlation_aware=args.correlation_aware,skip_spatial=args.skip_spatial)
        if args.reuse and (d/'candidate.npz').exists():
            if json.loads((d/'provenance.json').read_text())!=provenance:raise RuntimeError('Stale cache')
            a=np.load(d/'candidate.npz');candidate=a['candidate'];spatial=a['spatial']
            registration=json.loads((d/'registration.json').read_text())
        else:
            candidate=[];spatial=[];registration=[]
            for f in range(args.frames):
                inputs=[rr.rgba(observed[f])]
                for old in range(f-1,max(f-4,-1),-1):
                    aligned,stats=register(seed[f],seed[old],sample_previous=observed[old])
                    # Search uses the stable seed pilot, but the selected sample
                    # comes from raw observed RGB so clean small glyphs survive.
                    # Reuse the measured displacement, never truth/MV, for RGB.
                    inputs.append(aligned);registration.append(dict(frame=f,history=old,**stats))
                candidate.append(gpu.reconstruct(inputs,base[f],fallback=rr.rgba(reference[f]),correlation_aware=args.correlation_aware))
                if not args.skip_spatial:
                    spatial.append(gpu.reconstruct(inputs,base[f],spatial=True,fallback=rr.rgba(seed[f])))
                if (f+1)%4==0:print(label,'GPU reconstruction',f+1,'/',args.frames,flush=True)
            candidate=np.stack(candidate);spatial=np.stack(spatial) if spatial else np.empty((0,),np.float32)
            np.savez_compressed(d/'candidate.npz',candidate=candidate,spatial=spatial)
            (d/'provenance.json').write_text(json.dumps(provenance,indent=2))
            (d/'registration.json').write_text(json.dumps(registration,indent=2))
        record=dict(name=label,carrier_metrics={},runs=[])
        carriers=dict(flat=np.full_like(observed,128/255),oracle=clean,reference=reference,zero_noise=base,candidate=candidate)
        if not args.skip_spatial:carriers['spatial']=spatial
        for name,carrier in carriers.items():
            record['carrier_metrics'][name]=rr.metrics(carrier,carrier,clean,observed,observed,motion)
            for signal in ('dd','is'):
                run=run_rr(rr_exe,d/(signal+'_'+name),clean,observed,carrier,motion,signal)
                record['runs'].append(dict(carrier=name,signal=signal,**run))
                m=run['metrics'];print(label,signal,name,'error',m['quiet_error_ratio'],'contrast',m['structure_contrast_ratio'],'rmse',m['output_rmse'],flush=True)
        panels=[('Observed',observed[-1]),('Existing reference',reference[-1]),('Zero Noise',base[-1]),
                ('Seed pilot (registration)' if args.skip_spatial else 'Spatial candidate',seed[-1] if args.skip_spatial else spatial[-1]),
                ('Four observations',candidate[-1]),('Known clean (metric only)',clean[-1])]
        image=Image.new('RGB',(3*512,2*420),'#141a21');draw=ImageDraw.Draw(image)
        for i,(name,pixels) in enumerate(panels):
            x=(i%3)*512;y=(i//3)*420
            draw.text((x+10,y+8),name,fill='white')
            image.paste(Image.fromarray(np.uint8(np.clip(pixels,0,1)*255)).resize((512,384)),(x,y+30))
        image.save(d/'comparison.png')
        report['datasets'].append(record)
        (out/'results.json').write_text(json.dumps(report,indent=2))
        (out/'gpu_dispatches.json').write_text(json.dumps(gpu.logs,indent=2))
        (out/'production_dispatches.json').write_text(json.dumps(t.timings,indent=2))
    print('Completed',out/'results.json',flush=True)
    gpu.close()

if __name__=='__main__':main()
