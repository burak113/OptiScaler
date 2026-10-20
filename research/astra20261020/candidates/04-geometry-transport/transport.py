"""Explicit geometric transport, independent of Windows and any denoiser.

Coordinates are pixel-edge coordinates: texel (i, j) has centre (i+.5, j+.5).
All mathematical matrices multiply COLUMN vectors. NumPy C/F memory layout is
irrelevant; a transposed mathematical matrix is a different transform.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np


def _extent(value, name="extent"):
    out = tuple(int(x) for x in value)
    if len(out) != 2 or min(out) < 1 or any(a != b for a, b in zip(out, value)):
        raise ValueError(f"{name} must be two positive integer dimensions, width first")
    return out


@dataclass(frozen=True)
class RasterDomain:
    """Full active render, physical allocation, and observed crop are distinct.

    allocation_extent refers to the original render texture, not NPZ ROI storage.
    Crop origins and extents use original full-render pixel-edge coordinates.
    """
    active_extent: tuple[int, int]
    allocation_extent: tuple[int, int] | None = None
    crop_origin: tuple[int, int] = (0, 0)
    crop_extent: tuple[int, int] | None = None

    def __post_init__(self):
        active = _extent(self.active_extent, "active_extent")
        allocated = _extent(self.allocation_extent or active, "allocation_extent")
        crop = _extent(self.crop_extent or active, "crop_extent")
        origin = tuple(int(x) for x in self.crop_origin)
        if len(origin) != 2 or any(a != b for a, b in zip(origin, self.crop_origin)):
            raise ValueError("crop_origin must contain two integers")
        if any(a > b for a, b in zip(active, allocated)):
            raise ValueError("active extent exceeds allocation")
        if min(origin) < 0 or any(o + c > a for o, c, a in zip(origin, crop, active)):
            raise ValueError("observed crop must be inside active render")
        object.__setattr__(self, "active_extent", active)
        object.__setattr__(self, "allocation_extent", allocated)
        object.__setattr__(self, "crop_extent", crop)
        object.__setattr__(self, "crop_origin", origin)

    def local_to_render(self, local_xy):
        return np.asarray(local_xy, dtype=np.float64) + self.crop_origin

    def render_to_local(self, render_xy):
        return np.asarray(render_xy, dtype=np.float64) - self.crop_origin

    def allocation_uv(self, local_xy):
        """For an SRV of the original texture; never use as active-render UV."""
        return self.local_to_render(local_xy) / self.allocation_extent

    def observed_point(self, local_xy):
        p = np.asarray(local_xy, dtype=np.float64)
        return np.all(np.isfinite(p) & (p >= 0) & (p < self.crop_extent), axis=-1)


@dataclass(frozen=True)
class Camera:
    view_col: np.ndarray
    projection_col: np.ndarray
    active_extent: tuple[int, int]
    handedness: str = "LH"
    raster_shift_px: tuple[float, float] = (0.0, 0.0)

    def __post_init__(self):
        if self.handedness not in ("LH", "RH"):
            raise ValueError("handedness must be LH (+Z forward) or RH (-Z forward)")
        object.__setattr__(self, "active_extent", _extent(self.active_extent))
        for name in ("view_col", "projection_col"):
            matrix = np.array(getattr(self, name), dtype=np.float64, copy=True)
            if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
                raise ValueError(f"{name} must be a finite 4x4 column-vector matrix")
            matrix.setflags(write=False)
            object.__setattr__(self, name, matrix)
        shift = tuple(float(x) for x in self.raster_shift_px)
        if len(shift) != 2 or not np.all(np.isfinite(shift)):
            raise ValueError("raster_shift_px must contain two finite values")
        object.__setattr__(self, "raster_shift_px", shift)
        if abs(np.linalg.det(self.view_col)) < 1e-12:
            raise ValueError("view matrix is singular")


@dataclass(frozen=True)
class ProjectionResult:
    pixel_xy: np.ndarray
    view_depth: np.ndarray
    valid: np.ndarray


@dataclass(frozen=True)
class SampleResult:
    values: np.ndarray
    valid: np.ndarray
    coverage: np.ndarray


def pixel_centres(extent):
    w, h = _extent(extent)
    y, x = np.mgrid[:h, :w]
    return np.stack((x + 0.5, y + 0.5), axis=-1)


def perspective_col(extent, fov_y_degrees=60.0, near=0.1, far=1000.0,
                    handedness="LH", pixel_aspect=1.0):
    """D3D [0,1] device-depth perspective; signed linear view Z is separate."""
    w, h = _extent(extent)
    if handedness not in ("LH", "RH") or not (0 < near < far):
        raise ValueError("invalid handedness/near/far")
    if not (0 < fov_y_degrees < 180 and np.isfinite(pixel_aspect) and pixel_aspect > 0):
        raise ValueError("invalid FOV or physical pixel aspect")
    sign = 1.0 if handedness == "LH" else -1.0
    sy = 1.0 / np.tan(np.deg2rad(fov_y_degrees) * 0.5)
    p = np.zeros((4, 4), dtype=np.float64)
    p[0, 0] = sy / (w * pixel_aspect / h)
    p[1, 1] = sy
    p[2, 2] = sign * far / (far - near)
    p[2, 3] = -near * far / (far - near)
    p[3, 2] = sign
    return p


def view_from_pose(position=(0.0, 0.0, 0.0), yaw_degrees=0.0, pitch_degrees=0.0):
    """Inverse camera-to-world rigid pose; angles rotate local axes, not storage."""
    y, p = np.deg2rad([yaw_degrees, pitch_degrees])
    ry = np.array([[np.cos(y), 0, np.sin(y)], [0, 1, 0], [-np.sin(y), 0, np.cos(y)]])
    rx = np.array([[1, 0, 0], [0, np.cos(p), -np.sin(p)], [0, np.sin(p), np.cos(p)]])
    rotation = ry @ rx
    view = np.eye(4)
    view[:3, :3] = rotation.T
    view[:3, 3] = -rotation.T @ np.asarray(position, dtype=np.float64)
    return view


def _homogeneous(points):
    p = np.asarray(points, dtype=np.float64)
    if p.shape[-1] != 3:
        raise ValueError("expected (...,3) points")
    return np.concatenate((p, np.ones(p.shape[:-1] + (1,))), axis=-1)


def project_world(world_xyz, camera):
    view = np.einsum("ij,...j->...i", camera.view_col, _homogeneous(world_xyz))
    clip = np.einsum("ij,...j->...i", camera.projection_col, view)
    front = np.all(np.isfinite(clip), axis=-1) & (clip[..., 3] > 1e-12)
    safe_w = np.where(front, clip[..., 3], 1.0)
    ndc = clip[..., :2] / safe_w[..., None]
    pixel = (ndc * (0.5, -0.5) + 0.5) * camera.active_extent + camera.raster_shift_px
    # This validity is geometric only. Active viewport/ROI support is separate.
    return ProjectionResult(pixel, view[..., 2], front)


def unproject_pixels(pixel_xy, signed_view_depth, camera):
    """Explicit perspective inverse at a known *signed* linear view depth.

    The projection may have P02/P12 lens offsets. Orthographic/sheared clip-W
    matrices are rejected instead of silently being treated as perspective.
    """
    matrix = camera.projection_col
    if (not np.allclose(matrix[3, [0, 1, 3]], 0) or abs(matrix[3, 2]) < 1e-12
            or not np.allclose(matrix[[0, 1], [1, 0]], 0)
            or abs(matrix[0, 0] * matrix[1, 1]) < 1e-12):
        raise ValueError("this inverse requires non-sheared perspective clip W = P32 * Z")
    pixel = np.asarray(pixel_xy, dtype=np.float64)
    depth = np.broadcast_to(np.asarray(signed_view_depth, dtype=np.float64), pixel.shape[:-1])
    input_valid = np.all(np.isfinite(pixel), axis=-1) & np.isfinite(depth)
    safe_pixel = np.where(input_valid[..., None], pixel, 0.0)
    safe_depth = np.where(input_valid, depth, 0.0)
    ndc = ((safe_pixel - camera.raster_shift_px) / camera.active_extent - 0.5) * (2.0, -2.0)
    w = matrix[3, 2] * safe_depth
    x = (ndc[..., 0] * w - matrix[0, 2] * safe_depth - matrix[0, 3]) / matrix[0, 0]
    y = (ndc[..., 1] * w - matrix[1, 2] * safe_depth - matrix[1, 3]) / matrix[1, 1]
    view = np.stack((x, y, safe_depth), axis=-1)
    world_h = np.einsum("ij,...j->...i", np.linalg.inv(camera.view_col), _homogeneous(view))
    world = world_h[..., :3] / world_h[..., 3, None]
    valid = input_valid & np.all(np.isfinite(world), axis=-1) & (w > 1e-12)
    return np.where(valid[..., None], world, 0.0), valid


def surface_motion(current_world, previous_world, current_camera, previous_camera):
    """Current -> previous normalized ACTIVE render UV, including raster shifts."""
    cur = project_world(current_world, current_camera)
    old = project_world(previous_world, previous_camera)
    motion = old.pixel_xy / previous_camera.active_extent - cur.pixel_xy / current_camera.active_extent
    return motion, cur.valid & old.valid


def motion_to_previous(local_xy, motion_uv, current_domain, previous_domain,
                       current_raster_shift_px=(0.0, 0.0), previous_raster_shift_px=(0.0, 0.0),
                       motion_includes_raster_shift=True):
    """Map explicit current crop coordinates to previous crop coordinates.

    UV displacement is prev-active-UV minus current-active-UV. For fixed render
    dimensions this is exactly local + current_origin + MV*render - old_origin.
    Under DRS, endpoint normalization is used; no source-specific DRS convention
    is inferred for fixtures whose original camera witnesses are absent.
    """
    p = current_domain.local_to_render(local_xy)
    if not motion_includes_raster_shift:
        p = p - current_raster_shift_px
    previous_global = (p / current_domain.active_extent + np.asarray(motion_uv)) * previous_domain.active_extent
    if not motion_includes_raster_shift:
        previous_global = previous_global + previous_raster_shift_px
    return previous_domain.render_to_local(previous_global)


def bilinear_sample(image, local_edge_xy, known_mask=None):
    """Ideal arithmetic four-tap sample with strict nonzero-tap support.

    No out-of-domain point is clamped to a valid border texel. Invalid outputs
    have value zero and valid=False; coverage reports observed weight and is
    diagnostic, not authority to relabel partial observations as full history.
    This is not a bit-exact D3D sampler model (fraction quantization differs).
    """
    src = np.asarray(image)
    if src.ndim not in (2, 3):
        raise ValueError("image must have shape HxW or HxWxC")
    h, w = src.shape[:2]
    known = np.ones((h, w), dtype=bool) if known_mask is None else np.asarray(known_mask)
    if known.dtype != np.bool_:
        raise ValueError("known_mask must be boolean; numeric/NaN masks are not support")
    if known.shape != (h, w):
        raise ValueError("known_mask shape mismatch")
    p = np.asarray(local_edge_xy, dtype=np.float64)
    finite = np.all(np.isfinite(p), axis=-1)
    # Far-away finite coordinates must not overflow the float->index conversion.
    reachable = finite & np.all((p >= -1) & (p <= (w+1, h+1)), axis=-1)
    index = np.where(reachable[..., None], p - 0.5, 0.0)
    low = np.floor(index).astype(np.int64)
    frac = index - low
    output = np.zeros(p.shape[:-1] + src.shape[2:], dtype=np.float64)
    coverage = np.zeros(p.shape[:-1], dtype=np.float64)
    complete = reachable.copy()
    for dy in (0, 1):
        for dx in (0, 1):
            ix, iy = low[..., 0] + dx, low[..., 1] + dy
            weight = (frac[..., 0] if dx else 1-frac[..., 0]) * (frac[..., 1] if dy else 1-frac[..., 1])
            inside = reachable & (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
            # Clipping is only for memory-safe indexing; raw `inside` governs all weights.
            sx, sy = np.clip(ix, 0, w-1), np.clip(iy, 0, h-1)
            sample = src[sy, sx]
            sample_finite = np.all(np.isfinite(sample), axis=-1) if src.ndim == 3 else np.isfinite(sample)
            supported = inside & known[sy, sx] & sample_finite
            complete &= supported | (weight == 0)
            use = np.where(supported, weight, 0.0)
            coverage += use
            safe_sample = np.where(supported[..., None], sample, 0) if src.ndim == 3 else np.where(supported, sample, 0)
            output += safe_sample * (use[..., None] if src.ndim == 3 else use)
    output = np.where(complete[..., None], output, 0.0) if src.ndim == 3 else np.where(complete, output, 0.0)
    return SampleResult(output, complete, coverage)


def normalized_normals(normals):
    n = np.asarray(normals, dtype=np.float64)
    norm = np.linalg.norm(n, axis=-1)
    valid = np.all(np.isfinite(n), axis=-1) & np.isfinite(norm) & (norm > 1e-12)
    normalized = np.where(valid[..., None], n / np.where(valid, norm, 1.0)[..., None], 0.0)
    return normalized, valid


def correspondence_support(expected_depth_abs, sampled_depth_abs, current_normal,
                           previous_normal, known, depth_relative=0.02, normal_cosine=0.95):
    """Geometry-only support; caller must supply normals in the SAME space.

    Colour, corrected radiance, roughness and hit distance are deliberately not
    accepted as substitutes for a missing depth/normal correspondence guide.
    Zero/nonfinite depth and invalid normals have no correspondence support.
    """
    if not np.isfinite(depth_relative) or depth_relative < 0 or not np.isfinite(normal_cosine) or not -1 <= normal_cosine <= 1:
        raise ValueError("invalid geometric tolerance")
    known = np.asarray(known)
    if known.dtype != np.bool_:
        raise ValueError("known must be boolean; numeric/NaN masks are not support")
    expected, actual = np.broadcast_arrays(expected_depth_abs, sampled_depth_abs)
    cn, cv = normalized_normals(current_normal)
    pn, pv = normalized_normals(previous_normal)
    depth_valid = np.isfinite(expected) & np.isfinite(actual) & (expected > 1e-12) & (actual > 1e-12)
    depth_ok = np.abs(expected-actual) <= depth_relative * np.maximum(expected, 1e-3)
    normal_ok = np.sum(cn*pn, axis=-1) >= normal_cosine
    return known & depth_valid & depth_ok & cv & pv & normal_ok


def visibility_order(expected_depth_abs, observed_depth_abs, known, relative_tolerance=0.02):
    """Return 0 unknown, 1 same-depth, 2 occluded, 3 in-front-of-old-depth.

    Class 3 alone does not prove disocclusion; scene/object identity is needed.
    """
    e, o = np.broadcast_arrays(expected_depth_abs, observed_depth_abs)
    known = np.asarray(known)
    if known.dtype != np.bool_ or not np.isfinite(relative_tolerance) or relative_tolerance < 0:
        raise ValueError("known must be boolean and tolerance finite/nonnegative")
    valid = known & np.isfinite(e) & np.isfinite(o) & (e > 0) & (o > 0)
    tolerance = relative_tolerance*np.maximum(e, 1e-3)
    out = np.zeros(e.shape, dtype=np.uint8)
    out[valid & (np.abs(e-o) <= tolerance)] = 1
    out[valid & (o < e-tolerance)] = 2
    out[valid & (o > e+tolerance)] = 3
    return out


def native_shader_view_position(pixel_argument, stored_depth, projection_col, extent):
    """Frozen StatsRecall arithmetic witness, INCLUDING its extra +.5 phase.

    Input is the shader argument centre=8*cell+4, not our API's pixel centre.
    Native/combined shaders use abs(current depth) with sign from P32 here.
    """
    matrix = np.asarray(projection_col)
    pixel = np.asarray(pixel_argument, dtype=np.float64)
    z = np.abs(np.asarray(stored_depth, dtype=np.float64)) * (-1 if matrix[3, 2] < 0 else 1)
    ndc = ((pixel + 0.5) / extent - 0.5)*(2.0, -2.0)
    w = matrix[3, 2]*z
    x = (ndc[..., 0]*w-matrix[0, 2]*z)/matrix[0, 0]
    y = (ndc[..., 1]*w-matrix[1, 2]*z)/matrix[1, 1]
    return np.stack(np.broadcast_arrays(x, y, z), axis=-1)


def native_key_depth(signed_view_depth):
    """Native Gain stores abs(cell.depth); this is not combined signed capture."""
    return np.abs(np.asarray(signed_view_depth))


def native_recall_depth_match(stored_abs, clip_w, key_p32, relative_tolerance=0.02):
    if not np.isfinite(relative_tolerance) or relative_tolerance < 0:
        raise ValueError("depth tolerance must be finite/nonnegative")
    stored, w, p32 = np.broadcast_arrays(stored_abs, clip_w, key_p32)
    finite = np.isfinite(stored) & np.isfinite(w) & np.isfinite(p32)
    valid = finite & (w > 1e-6) & (np.abs(p32) > 1e-6)
    expected = np.abs(w/np.where(valid, p32, 1.0))
    return valid & (np.abs(stored-expected) <= relative_tolerance*np.maximum(expected, 1e-3))


def construct_virtual_point(surface_world, virtual_direction_world, hit_distance, *, observation_role):
    """Use an explicitly meaningful reflection-distance observation.

    `virtual_direction_world` is supplied by a physical reflection model; it is
    NOT automatically the normal or surface MV. For a planar mirror it is the
    camera-to-surface ray continued behind the mirror. Diffuse alpha or an
    arbitrary surface property is unsupported even when it contains numbers.
    """
    direction, valid = normalized_normals(virtual_direction_world)
    distance = np.asarray(hit_distance, dtype=np.float64)
    valid = valid & np.isfinite(distance) & (distance > 0) & (observation_role == "reflection_distance")
    point = np.asarray(surface_world, dtype=np.float64) + direction*distance[..., None]
    valid &= np.all(np.isfinite(point), axis=-1)
    return np.where(valid[..., None], point, 0.0), valid


def mirror_virtual_point(real_point, plane_normal, plane_point):
    normal, valid = normalized_normals(plane_normal)
    if not np.all(valid):
        raise ValueError("mirror normal must be finite and nonzero")
    p = np.asarray(real_point, dtype=np.float64)
    delta = p-np.asarray(plane_point, dtype=np.float64)
    return p-2*np.sum(delta*normal, axis=-1)[..., None]*normal


@dataclass(frozen=True)
class Plane:
    """World plane n.dot(p)+offset=0 with optional axis-aligned finite bounds."""
    normal: tuple[float, float, float]
    offset: float
    surface_id: int
    lower: tuple[float, float, float] = (-np.inf, -np.inf, -np.inf)
    upper: tuple[float, float, float] = (np.inf, np.inf, np.inf)


def render_planes(camera, planes, pixel_xy=None):
    """Analytic ray-plane intersections with exact nearest-surface visibility.

    No rasterizer/black-box warp is used. Bounds provide moving thin strips;
    normals and surface IDs are immutable analytic truth, not colour labels.
    """
    pixels = pixel_centres(camera.active_extent) if pixel_xy is None else np.asarray(pixel_xy)
    sign = 1.0 if camera.handedness == "LH" else -1.0
    near, ray_valid = unproject_pixels(pixels, np.full(pixels.shape[:-1], sign), camera)
    camera_origin = np.linalg.inv(camera.view_col)[:3, 3]
    direction = near-camera_origin
    nearest = np.full(pixels.shape[:-1], np.inf)
    points = np.zeros(pixels.shape[:-1]+(3,))
    normals = np.zeros_like(points)
    ids = np.full(pixels.shape[:-1], -1, dtype=np.int32)
    for plane in planes:
        n = np.asarray(plane.normal, dtype=np.float64)
        if not np.all(np.isfinite(n)) or np.linalg.norm(n) < 1e-12:
            raise ValueError("plane normal is invalid")
        denominator = np.sum(direction*n, axis=-1)
        valid = ray_valid & (np.abs(denominator) > 1e-12)
        distance = -(np.dot(camera_origin, n)+plane.offset)/np.where(valid, denominator, 1.0)
        p = camera_origin+distance[..., None]*direction
        valid &= (distance > 0) & np.all((p >= plane.lower) & (p <= plane.upper), axis=-1)
        replace = valid & (distance < nearest)
        nearest = np.where(replace, distance, nearest)
        points = np.where(replace[..., None], p, points)
        normals = np.where(replace[..., None], n/np.linalg.norm(n), normals)
        ids = np.where(replace, plane.surface_id, ids)
    signed_depth = project_world(points, camera).view_depth
    valid = ids >= 0
    return {"world": points, "depth": np.where(valid, signed_depth, 0.0), "normal": normals,
            "surface_id": ids, "valid": valid, "pixel_xy": pixels}
