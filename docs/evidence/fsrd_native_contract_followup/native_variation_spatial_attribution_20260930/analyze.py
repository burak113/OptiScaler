"""Describe spatial/temporal location of the retained tuning0 divergence."""
from pathlib import Path
import hashlib,json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    folder=Path(__file__).resolve().parent;out=folder/'evidence'
    if out.exists():raise ValueError('Preserve attribution')
    out.mkdir();source=ROOT/'tools_tmp/default_tuning_context_repeat_v2_20260930/evidence'
    files=[source/f'repeat_{i}/native_outputs.npz' for i in (0,2)]
    arrays=[]
    for p in files:
        with np.load(p) as a:arrays.append({k:a[k].astype(np.float64) for k in ('diffuse','specular')})
    result=dict(schema='retained-native-variation-spatial-attribution-v1',quality_accepted=False,native_dispatches=0,
        script_sha256=sha(__file__),source_arrays=[dict(path=str(p),sha256=sha(p)) for p in files],lobes={},
        scope='One observed nonzero tuning0 pair. Spatial descriptions neither prove a boundary defect nor estimate a population distribution.')
    h,w=arrays[0]['diffuse'].shape[1:3];y,x=np.indices((h,w))
    edge=np.minimum.reduce([y,h-1-y,x,w-1-x]);bands={'distance0to3':edge<4,'distance4to15':(edge>=4)&(edge<16),'distance16plus':edge>=16}
    fig,axes=plt.subplots(2,3,figsize=(12,6),constrained_layout=True)
    for row,key in enumerate(('diffuse','specular')):
        d=arrays[1][key][...,:3]-arrays[0][key][...,:3]
        rms=np.sqrt(np.mean(d*d,axis=(1,2,3)));first=int(np.flatnonzero(rms)[0])
        frames={}
        for f in (first,31,32,63):
            delta=d[f];where=np.argwhere(delta!=0)
            frames[str(f)]=dict(rms=float(rms[f]),different_values=int(len(where)),first_difference=where[0].tolist() if len(where) else None,
                changed_pixel_fraction=float(np.mean(np.any(delta!=0,axis=-1))),
                bands={name:dict(pixel_count=int(mask.sum()),rms=float(np.sqrt(np.mean(delta[mask]**2))),
                    changed_pixel_fraction=float(np.mean(np.any(delta[mask]!=0,axis=-1)))) for name,mask in bands.items()})
        result['lobes'][key]=dict(first_different_frame=first,frame_rms=rms.tolist(),selected_frames=frames,
            alpha_exact=bool(np.array_equal(arrays[0][key][...,3],arrays[1][key][...,3])))
        for col,f in enumerate((first,32,63)):
            mag=np.sqrt(np.mean(d[f]**2,axis=-1));p=axes[row,col].imshow(mag,origin='upper',cmap='magma',vmin=0,vmax=float(mag.max()) or 1)
            axes[row,col].set_title(f'{key}, frame {f}, RGB RMS {rms[f]:.3g}');axes[row,col].set_xlabel('x');axes[row,col].set_ylabel('y');fig.colorbar(p,ax=axes[row,col],shrink=.8)
    fig.suptitle('Same-input native context differences; one retained tuning0 pair')
    figure=out/'native_context_spatial_difference.png';fig.savefig(figure,dpi=140);plt.close(fig)
    result['figure_sha256']=sha(figure)
    (out/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v['selected_frames'] for k,v in result['lobes'].items()}))
if __name__=='__main__':main()
