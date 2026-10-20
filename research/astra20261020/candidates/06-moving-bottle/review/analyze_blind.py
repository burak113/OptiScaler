"""Independent blind measurements; does not import candidate code or labels."""
from pathlib import Path
import hashlib
import json
import numpy as np

HERE = Path(__file__).resolve().parent
PUBLIC = HERE.parent / 'evidence/blind_public'


def bilinear(image, q):
    h, w = image.shape[:2]
    x, y = q[..., 0], q[..., 1]
    valid = np.isfinite(q).all(-1) & (x >= 0) & (y >= 0) & (x < w-1) & (y < h-1)
    value = np.full(q.shape[:-1]+image.shape[2:], np.nan, dtype=np.float64)
    xv, yv = x[valid], y[valid]
    ix, iy = np.floor(xv).astype(int), np.floor(yv).astype(int)
    fx, fy = xv-ix, yv-iy
    tail = (1,)*(image.ndim-2)
    fx, fy = fx.reshape((-1,)+tail), fy.reshape((-1,)+tail)
    value[valid] = (image[iy,ix]*(1-fx)*(1-fy)+image[iy,ix+1]*fx*(1-fy)
                    +image[iy+1,ix]*(1-fx)*fy+image[iy+1,ix+1]*fx*fy)
    return value, valid


def correspondence(a, field, motion, fixed):
    if field not in a:
        return None
    identity, mv = a[field], a[motion]
    n, h, w = mv.shape[:3]
    yy, xx = np.mgrid[:h,:w]
    pixel = np.stack((xx,yy),axis=-1)
    rows=[]
    all_errors=[]
    for t in range(1,n):
        q=pixel+a['crop_origins'][t]-a['crop_origins'][t-1]+mv[t,...,:2].astype(np.float64)*a['render_extent']
        warped,valid=bilinear(identity[t-1],q)
        base=a[fixed][t]
        use=base&valid
        # Invalid samples retain their original denominator in separate support counts.
        delta=warped[use]-identity[t][use]
        errors=np.linalg.norm(delta[...,:2],axis=-1)
        all_errors.extend(errors.tolist())
        rows.append({'frame':int(a['frame_indices'][t]),'base_count':int(base.sum()),'valid_count':int(use.sum()),
                     'mean_error':float(errors.mean()) if len(errors) else None,
                     'p90_error':float(np.quantile(errors,.9)) if len(errors) else None,
                     'mean_delta_xy':delta[...,:2].mean(axis=0).tolist() if len(errors) else None,
                     'max_id_error':float(np.max(np.abs(delta[...,2]))) if len(errors) else None})
    return {'mean_error_pixels':float(np.mean(all_errors)) if all_errors else None,
            'p90_error_pixels':float(np.quantile(all_errors,.9)) if all_errors else None,'frames':rows}


def rigid_object_residual(a):
    """Recover screen correspondences independently from analytic local identities.

    This witness is deliberately unavailable for captured game fixtures. A rigid
    analytic bottle has an affine local-to-screen map; solve that map using the
    previous frame, then evaluate supplied motion without sampling across IDs.
    """
    if 'surface_identity' not in a:
        return None
    s=a['support_truth']; identity=a['surface_identity']; origins=a['crop_origins']
    h,w=s.shape[1:]; yy,xx=np.mgrid[:h,:w]; pixels=np.stack((xx,yy),-1)
    rows=[]
    for t in range(1,len(s)):
        previous=s[t-1]; current=a['fixed_geometry_mask'][t]
        if previous.sum()<4 or not current.any():
            continue
        features=np.concatenate([identity[t-1][previous,:2],np.ones((previous.sum(),1))],axis=-1)
        if np.linalg.matrix_rank(features)<3:
            continue
        fit=np.linalg.lstsq(features,pixels[previous]+origins[t-1],rcond=None)[0]
        current_id=np.concatenate([identity[t][current,:2],np.ones((current.sum(),1))],axis=-1)
        expected=current_id@fit
        observed=pixels[current]+origins[t]+a['motion_uv'][t][current,:2]*a['render_extent']
        residual=observed-expected
        rows.append({'frame':int(a['frame_indices'][t]),'mean_delta_render_pixels':residual.mean(0).tolist(),
                     'spread_pixels':residual.std(0).tolist(),'count':int(current.sum())})
    return rows


def main():
    manifest=json.loads((PUBLIC/'manifest.json').read_text())
    output=[]
    for item in manifest['cases']:
        path=PUBLIC/item['file']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
        with np.load(path,allow_pickle=False) as z:
            a={k:z[k] for k in z.files}
        assert np.all(np.diff(a['frame_indices'])==1)
        record={'case_id':item['case_id'],'sha256':item['sha256'],'guide_authority':bool(a['guide_authority']),
                'surface':correspondence(a,'surface_identity','motion_uv','fixed_geometry_mask'),
                'virtual':correspondence(a,'virtual_identity','virtual_motion_uv','fixed_virtual_mask'),
                'rigid_geometry_motion_residual':rigid_object_residual(a),
                'zero_hit_fraction':float(np.mean(a['hit_distance']==0)), 'stage_changes':{}}
        s=a.get('support_truth')
        for first,second in [('raw','raw_rr'),('raw_rr','selected'),('raw_specular','raw_rr_specular'),('raw_rr_specular','selected_specular')]:
            x,y=a[first],a[second]
            pos=x>0
            ratios=y[pos]/x[pos]
            record['stage_changes'][first+'->'+second]={
                'changed_pixels':int(np.count_nonzero(x!=y)),
                'mean_absolute_difference':float(np.abs(x-y).mean()),
                'positive_pixel_ratio_quantiles':np.quantile(ratios,[0,.5,1]).tolist(),
                'output_energy_outside_truth':float(y[~s].sum()) if s is not None else None,
                'changed_support_threshold_0_25':int(np.count_nonzero((x>.25)!=(y>.25))),
            }
        if s is not None:
            raw=a['raw']
            record['source']={'outside_truth_energy':float(raw[~s].sum()),
                              'total_energy':float(raw.sum()),
                              'inside_zero_fraction':float(np.mean(raw[s]==0)),
                              'outside_nonzero_pixels':int(np.count_nonzero(raw[~s])),
                              'frame_outside_energy':[float(raw[t][~s[t]].sum()) for t in range(len(s))]}
        output.append(record)
    result={'executor':'independent_skeptical_reviewer','candidate_implementation_imported':False,
            'truth_key_viewed':False,'cpu_model_only':True,'cases':output}
    (HERE/'blind_measurements.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    for r in output:
        print(json.dumps({'case':r['case_id'],
            'surface_error':None if r['surface'] is None else r['surface']['mean_error_pixels'],
            'virtual_error':None if r['virtual'] is None else r['virtual']['mean_error_pixels'],
            'source_outside_energy':r.get('source',{}).get('outside_truth_energy'),
            'changed_stages':[k for k,v in r['stage_changes'].items() if v['changed_pixels']]}))


if __name__=='__main__':
    main()
