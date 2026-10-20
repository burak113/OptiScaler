"""RR Lab variants: what is changed relative to the production bridge, as a JSON-able dict.

Shorthand (join with '+', e.g. 'd16+adaptive', 'd16+s0.85+patch:finalize_fmin'):
  base | native        production bridge: diffuse and specular fed to RR at x256, fork tuning from the capture
  d<N> / sp<N>         diffuse / specular input radiance scale (output divided back), e.g. d16, sp64
  s<V> | stab<V>       fixed stability bias (key 2)
  adaptive[(lo,hi,step,deg)]  stability lo while camera rotation > deg/frame, then +step per still frame up to hi
                       (default 0.5, 0.85, 0.035, 0.1 = the 2026-10-19 candidate)
  <key>=<v>            tuning key override: normal stability maxrad clipk relax disocc (keys 1..6)
  chris                Chris's fork defaults: maxrad 65500, relax 0, disocc 0.01
  patch:<name>         PSO swap: every <sha256>.dxil in patches/<name>/ replaces that RR shader
  rep<N>               identical RR work under a new cache key (run-to-run noise floor: base vs base+rep2)
  hook:<file.py>       Python hooks (any of prefilter/motion/controls/tuning, see README); file content is hashed
A full JSON dict is accepted as well (same keys as parse() returns)."""
import hashlib
import json
import re
from pathlib import Path
from .paths import PATCHES, LAB

KEYS = ['normal', 'stability', 'maxrad', 'clipk', 'relax', 'disocc']
PRODUCTION_SCALE = 256.0


def empty():
    return dict(scale=dict(diffuse=PRODUCTION_SCALE, specular=PRODUCTION_SCALE), tuning={}, schedule=None,
                patches=[], hooks=[], rep=0)


def parse(spec):
    if isinstance(spec, dict):
        v = empty()
        v.update(spec)
        return v
    s = spec.strip()
    if s.startswith('{'):
        return parse(json.loads(s))
    v = empty()
    for tok in [t.strip() for t in s.split('+') if t.strip()]:
        low = tok.lower()
        if low in ('base', 'native'):
            continue
        if m := re.fullmatch(r'd(\d+(?:\.\d+)?)', low):
            v['scale']['diffuse'] = float(m.group(1))
        elif m := re.fullmatch(r'sp(\d+(?:\.\d+)?)', low):
            v['scale']['specular'] = float(m.group(1))
        elif m := re.fullmatch(r'(?:s|stab)(\d*\.\d+|\d+)', low):
            v['tuning']['stability'] = float(m.group(1))
        elif m := re.fullmatch(r'adaptive(?:\(([^)]*)\))?', low):
            a = [float(x) for x in m.group(1).split(',')] if m.group(1) else []
            lo, hi, step, deg = (a + [0.5, 0.85, 0.035, 0.1][len(a):])[:4]
            v['schedule'] = dict(type='adaptive', lo=lo, hi=hi, step=step, deg=deg)
        elif m := re.fullmatch(r'rep(\d+)', low):
            v['rep'] = int(m.group(1))
        elif low == 'chris':
            v['tuning'].update(maxrad=65500.0, relax=0.0, disocc=0.01)
        elif m := re.fullmatch(r'([a-z]+)=([-+0-9.e]+)', low):
            if m.group(1) not in KEYS:
                raise ValueError(f'unknown tuning key {m.group(1)!r}; use one of {KEYS}')
            v['tuning'][m.group(1)] = float(m.group(2))
        elif low.startswith('patch:'):
            name = tok[6:]
            if not list((PATCHES / name).glob('*.dxil')):
                raise ValueError(f'patches/{name}/ holds no <sha256>.dxil')
            v['patches'].append(name)
        elif low.startswith('hook:'):
            p = Path(tok[5:])
            if not p.is_absolute():
                p = (LAB / 'hooks' / p) if (LAB / 'hooks' / p).exists() else p.resolve()
            if not p.exists():
                raise ValueError(f'hook file {p} not found')
            v['hooks'].append(str(p).replace('\\', '/'))
        else:
            raise ValueError(f'unknown variant token {tok!r}')
    return v


def label(spec):
    return spec if isinstance(spec, str) else json.dumps(spec, sort_keys=True)


def fingerprint(v):
    """Content hash of everything that changes the RR result (patch bytes and hook sources included)."""
    h = hashlib.sha256(json.dumps({k: v.get(k) for k in ('scale', 'tuning', 'schedule', 'rep')}, sort_keys=True).encode())
    for name in sorted(v['patches']):
        for f in sorted((PATCHES / name).glob('*.dxil')):
            h.update(f.name.encode() + hashlib.sha256(f.read_bytes()).digest())
    for p in v['hooks']:
        h.update(hashlib.sha256(Path(p).read_bytes()).digest())
    return h.hexdigest()[:20]


def tuning_values(v, base):
    """Six key values for frame 0 (base = capture's requested values)."""
    t = list(base)
    for k, val in v['tuning'].items():
        t[KEYS.index(k)] = float(val)
    return t


def per_frame_tuning(v, base_values, rot):
    """[N, 6] float32 tuning per frame, or None when nothing changes per frame."""
    import numpy as np
    sch = v.get('schedule')
    if not sch:
        return None
    t = np.tile(np.array(base_values, np.float32), (len(rot), 1))
    if sch['type'] == 'adaptive':
        cur = sch['lo']
        for i, r in enumerate(rot):
            cur = sch['lo'] if r > sch['deg'] else min(sch['hi'], cur + sch['step'])
            t[i, 1] = cur
    elif sch['type'] == 'list':  # explicit per-frame stability list (fixtures, hooks)
        for i, s in enumerate(sch['values'][:len(rot)]):
            t[i, 1] = s
    else:
        raise ValueError(f"unknown schedule {sch['type']}")
    return t
