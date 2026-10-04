"""Unsupported-albedo recovery: conversion signal, trust passes and composition blend.

Runs production DXIL with synthetic RR outputs, not AMD inference. The left surface is
water over a hidden sand bank: its albedo has an elliptical pattern the light does not
show. The right surface, at another depth, is a striped texture whose light follows its
albedo. Recovery must take the unmodulated specular path on the whole left surface,
including the bank's flat interior, and leave the textured surface bit-identical.
"""
import json
import os
import numpy as np
import run_fsrd_gpu_tests as t


def run():
    # New shaders and an enabled blend have no frozen counterpart: the lossless gate covers
    # the disabled path through every other fixture, not this feature's own outputs.
    os.environ.pop('FSRD_LOSSLESS_BASELINE', None)
    t.OUT = t.OUT.parent / 'unsupported_albedo'
    t.OUT.mkdir(parents=True, exist_ok=True)
    t.build_runner()
    w, h = 96, 64
    y, x = np.indices((h, w))
    left = x < w // 2
    floor = .008

    # Conversion publishes (1-b)*C*share for RR direct specular, with an eligibility alpha.
    c = t.rgba(w, h, (.15, .35, .7))
    z = np.ones((h, w), np.float32) * 10
    zero = t.rgba(w, h, (0, 0, 0))
    normal = t.rgba(w, h, (0, 0, 1))
    rough = np.ones((h, w), np.float32) * .5
    spec = t.rgba(w, h, (.1, .2, .3))
    diff = t.rgba(w, h, (.5, .4, .3))
    bias = t.rgba(w, h, (0, 0, 0))
    bias[:, :w // 4, :3] = .5
    vals = {'InvViewMatrix': np.eye(4).ravel(), 'InvProjMatrix': np.eye(4).ravel(),
            'PrevViewMatrix': np.eye(4).ravel(), 'DstTexSize': [w, h, 1 / w, 1 / h],
            'MotionInputSize': [w, h, 1 / w, 1 / h], 'MotionTransform': [1, 1, 0, 0],
            'NearPlane': .1, 'FarPlane': 1000, 'FloorDetailPreservation': .35,
            'Flags': (1 << 1) | (1 << 15) | (1 << 7) | (1 << 28), 'DemodDivisorFloor': floor, 'BiasMaskStrength': 1}
    packed = t.dispatch('FSRDInputConv', vals,
                        [c, z, zero, normal, rough, z, diff, spec, bias, t.rgba(w, h, (.05, .1, .2)),
                         zero, zero, zero, zero, z, zero, t.rgba(w, h, (.05, .1, .2), .1)],
                        [10, 10, 10, 24, 28, 28, 10, 10, 10], (w, h))
    direct = packed[8]
    qs, qd = packed[4][..., :3], packed[5][..., :3]
    total = qs + qd
    split = np.clip((total - .5 * floor) / (.5 * floor), 0, 1)
    share = qs / np.maximum(total, floor) * split * split * (3 - 2 * split)
    expected = (1 - bias[..., :3]) * c[..., :3] * share
    error = float(np.max(np.abs(direct[..., :3] - expected) / np.maximum(expected, 1e-3)))
    t.check('conversion unmodulated specular = (1-b) C share', error < 2e-3, error=error)
    t.check('conversion marks bias-routed pixels ineligible',
            np.all(direct[:, :w // 4, 3] == 0) and np.all(direct[:, w // 4:, 3] == 1))

    # Synthetic post-RR scene. Depth separates the two surfaces.
    depth = np.where(left, 10.0, 20.0).astype(np.float32)
    n = t.rgba(w, h, (.5, .5, .1), 0)
    bank = ((x - 24) / 16.0) ** 2 + ((y - 32) / 20.0) ** 2 < 1
    stripes = (x // 4) % 2 == 0
    qt = np.where(left, np.where(bank, .6, .15), np.where(stripes, .6, .15))
    qs = t.rgba(w, h, (0, 0, 0)); qd = t.rgba(w, h, (0, 0, 0))
    qs[..., :3] = (np.rint(qt * .85 * 255) / 255)[..., None]
    qd[..., :3] = (np.rint(qt * .15 * 255) / 255)[..., None]
    qtot = qs[..., :3] + qd[..., :3]
    split = np.clip((qtot - .5 * floor) / (.5 * floor), 0, 1)
    sh = qs[..., :3] / np.maximum(qtot, floor) * split * split * (3 - 2 * split)
    light = np.where(left, .16, .5 * qt)[..., None] * np.ones(3)   # water flat, texture follows albedo
    skip = t.rgba(w, h, (0, 0, 0)); skip[..., :3] = .4 * light
    resid = light - skip[..., :3]
    # Path A carries an albedo imprint (+20% inside the bank); path B is the clean light.
    imprint = np.where(left & bank, 1.2, 1.0)[..., None]
    rr_spec = t.rgba(w, h, (0, 0, 0)); rr_spec[..., :3] = resid / qtot * imprint
    rr_diff = t.rgba(w, h, (0, 0, 0)); rr_diff[..., :3] = resid / qtot
    path_b = t.rgba(w, h, (0, 0, 0)); path_b[..., :3] = light * sh
    signal = t.rgba(w, h, (0, 0, 0), 1)
    signal[40:48, 4:12, 3] = 0   # ineligible block on the water

    evidence = t.dispatch('FSRDAlbedoTrustEvidence',
                          {'DstTexSize': [w, h, 1 / w, 1 / h], 'DemodDivisorFloor': floor},
                          [path_b, rr_diff, qs, qd, skip, depth, n, signal], [16], (w, h))[0]
    evidence_four = t.dispatch('FSRDAlbedoTrustEvidence',
                               {'DstTexSize': [w, h, 1 / w, 1 / h], 'DemodDivisorFloor': floor, 'Flags': 1},
                               [path_b, rr_diff * .5, qs, qd, skip, depth, n, signal, rr_diff * .5], [16], (w, h))[0]
    t.check('four-signal evidence sums both diffuse outputs', np.array_equal(evidence, evidence_four))
    votes = evidence
    for step in range(6):
        votes = t.dispatch('FSRDAlbedoTrustPropagate',
                           {'DstTexSize': [w, h, 1 / w, 1 / h], 'StepSize': 1 << step},
                           [votes, depth, n], [16], (w, h))[0]
    t.check('trust votes finite and nonnegative', np.all(np.isfinite(votes)) and np.all(votes >= 0))

    def compose(strength, four=False):
        v = {'DstTexSize': [w, h, 1 / w, 1 / h], 'DetailPreservation': 0, 'Flags': 8,
             'UnsupportedAlbedoRecovery': strength, 'DemodDivisorFloor': floor}
        inputs = [rr_spec, qs, rr_diff * (.5 if four else 1), qd, skip, n, t.rgba(w, h, (0, 0, 0), -1), depth,
                  t.rgba(w, h, (0, 0, 0)), t.rgba(w, h, (-1, -1, -1), -1), np.zeros((h, w, 4), np.uint32),
                  path_b, signal, votes]
        if four:
            v['Flags'] |= 1 << 6
            inputs += [rr_diff * .5]
        return t.dispatch('FSRDOutputComp', v, inputs, [10, 10, 3], (w, h))[0][..., :3]

    off, on = compose(0.0), compose(1.0)
    four = compose(1.0, four=True)
    t.check('four-signal recovery preserves the three-signal reconstruction', np.array_equal(on, four))
    original = rr_spec[..., :3] * qs[..., :3] + rr_diff[..., :3] * qd[..., :3] + skip[..., :3]
    error = float(np.max(np.abs(off - original) / np.maximum(original, 1e-3)))
    t.check('disabled recovery keeps the original reconstruction', error < 2e-3, error=error)
    recovered = path_b[..., :3] + rr_diff[..., :3] * qd[..., :3] + skip[..., :3] * (1 - sh)
    eligible = left & (signal[..., 3] > .5)
    rel = np.abs(on - recovered) / np.maximum(recovered, 1e-3)
    taken = float(np.mean(rel[eligible].max(-1) < 3e-3))
    t.check('hidden-floor surface takes the unmodulated path, bank interior included',
            taken > .97 and float(np.mean(rel[eligible & bank].max(-1) < 3e-3)) > .97, fraction=taken)
    stain = float(abs(on[left & bank].mean() - on[left & ~bank & eligible].mean()) / on[left].mean())
    before = float(abs(off[left & bank].mean() - off[left & ~bank & eligible].mean()) / off[left].mean())
    t.check('albedo-shaped stain removed on the water', stain < .01 and before > .05, before=before, after=stain)
    t.check('textured surface whose light follows its albedo is bit-identical',
            np.array_equal(on[~left], off[~left]))
    t.check('ineligible pixels are bit-identical', np.array_equal(on[~(signal[..., 3] > .5)], off[~(signal[..., 3] > .5)]))

    (t.OUT / 'results.json').write_text(json.dumps({'checks': t.checks, 'dispatches': t.timings}, indent=2))
    assert all(c['passed'] for c in t.checks), 'unsupported-albedo recovery regression'
    print(f'{len(t.checks)} checks passed; {len(t.timings)} production shader dispatches')


if __name__ == '__main__':
    run()
