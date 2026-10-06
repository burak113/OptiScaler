# HISTORICAL: the sparkle-pedestal fix this pinned was REVERTED after in-game
# testing on 2026-09-25 - the darker pedestal handed more content to RR and
# small dark noise covered the scene. The user also identified specular albedo
# demodulation (0 disables the stain) as the actual in-game culprit. Excluded
# from validate_fsrd.py.
"""The spatial floor pedestal must not absorb specular sparkle.

Dense glint coverage (a sparkling reflection lane over dark water) previously
pooled into the pedestal as if it were volumetry: the Skip signal carried a
broad bright patch no single frame contained, bypassing RR and invisible to
recovery (both sides of its delta include Skip). Production seed + FSRDFloor
DXIL; symmetric grain and genuine broad brightness keep their contracts.
"""
import json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t


def luminance(a):
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def run():
    t.build_runner()
    w, h = 128, 96
    y, x = np.indices((h, w))
    rng = np.random.default_rng(5150)
    albedo = t.rgba(w, h, (0.05, 0.05, 0.05))

    # Sparkle lane: dense glints over flat dark water; no broad component.
    colour = t.rgba(w, h, (0.02, 0.02, 0.02))
    colour[..., :3] += 0.01 * rng.random((h, w, 1))
    colour[..., :3] += rng.normal(0, 0.02, (h, w, 3))
    lane = (x > 78) & (x < 112) & (y > 16) & (y < 80)
    glint = (rng.random((h, w)) < 0.85) & lane
    colour[..., :3] += (glint[..., None] * rng.uniform(0.25, 0.85, (h, w, 1))).astype(np.float32)
    f, z, g, reference = t.seed(colour)
    floor = t.filter_floor(f, z, g, albedo)
    roi = (slice(20, 70), slice(84, 106))
    far = (slice(20, 70), slice(8, 40))
    edge = (slice(20, 70), slice(70, 78))
    lane_pedestal = float(np.median(luminance(floor[roi])))
    far_pedestal = float(np.median(luminance(floor[far])))
    edge_pedestal = float(np.median(luminance(floor[edge])))
    lane_input = float(np.median(luminance(colour[roi])))
    t.check('dense sparkle does not become a bright pedestal',
            lane_pedestal < 0.4 * lane_input,
            lane_pedestal=lane_pedestal, lane_input_median=lane_input, far_pedestal=far_pedestal)
    t.check('sparkle lane edge keeps dark-water pedestal',
            edge_pedestal < 3.0 * max(far_pedestal, 1e-4),
            edge_pedestal=edge_pedestal, far_pedestal=far_pedestal)
    ref_contrast = float(np.percentile(luminance(reference[roi]), 90) - np.median(luminance(reference[roi])))
    t.check('reference keeps the sparkle as detail',
            ref_contrast > 0.5 * float(np.percentile(luminance(colour[roi]), 90) -
                                       np.median(luminance(colour[roi]))),
            reference_contrast=ref_contrast)

    # Symmetric grain over a mid-bright volume: the pedestal stays unbiased.
    vol = t.rgba(w, h, (0.30, 0.32, 0.34))
    vol[..., :3] += rng.normal(0, 0.03, (h, w, 3))
    f2, z2, g2, _ = t.seed(vol)
    floor2 = t.filter_floor(f2, z2, g2, albedo)
    centre = (slice(30, 60), slice(40, 88))
    t.check('symmetric grain pedestal stays near the input mean',
            abs(float(np.median(luminance(floor2[centre]))) - float(np.mean(luminance(vol[centre])))) <
            0.25 * float(np.mean(luminance(vol[centre]))),
            pedestal=float(np.median(luminance(floor2[centre]))), input=float(np.mean(luminance(vol[centre]))))

    # Genuine broad brightness (fog-like blob): the pedestal still follows it.
    blob = np.exp(-(((x - 64) / 18.0) ** 2 + ((y - 48) / 22.0) ** 2))
    fog = t.rgba(w, h, (0.02, 0.02, 0.02))
    fog[..., :3] += (blob * 0.5)[..., None] * np.float32((1.0, 0.95, 0.85))
    fog[..., :3] += rng.normal(0, 0.01, (h, w, 3))
    f3, z3, g3, _ = t.seed(fog)
    floor3 = t.filter_floor(f3, z3, g3, albedo)
    core = (slice(40, 56), slice(56, 72))
    t.check('broad genuine brightness keeps its pedestal',
            float(np.median(luminance(floor3[core]))) > 0.5 * float(np.mean(luminance(fog[core]))),
            pedestal=float(np.median(luminance(floor3[core]))), input=float(np.mean(luminance(fog[core]))))

    (t.OUT / 'results.json').write_text(json.dumps(dict(checks=t.checks, dispatches=t.timings), indent=2))
    assert all(c['passed'] for c in t.checks), 'floor glint pedestal regression'


if __name__ == '__main__':
    run()
