"""Inventory and source-contract diagnostics, not a new captured key selector."""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
PACKAGE=HERE.parents[1]
sys.path.insert(0,str(PACKAGE/'fixtures/clips'))
from clip_loader import load_clip, previous_coordinates, sample_previous


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def oct_normal(words):
    a=np.asarray(words,dtype=np.uint32)
    x=((a&1023).astype(float)/1023)*2-1
    y=(((a>>10)&1023).astype(float)/1023)*2-1
    z=1-np.abs(x)-np.abs(y)
    xx=np.where(z<0,(1-np.abs(y))*np.where(x>=0,1.,-1.),x)
    yy=np.where(z<0,(1-np.abs(x))*np.where(y>=0,1.,-1.),y)
    n=np.stack((xx,yy,z),axis=-1)
    return n/np.linalg.norm(n,axis=-1,keepdims=True)


def distribution(values):
    a=np.asarray(values,float)
    return {'count':a.size,'mean':float(a.mean()),'p50':float(np.median(a)),
            'p95':float(np.quantile(a,.95)),'max':float(a.max())} if a.size else None


def clip_diagnostic(path):
    arrays,meta=load_clip(path,verify=True)
    ids=arrays['frame_indices']; origins=arrays['crop_origin_render']
    render=arrays['render_extent'].astype(float)
    normals=oct_normal(arrays['input_normal_roughness'])
    depth=arrays['input_depth'].astype(float)
    rows=[]
    for t in range(1,len(ids)):
        qx,qy,valid=previous_coordinates(arrays,t)
        h,w=valid.shape;yy,xx=np.mgrid[:h,:w]
        mv=arrays['input_motion'][t].astype(float)
        delta=origins[t]-origins[t-1]
        roi_x=xx+delta[0]+mv[...,0]*w
        roi_y=yy+delta[1]+mv[...,1]*h
        wrong_scale=np.hypot(roi_x-qx,roi_y-qy)
        no_origin=np.hypot(np.full_like(qx,delta[0]),np.full_like(qy,delta[1]))
        sampled_z,_=sample_previous(depth[t-1],qx,qy)
        sampled_n,_=sample_previous(normals[t-1],qx,qy)
        length=np.linalg.norm(sampled_n,axis=-1)
        unit=np.zeros_like(sampled_n)
        np.divide(sampled_n,length[...,None],out=unit,where=(valid&(length>0))[...,None])
        normal_dot=np.sum(unit*normals[t],axis=-1)
        expected=depth[t]+mv[...,2]
        dz=np.abs(np.abs(sampled_z)-np.abs(expected))
        threshold=.02*np.maximum(np.abs(expected),1e-3)
        mask=valid&np.isfinite(dz)&(np.abs(expected)>1e-5)
        rows.append({'frame':int(ids[t]),'previous_frame':int(ids[t-1]),
                     'crop_origin_render':origins[t].tolist(),
                     'history_inside_previous_crop_fraction':float(valid.mean()),
                     'out_of_crop_clamp_would_manufacture_fraction':float((~valid).mean()),
                     'wrong_ROI_scaling_error_pixels_on_fixed_valid_support':distribution(wrong_scale[valid]),
                     'omitted_origin_error_pixels_on_fixed_valid_support':distribution(no_origin[valid]),
                     'reversed_MV_error_pixels_on_fixed_valid_support':distribution((2*np.linalg.norm(mv[...,:2]*render,axis=-1))[valid]),
                     'documented_depth_delta_consistency_2percent_on_fixed_support':float(np.mean(dz[mask]<=threshold[mask])) if mask.any() else None,
                     'normal_dot_on_fixed_supported_pixels':distribution(normal_dot[valid]),
                     'diagnostic_denominator':int(valid.sum()),'depth_denominator':int(mask.sum())})
    return {'fixture':path.name,'sha256':sha(path),'source_capture_uuid':meta['source_capture_uuid'],
            'source_capture_manifest_sha256':meta['source_capture_manifest_sha256'],
            'frame_indices':ids.tolist(),'render_extent':render.astype(int).tolist(),
            'crop_extent_width_height':[depth.shape[2],depth.shape[1]],
            'origins_render':origins.tolist(),'chronological_unlooped':bool(np.all(np.diff(ids)>0)),
            'first_frame_history_available':False,'albedo_available':False,
            'scope':'documented coordinate consistency; no ground-truth correspondence or key-selection improvement',
            'frame_diagnostics':rows}


def anchor_diagnostic(path):
    with np.load(path,allow_pickle=False) as z:
        stats=z['stats'].astype(float);recalled=z['recalled'].astype(float);gain=z['gain'].astype(float)
        fixed=z['fixed_mask'];frames=z['frames'];ks=z['k']
    moving=stats[...,2]<.5
    missing=recalled[...,1]<.5
    changed=gain<1
    return {'fixture':str(path.relative_to(PACKAGE)),'sha256':sha(path),'frames':frames.tolist(),'k':ks.tolist(),
            'fixed_mask_sha256':hashlib.sha256(np.ascontiguousarray(fixed).tobytes()).hexdigest(),
            'fixed_mask_count':int(fixed.sum()),'moving_centres':int(moving.sum()),
            'changed_moving_centres':int((changed&moving).sum()),
            'missing_own_recall_centres':int(missing.sum()),
            'changed_centres_without_own_recall':int((changed&missing).sum()),
            'raw_six_key_textures_available':False,
            'full_resolution_protected_mask_available':False,
            'scope':'recorded native-policy GPU fields; CPU readback check only, NOT fresh GPU or native bridge execution'}


def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    inventory=[]
    for folder in ('portable/anchor','portable/colour','fixtures/clips','fixtures/glass'):
        for path in sorted((PACKAGE/folder).rglob('*.npz')):
            with np.load(path,allow_pickle=False) as z:
                arrays={key:{'shape':list(z[key].shape),'dtype':z[key].dtype.str,
                             'bytes':z[key].nbytes,'sha256':hashlib.sha256(np.ascontiguousarray(z[key]).tobytes()).hexdigest()}
                        for key in z.files}
            inventory.append({'path':str(path.relative_to(PACKAGE)),'bytes':path.stat().st_size,
                              'sha256':sha(path),'allow_pickle':False,'arrays':arrays})
    result={'npz_inventory':inventory,
            'clips':[clip_diagnostic(p) for p in sorted((PACKAGE/'fixtures/clips').glob('*.npz'))],
            'native_anchor':[anchor_diagnostic(p) for p in sorted((PACKAGE/'portable/anchor/fixtures/native_policy').glob('*.npz'))],
            'limits':{
                'colour':'Frame63 CPU warmup0..62; stored one-frame GPU fields. Original-render UV preserved; not ROI UV. Missing pre-UAV guide low bits.',
                'glass':'Aligned RGB/masks and unwarped original geometry are different coordinate domains; never combine as pixel-aligned guides.',
                'anchor':'Already-recalled fields cannot validate key selection or a support certificate spanning actual keys.',
                'clips':'Partial unlooped history, no albedo, no converged truth, selected RR is baseline recovery.'}}
    (out/'fixture_diagnostics.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=HERE/'evidence')
    args=parser.parse_args();r=run(args.out)
    print(json.dumps({'npz_files':len(r['npz_inventory']),'native_anchor':r['native_anchor'],
                      'clips':[{'fixture':c['fixture'],'frames':len(c['frame_indices']),
                                'history_fraction_mean':float(np.mean([f['history_inside_previous_crop_fraction'] for f in c['frame_diagnostics']]))}
                               for c in r['clips']]},indent=2))
