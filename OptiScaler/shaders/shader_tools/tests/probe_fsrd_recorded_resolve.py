"""Historical same-frame predictive probe. No clean truth, AMD replay or promotion.

These captures used JointFieldV1, not the current alpha Legacy path. A fit to their
noisy observations cannot establish that their faint blotch was corrected.
"""
from pathlib import Path
import argparse,hashlib,json
import numpy as np
from fsrd_statistical_resolve import resolve
from fsrd_alpha_common import save_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--captures',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    if (a.output/'results.json').exists(): raise ValueError('Use fresh output directory')
    report=dict(scope=__doc__,quality_accepted=False,results=[])
    for folder in a.captures:
        folder=folder.resolve();manifest=json.loads((folder/'capture.json').read_text())
        if not manifest['settings']['conversion_flags']&4: raise ValueError('Source roughness is not declared packed')
        arrays={};hashes={}
        for name in ('raw_rgba','source_diffuse_albedo','source_specular_albedo','source_normals','rr_linear_depth','composition_production'):
            record=next(i for i in manifest['images'] if i['name']==name)
            path=(folder/record['file']).resolve()
            if path.parent!=folder: raise ValueError('Unexpected payload path')
            blob=path.read_bytes();digest=hashlib.sha256(blob).hexdigest()
            if digest!=record['sha256'] or record['channels']!=4 or len(blob)!=record['width']*record['height']*16:
                raise ValueError('Payload integrity failure')
            arr=np.frombuffer(blob,'<f4').reshape(record['height'],record['width'],4)
            if not np.isfinite(arr).all(): raise ValueError('Invalid source')
            arrays[name]=arr[:112,:112].copy();hashes[name]=digest
        raw=arrays['raw_rgba'][...,:3];base=arrays['composition_production'][...,:3]
        guides=[arrays['source_diffuse_albedo'][...,:3],arrays['source_specular_albedo'][...,:3]]
        normal=arrays['source_normals'];depth=arrays['rr_linear_depth'][...,0]
        roi=np.s_[25:85,5:85,:]
        variants={};saved=dict(raw=raw,legacy_historical_joint=base)
        for name,features in (('guide_only',guides),('same_frame_rr',guides+[base])):
            out,diag=resolve(raw,np.stack(features,-1),base,depth,normal[...,:3],normal[...,3],require_independence=False)
            saved[name]=out
            difference=out-base
            variants[name]=dict(activity_rgb=np.mean(abs(difference[roi])>1e-5,axis=(0,1)).tolist(),
                signed_correction_rgb=difference[roi].mean((0,1)).tolist(),
                noisy_observation_rmse_rgb=np.sqrt(np.mean((raw[roi]-out[roi])**2,axis=(0,1))).tolist(),
                baseline_observation_rmse_rgb=np.sqrt(np.mean((raw[roi]-base[roi])**2,axis=(0,1))).tolist(),
                confidence_rgb=diag['confidence'][roi].mean((0,1)).tolist(),
                warning='Predictive observation score, not clean-reference quality; same-source feature noise can leak.')
            np.savez_compressed(a.output/(folder.name+'_'+name+'_fit.npz'),**{k:v for k,v in diag.items() if isinstance(v,np.ndarray)})
        np.savez_compressed(a.output/(folder.name+'_images.npz'),**saved)
        row=dict(capture=folder.name,original_settings=manifest['settings'],payload_sha256=hashes,
            roi_xyxy=[5,25,85,85],models=variants)
        report['results'].append(row);save_json(a.output/'results.json',report)
        print(folder.name,variants,flush=True)


if __name__=='__main__': main()
