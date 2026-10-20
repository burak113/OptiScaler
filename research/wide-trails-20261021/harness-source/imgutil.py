"""Small numpy image helpers (no scipy on this machine)."""
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as _swv

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def gaussian(a, s):
    """Separable Gaussian over the last two axes with edge clamping."""
    r = int(3 * s + 0.5)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / s) ** 2)
    k /= k.sum()
    from . import gpu  # D3D12 helper; RRLAB_GPU=0 or a held GPU lock -> the numpy code below
    if a.ndim >= 2 and a.size >= gpu.MIN_PIXELS and gpu.available():
        out = gpu.blur(a, k.astype(np.float32))
        if out is not None:
            return out

    def conv(x, ax):
        pad = [(0, 0)] * x.ndim
        pad[ax] = (r, r)
        p = np.pad(x, pad, mode='edge')
        if r > 24:  # large sigma: same edge-clamped result via FFT (sigma <= 8 keeps the exact direct path)
            n = p.shape[ax] + 2 * r
            f = np.fft.irfft(np.fft.rfft(p.astype(np.float64), n, axis=ax)
                             * np.expand_dims(np.fft.rfft(k, n), [d for d in range(x.ndim) if d != ax]), n, axis=ax)
            sl = [slice(None)] * x.ndim
            sl[ax] = slice(2 * r, 2 * r + x.shape[ax])
            return f[tuple(sl)].astype(np.float32)
        out = np.zeros_like(x, dtype=np.float32)
        for i, w in enumerate(k):
            sl = [slice(None)] * x.ndim
            sl[ax] = slice(i, i + x.shape[ax])
            out += w * p[tuple(sl)]
        return out

    return conv(conv(a.astype(np.float32), a.ndim - 2), a.ndim - 1)


def medf(a, k):
    p = k // 2
    return np.median(_swv(np.pad(a, p, mode='edge'), (k, k)), axis=(-2, -1))


def boxf(a, k):
    p = k // 2
    return _swv(np.pad(a, p, mode='edge'), (k, k)).mean(axis=(-2, -1))


def tonemap(rgb, exposure):
    """Reinhard + gamma 2.2 to uint8 at a fixed exposure (same for every variant of a report)."""
    v = np.maximum(rgb, 0) * exposure
    return (np.clip(v / (1 + v), 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)


def heat(v, hi):
    """Dark blue (0) -> orange -> yellow (>= hi)."""
    t = np.clip(v / hi, 0, 1)
    return (np.stack([t, t ** 2 * 0.75 + 0.05 * (1 - t), 0.25 * (1 - t) + 0.1 * t ** 4], -1) * 255).astype(np.uint8)
