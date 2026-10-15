"""Immutable synthetic native-RR input sequence and same-input image metrics.

This module never loads game capture pixels. Geometry comes from the conversion
fixture's physical pinhole/world-plane oracle. It is a stepped camera replay,
not a Cyberpunk NRD comparison or a performance/FPS benchmark.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import numpy as np

SCHEMA = 'fsrd-native-rr-synthetic-quality-v1'


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _put(directory, name, array):
    array = np.ascontiguousarray(array)
    data = array.tobytes()
    (directory / name).write_bytes(data)
    return dict(file=name, sha256=_hash(data), bytes=len(data), dtype=array.dtype.str,
                shape=list(array.shape))


def sequence(width=128, height=128):
    """Own radiance/noise; shared already-tested camera and world-surface samples."""
    from test_fsrd_nrd_conversion import projected_depth_cases
    # Optional focal scales are supplied by the conversion fixture; defaults retain its old tests.
    # Ten per-pose values are required since the two T04 static-jitter poses joined the set.
    cases = projected_depth_cases(width, height, focal_scales=[1.0, .98, 1.02, 1.04, 1.01, 1, 1, 1, 1, 1])[:5]
    margin = 16
    y, x = np.mgrid[:height, :width]
    interior = (x >= margin) & (x < width-margin) & (y >= margin) & (y < height-margin)
    result = []
    rng = np.random.default_rng(0x13E2026)
    for key, case in enumerate(cases):
        point = case['world_points']
        wx, wy = point[..., 0], point[..., 1]
        checker = (np.floor(wx*5) + np.floor(wy*5)).astype(np.int64) & 1
        reflection = np.exp(-((wx-.35)**2/.13 + (wy+.15)**2/.4))
        thin_detail = (np.cos(wx*48) > .88).astype(np.float64)
        spec_base = .018 + .035*checker + .065*reflection + .012*thin_detail
        diff_base = .04 + .035*(1-checker) + .004*thin_detail
        truth_spec = np.stack((spec_base, spec_base*.7, spec_base*.42), axis=-1).astype('<f2')
        truth_diff = np.stack((diff_base*.9, diff_base, diff_base*.65), axis=-1).astype('<f2')
        repetitions = 12 if key == 0 else 8
        for repeat in range(repetitions):
            frame = len(result)+2  # Frame 1 is the explicit original-title discovery prefix.
            inputs = {name: value.copy() for name, value in case['inputs'].items()}
            clean = []
            for name, truth, alpha, probe in (
                    ('spec', truth_spec, 5., (.03125, .0625, .015625)),
                    ('diff', truth_diff, 7., (.125, .0625, .03125))):
                noisy = np.maximum(truth.astype(np.float32)+rng.normal(0, .015, truth.shape), 0)
                value = np.concatenate((noisy, np.full((height, width, 1), alpha)), axis=-1).astype('<f2')
                value[~interior, :3] = probe
                truth = truth.copy(); truth[~interior] = probe
                inputs[name] = value; clean.append(truth)
            motion = inputs['motion']
            if repeat:
                motion.fill(0)
            elif case['params']['jittered']:
                jitter_delta = (np.asarray(case['params']['previous_jitter'])-case['params']['jitter'])/(width, height)
                motion[..., :2] = (motion[..., :2].astype(np.float64)-jitter_delta).astype('<f2')
            # The excluded guard retains the existing exact title GPU binding probes.
            motion[~interior] = 0
            inputs['depth'][~interior] = 5.
            rough = (64+192*checker).astype(np.uint32)
            rough[~interior] = 768
            categories = ((np.floor(wx*3)+2*np.floor(wy*3)).astype(np.int64) & 3).astype(np.uint32)
            categories[~interior] = 0
            inputs['nr'] = (np.uint32(512) | (np.uint32(512) << 10) | (rough << 20) | (categories << 30)).astype('<u4')
            params = dict(case['params']); params['jittered'] = False
            params['reset'] = frame == 2
            if repeat:
                params['previous_jitter'] = params['jitter']
            expected_delta = np.zeros((height, width), '<f4') if repeat or key == 0 else case['expected_delta'].astype('<f4')
            expected_delta[~interior] = 0  # Candidate depth oracle is checked only in the interior crop.
            view = np.asarray(params['view'], dtype=np.float64)
            camera = -view[:3, :3].T @ view[:3, 3]
            reveal = case['reveal_mask'] & interior if key == 4 and repeat == 0 else np.zeros_like(interior)
            result.append(dict(frame=frame, key_pose=key, repeat=repeat, inputs=inputs,
                               reference=(clean[0], clean[1]), expected_delta=expected_delta,
                               reveal_mask=reveal.astype('u1'), params=params, camera=camera,
                               projection=np.asarray(params['projection'], dtype=np.float32),
                               view=np.asarray(params['view'], dtype=np.float32)))
    return result


def write_sequence(directory, width=128, height=128):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    frames = []
    for value in sequence(width, height):
        frame = value['frame']; prefix = f'frame{frame:03d}'
        payloads = {name: _put(directory, f'{prefix}-{name}.bin', value['inputs'][name])
                    for name in ('spec', 'diff', 'nr', 'depth', 'motion')}
        payloads['reference_spec'] = _put(directory, f'{prefix}-reference-spec.bin', value['reference'][0])
        payloads['reference_diff'] = _put(directory, f'{prefix}-reference-diff.bin', value['reference'][1])
        payloads['expected_delta'] = _put(directory, f'{prefix}-expected-delta.bin', value['expected_delta'])
        payloads['reveal_mask'] = _put(directory, f'{prefix}-reveal-mask.bin', value['reveal_mask'])
        params = value['params']
        frames.append(dict(frame=frame, key_pose=value['key_pose'], repeat=value['repeat'],
                           view=value['view'].tolist(), projection=value['projection'].tolist(),
                           camera=value['camera'].tolist(), jitter=list(params['jitter']),
                           reset=bool(params['reset']), payloads=payloads))
    manifest = dict(schema=SCHEMA, width=width, height=height, submitted_frames=len(frames),
                    discovery_frame=1, comparison_crop=[16, 16, width-32, height-32],
                    source_motion_jittered=False, seed=0x13E2026, frames=frames,
                    camera_sequence='five stepped RH poses; focal-length change, jitter, occluder reveal; static repeats between poses',
                    reference='analytic current-surface checker/reflection/thin detail, quantized to native half RGB',
                    guard='16-pixel excluded border pins original title binding probes; not a physical scene sample',
                    scope='synthetic signed-provider same-input comparison; no native NRD/combined-color/game-FPS claim',
                    geometry_source_sha256=_hash(Path(__file__).with_name('test_fsrd_nrd_conversion.py').read_bytes()),
                    generator_sha256=_hash(Path(__file__).read_bytes()))
    encoded = json.dumps(manifest, indent=2).encode('utf-8')+b'\n'
    (directory/'sequence.json').write_bytes(encoded)
    return manifest


def load_payload(directory, payload):
    name = payload['file']
    if Path(name).name != name or '/' in name or '\\' in name:
        raise ValueError('payload must be a local basename')
    data = (Path(directory)/name).read_bytes()
    if len(data) != payload['bytes'] or _hash(data) != payload['sha256']:
        raise ValueError(f'payload integrity mismatch: {name}')
    array = np.frombuffer(data, dtype=np.dtype(payload['dtype']))
    return array.reshape(payload['shape']).copy()


def frame_metrics(output, reference, crop, reveal_mask=None):
    x, y, width, height = crop
    out = np.asarray(output, dtype=np.float64)[y:y+height, x:x+width, :3]
    ref = np.asarray(reference, dtype=np.float64)[y:y+height, x:x+width, :3]
    if out.shape != ref.shape or not np.all(np.isfinite(out)):
        raise ValueError('incompatible/nonfinite RGB metrics')
    error = out-ref
    # Detail metric compares current gradients, retaining edge location and contrast.
    dx = np.diff(out, axis=1)-np.diff(ref, axis=1)
    dy = np.diff(out, axis=0)-np.diff(ref, axis=0)
    value = dict(rmse=float(np.sqrt(np.mean(error*error))), bias=float(np.mean(error)),
                 detail_gradient_rmse=float(np.sqrt((np.mean(dx*dx)+np.mean(dy*dy))*.5)))
    if reveal_mask is not None:
        mask = np.asarray(reveal_mask, dtype=bool)[y:y+height, x:x+width]
        if np.any(mask):
            value['reveal_rmse'] = float(np.sqrt(np.mean(error[mask]**2)))
            value['reveal_pixels'] = int(mask.sum())
    return value


def compare(directory, off_directory, on_directory):
    directory = Path(directory)
    manifest = json.loads((directory/'sequence.json').read_text(encoding='utf-8'))
    if manifest['schema'] != SCHEMA:
        raise ValueError('incompatible replay manifest')
    runs = [json.loads((Path(run)/'quality-result.json').read_text(encoding='utf-8'))
            for run in (off_directory, on_directory)]
    manifest_hash = _hash((directory/'sequence.json').read_bytes())
    if any(run['quality_replay']['input_manifest_sha256'] != manifest_hash for run in runs):
        raise ValueError('comparison runs did not consume the same immutable inputs')
    if [run['quality_replay']['camera_projected_depth_delta'] for run in runs] != [False, True]:
        raise ValueError('comparison requires baseline OFF and candidate ON')
    if runs[0]['dll_sha256'] != runs[1]['dll_sha256']:
        raise ValueError('comparison provider DLL differs')
    frame_ids = [frame['frame'] for frame in manifest['frames']]
    if any([frame['frame'] for frame in run['quality_replay']['frames']] != frame_ids for run in runs):
        raise ValueError('comparison rendered-frame alignment differs')
    output_records = [{frame['frame']: frame for frame in run['quality_replay']['frames']} for run in runs]
    rows = []
    for frame in manifest['frames']:
        key = frame['frame']; per_signal = {}
        mask = load_payload(directory, frame['payloads']['reveal_mask'])
        for signal in ('spec', 'diff'):
            reference = load_payload(directory, frame['payloads']['reference_'+signal])
            metrics = {}
            for mode, run, records in zip(('off', 'on'), (off_directory, on_directory), output_records):
                path = Path(run)/f'frame{key:03d}-{signal}.bin'
                data = path.read_bytes()
                expected = manifest['width']*manifest['height']*8
                if len(data) != expected or _hash(data) != records[key]['output_sha256'][signal]:
                    raise ValueError('output integrity/size mismatch')
                output = np.frombuffer(data, dtype='<f2').reshape(manifest['height'], manifest['width'], 4)
                metrics[mode] = frame_metrics(output, reference, manifest['comparison_crop'], mask)
            noisy = load_payload(directory, frame['payloads'][signal])
            metrics['noisy_input'] = frame_metrics(noisy, reference, manifest['comparison_crop'], mask)
            per_signal[signal] = metrics
        rows.append(dict(frame=key, key_pose=frame['key_pose'], repeat=frame['repeat'], signals=per_signal))
    totals = {mode: float(np.mean([row['signals'][signal][mode]['rmse'] for row in rows
                                  if row['repeat'] >= 4 for signal in ('spec', 'diff')]))
              for mode in ('off', 'on', 'noisy_input')}
    reveal = {mode: float(np.mean([row['signals'][signal][mode]['reveal_rmse'] for row in rows
                                  for signal in ('spec', 'diff') if 'reveal_rmse' in row['signals'][signal][mode]]))
              for mode in ('off', 'on', 'noisy_input')}
    gpu_ms = {mode: float(np.mean([frame['gpu_synthetic_title_chain_with_bridge_ms']
                                  for frame in run['quality_replay']['frames'][4:]]))
              for mode, run in zip(('off', 'on'), runs)}
    return dict(input_manifest_sha256=manifest_hash, frames=rows, late_repeat_mean_rmse=totals,
                reveal_rgb_rmse=reveal, reveal_rgb_rmse_improved=reveal['on'] < reveal['off'],
                mean_gpu_synthetic_title_chain_with_bridge_ms=gpu_ms,
                late_repeat_rgb_rmse_improved=totals['on'] < totals['off'],
                scope=manifest['scope'], native_nrd_paired=False, game_fps_measured=False,
                notes=['No quality-improvement assertion: observed direction is reported even if worse.',
                       'References are synthetic analytic radiance; title sentinel shader is not NRD.',
                       'Stepped pose changes and fixed-pose repeats are not a continuous game camera path.'])


def export_crops(directory, off_directory, on_directory, metrics, output):
    """Same frame/input panels; fixed preview transfer, metrics stay in linear half RGB."""
    from PIL import Image, ImageDraw
    directory, output = Path(directory), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((directory/'sequence.json').read_text(encoding='utf-8'))
    by_frame = {frame['frame']: frame for frame in metrics['frames']}
    chosen = [next(frame for frame in reversed(manifest['frames']) if frame['key_pose'] == 0)]
    chosen += [next(frame for frame in manifest['frames'] if frame['key_pose'] == pose) for pose in (2, 4)]
    crop = manifest['comparison_crop']; x, y, width, height = crop; scale = 3
    paths = []
    for frame in chosen:
        key = frame['frame']; preview = Image.new('RGB', (4*width*scale, 2*(height*scale+24)+32), (20, 20, 20))
        draw = ImageDraw.Draw(preview)
        draw.text((4, 5), f'Frame {key}, pose {frame["key_pose"]}: synthetic radiance; fixed gain4 + gamma2.2 preview', fill='white')
        for row, signal in enumerate(('spec', 'diff')):
            reference = load_payload(directory, frame['payloads']['reference_'+signal])
            noisy = load_payload(directory, frame['payloads'][signal])[..., :3]
            values = [reference, noisy]
            for run in (off_directory, on_directory):
                data = (Path(run)/f'frame{key:03d}-{signal}.bin').read_bytes()
                values.append(np.frombuffer(data, '<f2').reshape(manifest['height'], manifest['width'], 4)[..., :3])
            labels = [f'Analytic reference {signal}', f'Same noisy input {signal}',
                      f'B OFF {signal}: RMSE {by_frame[key]["signals"][signal]["off"]["rmse"]:.4f}',
                      f'Camera B ON {signal}: RMSE {by_frame[key]["signals"][signal]["on"]["rmse"]:.4f}']
            for column, (value, label) in enumerate(zip(values, labels)):
                linear = np.maximum(value[y:y+height, x:x+width].astype(np.float32), 0)*4
                display = np.clip(np.power(linear/(1+linear), 1/2.2)*255+.5, 0, 255).astype('u1')
                tile = Image.fromarray(display).resize((width*scale, height*scale), Image.Resampling.NEAREST)
                left, top = column*width*scale, 32+row*(height*scale+24)
                preview.paste(tile, (left, top+24)); draw.text((left+3, top+3), label, fill='white')
        path = output/f'quality-comparison-frame{key:03d}.png'; preview.save(path);paths.append(str(path))
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate', type=Path)
    parser.add_argument('--compare', nargs=3, type=Path, metavar=('INPUT', 'OFF', 'ON'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.generate:
        result = write_sequence(args.generate)
        print(json.dumps({key: result[key] for key in ('schema', 'submitted_frames', 'comparison_crop', 'scope')}))
    elif args.compare:
        result = compare(*args.compare)
        if args.output:
            args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(result, indent=2))
    else:
        parser.error('use --generate or --compare')


if __name__ == '__main__':
    main()
