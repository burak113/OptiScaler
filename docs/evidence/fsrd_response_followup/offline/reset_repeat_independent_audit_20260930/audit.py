"""Independent retained-FP16 audit of four pinned native contexts; no GPU."""
import hashlib,json,re
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
STUDY=ROOT/'tools_tmp/reset_context_repeat_20260930/evidence'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
rp=STUDY/'results.json';before=sha(rp);r=json.loads(rp.read_text())
assert r['status']=='completed_diagnostic_not_solution' and r['contexts']==4 and r['dispatches']==256
assert sha(STUDY.parent/'analyze.py')==r['script_sha256']
assert sha(STUDY.parent/'preregistration.md')==r['preregistration_sha256']
assert sha(Path(r['runner_path']))==r['runner_sha256']
assert sha(ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll')==r['native_provider_sha256']
ref=Path(r['input_authentication']['native_context']);assert sha(ref)==r['input_authentication']['manifest_sha256']
reference=json.loads(ref.read_text());assert reference['inputs']==r['input_authentication']['input_sha256']
assert sha(ref.parent/'frame_controls.txt')==r['input_authentication']['reset_jitter_sha256']

def metrics(a,b,frames=None):
    delta=np.asarray(b,dtype=np.float64)-np.asarray(a,dtype=np.float64)
    indices=np.argwhere(delta!=0);peak=tuple(np.unravel_index(np.argmax(np.abs(delta)),delta.shape))
    first=tuple(indices[0]) if len(indices) else None
    first_coordinates=list(map(int,first)) if first else None
    peak_coordinates=list(map(int,peak))
    if frames is not None:
        if first:first_coordinates[0]=int(frames[first[0]])
        peak_coordinates[0]=int(frames[peak[0]])
    return dict(exact_equal=bool(np.array_equal(a,b)),rms=float(np.sqrt(np.mean(delta**2))),
        differing_values=int(np.count_nonzero(delta)),first_frame_y_x_channel=first_coordinates,
        first_signed_delta=float(delta[first]) if first else None,
        maximum_frame_y_x_channel=peak_coordinates,maximum_signed_delta=float(delta[peak]),
        maximum_old_value=float(a[peak]),maximum_new_value=float(b[peak]),
        frame_rms=np.sqrt(np.mean(delta**2,axis=tuple(range(1,delta.ndim)))).tolist(),
        bias_by_channel=delta.mean(tuple(range(delta.ndim-1))).tolist())


def verify_derivation():
    path=STUDY.parent/'source_derivation.json';derivation=json.loads(path.read_text())
    assert sha(Path(derivation['source']))==derivation['source_sha256']
    assert sha(STUDY.parent/'analyze.py')==derivation['generated_sha256']
    header=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h'
    assert re.search(r'FFX_DENOISER_DISPATCH_RESET\s*=\s*\(1\s*<<\s*0\)',header.read_text())
    return dict(source_derivation_sha256=sha(path),derivation=derivation,local_sdk_RESET_mask_verified=True,local_header_sha256=sha(header))

def compare_old_new(report):
    old=ROOT/'tools_tmp/controlled_context_repeat_20260930/evidence'
    old_rp=old/'results.json';old_sha=sha(old_rp);original=json.loads(old_rp.read_text())
    assert original['runner_sha256']==report['runner_sha256'] and original['native_provider_sha256']==report['native_provider_sha256']
    records=[];windows={}
    for label,study in (('original',old),('RESET_frame32',STUDY)):
        data=[]
        for run in range(4):
            with np.load(study/f'repeat_{run}/native_outputs.npz') as a:
                data.append({k:a[k].copy() for k in a.files})
        pairs=[]
        for i in range(4):
            for j in range(i+1,4):
                a,b=data[i],data[j]
                pair=dict(first=i,second=j,windows={})
                for window,sl,select in (('before32',slice(None,32),slice(None,3)),('from32',slice(32,None),slice(3,None))):
                    delta=np.stack([b[k][sl,:,:,:3].astype(np.float64)-a[k][sl,:,:,:3] for k in ('diffuse','specular')],axis=-1)
                    c=b['selected_composed_rgb'][select].astype(np.float64)-a['selected_composed_rgb'][select]
                    pair['windows'][window]=dict(native_RGB_both_lobes_rms=float(np.sqrt(np.mean(delta**2))),
                        selected_composed_rms=float(np.sqrt(np.mean(c**2))))
                pairs.append(pair)
        windows[label]=pairs
    assert sha(old_rp)==old_sha
    return dict(original_report_sha256=old_sha,studies=windows,
        limitation='Descriptive within-four-context pair differences only. These independent context samples are neither paired random trials nor a confidence bound; RESET changes operator history, not quality acceptance.')

audit=dict(schema='same-binary-transition-reset-independent-audit-v1',report_sha256=before,analysis_sha256=sha(__file__),
    quality_accepted=False,game_run=False,native_contexts=4,dispatches=256,runner_sha256=r['runner_sha256'],
    provider_sha256=r['native_provider_sha256'],selected_composed_frames=r['selected_frames'],runs=[],pairs=[],
    limitations=['Four contexts on one fixture are not a confidence interval or universal SDK property.',
        'Same binary/input hashes and controlled frame32 RESET isolate history sensitivity; no concrete caller error was found by local code review.',
        'Full native lobes are retained FP16. Composed RGB is retained at seven selected frames only.',
        'No resource clearing/initialization change, production implementation, or game-quality inference.'])
arrays=[]
for record in r['runs']:
    i=record['run'];p=STUDY/f'repeat_{i}';payload=Path(record['retained_payload_path'])
    assert sha(payload)==record['payload_sha256'] and sha(p/'amd_context_identity.json')==record['manifest_sha256']
    m=json.loads((p/'amd_context_identity.json').read_text());inp=json.loads((p/'amd_input_identity.json').read_text())
    assert m['inputs']==inp==reference['inputs'] and len(inp)==7
    for key in ('dll_sha256','runner_sha256','dimensions','frames','signals','reset_every','tuning','passthrough','tuning_values'):
        assert m[key]==reference[key]
    binary=p/'dispatch_controls.bin';assert sha(binary)==m['applied_dispatch_sha256']
    controls=np.loadtxt(p/'frame_controls.txt',ndmin=2);data=binary.read_bytes();assert len(data)==64*184
    u=np.frombuffer(data,'<u4').reshape(64,46);f=np.frombuffer(data,'<f4').reshape(64,46)
    np.testing.assert_array_equal(u[:,0],np.arange(64))
    np.testing.assert_array_equal(u[:,1],2+np.where((controls[:,0]!=0)|(np.arange(64)==0),1,0))
    np.testing.assert_array_equal(u[:,2:4],np.tile([128,80],(64,1)))
    np.testing.assert_array_equal(f[:,10:12],controls[:,1:].astype(np.float32))
    expected_controls=np.loadtxt(ref.parent/'frame_controls.txt',ndmin=2)
    expected_controls[32,0]=1
    np.testing.assert_array_equal(controls,expected_controls)
    original_controls=(ref.parent/'dispatch_controls.bin').read_bytes()
    expected_bytes=bytearray(original_controls)
    import struct
    original_flag=struct.unpack_from('<I',expected_bytes,32*184+4)[0]
    struct.pack_into('<I',expected_bytes,32*184+4,original_flag|1)
    assert data==bytes(expected_bytes)
    assert [k for k,(a,b) in enumerate(zip(data,original_controls)) if a!=b]==[32*184+4]
    process=json.loads((p/'runner_process.json').read_text());log=(p/'runner.log').read_text()
    assert process['returncode']==0 and process['runner_sha256']==r['runner_sha256'] and process['log_sha256']==sha(p/'runner.log')
    assert 'debug_layer=1' in log and all(re.search(r'\b'+k+r'=0\b',log) for k in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'))
    assert re.search(r'\bdispatches=64\b',log)
    with np.load(payload) as a:
        values={k:a[k].copy() for k in a.files}
        for lobe in ('diffuse','specular'):
            value=values[lobe];assert value.shape==(64,80,128,4) and value.dtype==np.float16
            assert hashlib.sha256(value.astype('<f2').tobytes()).hexdigest()==m['output_sha256'][lobe+'.bin']
            assert np.isfinite(value).all()
        assert values['selected_composed_rgb'].shape==(7,80,128,3)
    arrays.append(values)
    audit['runs'].append(dict(run=i,payload_sha256=record['payload_sha256'],manifest_sha256=record['manifest_sha256'],
        seven_original_inputs_equal=True,applied_controls_only_RESET_bit_at_frame32=True,FP16_lobe_byte_hashes_valid=True,
        log_sha256=sha(p/'runner.log'),process_sha256=sha(p/'runner_process.json'),
        alpha_ranges={lobe:[float(values[lobe][...,3].min()),float(values[lobe][...,3].max())] for lobe in ('diffuse','specular')}))
for stored in r['pairwise']:
    i,j=stored['first'],stored['second'];a,b=arrays[i],arrays[j]
    lobes={}
    for lobe in ('diffuse','specular'):
        lobes[lobe]=dict(RGBA=metrics(a[lobe],b[lobe]),RGB=metrics(a[lobe][...,:3],b[lobe][...,:3]),alpha=metrics(a[lobe][...,3:4],b[lobe][...,3:4]))
    both=np.stack((a['diffuse'],a['specular']),axis=-1).astype(np.float64)
    other=np.stack((b['diffuse'],b['specular']),axis=-1).astype(np.float64)
    delta=other-both
    np.testing.assert_allclose(np.sqrt(np.mean(delta**2)),stored['native_lobes']['rms'],rtol=1e-12,atol=1e-15)
    composed=metrics(a['selected_composed_rgb'],b['selected_composed_rgb'],r['selected_frames'])
    np.testing.assert_allclose(composed['rms'],stored['selected_composed']['rms'],rtol=1e-12,atol=1e-15)
    audit['pairs'].append(dict(first=i,second=j,native_RGBA_both_lobes_rms=stored['native_lobes']['rms'],
        native_RGB_both_lobes_rms=float(np.sqrt(np.mean(delta[:,:,:,:3,:]**2))),lobes=lobes,selected_composed=composed,
        frame32_33_34_RGB_lobe_rms={lobe:[lobes[lobe]['RGB']['frame_rms'][k] for k in (32,33,34)] for lobe in lobes}))
assert sha(rp)==before
for record in r['runs']:assert sha(Path(record['retained_payload_path']))==record['payload_sha256']
audit['all_original_evidence_unchanged']=True
audit['control_change']=dict(frame=32,flag_mask=1,dispatch_stride=184,only_different_byte_offset=32*184+4,original_flag=2,changed_flag=3)
audit['control_source_derivation']=verify_derivation()
audit['descriptive_before_after_variability']=compare_old_new(r)
audit['all_pairs_native_RGB_nonzero']=all(p['native_RGB_both_lobes_rms']>0 for p in audit['pairs'])
audit['all_alpha_exact_equal_zero']=all(p['lobes'][lobe]['alpha']['exact_equal'] for p in audit['pairs'] for lobe in ('diffuse','specular')) and all(v==0 for row in audit['runs'] for value in row['alpha_ranges'].values() for v in value)
out=Path(__file__).with_name('audit.json');assert not out.exists();out.write_text(json.dumps(audit,indent=2)+'\n')
print('audit_sha256',sha(out))
for p in audit['pairs']:
 print(p['first'],p['second'],'nativeRGB',p['native_RGB_both_lobes_rms'],'composed',p['selected_composed']['rms'],
       'RGB_first',{k:p['lobes'][k]['RGB']['first_frame_y_x_channel'] for k in p['lobes']})
