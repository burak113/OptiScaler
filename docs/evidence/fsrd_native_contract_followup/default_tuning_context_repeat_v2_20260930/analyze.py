"""Same-binary repeated native source contexts; retain exact lobe payloads."""
from pathlib import Path
import ast,hashlib,json,sys
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests';sys.path.insert(0,str(TESTS))
from fsrd_alpha_common import GPUWorker,convert,compose,rgba,shader_identity
from probe_fsrd_response_calibration import authenticate_reused_source
from probe_fsrd_additive_split import DLL
from native_helper import run_amd
import run_fsrd_gpu_tests as t

CROOT=Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce')
NEW=CROOT/'response_soft_temporal_long_alpha_fresh';OLD=CROOT/'response_soft_temporal_alpha_fresh'
OUT=Path(__file__).resolve().parent/'evidence'
SELECTED=np.array([0,1,31,32,33,34,63])
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def difference(a,b):
    delta=np.asarray(b,dtype=float)-a;where=np.argwhere(delta!=0)
    idx=np.unravel_index(np.argmax(abs(delta)),delta.shape)
    return dict(exact_equal=bool(np.array_equal(a,b)),rms=float(np.sqrt(np.mean(delta**2))),
        differing_values=int(np.count_nonzero(delta)),first_difference=where[0].tolist() if len(where) else None,
        maximum_absolute_difference=float(abs(delta[idx])),maximum_location=list(map(int,idx)),
        first_value=float(a[idx]),second_value=float(b[idx]),
        frame_rms=np.sqrt(np.mean(delta**2,axis=tuple(range(1,delta.ndim)))).tolist())
def main():
    if OUT.exists():raise ValueError('Preserve prior context experiment')
    OUT.mkdir();report_path=NEW/'results.json';report=json.loads(report_path.read_text());before=sha(report_path)
    row=next(v for v in report['rows'] if v['scene']=='lighting_step');case=Path(row['evidence_directory'])
    old_path=OLD/'lighting_step/sequences.npz';new_path=case/'sequences.npz';hashes=dict(old=sha(old_path),new=sha(new_path))
    with np.load(new_path) as a:source=a['observed'].copy();anchor_new=a['baseline'][SELECTED].copy()
    with np.load(old_path) as a:
        np.testing.assert_array_equal(source,a['observed']);anchor_old=a['baseline'][SELECTED].copy()
    ns={'np':np};frozen={}
    for file,name in (('fsrd_alpha_common.py','rgba'),('probe_fsrd_statistical_resolve.py','fixture'),('probe_fsrd_response_calibration.py','research_fixture')):
        path=NEW/'source_snapshot'/file;frozen[file]=sha(path)
        if frozen[file]!=report['source_sha256'][file]:raise ValueError('Fixture source SHA mismatch')
        tree=ast.parse(path.read_text());node=next(v for v in tree.body if isinstance(v,ast.FunctionDef) and v.name==name)
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),ns)
    w,h=report['size'];n=report['frames'];data=ns['research_fixture']('lighting_step',w,h,n,report['seed'])
    controls=np.loadtxt(case/'observed/frame_controls.txt',ndmin=2);np.testing.assert_array_equal(controls,data['controls'])
    exe=NEW/'fsrd_rr_runner.exe';runner_hash=sha(exe);provider_hash=sha(DLL);identity=shader_identity(t.PRE)
    summary=dict(schema='pinned-runner-default-tuning-context-repeat-v1',status='running',quality_accepted=False,game_run=False,
        script_sha256=sha(__file__),preregistration_sha256=sha(Path(__file__).with_name('preregistration.md')),
        reference_report_sha256=before,reference_arrays_sha256=hashes,fixture_source_sha256=frozen,
        runner_path=str(exe),runner_sha256=runner_hash,native_provider_sha256=provider_hash,
        selected_frames=SELECTED.tolist(),contexts=0,dispatches=0,runs=[],pairwise=[],
        limitations=['Four observed contexts are not a population confidence bound.',
            'Only selected frames are composed; full native lobe arrays are retained exactly.',
            'Only tuning flag1->0 skips six effect overrides; no output clearing/binary/provider change. Earlier divergence remains evidence.',
            'Synthetic lighting on one fixed planar surface; no game quality inference.'])
    query=ROOT/'tools_tmp/provider_defaults_query_20260930/evidence/results.json'
    summary['separate_default_query']=dict(path=str(query),sha256=sha(query),keys=json.loads(query.read_text())['keys'],not_queried_by_pinned_runner=True)
    summary['native_helper_sha256']=sha(Path(__file__).with_name('native_helper.py'))
    summary['source_derivation_sha256']=sha(Path(__file__).with_name('source_derivation.json'))
    def save():(OUT/'results.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    save();native=[];composed=[]
    with GPUWorker(OUT):
        packed=[convert(rgba(source[i]),data['diff'][i],data['spec'][i],1,
            depth=data['depth'],normals=data['normals'],roughness=data['roughness'],
            motion=data.get('motion',[None]*n)[i],overrides=data.get('overrides'),resources=data.get('resources')) for i in range(n)]
        checks=OUT/'input_authentication';checks.mkdir()
        summary['input_authentication']=authenticate_reused_source(case/'observed',packed,data['depth'],controls,checks);save()
        for i in range(4):
            folder=OUT/f'repeat_{i}';d,s,_=run_amd(folder,exe,packed,data['depth'],frame_controls=controls)
            manifest=json.loads((folder/'amd_context_identity.json').read_text())
            original=json.loads((case/'observed/amd_context_identity.json').read_text())
            for key in ('inputs','applied_dispatch_sha256','dll_sha256','runner_sha256','dimensions','frames','signals','reset_every','passthrough'):
                if manifest[key]!=original[key]:raise ValueError('Native repeat contract differs: '+key)
            if manifest['tuning']!=0 or manifest['tuning_values']!=[] or manifest['effect_key_configure_count']!=0:raise ValueError('Tuning bundle metadata')
            job_header=(folder/'job.txt').read_text().splitlines()[0].split()
            if job_header[:8]!=['128','80','64','2','32','0','0','0']:raise ValueError('Tuning control job header')
            halves={'diffuse':d.astype('<f2'),'specular':s.astype('<f2')}
            for key,value in halves.items():
                if hashlib.sha256(value.tobytes()).hexdigest()!=manifest['output_sha256'][key+'.bin']:
                    raise ValueError('Native FP16 reconstruction differs from consumed output bytes')
            rgb=np.stack([compose(packed[j],s[j],d[j],depth=data['depth'],detail=0)[...,:3] for j in SELECTED])
            payload=folder/'native_outputs.npz';np.savez_compressed(payload,**halves,selected_composed_rgb=rgb)
            native.append(np.stack((d,s),axis=-1));composed.append(rgb)
            summary['contexts']+=1;summary['dispatches']+=n
            summary['runs'].append(dict(run=i,retained_payload_path=str(payload),payload_sha256=sha(payload),
                manifest_sha256=sha(folder/'amd_context_identity.json'),
                composed_vs_old16=difference(anchor_old,rgb),composed_vs_long64=difference(anchor_new,rgb)))
            save();print('completed_context',i,flush=True)
    for i in range(4):
        for j in range(i+1,4):
            summary['pairwise'].append(dict(first=i,second=j,native_lobes=difference(native[i],native[j]),selected_composed=difference(composed[i],composed[j])))
    if sha(exe)!=runner_hash or sha(DLL)!=provider_hash or sha(report_path)!=before or sha(old_path)!=hashes['old'] or sha(new_path)!=hashes['new'] or shader_identity(t.PRE)!=identity:
        raise ValueError('Experiment mutated pinned evidence/provider/shaders')
    summary['original_evidence_provider_runner_shaders_unchanged']=True
    summary['status']='completed_diagnostic_not_solution';save()
    print(json.dumps(dict(contexts=4,dispatches=4*n,pairwise_native_rms=[r['native_lobes']['rms'] for r in summary['pairwise']])),flush=True)
if __name__=='__main__':main()
