"""Noise-calibrated recovery using only current RR bands in the output.

Noisy light is a statistical calibration input, never an RGB correction source.
Positive lost-response covariance must exceed its temporal uncertainty, and
the RR band itself must be coherent above its measured noise. This is a CPU
research alternative; no shader, provider, or game-quality claim is implied.
"""
from dataclasses import dataclass
import numpy as np

from fsrd_nrd_recovery_prototype import Recovery,Settings,LUMA,down,up,neighbourhood,decode_normals
from fsrd_nrd_lobe_reference_prototype import finish


@dataclass(frozen=True)
class BandGainSettings(Settings):
    maximum_gain: float = 4
    negative_limit: float = .25


class RRBandGainRecovery(Recovery):
    def __init__(self,settings=BandGainSettings()):
        super().__init__(settings)

    def step(self,noisy,denoised,depth,packed_normal,motion,frame,reset=False):
        s = self.settings
        if not np.isfinite(noisy[...,:3]).all() or not np.isfinite(denoised[...,:3]).all():
            raise ValueError('nonfinite lighting must fail before recovery')
        if s.strength<=0:
            self.reset()
            self.last_stats = dict(correction_rms=0.,active_fraction=0.,uniform_bound_scale=1.,mature_fraction=0.)
            return denoised.copy()
        if reset or self.last_frame is None or frame!=self.last_frame+1 or self.extent!=depth.shape:
            self.states = None
        h,w = depth.shape
        normal,roughness,material = decode_normals(packed_normal)
        safe = np.isfinite(depth)&(np.abs(depth)>1e-5)&(roughness>0)&np.isfinite(motion).all(-1)&(motion[...,3]>=.5)
        safe &= np.isfinite(noisy[...,3])&(noisy[...,3]>0)
        safe &= neighbourhood(depth,maximum=True)-neighbourhood(depth,minimum=True) <= s.depth_relative_tolerance*np.maximum(np.abs(depth),1e-3)
        safe &= neighbourhood(material,minimum=True)==neighbourhood(material,maximum=True)
        pad = np.pad(normal,((1,1),(1,1),(0,0)),mode='edge')
        for dy in range(3):
            for dx in range(3):
                safe &= np.sum(normal*pad[dy:dy+h,dx:dx+w],-1)>s.normal_dot_minimum
        noisy_levels = [noisy[...,:3].astype(np.float32)]
        rr_levels = [denoised[...,:3].astype(np.float32)]
        masks = [safe.astype(np.float32)]
        for _ in range(s.levels):
            noisy_levels.append(down(noisy_levels[-1]))
            rr_levels.append(down(rr_levels[-1]))
            masks.append(down(masks[-1],minimum=True))
        states,corrections,gains = [],[],[]
        first_age = None
        for level in range(s.levels):
            lh,lw = rr_levels[level].shape[:2]
            raw_band = noisy_levels[level]-up(noisy_levels[level+1],(lh,lw))
            rr_band = rr_levels[level]-up(rr_levels[level+1],(lh,lw))
            raw_y,rr_y = raw_band @ LUMA,rr_band @ LUMA
            energy = neighbourhood(rr_y*rr_y)
            covariance = neighbourhood((raw_y-rr_y)*rr_y)
            observed = np.stack((covariance,energy,rr_y),-1)
            eligible = (neighbourhood(masks[level],minimum=True)>.999)&(up(masks[level+1],(lh,lw))>.999)
            yi = np.minimum(((np.arange(lh)+.5)*(1<<level)).astype(int),h-1)
            xi = np.minimum(((np.arange(lw)+.5)*(1<<level)).astype(int),w-1)
            sample = np.ix_(yi,xi)
            guide = depth[sample],normal[sample],roughness[sample],material[sample],eligible
            current_motion = motion[sample].astype(np.float32)
            if self.states is not None:
                mean,variance,age,q,reuse = self._reproject(self.states[level],guide,current_motion,level,(w,h))
            else:
                mean,variance = np.zeros_like(observed),np.zeros_like(observed)
                age,q,reuse = np.zeros((lh,lw),np.float32),np.ones((lh,lw),np.float32),np.zeros((lh,lw),bool)
            rate = np.maximum(1/(age+1),s.response).astype(np.float32)
            delta = observed-mean
            mean = np.where(reuse[...,None],mean+rate[...,None]*delta,observed)
            variance = np.where(reuse[...,None],(1-rate[...,None])*(variance+rate[...,None]*delta*delta),0)
            q = np.where(reuse,(1-rate)**2*q+rate*rate,1).astype(np.float32)
            age = np.where(eligible,np.minimum(age+1,1024),0).astype(np.float32)
            sem2 = variance*q[...,None]/np.maximum(1-q[...,None],1e-6)
            positive_covariance = np.maximum(mean[...,0]-s.sigma*np.sqrt(np.maximum(sem2[...,0],0)),0)
            estimated_excess = positive_covariance/np.maximum(mean[...,1],1e-20)
            # Never exceed the current patch's measured missing contrast. In
            # particular convergence of RR to the input makes this zero now,
            # instead of retaining a stale historical sharpening coefficient.
            current_excess = np.maximum(covariance,0)/np.maximum(energy,1e-20)
            stable_energy = neighbourhood(mean[...,2]*mean[...,2])
            mean_uncertainty = neighbourhood(np.maximum(sem2[...,2],0))
            coherence = np.maximum(0,1-s.sigma*s.sigma*mean_uncertainty/np.maximum(stable_energy,1e-20))
            excess = np.minimum(np.minimum(estimated_excess,current_excess),max(s.maximum_gain-1,0))*coherence
            active = eligible&(age>=s.minimum_age)&(1/np.maximum(q,1e-12)>=s.minimum_effective_count)
            excess = np.where(active,excess*s.strength,0).astype(np.float32)
            # This is the only RGB source for recovery: CURRENT denoised RR.
            correction = rr_band*excess[...,None]
            corrections.append(correction-up(down(correction),(lh,lw)))
            gains.append(excess)
            states.append(dict(mean=mean,variance=variance,q=q,age=age,depth=guide[0].copy(),normal=guide[1].copy(),
                roughness=guide[2].copy(),material=guide[3].copy()))
            if level==0:first_age = age
        collapsed = np.zeros_like(corrections[-1])
        for level in reversed(range(s.levels)):
            collapsed = corrections[level]+(up(collapsed,corrections[level].shape[:2]) if level<s.levels-1 else 0)
        rr = denoised[...,:3].astype(np.float32)
        supported = safe&(first_age>=s.minimum_age)&np.any(noisy[...,:3]!=rr,axis=-1)
        correction,statistics = finish(rr,collapsed,supported,s)
        result = denoised.copy()
        result[...,:3] = rr+correction
        self.states,self.last_frame,self.extent = states,frame,depth.shape
        self.last_stats = dict(**statistics,mature_fraction=float((first_age>=s.minimum_age).mean()),
            mean_excess_gain=float(np.mean(gains[0])),maximum_excess_gain=max(float(v.max()) for v in gains))
        return result
