"""Real AMD comparison of allocation and post-RR statistical reconstruction.

Independent observations use separate noisy streams AND separate AMD contexts.
They are a controlled feasibility experiment, not an available game history.
Truth is constructed here for scoring only; resolve receives noisy observations.
"""
from pathlib import Path
import argparse, hashlib, json, shutil, os
from concurrent.futures import ProcessPoolExecutor
import numpy as np
from fsrd_alpha_common import GPUWorker, convert, compose, rgba, save_json, shader_identity
from fsrd_allocation_models import estimate
from fsrd_statistical_resolve import resolve, observation_evidence
from probe_fsrd_allocation_models import build_field_shader
from probe_fsrd_additive_split import run_amd, blur, DLL, LUMA
from fsrd_toolchain import compile_cpp
import run_fsrd_gpu_tests as t

SCENES=('fake_diffuse','fake_specular','fake_both','material','specular_material',
        'wave','guide_noise','moving_light','lighting_step','hdr','reset','disocclusion','metadata_exposure')


def resolve_job(job):
    args,kwargs=job
    return resolve(*args,**kwargs)


def fixture(name,w,h,frames,seed):
    y,x=np.indices((h,w),dtype=float)
    island=(((x-.4*w)/(.12*w))**2+((y-.54*h)/(.16*h))**2)<1
    pattern=.5+.5*np.sin(.7*x+.17*y)*np.cos(.53*y)
    d=np.full((h,w,3),.2);s=np.full_like(d,.05)
    truth=np.broadcast_to([.14,.17,.2],(frames,h,w,3)).copy()
    if name in ('fake_diffuse','fake_both'): d+=(.28*island)[...,None]
    if name in ('fake_specular','fake_both'): s+=(.12*island)[...,None]
    if name in ('material','lighting_step','hdr','reset','disocclusion','metadata_exposure'):
        d=(.07+.4*pattern)[...,None]*[.7,.85,1.]
        truth[:]=(d+s)*[.45,.38,.32]+[.08,.07,.055]
    if name=='specular_material':
        s=(.025+.12*pattern)[...,None]*[.7,.9,1.]
        truth[:]=d*[.25,.3,.35]+s*[.75,.65,.55]
    if name in ('wave','moving_light'):
        for f in range(frames):
            phase=.8*f if name=='moving_light' else 0
            truth[f]+=(.022*np.sin(.53*x+.21*y+phase))[...,None]
    if name=='lighting_step': truth[frames//2:]*=1.6
    if name=='disocclusion': truth[frames//2:,:,:w//2]+=[.08,.03,.015]
    if name=='hdr': truth*=64
    rng=np.random.default_rng(seed)
    sigma=.012*(64 if name=='hdr' else 1)
    noise=rng.normal(0,sigma,truth.shape)
    if name.startswith('fake_'): noise[:]=0
    raw=(truth+noise).astype(np.float16).astype(np.float32)
    if np.any(raw<0): raise ValueError('Fixture needs biased clipping')
    diffs=np.repeat(rgba(d)[None],frames,0);specs=np.repeat(rgba(s)[None],frames,0)
    if name=='guide_noise': specs[...,:3]=.2+.5*noise
    # CPU predictors must see exactly the source precision uploaded to conversion,
    # not privileged pre-storage material values used to construct metric truth.
    diffs=diffs.astype(np.float16).astype(np.float32)
    specs=specs.astype(np.float16).astype(np.float32)
    depth=np.full((h,w),10,np.float32)
    normal=rgba(np.broadcast_to([0,0,-1],(h,w,3)))
    rough=np.full((h,w),.55,np.float32)
    controls=np.zeros((frames,3));controls[0,0]=1
    if name=='reset': controls[frames//2,0]=1
    exposure=np.ones(frames)
    if name=='metadata_exposure': exposure[frames//2:]=2
    return dict(raw=raw,diff=diffs,spec=specs,depth=depth,normals=normal,roughness=rough,
                truth=truth,controls=controls,pre_exposure_metadata=exposure,island=island)


def score(out,truth,island):
    frames,h,w,_=out.shape;roi=np.zeros((h,w),bool);roi[5:-5,5:-5]=True
    err=out-truth;mean=err.mean(0);low=blur(mean,8)
    contrast=[];phase=[]
    for observed,target in zip(out,truth):
        a=observed@LUMA;b=target@LUMA;a=a[roi]-a[roi].mean();b=b[roi]-b[roi].mean()
        contrast.append(float(a@b/(b@b)) if b@b>1e-8 else None)
        target_fft=np.fft.rfft2((target@LUMA)-(target@LUMA).mean())
        # Mean subtraction on FP32 constant images can leave a DC roundoff
        # residue. DC has no spatial phase and must never select the test mode.
        target_fft[0,0]=0
        idx=np.unravel_index(np.argmax(abs(target_fft)),target_fft.shape)
        v=target_fft[idx]
        phase.append(float(abs(np.angle(np.fft.rfft2((observed@LUMA)-(observed@LUMA).mean())[idx]/v))) if abs(v)>1e-5 else None)
    y,x=np.indices((h,w));radius=np.sqrt(((x-.4*w)/(.12*w))**2+((y-.54*h)/(.16*h))**2)
    profile=[]
    for lo in np.arange(.5,2.01,.1):
        mask=(radius>=lo)&(radius<lo+.1)&roi
        profile.append(mean[mask].mean(0) if mask.any() else np.zeros(3))
    profile=np.array(profile)
    return dict(rmse=float(np.sqrt(np.mean(err[:,roi]**2))),
        frame_rmse=np.sqrt(np.mean(err[:,roi]**2,axis=(1,2))).tolist(),
        bias_rgb=mean[roi].mean(0).tolist(),broad_tone_rms=float(np.sqrt(np.mean(low[roi]**2))),
        residual_temporal_std=float(np.mean(np.std(err[:,roi],axis=0))),
        ring_width=float(np.sum(np.any(abs(profile)>.002,axis=-1))*.1),
        contrast_gain=contrast,phase_error_radians=phase,
        finite=bool(np.isfinite(out).all()))


def acceptance(measured,base,activity,null_rms,scene):
    failures=[]
    for key in ('rmse','broad_tone_rms','residual_temporal_std'):
        if measured[key]>base[key]*1.05+1e-4: failures.append(key)
    if np.any(abs(np.array(measured['bias_rgb']))>abs(np.array(base['bias_rgb']))*1.05+1e-4): failures.append('RGB_bias')
    if np.any(np.array(measured['frame_rmse'])>np.array(base['frame_rmse'])*1.05+1e-4): failures.append('early_or_transition_frame')
    if scene.startswith('fake_') and measured['ring_width']>base['ring_width']+.001: failures.append('ring_width')
    for key,limit,target in (('contrast_gain',.05,1),('phase_error_radians',.05,0)):
        for a,b in zip(measured[key],base[key]):
            if a is not None and abs(a-target)>abs(b-target)+limit:
                failures.append(key);break
    improvement=base['rmse']-measured['rmse']
    return dict(failures=failures,nonregression=not failures,active=activity>=.01,
        exceeds_observed_null=improvement>max(3*null_rms,.05*base['rmse']),
        effective_success=not failures and activity>=.01 and improvement>max(3*null_rms,.05*base['rmse']))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--scenes',default=','.join(SCENES))
    ap.add_argument('--size',default='96x64');ap.add_argument('--frames',type=int,default=16)
    ap.add_argument('--seed',type=int,default=290929);ap.add_argument('--null-repeats',type=int,default=3)
    ap.add_argument('--cpu-workers',type=int,default=4)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if (out/'results.json').exists(): raise ValueError('Use fresh evidence directory')
    w,h=map(int,args.size.split('x'));frames=args.frames
    if min(w,h)<32 or frames<8 or args.null_repeats<2 or not 1<=args.cpu_workers<=8:
        raise ValueError('Invalid experiment size/worker count')
    os.environ['OPENBLAS_NUM_THREADS']='1' # Each worker owns independent complete frame fits.
    snapshot=out/'source_snapshot';snapshot.mkdir()
    for name in ('probe_fsrd_statistical_resolve.py','fsrd_statistical_resolve.py','fsrd_small_regression.py',
                 'fsrd_allocation_models.py','probe_fsrd_additive_split.py','fsrd_rr_runner.cpp','fsrd_alpha_common.py',
                 'probe_fsrd_allocation_models.py'):
        shutil.copy2(Path(__file__).with_name(name),snapshot/name)
    exe=out/'fsrd_rr_runner.exe';compile_cpp(Path(__file__).with_name('fsrd_rr_runner.cpp'),exe,('d3d12.lib','dxgi.lib'))
    fielddir=build_field_shader(out)
    report=dict(schema='post-rr-resolve-research-v1',status='running',quality_accepted=False,results=[],
        seed=args.seed,size=[w,h],frames=frames,null_repeats=args.null_repeats,production_shaders=shader_identity(t.PRE),
        cpu_workers=args.cpu_workers,source_storage='RGBA16_FLOAT values for both GPU upload and CPU source features',
        comparison_models=['legacy','additive','allocator','guide_only','same_frame_rr','independent_rr','independent_validated_rr'],
        source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.iterdir()},
        field_shader_sha256=hashlib.sha256((fielddir/'FSRDInputConvAdditive_Shader.cso').read_bytes()).hexdigest(),
        limitations=['CPU resolve, no HLSL/runtime deployment. Floor disabled.',
            'Four independent contexts are experimental replicates, not consecutive game history.',
            'Geometry/motion is synthetic; stale surface motion is deliberately tested.',
            'Noisy response and clean metric truth have separate call paths.',
            'Three null contexts measure observed spread, not a population confidence bound.',
            'Rank reduction describes a statistical span, not identified physical lobes.'])
    save_json(out/'results.json',report)
    with GPUWorker(out), ProcessPoolExecutor(max_workers=args.cpu_workers) as cpu:
      for scene in args.scenes.split(','):
        data=fixture(scene,w,h,frames,args.seed);folder=out/scene;folder.mkdir()
        def run(data,mode,directory):
            packed=[]
            for i in range(frames):
                kw={};strength=0
                if mode=='allocator':
                    p,mask,_=estimate(data['raw'][i],data['diff'][i],data['spec'][i],data['depth'],
                        data['normals'],data['roughness'],'lobes_overlap')
                    field=rgba(p);field[...,3]=mask@np.array([1,2,4])
                    kw=dict(directory=fielddir,kernel='additive',resources={17:field});strength=1
                elif mode=='additive': strength=1
                packed.append(convert(rgba(data['raw'][i]),data['diff'][i],data['spec'][i],strength,
                    depth=data['depth'],normals=data['normals'],roughness=data['roughness'],**kw))
            d,s,_=run_amd(directory,exe,packed,data['depth'],frame_controls=data['controls'])
            composed=np.stack([compose(p,s[i],d[i],detail=0)[...,:3] for i,p in enumerate(packed)])
            return composed,packed
        baseline,packed=run(data,'legacy',folder/'legacy')
        identity=json.loads((folder/'legacy/amd_context_identity.json').read_text());identity.pop('output_sha256')
        null=[];null_outputs=[]
        for repeat in range(1,args.null_repeats):
            path=folder/f'null_{repeat}'
            d,s,_=run_amd(path,exe,packed,data['depth'],frame_controls=data['controls'])
            other=json.loads((path/'amd_context_identity.json').read_text());other.pop('output_sha256')
            if identity!=other: raise ValueError('Null contexts have different applied controls/resources')
            color=np.stack([compose(p,s[i],d[i],detail=0)[...,:3] for i,p in enumerate(packed)])
            null.append(dict(rms=float(np.sqrt(np.mean((color-baseline)**2))),maximum=float(abs(color-baseline).max())))
            null_outputs.append(color)
        null_rms=max(v['rms'] for v in null)
        outputs={'legacy':baseline};summaries={}
        for mode in ('additive','allocator'): outputs[mode],_=run(data,mode,folder/mode)
        # Four distinct input noise streams; each owns a distinct complete AMD history.
        cohort=[];cohort_raw=[];cohort_d=[];cohort_s=[]
        for stream in range(4):
            replica=fixture(scene,w,h,frames,args.seed+100003*(stream+1))
            color,_=run(replica,'legacy',folder/f'independent_{stream}')
            cohort.append(color);cohort_raw.append(replica['raw']);cohort_d.append(replica['diff'][...,:3]);cohort_s.append(replica['spec'][...,:3])
        observed=np.array(cohort_raw);cohort=np.array(cohort);cohort_d=np.array(cohort_d);cohort_s=np.array(cohort_s)
        for mode in ('guide_only','same_frame_rr','independent_rr','independent_validated_rr'):
            colors=[];diagnostics=[];jobs=[];observation_records=[]
            for i in range(frames):
                features=[data['diff'][i,...,:3],data['spec'][i,...,:3]]
                kw=dict(require_independence=False)
                if mode=='same_frame_rr': features.append(baseline[i])
                evidence=None
                if mode in ('independent_rr','independent_validated_rr'):
                    # Previous observation, never a future frame. Reset/early-frame
                    # fallback does not claim to repair the underlying RR image.
                    previous=max(0,i-1)
                    count=3 if mode=='independent_validated_rr' else 4
                    samples=np.stack((cohort_d[:count,previous],cohort_s[:count,previous],cohort[:count,previous]),axis=-1)
                    evidence=observation_evidence(observed[:,:previous+1])
                    feature_count=count/(1+(count-1)*evidence['maximum_positive_correlation'])
                    features=list(np.moveaxis(samples.mean(0),-1,0))
                    correspondence=np.ones((h,w),bool)
                    if scene=='disocclusion' and i>=frames//2: correspondence[:,:w//2]=False
                    kw=dict(require_independence=True,history_raw=observed[:,previous],stream_ids=list(range(4)),
                        feature_variance=samples.var(0,ddof=1)/feature_count,correspondence=correspondence,
                        effective_observations=evidence['effective_count'],
                        reset=bool(data['controls'][i,0]) or i==0)
                    if mode=='independent_validated_rr':
                        kw['validation_response']=observed[3,previous]
                jobs.append(((data['raw'][i],np.stack(features,-1),baseline[i],data['depth'],data['normals'],data['roughness']),kw))
                observation_records.append(evidence)
            for i,(color,diag) in enumerate(cpu.map(resolve_job,jobs)):
                evidence=observation_records[i]
                colors.append(color)
                diagnostics.append(dict(activity=float(np.mean(abs(diag['delta'])>1e-5)),
                    confidence_rgb=diag['confidence'].mean((0,1)).tolist(),
                    reason_fraction={str(k):float(np.mean(diag['reason']==k)) for k in range(10)},
                    signed_residual_rgb=diag['residual'].mean((0,1)).tolist(),
                    effective_observations=diag['effective_observations'],observation_evidence=evidence))
                if i in (0,frames//2,frames//2+1,frames-1):
                    np.savez_compressed(folder/f'{mode}_frame{i}.npz',**{k:v for k,v in diag.items() if isinstance(v,np.ndarray)})
            outputs[mode]=np.array(colors);summaries[mode]=diagnostics
        # Raw inter-stream correlation is descriptive: common scene structure also
        # correlates raw observations. Do not call that AMD temporal independence.
        correlations=[]
        for i in range(1,4):
            a=observed[0].ravel();b=observed[i].ravel()
            correlations.append(float(np.corrcoef(a,b)[0,1]) if min(a.std(),b.std())>1e-12 else None)
        base=score(baseline,data['truth'],data['island'])
        rows=[]
        for mode,color in outputs.items():
            m=score(color,data['truth'],data['island'])
            activity=float(np.mean(abs(color-baseline)>1e-5))
            gate=None if mode=='legacy' else acceptance(m,base,activity,null_rms,scene)
            if mode in ('guide_only','same_frame_rr'):
                gate['eligible_for_promotion']=False # Same noisy source can leak into its own features.
            rows.append(dict(model=mode,metrics=m,activity=activity,acceptance=gate,fit=summaries.get(mode)))
            print(scene,mode,'rmse',m['rmse'],'gate',gate,flush=True)
        np.savez_compressed(folder/'sequences.npz',**outputs,truth=data['truth'],raw=data['raw'],
            pre_exposure_metadata=data['pre_exposure_metadata'],null_outputs=np.array(null_outputs))
        report['results'].append(dict(scene=scene,null_contexts=null,raw_inter_stream_correlation=correlations,
            raw_correlation_note='Contains common scene signal; not a calibrated effective sample count.',models=rows))
        save_json(out/'results.json',report)
    report['status']='completed';save_json(out/'results.json',report)


if __name__=='__main__': main()
