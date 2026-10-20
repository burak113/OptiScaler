"""GPU helpers for RR Lab (Claude 2026-10-19): a persistent runner/rrgpu.exe (D3D12 compute) runs the two hot numpy
operations - imgutil.gaussian and Capture.warp - and numpy keeps everything else.

- On by default; RRLAB_GPU=0 forces the original numpy code (bit-exact legacy numbers).
- Respects the machine-wide GPU lock: while F:/FSRD/sol_batch/gpu.lock exists (an RR replay or someone's timing run),
  every call falls back to numpy, so this helper never disturbs other agents' GPU timings.
- Any error disables the helper for the rest of the process and falls back to numpy.
- Results match numpy within float32 rounding (blur ~1e-6 relative; warp: same rules, float32 reprojection)."""
import atexit
import mmap
import os
import subprocess
import threading
import numpy as np
from .paths import LAB, GPU_LOCK_DIR

EXE = LAB / 'runner' / 'rrgpu.exe'
SHADERS = LAB / 'runner' / 'gpu'
SIZE = 192 << 20
LOCK_FILE = GPU_LOCK_DIR / 'gpu.lock'
MIN_PIXELS = 4096  # tiny arrays stay on the CPU (round trip ~1 ms)
_srv = None
_lock = threading.Lock()
_failed = False
stats = dict(gpu_calls=0, cpu_fallbacks=0)


def available():
    return os.environ.get('RRLAB_GPU', '1') != '0' and not _failed and EXE.exists() and not LOCK_FILE.exists()


class _Server:
    def __init__(self):
        self.name = f'rrlab_gpu_{os.getpid()}_{id(self)}'
        self.mm = mmap.mmap(-1, SIZE, tagname=self.name)
        self.f32 = np.frombuffer(self.mm, np.float32)
        self.p = subprocess.Popen([str(EXE), self.name, str(SIZE), str(SHADERS)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, bufsize=1,
                                  creationflags=getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0))
        line = self.p.stdout.readline().strip()
        if line != 'ready':
            raise RuntimeError(f'rrgpu start: {line}')

    def run(self, shader, up, down, groups, consts):
        c = ' '.join(str(int(x)) for x in consts)
        self.p.stdin.write(f'run {shader} {up[0]} {up[1]} {down[0]} {down[1]} {groups[0]} {groups[1]} {len(consts)} {c}\n')
        self.p.stdin.flush()
        line = self.p.stdout.readline().strip()
        if not line.startswith('ok'):
            raise RuntimeError(f'rrgpu {shader}: {line}')

    def close(self):
        try:
            self.p.stdin.write('quit\n'); self.p.stdin.flush(); self.p.wait(5)
        except Exception:
            self.p.kill()


def _server():
    global _srv
    if _srv is None:
        _srv = _Server()
        atexit.register(_srv.close)
    return _srv


def _groups(n):
    g = (n + 63) // 64
    gx = min(g, 65535)
    return gx, (g + gx - 1) // gx


def _u(x):
    return int(np.float32(x).view(np.uint32))


def _guard(fn):
    def wrapped(*a, **k):
        global _failed
        with _lock:
            try:
                out = fn(*a, **k)
                stats['gpu_calls'] += 1
                return out
            except Exception as e:  # never break an experiment: fall back to numpy for the rest of the process
                _failed = True
                print(f'[rrlab.gpu] disabled, numpy fallback: {e}', flush=True)
                return None
    return wrapped


@_guard
def blur(a, k):
    """Separable Gaussian (kernel k, len 2r+1) over the last two axes of float32 a, edge clamped. None if too big."""
    a = np.ascontiguousarray(a, np.float32)
    H, W = a.shape[-2:]
    P = int(np.prod(a.shape[:-2])) if a.ndim > 2 else 1
    n, r = P * H * W, (len(k) - 1) // 2
    K0, I0 = 0, 8192
    T0, O0 = I0 + n, I0 + 2 * n
    if len(k) > K0 + I0 or (O0 + n) * 4 > SIZE:
        raise ValueError('blur too large for the shared block')
    s = _server()
    s.f32[K0:K0 + len(k)] = k
    s.f32[I0:I0 + n] = a.ravel()
    gx, gy = _groups(n)
    s.run('blur', (0, (I0 + n) * 4), (0, 0), (gx, gy), [W, H, P, r, I0, T0, K0, 0, gx])
    s.run('blur', (0, 0), (O0 * 4, (O0 + n) * 4), (gx, gy), [W, H, P, r, T0, O0, K0, 1, gx])
    return s.f32[O0:O0 + n].reshape(a.shape).copy()


@_guard
def warp(cap, a, t, img):
    """Capture.warp on the GPU: (image, ok) or None."""
    H, W = cap.H, cap.W
    im = np.ascontiguousarray(img, np.float32)
    C = 1 if im.ndim == 2 else im.shape[-1]
    npx = H * W
    Z0, I0 = 0, npx
    O0 = I0 + npx * C
    K0 = O0 + npx * C
    if (K0 + npx) * 4 > SIZE:
        raise ValueError('warp too large for the shared block')
    _, _, Va, Pa = cap.camera(a)
    _, _, Vt, Pt = cap.camera(t)
    Vi = np.linalg.inv(Va.astype(np.float64))
    V3 = Vt[:3, :3].astype(np.float64)
    M = np.concatenate([V3 @ Vi[:3, :3], (V3 @ Vi[:3, 3] + Vt[:3, 3].astype(np.float64))[:, None]], 1)
    s = _server()
    s.f32[Z0:Z0 + npx] = cap.depth(a).astype(np.float32).ravel()
    s.f32[I0:I0 + npx * C] = im.ravel()
    gx, gy = _groups(npx)
    consts = [_u(v) for v in M.ravel()] + [_u(Pa[0, 0]), _u(Pa[1, 1]), _u(Pt[0, 0]), _u(Pt[1, 1]),
                                            _u(cap.X0), _u(cap.Y0), _u(cap.RW), _u(cap.RH)]
    consts += [W, H, C, Z0, I0, O0, K0, gx]
    s.run('warp', (0, O0 * 4), (O0 * 4, (K0 + npx) * 4), (gx, gy), consts)
    out = s.f32[O0:O0 + npx * C].reshape(im.shape).copy()
    ok = s.f32[K0:K0 + npx].reshape(H, W) > 0.5
    return out, ok
