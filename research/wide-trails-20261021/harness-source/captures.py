"""GAME_TRACE capture access for RR Lab (bridge and combined-colour captures).

Bridge captures (NRD route) hold the exact RR inputs in physical units (input_diffuse/specular, depth, motion,
normal_roughness, albedos) plus per-frame provider_controls.bin (ffxDispatchDescDenoiser suffix from motionVectorScale:
words 0-2 motion scale, 3-4 jitter, 5-7 camera delta, 8-23 view, 24-39 projection, 40-41 depth bounds,
42-43 render size, 44 frameIndex, 45 flags). Combined captures (FSR-RR route) are listed and analysable but not
replayable yet."""
import json
import time
from functools import lru_cache
from pathlib import Path
import numpy as np
from .paths import GAME_TRACE, CACHE
from .imgutil import LUMA

f32 = lambda w: np.array(w, np.uint32).view(np.float32)
# name -> (dtype, channels, dxgi format) of the seven RR inputs, in runner order
BRIDGE_INPUTS = [('input_depth', np.float32, 1, 41), ('input_motion', np.float16, 4, 10),
                 ('input_normal_roughness', np.uint32, 1, 24), ('input_specular_albedo', np.uint8, 4, 28),
                 ('input_diffuse_albedo', np.uint8, 4, 28), ('input_diffuse', np.float16, 4, 10),
                 ('input_specular', np.float16, 4, 10)]


class Capture:
    def __init__(self, uuid_prefix):
        matches = sorted(GAME_TRACE.glob(uuid_prefix + '*'))
        if not matches:
            raise FileNotFoundError(f'no GAME_TRACE capture starts with {uuid_prefix!r}')
        self.dir = matches[0]
        self.uuid = self.dir.name
        self.id = self.uuid[:8]
        self.j = json.loads((self.dir / 'capture.json').read_text())
        self.frames = self.j['frames']
        self.n = int(self.j.get('manifest_published_frames', len(self.frames)))
        r = self.j['roi']
        self.X0, self.Y0 = r['origin']
        self.W, self.H = r['extent']
        self.RW, self.RH = self.j['render_extent']
        self.names = {x['name'] for x in self.frames[0]['images']} if self.frames else set()
        self.kind = 'empty' if not self.frames else 'bridge' if 'input_diffuse' in self.names else 'combined'
        self._img = {}

    # ---- raw access
    def raw(self, i, name):
        im = {x['name']: x for x in self.frames[i]['images']}[name]
        return (self.dir / im['file']).read_bytes()

    def img(self, i, name, dt=np.float16, c=4):
        a = np.frombuffer(self.raw(i, name), dt)
        return a.reshape(self.H, self.W, c).astype(np.float32) if c > 1 else a.reshape(self.H, self.W)

    def depth(self, i):
        n = 'input_depth' if 'input_depth' in self.names else 'depth'
        return self.img(i, n, np.float32, 1).astype(np.float32)

    def rough(self, i):
        n = 'recovery_original_normal_roughness' if 'recovery_original_normal_roughness' in self.names else 'input_normal_roughness'
        return ((self.img(i, n, np.uint32, 1) >> 20) & 1023).astype(np.float32) / 1023.0

    def input_arrays(self, i):
        """The seven RR inputs of frame i as numpy arrays (physical units), in runner order."""
        out = {}
        for name, dt, c, _ in BRIDGE_INPUTS:
            a = np.frombuffer(self.raw(i, name), dt)
            out[name] = a.reshape(self.H, self.W, c) if c > 1 else a.reshape(self.H, self.W)
        return out

    def controls(self, i):
        return np.frombuffer((self.dir / f'frames/{i}/provider_controls.bin').read_bytes(), np.uint32).copy()

    def requested_tuning(self):
        s = self.frames[0].get('settings', {})
        # Unselected requested_values are canonical zeros, NOT the provider's tuning.
        # Prefer the effective state when the capture attests queried defaults.
        if s.get('defaults_ready') and s.get('provider_effective'):
            return [float(x) for x in f32(s['provider_effective'][:6])]
        v = s.get('requested_values')
        if v:
            values = [float(x) for x in f32(s['provider_defaults'][:6])] if s.get('provider_defaults') else [0.5, 0.5, 40000.0, 40.0, 0.5, 0.1]
            mask = int(s.get('override_mask', 63))
            for k in range(6):
                if mask & (1 << k): values[k] = float(f32(v[:6])[k])
            return values
        if s.get('provider_effective'):
            return [float(x) for x in f32(s['provider_effective'][:6])]
        t = s.get('sdk_tuning')
        return [float(x) for x in t] if t else [0.5, 0.5, 40000.0, 40.0, 0.5, 0.1]

    # ---- signals
    def rgb(self, i, kind='in'):
        if kind == 'rr':
            return self.img(i, 'selected_rr_diffuse')[..., :3] + self.img(i, 'selected_rr_specular')[..., :3]
        if kind == 'raw':
            return self.img(i, 'raw_rr_diffuse')[..., :3] + self.img(i, 'raw_rr_specular')[..., :3]
        return self.img(i, 'input_diffuse')[..., :3] + self.img(i, 'input_specular')[..., :3]

    # ---- camera / reprojection (frame a's view, frame t's image)
    def camera(self, i):
        fp = self.frames[i]['frame_parameters']
        cam = fp['camera']
        return (f32(fp['camera_position']), f32(fp['previous_camera_position']),
                f32(cam['view']).reshape(4, 4), f32(cam['projection']).reshape(4, 4))

    def _pix(self):
        yy, xx = np.mgrid[0:self.H, 0:self.W].astype(np.float64)
        return xx + self.X0 + 0.5, yy + self.Y0 + 0.5

    def _world(self, V, P, z):
        px, py = self._pix()
        nx, ny = px / self.RW * 2 - 1, 1 - py / self.RH * 2
        d = np.stack([nx * z / P[0, 0], ny * z / P[1, 1], z], -1)
        Vi = np.linalg.inv(V.astype(np.float64))
        return d @ Vi[:3, :3].T + Vi[:3, 3]

    def _project(self, V, P, X):
        xv = X @ V[:3, :3].T.astype(np.float64) + V[:3, 3]
        z = xv[..., 2]
        nx, ny = P[0, 0] * xv[..., 0] / z, P[1, 1] * xv[..., 1] / z
        return (nx + 1) / 2 * self.RW - self.X0 - 0.5, (1 - ny) / 2 * self.RH - self.Y0 - 0.5

    def _sample(self, img, qx, qy):
        x0 = np.floor(qx).astype(int); y0 = np.floor(qy).astype(int); fx = qx - x0; fy = qy - y0
        ok = (x0 >= 0) & (y0 >= 0) & (x0 < self.W - 1) & (y0 < self.H - 1)
        x0c, y0c = np.clip(x0, 0, self.W - 2), np.clip(y0, 0, self.H - 2)
        w = [(1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy]
        v = [img[y0c, x0c], img[y0c, x0c + 1], img[y0c + 1, x0c], img[y0c + 1, x0c + 1]]
        if img.ndim == 3:
            w = [a[..., None] for a in w]
        return sum(a * b for a, b in zip(w, v)), ok

    def warp(self, a, t, img):
        """Bring frame t's image into frame a's view (camera reprojection with frame a's depth)."""
        if a == t:
            return img, np.ones((self.H, self.W), bool)
        from . import gpu  # D3D12 helper; RRLAB_GPU=0 or a held GPU lock -> numpy below
        if self.H * self.W >= gpu.MIN_PIXELS and gpu.available():
            r = gpu.warp(self, a, t, img)
            if r is not None:
                return r
        _, _, Va, Pa = self.camera(a)
        z = self.depth(a).astype(np.float64)
        _, _, V, P = self.camera(t)
        qx, qy = self._project(V, P, self._world(Va, Pa, z))
        return self._sample(img, qx, qy)

    # ---- motion profile
    @lru_cache(maxsize=1)
    def motion(self):
        """Per frame: rotation (deg/frame) and translation (m/frame) from the previous frame."""
        rot, tr = [0.0], [0.0]
        for i in range(1, self.n):
            c0, c1 = self.camera(i - 1), self.camera(i)
            R0, R1 = c0[2][:3, :3], c1[2][:3, :3]
            rot.append(float(np.degrees(np.arccos(np.clip((np.trace(R1 @ R0.T) - 1) / 2, -1, 1)))))
            tr.append(float(np.linalg.norm(c1[0] - c0[0])))
        return np.array(rot), np.array(tr)

    def segments(self, still_deg=0.1, still_m=0.0015, dilate=2, min_len=8, warmup=10):
        """Still and moving frame runs (after an RR warm-up) and the last fast turn (> 3 deg/frame).
        Hand-held idle sway is 0.03-0.07 deg/frame, so 'moving' starts at 0.1 deg/frame (the adaptive-stability
        threshold); moving frames are dilated by `dilate` so short pauses inside a pan stay one run."""
        rot, tr = self.motion()
        hit = (rot > still_deg) | (tr > still_m)
        moving = np.array([hit[max(0, i - dilate):i + dilate + 1].any() for i in range(self.n)])
        runs, start = [], warmup
        for i in range(warmup, self.n + 1):
            if i == self.n or (i > start and moving[i] != moving[start]):
                if i - start >= min_len:
                    runs.append(('moving' if moving[start] else 'still', start, i))
                start = i
        merged = []  # same-kind runs separated only by a dropped short run become one
        for r in runs:
            if merged and merged[-1][0] == r[0] and r[1] - merged[-1][2] < min_len:
                merged[-1] = (r[0], merged[-1][1], r[2])
            else:
                merged.append(r)
        runs = merged
        fast = [i for i in range(self.n) if rot[i] > 3.0]
        return dict(runs=runs, last_fast_turn=(max(fast) if fast else None), rot=rot.tolist(), tr=tr.tolist())


def list_captures():
    """Index of every capture (cached by capture.json mtime)."""
    idx_path = CACHE / 'captures_index.json'
    old = json.loads(idx_path.read_text()) if idx_path.exists() else {}
    out = {}
    for d in sorted(GAME_TRACE.iterdir()):
        cj = d / 'capture.json'
        if not cj.exists():
            continue
        m = cj.stat().st_mtime
        if d.name in old and old[d.name].get('mtime') == m:
            out[d.name] = old[d.name]
            continue
        try:
            c = Capture(d.name)
            seg = c.segments() if c.kind == 'bridge' and c.n > 1 else dict(runs=[], last_fast_turn=None, rot=[], tr=[])
            out[d.name] = dict(mtime=m, id=c.id, kind=c.kind, domain=c.j.get('captured_domain'), frames=c.n,
                               date=time.strftime('%Y-%m-%d %H:%M', time.localtime(m)),
                               roi=[c.X0, c.Y0, c.W, c.H], render=[c.RW, c.RH],
                               runs=seg['runs'], last_fast_turn=seg['last_fast_turn'],
                               max_rot=max(seg['rot']) if seg['rot'] else 0.0)
        except Exception as e:  # malformed or partial capture
            out[d.name] = dict(mtime=m, id=d.name[:8], kind='error', error=str(e)[:200])
    idx_path.write_text(json.dumps(out, indent=1))
    return out
