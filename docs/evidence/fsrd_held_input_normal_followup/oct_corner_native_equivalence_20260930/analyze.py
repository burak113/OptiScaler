"""Controlled native test of physically identical oct corner representations."""
from pathlib import Path
import hashlib, json, shutil, sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT/'tools_tmp/frozen_source_context_repeat_20260930'
sys.path.insert(0,str(PARENT))
from native_resource_guard import run_guarded
from analyze import RUNNER, RUNNER_HASH, DLL, DLL_HASH, CONTROLS_HASH, W, H, N, difference

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def decode_uv(packed):
    xy=np.stack(((packed&1023)/1023,((packed>>10)&1023)/1023),axis=-1)*2-1
    normal=np.concatenate((xy,(1-abs(xy).sum(axis=-1))[...,None]),axis=-1)
    fold=np.maximum(-normal[...,2],0)[...,None]
    normal[...,:2]+=np.where(normal[...,:2]>=0,-fold,fold)
    return normal/np.linalg.norm(normal,axis=-1,keepdims=True)

def contrast(first,second):
    rgb1=first[...,:3,:]; rgb2=second[...,:3,:]
    return dict(RGBA=difference(first,second),RGB=difference(rgb1,rgb2),
                RGB_pre32=difference(rgb1[:32],rgb2[:32]),RGB_post32=difference(rgb1[32:],rgb2[32:]))

def main():
    folder=Path(__file__).resolve().parent; out=folder/'evidence'
    if out.exists(): raise ValueError('Preserve oct equivalence evidence')
    parent_path=PARENT/'evidence/results.json'; parent_hash=sha(parent_path); parent=json.loads(parent_path.read_text())
    if parent['status']!='completed_diagnostic_not_solution': raise ValueError('Incomplete parent')
    if sha(RUNNER)!=RUNNER_HASH or sha(DLL)!=DLL_HASH: raise ValueError('Pinned provider/runner changed')
    for row in parent['frozen_inputs']:
        if sha(row['path'])!=row['sha256']: raise ValueError('Frozen parent input changed')
    out.mkdir(); inputs=out/'normal_inputs'; inputs.mkdir()
    original=np.fromfile(parent['frozen_inputs'][2]['path'],dtype='<u4').reshape(H,W)
    if np.any(original&0xfffff): raise ValueError('Expected baseline oct corner0,0')
    alternate=(original | np.uint32(0xfffff)).astype('<u4')
    if not np.array_equal(original&np.uint32(0xfff00000),alternate&np.uint32(0xfff00000)):
        raise ValueError('Normal roughness/material bits changed')
    minus_z=np.broadcast_to([0.,0.,-1.],(H,W,3))
    if not np.array_equal(decode_uv(original),minus_z) or not np.array_equal(decode_uv(alternate),minus_z):
        raise ValueError('Local/sample physical normal equivalence failed')
    constant=inputs/'opposite_constant.bin'; alternate.tofile(constant)
    step=inputs/'opposite_step.bin'
    with step.open('wb') as f:
        for frame in range(N): f.write((original if frame<32 else alternate).tobytes())
    normal_paths={'baseline':Path(parent['frozen_inputs'][2]['path']), 'opposite_constant':constant,'opposite_step':step}
    report=dict(schema='native-three-arm-oct-corner-representation-equivalence-v1',status='running',
        quality_accepted=False,game_run=False,conversion_dispatches=0,completed_native_contexts=0,completed_native_RR_dispatches=0,
        script_sha256=sha(__file__),preregistration_sha256=sha(folder/'preregistration.md'),
        parent_results_path=str(parent_path),parent_results_sha256=parent_hash,
        guard_source_path=str(PARENT/'native_resource_guard.py'),guard_source_sha256=sha(PARENT/'native_resource_guard.py'),
        runner_sha256=RUNNER_HASH,provider_sha256=DLL_HASH,applied_controls_expected_sha256=CONTROLS_HASH,
        physical_normal_exact_local_sample_equivalence=True,baseline_oct=[0,0],opposite_oct=[1,1],
        normal_roughness_material_bits_exact=True,dimensions=[W,H],frames=N,signals=[2,32],tuning=1,
        normal_inputs={arm:dict(path=str(path),sha256=sha(path),frames=N if arm=='opposite_step' else 1) for arm,path in normal_paths.items()},
        runs=[],within_arm=[],cross_arm=[],limitations=[
            'Local/sample decoder equivalence does not reveal private provider implementation.',
            'Observed repeat spread is descriptive, not a confidence bound.',
            'Held noisy radiance and exact-Z planar normal are a diagnostic fixture, not a game quality target.'])
    def save(): (out/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    save(); native={arm:[] for arm in normal_paths}
    for repeat in range(4):
        for arm,normal in normal_paths.items():
            target=out/f'{arm}_repeat{repeat}'; target.mkdir()
            shutil.copyfile(PARENT/'evidence/repeat_0/frame_controls.txt',target/'frame_controls.txt')
            rows=[f'{W} {H} {N} 2 32 0 1 0 "{DLL.as_posix()}"']
            for row in parent['frozen_inputs']:
                index=row['index']; path=normal if index==2 else Path(row['path'])
                frames=N if index==2 and arm=='opposite_step' else 1
                rows.append(f'"{path.as_posix()}" {row["format"]} {frames}')
            rows.append(f'"{(target/"diffuse.bin").as_posix()}" "{(target/"specular.bin").as_posix()}"')
            job=target/'job.txt'; job.write_text('\n'.join(rows)+'\n')
            guard=run_guarded([str(RUNNER),str(job)],target)
            log=(target/'stdout.log').read_text(errors='replace')
            ok=guard['status']=='completed' and 'debug_layer=1' in log and 'dispatches=64 validation_errors=0 validation_warnings=0 sdk_errors=0 sdk_warnings=0' in log
            entry=dict(arm=arm,repeat=repeat,completed_all64=ok,guard=guard,guard_sha256=sha(target/'resource_guard.json'),
                job_sha256=sha(job),stdout_sha256=sha(target/'stdout.log'),stderr_sha256=sha(target/'stderr.log'))
            report['runs'].append(entry); save()
            if not ok: report['status']='stopped_native_or_guard_failure';save();return
            if sha(target/'dispatch_controls.bin')!=CONTROLS_HASH: raise ValueError('Applied dispatch controls differ')
            arrays=[]
            for name in ('diffuse','specular'):
                path=target/(name+'.bin'); value=np.fromfile(path,dtype='<f2')
                if value.size!=N*H*W*4 or not np.all(np.isfinite(value)): raise ValueError('Invalid native output')
                arrays.append(value.reshape(N,H,W,4).copy()); entry[name+'_sha256']=sha(path)
            entry['applied_controls_sha256']=sha(target/'dispatch_controls.bin')
            native[arm].append(np.stack(arrays,axis=-1))
            report['completed_native_contexts']+=1; report['completed_native_RR_dispatches']+=N;save()
            print('completed_oct_arm',arm,repeat,flush=True)
    for arm,values in native.items():
        for first in range(4):
            for second in range(first+1,4):
                report['within_arm'].append(dict(arm=arm,first=first,second=second,**contrast(values[first],values[second])))
    baseline_max=np.max([row['RGB']['frame_rms'] for row in report['within_arm'] if row['arm']=='baseline'],axis=0)
    report['observed_baseline_repeat_max_frame_RGB_RMS']=baseline_max.tolist()
    for arm in ('opposite_constant','opposite_step'):
        for first in range(4):
            for second in range(4):
                row=dict(arm=arm,baseline_repeat=first,candidate_repeat=second,**contrast(native['baseline'][first],native[arm][second]))
                rms=np.asarray(row['RGB']['frame_rms'])
                row['frames_exceeding_observed_baseline_max_repeat_RMS']=np.flatnonzero(rms>baseline_max+1e-12).tolist()
                report['cross_arm'].append(row)
    if sha(parent_path)!=parent_hash or sha(RUNNER)!=RUNNER_HASH or sha(DLL)!=DLL_HASH: raise ValueError('Pinned evidence mutated')
    for arm,path in normal_paths.items():
        if sha(path)!=report['normal_inputs'][arm]['sha256']: raise ValueError('Normal payload mutation')
    for row in parent['frozen_inputs']:
        if sha(row['path'])!=row['sha256']: raise ValueError('Parent input mutation')
    report['status']='completed_diagnostic_not_solution'; report['prior_evidence_unchanged']=True;save()
    for arm in normal_paths:
        rows=[row['RGB']['rms'] for row in report['within_arm'] if row['arm']==arm]
        print(arm,'within_RGB_RMS_range',min(rows),max(rows),flush=True)
    for arm in ('opposite_constant','opposite_step'):
        rows=[row for row in report['cross_arm'] if row['arm']==arm]
        print(arm,'vsbaseline_RGB_RMS_range',min(row['RGB']['rms'] for row in rows),max(row['RGB']['rms'] for row in rows),
            'post32_range',min(row['RGB_post32']['rms'] for row in rows),max(row['RGB_post32']['rms'] for row in rows),flush=True)

if __name__=='__main__': main()
