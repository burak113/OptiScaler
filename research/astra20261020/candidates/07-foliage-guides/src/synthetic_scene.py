"""Known-visibility layered CPU constructions, not claims about game sampling.

RGB is a linear synthetic radiance unit. Depth uses synthetic linear scene units.
Visibility is supersampled opaque geometry; alpha-test and stochastic coverage
are explicit alternative constructions. Per-layer truth is reserved for metrics
and clearly named oracle ablations, never passed to the candidate observer.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import numpy as np
from foliage_guides import GuideFrame, normalize, pack_normal_roughness


@dataclass(frozen=True)
class SceneConfig:
    name: str = "reference"
    family: str = "reference"
    split: str = "development"
    seed: int = 101
    kind: str = "foliage"
    width: int = 40
    height: int = 28
    frames: int = 16
    supersample: int = 4
    thickness: float = .8
    orientation: float = 31.0
    overlap: int = 2
    coverage_fraction: float = .75
    coverage_rule: str = "alpha_test"
    guide_rule: str = "dominant"
    guide_bits: int = 10
    camera_vx: float = .12
    camera_vy: float = -.035
    object_vx: float = .37
    object_vy: float = .09
    phase: float = .13
    noise_rho: float = 0.0
    noise_strength: float = .2
    sparse_probability: float = .04
    light_step: float = 1.1
    jitter_amplitude: float = .35


@dataclass
class SyntheticScene:
    config: SceneConfig
    frames: list[GuideFrame]
    truth: np.ndarray
    observed: np.ndarray
    diffuse_rgba: np.ndarray
    specular_rgba: np.ndarray
    coverage: np.ndarray
    layer_truth: np.ndarray
    layer_observed: np.ndarray
    layer_normal: np.ndarray
    layer_depth: np.ndarray
    layer_motion_uv: np.ndarray
    exact_dominant_normal: np.ndarray
    masks: dict[str, np.ndarray]
    manifest: dict


def _hash_arrays(arrays: dict[str, np.ndarray]) -> str:
    h = hashlib.sha256()
    for key, arr in sorted(arrays.items()):
        a = np.ascontiguousarray(arr)
        h.update(key.encode()); h.update(a.dtype.str.encode())
        h.update(json.dumps(a.shape).encode()); h.update(a.tobytes())
    return h.hexdigest()


def _background(x: np.ndarray, y: np.ndarray, frame: int, light: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # Rigid geometry contains flat-wall texture, narrow raised window frames,
    # repeated block-letter-like strokes, distant window views, and a sky gap.
    sky = y < 2.4
    window = ((x % 13) > 7.0) & ((x % 13) < 11.0) & ((y % 12) > 3.0) & ((y % 12) < 8.0)
    frame_v = (((x % 13) > 6.3) & ((x % 13) <= 7.0)) | (((x % 13) >= 11.0) & ((x % 13) < 11.7))
    frame_h = (((y % 12) > 2.3) & ((y % 12) <= 3.0)) | (((y % 12) >= 8.0) & ((y % 12) < 8.7))
    raised = (frame_v | frame_h) & ~sky
    text = (y > 20) & (y < 25) & (((x % 5) < .8) | ((y % 5) < .8) | (((y % 5) > 2.0) & ((y % 5) < 2.7)))
    texture = .5 + .15*np.sin(2*np.pi*x/2.7)*np.sin(2*np.pi*y/3.1)
    texture = np.where(text, .12, texture)
    albedo = np.stack((texture*.95, texture*.8, texture*.63), axis=-1)
    albedo = np.where(window[..., None], np.array([.07,.13,.22]), albedo)
    albedo = np.where(raised[..., None], np.array([.8,.7,.5]), albedo)
    n = np.zeros(x.shape + (3,), np.float32); n[..., 2] = 1
    n[..., 0] = np.where(frame_v, .8, 0)
    n[..., 1] = np.where(frame_h, -.7, 0)
    n = normalize(n)
    depth = np.where(window, 42.0, np.where(raised, 11.8, 12.0)).astype(np.float32)
    depth = np.where(sky, 0.0, depth)
    lamp = normalize(np.array([.4,.6,1], np.float32))
    diffuse = albedo * (.12 + .88*np.maximum(np.sum(n*lamp, axis=-1), 0))[..., None] * light
    halfv = normalize(lamp + np.array([0,0,1], np.float32))
    spec = (.015+.25*np.maximum(np.sum(n*halfv,axis=-1),0)**28)[...,None] * np.ones(3) * light
    diffuse = np.where(sky[...,None], np.array([.22,.38,.7])*light, diffuse)
    spec = np.where(sky[...,None], 0, spec)
    return diffuse.astype(np.float32), spec.astype(np.float32), n, depth


def generate_scene(config: SceneConfig) -> SyntheticScene:
    c = config
    if c.kind not in ("foliage", "facade") or c.coverage_rule not in ("geometric", "alpha_test", "stochastic"):
        raise ValueError("unsupported synthetic construction")
    coverage_rng = np.random.default_rng(np.random.SeedSequence([c.seed,1]))
    guide_rng = np.random.default_rng(np.random.SeedSequence([c.seed,2]))
    noise_rng = np.random.default_rng(np.random.SeedSequence([c.seed,3]))
    tcount,h,w,s,layers = c.frames,c.height,c.width,c.supersample,3
    oy,ox = np.meshgrid((np.arange(s)+.5)/s-.5,(np.arange(s)+.5)/s-.5,indexing="ij")
    yy,xx = np.indices((h,w),np.float32)
    bx,by = xx[...,None]+ox.ravel(), yy[...,None]+oy.ravel()
    shape = (tcount,h,w,layers)
    coverage = np.zeros(shape,np.float32)
    layer_truth = np.zeros(shape+(3,),np.float32)
    layer_d = np.zeros(shape+(3,),np.float32)
    layer_s = np.zeros(shape+(3,),np.float32)
    layer_normal = np.zeros(shape+(3,),np.float32)
    layer_depth = np.zeros(shape,np.float32)
    layer_motion = np.zeros(shape+(2,),np.float32)
    dominant_normals = np.zeros((tcount,h,w,3),np.float32)
    guides=[]
    # Jitter is a known synthetic sample-phase trajectory; it is neither object
    # motion nor a promise about a native game's jitter-corrected MV convention.
    jt=np.arange(tcount,dtype=np.float32)
    jitter=np.stack((np.sin(jt*2.399963+c.phase),np.cos(jt*1.618+c.phase)),axis=-1)*c.jitter_amplitude
    light_factors=np.where(jt>=tcount//2,c.light_step,1).astype(np.float32)
    for t in range(tcount):
        wx=bx+c.camera_vx*t+jitter[t,0]
        wy=by+c.camera_vy*t+jitter[t,1]
        bgd,bgs,bgn,bgz=_background(wx,wy,t,float(light_factors[t]))
        sample_d=[bgd]; sample_s=[bgs]; sample_n=[bgn]; sample_z=[bgz]
        visible=[]
        for layer in (1,2):
            theta=np.deg2rad(c.orientation+(layer-1)*59)
            dx=wx-c.object_vx*t*(1 if layer==1 else -.65)
            dy=wy-c.object_vy*t*(1 if layer==1 else -.65)
            card=np.zeros(wx.shape,bool)
            for row in range(4):
                for col in range(5):
                    cx=2.7+col*9.2+(row%2)*3+(layer-1)*1.6
                    cy=3.2+row*7.4+(layer-1)*.7
                    ex,ey=dx-cx,dy-cy
                    u=ex*np.cos(theta)+ey*np.sin(theta)
                    v=-ex*np.sin(theta)+ey*np.cos(theta)
                    card|=(u/4.7)**2+(v/(c.thickness*.5))**2 <= 1
            if c.coverage_rule=="alpha_test":
                # Deterministic binary alpha texture anchored in object space.
                alpha=(np.sin(dx*5.17+dy*7.23+layer)*437.17)%1
                card&=alpha<c.coverage_fraction
            elif c.coverage_rule=="stochastic":
                card&=coverage_rng.random(card.shape)<c.coverage_fraction
            if c.kind=="facade" or c.overlap<layer:
                card[:]=False
            visible.append(card)
            nv=normalize(np.array([.8*np.cos(theta),.8*np.sin(theta),.6],np.float32))
            if layer==2:
                nv=normalize(np.array([-.65,.35,.68],np.float32))
            nn=np.broadcast_to(nv,wx.shape+(3,))
            vein=.5+.5*np.sin(dx*7+dy*2)
            albedo=np.stack((.08+.05*vein,.3+.2*vein,.025+.03*vein),axis=-1)
            lamp=normalize(np.array([.4,.6,1],np.float32))
            dd=albedo*(.12+.88*max(float(np.dot(nv,lamp)),0))*light_factors[t]
            hv=normalize(lamp+np.array([0,0,1],np.float32))
            ss=np.ones_like(dd)*(.008+.12*max(float(np.dot(nv,hv)),0)**20)*light_factors[t]
            sample_d.append(dd.astype(np.float32)); sample_s.append(ss.astype(np.float32));sample_n.append(nn)
            sample_z.append(np.full(wx.shape,5.0 if layer==1 else 7.0,np.float32))
        # Layer 1 is nearer. One known owner per subpixel makes coverage sum 1.
        owner=np.zeros(wx.shape,np.int8)
        owner[visible[1]]=2; owner[visible[0]]=1
        for layer in range(layers):
            m=owner==layer
            cov=m.mean(axis=-1,dtype=np.float32)
            coverage[t,...,layer]=cov
            # Conditional visible-layer averages form an EXACT decomposition of
            # aggregate synthetic lighting; hidden-layer averages fill only
            # oracle buffers and are never candidate inputs.
            denom=np.maximum(m.sum(axis=-1),1)[...,None]
            dvis=(sample_d[layer]*m[...,None]).sum(axis=-2)/denom
            svis=(sample_s[layer]*m[...,None]).sum(axis=-2)/denom
            davg=sample_d[layer].mean(axis=-2);savg=sample_s[layer].mean(axis=-2)
            layer_d[t,...,layer,:]=np.where((cov>0)[...,None],dvis,davg)
            layer_s[t,...,layer,:]=np.where((cov>0)[...,None],svis,savg)
            layer_truth[t,...,layer,:]=layer_d[t,...,layer,:]+layer_s[t,...,layer,:]
            layer_normal[t,...,layer,:]=normalize(sample_n[layer].mean(axis=-2))
            layer_depth[t,...,layer]=sample_z[layer].mean(axis=-1)
            ov=np.array([0,0] if layer==0 else [c.object_vx,c.object_vy],np.float32)*(1 if layer!=2 else -.65)
            mv=np.array([c.camera_vx,c.camera_vy],np.float32)-ov
            if t:
                mv+=jitter[t]-jitter[t-1]
            layer_motion[t,...,layer,:]=mv/np.array([w,h],np.float32)
        if c.guide_rule=="dominant":
            chosen=np.argmax(coverage[t],axis=-1)
        elif c.guide_rule=="sample":
            chosen=owner[...,s*s//2]
        elif c.guide_rule=="stochastic_sample":
            draw=guide_rng.random((h,w))
            chosen=(draw[...,None]>np.cumsum(coverage[t],axis=-1)).sum(axis=-1).clip(0,2)
        else:
            raise ValueError("invalid guide observation rule")
        yi,xi=np.indices((h,w))
        # A plausible single guide observes one actual subpixel of its selected
        # layer. Using an unconditional background mean would confound guide
        # quantization with unlabelled window/sky/frame mixtures.
        witness=np.argmax(owner==chosen[...,None],axis=-1)
        if c.guide_rule=="sample":
            witness=np.full((h,w),s*s//2,np.int64)
        normal=np.zeros((h,w,3),np.float32)
        depth=np.zeros((h,w),np.float32)
        for layer in range(layers):
            nm=sample_n[layer][yi,xi,witness]
            dz=sample_z[layer][yi,xi,witness]
            normal=np.where((chosen==layer)[...,None],nm,normal)
            depth=np.where(chosen==layer,dz,depth)
        dominant_normals[t]=normal
        roughness=np.where(chosen==0,.65,.3).astype(np.float32)
        packed=pack_normal_roughness(normal,roughness,0,c.guide_bits)
        motion=np.zeros((h,w,4),np.float16)
        motion[...,:2]=layer_motion[t,yi,xi,chosen]
        # B=previous minus current linear depth is zero for the translating
        # analytic planes. Occlusion switches do not fabricate a layer MV.
        motion[...,2]=0
        guides.append(GuideFrame(packed,depth.astype(np.float32),motion,1000+t,(0,0),(w,h),True))
    # Positive, unit-mean sparse outlier field with controllable AR(1) persistence.
    # This is a stress model, NOT a ReSTIR or game noise model.
    innovations=noise_rng.standard_normal(shape).astype(np.float32)
    states=np.empty_like(innovations)
    states[0]=innovations[0]
    for t in range(1,tcount):
        states[t]=c.noise_rho*states[t-1]+np.sqrt(1-c.noise_rho**2)*innovations[t]
    tail=(noise_rng.random(shape)<c.sparse_probability).astype(np.float32)
    for t in range(1,tcount):
        persist=noise_rng.random((h,w,layers))<c.noise_rho
        tail[t]=np.where(persist,tail[t-1],tail[t])
    factor=np.exp(c.noise_strength*states-.5*c.noise_strength**2)
    factor*=1+3.5*tail
    factor/=1+3.5*c.sparse_probability
    layer_observed=layer_truth*factor[...,None]
    true_d=(coverage[...,None]*layer_d).sum(axis=-2)
    true_s=(coverage[...,None]*layer_s).sum(axis=-2)
    truth=true_d+true_s
    noisy_d=(coverage[...,None]*layer_d*factor[...,None]).sum(axis=-2)
    noisy_s=(coverage[...,None]*layer_s*factor[...,None]).sum(axis=-2)
    # Preserve a separate native-like alpha for each lobe and perform exactly
    # one disclosed half-store, followed by a float32 D+S sum.
    da=np.broadcast_to(np.float32(3.25),(tcount,h,w,1))
    sa=np.broadcast_to(np.float32(7.5),(tcount,h,w,1))
    drgba=np.concatenate((noisy_d,da),axis=-1).astype(np.float16)
    srgba=np.concatenate((noisy_s,sa),axis=-1).astype(np.float16)
    observed=drgba[...,:3].astype(np.float32)+srgba[...,:3].astype(np.float32)
    lum=truth@np.array([.2126,.7152,.0722],np.float32)
    mixed=(np.max(coverage,axis=-1)<.999)&(np.max(coverage,axis=-1)>.001)
    interior=np.ones((tcount,h,w),bool);interior[:,:2]=False;interior[:,-2:]=False;interior[:,:,:2]=False;interior[:,:,-2:]=False
    edge=np.zeros_like(interior)
    edge[:,:,1:]|=np.abs(np.diff(lum,axis=2))>.04
    edge[:,1:,:]|=np.abs(np.diff(lum,axis=1))>.04
    motion_change=np.zeros_like(interior)
    motion_change[1:]=np.abs(np.diff(coverage,axis=0)).sum(axis=-1)>.1
    masks={"interior":interior,"mixed_coverage":mixed&interior,"edge":edge&interior,
           "rigid_background":(coverage[...,0]>.999)&interior,"motion_change":motion_change&interior}
    manifest={"construction":"synthetic supersampled layered cards, not captured AMD RR",
              "config":asdict(c),"rgb_units":"linear synthetic radiance; D/S half store then float32 sum",
              "depth_units":"synthetic positive linear scene units, not asserted metres",
              "motion_units":"previous-minus-current full-render UV including explicitly modeled sample jitter",
              "normal_space":"synthetic common world space","material_codes":[0],
              "guide_observation":"exact selected-layer subpixel witness, then disclosed quantization; full precision ablation removes only quantization",
              "oracle_layer_guide_scope":"leaf planes exact; background guide is a known layer moment that may contain window/frame/sky samples, not an exact per-sample composite representation",
              "rng_streams":{"coverage":[c.seed,1],"guide_selection":[c.seed,2],"lighting":[c.seed,3]},
              "semantic_labels":"generator visibility truth only; not observer input",
              "frame_ids":list(range(1000,1000+tcount)),"crop_origins":[[0,0]]*tcount,
              "history":"chronological one-pass sequence; no history before first frame; four-tap crop support",
              "supersampling":f"{s}x{s}; discrete known sample coverage, not continuum ground truth",
              "masks_sha256":_hash_arrays(masks),"truth_sha256":_hash_arrays({"truth":truth,"coverage":coverage}),
              "inputs_sha256":_hash_arrays({"D":drgba,"S":srgba,"normal":np.stack([g.packed_normal_roughness for g in guides]),
                                             "depth":np.stack([g.depth for g in guides]),"motion":np.stack([g.motion for g in guides])}),
              "mean_leaf_coverage":float(coverage[...,1:].sum(axis=-1).mean()),
              "mixed_pixel_fraction":float(mixed.mean()),"mask_counts":{k:int(v.sum()) for k,v in masks.items()}}
    for array in [truth,observed,drgba,srgba,coverage,layer_truth,layer_observed,layer_normal,layer_depth,layer_motion,dominant_normals,*masks.values()]:
        array.setflags(write=False)
    for g in guides:
        g.packed_normal_roughness.setflags(write=False);g.depth.setflags(write=False);g.motion.setflags(write=False)
    return SyntheticScene(c,guides,truth,observed,drgba,srgba,coverage,layer_truth,layer_observed,
                          layer_normal,layer_depth,layer_motion,dominant_normals,masks,manifest)


def identical_observations() -> dict:
    """Exact observational collision: dominant guide cannot see minority layers."""
    h,w=8,12
    n=np.zeros((h,w,3),np.float32);n[...,2]=1
    packed=pack_normal_roughness(n,.4,0)
    depth=np.full((h,w),12,np.float32)
    motion=np.zeros((h,w,4),np.float16)
    frames=[GuideFrame(packed.copy(),depth.copy(),motion.copy(),t,(0,0),(w,h),True) for t in (50,51)]
    # A 60% front-facing layer dominates both observations. The unobserved 40%
    # contribution differs in radiance and counter-motion. The guide tensors are
    # byte-identical; no deterministic guide-only statistic can distinguish it.
    plane=np.broadcast_to(np.array([.4,.4,.4],np.float32),(h,w,3)).copy()
    mixture=.6*plane+.4*np.array([.03,.22,.8],np.float32)
    return {"frames":frames,"plane_radiance":plane,"mixture_radiance":mixture,
            "visible_front_fraction":.6,"hidden_motion_pixels":[1.0,-1.0],
            "guide_sha256":_hash_arrays({"packed":packed,"depth":depth,"motion":motion})}
