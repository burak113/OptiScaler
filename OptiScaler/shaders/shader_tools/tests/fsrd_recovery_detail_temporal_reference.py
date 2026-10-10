"""Paired-certified temporal input-band restoration, with measured uncertainty.

With identical causal weights/reprojection/reset, mean(input-RR)+mean(RR)
equals mean(input) algebraically. Store that input mean/variance directly;
its uncertainty already includes the input/RR covariance rather than treating
the two populations as independent. The separate paired-difference witness
remains mandatory: temporal RR variation can never authorize recovery alone.
The extra RGB mean/variance costs96B/pixel across two lobes and ping-pong,
337.5MiB at2560x1440 before scratch. This CPU hypothesis is not production.
"""
import numpy as np
from fsrd_recovery_detail_reference import PairedBandMoments, identity_taps, warp
from fsrd_recovery_detail_advanced_reference import AnchorObservations, BinaryWitnessMoments, apply_controls


class TemporalPairMoments(BinaryWitnessMoments):
    def __post_init__(self):
        super().__post_init__()
        self.input_mean = np.zeros((self.output_bands, *self.shape, 3), np.float32)
        self.input_variance = np.zeros_like(self.input_mean)
        self.reference_noise = np.zeros_like(self.input_mean)
        self.current_rr = np.zeros_like(self.input_mean)

    def update(self, observations, taps, reuse, rr_bands, source_bands=None):
        observations = np.asarray(observations, np.float32)
        rr_bands = np.asarray(rr_bands, np.float32)
        source_bands = observations[:, 0]+rr_bands if source_bands is None else np.asarray(source_bands, np.float32)
        if rr_bands.shape != self.input_mean.shape or source_bands.shape != self.input_mean.shape:
            raise ValueError("Source/RR band extent or lobe domain differs")
        finite = np.all(np.isfinite(observations), axis=(0, 1, 4)) & \
                 np.all(np.isfinite(source_bands) & np.isfinite(rr_bands), axis=(0, 3))
        reuse = np.asarray(reuse, bool) & finite
        mean, paired_noise = super().update(observations, taps, reuse)
        a = (self.response/self.mass)[..., None]
        for index, observed in enumerate(source_bands):
            observed = np.where(finite[..., None], observed, 0)
            previous = warp(self.input_mean[index], taps)
            previous_variance = warp(np.sqrt(np.maximum(self.input_variance[index], 0)), taps)**2
            delta = observed-previous
            self.input_mean[index] = np.where(reuse[..., None], previous+a*delta, observed)
            self.input_variance[index] = np.where(reuse[..., None],
                (1-a)*(previous_variance+a*delta**2), 0)
        self.current_rr = np.where(finite[None, ..., None], rr_bands, 0)
        sem2 = self.input_variance*self.q[None, ..., None]/np.maximum(1-self.q[None, ..., None], 1e-6)
        self.reference_noise = np.sqrt(np.maximum(sem2, 0))
        return mean, paired_noise

    @property
    def rr_mean(self):
        """Derived same-population RR mean; no extra independent evidence."""
        return self.input_mean-self.mean[0::2]

    def correction(self, noise, reuse, k=2., confidence="soft", minimum_count=8.):
        paired = PairedBandMoments.correction(self, noise, reuse, k, confidence, minimum_count)
        global_delta, local_delta = paired[0::2], paired[1::2]
        weight = np.divide(global_delta, self.mean[0::2], out=np.zeros_like(global_delta),
                           where=self.mean[0::2] != 0)
        witness = local_delta != 0
        # The temporal-input reference cannot certify itself. Paired identity,
        # unsupported alternating noise and reset/motion veto remain RR-only.
        return np.where(witness, (self.input_mean-self.current_rr)*np.clip(weight, 0, 1), 0)


class TemporalState:
    """Independent CPU safety adapter; real replay supplies original mapping."""
    def __init__(self, gate, width, height):
        self.gate, self.shape = gate, (height, width)
        AnchorObservations.global_band = staticmethod(gate.band)
        self.states = [TemporalPairMoments(self.shape, 1, .1) for _ in range(2)]
        self.previous_available = [np.zeros((*self.shape, 3), bool) for _ in range(2)]
        self.valid = False
        self.old_depth = np.zeros(self.shape, np.float32)
        self.old_normal = np.zeros((*self.shape, 3), np.float32)
        self.last_counters = []

    def step(self, signals, denoised, albedo, base, depth, normal, motion,
             strengths=(1., 1.), reset=False, eligibility=None, anchor=4., mix=1., **unused):
        from fsrd_recovery_detail_gpu import stored
        h, w = self.shape
        base = np.asarray(base[:h, :w], np.float16).astype(np.float32)
        depth = np.asarray(depth[:h, :w], np.float32)
        normal = self.gate.decode_normals(stored(normal[:h, :w], 24)).astype(np.float32)
        geometry = AnchorObservations(depth, normal)
        reuse = (self.valid and not reset) & geometry.valid & np.isfinite(self.old_depth) & \
                (abs(depth-self.old_depth) <= .03*np.maximum(abs(depth), .001)) & \
                ((normal*self.old_normal).sum(-1) > .95)
        correction = np.zeros((*self.shape, 3), np.float32)
        self.last_counters = []
        for index in range(2):
            guide = np.asarray(albedo[index][:h, :w, :3], np.float32)
            guide = guide/255. if albedo[index].dtype == np.uint8 else np.rint(np.clip(guide, 0, 1)*255)/255.
            signal = np.asarray(signals[index][:h, :w, :3], np.float16).astype(np.float32)
            rr = np.asarray(denoised[index][:h, :w, :3], np.float16).astype(np.float32)
            available = np.isfinite(guide) & (guide > 0) & np.isfinite(signal) & np.isfinite(rr)
            if eligibility is not None:
                veto = np.asarray(eligibility[index], bool)[:h, :w]
                available &= veto[..., None] if veto.ndim == 2 else veto
            changed = np.any(available != self.previous_available[index], -1)
            lobe_reuse = reuse & ~changed
            radiance_input, radiance_rr = np.zeros_like(signal), np.zeros_like(rr)
            np.multiply(signal, guide, out=radiance_input, where=available)
            np.multiply(rr, guide, out=radiance_rr, where=available)
            observed = geometry.band(radiance_input-radiance_rr, 3, 40)[None]
            rr_band = self.gate.band(radiance_rr, 3, 40)[None]
            source_band = self.gate.band(radiance_input, 3, 40)[None]
            state = self.states[index]
            _, noise = state.update(observed, identity_taps(h, w), lobe_reuse, rr_band, source_band)
            raw = strengths[index]*state.correction(noise, lobe_reuse, 2., "soft", 8.)[0]
            counters = {}
            raw = apply_controls(raw, radiance_rr, geometry, state.reference_noise[0],
                                 anchor, mix, counters=counters)
            value, _ = geometry.neutral(raw, available & np.isfinite(raw) & (raw != 0), base[..., :3])
            correction += value
            self.last_counters.append(counters)
            self.previous_available[index] = available
        negative = correction < 0
        scale = min(1., float(np.min(base[..., :3][negative]/-correction[negative]))) if negative.any() else 1.
        correction *= max(0., scale)
        correction = geometry.project_residual(correction, np.isfinite(correction) & (correction != 0), base[..., :3])
        output = base.copy(); output[..., :3] += correction
        self.valid = True
        self.old_depth, self.old_normal = depth.copy(), normal.copy()
        return output.astype(np.float16).astype(np.float32)
