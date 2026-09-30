"""Read-only CPU field inspection; no scoring, SDK load, device or model imports."""
from pathlib import Path
import sys, json, hashlib, struct, shlex
sys.dont_write_bytecode = True
import numpy as np

ROOT = Path('F:/OptiRevelations/OptiScaler-ffxD-alpha')
HERE = Path(__file__).resolve().parent
NATIVE = ROOT/'tools_tmp/fsrd_weak_material_clean_native_preparation_20260930'
CONV = ROOT/'tools_tmp/fsrd_weak_material_clean_converter_preparation_20260930'
SDK = ROOT/'external/FidelityFX-SDK-v2'

def ident(p):
    p = Path(p); b = p.read_bytes()
    return dict(path=str(p.resolve()), bytes=len(b), sha256=hashlib.sha256(b).hexdigest())
def save(name, obj):
    with (HERE/name).open('x', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, allow_nan=False); f.write('\n')
def stats(a):
    a = np.asarray(a)
    if a.ndim == 2: a = a[...,None]
    return [dict(min=float(np.min(c)), max=float(np.max(c)), finite=bool(np.all(np.isfinite(c))),
                 distinct_count=len(np.unique(c)), distinct_values=np.unique(c).tolist() if len(np.unique(c))<=16 else None)
            for c in np.moveaxis(a, -1, 0)]
def read_texture(p, fmt):
    if fmt == 41: return np.frombuffer(Path(p).read_bytes(), '<f4').reshape(80,128,1)
    if fmt == 10: return np.frombuffer(Path(p).read_bytes(), '<f2').reshape(80,128,4).astype(np.float32)
    if fmt == 28: return np.frombuffer(Path(p).read_bytes(), 'u1').reshape(80,128,4).astype(np.float64)/255
    if fmt == 24:
        u = np.frombuffer(Path(p).read_bytes(), '<u4').reshape(80,128)
        return np.stack([(u>>s)&1023 for s in (0,10,20)]+[(u>>30)&3],-1)/np.array([1023,1023,1023,3])
    raise ValueError(fmt)

sources = [NATIVE/'registration.json', NATIVE/'input_provenance.json', NATIVE/'frozen_runner/source_reference.cpp',
           SDK/'Kits/FidelityFX/denoisers/include/ffx_denoiser.h', SDK/'Kits/FidelityFX/docs/techniques/denoising.md',
           SDK/'samples/Denoisers/FidelityFX_Denoiser/dx12/shaders/trace_rays_denoiser.hlsl',
           SDK/'samples/Denoisers/FidelityFX_Denoiser/dx12/shaders/denoiser_compose.hlsl',
           SDK/'samples/Denoisers/FidelityFX_Denoiser/dx12/shaders/lighting.hlsl',
           SDK/'Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll',
           CONV/'frozen_shader/FSRDInputConv.hlsl', CONV/'frozen_shader/FSRDInputConvAdditive.hlsl',
           CONV/'frozen_shader/FSRDAdditiveSplit.hlsli', CONV/'frozen_shader/FSRDPreprocessCommon.hlsli',
           CONV/'frozen_shader/FSRDInputConvAdditive_Shader.cso', CONV/'registration.json']
# Do not silently substitute a missing sample source.
sources = [p for p in sources if p.exists()]
for c in ('C0','C1'):
    sources += [NATIVE/'planned_native'/c/name for name in ('job.txt','frame_controls.txt','dispatch_controls.bin','expected_applied_dispatch_controls.bin','stdout.log')]
sources += [NATIVE/'inputs'/f'input{i}.bin' for i in range(7)]
sources += [CONV/'historical_templates/00'/name for name in ('cb.bin','job.txt')]
clean_rows = [shlex.split(s) for s in (CONV/'planned_jobs/00/clean/job.txt').read_text().splitlines()]
sources += [Path(r[0]) for r in clean_rows[1:18]]
seq = ROOT/'tools_tmp/native_continuous_harmonic_remaining_20260930/evidence/weak_material/sequences.npz'
sources += [seq]
sources = list(dict.fromkeys(sources))
before = [ident(p) for p in sources]
save('source_records_before.json', before)

formats = [41,10,24,28,28,10,10]
names = ['signed_linear_depth','motion_UV_depth_delta','oct_normal_linear_roughness_material','linear_specular_albedo','linear_diffuse_albedo','direct_diffuse_demodulated_signal','indirect_specular_demodulated_signal']
inputs = [read_texture(NATIVE/'inputs'/f'input{i}.bin',fmt) for i,fmt in enumerate(formats)]
input_report = [dict(input=i, name=names[i], DXGI_format=fmt, upload_count=1, channels=stats(a)) for i,(fmt,a) in enumerate(zip(formats, inputs))]
u = np.frombuffer((NATIVE/'inputs/input2.bin').read_bytes(),'<u4')
input_report[2]['distinct_packed_UINT32'] = np.unique(u).tolist()
# Exact local-doc oct decode, in CPU arithmetic. Only descriptive guide orientation.
uv = inputs[2][...,:2]
normal = np.concatenate([uv*2-1, (1-np.abs(uv*2-1).sum(-1))[...,None]],-1)
t = np.maximum(-normal[...,2],0)
normal[...,:2] -= np.where(normal[...,:2]>=0,t[...,None],-t[...,None])
normal /= np.linalg.norm(normal, axis=-1)[...,None]
input_report[2]['decoded_normal_channels'] = stats(normal)
input_report[2]['decoded_normal_single_vector'] = normal[0,0].tolist() if np.all(normal==normal[0,0]) else None

ctrl0 = (NATIVE/'planned_native/C0/dispatch_controls.bin').read_bytes()
ctrl1 = (NATIVE/'planned_native/C1/dispatch_controls.bin').read_bytes()
assert len(ctrl0)==64*184 and ctrl0==ctrl1
packets = [struct.unpack_from('<4I42f',ctrl0,i*184) for i in range(64)]
assert [r[0] for r in packets]==list(range(64))
assert [r[1] for r in packets]==[3]+[2]*63
assert all(r[2:4]==(128,80) for r in packets)
assert all(r[4:]==packets[0][4:] for r in packets)
v = packets[0][4:]
controls = dict(record_bytes=184, records_per_context=64, C0_C1_exact=True, source_indices=list(range(64)),
                flags=[r[1] for r in packets], motionVectorScale=list(v[:3]), cameraPositionDelta=list(v[3:6]),
                jitterOffsets=list(v[6:8]), linearDepthBounds=list(v[8:10]), view=np.array(v[10:26]).reshape(4,4).tolist(),
                projection=np.array(v[26:42]).reshape(4,4).tolist(), all_float_fields_static=True,
                camera_override_present={c:(NATIVE/'planned_native'/c/'camera.txt').exists() for c in ('C0','C1')},
                raw_offsets=dict(frameIndex=0,flags=4,renderSize=8,motionVectorScale=16,cameraPositionDelta=28,jitterOffsets=40,linearDepthBounds=48,view=56,projection=120))
assert all((NATIVE/'planned_native'/c/'expected_applied_dispatch_controls.bin').read_bytes()==ctrl0 for c in ('C0','C1'))
controls['frame_controls_rows'] = [list(map(float,r.split())) for r in (NATIVE/'planned_native/C0/frame_controls.txt').read_text().splitlines()]

cb = (CONV/'historical_templates/00/cb.bin').read_bytes()
assert len(cb)==416
matrices = {name:np.array(struct.unpack_from('<16f',cb,o)).reshape(4,4).tolist() for name,o in [('InvViewMatrix',0),('InvProjMatrix',64),('PrevViewMatrix',128)]}
vectors = {name:list(struct.unpack_from('<4f',cb,o)) for name,o in [('DstTexSize',192),('MotionInputSize',208),('MotionTransform',224),('JitterOffsets',240)]}
vectors.update({f'InputBase{i}':list(struct.unpack_from('<4I',cb,256+16*i)) for i in range(6)})
fields = [('NearPlane',352,'f'),('FarPlane',356,'f'),('FloorDetailPreservation',360,'f'),('Flags',364,'I'),('InspectorChannel',368,'I'),('InspectorScale',372,'f'),('DebugDepthMax',376,'f'),('DiffuseHitDistanceMode',380,'I'),('ResponsivityTrustThreshold',384,'f'),('ResponsivityInvert',388,'I'),('BiasMaskStrength',392,'f'),('DemodDivisorFloor',396,'f'),('SpecularAlbedoDemodulation',400,'f'),('DiffuseAlbedoModulation',404,'f'),('RecoveryMask',408,'I'),('AdditiveLightSplit',412,'f')]
scalars = {name:struct.unpack_from('<'+fmt,cb,o)[0] for name,o,fmt in fields}
cb_static = all((CONV/'historical_templates'/f'{f:02d}/cb.bin').read_bytes()==cb for f in range(64))
cb_report = dict(bytes=416, matrices=matrices,vectors=vectors,scalars=scalars,all64_CB_exact=cb_static,
                 native_view_inverse_matches_converter=bool(np.allclose(np.linalg.inv(np.array(controls['view'])),matrices['InvViewMatrix'],rtol=0,atol=0)),
                 native_projection_inverse_matches_converter=bool(np.allclose(np.linalg.inv(np.array(controls['projection'])),matrices['InvProjMatrix'],rtol=1e-5,atol=1e-5)))
source_guide_report = [dict(SRV=i, DXGI_format=int(row[3]),name=Path(row[0]).name,channels=stats(read_texture(Path(row[0]),int(row[3])))) for i,row in enumerate(clean_rows[1:18]) if i not in (0,16)]
with np.load(seq) as z:
    truth=z['clean_reference']
    truth_report=dict(shape=list(truth.shape),all64_exact_to_frame0=bool(np.all(truth==truth[0])),finite=bool(np.all(np.isfinite(truth))),
                      channels=stats(truth[0]),semantics='Constructed clean_reference array; no model, score or physical oracle claim.')
save('semantic_field_evidence.json',dict(schema='bounded-clean-native-semantic-CPU-inspection',actual_new_native_GPU_build_scores=0,
    input_fields=input_report,controls=controls,converter_CB=cb_report,converter_source_guides=source_guide_report,
    clean_reference=truth_report,api_version=4202496, api_version_components=[1,2,0],
    source_semantics='Actual binary field inspection, not a rerun of any model, converter, native SDK or scorer.'))
after = [ident(p) for p in sources]
assert after==before
save('source_records_after.json',after)
print(json.dumps(dict(status='CPU_FIELD_INSPECTION_COMPLETE',source_records=len(before),actual_new_native_GPU_build_scores=0,
                     controls=controls, converter_CB=cb_report, input_fields=input_report),allow_nan=False))
