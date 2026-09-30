"""Remove all frame-to-frame native input changes without changing the provider."""
from pathlib import Path
import hashlib, json, shutil
import numpy as np
from native_resource_guard import run_guarded

ROOT = Path(__file__).resolve().parents[2]
RUNNER = Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce/response_soft_temporal_long_alpha_fresh/fsrd_rr_runner.exe')
RUNNER_HASH = '3427689a4764380f885545c353250277e4d71944d3310c8a17b3cbba0f3c21d2'
DLL = ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'
DLL_HASH = '48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
CONTROLS_HASH = '7e0b704eea9b7035dddab1517f4dd9bd4ee2a7e0d6fb04e90f4d8ec4a2b5d3f0'
FORMATS = [41,10,24,28,28,10,10]
BPP = [4,8,4,4,4,8,8]
W,H,N = 128,80,64

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def difference(first, second):
    delta = second.astype(float)-first
    where = np.argwhere(delta!=0)
    loc = np.unravel_index(np.argmax(abs(delta)), delta.shape)
    return dict(exact_equal=bool(np.array_equal(first,second)), rms=float(np.sqrt(np.mean(delta*delta))),
        maximum_absolute=float(abs(delta[loc])), maximum_location=list(map(int,loc)),
        differing_values=int(np.count_nonzero(delta)), first_difference=where[0].tolist() if len(where) else None,
        frame_rms=np.sqrt(np.mean(delta*delta, axis=tuple(range(1,delta.ndim)))).tolist())

def main():
    folder = Path(__file__).resolve().parent; out = folder/'evidence'
    if out.exists(): raise ValueError('Preserve prior frozen-source evidence')
    if sha(RUNNER)!=RUNNER_HASH or sha(DLL)!=DLL_HASH: raise ValueError('Pinned binary/provider changed')
    source = ROOT/'tools_tmp/default_tuning_context_repeat_20260930'
    failure = source/'failure.json'; records = json.loads(failure.read_text())['retained_files']
    for name,row in records.items():
        path = source/name
        if path.stat().st_size!=row['size'] or sha(path)!=row['sha256']:
            raise ValueError('Retained source changed: '+name)
    old = source/'evidence/repeat_0'
    out.mkdir(); inputs = out/'frozen_inputs'; inputs.mkdir()
    payloads = []
    for index,bpp in enumerate(BPP):
        origin = old/f'input{index}.bin'; path = inputs/f'input{index}.bin'
        data = origin.read_bytes()[:W*H*bpp]; path.write_bytes(data)
        payloads.append(dict(index=index,format=FORMATS[index],frames=1,path=str(path),sha256=sha(path),
            size=len(data),source_path=str(origin),source_sha256=sha(origin),source_frame=0))
    report = dict(schema='frozen-seven-input-pinned-native-four-context-repeat-v1',status='running',
        quality_accepted=False,game_run=False,conversion_dispatches=0,completed_native_contexts=0,completed_native_RR_dispatches=0,
        script_sha256=sha(__file__),guard_source_sha256=sha(folder/'native_resource_guard.py'),
        preregistration_sha256=sha(folder/'preregistration.md'),source_failure_report_sha256=sha(failure),
        runner_path=str(RUNNER),runner_sha256=RUNNER_HASH,provider_path=str(DLL),provider_sha256=DLL_HASH,
        applied_controls_expected_sha256=CONTROLS_HASH,dimensions=[W,H],frames=N,signals=[2,32],
        tuning=1,tuning_values=[.1,.5,.5,40000,40,.5],effect_key_configure_count=6,global_debug_configure=True,
        frozen_inputs=payloads,runs=[],pairwise=[],quality_limitation='Held noisy radiance is not a clean quality target or IID Monte Carlo sequence.')
    def save(): (out/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    save(); native = []
    for run in range(4):
        target = out/f'repeat_{run}'; target.mkdir()
        shutil.copyfile(old/'frame_controls.txt',target/'frame_controls.txt')
        job = target/'job.txt'
        rows = [f'{W} {H} {N} 2 32 0 1 0 "{DLL.as_posix()}"']
        rows.extend(f'"{Path(row["path"]).as_posix()}" {row["format"]} 1' for row in payloads)
        rows.append(f'"{(target/"diffuse.bin").as_posix()}" "{(target/"specular.bin").as_posix()}"')
        job.write_text('\n'.join(rows)+'\n')
        guard = run_guarded([str(RUNNER),str(job)], target)
        log = (target/'stdout.log').read_text(errors='replace')
        ok = guard['status']=='completed' and 'debug_layer=1' in log and (
            'dispatches=64 validation_errors=0 validation_warnings=0 sdk_errors=0 sdk_warnings=0' in log)
        entry = dict(run=run,guard=guard,guard_sha256=sha(target/'resource_guard.json'),job_sha256=sha(job),
            stdout_sha256=sha(target/'stdout.log'),stderr_sha256=sha(target/'stderr.log'),completed_all_64=ok)
        report['runs'].append(entry); save()
        if not ok:
            report['status']='stopped_native_or_resource_guard_failure'; save(); return
        if sha(target/'dispatch_controls.bin')!=CONTROLS_HASH:
            raise ValueError('Applied controls mismatch')
        values = []
        for name in ('diffuse','specular'):
            path = target/(name+'.bin')
            if path.stat().st_size!=N*W*H*8: raise ValueError('Native output byte count')
            array = np.fromfile(path,dtype='<f2').reshape(N,H,W,4)
            if not np.all(np.isfinite(array)): raise ValueError('Nonfinite native output')
            values.append(array.copy()); entry[name+'_sha256']=sha(path)
        entry['applied_controls_sha256']=sha(target/'dispatch_controls.bin')
        native.append(np.stack(values,axis=-1))
        report['completed_native_contexts']+=1; report['completed_native_RR_dispatches']+=N
        save(); print('completed_frozen_context',run,'working_set',guard['peak_observed_working_set_bytes'],flush=True)
    for first in range(4):
        for second in range(first+1,4):
            report['pairwise'].append(dict(first=first,second=second,
                RGBA=difference(native[first],native[second]),RGB=difference(native[first][...,:3,:],native[second][...,:3,:])))
    if sha(RUNNER)!=RUNNER_HASH or sha(DLL)!=DLL_HASH or any(sha(row['path'])!=row['sha256'] for row in payloads):
        raise ValueError('Pinned runner/provider/input mutation')
    for name,row in records.items():
        if sha(source/name)!=row['sha256']: raise ValueError('Old source mutated')
    report['status']='completed_diagnostic_not_solution'; report['prior_source_unchanged']=True; save()
    print('pairwise_RGB_RMS', [row['RGB']['rms'] for row in report['pairwise']], flush=True)

if __name__=='__main__': main()
