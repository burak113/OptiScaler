"""Independent read-only audit of the fresh soft native study."""
from pathlib import Path
import hashlib,importlib.util,json,re,sys
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests';sys.path.insert(0,str(TESTS))
from probe_fsrd_statistical_resolve import score
STUDY=Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce/response_soft_temporal_long_alpha_fresh')
VARIANT='soft_temporal_dc_current_safe'
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

OLD_STUDY=STUDY.with_name('response_soft_temporal_alpha_fresh')
def locate(delta):
    indices=np.argwhere(delta!=0)
    if not len(indices):return {'exact_equal':True,'rms':0.0}
    first=tuple(indices[0]);peak=np.unravel_index(np.argmax(np.abs(delta)),delta.shape)
    return dict(exact_equal=False,rms=float(np.sqrt(np.mean(delta.astype(np.float64)**2))),
        first_nonzero_frame_y_x_rgb=list(map(int,first)),first_signed_delta=float(delta[first]),
        max_absolute_frame_y_x_rgb=list(map(int,peak)),max_signed_delta=float(delta[peak]),
        frame_rms=[float(np.sqrt(np.mean(frame.astype(np.float64)**2))) for frame in delta],
        per_rgb_bias=delta.astype(np.float64).mean(axis=(0,1,2)).tolist())

def cross_run_comparison(report):
    old_report_path=OLD_STUDY/'results.json';old_report_sha=digest(old_report_path)
    old=json.loads(old_report_path.read_text());old_rows={x['scene']:x for x in old['rows']};rows=[]
    for row in report['rows']:
        scene=row['scene'];old_folder=OLD_STUDY/scene;new_folder=Path(row['evidence_directory'])
        before_old=digest(old_folder/'sequences.npz');before_new=digest(new_folder/'sequences.npz')
        manifests={}
        for context in ('observed','null_repeat'):
            a=json.loads((old_folder/context/'amd_context_identity.json').read_text())
            b=json.loads((new_folder/context/'amd_context_identity.json').read_text())
            differing=[key for key in set(a)|set(b) if a.get(key)!=b.get(key)]
            manifests[context]=dict(all_seven_inputs_equal=a['inputs']==b['inputs'],
                applied_control_hash_equal=a['applied_dispatch_sha256']==b['applied_dispatch_sha256'],
                frame_control_hash_equal=digest(old_folder/context/'frame_controls.txt')==digest(new_folder/context/'frame_controls.txt'),
                runner_hash_equal=a['runner_sha256']==b['runner_sha256'],provider_hash_equal=a['dll_sha256']==b['dll_sha256'],
                output_hashes_equal=a['output_sha256']==b['output_sha256'],differing_manifest_fields=differing)
            assert all(manifests[context][key] for key in ('all_seven_inputs_equal','applied_control_hash_equal','frame_control_hash_equal','provider_hash_equal'))
        with np.load(old_folder/'sequences.npz') as a,np.load(new_folder/'sequences.npz') as b:
            assert np.array_equal(a['observed'],b['observed'])
            baseline=locate(b['baseline']-a['baseline']);null=locate(b['null_repeat']-b['baseline'])
            raw_sha=hashlib.sha256(a['observed'].tobytes()).hexdigest()
            if scene=='lighting_step':
                peak=tuple(baseline['max_absolute_frame_y_x_rgb'])
                baseline.update(old_at_max=float(a['baseline'][peak]),new_at_max=float(b['baseline'][peak]),
                    old16_null_rms=old_rows[scene]['null_rms'],old16_internal_first_divergence_unavailable=True)
        assert digest(old_folder/'sequences.npz')==before_old and digest(new_folder/'sequences.npz')==before_new
        rows.append(dict(scene=scene,old_sequences_sha256=before_old,new_sequences_sha256=before_new,
            raw_array_sha256=raw_sha,source_raw_exact=True,manifests=manifests,
            cross_run_baseline=baseline,new64_composed_null=null))
    assert digest(old_report_path)==old_report_sha
    return dict(old_report_sha256=old_report_sha,old_runner_sha256=old['runner_sha256'],new_runner_sha256=report['runner_sha256'],runner_cpp_source_hashes_equal=all(old['source_sha256'][k]==report['source_sha256'][k] for k in ('fsrd_rr_runner.cpp','fsrd_gpu_runner.cpp')),rows=rows,
        warning='Native source baseline can vary between contexts/runs despite identical input/controls/provider and matching runner C++ sources, but different compiled runner hashes. New null zero does not explain or erase old lighting-step large null.')

rp=STUDY/'results.json';original_sha=digest(rp);r=json.loads(rp.read_text())
assert r['status']=='completed_research_not_solution' and r['frames']==64 and r['size']==[128,80]
assert r['seed']==920531 and r['history']==64 and r['split_strength']==1 and r['pilot_mode']=='soft_temporal'
assert r['radiance_fallback_registered'] and r['amd_completed_sequences']==39
snapshot=STUDY/'source_snapshot';source_valid={n:digest(snapshot/n)==h for n,h in r['source_sha256'].items()};assert all(source_valid.values())
assert digest(TESTS/'probe_fsrd_statistical_resolve.py')==r['source_sha256']['probe_fsrd_statistical_resolve.py']
spec=importlib.util.spec_from_file_location('frozen_soft',snapshot/'fsrd_response_soft_pilot.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert digest(STUDY/'fsrd_rr_runner.exe')==r['runner_sha256']
dll=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'
assert digest(dll)==r['native_provider_sha256']
audit=dict(schema='soft-temporal-fresh-independent-audit-v1',study=str(STUDY),report_sha256=original_sha,
    audit_source_sha256=digest(__file__),quality_accepted=False,source_snapshot_hashes_valid=source_valid,
    frozen_soft_sha256=r['source_sha256']['fsrd_response_soft_pilot.py'],frames=64,history=64,seed=920531,split_strength=1,
    native_contexts=0,dispatches=0,rows=[],limitations=[
        'Input/output payloads were deleted by the successful helper; retained input manifests attest consumed hashes but bytes cannot now be independently rehashed.',
        'Original history16 study omitted null_repeat: its exact internal first divergence remains unavailable; fresh history64 saved composed null.',
        'Provider direct-DLL version query unavailable result6/id0; native execution validation counts are separately zero.',
        'Relative gates do not promise absolute unit gain or improved temporal noise.',
        'No game capture/runtime acceptance; shared source/guide bias remains a failing case.'])
for row in r['rows']:
    scene=row['scene'];folder=Path(row['evidence_directory']);sp=folder/'sequences.npz';before=digest(sp);contexts={}
    for name in ('observed','null_repeat','pilot'):
        cp=folder/('blind_pilot' if name=='pilot' else name);m=json.loads((cp/'amd_context_identity.json').read_text());inp=json.loads((cp/'amd_input_identity.json').read_text())
        assert m['inputs']==inp and len(inp)==7 and set(inp)=={f'input{i}.bin' for i in range(7)}
        assert m['dll_sha256']==r['native_provider_sha256'] and m['runner_sha256']==r['runner_sha256']
        assert m['dimensions']==[128,80] and m['frames']==64 and m['signals']==[2,32]
        assert m['reset_every']==0 and m['tuning']==1 and m['passthrough']==0
        assert m['tuning_values']==[.1,.5,.5,40000.,40.,.5]
        binary=cp/'dispatch_controls.bin';assert digest(binary)==m['applied_dispatch_sha256']
        data=binary.read_bytes();assert len(data)==64*184
        ui=np.frombuffer(data,'<u4').reshape(64,46);fl=np.frombuffer(data,'<f4').reshape(64,46)
        controls=np.loadtxt(cp/'frame_controls.txt',ndmin=2)
        np.testing.assert_array_equal(ui[:,0],np.arange(64));np.testing.assert_array_equal(ui[:,2:],np.tile(ui[0,2:],(64,1)))
        # Floats after the header are constant except jitter; all current fixtures use zero jitter.
        np.testing.assert_array_equal(ui[:,1],2+np.where((controls[:,0]!=0)|(np.arange(64)==0),1,0))
        np.testing.assert_array_equal(ui[:,2:4],np.tile([128,80],(64,1)))
        np.testing.assert_array_equal(fl[:,4:7],np.ones((64,3)));assert not fl[:,7:10].any()
        np.testing.assert_array_equal(fl[:,10:12],controls[:,1:].astype(np.float32));assert np.isfinite(fl[:,4:]).all()
        log=(cp/'runner.log').read_text();process=json.loads((cp/'runner_process.json').read_text())
        assert process['returncode']==0 and process['runner_sha256']==r['runner_sha256'] and process['log_sha256']==digest(cp/'runner.log')
        assert 'debug_layer=1' in log and all(re.search(r'\b'+field+r'=0\b',log) for field in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'))
        match=re.search(r'\bdispatches=(\d+)\b',log);assert match and int(match.group(1))==64
        audit['native_contexts']+=1;audit['dispatches']+=64
        contexts[name]=dict(manifest_sha256=digest(cp/'amd_context_identity.json'),input_identity_sha256=digest(cp/'amd_input_identity.json'),
            applied_controls_sha256=digest(binary),frame_controls_sha256=digest(cp/'frame_controls.txt'),
            log_sha256=digest(cp/'runner.log'),process_sha256=digest(cp/'runner_process.json'),job_sha256=digest(cp/'job.txt'),
            output_sha256=m['output_sha256'],inputs=inp)
    assert contexts['observed']['inputs']==contexts['null_repeat']['inputs']
    for slot in (0,1,2,4):assert contexts['observed']['inputs'][f'input{slot}.bin']==contexts['pilot']['inputs'][f'input{slot}.bin']
    assert len({v['applied_controls_sha256'] for v in contexts.values()})==1
    assert len({v['frame_controls_sha256'] for v in contexts.values()})==1
    v=row['variants'][VARIANT]
    with np.load(sp) as a:
        controls=np.loadtxt(folder/'observed/frame_controls.txt',ndmin=2)
        pilot,active,_=module.make_soft_temporal_spectral_pilot(a['observed'],controls,history=64)
        np.testing.assert_array_equal(pilot.astype(np.float16).astype(np.float32),a['pilot']);np.testing.assert_array_equal(active,a['active'])
        np.testing.assert_array_equal(a['soft_temporal'],a['baseline']+a['active'][:,None,None,None]*(a['pilot']-a['pilot_response']))
        np.testing.assert_array_equal(a[VARIANT],a['soft_temporal_dc_current'])
        value=a[VARIANT];assert np.isfinite(value).all() and value.min()>=0 and value.max()<=65504
        windows={}
        for window,selected in (('full',slice(None)),('mature',slice(-16,None))):
            actual=score(value[selected],a['clean_reference'][selected],None)
            for key in ('rmse','residual_temporal_std','broad_tone_rms'):
                np.testing.assert_allclose(actual[key],v[window][key],rtol=1e-6,atol=1e-9)
            gain=[g for g in actual['contrast_gain'] if g is not None];phase=[p for p in actual['phase_error_radians'] if p is not None]
            windows[window]=dict(gate=v[window+'_gate'],rmse=actual['rmse'],residual_temporal_std=actual['residual_temporal_std'],
                baseline_temporal_std=row['baseline_'+window]['residual_temporal_std'],bias_rgb=actual['bias_rgb'],
                gain_min=min(gain) if gain else None,gain_mean=float(np.mean(gain)) if gain else None,gain_max=max(gain) if gain else None,
                absolute_gain_within_5_percent_every_frame=all(.95<=g<=1.05 for g in gain) if gain else None,
                phase_max=max(phase) if phase else None)
        transition={str(i):dict(candidate_frame_rmse=v['full']['frame_rmse'][i],baseline_frame_rmse=row['baseline_full']['frame_rmse'][i],
            gain=v['full']['contrast_gain'][i],phase=v['full']['phase_error_radians'][i]) for i in (0,1,30,31,32,33,34,63)}
        native_null_stored='null_repeat' in a.files
        assert native_null_stored and row['null_repeat_saved']
        null_difference=a['null_repeat'].astype(np.float64)-a['baseline'].astype(np.float64)
        np.testing.assert_allclose(np.sqrt(np.mean(null_difference**2)),row['null_rms'],rtol=1e-5,atol=1e-9)
        active_frames=int(a['active'].sum())
    assert digest(sp)==before
    audit['rows'].append(dict(scene=scene,sequences_sha256=before,native_contexts=contexts,null_rms=row['null_rms'],
        source_null_input_and_applied_controls_equal=True,
        source_null_native_output_hashes_equal=contexts['observed']['output_sha256']==contexts['null_repeat']['output_sha256'],
        source_only_pilot_reproduced_exactly=True,active_frames=active_frames,activity=v['activity'],
        negative_fraction=v['negative_fraction'],fallback_pixel_fraction=v['baseline_fallback_pixel_fraction'],
        contour_gate=v['contour']['gate'] if v['contour'] else None,full=windows['full'],mature=windows['mature'],transition_frames=transition))
assert audit['native_contexts']==39 and audit['dispatches']==2496
audit['counts']=dict(total_scenes=13,full_nonregression=sum(x['full']['gate']['nonregression'] for x in audit['rows']),
    mature_nonregression=sum(x['mature']['gate']['nonregression'] for x in audit['rows']),
    full_effective=sum(x['full']['gate']['effective_success'] for x in audit['rows']),
    mature_effective=sum(x['mature']['gate']['effective_success'] for x in audit['rows']),
    full_and_mature_effective=sum(x['full']['gate']['effective_success'] and x['mature']['gate']['effective_success'] for x in audit['rows']))
assert digest(rp)==original_sha
audit['source_report_unchanged']=True;audit['status']='completed_independent_audit_not_solution'
audit['cross_run_comparison']=cross_run_comparison(r)
output=Path(__file__).with_name('audit.json')
if output.exists():raise ValueError('Preserve prior audit')
output.write_text(json.dumps(audit,indent=2,allow_nan=False)+'\n')
print(json.dumps(audit['counts']))
for row in audit['rows']:
    print(row['scene'],row['full']['gate']['failures'],row['mature']['gate']['failures'],
        row['full']['gain_min'],row['mature']['gain_min'],row['full']['phase_max'])
