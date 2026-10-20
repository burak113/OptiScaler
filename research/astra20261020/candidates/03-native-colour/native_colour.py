"""Default-OFF, CPU-only native per-lobe colour experiment.

The domain is one physical linear-RGB native lighting lobe BEFORE game remod.
The current-frame physical RGB mean is formed before a log/opponent transform.
No temporal state, coarse target grid, upsampler or raw-pixel dark mask exists.
Geometry, roughness and the *raw RR* chromaticity define centre-anchored support.
Those guides are observations, not ground truth; noisy guide fragmentation and
coloured illumination boundaries can reject this candidate in quality testing.

Protection is stronger than numerical RGB equality: all ORIGINAL selected/raw
RGBA words must match before a pixel is eligible, and explicit authority must be
true. Alpha is never interpreted or converted. Output starts as a byte-preserving
selected copy, so protected pixels, inactive extents and all alpha words survive.

Only NumPy and the Python standard library are required. This arithmetic model
does not establish GPU sampler, DXC, native routing or final-game image parity.
"""
from dataclasses import asdict, dataclass
import math

import numpy as np


LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
CHROMA_EPS = np.float32(1.0e-4)  # dimensionless, AFTER luma normalization


def luminance(rgb):
    return np.sum(np.asarray(rgb, np.float32)[..., :3] * LUMA, axis=-1,
                  dtype=np.float32)


def normalized_colour(rgb):
    """Return (RGB/Y,Y); zero luma maps to zero, without an absolute dark gate."""
    rgb = np.asarray(rgb, np.float32)
    y = luminance(rgb)
    chroma = np.zeros_like(rgb)
    np.divide(rgb, y[..., None], out=chroma, where=(y > 0)[..., None])
    return chroma, y


def opponent_encode(rgb):
    """u=ln((R/Y+e)/(G/Y+e)), v=ln((B/Y+e)/(G/Y+e)).

    Valid domain is finite, nonnegative RGB with positive Y. The zero vector is
    encoded as (0,0) only as a sentinel; supported=False prevents its use. e is
    dimensionless, so positive uniform RGB scaling leaves the transform invariant.
    """
    chroma, _ = normalized_colour(rgb)
    safe = np.maximum(chroma, 0) + CHROMA_EPS
    return np.log(safe[..., (0, 2)] / safe[..., 1, None]).astype(np.float32)


def opponent_inverse(opponent, y=1.0):
    """Exact analytic inverse on the valid image of opponent_encode.

    Let r=(exp(u),1,exp(v)); c=(1+e)*r/dot(LUMA,r)-e, RGB=Y*c.
    A final nonnegative clamp absorbs float32 roundoff at a zero channel. This
    function is a transform-closure diagnostic; the candidate transports a bounded
    *gain* on original RGB so its channel zeros and pointwise luma detail remain.
    """
    uv = np.asarray(opponent, np.float32)
    ratios = np.stack([np.exp(uv[..., 0]), np.ones(uv.shape[:-1], np.float32),
                       np.exp(uv[..., 1])], axis=-1)
    chroma = ratios * ((1 + CHROMA_EPS) / luminance(ratios))[..., None] - CHROMA_EPS
    return np.maximum(chroma, 0) * np.asarray(y, np.float32)[..., None]


def rgba_words(rgba):
    """Preserve float16/float32 bit patterns, including signed zero and NaNs."""
    a = np.ascontiguousarray(rgba)
    if a.dtype == np.float16:
        return a.view(np.uint16)
    if a.dtype == np.float32:
        return a.view(np.uint32)
    raise TypeError("native RGBA must be float16 or float32, without implicit conversion")


def exact_selected_mask(raw_rr_rgba, selected_rgba):
    """Compare original words before any candidate arithmetic or half rounding."""
    if raw_rr_rgba.shape != selected_rgba.shape or raw_rr_rgba.dtype != selected_rgba.dtype:
        raise ValueError("raw and selected RGBA must have identical shapes and dtypes")
    return np.all(rgba_words(raw_rr_rgba) == rgba_words(selected_rgba), axis=-1)


def half_rtz(rgb):
    """Explicit model of finite float32 -> FP16 round toward zero.

    The proposed shader performs this conversion explicitly when repacking RGB.
    It does not rely on an assumed typed-UAV store conversion. Alpha bypasses it.
    """
    rgb = np.asarray(rgb, np.float32)
    h = rgb.astype(np.float16)
    overshot = np.abs(h.astype(np.float32)) > np.abs(rgb)
    return np.where(overshot, np.nextafter(h, np.float16(0)), h).astype(np.float16)


@dataclass(frozen=True)
class Config:
    enabled: bool = False
    representation: str = "log"
    strength: float = 1.0
    radius: int = 3
    spatial_sigma: float = 2.0
    depth_tolerance: float = 0.02
    normal_cosine: float = 0.9
    roughness_tolerance: float = 0.15
    guide_chroma_radius: float = 0.35
    max_log_delta: float = math.log(1.25)
    support_prior: float = 4.0

    def __post_init__(self):
        if self.representation not in ("log", "linear"):
            raise ValueError("representation must be 'log' or 'linear'")
        if not isinstance(self.enabled, (bool, np.bool_)):
            raise TypeError("enabled must be an explicit bool")
        if not isinstance(self.radius, int) or not 0 <= self.radius <= 8:
            raise ValueError("radius must be an integer in [0,8]")
        finite = [self.strength, self.spatial_sigma, self.depth_tolerance,
                  self.normal_cosine, self.roughness_tolerance,
                  self.guide_chroma_radius, self.max_log_delta, self.support_prior]
        if not all(math.isfinite(v) for v in finite):
            raise ValueError("configuration constants must be finite")
        if not 0 <= self.strength <= 1:
            raise ValueError("strength must be in [0,1]")
        if min(self.spatial_sigma, self.depth_tolerance,
               self.roughness_tolerance, self.guide_chroma_radius) <= 0:
            raise ValueError("support scales must be positive")
        if not -1 <= self.normal_cosine < 1 or not 0 <= self.max_log_delta <= 2:
            raise ValueError("invalid normal threshold or log-delta limit")
        if self.support_prior < 0:
            raise ValueError("support_prior must be nonnegative")


def _compact(distance):
    """(1-d^2)^2 on |d|<1, zero outside; value/slope vanish at support edge."""
    return np.maximum(1.0 - np.asarray(distance, np.float32) ** 2, 0.0) ** 2


def _overlap(height, width, dy, dx):
    # No edge-clamping duplication: missing taps reduce sample support.
    dst = (slice(max(0, -dy), min(height, height - dy)),
           slice(max(0, -dx), min(width, width - dx)))
    src = (slice(max(0, dy), min(height, height + dy)),
           slice(max(0, dx), min(width, width + dx)))
    return dst, src


def _support_means(source, rr, depth, normal, roughness, valid, cfg):
    height, width = depth.shape
    source_sum, rr_sum = np.zeros_like(source), np.zeros_like(rr)
    sum_w, sum_w2 = np.zeros_like(depth), np.zeros_like(depth)
    guide = opponent_encode(rr)
    for dy in range(-cfg.radius, cfg.radius + 1):
        for dx in range(-cfg.radius, cfg.radius + 1):
            if abs(dy) >= height or abs(dx) >= width:
                continue
            dst, src = _overlap(height, width, dy, dx)
            spatial = np.float32(math.exp(-0.5 * (dx * dx + dy * dy) / cfg.spatial_sigma ** 2))
            z, tz = depth[dst], depth[src]
            denom = np.maximum(cfg.depth_tolerance * np.abs(z), np.float32(1e-3))
            wz = _compact((z - tz) / denom)
            dot = np.clip(np.sum(normal[dst] * normal[src], axis=-1), -1, 1)
            wn = np.clip((dot - cfg.normal_cosine) / (1 - cfg.normal_cosine), 0, 1) ** 2
            wr = _compact((roughness[dst] - roughness[src]) / cfg.roughness_tolerance)
            dc2 = np.sum((guide[dst] - guide[src]) ** 2, axis=-1)
            wc = np.maximum(1 - dc2 / cfg.guide_chroma_radius ** 2, 0) ** 2
            good = valid[dst] & valid[src] & (np.signbit(z) == np.signbit(tz))
            w = np.where(good, spatial * wz * wn * wr * wc, 0).astype(np.float32)
            source_sum[dst] += w[..., None] * source[src]
            rr_sum[dst] += w[..., None] * rr[src]
            sum_w[dst] += w
            sum_w2[dst] += w * w
    source_mean, rr_mean = np.zeros_like(source_sum), np.zeros_like(rr_sum)
    np.divide(source_sum, sum_w[..., None], out=source_mean, where=(sum_w > 0)[..., None])
    np.divide(rr_sum, sum_w[..., None], out=rr_mean, where=(sum_w > 0)[..., None])
    n_eff = np.zeros_like(sum_w)
    np.divide(sum_w * sum_w, sum_w2, out=n_eff, where=sum_w2 > 0)
    return source_mean, rr_mean, n_eff, sum_w


class NativeColourModel:
    """One independent lobe. Current-frame-only by design; reset() has no state.

    Arrays may have allocation dimensions larger than active_extent=(W,H).
    render_extent/crop_origin/frame_id annotate provenance but do not enter this
    spatial estimator. motion_px, when supplied, is deliberately UNUSED. No crop
    translation can manufacture motion/history and no sequence is replayed here.
    """

    def __init__(self, config=None):
        self.config = config if config is not None else Config()

    def reset(self):
        """No retained history exists; included to make caller intent explicit."""
        return None

    def frame(self, input_rgba, raw_rr_rgba, selected_rgba, depth, normals_xyz,
              motion_px=None, roughness=None, authority=None, *, render_extent=None,
              crop_origin=(0, 0), active_extent=None, frame_id=None, reset=False,
              enabled=None):
        cfg = self.config
        source_rgba, raw, selected = map(np.asarray, (input_rgba, raw_rr_rgba, selected_rgba))
        if selected.ndim != 3 or selected.shape[-1] != 4:
            raise ValueError("RGBA arrays must have shape (allocation_height,allocation_width,4)")
        if any(a.shape != selected.shape or a.dtype != selected.dtype for a in (source_rgba, raw)):
            raise ValueError("source, raw and selected must share original RGBA shape and dtype")
        rgba_words(selected)  # validate supported original word format
        height, width = selected.shape[:2]
        if min(height, width) < 1:
            raise ValueError("empty extents are not supported")
        depth, normals_xyz = np.asarray(depth, np.float32), np.asarray(normals_xyz, np.float32)
        if depth.shape != (height, width) or normals_xyz.shape != (height, width, 3):
            raise ValueError("depth and decoded XYZ normals must match allocation extent")
        if authority is None or np.asarray(authority).dtype != np.bool_:
            raise TypeError("authority must be an explicit boolean texture; native alpha is not authority")
        authority = np.asarray(authority)
        if authority.shape != depth.shape:
            raise ValueError("authority must match allocation extent")
        if roughness is None:
            rough = np.zeros_like(depth)
        else:
            rough = np.asarray(roughness, np.float32)
            if rough.shape != depth.shape:
                raise ValueError("roughness must match allocation extent")
        aw, ah = (width, height) if active_extent is None else tuple(active_extent)
        if not isinstance(aw, (int, np.integer)) or not isinstance(ah, (int, np.integer)):
            raise ValueError("active extent must contain integer width,height")
        if not 0 < aw <= width or not 0 < ah <= height:
            raise ValueError("active extent must fit within allocation extent")
        if enabled is not None and not isinstance(enabled, (bool, np.bool_)):
            raise TypeError("enabled override must be bool")
        active = np.zeros((height, width), bool)
        active[:ah, :aw] = True
        same_words = exact_selected_mask(raw, selected)
        eligible = same_words & authority & active  # BEFORE every candidate operation
        output = selected.copy()
        diag = {
            "raw_equal": same_words,
            "eligible": eligible,
            "protected": active & ~same_words,
            "active": active,
            "history_used": np.zeros_like(active),
            "temporal_mode": "none_current_frame_only",
            "history_reset_reason": "stateless",
            "frame_id": frame_id,
            "crop_origin": tuple(crop_origin),
            "render_extent": None if render_extent is None else tuple(render_extent),
            "active_extent": (int(aw), int(ah)),
            "allocation_extent": (width, height),
            "motion_consumed": False,
            "reset_requested": bool(reset),
            "roughness_used": roughness is not None,
            "config": asdict(cfg),
        }
        for name in ("confidence", "effective_samples", "weight_sum"):
            diag[name] = np.zeros_like(depth)
        for name in ("source_mean", "colour_mean", "correction", "linear_delta"):
            diag[name] = np.zeros(selected.shape[:2] + (3,), np.float32)
        diag["log_delta"] = np.zeros(selected.shape[:2] + (2,), np.float32)
        diag["supported"] = np.zeros_like(active)
        diag["overflow_rejected"] = np.zeros_like(active)
        on = cfg.enabled if enabled is None else enabled
        if not on or cfg.strength == 0 or cfg.max_log_delta == 0:
            diag["changed"] = np.zeros_like(active)
            return output, diag

        # Alpha is intentionally never part of a float conversion.
        src_rgb = source_rgba[:ah, :aw, :3].astype(np.float32)
        rr_rgb = raw[:ah, :aw, :3].astype(np.float32)
        z, n, r = depth[:ah, :aw], normals_xyz[:ah, :aw], rough[:ah, :aw]
        src_valid = np.all(np.isfinite(src_rgb) & (src_rgb >= 0), axis=-1)
        rr_valid = np.all(np.isfinite(rr_rgb) & (rr_rgb >= 0), axis=-1)
        n_length = np.linalg.norm(n, axis=-1)
        geom_valid = np.isfinite(z) & (z != 0) & np.all(np.isfinite(n), axis=-1)
        geom_valid &= np.isfinite(n_length) & (n_length > 0) & np.isfinite(r) & (r >= 0) & (r <= 1)
        normal = np.zeros_like(n)
        np.divide(n, n_length[..., None], out=normal, where=(geom_valid)[..., None])
        valid = src_valid & rr_valid & geom_valid
        # Zero input samples remain zero in the SAME linear-mean denominator.
        # Only invalid (negative/nonfinite) observations and invalid guides are
        # removed; both source and RR use identical accepted sample support.
        clean_src = np.where(valid[..., None], src_rgb, 0)
        clean_rr = np.where(valid[..., None], rr_rgb, 0)
        clean_z = np.where(geom_valid, z, 0)
        clean_r = np.where(geom_valid, r, 0)
        source_mean, colour_mean, n_eff, sum_w = _support_means(
            clean_src, clean_rr, clean_z, normal, clean_r, valid, cfg)
        source_chroma, source_y = normalized_colour(source_mean)
        colour_chroma, colour_y = normalized_colour(colour_mean)
        _, pixel_y = normalized_colour(clean_rr)
        supported = valid & (source_y > 0) & (colour_y > 0) & (pixel_y > 0)
        extra_samples = np.maximum(n_eff - 1, 0)
        confidence = np.zeros_like(n_eff)
        np.divide(extra_samples, extra_samples + cfg.support_prior, out=confidence,
                  where=(extra_samples + cfg.support_prior) > 0)
        confidence = np.where(supported, confidence, 0).astype(np.float32)
        log_delta = np.clip(opponent_encode(source_mean) - opponent_encode(colour_mean),
                            -cfg.max_log_delta, cfg.max_log_delta)
        # The linear competitor has the same support and +/- amplitude budget
        # around the low-band reference, but additive rather than ratio transport.
        linear_limit = np.maximum(colour_chroma, CHROMA_EPS) * np.float32(math.expm1(cfg.max_log_delta))
        linear_delta = np.clip(source_chroma - colour_chroma, -linear_limit, linear_limit)
        amount = confidence * np.float32(cfg.strength)
        if cfg.representation == "log":
            change = log_delta * amount[..., None]
            gain = np.stack([np.exp(change[..., 0]), np.ones_like(amount), np.exp(change[..., 1])], axis=-1)
            transported = clean_rr * gain
            nonzero = np.any(change != 0, axis=-1)
        else:
            pixel_chroma, _ = normalized_colour(clean_rr)
            change = linear_delta * amount[..., None]
            transported = np.maximum(pixel_chroma + change, 0)
            nonzero = np.any(change != 0, axis=-1)
        transported_y = luminance(transported)
        corrected = np.zeros_like(transported)
        np.divide(transported * pixel_y[..., None], transported_y[..., None],
                  out=corrected, where=(transported_y > 0)[..., None])
        representable = np.all(np.isfinite(corrected) & (corrected >= 0), axis=-1)
        limit = np.finfo(selected.dtype).max
        representable &= np.all(corrected <= limit, axis=-1)
        write = eligible[:ah, :aw] & supported & (amount > 0) & nonzero & representable
        # No write occurs for a failed/zero correction, rather than an RGB
        # round-trip that would change innocent selected bytes.
        destination = output[:ah, :aw, :3]
        if selected.dtype == np.float16:
            destination[write] = half_rtz(corrected[write])
        else:
            destination[write] = corrected[write].astype(np.float32)
        diag["confidence"][:ah, :aw] = confidence
        diag["effective_samples"][:ah, :aw] = n_eff
        diag["weight_sum"][:ah, :aw] = sum_w
        diag["source_mean"][:ah, :aw] = source_mean
        diag["colour_mean"][:ah, :aw] = colour_mean
        diag["log_delta"][:ah, :aw] = log_delta
        diag["linear_delta"][:ah, :aw] = linear_delta
        diag["supported"][:ah, :aw] = supported
        diag["overflow_rejected"][:ah, :aw] = eligible[:ah, :aw] & supported & ~representable
        diag["correction"][:ah, :aw] = np.where(write[..., None], corrected - clean_rr, 0)
        diag["changed"] = np.any(rgba_words(output) != rgba_words(selected), axis=-1)
        return output, diag
