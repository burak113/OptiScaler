"""Test whether zero indirect-specular hit alpha is required for held-input variation."""
from pathlib import Path
import hashlib,json,shutil,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
PARENT=ROOT/'tools_tmp/frozen_source_context_repeat_20260930'
sys.path.insert(0,str(PARENT))
from native_resource_guard import run_guarded
from analyze import RUNNER,RUNNER_HASH,DLL,DLL_HASH,CONTROLS_HASH,W,H,N,difference

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def contrast(first,second):
    return dict(RGBA=difference(first,second),RGB=difference(first[...,:3,:],second[...,:3,:]),
                alpha=difference(first[...,3,:],second[...,3,:]))

def main():
    folder=Path(__file__).resolve().parent;out=folder/'evidence'
    if out.exists():raise ValueError('Preserve hit-distance ablation evidence')
    rp=PARENT/'evidence/results.json';rh=sha(rp);parent=json.loads(rp.read_text())
    if parent['status']!='completed_diagnostic_not_solution':raise ValueError('Incomplete parent')
    if sha(RUNNER)!=RUNNER_HASH or sha(DLL)!=DLL_HASH:raise ValueError('Pinned provider/runner changed')
    for row in parent['frozen_inputs']:
        if sha(row['path'])!=row['sha256']:raise ValueError('Parent payload changed')
    old=np.fromfile(parent['frozen_inputs'][6]['path'],dtype='<f2').reshape(H,W,4)
    if not np.all(old[...,3]==0):raise ValueError('Expected zero specular alpha source')
    out.mkdir();inputs=out/'specular_inputs';inputs.mkdir()
    paths={};input_records={}
    for arm,alpha in (('zero_distance',0),('finite_distance10',10),('sky_distance65504',65504)):
        data=old.copy();data[...,3]=alpha
        if not np.array_equal(data[...,:3],old[...,:3]):raise ValueError('Specular RGB changed')
        path=inputs/(arm+'.bin');data.tofile(path);paths[arm]=path
        input_records[arm]=dict(path=str(path),sha256=sha(path),frames=1,alpha=float(alpha),RGB_exact_original=True)
    report=dict(schema='native-three-arm-indirect-specular-hit-alpha-ablation-v1',status='running',quality_accepted=False,
        game_run=False,conversion_dispatches=0,completed_native_contexts=0,completed_native_RR_dispatches=0,
        script_sha256=sha(__file__),preregistration_sha256=sha(folder/'preregistration.md'),
        parent_report_path=str(rp),parent_report_sha256=rh,runner_sha256=RUNNER_HASH,provider_sha256=DLL_HASH,
        guard_source_sha256=sha(PARENT/'native_resource_guard.py'),applied_controls_expected_sha256=CONTROLS_HASH,
        dimensions=[W,H],frames=N,signals=[2,32],tuning=1,input_specular=input_records,
        input_upload_schedule_identical=True,runs=[],within_arm=[],cross_arm=[],limitations=[
            'Changing indirect hit alpha changes virtual geometry; candidate length is not independently traced.',
            'Held noisy source has no clean image-quality reference.',
            'Four repeat contexts do not establish a population confidence envelope.',
            'No native/provider zero-distance validity or output preservation cause is inferred from these values.'])
    def save():(out/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    save();native={arm:[] for arm in paths}
    for repeat in range(4):
        for arm,specular in paths.items():
            target=out/f'{arm}_repeat{repeat}';target.mkdir()
            shutil.copyfile(PARENT/'evidence/repeat_0/frame_controls.txt',target/'frame_controls.txt')
            rows=[f'{W} {H} {N} 2 32 0 1 0 "{DLL.as_posix()}"']
            for row in parent['frozen_inputs']:
                path=specular if row['index']==6 else Path(row['path'])
                rows.append(f'"{path.as_posix()}" {row["format"]} 1')
            rows.append(f'"{(target/"diffuse.bin").as_posix()}" "{(target/"specular.bin").as_posix()}"')
            job=target/'job.txt';job.write_text('\n'.join(rows)+'\n')
            guard=run_guarded([str(RUNNER),str(job)],target)
            log=(target/'stdout.log').read_text(errors='replace')
            ok=guard['status']=='completed' and 'debug_layer=1' in log and 'dispatches=64 validation_errors=0 validation_warnings=0 sdk_errors=0 sdk_warnings=0' in log
            entry=dict(arm=arm,repeat=repeat,completed_all64=ok,guard=guard,guard_sha256=sha(target/'resource_guard.json'),
                job_sha256=sha(job),stdout_sha256=sha(target/'stdout.log'),stderr_sha256=sha(target/'stderr.log'))
            report['runs'].append(entry);save()
            if not ok:report['status']='stopped_native_or_guard_failure';save();return
            if sha(target/'dispatch_controls.bin')!=CONTROLS_HASH:raise ValueError('Applied controls mismatch')
            values=[]
            for name in ('diffuse','specular'):
                path=target/(name+'.bin');value=np.fromfile(path,dtype='<f2')
                if value.size!=N*H*W*4 or not np.all(np.isfinite(value)):raise ValueError('Invalid native output')
                value=value.reshape(N,H,W,4);values.append(value.copy());entry[name+'_sha256']=sha(path)
                entry[name+'_alpha_unique']=np.unique(value[...,3]).astype(float).tolist()
            entry['applied_controls_sha256']=sha(target/'dispatch_controls.bin')
            native[arm].append(np.stack(values,axis=-1));report['completed_native_contexts']+=1
            report['completed_native_RR_dispatches']+=N;save();print('completed_hit_alpha',arm,repeat,flush=True)
    for arm,values in native.items():
        for first in range(4):
            for second in range(first+1,4):
                report['within_arm'].append(dict(arm=arm,first=first,second=second,**contrast(values[first],values[second])))
    for arm in ('finite_distance10','sky_distance65504'):
        for first in range(4):
            for second in range(4):
                report['cross_arm'].append(dict(arm=arm,zero_repeat=first,candidate_repeat=second,
                    **contrast(native['zero_distance'][first],native[arm][second])))
    if sha(rp)!=rh or sha(RUNNER)!=RUNNER_HASH or sha(DLL)!=DLL_HASH:raise ValueError('Pinned evidence mutated')
    for arm,path in paths.items():
        if sha(path)!=input_records[arm]['sha256']:raise ValueError('Generated payload mutated')
    for row in parent['frozen_inputs']:
        if sha(row['path'])!=row['sha256']:raise ValueError('Prior source mutated')
    report['prior_evidence_unchanged']=True;report['status']='completed_diagnostic_not_solution';save()
    for arm in paths:
        rows=[r['RGB']['rms'] for r in report['within_arm'] if r['arm']==arm]
        print(arm,'within_RGB_RMS_range',min(rows),max(rows),flush=True)
    for arm in ('finite_distance10','sky_distance65504'):
        rows=[r['RGB']['rms'] for r in report['cross_arm'] if r['arm']==arm]
        print(arm,'vs_zero_RGB_RMS_range',min(rows),max(rows),flush=True)

if __name__=='__main__':main()
