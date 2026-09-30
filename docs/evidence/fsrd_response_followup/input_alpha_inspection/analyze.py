"""Inspect frozen-source conversion ray channels; no new native RR dispatch."""
from pathlib import Path
import ast,hashlib,json,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2];TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests';sys.path.insert(0,str(TESTS))
from fsrd_alpha_common import GPUWorker,convert,rgba
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
    results=dict(schema='source-conversion-ray-alpha-inspection-v1',native_dispatches=0,quality_accepted=False,
        script_sha256=sha(__file__),reference_report_sha256=rh,source_array_sha256=sh,fixture_source_sha256=frozen,frames=[])
    with GPUWorker(out):
        for i in (0,32):
            p=convert(rgba(observed[i]),data['diff'][i],data['spec'][i],1,depth=data['depth'],normals=data['normals'],roughness=data['roughness'],
                motion=data.get('motion',[None]*len(observed))[i],overrides=data.get('overrides'),resources=data.get('resources'))
            item=dict(frame=i)
            for name,v in (('specular',p[0]),('diffuse',p[1])):
                item[name]=dict(input_alpha_min=float(v[...,3].min()),input_alpha_max=float(v[...,3].max()),
                    positive_fraction=float(np.mean(v[...,3]>0)),negative_fraction=float(np.mean(v[...,3]<0)),
                    finite=bool(np.isfinite(v).all()),rgba_fp16_sha256=hashlib.sha256(v.astype('<f2').tobytes()).hexdigest())
            payload=out/f'packed_frame_{i}.npz';np.savez_compressed(payload,specular=p[0],diffuse=p[1])
            item['payload_sha256']=sha(payload);results['frames'].append(item)
    if sha(rp)!=rh or sha(sp)!=sh:raise ValueError('Reference evidence changed')
    results['status']='completed_input_inspection_not_cause_or_solution'
    (out/'results.json').write_text(json.dumps(results,indent=2,allow_nan=False)+'\n')
    print(json.dumps(results['frames']))
if __name__=='__main__':main()
