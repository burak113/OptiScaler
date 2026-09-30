"""Bounded local SDK/sample/packing contract read and CPU oct algebra only."""
import hashlib,json,re
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sdk=ROOT/'external/FidelityFX-SDK-v2'
sample=sdk/'samples/Denoisers/FidelityFX_Denoiser/dx12'
pre=ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile'
paths=dict(header=sdk/'Kits/FidelityFX/denoisers/include/ffx_denoiser.h',docs=sdk/'Kits/FidelityFX/docs/techniques/denoising.md',
    sample_common=sample/'shaders/common.hlsl',sample_trace=sample/'shaders/trace_rays_denoiser.hlsl',sample_config=sample/'config/denoiserconfig.json',
    local_common=pre/'FSRDPreprocessCommon.hlsli',local_conversion=pre/'FSRDInputConv.hlsl',
    local_packing=ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
texts={k:p.read_text() for k,p in paths.items()}
def body(text,name):
    start=text.index(name+'(');opening=text.index('{',start);depth=1;i=opening+1
    while depth:
        if text[i]=='{':depth+=1
        elif text[i]=='}':depth-=1
        i+=1
    return text[opening+1:i-1]
def canonical(text):return re.sub(r'\s+','',re.sub(r'//[^\n]*','',text))
assert canonical(body(texts['sample_common'],'NormalToOctahedronUv'))==canonical(body(texts['local_common'],'OctahedralEncode'))
assert canonical(body(texts['sample_common'],'OctahedronUvToNormal'))==canonical(body(texts['local_common'],'OctahedralDecode'))
assert '* RG:  Octahedrally encoded normals' in texts['header']
assert 'Preferred format: `RGB10A2_UNORM`' in texts['docs']
config=json.loads(texts['sample_config'])['FSR Ray Regeneration']['RenderResources'];assert config['NormalsResource']['Format']=='RGB10A2_UNORM'
assert 'NormalToOctahedronUv(primaryHit.worldNormal), roughness, 0.0f' in texts['sample_trace']
assert 'Normals = DXGI_FORMAT_R10G10B10A2_UNORM' in texts['local_packing']
assert 'OutNormals[FSRD_OUTPUT_PIXEL(px)] = GetSafeFP16(float4(octNormal, roughness, materialType));' in texts['local_conversion']
def normalized(n):return n/np.linalg.norm(n)
def sample_encode(n):
    n=np.asarray(n,float).copy();xy=n[:2]/sum(abs(n));k=np.where(xy>0,1.,-1.)
    if n[2]<0:xy=(1-abs(xy[::-1]))*k
    return xy*.5+.5
def sample_decode(uv):
    xy=2*np.asarray(uv,float)-1;n=np.r_[xy,1-sum(abs(xy))];t=max(-n[2],0)
    n[:2]+=np.where(n[:2]>=0,-t,t)
    return normalized(n)
doc_encoder=body(texts['docs'],'NormalToOctahedronUv');doc_decoder=body(texts['docs'],'OctahedronUvToNormal')
assert 'float2 k = sign(N.xy);' in doc_encoder and 'float s = saturate(-N.z);' in doc_encoder
assert 'N.xy = lerp(N.xy, (1.0 - abs(N.yx)) * k, s);' in doc_encoder
assert 'float2 s = sign(N.xy);' in doc_decoder and 'N.xy += s * t;' in doc_decoder
def docs_encode(n):
    n=np.asarray(n,float);xy=n[:2]/sum(abs(n));k=np.sign(xy);s=np.clip(-n[2],0,1)
    return ((1-s)*xy+s*(1-abs(xy[::-1]))*k)*.5+.5
def docs_decode(uv):
    xy=2*np.asarray(uv,float)-1;n=np.r_[xy,1-sum(abs(xy))];t=np.clip(-n[2],0,1)
    n[:2]+=np.sign(n[:2])*t
    return normalized(n)
negative_z=np.array([0.,0.,-1.]);doc_uv=docs_encode(negative_z);doc_n=docs_decode(doc_uv)
np.testing.assert_array_equal(doc_uv,[.5,.5]);np.testing.assert_array_equal(doc_n,[0,0,1])
examples=[]
for uv in ((0,0),(0,1),(1,0),(1,1)):
    n=sample_decode(uv);np.testing.assert_array_equal(n,negative_z)
    examples.append(dict(UV=list(uv),local_and_sample_decode=n.tolist(),packaged_documentation_decode=docs_decode(uv).tolist()))
up=np.array([0.,1.,0.]);np.testing.assert_array_equal(sample_encode(up),[.5,1])
low=sample_decode((511/1023,1));high=sample_decode((512/1023,1));np.testing.assert_allclose(low,high,rtol=0,atol=1e-15)
up_error=float(np.arccos(np.clip(low@up,-1,1)))
record=dict(schema='local-sdk-normal-unorm-oct-contract-review-v1',CPU_only=True,new_GPU_calls=0,native_RR_dispatches=0,quality_accepted=False,
    analysis_sha256=sha(__file__),sources=[dict(name=k,path=str(p),sha256=sha(p)) for k,p in paths.items()],
    input_contract=dict(header='RG octahedral normal, B linear roughness, A material type.',preferred_format='RGB10A2_UNORM in local SDK docs; sample config and production use it.',
        world_space_evidence='Sample trace encodes primaryHit.worldNormal; local conversion transforms view-space normals using InvView then encodes world normal.',
        UNORM='Oct UV lies in[0,1]. R/G/B use10-bit UNORM, A uses2-bit material fraction. Exact0 and1 endpoints are representable.',
        local_storage='Shader emits half4(GetSafeFP16(octUV,roughness,materialType)) into R10G10B10A2_UNORM. CPU/production probe decodes bits0-9,10-19,20-29,30-31.'),
    sample_and_local_encoder_bodies_equivalent=True,sample_and_local_decoder_bodies_equivalent=True,
    corner_examples=examples,canonical_sample_encode_minusZ=sample_encode(negative_z).tolist(),
    documentation_example_inconsistency=dict(section='Local packaged denoising.md §5.3.1/5.3.2',exact_minusZ_documented_encode=doc_uv.tolist(),documented_decode_of_documented_encode=doc_n.tolist(),
        document_encoder_uses_sign_zero_and_fractional_negative_Z_lerp=True,document_decoder_adds_sign_times_fold_instead_of_sample_opposite_sign_fold=True,
        meaning='The displayed documentation examples fail a unit-normal encode/decode round trip. The header and sample oct contract is not proven invalid; native DLL implementation is unavailable.'),
    world_positiveY_R10_edge=dict(ideal_UV=[.5,1],midpoint_not_exactly_representable_on_10bit_grid=True,
        equivalent_neighbor_UVs=[[511/1023,1],[512/1023,1]],decoded_normal=low.tolist(),equivalent_to_each_other=True,angle_to_ideal_positiveY_radians=up_error),
    diagnostic_limits=['Equivalent local/sample decoded normals do not establish provider encoder-invariance. A native controlled-input comparison would change encoded bytes and must preserve all other resources/control settings.',
        'No SDK header restriction excluding0/1 endpoints or requiring one unique equivalent corner representation was found in this bounded local read.',
        'The provider may have unavailable implementation details; packaged documentation-code inconsistency is not evidence of provider behavior or old same-input variability cause.',
        'No game normal orientation, fresh alpha game quality or stain/wave solution is claimed.'])
out=HERE/'normal_contract_review.json';assert not out.exists();out.write_text(json.dumps(record,indent=2)+'\n')
print('normal_contract_review_sha256',sha(out));print('up_R10_angle',up_error)
