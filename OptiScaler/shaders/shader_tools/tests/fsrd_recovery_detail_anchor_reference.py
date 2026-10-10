"""Binary local witness + functional Floor-free anchor/mix CPU alternative.

Current same-lobe RR radiance supplies local anchor statistics. Reference color
is RR plus the certified signed paired band, never Floor or Skip RGB. Knobs are
the existing anchor/mix/luma/chroma controls; finite clamp4/1/1/1 defaults.
This candidate and its clean verdict require strict M3, grain and safety proof.
The original seven-shader and CPU reports are preserved unchanged.
"""
import numpy as np
from fsrd_recovery_detail_reference import PairedBandMoments, identity_taps
from fsrd_recovery_detail_geometry_reference import GeometryObservations
from fsrd_recovery_detail_surface_witness_reference import WitnessObservations, SurfaceWitnessMoments

LUMA = np.array([.2126, .7152, .0722], np.float32)


class BinaryWitnessMoments(SurfaceWitnessMoments):
    def correction(self, noise, reuse, k=2., confidence="soft", minimum_count=8.):
        supported = PairedBandMoments.correction(self, noise, reuse, k, confidence, minimum_count)
        return np.where(supported[1::2] != 0, supported[0::2], 0)


class AnchorObservations(WitnessObservations):
    def neutral(self, raw, mask, base):
        value, scale = GeometryObservations.neutral(self, raw, mask, base)
        return self.project_residual(value, mask, base), scale

    def project_residual(self, value, mask, base):
        # Correct the final FP32 subtraction/scale rounding residue at one
        # already-eligible positive contributor per connected surface/channel.
        # This is a numerical projection, not a per-pixel radiance clamp. A
        # residual subtraction reduces a positive value; adding a residual is
        # also safe for nonnegativity. Components without a safe pivot abstain.
        labels = self.labels.ravel()
        self.last_dc_cleanup = []
        mask = np.asarray(mask, bool) & np.isfinite(base) & (base > 0)
        for channel in range(3):
            flat = value[..., channel].ravel().copy()
            residual = np.bincount(labels, weights=flat, minlength=self.count)
            positive = mask[..., channel].ravel() & (flat > 0)
            maximum = np.zeros(self.count, np.float32)
            np.maximum.at(maximum, labels[positive], flat[positive])
            chosen = positive & (flat == maximum[labels])
            pivot = np.full(self.count, flat.size, np.int64)
            np.minimum.at(pivot, labels[chosen], np.flatnonzero(chosen))
            components = np.flatnonzero((pivot < flat.size) & (residual != 0))
            indices = pivot[components]
            candidate = (flat[indices].astype(np.float64)-residual[components]).astype(np.float32)
            safe = np.isfinite(candidate) & (candidate >= -base[..., channel].ravel()[indices])
            flat[indices[safe]] = candidate[safe]
            rejected = components[~safe]
            if rejected.size:
                flat[np.isin(labels, rejected)] = 0
            # A nonzero component with no positive eligible pivot cannot carry
            # a zero-sum signed correction; fail closed rather than transfer DC.
            no_pivot = np.flatnonzero((pivot == flat.size) & (residual != 0))
            if no_pivot.size:
                flat[np.isin(labels, no_pivot)] = 0
            value[..., channel] = flat.reshape(self.labels.shape)
            after = np.bincount(labels, weights=flat, minlength=self.count)
            self.last_dc_cleanup.append(dict(channel=channel,
                max_before=float(abs(residual).max()), max_after=float(abs(after).max()),
                corrected_components=int(components.size), abstained_components=int(rejected.size+no_pivot.size),
                maximum_mean_before=float(np.max(abs(residual)/np.maximum(np.bincount(labels), 1)))))
        return value


def apply_controls(raw, rr, geometry, noise, anchor=4., mix=1., luma=1., chroma=1., counters=None):
    """Apply anchor and correlation mix before surface-neutralization.

The clean exception requires the independently sampled local witness and
quiet temporal SEM. This is a new v2 verdict, not an asserted v1 equivalence.
Even a measured-clean exception is audited; eligible noisy fixtures must show
real clamp/mix branches and distinct A/B outputs. Chroma/luma extensions use
RR's own local pattern and can never exceed the anchored signed candidate.
"""
    raw, rr = np.asarray(raw, np.float32), np.asarray(rr, np.float32)
    if raw.shape != rr.shape:
        raise ValueError("Current RR and paired-band radiance domains differ")
    anchor = float(np.clip(anchor if np.isfinite(anchor) else 4., 0, 8))
    mix = float(np.clip(mix if np.isfinite(mix) else 1., 0, 1))
    luma, chroma = float(np.clip(luma, 0, 1)), float(np.clip(chroma, 0, 1))
    eligible = np.any(raw != 0, -1) & np.all(np.isfinite(raw) & np.isfinite(rr), -1)
    raw = np.where(eligible[..., None], raw, 0)
    low_rr = geometry.box(rr, 3)
    rr_variance = np.maximum(geometry.box(rr*rr, 3)-low_rr*low_rr, 0)
    reference = rr+raw
    low_reference = geometry.box(reference, 3)
    reference_variance = np.maximum(geometry.box(reference*reference, 3)-low_reference*low_reference, 0)
    cross = geometry.box(rr*reference, 3)-low_rr*low_reference
    noise = np.asarray(noise, np.float32)
    quiet = np.maximum(np.linalg.norm(low_reference, axis=-1)*.001, 1e-8)
    clean = eligible & (np.sqrt(np.mean(noise*noise, -1)) < quiet)
    graft = reference.copy()
    anchor_active = eligible & ~clean & (anchor > 0)
    if np.any(anchor_active):
        tolerance = anchor*np.sqrt(rr_variance)
        bounded = np.clip(reference, np.maximum(low_rr-tolerance, 0), low_rr+tolerance)
        graft = np.where(anchor_active[..., None], bounded, graft)
    delta = np.where(eligible[..., None], graft-rr, 0)
    # SSIM-like agreement and contrast retention, analogous to the existing
    # correlation mix. Current RR covariance, not a shared Floor covariance.
    vr, vp, covariance = np.mean(rr_variance, -1), np.mean(reference_variance, -1), np.mean(cross, -1)
    mr, mp = low_rr@LUMA, low_reference@LUMA
    agreement = np.clip((2*covariance+1e-3)/(vr+vp+1e-3), 0, 1)*\
                np.clip((2*mr*mp+1e-2)/(mr*mr+mp*mp+1e-2), 0, 1)
    agreement *= np.clip(vr/np.maximum(vp-2*np.mean(noise*noise, -1), 1e-6), 0, 1)
    mix_active = eligible & ~clean & (mix > 0)
    amount = np.where(mix_active, mix*agreement, 0)
    high_rr = rr-low_rr
    gain = np.clip((covariance-vr-2*np.mean(noise*noise, -1))/np.maximum(vr, 1e-6), 0, 2)
    predicted = gain[..., None]*high_rr
    predicted_luma = (predicted@LUMA)[..., None]
    luma_extension = luma*predicted_luma
    chroma_extension = chroma*(predicted-predicted_luma)
    predicted = luma_extension+chroma_extension
    # Signed-ray bound: extensions only occupy headroom the anchor already
    # permits, and opposite-direction covariance never becomes new detail.
    predicted = np.where(predicted*delta > 0, np.sign(delta)*np.minimum(abs(predicted), abs(delta)), 0)
    controlled = (1-amount[..., None])*delta+amount[..., None]*predicted
    if counters is not None:
        counters.update(eligible=int(eligible.sum()), clean_exception=int(clean.sum()),
            anchor_branch=int(anchor_active.sum()), anchor_changed=int(np.count_nonzero(np.any(graft != reference, -1))),
            mix_branch=int(mix_active.sum()), mix_changed=int(np.count_nonzero(np.any(controlled != delta, -1))),
            luma_extension=int(np.count_nonzero(amount*np.any(abs(luma_extension) > 0, -1))),
            chroma_extension=int(np.count_nonzero(amount*np.any(abs(chroma_extension) > 0, -1))),
            anchor=anchor, mix=mix, luma=luma, chroma=chroma)
    return controlled.astype(np.float32)


class AnchorState:
    def __init__(self, gate, width, height):
        self.gate, self.shape = gate, (height, width)
        AnchorObservations.global_band = staticmethod(gate.band)
        self.states = [BinaryWitnessMoments(self.shape, 1, .1) for _ in range(2)]
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
            available = np.isfinite(guide) & (guide > 0)
            if eligibility is not None:
                veto = np.asarray(eligibility[index], bool)[:h, :w]
                available &= veto[..., None] if veto.ndim == 2 else veto
            changed = np.any(available != self.previous_available[index], -1)
            lobe_reuse = reuse & ~changed
            signal = np.asarray(signals[index][:h, :w, :3], np.float16).astype(np.float32)
            rr = np.asarray(denoised[index][:h, :w, :3], np.float16).astype(np.float32)
            observed = geometry.band(np.where(available, (signal-rr)*guide, 0), 3, 40)[None]
            state = self.states[index]
            _, noise = state.update(observed, identity_taps(h, w), lobe_reuse)
            raw = strengths[index]*state.correction(noise, lobe_reuse, 2., "soft", 8.)[0]
            counter = {}
            raw = apply_controls(raw, rr*guide, geometry, noise[0], anchor, mix, counters=counter)
            mask = available & np.isfinite(raw) & (abs(raw) > 0)
            value, _ = geometry.neutral(raw, mask, base[..., :3])
            self.last_counters.append(dict(**counter, dc_cleanup=geometry.last_dc_cleanup))
            correction += value
            self.previous_available[index] = available
        negative = correction < 0
        scale = min(1., float(np.min(base[..., :3][negative]/-correction[negative]))) if negative.any() else 1.
        correction *= max(0., scale)
        correction = geometry.project_residual(correction, np.isfinite(correction) & (correction != 0), base[..., :3])
        output = base.copy(); output[..., :3] += correction
        self.valid = True
        self.old_depth, self.old_normal = depth.copy(), normal.copy()
        return output.astype(np.float16).astype(np.float32)
