"""Audit the real readbacks, including transient errors hidden by mean metrics."""
from pathlib import Path
import argparse,json,csv,hashlib
import numpy as np
from PIL import Image,ImageDraw
import probe_fsrd_real_rr as rr

def main():
    ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);args=ap.parse_args()
    root=args.output.resolve();report=json.loads((root/'results.json').read_text())
    rows=[];transients=[];case_count=0
    for dataset in report['datasets']:
        label=dataset['name'];d=root/label
        source=np.load(Path(report.get('source_root',str(root)))/'sources'/label/'inputs.npz')
        clean=source['clean'];observed=source['observed'];n,h,w,_=clean.shape
        measured={}
        for run in dataset['runs']:
            folder=d/(run['signal']+'_'+run['carrier']);case_count+=1
            log=(folder/'runner.log').read_text()
            expected=f'dispatches={n} validation_errors=0 validation_warnings=0 sdk_errors=0 sdk_warnings=0'
            if expected not in log or 'debug_layer=1' not in log:
                raise RuntimeError('Saved RR validation incomplete: '+str(folder))
            spec=run['signal']=='is'
            a=np.fromfile(folder/('spec_albedo.bin' if spec else 'diff_albedo.bin'),np.uint8).astype(np.float32).reshape(-1,h,w,4)[...,:3]/255
            s=np.fromfile(folder/('spec_signal.bin' if spec else 'diff_signal.bin'),'<f2').astype(np.float32).reshape(n,h,w,4)[...,:3]
            y=np.fromfile(folder/('output_spec.bin' if spec else 'output_diff.bin'),'<f2').astype(np.float32).reshape(n,h,w,4)[...,:3]
            final=y*a+np.maximum(observed-s*a,0)
            if not np.isfinite(final).all() or np.min(final)<0:raise RuntimeError('Invalid saved RR data')
            motion='untracked' if 'untracked' in label else 'static'
            metrics=rr.metrics(final,y,clean,observed,s,motion)
            for key,value in metrics.items():
                saved=run['metrics'][key]
                if (value is None) != (saved is None) or (value is not None and not np.allclose(value,saved,rtol=1e-5,atol=1e-7)):
                    raise RuntimeError('Readback metric mismatch: '+str(folder)+' '+key)
            frame=np.sqrt(np.mean((final-clean)**2,axis=(1,2,3)))
            transition=dict(dataset=label,signal=run['signal'],carrier=run['carrier'],frame_rmse=frame.tolist(),
                first_four_rmse=float(np.sqrt(np.mean((final[:4]-clean[:4])**2))))
            if label=='texture_cut':
                transition['cut_first_four_rmse']=float(np.sqrt(np.mean((final[n//2:n//2+4]-clean[n//2:n//2+4])**2)))
            transients.append(transition)
            measured[run['signal']+'_'+run['carrier']]=final
            rows.append(dict(dataset=label,signal=run['signal'],carrier=run['carrier'],
                output_rmse=metrics['output_rmse'],contrast=metrics['structure_contrast_ratio'],
                quiet_error_ratio=metrics['quiet_error_ratio'],quiet_std_ratio=metrics['quiet_temporal_std_ratio'],
                first_four_rmse=transition['first_four_rmse']))
        f=n-1
        panels=[('Known clean (oracle only)',clean[f]),('Observed',observed[f]),
                ('Existing reference -> RR (IS)',measured['is_reference'][f]),
                ('New carrier -> RR (IS)',measured['is_candidate'][f]),
                ('Perfect albedo -> RR (IS)',measured['is_oracle'][f]),
                ('New carrier -> RR (DD)',measured['dd_candidate'][f])]
        im=Image.new('RGB',(1536,840),'#141a21');draw=ImageDraw.Draw(im)
        for i,(name,rgb) in enumerate(panels):
            x=i%3*512;y=i//3*420;draw.text((x+8,y+8),name,fill='white')
            im.paste(Image.fromarray(np.uint8(np.clip(rgb,0,1)*255)).resize((512,384)),(x,y+30))
        im.save(d/'real_rr_comparison.png')
    with (root/'measurements.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (root/'transient_errors.json').write_text(json.dumps(transients,indent=2))
    gpu=json.loads((root/'gpu_dispatches.json').read_text());floor=json.loads((root/'production_dispatches.json').read_text())
    if not all('validation_errors=0 validation_warnings=0' in d['log'] and 'debug_layer=1' in d['log'] for d in gpu):
        raise RuntimeError('Experimental GPU validation incomplete')
    if not all(d.get('validation_errors')=='0' and d.get('validation_warnings')=='0' and d.get('debug_layer')=='1' for d in floor):
        raise RuntimeError('Production GPU validation incomplete')
    audit=dict(datasets=len(report['datasets']),rr_cases=case_count,rr_dispatches=case_count*report['frames'],
               experiment_dispatches=len(gpu),production_dispatches=len(floor),all_saved_metrics_reproduced=True,
               validation_errors=0,validation_warnings=0,results_sha256=hashlib.sha256((root/'results.json').read_bytes()).hexdigest())
    (root/'audit.json').write_text(json.dumps(audit,indent=2))
    print(json.dumps(audit,indent=2))
    for label in [d['name'] for d in report['datasets']]:
        for signal in ('dd','is'):
            pair=[r for r in rows if r['dataset']==label and r['signal']==signal and r['carrier'] in ('reference','candidate')]
            print(label,signal,[(r['carrier'],r['output_rmse'],r['contrast'],r['quiet_error_ratio']) for r in pair])

if __name__=='__main__':main()
