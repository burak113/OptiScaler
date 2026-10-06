"""Isolated production conversion timing; run without concurrent GPU workloads.

Includes the existing conversion workload, not AMD RR or game frame time.
The first ten of forty repeated dispatches are discarded by the native runner.
"""
from pathlib import Path
import argparse
import os
import numpy as np
import run_fsrd_gpu_tests as t
from fsrd_alpha_common import GPUWorker, CONV_FORMATS, conversion_cb, frozen_identity, rgba, save_json


def main():
    # This tool times intentional algorithm differences. An inherited generic
    # lossless hook would insert extra dispatches and mislabel their timings.
    os.environ.pop('FSRD_LOSSLESS_BASELINE', None)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--trials', type=int, default=3)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.baseline = args.baseline.resolve()
    w, h = args.width, args.height
    if w < 16 or h < 16 or args.trials < 1:
        parser.error('Use dimensions of at least 16 pixels and at least one trial')
    baseline = frozen_identity(args.baseline)
    y, x = np.indices((h, w), dtype=np.float32)
    normals = t.rgba(w, h, (0, 0, -1))
    depth = np.full((h, w), 10, np.float32)
    roughness = np.full((h, w), .55, np.float32)
    zero = t.rgba(w, h, (0, 0, 0))
    spec = t.rgba(w, h, (.05, .05, .05))
    rows = []
    with GPUWorker(args.output):
        for scene in ('flat', 'textured'):
            a = np.full((h, w), .22, np.float32) if scene == 'flat' else (
                .07 + .4 * (.5 + .5*np.sin(x*.70+.17*y)*np.cos(y*.53)))
            diff = rgba(a)
            raw = rgba((diff[..., :3]+spec[..., :3])*.4 + .08)
            # A known constant Floor is a timing fixture, not a quality reference.
            floor = t.rgba(w, h, (.035, .035, .035))
            for floor_on in (False, True):
                inputs = [raw, depth, zero, normals, roughness, depth, diff, spec,
                          zero, floor if floor_on else zero, zero, zero, zero, zero,
                          depth, zero, raw]
                variants = [('baseline', 0, args.baseline), ('alpha_off', 0, t.PRE), ('alpha_on', 1, t.PRE)]
                for trial in range(args.trials):
                    # Rotate order to expose rather than confuse clock/warmup
                    # effects with a change in the byte-identical OFF pipeline.
                    offset = trial % len(variants)
                    for variant, strength, directory in variants[offset:]+variants[:offset]:
                        shader = 'FSRDInputConvAdditive' if strength > 0 and directory == t.PRE else 'FSRDInputConv'
                        t.dispatch(shader, conversion_cb(w, h, strength, floor_on),
                                   inputs, CONV_FORMATS, (w, h), directory=directory, repetitions=40)
                        row = dict(scene=scene, floor=floor_on, variant=variant, trial=trial, **t.timings[-1])
                        rows.append(row)
                        print(scene, floor_on, variant, trial, row['gpu_ms_median'], flush=True)
    aggregate = []
    for scene in ('flat', 'textured'):
        for floor_on in (False, True):
            for variant in ('baseline', 'alpha_off', 'alpha_on'):
                values = [float(r['gpu_ms_median']) for r in rows
                          if r['scene'] == scene and r['floor'] == floor_on and r['variant'] == variant]
                aggregate.append(dict(scene=scene, floor=floor_on, variant=variant,
                    median_ms=float(np.median(values)), min_ms=min(values), max_ms=max(values)))
    save_json(args.output/'results.json', dict(baseline=baseline, width=w, height=h,
        note='Isolated conversion microbenchmark, debug layer enabled; not game frame time.',
        extra_full_resolution_resources=0, extra_history_resources=0, results=rows, aggregate=aggregate))


if __name__ == '__main__':
    main()
