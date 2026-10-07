"""CPU-only visual QA of captured raw data and four verified replay outputs.

All panels use the same exposure and tone mapping. The late raw temporal mean
is a noisy stationary-scene proxy, never a clean target or full-frame proof.
"""
from pathlib import Path
import argparse
import json

import numpy as np
from PIL import Image, ImageDraw

import fsrd_real_capture_replay as replay


def display(rgb, exposure):
    x=np.maximum(np.nan_to_num(np.asarray(rgb,np.float32)[...,:3]),0)*exposure
    x=np.clip(2*x/(1+x),0,1)
    srgb=np.where(x<=.0031308,12.92*x,1.055*np.power(x,1/2.4)-.055)
    return np.asarray(np.clip(srgb,0,1)*255+.5,np.uint8)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',type=Path,required=True)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--replay-dir',type=Path)
    source.add_argument('--comparison-dir',type=Path,help='Baseline/candidate Floor-only and Floor+Bleed A/B panels')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--frames',type=int,nargs='+',default=[0,1,8,64,127])
    parser.add_argument('--exposure',type=float,default=1)
    parser.add_argument('--scale',type=int,default=2)
    args=parser.parse_args()
    if args.scale<1 or not np.isfinite(args.exposure) or args.exposure<=0:
        parser.error('--scale must be positive and --exposure finite and positive')
    provenance,cap=replay.inspect_capture(args.capture,True)
    raw=cap['raw_color'].astype(np.float32)[...,:3]
    proxy=raw[len(raw)//2:].mean(0)
    images=[];sources={}
    root=replay.safe_path(args.replay_dir or args.comparison_dir)
    if args.comparison_dir:
        labels=['Raw current','Raw late temporal mean','Baseline Floor','Candidate Floor','Baseline Floor + Bleed','Candidate Floor + Bleed']
        paths=[root/f'floor1_bleed{bleed}'/(label+'_final.npz') for bleed in (0,1) for label in ('baseline','candidate')]
        shader_provenance=root/'comparison.json'
        comparison=json.loads(shader_provenance.read_text())
        first_case=next(iter(comparison['cases'].values()))
        resets=first_case['metrics']['baseline']['resets']
        reset_list=sorted({0,*resets['captured'],*resets['injected']})
        footnote=f'Native RR resets {reset_list} in each repeated segment; Floor composition history commits successful frames.'
        title='Actual AMD RR: baseline / candidate | Floor and Bleed | captured 128 x 128 ROI'
    else:
        labels=['Raw current','Raw late temporal mean','RR only','RR + Bleed','Floor + RR','Floor + RR + Bleed']
        paths=[root/f'floor{floor}_bleed{bleed}'/'final.npz' for floor,bleed in ((0,0),(0,1),(1,0),(1,1))]
        shader_provenance=root/'shader_provenance.json'
        title='Actual AMD RR: baseline 2 x 2 Floor / Bleed | captured 128 x 128 ROI | 128 real frames'
        footnote='Native RR reset at replay frame 0; Floor composition history commits on subsequent successful frames.'
    for path in paths:
        with np.load(path,allow_pickle=False) as archive:images.append(archive['image'])
        sources[str(path)]=replay.digest(path)
        extras=(path.with_name(path.stem.replace('_final','_metrics')+'.json'),path.parent/'rr_joint/metadata.json') if args.comparison_dir else (path.parent/'metrics.json',path.parent/'rr/metadata.json')
        for extra in extras:
            if extra.is_file():sources[str(extra)]=replay.digest(extra)
    sources[str(shader_provenance)]=replay.digest(shader_provenance)
    w,h=cap['roi']['extent'];pw,ph=w*args.scale,h*args.scale
    cell_h=ph+28;top=62;footer=52
    sheet=Image.new('RGB',(pw*6,top+cell_h*(len(args.frames)+1)+footer),(22,22,22))
    draw=ImageDraw.Draw(sheet)
    draw.text((8,6),title,fill='white')
    draw.text((8,22),f'Exposure {args.exposure:g} for every panel; display = sRGB(clamp(2*linear/(1+linear),0,1))',fill=(210,210,210))
    for column,label in enumerate(labels):draw.text((column*pw+6,42),label,fill='white')
    rows=[]
    for frame in args.frames:
        if not 0<=frame<len(raw):raise ValueError('contact frame outside sequence')
        rows.append((f'frame {frame}',[raw[frame],proxy]+[a[frame] for a in images]))
    rows.append((f'late mean {len(raw)//2}:{len(raw)}',[proxy,proxy]+[a[len(raw)//2:].mean(0) for a in images]))
    for row,(label,panels) in enumerate(rows):
        for column,panel in enumerate(panels):
            x,y=column*pw,top+row*cell_h
            draw.text((x+6,y+4),label,fill=(230,230,230))
            raster=Image.fromarray(display(panel,args.exposure)).resize((pw,ph),Image.Resampling.NEAREST)
            sheet.paste(raster,(x,y+26))
    y=sheet.height-footer+4
    draw.text((8,y),'Late raw temporal mean is a stationary proxy. This capture contains no recorded camera cut or RR reset.',fill=(230,200,160))
    draw.text((8,y+16),footnote,fill=(230,200,160))
    output=replay.safe_path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    sheet.save(output)
    output.with_suffix('.json').write_text(json.dumps(dict(capture_manifest_sha256=provenance['capture_manifest_sha256'],
        authenticated_capture_payload_files=len(provenance['authenticated_payload_files']),
        replay_directory=str(root),output_sha256=replay.digest(output),frames=args.frames,exposure=args.exposure,
        contact_sheet_source_sha256=replay.digest(Path(__file__)),
        frozen_shader_provenance=json.loads(shader_provenance.read_text()),
        tone_mapping='sRGB(clamp(2*exposure*linear/(1+exposure*linear),0,1))',sources=sources,
        limitation='Stationary crop; late raw temporal mean is a proxy, not clean truth.'),indent=2)+'\n')
    print(output)


if __name__=='__main__':main()
