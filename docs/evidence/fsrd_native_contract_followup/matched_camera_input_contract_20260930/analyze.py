"""Inspect frozen-source conversion ray channels; no new native RR dispatch."""
from pathlib import Path
import ast,hashlib,json,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2];TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests';sys.path.insert(0,str(TESTS))
from fsrd_alpha_common import GPUWorker,convert,rgba
from probe_fsrd_additive_split import write_texture
REFERENCE=Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce/response_soft_temporal_long_alpha_fresh')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    folder=Path(__file__).resolve().parent;out=folder/'evidence'
    if out.exists():raise ValueError('Preserve previous source inspection')
    out.mkdir();rp=REFERENCE/'results.json';report=json.loads(rp.read_text());rh=sha(rp);ns={'np':np};frozen={}
    for file,name in (('fsrd_alpha_common.py','rgba'),('probe_fsrd_statistical_resolve.py','fixture'),('probe_fsrd_response_calibration.py','research_fixture')):
        path=REFERENCE/'source_snapshot'/file;frozen[file]=sha(path)
        if frozen[file]!=report['source_sha256'][file]:raise ValueError('Frozen source SHA mismatch')
        node=next(v for v in ast.parse(path.read_text()).body if isinstance(v,ast.FunctionDef) and v.name==name)
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),ns)
    row=next(r for r in report['rows'] if r['scene']=='lighting_step');case=Path(row['evidence_directory']);sp=case/'sequences.npz';sh=sha(sp)
    with np.load(sp) as a:observed=a['observed'].copy()
    w,h=report['size'];data=ns['research_fixture']('lighting_step',w,h,report['frames'],report['seed'])
    applied=(case/'observed/dispatch_controls.bin').read_bytes()
    projection=np.frombuffer(applied,dtype='<f4',count=16,offset=120).reshape(4,4)
    inverse=np.linalg.inv(projection.astype(float)).astype(np.float32)
    results=dict(schema='matched-camera-source-payload-control-v1',native_dispatches=0,quality_accepted=False,
        script_sha256=sha(__file__),reference_report_sha256=rh,source_array_sha256=sh,fixture_source_sha256=frozen,frames=[])
    with GPUWorker(out):
        for i,matched in ((0,False),(0,True),(32,False),(32,True)):
            p=convert(rgba(observed[i]),data['diff'][i],data['spec'][i],1,depth=data['depth'],normals=data['normals'],roughness=data['roughness'],
                motion=data.get('motion',[None]*len(observed))[i],overrides=({**(data.get('overrides') or {}),'InvProjMatrix':inverse.ravel()} if matched else data.get('overrides')),resources=data.get('resources'))
            item=dict(frame=i,matched_inverse_projection=matched,native_input_sha256={})
            arrays=[data['depth'],p[2],p[3],p[4],p[5],p[1],p[0]]
            for slot,(array,fmt) in enumerate(zip(arrays,[41,10,24,28,28,10,10])):
                path=out/f'frame_{i}_matched_{int(matched)}_input{slot}.bin'
                write_texture(path,array,fmt);item['native_input_sha256'][str(slot)]=sha(path)
            for name,v in (('specular',p[0]),('diffuse',p[1])):
                item[name]=dict(input_alpha_min=float(v[...,3].min()),input_alpha_max=float(v[...,3].max()),
                    positive_fraction=float(np.mean(v[...,3]>0)),negative_fraction=float(np.mean(v[...,3]<0)),
                    finite=bool(np.isfinite(v).all()),rgba_fp16_sha256=hashlib.sha256(v.astype('<f2').tobytes()).hexdigest())
            payload=out/f'packed_frame_{i}_matched_{int(matched)}.npz';np.savez_compressed(payload,specular=p[0],diffuse=p[1])
            item['payload_sha256']=sha(payload);results['frames'].append(item)
    if sha(rp)!=rh or sha(sp)!=sh:raise ValueError('Reference evidence changed')
    results['native_projection_sha256']=hashlib.sha256(projection.tobytes()).hexdigest()
    results['inverse_projection']=inverse.ravel().tolist()
    results['comparisons']=[]
    for i in (0,32):
        old=next(v for v in results['frames'] if v['frame']==i and not v['matched_inverse_projection'])
        new=next(v for v in results['frames'] if v['frame']==i and v['matched_inverse_projection'])
        results['comparisons'].append(dict(frame=i,all_seven_input_hashes_equal=old['native_input_sha256']==new['native_input_sha256'],differing_slots=[k for k in old['native_input_sha256'] if old['native_input_sha256'][k]!=new['native_input_sha256'][k]]))
    results['status']='completed_input_control_not_native_quality'
    (out/'results.json').write_text(json.dumps(results,indent=2,allow_nan=False)+'\n')
    print(json.dumps(results['comparisons']))
if __name__=='__main__':main()
