"""Input colour noise filter: production InputConv DXIL on synthetic coloured lighting.

Checks that an isolated coloured sample takes its same-surface neighbourhood's light colour and keeps
its luminance, that every sample keeps its luminance, that colour does not cross a depth edge, that
near-mirror surfaces are left alone, that the flag changes nothing on uniformly lit content, and that
the flag off stores bit-identical outputs to the pre-change DXIL.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

OUTPUT = Path(os.environ.get('FSRD_CHROMA_TEST_OUTPUT', Path(tempfile.gettempdir()) / 'fsrd_input_chroma'))
os.environ.setdefault('FSRD_GPU_TEST_OUTPUT', str(OUTPUT / 'gpu'))
import numpy as np
import fsrd_alpha_common as a
import run_fsrd_gpu_tests as t

W = H = 64
CHROMA = 0x80000000
LUMA = np.array([.2126, .7152, .0722], np.float32)
failures = []


def check(name, ok, **detail):
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else ' ' + repr(detail)), flush=True)
    if not ok:
        failures.append(name)


albedo = a.rgba(np.full((H, W, 3), .4, np.float32))


def run(raw, flags_extra=0, depth=None, roughness=None, directory=t.PRE):
    flags = a.conversion_cb(W, H)['Flags'] | flags_extra
    out = a.convert(raw.astype(np.float32), albedo, albedo, depth=depth, roughness=roughness,
                    directory=directory, overrides=dict(Flags=flags))
    return out


def residual(out):
    """What composition remodulates: both RR inputs times their stored albedos."""
    return out[0][..., :3] * out[4][..., :3] + out[1][..., :3] * out[5][..., :3]


def chroma(x):
    return x / np.maximum(x.sum(-1, keepdims=True), 1e-8)


def main():
    rng = np.random.default_rng(7)
    grey = np.full((H, W, 3), .5, np.float32)
    outliers = [(12, 12), (12, 44), (44, 12), (44, 44)]
    spotted = grey.copy()
    for y, x in outliers:
        spotted[y, x] = (3.0, .3, .3)
    with a.GPUWorker(OUTPUT / 'worker'):
        off = residual(run(spotted))
        on = residual(run(spotted, CHROMA))
        at = tuple(np.array(outliers).T)
        check('flag off keeps the red sample red', np.all(chroma(off[at])[:, 0] > .7))
        check('an isolated red sample takes the grey of its surface',
              np.allclose(chroma(on[at]), 1 / 3, atol=2e-3), chroma=chroma(on[at]).tolist())
        check('it keeps its luminance', np.allclose(on[at] @ LUMA, off[at] @ LUMA, rtol=2e-3))
        far = np.ones((H, W), bool)
        for y, x in outliers:
            far[y - 4:y + 5, x - 4:x + 5] = False
        check('samples beyond the window are unchanged', np.allclose(on[far], off[far], rtol=1e-3))
        # A sample next to the red one sums it into its reference: it turns slightly red (the
        # red energy is spread over the window, not removed).
        near = on[12, 13]
        check('a neighbour takes a share of the red energy', chroma(near)[0] > 1 / 3 + 1e-3, chroma=chroma(near).tolist())
        check('the window keeps the red energy within 5%',
              abs(on[8:17, 8:17, 0].sum() / off[8:17, 8:17, 0].sum() - 1) < .05,
              ratio=float(on[8:17, 8:17, 0].sum() / off[8:17, 8:17, 0].sum()))

        # Heavy-tailed one-sample lighting whose channels correlate as in the captures (about 0.85):
        # a common intensity times a per-sample colour.
        noise = (rng.gamma(.3, 1, (H, W, 1)) * rng.gamma(8, 1 / 8, (H, W, 3))).astype(np.float32)
        off = residual(run(noise))
        on = residual(run(noise, CHROMA))
        lum_off, lum_on = off @ LUMA, on @ LUMA
        check('every sample keeps its luminance (heavy-tailed coloured noise)',
              np.allclose(lum_on, lum_off, rtol=3e-3, atol=1e-5),
              worst=float(np.max(np.abs(lum_on - lum_off) / np.maximum(lum_off, 1e-5))))
        def spread(x):
            c = chroma(x)[(x @ LUMA) > 1e-3]
            return float(c.std(0).mean())
        check('colour noise is reduced', spread(on) < .5 * spread(off), off=spread(off), on=spread(on))
        check('the overall light colour is kept within 2%',
              np.allclose(chroma(on.reshape(-1, 3).sum(0)), chroma(off.reshape(-1, 3).sum(0)), atol=.02 / 3),
              off=chroma(off.reshape(-1, 3).sum(0)).tolist(), on=chroma(on.reshape(-1, 3).sum(0)).tolist())

        # Red-lit near surface on the left, blue-lit far surface on the right.
        split = np.where(np.arange(W)[None, :, None] < 32, (1., .2, .2), (.2, .2, 1.)) * np.ones((H, 1, 1))
        depth = np.where(np.arange(W)[None, :] < 32, 10., 30.).astype(np.float32) * np.ones((H, 1), np.float32)
        off = residual(run(split, depth=depth))
        on = residual(run(split, CHROMA, depth=depth))
        check('colour does not cross a depth edge', np.allclose(on, off, rtol=2e-3, atol=1e-6),
              worst=float(np.abs(on - off).max()))
        same = np.ones((H, W), np.float32) * 10
        on = residual(run(split, CHROMA, depth=same))
        check('without the depth edge the colours do mix', not np.allclose(on[:, 30:34], off[:, 30:34], rtol=2e-2))

        mirror = np.full((H, W), .1, np.float32)
        check('near-mirror surfaces are left alone',
              all(np.array_equal(x, y) for x, y in zip(run(noise, CHROMA, roughness=mirror),
                                                       run(noise, roughness=mirror))))
        check('uniformly lit content is unchanged', np.allclose(residual(run(grey, CHROMA)), residual(run(grey)),
                                                              rtol=1e-3))

        frozen = OUTPUT / 'frozen_base'
        frozen.mkdir(parents=True, exist_ok=True)
        base = '8b46ea6a498e139b75edda273e0340fde813c1f5'
        for path in subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', base, a.SHADER_PATH],
                                            cwd=t.ROOT, text=True).splitlines():
            if Path(path).suffix in ('.hlsl', '.hlsli', '.cso'):
                (frozen / Path(path).name).write_bytes(
                    subprocess.check_output(['git', 'show', f'{base}:{path}'], cwd=t.ROOT))
        for name, image in (('spotted', spotted), ('noise', noise)):
            new = run(image)
            old = run(image, directory=frozen)
            changed = [i for i, (x, y) in enumerate(zip(new, old)) if not np.array_equal(x, y, equal_nan=True)]
            check(f'flag off is bit-identical to 8b46ea6a DXIL ({name})', not changed, outputs=changed)
    print('input chroma: %d failures' % len(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
