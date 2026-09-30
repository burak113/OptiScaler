"""Eight retained conversion jobs: independent hashes/geometry/normals, CPU only."""
import ast,hashlib,json,re,struct
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
STUDY=ROOT/'tools_tmp/current_camera_gpu_conformance_20260930/evidence'
CPU=ROOT/'tools_tmp/current_camera_conformance_20260930'
PRE=ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile';TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stats(a,b):
    a,b=np.asarray(a,float),np.asarray(b,float);d=a-b;loc=np.unravel_index(np.argmax(abs(d)),d.shape)
    return dict(exact_equal=bool(np.array_equal(a,b)),rms=float(np.sqrt(np.mean(d*d))),maximum_absolute=float(abs(d[loc])),maximum_location=list(map(int,loc)),differing_values=int(np.count_nonzero(d)))
def tolerance(a):
    a=np.asarray(a,np.float16)
    return np.maximum(abs(np.nextafter(a,np.float16(np.inf)).astype(float)-a.astype(float)),abs(a.astype(float)-np.nextafter(a,np.float16(-np.inf)).astype(float)))+1e-5
def check(a,b):
    error=abs(np.asarray(a,float)-b);bad=error>tolerance(b)
    return dict(**stats(a,b),within_tolerance=bool(not np.any(bad)),failing_values=int(np.count_nonzero(bad)))
def normalize(n):return n/np.linalg.norm(n,axis=-1,keepdims=True)
def oct_decode(uv):
    xy=np.asarray(uv,float)*2-1;n=np.concatenate((xy,1-abs(xy).sum(-1,keepdims=True)),-1)
    fold=np.maximum(-n[...,2:3],0);n[...,:2]+=np.where(n[...,:2]>=0,-fold,fold)
    return normalize(n)
def angles(a,b):
    angle=np.arccos(np.clip((a*normalize(np.asarray(b,float))).sum(-1),-1,1))
    return dict(maximum_angle_radians=float(angle.max()),rms_angle_radians=float(np.sqrt(np.mean(angle*angle))),within_0_003_radians=bool(np.all(angle<=.003)),failing_pixels=int(np.count_nonzero(angle>.003)))
def parse(line,n):
    decoder=json.JSONDecoder();paths=[]
    for i in range(n):line=line.lstrip();value,end=decoder.raw_decode(line);paths.append(Path(value));line=line[end:]
    return paths,list(map(int,line.split()))
def storage(a,fmt):
    a=np.asarray(a,np.float32)
    if a.ndim==2:a=np.repeat(a[...,None],4,-1)
    if fmt==10:return a.astype('<f2').tobytes()
    if fmt==41:return a[...,0].astype('<f4').tobytes()
    raise ValueError(fmt)
def decode(p,fmt):
    if fmt==10:return np.frombuffer(p.read_bytes(),'<f2').reshape(80,128,4).astype(np.float32)
    if fmt==28:return np.frombuffer(p.read_bytes(),np.uint8).reshape(80,128,4).astype(np.float32)/255
    if fmt==24:
        u=np.frombuffer(p.read_bytes(),'<u4').reshape(80,128)
        return np.stack(((u&1023)/1023,((u>>10)&1023)/1023,((u>>20)&1023)/1023,((u>>30)&3)/3),-1).astype(np.float32)
    raise ValueError(fmt)
rp=STUDY/'results.json';before=sha(rp);r=json.loads(rp.read_text());crp=CPU/'results.json';cr=json.loads(crp.read_text())
assert r['status']=='completed_conversion_diagnostic_not_solution' and r['conversion_dispatches']==8 and r['native_RR_dispatches']==0 and not r['quality_accepted']
assert sha(crp)==r['CPU_reference_sha256'] and sha(STUDY.parent/'analyze.py')==r['script_sha256']
assert sha(CPU/'fixture.py')==cr['fixture_source_sha256'] and sha(CPU/'analyze.py')==cr['analysis_sha256']
for row in cr['source_identities']:assert sha(row['path'])==row['sha256']
for name,value in r['production_shader_identity'].items():assert sha(PRE/name)==value
worker=STUDY.parent/'capturing_worker.py';parent=Path(r['byte_identical_capture_parent_path'])
assert worker.read_bytes()==parent.read_bytes() and sha(worker)==r['capture_worker_sha256']
mp=STUDY/'persisted_shader_jobs/manifest.json';m=json.loads(mp.read_text())
assert sha(mp)==r['captured_jobs_manifest_sha256'] and m['source_sha256']==sha(worker) and len(m['jobs'])==8
converter=(TESTS/'fsrd_alpha_common.py').read_text();tree=ast.parse(converter)
node=next(v for v in tree.body if isinstance(v,ast.FunctionDef) and v.name=='conversion_cb');ns={'np':np}
exec(compile(ast.Module(body=[node],type_ignores=[]),str(TESTS/'fsrd_alpha_common.py'),'exec'),ns)
body=(PRE/'FSRDInputConv.hlsl').read_text().split('cbuffer CB_Packing : register(b0)',1)[1].split('{',1)[1].split('}',1)[0]
fields=[];offset=0
for line in body.splitlines():
    line=line.split('//',1)[0].strip()
    if not line or line.startswith('#'):continue
    typ,name=re.fullmatch(r'(\w+)\s+(\w+);',line).groups()
    size,align={'float4x4':(64,16),'float4':(16,16),'uint4':(16,16),'float':(4,4),'uint':(4,4)}[typ]
    offset=(offset+align-1)//align*align
    if offset%16 and offset%16+size>16:offset=(offset+15)//16*16
    fields.append((typ,name,offset,size));offset+=size
assert (offset+15)//16*16==416
offsets={name:offset for typ,name,offset,size in fields}
audit=dict(schema='current-camera-eight-retained-job-independent-audit-v1',analysis_sha256=sha(__file__),report_sha256=before,
    CPU_reference_sha256=sha(crp),job_manifest_sha256=sha(mp),conversion_dispatches=8,native_RR_dispatches=0,new_GPU_calls=0,quality_accepted=False,
    capture_worker_byte_identical_parent=True,all_actual_CB_input_output_and_logs_retained=True,rows=[],comparisons=[],
    qualifications=['Only conversion conformance: no native RR, game quality or old same-input context variability cause is inferred.',
        'Hardware-depth arms exercise the defensive GetViewSpacePos hardware path, not production FloorSeed canonical-depth or native RR input conformance.',
        'World/view normal conformance uses decoded 3D angular error; raw oct corner UV equality is only a diagnostic.',
        'FP16/R32 uploads and float32 consumed matrices are included. Tolerances are frozen one FP16 ulp+1e-5 and normal angle.003rad.'])
fingerprints={rp:before,crp:sha(crp),mp:sha(mp)};arrays={};CBs={};inputs={}
for row,entry in zip(r['rows'],m['jobs']):
    key=f"{row['arm']}_strength{row['strength']}";folder=STUDY/'persisted_shader_jobs'/entry['job_name']
    assert entry['returncode']==0 and entry['actual_run_completed'] and len(entry['files'])==27
    for identity in entry['files']:
        path=folder/identity['name'];assert path.stat().st_size==identity['size'] and sha(path)==identity['sha256'];fingerprints[path]=sha(path)
    log=folder/'runner.log';text=log.read_text();assert sha(log)==entry['runner_log_sha256']
    assert 'debug_layer=1' in text and 'validation_errors=0 validation_warnings=0' in text;fingerprints[log]=sha(log)
    arm=next(v for v in cr['arms'] if v['name']==row['arm']);fp=Path(arm['payload_path'])
    assert sha(fp)==arm['payload_sha256']==row['fixture_sha256'] and arm['overrides']==row['overrides'];fingerprints[fp]=sha(fp)
    with np.load(fp) as pack:f={k:pack[k].copy() for k in pack.files}
    payload=Path(row['payload_path']);assert sha(payload)==row['payload_sha256'];fingerprints[payload]=sha(payload)
    with np.load(payload) as pack:values=[pack[f'packed_{i}'].copy() for i in range(8)]
    arrays[key]=values;shader='FSRDInputConv' if row['strength']==0 else 'FSRDInputConvAdditive'
    lines=(folder/'job.txt').read_text().splitlines();paths,header=parse(lines[0],2)
    assert paths[0].resolve()==(PRE/(shader+'_Shader.cso')).resolve() and row['actual_shader']==shader and header==[128,80,17,8,1]
    assert sha(paths[0])==r['production_shader_identity'][paths[0].name]
    values_cb=ns['conversion_cb'](128,80,row['strength'],False,**row['overrides']);expected_cb=bytearray(416)
    for typ,name,offset,size in fields:
        if name not in values_cb:continue
        v=values_cb[name];v=[v] if np.isscalar(v) else list(v)
        data=struct.pack('<'+('I' if typ.startswith('uint') else 'f')*len(v),*v);assert len(data)==size;expected_cb[offset:offset+size]=data
    cb=(folder/'cb.bin').read_bytes();assert cb==bytes(expected_cb);CBs[key]=cb
    matrices={name:np.frombuffer(cb,'<f4',count=16,offset=offsets[name]).reshape(4,4).astype(float) for name in ('InvViewMatrix','InvProjMatrix','PrevViewMatrix')}
    for name,matrix in matrices.items():np.testing.assert_array_equal(matrix.ravel(),np.asarray(row['overrides'][name],np.float32))
    flags=struct.unpack_from('<I',cb,offsets['Flags'])[0];assert flags==arm['overrides']['Flags']
    zero=np.zeros((80,128,4),np.float32)
    expected_inputs=[f['raw'],f['depth'],f['motion'],f['normals'],f['roughness'],f['depth'],f['diff'],f['spec'],zero,zero,zero,zero,zero,zero,f['depth'],zero,f['raw']]
    hashes={}
    formats=[10,41,10,10,41,41,10,10,41,10,10,10,10,10,41,41,10]
    for i,(line,a) in enumerate(zip(lines[1:18],expected_inputs)):
        p,desc=parse(line,1);assert p[0].name==f'in{i}.bin' and desc==[128,80,formats[i]]
        actual=folder/p[0].name;assert actual.read_bytes()==storage(a,desc[2]);hashes[actual.name]=sha(actual)
    inputs[key]=hashes;out_hashes={}
    for i,line in enumerate(lines[18:]):
        p,desc=parse(line,1);assert p[0].name==f'out{i}.bin' and desc==[128,80,[10,10,10,24,28,28,10,10][i]]
        raw=folder/p[0].name;np.testing.assert_array_equal(decode(raw,desc[2]),values[i]);out_hashes[raw.name]=sha(raw)
    # Predict same-current-world-point geometry from actual consumed CB/R32.
    y,x=np.indices((80,128));uv=np.stack(((x+.5)/128,(y+.5)/80),-1)
    depth=np.frombuffer((folder/'in1.bin').read_bytes(),'<f4').reshape(80,128).astype(float)
    z=np.full((80,128),.5) if flags&2 else depth
    clip=np.stack((2*uv[...,0]-1,1-2*uv[...,1],z,np.ones((80,128))),-1)
    p=clip@matrices['InvProjMatrix'];xyz=p[...,:3]/p[...,3:4]
    target_z=np.clip(abs(depth if flags&2 else xyz[...,2]),.1,1000.)
    xyz*=target_z[...,None]/xyz[...,2:3];xyz[...,2]=target_z
    world=np.concatenate((xyz,np.ones((80,128,1))),-1)@matrices['InvViewMatrix']
    prev=world@matrices['PrevViewMatrix'];delta=prev[...,2]-xyz[...,2]
    consumed_mv=np.frombuffer((folder/'in2.bin').read_bytes(),'<f2').reshape(80,128,4).astype(float)
    expected=np.concatenate((consumed_mv[...,:2],delta[...,None],np.ones((80,128,1))),-1).astype(np.float16)
    np.testing.assert_array_equal(expected,f['expected_converter_motion_fp16'])
    motion_check=check(values[2],expected);physical_check=check(values[2][...,2],f['physical_mvz'])
    assert motion_check==row['expected_converter_motion'] and physical_check==row['physical_mvz']
    np.testing.assert_array_equal(values[2][...,:2],consumed_mv[...,:2]);assert np.all(values[2][...,3]==1)
    normal_raw=np.frombuffer((folder/'in3.bin').read_bytes(),'<f2').reshape(80,128,4)[...,:3].astype(float)
    expected_world_normal=normalize(normal_raw@matrices['InvViewMatrix'][:3,:3] if flags&2048 else normal_raw)
    np.testing.assert_allclose(expected_world_normal,f['expected_converter_world_normal'],rtol=0,atol=0)
    decoded=oct_decode(values[3][...,:2]);normal_physical=angles(decoded,f['world_normal']);normal_expected=angles(decoded,expected_world_normal)
    for actual,stored in ((normal_physical,row['decoded_normal_physical']),(normal_expected,row['decoded_normal_consumed_expected'])):
        for k,v in actual.items():
            if isinstance(v,float):np.testing.assert_allclose(v,stored[k],rtol=0,atol=1e-12)
            else:assert v==stored[k]
    spec_check=check(values[0][...,3],f['expected_specular_alpha_fp16']);assert spec_check==row['specular_alpha']
    rough=float(abs(values[3][...,2]-f['roughness']).max());assert rough==row['roughness_maximum_error'] and rough<=1/1023+1e-4
    assert np.all(values[3][...,3]==0) and np.all(values[1][...,3]==65504)
    gates=motion_check['within_tolerance'] and physical_check['within_tolerance'] and normal_physical['within_0_003_radians'] and normal_expected['within_0_003_radians'] and spec_check['within_tolerance']
    assert gates==row['conformance_pass']==True
    audit['rows'].append(dict(arm=row['arm'],strength=row['strength'],payload_sha256=sha(payload),fixture_sha256=sha(fp),actual_shader=shader,CSO_sha256=sha(paths[0]),
        actual_CB_sha256=hashlib.sha256(cb).hexdigest(),all_CB_bytes_source_expected_exact=True,all_17_input_bytes_fixture_storage_exact=True,input_sha256=hashes,
        all_8_raw_output_decodes_NPZ_exact=True,output_sha256=out_hashes,job_sha256=sha(folder/'job.txt'),log_sha256=sha(log),
        D3D_debug_errors=0,D3D_debug_warnings=0,actual_flags=flags,converter_motion=motion_check,physical_MVZ=physical_check,
        normal_world=normal_physical,normal_consumed_expected=normal_expected,specular_alpha=spec_check,
        raw_oct_encodings=np.unique(values[3][...,:2].reshape(-1,2),axis=0).tolist(),conformance_pass=bool(gates)))
for arm in cr['arms']:
    name=arm['name'];a,b=arrays[name+'_strength0'],arrays[name+'_strength1']
    assert all(np.array_equal(x,y) for x,y in zip(a,b))
    changed=np.flatnonzero(np.frombuffer(CBs[name+'_strength0'],np.uint8)!=np.frombuffer(CBs[name+'_strength1'],np.uint8)).tolist();assert changed==[414,415]
    audit['comparisons'].append(dict(kind='split0_vs1',arm=name,all_eight_outputs_exact=True,CB_only_AdditiveLightSplit_differs=True,changed_CB_offsets=changed))
for depth in ('linear','hardware'):
    for strength in (0,1):
        a,b=arrays[f'{depth}_world_strength{strength}'],arrays[f'{depth}_view_strength{strength}']
        normal_agreement=angles(oct_decode(a[3][...,:2]),oct_decode(b[3][...,:2]))
        changed_inputs=[name for name in inputs[f'{depth}_world_strength{strength}'] if inputs[f'{depth}_world_strength{strength}'][name]!=inputs[f'{depth}_view_strength{strength}'][name]];assert changed_inputs==['in3.bin']
        changed_CB=np.flatnonzero(np.frombuffer(CBs[f'{depth}_world_strength{strength}'],np.uint8)!=np.frombuffer(CBs[f'{depth}_view_strength{strength}'],np.uint8)).tolist();assert all(offsets['Flags']<=i<offsets['Flags']+4 for i in changed_CB)
        audit['comparisons'].append(dict(kind='world_vs_view',depth_mode=depth,strength=strength,only_normal_input_and_space_flag_change=True,decoded_normal_angular=normal_agreement,
            all_eight_outputs_exact=all(np.array_equal(x,y) for x,y in zip(a,b)),raw_oct_UV_equal=np.array_equal(a[3][...,:2],b[3][...,:2])))
stderr=STUDY/'gpu_worker_stderr.log';assert sha(stderr)==r['worker_stderr_sha256'] and stderr.stat().st_size==0
audit['worker_stderr_sha256']=sha(stderr);audit['runner_binary_sha256']=sha(STUDY/'fsrd_gpu_runner.exe')
audit['all_eight_independent_conformance_pass']=all(v['conformance_pass'] for v in audit['rows']);assert r['all_eight_conformance_pass']==audit['all_eight_independent_conformance_pass']
audit['physical_MVZ_maximum_absolute_all_arms']=max(v['physical_MVZ']['maximum_absolute'] for v in audit['rows'])
audit['normal_world_maximum_angle_all_arms']=max(v['normal_world']['maximum_angle_radians'] for v in audit['rows'])
assert all(sha(path)==value for path,value in fingerprints.items());audit['all_original_evidence_unchanged']=True
out=HERE/'audit.json';assert not out.exists();out.write_text(json.dumps(audit,indent=2)+'\n')
print('audit_sha256',sha(out));print('MVZ_max',audit['physical_MVZ_maximum_absolute_all_arms'],'normal_maxangle',audit['normal_world_maximum_angle_all_arms'])
