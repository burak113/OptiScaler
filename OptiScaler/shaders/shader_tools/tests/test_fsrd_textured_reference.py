"""Multitone animated texture recovery; independent known clean signal + noise.

Unlike a flat binary glyph, every local patch has nonzero curvature/contrast.
The stale/blurred RR input must not veto current-frame colour detail.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur


def run():
    t.OUT = t.OUT.parent / 'textured_reference'
    t.OUT.mkdir(parents=True, exist_ok=True)
    t.build_runner()
    w, h = 97, 73
    y, x = np.indices((h, w), dtype=np.float32)
    clean = t.rgba(w, h, (0, 0, 0))
    for channel, phase in enumerate((0, 1.3, 2.7)):
        clean[..., channel] = (.45 + .16*np.sin(x*.43 + y*.17 + phase)
                              + .12*np.cos(y*.57-x*.11+phase)
                              + .06*np.sin(x*.91+y*.71+phase))
    # Fine moving text over a multitone texture: an independent 5x7 bitmap mask.
    glyphs = ('11111100001000011110100001000010000',
              '01110100011000110001100011000101110')
    ink = np.zeros((h, w), bool)
    for row in (19, 40):
        for col in range(12, 82, 8):
            bits = np.array(list(glyphs[(col//8) % 2])) == '1'
            ink[row:row+7, col:col+5] = bits.reshape(7, 5)
    clean[ink, :3] = [.06, .09, .12]
    z = np.full((h, w), 10, np.float32)
    normal = t.rgba(w, h, (.5, .5, .1), 1/3)
    alb = t.rgba(w, h, (1, 1, 1))
    crop = (slice(5, -5), slice(5, -5), slice(0, 3))
    rng = np.random.default_rng(7605)
    for sigma in (0, .005, .01, .025, .07):
        noisy = clean.copy()
        noisy[..., :3] += rng.normal(0, sigma, noisy[..., :3].shape)
        ref = t.seed(noisy)[3]
        rr = blur(np.roll(clean, 2, axis=1), 8)
        # Test reference recovery separately from deliberate RR anchoring/mixing.
        out = t.compose(rr, ref, z, normal, alb, anchor=0, mix=0)
        before = float(np.sqrt(np.mean((rr[crop]-clean[crop])**2)))
        after = float(np.sqrt(np.mean((out[crop]-clean[crop])**2)))
        ink_error = float(np.mean(np.abs(out[ink, :3]-clean[ink, :3])))
        t.check(f'multitone current frame recovery (anchor/mix off) sigma={sigma}',
                after < before*.55, before=before, after=after, ink_error=ink_error,
                reference_error=float(np.sqrt(np.mean((ref[crop]-clean[crop])**2))),
                sigma_median=float(np.median(ref[5:-5, 5:-5, 3])))
    for kind in ('luminance', 'chromatic', 'correlated'):
        flat = t.rgba(w, h, (.4, .4, .4))
        noisy = flat.copy()
        noise = rng.normal(0, .055, (h, w, 1))
        if kind == 'correlated':
            noise = (noise + np.roll(noise, 1, axis=1)) / np.sqrt(2)
        noisy[..., :3] += noise * (np.array([1, .2, .05]) if kind == 'chromatic' else 1)
        ref = t.seed(noisy)[3]
        out = t.compose(flat, ref, z, normal, alb)
        rms = float(np.sqrt(np.mean((out[crop]-flat[crop])**2)))
        t.check(f'flat RR rejects {kind} grain', rms < .004, rms=rms)
    flat = t.rgba(w, h, (.4, .4, .4))
    reference = t.rgba(w, h, (.7, .7, .7))
    out = t.compose(flat, reference, z, normal, alb)
    t.check('flat reference cannot replace RR broad lighting',
            np.max(np.abs(out[..., :3]-flat[..., :3])) < .001)
    (t.OUT/'results.json').write_text(json.dumps({'checks': t.checks, 'dispatches': t.timings}, indent=2))
    assert all(c['passed'] for c in t.checks), 'textured reference regression'


if __name__ == '__main__':
    run()
