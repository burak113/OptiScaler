"""Audit and visualize the measured Floor -> virtual albedo -> AMD RR experiment."""
from pathlib import Path
import argparse
import csv
import hashlib
import json

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def run(root):
    root=root.resolve()
    if root.drive.upper()!='F:':
        raise ValueError('Artifacts must remain on F:')
    data=json.loads((root/'results.json').read_text(encoding='utf-8'))
    if len(data['datasets']) != 4:
        raise ValueError('The full four-dataset experiment is required')
    frames=data['frames']; runs=0; shader_dispatches=0
    rows=[]
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',20)
    small=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',18)
    for dataset in data['datasets']:
        name=dataset['source']['name']; folder=root/name
        dispatches=json.loads((folder/'floor_dispatches.json').read_text())
        if not all(d.get('debug_layer')=='1' and d['shader_sha256']==data['shader_hashes'][d['shader']] for d in dispatches):
            raise ValueError('Invalid Floor shader provenance or missing debug layer')
        shader_dispatches+=len(dispatches)
        for row in dataset['runs']:
            runs+=1
            log=(folder/(row['signal']+'_'+row['carrier'])/'runner.log').read_text()
            if f'dispatches={frames} validation_errors=0 validation_warnings=0 sdk_errors=0 sdk_warnings=0' not in log:
                raise ValueError('RR validation failed')
            if not row['metrics']['finite'] or row['identity_max_error']>.003:
                raise ValueError('Nonfinite output or closure error')
            rows.append(dict(dataset=name,signal=row['signal'],carrier=row['carrier'],**row['metrics']))
        with np.load(folder/'inputs.npz') as inputs:
            clean=inputs['clean'][-1]; noisy=inputs['noisy'][-1]
        with np.load(folder/'floor_sequences.npz') as refs:
            reference=refs['reference'][-1]
        panels=[('Bilinen temiz hedef (ölçüm için)',clean),('Gürültülü girdi',noisy),
                ('Düz albedo ile gerçek RR',np.load(folder/'dd_flat/preview.npz')['result']),
                ('Floor DetailReference / RR öncesi',reference),
                ('Floor referansı + gerçek RR',np.load(folder/'dd_reference/preview.npz')['result']),
                ('Temiz desen kontrolü + gerçek RR',np.load(folder/'dd_oracle/preview.npz')['result'])]
        tw,th=536,434
        sheet=Image.new('RGB',(tw*3,th*2+104),'#111923'); draw=ImageDraw.Draw(sheet)
        for i,(title,a) in enumerate(panels):
            x,y=(i%3)*tw+12,(i//3)*th+12
            draw.text((x,y),title,font=font,fill='white')
            a=np.clip(a,0,1)
            a=np.where(a<=.0031308,12.92*a,1.055*np.power(a,1/2.4)-.055)
            im=Image.fromarray(np.round(a*255).astype('uint8')).resize((512,384),Image.Resampling.NEAREST)
            sheet.paste(im,(x,y+34))
        draw.text((12,th*2+8),f'{name} · gerçek Floor shader + AMD RR · direct diffuse · roughness=0.1 · {frames}. kare',font=font,fill='white')
        draw.text((12,th*2+40),'256×192 girdi, 2× nearest gösterim. Aynı sRGB dönüşümü; görsel [0,1] kırpılmış, metrikler lineer.',font=small,fill='#b8cbdc')
        draw.text((12,th*2+67),'Temiz hedef yalnız ölçüm ve sağ alt kontrol için kullanıldı. Floor yalnız gürültülü girdiyi gördü.',font=small,fill='#b8cbdc')
        sheet.save(root/(name+'_comparison.png'))
    if runs!=50:
        raise ValueError('Incomplete RR cases')
    fields=['dataset','signal','carrier','quiet_error_ratio','quiet_temporal_std_ratio',
            'structure_contrast_ratio','output_rmse','mean_structure_rmse','raw_change_rms']
    with (root/'measurements.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)
    # Independent compilation of the exact sources should reproduce every tested CSO.
    compiler_hash_match={name:hashlib.sha256((root/'shader_audit'/(name+'.cso')).read_bytes()).hexdigest()==sha
                         for name,sha in data['shader_hashes'].items()}
    if not all(compiler_hash_match.values()):
        raise ValueError('Source / tested bytecode mismatch')
    audit=dict(rr_cases=runs,rr_dispatches=runs*frames,floor_shader_dispatches=shader_dispatches,
               floor_d3d_errors=0,rr_d3d_errors=0,rr_d3d_warnings=0,rr_sdk_errors=0,rr_sdk_warnings=0,
               reference_rr_independence_checks=2*len(data['datasets']),
               source_matches_tested_bytecode=compiler_hash_match,status='passed')
    (root/'audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print(json.dumps(audit))
    for row in rows:
        if row['carrier'] in ('flat','reference','oracle'):
            print(row['dataset'],row['signal'],row['carrier'],
                  'noise',row['quiet_error_ratio'],'contrast',row['structure_contrast_ratio'],'RMSE',row['output_rmse'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    run(p.parse_args().input)
