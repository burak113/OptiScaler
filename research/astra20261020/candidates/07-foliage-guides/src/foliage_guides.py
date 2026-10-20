"""Original-guide observer; no semantic labels and no production writes.

The experimental multiplier is a geometric cosine proxy, NOT an AMD RR
confidence input or a calibrated probability. All production fields are inputs
only. Unknown chronology/depth support returns identity, not manufactured history.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag
import numpy as np


class SupportFlag(IntFlag):
    CURRENT_FINITE = 1
    SPATIAL = 2
    MOTION_FINITE = 4
    CHRONOLOGICAL = 8
    IN_PREVIOUS_CROP = 16
    CATEGORY_MATCH = 32
    DEPTH_MATCH = 64
    TEMPORAL_SUPPORTED = 128


@dataclass(frozen=True)
class GuideFrame:
    packed_normal_roughness: np.ndarray
    depth: np.ndarray
    motion: np.ndarray
    frame_id: int
    crop_origin: tuple[float, float]
    render_extent: tuple[int, int]
    depth_is_positive_linear: bool = False
    reset: bool = False

    def validate(self) -> None:
        if self.packed_normal_roughness.dtype != np.uint32:
            raise TypeError("normal/roughness must be original uint32 R10G10B10A2")
        if self.depth.ndim != 2 or self.packed_normal_roughness.shape != self.depth.shape:
            raise ValueError("guide/depth shape mismatch")
        if self.motion.shape != self.depth.shape + (4,):
            raise ValueError("motion must retain all four native channels")
        if any(x <= 0 for x in self.render_extent):
            raise ValueError("render extent must be positive")


@dataclass(frozen=True)
class GuideObservation:
    angular_dispersion: np.ndarray
    relative_depth_span: np.ndarray
    temporal_innovation: np.ndarray
    temporal_supported: np.ndarray
    flags: np.ndarray
    experimental_history_multiplier: np.ndarray


def normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), np.float32(1e-20))


def unpack_normal_roughness(words: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Mirror FSRDPreprocessCommon.hlsli oct decode; category zero is valid."""
    w = np.asarray(words, dtype=np.uint32)
    x = ((w & 1023).astype(np.float32) / np.float32(1023)) * 2 - 1
    y = (((w >> 10) & 1023).astype(np.float32) / np.float32(1023)) * 2 - 1
    z = 1 - np.abs(x) - np.abs(y)
    t = np.maximum(-z, 0)
    n = np.stack((x + np.where(x >= 0, -t, t),
                  y + np.where(y >= 0, -t, t), z), axis=-1)
    return (normalize(n), ((w >> 20) & 1023).astype(np.float32) / 1023,
            ((w >> 30) & 3).astype(np.uint8))


def pack_normal_roughness(normal: np.ndarray, roughness: np.ndarray | float,
                          category: np.ndarray | int = 0, quantization_bits: int = 10) -> np.ndarray:
    """Synthetic encoder. Coarser quantization is an explicit intervention."""
    if not 2 <= quantization_bits <= 10:
        raise ValueError("quantization_bits must be 2..10")
    n = normalize(normal)
    p = n[..., :2] / np.maximum(np.sum(np.abs(n), axis=-1, keepdims=True), 1e-20)
    folded = (1 - np.abs(p[..., ::-1])) * np.where(p >= 0, 1, -1)
    p = np.where((n[..., 2] < 0)[..., None], folded, p)
    u = np.clip(p * .5 + .5, 0, 1)
    levels = (1 << quantization_bits) - 1
    u = np.rint(u * levels) / levels
    q = np.rint(u * 1023).astype(np.uint32)
    r = np.rint(np.clip(roughness, 0, 1) * 1023).astype(np.uint32)
    c = np.asarray(category, dtype=np.uint32)
    if np.any(c > 3):
        raise ValueError("category must be original two-bit code, not a semantic class")
    return q[..., 0] | (q[..., 1] << 10) | (r << 20) | (c << 30)


def bilinear_coordinates(height: int, width: int, motion_uv: np.ndarray,
                         render_extent: tuple[int, int], current_origin: tuple[float, float],
                         previous_origin: tuple[float, float], previous_shape: tuple[int, int]
                         ) -> tuple[list[tuple[np.ndarray, np.ndarray, np.ndarray]], np.ndarray]:
    """Pixel-centre convention: integer local indices identify texel centres.

    All four taps must exist, even at zero fractional weight. This conservative
    support rule intentionally excludes the last row/column at integer motion.
    It is ideal CPU bilinear, not bit-exact D3D sampler emulation.
    """
    yy, xx = np.indices((height, width), dtype=np.float32)
    uv = np.asarray(motion_uv, dtype=np.float32)
    finite = np.all(np.isfinite(uv), axis=-1)
    qx = xx + np.float32(current_origin[0]) - np.float32(previous_origin[0]) + uv[..., 0] * np.float32(render_extent[0])
    qy = yy + np.float32(current_origin[1]) - np.float32(previous_origin[1]) + uv[..., 1] * np.float32(render_extent[1])
    qx = np.where(finite, qx, 0)
    qy = np.where(finite, qy, 0)
    # Range-check floats before integer conversion; huge finite motion is invalid.
    inside = finite & (qx >= 0) & (qy >= 0) & (qx < previous_shape[1] - 1) & (qy < previous_shape[0] - 1)
    safe_x = np.where(inside, qx, 0)
    safe_y = np.where(inside, qy, 0)
    x0, y0 = np.floor(safe_x).astype(np.int64), np.floor(safe_y).astype(np.int64)
    fx, fy = safe_x - x0.astype(np.float32), safe_y - y0.astype(np.float32)
    taps = [(y0, x0, (1-fx)*(1-fy)), (y0, x0+1, fx*(1-fy)),
            (y0+1, x0, (1-fx)*fy), (y0+1, x0+1, fx*fy)]
    # One-pixel crops cannot provide a bilinear footprint. Safe indices are only
    # for a non-contributing read; callers still use the explicit inside mask.
    taps = [(np.clip(y, 0, previous_shape[0]-1), np.clip(x, 0, previous_shape[1]-1), w)
            for y, x, w in taps]
    return taps, inside


def sample_bilinear(array: np.ndarray, taps: list[tuple[np.ndarray, np.ndarray, np.ndarray]]) -> np.ndarray:
    tail = (1,) * (array.ndim - 2)
    result = np.zeros(taps[0][0].shape + array.shape[2:], dtype=np.float32)
    for y, x, w in taps:
        result += np.asarray(array[y, x], dtype=np.float32) * w.reshape(w.shape + tail)
    return result


def observe_guides(current: GuideFrame, previous: GuideFrame | None = None, *,
                   enabled: bool = False, depth_relative_tolerance: float = .02) -> GuideObservation:
    """Measure guide evidence only. Never consumes radiance or hidden layer truth.

    TEMPORAL_SUPPORTED means numerical comparability of the observed fields,
    not proven raw physical geometry or permission to reuse denoiser history.
    An invalid raw depth sanitized to the same finite value is unidentifiable
    without the native raw-validity provenance. No active consumer is proposed.

    Depth is in the same linear scene units as motion B. The caller must prove
    positive-linear depth semantics explicitly. The relative tolerance is an
    experiment setting, frozen before holdouts, not a fitted game threshold.
    """
    current.validate()
    shape = current.depth.shape
    zeros = lambda: np.zeros(shape, dtype=np.float32)
    flags = np.zeros(shape, dtype=np.uint16)
    supported = np.zeros(shape, dtype=bool)
    identity = np.ones(shape, dtype=np.float32)
    if not enabled:
        return GuideObservation(zeros(), zeros(), zeros(), supported, flags, identity)
    if not (np.isfinite(depth_relative_tolerance) and depth_relative_tolerance >= 0):
        raise ValueError("invalid depth tolerance")
    n, _, category = unpack_normal_roughness(current.packed_normal_roughness)
    d = np.asarray(current.depth, dtype=np.float32)
    valid = np.isfinite(d) & (d > 0) & np.all(np.isfinite(n), axis=-1)
    flags[valid] |= np.uint16(SupportFlag.CURRENT_FINITE)
    total_n = np.zeros(shape + (3,), dtype=np.float32)
    count = np.zeros(shape, dtype=np.float32)
    minimum = np.full(shape, np.inf, dtype=np.float32)
    maximum = np.full(shape, -np.inf, dtype=np.float32)
    h, w = shape
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            ys, xs = slice(max(0, dy), min(h, h+dy)), slice(max(0, dx), min(w, w+dx))
            yn, xn = slice(max(0, -dy), min(h, h-dy)), slice(max(0, -dx), min(w, w-dx))
            v = valid[yn, xn]
            total_n[ys, xs] += np.where(v[..., None], n[yn, xn], 0)
            count[ys, xs] += v
            minimum[ys, xs] = np.minimum(minimum[ys, xs], np.where(v, d[yn, xn], np.inf))
            maximum[ys, xs] = np.maximum(maximum[ys, xs], np.where(v, d[yn, xn], -np.inf))
    spatial = valid & (count >= 3)
    flags[spatial] |= np.uint16(SupportFlag.SPATIAL)
    mean_n = total_n / np.maximum(count[..., None], 1)
    dispersion = np.where(spatial, np.clip(1 - np.linalg.norm(mean_n, axis=-1), 0, 1), 0).astype(np.float32)
    # No arbitrary sky classification or material filter is applied. A rigid
    # crease and a coverage mixture can both produce dispersion.
    span = np.zeros(shape, dtype=np.float32)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        np.divide(maximum-minimum, np.maximum(d, 1e-20), out=span, where=spatial)
    span = np.where(spatial, np.maximum(span, 0), 0).astype(np.float32)
    span = np.nan_to_num(span, nan=0.0, posinf=np.finfo(np.float32).max, neginf=0.0)
    innovation = zeros()
    finite_motion = np.all(np.isfinite(current.motion[..., :3]), axis=-1)
    flags[finite_motion] |= np.uint16(SupportFlag.MOTION_FINITE)
    chronology = (previous is not None and not current.reset and
                  previous.frame_id + 1 == current.frame_id and
                  previous.render_extent == current.render_extent)
    if not chronology:
        return GuideObservation(dispersion, span, innovation, supported, flags, identity)
    previous.validate()
    flags[:] |= np.uint16(SupportFlag.CHRONOLOGICAL)
    taps, inside = bilinear_coordinates(h, w, current.motion[..., :2], current.render_extent,
                                        current.crop_origin, previous.crop_origin, previous.depth.shape)
    flags[inside] |= np.uint16(SupportFlag.IN_PREVIOUS_CROP)
    pn, _, pc = unpack_normal_roughness(previous.packed_normal_roughness)
    pd = np.asarray(previous.depth, dtype=np.float32)
    with np.errstate(over="ignore", invalid="ignore"):
        predicted = d + np.asarray(current.motion[..., 2], dtype=np.float32)
    valid_prediction = np.isfinite(predicted) & (predicted > 0)
    safe_prediction = np.where(valid_prediction, predicted, 0)
    material_match = np.ones(shape, dtype=bool)
    depth_match = valid_prediction.copy()
    previous_finite = np.ones(shape, dtype=bool)
    angular = zeros()
    for y, x, weight in taps:
        previous_finite &= np.isfinite(pd[y, x]) & (pd[y, x] > 0)
        material_match &= pc[y, x] == category
        scale = np.maximum(np.maximum(np.abs(safe_prediction), np.abs(pd[y, x])), 1e-6)
        depth_match &= np.abs(safe_prediction - pd[y, x]) <= depth_relative_tolerance * scale
        angular += weight.astype(np.float32) * np.clip(1 - np.sum(n * pn[y, x], axis=-1), 0, 2)
    flags[inside & material_match] |= np.uint16(SupportFlag.CATEGORY_MATCH)
    trusted_depth = current.depth_is_positive_linear and previous.depth_is_positive_linear
    if trusted_depth:
        flags[inside & previous_finite & depth_match] |= np.uint16(SupportFlag.DEPTH_MATCH)
    supported = valid & finite_motion & inside & previous_finite & material_match & depth_match & trusted_depth
    flags[supported] |= np.uint16(SupportFlag.TEMPORAL_SUPPORTED)
    innovation[supported] = angular[supported]
    # Cosine agreement is interpretable geometry, not inferred mixture coverage.
    # Unsupported evidence returns identity. An adapter may display this number;
    # it must not silently substitute it for an existing native validity mask.
    identity[supported] = np.clip(1 - angular[supported], 0, 1)
    return GuideObservation(dispersion, span, innovation, supported, flags, identity)
