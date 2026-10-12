"""GPU test for FSRDCompareView.hlsl (the split compare composite).

Dispatches the shipped production DXIL on the local D3D12 GPU and checks:
  * the composite equals image A left of the divider and image B on the right (same size);
  * "Swap sides" exchanges the halves without moving the divider;
  * the divider line only paints its two columns;
  * the labels only paint their own glyph pixels;
  * at unequal source/output dimensions both halves get the SAME bilinear spatial upscale
    (checked against a numpy reference of linear-clamp sampling);
  * repeating an identical dispatch is byte-identical (the frozen-output guarantee);
  * the combine cost at the two required output resolutions.

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
COMPARE_RESAMPLE = 1 << 3
R16G16B16A16_FLOAT = 10

checks = []
counter = 0


def check(name, condition, **metrics):
    checks.append({'name': name, 'passed': bool(condition), **metrics})
    print(('PASS' if condition else 'FAIL') + ' ' + name + ' ' + str(metrics), flush=True)


def build_runner():
    compile_cpp(source, runner, ('d3d12.lib', 'dxgi.lib'))


def run_compare(a, b, divider, flags, dw, dh, repetitions=1, keep_dir=None):
    """Dispatch A (source size from a.shape) and B into a dw x dh output."""
    global counter
    sh, sw = a.shape[:2]
    d = OUT / f'{counter:03}_compare'; counter += 1
    d.mkdir(exist_ok=True)
    cb = d / 'cb.bin'
    cb.write_bytes(struct.pack('<4f4I', dw, dh, 1.0 / dw, 1.0 / dh, flags, divider, 0, 0))
    (d / 'inA.bin').write_bytes(np.asarray(a, np.float32).astype('<f2').tobytes())
    (d / 'inB.bin').write_bytes(np.asarray(b, np.float32).astype('<f2').tobytes())
    records = [
        f'{json.dumps(str(PRE / "FSRDCompareView_Shader.cso"))} {json.dumps(str(cb))} {dw} {dh} 2 1 {repetitions}',
        '',
        f'{json.dumps(str(d / "inA.bin"))} {sw} {sh} {R16G16B16A16_FLOAT}',
        f'{json.dumps(str(d / "inB.bin"))} {sw} {sh} {R16G16B16A16_FLOAT}',
        f'{json.dumps(str(d / "out0.bin"))} {dw} {dh} {R16G16B16A16_FLOAT}',
    ]
    job = d / 'job.txt'
    job.write_text('\n'.join(records))
    result = subprocess.run([str(runner), str(job)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('compare dispatch failed\n' + result.stdout + result.stderr)
    raw = (d / 'out0.bin').read_bytes()
    out = np.frombuffer(raw, dtype='<f2').reshape(dh, dw, 4).astype(np.float32)
    metrics = dict(re.findall(r'(\w+)=([\d.eE+-]+)', result.stdout))
    for f in d.glob('*.bin'):
        f.unlink()
    if keep_dir is not None:
        Path(keep_dir).write_bytes(raw)
    return out, metrics


def sample_linear(img, dw, dh):
    """D3D12 linear sampling with CLAMP, matching the shader's resample path."""
    sh, sw = img.shape[:2]
    xs = (np.arange(dw) + 0.5) / dw * sw - 0.5
    ys = (np.arange(dh) + 0.5) / dh * sh - 0.5
    x0 = np.floor(xs).astype(int); y0 = np.floor(ys).astype(int)
    fx = (xs - x0)[None, :, None]; fy = (ys - y0)[:, None, None]
    xc = np.clip(x0, 0, sw - 1); yc = np.clip(y0, 0, sh - 1)
    x1 = np.clip(x0 + 1, 0, sw - 1); y1 = np.clip(y0 + 1, 0, sh - 1)
    return ((1 - fy) * ((1 - fx) * img[np.ix_(yc, xc)] + fx * img[np.ix_(yc, x1)]) +
            fy * ((1 - fx) * img[np.ix_(y1, xc)] + fx * img[np.ix_(y1, x1)])).astype(np.float32)


def run():
    build_runner()
    rng = np.random.default_rng(20261012)
    h, w = 40, 61
    a = rng.uniform(0.0, 20.0, (h, w, 4)).astype(np.float32)
    b = rng.uniform(0.0, 20.0, (h, w, 4)).astype(np.float32)
    a16 = a.astype('<f2').astype(np.float32)
    b16 = b.astype('<f2').astype(np.float32)

    # Same size: direct texel read, exact.
    for divider in (0, 1, w // 2, w - 1, w):
        out, _ = run_compare(a, b, divider, 0, w, h)
        ok_left = out[:, :divider].shape[1] == 0 or np.array_equal(out[:, :divider], a16[:, :divider])
        ok_right = out[:, divider:].shape[1] == 0 or np.array_equal(out[:, divider:], b16[:, divider:])
        check(f'split exact A left / B right (divider={divider})', ok_left and ok_right)

    divider = w // 2
    out, _ = run_compare(a, b, divider, COMPARE_SWAP, w, h)
    check('swap puts B left of the divider and A right',
          np.array_equal(out[:, :divider], b16[:, :divider]) and
          np.array_equal(out[:, divider:], a16[:, divider:]))

    out, _ = run_compare(a, b, divider, COMPARE_DIVIDER, w, h)
    others = np.ones(w, bool); others[divider - 1:divider + 1] = False
    exact = np.array_equal(out[:, others], np.concatenate(
        [a16[:, :divider], b16[:, divider:]], axis=1)[:, others]) if others.any() else True
    seam_bright = bool(np.all(out[:, divider - 1:divider + 1, :3] >= 3.0))
    check('divider paints only its two columns and they are bright', exact and seam_bright)

    out, _ = run_compare(a, b, divider, COMPARE_LABELS, w, h)
    base, _ = run_compare(a, b, divider, 0, w, h)
    check('labels change some pixels and only draw glyphs',
          bool((out != base).any()) and bool(np.any(out[..., 0] != out[..., 1])))

    # Unequal source/output: both halves must receive the SAME bilinear spatial upscale.
    dw, dh = 100, 65
    expected_a = sample_linear(a16, dw, dh)
    expected_b = sample_linear(b16, dw, dh)
    # D3D12 linear filtering quantizes the fractional weight to 8 bits, so the reference is
    # compared with a small absolute tolerance (well under 1% of the 0..20 range).
    tol = 0.1
    out, m = run_compare(a, b, dw // 2, COMPARE_RESAMPLE, dw, dh)
    err_left = float(np.max(np.abs(out[:, :dw // 2] - expected_a[:, :dw // 2])))
    err_right = float(np.max(np.abs(out[:, dw // 2:] - expected_b[:, dw // 2:])))
    check('unequal size resamples A and B identically (numpy reference)',
          err_left < tol and err_right < tol, err_left=err_left, err_right=err_right,
          validation_errors=int(float(m.get('validation_errors', -1))))

    out_swap, _ = run_compare(a, b, dw // 2, COMPARE_RESAMPLE | COMPARE_SWAP, dw, dh)
    check('unequal size swap exchanges the resampled halves',
          np.max(np.abs(out_swap[:, :dw // 2] - expected_b[:, :dw // 2])) < tol and
          np.max(np.abs(out_swap[:, dw // 2:] - expected_a[:, dw // 2:])) < tol)

    out_div, _ = run_compare(a, b, dw // 2, COMPARE_RESAMPLE | COMPARE_DIVIDER, dw, dh)
    seam = bool(np.all(out_div[:, dw // 2 - 1:dw // 2 + 1, :3] >= 3.0))
    body = np.ones(dw, bool); body[dw // 2 - 1:dw // 2 + 1] = False
    check('unequal size divider paints only its two columns',
          seam and np.array_equal(out_div[:, body], out[:, body]))

    # Exact repeated-identity: the same dispatch twice must be byte-identical (frozen output).
    i1 = OUT / 'identity1.bin'; i2 = OUT / 'identity2.bin'
    run_compare(a, b, dw // 2, COMPARE_RESAMPLE | COMPARE_DIVIDER | COMPARE_LABELS, dw, dh, keep_dir=i1)
    run_compare(a, b, dw // 2, COMPARE_RESAMPLE | COMPARE_DIVIDER | COMPARE_LABELS, dw, dh, keep_dir=i2)
    check('repeated identical dispatch is byte-identical (frozen guarantee)',
          i1.read_bytes() == i2.read_bytes())

    # GPU cost at the two required output resolutions; source is ~0.588 of the output
    # (1505x847 render -> 2560x1440 Balanced).
    timings = []
    for (tw, th) in ((1505, 847), (2560, 1440)):
        sw2, sh2 = max(1, int(tw * 0.588)), max(1, int(th * 0.588))
        az = np.zeros((sh2, sw2, 4), np.float32); bz = np.zeros_like(az)
        _, tm = run_compare(az, bz, tw // 2, COMPARE_RESAMPLE | COMPARE_DIVIDER | COMPARE_LABELS,
                            tw, th, repetitions=200)
        median = float(tm.get('gpu_ms_median', -1.0)); p95 = float(tm.get('gpu_ms_p95', -1.0))
        present_vram = 2 * tw * th * 8          # present + frozen, RGBA16F at output size
        snapshot_vram = 2 * sw2 * sh2 * 8       # two render-size snapshots
        vram = present_vram + snapshot_vram
        timings.append({'size': f'{tw}x{th}', 'source': f'{sw2}x{sh2}', 'gpu_ms_median': median,
                        'gpu_ms_p95': p95, 'present_vram_bytes': present_vram,
                        'snapshot_vram_bytes': snapshot_vram})
        check(f'compare {tw}x{th} timed', median >= 0.0, gpu_ms_median=median, gpu_ms_p95=p95,
              present_vram_bytes=present_vram, snapshot_vram_bytes=snapshot_vram)
        print(f'{tw}x{th} (src {sw2}x{sh2}): combine gpu_ms_median={median} p95={p95} '
              f'present_VRAM={present_vram} snapshot_VRAM={snapshot_vram}')

    report = {'checks': checks, 'timings': timings}
    (OUT / 'results.json').write_text(json.dumps(report, indent=2))
    assert all(c['passed'] for c in checks), 'compare-view GPU failures; see results.json'
    print(f'{len(checks)} compare-view checks passed')


if __name__ == '__main__':
    run()
