"""Fixed spatial high-spp audit of V5's two finite MC references, CPU only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np

import fsrd_nrd_rr_ggx_oracle as oracle
import fsrd_nrd_rr_material_quality as sealed


FRAMES = (2, 25, 49, 65)
GRID = tuple(range(22, 112, 12))
SAMPLES_PER_REPLICA = 16384
SEEDS = (0x15C5C301, 0x15C5D402)


def run(cases, output):
    if output.exists():
        raise AssertionError('fresh audit folder preserves previous calibration evidence')
    output.mkdir(parents=True)
    camera = oracle.camera_api()
    ys, xs = np.meshgrid(GRID, GRID, indexing='ij')
    rows, checks = [], 0
    begin = time.perf_counter()
    for case in cases:
        manifest = json.loads((case / 'ggx-sequence.json').read_bytes())
        if manifest['schema'] != oracle.SCHEMA or manifest['zero_roughness_used']:
            raise AssertionError('audit only the physical positive-roughness integrated source')
        checks += 1
        frame_rows = []
        for number in FRAMES:
            index = number - 2
            frame = manifest['frames'][index]
            folder = case / 'dataset' / frame['directory']
            geometry = oracle.frame_geometry(index, camera)
            stored = sealed.load(folder, frame['payloads']['current_world'])
            if not np.array_equal(stored[ys, xs], geometry['current']['point'][ys, xs].astype('<f4')):
                raise AssertionError('high-spp audit reconstructs exact original physical points')
            checks += 1
            points = geometry['current']['point'][ys, xs]
            view = -geometry['current']['direction'][ys, xs]
            high, high_infos = [], []
            for replica, seed in enumerate(SEEDS):
                value, info = oracle.integrate_reference(points, view, geometry['pose'], manifest['roughness'], SAMPLES_PER_REPLICA, seed + index)
                record = sealed.put(output, f'r{manifest["code"]}-frame{number:03d}-replica{replica}.bin', value.astype('<f4'))
                high.append(value)
                info.update(payload=record)
                high_infos.append(info)
            low_a = sealed.load(folder, frame['payloads']['reference_spec_a'])[ys, xs].astype(np.float64)
            low_b = sealed.load(folder, frame['payloads']['reference_spec_b'])[ys, xs].astype(np.float64)
            low, high_mean = (low_a + low_b) * .5, (high[0] + high[1]) * .5
            delta = low - high_mean
            frame_rows.append(dict(frame=number, points=int(points.shape[0] * points.shape[1]),
                high_reference_replicas=high_infos,
                low_total_spp=manifest['reference_samples_per_replica'] * 2, high_total_spp=SAMPLES_PER_REPLICA * 2,
                low_mean_minus_high_mean_rgb_rmse=float(np.sqrt(np.mean(delta * delta))),
                low_mean_minus_high_mean_rgb_bias=np.mean(delta, axis=(0, 1)).tolist(),
                low_split_rgb_rmse=float(np.sqrt(np.mean((low_a - low_b) ** 2))),
                high_split_rgb_rmse=float(np.sqrt(np.mean((high[0] - high[1]) ** 2))),
                max_abs_low_mean_minus_high_mean=float(np.max(np.abs(delta)))))
        rows.append(dict(case=str(case), manifest_sha256=sealed.file_sha(case / 'ggx-sequence.json'),
            roughness=manifest['roughness'], frames=frame_rows))
    result = dict(schema=oracle.SCHEMA + '-fixed-spatial-reference-audit', rows=rows,
        fixed_frames=list(FRAMES), fixed_pixel_coordinates=list(GRID), points_per_frame=len(GRID) ** 2,
        high_spp_per_replica=SAMPLES_PER_REPLICA, independent_reference_seeds=list(SEEDS),
        source_sha256=sealed.file_sha(Path(__file__)), elapsed_seconds=time.perf_counter() - begin,
        checks=checks, payload_integrity_checks=sealed.CHECKS,
        scope='finite independently randomized high-spp calibration at a prespecified uniform grid; not a full-image exact reference or a quality win',
        candidate_gate_uses_reference=False, gpu_executed=False, compiler_executed=False)
    sealed.write_json(output / 'audit.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, default=Path('E:/FSRD/sol_batch/15c-rr/ggx-reference-audit-1'))
    args = parser.parse_args()
    run(args.case, args.output)
