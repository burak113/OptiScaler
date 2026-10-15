"""Local box/zero-DC projection; no image-wide reduction or light source.

Each tile/channel solves min ||x-c||^2, subject to per-pixel RR-derived bounds
and sum(x)=0. Unsupported coordinates have the box {0}, so the projection
cannot create recovery outside measured support. One dark pixel affects only
its own tile, never an unrelated region of the image.
"""
import numpy as np


def tile_view(value,tile):
    h,w,channels = value.shape
    padded = np.pad(value,((0,(-h)%tile),(0,(-w)%tile),(0,0)),mode='constant')
    ph,pw = padded.shape[:2]
    return padded.reshape(ph//tile,tile,pw//tile,tile,channels).transpose(0,2,1,3,4).reshape(-1,tile*tile,channels),(ph,pw)


def project_local_box(correction,lower,upper,mask,tile=8):
    if tile not in (8,16):
        raise ValueError('explicit bounded8/16-pixel research domains only')
    if correction.shape!=lower.shape or correction.shape!=upper.shape or correction.shape!=mask.shape:
        raise ValueError('projection RGB/mask extents must agree')
    if not np.isfinite(correction).all() or not np.isfinite(lower).all() or not np.isfinite(upper).all():
        raise ValueError('finite candidate/bounds required')
    if np.any(lower>0) or np.any(upper<0) or np.any(lower>upper):
        raise ValueError('every interval must include unchanged RR (zero correction)')
    shape = correction.shape
    c,padded = tile_view(np.where(mask,correction,0).astype(np.float32),tile)
    lo,_ = tile_view(np.where(mask,lower,0).astype(np.float32),tile)
    hi,_ = tile_view(np.where(mask,upper,0).astype(np.float32),tile)
    left,right = np.min(c-hi,axis=1),np.max(c-lo,axis=1)
    for _ in range(32):
        middle = (left+right)*np.float32(.5)
        candidate = np.minimum(np.maximum(c-middle[:,None,:],lo),hi)
        total = np.sum(candidate,axis=1,dtype=np.float32)
        positive,zero = total>0,total==0
        left = np.where(zero,middle,np.where(positive,middle,left))
        right = np.where(zero,middle,np.where(positive,right,middle))
    middle = (left+right)*np.float32(.5)
    projected = np.minimum(np.maximum(c-middle[:,None,:],lo),hi)
    ph,pw = padded
    result = projected.reshape(ph//tile,pw//tile,tile,tile,shape[2]).transpose(0,2,1,3,4).reshape(ph,pw,shape[2])
    result = result[:shape[0],:shape[1]]
    return result,dict(bound_projection='local_box_zero_dc',projection_tile=tile,
        projection_iterations=32,uniform_bound_scale=None,
        projection_max_tile_dc_residual=float(np.max(np.abs(np.sum(projected,axis=1,dtype=np.float64)))),
        projection_clipped_component_fraction=float(np.mean((projected==lo)|(projected==hi))))
