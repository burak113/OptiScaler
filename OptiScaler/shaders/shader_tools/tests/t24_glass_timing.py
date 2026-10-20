"""Task 24 GPU pass timings: the flat-detail chain (which ends in the apply pass that carries the vertical-surface
gate) with the gate OFF (VerticalMode 0) and ON (VerticalMode 1, strength .5), at the user's render resolution
(1505x847) and at 2560x1440. Reported per pass: the GPU median and p95 of each production dispatch.

Run through lead_ops/run_task_test.py (shared GPU lock). Result: <FSRD_GPU_TEST_OUTPUT>/t24_timing.json
"""
import json
import os
from pathlib import Path

import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_flat_chain as C
from fsrd_gpu_chain import compile_shader

SHADERS = ('FSRDFlatDetailClassify', 'FSRDFlatDetailSeed', 'FSRDFlatDetailRefine', 'FSRDFlatDetailBase',
           'FSRDFlatDetailApply')


def packed_normal(w, h):
    """R10G10B10A2: octahedral RG of a vertical world normal (0,1,0), roughness 0, alpha field 1 = the flat flag."""
    word = np.uint32(512) | (np.uint32(1023) << 10) | (np.uint32(0) << 20) | (np.uint32(1) << 30)
    return np.full((h, w), word, np.uint32)


def make_frame(w, h, mode):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    level = 0.02 + 0.01 * np.sin(xx / 37.0) * np.cos(yy / 29.0)
    rgb = np.stack([level, level * 0.9, level * 0.8], -1)
    return dict(U=C.rgba(rgb), V=C.rgba(rgb * 0.5), qs8=C.rgba(np.ones_like(rgb) * 0.5),
                qd8=C.rgba(np.ones_like(rgb) * 0.5), skip=C.rgba(np.zeros_like(rgb), -1.0),
                packed=packed_normal(w, h), depth=np.full((h, w), 10.0, np.float32),
                motion=C.rgba(np.zeros_like(rgb), 1.0), rr=C.rgba(rgb),
                vertical_mode=mode, vertical_strength=0.5 if mode else 0.0)


def main():
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    t.OUT = out
    t.build_runner()
    results = []
    # FSRD24_TIMING_REVERSE=1 flips the mode order: the option must not move the number, and the reset copies in
    # the same chain (which cannot depend on it) show whether a difference is real or a run-order artifact.
    modes = (1, 0) if os.environ.get('FSRD24_TIMING_REVERSE') else (0, 1)
    for (w, h) in ((1505, 847), (2560, 1440)):
        for mode in modes:
            directory = out / f'timing_{w}x{h}_m{mode}'
            directory.mkdir(parents=True, exist_ok=True)
            # The chain creates each pass root signature from the file it is given, so the map has to point at
            # freshly compiled CSOs, never at the HLSL sources.
            compiled = {name: compile_shader(t.PRE / (name + '.hlsl'), directory / (name + '.cso')) for name in SHADERS}
            job, names = C.build_chain([make_frame(w, h, mode)],
                                       {name: compiled[name]['output'] for name in SHADERS},
                                       directory, temporal=False, cached_reference=False)
            outputs, metadata = job.run(repetitions=12, warmup=2)
            row = dict(size=[w, h], mode=mode,
                       passes={name: dict(median_ms=float(values['median']), p95_ms=float(values['p95']))
                               for name, values in metadata['timings'].items()})
            results.append(row)
            print(json.dumps(row), flush=True)
    by_size = {}
    for row in results:
        for shader, times in row['passes'].items():
            by_size.setdefault('x'.join(map(str, row['size'])), {}).setdefault(shader, {})[row['mode']] = times
    (out / 't24_timing.json').write_text(json.dumps(dict(rows=results, by_size=by_size), indent=1), encoding='utf-8')
    print(json.dumps(by_size, indent=1))


if __name__ == '__main__':
    main()
