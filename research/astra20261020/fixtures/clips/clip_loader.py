"""Portable CPU-only loader and correspondence. Python stdlib + NumPy only."""
import hashlib
import json
from pathlib import Path
import numpy as np


def array_sha(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes(order="C")).hexdigest()


def load_clip(path, verify=True):
    path = Path(path)
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    with np.load(path, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    if verify:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for b in iter(lambda: f.read(1024 * 1024), b""):
                h.update(b)
        if h.hexdigest() != meta["archive"]["sha256"]:
            raise ValueError("Archive hash mismatch")
        if set(arrays) != set(meta["arrays"]):
            raise ValueError("Array set mismatch")
        for key, a in arrays.items():
            desc = meta["arrays"][key]
            if a.dtype.str != desc["dtype"] or list(a.shape) != desc["shape"] or array_sha(a) != desc["raw_sha256"]:
                raise ValueError("Array bit/dtype/shape mismatch: " + key)
            if a.dtype.kind == "f" and not np.isfinite(a).all():
                raise ValueError("Nonfinite captured float array: " + key)
    return arrays, meta


def previous_coordinates(arrays, t):
    if t <= 0:
        raise ValueError("Previous frame is outside this partial fixture")
    mv = arrays["input_motion"][t, ..., :2].astype(np.float64)
    h, w = mv.shape[:2]
    yy, xx = np.mgrid[:h, :w]
    origin = arrays["crop_origin_render"]
    delta = origin[t].astype(np.float64) - origin[t - 1]
    qx = xx + delta[0] + mv[..., 0] * int(arrays["render_extent"][0])
    qy = yy + delta[1] + mv[..., 1] * int(arrays["render_extent"][1])
    valid = np.isfinite(qx) & np.isfinite(qy) & (qx >= 0) & (qy >= 0) & (qx < w - 1) & (qy < h - 1)
    return qx, qy, valid


def sample_previous(image, qx, qy):
    """Bilinear sample; invalid values are NaN, never an edge-clamp sample."""
    h, w = image.shape[:2]
    valid = np.isfinite(qx) & np.isfinite(qy) & (qx >= 0) & (qy >= 0) & (qx < w - 1) & (qy < h - 1)
    tail = image.shape[2:]
    result = np.full(qx.shape + tail, np.nan, dtype=np.float64)
    x, y = np.floor(qx[valid]).astype(int), np.floor(qy[valid]).astype(int)
    fx, fy = qx[valid] - x, qy[valid] - y
    if tail:
        fx, fy = fx[:, None], fy[:, None]
    result[valid] = (image[y, x] * (1 - fx) * (1 - fy) + image[y, x + 1] * fx * (1 - fy) + image[y + 1, x] * (1 - fx) * fy + image[y + 1, x + 1] * fx * fy)
    return result, valid
