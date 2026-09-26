"""Sharp pattern recovery versus grain, exposure, and real Floor/Skip.

Production DXIL on D3D12. RR is a controlled synthetic input, not AMD inference.
Metrics never label an entire game image as a percentage correct. NRMSE uses
the clean target's RMS as denominator; contrast retention is a projection on
its mean-centred RGB pattern. Temporal variation is measured only for static
targets, where animation cannot be mislabelled as stochastic noise.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_stage_probe as p
from test_fsrd_panel_recovery import blur
from test_fsrd_stage_diagnostics import fixture
from test_fsrd_zero_rough_screen import chain_cb


def metrics(image, target, roi):
    c = target[roi].astype(np.float64)
    o = image[roi].astype(np.float64)
    centred = c-c.mean(axis=(0, 1))
    error = float(np.sqrt(np.mean((o-c)**2)))
    return {'rmse': error, 'nrmse_percent': 100*error/max(float(np.sqrt(np.mean(c*c))), 1e-20),
            'contrast_retained_percent': 100*float(np.mean((o-o.mean(axis=(0, 1)))*centred))/
                                         max(float(np.mean(centred*centred)), 1e-20)}


def run(baseline=None):
    t.OUT = t.OUT.parent/'blur_evidence'
    t.OUT.mkdir(parents=True, exist_ok=True)
    t.build_runner()
    records = []
    # Exactly the same inputs scaled before FP16 storage isolate composition
    # exposure dependence from upstream seed classification changes.
    for scale in (1, 2, 3):
        for noisy in (False, True):
            values, inputs, target, raw, ink = fixture(scale, noisy)
            ys, xs = np.where(ink)
            roi = (slice(ys.min()-2, ys.max()+3), slice(xs.min()-2, xs.max()+3), slice(0, 3))
            retained = []
            for exposure in (.01, .1, 1, 10):
                ii = [a.copy() for a in inputs]
                truth = target.copy(); truth[..., :3] *= exposure
                for k in (0, 2, 4): ii[k][..., :3] *= exposure
                ii[6] *= exposure
                out = p.dispatch(values, ii)
                row = dict(case='lettering', scale=scale, noisy=noisy, exposure=exposure,
                           **metrics(out, truth, roi))
                retained.append(row['contrast_retained_percent'])
                label = f'blur evidence lettering scale={scale} noisy={noisy} exposure={exposure}'
                rr = metrics(ii[2], truth, roi)
                t.check(label+' improves blurred RR', row['rmse'] < rr['rmse']*.99, **row)
                if not noisy:
                    t.check(label+' clean contrast recovered', retained[-1] > (78, 89, 93)[scale-1], **row)
                if baseline:
                    old = p.dispatch(values, ii, directory=baseline)
                    row['previous'] = metrics(old, truth, roi)
                    t.check(label+' no prior-delivery error regression',
                            row['rmse'] <= row['previous']['rmse']+exposure*.0003, **row)
                    if not noisy:
                        t.check(label+' material clean-pattern improvement',
                                row['rmse'] < row['previous']['rmse']*.8, **row)
                records.append(row)
            if not noisy:
                t.check(f'clean contrast stable across exposure scale={scale}',
                        max(retained)-min(retained) < 2, retained_percent=retained)

    w, h = 65, 49
    y, x = np.indices((h, w)); roi = (slice(8, -8), slice(8, -8), slice(0, 3))
    a = t.rgba(w, h, (1, 1, 1)); zero = t.rgba(w, h, (0, 0, 0))
    n = t.rgba(w, h, (.5, .5, .1), 1/3); depth = np.full((h, w), 10, np.float32)
    values = dict(DstTexSize=[w, h, 1/w, 1/h], DetailPreservation=1.0, NoiseSuppression=.75,
                  FloorHandoverAnchorClamp=4, FloorHandoverCorrelationMix=1)
    target = t.rgba(w, h, (0, 0, 0))
    for channel, phase in enumerate((0, 1.1, 2.4)):
        target[..., channel] = .5+.16*np.sin(x*.43+y*.11+phase)+.10*np.cos(y*.61-x*.23-phase)
    # Unseen random seeds and colours: smoothing noisy current content often
    # fits a clean RR better, but must not be permission to restore that noise.
    for exposure in (.01, 1, 32):
        for sample in range(6):
            rng = np.random.default_rng(21837+sample)
            field = t.rgba(w, h, (0, 0, 0)); field[..., :3] = rng.normal(0, 1, (h, w, 3))
            coarse = blur(field, 3+sample)[..., :3]; coarse /= np.std(coarse)
            truth = target.copy(); truth[..., :3] *= exposure
            raw = truth.copy()
            if sample % 2: raw[..., :3] *= np.clip(1+.13*coarse, .5, 1.5)
            else: raw[..., :3] += .045*exposure*coarse
            raw[..., :3] = np.maximum(raw[..., :3]+rng.normal(0, .025*exposure, (h, w, 3)), 0)
            ii = [zero, a, truth, a, zero, n, t.seed(raw)[3], depth]
            out = p.dispatch(values, ii)
            row = dict(case='held-out lighting noise', exposure=exposure, sample=sample,
                       **metrics(out, truth, roi))
            row['raw_rmse'] = metrics(raw, truth, roi)['rmse']
            row['remaining_noise_error_percent'] = 100*row['rmse']/row['raw_rmse']
            t.check(f'held-out noise exposure={exposure} sample={sample} bounded',
                    row['rmse'] < row['raw_rmse']*.5, **row)
            if baseline:
                old = p.dispatch(values, ii, directory=baseline)
                row['previous'] = metrics(old, truth, roi)
                t.check(f'held-out noise exposure={exposure} sample={sample} no regression',
                        row['rmse'] <= max(row['previous']['rmse']*1.05, .0005*exposure), **row)
            records.append(row)

    # Existing tests cover surface/routing boundaries. Explicit opt-outs remain
    # exactly equal to the previous shader; no new permission at Noise=0.
    ii = [zero, a, blur(target, 3), a, zero, n, t.seed(target)[3], depth]
    for label, change in (
        ('ordinary', lambda v, i: i[5].__setitem__((Ellipsis, 3), 0)),
        ('routed', lambda v, i: i[6].__setitem__((Ellipsis, 3), -1)),
        ('detail off', lambda v, i: v.update(DetailPreservation=0)),
        ('mix off', lambda v, i: v.update(FloorHandoverCorrelationMix=0))):
        vv = dict(values); jj = [q.copy() for q in ii]; change(vv, jj)
        out = p.dispatch(vv, jj)
        t.check(label+' finite radiance', np.all(np.isfinite(out)) and np.all(out[..., :3] >= 0))
        if baseline:
            t.check(label+' output unchanged', np.array_equal(out, p.dispatch(vv, jj, directory=baseline)))

    # Actual seed -> all Floor passes -> conversion -> synthetic full RR ->
    # composition. Selected displays send full radiance to RR; the independent
    # clean target defines RR without cancelling any current-frame Skip error.
    material = t.rgba(w, h, (.5, .5, .5)); normals = t.rgba(w, h, (0, 0, 1))
    clean_f, z, guide, _ = t.seed(target, albedo=material)
    clean_f = t.filter_floor(clean_f, z, guide, material)
    clean_rr = blur(target, 3)
    sequences = {'current': [], 'previous': [], 'raw': [], 'skip': []}
    for frame in range(6):
        rng = np.random.default_rng(957+frame)
        raw = target.copy(); raw[..., :3] += rng.normal(0, .035, (h, w, 3))
        f, z, guide, ref = t.seed(raw, albedo=material)
        f = t.filter_floor(f, z, guide, material)
        packed = t.dispatch('FSRDInputConv', chain_cb(w, h, (1 << 1) | (1 << 7)),
                            [raw, z, zero, normals, np.zeros((h, w), np.float32), z,
                             material, material, zero, f, zero, zero, zero, zero, z, zero, ref],
                            [10, 10, 10, 24, 28, 28, 10, 10], (w, h))
        denoised = clean_rr.copy()
        denoised[..., :3] /= np.maximum(packed[5][..., :3], .008)
        jj = [zero, packed[4], denoised, packed[5], packed[6], packed[3], packed[7], z]
        out = p.dispatch(values, jj)
        sequences['current'].append(out); sequences['raw'].append(raw); sequences['skip'].append(packed[6])
        if baseline: sequences['previous'].append(p.dispatch(values, jj, directory=baseline))
        t.check(f'full pipeline frame={frame} bounded', metrics(out, target, roi)['rmse'] < .1)
    variation = lambda arr: float(np.sqrt(np.mean(np.var(np.stack(arr)[:, 8:-8, 8:-8, :3], axis=0))))
    row = {'case': 'static full pipeline', 'frames': 6,
           'final_variation': variation(sequences['current']), 'raw_variation': variation(sequences['raw']),
           'skip_variation': variation(sequences['skip']),
           **metrics(np.mean(sequences['current'], axis=0), target, roi)}
    row['remaining_variation_percent'] = 100*row['final_variation']/row['raw_variation']
    t.check('real Skip sequence reduces input grain', row['final_variation'] < row['raw_variation']*.8, **row)
    if baseline:
        row['previous_variation'] = variation(sequences['previous'])
        row['previous'] = metrics(np.mean(sequences['previous'], axis=0), target, roi)
        t.check('real Skip sequence noise not worsened', row['final_variation'] <= row['previous_variation']*1.05+.0001, **row)
        t.check('real Skip sequence structure not worsened', row['rmse'] <= row['previous']['rmse']+.0003, **row)
    records.append(row)
    (t.OUT/'results.json').write_text(json.dumps({'checks': t.checks, 'dispatches': t.timings, 'records': records}, indent=2))
    assert all(c['passed'] for c in t.checks), 'blur evidence regression'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path)
    run(parser.parse_args().baseline)
