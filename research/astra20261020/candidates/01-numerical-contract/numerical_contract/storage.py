"""Explicit float32 -> binary16 storage models and discrete preimage bounds.

These are named numerical models, not universal typed-UAV hardware assertions.
The input staging is float32; results are expanded float32 unless bits are asked
for. Subnormals are preserved by default. NaN payloads are canonicalized by this
model only; actual GPU NaN payload and denormal behavior require a local witness.
"""
from dataclasses import dataclass

import numpy as np


_F16_MAX = np.float32(65504.0)
_F32_MAX = np.finfo(np.float32).max


def fp16_bits(values, *, rounding="rne", overflow="ieee", subnormals="preserve"):
    """Convert float32-staged values to binary16 bits with explicit policies.

    ``rne`` means nearest, ties to even. ``rtz`` truncates magnitude, including
    finite overflow to the largest finite half. ``overflow='saturate'`` clamps
    *finite* inputs to +/-65504 before conversion; infinities remain infinities.
    ``subnormals='flush'`` is a separate experimental model, preserving the sign
    of the resulting zero. None of these policies is silently inferred per GPU.
    """
    if rounding not in ("rne", "rtz"):
        raise ValueError("rounding must be 'rne' or 'rtz'")
    if overflow not in ("ieee", "saturate"):
        raise ValueError("overflow must be 'ieee' or 'saturate'")
    if subnormals not in ("preserve", "flush"):
        raise ValueError("subnormals must be 'preserve' or 'flush'")
    a = np.asarray(values, dtype=np.float32)
    if overflow == "saturate":
        a = np.where(np.isfinite(a), np.clip(a, -_F16_MAX, _F16_MAX), a)
    with np.errstate(over="ignore", invalid="ignore"):
        nearest = a.astype(np.float16)
        bits = nearest.view(np.uint16).copy()
        if rounding == "rtz":
            away = np.isfinite(a) & (np.abs(nearest.astype(np.float32)) > np.abs(a))
            # Sign-magnitude binary16: decrement magnitude when RNE overshot.
            bits = np.where(away, bits - np.uint16(1), bits).astype(np.uint16)
    sign = ((a.view(np.uint32) >> np.uint32(16)) & np.uint32(0x8000)).astype(np.uint16)
    bits = np.where(np.isnan(a), sign | np.uint16(0x7e00), bits).astype(np.uint16)
    if subnormals == "flush":
        bits = np.where((bits & np.uint16(0x7c00)) == 0,
                        bits & np.uint16(0x8000), bits).astype(np.uint16)
    return np.asarray(bits, dtype=np.uint16)


def store_fp16(values, *, rounding="rne", overflow="ieee", subnormals="preserve"):
    """Store at one declared boundary, then expand the stored bits to float32."""
    return fp16_bits(values, rounding=rounding, overflow=overflow,
                     subnormals=subnormals).view(np.float16).astype(np.float32)


def sanitize_radiance(values):
    """Source-shaped FSRDFlatDetailCommon SanitizeRadiance, lane by lane.

    Nonfinite RGB ->0, finite RGB ->[0,65500]. This operation is separate from a
    store: e.g.65500 stores as65472 in RTZ and65504 in RNE. Signed-zero min/max tie
    bits are not asserted as a hardware guarantee by this numeric clamp model.
    """
    a = np.asarray(values, dtype=np.float32)
    return np.where(np.isfinite(a), np.clip(a, np.float32(0), np.float32(65500)),
                    np.float32(0)).astype(np.float32)


@dataclass(frozen=True)
class FP16Preimage:
    """Inclusive float32 endpoints mapping to a finite stored half payload.

    Endpoints are actual float32 values, not open real-valued bounds. Signed
    zeros are separate payloads. Bounds assume finite inputs, IEEE overflow and
    preserved half subnormals; unsupported alternative policies are not guessed.
    """
    lower: np.ndarray
    upper: np.ndarray
    stored_bits: np.ndarray
    rounding: str

    def contains(self, values):
        a = np.asarray(values, dtype=np.float32)
        in_range = np.isfinite(a) & (a >= self.lower) & (a <= self.upper)
        same_zero_sign = (a != 0) | (np.signbit(a) == ((self.stored_bits & 0x8000) != 0))
        return in_range & same_zero_sign


def fp16_preimage_f32(stored, *, rounding="rne"):
    """Exact float32 preimage endpoints for finite, exactly expanded half data.

    Ties-to-even endpoints are included/excluded by payload parity. RTZ bounds
    end just before the next magnitude. At the finite extremes RTZ admits every
    finite float32 of larger magnitude; RNE ends just below +/-65520.
    """
    if rounding not in ("rne", "rtz"):
        raise ValueError("rounding must be 'rne' or 'rtz'")
    a = np.asarray(stored, dtype=np.float32)
    if not np.isfinite(a).all():
        raise ValueError("preimage requires finite stored FP16 values")
    bits = fp16_bits(a, rounding="rne")
    expanded = bits.view(np.float16).astype(np.float32)
    if not np.array_equal(expanded.view(np.uint32), a.view(np.uint32)):
        raise ValueError("input is not an exactly expanded FP16 payload")
    magnitude = bits & np.uint16(0x7fff)
    positive = magnitude.view(np.float16)
    v = positive.astype(np.float64)
    with np.errstate(over="ignore", invalid="ignore"):
        prev = np.nextafter(positive, np.float16(-np.inf)).astype(np.float64)
        following = np.nextafter(positive, np.float16(np.inf)).astype(np.float64)
    if rounding == "rne":
        #65536 is the virtual next finite value for the overflow midpoint.
        following = np.where(magnitude == 0x7bff, 65536.0, following)
        low = np.maximum((prev + v) * .5, 0).astype(np.float32)
        high = ((following + v) * .5).astype(np.float32)
        odd = (magnitude & np.uint16(1)) != 0
        low = np.where(odd, np.nextafter(low, np.float32(np.inf)), low)
        high = np.where(odd, np.nextafter(high, np.float32(-np.inf)), high)
    else:
        low = v.astype(np.float32)
        high = np.nextafter(following.astype(np.float32), np.float32(-np.inf))
        high = np.where(magnitude == 0x7bff, _F32_MAX, high)
    negative = (bits & np.uint16(0x8000)) != 0
    lower = np.where(negative, -high, low).astype(np.float32)
    upper = np.where(negative, -low, high).astype(np.float32)
    return FP16Preimage(lower, upper, bits, rounding)


class NonIdentifiableError(ValueError):
    """An exact observable was requested but compatible inputs disagree."""
