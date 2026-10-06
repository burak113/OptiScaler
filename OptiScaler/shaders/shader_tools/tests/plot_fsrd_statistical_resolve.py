"""Fixed-scale scientific image grid from saved real-AMD sequences."""
from pathlib import Path
import argparse
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--scenes',default='fake_specular,material,wave,guide_noise,moving_light')
    p.add_argument('--models',default='truth,legacy,allocator,same_frame_rr,independent_rr')
    a=p.parse_args();scenes=a.scenes.split(',')
    columns=a.models.split(',')
    first=np.load(a.study/scenes[0]/'sequences.npz')['legacy']
    h,w=first.shape[1:3];scale=2;header=52;label=38
    cw=w*scale;rowh=h*scale+label
    canvas=Image.new('RGB',(cw*len(columns),header+2*rowh*len(scenes)),(22,24,28))
    draw=ImageDraw.Draw(canvas);font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',13)
    draw.text((6,5),'Actual AMD / CPU research | Last frame | RGB x3, gamma 2.2',fill='white',font=font)
    draw.text((6,24),'Second row: signed luminance error, fixed +/-0.025 | blue negative / red positive | no quality promotion',fill='white',font=font)
    for index,scene in enumerate(scenes):
        with np.load(a.study/scene/'sequences.npz') as data:
            truth=data['truth'][-1]
            for col,model in enumerate(columns):
                rgb=data[model][-1]
                error=(rgb-truth)@np.array([.2126,.7152,.0722])
                signed=np.clip(error/.025,-1,1)
                colors=np.stack((1+np.minimum(signed,0),1-abs(signed),1-np.maximum(signed,0)),axis=-1)
                for sub,array in enumerate((np.clip(rgb*3,0,1)**(1/2.2),colors)):
                    x=col*cw;y=header+(2*index+sub)*rowh
                    draw.text((x+3,y+2),scene,fill='white',font=font)
                    title={'same_frame_rr':'Same-frame RR features','independent_rr':'Independent RR features',
                           'independent_validated_rr':'Independent + holdout'}.get(model,model)
                    draw.text((x+3,y+18),title,fill='white',font=font)
                    tile=Image.fromarray(np.rint(np.clip(array,0,1)*255).astype(np.uint8))
                    canvas.paste(tile.resize((cw,h*scale),Image.Resampling.NEAREST),(x,y+label))
    a.output.parent.mkdir(parents=True,exist_ok=True);canvas.save(a.output)


if __name__=='__main__': main()
