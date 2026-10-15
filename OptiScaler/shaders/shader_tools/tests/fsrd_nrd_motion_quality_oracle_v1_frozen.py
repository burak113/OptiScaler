"""Independent world-surface temporal oracle, not a game/NRD reference capture.

Pinhole primary rays intersect a static mirror plane and a translating rectangle.
Secondary specular rays hit a fixed checker/line environment plane. Current and
previous object poses establish correspondence BEFORE either camera projection.
The old visible-depth lookup is retained only as an intentionally different
guide candidate; it is never used to define the geometric reference.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import os

os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
os.environ.setdefault('MKL_NUM_THREADS', '2')
import numpy as np

SCHEMA = 'fsrd-world-surface-motion-quality-v1'
MODES = ('surface', 'visible', 'camera', 'zero', 'wrong-sign')
SEED = 0x15E2026


def sha(data):
    return hashlib.sha256(data).hexdigest()


def put(directory, name, value):
    value = np.ascontiguousarray(value)
    data = value.tobytes()
    (directory / name).write_bytes(data)
    return dict(file=name, bytes=len(data), sha256=sha(data), dtype=value.dtype.str,
                shape=list(value.shape))


def load(directory, record):
    name = record['file']
    if Path(name).name != name or '/' in name or '\\' in name:
        raise ValueError('payload path must be an exact local basename')
    data = (Path(directory) / name).read_bytes()
    if len(data) != record['bytes'] or sha(data) != record['sha256']:
        raise ValueError('sealed payload integrity mismatch: ' + name)
    value = np.frombuffer(data, dtype=np.dtype(record['dtype']))
    return value.reshape(record['shape']).copy()


def halton(index, base):
    value, scale = 0., 1.
    while index:
        scale /= base
        value += scale * (index % base)
        index //= base
    return value


def pose(index, width, height):
    # Static lighting warmup, camera/object motion, long reveal, settled tail.
    t = max(0., min(1., (index - 15) / 32.))
    camera_t = max(0., min(1., (index - 15) / 40.))
    yaw = .07 * math.sin(camera_t * math.pi * .8)
    c, s = math.cos(yaw), math.sin(yaw)
    rotation = np.array([[c, 0., s], [0., 1., 0.], [-s, 0., c]], np.float64)
    camera = np.array([.42 * camera_t, .025 * math.sin(camera_t * math.pi),
                       .12 * camera_t], np.float64)
    view = np.eye(4)
    view[:3, :3] = rotation
    view[:3, 3] = -rotation @ camera
    focal = 1. / math.tan(math.pi / 6.) * (1. + .035 * math.sin(camera_t * math.pi))
    projection = np.zeros((4, 4))
    projection[0, 0], projection[1, 1] = focal / (width / height), focal
    projection[2, 3], projection[3, 2] = .05, -1.
    # This rigid object has BOTH lateral and axial displacement. The final
    # offscreen position is attained continuously rather than deleting geometry.
    center = np.array([-.55 + 5. * t, .03 * math.sin(t * math.pi * 2),
                       -3.5 + .65 * math.sin(t * math.pi * 2)], np.float64)
    jitter = np.array([halton(index % 16 + 1, 2) - .5,
                       halton(index % 16 + 1, 3) - .5], np.float64)
    return dict(index=index, rotation=rotation, camera=camera, view=view,
                projection=projection, center=center, jitter=jitter)


def project(world, camera_pose):
    point = (world - camera_pose['camera']) @ camera_pose['rotation'].T
    depth = point[..., 2]
    uv = np.stack((.5 - point[..., 0] * camera_pose['projection'][0, 0] / (2 * depth),
                   .5 + point[..., 1] * camera_pose['projection'][1, 1] / (2 * depth)), axis=-1)
    return uv, depth


def trace(uv, camera_pose):
    """Exact center-ray scene. No texture-history or production matrix helper."""
    projection, camera = camera_pose['projection'], camera_pose['camera']
    direction = np.stack(((2 * uv[..., 0] - 1) / projection[0, 0],
                          (1 - 2 * uv[..., 1]) / projection[1, 1],
                          -np.ones(uv.shape[:-1])), axis=-1) @ camera_pose['rotation']
    direction /= np.linalg.norm(direction, axis=-1, keepdims=True)
    background_t = (-8. - camera[2]) / direction[..., 2]
    foreground_t = (camera_pose['center'][2] - camera[2]) / direction[..., 2]
    candidate = camera + direction * foreground_t[..., None]
    local = candidate - camera_pose['center']
    foreground = ((foreground_t > 0) & (foreground_t < background_t) &
                  (np.abs(local[..., 0]) <= .64) & (np.abs(local[..., 1]) <= .95))
    distance = np.where(foreground, foreground_t, background_t)
    point = camera + direction * distance[..., None]
    local = np.where(foreground[..., None], point - camera_pose['center'], point)
    reflected = direction.copy()
    reflected[..., 2] *= -1  # Both planar surfaces have the exact world normal +Z.
    secondary_distance = (3. - point[..., 2]) / reflected[..., 2]
    environment = point + reflected * secondary_distance[..., None]
    u, v = environment[..., 0], environment[..., 1]
    checker = .5 + .5 * np.tanh(5 * np.sin(u * 8.) * np.sin(v * 8.))
    thin = np.exp(-(np.sin(u * 18. + v * .6) / .10) ** 2)
    narrow = np.exp(-((u - .7) ** 2 / .05 + (v + .2) ** 2 / .7))
    spec_level = .025 + .055 * checker + .16 * thin + .12 * narrow
    tint = np.where(foreground[..., None], [.95, .16, .04], [.55, .82, 1.])
    spec = spec_level[..., None] * tint
    pattern = .075 + .02 * np.sin(local[..., 0] * 3.) * np.cos(local[..., 1] * 2.)
    diff = pattern[..., None] * np.where(foreground[..., None], [1., .18, .06], [.65, .85, 1.])
    _, view_depth = project(point, camera_pose)
    no_v = -direction[..., 2]
    return dict(point=point, object=foreground.astype('u1'), spec=spec, diff=diff,
                signed_depth=view_depth, spec_hit=secondary_distance, no_v=no_v)


def sequence(width=128, height=128, count=64):
    if width < 64 or height < 64 or not 56 <= count <= 96:
        raise ValueError('oracle requires >=64 each axis and 56..96 temporal samples')
    y, x = np.mgrid[:height, :width]
    screen = np.stack((x + .5, y + .5), axis=-1) / (width, height)
    interior = (x >= 16) & (x < width - 16) & (y >= 16) & (y < height - 16)
    rng = np.random.default_rng(SEED)
    previous = None
    for index in range(count):
        current_pose = pose(index, width, height)
        uv = screen - current_pose['jitter'] / (width, height)
        current = trace(uv, current_pose)
        previous_pose = current_pose if previous is None else previous['pose']
        previous_point = current['point'].copy()
        previous_point += current['object'][..., None] * (previous_pose['center'] - current_pose['center'])
        previous_uv, previous_depth = project(previous_point, previous_pose)
        _, camera_previous_depth = project(current['point'], previous_pose)
        canonical = (previous_uv - uv).astype('<f2')
        rr_xy = canonical.astype(np.float64) + (previous_pose['jitter'] - current_pose['jitter']) / (width, height)
        sample = screen + rr_xy
        inside = ((sample[..., 0] >= 0) & (sample[..., 0] < 1) &
                  (sample[..., 1] >= 0) & (sample[..., 1] < 1))
        sx = np.clip(np.floor(sample[..., 0] * width).astype(int), 0, width - 1)
        sy = np.clip(np.floor(sample[..., 1] * height).astype(int), 0, height - 1)
        # Independent exact previous visibility at the SAME material point's
        # projection; sampled legacy depth below intentionally does not define it.
        previous_visible = trace(previous_uv, previous_pose)
        same_visible_surface = ((previous_visible['object'] == current['object']) &
                                (np.linalg.norm(previous_visible['point'] - previous_point, axis=-1) < 1e-7))
        surface_b = previous_depth - current['signed_depth']
        camera_b = camera_previous_depth - current['signed_depth']
        visible_b = np.zeros((height, width)) if previous is None else previous['signed_depth'][sy, sx] - current['signed_depth']
        for value in (surface_b, camera_b, visible_b):
            value[~inside] = 0
            if previous is None:
                value.fill(0)
        motion = {}
        for mode, b in (('surface', surface_b), ('visible', visible_b), ('camera', camera_b),
                        ('zero', np.zeros_like(surface_b)), ('wrong-sign', -surface_b)):
            packet = np.concatenate((rr_xy, b[..., None], np.ones((height, width, 1))), axis=-1)
            motion[mode] = packet.astype('<f2')
        age = np.full((height, width), 255, 'u1')
        ghost = {signal: np.zeros((height, width, 3), '<f2') for signal in ('spec', 'diff')}
        # Exclude subpixel silhouette disagreements from measured cohorts: the
        # exact geometric previous ray AND the quantized nearest history sample
        # must both have seen foreground. These are independently observable.
        revealed = inside & (current['object'] == 0) & (previous_visible['object'] == 1)
        if previous is None:
            revealed.fill(False)
        if previous is not None:
            revealed &= previous['object'][sy, sx] == 1
            carried = inside & same_visible_surface & (previous['age'][sy, sx] < 32)
            age[carried] = np.minimum(previous['age'][sy[carried], sx[carried]].astype(int) + 1, 32)
            for signal in ghost:
                ghost[signal][carried] = previous['ghost'][signal][sy[carried], sx[carried]]
        age[revealed] = 0
        for signal in ghost:
            ghost[signal][revealed] = previous_visible[signal][revealed]
        inputs, references, outliers = {}, {}, {}
        for signal in ('spec', 'diff'):
            truth = current[signal].astype('<f2')
            # Every multiplicative factor has analytical expectation one, stays
            # nonnegative, and uses a sealed seed common to ALL guide candidates.
            achromatic = rng.lognormal(-.5 * .34 ** 2, .34, (height, width, 1))
            impulse = rng.random(truth.shape) < .004
            gain = np.where(impulse, 24., (1. - .004 * 24.) / (1. - .004))
            noisy = (truth.astype(np.float64) * achromatic * gain).astype('<f2')
            hit = current['spec_hit'] if signal == 'spec' else 3. - current['point'][..., 2]
            inputs[signal] = np.concatenate((noisy, hit[..., None].astype('<f2')), axis=-1)
            references[signal] = truth
            outliers[signal] = impulse.any(axis=-1).astype('u1')
        roughness = np.uint32(round(.12 * 1023))
        nr = np.full((height, width), np.uint32(512) | (np.uint32(512) << 10) | (roughness << 20), '<u4')
        spec_albedo = np.full((height, width, 4), 255, 'u1')
        spec_albedo[..., 3] = np.rint(current['no_v'] * 255).astype('u1')
        diff_albedo = spec_albedo.copy()
        diff_albedo[..., 3] = 0
        common = dict(spec=inputs['spec'], diff=inputs['diff'],
                      depth=current['signed_depth'].astype('<f4'), normals=nr,
                      spec_albedo=spec_albedo, diff_albedo=diff_albedo)
        value = dict(frame=index + 2, index=index, pose=current_pose, common=common,
                     motion=motion, reference=references, ghost=ghost, reveal_age=age,
                     reveal_mask=revealed.astype('u1'), surface_visible=same_visible_surface.astype('u1'),
                     object=current['object'], current_world=current['point'].astype('<f4'),
                     previous_world=previous_point.astype('<f4'), previous_uv=previous_uv.astype('<f4'),
                     rr_previous_uv=sample.astype('<f4'), reprojection_valid=inside.astype('u1'),
                     previous_surface_depth=previous_depth.astype('<f4'),
                     canonical_motion=canonical, interior=interior.astype('u1'), outliers=outliers)
        previous = dict(pose=current_pose, signed_depth=current['signed_depth'], age=age,
                        ghost=ghost, object=current['object'])
        yield value


def write_sequence(directory, width=128, height=128, count=64):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    frames, numeric = [], [f'{count} {width} {height}']
    for value in sequence(width, height, count):
        folder = directory / f'frame{value["frame"]:03d}'
        folder.mkdir(parents=True, exist_ok=True)
        payloads = {name: put(folder, name + '.bin', array) for name, array in value['common'].items()}
        payloads.update({'motion_' + mode: put(folder, 'motion-' + mode + '.bin', array)
                         for mode, array in value['motion'].items()})
        for signal in ('spec', 'diff'):
            payloads['reference_' + signal] = put(folder, 'reference-' + signal + '.bin', value['reference'][signal])
            payloads['ghost_' + signal] = put(folder, 'ghost-' + signal + '.bin', value['ghost'][signal])
            payloads['outliers_' + signal] = put(folder, 'outliers-' + signal + '.bin', value['outliers'][signal])
        for name in ('reveal_age', 'reveal_mask', 'surface_visible', 'object', 'current_world',
                     'previous_world', 'previous_uv', 'rr_previous_uv', 'reprojection_valid',
                     'previous_surface_depth', 'canonical_motion', 'interior'):
            payloads[name] = put(folder, name + '.bin', value[name])
        p = value['pose']
        numbers = [value['frame'], value['index'], 0, int(value['index'] == 0)]
        numbers += list(p['view'].ravel()) + list(p['projection'].ravel()) + list(p['camera']) + list(p['jitter'])
        numeric.append(' '.join(format(float(v), '.17g') for v in numbers))
        frames.append(dict(frame=value['frame'], index=value['index'], directory=folder.name,
                           view=p['view'].tolist(), projection=p['projection'].tolist(),
                           camera=p['camera'].tolist(), jitter=p['jitter'].tolist(),
                           object_center=p['center'].tolist(), reset=value['index'] == 0,
                           payloads=payloads))
    text = ('\n'.join(numeric) + '\n').encode('ascii')
    (directory / 'native-replay.txt').write_bytes(text)
    manifest = dict(schema=SCHEMA, width=width, height=height, submitted_frames=count,
                    comparison_crop=[16, 16, width - 32, height - 32], modes=list(MODES), seed=SEED,
                    frames=frames, native_replay=dict(file='native-replay.txt', bytes=len(text), sha256=sha(text)),
                    source='independent analytic world ray/object-pose oracle, not conversion test helpers',
                    motion='normalized previous-current UV with previous-current pixel jitter exactly once; RH previous-surfaceZ-currentZ, W1',
                    wrong_guides=dict(visible='nearest previous visible depth-current depth; may refer to the occluder',
                                      camera='previous camera applied to CURRENT world point; omits object motion',
                                      zero='B identically0', wrong_sign='negative of independently computed same-surface B'),
                    geometry='static plane worldZ-8; translating rectangle half extent[.64,.95]; both world normal+Z; secondary specular mirror ray first hits fixed environment plane worldZ+3',
                    radiance='prescribed nonnegative environment checker/thin lines + two-tint surfaces; point-sampled pinhole truth, not Monte Carlo integrated radiance',
                    alpha='spec is actual first reflected-ray distance; diffuse is declared secondary+Z ray distance to worldZ+3 with foreground rectangle excluded by secondary visibility mask; DD alpha only an active positive metric',
                    noise='independent mean-one lognormal intensity and mean-one rare per-channel gain impulses; quantized positive native half RGB',
                    normals='packed oct RG/world+Z, roughness .12, materialA0; all modes identical',
                    native_title_operand_encoding='not yet attested by this independent oracle; no raw title Z packet is guessed',
                    reset='first sample only; physically fresh RR context for each complete guide candidate',
                    reveal_support='current background whose exact previous ray AND quantized nearest previous history sample both saw foreground; subpixel silhouette disagreements excluded',
                    temporal_capture=False, native_nrd_paired=False, game_fps_measured=False,
                    generator_sha256=sha(Path(__file__).read_bytes()))
    data = json.dumps(manifest, indent=2, allow_nan=False).encode() + b'\n'
    (directory / 'sequence.json').write_bytes(data)
    return manifest


def metrics(output, reference, age, ghost, crop):
    x, y, width, height = crop
    cut = np.s_[y:y + height, x:x + width]
    out, ref = np.asarray(output, np.float64)[cut][..., :3], np.asarray(reference, np.float64)[cut]
    ages, old = np.asarray(age)[cut], np.asarray(ghost, np.float64)[cut]
    if out.shape != ref.shape or not np.isfinite(out).all():
        raise ValueError('quality output has invalid shape or nonfinite RGB')
    error = out - ref
    opponent = np.stack((error[..., 0] - error[..., 1], error[..., 2] - error[..., 1]), axis=-1)
    dx, dy = np.diff(out, axis=1), np.diff(out, axis=0)
    rx, ry = np.diff(ref, axis=1), np.diff(ref, axis=0)
    energy = float(np.sum(rx * rx) + np.sum(ry * ry))
    result = dict(rgb_rmse=float(np.sqrt(np.mean(error * error))),
                  chroma_rmse=float(np.sqrt(np.mean(opponent * opponent))),
                  chroma_absolute_p99=float(np.quantile(np.abs(opponent), .99)),
                  detail_gradient_rmse=float(np.sqrt((np.mean((dx - rx) ** 2) + np.mean((dy - ry) ** 2)) * .5)),
                  reference_gradient_energy=energy,
                  gradient_projection_ratio=float((np.sum(dx * rx) + np.sum(dy * ry)) / energy) if energy else None,
                  reveal_tail={})
    direction = old - ref
    norm2 = np.sum(direction * direction, axis=-1)
    stale_component = np.sum(error * direction, axis=-1)
    for label, mask in [(str(n), ages == n) for n in range(9)] + [('9..16', (ages >= 9) & (ages <= 16))]:
        valid = mask & (norm2 > 1e-6)
        if valid.any():
            result['reveal_tail'][label] = dict(pixels=int(valid.sum()),
                rgb_rmse=float(np.sqrt(np.mean(error[valid] ** 2))),
                mean_signed_stale_fraction=float(np.mean(stale_component[valid] / norm2[valid])),
                positive_stale_energy=float(np.mean(np.maximum(stale_component[valid], 0))),
                error_energy=float(np.mean(np.sum(error[valid] ** 2, axis=-1))))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('F:/FSRD/sol_batch/15e-quality/inputs'))
    parser.add_argument('--frames', type=int, default=64)
    args = parser.parse_args()
    value = write_sequence(args.output, count=args.frames)
    print(json.dumps(dict(schema=value['schema'], frames=value['submitted_frames'],
                          manifest=str(args.output / 'sequence.json'),
                          manifest_sha256=sha((args.output / 'sequence.json').read_bytes()),
                          compiler_executed=False, gpu_executed=False), indent=2))


if __name__ == '__main__':
    main()
