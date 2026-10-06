"""Light Anchor Mix (Noise Removal method 1) core contracts on production DXIL.

The current-frame reference is the only detail source: no history is read, so
dispatches are deterministic and history-blind; a measured-clean reference
transfers exactly; a matching reference is a no-op; filter pixels still write
valid metadata colour so neighbouring Anchor reprojection can cross-validate.
Known synthetic truth, not a claim about Cyberpunk/AMD RR image quality.
"""
import json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur


def run():
    t.build_runner()
    w, h = 65, 49
    y, x = np.indices((h, w))
    roi = (slice(8, -8), slice(8, -8), slice(0, 3))
    zero = t.rgba(w, h, (0, 0, 0)); a = t.rgba(w, h, (.8, .8, .8)); d = t.rgba(w, h, (.2, .2, .2))
    n = t.rgba(w, h, (.5, .5, .4), 0); z = np.full((h, w), 10, np.float32)
    mv = t.rgba(w, h, (0, 0, 0), 1)
    cb = dict(DstTexSize=[w, h, 1 / w, 1 / h], DetailPreservation=1, RecoveryMask=2, SpatialTemporalMask=2,
              WriteHistory=1, SpecularAlbedoDemodulation=0, DiffuseAlbedoModulation=0,
              FloorHandoverAnchorClamp=4, FloorHandoverCorrelationMix=1, LumaRecovery=1, ChromaRecovery=1)
    fresh_history = [t.rgba(w, h, (-1, -1, -1), -1), np.zeros((h, w, 4), np.uint32)]

    def dispatch(ref, rr, history=None, **over):
        inputs = [zero, a, rr, d, zero, n, ref, z, mv] + (
            fresh_history if history is None else [history[1], history[2]])
        return t.dispatch('FSRDOutputComp', dict(cb, HistoryValid=int(history is not None), **over),
                          inputs, [10, 10, 3], (w, h))

    # Determinism and history blindness on a textured noisy frame.
    clean = t.rgba(w, h, (.4, .45, .5), 0)
    clean[..., :3] += (.12 * np.sin(x * .9) + .08 * np.cos(y * .7))[..., None]
    rng = np.random.default_rng(31337)
    ref = clean.copy(); ref[..., :3] += rng.normal(0, .012, (h, w, 3)); ref[..., 3] = .012
    rr = blur(clean, 4)
    first = dispatch(ref, rr)
    second = dispatch(ref, rr)
    t.check('deterministic dispatch', np.array_equal(first[0], second[0]))
    chain = dispatch(ref, rr, history=first)
    t.check('history blind', np.array_equal(first[0], chain[0]))
    t.check('filter stores no decision state', bool(np.all(first[1][roi] < 0)),
            stored=float(np.max(first[1][roi][..., :3])))
    meta = first[2]
    valid = (meta[..., 1] >> 31).astype(bool)
    t.check('filter stores valid metadata for anchor cross-validation', bool(np.all(valid[8:-8, 8:-8])))
    out = dispatch(ref, rr)[0][roi][..., :3]
    t.check('composition improves blurred RR',
            float(np.mean((out - clean[roi][..., :3]) ** 2)) < float(np.mean((rr[roi][..., :3] - clean[roi][..., :3]) ** 2)) * .7)

    # Identity: a reference equal to RR changes nothing.
    same = dispatch(rr, rr)
    t.check('matching reference is a no-op', np.allclose(same[0][roi][..., :3], rr[roi][..., :3], atol=2e-3),
            max_error=float(np.max(np.abs(same[0][roi][..., :3] - rr[roi][..., :3]))))

    # Clean content transfers exactly: sharp colour edge over blurred RR. Both
    # lobes are enabled - a single lobe recovers only its albedo share by
    # design, which would leave that share of the blur in place.
    edge = t.rgba(w, h, (.1, .3, .8), 0); edge[:, w // 2:, :3] = (.8, .3, .1)
    restored = dispatch(edge, blur(edge, 2), RecoveryMask=6, SpatialTemporalMask=6)[0]
    t.check('clean sharp edge restored exactly', float(np.max(np.abs(restored[..., :3] - edge[..., :3]))) < .001,
            max_error=float(np.max(np.abs(restored[..., :3] - edge[..., :3]))))

    # A flat clean region beside RR damage: no local structure of its own, but
    # the measured-clean verdict must still replace the damaged RR values.
    damaged = blur(edge, 2)
    flat_ref = t.rgba(w, h, (.1, .3, .8), 0)
    flat_out = dispatch(flat_ref, damaged, RecoveryMask=6, SpatialTemporalMask=6)[0]
    t.check('clean flat region beside damage restored', float(np.max(np.abs(flat_out[:5, :5, :3] - (.1, .3, .8)))) < .001,
            corner=float(np.max(np.abs(flat_out[:5, :5, :3] - (.1, .3, .8)))))

    # Grain with a lying alpha stays anchored to RR (absolute).
    grainy = clean.copy(); grainy[..., :3] += rng.normal(0, .05, (h, w, 3)); grainy[..., 3] = .004
    noisy = dispatch(grainy, clean)[0]
    error = float(np.mean((noisy[roi][..., :3] - clean[roi][..., :3]) ** 2))
    t.check('lying alpha grain anchored to RR', error < 2.5e-5, mse=error)

    (t.OUT / 'results.json').write_text(json.dumps(dict(checks=t.checks, dispatches=t.timings), indent=2))
    assert all(c['passed'] for c in t.checks), 'light anchor mix regression'


if __name__ == '__main__':
    run()
