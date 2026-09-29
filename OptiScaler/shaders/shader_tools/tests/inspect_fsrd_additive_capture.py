"""Verify and summarize an additive channel capture without altering its evidence.

python inspect_fsrd_additive_capture.py --capture <RRTrace/additive_...> --output <new-folder>
"""
from pathlib import Path
import argparse, hashlib, json
import numpy as np
from fsrd_additive_diagnostics import FIELDS, REASONS, summarize
from fsrd_alpha_common import save_json

LIVE_FIELDS=FIELDS+('source_diffuse','source_specular','source_normal','source_roughness',
                    'linear_depth','source_motion','stored_specular','stored_diffuse')


def read_live(folder):
    folder=Path(folder).resolve()
    metadata=json.loads((folder/'capture.json').read_text(encoding='utf-8'))
    if metadata['schema'] not in ('fsrd-additive-live-v1','fsrd-additive-live-v2'):
        raise ValueError('Unsupported capture schema')
    paired=metadata['schema']=='fsrd-additive-live-v2'
    if paired:
        p=metadata['paired']
        for key,count in (('view',16),('projection',16),('jitter',2),('motion_scale',3),
                          ('camera_delta',3),('linear_depth_bounds',2),('composition_controls',7)):
            a=np.asarray(p[key],float)
            if a.shape!=(count,) or not np.isfinite(a).all(): raise ValueError('Invalid paired '+key)
        if not np.isfinite(p['pre_exposure']) or p['pre_exposure']<=0:
            raise ValueError('Invalid paired pre-exposure')
        if type(p['frame_index']) is not int or not 0<=p['frame_index']<=0xffffffff:
            raise ValueError('Invalid paired frame index')
        if type(p['reset']) is not bool or p['reset'] != bool(p['dispatch_flags'] & 1):
            raise ValueError('Invalid paired reset metadata')
    w,h=metadata['size']
    if not (0<w<=128 and 0<h<=128): raise ValueError('Invalid capture size')
    constants=(folder/'conversion_constants.bin').read_bytes()
    if len(constants)!=416 or hashlib.sha256(constants).hexdigest()!=metadata['constants_sha256']:
        raise ValueError('Constant buffer hash/size mismatch')
    arrays={}
    expected={f'strength{v}_{name}' for v in (0,1) for name in LIVE_FIELDS}
    if paired: expected.add('pre_sr_output')
    for item in metadata['images']:
        name=item['name']; filename=item['file']
        output=name=='pre_sr_output'
        if name not in expected or name in arrays or filename!=name+('.f16' if output else '.f32'):
            raise ValueError('Invalid/duplicate image identity')
        if item.get('format')!=('RGBA16_FLOAT' if output else 'RGBA32_FLOAT'): raise ValueError('Invalid image format')
        data=(folder/filename).read_bytes()
        if len(data)!=w*h*(8 if output else 16) or hashlib.sha256(data).hexdigest()!=item['sha256']:
            raise ValueError('Image hash/size mismatch: '+name)
        a=np.frombuffer(data,'<f2' if output else '<f4').reshape(h,w,4)[...,:3].astype(np.float32)
        field=name.split('_',1)[1]
        if not (field.startswith('source_') or field=='linear_depth') and not np.isfinite(a).all():
            raise ValueError('Nonfinite computed channel journal: '+name)
        arrays[name]=a
    if set(arrays)!=expected: raise ValueError('Incomplete channel journal')
    return metadata,arrays


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    metadata,arrays=read_live(args.capture)
    args.output.mkdir(parents=True,exist_ok=True)
    if (args.output/'summary.json').exists(): raise ValueError('Use a fresh output directory')
    j=[{name:arrays[f'strength{v}_{name}'] for name in LIVE_FIELDS} for v in (0,1)]
    for strength,fields in enumerate(j):
        # The unregularized intercept is exactly determined by the exported
        # moments and slope. Interpret only where fit moments were evaluated.
        arrays[f'strength{strength}_unregularized_intercept']=(fields['mean_residual']-
            fields['unregularized_slope']*fields['mean_albedo'])
    report=dict(source=str(args.capture.resolve()),metadata=metadata,
        reason_bits={str(k):v for k,v in REASONS.items()},summaries=[summarize(f) for f in j],
        fields_note='RGB independently. Fit evidence is evaluated even at zero strength; eligible also includes endpoint-dependent model/FP16 safety guards. Actual delta is recorded separately. Unvisited checks are not passes. Diagnostic signals are not an AMD output quality comparison.',
        actual_signal_delta_rgb={key:np.mean(abs(j[1][key]-j[0][key]),axis=(0,1)).tolist()
                                 for key in ('specular_signal','diffuse_signal','skip_rgb')},
        source_same={key:bool(np.array_equal(j[0][key],j[1][key],equal_nan=True))
                     for key in ('raw_rgb','source_diffuse','source_specular','source_normal',
                                 'source_roughness','source_motion','linear_depth','spatial_floor_rgb')},
        source_nonfinite_rgb={key:(~np.isfinite(value)).sum((0,1)).tolist() for key,value in j[0].items()
                              if key.startswith('source_') or key=='linear_depth'})
    if 'pre_sr_output' in arrays:
        residual=j[0]['raw_rgb']-arrays['pre_sr_output']
        arrays['observed_pre_sr_residual']=residual
        report['paired_observation']=dict(
            signed_raw_minus_pre_sr_rgb=residual.mean((0,1)).tolist(),
            rms_raw_minus_pre_sr_rgb=np.sqrt(np.mean(residual**2,axis=(0,1))).tolist(),
            note='Same-frame noisy observation difference, not clean-reference error. Output uses the actual configured strength, Floor and recovery controls, not both diagnostic endpoints.')
    # Stored-domain accounting also covers partial Floor restoration, which occurs
    # after the estimator's residual-only R*delta-p journal point.
    spec_strength=np.clip(j[1]['settings'][...,1:2],0,1)
    diff_strength=np.clip(j[1]['settings'][...,2:3],0,1)
    spec_multiplier=1+(j[1]['stored_specular']-1)*spec_strength
    diff_multiplier=1+(j[1]['stored_diffuse']-1)*diff_strength
    ds=(j[1]['specular_signal']-j[0]['specular_signal'])*spec_multiplier
    dd=(j[1]['diffuse_signal']-j[0]['diffuse_signal'])*diff_multiplier
    dk=j[1]['skip_rgb']-j[0]['skip_rgb']
    arrays.update(stored_specular_transfer_rgb=ds,stored_diffuse_transfer_rgb=dd,stored_skip_delta_rgb=dk,
                  stored_closure_delta_rgb=ds+dd+dk)
    report['stored_domain']=dict(mean_signed_specular_transfer=ds.mean((0,1)).tolist(),
        mean_absolute_specular_transfer=abs(ds).mean((0,1)).tolist(),
        mean_signed_diffuse_transfer=dd.mean((0,1)).tolist(),mean_signed_skip_delta=dk.mean((0,1)).tolist(),
        maximum_absolute_closure_delta=abs(ds+dd+dk).max((0,1)).tolist())
    for f,row in zip(j,report['summaries']):
        energy=np.maximum(f['raw_rgb'].sum((0,1)),1e-12)
        row['energy_weighted_skip_fraction_rgb']=(f['skip_rgb'].sum((0,1))/energy).tolist()
        row['energy_weighted_eligible_fraction_rgb']=(f['eligible_rgb'].sum((0,1))/energy).tolist()
        row['energy_weighted_abs_transfer_fraction_rgb']=(abs(f['transferred_rgb']).sum((0,1))/energy).tolist()
    np.savez_compressed(args.output/'channels.npz',**arrays)
    save_json(args.output/'summary.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('metadata',)},indent=2))


if __name__=='__main__': main()
