"""Fixed-scale scientific previews and identity-control variance, CPU only.

No image is edited or retouched. RGB tiles are numeric renderings of sealed
raw inputs, independent finite-spp references and actual signed-provider output.
Every compared column uses identical crop, nearest zoom and exposure.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image,ImageDraw

import fsrd_nrd_rr_albedo_pair_compare as pair
import fsrd_nrd_rr_material_quality as files


FRAMES=(2,25,41,65)
CROP=(16,16,96,96)
CHECKS=0


def need(condition,message):
    global CHECKS
    CHECKS+=1
    if not bool(condition):
        raise AssertionError(message)


def output_rgb(root,runs,key,frame,signal):
    path=root/key/frame['directory']/(signal+'.bin')
    need(files.file_sha(path)==runs[key]['outputs'][str(frame['frame'])][signal],'actual signed-provider output hash before preview/variance')
    return np.fromfile(path,'<f2').reshape(128,128,4)


def identity_control(root,runs):
    case=Path(runs['corrected-v7-r123-white']['input_case'])
    _,manifest=pair.read_manifest(case)
    need(manifest['identity_pair'],'variance evaluated ONLY for byte-identical corrected-r123 controls')
    rows={}
    crop=np.s_[16:112,16:112,:3]
    for signal in ('spec','diff'):
        total_squared=count=mismatch=0
        maximum=0.
        frame_rows=[]
        for frame in manifest['frames']:
            a=output_rgb(root,runs,'corrected-v7-r123-white',frame,signal)
            b=output_rgb(root,runs,'corrected-v7-r123-correct',frame,signal)
            diff=a[crop].astype(np.float64)-b[crop].astype(np.float64)
            changed=int(np.count_nonzero(a[crop].copy().view('<u2')!=b[crop].copy().view('<u2')))
            square=float(np.sum(diff*diff))
            total_squared+=square;count+=diff.size;mismatch+=changed
            maximum=max(maximum,float(np.max(abs(diff))))
            frame_rows.append(dict(frame=frame['frame'],roi_rmse=float(np.sqrt(square/diff.size)),changed_half_words=changed))
        rows[signal]=dict(roi_rgb_words=count,mismatched_half_words=mismatch,
            mismatched_fraction=mismatch/count,aggregate_roi_rgb_rmse=float(np.sqrt(total_squared/count)),
            maximum_roi_abs_difference=maximum,frames=frame_rows)
    return dict(crop=list(CROP),source_manifest_sha256=files.file_sha(case/'ggx-sequence.json'),signals=rows,
        interpretation='observed fresh-context repetition variation under identical actual seven inputs/settings; not caused by albedo and not proof of its private cause')


def srgb_tile(rgb,exposure):
    linear=np.asarray(rgb,np.float64)*exposure
    need(np.isfinite(linear).all(),'finite sealed RGB visualized without NaN replacement')
    clipped=int(np.count_nonzero((linear<0)|(linear>1)))
    x=np.clip(linear,0,1)
    encoded=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
    image=Image.fromarray(np.rint(encoded*255).astype('u1'))
    return image.resize((288,288),Image.Resampling.NEAREST),clipped


def run(root,output):
    need(not output.exists(),'fresh preview folder preserves all old figures')
    output.mkdir(parents=True)
    info=json.loads((root/'runs.json').read_bytes())
    runs=info['runs']
    case=Path(runs['colored-v8-g31-b124-both']['input_case'])
    _,manifest=pair.read_manifest(case)
    need(tuple(manifest['views'])==('white','diffuse-only','specular-only','both'),'all four colored material candidates retained in every figure')
    columns=('noisy_input','reference_a','reference_b','white','diffuse-only','specular-only','both')
    metadata={}
    for domain,exposure in (('physical_spec',16.),('demod_spec',4.),('physical_combined',8.)):
        image=Image.new('RGB',(88+len(columns)*296,56+len(FRAMES)*312),(22,22,22))
        draw=ImageDraw.Draw(image)
        draw.text((6,5),f'V8 synthetic {domain} | fixed linear exposure {exposure:g}, sRGB display | crop16,16 96x96, nearest3x | independent256spp A/B',fill='white')
        for col,name in enumerate(columns):draw.text((88+col*296,29),name,fill='white')
        tiles=[]
        for row,number in enumerate(FRAMES):
            frame=manifest['frames'][number-2]
            data=pair.load(case,manifest,frame)
            qs=np.rint(data['qs_current'].astype(np.float64)*255)/255
            qd=np.rint(data['qd_current'].astype(np.float64)*255)/255
            refs={suffix:data['reference_spec_'+suffix].astype(np.float64) for suffix in ('a','b')}
            lights={'noisy_input':dict(spec=data['spec'][...,:3].astype(np.float64),diff=data['diff'][...,:3].astype(np.float64))}
            for name in manifest['views']:
                key='colored-v8-g31-b124-'+name
                lights[name]={signal:output_rgb(root,runs,key,frame,signal)[...,:3].astype(np.float64) for signal in ('spec','diff')}
            values={n:light['spec']*(1 if domain=='demod_spec' else qs) for n,light in lights.items()}
            for suffix in ('a','b'):
                values['reference_'+suffix]=refs[suffix]/qs if domain=='demod_spec' else refs[suffix]
            if domain=='physical_combined':
                for n,light in lights.items():values[n]+=light['diff']*qd
                for suffix in ('a','b'):values['reference_'+suffix]+=data['reference_diff']
            new_count=int(np.count_nonzero(data['reveal_age'][16:112,16:112]==0))
            draw.text((4,57+row*312),f'SL{number}',fill='white')
            draw.text((4,74+row*312),f'new:{new_count}',fill='white')
            for col,name in enumerate(columns):
                rgb=values[name][16:112,16:112]
                tile,clipped=srgb_tile(rgb,exposure)
                image.paste(tile,(88+col*296,56+row*312))
                draw.text((88+col*296,347+row*312),f'clip channels:{clipped}/{rgb.size}',fill=(180,180,180))
                tiles.append(dict(frame=number,candidate=name,clipped_channels=clipped,displayed_channels=int(rgb.size)))
        path=output/(domain+'.png');image.save(path)
        metadata[domain]=dict(path=str(path),sha256=files.file_sha(path),exposure=exposure,tiles=tiles)
    result=dict(schema='corrected-albedo-fixed-preview-and-repeat-variance',checks=CHECKS,
        prepared_manifest_sha256=files.file_sha(case/'colored-ggx-sequence.json'),
        runs_sha256=files.file_sha(root/'runs.json'),comparison_sha256=files.file_sha(root/'comparison.json'),
        figures=metadata,identity_control=identity_control(root,runs),frames=list(FRAMES),crop=list(CROP),
        pixels_retouched=False,exposure_shared_between_all_columns=True,
        finite_reference_noise_visible=True,native_game_capture=False,
        gamma='linear exposure then standard sRGB display only; raw analytical metrics unchanged',
        physical_combined_caveat='material edges contribute strongly; no reflection detail claim from combined contrast',
        gpu_executed=False,compiler_executed=False)
    result['checks']=CHECKS
    files.write_json(output/'preview-and-variance.json',result)
    print(json.dumps(dict(checks=CHECKS,figures={k:v['path'] for k,v in metadata.items()},
        identity={s:{k:v for k,v in row.items() if k!='frames'} for s,row in result['identity_control']['signals'].items()}),indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();run(args.results,args.output)
