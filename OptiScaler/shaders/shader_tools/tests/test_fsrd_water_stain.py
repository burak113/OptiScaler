"""Water stain fix (FSRDWaterVote + FSRDWaterApply) on the D3D12 runner against an independent NumPy mirror.

Synthetic frame: a large up-facing specular water region with a bright 'sea floor' oval in its guides, a 3-pixel
water-like band (must stay untouched), a flat (material 1) patch inside the water (untouched), a wall (normal not up),
a diffuse floor (low specular share) and sky (zero guides). Checks the block vote, the applied signals/guides/material
and that every pixel outside the gate is bit-identical.
"""
from pathlib import Path
import argparse
import json
import struct
import sys
import numpy as np
sys.dont_write_bytecode = True
import run_fsrd_gpu_tests as t
from fsrd_gpu_chain import compile_shader

L = np.array([.2126, .7152, .0722], np.float32)
SHARE, UP, VOTE, LOW, BLOCK = .6, .9, .75, .6, 16


def oct_encode(n):
    n = n / np.abs(n).sum(-1, keepdims=True)
    xy = n[..., :2].copy()
    neg = n[..., 2] < 0
    xy[neg] = (1 - np.abs(n[neg][:, [1, 0]])) * np.where(n[neg][:, :2] >= 0, 1, -1)
    return xy * .5 + .5


def oct_decode(uv):
    uv = 2 * uv - 1
    n = np.stack([uv[..., 0], uv[..., 1], 1 - np.abs(uv[..., 0]) - np.abs(uv[..., 1])], -1)
    tt = np.maximum(-n[..., 2], 0)
    n[..., 0] += np.where(n[..., 0] >= 0, -tt, tt); n[..., 1] += np.where(n[..., 1] >= 0, -tt, tt)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def pack_normals(normal, rough, material):
    uv = np.round(oct_encode(normal) * 1023).astype(np.uint32)
    r = np.round(rough * 1023).astype(np.uint32)
    return uv[..., 0] | (uv[..., 1] << 10) | (r << 20) | (np.asarray(material, np.uint32) << 30)


def fixture(w=70, h=50):
    y, x = np.mgrid[:h, :w]
    qs = np.zeros((h, w, 4), np.uint8); qd = np.zeros((h, w, 4), np.uint8)
    normal = np.zeros((h, w, 3), np.float32); normal[..., 2] = 1
    material = np.zeros((h, w), np.uint32)
    water = (x < 48) & (y < 34)
    oval = water & (((x - 22) / 12.) ** 2 + ((y - 16) / 8.) ** 2 < 1)
    qs[water, :3] = 27; qd[water, :3] = 3          # specular share 0.9
    qs[oval, :3] = 77; qd[oval, :3] = 9            # the sea floor's 3x step
    band = (x >= 52) & (x < 55) & (y < 40)          # 3-pixel water-like band
    qs[band, :3] = 60; qd[band, :3] = 6
    wall = (x >= 56) & (y < 34)
    qs[wall, :3] = 60; qd[wall, :3] = 6; normal[wall] = (1, 0, 0)
    floor = (y >= 34) & (x < 48)
    qs[floor, :3] = 10; qd[floor, :3] = 120         # diffuse floor, share 0.08
    flat = water & (x >= 34) & (x < 40) & (y >= 4) & (y < 10)
    material[flat] = 1
    sky = (y >= 40) & (x >= 48)                      # zero guides, nothing demodulated
    qs[..., 3] = 255; qd[..., 3] = 255
    packed = pack_normals(normal, np.full((h, w), .3, np.float32), material)
    packed[sky] = 0
    rng = np.random.default_rng(2026_10_13)
    U = np.zeros((h, w, 4), np.float16); V = np.zeros((h, w, 4), np.float16)
    U[..., :3] = rng.uniform(.05, 4, (h, w, 3)); V[..., :3] = rng.uniform(.05, 4, (h, w, 3))
    U[..., 3] = 1800; V[..., 3] = -1
    U[sky, :3] = 0; V[sky, :3] = 0
    skip = np.zeros((h, w, 4), np.float16); skip[..., 3] = .1
    return dict(qs=qs, qd=qd, packed=packed, U=U, V=V, skip=skip, w=w, h=h)


def mirror(fx):
    w, h = fx['w'], fx['h']
    qs = fx['qs'][..., :3].astype(np.float32) / 255; qd = fx['qd'][..., :3].astype(np.float32) / 255
    packed = fx['packed']
    uv = np.stack([(packed & 1023) / 1023., ((packed >> 10) & 1023) / 1023.], -1).astype(np.float32)
    material = (packed >> 30).astype(np.float32) / 3
    s, d = qs @ L, qd @ L
    like = (material <= 1 / 6) & (fx['skip'][..., 3] != -1) & (s + d > 1e-3) & (s > SHARE * (s + d)) & (oct_decode(uv)[..., 2] > UP)
    hb, wb = (h + BLOCK - 1) // BLOCK, (w + BLOCK - 1) // BLOCK
    vote = np.zeros((hb, wb), np.float32)
    for by in range(hb):
        for bx in range(wb):
            blk = like[by * BLOCK:(by + 1) * BLOCK, bx * BLOCK:(bx + 1) * BLOCK]
            vote[by, bx] = blk.mean() if blk.size else 0
    vote8 = np.round(vote * 255).astype(np.uint8)
    v = vote8.astype(np.float32) / 255
    gate = np.zeros((h, w), bool)
    for yy in range(h):
        for xx in range(w):
            u = np.clip((np.array([xx, yy], np.float32) - .5 * (BLOCK - 1)) / BLOCK, 0, [wb - 1, hb - 1])
            b0 = np.floor(u).astype(int); b1 = np.minimum(b0 + 1, [wb - 1, hb - 1]); f = u - b0
            top = v[b0[1], b0[0]] * (1 - f[0]) + v[b0[1], b1[0]] * f[0]
            bottom = v[b1[1], b0[0]] * (1 - f[0]) + v[b1[1], b1[0]] * f[0]
            vv = top * (1 - f[1]) + bottom * f[1]
            gate[yy, xx] = vv > VOTE or (vv > LOW and like[yy, xx])
    gate &= (material <= 1 / 6) & ((qs + qd).sum(-1) > 0)
    return vote8, gate, like


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    shaders = {n: output / (n + '.cso') for n in ('FSRDWaterVote', 'FSRDWaterApply')}
    for n, p in shaders.items():
        compile_shader(t.PRE / (n + '.hlsl'), p)
    fx = fixture(); w, h = fx['w'], fx['h']
    vote8, gate, like = mirror(fx)
    cb = struct.pack('<4f4f', w, h, 1 / w, 1 / h, SHARE, UP, VOTE, LOW)
    job = t.create_chain(output / 'job')
    job.texture('qs', fx['qs'], format=28, writable=True, readback=True)
    job.texture('qd', fx['qd'], format=28, writable=True, readback=True)
    job.texture('normals', fx['packed'], format=24, writable=True, readback=True)
    job.texture('skip', fx['skip'], format=10)
    job.texture('U', fx['U'], format=10, writable=True, readback=True)
    job.texture('V', fx['V'], format=10, writable=True, readback=True)
    hb, wb = (h + BLOCK - 1) // BLOCK, (w + BLOCK - 1) // BLOCK
    job.texture('vote', None, format=61, size=(wb, hb), writable=True, readback=True)
    job.texture('like', None, format=61, size=(w, h), writable=True, readback=True)
    job.compute('Vote', shaders['FSRDWaterVote'], cb, ['qs', 'qd', 'normals', 'skip'], ['vote', 'like'], groups=(wb, hb, 1))
    job.compute('Apply', shaders['FSRDWaterApply'], cb, ['vote', 'like'], ['qs', 'qd', 'U', 'V', 'normals'],
                groups=((w + 7) // 8, (h + 7) // 8, 1))
    out, meta = job.run()
    checks = []
    add = lambda name, ok, **kw: checks.append(dict(test=name, passed=bool(ok), **kw))
    add('vote equals mirror (UNORM8)', np.array_equal(out['vote'], vote8), gpu=out['vote'].tolist(), mirror=vote8.tolist())
    add('per-pixel water-like mask equals mirror', np.array_equal(out['like'].reshape(h, w) > 127, like))
    add('gate covers the water region incl. the floor oval', gate[(np.mgrid[:h, :w][1] < 32) & (np.mgrid[:h, :w][0] < 24)].mean() > .99,
        fraction=float(gate[:24, :32].mean()))
    add('3-pixel band, wall, diffuse floor, flat patch and sky untouched', not gate[:, 52:].any() and not gate[34:].any()
        and not gate[4:10, 34:40].any())
    qs_out = out['qs'].reshape(h, w, 4); qd_out = out['qd'].reshape(h, w, 4)
    U_out = out['U'].reshape(h, w, 4); V_out = out['V'].reshape(h, w, 4); n_out = out['normals'].reshape(h, w)
    keep = ~gate
    add('outside the gate bit-identical', np.array_equal(qs_out[keep], fx['qs'][keep]) and np.array_equal(qd_out[keep], fx['qd'][keep])
        and np.array_equal(U_out[keep], fx['U'][keep]) and np.array_equal(V_out[keep], fx['V'][keep])
        and np.array_equal(n_out[keep], fx['packed'][keep]))
    add('gated guides are 1 (alpha kept)', np.all(qs_out[gate][:, :3] == 255) and np.all(qd_out[gate][:, :3] == 255)
        and np.array_equal(qs_out[gate][:, 3], fx['qs'][gate][:, 3]))
    add('gated material type 2, normal and roughness kept', np.all((n_out[gate] >> 30) == 2)
        and np.array_equal(n_out[gate] & 0x3FFFFFFF, fx['packed'][gate] & 0x3FFFFFFF))
    qsf = fx['qs'][..., :3].astype(np.float32) / 255; qdf = fx['qd'][..., :3].astype(np.float32) / 255
    eu = (fx['U'][..., :3].astype(np.float32) * qsf)[gate]; ev = (fx['V'][..., :3].astype(np.float32) * qdf)[gate]
    gu = U_out[gate][:, :3].astype(np.float32); gv = V_out[gate][:, :3].astype(np.float32)
    err = float(max(np.max(np.abs(gu - eu) / np.maximum(eu, 1e-6)), np.max(np.abs(gv - ev) / np.maximum(ev, 1e-6))))
    add('gated signals are unmodulated (relative error <= 1e-3, FP16 store)', err <= 1e-3, value=err)
    add('remodulated radiance preserved: U*Qs before == U*1 after', err <= 1e-3)
    add('hit distance alpha kept', np.array_equal(U_out[..., 3], fx['U'][..., 3]) and np.array_equal(V_out[..., 3], fx['V'][..., 3]))
    add('zero D3D12 validation errors and warnings', meta['counters'].get('validation_errors') == 0 and meta['counters'].get('validation_warnings') == 0)
    result = dict(passed=all(c['passed'] for c in checks), checks=checks, gated=int(gate.sum()))
    (output / 'results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    for c in checks:
        print(('PASS ' if c['passed'] else 'FAIL ') + c['test'], flush=True)
    print(json.dumps(dict(passed=result['passed'], checks=len(checks), gated=result['gated'])), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=t.OUT / 'water_stain')
    p.add_argument('--runner', type=Path)
    a = p.parse_args()
    if a.runner: t.runner = a.runner
    else: t.build_runner()
    raise SystemExit(run(a.output))
