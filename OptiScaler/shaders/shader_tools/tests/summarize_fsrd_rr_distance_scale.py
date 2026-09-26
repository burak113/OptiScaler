"""Summarize the actual RR probe; previews are linear values with display gamma only."""
from pathlib import Path
import argparse,json
import numpy as np
from PIL import Image,ImageDraw,ImageFont

def main():
    ap=argparse.ArgumentParser();ap.add_argument('root',type=Path);args=ap.parse_args();root=args.root.resolve()
    if root.drive.upper()!='F:':raise ValueError('F: output required')
    report=[];total=0
    for suite in ('full','smooth'):
        p=root/suite/'results.json'
        if not p.exists():continue
        data=json.loads(p.read_text());rows=data['results'];total+=len(rows)*data['frames']
        for scene in sorted({r['scene'] for r in rows}):
            for signal in ('dd','is'):
                selected=[r for r in rows if r['scene']==scene and r['signal']==signal]
                base={r['seed']:r['metrics'] for r in selected if r['variant']=='far'}
                for variant in sorted({r['variant'] for r in selected}):
                    candidates=[r for r in selected if r['variant']==variant]
                    average={k:np.mean([r['metrics'][k] for r in candidates],axis=0).tolist() for k in candidates[0]['metrics']}
                    changes={k:float(np.mean([100*(r['metrics'][k]/max(base[r['seed']][k],1e-12)-1) for r in candidates]))
                             for k in ('rmse','quiet_temporal_std','quiet_rmse','error_flicker')}
                    report.append(dict(suite=suite,scene=scene,signal=signal,variant=variant,seeds=len(candidates),mean=average,percent_change_vs_far=changes))
    (root/'summary.json').write_text(json.dumps(dict(actual_dispatches=total,rows=report),indent=2))
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',19)
    small=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',15)
    for suite,scene in [('full','static_fine'),('full','untracked_fine'),('full','static_clean'),('smooth','smooth_fine')]:
        base=root/suite/f'{scene}_7123_is_far'/'preview.npz'
        if not base.exists():continue
        a=np.load(base);items=[('Clean reference',a['clean']),('Noisy input',a['noisy']),('RR: far (z=20)',a['result'])]
        for variant,label in [('near_scaled','RR: near (z=2)'),('up_bilinear','2x bilinear + RR'),('native_high','Independent high-res + RR')]:
            items.append((label,np.load(root/suite/f'{scene}_7123_is_{variant}'/'preview.npz')['result']))
        canvas=Image.new('RGB',(6*384,2*256+110),(25,28,32));draw=ImageDraw.Draw(canvas)
        for i,(label,pixels) in enumerate(items):
            rgb=np.uint8(np.clip(pixels,0,1)**(1/2.2)*255)
            im=Image.fromarray(rgb).resize((384,256),Image.Resampling.NEAREST)
            canvas.paste(im,(i*384,32));draw.text((i*384+8,6),label,font=font,fill='white')
            # Fixed signed error display range, not independently normalized.
            err=np.uint8(np.clip(.5+4*(pixels-a['clean']),0,1)*255)
            canvas.paste(Image.fromarray(err).resize((384,256),Image.Resampling.NEAREST),(i*384,322))
        draw.text((8,294),'Signed RGB error: mid-gray = zero; fixed 4x error scale. Top: last frame, gamma 2.2 for display.',font=small,fill='white')
        draw.text((8,589),f'{scene}; actual AMD RR indirect specular; flat albedo; roughness 0.1; common 192x128 output grid.',font=small,fill='white')
        canvas.save(root/f'{scene}_comparison.png')
    print('actual_dispatches',total)
    for r in report:
        if r['signal']=='is' and r['variant'] in ('far','near_scaled','up_bilinear','native_high'):
            print(r['scene'],r['variant'],'RMSE',round(r['mean']['rmse'],6),'change%',round(r['percent_change_vs_far']['rmse'],2),
                  'quiet_std',round(r['mean']['quiet_temporal_std'],6),'std_change%',round(r['percent_change_vs_far']['quiet_temporal_std'],2),
                  'text_gain',round(r['mean']['text_gain'],3),'stripe_gain',np.round(r['mean']['stripe_gain'],3).tolist())

if __name__=='__main__':main()
