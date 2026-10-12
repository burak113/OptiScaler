"""Offline RR-scale downsampling hypotheses; NOT a production RRResolutionScale option.

The shipping path uses NON_GAMMA_ALBEDO. Qs/Qd are linear UNORM guides, not sqrt encoded.
This focused half-grid prototype crops odd edge rows exactly like the prior hr.py experiment.
"""
import numpy as np


def normals(packed):
    p=packed.astype(np.uint32)
    x=(p&1023).astype(np.float32)/1023*2-1;y=((p>>10)&1023).astype(np.float32)/1023*2-1
    z=1-np.abs(x)-np.abs(y)
    xx=np.where(z<0,(1-np.abs(y))*np.where(x>=0,1,-1),x)
    yy=np.where(z<0,(1-np.abs(x))*np.where(y>=0,1,-1),y)
    n=np.stack([xx,yy,z],-1).astype(np.float32)
    return n/np.maximum(np.linalg.norm(n,axis=-1,keepdims=True),1e-8)


def down_half(depth,packed,motion,qs,qd,u,v, *, energy=True, material_priority=True, roughness_squared=True):
    H,W=depth.shape;h,w=H//2,W//2
    def blocks(a):
        return a[:2*h,:2*w].reshape(h,2,w,2,*a.shape[2:]).swapaxes(1,2).reshape(h,w,4,*a.shape[2:])
    D=blocks(depth);P=blocks(packed);IDs=P>>30
    target=np.max(np.where(IDs==1,2,np.where(IDs==3,1,0)),axis=-1)
    allowed=np.where(target[...,None]==2,IDs==1,np.where(target[...,None]==1,IDs==3,True)) if material_priority else np.ones_like(D,bool)
    median=np.median(D,axis=-1,keepdims=True)
    scores=np.where(allowed,np.abs(D-median),np.inf)
    rep=np.argmin(scores,axis=-1)
    def take(a):
        B=blocks(a);index=rep[...,None,*([None]*(a.ndim-2))]
        return np.take_along_axis(B,index,axis=2)[:,:,0].copy()
    drep=take(depth);nrep=take(normals(packed))
    same=(np.abs(D-drep[...,None])<=.02*np.maximum(np.abs(drep[...,None]),1e-3))&\
         ((blocks(normals(packed))*nrep[...,None,:]).sum(-1)>.9)
    if material_priority:same&=IDs==(take(packed)>>30)[...,None]
    weights=same.astype(np.float32)[...,None]
    count=np.maximum(weights.sum(2),1)
    def avg(a):return (blocks(a).astype(np.float32)*weights).sum(2)/count
    def lobe(signal,guide):
        result=take(signal).astype(np.float32)
        mean_q=avg(guide[...,:3].astype(np.float32)/255)
        if energy:
            mean_raw=avg(signal[...,:3].astype(np.float32)*(guide[...,:3].astype(np.float32)/255))
            result[...,:3]=np.divide(mean_raw,mean_q,out=np.zeros_like(mean_raw),where=mean_q>0)
        else:result[...,:3]=avg(signal[...,:3])
        g=np.rint(avg(guide)).clip(0,255).astype(np.uint8)
        return result.astype(np.float16),g
    uh,qsh=lobe(u,qs);vh,qdh=lobe(v,qd);ph=take(packed).astype(np.uint32)
    if roughness_squared:
        rough=((P>>20)&1023).astype(np.float32)/1023
        r=np.sqrt((rough*rough*weights[...,0]).sum(2)/count[...,0])
        code=np.rint(r*1023).astype(np.uint32)
        ph=(ph&np.uint32(~(1023<<20)&0xffffffff))|(code<<20)
    return drep,ph,take(motion),qsh,qdh,uh,vh,float(same.mean())


def guided_up_half(low,depth_low,packed_low,depth_high,packed_high, *, material=True):
    h,w,c=low.shape;H,W=depth_high.shape
    y=(np.arange(H)+.5)/2-.5;x=(np.arange(W)+.5)/2-.5
    y0=np.clip(np.floor(y).astype(int),0,h-1);x0=np.clip(np.floor(x).astype(int),0,w-1)
    y1=np.minimum(y0+1,h-1);x1=np.minimum(x0+1,w-1)
    fy=np.clip(y-y0,0,1)[:,None];fx=np.clip(x-x0,0,1)[None,:]
    Nh=normals(packed_high);Nl=normals(packed_low)
    total=np.zeros((H,W,c),np.float32);wsum=np.zeros((H,W),np.float32)
    best=np.full((H,W),np.inf,np.float32);nearest=np.zeros_like(total)
    for yy,wy in ((y0,1-fy),(y1,fy)):
        for xx,wx in ((x0,1-fx),(x1,fx)):
            dl=depth_low[np.ix_(yy,xx)];nl=Nl[np.ix_(yy,xx)];values=low[np.ix_(yy,xx)]
            rel=np.abs(dl-depth_high)/np.maximum(np.abs(depth_high),1e-3)
            same=(packed_low[np.ix_(yy,xx)]>>30)==(packed_high>>30)
            weight=(wy*wx)*np.exp(-(rel/.02)**2)*np.clip((Nh*nl).sum(-1),0,1)**8
            if material:weight*=same
            total+=weight[...,None]*values;wsum+=weight
            score=rel+(0 if not material else (~same)*100)
            closer=score<best;best=np.minimum(best,score);nearest=np.where(closer[...,None],values,nearest)
    return np.where((wsum>1e-4)[...,None],total/np.maximum(wsum,1e-6)[...,None],nearest),float((wsum<=1e-4).mean())
