"""Cached real-AMD-RR replays of bridge captures.

run(capture, variant, frames=None) -> Result with .diffuse .specular .rgb (float32 [N,H,W,3], game units).
Identical (capture, frames, variant content, runner exe, denoiser DLL, input-prep version) never runs twice:
results live in cache/runs/<key>.npy (raw RR fp16 output, lossless) + .json, trimmed LRU to CACHE_LIMIT_GB.
The ROI is RR's whole screen: motion is rescaled to ROI UV and the captured projection is cropped, so history
from outside the ROI is treated as off-screen (same as the earlier rr_bridge replays)."""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
from . import variants as V
from .captures import Capture, BRIDGE_INPUTS
from .paths import CACHE, TMP, RUNNER, LOADER_DLL, DENOISER_DLL, GPU_LOCK_DIR, CACHE_LIMIT_GB

PREP_VERSION = 'prep-1'   # bump when input preparation changes
RUNS = CACHE / 'runs'
RUNS.mkdir(parents=True, exist_ok=True)
_sha_memo = {}


def _filesha(p):
    p = Path(p)
    k = (str(p), p.stat().st_mtime, p.stat().st_size)
    if k not in _sha_memo:
        _sha_memo[k] = hashlib.sha256(p.read_bytes()).hexdigest()
    return _sha_memo[k]


def _load_hooks(v):
    hooks = {}
    for path in v['hooks']:
        spec = importlib.util.spec_from_file_location('rrlab_hook_' + hashlib.md5(path.encode()).hexdigest()[:8], path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for name in ('prefilter', 'motion', 'controls', 'tuning', 'output_scale'):
            if hasattr(mod, name):
                hooks.setdefault(name, []).append(getattr(mod, name))
    return hooks


def roi_controls(c, i):
    """Captured dispatch suffix with the projection cropped to the ROI and renderSize = ROI size."""
    a = np.frombuffer(c.controls(i).tobytes(), np.float32).copy()
    u = a.view(np.uint32)
    P = a[24:40].reshape(4, 4).astype(np.float64)              # row-vector convention: clip = v @ P
    ax, bx = c.RW / c.W, (c.RW - 2 * c.X0 - c.W) / c.W          # ndc_roi = a*ndc_full + b (x)
    ay, by = c.RH / c.H, (c.H - c.RH + 2 * c.Y0) / c.H          # (y up)
    P[:, 0] = ax * P[:, 0] + bx * P[:, 3]
    P[:, 1] = ay * P[:, 1] + by * P[:, 3]
    a[24:40] = P.astype(np.float32).ravel()
    u[42], u[43] = c.W, c.H
    return a


def cache_key(c, frames, v):
    h = hashlib.sha256()
    for part in (c.uuid, ','.join(map(str, frames)), V.fingerprint(v), _filesha(RUNNER), _filesha(DENOISER_DLL),
                 _filesha(LOADER_DLL), PREP_VERSION):
        h.update(part.encode() + b'|')
    # Preserve existing calibrated keys where effective == requested. Segregate the old invalid cache
    # for defaults/partial-override captures that previously replayed unselected zero-valued keys.
    settings = c.frames[0].get('settings', {})
    legacy = settings.get('requested_values') or settings.get('provider_effective')
    if legacy and list(np.asarray(legacy[:6],np.uint32).view(np.float32)) != c.requested_tuning():
        h.update(b'effective-tuning-fix23|' + np.asarray(c.requested_tuning(),np.float32).tobytes())
    return h.hexdigest()[:24]


class Result:
    def __init__(self, c, frames, v, raw, meta):
        self.cap, self.frames, self.variant, self.meta = c, frames, v, meta
        self._raw = raw  # [2, N, H, W, 3] float16 at RR scale (memmap)
        # Optional new-hook metadata only. Legacy variants keep the original scalar arithmetic.
        self._output_scale = None
        if 'output_scale' in meta:
            scales = np.asarray(meta['output_scale'], np.float32)
            if scales.shape != (len(frames), 2) or not np.all(np.isfinite(scales)) or not np.all(scales > 0):
                raise ValueError('invalid per-frame output_scale metadata')
            self._output_scale = scales

    @property
    def diffuse(self):
        if self._output_scale is not None:
            return self._raw[0].astype(np.float32) / self._output_scale[:,0,None,None,None]
        return self._raw[0].astype(np.float32) / self.variant['scale']['diffuse']

    @property
    def specular(self):
        if self._output_scale is not None:
            return self._raw[1].astype(np.float32) / self._output_scale[:,1,None,None,None]
        return self._raw[1].astype(np.float32) / self.variant['scale']['specular']

    @property
    def rgb(self):
        return self.diffuse + self.specular

    def frame(self, t):
        """Output of capture frame t (game units)."""
        k = self.frames.index(t)
        if self._output_scale is not None:
            return (self._raw[0,k].astype(np.float32) / self._output_scale[k,0]
                    + self._raw[1,k].astype(np.float32) / self._output_scale[k,1])
        return (self._raw[0, k].astype(np.float32) / self.variant['scale']['diffuse']
                + self._raw[1, k].astype(np.float32) / self.variant['scale']['specular'])


def _prepare(c, frames, v, hooks, work):
    work.mkdir(parents=True, exist_ok=True)
    files = {n: open(work / f'{n}.bin', 'wb') for n, *_ in BRIDGE_INPUTS}
    scale = {'input_diffuse': v['scale']['diffuse'], 'input_specular': v['scale']['specular']}
    with open(work / 'controls.bin', 'wb') as cf:
        for i in frames:
            for name, dt, ch, _ in BRIDGE_INPUTS:
                if name == 'input_motion':
                    m = np.frombuffer(c.raw(i, name), np.float16).reshape(c.H, c.W, 4).astype(np.float32)
                    m[..., 0] *= c.RW / c.W
                    m[..., 1] *= c.RH / c.H
                    for f in hooks.get('motion', []):
                        m = f(c, i, m)
                    files[name].write(m.astype(np.float16).tobytes())
                elif name in scale:
                    s = np.frombuffer(c.raw(i, name), np.float16).reshape(c.H, c.W, 4).astype(np.float32)
                    for f in hooks.get('prefilter', []):
                        s = f(c, i, name, s)
                    s = s.copy()
                    s[..., :3] = np.minimum(s[..., :3] * scale[name], 65504.0)
                    files[name].write(s.astype(np.float16).tobytes())
                else:
                    files[name].write(c.raw(i, name))
            a = roi_controls(c, i)
            for f in hooks.get('controls', []):
                a = f(c, i, a)
            cf.write(np.asarray(a, np.float32).tobytes())
    for f in files.values():
        f.close()


def _trim_cache():
    items = []
    for p in RUNS.glob('*.npy'):
        try:
            st = p.stat()
        except FileNotFoundError:  # Another trimming process already removed this entry.
            continue
        items.append((st.st_atime, st.st_size, p))
    total = sum(s for _, s, _ in items)
    limit = CACHE_LIMIT_GB * 1024 ** 3
    for _, size, p in sorted(items):
        if total <= limit:
            break
        try:
            p.unlink(missing_ok=True)
        except PermissionError:
            # Windows refuses deletion of another reader's live memory map. Keep its
            # metadata and try the next LRU entry; do not fail a completed replay.
            continue
        total -= size
        try:
            p.with_suffix('.json').unlink(missing_ok=True)
        except PermissionError:
            pass  # A reader owns the small sidecar; an orphan does not count as a hit.
    if total > limit:
        print('[rrlab] cache trim deferred: live locked readers keep cache above limit', flush=True)


def run(capture, variant='base', frames=None, owner='rrlab', force=False, verbose=True):
    c = capture if isinstance(capture, Capture) else Capture(capture)
    if c.kind != 'bridge':
        raise ValueError(f'{c.id} is a {c.kind} capture; RR Lab replays bridge (NRD route) captures only')
    v = V.parse(variant)
    frames = list(range(c.n)) if frames is None else [int(f) for f in frames]
    key = cache_key(c, frames, v)
    npy, meta_path = RUNS / f'{key}.npy', RUNS / f'{key}.json'
    if npy.exists() and meta_path.exists() and not force:
        os.utime(npy)  # LRU touch
        meta = json.loads(meta_path.read_text())
        return Result(c, frames, v, np.load(npy, mmap_mode='r'), meta)

    hooks = _load_hooks(v)
    base = c.requested_tuning()
    t0 = V.tuning_values(v, base)
    rot = c.motion()[0][frames]
    per = V.per_frame_tuning(v, t0, rot)
    for f in hooks.get('tuning', []):
        per = f(c, frames, per if per is not None else np.tile(np.array(t0, np.float32), (len(frames), 1)))
    output_scale = None
    for f in hooks.get('output_scale', []):
        if output_scale is not None:
            raise ValueError('only one output_scale hook may define the absolute per-frame lobe factors')
        output_scale = np.asarray(f(c, frames), np.float32)
        if output_scale.shape != (len(frames), 2) or not np.all(np.isfinite(output_scale)) or not np.all(output_scale > 0):
            raise ValueError('output_scale must be positive finite float32 [len(frames),2], diffuse then specular')
    work = TMP / f'run_{key}'
    try:
        _prepare(c, frames, v, hooks, work)
        env = dict(os.environ)
        for k in ('RR_SWAP_DIR', 'RR_PSO_LOG', 'RR_TUNING_FILE', 'RR_STAB_FILE'):
            env.pop(k, None)
        if v['patches']:
            swap = work / 'swap'
            swap.mkdir()
            from .paths import PATCHES
            for name in v['patches']:
                for f in (PATCHES / name).glob('*.dxil'):
                    shutil.copy(f, swap / f.name)
            env['RR_SWAP_DIR'] = str(swap)
            env['RR_PSO_LOG'] = str(work / 'pso.log')
        if per is not None:
            np.asarray(per, np.float32).tofile(work / 'tuning.bin')
            env['RR_TUNING_FILE'] = str(work / 'tuning.bin')
        names = [n for n, *_ in BRIDGE_INPUTS]
        job = [f'{c.W} {c.H} {len(frames)} 1 ' + ' '.join(f'{float(x):.9g}' for x in t0) + f' "{LOADER_DLL.as_posix()}"']
        job += [f'"{(work / (n + ".bin")).as_posix()}" {fmt}' for n, _, _, fmt in BRIDGE_INPUTS]
        job += [f'"{(work / "diff_out.bin").as_posix()}" "{(work / "spec_out.bin").as_posix()}" "{(work / "controls.bin").as_posix()}"']
        (work / 'job.txt').write_text('\n'.join(job) + '\n')
        sys.path.insert(0, str(GPU_LOCK_DIR))
        from gpu_lock import gpu_lock
        t_start = time.time()
        with gpu_lock(owner):
            r = subprocess.run([str(RUNNER), str(work / 'job.txt')], capture_output=True, text=True, env=env)
        elapsed = time.time() - t_start
        if r.returncode not in (0,):
            raise RuntimeError(f'runner exit {r.returncode}\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}')
        swapped = None
        for line in r.stdout.splitlines():
            if line.startswith('dispatches='):
                swapped = int(line.split('swapped=')[1].split()[0])
        if v['patches'] and not swapped:
            raise RuntimeError('patch requested but no PSO was swapped (sha mismatch?)')
        rd = lambda n: np.fromfile(work / n, np.float16).reshape(len(frames), c.H, c.W, 4)[..., :3]
        raw = np.stack([rd('diff_out.bin'), rd('spec_out.bin')])
        np.save(npy, raw)
        meta = dict(capture=c.uuid, frames=[frames[0], frames[-1], len(frames)], variant=v, label=V.label(variant),
                    tuning0=t0, per_frame=per is not None, swapped=swapped, seconds=round(elapsed, 2),
                    created=time.strftime('%Y-%m-%d %H:%M:%S'))
        if output_scale is not None:
            meta['output_scale'] = output_scale.tolist()
        meta_path.write_text(json.dumps(meta, indent=1))
        if verbose:
            print(f'[rrlab] {c.id} {V.label(variant)}: {len(frames)} frames in {elapsed:.1f}s (key {key})', flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # Pin the just-written result before trimming; it must survive other live readers.
    raw = np.load(npy, mmap_mode='r')
    _trim_cache()
    return Result(c, frames, v, raw, meta)


def production(capture, frames=None, which='selected'):
    """What the game itself showed: selected_rr_* (post-bridge output) or raw_rr_* (RR output before NZR etc.)."""
    c = capture if isinstance(capture, Capture) else Capture(capture)
    frames = list(range(c.n)) if frames is None else frames
    kind = 'rr' if which == 'selected' else 'raw'
    return np.stack([c.rgb(t, kind) for t in frames])
