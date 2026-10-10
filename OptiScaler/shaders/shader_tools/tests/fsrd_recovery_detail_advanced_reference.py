"""Floor-free advanced controls with a continuous signed candidate bound.

The frozen first anchor model can move a current RR spike into its anchor box
even when the paired candidate tends to zero. Both alternatives below project
the controlled delta onto the original signed candidate ray. The advanced
model additionally uses the v1 Light path's supported attenuation and variance
relaxation ideas, evaluated on current RR plus the independent paired mean.
No Floor/Skip reference, changed quality gate or production enable is implied.
"""
import numpy as np
import fsrd_recovery_detail_anchor_reference as original
from fsrd_recovery_detail_anchor_reference import AnchorObservations, BinaryWitnessMoments, LUMA

FROZEN_CONTROLS = original.apply_controls


def smoothstep(a, b, x):
    t = np.clip((x-a)/(b-a), 0, 1)
    return t*t*(3-2*t)


def signed_ray(value, raw):
    """A zero candidate stays zero; no new direction or larger delta exists."""
    direction = np.sign(raw)
    return (direction*np.minimum(np.maximum(direction*value, 0), abs(raw))).astype(np.float32)


def apply_controls(raw, rr, geometry, noise, anchor=4., mix=1., luma=1., chroma=1.,
                   counters=None, control_model="advanced"):
    raw, rr, noise = (np.asarray(v, np.float32) for v in (raw, rr, noise))
    if raw.shape != rr.shape or noise.shape != raw.shape:
        raise ValueError("Paired candidate, same-lobe RR and uncertainty must share a radiance domain")
    anchor = float(np.clip(anchor if np.isfinite(anchor) else 4., 0, 8))
    mix = float(np.clip(mix if np.isfinite(mix) else 1., 0, 1))
    luma = float(np.clip(luma if np.isfinite(luma) else 1., 0, 1))
    chroma = float(np.clip(chroma if np.isfinite(chroma) else 1., 0, 1))
    eligible = np.any(raw != 0, -1) & np.all(np.isfinite(raw) & np.isfinite(rr) & np.isfinite(noise), -1)
    candidate = np.where(eligible[..., None], raw, 0)
    rr_safe = np.where(np.isfinite(rr), rr, 0)
    noise_safe = np.where(np.isfinite(noise), noise, 0)
    counted = {}
    if control_model == "ray":
        unbounded = FROZEN_CONTROLS(candidate, rr_safe, geometry, noise_safe,
                            anchor, mix, luma, chroma, counted)
        result = signed_ray(unbounded, candidate)
        counted.update(ray_changed=int(np.count_nonzero(np.any(result != unbounded, -1))),
                       control_model=control_model)
        if counters is not None:
            counters.update(counted)
        return result
    if control_model != "advanced":
        raise ValueError("Unknown advanced-control alternative: "+control_model)

    # Statistics are geometry-local; they do not introduce another color source.
    low_rr = geometry.box(rr_safe, 3)
    reference = rr_safe+candidate
    low_reference = geometry.box(reference, 3)
    variance_rr = np.maximum(geometry.box(rr_safe*rr_safe, 3)-low_rr*low_rr, 0)
    variance_ref = np.maximum(geometry.box(reference*reference, 3)-low_reference*low_reference, 0)
    lr, lp = rr_safe@LUMA, reference@LUMA
    mr, mp = low_rr@LUMA, low_reference@LUMA
    vr = np.maximum(geometry.box(lr*lr, 3)-mr*mr, 0)
    vp = np.maximum(geometry.box(lp*lp, 3)-mp*mp, 0)
    cov = geometry.box(lr*lp, 3)-mr*mp
    cr, cp = rr_safe-lr[..., None], reference-lp[..., None]
    mcr, mcp = geometry.box(cr, 3), geometry.box(cp, 3)
    vcr = np.maximum(np.mean(geometry.box(cr*cr, 3)-mcr*mcr, -1), 0)
    vcp = np.maximum(np.mean(geometry.box(cp*cp, 3)-mcp*mcp, -1), 0)
    ccp = np.mean(geometry.box(cr*cp, 3)-mcr*mcp, -1)
    sigma = np.sqrt(np.mean(noise_safe*noise_safe, -1))
    patch_variance = sigma*sigma*.75
    amplitude = np.sqrt(np.mean(variance_ref, -1))
    snr = amplitude/np.maximum(sigma, 1e-5)
    structure = (amplitude >= np.maximum(np.linalg.norm(low_reference, axis=-1)*1e-4, 1e-6))*\
        smoothstep(1.2, 1.8, snr)*np.maximum(smoothstep(.22, .28, amplitude/np.maximum(sigma+mp, 1e-5)),
                                          smoothstep(4, 8, snr))
    rr_error = np.sqrt(np.mean(geometry.box(candidate*candidate, 3), -1))
    rr_agreement = 1-smoothstep(.8, 1.2, rr_error/np.maximum(sigma, 1e-5))
    luma_coherence = np.clip(cov/np.maximum(np.sqrt(vr*vp), 1e-12), 0, 1)
    chroma_coherence = np.clip(ccp/np.maximum(np.sqrt(vcr*vcp), 1e-12), 0, 1)
    retained = np.sqrt((vr+vcr)/np.maximum(vp+vcp-2*patch_variance, 1e-12))*\
               np.maximum(mp, 1e-5)/np.maximum(mr, 1e-5)
    rr_support = smoothstep(.005, .015, np.sqrt(vr+vcr)/np.maximum(mr, 1e-5))*smoothstep(2.5, 6.5, snr)
    attenuation = np.maximum(smoothstep(.85, .97, luma_coherence),
                             smoothstep(.85, .97, chroma_coherence))*\
                  rr_support*structure*(1-rr_agreement)*np.clip(1-retained, 0, 1)
    clean = eligible & (sigma < np.maximum(np.linalg.norm(low_reference, axis=-1)*.001, 1e-8))
    anchor_active = eligible & ~clean & (anchor > 0)
    structure_variance = np.maximum(variance_ref-sigma[..., None]**2, 0)
    contrast = np.sqrt(np.mean(structure_variance, -1))/np.maximum(mp, 1e-5)
    corroborated = np.maximum(np.clip(cov/np.maximum(vp, 1e-12), 0, 1), attenuation)
    relaxation = smoothstep(.06, .10, contrast)*corroborated
    tolerance = anchor*np.sqrt(np.maximum(variance_rr, relaxation[..., None]*structure_variance))
    graft = np.where(anchor_active[..., None],
            np.clip(reference, np.maximum(low_rr-tolerance, 0), low_rr+tolerance), reference)
    # Anchor controls only the proposed paired transfer. It cannot retouch RR.
    delta = signed_ray(np.where(eligible[..., None], graft-rr_safe, 0), candidate)
    luma_agreement = np.clip(((2*cov+1e-3)/(vr+vp+1e-3))*\
                           ((2*mr*mp+1e-2)/(mr*mr+mp*mp+1e-2)), 0, 1)
    chroma_stabilizer = np.maximum(4*sigma*sigma, 1e-6)
    chroma_agreement = np.clip((2*ccp+chroma_stabilizer)/np.maximum(vcr+vcp+chroma_stabilizer, 1e-6), 0, 1)
    color_evidence = vcr/(vcr+vr+chroma_stabilizer)
    agreement = luma_agreement+color_evidence*(np.minimum(luma_agreement, chroma_agreement)-luma_agreement)
    agreement *= np.clip(vr/np.maximum(vp-2*patch_variance, 1e-6), 0, 1)*(1-attenuation)
    mix_active = eligible & ~clean & (mix > 0)
    amount = np.where(mix_active, mix*agreement, 0)
    gain = np.clip((cov-vr-2*patch_variance)/np.maximum(vr, 1e-6), 0, 2)
    predicted = gain[..., None]*(rr_safe-low_rr)
    predicted_luma = (predicted@LUMA)[..., None]
    luma_extension = luma*predicted_luma
    chroma_extension = chroma*(predicted-predicted_luma)
    predicted = signed_ray(luma_extension+chroma_extension, delta)
    result = signed_ray((1-amount[..., None])*delta+amount[..., None]*predicted, candidate)
    if counters is not None:
        counters.update(eligible=int(eligible.sum()), clean_exception=int(clean.sum()),
            anchor_branch=int(anchor_active.sum()),
            anchor_changed=int(np.count_nonzero(anchor_active & np.any(delta != candidate, -1))),
            ray_rounding_changed=int(np.count_nonzero(~anchor_active & np.any(delta != candidate, -1))),
            mix_branch=int(mix_active.sum()), mix_changed=int(np.count_nonzero(np.any(result != delta, -1))),
            luma_extension=int(np.count_nonzero(amount*np.any(abs(luma_extension) > 0, -1))),
            chroma_extension=int(np.count_nonzero(amount*np.any(abs(chroma_extension) > 0, -1))),
            attenuation_supported=int(np.count_nonzero(eligible & (attenuation > 0))),
            anchor_relaxed=int(np.count_nonzero(anchor_active & (relaxation > 0))),
            anchor=anchor, mix=mix, luma=luma, chroma=chroma, control_model=control_model,
            maximum_raw=float(abs(candidate).max()), maximum_controlled=float(abs(result).max()))
    return result


class AdvancedState(original.AnchorState):
    """Single-thread CPU fixture adapter with a temporary module substitution.

    It restores the frozen module function after each call. This adapter is
    process-local test plumbing, not a thread-safe or production runtime API.
    The captured FROZEN_CONTROLS keeps the ray-only ablation nonrecursive.
    """
    control_model = "advanced"

    def step(self, *args, **kwargs):
        previous = original.apply_controls
        def controls(*a, **k):
            return apply_controls(*a, **k, control_model=self.control_model)
        original.apply_controls = controls
        try:
            return super().step(*args, **kwargs)
        finally:
            original.apply_controls = previous


class RayState(AdvancedState):
    control_model = "ray"
