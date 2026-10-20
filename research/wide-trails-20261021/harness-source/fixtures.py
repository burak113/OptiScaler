"""Synthetic scenes built from real captures (they replay through runner.run like any capture).

Step(cap, at, gain, box=None)   real frames, input radiance x gain from frame `at` on (whole ROI or box x0,y0,x1,y1):
                                a light switching on/off. Use a static capture (d6d2a083: 128 still frames).
ChromaStep(cap, at, box=None)  same, but a luma-neutral colour step: per-channel gain (1.15, 0.97, 0.85) from frame
                                `at` on (whole ROI or box), per lobe+frame normalised so the mean luminance is
                                unchanged (task 25; GAIN matches hooks/claude_cstep.py for comparability).
Freeze(cap, frame, n, step_at=None, gain=1.0)
                                one frame repeated n times with zero motion/jitter/camera delta and a progressing
                                frameIndex (noise frozen too: measures pure temporal response, no boiling)."""
import numpy as np
from .captures import Capture
from .imgutil import LUMA

CHROMA_GAIN = np.array([1.15, 0.97, 0.85], np.float32)


class _Wrapped(Capture):
    def __init__(self, src, tag):
        self.__dict__.update({k: v for k, v in src.__dict__.items() if k != '_img'})
        self.src = src
        self.uuid = f'{src.uuid}#{tag}'
        self.id = f'{src.id}#{tag}'


class Step(_Wrapped):
    def __init__(self, src, at, gain, box=None):
        src = src if isinstance(src, Capture) else Capture(src)
        super().__init__(src, f'step{at}x{gain:g}' + (f'box{"_".join(map(str, box))}' if box else ''))
        self.at, self.gain, self.box = at, gain, box

    def _gain_map(self):
        g = np.ones((self.H, self.W, 1), np.float32)
        if self.box:
            x0, y0, x1, y1 = self.box
            g[y0:y1, x0:x1] = self.gain
        else:
            g[:] = self.gain
        return g

    def raw(self, i, name):
        b = self.src.raw(i, name)
        if i < self.at or name not in ('input_diffuse', 'input_specular'):
            return b
        a = np.frombuffer(b, np.float16).reshape(self.H, self.W, 4).astype(np.float32)
        a[..., :3] *= self._gain_map()
        return np.minimum(a, 65504).astype(np.float16).tobytes()

    def rgb(self, i, kind='in'):
        x = self.src.rgb(i, kind)
        return x * self._gain_map() if (kind == 'in' and i >= self.at) else x


class ChromaStep(_Wrapped):
    """Luma-neutral colour step (task 25): per-channel gain in `box` (or whole ROI) from frame `at` on.
    Per lobe and frame the gain is normalised so that lobe's mean luminance is unchanged, so a level
    change can never pose as a colour response. k is computed over the whole ROI (matches claude_cstep.py)."""

    def __init__(self, src, at, box=None):
        src = src if isinstance(src, Capture) else Capture(src)
        super().__init__(src, f'chroma{at}' + (f'box{"_".join(map(str, box))}' if box else ''))
        self.at, self.box = at, box

    def _apply(self, a):
        y = a[..., :3] * CHROMA_GAIN
        k = (a[..., :3] @ LUMA).mean() / max((y @ LUMA).mean(), 1e-12)
        out = a.copy()
        out[..., :3] = y * k
        return out

    def _mask3(self):
        g = np.zeros((self.H, self.W, 3), bool)
        if self.box:
            x0, y0, x1, y1 = self.box
            g[y0:y1, x0:x1] = True
        else:
            g[:] = True
        return g

    def raw(self, i, name):
        b = self.src.raw(i, name)
        if i < self.at or name not in ('input_diffuse', 'input_specular'):
            return b
        a = np.frombuffer(b, np.float16).reshape(self.H, self.W, 4).astype(np.float32)
        m = self._mask3()
        a[..., :3] = np.where(m, self._apply(a)[..., :3], a[..., :3])
        return np.minimum(a, 65504).astype(np.float16).tobytes()

    def rgb(self, i, kind='in'):
        x = self.src.rgb(i, kind)
        if kind != 'in' or i < self.at:
            return x
        a = np.concatenate([x, np.ones_like(x[..., :1])], -1)
        out = self._apply(a)[..., :3]
        return np.where(self._mask3(), out, x)


class Freeze(_Wrapped):
    def __init__(self, src, frame, n, step_at=None, gain=1.0):
        src = src if isinstance(src, Capture) else Capture(src)
        tag = f'freeze{frame}n{n}' + (f'step{step_at}x{gain:g}' if step_at is not None else '')
        super().__init__(src, tag)
        self.frame, self.n, self.step_at, self.gain = frame, n, step_at, gain
        self.frames = [src.frames[frame]] * n

    def raw(self, i, name):
        b = self.src.raw(self.frame, name)
        if name == 'input_motion':
            m = np.frombuffer(b, np.float16).reshape(self.H, self.W, 4).copy()
            m[..., :3] = 0
            return m.tobytes()
        if self.step_at is not None and i >= self.step_at and name in ('input_diffuse', 'input_specular'):
            a = np.frombuffer(b, np.float16).reshape(self.H, self.W, 4).astype(np.float32)
            a[..., :3] *= self.gain
            return np.minimum(a, 65504).astype(np.float16).tobytes()
        return b

    def controls(self, i):
        u = self.src.controls(self.frame)
        a = u.view(np.float32)
        a[3:5] = 0.0      # jitter
        a[5:8] = 0.0      # camera position delta
        u[44] = (int(u[44]) - self.frame + i) & 0xffffffff  # frameIndex keeps counting
        return u

    def camera(self, i):
        return self.src.camera(self.frame)

    def depth(self, i):
        return self.src.depth(self.frame)

    def rgb(self, i, kind='in'):
        x = self.src.rgb(self.frame, kind)
        return x * self.gain if (kind == 'in' and self.step_at is not None and i >= self.step_at) else x

    def motion(self):
        return np.zeros(self.n), np.zeros(self.n)
