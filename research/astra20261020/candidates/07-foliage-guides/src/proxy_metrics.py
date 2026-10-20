"""Transparent CPU surrogate and truth-aware scoring, never an AMD RR model.

The main candidate is an observer and leaves RGB untouched. A hypothetical
cosine-weight consumer is tested separately. Oracle buffers intentionally expose
hidden-layer lighting; this privilege is stated and cannot be used in production.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from foliage_guides import (bilinear_coordinates, sample_bilinear, normalize,
                            unpack_normal_roughness, observe_guides)
from synthetic_scene import SyntheticScene


@dataclass
class ProxyOutput:
    rgb: np.ndarray
    history_weight: np.ndarray
    coverage_mismatch: np.ndarray
    layer_leakage: np.ndarray


def spatial_proxy(rgb: np.ndarray, normal: np.ndarray, depth: np.ndarray,
                  coverage_for_metrics: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """A fixed 3x3 joint filter with normal cosine^32 and 2% depth gate.

    Truth coverage is used ONLY to meter leakage, never to compute weights.
    Material codes are all zero in these synthetic constructions.
    """
    h,w=depth.shape
    total=np.zeros_like(rgb,dtype=np.float32);denom=np.zeros((h,w),np.float32)
    leak=np.zeros((h,w),np.float32)
    for dy in (-1,0,1):
        for dx in (-1,0,1):
            ys,xs=slice(max(0,dy),min(h,h+dy)),slice(max(0,dx),min(w,w+dx))
            yn,xn=slice(max(0,-dy),min(h,h-dy)),slice(max(0,-dx),min(w,w-dx))
            cosine=np.clip(np.sum(normal[ys,xs]*normal[yn,xn],axis=-1),0,1)
            dz=np.abs(depth[ys,xs]-depth[yn,xn])
            support=dz<=.02*np.maximum(np.maximum(depth[ys,xs],depth[yn,xn]),1e-6)
            weight=cosine**32*support*(1 if dx==0 and dy==0 else .65)
            total[ys,xs]+=rgb[yn,xn]*weight[...,None];denom[ys,xs]+=weight
            if coverage_for_metrics is not None:
                mismatch=.5*np.abs(coverage_for_metrics[ys,xs]-coverage_for_metrics[yn,xn]).sum(axis=-1)
                leak[ys,xs]+=weight*mismatch
    return total/np.maximum(denom[...,None],1e-20),leak/np.maximum(denom,1e-20)


def _transport(current, previous, normals: np.ndarray, previous_normals: np.ndarray,
               rgb_history: np.ndarray, previous_coverage: np.ndarray | None = None):
    h,w=current.depth.shape
    taps,inside=bilinear_coordinates(h,w,current.motion[...,:2],current.render_extent,
                                     current.crop_origin,previous.crop_origin,previous.depth.shape)
    history=sample_bilinear(rgb_history,taps)
    pd=sample_bilinear(previous.depth,taps)
    pn=normalize(sample_bilinear(previous_normals,taps))
    predicted=current.depth+current.motion[...,2].astype(np.float32)
    support=inside&(current.depth>0)&(pd>0)&(np.abs(pd-predicted)<=.02*np.maximum(np.maximum(pd,predicted),1e-6))
    support&=np.sum(normals*pn,axis=-1)>=.75
    pc=sample_bilinear(previous_coverage,taps) if previous_coverage is not None else None
    return history,support,pc


def run_proxy(scene: SyntheticScene, mode: str) -> ProxyOutput:
    tcount,h,w=scene.observed.shape[:3]
    zeros=np.zeros((tcount,h,w),np.float32)
    if mode in ("raw_half_inputs", "diagnostic_identity"):
        return ProxyOutput(scene.observed.copy(),zeros.copy(),zeros.copy(),zeros.copy())
    if mode in ("oracle_layer_guides_single_motion", "oracle_layer_guides_layer_motion"):
        return _oracle_proxy(scene,mode.endswith("layer_motion"))
    allowed=("single_dominant_guide", "perfect_unquantized_dominant_guide", "flattened_normals",
             "misdecoded_normals", "cosine_support_consumer")
    if mode not in allowed:
        raise ValueError(mode)
    normals=np.stack([unpack_normal_roughness(g.packed_normal_roughness)[0] for g in scene.frames])
    if mode=="perfect_unquantized_dominant_guide":
        normals=scene.exact_dominant_normal
    elif mode=="flattened_normals":
        normals=np.zeros_like(normals);normals[...,2]=1
    elif mode=="misdecoded_normals":
        # Deliberate false XYZ-UNORM interpretation of oct-RG + roughness-B.
        words=np.stack([g.packed_normal_roughness for g in scene.frames])
        normals=normalize(np.stack([(words&1023)/1023,((words>>10)&1023)/1023,
                                     ((words>>20)&1023)/1023],axis=-1).astype(np.float32)*2-1)
    out=np.zeros_like(scene.observed);hw=zeros.copy();cm=zeros.copy();leak=zeros.copy()
    for t,g in enumerate(scene.frames):
        spatial,spatial_leak=spatial_proxy(scene.observed[t],normals[t],g.depth,scene.coverage[t])
        if t==0:
            out[t]=spatial;leak[t]=spatial_leak;continue
        hist,valid,prevcov=_transport(g,scene.frames[t-1],normals[t],normals[t-1],out[t-1],scene.coverage[t-1])
        weight=valid.astype(np.float32)*.8
        if mode=="cosine_support_consumer":
            obs=observe_guides(g,scene.frames[t-1],enabled=True)
            weight*=obs.experimental_history_multiplier
        hw[t]=weight
        cm[t]=.5*np.abs(scene.coverage[t]-prevcov).sum(axis=-1)
        out[t]=spatial*(1-weight[...,None])+hist*weight[...,None]
        leak[t]=spatial_leak*(1-weight)+weight*cm[t]
    return ProxyOutput(out,hw,cm,leak)


def _oracle_proxy(scene: SyntheticScene, per_layer_motion: bool) -> ProxyOutput:
    tcount,h,w,layers=scene.coverage.shape
    result=np.zeros_like(scene.observed)
    history=np.zeros((h,w,layers,3),np.float32)
    weights=np.zeros((tcount,h,w),np.float32)
    for t,g in enumerate(scene.frames):
        for layer in range(layers):
            current=scene.layer_observed[t,...,layer,:]
            spatial,_=spatial_proxy(current,scene.layer_normal[t,...,layer,:],scene.layer_depth[t,...,layer])
            if t:
                uv=scene.layer_motion_uv[t,...,layer,:] if per_layer_motion else g.motion[...,:2].astype(np.float32)
                taps,valid=bilinear_coordinates(h,w,uv,g.render_extent,g.crop_origin,scene.frames[t-1].crop_origin,(h,w))
                prev=sample_bilinear(history[...,layer,:],taps)
                pd=sample_bilinear(scene.layer_depth[t-1,...,layer],taps)
                nd=scene.layer_depth[t,...,layer]
                valid&=(nd>0)&(pd>0)&(np.abs(pd-nd)<=.02*np.maximum(np.maximum(pd,nd),1e-6))
                weight=.8*valid.astype(np.float32)
                filtered=spatial*(1-weight[...,None])+prev*weight[...,None]
                weights[t]+=scene.coverage[t,...,layer]*weight
            else:
                filtered=spatial
            history[...,layer,:]=filtered
            # Recompose with CURRENT exact coverage. A composite history with a
            # single guide cannot perform this privileged per-layer operation.
            result[t]+=scene.coverage[t,...,layer,None]*filtered
    zeros=np.zeros((tcount,h,w),np.float32)
    return ProxyOutput(result,weights,zeros.copy(),zeros.copy())


def luma(rgb: np.ndarray) -> np.ndarray:
    return rgb@np.array([.2126,.7152,.0722],np.float32)


def _masked_mean(a: np.ndarray,m: np.ndarray) -> float | None:
    return float(np.asarray(a)[m].mean()) if np.any(m) else None


def gradient_transfer(truth: np.ndarray, output: np.ndarray, mask: np.ndarray) -> float | None:
    """Both spatial axes contribute; a constant truth has no detail denominator."""
    covariance=0.0;energy=0.0
    for axis in (1,2):
        gt=np.diff(truth,axis=axis);go=np.diff(output,axis=axis)
        if axis==1:
            gm=mask[:,1:,:]&mask[:,:-1,:]
        else:
            gm=mask[:,:,1:]&mask[:,:,:-1]
        covariance+=float(np.sum((gt*go)[gm],dtype=np.float64))
        energy+=float(np.sum((gt*gt)[gm],dtype=np.float64))
    return covariance/energy if energy>1e-12 else None


def metrics(scene: SyntheticScene,result: ProxyOutput) -> dict:
    truth=luma(scene.truth);out=luma(result.rgb);error=out-truth
    mask=scene.masks["interior"]
    denom=max(float(truth[mask].mean()),1e-8)
    hp=error.copy()
    hp[:,1:-1,1:-1]=error[:,1:-1,1:-1]-.25*(error[:,1:-1,:-2]+error[:,1:-1,2:]+error[:,:-2,1:-1]+error[:,2:,1:-1])
    transfer=gradient_transfer(truth,out,mask)
    edge=scene.masks["edge"]
    rigid=scene.masks["rigid_background"]
    rigid_transfer=gradient_transfer(truth,out,rigid)
    temporal_mask=mask[1:]&mask[:-1]
    flicker=float(np.sqrt(np.mean(np.diff(error,axis=0)[temporal_mask]**2))/denom)
    mixed=scene.masks["mixed_coverage"]
    edge_error=float(np.sqrt(np.mean(error[edge]**2))/denom) if np.any(edge) else None
    coverage_projection=[]
    if np.any(mixed):
        bg=scene.layer_truth[...,0,:]
        leaf_mean=(scene.layer_truth[...,1,:]+scene.layer_truth[...,2,:])*.5
        direction=leaf_mean-bg
        residual=result.rgb-scene.truth
        projection=np.abs(np.sum(residual*direction,axis=-1)/np.maximum(np.sum(direction*direction,axis=-1),.02))
        coverage_projection=float(projection[mixed].mean())
    else:
        coverage_projection=None
    false=(result.history_weight>.5)&(result.coverage_mismatch>.2)
    # Every output uses the SAME truth-derived masks and scalar denominator.
    grain=float(np.sqrt(np.mean(hp[mask]**2))/denom)
    sparkle=float(np.quantile(np.abs(error[mask]),.99)/denom)
    detail_loss=max(0.0,1-transfer) if transfer is not None else None
    return {"mean_truth_luma":denom,"relative_bias":float(error[mask].mean()/denom),
            "rmse_normalized":float(np.sqrt(np.mean(error[mask]**2))/denom),
            "grain_highpass_rms":grain,"sparkle_abs_error_p99":sparkle,
            "sparkle_event_fraction":float((np.abs(error[mask])>.75*denom).mean()),
            "flicker_residual_difference_rms":flicker,
            "edge_error_normalized":edge_error,"coverage_projection_mae_proxy":coverage_projection,
            "detail_gradient_transfer":transfer,"rigid_detail_gradient_transfer":rigid_transfer,
            "false_history_support_fraction":float(false[mask].mean()),
            "history_coverage_mismatch_weight":float((result.history_weight*result.coverage_mismatch)[mask].mean()),
            "cross_layer_mixing_weight":float(result.layer_leakage[mask].mean()),
            "motion_region_error_normalized":(_masked_mean(np.abs(error)/denom,scene.masks["motion_change"])),
            "fixed_score_lower_better":(grain+2*sparkle+flicker+4*detail_loss if detail_loss is not None else None),
            "detail_loss_gate_pass":(bool(transfer>=.95) if transfer is not None else None),
            "mask_pixels":int(mask.sum())}


def paired_light_response(step: SyntheticScene,step_output: ProxyOutput,
                          no_step: SyntheticScene,no_step_output: ProxyOutput) -> float | None:
    start=step.config.frames//2;stop=min(start+4,step.config.frames)
    mask=step.masks["interior"][start:stop]
    td=luma(step.truth[start:stop]-no_step.truth[start:stop])
    od=luma(step_output.rgb[start:stop]-no_step_output.rgb[start:stop])
    denom=float(td[mask].sum())
    return float(od[mask].sum()/denom) if denom>1e-8 else None


def auc_with_ties(scores: np.ndarray,labels: np.ndarray) -> float | None:
    s=np.asarray(scores).ravel();labels=np.asarray(labels).ravel().astype(bool)
    p=int(labels.sum());n=len(labels)-p
    if not p or not n:return None
    order=np.argsort(s,kind="stable");sorted_s=s[order]
    _,first,counts=np.unique(sorted_s,return_index=True,return_counts=True)
    rank=np.empty(len(s),np.float64)
    for a,k in zip(first,counts):rank[order[a:a+k]]=a+(k+1)/2
    return float((rank[labels].sum()-p*(p+1)/2)/(p*n))


def diagnostic_metrics(scene: SyntheticScene) -> dict:
    obs=[observe_guides(g,scene.frames[t-1] if t else None,enabled=True) for t,g in enumerate(scene.frames)]
    spatial=np.stack([x.angular_dispersion for x in obs]);temporal=np.stack([x.temporal_innovation for x in obs])
    support=np.stack([x.temporal_supported for x in obs]);mult=np.stack([x.experimental_history_multiplier for x in obs])
    mask=scene.masks["interior"];truth=scene.masks["mixed_coverage"]
    return {"claim_scope":"guide-domain diagnostic only; no semantic foliage ground truth in captures",
            "spatial_auc_for_synthetic_mixed_coverage":auc_with_ties(spatial[mask],truth[mask]),
            "temporal_auc_for_synthetic_mixed_coverage_on_supported":auc_with_ties(temporal[mask&support],truth[mask&support]),
            "temporal_supported_fraction":float(support[mask].mean()),
            "unsupported_identity_exact":bool(np.all(mult[~support]==1)),
            "spatial_dispersion_mixed_mean":_masked_mean(spatial,truth),
            "spatial_dispersion_rigid_mean":_masked_mean(spatial,scene.masks["rigid_background"]),
            "mean_support_multiplier_on_mixed":_masked_mean(mult,truth),
            "mean_support_multiplier_on_rigid":_masked_mean(mult,scene.masks["rigid_background"]),
            "spatial_dispersion_p99":float(np.quantile(spatial[mask],.99)),
            "temporal_innovation_p99":float(np.quantile(temporal[mask],.99))}
