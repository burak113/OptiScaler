"""Independent analytic geometry and immutable V4 mirror payload checks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import fsrd_nrd_rr_material_quality as sealed
import fsrd_nrd_rr_mirror_oracle as mirror


def scalar_plane(origin, direction, center, normal):
    denominator = sum(float(direction[i]) * float(normal[i]) for i in range(3))
    if abs(denominator) <= 1e-15:
        return float('inf')
    value = sum((float(center[i]) - float(origin[i])) * float(normal[i]) for i in range(3)) / denominator
    return value if value > mirror.EPSILON else float('inf')


def scalar_secondary(origin, direction, primary_id, pose):
    distances = []
    for identity, center in ((0, mirror.BACKGROUND), (1, pose['center'])):
        distance = scalar_plane(origin, direction, center, mirror.NORMAL)
        if identity == primary_id:
            distance = float('inf')
        if identity == 1 and np.isfinite(distance):
            point = origin + direction * distance - center
            if abs(float(np.dot(point, mirror.TANGENT))) > .64 or abs(float(np.dot(point, mirror.BITANGENT))) > .95:
                distance = float('inf')
        distances.append(distance)
    distances.append(scalar_plane(origin, direction, np.array([0., 0., 3.]), np.array([0., 0., 1.])))
    identity = int(np.argmin(distances))
    return identity, distances[identity]


def properties(camera_source):
    expected = np.array([1., 1., 1021.])
    expected /= np.linalg.norm(expected)
    mirror.need(np.array_equal(mirror.NORMAL, mirror.unpack_normal(mirror.NORMAL_RG)), 'decoded normal is stable')
    mirror.need(np.max(np.abs(mirror.NORMAL - expected)) < 1e-15, 'independent integer-ratio oct normal')
    basis = np.stack((mirror.TANGENT, mirror.BITANGENT, mirror.NORMAL))
    mirror.need(np.max(np.abs(basis @ basis.T - np.eye(3))) < 1e-15, 'plane tangent basis orthonormal')
    source = sealed.original(Path('F:/FSRD/sol_batch/15e-quality/inputs'))
    old = sealed.reference_oracle(camera_source, source['generator_sha256'])
    pose = old['pose'](0, mirror.WIDTH, mirror.HEIGHT)
    points = np.array([mirror.BACKGROUND, mirror.BACKGROUND + mirror.TANGENT * 3.,
        pose['center'], pose['center'] + mirror.TANGENT * .3])
    directions = np.broadcast_to(mirror.NORMAL, points.shape).copy()
    identities = np.array([0, 0, 1, 1])
    result = mirror.secondary(points, directions, pose, identities)
    mirror.need(list(result['object']) == [1, 2, 2, 2], 'nearest foreground rear hit versus environment and excluded selfhit')
    mirror.need(result['distance'][0] < result['candidate_distances'][0, 2], 'foreground is strictly before environment, not overwritten by a remote A')
    mirror.need(result['radiance'][0, 0] > result['radiance'][0, 2], 'near foreground rear emits defined warm radiance')
    for index, (point, direction, identity) in enumerate(zip(points, directions, identities)):
        distances = []
        for target, center in ((0, mirror.BACKGROUND), (1, pose['center'])):
            distance = scalar_plane(point, direction, center, mirror.NORMAL)
            if target == identity:
                distance = float('inf')
            if target == 1 and np.isfinite(distance):
                local = point + direction * distance - center
                if abs(float(np.dot(local, mirror.TANGENT))) > .64 or abs(float(np.dot(local, mirror.BITANGENT))) > .95:
                    distance = float('inf')
            distances.append(distance)
        distances.append(scalar_plane(point, direction, np.array([0., 0., 3.]), np.array([0., 0., 1.])))
        mirror.need(np.argmin(distances) == result['object'][index], 'scalar nearest scene identity matches vector trace')
        mirror.need(abs(min(distances) - result['distance'][index]) < 1e-12, 'scalar nearest distance matches vector trace')
    uv = np.array([[.5, .5], [.1, .2], [.75, .84]])
    hit = mirror.primary(uv, pose)
    reflected = hit['direction'] - 2. * (hit['direction'] @ mirror.NORMAL)[..., None] * mirror.NORMAL
    mirror.need(np.max(np.abs((hit['direction'] + reflected) @ mirror.NORMAL)) < 1e-15, 'equal incidence/reflection angle about decoded normal')
    mirror.need(np.max(np.abs(np.linalg.norm(reflected, axis=-1) - 1.)) < 1e-15, 'reflected unit direction')
    projected, _ = old['project'](hit['point'], pose)
    mirror.need(np.max(np.abs(projected - uv)) < 1e-15, 'independent scene primary hits reproject to requested rays')
    probability = .004
    ordinary_gain = (1. - probability * 24.) / (1. - probability)
    mirror.need(abs(probability * 24. + (1. - probability) * ordinary_gain - 1.) < 1e-15,
                'rare channel-gain noise has analytical expectation one')
    rng = np.random.default_rng(0x4C15)
    scalar_cases = 0
    for index in (0, 23, 47, 63):
        current_pose = old['pose'](index, mirror.WIDTH, mirror.HEIGHT)
        sample_uv = rng.uniform(0., 1., (100, 2))
        current = mirror.trace(sample_uv, current_pose, old['project'])
        for ray_index in range(len(sample_uv)):
            identity, distance = scalar_secondary(current['point'][ray_index], current['reflected_direction'][ray_index],
                                                   current['object'][ray_index], current_pose)
            mirror.need(identity == current['spec_secondary']['object'][ray_index], 'independent scalar nearest object over four moving poses')
            mirror.need(abs(distance - current['spec_hit'][ray_index]) < 1e-12, 'independent scalar nearest reflected distance over four moving poses')
            mirror.need(np.float16(distance).view('<u2') == np.float16(current['spec_hit'][ray_index]).view('<u2'), 'exact half metric quantization from scalar first hit')
            scalar_cases += 1
    return dict(checks=mirror.CHECKS, normal=mirror.NORMAL.tolist(),
                nearest_secondary_case_ids=result['object'].tolist(), scalar_dynamic_cases=scalar_cases,
                gpu_executed=False, compiler_executed=False)


def validate(prepared, camera_source):
    manifest = json.loads((prepared / 'mirror-sequence.json').read_bytes())
    mirror.need(manifest['schema'] == mirror.SCHEMA, 'V4 exact schema')
    mirror.need(manifest['generator_sha256'] == sealed.file_sha(Path(mirror.__file__)), 'generator source hash belongs to prepared data')
    mirror.need(manifest['camera_source_sha256'] == sealed.file_sha(camera_source), 'frozen camera source hash')
    mirror.need(tuple(manifest['views']) == mirror.CANDIDATES and len(manifest['frames']) == 64, 'all three complete paired/diagnostic histories')
    original = sealed.original(Path('F:/FSRD/sol_batch/15e-quality/inputs'))
    mirror.need(manifest['source_v1_manifest_sha256'] == sealed.SOURCE_SHA, 'V1 camera/noise provenance retained, not altered')
    for directory in manifest['views'].values():
        mirror.need(sealed.file_sha(Path(directory) / 'native-replay.txt') == original['native_replay']['sha256'], 'same native camera table across all candidates')
    previous_frame = 1
    counts = np.zeros(3, np.int64)
    reveals = valid_reflections = 0
    for frame in manifest['frames']:
        mirror.need(frame['frame'] == previous_frame + 1, 'continuous frame samples2..65')
        previous_frame = frame['frame']
        folder = prepared / 'dataset' / frame['directory']
        data = {name: sealed.load(folder, record) for name, record in frame['payloads'].items()}
        for signal in ('spec', 'diff'):
            mirror.need(np.isfinite(data[signal]).all() and np.all(data[signal] >= 0), 'finite positive RGB and actual active metrics')
            mirror.need(np.isfinite(data['reference_' + signal]).all() and np.all(data['reference_' + signal] >= 0), 'finite independent lighting reference')
        mirror.need(np.all(data['spec'][..., 3] > 0) and np.all(data['spec'][..., 3] < 65504), 'finite real first hits, no synthetic miss sentinel')
        mirror.need(np.all(data['normals'] == mirror.NORMAL_RG), 'actual decoded normal and exact roughness0')
        mirror.need(np.all(data['motion'][..., 3] == np.float16(1.)), 'primary packet W remains one')
        interior = data['interior'].astype(bool)
        counts += np.bincount(data['secondary_object'][interior], minlength=3)
        reveals += int(data['reveal_mask'].sum())
        valid_reflections += int(data['reflected_valid'][interior].sum())
        for candidate, directory in manifest['views'].items():
            current = Path(directory) / frame['directory']
            for name in ('spec', 'diff', 'depth', 'spec_albedo', 'diff_albedo'):
                mirror.need(sealed.file_sha(current / (name + '.bin')) == frame['payloads'][name]['sha256'],
                            'all candidate lighting/noise/A/depth/albedo payloads are byte-identical')
            normal = np.fromfile(current / 'normals.bin', '<u4').reshape(128, 128)
            expected = data['normals'] | (mirror.ROUGH_012 << np.uint32(20)) if candidate == 'negative-r012' else data['normals']
            mirror.need(np.array_equal(normal, expected), 'only declared B0/123 differs; RG and materialA exact')
            motion = data['diagnostic_motion'] if candidate == 'diagnostic-reflected-mv' else data['motion']
            mirror.need((current / 'motion.bin').read_bytes() == np.ascontiguousarray(motion).tobytes(),
                        'primary motion identical except explicitly labeled nonproduction reflected diagnostic')
    mirror.need(counts[1] > 0 and counts[2] > counts[1], 'nearest-hit scene contains both foreground and environment secondary hits')
    mirror.need(counts.tolist() == [manifest['secondary_interior_counts'][key] for key in ('background', 'foreground_back', 'environment')],
                'all reported nearest secondary counts are from exact stored identities')
    mirror.need(reveals == manifest['reveal_pixels'] > 0, 'new independent reveal cohort has actual support')
    mirror.need(valid_reflections == manifest['reflected_valid_interior_samples'] > 0, 'reflected correspondence has separately attested support')
    return dict(schema=mirror.SCHEMA, prepared_manifest_sha256=sealed.file_sha(prepared / 'mirror-sequence.json'),
        checks=mirror.CHECKS, sealed_payload_checks=sealed.CHECKS, secondary_interior_counts=counts.tolist(),
        reveal_pixels=reveals, reflected_valid_interior_samples=valid_reflections,
        gpu_executed=False, compiler_executed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--camera-source', type=Path, default=Path('F:/OptiRevelations/OSA-15-nrd-ghosting/OptiScaler/shaders/shader_tools/tests/fsrd_nrd_motion_quality_oracle.py'))
    parser.add_argument('--output', type=Path, default=Path('E:/FSRD/sol_batch/15c-rr/mirror-properties.json'))
    args = parser.parse_args()
    result = validate(args.prepared, args.camera_source) if args.prepared else properties(args.camera_source)
    sealed.write_json(args.output, result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
