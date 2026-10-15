"""CPU-batched positive-roughness one-bounce GGX scene/reference, V5 research.

Uses V4 decoded-normal geometry, actual nearest ray hits and explicit misses.
Noisy rays use bounded VNDF; independent reference uses GGX NDF inverse-CDF.
No production files, provider calls, shader compilation or rough0 shortcut.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np

import fsrd_nrd_rr_ggx_sampling as sampling
import fsrd_nrd_rr_material_quality as sealed
import fsrd_nrd_rr_mirror_oracle as scene


SCHEMA = 'fsrd-positive-ggx-nearest-surface-v5'
ROUGHNESS_CODES = (123, 307)
RAY_ORIGIN_OFFSET = 1e-5
RAY_MIN = 1e-7
RAY_MAX = 1024.
MISS_DISTANCE = 65504.
PIXEL_BATCH = 1024
SAMPLE_BATCH = 64
INPUT_SEED = 0x15C5100
REFERENCE_SEEDS = (0x15C5A001, 0x15C5B002)
CAMERA_SOURCE = Path('F:/OptiRevelations/OSA-15-nrd-ghosting/OptiScaler/shaders/shader_tools/tests/fsrd_nrd_motion_quality_oracle.py')


def nearest_emission(origins, directions, pose):
    """All actual surfaces, including below-hemisphere selfhit after offset.

    A real ray miss within the declared1024unit trace range carries65504. No
    native signal is remapped and no fictitious finite geometry is invented.
    """
    denominator = directions @ scene.NORMAL
    safe = np.where(np.abs(denominator) > 1e-15, denominator, 1.)
    candidates = []
    for identity, center in ((0, scene.BACKGROUND), (1, pose['center'])):
        distance = ((center - origins) @ scene.NORMAL) / safe
        valid = (np.abs(denominator) > 1e-15) & (distance > RAY_MIN) & (distance <= RAY_MAX)
        if identity == 1:
            point = origins + directions * distance[..., None] - center
            valid &= (np.abs(point @ scene.TANGENT) <= .64) & (np.abs(point @ scene.BITANGENT) <= .95)
        candidates.append(np.where(valid, distance, np.inf))
    z = directions[..., 2]
    t_environment = (3. - origins[..., 2]) / np.where(np.abs(z) > 1e-15, z, 1.)
    candidates.append(np.where((np.abs(z) > 1e-15) & (t_environment > RAY_MIN) & (t_environment <= RAY_MAX), t_environment, np.inf))
    distances = np.stack(candidates, axis=-1)
    identity = np.argmin(distances, axis=-1).astype('u1')
    distance = np.take_along_axis(distances, identity[..., None], axis=-1)[..., 0]
    hit = np.isfinite(distance)
    point = origins + directions * np.where(hit, distance, 0.)[..., None]
    identity = np.where(hit, identity, np.uint8(255)).astype('u1')
    environment_u, environment_v = point[..., 0], point[..., 1]
    checker = .5 + .5 * np.tanh(5. * np.sin(environment_u * 8.) * np.sin(environment_v * 8.))
    thin = np.exp(-(np.sin(environment_u * 18. + environment_v * .6) / .10) ** 2)
    narrow = np.exp(-((environment_u - .7) ** 2 / .05 + (environment_v + .2) ** 2 / .7))
    environment_level = .025 + .055 * checker + .16 * thin + .12 * narrow
    local = point - pose['center']
    u, v = local @ scene.TANGENT, local @ scene.BITANGENT
    rear_level = .04 + .04 * (.5 + .5 * np.sin(u * 9.) * np.cos(v * 5.)) + .10 * np.exp(-(np.sin(u * 14. - v) / .12) ** 2)
    front_or_background = np.zeros(point.shape, np.float64)
    # Only the rectangle rear emits. A below-surface ray sees the nonemissive
    # primary front and its BRDF contribution is zero, not a discarded sample.
    radiance = np.where(((identity == 1) & (denominator > 0.))[..., None], rear_level[..., None] * [.95, .16, .04],
        np.where((identity == 2)[..., None], environment_level[..., None] * [.55, .82, 1.],
            np.where((identity == 255)[..., None], np.broadcast_to([.025, .035, .045], point.shape), front_or_background)))
    return dict(radiance=radiance, distance=np.where(hit, distance, MISS_DISTANCE),
                object=identity, point=point, miss=~hit)


def integrate_reference(points, to_camera, pose, roughness, samples, seed):
    """One deterministic, independently randomized high-spp NDF estimator.

    Only one pixel/sample tile is resident. A second independent call records
    reference disagreement; it is never used to tune the candidate/noisy rays.
    """
    shape = points.shape[:-1]
    points = np.asarray(points, np.float64).reshape(-1, 3)
    view = np.asarray(to_camera, np.float64).reshape(-1, 3)
    shifts = np.random.default_rng(seed).random((len(points), 2))
    base = sampling.reference_points(samples)
    result = np.zeros((len(points), 3), np.float64)
    miss_count = invalid_count = 0
    for first in range(0, len(points), PIXEL_BATCH):
        stop = min(first + PIXEL_BATCH, len(points))
        origin = points[first:stop, None, :] + scene.NORMAL * RAY_ORIGIN_OFFSET
        v = view[first:stop, None, :]
        total = np.zeros((stop - first, 3), np.float64)
        for begin in range(0, samples, SAMPLE_BATCH):
            xi = np.mod(base[None, begin:begin + SAMPLE_BATCH, :] + shifts[first:stop, None, :], 1.)
            sample = sampling.ndf_reference(v, roughness, xi)
            ray = nearest_emission(origin, sample['direction'], pose)
            contribution = ray['radiance'] * sample['weight'][..., None]
            if not np.isfinite(contribution).all():
                raise AssertionError('physical GGX reference contributions must stay finite')
            total += np.sum(contribution, axis=1)
            miss_count += int(np.count_nonzero(ray['miss']))
            invalid_count += int(np.count_nonzero(sample['no_l'] <= 0.))
        result[first:stop] = total / samples
    return result.reshape(shape + (3,)), dict(samples=samples, rays=len(points) * samples,
        explicit_range_misses=miss_count, below_hemisphere_zero_contributions=invalid_count)


def noisy_sample(points, to_camera, pose, roughness, xi):
    sample = sampling.bounded_vndf(to_camera, roughness, xi)
    ray = nearest_emission(points + scene.NORMAL * RAY_ORIGIN_OFFSET, sample['direction'], pose)
    lighting = ray['radiance'] * sample['weight'][..., None]
    if not np.isfinite(lighting).all() or not np.isfinite(ray['distance']).all():
        raise AssertionError('all actual path RGB/A finite')
    return np.concatenate((lighting, ray['distance'][..., None]), axis=-1).astype('<f2'), sample, ray


def camera_api():
    original = sealed.original(Path('F:/FSRD/sol_batch/15e-quality/inputs'))
    return sealed.reference_oracle(CAMERA_SOURCE, original['generator_sha256'])


def frame_geometry(index, camera):
    pose = camera['pose'](index, scene.WIDTH, scene.HEIGHT)
    previous_pose = camera['pose'](max(0, index - 1), scene.WIDTH, scene.HEIGHT)
    y, x = np.mgrid[:scene.HEIGHT, :scene.WIDTH]
    screen = np.stack((x + .5, y + .5), axis=-1) / (scene.WIDTH, scene.HEIGHT)
    uv = screen - pose['jitter'] / (scene.WIDTH, scene.HEIGHT)
    current = scene.trace(uv, pose, camera['project'])
    previous_point = current['point'] + current['object'][..., None] * (previous_pose['center'] - pose['center'])
    previous_uv, previous_depth = camera['project'](previous_point, previous_pose)
    previous_visible = scene.trace(previous_uv, previous_pose, camera['project'])
    canonical = (previous_uv - uv).astype('<f2')
    rr_xy = canonical.astype(np.float64) + (previous_pose['jitter'] - pose['jitter']) / (scene.WIDTH, scene.HEIGHT)
    sample_uv = screen + rr_xy
    inside = (sample_uv[..., 0] >= 0.) & (sample_uv[..., 0] < 1.) & (sample_uv[..., 1] >= 0.) & (sample_uv[..., 1] < 1.)
    sx = np.clip(np.floor(sample_uv[..., 0] * scene.WIDTH).astype(int), 0, scene.WIDTH - 1)
    sy = np.clip(np.floor(sample_uv[..., 1] * scene.HEIGHT).astype(int), 0, scene.HEIGHT - 1)
    same = ((previous_visible['object'] == current['object']) & (np.linalg.norm(previous_visible['point'] - previous_point, axis=-1) < 1e-7))
    motion = np.concatenate((rr_xy, (previous_depth - current['signed_depth'])[..., None], np.ones((scene.HEIGHT, scene.WIDTH, 1))), axis=-1).astype('<f2')
    return dict(pose=pose, previous_pose=previous_pose, current=current, previous_point=previous_point,
        previous_uv=previous_uv, previous_depth=previous_depth, previous_visible=previous_visible,
        motion=motion, canonical=canonical, sample_uv=sample_uv, inside=inside, same=same, sx=sx, sy=sy)


def source_contract(code, samples):
    root = Path(__file__).resolve().parents[4]
    official = root / 'external/FidelityFX-SDK-v2/Samples/Denoisers/FidelityFX_Denoiser/dx12/shaders'
    sources = {str(path): sealed.file_sha(path) for path in
        (Path(__file__), Path(sampling.__file__), Path(scene.__file__), Path(sealed.__file__), CAMERA_SOURCE,
         official / 'importance_sampling.hlsl', official / 'trace_rays_denoiser.hlsl')}
    return dict(schema=SCHEMA, code=code, roughness=code / 1023., width=scene.WIDTH, height=scene.HEIGHT,
        count=scene.COUNT, reference_samples_per_replica=samples, reference_replicas=2,
        reference_seeds=list(REFERENCE_SEEDS), input_seed=INPUT_SEED, input_spp=1,
        source_files=sources, ray_origin_offset=RAY_ORIGIN_OFFSET, ray_min=RAY_MIN,
        ray_max=RAY_MAX, true_miss_alpha=MISS_DISTANCE, normal=scene.NORMAL.tolist(),
        reference_sampling='independent NDF inverse-CDF QMC with independent per-pixel Cranley-Patterson shifts; both replicas preserved',
        noisy_sampling='bounded VNDF with matching GGX PDF, F=1D*SmithVisibility*NoL/pdf; no added channel/intensity noise',
        albedo_guide='pinned AMD rational ApproximateBRDF forF0=1 and actual packed roughness/NoV; diffuseRGB1; linearRGBA8',
        independent_diffuse='analytic direct point-light reference/input control, no added artificial noise',
        units='declared synthetic world and pre-Consumer64 radiance units; no native-meter/exposure inference',
        sample_demo_boundary='SDK demo D_GGX(alpha)/.5pdf is retained in sampling calibration only, not used as physical estimator',
        zero_roughness_used=False, native_nrd_paired=False, game_fps_measured=False)


def prepare_frame(root, index, code, samples, config, camera):
    prefix = f'frame{index + 2:03d}'
    folder = root / 'dataset' / prefix
    metadata_file = folder / 'frame.json'
    if folder.exists():
        if not metadata_file.exists():
            raise AssertionError('partial frame evidence exists; use a fresh research root for a repaired attempt')
        data = json.loads(metadata_file.read_bytes())
        if data['config_sha256'] != sealed.sha(json.dumps(config, sort_keys=True).encode()):
            raise AssertionError('existing frame belongs to different source/configuration')
        return data
    folder.mkdir(parents=True)
    geometry = frame_geometry(index, camera)
    current, pose, old_pose = geometry['current'], geometry['pose'], geometry['previous_pose']
    roughness = code / 1023.
    xi = np.random.default_rng(INPUT_SEED + index).random((scene.HEIGHT, scene.WIDTH, 2))
    noisy, sample, ray = noisy_sample(current['point'], -current['direction'], pose, roughness, xi)
    refs, infos = [], []
    for seed in REFERENCE_SEEDS:
        reference, info = integrate_reference(current['point'], -current['direction'], pose, roughness, samples, seed + index)
        refs.append(reference)
        infos.append(info)
    age = np.full((scene.HEIGHT, scene.WIDTH), 255, 'u1')
    ghost_a = np.zeros((scene.HEIGHT, scene.WIDTH, 3), np.float64)
    ghost_b = ghost_a.copy()
    ghost_diff = ghost_a.copy()
    reveal = geometry['inside'] & (current['object'] == 0) & (geometry['previous_visible']['object'] == 1)
    if index == 0:
        reveal[:] = False
    else:
        previous = json.loads((root / 'dataset' / f'frame{index + 1:03d}' / 'frame.json').read_bytes())
        old_folder = root / 'dataset' / previous['directory']
        old = {name: sealed.load(old_folder, previous['payloads'][name]) for name in
            ('object', 'reveal_age', 'ghost_spec_a', 'ghost_spec_b', 'ghost_diff')}
        sy, sx = geometry['sy'], geometry['sx']
        reveal &= old['object'][sy, sx] == 1
        carried = geometry['inside'] & geometry['same'] & (old['reveal_age'][sy, sx] < 32) & (current['object'] == 0)
        age[carried] = np.minimum(old['reveal_age'][sy[carried], sx[carried]].astype(int) + 1, 32).astype('u1')
        ghost_a[carried] = old['ghost_spec_a'][sy[carried], sx[carried]]
        ghost_b[carried] = old['ghost_spec_b'][sy[carried], sx[carried]]
        ghost_diff[carried] = old['ghost_diff'][sy[carried], sx[carried]]
    age[reveal] = 0
    ghost_info = []
    if np.any(reveal):
        old_points = geometry['previous_visible']['point'][reveal]
        old_view = -geometry['previous_visible']['direction'][reveal]
        for replica, seed in enumerate(REFERENCE_SEEDS):
            previous_value, info = integrate_reference(old_points, old_view, old_pose, roughness, samples, seed + 0x100000 + index)
            (ghost_a if replica == 0 else ghost_b)[reveal] = previous_value
            ghost_info.append(info)
        ghost_diff[reveal] = geometry['previous_visible']['diff'][reveal]
    no_v = current['no_v']
    albedo = sealed.ggx_albedo(np.ones((scene.HEIGHT, scene.WIDTH, 3)), np.ones((scene.HEIGHT, scene.WIDTH)), roughness, no_v)
    spec_albedo = np.concatenate((np.rint(np.clip(albedo, 0., 1.) * 255.).astype('u1'),
        np.zeros((scene.HEIGHT, scene.WIDTH, 1), 'u1')), axis=-1)
    diff_albedo = np.full((scene.HEIGHT, scene.WIDTH, 4), 255, 'u1')
    diff_albedo[..., 3] = 0
    common = dict(spec=noisy, diff=np.concatenate((current['diff'], current['diffuse_metric'][..., None]), axis=-1).astype('<f2'),
        depth=current['signed_depth'].astype('<f4'), motion=geometry['motion'],
        normals=np.full((scene.HEIGHT, scene.WIDTH), scene.NORMAL_RG | (np.uint32(code) << np.uint32(20)), '<u4'),
        spec_albedo=spec_albedo, diff_albedo=diff_albedo)
    arrays = dict(common, reference_spec=((refs[0] + refs[1]) * .5).astype('<f4'),
        reference_spec_a=refs[0].astype('<f4'), reference_spec_b=refs[1].astype('<f4'), reference_diff=current['diff'].astype('<f4'),
        ghost_spec=((ghost_a + ghost_b) * .5).astype('<f4'), ghost_spec_a=ghost_a.astype('<f4'), ghost_spec_b=ghost_b.astype('<f4'),
        ghost_diff=ghost_diff.astype('<f4'), reveal_age=age, reveal_mask=reveal.astype('u1'), object=current['object'],
        current_world=current['point'].astype('<f4'), previous_world=geometry['previous_point'].astype('<f4'),
        previous_uv=geometry['previous_uv'].astype('<f4'), rr_previous_uv=geometry['sample_uv'].astype('<f4'),
        reprojection_valid=geometry['inside'].astype('u1'), surface_visible=geometry['same'].astype('u1'),
        previous_surface_depth=geometry['previous_depth'].astype('<f4'), canonical_motion=geometry['canonical'],
        interior=np.pad(np.ones((96, 96), 'u1'), ((16, 16), (16, 16))),
        secondary_world=ray['point'].astype('<f4'), secondary_object=ray['object'],
        sampled_direction=sample['direction'].astype('<f4'), sampled_weight=sample['weight'].astype('<f4'),
        sampled_pdf=sample['pdf'].astype('<f4'), below_hemisphere=(sample['no_l'] <= 0.).astype('u1'), real_miss=ray['miss'].astype('u1'))
    for value in arrays.values():
        if not np.isfinite(value).all():
            raise AssertionError('all V5 finite stored signal/geometry/reference payloads')
    payloads = {name: sealed.put(folder, name + '.bin', value) for name, value in arrays.items()}
    native = root / 'views' / f'ggx-r{code}' / prefix
    native.mkdir(parents=True)
    for name in common:
        sealed.immutable(native / (name + '.bin'), (folder / payloads[name]['file']).read_bytes())
    crop = np.s_[16:112, 16:112]
    metadata = dict(frame=index + 2, directory=prefix, payloads=payloads,
        config_sha256=sealed.sha(json.dumps(config, sort_keys=True).encode()),
        reference_replicas=infos, ghost_reference_replicas=ghost_info,
        replica_difference_rgb_rmse=float(np.sqrt(np.mean((refs[0][crop] - refs[1][crop]) ** 2))),
        raw_to_reference_rgb_rmse=float(np.sqrt(np.mean((noisy[crop][..., :3].astype(np.float64) - arrays['reference_spec'][crop]) ** 2))),
        input_below_hemisphere=int(np.count_nonzero(sample['no_l'] <= 0.)), input_real_misses=int(np.count_nonzero(ray['miss'])),
        reveal_pixels=int(np.count_nonzero(reveal)))
    sealed.write_json(metadata_file, metadata)
    return metadata


def prepare_chunk(destination, code, first, count, samples):
    if code not in ROUGHNESS_CODES or not 0 <= first < scene.COUNT or not 1 <= count <= 8 or first + count > scene.COUNT:
        raise ValueError('bounded V5 positive-roughness case and <=8 consecutive frames')
    if samples < 64 or samples > 4096 or not destination.resolve().is_relative_to(scene.BASE.resolve()):
        raise ValueError('bounded independent reference samples and task-local output')
    root = destination / f'r{code}'
    root.mkdir(parents=True, exist_ok=True)
    config = source_contract(code, samples)
    sealed.immutable(root / 'config.json', (json.dumps(config, indent=2, sort_keys=True) + '\n').encode())
    original = sealed.original(Path('F:/FSRD/sol_batch/15e-quality/inputs'))
    camera_table = (Path('F:/FSRD/sol_batch/15e-quality/inputs') / original['native_replay']['file']).read_bytes()
    view = root / 'views' / f'ggx-r{code}'
    sealed.immutable(view / 'native-replay.txt', camera_table)
    sealed.immutable(root / 'native-replay.txt', camera_table)
    camera = camera_api()
    begin = time.perf_counter()
    rows = []
    for index in range(first, first + count):
        frame_begin = time.perf_counter()
        metadata = prepare_frame(root, index, code, samples, config, camera)
        rows.append(metadata)
        print(json.dumps(dict(frame=metadata['frame'], roughness=code / 1023., elapsed_seconds=time.perf_counter() - frame_begin,
            replica_difference_rgb_rmse=metadata['replica_difference_rgb_rmse'], input_real_misses=metadata['input_real_misses'])), flush=True)
    result = dict(schema=SCHEMA + '-chunk', code=code, first=first, count=count,
        reference_samples_per_replica=samples, elapsed_seconds=time.perf_counter() - begin,
        frames=[row['frame'] for row in rows], gpu_executed=False, compiler_executed=False)
    sealed.write_json(root / f'chunk-{first:03d}-{first + count - 1:03d}.json', result)
    if first + count == scene.COUNT:
        frames = [json.loads((root / 'dataset' / f'frame{index + 2:03d}' / 'frame.json').read_bytes()) for index in range(scene.COUNT)]
        manifest = dict(config, submitted_frames=scene.COUNT, comparison_crop=[16, 16, 96, 96],
            views={f'ggx-r{code}': str(view)}, frames=frames,
            native_replay=original['native_replay'], source_v1_manifest_sha256=sealed.SOURCE_SHA,
            reference_uncertainty='two independently randomized NDF replicas saved perframe; compare candidate pairedMSE againstBOTH; no winner below uncertainty')
        sealed.write_json(root / 'ggx-sequence.json', manifest)
        result['manifest_sha256'] = sealed.file_sha(root / 'ggx-sequence.json')
    print(json.dumps(result, indent=2))


def pilot(output, samples=64):
    original = sealed.original(Path('F:/FSRD/sol_batch/15e-quality/inputs'))
    camera = sealed.reference_oracle(CAMERA_SOURCE, original['generator_sha256'])
    pose = camera['pose'](0, scene.WIDTH, scene.HEIGHT)
    y, x = np.mgrid[:scene.HEIGHT, :scene.WIDTH]
    uv = (np.stack((x + .5, y + .5), axis=-1) - pose['jitter']) / (scene.WIDTH, scene.HEIGHT)
    current = scene.primary(uv, pose)
    view = -current['direction']
    xi = np.random.default_rng(INPUT_SEED).random((scene.HEIGHT, scene.WIDTH, 2))
    rows = []
    for code in ROUGHNESS_CODES:
        roughness = code / 1023.
        noisy, sample, ray = noisy_sample(current['point'], view, pose, roughness, xi)
        begin = time.perf_counter()
        a, a_info = integrate_reference(current['point'], view, pose, roughness, samples, REFERENCE_SEEDS[0])
        b, b_info = integrate_reference(current['point'], view, pose, roughness, samples, REFERENCE_SEEDS[1])
        elapsed = time.perf_counter() - begin
        crop = np.s_[16:112, 16:112]
        rows.append(dict(roughness=roughness, samples_per_replica=samples, replicas=2,
            reference_seconds=elapsed, reference_a=a_info, reference_b=b_info,
            replica_difference_rgb_rmse=float(np.sqrt(np.mean((a[crop] - b[crop]) ** 2))),
            reference_mean=float(np.mean((a[crop] + b[crop]) * .5)),
            raw_to_reference_rgb_rmse=float(np.sqrt(np.mean((noisy[crop][..., :3].astype(np.float64) - (a[crop] + b[crop]) * .5) ** 2))),
            input_below_hemisphere=int(np.count_nonzero(sample['no_l'] <= 0.)),
            input_real_misses=int(np.count_nonzero(ray['miss'])),
            input_nearest_hit_counts={str(int(value)): int(count) for value, count in zip(*np.unique(ray['object'], return_counts=True))},
            reference_full64_seconds_linear_forecast=elapsed * scene.COUNT))
    result = dict(schema=SCHEMA + '-cpu-pilot', samples=samples, rows=rows,
        note='pilot forecasts only; no full-reference quality/FPS/ground-truth convergence claim',
        roughness_zero_used=False, reference_sampling='independent GGX half-vector NDF with correct BRDF*cos/pdf',
        noisy_sampling='1spp bounded VNDF with matching correct PDF and BRDF*cos/pdf; no fake multiplicative/channel noise',
        gpu_executed=False, compiler_executed=False, production_changes=False)
    sealed.write_json(output, result)
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', action='store_true')
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--code', type=int, choices=ROUGHNESS_CODES, default=123)
    parser.add_argument('--first', type=int, default=0)
    parser.add_argument('--count', type=int, default=8)
    parser.add_argument('--samples', type=int, default=64)
    parser.add_argument('--output', type=Path, default=Path('E:/FSRD/sol_batch/15c-rr/ggx-reference-pilot.json'))
    args = parser.parse_args()
    if args.pilot == args.prepare:
        raise ValueError('select exactly one CPU pilot or bounded preparation action')
    if args.pilot:
        pilot(args.output, args.samples)
    else:
        prepare_chunk(args.output, args.code, args.first, args.count, args.samples)


if __name__ == '__main__':
    main()
