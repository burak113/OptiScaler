"""Derive a source-only inverse-projection payload control, before execution."""
from pathlib import Path
import hashlib,json
folder=Path(__file__).resolve().parent
source=folder.parent/'source_alpha_contract_20260930/analyze.py';target=folder/'analyze.py'
if target.exists():raise ValueError('Preserve derived control')
text=source.read_text()
changes=(
    ("from fsrd_alpha_common import GPUWorker,convert,rgba", "from fsrd_alpha_common import GPUWorker,convert,rgba\nfrom probe_fsrd_additive_split import write_texture"),
    ("results=dict(schema='source-conversion-ray-alpha-inspection-v1'", "applied=(case/'observed/dispatch_controls.bin').read_bytes()\n    projection=np.frombuffer(applied,dtype='<f4',count=16,offset=120).reshape(4,4)\n    inverse=np.linalg.inv(projection.astype(float)).astype(np.float32)\n    results=dict(schema='matched-camera-source-payload-control-v1'"),
    ("for i in (0,32):", "for i,matched in ((0,False),(0,True),(32,False),(32,True)):"),
    ("overrides=data.get('overrides'),resources=data.get('resources'))", "overrides=({**(data.get('overrides') or {}),'InvProjMatrix':inverse.ravel()} if matched else data.get('overrides')),resources=data.get('resources'))"),
    ("item=dict(frame=i)", "item=dict(frame=i,matched_inverse_projection=matched,native_input_sha256={})\n            arrays=[data['depth'],p[2],p[3],p[4],p[5],p[1],p[0]]\n            for slot,(array,fmt) in enumerate(zip(arrays,[41,10,24,28,28,10,10])):\n                path=out/f'frame_{i}_matched_{int(matched)}_input{slot}.bin'\n                write_texture(path,array,fmt);item['native_input_sha256'][str(slot)]=sha(path)"),
    ("f'packed_frame_{i}.npz'", "f'packed_frame_{i}_matched_{int(matched)}.npz'"),
    ("results['status']='completed_input_inspection_not_cause_or_solution'", "results['native_projection_sha256']=hashlib.sha256(projection.tobytes()).hexdigest()\n    results['inverse_projection']=inverse.ravel().tolist()\n    results['comparisons']=[]\n    for i in (0,32):\n        old=next(v for v in results['frames'] if v['frame']==i and not v['matched_inverse_projection'])\n        new=next(v for v in results['frames'] if v['frame']==i and v['matched_inverse_projection'])\n        results['comparisons'].append(dict(frame=i,all_seven_input_hashes_equal=old['native_input_sha256']==new['native_input_sha256'],differing_slots=[k for k in old['native_input_sha256'] if old['native_input_sha256'][k]!=new['native_input_sha256'][k]]))\n    results['status']='completed_input_control_not_native_quality'"),
    ("print(json.dumps(results['frames']))", "print(json.dumps(results['comparisons']))"),
)
for old,new in changes:
    if text.count(old)!=1:raise ValueError('Ambiguous source control anchor')
    text=text.replace(old,new,1)
target.write_text(text,encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
(folder/'source_derivation.json').write_text(json.dumps(dict(source=str(source),source_sha256=sha(source),generated_sha256=sha(target),
    generator_sha256=sha(Path(__file__)),control='Only conversion inverse projection uses inverse of actual native dispatch projection; frames0/32, exactseveninputhashes'),indent=2)+'\n')
