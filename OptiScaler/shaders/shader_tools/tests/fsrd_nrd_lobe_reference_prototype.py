"""CPU adaptation of RecoveryLobe's jitter-gradient reference to separate NRD.

RR is the only lighting base; this returns a noise-gated non-DC correction to
its current lobes, without material remodulation, Skip colour, or Mix-to-noisy.
No reference/age/object mask from an oracle can enter this operator. Histories
are float32 research data, not claimed native FP16/shader parity.
"""
from dataclasses import dataclass
import numpy as np

from fsrd_nrd_recovery_prototype import LUMA, Settings, Recovery, down, up, neighbourhood, decode_normals


@dataclass(frozen=True)
class ReferenceSettings(Settings):
    gradient_age: int = 8
    band_threshold: float = 3
    noise_response: float = 1/16
    negative_limit: float = .25
    bound_projection: str = 'uniform'
    projection_tile: int = 8


def gradient_colour(value):
    positive = np.maximum(value,0)
    return positive/np.maximum((positive @ LUMA)[...,None],1e-4)


def smoothstep(a,b,value):
    x = np.clip((value-a)/(b-a),0,1)
    return x*x*(3-2*x)


def finish(rr,correction,supported,settings):
    """DC-neutral projection + one uniform bound; never clip RGB independently."""
    mask = supported[...,None]&np.isfinite(correction)&(correction != 0)&(rr > 0)
    projection = getattr(settings,'bound_projection','uniform')
    if projection == 'uniform':
        count = mask.sum((0,1))
        offset = np.sum(np.where(mask,correction,0),axis=(0,1))/np.maximum(count,1)
        correction = np.where(mask,correction-offset,0).astype(np.float32)
    else:
        correction = np.where(mask,correction,0).astype(np.float32)
    low,high = np.zeros_like(rr),np.full_like(rr,65504)
    if settings.anchor > 0:
        mean = neighbourhood(rr)
        variance = np.maximum(neighbourhood(rr*rr)-mean*mean,0)
        deviation = settings.anchor*np.sqrt(variance+1e-4*mean*mean)
        low = np.maximum(np.minimum(mean-deviation,rr),0)
        high = np.minimum(np.maximum(mean+deviation,rr),65504)
    if settings.negative_limit > 0:
        low = np.maximum(low,rr*(1-settings.negative_limit))
    if projection in ('local_anchor','local_box_zero_dc'):
        lower = low-rr
        if settings.negative_limit > 0:
            lower = np.maximum(lower,-settings.negative_limit*rr)
        if projection == 'local_anchor':
            projected = np.minimum(np.maximum(correction,lower),high-rr)
            extra = dict(bound_projection=projection,uniform_bound_scale=None,
                projection_clipped_component_fraction=float(np.mean(projected!=correction)))
        else:
            from fsrd_nrd_recovery_local_bounds import project_local_box
            projected,extra = project_local_box(correction,lower,high-rr,mask,settings.projection_tile)
        return projected,dict(**extra,correction_rms=float(np.sqrt(np.mean(projected**2))),
            active_fraction=float(mask.any(-1).mean()),
            correction_rgb_sum=np.sum(projected.astype(np.float64),axis=(0,1)).tolist())
    if projection != 'uniform':
        raise ValueError('unknown correction bound projection')
    ratios = np.ones_like(rr)
    np.divide(high-rr,correction,out=ratios,where=correction>0)
    np.divide(rr-low,-correction,out=ratios,where=correction<0)
    scale = float(np.clip(ratios.min(),0,1))
    return correction*scale,dict(correction_rms=float(np.sqrt(np.mean((correction*scale)**2))),
        active_fraction=float(mask.any(-1).mean()),uniform_bound_scale=scale,
        correction_rgb_sum=np.sum(correction.astype(np.float64)*scale,axis=(0,1)).tolist())


class LobeReferenceRecovery(Recovery):
    def __init__(self,settings=ReferenceSettings()):
        super().__init__(settings)
        self.reference = None
        self.previous_jitter = None

    def reset(self):
        super().reset()
        self.reference = None
        self.previous_jitter = None

    def read_reference(self,guide,motion,jitter):
        depth,normal,roughness,material,safe = guide
        h,w = depth.shape
        old,s = self.reference,self.settings
        yy,xx = np.mgrid[:h,:w]
        # The SDK pixel-grid motion already includes (Jprev-Jcur)/size. The
        # gradient model lives on the jitter-free grid, so remove that once.
        position = np.stack((xx,yy),-1).astype(np.float32)+motion[...,:2]*(w,h)-(self.previous_jitter-jitter)
        finite = np.isfinite(position).all(-1)&np.isfinite(motion).all(-1)
        position = np.where(finite[...,None],position,0)
        base = np.floor(position).astype(int)
        fraction = position-base
        expected = depth+motion[...,2]
        value = np.zeros((h,w,3),np.float32)
        gradient = np.zeros((h,w,2),np.float32)
        total = np.zeros((h,w),np.float32)
        age = np.full((h,w),np.inf,np.float32)
        q = np.zeros((h,w),np.float32)
        for dx,dy in ((0,0),(1,0),(0,1),(1,1)):
            x,y = base[...,0]+dx,base[...,1]+dy
            inside = (x>=0)&(y>=0)&(x<w)&(y<h)
            x,y = np.clip(x,0,w-1),np.clip(y,0,h-1)
            valid = safe&finite&inside&(old['age'][y,x]>0)
            valid &= np.abs(old['depth'][y,x]-expected) <= s.depth_relative_tolerance*np.maximum(np.abs(expected),1e-3)
            valid &= np.sum(old['normal'][y,x]*normal,-1)>s.normal_dot_minimum
            valid &= (old['material'][y,x]==material)&(np.abs(old['roughness'][y,x]-roughness)<=.025)
            tap,grad = old['value'][y,x],old['gradient'][y,x]
            valid &= np.isfinite(tap).all(-1)&np.isfinite(grad).all(-1)
            weight = np.where(valid,(fraction[...,0] if dx else 1-fraction[...,0])*
                (fraction[...,1] if dy else 1-fraction[...,1]),0).astype(np.float32)
            counted = weight>0
            shift = position-np.stack((x,y),-1)
            predicted = tap+np.sum(grad*shift,-1)[...,None]*gradient_colour(tap)
            value += weight[...,None]*np.where(counted[...,None],predicted,0)
            gradient += weight[...,None]*np.where(counted[...,None],grad,0)
            total += weight
            age = np.minimum(age,np.where(counted,old['age'][y,x],np.inf))
            q = np.maximum(q,np.where(counted,old['q'][y,x],0))
        valid = safe&finite&(total>=s.footprint_minimum)&np.isfinite(age)
        value /= np.maximum(total,1e-20)[...,None]
        gradient /= np.maximum(total,1e-20)[...,None]
        return value,gradient,np.where(valid,age,0),q,valid

    def step(self,noisy,denoised,depth,packed_normal,motion,frame,reset=False,jitter=(0,0)):
        s = self.settings
        if not np.isfinite(noisy[...,:3]).all() or not np.isfinite(denoised[...,:3]).all():
            raise ValueError('nonfinite lighting must fail before recovery')
        if s.strength<=0:
            self.reset()
            self.last_stats = dict(correction_rms=0.,active_fraction=0.,uniform_bound_scale=1.,mature_fraction=0.)
            return denoised.copy()
        if reset or self.last_frame is None or frame!=self.last_frame+1 or self.extent!=depth.shape:
            self.reset()
        jitter = np.asarray(jitter,np.float32)
        if jitter.shape!=(2,) or not np.isfinite(jitter).all() or np.max(np.abs(jitter))>.5:
            raise ValueError('finite signed render-pixel jitter within half a pixel is required')
        height,width = depth.shape
        normal,roughness,material = decode_normals(packed_normal)
        safe = np.isfinite(depth)&(np.abs(depth)>1e-5)&(roughness>0)&np.isfinite(motion).all(-1)&(motion[...,3]>=.5)
        safe &= np.isfinite(noisy[...,3])&(noisy[...,3]>0)
        safe &= neighbourhood(depth,maximum=True)-neighbourhood(depth,minimum=True) <= s.depth_relative_tolerance*np.maximum(np.abs(depth),1e-3)
        safe &= neighbourhood(material,minimum=True)==neighbourhood(material,maximum=True)
        padded = np.pad(normal,((1,1),(1,1),(0,0)),mode='edge')
        for dy in range(3):
            for dx in range(3):
                safe &= np.sum(normal*padded[dy:dy+height,dx:dx+width],-1)>s.normal_dot_minimum
        signal,rr = noisy[...,:3].astype(np.float32),denoised[...,:3].astype(np.float32)
        guide = depth,normal,roughness,material,safe
        if self.reference is not None:
            value,gradient,age,q,reuse = self.read_reference(guide,motion,jitter)
        else:
            value = np.zeros_like(signal)
            gradient = np.zeros((height,width,2),np.float32)
            age = np.zeros((height,width),np.float32)
            q = np.ones((height,width),np.float32)
            reuse = np.zeros((height,width),bool)
        rate = np.maximum(1/(age+1),s.response).astype(np.float32)
        offset = -jitter
        predicted = value+np.sum(gradient*offset,-1)[...,None]*gradient_colour(value)
        error = signal-predicted
        innovation = np.where(reuse,error @ LUMA,0).astype(np.float32)
        value = np.where(reuse[...,None],value+rate[...,None]*error,signal)
        gradient_rate = np.where(reuse&(age>=s.gradient_age),rate,0)
        gradient = np.where(reuse[...,None],gradient+12*gradient_rate[...,None]*innovation[...,None]*offset,0)
        age = np.where(safe,np.minimum(age+1,1024),0).astype(np.float32)
        q = np.where(reuse,(1-rate)**2*q+rate*rate,1).astype(np.float32)
        reference = np.maximum(value+np.sum(gradient*offset,-1)[...,None]*gradient_colour(value),0)
        # An isolated reference spike is not a measured feature. Clamp only to
        # compatible neighbouring temporal references, never to noisy samples.
        low,high = np.full_like(reference,np.inf),np.full_like(reference,-np.inf)
        p = np.pad(reference,((1,1),(1,1),(0,0)),mode='edge')
        a = np.pad(age,((1,1),(1,1)),mode='edge')
        for dy in range(3):
            for dx in range(3):
                if dx==dy==1:
                    continue
                valid = a[dy:dy+height,dx:dx+width]>0
                tap = p[dy:dy+height,dx:dx+width]
                low = np.minimum(low,np.where(valid[...,None],tap,np.inf))
                high = np.maximum(high,np.where(valid[...,None],tap,-np.inf))
        reference = np.where((low<=high),np.clip(reference,low,high),reference)
        levels,innovations,masks,ages,weights = [reference-rr],[innovation],[safe.astype(np.float32)],[age],[q]
        for _ in range(s.levels):
            levels.append(down(levels[-1]))
            innovations.append(down(innovations[-1]))
            masks.append(down(masks[-1],minimum=True))
            ages.append(down(ages[-1],minimum=True))
            weights.append(-down(-weights[-1],minimum=True))
        states,corrections = [],[]
        for level in range(s.levels):
            lh,lw = levels[level].shape[:2]
            difference = levels[level]-up(levels[level+1],(lh,lw))
            innovation_band = innovations[level]-up(innovations[level+1],(lh,lw))
            power = innovation_band*innovation_band
            eligible = (masks[level]>.999)&(up(masks[level+1],(lh,lw))>.999)
            yi = np.minimum(((np.arange(lh)+.5)*(1<<level)).astype(int),height-1)
            xi = np.minimum(((np.arange(lw)+.5)*(1<<level)).astype(int),width-1)
            sample = np.ix_(yi,xi)
            level_guide = depth[sample],normal[sample],roughness[sample],material[sample],eligible
            current_motion = motion[sample].astype(np.float32)
            if self.states is not None:
                old_power,_,noise_age,_,reuse_noise = self._reproject(self.states[level],level_guide,current_motion,level,(width,height))
                old_power = old_power[...,0]
            else:
                old_power,noise_age,reuse_noise = np.zeros((lh,lw),np.float32),np.zeros((lh,lw),np.float32),np.zeros((lh,lw),bool)
            noise_rate = np.maximum(1/(noise_age+1),s.noise_response).astype(np.float32)
            variance = np.where(reuse_noise,old_power+noise_rate*(power-old_power),power)
            noise_age = np.where(eligible,np.minimum(noise_age+1,1024),0).astype(np.float32)
            band_luma = difference @ LUMA
            energy = neighbourhood(band_luma*band_luma)
            noise = np.maximum(variance*weights[level]/(1+weights[level]),1e-20)
            speed = np.linalg.norm(current_motion[...,:2]*(width,height),axis=-1)
            margin = smoothstep(4,20,speed) if level>=2 else 0
            threshold = s.band_threshold*(1+.5*level*level*margin)
            wiener = np.maximum(0,1-threshold*noise/np.maximum(energy,1e-30))
            active = eligible&(ages[level]>=s.minimum_age)&(noise_age>=4)&(1/np.maximum(weights[level],1e-12)>=s.minimum_effective_count)
            correction = np.where(active[...,None],difference*(wiener*s.strength)[...,None],0).astype(np.float32)
            corrections.append(correction-up(down(correction),(lh,lw)))
            states.append(dict(mean=np.repeat(variance[...,None],3,-1),variance=np.zeros((lh,lw,3),np.float32),
                q=np.zeros((lh,lw),np.float32),age=noise_age,depth=level_guide[0].copy(),normal=level_guide[1].copy(),
                roughness=level_guide[2].copy(),material=level_guide[3].copy()))
        collapsed = np.zeros_like(corrections[-1])
        for level in reversed(range(s.levels)):
            collapsed = corrections[level]+(up(collapsed,corrections[level].shape[:2]) if level<s.levels-1 else 0)
        # Exact current noisy==RR provides no measured evidence of lost detail.
        supported = safe&(age>=s.minimum_age)&np.any(signal!=rr,axis=-1)
        correction,statistics = finish(rr,collapsed,supported,s)
        result = denoised.copy()
        result[...,:3] = rr+correction
        self.reference = dict(value=value,gradient=gradient,age=age,q=q,depth=depth.copy(),normal=normal.copy(),
            roughness=roughness.copy(),material=material.copy())
        self.states,self.last_frame,self.extent,self.previous_jitter = states,frame,depth.shape,jitter
        self.last_stats = dict(**statistics,mature_fraction=float((age>=s.minimum_age).mean()),
            mean_luminance_gradient=float(np.mean(np.linalg.norm(gradient,axis=-1))))
        return result
