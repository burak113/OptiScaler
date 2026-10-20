"""Named texture sampling models with observation and active-region support.

The ideal reference, float32 source emulator, observed 8-bit fraction profile,
and documented API envelope are deliberately separate. This module never
rewrites the frozen portable sampler. No hardware or GPU execution is implied.
"""
from __future__ import annotations

from dataclasses import dataclass
import operator
import numpy as np

from .coordinates import arithmetic_dtype, extent_xy, uv_to_texel, cell_tap_uv

SAMPLING_CONTRACT_VERSION = "1.0.0"


@dataclass(frozen=True)
class TextureDomain:
    """Allocation and active dimensions plus a recorded crop's global origin.

    ``texture.shape[:2]`` supplies the observed crop height and width. Clamping
    always uses allocation bounds. Active-region padding may be observed but
    is separately marked inactive; it is never silently redefined as an edge.
    """
    allocation_extent: tuple[int, int]
    active_extent: tuple[int, int] | None = None
    crop_origin: tuple[int, int] = (0, 0)
    active_origin: tuple[int, int] = (0, 0)

    def __post_init__(self):
        allocation = extent_xy(self.allocation_extent, "allocation_extent")
        active = allocation if self.active_extent is None else extent_xy(self.active_extent, "active_extent")
        origins = []
        for origin in (self.crop_origin, self.active_origin):
            if len(origin) != 2:
                raise ValueError("origins must contain (x,y)")
            origin = tuple(operator.index(n) for n in origin)
            if any(n < 0 for n in origin):
                raise ValueError("origins must be nonnegative")
            origins.append(origin)
        if any(origins[1][i] + active[i] > allocation[i] for i in range(2)):
            raise ValueError("active region must fit the allocation")
        object.__setattr__(self, "allocation_extent", allocation)
        object.__setattr__(self, "active_extent", active)
        object.__setattr__(self, "crop_origin", origins[0])
        object.__setattr__(self, "active_origin", origins[1])


class UnsupportedSampleError(ValueError):
    pass


@dataclass(frozen=True)
class SampleResult:
    values: np.ndarray
    supported: np.ndarray
    active_support: np.ndarray
    in_bounds: np.ndarray

    def require_supported(self, *, active=False):
        """Fail closed when a caller needs complete recorded sample support."""
        support = self.active_support if active else self.supported
        if not np.all(support):
            raise UnsupportedSampleError(f"{np.count_nonzero(~support)} sample(s) lack required support")
        return self.values


@dataclass(frozen=True)
class SamplingEnvelope:
    lower: np.ndarray
    upper: np.ndarray
    supported: np.ndarray
    active_support: np.ndarray
    coordinate_radius_texels: float
    kind: str = "documented_api_convex_hull"


def _texture(texture, domain):
    texture = np.asarray(texture)
    if texture.ndim < 2 or 0 in texture.shape[:2] or texture.dtype.kind not in "fiu":
        raise ValueError("texture must be a nonempty numeric (H,W,...) array")
    if domain is None:
        domain = TextureDomain((texture.shape[1], texture.shape[0]))
    if not isinstance(domain, TextureDomain):
        raise TypeError("domain must be TextureDomain or None")
    observed_extent = (texture.shape[1], texture.shape[0])
    if any(domain.crop_origin[i] + observed_extent[i] > domain.allocation_extent[i] for i in range(2)):
        raise ValueError("observed crop must fit the allocation")
    return texture, domain


def _coordinates(xy, dtype=None):
    result = np.asarray(xy, dtype=dtype)
    if result.ndim == 0 or result.shape[-1] != 2:
        raise ValueError("coordinates must have a final (x,y) axis")
    return result


def _expanded(mask, texture_ndim):
    return mask[(...,) + (None,) * (texture_ndim - 2)]


def _fetch(texture, indices, domain, address):
    """Fetch mapped integer taps; absent in-allocation observations stay absent."""
    if address not in ("zero", "clamp", "invalid"):
        raise ValueError("address must be zero, clamp or invalid")
    extent = np.asarray(domain.allocation_extent, dtype=np.int64)
    inside = np.all((indices >= 0) & (indices < extent), axis=-1)
    mapped = np.clip(indices, 0, extent - 1)
    local = mapped - np.asarray(domain.crop_origin, dtype=np.int64)
    crop_extent = np.asarray((texture.shape[1], texture.shape[0]), dtype=np.int64)
    observed = np.all((local >= 0) & (local < crop_extent), axis=-1)
    safe = np.clip(local, 0, crop_extent - 1)
    values = texture[safe[..., 1], safe[..., 0]]
    if address == "zero":
        supported = ~inside | observed
        values = np.where(_expanded(inside, texture.ndim), values, 0)
    elif address == "clamp":
        supported = observed
    else:
        supported = inside & observed
    origin = np.asarray(domain.active_origin, dtype=np.int64)
    active_extent = np.asarray(domain.active_extent, dtype=np.int64)
    active = np.all((mapped >= origin) & (mapped < origin + active_extent), axis=-1)
    active &= supported & (inside | (address == "clamp"))
    fill = np.nan if texture.dtype.kind == "f" else 0
    values = np.where(_expanded(supported, texture.ndim), values, fill)
    return SampleResult(values, supported, active, inside)


def load(texture, xy, *, domain=None, address="zero"):
    """Mip-zero integer Load; API out-of-allocation zero is the default.

    Explicit ``address='clamp'`` models source integer index clamping before
    Load. It is not a sampler state on a Load instruction. Input type and
    selected values (including uint32 and signed zero) are preserved.
    """
    texture, domain = _texture(texture, domain)
    xy = _coordinates(xy)
    if xy.dtype.kind not in "iu":
        raise TypeError("Load requires integer coordinates; use an explicit integer conversion")
    # Prevent unsigned-to-int64 wrap before checking the physical domain.
    if xy.dtype.kind == "u" and np.any(xy > np.iinfo(np.int64).max):
        raise ValueError("Load coordinates exceed the signed integer model")
    return _fetch(texture, xy.astype(np.int64), domain, address)


def _fraction_profile(mode, fraction_bits, fraction_rounding):
    arithmetic_dtype(mode)
    if fraction_bits is None and mode == "observed":
        fraction_bits = 8
    if fraction_bits is not None:
        fraction_bits = operator.index(fraction_bits)
        if not 0 <= fraction_bits <= 23:
            raise ValueError("fraction_bits must be between 0 and 23")
        if fraction_rounding not in ("nearest_even", "nearest_up", "floor", "ceil"):
            raise ValueError("unknown fraction rounding rule")
    return fraction_bits


def quantize_fraction(fraction, bits=8, *, rounding="nearest_even", mode="source"):
    """Snap [0,1] fractions; endpoint 1 is retained as a carry-equivalent tap."""
    dtype = arithmetic_dtype(mode)
    bits = _fraction_profile(mode, bits, rounding)
    fraction = np.asarray(fraction, dtype=dtype)
    if np.any(~np.isfinite(fraction)) or np.any((fraction < 0) | (fraction > 1)):
        raise ValueError("fraction must be finite and in [0,1]")
    if bits is None:
        return fraction.copy()
    scale = dtype(2 ** bits)
    scaled = (fraction * scale).astype(dtype)
    if rounding == "nearest_even":
        q = np.rint(scaled)
    elif rounding == "nearest_up":
        q = np.floor(scaled + dtype(0.5))
    elif rounding == "floor":
        q = np.floor(scaled)
    else:
        q = np.ceil(scaled)
    return (q / scale).astype(dtype)


def _safe_finite_coordinates(xy, extent):
    finite = np.all(np.isfinite(xy), axis=-1)
    # Preserve even off-resource fractional phases: the frozen weighted-sum
    # arithmetic can round differently although all taps clamp to one texel.
    # Only enormous coordinates are bounded to avoid int64 cast overflow.
    safe = np.where(finite[..., None], xy, 0)
    safe = np.clip(safe, -(2**50), 2**50)
    return safe, finite


def bilinear_texel(texture, xy, *, domain=None, mode="ideal", address="clamp",
                    fraction_bits=None, fraction_rounding="nearest_even",
                    interpolation="separable_lerp"):
    """Bilinear interpolation at explicit texel-index coordinates (...,2).

    ``weighted_sum`` reproduces the frozen portable order (00,10,01,11) in
    source mode; it is an arithmetic emulator, not a conformance assertion.
    The default separable lerp preserves finite constant fields exactly. It is
    still an explicit CPU arithmetic expression: opposite near-F32_MAX taps
    can overflow its subtraction, unlike a conformant finite convex filter.
    The documented envelope can reject such an emulator result. Radiance
    bounded to the source's FP16 range does not have this overflow mechanism.
    Zero-weight taps do not require observations and ignore NaN/Inf payloads;
    the API allows a different zero-weight nonfinite propagation choice.
    """
    texture, domain = _texture(texture, domain)
    if texture.dtype.kind != "f":
        raise TypeError("bilinear filtering here is defined for float textures")
    dtype = arithmetic_dtype(mode)
    bits = _fraction_profile(mode, fraction_bits, fraction_rounding)
    if interpolation not in ("separable_lerp", "weighted_sum"):
        raise ValueError("interpolation must be separable_lerp or weighted_sum")
    xy = _coordinates(xy, dtype)
    extent = np.asarray(domain.allocation_extent, dtype=dtype)
    in_bounds = np.all((xy >= dtype(-0.5)) & (xy <= extent - dtype(0.5)), axis=-1)
    safe, finite = _safe_finite_coordinates(xy, domain.allocation_extent)
    base = np.floor(safe).astype(np.int64)
    frac = (safe - base).astype(dtype)
    if bits is not None:
        frac = quantize_fraction(frac, bits, rounding=fraction_rounding, mode=mode)
    fx, fy = frac[..., 0], frac[..., 1]
    weights = ((dtype(1)-fx)*(dtype(1)-fy), fx*(dtype(1)-fy), (dtype(1)-fx)*fy, fx*fy)
    taps = []
    supported = finite.copy()
    active = finite.copy()
    for (dx, dy), weight in zip(((0,0), (1,0), (0,1), (1,1)), weights):
        tap = _fetch(texture, base + (dx,dy), domain, address)
        needed = weight != 0
        supported &= (~needed | tap.supported)
        active &= (~needed | tap.active_support)
        values = tap.values.astype(dtype)
        # This ignores unused NaN/Inf values as an explicitly named policy.
        values = np.where(_expanded(needed, texture.ndim), values, dtype(0))
        taps.append(values)
    if interpolation == "weighted_sum":
        values = np.zeros(xy.shape[:-1] + texture.shape[2:], dtype=dtype)
        for tap, weight in zip(taps, weights):
            values += (tap * _expanded(weight.astype(dtype), texture.ndim)).astype(dtype)
    else:
        def lerp(a, b, t):
            t = _expanded(t, texture.ndim)
            # Endpoint selection prevents 0 * NaN/Inf from unrelated values.
            with np.errstate(invalid="ignore", over="ignore"):
                mixed = (a + ((b-a).astype(dtype)*t).astype(dtype)).astype(dtype)
            return np.where(t == 0, a, np.where(t == 1, b, mixed))
        top = lerp(taps[0], taps[1], fx)
        bottom = lerp(taps[2], taps[3], fx)
        values = lerp(top, bottom, fy)
    values = np.where(_expanded(supported, texture.ndim), values, dtype(np.nan))
    return SampleResult(values, supported, active, in_bounds & finite)


def sample_bilinear(texture, uv, *, domain=None, mode="ideal", address="clamp",
                     fraction_bits=None, fraction_rounding="nearest_even",
                     interpolation="separable_lerp"):
    """Mip-zero normalized-UV sampling using *allocation*, never crop extent."""
    texture, domain = _texture(texture, domain)
    dtype = arithmetic_dtype(mode)
    uv = _coordinates(uv, dtype)
    finite = np.all(np.isfinite(uv), axis=-1)
    bounded = np.clip(np.where(finite[..., None], uv, 0), -1, 2)
    xy = uv_to_texel(bounded, domain.allocation_extent, mode=mode)
    xy = np.where(finite[..., None], xy, dtype(np.nan))
    return bilinear_texel(texture, xy, domain=domain, mode=mode, address=address,
                          fraction_bits=fraction_bits, fraction_rounding=fraction_rounding,
                          interpolation=interpolation)


def sample_point(texture, uv, *, domain=None, mode="ideal", address="clamp",
                   fraction_bits=None, fraction_rounding="nearest_even"):
    """Normalized point sample; optional fraction snapping occurs before floor.

    A selected integer-format value is preserved without conversion to float32.
    Float32 denorm flushing is not imposed by this CPU operation.
    """
    texture, domain = _texture(texture, domain)
    dtype = arithmetic_dtype(mode)
    bits = _fraction_profile(mode, fraction_bits, fraction_rounding)
    uv = _coordinates(uv, dtype)
    finite = np.all(np.isfinite(uv), axis=-1)
    in_bounds = np.all((uv >= 0) & (uv <= 1), axis=-1) & finite
    bounded = np.clip(np.where(finite[..., None], uv, 0), -1, 2)
    scaled = (bounded * np.asarray(domain.allocation_extent, dtype=dtype)).astype(dtype)
    integer = np.floor(scaled).astype(np.int64)
    if bits is not None:
        fraction = (scaled-integer).astype(dtype)
        snapped = quantize_fraction(fraction, bits, rounding=fraction_rounding, mode=mode)
        integer += (snapped == dtype(1)).astype(np.int64)
    result = _fetch(texture, integer, domain, address)
    supported = result.supported & finite
    fill = np.nan if texture.dtype.kind == "f" else 0
    values = np.where(_expanded(supported, texture.ndim), result.values, fill)
    return SampleResult(values, supported, result.active_support & finite, in_bounds)


def sample_cell_four_taps(texture, cells, cell_size, *, domain=None, mode="source",
                           fraction_bits=None, interpolation="separable_lerp"):
    """Source-shaped four SampleLevel calls then float32 sum*0.25, no UAV store."""
    texture, domain = _texture(texture, domain)
    dtype = arithmetic_dtype(mode)
    uv = cell_tap_uv(cells, cell_size, domain.allocation_extent, mode=mode)
    result = sample_bilinear(texture, uv, domain=domain, mode=mode,
                             fraction_bits=fraction_bits, interpolation=interpolation)
    axis = np.asarray(cells).ndim - 1
    values = np.zeros(result.values.shape[:axis] + result.values.shape[axis+1:], dtype=dtype)
    for k in range(4):
        values += np.take(result.values, k, axis=axis).astype(dtype)
    values = (values * dtype(0.25)).astype(dtype)
    return SampleResult(values, np.all(result.supported, axis=-1),
                        np.all(result.active_support, axis=-1), np.all(result.in_bounds, axis=-1))


def documented_bilinear_envelope(texture, uv, *, domain=None, address="clamp",
                                  coordinate_radius_texels=1/256):
    """Conservative API min/max envelope, not an exact sampler implementation.

    All texels admitted by a coordinate window around source-float32 uv*N-.5
    are included; the hull bounds any convex filter over those texels. Default
    radius is a conservative whole 8-bit step, not a universal hardware lattice.
    This uses the API's filtering min/max invariant, not a claim that arbitrary
    float32 shader lerps or weighted sums stay in their exact-real convex hull.
    In particular, an arithmetic emulator's overflow or constant-field rounding
    can be rejected by this envelope. It bounds addressing/filter choice, not
    source shader UV-expression or pre-store uncertainty. Callers must widen
    those inputs separately. NaN payloads do not have a finite ordered bound.
    """
    texture, domain = _texture(texture, domain)
    if texture.dtype.kind != "f":
        raise TypeError("envelope is defined for float textures")
    radius = float(coordinate_radius_texels)
    if not np.isfinite(radius) or not 0 <= radius < 0.5:
        raise ValueError("coordinate radius must be finite and in [0,0.5)")
    uv = _coordinates(uv, np.float32)
    finite = np.all(np.isfinite(uv), axis=-1)
    bounded = np.clip(np.where(finite[..., None], uv, 0), -1, 2)
    xy = uv_to_texel(bounded, domain.allocation_extent, mode="source").astype(np.float64)
    xy, _ = _safe_finite_coordinates(xy, domain.allocation_extent)
    left = np.floor(xy-radius).astype(np.int64)
    right = np.floor(xy+radius).astype(np.int64) + 1
    shape = xy.shape[:-1] + texture.shape[2:]
    lower, upper = np.full(shape, np.inf), np.full(shape, -np.inf)
    supported, active = finite.copy(), finite.copy()
    for dy in range(3):
        for dx in range(3):
            index = left + (dx,dy)
            needed = np.all(index <= right, axis=-1)
            tap = _fetch(texture, index, domain, address)
            supported &= ~needed | tap.supported
            active &= ~needed | tap.active_support
            values = tap.values.astype(np.float64)
            lower = np.minimum(lower, np.where(_expanded(needed, texture.ndim), values, np.inf))
            upper = np.maximum(upper, np.where(_expanded(needed, texture.ndim), values, -np.inf))
    lower = np.where(_expanded(supported, texture.ndim), lower, np.nan)
    upper = np.where(_expanded(supported, texture.ndim), upper, np.nan)
    return SamplingEnvelope(lower, upper, supported, active, radius)


def microcase_inputs():
    """Small deterministic GPU-request inputs; all arrays are C-order float32.

    Array hashes are over the little-endian C-order bytes, with shapes and roles
    documented in evidence/SAMPLING.md. These are synthetic test vectors.
    """
    yy, xx = np.mgrid[:11, :17]
    phases = np.array([.499, .5, .5001, .501, .502], dtype=np.float32)
    phase_uv = np.column_stack(((phases + np.float32(.5)) / np.float32(2),
                                np.full(phases.size, .5, dtype=np.float32)))
    centres = np.array([[3,2], [3.25,2.5]], dtype=np.float32)
    ramp_uv = (centres + np.float32(.5)) / np.array([17,11], dtype=np.float32)
    wrong_ramp_uv = (centres + np.float32(.5)) / np.array([13,7], dtype=np.float32)
    return {
        "phase_texture": np.array([[1.,1.04]], dtype=np.float32),
        "phase_uv": phase_uv,
        "ramp_texture": (xx+10*yy).astype(np.float32),
        "ramp_uv": ramp_uv,
        "wrong_active_extent_uv": wrong_ramp_uv,
        "quarter_impulses": np.eye(16,dtype=np.float32).reshape(16,4,4),
        "eighth_impulses": np.eye(64,dtype=np.float32).reshape(64,8,8),
    }
