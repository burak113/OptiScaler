"""Analysis only: preserve calibrated metrics and derive geometric history ROI.

No compiler, DLL, GPU or production change. Existing outputs and inputs are
read-only. The additional masks model the supplied canonical UV history; they
cannot certify AMD's private spatial/virtual-hit sampling footprint.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import struct

os.environ.update(TEMP='F:/FSRD/tmp', TMP='F:/FSRD/tmp', OMP_NUM_THREADS='2',
                  OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
import numpy as np


def load(folder, payload):
    data=(folder/payload['file']).read_bytes()
    if len(data)!=payload['bytes'] or hashlib.sha256(data).hexdigest()!=payload['sha256']:
        raise ValueError('sealed payload integrity mismatch')
    return np.frombuffer(data,np.dtype(payload['dtype'])).reshape(payload['shape'])


def chroma(rgb):
    return np.stack((rgb[...,0]-rgb[...,2],rgb[...,1]-(rgb[...,0]+rgb[...,2])*.5),-1)


def masked_metrics(out, ref, mask):
    if not mask.any():
        return None
    out=np.asarray(out,dtype=np.float64)[...,:3];ref=np.asarray(ref,dtype=np.float64)[...,:3]
    error=out-ref;cc=chroma(out)-chroma(ref)
    mx=mask[:,1:]&mask[:,:-1];my=mask[1:,:]&mask[:-1,:]
    dx=np.diff(error,axis=1);dy=np.diff(error,axis=0)
    n=int(mx.sum()+my.sum())*3
    return dict(pixels=int(mask.sum()),rmse=float(np.sqrt(np.mean(error[mask]**2))),
                bias=float(error[mask].mean()),opponent_chroma_rmse=float(np.sqrt(np.mean(cc[mask]**2))),
                detail_gradient_rmse=float(np.sqrt((np.sum(dx[mx]**2)+np.sum(dy[my]**2))/n)) if n else None,
                gradient_component_support=n)


def propagated(mask, previous_plane, current_plane, motion, physical):
    height,width=mask.shape;y,x=np.mgrid[:height,:width]
    px=x+motion[...,0].astype(np.float64)*width;py=y+motion[...,1].astype(np.float64)*height
    x0=np.floor(px).astype(np.int64);y0=np.floor(py).astype(np.int64)
    ax=px-x0;ay=py-y0;result=physical.copy()
    for ox,oy,weight in ((0,0,(1-ax)*(1-ay)),(1,0,ax*(1-ay)),(0,1,(1-ax)*ay),(1,1,ax*ay)):
        sx=x0+ox;sy=y0+oy
        inside=(sx>=0)&(sx<width)&(sy>=0)&(sy<height)
        safe=inside.copy();bounded_x=np.clip(sx,0,width-1);bounded_y=np.clip(sy,0,height-1)
        safe &= mask[bounded_y,bounded_x]&(previous_plane[bounded_y,bounded_x]==current_plane)
        result &= (weight==0)|safe
    return result


def analyse(report):
    report=Path(report);comparison=json.loads((report/'comparison.json').read_text(encoding='utf-8'))
    runs={row['candidate']:json.loads((report/(row['candidate']+'.json')).read_text(encoding='utf-8'))
          for row in comparison['rows']}
    work=Path(next(iter(runs.values()))['native_log']).parents[1];inputs=work/'inputs'
    manifest=json.loads((inputs/'sequence.json').read_text(encoding='utf-8'))
    x,y,cw,ch=manifest['comparison_crop'];height,width=manifest['height'],manifest['width']
    physical=np.zeros((height,width),bool);physical[y:y+ch,x:x+cw]=True
    previous_plane=None;history_safe=physical.copy();rows=[];aggregate={}
    input_max={signal:0. for signal in ('spec','diff')}
    for frame in manifest['frames']:
        folder=inputs/frame['directory'];payload=frame['payloads']
        world=load(folder,payload['primary_world']);motion=load(folder,payload['motion'])
        # Exactly two declared primary planes: -6 and -2. The midpoint -4 is
        # derived from geometry, not an error threshold or tuned pixel margin.
        plane=world[...,2]>-4
        if previous_plane is None:
            direct=physical.copy();history_safe=physical.copy()
        else:
            direct=propagated(physical,previous_plane,plane,motion,physical)
            history_safe=propagated(history_safe,previous_plane,plane,motion,physical)
        previous_plane=plane
        row=dict(frame=frame['frame'],key_pose=frame['key_pose'],repeat=frame['repeat'],
                 physical_pixels=int(physical.sum()),direct_support_pixels=int(direct.sum()),
                 recursive_support_pixels=int(history_safe.sum()),signals={})
        for signal in ('spec','diff'):
            reference=load(folder,payload['reference_'+signal]);noisy=load(folder,payload[signal])
            input_max[signal]=max(input_max[signal],float(np.max(noisy[...,:3])))
            metrics={'noisy_input':{}}
            for roi,mask in [('direct_canonical_support',direct),('recursive_canonical_support',history_safe)]:
                metrics['noisy_input'][roi]=masked_metrics(noisy,reference,mask)
            for candidate in runs:
                data=(work/candidate/frame['directory']/(signal+'.bin')).read_bytes()
                output=np.frombuffer(data,'<f2').reshape(height,width,4)
                metrics[candidate]={roi:masked_metrics(output,reference,mask) for roi,mask in
                                    [('direct_canonical_support',direct),('recursive_canonical_support',history_safe)]}
            row['signals'][signal]=metrics
        rows.append(row)
    for roi in ('direct_canonical_support','recursive_canonical_support'):
        aggregate[roi]={}
        for candidate in ['noisy_input',*runs]:
            aggregate[roi][candidate]={}
            for signal in ('spec','diff'):
                values=[row['signals'][signal][candidate][roi] for row in rows if row['repeat']>=4]
                values=[value for value in values if value]
                aggregate[roi][candidate][signal]={name:float(np.mean([v[name] for v in values if v[name] is not None]))
                                                  for name in ('rmse','bias','opponent_chroma_rmse','detail_gradient_rmse')}
    candidate_status=[];original={r['candidate']:r for r in comparison['rows']}
    for candidate,run in runs.items():
        row=original[candidate];same_route=original[run['route']+'_gain1'];status={}
        for signal in ('spec','diff'):
            noisy=float(np.mean([f['signals'][signal]['noisy_input']['rmse'] for f in run['frames_metrics'] if f['repeat']>=4]))
            baseline=original['dd_gain1']['metrics'][signal]
            status[signal]=dict(noisy_rmse_original_crop=noisy,
                               rr_original_rmse=row['metrics'][signal]['rmse'],
                               rr_original_change_vs_noisy_pct=100*(row['metrics'][signal]['rmse']/noisy-1),
                               change_vs_same_route_gain1_pct={name:100*(value/same_route['metrics'][signal][name]-1)
                                                              for name,value in row['metrics'][signal].items() if name!='bias'},
                               change_vs_dd_gain1_pct={name:100*(value/baseline[name]-1)
                                                      for name,value in row['metrics'][signal].items() if name!='bias'})
        candidate_status.append(dict(candidate=candidate,route=run['route'],gain=run['gain'],signals=status,
                                     native_checks=run['checks'],creates=run['creates'],destroys=run['destroys'],
                                     dispatches=run['dispatches'],debug_errors=run['debug_errors'],debug_warnings=run['debug_warnings'],
                                     peak_working_set_bytes=run['peak_working_set_bytes'],elapsed_seconds=run['elapsed_seconds']))
    return dict(schema='fsrd-rr-conditioning-derived-analysis-v1',source_comparison=str(report/'comparison.json'),
                source_comparison_sha256=hashlib.sha256((report/'comparison.json').read_bytes()).hexdigest(),
                original_metrics_modified=False,calibrated_stage=True,candidate_status=candidate_status,
                effective_values=list(struct.unpack('<8f',struct.pack('<8I',*comparison['effective_words']))),
                support_rule='physical declared interior AND every nonzero-weight bilinear MV support is previous physical same-plane; recursive mask retains all earlier exclusions',
                roi_certification='canonical surface-camera history only; AMD private NN spatial/virtual-hit tap footprint is unknown and NOT certified guard-free',
                frame_pixel_counts=[{k:row[k] for k in ('frame','key_pose','repeat','physical_pixels','direct_support_pixels','recursive_support_pixels')} for row in rows],
                per_frame_roi_metrics=rows,late_mean_roi_metrics=aggregate,
                gain64_input_bound={signal:dict(maximum_original_half_rgb=value,maximum_times64=value*64,half_maximum=65504)
                                    for signal,value in input_max.items()},
                scope=manifest['scope'],native_nrd_paired=False,game_fps_measured=False,production_default_changed=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=analyse(args.report)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(json.dumps(result,indent=2,allow_nan=False).encode('utf-8')+b'\n')
    print(json.dumps({key:result[key] for key in ('source_comparison_sha256','original_metrics_modified','late_mean_roi_metrics','gain64_input_bound')}))


if __name__=='__main__':
    main()
