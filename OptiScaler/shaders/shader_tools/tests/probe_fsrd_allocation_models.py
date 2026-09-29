"""Bounded spatial-model research -> production packing -> real AMD -> composition.

No new game setting. A CPU-estimated allocation field is injected ONLY in a
separate test shader. Runtime promotion requires all independent quality gates.
"""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess, time
import numpy as np
import run_fsrd_gpu_tests as t
from fsrd_toolchain import dxc, compile_cpp
from fsrd_alpha_common import GPUWorker, convert, compose, rgba, save_json, seed_frame
from fsrd_allocation_models import estimate
from probe_fsrd_additive_split import fixture, run_amd, metrics, DLL, LUMA, blur

SCENES=('fake_diffuse_clean','fake_specular_clean','material_additive',
        'specular_material','wave_constant','lighting_gradient','collinear',
        'fake_specular_noise','exposure_additive','independent_lobes','independent_lobes_additive')


def scene_data(name,frames,seed):
    source=name if name in ('material_additive','exposure_additive') else 'fake_island'
    a=fixture(source,frames,seed)
    if source==name: return a
    h,w=a['depth'].shape; y,x=np.indices((h,w),dtype=float)
    mask=a['island']; pattern=.5+.5*np.sin(x*.70+.17*y)*np.cos(y*.53)
    clean=np.broadcast_to([.14,.17,.20],(h,w,3)).copy()
    if name.startswith('fake_specular'):
        a['diff']=rgba(np.full((h,w,3),.20))
        a['spec']=rgba(np.repeat((.025+.12*mask)[...,None],3,axis=-1))
    elif name=='specular_material':
        a['diff']=rgba(np.full((h,w,3),.20))
        a['spec']=rgba((.025+.12*pattern)[...,None]*np.array([.7,.9,1.]))
        clean=a['diff'][...,:3]*[.25,.30,.35]+a['spec'][...,:3]*[.75,.65,.55]
    elif name=='wave_constant':
        a['diff']=rgba(np.full((h,w,3),.20)); a['spec']=rgba(np.full((h,w,3),.05))
        clean+=(.022*np.sin(x*.53+y*.21)+.014*np.cos(x*.17-y*.39))[...,None]
    elif name=='lighting_gradient':
        a['diff']=rgba((.07+.4*pattern)[...,None]*np.array([.7,.85,1.]))
        clean=(a['diff'][...,:3]+a['spec'][...,:3])*[.45,.38,.32]+(.02+.12*x/w)[...,None]*[1,.5,.2]
    elif name=='collinear':
        a['spec']=rgba(a['diff'][...,:3]*.25)
    elif name in ('independent_lobes','independent_lobes_additive'):
        a['diff']=rgba((.07+.4*pattern)[...,None]*np.array([.7,.85,1.]))
        other=.5+.5*np.sin(x*.21-y*.63)
        a['spec']=rgba((.025+.12*other)[...,None]*np.array([.9,.7,1.]))
        clean=a['diff'][...,:3]*[.25,.30,.35]+a['spec'][...,:3]*[.75,.65,.55]
        if name.endswith('_additive'): clean+=[.08,.07,.055]
    a['truth']=np.repeat(clean[None],frames,axis=0).astype(np.float32)
    rng=np.random.default_rng(seed)
    noise=0 if name.endswith('_clean') else rng.uniform(-np.sqrt(3),np.sqrt(3),a['truth'].shape)*.012
    a['raw']=(a['truth']+noise).astype(np.float16).astype(np.float32)
    a['detail']=(clean@LUMA) if name in ('specular_material','wave_constant','lighting_gradient') else np.zeros((h,w))
    a['scene']=name
    return a


def build_field_shader(output):
    directory=Path(output)/'field_shader'; directory.mkdir(parents=True,exist_ok=True)
    for src in t.PRE.glob('*.hlsl*'): shutil.copy2(src,directory/src.name)
    p=directory/'FSRDInputConv.hlsl'; s=p.read_text()
    s=s.replace('SRV(t0, numDescriptors = 17)','SRV(t0, numDescriptors = 18)')
    s=s.replace('// Dispatch config','Texture2D<float4> ResearchField : register(t17);\n// Dispatch config',1)
    start=s.index('            fittedSpecShare = GetAdditiveSplitShare')
    end=s.index(';',start)+1
    s=s[:start]+'''            const float4 field = ResearchField[px];
            const uint mask = (uint)field.a;
            additiveFitChannels = bool3((mask&1u)!=0, (mask&2u)!=0, (mask&4u)!=0);
            fittedSpecShare = saturate(field.rgb);'''+s[end:]
    p.write_text(s)
    subprocess.run([str(dxc()),'-T','cs_6_2','-E','CSMain','-enable-16bit-types','-O3',
        '-Qstrip_debug','-Qstrip_reflect',str(directory/'FSRDInputConvAdditive.hlsl'),'-Fo',
        str(directory/'FSRDInputConvAdditive_Shader.cso')],check=True,capture_output=True)
    return directory


def extended_metrics(out,data,base):
    roi=data['region']; err=out-data['truth']; mean=err[-16:].mean(0)
    # Signed radial profile and thresholded width: a broader dark ring cannot hide
    # behind a lower global RMSE. Pixel coordinates and threshold are fixed here.
    h,w=roi.shape; y,x=np.indices((h,w)); r=np.sqrt(((x-w*.4)/(w*.12))**2+((y-h*.54)/(h*.16))**2)
    profile=[]
    for lo in np.arange(.5,2.01,.1):
        mask=(r>=lo)&(r<lo+.1)&roi
        profile.append(mean[mask].mean(0).tolist() if mask.any() else [0,0,0])
    profile=np.array(profile)
    return dict(signed_ring_profile_rgb=profile.tolist(),
        ring_width_normalized=(np.sum(np.any(abs(profile)>.002,axis=-1))*.1),
        broad_tone_rgb=blur(mean,8)[roi].mean(0).tolist(),
        broad_tone_rms=float(np.sqrt(np.mean(blur(mean,8)[roi]**2))),
        frame_rmse=[float(np.sqrt(np.mean(e[roi]**2))) for e in err])


def assess(scene, measured, base, frames):
    """Fixed budgets; the radial width gate applies only to island fixtures."""
    failures=[]
    for key in ('target_rmse','low_frequency_error_rms','quiet_temporal_std','broad_tone_rms'):
        if measured[key]>base[key]*1.05+.0001: failures.append(key)
    if np.any(abs(np.array(measured['bias_rgb']))>abs(np.array(base['bias_rgb']))*1.05+.0001):
        failures.append('signed_rgb_bias')
    if scene.startswith('fake_') and measured['ring_width_normalized']>base['ring_width_normalized']+.001:
        failures.append('ring_width')
    if measured['detail_gain_truth_distance'] is not None and measured['detail_gain_truth_distance']>base['detail_gain_truth_distance']+.05:
        failures.append('detail_contrast')
    if scene=='exposure_additive':
        f=frames//2
        if np.any(np.array(measured['frame_rmse'][f:f+4])>np.array(base['frame_rmse'][f:f+4])*1.05+.0001):
            failures.append('early_transition')
    active_enough=max(measured['effect_fraction_rgb'])>=.01 and measured.get('actual_signal_changed',False)
    improved=measured['target_rmse']<base['target_rmse']*.95
    return dict(nonregression=not failures,failures=failures,active=active_enough,
                effective_success=not failures and active_enough and improved)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--scenes',default=','.join(SCENES))
    parser.add_argument('--frames',type=int,default=64)
    parser.add_argument('--seed',type=int,default=618203)
    parser.add_argument('--floor',choices=['off','on'],default='off')
    parser.add_argument('--models',default='surface_overlap,lobes_overlap')
    args=parser.parse_args(); output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    if (output/'results.json').exists(): raise ValueError('Use a fresh evidence directory')
    fielddir=build_field_shader(output)
    snapshot=output/'source_snapshot'; snapshot.mkdir()
    for name in ('fsrd_allocation_models.py','probe_fsrd_allocation_models.py','fsrd_alpha_common.py'):
        shutil.copy2(Path(__file__).with_name(name),snapshot/name)
    executable=output/'fsrd_rr_runner.exe'
    compile_cpp(Path(__file__).with_name('fsrd_rr_runner.cpp'),executable,('d3d12.lib','dxgi.lib'))
    report=dict(schema='allocation-field-research-v1',seed=args.seed,frames=args.frames,
        floor=args.floor,status='running',quality_accepted=False,results=[],
        gates=dict(relative_regression=.05,absolute_error_floor=.0001,min_effect_fraction=.01,
                   minimum_target_improvement=.05,ring_width_increase=0,ring_width_scenes='fake_*'),
        routing='Two-lobe estimates have no additive destination. Identifiable additive residuals reject routing.',
        limitations='CPU block-support feasibility estimator, not runtime performance or game acceptance. No share history. Truth excluded from estimator.',
        source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.iterdir()},
        field_shader_sha256=hashlib.sha256((fielddir/'FSRDInputConvAdditive_Shader.cso').read_bytes()).hexdigest(),
        dll_sha256=hashlib.sha256(DLL.read_bytes()).hexdigest())
    save_json(output/'results.json',report)
    with GPUWorker(output):
      for scene in args.scenes.split(','):
        data=scene_data(scene,args.frames,args.seed)
        floor_data=[seed_frame(rgba(raw),data['diff'],data['depth'],data['normals'],t.PRE)
                    for raw in data['raw']] if args.floor=='on' else None
        floors=[v[0] for v in floor_data] if floor_data is not None else [None]*args.frames
        base=None; baseline_identity=None
        for mode in ['baseline']+args.models.split(','):
            begin=time.monotonic(); packed=[]; diag_rows=[]; active=[]; effects=[]; allocations=[]; closure=0
            folder=output/(scene+'_'+mode); folder.mkdir()
            cached_fit=None
            for f,raw in enumerate(data['raw']):
                # Both endpoints run the SAME injected-field DXIL. Strength zero
                # ignores this texture; unrelated compiler reassociation is excluded.
                resources={17:np.zeros_like(data['diff'])}
                if mode!='baseline':
                    residual=np.maximum(raw-floors[f][...,:3],0) if floors[f] is not None else raw
                    same_input=(f>0 and np.array_equal(raw,data['raw'][f-1]) and
                                (floors[f] is None or np.array_equal(floors[f],floors[f-1])))
                    if same_input and cached_fit is not None:
                        p,mask,diagnostics=cached_fit
                    else:
                        p,mask,diagnostics=estimate(residual,data['diff'],data['spec'],data['depth'],data['normals'],data['roughness'],mode)
                        cached_fit=(p,mask,diagnostics)
                    field=rgba(p)
                    field[...,3]=mask@np.array([1,2,4])
                    resources[17]=field
                    active.append(mask[data['region']].mean(0).tolist())
                    qd=np.rint(data['diff'][...,:3].astype(np.float16).astype(float)*255)/255
                    qs=np.rint(data['spec'][...,:3].astype(np.float16).astype(float)*255)/255
                    effects.append(((abs(p-qs/np.maximum(qd+qs,.008))>1e-4)&mask)[data['region']].mean(0).tolist())
                    allocations.append(p)
                    diag_rows.append({k:np.mean(v[data['region']],axis=0).tolist() for k,v in diagnostics.items()})
                    if f in (0,args.frames//2,args.frames-1):
                        np.savez_compressed(folder/f'fit_{f}.npz',p=p,active=mask,**diagnostics)
                pack=convert(rgba(raw),data['diff'],data['spec'],0 if mode=='baseline' else 1,
                    directory=fielddir,kernel='additive',
                    depth=data['depth'] if floor_data is None else floor_data[f][1],
                    normals=data['normals'],roughness=data['roughness'],floor=floors[f],
                    reference=None if floor_data is None else floor_data[f][2],resources=resources)
                packed.append(pack)
                if f in (0,args.frames//2,args.frames-1):
                    closure=max(closure,float(np.max(abs(compose(pack,detail=0)[...,:3]-raw))))
            rr_depth=data['depth'] if floor_data is None else floor_data[0][1]
            if floor_data is not None and not all(np.array_equal(v[1],rr_depth) for v in floor_data):
                raise ValueError('Changing depth needs per-frame AMD uploads')
            rr_d,rr_s,log=run_amd(folder,executable,packed,rr_depth,data['camera'])
            identity=json.loads((folder/'amd_input_identity.json').read_text())
            if mode=='baseline': baseline_identity=identity
            composed=np.stack([compose(p,rr_s[f],rr_d[f],detail=0)[...,:3] for f,p in enumerate(packed)])
            skip=np.stack([p[6][...,:3] for p in packed])
            shares=np.stack([p[4][...,3] for p in packed])
            measured=metrics(composed,data,skip,shares,min(16,args.frames),closure)
            measured['identity_audited_frames']=[0,args.frames//2,args.frames-1]
            measured.update(extended_metrics(composed,data,base))
            measured['amd_input_sha256']=identity
            measured['actual_signal_changed']=any(identity[f'input{i}.bin']!=baseline_identity[f'input{i}.bin'] for i in (5,6))
            measured['activity_rgb']=np.mean(active,axis=0).tolist() if active else [0,0,0]
            measured['effect_fraction_rgb']=np.mean(effects,axis=0).tolist() if effects else [0,0,0]
            measured['allocation_temporal_std_rgb']=np.std(allocations,axis=0)[data['region']].mean(0).tolist() if allocations else [0,0,0]
            np.savez_compressed(folder/'preview.npz',result=composed[-1],mean=composed[-16:].mean(0),truth=data['truth'][-1],mean_error=(composed[-16:]-data['truth'][-16:]).mean(0))
            passed=None
            if mode=='baseline': base=measured
            else:
                passed=assess(scene,measured,base,args.frames)
            report['results'].append(dict(scene=scene,model=mode,metrics=measured,acceptance=passed,
                                           fit_summary=diag_rows,seconds=time.monotonic()-begin))
            save_json(output/'results.json',report)
            print(scene,mode,'RMSE',measured['target_rmse'],'active',measured['activity_rgb'],'acceptance',passed,flush=True)
    report['status']='completed'
    save_json(output/'results.json',report)
    return 0


if __name__=='__main__': raise SystemExit(main())
