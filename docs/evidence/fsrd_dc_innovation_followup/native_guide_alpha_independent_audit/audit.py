"""Read-only guide-alpha retained native byte/control/pair trajectory audit."""
from pathlib import Path
import hashlib,json,re,itertools,difflib
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];TMP=ROOT/'tools_tmp'
BASE=TMP/'native_guide_alpha_ablation_20260930';WAVE=TMP/'native_guide_alpha_wave_continuation_20260930';REPEAT=TMP/'native_guide_alpha_wave_identical_repeat_20260930'
EXE=Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce/response_soft_temporal_long_alpha_fresh/fsrd_rr_runner.exe')
DLL=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'
BH='3427689a4764380f885545c353250277e4d71944d3310c8a17b3cbba0f3c21d2';DH='48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
FORMATS=[41,10,24,28,28,10,10];SIZES={41:4,10:8,24:4,28:4}
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def tokens(s):return [json.loads(x) if x.startswith('"') else x for x in re.findall(r'"(?:\\.|[^"\\])*"|[^\s]+',s)]
def job(folder):
    rows=[tokens(s) for s in (folder/'job.txt').read_text().splitlines()]
    assert len(rows)==9 and list(map(int,rows[0][:8]))==[128,80,64,2,32,0,1,0]
    assert Path(rows[0][8])==DLL and sha(Path(rows[0][8]))==DH
    uploads=[]
    for i,line in enumerate(rows[1:8]):
        assert Path(line[0])==folder/f'input{i}.bin'
        fmt,n=map(int,line[1:]);assert fmt==FORMATS[i] and n in (1,64)
        assert (folder/f'input{i}.bin').stat().st_size==128*80*SIZES[fmt]*n;uploads.append(n)
    assert [Path(p) for p in rows[-1]]==[folder/'diffuse.bin',folder/'specular.bin']
    return uploads
def alpha_full(folder):
    n=job(folder)[3];a=np.fromfile(folder/'input3.bin','u1').reshape(n,80,128,4)
    return np.broadcast_to(a,(64,80,128,4))[...,3]
def controls(folder,original):
    raw=(folder/'dispatch_controls.bin').read_bytes();assert raw==(original/'dispatch_controls.bin').read_bytes() and len(raw)==64*184
    assert (folder/'frame_controls.txt').read_bytes()==(original/'frame_controls.txt').read_bytes()
    assert not (folder/'camera.txt').exists() and not (original/'camera.txt').exists()
    intended=np.loadtxt(folder/'frame_controls.txt').astype('f4');assert intended.shape==(64,3)
    records=np.frombuffer(raw,dtype=np.dtype([('header','<u4',(4,)),('values','<f4',(42,))]))
    for frame,r in enumerate(records):
        np.testing.assert_array_equal(r['header'],[frame,2|int(frame==0 or intended[frame,0]),128,80])
        np.testing.assert_array_equal(r['values'][6:8],intended[frame,1:])
    return {'sha256':sha(folder/'dispatch_controls.bin'),'flags':records['header'][:,1].tolist(),'intended_reset_frames':np.flatnonzero(intended[:,0]).tolist(),'all184_bytes_equal_original':True}
def verify_context(folder,original,variant,source_observed,claimed=None):
    uploads=job(folder);assert uploads==job(original)
    rawold=(original/'input3.bin').read_bytes();old=np.frombuffer(rawold,'u1').reshape(uploads[3],80,128,4)
    expected=old.copy()
    if variant=='zero':expected[...,3]=0
    elif variant=='one':expected[...,3]=255
    elif variant=='source_alpha':
        a=alpha_full(source_observed)
        if uploads[3]==1:assert np.array_equal(a,np.broadcast_to(a[:1],a.shape));a=a[:1]
        expected[...,3]=a
    assert (folder/'input3.bin').read_bytes()==expected.tobytes()
    np.testing.assert_array_equal(expected[...,:3],old[...,:3])
    for i in (0,1,2,4,5,6):assert (folder/f'input{i}.bin').read_bytes()==(original/f'input{i}.bin').read_bytes()
    identity=read(folder/'amd_context_identity.json');assert identity['runner_sha256']==BH and identity['dll_sha256']==DH
    ih={f'input{i}.bin':sha(folder/f'input{i}.bin') for i in range(7)};assert ih==identity['inputs']==read(folder/'amd_input_identity.json')
    if claimed is not None:assert identity==claimed
    outputs=identity.get('outputs',identity.get('output_sha256'));assert outputs is not None
    for name,digest in outputs.items():assert sha(folder/name)==digest and (folder/name).stat().st_size==64*128*80*8
    ctl=controls(folder,original);assert identity['applied_dispatch_sha256']==ctl['sha256']
    log=(folder/'runner.log').read_text();assert 'debug_layer=1' in log and 'dispatches=64' in log
    assert all(re.search(r'\b'+f+r'=0\b',log) for f in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'))
    guard=None
    if claimed is not None:
        assert log==(folder/'stdout.log').read_text(errors='replace')+(folder/'stderr.log').read_text(errors='replace')
        g=read(folder/'resource_guard.json');assert g['status']=='completed' and g['returncode']==0 and not g['terminated_owned_child']
        assert g['minimum_available_memory_bytes']==2**30 and g['maximum_working_set_bytes']==2**31 and g['timeout_seconds']==240
        assert [Path(p) for p in g['args']]==[EXE,folder/'job.txt'];guard=sha(folder/'resource_guard.json')
    return dict(inputs=ih,outputs=outputs,uploads=uploads,controls=ctl,guard_sha256=guard,runner_log_sha256=sha(folder/'runner.log'),
                input3_alpha_range=[int(expected[...,3].min()),int(expected[...,3].max())],input3_alpha_changed_fraction_vs_original=float(np.mean(expected[...,3]!=old[...,3])))
def compare(a,b):
    aa=np.fromfile(a,'<f2').reshape(64,80,128,4);bb=np.fromfile(b,'<f2').reshape(64,80,128,4)
    out={'bytes_exact':a.read_bytes()==b.read_bytes(),'all_finite':bool(np.isfinite(aa).all() and np.isfinite(bb).all())}
    for idx,label in [(slice(0,3),'RGB'),(slice(3,4),'alpha'),(slice(None),'RGBA')]:
        delta=aa[...,idx].astype(float)-bb[...,idx].astype(float)
        out[label]={'rms':float(np.sqrt(np.mean(delta**2))),'max_abs':float(abs(delta).max()),'changed_fraction':float(np.mean(delta!=0)),'per_frame_rms':np.sqrt(np.mean(delta**2,axis=(1,2,3))).tolist()}
    return out
def trajectory(left,right):
    A=np.concatenate([np.fromfile(left/n,'<f2').reshape(64,80,128,4) for n in ('diffuse.bin','specular.bin')],axis=-1)
    B=np.concatenate([np.fromfile(right/n,'<f2').reshape(64,80,128,4) for n in ('diffuse.bin','specular.bin')],axis=-1)
    delta=A.astype(float)-B.astype(float);perframe=np.sqrt(np.mean(delta**2,axis=(1,2,3)));changed=np.any(delta!=0,axis=(1,2,3));loc=np.unravel_index(np.argmax(abs(delta)),delta.shape)
    rgb=delta[...,[0,1,2,4,5,6]];alpha=delta[...,[3,7]]
    return dict(raw8_RGBA_RMS=float(np.sqrt(np.mean(delta**2))),raw6_RGB_RMS=float(np.sqrt(np.mean(rgb**2))),raw2_alpha_RMS=float(np.sqrt(np.mean(alpha**2))),
                first_difference_frame=int(np.flatnonzero(changed)[0]) if changed.any() else None,changed_frames=np.flatnonzero(changed).tolist(),
                raw8_per_frame_RMS=perframe.tolist(),maximum_frame=int(np.argmax(perframe)) if changed.any() else None,
                maximum_abs_location_frame_y_x_lobeRGBA=list(map(int,loc)) if changed.any() else None,maximum_abs=float(abs(delta).max()),
                input_caller_flags_not_a_model_event_inference=True)
def main():
    if (HERE/'audit.json').exists():raise ValueError('Preserve audit')
    assert sha(EXE)==BH and sha(DLL)==DH
    folders=[BASE,WAVE,REPEAT];pins={};registrations=[]
    for base in folders:
        F=read(base/'pre_native_freeze.json');R=read(base/'evidence/results.json')
        assert R['pre_native_freeze_sha256']==sha(base/'pre_native_freeze.json')
        for p,s in F['sources'].items():assert sha(p)==s;pins[p]=s
        for p in (base/'evidence/source_snapshot').iterdir():
            if p.name!='run.log':assert p.read_bytes()==(base/p.name).read_bytes()
        for p in base.rglob('*'):
            if p.is_file():pins[str(p)]=sha(p)
        registrations.append(dict(path=str(base),report_sha256=sha(base/'evidence/results.json'),status=R['status'],contexts=R['completed_native_contexts'],RR=R['native_RR_calls']))
    assert [(r['contexts'],r['RR']) for r in registrations]==[(4,256),(4,256),(3,192)]
    assert registrations[0]['status']=='failed_preserved' and all(r['status']=='completed_native_diagnostic_not_solution' for r in registrations[1:])
    original_material=TMP/'native_continuous_harmonic_fresh_retry_20260930/evidence/material/harmonic_pilot'
    original_wave=TMP/'native_continuous_harmonic_remaining_20260930/evidence/wave/harmonic_pilot'
    M=read(BASE/'evidence/results.json');W=read(WAVE/'evidence/results.json');R=read(REPEAT/'evidence/results.json')
    assert len(M['rows'])==len(W['rows'])==len(R['rows'])==1 and M['rows'][0]['case']=='material'
    assert 'AssertionError' in M['error'] and not list((BASE/'evidence/wave').iterdir())
    assert job(original_material)[3]==64 and job(original_wave)[3]==1
    contexts={};material={};wave={'old_original':original_wave}
    source_observed_material=original_material.parent/'observed';source_observed_wave=original_wave.parent/'observed'
    for group,base,orig,obs in [('material',BASE,original_material,source_observed_material),('wave',WAVE,original_wave,source_observed_wave),('wave',REPEAT,original_wave,source_observed_wave)]:
        rr=read(base/'evidence/results.json')['rows'][0]
        expected_source_difference=float(np.mean(alpha_full(obs)!=alpha_full(orig)))
        assert expected_source_difference==rr['source_alpha_difference_fraction']
        for name,claim in rr['contexts'].items():
            p=base/'evidence'/group/name;contexts[group+'/'+name]=verify_context(p,orig,name,obs,claim)
            (material if group=='material' else wave)[name]=p
        for key,pair in rr['comparisons'].items():
            a,b=key.split('__')
            for n in ('diffuse.bin','specular.bin'):assert compare(base/'evidence'/group/a/n,base/'evidence'/group/b/n)==pair[n]
        first='repeat0' if base==REPEAT else 'original'
        for n in ('diffuse.bin','specular.bin'):assert compare(base/'evidence'/group/first/n,orig/n)==rr['fresh_original_vs_previous'][n]
    assert len(contexts)==11 and len(wave)==8 and len(material)==4
    # Authenticate old reference contexts too; no new dispatches counted for them.
    contexts['wave/old_original']=verify_context(original_wave,original_wave,'original',source_observed_wave)
    contexts['material/old_original']=verify_context(original_material,original_material,'original',source_observed_material)
    material_pairs=[]
    for a,b in itertools.combinations(material,2):
        assert all(compare(material[a]/n,material[b]/n)['bytes_exact'] for n in ('diffuse.bin','specular.bin'))
        material_pairs.append(dict(left=a,right=b,trajectory=trajectory(material[a],material[b])))
    assert all(compare(p/n,original_material/n)['bytes_exact'] for p in material.values() for n in ('diffuse.bin','specular.bin'))
    CROSS=REPEAT/'cross_comparison.json';assert sha(CROSS)=='f45dd2e52b3452f40a0f8a02d443136df3e7d9d33b81c29163a3b8161d62ec6d';cross=read(CROSS)
    pairs=[]
    for a,b in itertools.combinations(wave,2):
        x,y=contexts['wave/'+a],contexts['wave/'+b];p=next(v for v in cross['pairs'] if v['left']==a and v['right']==b)
        equalinput=x['inputs']==y['inputs'];equalcontrols=x['controls']['sha256']==y['controls']['sha256']
        assert equalinput==p['all7_inputs_exact'] and equalcontrols==p['controls_exact']
        outputs={n:compare(wave[a]/n,wave[b]/n) for n in ('diffuse.bin','specular.bin')};assert outputs==p['outputs']
        pairs.append(dict(left=a,right=b,all7_inputs_exact=equalinput,controls_exact=equalcontrols,outputs=outputs,trajectory=trajectory(wave[a],wave[b])))
    assert len(pairs)==28 and sum(p['all7_inputs_exact'] for p in pairs)==15
    nonexact=sum(p['all7_inputs_exact'] and not all(v['bytes_exact'] for v in p['outputs'].values()) for p in pairs);assert nonexact==9
    maximum=max(v['RGB']['rms'] for p in pairs if p['all7_inputs_exact'] for v in p['outputs'].values());assert maximum==read(REPEAT/'cross_comparison_compact.json')['maximum_identical_input_RGB_RMS']
    assert contexts['wave/original']['inputs']==contexts['wave/source_alpha']['inputs']==contexts['wave/old_original']['inputs']
    assert all(contexts['wave/'+n]['inputs']==contexts['wave/old_original']['inputs'] for n in ('repeat0','repeat1','repeat2'))
    scripts=[TMP/'prepare_guide_alpha_wave_continuation_20260930.py',TMP/'prepare_guide_alpha_wave_identical_repeat_20260930.py',TMP/'guide_alpha_wave_cross_comparison_20260930.py']
    # Derivation scope represented by exact driver diffs and original generator
    # hashes. No script execution or producer mutation by this audit.
    derivation={str(p):sha(p) for p in scripts}
    diffs={'continuation':''.join(difflib.unified_diff((BASE/'analyze.py').read_text().splitlines(True),(WAVE/'analyze.py').read_text().splitlines(True))),
           'identical_repeat':''.join(difflib.unified_diff((WAVE/'analyze.py').read_text().splitlines(True),(REPEAT/'analyze.py').read_text().splitlines(True)))}
    err=read(WAVE/'continuation_erratum.json');assert err['original_driver_sha256']==sha(BASE/'analyze.py') and err['preserved_original_result_sha256']==sha(BASE/'evidence/results.json')
    reg=read(REPEAT/'repeat_registration.json');assert reg['source_ablation_result_sha256']==sha(WAVE/'evidence/results.json') and reg['old_driver_sha256']==sha(WAVE/'analyze.py')
    assert all(sha(p)==s for p,s in pins.items())
    out=dict(status='completed_independent_native_diagnostic_not_solution',quality_accepted=False,GPU_used=False,new_native_contexts_audited=11,new_RR_calls_audited=704,
        runner_sha256=BH,provider_sha256=DH,registrations=registrations,contexts=contexts,material_pairs=material_pairs,material_fresh4_vs_old_all_raw_exact=True,
        wave_pairs=pairs,wave_identical_input_pairs=15,wave_nonexact_identical_input_pairs=nonexact,wave_maximum_identical_input_per_lobe_RGB_RMS=maximum,
        source_and_preparation_hashes=derivation,driver_diffs=diffs,continuation_erratum=err,repeat_registration=reg,source_freeze_before_and_after_all_equal=pins,
        qualifiers=['SDK albedo RGB and native signal ray-alpha/geometry remain exact; native albedo input3 diagnosticA is actually changed where specified.',
                    'Wave sourceAlpha and original all7inputs are identical but native outputs can differ. This does not identify an alpha effect.',
                    'Material4alpha arms and old rawoutput are exact in this fixture; not a universal opaque SDK alpha-consumer proof.',
                    'Raw per-lobe RGB3/alpha1/RGBA4 and combined rawRGB6/alpha2/RGBA8 metrics are separately recorded. No composed quality score, averaging, subtraction or native-response substitution.',
                    'Initial wave uploadcount64 assertion failed before launching wave; legitimate dedupcount1 retained by separate continuation. Material4completed counts remain.',
                    'Supplemental cross comparison first import failed before scores/results; corrected sys.path only. Root erratum retained separately; no native rerun caused by that script.',
                    'Flags native2 NON_GAMMA_ALBEDO plus1 RESET; all184byte controls identical originals. Converter depth flags are a separate namespace.',
                    'Context sample variation is diagnostic, not population confidence, a caller bug, native cause or game fix.'])
    out['audit_source_sha256']=sha(__file__);(HERE/'audit.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':out['status'],'contexts':11,'RR':704,'wave_pairs':28,'identical':15,'nonexact_identical':9,'maximum_per_lobe_RGB_RMS':maximum,'audit_sha256':sha(HERE/'audit.json')}))
if __name__=='__main__':main()
