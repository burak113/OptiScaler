"""Source-shaped decisions and explicit rejection of unidentifiable observables."""
import numpy as np

from .storage import NonIdentifiableError, sanitize_radiance, store_fp16


def colour_history_valid(history_depth, current_depth, motion_depth, uv, *,
                         tolerance=0.02, history_enabled=True, dtype=np.float32):
    """FSRDColourTrackTrack's inclusive signed-depth and viewport predicates.

    Sampling is deliberately separate. `dtype=float64` is an analytic arithmetic
    intervention, not a claim about HLSL execution. Inactive history does not
    inspect unused history/motion/UV values.
    """
    current = np.asarray(current_depth, dtype=dtype)
    if not history_enabled:
        return np.zeros(current.shape, dtype=bool)
    history = np.asarray(history_depth, dtype=dtype)
    motion = np.asarray(motion_depth, dtype=dtype)
    uv = np.asarray(uv, dtype=dtype)
    if uv.shape != current.shape + (2,):
        raise ValueError("uv must have current_depth.shape + (2,)")
    expected = (current + motion).astype(dtype)
    with np.errstate(invalid="ignore", over="ignore"):
        return (np.all(uv >= dtype(0), axis=-1) & np.all(uv <= dtype(1), axis=-1)
                & (np.abs(history) > dtype(1e-9))
                & (np.abs(history - expected)
                   <= dtype(tolerance) * np.maximum(np.abs(expected), dtype(1e-3))))


def colour_apply_pixel(colour, gain, authority, *, enabled=True, rounding="rtz"):
    """Colour Apply after sampling; authority<.5 returns original RGBA bytes.

    Inputs must be float32-expanded FP16. Colour Apply writes alpha1 on active
    pixels; native Anchor's alpha contract is different (apply_anchor_lobes).
    """
    colour = np.asarray(colour, dtype=np.float32)
    if colour.ndim < 1 or colour.shape[-1] != 4:
        raise ValueError("expected ...x4 colour")
    out = colour.copy()
    if not enabled:
        return out
    authority = np.broadcast_to(np.asarray(authority, np.float32), colour.shape[:-1])
    active = ~(authority < np.float32(.5))
    if not np.any(active):
        return out
    gain = np.broadcast_to(np.asarray(gain, np.float32), colour.shape[:-1]+(3,))
    original = colour[active, :3]
    tracked = (original * gain[active]).astype(np.float32)
    weights = np.array([.2126, .7152, .0722], np.float32)
    # One named unfused left-to-right dot profile; DXC contraction is unresolved.
    def luma(v):
        p = (v * weights).astype(np.float32)
        return ((p[..., 0] + p[..., 1]).astype(np.float32) + p[..., 2]).astype(np.float32)
    tracked *= (luma(original) / np.maximum(luma(tracked), np.float32(1e-9)))[..., None]
    out[active, :3] = store_fp16(sanitize_radiance(tracked), rounding=rounding)
    out[active, 3] = np.float32(1)
    return out


def colour_history_valid_finite(history_depth,current_depth,motion_depth,uv,*,
                               tolerance=0.02,history_enabled=True,dtype=np.float32):
    """Proposed numerical adapter: reject nonfinite history/expected depth.

    This is separate from the frozen source-shaped predicate above. Original
    source can accept finite history when expected depth is infinity, since its
    comparison can become infinity<=infinity. Production is not modified here.
    DXC and device validation of the accompanying patch remain a local gate.
    """
    valid=colour_history_valid(history_depth,current_depth,motion_depth,uv,
        tolerance=tolerance,history_enabled=history_enabled,dtype=dtype)
    if not history_enabled:return valid
    with np.errstate(invalid="ignore",over="ignore"):
        expected=np.asarray(current_depth,dtype=dtype)+np.asarray(motion_depth,dtype=dtype)
    return valid & np.isfinite(np.asarray(history_depth,dtype=dtype)) & np.isfinite(expected)


def require_unique_observable(possible_outputs):
    """Return one exact byte value only when all supplied witnesses agree.

    Agreement of witnesses is not proof that an unsampled continuum is unique.
    This helper only falsifies an exact reconstruction with distinct witnesses;
    interval singleton proof is provided by the fixedpoint contract.
    """
    values = [np.asarray(v) for v in possible_outputs]
    if not values:
        raise ValueError("at least one observable is required")
    reference = values[0]
    if any(v.shape != reference.shape or v.dtype != reference.dtype
           or v.tobytes() != reference.tobytes() for v in values[1:]):
        raise NonIdentifiableError("compatible pre-store inputs produce distinct exact observables")
    return reference.copy()
