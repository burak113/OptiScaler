"""Analytic two-layer transport counterexample, independent of a denoiser.

This is a targeted falsifier, not another tuned candidate. A 60/40 unresolved
coverage mixture has fixed dominant guides, while its two textures move with
different velocities. Exact previous-frame layer evaluation separates composite
motion error from any interpolation, noise, quantization, or history-estimator
effect. The result is not a captured game observation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import numpy as np
from foliage_guides import GuideFrame, observe_guides, pack_normal_roughness


def run_discriminator() -> dict:
    width,height,frames=64,8,12
    fraction=np.float32(.6)
    velocities=(.25,-.5)
    yy,xx=np.indices((height,width),np.float32)
    mask=(xx>=2)&(xx<=width-3)
    normal=np.zeros((height,width,3),np.float32);normal[...,2]=1
    packed=pack_normal_roughness(normal,.4,0)
    depth=np.full((height,width),12,np.float32)
    mv=np.zeros((height,width,4),np.float16);mv[...,0]=-velocities[0]/width
    observed_guides=[GuideFrame(packed,depth,mv,200+t,(0,0),(width,height),True) for t in range(frames)]

    def layer(index:int,x:np.ndarray,t:int)->np.ndarray:
        phase=x-velocities[index]*t
        if index==0:
            v=.4+.24*np.sin(2*np.pi*phase/3.7)
            return np.stack((v,.7*v,.2*v),axis=-1)
        v=.35+.22*np.cos(2*np.pi*phase/6.1)
        return np.stack((.2*v,.6*v,v),axis=-1)

    errors={"dominant_layer_motion":[],"minority_layer_motion":[],"coverage_mean_motion":[],"oracle_per_layer_motion":[]}
    current_energy=[];observation_innovation=[]
    single_velocities={"dominant_layer_motion":velocities[0],"minority_layer_motion":velocities[1],
                       "coverage_mean_motion":float(fraction*velocities[0]+(1-fraction)*velocities[1])}
    for t in range(1,frames):
        truth=fraction*layer(0,xx,t)+(1-fraction)*layer(1,xx,t)
        current_energy.append(truth[mask])
        for name,v in single_velocities.items():
            # All candidate single-motion queries use the same exact analytic
            # previous composite, with no filter or sampler approximation.
            previous=fraction*layer(0,xx-v,t-1)+(1-fraction)*layer(1,xx-v,t-1)
            errors[name].append((previous-truth)[mask])
        oracle=fraction*layer(0,xx-velocities[0],t-1)+(1-fraction)*layer(1,xx-velocities[1],t-1)
        errors["oracle_per_layer_motion"].append((oracle-truth)[mask])
        obs=observe_guides(observed_guides[t],observed_guides[t-1],enabled=True)
        observation_innovation.append(obs.temporal_innovation[mask&obs.temporal_supported])
    denom=float(np.mean(np.concatenate(current_energy)))
    rmse={k:float(np.sqrt(np.mean(np.concatenate(v)**2))/denom) for k,v in errors.items()}
    return {"schema":"job07-analytic-two-layer-motion-v1","stage":"analytic synthetic truth, CPU executed",
            "gpu_executed":False,"frame_ids":list(range(200,200+frames)),"extent":[width,height],
            "crop_origin":[0,0],"fixed_mask_pixels_per_frame":int(mask.sum()),
            "history_frames_evaluated":frames-1,"coverage_fractions":[float(fraction),float(1-fraction)],
            "object_velocities_pixels_per_frame":list(velocities),
            "dominant_guide_motion_uv":[float(mv[0,0,0]),0],
            "rgb_units":"positive linear synthetic radiance","depth_units":"positive synthetic linear scene unit",
            "previous_evaluation":"exact analytic per-layer sample; no bilinear or GPU sampler approximation",
            "normal_material_depth_guides":"identical at every frame; zero category means no semantic claim",
            "normalized_rgb_rmse":rmse,
            "maximum_observable_temporal_innovation":float(np.max(np.concatenate(observation_innovation))),
            "falsifier":"Even analytically correct dominant-layer motion cannot transport both components of an unresolved moving composite.",
            "limitation":"Unresolved constant synthetic 60/40 coverage, not an assertion about a game pixel's coverage rule; no real image improvement claim."}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,default=Path(__file__).resolve().parents[1]/"evidence"/"synthetic_transport_discriminator.json")
    args=p.parse_args()
    result=run_discriminator()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps(result["normalized_rgb_rmse"],allow_nan=False))
