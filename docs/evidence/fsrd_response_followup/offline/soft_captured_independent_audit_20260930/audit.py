"""Read-only captured96/native contracts and exact-water metrics; no GPU."""
from pathlib import Path
import hashlib, importlib.util, json, re, sys
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests';sys.path.insert(0,str(TESTS))
STUDY=ROOT/'tools_tmp/response_soft_temporal_long_captured_alpha_fresh'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
report_path=STUDY/'results.json';before=sha(report_path);r=json.loads(report_path.read_text())
assert r['status']=='completed_research_not_solution' and (r['frames'],r['history'],r['seed'])==(96,64,932061)
assert r['size']==[256,256] and r['split_strength']==1 and r['noise_distribution']=='uniform'
snapshot=STUDY/'source_snapshot'
assert all(sha(snapshot/k)==v for k,v in r['source_sha256'].items())
assert sha(STUDY/'fsrd_rr_runner.exe')==r['runner_sha256']
assert sha(ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll')==r['native_provider_sha256']
def load(name):
    spec=importlib.util.spec_from_file_location('captured_audit_'+name,snapshot/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
score=load('probe_fsrd_statistical_resolve').score
pilot_module=load('fsrd_response_soft_pilot')
source=r['captured_source'];metadata=Path(source['metadata_path']);assert sha(metadata)==source['metadata_sha256']
original=json.loads(metadata.read_text());assert original['complete'] and original['gpu_completion_verified']
assert source['source_backend']=='JointFieldV1' and not source['true_game_history'] and source['synthetic_independent_radiance']
assert sha(STUDY/'captured_source.npz')==source['npz_sha256']
with np.load(STUDY/'captured_source.npz') as captured:
    for name,digest in source['source_payload_sha256'].items():
        image=next(x for x in original['images'] if x['name']==name)
        payload=(metadata.parent/image['file']).read_bytes()
        assert hashlib.sha256(payload).hexdigest()==digest==image['sha256']
        expected=np.frombuffer(payload,'<f4').reshape(256,256,4)
        np.testing.assert_array_equal(expected,captured[name])
    mask=np.zeros((256,256),bool);mask[25:85,5:85]=True
    np.testing.assert_array_equal(mask,captured['mask']);assert hashlib.sha256(mask.tobytes()).hexdigest()==source['mask_sha256']
audit=dict(schema='soft-long-captured-independent-audit-v1',study=str(STUDY),report_sha256=before,
    analysis_sha256=sha(__file__),quality_accepted=False,frames=96,history=64,seed=932061,
    captured_source=source,original_five_payloads_and_derived_mask_reauthenticated=True,
    snapshot_hashes_valid=True,native_contexts=0,dispatches=0,rows=[],limitations=[
        'Historical JointFieldV1 geometry/guides with fresh synthetic radiance; not fresh alpha game input or actual game history.',
        'Successful native helper deleted uploaded and raw lobe payloads: manifest hashes attest inputs; input bytes cannot be retroactively rehashed.',
        'Score error/contrast uses exact water [y25:85,x5:85]; dominant-frequency phase uses real 90x70 halo [y20:90,x0:90].',
        'Relative gate pass does not guarantee lower mature temporal noise or absolute unit contrast.',
        'Shared source/guide bias and broader dynamic/history assumptions are unresolved.'])

def compact(m):
    gains=[x for x in m['contrast_gain'] if x is not None];phases=[x for x in m['phase_error_radians'] if x is not None]
    return {**{k:m[k] for k in ('rmse','bias_rgb','broad_tone_rms','residual_temporal_std','finite')},
        'gain_min':min(gains) if gains else None,'gain_mean':float(np.mean(gains)) if gains else None,
        'gain_max':max(gains) if gains else None,'phase_max':max(phases) if phases else None,
        'absolute_gain_within_5_percent_every_frame':all(.95<=g<=1.05 for g in gains) if gains else None}

for row in r['rows']:
    scene=row['scene'];folder=Path(row['evidence_directory']);sp=folder/'sequences.npz';sp_before=sha(sp);contexts={}
    for context in ('observed','null_repeat','blind_pilot'):
        p=folder/context;m=json.loads((p/'amd_context_identity.json').read_text());inp=json.loads((p/'amd_input_identity.json').read_text())
        assert m['inputs']==inp and set(inp)=={f'input{i}.bin' for i in range(7)}
        assert m['dimensions']==[256,256] and m['frames']==96 and m['signals']==[2,32] and m['reset_every']==0 and m['tuning']==1
        assert m['dll_sha256']==r['native_provider_sha256'] and m['runner_sha256']==r['runner_sha256']
        assert m['tuning_values']==[.1,.5,.5,40000.,40.,.5]
        controls=np.loadtxt(p/'frame_controls.txt',ndmin=2);binary=p/'dispatch_controls.bin'
        assert sha(binary)==m['applied_dispatch_sha256'];data=binary.read_bytes();assert len(data)==96*184
        u=np.frombuffer(data,'<u4').reshape(96,46);f=np.frombuffer(data,'<f4').reshape(96,46)
        np.testing.assert_array_equal(u[:,0],np.arange(96));np.testing.assert_array_equal(u[:,1],2+np.where((controls[:,0]!=0)|(np.arange(96)==0),1,0))
        np.testing.assert_array_equal(u[:,2:4],np.tile([256,256],(96,1)))
        np.testing.assert_array_equal(f[:,4:7],np.ones((96,3)));assert not f[:,7:10].any()
        np.testing.assert_array_equal(f[:,10:12],controls[:,1:].astype(np.float32))
        camera=np.loadtxt(p/'camera.txt').astype(np.float32)
        np.testing.assert_array_equal(f[:,12:14],np.tile(camera[34:36],(96,1)))
        np.testing.assert_array_equal(f[:,14:30],np.tile(camera[:16],(96,1)))
        np.testing.assert_array_equal(f[:,30:46],np.tile(camera[16:32],(96,1)))
        process=json.loads((p/'runner_process.json').read_text());log=(p/'runner.log').read_text()
        assert process['returncode']==0 and process['runner_sha256']==r['runner_sha256'] and process['log_sha256']==sha(p/'runner.log')
        assert 'debug_layer=1' in log and 'custom_camera=1' in log
        assert all(re.search(r'\b'+k+r'=0\b',log) for k in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'))
        assert re.search(r'\bdispatches=96\b',log)
        contexts[context]=dict(inputs=inp,manifest_sha256=sha(p/'amd_context_identity.json'),frame_controls_sha256=sha(p/'frame_controls.txt'),
            camera_sha256=sha(p/'camera.txt'),applied_controls_sha256=sha(binary),log_sha256=sha(p/'runner.log'),
            process_sha256=sha(p/'runner_process.json'),output_sha256=m['output_sha256'])
        audit['native_contexts']+=1;audit['dispatches']+=96
    assert contexts['observed']['inputs']==contexts['null_repeat']['inputs']
    for i in (0,1,2,4):assert contexts['observed']['inputs'][f'input{i}.bin']==contexts['blind_pilot']['inputs'][f'input{i}.bin']
    for key in ('frame_controls_sha256','camera_sha256','applied_controls_sha256'):assert len({x[key] for x in contexts.values()})==1
    with np.load(sp) as a:
        raw=a['observed'];pilot,active,_=pilot_module.make_soft_temporal_spectral_pilot(raw,controls,history=64)
        np.testing.assert_array_equal(pilot.astype(np.float16).astype(np.float32),a['pilot']);np.testing.assert_array_equal(active,a['active'])
        np.testing.assert_array_equal(a['soft_temporal'],a['baseline']+active[:,None,None,None]*(a['pilot']-a['pilot_response']))
        null=a['null_repeat']-a['baseline'];assert row['null_repeat_saved']
        np.testing.assert_allclose(np.sqrt(np.mean(null**2)),row['null_rms'],rtol=1e-6,atol=1e-9)
        region=row['recorded_roi'];assert region['measured_rectangle_xywh']==[5,25,80,60] and region['fft_phase_halo_xywh']==[0,20,90,70]
        variants={}
        for name in row['variants']:
            value=a[name];windows={}
            for label,sl in (('full',slice(None)),('mature',slice(-16,None))):
                truth=a['clean_reference'][sl];global_score=score(value[sl],truth,None)
                roi_score=score(value[sl,20:90,0:90],truth[:,20:90,0:90],None)
                for actual,stored in ((global_score,row['variants'][name][label]),(roi_score,region['variants'][name][label])):
                    for key in ('rmse','bias_rgb','broad_tone_rms','residual_temporal_std','contrast_gain','phase_error_radians'):
                        np.testing.assert_allclose(actual[key],stored[key],rtol=1e-6,atol=1e-8)
                roi_null=float(np.sqrt(np.mean(null[sl,25:85,5:85]**2)))
                np.testing.assert_allclose(roi_null,region['null_rms_'+label],rtol=1e-6,atol=1e-9)
                windows[label]=dict(global_metric=compact(global_score),global_gate=row['variants'][name][label+'_gate'],
                    exact_water_metric=compact(roi_score),exact_water_gate=region['variants'][name][label+'_gate'],
                    baseline_water_temporal_std=region['baseline_'+label]['residual_temporal_std'],roi_null_rms=roi_null)
            valid=np.isfinite(value).all(-1)&(value>=0).all(-1)&(value<=65504).all(-1)
            variants[name]=dict(windows=windows,invalid_pixel_fraction=float(np.mean(~valid)),
                fallback_pixel_fraction=row['variants'][name]['baseline_fallback_pixel_fraction'],activity=row['variants'][name]['activity'])
        indices=np.argwhere(null!=0);first=list(map(int,indices[0])) if len(indices) else None
        peak=tuple(np.unravel_index(np.argmax(np.abs(null)),null.shape))
        null_audit=dict(full_rms=row['null_rms'],first_nonzero_frame_y_x_rgb=first,
            maximum_frame_y_x_rgb=list(map(int,peak)),maximum_signed_delta=float(null[peak]),
            full_frame_rms=np.sqrt(np.mean(null.astype(np.float64)**2,axis=(1,2,3))).tolist())
    assert sha(sp)==sp_before
    audit['rows'].append(dict(scene=scene,sequences_sha256=sp_before,contexts=contexts,active_frames=int(active.sum()),
        source_only_pilot_exact_FP16=True,null_audit=null_audit,variants=variants))
assert audit['native_contexts']==r['amd_completed_sequences']==3*len(r['rows'])
assert audit['dispatches']==96*audit['native_contexts'] and sha(report_path)==before
audit['all_original_evidence_unchanged']=True
output=Path(__file__).with_name('audit.json');assert not output.exists()
output.write_text(json.dumps(audit,indent=2,allow_nan=False)+'\n')
print('audit_sha256',sha(output))
for row in audit['rows']:
    print(row['scene'],row['null_audit']['full_rms'],row['variants']['soft_temporal_dc_current_safe'])
