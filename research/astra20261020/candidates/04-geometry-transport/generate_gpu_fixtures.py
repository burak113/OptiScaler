"""Export exact inputs/expected CPU outputs for the pending local GPU gate."""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import numpy as np
from experiments import scene
from reconstruction import Policy,certify_cells,local_estimator_support,reconstruct

HERE=Path(__file__).resolve().parent


def run(out,all_phases=False):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    phases=list(np.arange(0,8,.25)) if all_phases else [0.,3.25]
    angles=[0,17,45,90] if all_phases else [0,17]
    records=[]
    for angle in angles:
        for phase in phases:
            field,gain,truth,fg=scene((67,53),angle,float(phase),cell=8)
            default=Policy()
            policy=Policy(cell=8,
                plane_absolute_tolerance=float(np.float32(default.plane_absolute_tolerance)),
                plane_relative_tolerance=float(np.float32(default.plane_relative_tolerance)),
                normal_cosine=float(np.float32(default.normal_cosine)),
                minimum_weight=float(np.float32(default.minimum_weight)))
            cells=certify_cells(field,policy)
            support=local_estimator_support(cells,np.ones_like(cells.valid))
            # Float32 upload is the actual proposed shader input. CPU validation
            # still uses double arithmetic on these values; GPU tolerances apply.
            cells.position=cells.position.astype(np.float32).astype(float)
            cells.normal=cells.normal.astype(np.float32).astype(float)
            cells.depth_scale=cells.depth_scale.astype(np.float32).astype(float)
            field.position=field.position.astype(np.float32).astype(float)
            field.normal=field.normal.astype(np.float32).astype(float)
            gain=gain.astype(np.float32).astype(float)
            result=reconstruct(gain,support,field)
            p=cells.policy
            constants=struct.pack('<6I4f2I',67,53,gain.shape[1],gain.shape[0],8,1,
                p.plane_absolute_tolerance,p.plane_relative_tolerance,p.normal_cosine,p.minimum_weight,0,0)
            assert len(constants)==48
            yy,xx=np.mgrid[:53,:67]
            diffuse=np.empty((53,67,4),np.float16)
            diffuse[...,:3]=(1+.05*np.sin(xx*1.71))[...,None]
            diffuse[...,3]=np.where(fg,2.,5.)
            specular=diffuse.copy();specular[...,:3]*=np.float16(.125)
            specular[...,3]=np.where(fg,4.,12.)
            name=f'apply_angle{angle:03d}_phase{round(float(phase)*100):03d}.npz'
            path=out/name
            np.savez_compressed(path,
                Gain=gain.astype(np.float32),
                CellPointDepth=np.concatenate((cells.position,cells.depth_scale[...,None]),axis=-1).astype(np.float32),
                CellNormalValid=np.concatenate((cells.normal,support.valid[...,None]),axis=-1).astype(np.float32),
                QueryPositionDepth=np.concatenate((field.position,field.depth[...,None]),axis=-1).astype(np.float32),
                QueryNormalEligibility=np.concatenate((field.normal,field.eligible[...,None]),axis=-1).astype(np.float32),
                InOutDiffuse=diffuse,InOutSpecular=specular,
                SupportConstants_bytes=np.frombuffer(constants,np.uint8),
                expected_gain_f64=result.gain,expected_support_mass_f64=result.support_mass,
                expected_contributor_count=result.contributor_count,protected_BASE=fg,
                analytic_truth_gain=truth,active_extent=np.array([67,53],np.uint32))
            records.append({'path':name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                            'bytes':path.stat().st_size,'angle_degrees':angle,'phase_pixels':float(phase)})
    manifest={'scope':'CPU-generated GPU inputs and arithmetic oracle; NO GPU execution',
              'source_shader':'adapter/SupportCertifiedApply.hlsl','entry':'CSMain',
              'support':'exact local-gain synthetic intervention; not native estimator certificate',
              'gpu_executed':False,'files':records,'all_phases':all_phases,
              'scalar_tolerances_from_float32_cb':True,
              'alpha':'legal finite FP16 values; raw word equality required locally',
              'format':'NPZ arrays tightly packed C order; local harness must honor D3D row pitch separately'}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--all-phases',action='store_true');args=parser.parse_args()
    print(json.dumps(run(args.out,args.all_phases),indent=2))
