"""Native Anchor 16.16 sums, exact byte layout and pre-store uncertainty.

This is the native shader's emulated uint64 contract. The combined shader uses
a different1/1024 uint32 format; it must not be passed through this API implicitly.
"""
from dataclasses import dataclass

import numpy as np

from .arithmetic import f32, f32_add, f32_div, f32_mul, to_uint32
from .storage import NonIdentifiableError, fp16_preimage_f32


UINT32_MASK = (1 << 32) - 1
UINT64_MASK = (1 << 64) - 1
FRACTION_SCALE = 65536
PHYSICAL_CAP = 16
SUM_BUFFER_BYTES = 32


def _u32(value):
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("expected a uint32 integer") from exc
    if n != value or not 0 <= n <= UINT32_MASK:
        raise ValueError("expected a uint32 integer")
    return n


def uint64_add_words(low, high, increment):
    """One returned-old-value low atomic plus high-word carry, modulo2**64.

    Atomic order can permute, but every carry is determined from that atomic's
    own returned old low word. Reading the composed value requires the host UAV
    ordering barrier after all increments; this sequential model is not a race
    detector or a claim of device execution.
    """
    low, high, increment = _u32(low), _u32(high), _u32(increment)
    carry = int(low > UINT32_MASK - increment)
    return (low + increment) & UINT32_MASK, (high + carry) & UINT32_MASK


def compose_uint64(low, high):
    return _u32(low) | (_u32(high) << 32)


def reconstruct_float32(low, high):
    """Source Gain: float(low)+float(high)*4294967296, separate stages."""
    return f32_add(f32(_u32(low)), f32_mul(f32(_u32(high)), np.float32(4294967296)))


def quantize_u16_16(physical_level):
    """uint(min(max(float32(level),0),16)*65536), finite validated domain.

    The cap is16 in physical linear level units before scaling, not16 fixed-point
    units, and no FP16 store belongs between level and this source expression.
    """
    a = f32(physical_level)
    if not np.isfinite(a).all():
        raise ValueError("nonfinite pre-store level has no established portable atomic contract")
    return to_uint32(f32_mul(np.clip(a, 0, PHYSICAL_CAP), FRACTION_SCALE))


class FrameSums:
    """Exact32-byte native sum buffer: current0/4, recalled8/12, count16.

    Bytes20..31 are reserved padding but participate in a full reset. Accumulate
    current/recalled on the *same supplied immutable support mask*. Count is a
    uint32 word; deliberate count overflow is exposed, not silently widened.
    """
    def __init__(self, words=None):
        if words is None:
            self.words = np.zeros(8, np.uint32)
        else:
            w = list(words)
            if len(w) != 8:
                raise ValueError("native sum buffer needs exactly8 uint32 words")
            self.words = np.array([_u32(v) for v in w], np.uint32)

    @classmethod
    def from_bytes(cls, buffer):
        if len(buffer) != SUM_BUFFER_BYTES:
            raise ValueError("native sum buffer must be exactly32 bytes")
        return cls(np.frombuffer(buffer, dtype="<u4"))

    def to_bytes(self):
        return self.words.astype("<u4", copy=False).tobytes()

    def reset(self):
        self.words.fill(0)
        return self

    @property
    def current_total(self):
        return compose_uint64(self.words[0], self.words[1])

    @property
    def recalled_total(self):
        return compose_uint64(self.words[2], self.words[3])

    @property
    def count(self):
        return int(self.words[4])

    def add_quantized(self, current, recalled):
        c, r = np.broadcast_arrays(np.asarray(current), np.asarray(recalled))
        # Validate before mutating; a malformed observation must not leave a
        # partially accumulated buffer that looks usable to a later experiment.
        pairs = [(_u32(ci), _u32(ri)) for ci, ri in zip(c.flat, r.flat)]
        for ci, ri in pairs:
            low, high = uint64_add_words(self.words[0], self.words[1], ci)
            self.words[0], self.words[1] = low, high
            low, high = uint64_add_words(self.words[2], self.words[3], ri)
            self.words[2], self.words[3] = low, high
            self.words[4] = (int(self.words[4]) + 1) & UINT32_MASK
        return self

    def add(self, current, recalled, *, support=None):
        c, r = f32(current), f32(recalled)
        if c.shape != r.shape:
            raise ValueError("current/recalled must use the same cell population")
        mask = np.ones(c.shape, bool) if support is None else np.asarray(support, bool)
        if mask.shape != c.shape:
            raise ValueError("support must match the cell population")
        # Unused cells are not inspected or converted, matching the source gate.
        return self.add_quantized(quantize_u16_16(c[mask]), quantize_u16_16(r[mask]))

    def float_totals(self):
        return (reconstruct_float32(self.words[0], self.words[1]),
                reconstruct_float32(self.words[2], self.words[3]))

    def source_ratio(self):
        current, recalled = self.float_totals()
        if current <= 0 or self.count == 0:
            return np.float32(1)
        return np.minimum(f32_div(recalled, current), np.float32(4))

    def source_coverage(self, total_cells):
        if not np.isfinite(total_cells) or total_cells < 1:
            raise ValueError("total_cells must be finite and >=1")
        return f32_div(f32(self.count), f32(total_cells))


def _sum_increments(values):
    # Python integers keep the analytic total exact, without uint64 reduction wrap.
    return sum(map(int, quantize_u16_16(values).flat))


def _ratio_from_totals(current, recalled, count):
    if not count or not current:
        return 1.0
    c = reconstruct_float32(current & UINT32_MASK, current >> 32)
    r = reconstruct_float32(recalled & UINT32_MASK, recalled >> 32)
    return float(np.minimum(f32_div(r, c), np.float32(4)))


@dataclass(frozen=True)
class FrameSumBounds:
    current_min: int
    current_max: int
    recalled_min: int
    recalled_max: int
    current_stored_estimate: int
    recalled_stored_estimate: int
    count: int
    rounding: str

    def __post_init__(self):
        count = _u32(self.count)
        if self.rounding not in ("rne", "rtz"):
            raise ValueError("sum bounds require an explicit supported rounding")
        for low, estimate, high in ((self.current_min, self.current_stored_estimate, self.current_max),
                                    (self.recalled_min, self.recalled_stored_estimate, self.recalled_max)):
            if any(int(v) != v for v in (low, estimate, high)) or not 0 <= low <= estimate <= high <= count * (1 << 20):
                raise ValueError("sum bounds exceed the native cap16/count domain")

    def require_exact_totals(self):
        """Reject a claim of exact pre-store atomics unless the bounds collapse."""
        if self.current_min != self.current_max or self.recalled_min != self.recalled_max:
            raise NonIdentifiableError("stored FP16 fields admit distinct valid pre-store atomic totals")
        return self.current_min, self.recalled_min, self.count

    def ratio_interval(self):
        """Source float32 ratio envelope, including unmeasured identity fallback.

        Valid native populations have count<=2**32-1 and increment<=2**20,
        hence total<2**52 and high<2**20. The high word and high*2**32 are then
        exactly representable as float32. Low-word rounding and final addition
        are monotone; at a low-word wrap, float(0xffffffff)==2**32 makes the
        previous rounded endpoint equal the next high-word origin. Endpoint
        ratios therefore bound the source reconstruction on this domain.
        """
        if not self.count or self.current_max == 0:
            return 1.0, 1.0
        lo = _ratio_from_totals(self.current_max, self.recalled_min, self.count)
        # Smallest positive total1 is conservative if zero is also compatible.
        hi = _ratio_from_totals(max(self.current_min, 1), self.recalled_max, self.count)
        if self.current_min == 0:
            lo, hi = min(lo, 1.0), max(hi, 1.0)
        return lo, hi

    def as_dict(self):
        low, high = self.ratio_interval()
        return {
            "current_min": self.current_min, "current_max": self.current_max,
            "recalled_min": self.recalled_min, "recalled_max": self.recalled_max,
            "current_stored_estimate": self.current_stored_estimate,
            "recalled_stored_estimate": self.recalled_stored_estimate,
            "count": self.count, "rounding": self.rounding,
            "source_ratio_estimate": _ratio_from_totals(self.current_stored_estimate,
                                                        self.recalled_stored_estimate, self.count),
            "source_ratio_min": low, "source_ratio_max": high,
            "exact_totals_identifiable": (self.current_min == self.current_max and
                                           self.recalled_min == self.recalled_max),
        }


def frame_sum_bounds(current_stored, recalled_stored, fixed_mask, *, rounding="rne"):
    """Exact integer bounds from finite FP16 fields and a frozen support mask.

    The chosen rounding model defines each independent float32 preimage. These
    bounds are conditional on that model; they do not restore absent atomics.
    Source expressions and cap16 are applied to discrete endpoints, avoiding the
    inclusive-midpoint looseness of continuous half-ULP estimates.
    """
    c, r = f32(current_stored), f32(recalled_stored)
    mask = np.asarray(fixed_mask, dtype=bool)
    if c.shape != r.shape or mask.shape != c.shape:
        raise ValueError("stored fields and fixed support must have equal shape")
    count = int(mask.sum())
    if count > UINT32_MASK:
        raise ValueError("count exceeds the native uint32 support contract")
    c, r = c[mask], r[mask]
    cb = fp16_preimage_f32(c, rounding=rounding)
    rb = fp16_preimage_f32(r, rounding=rounding)
    return FrameSumBounds(_sum_increments(cb.lower), _sum_increments(cb.upper),
                          _sum_increments(rb.lower), _sum_increments(rb.upper),
                          _sum_increments(c), _sum_increments(r), count, rounding)
