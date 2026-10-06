"""Albedo-trust evidence must count independent, in-bounds surface samples."""
import json
import numpy as np
import run_fsrd_gpu_tests as t


def evidence(w, h, depth):
    y, x = np.indices((h, w))
    spec = t.rgba(w, h, (0, 0, 0))
    spec[..., :3] = np.where((x + y) % 2 == 0, .1, .8)[..., None]
    zero = t.rgba(w, h, (0, 0, 0))
    # Flat light over a varying albedo is potential evidence only with enough support.
    return t.dispatch('FSRDAlbedoTrustEvidence',
                      {'DstTexSize': [w, h, 1 / w, 1 / h], 'DemodDivisorFloor': .008},
                      [t.rgba(w, h, (.2, .2, .2)), zero, spec, zero, zero,
                       depth, t.rgba(w, h, (.5, .5, .2)), t.rgba(w, h, (0, 0, 0), 1)],
                      [t.TRUST], (w, h))[0]


def run():
    t.OUT = t.OUT.parent / 'albedo_support'
    t.OUT.mkdir(parents=True, exist_ok=True)
    t.build_runner()
    for w, h in ((1, 1), (2, 2), (3, 3), (1, 17), (17, 1)):
        votes = evidence(w, h, np.full((h, w), 10, np.float32))
        t.check(f'{w}x{h}: fewer than ten unique samples cannot authorize recovery',
                np.all(np.isfinite(votes)) and np.all(votes == 0),
                maximum_vote=float(np.max(votes)))

    w = h = 17
    # The same one-pixel surface at an edge and in the interior has at most nine
    # independent samples. Replicating edge texels must not turn it into 45 votes.
    for column in (0, 8, 16):
        depth = np.full((h, w), 20, np.float32)
        depth[:, column] = 10
        votes = evidence(w, h, depth)
        t.check(f'thin surface at x={column} abstains', np.all(votes[:, column] == 0),
                maximum_vote=float(np.max(votes[:, column])))

    votes = evidence(w, h, np.full((h, w), 10, np.float32))
    t.check('supported interior still supplies unsupported-albedo evidence',
            np.all(votes[4:-4, 4:-4] > .99))
    (t.OUT / 'results.json').write_text(json.dumps({'checks': t.checks, 'dispatches': t.timings}, indent=2))
    assert all(c['passed'] for c in t.checks), 'albedo support regression'
    print(f'{len(t.checks)} checks passed; {len(t.timings)} production shader dispatches')


if __name__ == '__main__':
    run()
