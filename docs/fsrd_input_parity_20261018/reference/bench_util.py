import numpy as np
def erode(m, r):
    out = m.copy()
    for _ in range(r):
        p = np.pad(out, 1, constant_values=False)
        out = p[1:-1, 1:-1] & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
    return out
def gaussian(a, s):
    """Separable Gaussian over the last two image axes (H, W) with edge clamping."""
    r = int(3*s+0.5); k = np.exp(-0.5*(np.arange(-r, r+1)/s)**2); k /= k.sum()
    ax_h, ax_w = (a.ndim-2, a.ndim-1)
    def conv(x, ax):
        pad = [(0, 0)]*x.ndim; pad[ax] = (r, r); p = np.pad(x, pad, mode='edge')
        out = np.zeros_like(x, dtype=np.float32)
        for i, w in enumerate(k):
            sl = [slice(None)]*x.ndim; sl[ax] = slice(i, i+x.shape[ax]); out += w*p[tuple(sl)]
        return out
    return conv(conv(a.astype(np.float32), ax_h), ax_w)
def mgauss(a, m, s):
    return gaussian(a*m, s)/np.maximum(gaussian(m.astype(np.float32), s), 1e-6)
