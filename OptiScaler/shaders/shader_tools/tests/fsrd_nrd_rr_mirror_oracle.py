"""V4 decoded-normal, nearest-secondary-hit ideal-mirror control, CPU only.

V1/V2 remain immutable. Camera poses and mean-one noise distribution/seed match
V1; every V4 geometric/radiometric payload is rebuilt, not relabeled. The paired
roughness .12 is an intentional mirror-model mismatch, not rough-GGX truth.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

import fsrd_nrd_rr_material_quality as sealed


SCHEMA = 'fsrd-decoded-normal-nearest-mirror-v4'
SEED = 0x15E2026
WIDTH = HEIGHT = 128
COUNT = 64
NORMAL_RG = np.uint32(512 | (512 << 10))
ROUGH_012 = np.uint32(round(.12 * 1023))
EPSILON = 1e-6
BACKGROUND = np.array([0., 0., -8.])
LIGHT_POSITION = np.array([-1.5, 2., 2.5])
LIGHT_POWER = np.array([256., 224., 192.])
BASE = Path('F:/FSRD/sol_batch/15c-rr')
CANDIDATES = ('mirror-r0', 'negative-r012', 'diagnostic-reflected-mv')
CHECKS = 0


def need(condition, description):
    global CHECKS
    CHECKS += 1
    if not bool(condition):
        raise AssertionError(description)


def unpack_normal(word):
    oct_uv = np.array([int(word) & 1023, (int(word) >> 10) & 1023], np.float64) / 1023. * 2. - 1.
    normal = np.array([oct_uv[0], oct_uv[1], 1. - np.abs(oct_uv).sum()])
    normal[:2] += np.sign(normal[:2]) * np.clip(-normal[2], 0., 1.)
    return normal / np.linalg.norm(normal)


NORMAL = unpack_normal(NORMAL_RG)
TANGENT = np.cross([0., 1., 0.], NORMAL)
TANGENT /= np.linalg.norm(TANGENT)
BITANGENT = np.cross(NORMAL, TANGENT)


def primary(uv, pose):
    projection, camera = pose['projection'], pose['camera']
    direction = np.stack(((2. * uv[..., 0] - 1.) / projection[0, 0],
        (1. - 2. * uv[..., 1]) / projection[1, 1], -np.ones(uv.shape[:-1])), axis=-1) @ pose['rotation']
    direction /= np.linalg.norm(direction, axis=-1, keepdims=True)
    denominator = direction @ NORMAL
    background_t = np.dot(BACKGROUND - camera, NORMAL) / denominator
    foreground_t = np.dot(pose['center'] - camera, NORMAL) / denominator
    foreground_point = camera + direction * foreground_t[..., None]
    offset = foreground_point - pose['center']
    foreground = ((foreground_t > EPSILON) & (foreground_t < background_t) &
        (np.abs(offset @ TANGENT) <= .64) & (np.abs(offset @ BITANGENT) <= .95))
    distance = np.where(foreground, foreground_t, background_t)
    point = camera + direction * distance[..., None]
    return dict(point=point, direction=direction, object=foreground.astype('u1'), distance=distance)


def secondary(point, direction, pose, primary_id):
    shape = point.shape[:-1]
    denominator = direction @ NORMAL
    safe_denominator = np.where(np.abs(denominator) > 1e-15, denominator, 1.)
    candidates = []
    for identity, center in ((0, BACKGROUND), (1, pose['center'])):
        distance = ((center - point) @ NORMAL) / safe_denominator
        valid = ((np.abs(denominator) > 1e-15) & (distance > EPSILON) & (np.asarray(primary_id) != identity))
        if identity == 1:
            offset = point + direction * distance[..., None] - center
            valid &= (np.abs(offset @ TANGENT) <= .64) & (np.abs(offset @ BITANGENT) <= .95)
        candidates.append(np.where(valid, distance, np.inf))
    safe_z = np.where(np.abs(direction[..., 2]) > 1e-15, direction[..., 2], 1.)
    environment_t = (3. - point[..., 2]) / safe_z
    candidates.append(np.where((np.abs(direction[..., 2]) > 1e-15) & (environment_t > EPSILON), environment_t, np.inf))
    distances = np.stack(candidates, axis=-1)
    identity = np.argmin(distances, axis=-1).astype('u1')
    distance = np.take_along_axis(distances, identity[..., None], axis=-1)[..., 0]
    need(np.isfinite(distance).all() and np.all(distance > EPSILON), 'bounded control rays have a positive nearest scene hit')
    hit = point + direction * distance[..., None]
    local = np.where((identity == 1)[..., None], hit - pose['center'], hit)
    u, v = local @ TANGENT, local @ BITANGENT
    environment_u, environment_v = hit[..., 0], hit[..., 1]
    checker = .5 + .5 * np.tanh(5. * np.sin(environment_u * 8.) * np.sin(environment_v * 8.))
    thin = np.exp(-(np.sin(environment_u * 18. + environment_v * .6) / .10) ** 2)
    narrow = np.exp(-((environment_u - .7) ** 2 / .05 + (environment_v + .2) ** 2 / .7))
    environment_level = .025 + .055 * checker + .16 * thin + .12 * narrow
    # The front face of the translating rectangle is the primary mirror. Its
    # rear face is an emitter seen by secondary rays from the background.
    rear_level = .04 + .04 * (.5 + .5 * np.sin(u * 9.) * np.cos(v * 5.)) + .10 * np.exp(-(np.sin(u * 14. - v) / .12) ** 2)
    radiance = np.where((identity == 1)[..., None], rear_level[..., None] * [.95, .16, .04],
        np.where((identity == 2)[..., None], environment_level[..., None] * [.55, .82, 1.],
                 np.broadcast_to([.02, .03, .05], shape + (3,))))
    return dict(point=hit, distance=distance, object=identity, radiance=radiance, candidate_distances=distances)


def trace(uv, pose, project):
    hit = primary(uv, pose)
    direction = hit['direction']
    reflected = direction - 2. * (direction @ NORMAL)[..., None] * NORMAL
    indirect = secondary(hit['point'], reflected, pose, hit['object'])
    to_light = LIGHT_POSITION - hit['point']
    light_distance = np.linalg.norm(to_light, axis=-1)
    light_direction = to_light / light_distance[..., None]
    blocker = secondary(hit['point'], light_direction, pose, hit['object'])
    visible_light = blocker['distance'] >= light_distance - EPSILON
    # Separate unit-diffuse direct-lighting lobe. The test does not claim that
    # adding both unit-reflectance lobes forms an energy-conserving material.
    irradiance = LIGHT_POWER / (4. * math.pi * math.pi * light_distance[..., None] ** 2)
    diffuse = irradiance * np.maximum(light_direction @ NORMAL, 0.)[..., None] * visible_light[..., None]
    _, depth = project(hit['point'], pose)
    hit.update(spec=indirect['radiance'], diff=diffuse, spec_hit=indirect['distance'],
        diffuse_metric=light_distance, spec_secondary=indirect, signed_depth=depth,
        no_v=-(direction @ NORMAL), reflected_direction=reflected)
    return hit


def reflected_correspondence(current, pose, previous_pose, project):
    primary_id = current['object']
    emitter_id = current['spec_secondary']['object']
    secondary_point = current['spec_secondary']['point'].copy()
    secondary_point += (emitter_id == 1)[..., None] * (previous_pose['center'] - pose['center'])
    previous_plane_center = np.where((primary_id == 1)[..., None], previous_pose['center'], BACKGROUND)
    virtual = secondary_point - 2. * np.sum((secondary_point - previous_plane_center) * NORMAL, axis=-1, keepdims=True) * NORMAL
    direction = virtual - previous_pose['camera']
    fraction = np.sum((previous_plane_center - previous_pose['camera']) * NORMAL, axis=-1) / (direction @ NORMAL)
    previous_primary = previous_pose['camera'] + direction * fraction[..., None]
    uv, depth = project(previous_primary, previous_pose)
    old = trace(uv, previous_pose, project)
    valid = ((old['object'] == primary_id) & (old['spec_secondary']['object'] == emitter_id) &
        (np.linalg.norm(old['point'] - previous_primary, axis=-1) < 1e-7) &
        (np.linalg.norm(old['spec_secondary']['point'] - secondary_point, axis=-1) < 1e-7) &
        (uv[..., 0] >= 0.) & (uv[..., 0] < 1.) & (uv[..., 1] >= 0.) & (uv[..., 1] < 1.))
    return dict(uv=uv, depth=depth, valid=valid, previous_primary=previous_primary,
                previous_secondary=secondary_point, validated_secondary=old['spec_secondary']['point'])


def sequence(camera_source):
    original = sealed.original(Path('F:/FSRD/sol_batch/15e-quality/inputs'))
    camera = sealed.reference_oracle(camera_source, original['generator_sha256'])
    project = camera['project']
    rng = np.random.default_rng(SEED)
    y, x = np.mgrid[:HEIGHT, :WIDTH]
    screen = np.stack((x + .5, y + .5), axis=-1) / (WIDTH, HEIGHT)
    interior = (x >= 16) & (x < WIDTH - 16) & (y >= 16) & (y < HEIGHT - 16)
    previous = None
    for index in range(COUNT):
        pose = camera['pose'](index, WIDTH, HEIGHT)
        uv = screen - pose['jitter'] / (WIDTH, HEIGHT)
        current = trace(uv, pose, project)
        previous_pose = pose if previous is None else previous['pose']
        previous_point = current['point'] + current['object'][..., None] * (previous_pose['center'] - pose['center'])
        previous_uv, previous_depth = project(previous_point, previous_pose)
        canonical = (previous_uv - uv).astype('<f2')
        rr_xy = canonical.astype(np.float64) + (previous_pose['jitter'] - pose['jitter']) / (WIDTH, HEIGHT)
        rr_previous_uv = screen + rr_xy
        inside = (rr_previous_uv[..., 0] >= 0.) & (rr_previous_uv[..., 0] < 1.) & (rr_previous_uv[..., 1] >= 0.) & (rr_previous_uv[..., 1] < 1.)
        sx = np.clip(np.floor(rr_previous_uv[..., 0] * WIDTH).astype(int), 0, WIDTH - 1)
        sy = np.clip(np.floor(rr_previous_uv[..., 1] * HEIGHT).astype(int), 0, HEIGHT - 1)
        previous_visible = trace(previous_uv, previous_pose, project)
        same_visible = ((previous_visible['object'] == current['object']) &
                        (np.linalg.norm(previous_visible['point'] - previous_point, axis=-1) < 1e-7))
        motion = np.concatenate((rr_xy, (previous_depth - current['signed_depth'])[..., None], np.ones((HEIGHT, WIDTH, 1))), axis=-1).astype('<f2')
        reflected = reflected_correspondence(current, pose, previous_pose, project)
        diagnostic_canonical = (reflected['uv'] - uv).astype('<f2')
        diagnostic_xy = diagnostic_canonical.astype(np.float64) + (previous_pose['jitter'] - pose['jitter']) / (WIDTH, HEIGHT)
        diagnostic_b = reflected['depth'] - current['signed_depth']
        diagnostic = np.where(reflected['valid'][..., None],
            np.concatenate((diagnostic_xy, diagnostic_b[..., None], np.ones((HEIGHT, WIDTH, 1))), axis=-1), motion).astype('<f2')
        age = np.full((HEIGHT, WIDTH), 255, 'u1')
        ghost = {name: np.zeros((HEIGHT, WIDTH, 3), '<f2') for name in ('spec', 'diff')}
        revealed = inside & (current['object'] == 0) & (previous_visible['object'] == 1)
        if previous is None:
            revealed[:] = False
        else:
            revealed &= previous['object'][sy, sx] == 1
            carried = inside & same_visible & (previous['age'][sy, sx] < 32) & (current['object'] == 0)
            age[carried] = np.minimum(previous['age'][sy[carried], sx[carried]].astype(int) + 1, 32).astype('u1')
            for name in ghost:
                ghost[name][carried] = previous['ghost'][name][sy[carried], sx[carried]]
        age[revealed] = 0
        for name in ghost:
            ghost[name][revealed] = previous_visible[name][revealed]
        common, reference, outliers = {}, {}, {}
        for name, distance in (('spec', current['spec_hit']), ('diff', current['diffuse_metric'])):
            truth = current[name].astype('<f2')
            achromatic = rng.lognormal(-.5 * .34 ** 2, .34, (HEIGHT, WIDTH, 1))
            impulse = rng.random(truth.shape) < .004
            gain = np.where(impulse, 24., (1. - .004 * 24.) / (1. - .004))
            noisy = (truth.astype(np.float64) * achromatic * gain).astype('<f2')
            common[name] = np.concatenate((noisy, distance[..., None].astype('<f2')), axis=-1)
            reference[name] = truth
            outliers[name] = impulse.any(axis=-1).astype('u1')
        spec_albedo = np.full((HEIGHT, WIDTH, 4), 255, 'u1')
        spec_albedo[..., 3] = np.rint(current['no_v'] * 255.).astype('u1')
        diff_albedo = spec_albedo.copy()
        diff_albedo[..., 3] = 0
        common.update(depth=current['signed_depth'].astype('<f4'), motion=motion,
            normals=np.full((HEIGHT, WIDTH), NORMAL_RG, '<u4'), spec_albedo=spec_albedo, diff_albedo=diff_albedo)
        need(np.isfinite(current['spec_secondary']['distance']).all(), 'all one-bounce specular rays terminate at a real nearest scene surface')
        need(np.max(np.abs(np.sum((current['point'] - np.where(current['object'][..., None], pose['center'], BACKGROUND)) * NORMAL, axis=-1))) < 1e-12,
             'primary geometry uses exact decoded normal plane')
        need(np.max(np.abs(np.linalg.norm(current['reflected_direction'], axis=-1) - 1.)) < 1e-12, 'reflected ray is normalized')
        yield dict(frame=index + 2, index=index, pose=pose, current=current, common=common,
            reference=reference, ghost=ghost, reveal_age=age, reveal_mask=revealed.astype('u1'),
            object=current['object'], current_world=current['point'].astype('<f4'), previous_world=previous_point.astype('<f4'),
            previous_uv=previous_uv.astype('<f4'), rr_previous_uv=rr_previous_uv.astype('<f4'),
            reprojection_valid=inside.astype('u1'), surface_visible=same_visible.astype('u1'),
            previous_surface_depth=previous_depth.astype('<f4'), interior=interior.astype('u1'),
            canonical_motion=canonical, outliers=outliers, diagnostic_motion=diagnostic,
            reflected_previous_uv=reflected['uv'].astype('<f4'), reflected_valid=reflected['valid'].astype('u1'),
            secondary_world=current['spec_secondary']['point'].astype('<f4'), secondary_object=current['spec_secondary']['object'])
        previous = dict(pose=pose, object=current['object'], age=age, ghost=ghost)


def write_sequence(destination, camera_source):
    need(destination.resolve().is_relative_to(BASE.resolve()) and not destination.exists(), 'fresh V4 output stays inside this task scratch')
    destination.mkdir(parents=True)
    views = {name: destination / 'views' / name for name in CANDIDATES}
    for directory in views.values():
        directory.mkdir(parents=True)
    frames, numeric, secondary_counts = [], [f'{COUNT} {WIDTH} {HEIGHT}'], np.zeros(3, np.int64)
    reveal_pixels = reflected_valid_pixels = 0
    for item in sequence(camera_source):
        prefix = f'frame{item["frame"]:03d}'
        folder = destination / 'dataset' / prefix
        folder.mkdir(parents=True)
        payload = {name: sealed.put(folder, name + '.bin', data) for name, data in item['common'].items()}
        for name in ('spec', 'diff'):
            payload['reference_' + name] = sealed.put(folder, 'reference-' + name + '.bin', item['reference'][name])
            payload['ghost_' + name] = sealed.put(folder, 'ghost-' + name + '.bin', item['ghost'][name])
            payload['outliers_' + name] = sealed.put(folder, 'outliers-' + name + '.bin', item['outliers'][name])
        for name in ('reveal_age', 'reveal_mask', 'object', 'current_world', 'previous_world', 'previous_uv',
                     'rr_previous_uv', 'reprojection_valid', 'surface_visible', 'previous_surface_depth', 'interior',
                     'canonical_motion', 'diagnostic_motion', 'reflected_previous_uv', 'reflected_valid',
                     'secondary_world', 'secondary_object'):
            payload[name] = sealed.put(folder, name + '.bin', item[name])
        secondary_counts += np.bincount(item['secondary_object'][item['interior'].astype(bool)], minlength=3)
        reveal_pixels += int(item['reveal_mask'].sum())
        reflected_valid_pixels += int(item['reflected_valid'][item['interior'].astype(bool)].sum())
        for candidate, directory in views.items():
            current = directory / prefix
            current.mkdir()
            for name, value in item['common'].items():
                if name == 'normals' and candidate == 'negative-r012':
                    value = value | (ROUGH_012 << np.uint32(20))
                elif name == 'motion' and candidate == 'diagnostic-reflected-mv':
                    value = item['diagnostic_motion']
                (current / (name + '.bin')).write_bytes(np.ascontiguousarray(value).tobytes())
        p = item['pose']
        numbers = [item['frame'], item['index'], 0, int(item['index'] == 0)]
        numbers += list(p['view'].ravel()) + list(p['projection'].ravel()) + list(p['camera']) + list(p['jitter'])
        numeric.append(' '.join(format(float(value), '.17g') for value in numbers))
        frames.append(dict(frame=item['frame'], directory=prefix, payloads=payload))
    text = ('\n'.join(numeric) + '\n').encode('ascii')
    (destination / 'native-replay.txt').write_bytes(text)
    for directory in views.values():
        (directory / 'native-replay.txt').write_bytes(text)
    original = sealed.original(Path('F:/FSRD/sol_batch/15e-quality/inputs'))
    need(sealed.sha(text) == original['native_replay']['sha256'], 'V4 camera samples match the independently sealed V1 camera table exactly')
    manifest = dict(schema=SCHEMA, width=WIDTH, height=HEIGHT, submitted_frames=COUNT,
        comparison_crop=[16, 16, 96, 96], seed=SEED, source_v1_manifest_sha256=sealed.SOURCE_SHA,
        camera_source_sha256=sealed.file_sha(camera_source), generator_sha256=sealed.file_sha(Path(__file__)),
        native_replay=dict(file='native-replay.txt', bytes=len(text), sha256=sealed.sha(text)),
        views={name: str(path) for name, path in views.items()}, frames=frames,
        normal=dict(packed_rg=int(NORMAL_RG), decoded=NORMAL.tolist(), tangent=TANGENT.tolist(), bitangent=BITANGENT.tolist()),
        geometry='parallel decoded-normal static background plane and translating finite rectangle; full nearest secondary visibility with primary selfhit excluded; fixed emitter worldZ+3; rectangle rear face emissive/front mirror',
        radiance='unit specular perfect-mirror one-bounce emitted radiance; separate analytic point-light direct diffuse; per-lobe units, no energy-conserving combined-material claim',
        hit_alpha='spec actual nearest positive reflected-ray distance; DD actual positive point-light distance as active metric; no alpha0/sentinel remapping',
        motion='SDK primary material-point previous-current UV plus jitter once, previous signed viewZ-current viewZ; W1',
        diagnostic_motion='reflected-feature previous UV/Z only where exact previous mirror+secondary visibility agrees, primary fallback elsewhere; intentionally NOT SDK primary-surface semantics or production candidate',
        candidates={name: dict(roughness=float(ROUGH_012)/1023. if name == 'negative-r012' else 0.,
            interpretation='intentional ideal-mirror/nonzero-roughness guide mismatch negative' if name == 'negative-r012' else
                'nonproduction reflected-motion diagnostic' if name == 'diagnostic-reflected-mv' else 'coherent decoded-normal exact mirror control') for name in CANDIDATES},
        invariant='all candidate noisyRGB/hitA/depth/camera/albedo/normalRG/materialA identical; B only differs negative-r012; diagnostic view changes motion only',
        secondary_interior_counts=dict(background=int(secondary_counts[0]), foreground_back=int(secondary_counts[1]), environment=int(secondary_counts[2])),
        reveal_pixels=reveal_pixels, reflected_valid_interior_samples=reflected_valid_pixels,
        native_nrd_paired=False, game_fps_measured=False, rough_ggx_integrated_truth=False,
        production_files_changed=False, checks=CHECKS)
    sealed.write_json(destination / 'mirror-sequence.json', manifest)
    print(json.dumps({key: value for key, value in manifest.items() if key != 'frames'}, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=BASE / 'mirror-v4')
    # Frozen v1 generator source; the sealed manifest pins these bytes.
    parser.add_argument('--camera-source', type=Path, default=Path(__file__).resolve().parent / 'fsrd_nrd_motion_quality_oracle_v1_frozen.py')
    args = parser.parse_args()
    write_sequence(args.output, args.camera_source)


if __name__ == '__main__':
    main()
