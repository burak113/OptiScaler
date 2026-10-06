"""Preflight short Floor history on actual production spatial GPU outputs.

Temporal candidates are NumPy prototypes, NOT production/GPU temporal code.
Static geometry deliberately has zero motion while the volume moves in front
of it. This measures the missing volume-motion problem before allocating GPU
history. Results never imply AMD RR or game validation.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t


def main():
    t.OUT=t.OUT.parent/'volume_temporal_preflight';t.OUT.mkdir(parents=True,exist_ok=True)
    t.build_runner();w,h=49,33;y,x=np.indices((h,w));roi=(slice(5,-5),slice(5,-5))
    albedo=t.rgba(w,h,(.5,.5,.5));report=[]
    for scene in ('static','moving_volume','light_off','moving_background'):
        spatial=[];truth=[];raw_frames=[]
        for frame in range(16):
            shift=0 if scene in ('static','light_off') else frame*.35
            radius=(x-22-shift)/4
            light=.13*np.exp(-.5*radius**2)
            if scene=='light_off' and frame>=8:light*=0
            clean=t.rgba(w,h,(.07,.09,.12));clean[...,:3]+=light[...,None]*[.6,.8,1]
            raw=clean.copy();raw[...,:3]+=np.random.default_rng(7140+frame).normal(0,.009,(h,w,3))
            f,z,g,_=t.seed(raw,albedo=albedo);f=t.filter_floor(f,z,g,albedo)
            spatial.append(f[...,:3]);truth.append(clean[...,:3]);raw_frames.append(raw[...,:3])
        spatial=np.stack(spatial);truth=np.stack(truth);raw_frames=np.stack(raw_frames)
        for history_length in (2,4):
            outputs=[];history=None
            for frame,current in enumerate(spatial):
                if history is None:result=current
                else:
                    # Surface motion can track a background while leaving the
                    # actual foreground volume stationary (or conversely).
                    old=np.roll(history,1,axis=1) if scene=='moving_background' else history
                    padded=np.pad(current,((1,1),(1,1),(0,0)),mode='edge')
                    neighbours=np.stack([padded[dy:dy+h,dx:dx+w] for dy in range(3) for dx in range(3)])
                    old=np.clip(old,neighbours.min(axis=0),neighbours.max(axis=0))
                    scale=np.maximum(np.linalg.norm(current,axis=2),.01)
                    change=np.linalg.norm(old-current,axis=2)/scale
                    reuse=(1-1/history_length)*np.clip((.08-change)/.055,0,1)
                    result=current+(old-current)*reuse[...,None]
                outputs.append(result);history=result
            outputs=np.stack(outputs)
            sel=(slice(4,None),)+roi+(slice(None),)
            spatial_error=spatial[sel]-truth[sel];error=outputs[sel]-truth[sel]
            row=dict(scene=scene,effective_frames=history_length,
                     spatial_rmse=float(np.sqrt(np.mean(spatial_error**2))),
                     temporal_rmse=float(np.sqrt(np.mean(error**2))),
                     spatial_variation=float(np.sqrt(np.mean(np.var(spatial_error,axis=0)))),
                     temporal_variation=float(np.sqrt(np.mean(np.var(error,axis=0)))),
                     max_added_error=float(np.max(abs(error)-abs(spatial_error))))
            if scene=='light_off':
                row['first_off_added_light']=float(np.max(outputs[8]-spatial[8]))
            report.append(row);print(json.dumps(row),flush=True)
    (t.OUT/'results.json').write_text(json.dumps(dict(records=report,dispatches=t.timings,
        limitation='GPU spatial Floor; CPU temporal prototypes. No production temporal addition.'),indent=2))


if __name__=='__main__':main()
