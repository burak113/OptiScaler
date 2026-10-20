"""Audited octahedral payload operations and deliberately lossy legacy control."""
import numpy as np

from .arithmetic import f32, f32_add, f32_div, f32_mul, f32_sub


def _components(values, size):
    a = f32(values)
    if a.ndim == 0 or a.shape[-1] != size:
        raise ValueError(f"expected final dimension {size}")
    return a


def pack_normal11(octahedral_uv):
    """Source PackNormal: floor(clamp(uv,0,1)*[63,31]+.5), qx*32+qy.

    Finite UVs may be outside [0,1] and are saturated exactly as the source.
    Nonfinite guides are rejected rather than assigned an invented normal.
    Returned payload is float32, ready for a declared FP16 store boundary.
    """
    uv = _components(octahedral_uv, 2)
    if not np.isfinite(uv).all():
        raise ValueError("nonfinite octahedral guide is outside the valid contract")
    q = np.floor(f32_add(f32_mul(np.clip(uv, 0, 1), f32([63, 31])), .5))
    return f32_add(f32_mul(q[..., 0], 32), q[..., 1])


def unpack_normal11(packed):
    """Validated source UnpackNormal; accepts only integer payloads0..2047."""
    p = f32(packed)
    if (not np.isfinite(p).all() or np.any(p < 0) or np.any(p > 2047)
            or np.any(p != np.floor(p))):
        raise ValueError("normal payload must be an integer in [0,2047]")
    x = np.floor(f32_div(p, 32))
    y = f32_sub(p, f32_mul(x, 32))
    return f32_div(np.stack([x, y], axis=-1), f32([63, 31]))


def octahedral_encode(normal, *, degenerate="raise"):
    """FSRDPreprocessCommon source-shaped encode, including >0 fold signs.

    A zero/nonfinite vector is not a valid source guide. ``degenerate='nan'``
    marks it explicitly; it never silently substitutes a face normal. No claim
    is made about a particular compiler's result for source divide-by-zero.
    """
    if degenerate not in ("raise", "nan"):
        raise ValueError("degenerate must be 'raise' or 'nan'")
    n = _components(normal, 3)
    denominator = f32_add(f32_add(np.abs(n[..., 0]), np.abs(n[..., 1])), np.abs(n[..., 2]))
    valid = np.isfinite(n).all(axis=-1) & np.isfinite(denominator) & (denominator > 0)
    if degenerate == "raise" and not valid.all():
        raise ValueError("zero/nonfinite/overflowed normal has no supported source encoding")
    with np.errstate(divide="ignore", invalid="ignore"):
        xy = f32_div(n[..., :2], denominator[..., None])
    k = np.where(xy > 0, np.float32(1), np.float32(-1))
    folded = f32_mul(f32_sub(1, np.abs(xy[..., ::-1])), k)
    xy = np.where((n[..., 2] < 0)[..., None], folded, xy)
    encoded = f32_add(f32_mul(xy, .5), .5)
    return np.where(valid[..., None], encoded, np.float32(np.nan))


def octahedral_decode(octahedral_uv):
    """Source-shaped decode with >=0 fold convention and explicit normalization.

    Finite [0,1] UV is the audited domain. Outside-domain values are rejected.
    Separate float32 adds/multiplies are a named staging model; normalize codegen
    and reciprocal-square-root accuracy are not inferred from this CPU result.
    """
    uv = _components(octahedral_uv, 2)
    if not np.isfinite(uv).all() or np.any(uv < 0) or np.any(uv > 1):
        raise ValueError("decode requires finite octahedral UV in [0,1]")
    u = f32_mul(2, f32_sub(uv, .5))
    z = f32_sub(f32_sub(1, np.abs(u[..., 0])), np.abs(u[..., 1]))
    t = np.maximum(-z, np.float32(0))
    xy = f32_add(u, np.where(u >= 0, -t[..., None], t[..., None]))
    n = np.concatenate([xy, z[..., None]], axis=-1)
    length_squared = f32_add(f32_add(f32_mul(n[..., 0], n[..., 0]),
                                    f32_mul(n[..., 1], n[..., 1])),
                            f32_mul(n[..., 2], n[..., 2]))
    return f32_div(n, np.sqrt(length_squared).astype(np.float32)[..., None])


def pack_normal16_old(octahedral_uv):
    """Negative control: normalized16-bit (8+8) payload stored into one half.

    Input is [0,1] oct UV. The frozen portable pack_old accepts signed oct and
    first maps it to this UV domain; the code arithmetic is the same here.
    """
    uv = _components(octahedral_uv, 2)
    if not np.isfinite(uv).all():
        raise ValueError("nonfinite legacy guide")
    q = np.floor(f32_add(f32_mul(np.clip(uv, 0, 1), 255), .5))
    return f32_div(f32_add(f32_mul(q[..., 0], 256), q[..., 1]), 65535)


def unpack_normal16_old(packed):
    """Decode the lossy old normalized payload into unit-interval oct UV."""
    p = f32(packed)
    if not np.isfinite(p).all() or np.any(p < 0) or np.any(p > 1):
        raise ValueError("legacy payload must be finite in [0,1]")
    q = np.floor(f32_add(f32_mul(p, 65535), .5))
    x = np.floor(f32_div(q, 256))
    return f32_div(np.stack([x, f32_sub(q, f32_mul(x, 256))], -1), 255)


def angular_error_degrees(a, b):
    """Float64 diagnostic angular error, distinct from source guide arithmetic."""
    aa = np.asarray(a, dtype=np.float64)
    bb = np.asarray(b, dtype=np.float64)
    if aa.shape[-1:] != (3,) or bb.shape[-1:] != (3,):
        raise ValueError("expected normals with final dimension3")
    na = np.linalg.norm(aa, axis=-1)
    nb = np.linalg.norm(bb, axis=-1)
    if not np.isfinite(aa).all() or not np.isfinite(bb).all() or np.any(na == 0) or np.any(nb == 0):
        raise ValueError("angular error needs finite nonzero normals")
    dot = np.sum((aa / na[..., None]) * (bb / nb[..., None]), axis=-1)
    return np.degrees(np.arccos(np.clip(dot, -1, 1)))
