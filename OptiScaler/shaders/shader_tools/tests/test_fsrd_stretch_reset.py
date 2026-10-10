"""Magnified-history reset: production InputConv DXIL on synthetic motion fields.

Checks that motion Z is pushed past RR's disocclusion test exactly where the frame magnifies
the previous one below the selected stretch, that a motion jump at a depth edge is not read
as stretch, that the debug view marks the same pixels, and that level 0 stores bit-identical
outputs to the pre-change DXIL.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

OUTPUT = Path(os.environ.get('FSRD_STRETCH_TEST_OUTPUT', Path(tempfile.gettempdir()) / 'fsrd_stretch_reset'))
os.environ.setdefault('FSRD_GPU_TEST_OUTPUT', str(OUTPUT / 'gpu'))
import numpy as np
import fsrd_alpha_common as a
import run_fsrd_gpu_tests as t

W = H = 64
DEPTH = 10.0
BASE_FLAGS = a.conversion_cb(W, H)['Flags']
LEVEL1 = 1 << 29
DEBUG_STRETCH = (43 << 17) | (1 << 16)
failures = []


def check(name, ok, **detail):
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else ' ' + repr(detail)), flush=True)
    if not ok:
        failures.append(name)


def motion_field(mv_px_x, mv_px_y):
    m = np.zeros((H, W, 4), np.float32)
    m[..., 0] = mv_px_x / W
    m[..., 1] = mv_px_y / H
    return m


def run(motion, depth, flags, directory=t.PRE):
    raw = np.full((H, W, 3), .5, np.float32)
    alb = a.rgba(np.full((H, W, 3), .5, np.float32))
    out = a.convert(raw, alb, alb, depth=depth, motion=motion, directory=directory,
                    overrides=dict(Flags=flags))
    return out


def bands():
    """Rows 0-15 stretch 1, 16-31 0.5, 32-47 0.7, 48-63 0.8 (continuous motion, slope per band)."""
    slope = np.select([np.arange(H) < 16, np.arange(H) < 32, np.arange(H) < 48], [0, -.5, -.3], -.2)
    mv_y = np.concatenate([[0], np.cumsum(slope[:-1])]).astype(np.float32)
    stretch = 1 + slope
    interior = np.ones(H, bool)
    for edge in (16, 32, 48):
        interior[edge - 1:edge + 1] = False
    return motion_field(np.zeros((H, W)), np.repeat(mv_y[:, None], W, 1)), stretch, interior


def main():
    depth = np.full((H, W), DEPTH, np.float32)
    motion, stretch, interior = bands()
    with a.GPUWorker(OUTPUT / 'worker'):
        z_off = run(motion, depth, BASE_FLAGS)[2][..., 2]
        check('level 0 leaves motion Z alone', np.all(z_off == 0), max=float(np.abs(z_off).max()))
        for level, threshold in ((1, .6), (2, .75), (3, .85)):
            z = run(motion, depth, BASE_FLAGS | level * LEVEL1)[2][..., 2]
            expected = np.repeat((stretch < threshold)[:, None], W, 1)
            reset = z > .5 * DEPTH * .99
            rows = interior[:, None] & np.ones((1, W), bool)
            check(f'level {level} resets exactly the bands below {threshold}',
                  np.array_equal(reset[rows], expected[rows]),
                  wrong=int(np.count_nonzero(reset[rows] != expected[rows])))
            check(f'level {level} offset is half the view depth',
                  np.allclose(z[reset], .5 * DEPTH, rtol=1e-3) and np.all(z[~reset] == 0))
            debug = run(motion, depth, BASE_FLAGS | level * LEVEL1 | DEBUG_STRETCH)[0][..., :3]
            white = np.all(debug == 1, -1)
            check(f'level {level} debug view marks the reset pixels',
                  np.array_equal(white[rows], expected[rows]))
            # Stretch 0.7 and 0.8 sit at or below the filter's full-gate point (0.8).
            magenta_rows = interior & (stretch < .85) & (stretch >= threshold)
            magenta_rows[-1] = False  # image edge: one-sided slope, FP16 motion rounding moves it off 0.8
            # The 0.8 band sits on the full-gate point; motion rounding leaves its gate near 0.99.
            magenta = np.all(np.abs(debug - np.array([1, 0, 1])) < 2e-2, -1)
            check(f'level {level} debug view marks the filter region in magenta',
                  bool(np.all(magenta[magenta_rows])) and not np.any(magenta[interior & (stretch > .95)]))

        # A horizontal motion jump of -0.8 px between columns 31 and 32: on one surface the
        # central differences there read stretch 0.6; across a depth edge they must not.
        mv_x = np.where(np.arange(W) < 32, 0, -.8).astype(np.float32)
        jump = motion_field(np.repeat(mv_x[None], H, 0), np.zeros((H, W)))
        z_same = run(jump, depth, BASE_FLAGS | 3 * LEVEL1)[2][..., 2]
        check('same-surface jump reads as stretch', np.all(z_same[:, 31:33] > 0) and np.all(z_same[:, :30] == 0))
        step = depth.copy()
        step[:, 32:] = 3 * DEPTH
        z_edge = run(jump, step, BASE_FLAGS | 3 * LEVEL1)[2][..., 2]
        check('depth edge is not read as stretch', np.all(z_edge == 0), reset=int(np.count_nonzero(z_edge)))

        # Geometric disocclusion check. Identity camera: a still scene where the title's motion
        # agrees with the camera-only reprojection. Last frame's depth carries a band of rows 20-39
        # that was closer (an occluder) by 5%, or by 2% (below the 3% test).
        disocclusion = 1 << 10
        still = np.zeros((H, W, 4), np.float32)
        def with_previous(previous, motion_field=still, flags=BASE_FLAGS | disocclusion):
            raw = np.full((H, W, 3), .5, np.float32)
            alb = a.rgba(np.full((H, W, 3), .5, np.float32))
            return a.convert(raw, alb, alb, depth=depth, motion=motion_field, overrides=dict(Flags=flags),
                             resources={17: a.rgba(np.zeros((H, W, 3), np.float32)), 18: previous})
        band = np.zeros((H, W), bool); band[20:40] = True
        closer5 = np.where(band, DEPTH * .95, DEPTH).astype(np.float32)
        closer2 = np.where(band, DEPTH * .98, DEPTH).astype(np.float32)
        expected = np.zeros((H, W), bool); expected[20:39, :W - 1] = True   # 2x2 footprint, image edge excluded
        z = with_previous(depth)[2][..., 2]
        check('disocclusion: unchanged depth resets nothing', np.all(z == 0))
        z = with_previous(closer5)[2][..., 2]
        check('disocclusion: revealed band (5% closer last frame) restarts exactly',
              np.array_equal(z > .5 * DEPTH * .99, expected), wrong=int(np.count_nonzero((z > .5 * DEPTH * .99) != expected)))
        check('disocclusion: offset is half the view depth', np.allclose(z[expected], .5 * DEPTH, rtol=1e-3))
        z = with_previous(closer2)[2][..., 2]
        check('disocclusion: 2% mismatch stays below the 3% test', np.all(z == 0))
        z = with_previous(closer5, flags=BASE_FLAGS)[2][..., 2]
        check('disocclusion: flag off resets nothing', np.all(z == 0))
        moving = still.copy(); moving[..., 0] = 2.0 / W     # title motion 2 px, camera still: a moving object
        z = with_previous(closer5, moving)[2][..., 2]
        check('disocclusion: motion that disagrees with the camera is left to RR', np.all(z == 0))
        debug = with_previous(closer5, flags=BASE_FLAGS | disocclusion | DEBUG_STRETCH)[0][..., :3]
        cyan = np.all(debug == np.array([0, 1, 1]), -1)
        check('disocclusion: debug view marks the restarted pixels in cyan', np.array_equal(cyan, expected))

        # Level 0 must store exactly what the pre-change shader stored.
        frozen = OUTPUT / 'frozen_base'
        frozen.mkdir(parents=True, exist_ok=True)
        base = '8b46ea6a498e139b75edda273e0340fde813c1f5'
        for path in subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', base, a.SHADER_PATH],
                                            cwd=t.ROOT, text=True).splitlines():
            if Path(path).suffix in ('.hlsl', '.hlsli', '.cso'):
                (frozen / Path(path).name).write_bytes(
                    subprocess.check_output(['git', 'show', f'{base}:{path}'], cwd=t.ROOT))
        for name, m, d in (('bands', motion, depth), ('jump', jump, step)):
            new = run(m, d, BASE_FLAGS)
            old = run(m, d, BASE_FLAGS, directory=frozen)
            changed = [i for i, (x, y) in enumerate(zip(new, old)) if not np.array_equal(x, y, equal_nan=True)]
            check(f'level 0 is bit-identical to 8b46ea6a DXIL ({name})', not changed, outputs=changed)
    print('stretch reset: %d failures' % len(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
