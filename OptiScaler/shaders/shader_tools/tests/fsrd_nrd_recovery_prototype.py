"""Causal NRD lobe-detail research; no oracle data enters this operator.

Adapted from RecoveryLobe's Laplacian collapse and RecoveryDetail's paired
noisy-minus-RR moments. RR is always the base. Only statistically supported
non-DC bands may be added; no current-noisy blend or low-pass replacement.
Zero roughness is excluded from this ordinary-lobe prototype.
CPU float32 prototype only: native shader parity/cost is not measured yet.
"""
from dataclasses import dataclass
import numpy as np

LUMA = np.array([.2126, .7152, .0722], np.float32)


@dataclass(frozen=True)
class Settings:
    levels: int = 6
    response: float = .03
    sigma: float = 3
    minimum_age: int = 8
    minimum_effective_count: float = 6
    depth_relative_tolerance: float = .02
    normal_dot_minimum: float = .95
    footprint_minimum: float = .75
    anchor: float = 4
    strength: float = 1
    luma_only: bool = False


def down(value, minimum=False):
    height, width = value.shape[:2]
    pad = [(0, height & 1), (0, width & 1)] + [(0, 0)] * (value.ndim - 2)
    padded = np.pad(value, pad, mode='edge')
    taps = np.stack((padded[::2, ::2], padded[1::2, ::2], padded[::2, 1::2], padded[1::2, 1::2]))
    return taps.min(0) if minimum else taps.mean(0, dtype=np.float32)


def up(value, shape):
    height, width = shape
    y = np.clip((np.arange(height, dtype=np.float32) + .5) * .5 - .5, 0, value.shape[0] - 1)
    x = np.clip((np.arange(width, dtype=np.float32) + .5) * .5 - .5, 0, value.shape[1] - 1)
    y0, x0 = np.floor(y).astype(int), np.floor(x).astype(int)
    y1, x1 = np.minimum(y0 + 1, value.shape[0] - 1), np.minimum(x0 + 1, value.shape[1] - 1)
    fy, fx = (y-y0).astype(np.float32), (x-x0).astype(np.float32)
    if value.ndim == 3:
        fy, fx = fy[:, None, None], fx[None, :, None]
    else:
        fy, fx = fy[:, None], fx[None, :]
    return ((1-fy)*((1-fx)*value[y0[:, None], x0] + fx*value[y0[:, None], x1]) +
            fy*((1-fx)*value[y1[:, None], x0] + fx*value[y1[:, None], x1]))


def neighbourhood(value, minimum=False, maximum=False):
    padding = [(1, 1), (1, 1)] + [(0, 0)] * (value.ndim - 2)
    p = np.pad(value, padding, mode='edge')
    h, w = value.shape[:2]
    rows = np.stack([p[y:y+h, x:x+w] for y in range(3) for x in range(3)])
    if minimum:
        return rows.min(0)
    if maximum:
        return rows.max(0)
    return rows.mean(0, dtype=np.float32)


def decode_normals(packed):
    words = np.asarray(packed, np.uint32)
    xy = np.stack((words & 1023, (words >> 10) & 1023), -1).astype(np.float32)/1023*2-1
    z = 1-np.abs(xy).sum(-1)
    folded = (1-np.abs(xy[..., ::-1])) * np.where(xy >= 0, 1, -1)
    normal = np.concatenate((np.where((z < 0)[..., None], folded, xy), z[..., None]), -1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    return normal.astype(np.float32), ((words >> 20) & 1023).astype(np.float32)/1023, (words >> 30).astype(np.uint8)


class Recovery:
    def __init__(self, settings=Settings()):
        self.settings = settings
        self.states = None
        self.last_frame = None
        self.extent = None
        self.last_stats = {}

    def reset(self):
        self.states = None
        self.last_frame = None
        self.extent = None

    def _reproject(self, previous, guide, motion, level, full_extent):
        s = self.settings
        depth, normal, roughness, material, eligible = guide
        h, w = depth.shape
        yy, xx = np.mgrid[:h, :w]
        position = np.stack((xx, yy), -1).astype(np.float32) + motion[..., :2] * np.array(full_extent, np.float32)/(1 << level)
        finite = np.isfinite(position).all(-1) & np.isfinite(motion).all(-1)
        position = np.where(finite[..., None], position, 0)
        base = np.floor(position).astype(int)
        fraction = position-base
        expected = depth+motion[..., 2]
        available = eligible & finite & (motion[..., 3] >= .5)
        total = np.zeros((h, w), np.float32)
        mean = np.zeros((h, w, 3), np.float32)
        second = mean.copy()
        age = np.full((h, w), np.inf, np.float32)
        q = np.zeros((h, w), np.float32)
        for dx, dy in ((0,0), (1,0), (0,1), (1,1)):
            x, y = base[..., 0]+dx, base[..., 1]+dy
            inside = (x >= 0) & (y >= 0) & (x < w) & (y < h)
            x, y = np.clip(x, 0, w-1), np.clip(y, 0, h-1)
            valid = available & inside & (previous['age'][y,x] > 0)
            valid &= np.abs(previous['depth'][y,x]-expected) <= s.depth_relative_tolerance*np.maximum(np.abs(expected), 1e-3)
            valid &= np.sum(previous['normal'][y,x]*normal, -1) > s.normal_dot_minimum
            valid &= (previous['material'][y,x] == material) & (np.abs(previous['roughness'][y,x]-roughness) <= .025)
            tap_mean, tap_variance = previous['mean'][y,x], previous['variance'][y,x]
            valid &= np.isfinite(tap_mean).all(-1) & np.isfinite(tap_variance).all(-1)
            weight = np.where(valid, (fraction[...,0] if dx else 1-fraction[...,0]) *
                                      (fraction[...,1] if dy else 1-fraction[...,1]), 0).astype(np.float32)
            counted = weight > 0
            clean_mean = np.where(counted[...,None], tap_mean, 0)
            clean_variance = np.where(counted[...,None], tap_variance, 0)
            total += weight
            mean += weight[...,None]*clean_mean
            second += weight[...,None]*(clean_variance+clean_mean*clean_mean)
            age = np.minimum(age, np.where(counted, previous['age'][y,x], np.inf))
            q = np.maximum(q, np.where(counted, previous['q'][y,x], 0))
        divisor = np.maximum(total, 1e-20)
        mean /= divisor[...,None]
        variance = np.maximum(second/divisor[...,None]-mean*mean, 0)
        valid = available & (total >= s.footprint_minimum) & np.isfinite(age)
        return mean, variance, np.where(valid, age, 0), q, valid

    def step(self, noisy, denoised, depth, packed_normal, motion, frame, reset=False):
        s = self.settings
        if not np.isfinite(denoised[..., :3]).all() or not np.isfinite(noisy[..., :3]).all():
            raise ValueError('nonfinite lighting must fail before recovery')
        if s.strength <= 0:
            self.reset()
            self.last_stats = dict(correction_rms=0., active_fraction=0., uniform_bound_scale=1.)
            return denoised.copy()
        if reset or self.last_frame is None or frame != self.last_frame+1 or self.extent != depth.shape:
            self.states = None
        h, w = depth.shape
        normal, roughness, material = decode_normals(packed_normal)
        geometry = np.isfinite(depth) & (np.abs(depth) > 1e-5)
        # Ordinary lobe recovery must never use the roughness0 filter-skip path
        # as evidence of successful denoising. Flat recovery is a separate route.
        geometry &= (roughness > 0) & np.isfinite(motion).all(-1) & (motion[...,3] >= .5)
        geometry &= np.isfinite(noisy[...,3]) & (noisy[...,3] > 0)
        near_depth, far_depth = neighbourhood(depth, minimum=True), neighbourhood(depth, maximum=True)
        safe = geometry & ((far_depth-near_depth) <= s.depth_relative_tolerance*np.maximum(np.abs(depth), 1e-3))
        safe &= neighbourhood(material, minimum=True) == neighbourhood(material, maximum=True)
        # Never average a candidate band through a current normal edge merely
        # because the motion/depth planes happen to agree.
        padded_normal = np.pad(normal, ((1,1),(1,1),(0,0)), mode='edge')
        for dy in range(3):
            for dx in range(3):
                safe &= np.sum(normal*padded_normal[dy:dy+h,dx:dx+w], -1) > s.normal_dot_minimum
        residual = noisy[..., :3].astype(np.float32)-denoised[..., :3].astype(np.float32)
        pyramid, masks = [residual], [safe.astype(np.float32)]
        for _ in range(s.levels):
            pyramid.append(down(pyramid[-1]))
            masks.append(down(masks[-1], minimum=True))
        states, corrections, first_age = [], [], None
        for level in range(s.levels):
            observed = pyramid[level]-up(pyramid[level+1], pyramid[level].shape[:2])
            lh, lw = observed.shape[:2]
            scale = 1 << level
            yi = np.minimum(((np.arange(lh)+.5)*scale).astype(int), h-1)
            xi = np.minimum(((np.arange(lw)+.5)*scale).astype(int), w-1)
            sample = np.ix_(yi,xi)
            eligible = (masks[level] > .999) & (up(masks[level+1], (lh,lw)) > .999)
            guide = (depth[sample], normal[sample], roughness[sample], material[sample], eligible)
            current_motion = motion[sample].astype(np.float32)
            if self.states is not None:
                mean, variance, age, q, reuse = self._reproject(self.states[level], guide, current_motion, level, (w,h))
            else:
                mean, variance = np.zeros_like(observed), np.zeros_like(observed)
                age, q, reuse = np.zeros((lh,lw),np.float32), np.ones((lh,lw),np.float32), np.zeros((lh,lw),bool)
            rate = np.maximum(1/(age+1), s.response).astype(np.float32)
            delta = observed-mean
            mean = np.where(reuse[...,None], mean+rate[...,None]*delta, observed)
            variance = np.where(reuse[...,None], (1-rate[...,None])*(variance+rate[...,None]*delta*delta), 0)
            q = np.where(reuse, (1-rate)*(1-rate)*q+rate*rate, 1).astype(np.float32)
            age = np.where(eligible, np.minimum(age+1, 1024), 0).astype(np.float32)
            sem2 = variance*q[...,None]/np.maximum(1-q[...,None], 1e-6)
            active = eligible & (age >= s.minimum_age) & (1/np.maximum(q,1e-12) >= s.minimum_effective_count)
            if s.luma_only:
                value = mean @ LUMA
                sem_luma = (np.sqrt(np.maximum(variance,0)) @ LUMA)**2*q/np.maximum(1-q,1e-6)
                weight = np.maximum(0,1-s.sigma*s.sigma*sem_luma/np.maximum(value*value,1e-20))
                rr = denoised[sample][...,:3].astype(np.float32)
                color = np.maximum(rr,0)/np.maximum((np.maximum(rr,0) @ LUMA)[...,None],1e-12)
                correction = color*(value*weight)[...,None]
            else:
                weight = np.maximum(0,1-s.sigma*s.sigma*sem2/np.maximum(mean*mean,1e-20))
                correction = mean*weight
            correction = np.where(active[...,None], correction*s.strength, 0).astype(np.float32)
            corrections.append(correction-up(down(correction), (lh,lw)))
            states.append(dict(mean=mean,variance=variance,q=q,age=age,depth=guide[0].copy(),normal=guide[1].copy(),
                               roughness=guide[2].copy(),material=guide[3].copy()))
            if level == 0:
                first_age = age
        collapsed = np.zeros_like(corrections[-1])
        for level in reversed(range(s.levels)):
            collapsed = corrections[level]+(up(collapsed,corrections[level].shape[:2]) if level < s.levels-1 else 0)
        rr = denoised[...,:3].astype(np.float32)
        supported = safe & (first_age >= s.minimum_age)
        mask = supported[...,None] & np.isfinite(collapsed) & (collapsed != 0) & (rr > 0)
        count = mask.sum((0,1))
        offset = np.sum(np.where(mask,collapsed,0),axis=(0,1))/np.maximum(count,1)
        collapsed = np.where(mask,collapsed-offset,0).astype(np.float32)
        low, high = np.zeros_like(rr), np.full_like(rr,65504)
        if s.anchor > 0:
            mean = neighbourhood(rr)
            variance = np.maximum(neighbourhood(rr*rr)-mean*mean,0)
            deviation = s.anchor*np.sqrt(variance+1e-4*mean*mean)
            low = np.maximum(np.minimum(mean-deviation,rr),0)
            high = np.minimum(np.maximum(mean+deviation,rr),65504)
        ratios = np.ones_like(rr)
        np.divide(high-rr,collapsed,out=ratios,where=collapsed>0)
        np.divide(rr-low,-collapsed,out=ratios,where=collapsed<0)
        uniform = float(np.clip(ratios.min(),0,1))
        result = denoised.copy()
        result[...,:3] = rr+collapsed*uniform
        self.states, self.last_frame = states, frame
        self.extent = depth.shape
        self.last_stats = dict(correction_rms=float(np.sqrt(np.mean((collapsed*uniform)**2))),
            active_fraction=float(mask.any(-1).mean()), uniform_bound_scale=uniform,
            mature_fraction=float((first_age>=s.minimum_age).mean()),
            correction_rgb_sum=np.sum(collapsed.astype(np.float64)*uniform,axis=(0,1)).tolist())
        return result
