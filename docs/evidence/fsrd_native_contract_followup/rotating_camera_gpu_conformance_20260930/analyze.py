"""Four conversion dispatches against the independently specified camera fixture."""
from pathlib import Path
import hashlib,json,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2];TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests';sys.path.insert(0,str(TESTS))
from fsrd_alpha_common import GPUWorker,convert,shader_identity
import run_fsrd_gpu_tests as t
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stats(a,b):
    d=np.asarray(a,dtype=float)-b
    return dict(rms=float(np.sqrt(np.mean(d*d))),maximum_absolute=float(abs(d).max()),exact_equal=bool(np.array_equal(a,b)))
def half_tolerance(a):
    a=np.asarray(a,dtype=np.float16)
    ulp=np.maximum(abs(np.nextafter(a,np.float16(np.inf)).astype(float)-a),abs(a.astype(float)-np.nextafter(a,np.float16(-np.inf)).astype(float)))
    return ulp+1e-5
def main():
    folder=Path(__file__).resolve().parent;out=folder/'evidence'
    if out.exists():raise ValueError('Preserve GPU camera conformance')
    out.mkdir();cpu=ROOT/'tools_tmp/rotating_camera_conformance_20260930';rp=cpu/'results.json';rh=sha(rp);report=json.loads(rp.read_text())
    identity=shader_identity(t.PRE)
    result=dict(schema='rotating-camera-four-conversion-gpu-conformance-v1',status='running',quality_accepted=False,native_dispatches=0,
        script_sha256=sha(__file__),CPU_reference_sha256=rh,production_shader_identity=identity,conversion_dispatches=0,rows=[])
    def save():(out/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    save();retained={}
    with GPUWorker(out):
        for row in report['payloads']:
            if row['roughness']!=.1:continue
            path=Path(row['path'])
            if sha(path)!=row['sha256']:raise ValueError('CPU fixture payload changed')
            with np.load(path) as f:data={k:f[k].copy() for k in f.files}
            for strength in (0,1):
                packed=convert(data['raw'],data['diff'],data['spec'],strength,depth=data['depth'],normals=data['normals'],
                    roughness=data['roughness'],motion=data['motion'],overrides=row['overrides'],kernel='auto',directory=t.PRE)
                arm='matched' if row['matched_inverse_projection'] else 'identity';key=f'{arm}_strength{strength}'
                target=out/(key+'.npz');np.savez_compressed(target,**{f'packed_{i}':v for i,v in enumerate(packed)})
                expected=data['expected_converter_motion_fp16'].astype(float)
                motion=packed[2];tol=half_tolerance(expected)
                check=np.all(abs(motion-expected)<=tol)
                physical=data['expected_physical_mvz'];physical_check=np.all(abs(motion[...,2]-physical)<=half_tolerance(physical))
                normals=data['expected_normal_before_storage']
                normal_check=bool(np.all(abs(packed[3]-normals)<=1/1023+1e-4))
                entry=dict(arm=arm,strength=strength,fixture_sha256=row['sha256'],overrides=row['overrides'],
                    actual_shader='FSRDInputConv' if strength==0 else 'FSRDInputConvAdditive',payload_sha256=sha(target),
                    expected_converter_motion=stats(motion,expected),all_pixel_motion_within_one_ulp_plus_1e5=bool(check),
                    physical_mvz=stats(motion[...,2],physical),all_pixel_physical_mvz_within_tolerance=bool(physical_check),
                    primary_motion_xy=stats(motion[...,:2],data['motion'][...,:2].astype(np.float16).astype(float)),
                    motion_alpha_exact_one=bool(np.all(motion[...,3]==1)),normal_roughness_material_within_tolerance=normal_check,
                    spec_alpha_min=float(packed[0][...,3].min()),spec_alpha_max=float(packed[0][...,3].max()),
                    diffuse_alpha_min=float(packed[1][...,3].min()),diffuse_alpha_max=float(packed[1][...,3].max()))
                result['rows'].append(entry);result['conversion_dispatches']+=1;retained[key]=packed;save()
                print(key,check,physical_check,entry['physical_mvz'],flush=True)
    result['comparisons']=[]
    for strength in (0,1):
        a=retained[f'matched_strength{strength}'];b=retained[f'identity_strength{strength}']
        result['comparisons'].append(dict(strength=strength,motion_xy=stats(a[2][...,:2],b[2][...,:2]),motion_z=stats(a[2][...,2],b[2][...,2]),
            normal_roughness_material=stats(a[3],b[3]),specular_input_rgb=stats(a[0][...,:3],b[0][...,:3]),diffuse_input_rgb=stats(a[1][...,:3],b[1][...,:3])))
    if sha(rp)!=rh or shader_identity(t.PRE)!=identity:raise ValueError('Reference/production shader changed')
    result['status']='completed_conversion_conformance_not_solution';save()
if __name__=='__main__':main()
