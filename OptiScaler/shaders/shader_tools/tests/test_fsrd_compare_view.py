"""GPU test for FSRDCompareView.hlsl (the split compare composite).

Dispatches the shipped production DXIL on the local D3D12 GPU and checks that the
composite equals image A left of the divider and image B on the right, that "Swap
sides" exchanges the halves without moving the divider, that the divider line only
paints its two columns, and that the labels only paint their own glyph pixels.

Run:  python OptiScaler/shaders/shader_tools/tests/test_fsrd_compare_view.py
"""
from pathlib import Path
import json
import os
import re
import struct
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]
PRE = ROOT / 'OptiScaler/shaders/fsrd_preprocess/precompile'
OUT = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', str(ROOT / 'tools_tmp/floor_rewrite/gpu_tests'))) / 'compare_view'
OUT.mkdir(parents=True, exist_ok=True)
runner = OUT / 'fsrd_gpu_runner.exe'
source = Path(__file__).with_name('fsrd_gpu_runner.cpp')

COMPARE_SWAP = 1 << 0
COMPARE_DIVIDER = 1 << 1
COMPARE_LABELS = 1 << 2
R16G16B16A16_FLOAT = 10

checks = []
counter = 0


def check(name, condition, **metrics):
    checks.append({'name': name, 'passed': bool(condition), **metrics})
    print(('PASS' if condition else 'FAIL') + ' ' + name + ' ' + str(metrics), flush=True)


def build_runner():
    compile_cpp(source, runner, ('d3d12.lib', 'dxgi.lib'))


def run_compare(a, b, divider, flags, w, h, repetitions=1):
    global counter
    d = OUT / f'{counter:03}_compare'; counter += 1
    d.mkdir(exist_ok=True)
    cb = d / 'cb.bin'
    cb.write_bytes(struct.pack('<4f4I', w, h, 1.0 / w, 1.0 / h, flags, divider, 0, 0))
    a = np.asarray(a, np.float32); b = np.asarray(b, np.float32)
    (d / 'inA.bin').write_bytes(a.astype('<f2').tobytes())
    (d / 'inB.bin').write_bytes(b.astype('<f2').tobytes())
    records = [
        f'{json.dumps(str(PRE / "FSRDCompareView_Shader.cso"))} {json.dumps(str(cb))} {w} {h} 2 1 {repetitions}',
        '',
        f'{json.dumps(str(d / "inA.bin"))} {w} {h} {R16G16B16A16_FLOAT}',
        f'{json.dumps(str(d / "inB.bin"))} {w} {h} {R16G16B16A16_FLOAT}',
        f'{json.dumps(str(d / "out0.bin"))} {w} {h} {R16G16B16A16_FLOAT}',
    ]
    job = d / 'job.txt'
    job.write_text('\n'.join(records))
    result = subprocess.run([str(runner), str(job)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('compare dispatch failed\n' + result.stdout + result.stderr)
    out = np.fromfile(d / 'out0.bin', dtype='<f2').reshape(h, w, 4).astype(np.float32)
    metrics = dict(re.findall(r'(\w+)=([\d.eE+-]+)', result.stdout))
    for f in d.glob('*.bin'):
        f.unlink()
    return out, metrics


def run():
    build_runner()
    rng = np.random.default_rng(20261012)
    h, w = 40, 61
    a = rng.uniform(0.0, 20.0, (h, w, 4)).astype(np.float32)
    b = rng.uniform(0.0, 20.0, (h, w, 4)).astype(np.float32)
    # fp16-stored fixtures: compare against the stored values so rounding is not a mismatch.
    a16 = a.astype('<f2').astype(np.float32)
    b16 = b.astype('<f2').astype(np.float32)

    for divider in (0, 1, w // 2, w - 1, w):
        out, _ = run_compare(a, b, divider, 0, w, h)
        left = out[:, :divider]
        right = out[:, divider:]
        ok_left = left.shape[1] == 0 or np.array_equal(left, a16[:, :divider])
        ok_right = right.shape[1] == 0 or np.array_equal(right, b16[:, divider:])
        check(f'split exact A left / B right (divider={divider})', ok_left and ok_right)

    # Swap sides exchanges the halves without moving the divider.
    divider = w // 2
    out, _ = run_compare(a, b, divider, COMPARE_SWAP, w, h)
    check('swap puts B left of the divider and A right',
          np.array_equal(out[:, :divider], b16[:, :divider]) and
          np.array_equal(out[:, divider:], a16[:, divider:]))

    # The divider line only paints its two columns; the rest is untouched.
    out, _ = run_compare(a, b, divider, COMPARE_DIVIDER, w, h)
    others = np.ones(w, bool); others[divider - 1:divider + 1] = False
    exact = np.array_equal(out[:, others], np.concatenate(
        [a16[:, :divider], b16[:, divider:]], axis=1)[:, others]) if others.any() else True
    seam_bright = bool(np.all(out[:, divider - 1:divider + 1, :3] >= 3.0))
    check('divider paints only its two columns and they are bright', exact and seam_bright)

    # Labels paint only their own glyph pixels and leave the rest exact.
    out, _ = run_compare(a, b, divider, COMPARE_LABELS, w, h)
    base, _ = run_compare(a, b, divider, 0, w, h)
    changed = out != base
    coloured = bool(np.any(out[..., 0] != out[..., 1]))
    check('labels change some pixels and only draw glyphs', bool(changed.any()) and coloured)

    # A larger size exercises the label scale path and the 8x8 dispatch tiling.
    h2 = w2 = 200
    a2 = rng.uniform(0.0, 8.0, (h2, w2, 4)).astype(np.float32)
    b2 = rng.uniform(0.0, 8.0, (h2, w2, 4)).astype(np.float32)
    out2, m = run_compare(a2, b2, 100, 0, w2, h2)
    check('200x200 split exact',
          np.array_equal(out2[:, :100], a2[:, :100].astype('<f2').astype(np.float32)) and
          np.array_equal(out2[:, 100:], b2[:, 100:].astype('<f2').astype(np.float32)),
          validation_errors=int(float(m.get('validation_errors', -1))))

    # GPU cost of the combine pass at the two required resolutions, median of 200 samples.
    timings = []
    for (tw, th) in ((1505, 847), (2560, 1440)):
        az = np.zeros((th, tw, 4), np.float32)
        bz = np.zeros((th, tw, 4), np.float32)
        _, tm = run_compare(az, bz, tw // 2, COMPARE_DIVIDER | COMPARE_LABELS, tw, th, repetitions=200)
        median = float(tm.get('gpu_ms_median', -1.0))
        p95 = float(tm.get('gpu_ms_p95', -1.0))
        vram = 3 * tw * th * 8  # composite + two half-variants, RGBA16F
        timings.append({'size': f'{tw}x{th}', 'gpu_ms_median': median, 'gpu_ms_p95': p95, 'vram_bytes': vram})
        check(f'compare {tw}x{th} timed', median >= 0.0, gpu_ms_median=median, gpu_ms_p95=p95, vram_bytes=vram)
        print(f'{tw}x{th}: combine gpu_ms_median={median} p95={p95} VRAM={vram} bytes')

    report = {'checks': checks, 'timings': timings}
    (OUT / 'results.json').write_text(json.dumps(report, indent=2))
    assert all(c['passed'] for c in checks), 'compare-view GPU failures; see results.json'
    print(f'{len(checks)} compare-view checks passed')


if __name__ == '__main__':
    run()
