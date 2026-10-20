"""Analytic scenes and one-mechanism synthetic interventions; never AMD RR.

The generator exposes oracle arrays only as declared analytic witnesses. The
noise seed and trajectory holdout are frozen in synthetic_experiments.py.
No measured game tensor is replaced by a synthetic one.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, replace
import numpy as np
from support_tracer import previous_coordinates, sample_previous


@dataclass(frozen=True)
class SceneConfig:
    frames: int = 24
    width: int = 80
    height: int = 56
    trajectory: str = "straight"
    noise_family: str = "gaussian"
    camera: str = "static"
    rotating: bool = True
    moving_crop: bool = True
    thin: bool = False
    light_step: float = 1.0
    hit_distance: float = 2.0
    opaque: bool = False


CAUSES = ("clean", "source_delay", "mv_bias", "jitter_error", "sparse_source",
          "virtual_mismatch", "provider_tail", "selected_tail", "exposure_only",
          "wrong_guide", "missing_geometry", "zero_hit_distance")


def _bottle(u, v, thin=False):
    if thin:
        return (np.abs(u) < .55) & (v >= -13) & (v <= 12)
    body=(np.abs(u)<4.0)&(v>=-5)&(v<=12)
    shoulder=(v>=-9)&(v<-5)&(np.abs(u)<(2+(v+9)*.5))
    neck=(np.abs(u)<2)&(v>=-14)&(v<-9)
    return body|shoulder|neck


def _warp(frame, motion, origin, old_origin, extent):
    qx,qy,_=previous_coordinates(motion,origin,old_origin,extent,frame.shape)
    value,valid=sample_previous(frame,qx,qy)
    return np.where(valid[...,None],value,0) if frame.ndim==3 else np.where(valid,value,0),valid


def make_scene(config=SceneConfig(), seed=100, cause="clean"):
    if cause not in CAUSES:
        raise ValueError("Unknown isolated cause")
    n,h,w=config.frames,config.height,config.width
    if n<4 or h<32 or w<40:
        raise ValueError("Scene too small for declared controls")
    rng=np.random.default_rng(seed)
    tt=np.arange(n,dtype=float)
    origin=np.tile(np.array([40.,22.]),(n,1))
    if config.moving_crop:
        origin[:,0]+=np.round(3*np.sin(tt*.23));origin[:,1]+=np.round(2*np.cos(tt*.19))
    extent=np.array([160,100],int)
    if config.trajectory=="straight":
        tx=-17+tt*1.35;ty=1.5*np.sin(tt*.1)
    elif config.trajectory=="slow":
        tx=-7+tt*.4;ty=np.zeros(n)
    elif config.trajectory=="fast":
        tx=-34+tt*3.0;ty=np.zeros(n)
    elif config.trajectory=="static":
        tx=np.zeros(n);ty=np.zeros(n)
    elif config.trajectory=="curved_reentry":
        phase=2*np.pi*tt/(n-1)
        tx=53*np.sin(phase-.6);ty=7*np.cos(phase+.3)
    else: raise ValueError("Undeclared trajectory")
    camera=np.zeros((n,2),float)
    if config.camera=="moving":
        camera=np.c_[tt*.55,2*np.sin(tt*.17)]
    elif config.camera!="static": raise ValueError("Undeclared camera")
    theta=.15*np.sin(tt*.17) if config.rotating else np.zeros(n)
    centre=np.c_[80+tx,50+ty]-camera
    velocity=np.vstack([np.zeros(2),np.diff(centre,axis=0)])
    # Reflected feature travels relative to the surface. This is a synthetic
    # apparent correspondence, not a formula derived from real hit distance.
    stripe_u=2.6*np.sin(tt*.58)
    feature_centre=centre+np.c_[np.cos(theta)*stripe_u,np.sin(theta)*stripe_u]
    feature_velocity=np.vstack([np.zeros(2),np.diff(feature_centre,axis=0)])
    yy,xx=np.mgrid[:h,:w]
    mask=np.zeros((n,h,w),bool);virtual_mask=np.zeros_like(mask)
    geometry=np.empty((n,h,w,3),np.float32)
    virtual_geometry=np.empty_like(geometry)
    depth=np.empty((n,h,w),np.float32)
    normal=np.empty((n,h,w,3),np.float32)
    truth=np.zeros((n,h,w),np.float32);spec=np.zeros_like(truth)
    background=np.zeros_like(truth);detail_mask=np.zeros_like(mask)
    oracle_motion=np.zeros((n,h,w,4),np.float32)
    virtual_motion=oracle_motion.copy()
    light=np.where(tt>=n//2,config.light_step,1.).astype(np.float32)
    for t in range(n):
        x=xx+origin[t,0];y=yy+origin[t,1]
        dx=x-centre[t,0];dy=y-centre[t,1]
        c,s=np.cos(theta[t]),np.sin(theta[t])
        u=c*dx+s*dy;v=-s*dx+c*dy
        m=_bottle(u,v,config.thin);mask[t]=m
        reflection=m&(np.abs(u-stripe_u[t])<.9);virtual_mask[t]=reflection
        # A constant-colour opaque object is available without varying albedo.
        texture=np.ones((h,w)) if config.opaque else (1+.12*np.cos(v*1.9))
        truth[t]=m*light[t]*texture
        spec[t]=m*light[t]*(.4+reflection*.8) if not config.opaque else 0
        world_x=x+camera[t,0];world_y=y+camera[t,1]
        text=(world_x>=44)&(world_x<67)&(world_y>=28)&(world_y<38)
        ink=text & ((np.floor(world_x).astype(int)%4==0)|(np.floor(world_y).astype(int)%5==0))
        background[t]=.015+ink*.12+(np.floor(world_x)%19==0)*.025
        detail_mask[t]=text&~m
        # Independent identity field: local object coordinates or world wall
        # coordinates. The third component is a discrete surface identifier.
        geometry[t,:,:,0]=np.where(m,u,world_x)
        geometry[t,:,:,1]=np.where(m,v,world_y)
        geometry[t,:,:,2]=m
        virtual_geometry[t,:,:,0]=np.where(m,u-stripe_u[t],world_x)
        virtual_geometry[t,:,:,1]=np.where(m,v,world_y)
        virtual_geometry[t,:,:,2]=m
        depth[t]=np.where(m,2.,7.)
        normal[t]=[0,0,1]
        normal[t,m]=[.25*np.sin(theta[t]),0,np.sqrt(1-(.25*np.sin(theta[t]))**2)]
        if t:
            cp,sp=np.cos(theta[t-1]),np.sin(theta[t-1])
            px=centre[t-1,0]+cp*u-sp*v
            py=centre[t-1,1]+sp*u+cp*v
            wall_x=x+camera[t,0]-camera[t-1,0]
            wall_y=y+camera[t,1]-camera[t-1,1]
            oracle_motion[t,:,:,0]=np.where(m,px-x,wall_x-x)/extent[0]
            oracle_motion[t,:,:,1]=np.where(m,py-y,wall_y-y)/extent[1]
            virtual_motion[t]=oracle_motion[t]
            shift=stripe_u[t-1]-stripe_u[t]
            virtual_motion[t,:,:,0]+=np.where(m,cp*shift/extent[0],0)
            virtual_motion[t,:,:,1]+=np.where(m,sp*shift/extent[1],0)
    # Physical background disocclusion in current coordinates. Object-surface
    # MVs cannot identify which prior wall point was hidden. Use the separately
    # known analytic wall/camera correspondence and preserve crop validity.
    disocclusion=np.zeros_like(mask)
    for t in range(1,n):
        wall_motion=np.zeros((h,w,4),np.float32)
        wall_motion[...,:2]=(camera[t]-camera[t-1])/extent
        previous_support,valid=_warp(mask[t-1].astype(float),wall_motion,origin[t],origin[t-1],extent)
        disocclusion[t]=valid & ~mask[t] & (previous_support>.5)
    raw=truth.copy();raw_spec=spec.copy()
    if config.noise_family=="gaussian":
        noise=np.maximum(0,1+rng.normal(0,.025,size=truth.shape))
    elif config.noise_family=="salt_poisson":
        noise=rng.poisson(5.,size=truth.shape)/5.
        noise*=np.where(rng.random(truth.shape)<.02,3.,1.)
    else: raise ValueError("Undeclared noise family")
    raw*=noise;raw_spec*=noise
    if cause=="sparse_source":
        sample=rng.random(truth.shape)<.32
        raw*=sample/.32;raw_spec*=sample/.32
    if cause=="source_delay":
        for t in range(2,n):
            raw[t],_=_warp(truth[t-2],np.zeros((h,w,4)),origin[t],origin[t-2],extent)
            raw_spec[t],_=_warp(spec[t-2],np.zeros((h,w,4)),origin[t],origin[t-2],extent)
            raw[t]*=noise[t];raw_spec[t]*=noise[t]
    observed_motion=oracle_motion.copy()
    if cause=="mv_bias":
        observed_motion[1:,:,:,0]+=2.5/extent[0]
    if cause=="jitter_error":
        observed_motion[1:,:,:,0]+=(np.where(tt[1:]%2==0,1.1,-1.1)/extent[0])[:,None,None]
    observed_virtual=virtual_motion.copy()
    if cause=="virtual_mismatch": observed_virtual=oracle_motion.copy()
    rr=raw.copy();rr_spec=raw_spec.copy()
    selected=rr.copy();selected_spec=rr_spec.copy()
    for t in range(1,n):
        if cause in ("mv_bias","jitter_error"):
            prior,_=_warp(truth[t-1],observed_motion[t],origin[t],origin[t-1],extent)
            rr[t]=.55*raw[t]+.45*prior
        if cause=="virtual_mismatch":
            prior,_=_warp(spec[t-1],observed_virtual[t],origin[t],origin[t-1],extent)
            rr_spec[t]=.55*raw_spec[t]+.45*prior
        if cause=="provider_tail":
            prior_t=max(0,t-2)
            prior,_=_warp(truth[prior_t],np.zeros((h,w,4)),origin[t],origin[prior_t],extent)
            rr[t]=.55*raw[t]+.45*prior
    selected=rr.copy();selected_spec=rr_spec.copy()
    if cause=="selected_tail":
        for t in range(1,n):
            prior_t=max(0,t-2)
            prior,_=_warp(truth[prior_t],np.zeros((h,w,4)),origin[t],origin[prior_t],extent)
            selected[t]=.55*rr[t]+.45*prior
    if cause=="exposure_only": selected*=.65;selected_spec*=.65
    geometry_observed=geometry.copy()
    if cause=="wrong_guide":
        # Same numerical symptom as transport error, but the independently
        # declared guide-authority flag is withheld. The cause is unidentifiable.
        geometry_observed[1:,:,:,0]+=1.3*np.where(tt[1:]%2==0,1,-1)[:,None,None]
    hit=np.full_like(truth,config.hit_distance)
    if cause=="zero_hit_distance": hit.fill(0)
    # Renderer alpha is a separate immutable payload. Nothing treats it as view Z.
    alpha=hit.astype(np.float16)
    return {"config":asdict(config),"cause":cause,"seed":int(seed),
            "frame_indices":np.arange(100,100+n,dtype=np.int32),"crop_origins":origin,
            "render_extent":extent,"centres_local":centre-origin,"velocity":velocity,
            "feature_centres_local":feature_centre-origin,"feature_velocity":feature_velocity,
            "motion":observed_motion,"oracle_motion":oracle_motion,
            "virtual_motion":observed_virtual,"oracle_virtual_motion":virtual_motion,
            "geometry":geometry_observed,"oracle_geometry":geometry,"virtual_geometry":virtual_geometry,
            "depth":depth,"normal":normal,"hit_distance":hit,"alpha":alpha,
            "truth":truth,"truth_specular":spec,"truth_mask":mask,
            "virtual_feature_mask":virtual_mask,"detail_mask":detail_mask,"disocclusion_mask":disocclusion,
            "background":background,"raw":raw,"raw_specular":raw_spec,
            "raw_rr":rr,"raw_rr_specular":rr_spec,"selected":selected,
            "selected_specular":selected_spec,"light":light,
            "independent_geometry":cause!="missing_geometry",
            "guide_authority":cause!="wrong_guide",
            "known_support":cause!="missing_geometry"}


def intervene(scene, mechanism):
    """Change exactly one declared diagnostic input. Never a production fix."""
    out=dict(scene)
    if mechanism=="oracle_motion": out["motion"]=scene["oracle_motion"].copy()
    elif mechanism=="oracle_support":
        # Explicit oracle replaces source support while retaining declared light;
        # downstream stored observations are intentionally not recomputed.
        out["raw"]=scene["truth"].copy()
        out["raw_specular"]=scene["truth_specular"].copy()
    elif mechanism=="current_input_only":
        out["raw_rr"]=scene["raw"].copy();out["selected"]=scene["raw"].copy()
        out["raw_rr_specular"]=scene["raw_specular"].copy();out["selected_specular"]=scene["raw_specular"].copy()
    elif mechanism=="observe_raw_instead_selected": out["selected"]=scene["raw_rr"].copy()
    elif mechanism=="oracle_virtual": out["virtual_motion"]=scene["oracle_virtual_motion"].copy()
    else: raise ValueError("Unknown single-mechanism intervention")
    out["diagnostic_intervention"]=mechanism
    return out
