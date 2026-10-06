"""Production DXIL contracts for the current white boundary diagnostic.

The retired RGB view exposed divisor risk alone in green. The current view
requires coherent added structure AND divisor risk in the same channel. A low
constant divisor is therefore quiet. Fixtures specify known spatial boundaries,
not a CPU reimplementation of the classifier. Full-strength diagnostic evidence
is independent of the global slider and never drives production correction.
"""
import json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_zero_rough_screen import chain_cb


def run():
    t.build_runner()
    w, h = 96, 72
    y, x = np.indices((h, w))
    rng = np.random.default_rng(4242)
    zero = t.rgba(w, h, (0, 0, 0))
    depth = np.full((h, w), 10, np.float32)
    normal = t.rgba(w, h, (0, 0, 1))
    rough = np.full((h, w), 0.1, np.float32)
    DEBUG_FLAG = (42 << 17) | (1 << 16)

    def view(colour, spec_albedo, diff_albedo, strength=1.0):
        cb = chain_cb(w, h, DEBUG_FLAG | (1 << 1))
        cb['SpecularAlbedoDemodulation'] = strength
        out = t.dispatch('FSRDInputConv', cb,
                         [t.rgba(w, h, colour), depth, zero, normal, rough, depth,
                          t.rgba(w, h, diff_albedo), t.rgba(w, h, spec_albedo), zero,
                          zero, zero, zero, zero, zero, depth, zero, t.rgba(w, h, colour)],
                         [10, 10, 10, 24, 28, 28, 10, 10], (w, h))
        return out[0][..., :3]

    # A broad guide-only step has a known boundary at x=48. Its interior is
    # deliberately constant: the old Gaussian-centre ROI was not a boundary ROI.
    colour = np.zeros((h, w, 3), np.float32) + np.array((0.05, 0.06, 0.07))
    colour += (0.01 * np.sin(x * 0.3))[..., None]
    spec = np.zeros((h, w, 3), np.float32) + 0.02
    spec += ((x >= 48) * 0.6)[..., None]
    diff = np.zeros((h, w, 3), np.float32) + 0.01
    v = view(colour, spec, diff)
    edge = float(v[18:54, 46:50, 0].mean())
    far = float(v[8:32, 4:20, 0].max())
    t.check('guide-only boundary is strongly marked', edge > 0.8, edge=edge)
    t.check('clean water stays quiet', far < 0.05, far=far)
    t.check('constant blob interior stays quiet', float(v[18:54, 60:80].max()) < 0.05)
    t.check('diagnostic is grayscale', np.array_equal(v[..., 0], v[..., 1]) and
            np.array_equal(v[..., 1], v[..., 2]))
    t.check('diagnostic finite and bounded', bool(np.isfinite(v).all() and
            (v >= 0).all() and (v <= 1).all()))
    v_zero = view(colour, spec, diff, strength=0.0)
    t.check('baseline evidence independent of slider', np.array_equal(v, v_zero))

    # Equal local range with alternating signs is not a coherent blob boundary.
    alternating = np.broadcast_to((0.02 + 0.6 * ((x+y) % 2))[..., None], (h,w,3))
    grain_view = view(colour, alternating, diff)
    t.check('alternating guide grain rejected', float(grain_view[8:-8,8:-8].max()) < 0.05)

    # Consistent metal: radiance = albedo * smooth lighting.
    lighting = 0.3 + 0.2 * np.sin(x * 0.2 + y * 0.15)
    metal_albedo = np.zeros((h, w, 3), np.float32)
    metal_albedo += (0.5 + 0.35 * np.clip(np.sin(x * 0.5) * np.sin(y * 0.4), 0, 1))[..., None]
    v = view(metal_albedo * lighting[..., None], metal_albedo,
             np.zeros((h, w, 3), np.float32) + 0.04)
    risk = float(v[20:52, 20:76, 0].mean())
    t.check('consistent factorization stays quiet', risk < 0.1, risk=risk)

    # Flat albedo, detailed radiance: constant gain cancels.
    flat = colour + (0.05 * rng.random((h, w, 1))).astype(np.float32)
    v = view(flat, np.zeros((h, w, 3), np.float32) + 0.3,
             np.zeros((h, w, 3), np.float32) + 0.2)
    t.check('constant gain cancelled', float(v[20:52, 20:76].max()) < 0.05)

    # Low divisor alone is insufficient evidence for the white intersection.
    v = view(colour, np.zeros((h, w, 3), np.float32) + 0.002,
             np.zeros((h, w, 3), np.float32) + 0.002)
    risk = float(v[20:52, 20:76].max())
    t.check('constant clamped divisor remains quiet', risk < 0.05, risk=risk)

    (t.OUT / 'results.json').write_text(json.dumps(dict(checks=t.checks, dispatches=t.timings), indent=2))
    assert all(c['passed'] for c in t.checks), 'demod risk view regression'


if __name__ == '__main__':
    run()
