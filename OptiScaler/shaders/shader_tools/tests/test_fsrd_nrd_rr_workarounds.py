"""Adversarial CPU properties; these are not signed-provider quality results."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from fsrd_nrd_rr_signal_contract import alpha_statistics
from fsrd_nrd_rr_workarounds import Parameters, condition, luma

checks = 0


def require(value, reason):
    global checks
    checks += 1
    if not value:
        raise AssertionError(reason)


def scene(width=24, height=24, rgb=(.125, .125, .125), alpha=5.):
    signal = np.empty((height, width, 4), dtype='<f2')
    signal[..., :3] = rgb
    signal[..., 3] = alpha
    normals = np.full((height, width), 512 | (512 << 10) | (256 << 20), dtype='<u4')
    motion = np.zeros((height, width, 4), dtype='<f2')
    motion[..., 3] = 1
    return dict(signal=signal, depth=np.full((height, width), -6, dtype='<f4'),
                normals=normals, motion=motion)


def clone(frame):
    return {key: value.copy() for key, value in frame.items()}


def exact(a, b):
    return np.array_equal(np.ascontiguousarray(a).view('u1'), np.ascontiguousarray(b).view('u1'))


def run():
    p = Parameters()
    base = scene()
    impulse = clone(base)
    impulse['signal'][12, 12, :3] = (.25, .0625, .125)  # exactly same Y as gray.
    sealed = {name: value.copy() for name, value in impulse.items()}
    for mode, previous, older in ((0, base, base), (1, None, None), (2, base, None), (3, base, base)):
        result, gate = condition(impulse, previous, older, mode=mode)
        require(exact(result, impulse['signal']), 'off/unsupported/missing-history exact source identity')
        require(not np.any(gate), 'off/unsupported/missing-history writes no nonzero admission')
    for strength in (0, float('nan'), float('inf'), -float('inf'), -1):
        result, gate = condition(impulse, base, base, parameters=replace(p, strength=strength))
        require(exact(result, impulse['signal']) and not np.any(gate), 'actual nonfinite/zero/negative strength exact identity')
    for mode in (1, 2):
        result, gate = condition(impulse, base, base, mode=mode)
        require(bool(gate[12, 12, 0] & 64), 'declared chroma-only impulse has spatial AND temporal support')
        require(np.count_nonzero(gate[..., 0] & 64) == 1, 'exactly one isolated impulse admitted, no halo texels')
        require(np.max(np.abs(result[12, 12, :3].astype(float)-.125)) < .02, 'synthetic impulse chroma bounded by declared radius')
        require(exact(result[..., 3], impulse['signal'][..., 3]), 'every alpha word preserved')
        require(np.all(np.isfinite(result)), 'admitted finite half output')
        for name, value in sealed.items():
            require(exact(impulse[name], value), 'source and all geometry/motion words immutable')
    for reason in ('depth', 'normal', 'roughness', 'material', 'outside', 'nonfinite-motion'):
        current = clone(impulse)
        if reason == 'depth':
            current['motion'][12, 12, 2] = 2
        elif reason == 'normal':
            current['normals'][12, 12] ^= 255
        elif reason == 'roughness':
            current['normals'][12, 12] ^= 768 << 20
        elif reason == 'material':
            current['normals'][12, 12] |= 1 << 30
        elif reason == 'outside':
            current['motion'][12, 12, 0] = 2
        elif reason == 'nonfinite-motion':
            current['motion'][12, 12, 2] = float('nan')
        result, gate = condition(current, base, base)
        require(exact(result, current['signal']) and not np.any(gate[..., 0] & 64), 'reject mismatched '+reason+' guide/history')
    unsupported = clone(impulse)
    unsupported['normals'][12, 12] |= 3 << 30
    result, gate = condition(unsupported, base, base)
    require(gate[12, 12, 1] == 0, 'material-isolated point has exactly zero valid spatial support')
    require(exact(result, unsupported['signal']) and not np.any(gate[..., 0] & 64),
            'zero-support identity is decided before median/count arithmetic')
    previous = clone(base)
    previous['motion'][12, 12, 2] = 3
    result1, gate1 = condition(impulse, previous, base, mode=1)
    result2, gate2 = condition(impulse, previous, base, mode=2)
    require(bool(gate1[12, 12, 0] & 64), 'one-level ablation does not silently use a second motion source')
    require(exact(result2, impulse['signal']) and not np.any(gate2[..., 0] & 64), 'two-level confirmation rejects older depth discontinuity')
    translated = clone(impulse)
    translated['motion'][12, 12, :2] = (2/24, 0)
    previous = clone(base)
    previous['signal'][12, 12, :3] = (.25, .0625, .125)
    result, gate = condition(translated, previous, base, mode=1)
    require(bool(gate[12, 12, 0] & 64), 'history uses actual nonzero previousUV, not same-pixel lookup')
    for variant in ('persistent-point', 'thin-colored-line', 'colored-step', 'bright-line'):
        current = clone(base)
        if variant == 'persistent-point':
            current['signal'][12, 12, :3] = (.25, .0625, .125)
        elif variant == 'thin-colored-line':
            current['signal'][3:-3, 12, :3] = (.25, .0625, .125)
        elif variant == 'colored-step':
            current['signal'][:, 12:, :3] = (.25, .0625, .125)
        else:
            current['signal'][3:-3, 12, :3] = (.5, .5, .5)
        result, gate = condition(current, clone(current), clone(current))
        require(exact(result, current['signal']), 'persistent synthetic '+variant+' remains bit exact')
        require(not np.any(gate[..., 0] & 64), 'no corrective halo on '+variant)
    for alpha_word in (0, 0x8000, 0xbc00, 0x7bff, 0x3c00, 0x0001):
        current = clone(impulse)
        current['signal'][12, 12, 3:].view('<u2')[0] = alpha_word
        result, gate = condition(current, base, base)
        require(exact(result[..., 3], current['signal'][..., 3]), 'zero/signed-zero/negative/finite-max/subnormal A is opaque')
        if alpha_word == 0xbc00:
            require(exact(result, current['signal']), 'negative inactive signal never conditioned')
    for rgb in ((.25, .0625, .125), (.5, .25, 0), (0, .25, .5), (60000, 30000, 0)):
        current = scene(rgb=tuple(float(luma(np.array(rgb, dtype=np.float32))) for _ in range(3)))
        current['signal'][12, 12, :3] = rgb
        previous = scene(rgb=current['signal'][0, 0, :3])
        result, gate = condition(current, previous, previous)
        require(np.all(np.isfinite(result)) and np.all(result[..., :3] >= 0), 'finite nonnegative gamut including high radiance')
        # The mathematical opponent transform preserves Y. Half output cannot
        # preserve arbitrary exact Y; bound it by half-ULP of each RGB component.
        out = result[..., :3]
        up = np.nextafter(out, np.float16(np.inf)).astype(float)-out.astype(float)
        down = out.astype(float)-np.nextafter(out, np.float16(-np.inf)).astype(float)
        spacing = np.maximum(up, down)
        bound = np.sum(spacing*np.array((.25, .5, .25)), axis=-1)*.5
        before_y = np.sum(current['signal'][..., :3].astype(float)*np.array((.25, .5, .25)), axis=-1)
        after_y = np.sum(out.astype(float)*np.array((.25, .5, .25)), axis=-1)
        require(np.all(np.abs(after_y-before_y) <= bound+np.finfo(np.float32).eps*np.maximum(before_y, 1)*8),
                'luma changes bounded by independently derived half storage error')
    values = np.zeros((1, 7, 4), dtype='<f2')
    values[..., :3] = .125
    values[..., 3].view('<u2')[0] = (0, 0x8000, 0xbc00, 0x3c00, 0x7bff, 0x7c00, 0x7e00)
    stats = alpha_statistics(values)
    require(stats['positive_zero'] == stats['negative_zero'] == stats['negative'] == 1, 'numeric A zero/sign/inactive buckets disjoint')
    require(stats['half_max65504'] == 1 and stats['nonfinite'] == 2 and stats['numeric_partition_complete'], 'finite maximum and malformed A buckets complete')
    impulse_result, gate = condition(impulse, base, base)
    # Intentionally record an adverse identifiability case. The same first
    # appearance can be a real one-pixel color event or stochastic noise; no
    # estimator using these identical observations can distinguish its truth.
    first_true_color = clone(impulse)
    true_result, _ = condition(first_true_color, base, base)
    require(exact(impulse_result, true_result), 'no hidden reference/ground-truth flag enters admission')
    ambiguity = dict(first_real_colored_point_affected=not exact(true_result, first_true_color['signal']),
        changed_rgb_components=int(np.count_nonzero(true_result[..., :3].view('<u2') != first_true_color['signal'][..., :3].copy().view('<u2'))),
        interpretation='single-frame iso-luma real color appearance is indistinguishable from the chosen noise impulse; this is a negative limitation, not a quality win')
    return dict(schema='fsrd-nrd-rr-workaround-cpu-v1', checks=checks, gpu_executed=False,
        compiler_executed=False, signed_provider_executed=False, production_defaults_changed=False,
        synthetic_point_admitted_pixels=int(np.count_nonzero(gate[..., 0] & 64)),
        persistent_thin_edges_bit_exact=True, alpha_and_guides_bit_exact=True,
        first_appearance_ambiguity=ambiguity,
        quality_claim='not measured; CPU conditioner properties are not full RR output quality')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
