"""Bounded CPU research candidate; not a port of native NZR or AMD RR.

The caller supplies current raw-RR and pre-Glass NZR RGB, in the same physical
linear radiance units. A provenanced uncertainty sidecar is REQUIRED to change
anything. Neither the captured glass fixture nor native history count by itself
provides that sidecar. No previous-frame RGB is read here.

We shrink only the three orthonormal Haar high bands of NZR-minus-RR in a 2x2
block. Its low band is retained. Unsupported blocks retain NZR exactly. Existing
Glass policy follows this operation; strength remains the NZR fraction.
"""

from dataclasses import dataclass
import numpy as np


CONTRACT_VERSION = "glass-correction-uncertainty-v1"
HALF_MAX = np.float32(65504.0)


@dataclass(frozen=True)
class CandidateConfig:
    enabled: bool = False
    noise_scale: float = 1.0
    min_effective_count: float = 8.0


@dataclass(frozen=True)
class SupportUncertainty:
    """Per-specular-lobe evidence; all arrays have shape (height, width).

    noise_trace is SUM over RGB of Var(NZR-RR), in radiance squared, including
    NZR/RR covariance. valid means the estimate has current stage provenance.
    effective_count counts independent observations supporting that estimate,
    not the native history count. independent_spatial asserts that the four
    correction noise samples in an accepted block are independent. Otherwise
    the simple transformed variance used here is unjustified and we abstain.
    surface_id groups current support proven to describe the same surface; it
    is not an NRD material ID and no semantic glass classification is inferred.
    """

    noise_trace: np.ndarray
    effective_count: np.ndarray
    valid: np.ndarray
    independent_spatial: np.ndarray
    surface_id: np.ndarray


def _blocks(array):
    h, w = array.shape[:2]
    h2, w2 = h // 2 * 2, w // 2 * 2
    # Axis 2 order is a,b,c,d = top-left, top-right, bottom-left, bottom-right.
    return np.stack((array[:h2:2, :w2:2], array[:h2:2, 1:w2:2],
                     array[1:h2:2, :w2:2], array[1:h2:2, 1:w2:2]), axis=2)


def haar_forward(blocks):
    a, b, c, d = (blocks[:, :, i] for i in range(4))
    half = np.float32(.5)
    return np.stack((half * (a + b + c + d), half * (a - b + c - d),
                     half * (a + b - c - d), half * (a - b - c + d)), axis=2)


def haar_inverse(coefficients):
    ll, horizontal, vertical, diagonal = (coefficients[:, :, i] for i in range(4))
    half = np.float32(.5)
    return np.stack((half * (ll + horizontal + vertical + diagonal),
                     half * (ll - horizontal + vertical - diagonal),
                     half * (ll + horizontal - vertical - diagonal),
                     half * (ll - horizontal - vertical + diagonal)), axis=2)


def shrink_specular(raw_rgb, selected_rgb, eligible, uncertainty=None,
                    config=CandidateConfig()):
    """Return (candidate pre-Glass RGB, diagnostics), with float32 arithmetic.

    OFF/missing evidence returns a byte copy of selected without inspecting the
    optional evidence. Full-resolution 2x2 blocks begin at global origin (0,0).
    A cropped native adapter must pass its global parity rather than pretending
    the crop begins there. This reference deliberately has only origin-zero API.
    """
    selected = np.asarray(selected_rgb)
    if selected.ndim != 3 or selected.shape[2] != 3 or selected.dtype != np.float32:
        raise ValueError("selected_rgb must be float32 HxWx3 in physical radiance")
    h, w = selected.shape[:2]
    out = selected.copy()
    diagnostics = {
        "contract_version": CONTRACT_VERSION,
        "total_full_blocks": (h // 2) * (w // 2),
        "partial_pixels": h * w - (h // 2 * 2) * (w // 2 * 2),
        "accepted_blocks": 0,
        "range_abstain_blocks": 0,
        "changed_pixels": 0,
        "accepted_mask": np.zeros((h, w), dtype=bool),
        "gains": np.ones((h // 2, w // 2, 3), dtype=np.float32),
    }
    if not config.enabled or uncertainty is None or h < 2 or w < 2:
        diagnostics["reason"] = "off" if not config.enabled else "missing_or_empty_support"
        return out, diagnostics
    if not np.isfinite(config.noise_scale) or config.noise_scale < 0:
        raise ValueError("noise_scale must be finite and nonnegative")
    if not np.isfinite(config.min_effective_count) or config.min_effective_count < 2:
        raise ValueError("min_effective_count must be finite and >=2")
    raw = np.asarray(raw_rgb)
    eligible = np.asarray(eligible, dtype=bool)
    if raw.shape != selected.shape or raw.dtype != np.float32 or eligible.shape != (h, w):
        raise ValueError("raw_rgb/eligible shape or radiance dtype mismatch")
    fields = {name: np.asarray(getattr(uncertainty, name)) for name in
              ("noise_trace", "effective_count", "valid", "independent_spatial", "surface_id")}
    if any(a.shape != (h, w) for a in fields.values()):
        raise ValueError("uncertainty fields must all match the current render extent")
    trace = fields["noise_trace"].astype(np.float32)
    count = fields["effective_count"].astype(np.float32)
    finite_rgb = np.all(np.isfinite(raw) & np.isfinite(selected) & (raw >= 0) &
                        (selected >= 0) & (raw <= HALF_MAX) & (selected <= HALF_MAX), axis=2)
    valid = (eligible & fields["valid"].astype(bool) & fields["independent_spatial"].astype(bool) &
             np.isfinite(trace) & (trace >= 0) & np.isfinite(count) &
             (count >= np.float32(config.min_effective_count)) & finite_rgb)
    block_valid = np.all(_blocks(valid), axis=2)
    surface = _blocks(fields["surface_id"])
    same_surface = (np.all(surface == surface[:, :, :1], axis=2) &
                    np.all(np.isfinite(surface), axis=2) & (surface[:, :, 0] >= 0))
    accepted = block_valid & same_surface
    diagnostics["support_abstain_blocks"] = int(np.count_nonzero(~block_valid))
    diagnostics["geometry_abstain_blocks"] = int(np.count_nonzero(block_valid & ~same_surface))
    if not np.any(accepted):
        diagnostics["reason"] = "unsupported"
        return out, diagnostics
    # Invalid pixels are made arithmetically inert before vectorized operations.
    safe_raw = np.where(valid[..., None], raw, np.float32(0))
    safe_selected = np.where(valid[..., None], selected, np.float32(0))
    correction = _blocks(safe_selected - safe_raw)
    coefficients = haar_forward(correction)
    high = coefficients[:, :, 1:, :]
    energy = np.sum(high * high, axis=3, dtype=np.float32)
    # For orthonormal +/-1/2 coefficients and independent spatial samples.
    with np.errstate(over="ignore", invalid="ignore"):
        variance = np.float32(.25) * np.sum(_blocks(np.where(valid, trace, np.float32(0))),
                                           axis=2, dtype=np.float32)
    denominator = np.maximum(energy, np.float32(1e-30))
    with np.errstate(over="ignore", invalid="ignore"):
        scaled_variance = np.float32(config.noise_scale) * variance
    accepted &= np.isfinite(scaled_variance)
    gain = np.clip(np.float32(1) - np.where(np.isfinite(scaled_variance), scaled_variance,
                                           np.float32(0))[..., None] /
                   denominator, np.float32(0), np.float32(1))
    # A zero-variance or constant-correction block must not acquire a rounding
    # edit merely from a forward/inverse transform.
    needs_change = np.any((gain < np.float32(1)) & (energy > np.float32(0)), axis=2)
    coefficients[:, :, 1:, :] *= gain[..., None]
    reconstructed = _blocks(safe_raw) + haar_inverse(coefficients)
    in_range = np.all(np.isfinite(reconstructed) & (reconstructed >= 0) &
                      (reconstructed <= HALF_MAX), axis=(2, 3))
    diagnostics["range_abstain_blocks"] = int(np.count_nonzero(accepted & ~in_range))
    accepted &= in_range
    # A whole block is accepted/rejected together. Per-channel clipping would
    # destroy the low-band constraint, so negative candidates simply abstain.
    positions = ((slice(0, h // 2 * 2, 2), slice(0, w // 2 * 2, 2)),
                 (slice(0, h // 2 * 2, 2), slice(1, w // 2 * 2, 2)),
                 (slice(1, h // 2 * 2, 2), slice(0, w // 2 * 2, 2)),
                 (slice(1, h // 2 * 2, 2), slice(1, w // 2 * 2, 2)))
    for i, index in enumerate(positions):
        out[index] = np.where((accepted & needs_change)[..., None], reconstructed[:, :, i], selected[index])
        diagnostics["accepted_mask"][index] = accepted
    diagnostics["gains"] = np.where(accepted[..., None], gain, np.float32(1))
    diagnostics["accepted_blocks"] = int(np.count_nonzero(accepted))
    diagnostics["changed_pixels"] = int(np.count_nonzero(np.any(out.view(np.uint32) !=
                                                               selected.view(np.uint32), axis=2)))
    diagnostics["reason"] = "processed"
    return out, diagnostics


def glass_policy(raw_rgba, selected_rgba, mode=2, strength=.5, gate=None):
    """Bounded CPU formula for existing policy; no final remodulation or half store.

    Alpha always comes from raw/current output. Gate is the existing externally
    supplied orientation gate, not a new material classification. The default
    gate of one is suitable only for a known full-vertical test region.
    """
    raw = np.asarray(raw_rgba, dtype=np.float32)
    selected = np.asarray(selected_rgba, dtype=np.float32)
    if raw.shape != selected.shape or raw.ndim != 3 or raw.shape[2] != 4:
        raise ValueError("glass policy expects matching float32 HxWx4 fields")
    if mode not in (0, 1, 2):
        raise ValueError("only source-shaped Glass modes 0/1/2 are modeled; alternate routing is unsupported")
    result = raw.copy()
    result[..., :3] = selected[..., :3]
    if mode not in (1, 2):
        return result
    if not 0 <= strength <= 1 or not np.isfinite(strength):
        raise ValueError("strength must be finite in [0,1]")
    policy = (raw[..., :3] if mode == 1 else raw[..., :3] +
              np.float32(strength) * (selected[..., :3] - raw[..., :3]))
    if gate is None:
        result[..., :3] = policy
    else:
        g = np.clip(np.asarray(gate, dtype=np.float32), 0, 1)
        if g.shape != raw.shape[:2] or not np.all(np.isfinite(g)):
            raise ValueError("orientation gate must be finite with shape HxW")
        mixed = selected[..., :3] + g[..., None] * (policy - selected[..., :3])
        # Preserve a gate-zero pixel without unnecessary add/subtract rounding.
        result[..., :3] = np.where((g > 0)[..., None], mixed, selected[..., :3])
    return result


def apply_specular(raw_rgba, selected_rgba, eligible, uncertainty=None,
                   config=CandidateConfig(), mode=2, strength=.5, gate=None):
    candidate_rgb, diagnostics = shrink_specular(np.asarray(raw_rgba)[..., :3],
                                                np.asarray(selected_rgba)[..., :3],
                                                eligible, uncertainty, config)
    candidate = np.asarray(selected_rgba).copy()
    candidate[..., :3] = candidate_rgb
    return glass_policy(raw_rgba, candidate, mode, strength, gate), diagnostics
