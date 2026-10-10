"""Execute production conversion DXIL with the full-light Floor routing flag.

The disabled flag must preserve the frozen 8b46ea6a outputs, including Floor, while
the enabled flag leaves no Floor pedestal in Skip and sends the raw energy to RR.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

OUTPUT = Path(os.environ.get('FSRD_FLOOR_THROUGH_RR_TEST_OUTPUT',
                            Path(tempfile.gettempdir()) / 'fsrd_floor_through_rr'))
os.environ.setdefault('FSRD_GPU_TEST_OUTPUT', str(OUTPUT / 'gpu'))
import numpy as np
import fsrd_alpha_common as a
import run_fsrd_gpu_tests as t

W, H = 64, 48
FLOOR_THROUGH_RR = 1 << 0
BASE = '8b46ea6a498e139b75edda273e0340fde813c1f5'


def run(raw, floor, enabled, directory=t.PRE):
    albedo = a.rgba(np.full((H, W, 3), .4, np.float32))
    flags = a.conversion_cb(W, H, floor=True)['Flags'] | (FLOOR_THROUGH_RR if enabled else 0)
    return a.convert(raw, albedo, albedo, floor=floor, reference=floor,
                     directory=directory, overrides=dict(Flags=flags),
                     output_formats=a.CONV_FORMATS + [10, 10])


def residual(out):
    return out[0][..., :3] * out[4][..., :3] + out[1][..., :3] * out[5][..., :3]


def main():
    rng = np.random.default_rng(71)
    ramp = np.linspace(.5, 1.5, W, dtype=np.float32)[None, :, None]
    raw = np.broadcast_to(ramp * np.array([1., .75, 1.25], np.float32), (H, W, 3)).copy()
    noisy = (raw * rng.uniform(.8, 1.2, (H, W, 3))).astype(np.float32)
    floor = a.rgba(np.full((H, W, 3), .2, np.float32), .01)
    frozen = OUTPUT / 'frozen_base'
    frozen.mkdir(parents=True, exist_ok=True)
    for path in subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', BASE, a.SHADER_PATH],
                                       cwd=t.ROOT, text=True).splitlines():
        if Path(path).suffix in ('.hlsl', '.hlsli', '.cso'):
            (frozen / Path(path).name).write_bytes(
                subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=t.ROOT))

    with a.GPUWorker(OUTPUT / 'worker'):
        for name, image in (('gradient', raw), ('noisy lighting', noisy)):
            off = run(image, floor, False)
            on = run(image, floor, True)
            old = run(image, floor, False, frozen)
            albedo = a.rgba(np.full((H, W, 3), .4, np.float32))
            no_floor = a.convert(image, albedo, albedo)
            changed = [i for i, (x, y) in enumerate(zip(off, old))
                       if not np.array_equal(x, y, equal_nan=True)]
            t.check(f'flag off is bit-identical to 8b46ea6a DXIL ({name})', not changed, outputs=changed)
            t.check(f'old routing has a Floor pedestal ({name})', np.all(off[6][..., :3] > .1))
            # Skip may retain FP16 demodulation closure, but no Floor share:
            # it must exactly match conversion with no Floor at all.
            t.check(f'Floor contributes no Skip energy ({name})', np.array_equal(on[6], no_floor[6]),
                    maximum_difference=float(np.max(np.abs(on[6] - no_floor[6]))))
            packed_raw = image.astype(np.float16).astype(np.float32)
            restored = residual(on)
            t.check(f'remodulated RR input equals raw within FP16 ({name})',
                    np.allclose(restored, packed_raw, rtol=2e-3, atol=5e-4),
                    maximum=float(np.max(np.abs(restored - packed_raw))))
            t.check(f'Floor detail reference is preserved ({name})', np.array_equal(on[7], off[7]))
            t.check(f'no NaN or Inf ({name})', all(np.all(np.isfinite(x)) for x in on))
        # Routing a pedestal must not depend on its size or colour.
        other_floor = a.rgba(np.full((H, W, 3), (.03, .25, .4), np.float32), .01)
        left, right = run(raw, floor, True), run(raw, other_floor, True)
        t.check('RR full-light energy is independent of the Floor pedestal',
                np.array_equal(residual(left), residual(right)))
    failures = sum(not row['passed'] for row in t.checks)
    a.save_json(t.OUT / 'results.json', dict(checks=t.checks, dispatches=t.timings,
                                           frozen_commit=BASE, failures=failures))
    print(f'floor through RR: {failures} failures', flush=True)
    return int(failures != 0)


if __name__ == '__main__':
    sys.exit(main())
