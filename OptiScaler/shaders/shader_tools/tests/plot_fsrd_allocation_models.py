"""Render a fixed-scale scientific comparison from a completed probe's NPZ files.

Requires Pillow. No display normalization is inferred from an individual panel.
"""
from pathlib import Path
import argparse,json
import numpy as np
from PIL import Image, ImageDraw


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--models',default='baseline,surface_overlap,lobes_overlap')
    parser.add_argument('--scenes',default='fake_diffuse_clean,fake_specular_clean')
    args=parser.parse_args()
    scenes=args.scenes.split(',')
    frames=json.loads((args.input/'results.json').read_text())['frames']
    models=args.models.split(',')
    width,height=288,216
    canvas=Image.new('RGB',(width*len(models),60+len(scenes)*(height*2+56)),(24,26,29))
    draw=ImageDraw.Draw(canvas)
    draw.text((10,10),f'{frames}-frame AMD replay: mean of last {min(frames,16)} frames',fill='white')
    draw.text((10,28),'Top: RGB x 3, gamma 2.2. Bottom: signed luminance error, +/- 0.025.',fill='white')
    for row,scene in enumerate(scenes):
        top=60+row*(height*2+56)
        for col,model in enumerate(models):
            with np.load(args.input/(scene+'_'+model)/'preview.npz') as data:
                mean=data['mean']; error=data['mean_error']
            rgb=np.clip(np.maximum(mean*3,0)**(1/2.2),0,1)
            luma=error@np.array([.2126,.7152,.0722])
            signed=np.clip(luma/.025,-1,1)
            # Neutral is gray, positive is red, negative is blue.
            color=np.repeat((1-abs(signed))[...,None]*.5,3,axis=-1)
            color[...,0]+=np.maximum(signed,0)
            color[...,2]+=np.maximum(-signed,0)
            for offset,array in ((22,rgb),(height+30,color)):
                tile=Image.fromarray(np.uint8(np.clip(array,0,1)*255))
                scale=min((width-8)/tile.width,height/tile.height)
                tile=tile.resize((round(tile.width*scale),round(tile.height*scale)),Image.Resampling.NEAREST)
                canvas.paste(tile,(col*width+(width-tile.width)//2,top+offset))
            draw.text((col*width+6,top+4),scene+' / '+model,fill='white')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(args.output)


if __name__=='__main__': main()
