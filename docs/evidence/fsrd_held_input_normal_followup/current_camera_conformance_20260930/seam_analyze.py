"""Exact octahedral seam algebra from local HLSL; no GPU/native calls."""
import hashlib,json,re
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
shader=ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile/FSRDPreprocessCommon.hlsli'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
text=shader.read_text()
start=text.index('float3 OctahedralDecode(float2 UV)');end=text.index('\n}\n',start)+3
decoder=text[start:end]
for token in ('UV = 2.0f * (UV - 0.5f);','float3 N = float3(UV, 1.0f - abs(UV.x) - abs(UV.y));','float t = max(-N.z, 0.0f);','N.x >= 0.0f ? -t : t','N.y >= 0.0f ? -t : t','N.xy += k;','return normalize(N);'):
    assert token in decoder
def local_shader_decode(uv):
    uv=2*(np.asarray(uv,float)-.5)
    n=np.array([uv[0],uv[1],1-abs(uv[0])-abs(uv[1])])
    t=max(-n[2],0.)
    k=np.array([-t if n[0]>=0 else t,-t if n[1]>=0 else t])
    n[:2]+=k
    return n/np.linalg.norm(n)
corners=[]
for uv in ((0.,0.),(0.,1.),(1.,0.),(1.,1.)):
    n=local_shader_decode(uv);np.testing.assert_array_equal(n,[0.,0.,-1.])
    corners.append(dict(oct_UV=list(uv),decoded_world_normal=n.tolist(),exact_minus_Z=True))
up=local_shader_decode((.5,1.));down=local_shader_decode((.5,0.))
np.testing.assert_array_equal(up,[0.,1.,0.]);np.testing.assert_array_equal(down,[0.,-1.,0.])
pairs=[]
for u in (.125,.25,.375):
    a=local_shader_decode((u,1));b=local_shader_decode((1-u,1));np.testing.assert_array_equal(a,b)
    assert a[0]==0 and a[1]>0 and a[2]<0
    pairs.append(dict(first_UV=[u,1],second_UV=[1-u,1],decoded_world_normal=a.tolist(),exact_equal=True))
notes=dict(schema='local-octahedral-seam-exact-algebra-v1',analysis_sha256=sha(__file__),shader_path=str(shader),shader_sha256=sha(shader),
    decoder_source=decoder,CPU_only=True,GPU_calls=0,native_dispatches=0,quality_accepted=False,
    exact_four_corners=corners,world_positive_Y=dict(canonical_UV=[.5,1.],decoded=up.tolist(),on_top_atlas_edge=True,
        qualification='The exact +Y direction is the top-edge midpoint; the entire top edge is not +Y. Mirrored top-edge pairs encode equal x=0,y>0,z<0 normals.'),
    world_negative_Y=dict(canonical_UV=[.5,0.],decoded=down.tolist()),mirrored_top_edge_equivalent_pairs=pairs,
    local_encoder_boundary='OctahedralEncode chooses k.x/y using strict >0. At exact -Z with x=y=0 it chooses UV(0,0). Current-camera world-YRotation view normal is rounded to FP16 before InvView; compare decoded 3D normals rather than ideal raw UV equality.',
    implications=['All four exact atlas corners are valid equivalent decoded -Z under this local decoder. This is a mathematically defined input-equivalence diagnostic lead, not measured native provider invariance.',
        'For world-up Y, the top-edge midpoint and mirrored neighboring edge encodings require 3D angular interpretation. Near -Z, equivalent corner encodings can be far apart in raw UV despite identical decoded normals.',
        'Typical water-normal orientation is not a measured property of this new fixture or a fresh alpha game capture; this only records the +Y algebra.',
        'No cause of old same-input context variation is claimed: changing oct representation would change input bytes and requires a separate controlled native study.'])
out=HERE/'seam_notes.json';assert not out.exists();out.write_text(json.dumps(notes,indent=2)+'\n')
print('seam_notes_sha256',sha(out))
