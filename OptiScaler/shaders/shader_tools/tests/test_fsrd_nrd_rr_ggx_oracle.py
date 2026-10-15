"""Positive-GGX ray geometry, real miss and below-surface contribution tests."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import fsrd_nrd_rr_ggx_oracle as oracle
import fsrd_nrd_rr_material_quality as sealed
import fsrd_nrd_rr_mirror_oracle as scene


def run(output):
    checks = 0
    def need(value, description):
        nonlocal checks
        checks += 1
        if not bool(value):
            raise AssertionError(description)
    camera = oracle.camera_api()
    pose = camera['pose'](0, scene.WIDTH, scene.HEIGHT)
    origins = np.stack((scene.BACKGROUND, scene.BACKGROUND, scene.BACKGROUND, pose['center'])) + scene.NORMAL * oracle.RAY_ORIGIN_OFFSET
    directions = np.stack((scene.NORMAL, -scene.NORMAL, scene.TANGENT, -scene.NORMAL))
    ray = oracle.nearest_emission(origins, directions, pose)
    need(ray['object'].tolist() == [1, 0, 255, 1], 'nearer foreground, below-surface selfhit, actual tangent miss, foreground selfhit')
    need(ray['distance'][0] < 11. and abs(ray['distance'][1] - oracle.RAY_ORIGIN_OFFSET) < 1e-12,
         'actual positive nearest surface distances, not guessed hit metrics')
    need(ray['distance'][2] == 65504. and ray['miss'][2], '65504 only the explicitly demonstrated geometry miss')
    need(not ray['miss'][[0, 1, 3]].any(), 'finite hits never turned into misses')
    need(np.all(ray['radiance'][[1, 3]] == 0.), 'primary front/selfhit is nonemissive')
    need(ray['radiance'][0, 0] > ray['radiance'][0, 2], 'foreground rear is defined warm emission')
    for i in (0, 1, 3):
        need(abs(np.linalg.norm(ray['point'][i] - origins[i]) - ray['distance'][i]) < 1e-12,
             'A is Euclidean distance from the declared actual ray origin')
    geometry = oracle.frame_geometry(31, camera)
    xi = np.random.default_rng(oracle.INPUT_SEED + 31).random((128, 128, 2))
    rows = []
    for code in oracle.ROUGHNESS_CODES:
        values, sample, path = oracle.noisy_sample(geometry['current']['point'], -geometry['current']['direction'],
            geometry['pose'], code / 1023., xi)
        need(np.isfinite(values).all() and np.all(values >= 0.), 'all actual stochastic path RGBA finite/nonnegative')
        need(np.all(values[..., 3] > 0.), 'active Monte Carlo pixels always have a positive actual hit or real-miss metric')
        need(np.array_equal(values[..., 3], path['distance'].astype('<f2')), 'hit A exact half conversion, no sentinel/zero mapping')
        below = sample['no_l'] <= 0.
        need(np.all(values[..., :3][below] == 0.), 'below-hemisphere BRDF contribution is exactly zero without renormalizing sample probability')
        need(np.all(values[..., 3][path['miss']] == np.float16(65504.)), 'every range/geometry miss is explicit')
        need(np.all(path['distance'][~path['miss']] <= oracle.RAY_MAX), 'all finite traced hits respect the declared max ray length')
        expected = (path['radiance'] * sample['weight'][..., None]).astype('<f2')
        need(np.array_equal(values[..., :3], expected), 'no artificial per-channel noise or inverse-PDF-only weighting')
        config = oracle.source_contract(code, 256)
        need(config['zero_roughness_used'] is False and config['reference_replicas'] == 2, 'only positive physical GGX with independent references')
        need(len(config['source_files']) == 7 and all(len(sha) == 64 for sha in config['source_files'].values()), 'all math/camera/official-source provenance hashes present')
        rows.append(dict(roughness=code / 1023., below_hemisphere=int(below.sum()), real_misses=int(path['miss'].sum()),
            nearest_ids={str(int(i)): int(n) for i, n in zip(*np.unique(path['object'], return_counts=True))}))
    result = dict(schema=oracle.SCHEMA + '-geometry-properties', checks=checks, rows=rows,
        gpu_executed=False, compiler_executed=False, production_changes=False)
    sealed.write_json(output, result)
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('E:/FSRD/sol_batch/15c-rr/ggx-geometry-properties.json'))
    run(parser.parse_args().output)


if __name__ == '__main__':
    main()
