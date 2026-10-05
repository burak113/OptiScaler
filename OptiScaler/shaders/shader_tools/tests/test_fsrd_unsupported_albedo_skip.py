"""Unsupported-albedo recovery must keep each lobe's divisor-floor loss with its own lobe.

Conversion cannot represent a lobe whose stored albedo is below DemodDivisorFloor and leaves
the rest in Skip. Recovery replaces the specular part of the reconstruction, so it has to know
how much of Skip is specular; splitting the loss by the albedo ratio instead brightened the
reported counterexample (radiance 1, albedo 1/255 + 2/255, Floor off, identity RR) by 10.9%.

Production conversion feeds production composition with identity RR (every RR output equals
its input) and forced full recovery weight. The result must then reproduce the title colour on
every eligible pixel, across a grid of dark albedo pairs, with Floor off/on, with the four-signal
half diffuse split, and on a highlight whose lobe saturates at the FP16 limit.
"""
import json
import os
import numpy as np
import run_fsrd_gpu_tests as t

FLOOR = .008
LEVELS = [0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 20, 60, 120, 200]


def scene():
    n = len(LEVELS)
    y, x = np.indices((n, n))
    level = np.array(LEVELS, np.float32) / 255
    spec = np.zeros((n, n, 4), np.float32)
    diff = np.zeros((n, n, 4), np.float32)
    # Independent RGB pairs: per-channel lobe losses differ inside one pixel.
    spec[..., 0], spec[..., 1], spec[..., 2] = level[x], level[y], level[(x + 3 * y) % n]
    diff[..., 0], diff[..., 1], diff[..., 2] = level[y], level[x], level[(2 * x + y) % n]
    colour = t.rgba(n, n, (1.0, .7, .4))
    return spec, diff, colour


def convert(colour, spec, diff, flags, floor_colour=None):
    h, w = colour.shape[:2]
    z = np.ones((h, w), np.float32) * 10
    zero = t.rgba(w, h, (0, 0, 0))
    vals = {'InvViewMatrix': np.eye(4).ravel(), 'InvProjMatrix': np.eye(4).ravel(),
            'PrevViewMatrix': np.eye(4).ravel(), 'DstTexSize': [w, h, 1 / w, 1 / h],
            'MotionInputSize': [w, h, 1 / w, 1 / h], 'MotionTransform': [1, 1, 0, 0],
            'NearPlane': .1, 'FarPlane': 1000, 'FloorDetailPreservation': 0, 'RecoveryMask': 0,
            'Flags': (1 << 1) | (1 << 28) | flags, 'DemodDivisorFloor': FLOOR}
    floor_colour = zero if floor_colour is None else floor_colour
    return t.dispatch('FSRDInputConv', vals,
                      [colour, z, zero, t.rgba(w, h, (0, 0, 1)), np.ones((h, w), np.float32) * .5, z,
                       diff, spec, zero, floor_colour, zero, zero, zero, zero, z, zero,
                       t.rgba(w, h, (0, 0, 0), -1)],
                      [10, 10, 10, 24, 28, 28, 10, 10, 10], (w, h))


def compose(packed, strength, four=False):
    """Identity RR: each denoised output is exactly the RR input conversion produced."""
    u, v, _, normals, qs, qd, skip, _, direct = packed
    h, w = u.shape[:2]
    flags = 8 | ((1 << 6) if four else 0)
    inputs = [u, qs, v, qd, skip, normals, t.rgba(w, h, (0, 0, 0), -1), np.ones((h, w), np.float32) * 10,
              t.rgba(w, h, (0, 0, 0)), t.rgba(w, h, (-1, -1, -1), -1), np.zeros((h, w, 4), np.uint32),
              direct, direct, np.full((h, w, 2), 4, np.float32),
              v if four else t.rgba(w, h, (0, 0, 0)), u, v]
    return t.dispatch('FSRDOutputComp', {'DstTexSize': [w, h, 1 / w, 1 / h], 'DetailPreservation': 0,
                                         'Flags': flags, 'UnsupportedAlbedoRecovery': strength,
                                         'DemodDivisorFloor': FLOOR},
                      inputs, [10, 10, 3], (w, h))[0][..., :3]


def run():
    # The fixed recovery is a new result for an enabled path; there is no frozen counterpart.
    os.environ.pop('FSRD_LOSSLESS_BASELINE', None)
    t.OUT = t.OUT.parent / 'unsupported_albedo_skip'
    t.OUT.mkdir(parents=True, exist_ok=True)
    t.build_runner()
    spec, diff, colour = scene()
    expected = colour[..., :3]
    results = {}
    for label, flags, floor_colour, four in [
            ('Floor off', 0, None, False),
            ('Floor on', 1 << 7, colour * .6, False),
            ('four-signal half diffuse', 1 << 24, None, True)]:
        packed = convert(colour, spec, diff, flags, floor_colour)
        eligible = packed[8][..., 3] > .5
        on, off = compose(packed, 1.0, four), compose(packed, 0.0, four)
        error = np.abs(on - expected) / expected
        results[label] = float(error[eligible].max())
        t.check(f'{label}: identity RR keeps the title colour under full recovery',
                eligible.all() and results[label] < 2e-3, maximum_relative_error=results[label],
                eligible=int(eligible.sum()))
        closed = float((np.abs(off - expected) / expected).max())
        t.check(f'{label}: recovery off closes energy as before', closed < 2e-3, maximum_relative_error=closed)
        if label == 'Floor off':
            # The reported pixel: spec 1/255, diffuse 2/255 in every channel's pair grid.
            i, j = LEVELS.index(2), LEVELS.index(1)
            pixel = on[i, j, 0]
            t.check('reported 1/255 + 2/255 counterexample is not brightened',
                    abs(pixel - 1.0) < 2e-3, output=float(pixel), stored_spec=float(packed[4][i, j, 0] * 255),
                    stored_diffuse=float(packed[5][i, j, 0] * 255))

    # A highlight whose specular lobe saturates at the FP16 limit lost an unknown amount to
    # Skip. Recovery must leave it on the original reconstruction rather than guess.
    w = h = 8
    hot = t.rgba(w, h, (1.0, .7, .4))
    hot[2:4, 2:4, :3] = 2000.0
    s = t.rgba(w, h, (3 / 255, 3 / 255, 3 / 255))
    d = t.rgba(w, h, (0, 0, 0))
    d[:, 4:, :3] = 2 / 255
    packed = convert(hot, s, d, 0)
    on, off = compose(packed, 1.0), compose(packed, 0.0)
    saturated = np.zeros((h, w), bool)
    saturated[2:4, 2:4] = True
    t.check('saturated lobe input keeps the original reconstruction',
            np.all(packed[0][saturated][:, :3] >= 65472) and np.array_equal(on[saturated], off[saturated]))
    error = float((np.abs(on - hot[..., :3]) / hot[..., :3])[~saturated].max())
    t.check('unsaturated neighbours are still recovered exactly', error < 2e-3, maximum_relative_error=error)

    (t.OUT / 'results.json').write_text(json.dumps({'checks': t.checks, 'dispatches': t.timings,
                                                   'maximum_relative_error': results}, indent=2))
    assert all(c['passed'] for c in t.checks), 'unsupported-albedo Skip accounting regression'
    print(f'{len(t.checks)} checks passed; {len(t.timings)} production shader dispatches')


if __name__ == '__main__':
    run()
