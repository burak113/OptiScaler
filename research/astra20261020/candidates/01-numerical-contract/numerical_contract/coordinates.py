"""Explicit 2D coordinate units used by the tagged ColourTrack/Anchor sources.

All extents and coordinates are (x, y); NumPy image storage remains (y, x, ...).
``ideal`` stages in float64. ``source`` and ``observed`` stage in float32;
neither claims to reproduce DXC reciprocal/fusion choices on every device.
"""
from __future__ import annotations

import operator
import numpy as np


def arithmetic_dtype(mode: str):
    if mode == "ideal":
        return np.float64
    if mode in ("source", "observed"):
        return np.float32
    raise ValueError("mode must be ideal, source or observed; API bounds are separate")


def extent_xy(extent, name="extent") -> tuple[int, int]:
    if len(extent) != 2:
        raise ValueError(f"{name} must contain (width, height)")
    try:
        result = tuple(operator.index(x) for x in extent)
    except TypeError as exc:
        raise TypeError(f"{name} must contain integer dimensions") from exc
    if any(x <= 0 for x in result):
        raise ValueError(f"{name} dimensions must be positive")
    return result


def _xy(value, dtype):
    value = np.asarray(value, dtype=dtype)
    if value.ndim == 0 or value.shape[-1] != 2:
        raise ValueError("coordinates must have a final (x, y) axis")
    return value


def grid_extent(full_extent, cell_size: int) -> tuple[int, int]:
    """Host allocation rule: floor division, clamped to one (not ceil)."""
    full = extent_xy(full_extent)
    cell = operator.index(cell_size)
    if cell <= 0:
        raise ValueError("cell_size must be positive")
    return tuple(max(1, n // cell) for n in full)


def pixel_grid(extent, *, mode="source"):
    """Integer texel centres represented by their indices, shape (H,W,2)."""
    width, height = extent_xy(extent)
    yy, xx = np.mgrid[:height, :width]
    return np.stack((xx, yy), axis=-1).astype(arithmetic_dtype(mode))


def texel_to_uv(xy, allocation_extent, *, mode="source", method="divide"):
    """Texel-index centre -> normalized allocation UV, ``(xy+0.5)/extent``.

    ``reciprocal_multiply`` represents Anchor Apply's uploaded reciprocal. The
    two expressions can differ for odd extents; they are intentionally named.
    """
    dtype = arithmetic_dtype(mode)
    xy = _xy(xy, dtype)
    extent = np.asarray(extent_xy(allocation_extent), dtype=dtype)
    centre = (xy + dtype(0.5)).astype(dtype)
    if method == "divide":
        return (centre / extent).astype(dtype)
    if method == "reciprocal_multiply":
        inverse = (dtype(1) / extent).astype(dtype)
        return (centre * inverse).astype(dtype)
    raise ValueError("method must be divide or reciprocal_multiply")


def uv_to_texel(uv, allocation_extent, *, mode="source"):
    """Normalized allocation UV -> texel-centre index, ``uv*extent-0.5``."""
    dtype = arithmetic_dtype(mode)
    uv = _xy(uv, dtype)
    extent = np.asarray(extent_xy(allocation_extent), dtype=dtype)
    scaled = (uv * extent).astype(dtype)
    return (scaled - dtype(0.5)).astype(dtype)


def active_uv_to_allocation_uv(uv, active_extent, allocation_extent,
                                *, active_origin=(0, 0), mode="source"):
    """Convert normalized active ROI coordinates to the resource's UV space."""
    dtype = arithmetic_dtype(mode)
    uv = _xy(uv, dtype)
    active = np.asarray(extent_xy(active_extent), dtype=dtype)
    allocation = np.asarray(extent_xy(allocation_extent), dtype=dtype)
    origin = _xy(active_origin, dtype)
    if np.any(origin < 0) or np.any(origin + active > allocation):
        raise ValueError("active region must fit inside the allocation")
    return ((uv * active + origin).astype(dtype) / allocation).astype(dtype)


def full_pixel_to_grid_texel(pixel_xy, full_extent, field_extent,
                              *, mode="source", method="divide"):
    """Actual apply mapping; uses both extents even when full size is odd."""
    uv = texel_to_uv(pixel_xy, full_extent, mode=mode, method=method)
    return uv_to_texel(uv, field_extent, mode=mode)


def motion_uv_to_pixels(motion_uv, original_render_extent, *, mode="source"):
    """Captured UV displacement -> original-render pixels, never crop pixels."""
    dtype = arithmetic_dtype(mode)
    motion = _xy(motion_uv, dtype)
    full = np.asarray(extent_xy(original_render_extent), dtype=dtype)
    return (motion * full).astype(dtype)


def reproject_crop(local_xy, previous_minus_current_pixels, *, current_origin,
                   previous_origin, mode="source"):
    """Previous-frame crop indices, separating crop movement from scene motion.

    The displacement sign is part of the argument's name. Callers must establish
    their capture's sign convention before using it; no sign is inferred here.
    """
    dtype = arithmetic_dtype(mode)
    local = _xy(local_xy, dtype)
    motion = _xy(previous_minus_current_pixels, dtype)
    current = _xy(current_origin, dtype)
    previous = _xy(previous_origin, dtype)
    return (((local + current).astype(dtype) + motion).astype(dtype) - previous).astype(dtype)


def colour_track_previous_uv(cell_xy, motion_pixels, field_extent,
                              *, cell_size=4, mode="source"):
    """Track shader's explicit plus-sign warp in cell coordinates."""
    dtype = arithmetic_dtype(mode)
    cell = operator.index(cell_size)
    if cell <= 0:
        raise ValueError("cell_size must be positive")
    previous = (_xy(cell_xy, dtype) + _xy(motion_pixels, dtype) / dtype(cell)).astype(dtype)
    return texel_to_uv(previous, field_extent, mode=mode)


def cell_tap_uv(cell_xy, cell_size, allocation_extent, *, mode="source"):
    """Four Stats taps, (...,4,2); Colour=4/offsets1,3, Anchor=8/2,6.

    The Anchor pattern is a sparse 16-texel estimate of an 8x8 cell. This
    operation deliberately does not replace it with a 64-texel mean.
    """
    dtype = arithmetic_dtype(mode)
    if cell_size not in (4, 8):
        raise ValueError("audited Stats patterns have cell_size 4 or 8")
    cell = _xy(cell_xy, dtype)
    low, high = cell_size / 4, 3 * cell_size / 4
    offsets = np.asarray(((low, low), (high, low), (low, high), (high, high)), dtype=dtype)
    edge_pixels = (cell[..., None, :] * dtype(cell_size) + offsets).astype(dtype)
    extent = np.asarray(extent_xy(allocation_extent), dtype=dtype)
    return (edge_pixels / extent).astype(dtype)


def anchor_view_position(pixel_xy, depth, full_extent, projection,
                          projection_w_scale, *, mode="source"):
    """Source ViewPosition: projection=(P00,P11,P02,P12), w=P32*z.

    Inputs with zero projection divisors are rejected; production guards them
    outside this helper. Depth remains signed in this mathematical operation.
    """
    dtype = arithmetic_dtype(mode)
    pixel = _xy(pixel_xy, dtype)
    proj = np.asarray(projection, dtype=dtype)
    if proj.shape != (4,) or not np.all(np.isfinite(proj)) or np.any(proj[:2] == 0):
        raise ValueError("projection must have four finite entries with nonzero P00/P11")
    scale = dtype(projection_w_scale)
    if not np.isfinite(scale) or scale == 0:
        raise ValueError("projection_w_scale must be finite and nonzero")
    z = np.asarray(depth, dtype=dtype)
    uv = texel_to_uv(pixel, full_extent, mode=mode)
    ndc = np.stack((uv[..., 0] * dtype(2) - dtype(1),
                    dtype(1) - uv[..., 1] * dtype(2)), axis=-1).astype(dtype)
    w = (scale * z).astype(dtype)
    xy = ((ndc * w[..., None] - proj[2:] * z[..., None]).astype(dtype) / proj[:2]).astype(dtype)
    xy, zz = np.broadcast_arrays(xy, np.broadcast_to(z, xy.shape[:-1])[..., None])
    return np.concatenate((xy, zz[..., :1]), axis=-1)


def project_to_edge_pixels(clip, full_extent, *, mode="source"):
    """Source ProjectToPixels returns edge-space pixels (not texel indices)."""
    dtype = arithmetic_dtype(mode)
    clip = np.asarray(clip, dtype=dtype)
    if clip.ndim == 0 or clip.shape[-1] != 4:
        raise ValueError("clip must have a final four-component axis")
    if np.any(~np.isfinite(clip)) or np.any(clip[..., 3] == 0):
        raise ValueError("finite clip coordinates and nonzero clip.w are required")
    full = np.asarray(extent_xy(full_extent), dtype=dtype)
    ndc = (clip[..., :2] / clip[..., 3:4]).astype(dtype)
    uv = np.stack(((ndc[..., 0] + dtype(1)) * dtype(0.5),
                    (dtype(1) - ndc[..., 1]) * dtype(0.5)), axis=-1).astype(dtype)
    return (uv * full).astype(dtype)


def project_to_texel_indices(clip, full_extent, *, mode="source"):
    """Named centre-coordinate counterpart; not a silent source modification."""
    dtype = arithmetic_dtype(mode)
    return (project_to_edge_pixels(clip, full_extent, mode=mode) - dtype(0.5)).astype(dtype)
