"""Replay exact significant-phase P; isolate observed native cohort scatter."""
from pathlib import Path
import hashlib,importlib.util,itertools,json,shutil,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests';sys.path.insert(0,str(TESTS))
from fsrd_alpha_common import convert,compose,rgba,shader_identity,save_json
from probe_fsrd_additive_split import write_texture,DLL
from probe_fsrd_statistical_resolve import fixture
from native_helper import run_amd
from capturing_worker import CapturingGPUWorker
SRC=ROOT/'tools_tmp/native_significant_phase_initial_20260930/evidence'
EXE=Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce/response_soft_temporal_long_alpha_fresh/fsrd_rr_runner.exe')
DEST=Path(__file__).with_name('evidence')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def centered(a):return a-a.mean(0,keepdims=True)
def compare(a,b):
    a=np.asarray(a,float);b=np.asarray(b,float);different=np.any(a!=b,axis=(1,2,3))
    return dict(exact=not different.any(),first_difference_frame=int(np.flatnonzero(different)[0]) if different.any() else None,
        rms=float(np.sqrt(np.mean((a-b)**2))),maximum=float(abs(a-b).max()),
        per_frame_rms=np.sqrt(np.mean((a-b)**2,axis=(1,2,3))).tolist())
def decomposition(p,cohort):
    p=np.asarray(p,float);tp=np.asarray(cohort,float)
    d=p[None]-tp;dc=d-d.mean(1,keepdims=True);common=dc.mean(0)
    scatter=dc-common[None]
    total=float(np.mean(dc**2));shared=float(np.mean(common**2));between=float(np.mean(scatter**2))
    np.testing.assert_allclose(total,shared+between,rtol=1e-12,atol=1e-22)
    pc=centered(p);tc=centered(tp.mean(0));vp=float(np.mean(pc**2));vt=float(np.mean(tc**2));cov=float(np.mean(pc*tc))
    np.testing.assert_allclose(shared,vp+vt-2*cov,rtol=1e-12,atol=1e-22)
    np.testing.assert_allclose(scatter,-(tp-tp.mean(1,keepdims=True)-(tp-tp.mean(1,keepdims=True)).mean(0)),rtol=0,atol=1e-15)
    return dict(cohort_count=len(tp),mean_context_temporal_variance=total,common_correction_temporal_variance=shared,
        context_scatter_temporal_variance=between,scatter_fraction=between/total if total else None,
        common_pilot_temporal_variance=vp,mean_native_response_temporal_variance=vt,pilot_mean_response_covariance=cov,
        variance_identity_error=abs(total-shared-between),shared_identity_error=abs(shared-vp-vt+2*cov))
def main():
    if DEST.exists():raise ValueError('Preserve earlier evidence')
    original=json.loads((SRC/'results.json').read_text());assert original['status']=='completed_research_not_solution'
    assert sha(EXE)=='3427689a4764380f885545c353250277e4d71944d3310c8a17b3cbba0f3c21d2'
    assert sha(DLL)==original['native_provider_sha256']
    DEST.mkdir();snap=DEST/'source_snapshot';snap.mkdir()
    for p in Path(__file__).parent.iterdir():
        if p.suffix in ('.py','.md'):shutil.copyfile(p,snap/p.name)
    report=dict(schema='same-pilot-native-context-cohort-v1',status='running',quality_accepted=False,game_run=False,runtime_implemented=False,
        original_report_sha256=sha(SRC/'results.json'),provider_sha256=sha(DLL),runner_sha256=sha(EXE),rows=[],completed_native_contexts=0,
        source_sha256={p.name:sha(p) for p in snap.iterdir()},limitations=[
            'Two frozen synthetic cases; context0 measured earlier, not randomized population inference.',
            'Shared P fluctuations and deterministic native settling remain in common correction.',
            'Repeated native contexts do not provide independent source observations.',
            'All GPU/native contracts retained; ordinary debug only. No solution acceptance.'])
    save_json(DEST/'results.json',report)
    with CapturingGPUWorker(DEST):
        for scene in ('material','wave'):
            folder=DEST/scene;folder.mkdir();old=SRC/scene/'blind_pilot';identity=json.loads((old/'amd_context_identity.json').read_text())
            npz=SRC/scene/'sequences.npz';seqhash=sha(npz)
            with np.load(npz) as a:p=a['pilot'].copy();saved=a['pilot_response'].copy()
            data=fixture(scene,128,80,64,950301);controls=np.loadtxt(old/'frame_controls.txt',ndmin=2)
            np.testing.assert_array_equal(controls,data['controls'])
            packed=[convert(rgba(p[i]),data['diff'][i],data['spec'][i],1,depth=data['depth'],normals=data['normals'],roughness=data['roughness']) for i in range(64)]
            arrays=[data['depth'],np.stack([v[2] for v in packed]),np.stack([v[3] for v in packed]),
                np.stack([v[4] for v in packed]),np.stack([v[5] for v in packed]),np.stack([v[1] for v in packed]),np.stack([v[0] for v in packed])]
            contract=folder/'regenerated_native_inputs';contract.mkdir()
            for i,(arr,fmt) in enumerate(zip(arrays,[41,10,24,28,28,10,10])):
                target=contract/f'input{i}.bin';write_texture(target,arr,fmt)
                if sha(target)!=identity['inputs'][target.name] or sha(old/target.name)!=identity['inputs'][target.name]:raise ValueError('Regenerated native input mismatch')
            def compose_lobes(d,s):return np.stack([compose(v,s[i],d[i],depth=data['depth'],detail=0)[...,:3] for i,v in enumerate(packed)])
            def raw(path):return np.fromfile(path,'<f2').reshape(64,80,128,4).astype(np.float32)
            old_d=raw(old/'diffuse.bin');old_s=raw(old/'specular.bin')
            assert sha(old/'diffuse.bin')==identity['output_sha256']['diffuse.bin'] and sha(old/'specular.bin')==identity['output_sha256']['specular.bin']
            recomposed=compose_lobes(old_d,old_s);np.testing.assert_array_equal(recomposed,saved)
            composed=[recomposed];native=[np.concatenate([old_d,old_s],axis=-1)]
            for repeat in range(1,4):
                ctx=folder/f'repeat_{repeat}';d,s,_=run_amd(ctx,EXE,packed,data['depth'],frame_controls=controls)
                current=json.loads((ctx/'amd_context_identity.json').read_text())
                assert current['inputs']==identity['inputs'] and current['applied_dispatch_sha256']==identity['applied_dispatch_sha256']
                composed.append(compose_lobes(d,s));native.append(np.concatenate([d,s],axis=-1))
                report['completed_native_contexts']+=1;save_json(DEST/'results.json',report)
            cohort=np.stack(composed);native=np.stack(native)
            windows={}
            for name,sl in [('full',slice(None)),('mature',slice(-16,None))]:
                pp=p[sl,5:-5,5:-5];tt=cohort[:,sl,5:-5,5:-5]
                ps=pp-pp.mean((1,2),keepdims=True);ts=tt-tt.mean((2,3),keepdims=True)
                windows[name]=dict(total=decomposition(pp,tt),non_dc=decomposition(ps,ts))
            pairs=[dict(a=i,b=j,composed=compare(cohort[i],cohort[j]),raw_lobes=compare(native[i],native[j])) for i,j in itertools.combinations(range(4),2)]
            np.savez_compressed(folder/'cohort.npz',pilot=p,pilot_responses=cohort)
            assert sha(npz)==seqhash
            report['rows'].append(dict(scene=scene,source_sequences_sha256=seqhash,source_context_identity_sha256=sha(old/'amd_context_identity.json'),
                source_original_files_unchanged=True,original_response_recomposition_bit_exact=True,all_seven_native_inputs_exact=True,
                applied_controls_exact=True,windows=windows,pairs=pairs))
            save_json(DEST/'results.json',report)
            print(scene,dict(nonexact_pairs=sum(not q['composed']['exact'] for q in pairs),mature_non_dc=windows['mature']['non_dc']),flush=True)
    assert report['completed_native_contexts']==6
    report['status']='completed_diagnostic_not_solution';report['native_RR_dispatches']=384
    report['conversion_dispatches']=128;report['composition_dispatches']=512
    save_json(DEST/'results.json',report)
if __name__=='__main__':main()
