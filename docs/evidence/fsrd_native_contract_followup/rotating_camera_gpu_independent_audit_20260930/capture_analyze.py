"""Read-only CPU audit of four retained actual GPU jobs, no GPU imports/calls."""
import ast,hashlib,json,re,struct
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
STUDY=ROOT/'tools_tmp/rotating_camera_gpu_capture_20260930/evidence'
CPU=ROOT/'tools_tmp/rotating_camera_conformance_20260930'
PRE=ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stats(a,b):
    d=np.asarray(a,float)-np.asarray(b,float)
    return dict(rms=float(np.sqrt(np.mean(d*d))),maximum_absolute=float(abs(d).max()),exact_equal=bool(np.array_equal(a,b)))
def tolerance(a):
    a=np.asarray(a,np.float16)
    return np.maximum(abs(np.nextafter(a,np.float16(np.inf)).astype(float)-a.astype(float)),abs(a.astype(float)-np.nextafter(a,np.float16(-np.inf)).astype(float)))+1e-5
def parse(line,npaths):
    decoder=json.JSONDecoder();paths=[]
    for i in range(npaths):
        line=line.lstrip();value,end=decoder.raw_decode(line);paths.append(Path(value));line=line[end:]
    return paths,list(map(int,line.split()))
def storage(array,fmt):
    a=np.asarray(array,np.float32)
    if a.ndim==2:a=np.repeat(a[...,None],4,axis=2)
    if a.shape[-1]<4:a=np.pad(a,((0,0),(0,0),(0,4-a.shape[-1])))
    if fmt==10:return a.astype('<f2').tobytes()
    if fmt==41:return a[...,0].astype('<f4').tobytes()
    raise ValueError(fmt)
def decode(path,fmt):
    if fmt==10:return np.frombuffer(path.read_bytes(),'<f2').reshape(80,128,4).astype(np.float32)
    if fmt==28:return np.frombuffer(path.read_bytes(),np.uint8).reshape(80,128,4).astype(np.float32)/255
    if fmt==24:
        u=np.frombuffer(path.read_bytes(),'<u4').reshape(80,128)
        return np.stack(((u&1023)/1023,((u>>10)&1023)/1023,((u>>20)&1023)/1023,((u>>30)&3)/3),-1).astype(np.float32)
    raise ValueError(fmt)
rp=STUDY/'results.json';before=sha(rp);r=json.loads(rp.read_text())
assert r['conversion_dispatches']==4 and r['native_dispatches']==0 and r['status']=='completed_conversion_conformance_not_solution'
assert sha(STUDY.parent/'analyze.py')==r['script_sha256'] and sha(CPU/'results.json')==r['CPU_reference_sha256']
cr=json.loads((CPU/'results.json').read_text());baseline=json.loads((HERE/'audit.json').read_text())
manifest_path=STUDY/'persisted_shader_jobs/manifest.json';manifest=json.loads(manifest_path.read_text())
assert sha(manifest_path)==r['captured_jobs_manifest_sha256'] and len(manifest['jobs'])==4
assert sha(STUDY.parent/'capturing_worker.py')==manifest['source_sha256']==r['capture_worker_sha256']
derivation=json.loads((STUDY.parent/'source_derivation.json').read_text())
for path,key in ((Path(derivation['parent']),'parent_sha256'),(STUDY.parent/'analyze.py','derived_script_sha256'),(STUDY.parent/'generate.py','generator_sha256'),(STUDY.parent/'capturing_worker.py','capture_worker_sha256')):assert sha(path)==derivation[key]
tree=ast.parse((STUDY.parent/'generate.py').read_text())
changes=ast.literal_eval(next(n.value for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='changes' for t in n.targets)))
text=Path(derivation['parent']).read_text()
for old,new in changes:assert text.count(old)==1;text=text.replace(old,new,1)
assert text==(STUDY.parent/'analyze.py').read_text()
worker=(STUDY.parent/'capturing_worker.py').read_text()
assert worker.index('completed=super().run(args,**kwargs)')<worker.index('shutil.copyfile(p,target)')<worker.index('return completed',worker.index('shutil.copyfile(p,target)'))
assert 'sha(p)!=before or sha(target)!=before' in worker
for name,value in r['production_shader_identity'].items():assert sha(PRE/name)==value
audit=dict(schema='retained-four-camera-conversion-independent-audit-v1',analysis_sha256=sha(__file__),report_sha256=before,
    original_limited_audit_sha256=sha(HERE/'audit.json'),source_derivation_sha256=sha(STUDY.parent/'source_derivation.json'),manifest_sha256=sha(manifest_path),
    conversion_dispatches=4,native_RR_dispatches=0,new_GPU_calls=0,quality_accepted=False,actual_CB_and_inputs_outputs_retained=True,
    same_four_call_protocol_source_derivation_verified=True,rows=[],comparisons=[],
    limitations=['These are conversion-only fixtures; no native RR or game-quality result.',
        'Identity inverse projection is intentionally inconsistent geometry; it is not a shader implementation failure.',
        'Current View identity does not independently validate nonidentity current-view normal conversion.',
        'The new repeat supplies actual retained job bytes/logs; the original repeat staging/log gap remains explicitly preserved in its separate audit.'])
fingerprints={rp:before,manifest_path:sha(manifest_path)};arrays={};CBs={};inputsets={}
for row,entry in zip(r['rows'],manifest['jobs']):
    key=f"{row['arm']}_strength{row['strength']}";folder=STUDY/'persisted_shader_jobs'/entry['job_name']
    assert entry['returncode']==0 and entry['actual_run_completed']
    for identity in entry['files']:
        file=folder/identity['name'];assert file.stat().st_size==identity['size'] and sha(file)==identity['sha256'];fingerprints[file]=sha(file)
    assert len(entry['files'])==27 # CB + 17 inputs + 8 outputs + job
    log=folder/'runner.log';logtext=log.read_text();assert sha(log)==entry['runner_log_sha256'];fingerprints[log]=sha(log)
    assert 'debug_layer=1' in logtext and 'validation_errors=0 validation_warnings=0' in logtext
    fixture=next(v for v in cr['payloads'] if v['roughness']==.1 and v['matched_inverse_projection']==(row['arm']=='matched'))
    fp=Path(fixture['path']);assert sha(fp)==fixture['sha256']==row['fixture_sha256'] and fixture['overrides']==row['overrides'];fingerprints[fp]=sha(fp)
    with np.load(fp) as pack:f={k:pack[k].copy() for k in pack.files}
    payload=STUDY/(key+'.npz');assert sha(payload)==row['payload_sha256'];fingerprints[payload]=sha(payload)
    with np.load(payload) as pack:values=[pack[f'packed_{i}'].copy() for i in range(8)]
    arrays[key]=values
    original=ROOT/'tools_tmp/rotating_camera_gpu_conformance_20260930/evidence'/(key+'.npz')
    assert sha(original)==row['payload_sha256'] # new repeat results byte-identical to old immutable payload
    job=folder/'job.txt';lines=job.read_text().splitlines();paths,header=parse(lines[0],2)
    shader='FSRDInputConv' if row['strength']==0 else 'FSRDInputConvAdditive'
    assert paths[0].resolve()==(PRE/(shader+'_Shader.cso')).resolve() and row['actual_shader']==shader and header==[128,80,17,8,1]
    assert sha(paths[0])==r['production_shader_identity'][paths[0].name]
    cb=folder/'cb.bin';expected_cb=HERE/f'{key}_source_reconstructed_cb.bin'
    assert cb.read_bytes()==expected_cb.read_bytes() and cb.stat().st_size==416;CBs[key]=cb.read_bytes()
    # Actual retained matrix bytes, independent of row metadata inference.
    parsed_matrices={name:np.frombuffer(cb.read_bytes(),'<f4',count=16,offset=offset).reshape(4,4).copy() for name,offset in (('InvViewMatrix',0),('InvProjMatrix',64),('PrevViewMatrix',128))}
    for name,matrix in parsed_matrices.items():np.testing.assert_array_equal(matrix.ravel(),np.asarray(row['overrides'][name],np.float32))
    offsets=next(v['CB_field_offsets'] for v in baseline['rows'] if v['arm']==row['arm'] and v['strength']==row['strength'])
    assert struct.unpack_from('<I',cb.read_bytes(),offsets['Flags'])[0]==2082
    assert struct.unpack_from('<f',cb.read_bytes(),412)[0]==row['strength']
    zero=np.zeros((80,128,4),np.float32)
    expected_inputs=[f['raw'],f['depth'],f['motion'],f['normals'],f['roughness'],f['depth'],f['diff'],f['spec'],zero,zero,zero,zero,zero,zero,f['depth'],zero,f['raw']]
    inputhashes={}
    for i,(line,array) in enumerate(zip(lines[1:18],expected_inputs)):
        p,desc=parse(line,1);assert p[0].name==f'in{i}.bin' and desc[:2]==[128,80]
        actual=folder/p[0].name;assert actual.read_bytes()==storage(array,desc[2]);inputhashes[actual.name]=sha(actual)
    inputsets[key]=inputhashes
    rawhashes={}
    for i,line in enumerate(lines[18:]):
        p,desc=parse(line,1);assert p[0].name==f'out{i}.bin' and desc[:2]==[128,80]
        actual=folder/p[0].name;np.testing.assert_array_equal(decode(actual,desc[2]),values[i]);rawhashes[actual.name]=sha(actual)
    # All-pixel reconstruction uses ACTUAL consumed CB inverse/view matrices.
    y,x=np.indices((80,128));uv=np.stack(((x+.5)/128,(y+.5)/80),-1)
    ndc=np.concatenate((2*uv[...,:1]-1,1-2*uv[...,1:2],np.full((80,128,1),.5),np.ones((80,128,1))),-1)
    point=ndc@parsed_matrices['InvProjMatrix'].astype(float);xyz=point[...,:3]/point[...,3:4]
    xyz*=10/xyz[...,2:3];xyz[...,2]=10
    world=np.concatenate((xyz,np.ones((80,128,1))),-1)@parsed_matrices['InvViewMatrix'].astype(float)
    previous=world@parsed_matrices['PrevViewMatrix'].astype(float)
    consumed_motion=np.frombuffer((folder/'in2.bin').read_bytes(),'<f2').reshape(80,128,4).astype(float)
    expected=np.concatenate((consumed_motion[...,:2],(previous[...,2]-10)[...,None],np.ones((80,128,1))),-1).astype(np.float16).astype(float)
    motion=values[2];err=abs(motion-expected);passes=np.all(err<=tolerance(expected))
    assert bool(passes)==row['all_pixel_motion_within_one_ulp_plus_1e_minus_5']
    physical=f['expected_physical_mvz'];physical_error=abs(motion[...,2]-physical)
    physical_pass=bool(np.all(physical_error<=tolerance(physical)));assert physical_pass==row['all_pixel_physical_mvz_within_tolerance']==(row['arm']=='matched')
    assert stats(motion[...,2],physical)==row['physical_mvz']
    np.testing.assert_array_equal(motion[...,:2],consumed_motion[...,:2]);assert np.all(motion[...,3]==1)
    assert np.all(abs(values[3]-f['expected_normal_before_storage'])<=1/1023+1e-4)
    assert np.all(values[0][...,3]==10) and np.all(values[1][...,3]==65504)
    audit['rows'].append(dict(arm=row['arm'],strength=row['strength'],actual_job_name=entry['job_name'],CSO_sha256=sha(paths[0]),CB_sha256=sha(cb),
        job_sha256=sha(job),log_sha256=sha(log),all_17_actual_input_bytes_match_fixture_storage=True,input_sha256=inputhashes,
        all_8_actual_output_decodes_exact_NPZ=True,output_sha256=rawhashes,original_repeat_payload_exact=True,
        consumed_float32_matrix_overrides_exact=True,converter_all_pixel_tolerance_pass=bool(passes),physical_all_pixel_tolerance_pass=physical_pass,
        physical_failing_pixels=int(np.count_nonzero(physical_error>tolerance(physical))),physical_MVZ=stats(motion[...,2],physical),
        D3D_debug_errors=0,D3D_debug_warnings=0,motion_alpha_exact_one=True))
for strength in (0,1):
    matched=f'matched_strength{strength}';identity=f'identity_strength{strength}'
    assert inputsets[matched]==inputsets[identity]
    changed=np.flatnonzero(np.frombuffer(CBs[matched],np.uint8)!=np.frombuffer(CBs[identity],np.uint8)).tolist()
    assert all(64<=i<128 for i in changed)
    a,b=arrays[matched],arrays[identity]
    assert np.array_equal(a[2][...,:2],b[2][...,:2]) and np.array_equal(a[3],b[3]) and np.array_equal(a[0][...,:3],b[0][...,:3]) and np.array_equal(a[1][...,:3],b[1][...,:3])
    audit['comparisons'].append(dict(strength=strength,matched_identity_inputs_all_17_exact=True,CB_changed_byte_offsets=changed,
        CB_only_inverse_projection_differs=True,MVXY_normals_specRGB_diffRGB_exact=True,MVZ=stats(a[2][...,2],b[2][...,2])))
for arm in ('matched','identity'):
    a,b=CBs[f'{arm}_strength0'],CBs[f'{arm}_strength1'];changed=np.flatnonzero(np.frombuffer(a,np.uint8)!=np.frombuffer(b,np.uint8)).tolist();assert changed==[414,415]
    assert all(np.array_equal(x,y) for x,y in zip(arrays[f'{arm}_strength0'],arrays[f'{arm}_strength1']))
audit['split0_split1_CB_only_additive_strength_differs_and_all_outputs_exact']=True
assert all(sha(path)==value for path,value in fingerprints.items())
audit['all_original_evidence_unchanged']=True
out=HERE/'capture_audit.json';assert not out.exists();out.write_text(json.dumps(audit,indent=2)+'\n')
print('capture_audit_sha256',sha(out))
for row in audit['rows']:print(row['arm'],row['strength'],row['physical_MVZ'],row['physical_failing_pixels'])
