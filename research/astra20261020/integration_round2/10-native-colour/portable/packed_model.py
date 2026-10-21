"""CPU reference for the rejected native research shader and its byte contract.

This model is independent of the frozen job03 implementation. It mirrors ordered
float32 tap accumulation, not GPU instructions/FMA/denormals. Native parity must
be measured separately. Metadata is an explicit caller assertion, not a producer
of material/light identity. No quality claim follows from passing this module.
"""
from dataclasses import dataclass, replace
import math
import struct

import numpy as np

F = np.float32
LUMA = np.array([.2126, .7152, .0722], np.float32)
EPS = F(1e-4)
MAX_DIM = 16384


@dataclass(frozen=True)
class Config:
    enabled: bool = False
    acknowledge_rejected_research: bool = False
    representation: int = 0
    radius: int = 3
    spatial_sigma: float = 2.
    depth_tolerance: float = .02
    normal_cosine: float = .9
    roughness_tolerance: float = .15
    guide_chroma_radius: float = .35
    max_log_delta: float = .2231435513
    support_prior: float = 4.
    strength: float = 1.

    def uploaded(self):
        """Validate the actual float32 CB values, including squared divisors."""
        names = ('spatial_sigma', 'depth_tolerance', 'normal_cosine',
                 'roughness_tolerance', 'guide_chroma_radius', 'max_log_delta',
                 'support_prior', 'strength')
        if type(self.enabled) is not bool or type(self.acknowledge_rejected_research) is not bool:
            raise ValueError('explicit boolean switches required')
        if type(self.representation) is not int or self.representation not in (0, 1):
            raise ValueError('unknown representation')
        if type(self.radius) is not int or not 0 <= self.radius <= 8:
            raise ValueError('invalid radius')
        with np.errstate(over='ignore', invalid='ignore'):
            values = {name: F(getattr(self, name)) for name in names}
        if not all(np.isfinite(v) for v in values.values()):
            raise ValueError('nonfinite float32 constant')
        if any(v != 0 and abs(v) < np.finfo(np.float32).tiny for v in values.values()):
            raise ValueError('nonzero subnormal constant can flush on GPU')
        c = replace(self, **values)
        if not (0 <= c.strength <= 1 and 0 <= c.max_log_delta <= 2 and
                -1 <= c.normal_cosine < 1 and 0 <= c.support_prior <= 1048576):
            raise ValueError('constant out of range')
        with np.errstate(over='ignore', under='ignore'):
            positive = (c.spatial_sigma, F(c.spatial_sigma*c.spatial_sigma),
                        c.depth_tolerance, c.roughness_tolerance,
                        c.guide_chroma_radius, F(c.guide_chroma_radius*c.guide_chroma_radius),
                        F(1)-c.normal_cosine)
        if not all(np.isfinite(v) and v >= np.finfo(np.float32).tiny for v in positive):
            raise ValueError('denormal/zero/overflow divisor')
        if c.depth_tolerance > 1 or c.roughness_tolerance > 1 or c.spatial_sigma > 4096 or c.guide_chroma_radius > 64:
            raise ValueError('unsupported diagnostic range')
        return c


@dataclass(frozen=True)
class Identity:
    frame: int = 7
    generation: int = 1
    recording: int = 11
    render_width: int = 13
    render_height: int = 9
    crop_x: int = 0
    crop_y: int = 0
    active_width: int = 13
    active_height: int = 9
    lobe: int = 0
    provider_scale: int = 16

    def valid(self):
        values = tuple(self.__dict__.values())
        return (all(type(x) is int for x in values) and 0 <= self.frame < (1 << 64) and
                0 < self.generation < (1 << 64) and 0 < self.recording < (1 << 64) and
                0 < self.render_width <= MAX_DIM and 0 < self.render_height <= MAX_DIM and
                self.crop_x >= 0 and self.crop_y >= 0 and
                0 < self.active_width <= self.render_width-self.crop_x and
                0 < self.active_height <= self.render_height-self.crop_y and
                (self.lobe, self.provider_scale) in ((0, 16), (1, 256)))


@dataclass(frozen=True)
class Evidence:
    identity: Identity
    authority_kind: int = 0  # 0 unknown; 1 synthetic; 2 external certified
    support_kind: int = 0
    source_stage: int = 0  # 1 pre-provider physical snapshot only
    estimator_version: int = 1
    radius: int = 3
    producer_version: int = 0


@dataclass(frozen=True)
class Layout:
    width: int
    height: int
    row_pitch: int
    offset: int
    size: int

    def validate(self, active):
        aw, ah = active
        if (any(type(x) is not int for x in (*self.__dict__.values(), aw, ah)) or
                not 0 < aw <= self.width <= MAX_DIM or not 0 < ah <= self.height <= MAX_DIM or
                self.row_pitch < self.width*8 or self.row_pitch % 256 or self.offset < 0 or
                self.offset % 512 or self.size <= 0 or self.size % 4 or
                self.size > 0xffffffff or self.offset+self.row_pitch*self.height > self.size):
            raise ValueError('invalid full-allocation footprint')
        return self


def words(value):
    a = np.asarray(value)
    if a.ndim != 3 or a.shape[2] != 4 or a.dtype not in (np.dtype('<f2'), np.dtype('<u2')):
        raise ValueError('original little-endian native RGBA16 words required')
    return np.ascontiguousarray(a).view('<u2')


def pack(value, layout, fill=0xcd):
    a = words(value)
    layout.validate((a.shape[1], a.shape[0]))
    if (a.shape[1], a.shape[0]) != (layout.width, layout.height):
        raise ValueError('layout is for a different texture')
    out = np.full(layout.size, fill, np.uint8)
    for y in range(layout.height):
        start = layout.offset+y*layout.row_pitch
        out[start:start+8*layout.width] = a[y].view(np.uint8).ravel()
    return out


def unpack(data, layout):
    layout.validate((layout.width, layout.height))
    data = np.asarray(data)
    if data.dtype != np.uint8 or data.ndim != 1 or data.size != layout.size:
        raise ValueError('raw SRV capacity differs from footprint')
    return np.stack([data[layout.offset+y*layout.row_pitch:
                         layout.offset+y*layout.row_pitch+8*layout.width]
                     for y in range(layout.height)]).copy().view('<u2').reshape(layout.height, layout.width, 4)


def constants(c, identity, layouts):
    c = c.uploaded()
    if not identity.valid() or len(layouts) != 4:
        raise ValueError('invalid constant identity/layout count')
    for layout in layouts:
        layout.validate((identity.active_width, identity.active_height))
    if layouts[2] != layouts[3]:
        raise ValueError('selected/output complete-buffer copy requires identical layout')
    return struct.pack('<16I8f4I', identity.active_width, identity.active_height,
                       layouts[2].width, layouts[2].height,
                       *(x.row_pitch for x in layouts), *(x.offset for x in layouts),
                       1, c.representation, c.radius, 1,
                       c.spatial_sigma, c.depth_tolerance, c.normal_cosine, c.roughness_tolerance,
                       c.guide_chroma_radius, c.max_log_delta, c.support_prior, c.strength,
                       *(x.size for x in layouts))


def luma(a):
    return np.sum(a*LUMA, axis=-1, dtype=np.float32)


def chroma(a):
    y = luma(a)
    result = np.zeros_like(a)
    np.divide(a, y[..., None], out=result, where=(y > 0)[..., None])
    return result


def opponent(a):
    q = np.maximum(chroma(a), F(0))+EPS
    return np.log(q[..., (0, 2)]/q[..., 1, None]).astype(np.float32)


def decode_normals(packed):
    p = np.asarray(packed)
    if p.dtype != np.uint32 or p.ndim != 2:
        raise ValueError('original R10G10B10A2 uint32 words required')
    u = ((p & 1023).astype(np.float32)/F(1023)-F(.5))*F(2)
    v = (((p >> 10) & 1023).astype(np.float32)/F(1023)-F(.5))*F(2)
    z = F(1)-np.abs(u)-np.abs(v)
    t = np.maximum(-z, F(0))
    n = np.stack((u+np.where(u >= 0, -t, t), v+np.where(v >= 0, -t, t), z), axis=-1)
    n /= np.sqrt(np.sum(n*n, axis=-1, dtype=np.float32))[..., None]
    r = ((p >> 20) & 1023).astype(np.float32)/F(1023)
    return n, r


def _overlap(h, w, dy, dx):
    return ((slice(max(0, -dy), min(h, h-dy)), slice(max(0, -dx), min(w, w-dx))),
            (slice(max(0, dy), min(h, h+dy)), slice(max(0, dx), min(w, w+dx))))


def _compact(a):
    v = np.maximum(F(1)-a*a, F(0))
    return v*v


def process(source, raw, selected, depth, normal, authority, support, *, config=Config(),
            identity=Identity(), evidence=None, reset=False, resized=False):
    """Return selected allocation words, diagnostic, admission reason.

    OFF/invalid admission does not inspect optional source/guide arrays. In the
    native host it returns the original selected resource, allocating nothing.
    Here returning a CPU copy makes the expected byte result directly testable.
    Unequal allocation dimensions are supported; only common active extent is read.
    """
    selected_original = np.asarray(selected)
    selected = words(selected_original)
    out = selected.copy()
    diagnostic = np.zeros((*selected.shape[:2], 4), np.float32)
    try:
        c = config.uploaded()
    except (ValueError, TypeError, OverflowError):
        return out, diagnostic, 'InvalidConfig'
    if not c.enabled or not c.acknowledge_rejected_research:
        return out, diagnostic, 'Off'
    if c.strength == 0 or c.max_log_delta == 0:
        return out, diagnostic, 'ZeroStrength'
    if reset or resized:
        return out, diagnostic, 'ResetOrResize'
    if not identity.valid() or evidence is None or evidence.identity != identity:
        return out, diagnostic, 'InvalidIdentity'
    if evidence.source_stage != 1:
        return out, diagnostic, 'UnsupportedSource'
    if type(evidence.authority_kind) is not int or evidence.authority_kind not in (1, 2):
        return out, diagnostic, 'UnknownAuthority'
    if (type(evidence.support_kind) is not int or evidence.support_kind not in (1, 2) or
            type(evidence.producer_version) is not int or not 0 < evidence.producer_version < (1 << 64) or
            type(evidence.estimator_version) is not int or evidence.estimator_version != 1 or
            type(evidence.radius) is not int or evidence.radius != c.radius):
        return out, diagnostic, 'UnknownSupport'
    h, w = identity.active_height, identity.active_width
    try:
        if (np.shares_memory(np.asarray(source), np.asarray(raw)) or
                np.shares_memory(np.asarray(source), selected_original)):
            return out, diagnostic, 'InvalidNativeResource'
        source, raw = words(source), words(raw)
        arrays = [source, raw, selected, depth, normal, authority, support]
        if any(not (h <= np.asarray(a).shape[0] <= MAX_DIM and
                    w <= np.asarray(a).shape[1] <= MAX_DIM) for a in arrays):
            return out, diagnostic, 'InvalidNativeResource'
        if np.asarray(depth).dtype != np.float32 or np.asarray(depth).ndim != 2:
            return out, diagnostic, 'InvalidNativeResource'
        if any(np.asarray(a).dtype != np.uint32 or np.asarray(a).ndim != 2 for a in (normal, authority, support)):
            return out, diagnostic, 'InvalidNativeResource'
        n, rough = decode_normals(normal[:h, :w])
    except (ValueError, TypeError, IndexError):
        return out, diagnostic, 'InvalidNativeResource'
    original = raw[:h, :w]
    source_rgb = source[:h, :w].view(np.float16)[..., :3].astype(np.float32)
    rr = original.view(np.float16)[..., :3].astype(np.float32)
    z = np.asarray(depth[:h, :w])
    eligible = (np.all(original == selected[:h, :w], axis=-1) &
                (authority[:h, :w] == 1) & (support[:h, :w] == 1))
    valid = (np.all(np.isfinite(source_rgb) & (source_rgb >= 0), axis=-1) &
             np.all(np.isfinite(rr) & (rr >= 0), axis=-1) & np.isfinite(z) & (z != 0))
    valid &= (authority[:h, :w] == 1) & (support[:h, :w] == 1)
    # Invalid donors cannot contaminate sums through 0*NaN/Inf.
    source_rgb = np.where(valid[..., None], source_rgb, F(0))
    rr = np.where(valid[..., None], rr, F(0))
    safe_z = np.where(valid, z, F(1))
    source_sum, rr_sum = np.zeros_like(rr), np.zeros_like(rr)
    sum_w, sum_w2 = np.zeros((h, w), np.float32), np.zeros((h, w), np.float32)
    guide = opponent(rr)
    with np.errstate(over='ignore', invalid='ignore', divide='ignore', under='ignore'):
        for dy in range(-c.radius, c.radius+1):
            for dx in range(-c.radius, c.radius+1):
                if abs(dy) >= h or abs(dx) >= w:
                    continue
                dst, src = _overlap(h, w, dy, dx)
                spatial = F(math.exp(float(F(-.5)*F(dx*dx+dy*dy)/F(c.spatial_sigma*c.spatial_sigma))))
                wz = _compact((safe_z[dst]-safe_z[src])/np.maximum(c.depth_tolerance*np.abs(safe_z[dst]), F(.001)))
                nd = np.clip((np.clip(np.sum(n[dst]*n[src], axis=-1), -1, 1)-c.normal_cosine)/(F(1)-c.normal_cosine), 0, 1)
                wr = _compact((rough[dst]-rough[src])/c.roughness_tolerance)
                delta = guide[dst]-guide[src]
                wc = np.maximum(F(1)-np.sum(delta*delta, axis=-1)/(c.guide_chroma_radius*c.guide_chroma_radius), F(0))
                good = valid[dst] & valid[src] & (np.signbit(safe_z[dst]) == np.signbit(safe_z[src]))
                weight = np.where(good, spatial*wz*nd*nd*wr*wc*wc, F(0))
                source_sum[dst] += weight[..., None]*source_rgb[src]
                rr_sum[dst] += weight[..., None]*rr[src]
                sum_w[dst] += weight
                sum_w2[dst] += weight*weight
        mean_s = np.zeros_like(rr)
        mean_r = np.zeros_like(rr)
        np.divide(source_sum, sum_w[..., None], out=mean_s, where=(sum_w > 0)[..., None])
        np.divide(rr_sum, sum_w[..., None], out=mean_r, where=(sum_w > 0)[..., None])
        neff = np.zeros_like(sum_w)
        np.divide(sum_w*sum_w, sum_w2, out=neff, where=sum_w2 > 0)
        extra = np.maximum(neff-F(1), F(0))
        conf = np.zeros_like(extra)
        np.divide(extra, extra+c.support_prior, out=conf, where=extra+c.support_prior > 0)
        amount = conf*c.strength
        admitted = (eligible & valid & (sum_w > 0) & (sum_w2 > 0) &
                    (luma(mean_s) > 0) & (luma(mean_r) > 0) & (luma(rr) > 0))
        if c.representation == 0:
            delta = np.clip(opponent(mean_s)-opponent(mean_r), -c.max_log_delta, c.max_log_delta)*amount[..., None]
            transported = rr*np.stack((np.exp(delta[..., 0]), np.ones_like(amount), np.exp(delta[..., 1])), axis=-1)
        else:
            cr = chroma(mean_r)
            limit = np.maximum(cr, EPS)*(np.exp(c.max_log_delta)-F(1))
            delta = np.clip(chroma(mean_s)-cr, -limit, limit)*amount[..., None]
            transported = np.maximum(chroma(rr)+delta, F(0))
        result = transported*luma(rr)[..., None]/luma(transported)[..., None]
        change = (admitted & (amount > 0) & np.any(delta != 0, axis=-1) &
                  (luma(transported) > 0) & np.all(np.isfinite(result) & (result >= 0) & (result <= 65504), axis=-1))
        safe = np.where(change[..., None], result, F(0))
        packed = safe.astype(np.float16)
        overshot = packed.astype(np.float32) > safe
        packed = np.where(overshot, np.nextafter(packed, np.float16(0)), packed).astype(np.float16).view(np.uint16)
    rgb = out[:h, :w, :3]
    rgb[change] = packed[change]
    diagnostic[:h, :w, 0] = eligible
    diagnostic[:h, :w, 1] = admitted
    diagnostic[:h, :w, 2] = np.where(admitted, conf, F(0))
    diagnostic[:h, :w, 3] = np.where(admitted, neff, F(0))
    return out, diagnostic, 'Ready'
