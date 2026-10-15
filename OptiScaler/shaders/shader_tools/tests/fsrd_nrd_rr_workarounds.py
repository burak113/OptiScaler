"""CPU oracle for a test-only, pre-RR chroma impulse experiment.

This is not a second output denoiser: every resulting RGB sample must enter RR.
Alpha, geometry, motion and albedo are never changed. The raw-input histories
must be from the same ordered domain and must be cleared on any discontinuity.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class Parameters:
    strength: float = 1.0
    chroma_floor: float = 0.05
    mad_scale: float = 3.0
    depth_relative_tolerance: float = 0.01
    normal_oct_tolerance: float = 0.02
    roughness_tolerance: float = 0.05
    luma_floor: float = 0.001
    temporal_tolerance: float = 1.0


def luma(rgb):
    rgb = np.asarray(rgb, dtype=np.float32)
    return ((rgb[..., 0] + np.float32(2)*rgb[..., 1]) + rgb[..., 2])*np.float32(.25)


def chroma(rgb, floor):
    rgb = np.asarray(rgb, dtype=np.float32)
    co = (rgb[..., 0] - rgb[..., 2])*np.float32(.5)
    cg = ((-rgb[..., 0] + np.float32(2)*rgb[..., 1]) - rgb[..., 2])*np.float32(.25)
    return np.stack((co, cg), axis=-1)/np.maximum(luma(rgb), np.float32(floor))[..., None]


def normal_channels(value):
    value = np.asarray(value)
    if value.ndim == 2 and value.dtype == np.dtype('<u4'):
        result = np.empty(value.shape+(4,), dtype=np.float32)
        for channel in range(3):
            result[..., channel] = ((value >> (channel*10)) & 1023).astype(np.float32)/np.float32(1023)
        result[..., 3] = (value >> 30).astype(np.float32)/np.float32(3)
        return result
    if value.ndim != 3 or value.shape[-1] != 4:
        raise ValueError('normals must be original RGB10A2 words or decoded float4')
    return value.astype(np.float32)


def _active(value):
    return (np.all(np.isfinite(value), axis=-1) & np.all(value[..., :3] >= 0, axis=-1) &
            np.all(value[..., :3] <= 65504, axis=-1) & (value[..., 3] >= 0))


def _guide(depth, normal, other_depth, other_normal, p):
    return (np.isfinite(depth) & np.isfinite(other_depth) & (depth != 0) & (other_depth != 0) &
            np.all(np.isfinite(normal), axis=-1) & np.all(np.isfinite(other_normal), axis=-1) &
            (np.abs(depth-other_depth) <= np.float32(p.depth_relative_tolerance)*np.maximum(np.abs(depth), np.float32(.001))) &
            np.all(np.abs(normal[..., :2]-other_normal[..., :2]) <= np.float32(p.normal_oct_tolerance), axis=-1) &
            (np.abs(normal[..., 2]-other_normal[..., 2]) <= np.float32(p.roughness_tolerance)) &
            (normal[..., 3] == other_normal[..., 3]))


def _prepare(frame):
    value = np.asarray(frame['signal'])
    if value.dtype != np.dtype('<f2') or value.ndim != 3 or value.shape[-1] != 4:
        raise ValueError('signal must be original finite RGBA16F words')
    depth = np.asarray(frame['depth'], dtype=np.float32)
    normal = normal_channels(frame['normals'])
    motion = np.asarray(frame['motion'], dtype=np.float32)
    if depth.shape != value.shape[:2] or normal.shape != value.shape or motion.shape != value.shape:
        raise ValueError('signal/guides must have the same extent')
    return value, depth, normal, motion


def _project(uv, motion, width, height):
    previous_uv = uv+motion[..., :2]
    valid = (np.all(np.isfinite(motion[..., :3]), axis=-1) & np.all(np.isfinite(previous_uv), axis=-1) &
             np.all(previous_uv >= 0, axis=-1) & np.all(previous_uv < 1, axis=-1))
    safe_uv = np.where(valid[..., None], previous_uv, np.float32(0))
    xy = np.floor(safe_uv*np.array((width, height), dtype=np.float32)).astype(np.int32)
    xy[..., 0] = np.clip(xy[..., 0], 0, width-1)
    xy[..., 1] = np.clip(xy[..., 1], 0, height-1)
    return previous_uv, xy, valid


def _sample(value, xy):
    return value[xy[..., 1], xy[..., 0]]


def _median(values, valid, counts):
    ordered = np.sort(np.where(valid[..., None], values, np.float32(np.inf)), axis=0)
    # Match the shader's count<5 identity BEFORE any median indexing. Counts
    # are unsigned evidence words; subtracting one at zero would wrap.
    result = np.zeros(counts.shape+(2,), dtype=np.float32)
    yy, xx = np.where(counts >= 5)
    supported = counts[yy, xx].astype(np.int32)
    if supported.size:
        first = (supported-1)//2
        second = supported//2
        result[yy, xx] = (ordered[first, yy, xx]+ordered[second, yy, xx])*np.float32(.5)
    return result


def condition(current, previous=None, older=None, *, mode=2, parameters=Parameters()):
    """Return conditioned RGBA16F and shader-equivalent uint4 gate evidence.

    Mode0 and strength0 return exact source words. Mode1 requires one previous
    raw frame, mode2 requires two. Nearest-pixel history support is intentional;
    no claim is made that primary-surface motion tracks reflected object motion.
    """
    source, depth, normal, motion = _prepare(current)
    output = source.copy()
    height, width = depth.shape
    evidence = np.zeros((height, width, 4), dtype='<u4')
    p = parameters
    strength = np.float32(np.clip(p.strength, 0, 1)) if np.isfinite(p.strength) else np.float32(0)
    if mode not in (1, 2) or strength == 0 or previous is None or (mode == 2 and older is None):
        return output, evidence
    if not all(np.isfinite(v) and v > 0 for v in (
            p.chroma_floor, p.mad_scale, p.depth_relative_tolerance, p.normal_oct_tolerance,
            p.roughness_tolerance, p.luma_floor, p.temporal_tolerance)):
        raise ValueError('fixed experiment thresholds must be positive and finite')
    rgb = source[..., :3].astype(np.float32)
    center_y = luma(rgb)
    center_c = chroma(rgb, p.luma_floor)
    values, valid_taps, tap_y = [], [], []
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            if dx == dy == 0:
                continue
            tap = np.roll(source, (-dy, -dx), axis=(0, 1))
            tap_depth = np.roll(depth, (-dy, -dx), axis=(0, 1))
            tap_normal = np.roll(normal, (-dy, -dx), axis=(0, 1))
            valid_taps.append(_active(tap) & _guide(depth, normal, tap_depth, tap_normal, p))
            values.append(chroma(tap[..., :3], p.luma_floor))
            tap_y.append(luma(tap[..., :3]))
    values, valid_taps, tap_y = map(np.stack, (values, valid_taps, tap_y))
    counts = valid_taps.sum(axis=0).astype(np.uint32)
    enough = counts >= 5
    active = _active(source)
    interior = np.ones((height, width), dtype=bool)
    interior[[0, -1], :] = False
    interior[:, [0, -1]] = False
    flags = np.where(enough, 1, 0).astype(np.uint32)
    median = _median(values, valid_taps, counts)
    mad = _median(np.abs(values-median[None]), valid_taps, counts)
    radius = np.maximum(np.float32(p.chroma_floor), mad*np.float32(p.mad_scale))
    minimum = np.min(np.where(valid_taps, tap_y, np.float32(65504)), axis=0)
    maximum = np.max(np.where(valid_taps, tap_y, np.float32(0)), axis=0)
    margin = np.maximum(center_y*np.float32(.1), np.float32(p.luma_floor))
    luma_edge = (center_y < minimum-margin) | (center_y > maximum+margin)
    flags |= np.where(enough & luma_edge, 128, 0).astype(np.uint32)
    clipped = np.clip(center_c, median-radius, median+radius)
    correction = np.max(np.abs(center_c-clipped), axis=-1)
    candidate = interior & active & enough & ~luma_edge & (correction > 0)
    flags |= np.where(candidate, 2, 0).astype(np.uint32)
    yy, xx = np.indices((height, width), dtype=np.float32)
    uv = (np.stack((xx, yy), axis=-1)+np.float32(.5))/np.array((width, height), dtype=np.float32)
    previous_uv, xy, valid = _project(uv, motion, width, height)
    prev_source, prev_depth, prev_normal, prev_motion = _prepare(previous)
    value, z, n = _sample(prev_source, xy), _sample(prev_depth, xy), _sample(prev_normal, xy)
    valid &= _active(value) & _guide(depth+motion[..., 2], normal, z, n, p)
    flags |= np.where(candidate & valid, 4, 0).astype(np.uint32)
    valid &= (np.all(np.abs(chroma(value[..., :3], p.luma_floor)-median) <= radius*np.float32(p.temporal_tolerance), axis=-1) &
              (np.abs(luma(value[..., :3])-center_y) <= np.maximum(center_y*np.float32(.25), np.float32(p.luma_floor))))
    flags |= np.where(candidate & valid, 8, 0).astype(np.uint32)
    if mode == 2:
        previous_motion = _sample(prev_motion, xy)
        _, xy2, valid2 = _project(previous_uv, previous_motion, width, height)
        old_source, old_depth, old_normal, _ = _prepare(older)
        value2 = _sample(old_source, xy2)
        valid &= valid2 & _active(value2) & _guide(z+previous_motion[..., 2], n,
            _sample(old_depth, xy2), _sample(old_normal, xy2), p)
        flags |= np.where(candidate & valid, 16, 0).astype(np.uint32)
        valid &= (np.all(np.abs(chroma(value2[..., :3], p.luma_floor)-median) <= radius*np.float32(p.temporal_tolerance), axis=-1) &
                  (np.abs(luma(value2[..., :3])-center_y) <= np.maximum(center_y*np.float32(.25), np.float32(p.luma_floor))))
        flags |= np.where(candidate & valid, 32, 0).astype(np.uint32)
    admit = candidate & valid
    selected = center_c+strength*(clipped-center_c)
    c = selected*np.maximum(center_y, np.float32(p.luma_floor))[..., None]
    delta = np.stack((c[..., 0]-c[..., 1], c[..., 1], -c[..., 0]-c[..., 1]), axis=-1)
    scale = np.ones((height, width), dtype=np.float32)
    for channel in range(3):
        d = delta[..., channel]
        safe = np.where(d == 0, np.float32(1), d)
        bound = np.where(d < 0, center_y/-safe, np.where(d > 0, (np.float32(65504)-center_y)/safe, np.float32(1)))
        scale = np.minimum(scale, bound)
    rgb = center_y[..., None]+delta*np.clip(scale, 0, 1)[..., None]
    half = rgb.astype('<f2')
    admit &= np.all(np.isfinite(half), axis=-1)
    output[..., :3] = np.where(admit[..., None], half, source[..., :3])
    flags |= np.where(admit, 64, 0).astype(np.uint32)
    evidence[..., 0] = np.where(interior & active, flags, np.where(~active, 256, 0))
    evidence[..., 1] = np.where(interior & active, counts, 0)
    evidence[..., 2] = np.where(interior & active & enough & ~luma_edge, np.max(radius, axis=-1), np.float32(0)).astype('<f4').view('<u4')
    evidence[..., 3] = np.where(candidate, correction, np.float32(0)).astype('<f4').view('<u4')
    return output, evidence
