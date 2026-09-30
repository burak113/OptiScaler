"""CPU-only independent audit of original four conversion outputs.

Deleted staging files and unsaved per-job logs are explicitly NOT attested as
retained consumed bytes. Reconstructed CBs are saved only inside this audit.
"""
import ast,hashlib,json,math,re,struct
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
STUDY=ROOT/'tools_tmp/rotating_camera_gpu_conformance_20260930/evidence'
CPU=ROOT/'tools_tmp/rotating_camera_conformance_20260930'
PRE=ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile'
TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(b):return hashlib.sha256(b).hexdigest()
def stats(a,b):
    d=np.asarray(a,float)-np.asarray(b,float)
    return dict(rms=float(np.sqrt(np.mean(d*d))),maximum_absolute=float(abs(d).max()),exact_equal=bool(np.array_equal(a,b)))
def tolerance(a):
    a=np.asarray(a,np.float16)
    up=np.nextafter(a,np.float16(np.inf)).astype(float)-a.astype(float)
    down=a.astype(float)-np.nextafter(a,np.float16(-np.inf)).astype(float)
    return np.maximum(abs(up),abs(down))+1e-5
def reconstruct(uv,depth,inv):
    clip=np.concatenate((2*uv[...,:1]-1,1-2*uv[...,1:2],np.full((*uv.shape[:-1],1),.5),np.ones((*uv.shape[:-1],1))),-1)
    point=clip@inv
    xyz=point[...,:3]/point[...,3:4]
    xyz*=depth[...,None]/xyz[...,2:3];xyz[...,2]=depth
    return xyz
def json_paths(line,count):
    decoder=json.JSONDecoder();paths=[];remainder=line
    for _ in range(count):
        remainder=remainder.lstrip();value,end=decoder.raw_decode(remainder);assert isinstance(value,str)
        paths.append(Path(value));remainder=remainder[end:]
    return paths,list(map(int,remainder.split()))

rp=STUDY/'results.json';before=sha(rp);r=json.loads(rp.read_text())
assert r['status']=='completed_conversion_conformance_not_solution' and r['conversion_dispatches']==4 and r['native_dispatches']==0 and not r['quality_accepted']
assert sha(STUDY.parent/'analyze.py')==r['script_sha256']
crp=CPU/'results.json';assert sha(crp)==r['CPU_reference_sha256'];cr=json.loads(crp.read_text())
assert sha(CPU/'fixture.py')==cr['fixture_source_sha256'] and sha(CPU/'analyze.py')==cr['analysis_sha256']
for name,expected in r['production_shader_identity'].items():assert sha(PRE/name)==expected
converter=(TESTS/'fsrd_alpha_common.py').read_text();runnerpy=(TESTS/'run_fsrd_gpu_tests.py').read_text()
assert "(kernel == 'auto' and applied > 0 and Path(directory).resolve() == t.PRE.resolve())" in converter
assert 'for staging in d.glob(\'*.bin\'):' in runnerpy and 'staging.unlink()' in runnerpy
assert "'debug_layer=1' not in log" in converter and "'validation_errors=0 validation_warnings=0' not in log" in converter
source=ast.parse(converter);node=next(v for v in source.body if isinstance(v,ast.FunctionDef) and v.name=='conversion_cb')
ns={'np':np};exec(compile(ast.Module(body=[node],type_ignores=[]),str(TESTS/'fsrd_alpha_common.py'),'exec'),ns)

def serialize_expected_cb(row):
    # Parse current source layout independently, including experimental padding.
    text=(PRE/'FSRDInputConv.hlsl').read_text();body=text.split('cbuffer CB_Packing : register(b0)',1)[1].split('{',1)[1].split('}',1)[0]
    fields=[];offset=0
    sizes={'float4x4':(64,16),'float4':(16,16),'uint4':(16,16),'float':(4,4),'uint':(4,4)}
    for line in body.splitlines():
        line=line.split('//',1)[0].strip()
        if not line or line.startswith('#'):continue
        typ,name=re.fullmatch(r'(\w+)\s+(\w+);',line).groups();size,align=sizes[typ]
        offset=(offset+align-1)//align*align
        if offset%16 and offset%16+size>16:offset=(offset+15)//16*16
        fields.append((typ,name,offset,size));offset+=size
    size=(offset+15)//16*16;assert size==416
    values=ns['conversion_cb'](128,80,row['strength'],False,**row['overrides']);blob=bytearray(size)
    for typ,name,offset,size in fields:
        if name not in values:continue
        value=values[name];value=[value] if np.isscalar(value) else list(value)
        packed=struct.pack('<'+('I' if typ.startswith('uint') else 'f')*len(value),*value)
        assert len(packed)==size;blob[offset:offset+size]=packed
    field_offsets={name:offset for typ,name,offset,size in fields}
    assert field_offsets['InvViewMatrix']==0 and field_offsets['InvProjMatrix']==64 and field_offsets['PrevViewMatrix']==128 and field_offsets['AdditiveLightSplit']==412
    for name in ('InvViewMatrix','InvProjMatrix','PrevViewMatrix'):
        np.testing.assert_array_equal(np.frombuffer(blob,'<f4',count=16,offset=field_offsets[name]),np.asarray(row['overrides'][name],np.float32))
    assert struct.unpack_from('<I',blob,field_offsets['Flags'])[0]==2082
    assert struct.unpack_from('<f',blob,412)[0]==row['strength']
    return bytes(blob),field_offsets

audit=dict(schema='original-four-camera-conversion-independent-audit-v1',analysis_sha256=sha(__file__),original_report_sha256=before,
    conversion_dispatches=4,native_RR_dispatches=0,new_GPU_calls=0,quality_accepted=False,rows=[],comparisons=[],
    provenance_qualification=['Original staging CB/input/output bins were deleted by _dispatch. Expected CBs here are source-reconstructed, not authenticated retained consumed CB bytes.',
        'Original per-job stdout was checked inside GPUWorker but not retained. Job requests and shader file hashes are directly inspectable; per-job D3D logs cannot be directly re-audited.',
        'Reported key all_pixel_motion_within_one_ulp_plus_1e5 is a naming typo: source and independent calculation both use one FP16 ulp PLUS 1e-5, not 1e5.',
        'Current View identity does not establish nonidentity current-view normal-space conformance.',
        'Identity inverse projection is intentionally mismatched geometry, not a shader-failure/quality result or a cause of old static native variability.'])
arrays={};fingerprints={rp:before,crp:sha(crp)}
for i,row in enumerate(r['rows']):
    key=f"{row['arm']}_strength{row['strength']}";path=STUDY/(key+'.npz')
    assert sha(path)==row['payload_sha256'];fingerprints[path]=sha(path)
    fixture=next(p for p in cr['payloads'] if p['roughness']==.1 and p['matched_inverse_projection']==(row['arm']=='matched'))
    fp=Path(fixture['path']);assert sha(fp)==fixture['sha256']==row['fixture_sha256'] and fixture['overrides']==row['overrides'];fingerprints[fp]=sha(fp)
    with np.load(fp) as pack:f={name:pack[name].copy() for name in pack.files}
    with np.load(path) as pack:values=[pack[f'packed_{k}'].copy() for k in range(8)];assert len(pack.files)==8
    assert all(v.shape==(80,128,4) and v.dtype==np.float32 and np.isfinite(v).all() for v in values)
    arrays[key]=values
    shader='FSRDInputConv' if row['strength']==0 else 'FSRDInputConvAdditive'
    job=STUDY/'shader_jobs'/f'{i:03}_{shader}'/'job.txt';fingerprints[job]=sha(job)
    lines=job.read_text().splitlines();paths,header=json_paths(lines[0],2)
    assert paths[0].resolve()==(PRE/(shader+'_Shader.cso')).resolve() and header==[128,80,17,8,1]
    assert shader==row['actual_shader'] and sha(paths[0])==r['production_shader_identity'][paths[0].name]
    inputs=[json_paths(line,1) for line in lines[1:18]];outputs=[json_paths(line,1) for line in lines[18:]]
    assert [item[1] for item in inputs]==[[128,80,fmt] for fmt in [10,41,10,10,41,41,10,10,41,10,10,10,10,10,41,41,10]]
    assert [item[1] for item in outputs]==[[128,80,fmt] for fmt in [10,10,10,24,28,28,10,10]]
    assert not paths[1].exists() and all(not item[0][0].exists() for item in inputs+outputs)
    cb,offsets=serialize_expected_cb(row);cbpath=HERE/f'{key}_source_reconstructed_cb.bin';assert not cbpath.exists();cbpath.write_bytes(cb)
    # Independent physical reference from consumed float32 projection entries.
    projection=f['projection'].astype(float);previous=np.asarray(row['overrides']['PrevViewMatrix'],np.float32).reshape(4,4).astype(float)
    inverse=np.asarray(row['overrides']['InvProjMatrix'],np.float32).reshape(4,4).astype(float)
    y,x=np.indices((80,128));uv=np.stack(((x+.5)/128,(y+.5)/80),-1)
    physical_xyz=np.stack(((2*uv[...,0]-1)*10/projection[0,0],(1-2*uv[...,1])*10/projection[1,1],np.full((80,128),10.)),axis=-1)
    physical_prev=np.concatenate((physical_xyz,np.ones((80,128,1))),-1)@previous
    physical_delta=physical_prev[...,2]-10.
    np.testing.assert_allclose(physical_delta,f['expected_physical_mvz'],atol=0,rtol=0)
    xyz=reconstruct(uv,f['depth'].astype(float),inverse);prev=np.concatenate((xyz,np.ones((80,128,1))),-1)@previous
    expected=np.concatenate((f['motion'][...,:2],(prev[...,2]-xyz[...,2])[...,None],np.ones((80,128,1))),-1).astype(np.float16).astype(float)
    np.testing.assert_array_equal(expected,f['expected_converter_motion_fp16'].astype(float))
    motion=values[2];err=np.abs(motion-expected);tol=tolerance(expected)
    physical_err=np.abs(motion[...,2]-physical_delta);physical_tol=tolerance(physical_delta)
    checks=dict(converter_all_pixel_within_one_FP16_ulp_plus_1e_minus_5=bool(np.all(err<=tol)),converter_failing_values=int(np.count_nonzero(err>tol)),
        physical_MVZ_all_pixel_within_one_FP16_ulp_plus_1e_minus_5=bool(np.all(physical_err<=physical_tol)),physical_failing_pixels=int(np.count_nonzero(physical_err>physical_tol)))
    assert checks['converter_all_pixel_within_one_FP16_ulp_plus_1e_minus_5']==row['all_pixel_motion_within_one_ulp_plus_1e5']
    assert checks['physical_MVZ_all_pixel_within_one_FP16_ulp_plus_1e_minus_5']==row['all_pixel_physical_mvz_within_tolerance']==(row['arm']=='matched')
    physical_stats=stats(motion[...,2],physical_delta);expected_stats=stats(motion,expected)
    for actual,reported in ((physical_stats,row['physical_mvz']),(expected_stats,row['expected_converter_motion'])):
        for k in actual:assert actual[k]==reported[k]
    np.testing.assert_array_equal(motion[...,:2],f['motion'][...,:2].astype(np.float16).astype(float))
    assert np.all(motion[...,3]==1) and np.all(abs(values[3]-f['expected_normal_before_storage'])<=1/1023+1e-4)
    assert np.all(values[0][...,3]==10) and np.all(values[1][...,3]==65504)
    # Retained FP16 outputs are exact float16 decoded values. Their reconstructed
    # byte hashes are new facts, NOT a comparison against deleted raw outputs.
    out_hashes={}
    for k in (0,1,2,6,7):
        np.testing.assert_array_equal(values[k],values[k].astype(np.float16).astype(np.float32))
        out_hashes[f'packed_{k}']=digest(values[k].astype('<f2').tobytes())
    peak=np.unravel_index(np.argmax(physical_err),physical_err.shape)
    audit['rows'].append(dict(arm=row['arm'],strength=row['strength'],payload_sha256=sha(path),fixture_sha256=sha(fp),job_sha256=sha(job),
        requested_shader_proven_by_job=shader,requested_CSO_sha256=sha(paths[0]),job_dimensions_formats_valid=True,retained_CB=False,
        source_reconstructed_CB_sha256=sha(cbpath),CB_field_offsets=offsets,retained_per_job_stdout=False,
        reconstructed_output_FP16_bytes_sha256=out_hashes,physical_MVZ=physical_stats,converter_motion=expected_stats,
        physical_peak_y_x=list(map(int,peak)),physical_peak_signed_error=float(motion[...,2][peak]-physical_delta[peak]),
        motion_alpha_exact_one=True,spec_alpha_exact10=True,diff_alpha_exact65504=True,**checks))
for strength in (0,1):
    a,b=arrays[f'matched_strength{strength}'],arrays[f'identity_strength{strength}']
    measures=dict(motion_xy=stats(a[2][...,:2],b[2][...,:2]),motion_z=stats(a[2][...,2],b[2][...,2]),normal_roughness_material=stats(a[3],b[3]),specular_input_rgb=stats(a[0][...,:3],b[0][...,:3]),diffuse_input_rgb=stats(a[1][...,:3],b[1][...,:3]))
    reported=next(v for v in r['comparisons'] if v['strength']==strength)
    for k,v in measures.items():assert v==reported[k]
    assert all(measures[k]['exact_equal'] for k in measures if k!='motion_z') and not measures['motion_z']['exact_equal']
    audit['comparisons'].append(dict(strength=strength,**measures))
audit['strength0_vs1_all_eight_outputs_exact_equal']={arm:all(np.array_equal(a,b) for a,b in zip(arrays[f'{arm}_strength0'],arrays[f'{arm}_strength1'])) for arm in ('matched','identity')}
stderr=STUDY/'gpu_worker_stderr.log';assert stderr.exists() and stderr.stat().st_size==0
audit['worker_stderr_sha256']=sha(stderr);audit['worker_stderr_empty']=True
audit['runner_binary_sha256']=sha(STUDY/'fsrd_gpu_runner.exe');audit['runner_build_command_sha256']=sha(STUDY/'fsrd_gpu_runner.build.cmd')
audit['CPU_reference_consumed_float32_matrices_verified']=True
audit['original_evidence_unchanged']=all(sha(path)==value for path,value in fingerprints.items());assert audit['original_evidence_unchanged']
out=HERE/'audit.json';assert not out.exists();out.write_text(json.dumps(audit,indent=2)+'\n')
print('audit_sha256',sha(out))
for row in audit['rows']:print(row['arm'],row['strength'],row['physical_MVZ'],row['physical_failing_pixels'])
