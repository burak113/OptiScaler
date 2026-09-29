"""Production conversion -> exact AMD DLL -> production composition, every frame.

Clean truth is generated independently and is never passed to production shaders.
The optional captured island supplies only real source guides/geometry; synthetic
clean radiance remains its truth. This is controlled evidence, not game acceptance.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fsrd_toolchain import compile_cpp
import run_fsrd_gpu_tests as t
from fsrd_alpha_common import (GPUWorker, LUMA, compose, convert, frozen_identity,
                               rgba, save_json, seed_frame, shader_identity)

HERE = Path(__file__).resolve().parent
DLL = t.ROOT / 'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'
DEFAULT_SCENES = ('fake_island', 'material_additive', 'wave_lighting', 'small_specular',
                  'dark_rgb_specular', 'textured_specular', 'flat_noise', 'correlated_island')
# Frozen before measurements. Absolute floors avoid noisy percentages near zero.
GATES = dict(relative_error_budget=.05, absolute_error_floor=1e-4,
             detail_gain_drop_budget=.05, required_additive_improvement=.05,
             absolute_skip_fraction_increase=.005)


def blur(image, passes=2):
    result = np.asarray(image, np.float64).copy()
    for _ in range(passes):
        for axis in (0, 1):
            result = (.25*np.roll(result, 1, axis) + .5*result + .25*np.roll(result, -1, axis))
    return result


def fixture(scene, frames, seed, capture=None, metadata=None):
    temporal = scene in ('moving_additive', 'exposure_additive')
    source_scene = 'material_additive' if temporal else scene
    w, h = 160, 112
    y, x = np.indices((h, w), dtype=np.float32)
    island = (((x-w*.40)/(w*.12))**2 + ((y-h*.54)/(h*.16))**2) < 1
    pattern = .5 + .5*np.sin(x*.70 + .17*y)*np.cos(y*.53)
    broad = .10 + .28*island.astype(np.float32)
    diff = np.repeat(broad[..., None], 3, axis=-1)
    spec = np.full((h, w, 3), .05, np.float32)
    normals = t.rgba(w, h, (0, 0, -1))
    roughness = np.full((h, w), .55, np.float32)
    depth = np.full((h, w), 10, np.float32)
    resources, extra_flags = {}, 0
    detail = np.zeros((h, w), np.float32)
    clean = np.broadcast_to([.14, .17, .20], (h, w, 3)).copy()
    if source_scene in ('material_additive', 'small_specular', 'dark_rgb_specular', 'textured_specular'):
        # Fine material pattern with a quiet upper band. Additive RGB is independent
        # of both reflectances, and production receives only their noisy composite.
        pattern[y < h*.25] = .5
        diff = (.07 + .40*pattern)[..., None] * np.array([.70, .85, 1], np.float32)
        if scene == 'small_specular':
            spec[:] = 1/255
        elif scene == 'dark_rgb_specular':
            spec[:] = [1/255, .025, .05]
        elif scene == 'textured_specular':
            spec = np.array([.04, .055, .07], np.float32)*(1+.23*np.sin(x*.62-y*.19))[..., None]
        clean = (diff+spec)*np.array([.45, .38, .32], np.float32) + np.array([.08, .07, .055], np.float32)
        detail = clean @ LUMA
    elif scene == 'wave_lighting':
        wave = .022*np.sin(x*.53+y*.21) + .014*np.cos(x*.17-y*.39)
        wave[y < h*.25] = 0
        clean += wave[..., None]
        detail = wave
    elif scene == 'flat_noise':
        diff[:] = .20
    elif scene in ('recorded_island', 'recorded_wave'):
        if capture is None or metadata is None:
            raise ValueError('Recorded scenes require --captured-island NPZ and --captured-metadata capture.json')
        m = json.loads(Path(metadata).read_text())
        if not m['settings']['conversion_flags'] & (1 << 2):
            raise ValueError('Capture does not identify source_normals.a as packed source roughness')
        with np.load(capture) as a:
            diff = a['source_diffuse_albedo'][..., :3].astype(np.float32)
            spec = a['source_specular_albedo'][..., :3].astype(np.float32)
            normals = a['source_normals'].astype(np.float32)
            roughness = normals[..., 3].copy()
            depth = a['rr_linear_depth'][..., 0].astype(np.float32)
            resources[5] = a['source_specular_hit_distance'][..., 0].astype(np.float32)
            extra_flags = (1 << 4) | (m['settings']['conversion_flags'] & (1 << 11))
            island = a['mask'].astype(bool)
            # Authenticate the derived NPZ to the supplied original capture.
            for name in ('source_diffuse_albedo', 'source_specular_albedo', 'source_normals',
                         'rr_linear_depth', 'source_specular_hit_distance'):
                record = next(r for r in m['images'] if r['name'] == name)
                if hashlib.sha256(a[name].astype('<f4').tobytes()).hexdigest() != record['sha256']:
                    raise ValueError('NPZ/source metadata mismatch: '+name)
        h, w = depth.shape
        y, x = np.indices((h, w), dtype=np.float32)
        clean = np.broadcast_to([.065, .080, .095], (h, w, 3)).copy()
        detail = np.zeros((h, w), np.float32)
        if scene == 'recorded_wave':
            detail = .012*np.sin(x*.53+y*.21)+.008*np.cos(x*.17-y*.39)
            clean += detail[..., None]
    elif scene not in ('fake_island', 'correlated_island'):
        raise ValueError(scene)
    truth = np.repeat(clean[None], frames, axis=0).astype(np.float32)
    diff, spec = rgba(diff), rgba(spec)
    shifts = np.zeros(frames, np.int32)
    motion = np.zeros((frames, h, w, 4), np.float32)
    if scene == 'moving_additive':
        shifts = np.arange(frames, dtype=np.int32)
        truth = np.stack([np.roll(clean, f, axis=1) for f in shifts])
        diff = np.stack([np.roll(diff, f, axis=1) for f in shifts])
        spec = np.stack([np.roll(spec, f, axis=1) for f in shifts])
        motion[1:, ..., 0] = -1/w
    if scene == 'exposure_additive':
        # Known lighting step with fixed guides and geometry: no share history,
        # but the real denoiser still has temporal history and must settle again.
        truth[frames//2:] *= 1.6
    rng = np.random.default_rng(seed)
    # Independent frames are the main noise control. Truth stays independent even
    # when the finite sample mean is nonzero; report that input mean explicitly.
    z = rng.uniform(-np.sqrt(3), np.sqrt(3), (frames, h, w, 3)).astype(np.float32)
    if scene == 'correlated_island':
        coarse = np.stack([blur(frame, 2) for frame in z]).astype(np.float32)
        coarse *= 1 / max(float(np.std(coarse)), 1e-6)
        coarse = np.clip(coarse, -2.8, 2.8)
        z = np.where(island[None, ..., None], coarse, z)
    noise = z*.012
    if np.any(truth+noise < 0):
        raise ValueError('Fixture would require biased radiance clipping')
    raw = (truth+noise).astype(np.float16).astype(np.float32)
    region = np.zeros((h, w), bool)
    region[5:-5, 5:-5] = True
    if scene in ('recorded_island', 'recorded_wave'):
        region[:] = (y >= 25) & (y < 85) & (x < 85) & (x >= 5)
    quiet = region & (y < h*.25)
    if not quiet.any():
        quiet = region & ~island
    camera, overrides = None, {}
    if scene in ('recorded_island', 'recorded_wave'):
        view = np.array(m['dispatch']['view']).reshape(4, 4)
        projection = np.array(m['dispatch']['projection']).reshape(4, 4)
        fw, fh = m['render_size']
        ox, oy = m['origin_xy']
        crop = np.eye(4)
        crop[0, 0], crop[1, 1] = fw/w, fh/h
        crop[3, 0], crop[3, 1] = (fw-2*ox-w)/w, (2*oy+h-fh)/h
        cropped = projection @ crop
        jitter = m['dispatch']['jitter']
        lo, hi = m['dispatch']['depth_bounds']
        depth = np.clip(np.abs(depth), lo, hi).astype(np.float32)
        camera = list(view.ravel())+list(cropped.ravel())+list(jitter)+[lo, hi]
        overrides = dict(InvViewMatrix=np.linalg.inv(view).ravel(),
                         InvProjMatrix=np.linalg.inv(cropped).ravel(), PrevViewMatrix=view.ravel(),
                         NearPlane=lo, FarPlane=hi, JitterOffsets=[*jitter, *jitter])
    return dict(scene=scene, truth=truth, raw=raw, diff=diff, spec=spec,
                normals=normals, roughness=roughness, depth=depth,
                island=island, detail=detail, region=region, quiet=quiet,
                shifts=shifts, motion=motion, camera=camera, overrides=overrides,
                resources=resources, extra_flags=extra_flags)


def frame_array(array, index):
    return array[index] if array.ndim == 4 else array


def write_texture(path, array, fmt):
    a = np.asarray(array)
    if a.ndim == 4 and np.array_equal(a, np.broadcast_to(a[0], a.shape)):
        a = a[0]
    count = a.shape[0] if a.ndim == 4 else 1
    if fmt == 10:
        a = a.astype('<f2')
    elif fmt == 41:
        a = a.astype('<f4')
    elif fmt == 28:
        a = np.rint(np.clip(a, 0, 1)*255).astype('u1')
    elif fmt == 24:
        q = np.rint(np.clip(a, 0, 1)*[1023, 1023, 1023, 3]).astype(np.uint32)
        a = q[..., 0] | (q[..., 1] << 10) | (q[..., 2] << 20) | (q[..., 3] << 30)
        a = a.astype('<u4')
    else:
        raise ValueError(fmt)
    a.tofile(path)
    return f'"{path.as_posix()}" {fmt} {count}'


def run_amd(folder, executable, packed, depth, camera=None):
    folder.mkdir(parents=True, exist_ok=True)
    n = len(packed)
    h, w = depth.shape
    arrays = [depth, np.stack([p[2] for p in packed]), np.stack([p[3] for p in packed]),
              np.stack([p[4] for p in packed]), np.stack([p[5] for p in packed]),
              np.stack([p[1] for p in packed]), np.stack([p[0] for p in packed])]
    formats = [41, 10, 24, 28, 28, 10, 10]
    camera_path = folder/'camera.txt'
    if camera is not None:
        camera_path.write_text(' '.join(map(str, camera))+'\n')
    elif camera_path.exists():
        camera_path.unlink()
    inputs = [folder/f'input{i}.bin' for i in range(7)]
    rows = [write_texture(p, a, fmt) for p, a, fmt in zip(inputs, arrays, formats)]
    save_json(folder/'amd_input_identity.json',
              {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs})
    od, ospec = folder/'diffuse.bin', folder/'specular.bin'
    # The same tuning, reset-on-first-frame, ray flags and DLL for every strength.
    job = folder/'job.txt'
    job.write_text('\n'.join([f'{w} {h} {n} 2 32 0 1 0 "{DLL.as_posix()}"'] + rows +
                             [f'"{od.as_posix()}" "{ospec.as_posix()}"'])+'\n', encoding='utf-8')
    proc = subprocess.run([str(executable), str(job)], capture_output=True, text=True, timeout=300)
    log = proc.stdout+proc.stderr
    (folder/'runner.log').write_text(log, encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(log)
    for field in ('validation_errors', 'validation_warnings', 'sdk_errors', 'sdk_warnings'):
        if not re.search(r'\b'+field+r'=0\b', log):
            raise RuntimeError(log)
    if 'debug_layer=1' not in log:
        raise RuntimeError('D3D12 debug layer unavailable')
    def read(path):
        if path.stat().st_size != n*h*w*8:
            raise RuntimeError(f'Truncated {path}')
        return np.fromfile(path, '<f2').reshape(n, h, w, 4).astype(np.float32)
    diff, spec = read(od), read(ospec)
    for path in inputs+[od, ospec]:
        path.unlink()
    return diff, spec, log


def metrics(output, data, skips, spec_share, score_frames, identity_error):
    start = len(output)-score_frames
    truth, raw = data['truth'], data['raw']
    if np.any(data.get('shifts', 0)):
        align = lambda a: np.stack([np.roll(frame, -int(shift), axis=1)
                                    for frame, shift in zip(a, data['shifts'])])
        output, truth, raw, skips, spec_share = map(align, (output, truth, raw, skips, spec_share))
    roi, quiet = data['region'], data['quiet']
    error = output[start:]-truth[start:]
    mean_error = error.mean(0)
    low = blur(mean_error, 3)
    signal = data['detail'].astype(np.float64)
    if data['scene'] == 'exposure_additive':
        signal = (truth[start:].mean(0) @ LUMA).astype(np.float64)
    signal = signal-signal[roi].mean()
    gain = None
    if np.sum(signal[roi]**2) > 1e-9:
        observed = output[start:].mean(0) @ LUMA
        gain = float(np.sum(signal[roi]*(observed[roi]-observed[roi].mean()))/np.sum(signal[roi]**2))
    h, w = roi.shape
    y, x = np.indices((h, w), dtype=np.float64)
    x = (x-x[roi].mean())/max(w, 1)
    y = (y-y[roi].mean())/max(h, 1)
    mask = data['island']
    coeff = None
    if mask[roi].any() and (~mask[roi]).any():
        design = np.stack((np.ones_like(x), x, y, x*x, x*y, y*y, mask), axis=-1)[roi]
        coeff = np.linalg.lstsq(design, mean_error[roi], rcond=None)[0][-1].tolist()
    inp_error = raw[start:]-truth[start:]
    skip = skips[start:]
    result = dict(target_rmse=float(np.sqrt(np.mean(error[:, roi]**2))),
                mean_error_rms=float(np.sqrt(np.mean(mean_error[roi]**2))),
                low_frequency_error_rms=float(np.sqrt(np.mean(low[roi]**2))),
                island_error_coefficient_rgb=coeff, detail_gain=gain,
                detail_gain_truth_distance=abs(gain-1) if gain is not None else None,
                bias_rgb=mean_error[roi].mean(0).tolist(),
                quiet_temporal_std=float(np.sqrt(np.mean(np.var(error[:, quiet], axis=0)))),
                quiet_target_rmse=float(np.sqrt(np.mean(error[:, quiet]**2))),
                input_rmse=float(np.sqrt(np.mean(inp_error[:, roi]**2))),
                input_mean_error_rms=float(np.sqrt(np.mean(inp_error.mean(0)[roi]**2))),
                skip_energy_fraction=float(np.mean((skip @ LUMA)[:, roi])/max(np.mean((raw[start:] @ LUMA)[:, roi]), 1e-12)),
                skip_temporal_std=float(np.sqrt(np.mean(np.var(skip[:, roi], axis=0)))),
                mean_specular_share=float(np.mean(spec_share[:, roi])),
                identity_max_error=float(identity_error), finite=bool(np.isfinite(output).all()))
    if data['scene'] == 'exposure_additive':
        step = len(output)//2
        result['transition_target_rmse'] = [float(np.sqrt(np.mean((output[f]-truth[f])[roi]**2)))
                                             for f in range(max(0, step-2), min(len(output), step+16))]
        result['transition_frame_start'] = max(0, step-2)
    return result


def compare_results(results, prospective=False):
    comparison = []
    for row in results:
        if row['variant'] == 'baseline':
            continue
        base = next(r for r in results if r['scene'] == row['scene'] and r['floor'] == row['floor'] and r['variant'] == 'baseline')
        a, b = row['metrics'], base['metrics']
        safe_error = a['target_rmse'] <= b['target_rmse']*(1+GATES['relative_error_budget'])+GATES['absolute_error_floor']
        safe_noise = a['quiet_temporal_std'] <= b['quiet_temporal_std']*(1+GATES['relative_error_budget'])+GATES['absolute_error_floor']
        safe_detail = (a['detail_gain'] is None or b['detail_gain'] is None or
                       a['detail_gain'] >= b['detail_gain']-GATES['detail_gain_drop_budget'])
        if prospective:
            safe_detail = (a['detail_gain'] is None or b['detail_gain'] is None or
                abs(a['detail_gain']-1) <= abs(b['detail_gain']-1)+GATES['detail_gain_drop_budget'])
        safe_skip = a['skip_energy_fraction'] <= b['skip_energy_fraction']+GATES['absolute_skip_fraction_increase']
        improvement = b['target_rmse']-a['target_rmse']
        result = dict(scene=row['scene'], floor=row['floor'], strength=row['strength'],
                               rmse_delta=-improvement, error_budget_passed=safe_error,
                               quiet_noise_budget_passed=safe_noise, detail_budget_passed=safe_detail,
                               skip_energy_budget_passed=safe_skip,
                               additive_improvement_passed=(improvement > max(GATES['absolute_error_floor'],
                                   b['target_rmse']*GATES['required_additive_improvement'])) if row['scene']=='material_additive' else None)
        if prospective:
            result['low_frequency_budget_passed'] = a['low_frequency_error_rms'] <= b['low_frequency_error_rms']*1.05+1e-4
            ac, bc = a['island_error_coefficient_rgb'], b['island_error_coefficient_rgb']
            result['island_coefficient_budget_passed'] = (ac is None or bc is None or
                max(abs(v) for v in ac) <= max(abs(v) for v in bc)*1.05+1e-4)
            result['rgb_bias_budget_passed'] = max(abs(v) for v in a['bias_rgb']) <= max(abs(v) for v in b['bias_rgb'])*1.05+1e-4
        comparison.append(result)
    return comparison


def main():
    os.environ.pop('FSRD_LOSSLESS_BASELINE', None)
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=64)
    parser.add_argument('--score-frames', type=int, default=16)
    parser.add_argument('--strengths', default='.5,1')
    parser.add_argument('--scenes', default=','.join(DEFAULT_SCENES))
    parser.add_argument('--floor', default='off,on', help='Matched Floor states; comma-separated off/on')
    parser.add_argument('--captured-island', '--trace', type=Path)
    parser.add_argument('--captured-metadata', type=Path)
    parser.add_argument('--detail', type=float, default=0, help='Composition recovery master;0 isolates factorization')
    parser.add_argument('--prospective', action='store_true', help='Prospective holdout truth-distance and local bias gates')
    parser.add_argument('--seed', type=int, default=17331, help='Holdout seed; development uses842')
    args = parser.parse_args()
    if bool(args.captured_island) != bool(args.captured_metadata):
        parser.error('--captured-island and --captured-metadata must be supplied together')
    if args.frames < 4 or args.frames % 2 or args.score_frames % 2 or not 2 <= args.score_frames <= args.frames:
        raise ValueError('Even sequence and score counts required')
    strengths = [float(v) for v in args.strengths.split(',')]
    if any(not 0 < v <= 1 for v in strengths):
        raise ValueError('Candidate strengths must be in (0,1]; baseline is genuine frozen0')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output/'results.json').exists():
        raise ValueError('Use a fresh output directory to preserve prior evidence')
    temp = output/'temp'
    temp.mkdir(exist_ok=True)
    os.environ.update(TEMP=str(temp), TMP=str(temp))
    baseline = frozen_identity(args.baseline)
    executable = output/'fsrd_rr_runner.exe'
    compile_cpp(HERE/'fsrd_rr_runner.cpp', executable, ('d3d12.lib', 'dxgi.lib'))
    snapshot = output/'source_snapshot'
    snapshot.mkdir(exist_ok=True)
    sources = ['probe_fsrd_additive_split.py', 'fsrd_alpha_common.py', 'fsrd_rr_runner.cpp',
               'fsrd_gpu_runner.cpp', 'run_fsrd_gpu_tests.py']
    for name in sources:
        shutil.copy2(HERE/name, snapshot/name)
    report = dict(baseline=baseline, candidate_shaders=shader_identity(t.PRE),
                  dll=str(DLL), dll_sha256=hashlib.sha256(DLL.read_bytes()).hexdigest(),
                  rr_runner_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                  source_hashes={name:hashlib.sha256((snapshot/name).read_bytes()).hexdigest() for name in sources},
                  frames=args.frames, score_frames=args.score_frames, seed=args.seed, gates=GATES, detail=args.detail,
                  quality_path='Production conversion DXIL (original at0, additive at enabled strengths) -> real AMD RR1.2 -> production composition DXIL, every frame',
                  acceptance_version='prospective truth-distance/local-bias' if args.prospective else 'original frozen gain-drop',
                  limitations='Synthetic independent truth; captured input is guides/geometry only. Moving scene uses a wrapping planar translation; exposure scene is a fixed-guide lighting step. No game quality, skin or ghosting acceptance.',
                  metric_notes={
                      'specular_signal_change': 'Compared with genuine frozen strength0; may include compiler/storage differences. It is not a fitted-channel mask. An off/current0 audit is required for sparse effects.',
                      'identity_max_error': 'Descriptive difference from noisy input. With Floor on, the existing spatial pedestal/noise ceiling can cause this difference; compare candidate delta to the matched baseline.',
                      'skip_energy_fraction': 'Existing Floor/bypass energy is included. Only the candidate-minus-baseline increase tests newly added raw bypass.'},
                  results=[], comparisons=[])
    if args.captured_island:
        report['capture_fixture'] = dict(path=str(args.captured_island.resolve()),
            sha256=hashlib.sha256(args.captured_island.read_bytes()).hexdigest())
        report['capture_metadata'] = dict(path=str(args.captured_metadata.resolve()),
            sha256=hashlib.sha256(args.captured_metadata.read_bytes()).hexdigest())
    save_json(output/'results.json', report)
    with GPUWorker(output) as worker:
        report['gpu_runner_sha256'] = hashlib.sha256(t.runner.read_bytes()).hexdigest()
        for scene in args.scenes.split(','):
            data = fixture(scene, args.frames, args.seed, args.captured_island, args.captured_metadata)
            np.savez_compressed(output/(scene+'_truth.npz'), clean=data['truth'][0], noisy_last=data['raw'][-1],
                                diffuse=data['diff'], specular=data['spec'], mask=data['island'])
            for floor_mode in args.floor.split(','):
                if floor_mode not in ('off', 'on'):
                    raise ValueError(floor_mode)
                floor_on = floor_mode == 'on'
                floor_data = None
                if floor_on:
                    floor_data = [seed_frame(rgba(raw), frame_array(data['diff'], f), data['depth'], data['normals'], args.baseline,
                                             overrides=data['overrides'])
                                  for f, raw in enumerate(data['raw'])]
                baseline_spec = None
                for strength in [0]+strengths:
                    variant = 'baseline' if strength == 0 else 'alpha'+str(strength)
                    folder = output/(scene+'_floor_'+floor_mode+'_'+variant)
                    folder.mkdir(exist_ok=True)
                    directory = args.baseline if strength == 0 else t.PRE
                    begin = time.monotonic()
                    packed = []
                    max_error = 0
                    share = []
                    for f, raw in enumerate(data['raw']):
                        floor, depth, reference = floor_data[f] if floor_on else (None, data['depth'], None)
                        overrides = dict(data['overrides'])
                        if data['extra_flags']:
                            overrides['Flags'] = (1 << 1)|(1 << 5)|data['extra_flags']|((1 << 7) if floor_on else 0)
                        p = convert(rgba(raw), frame_array(data['diff'], f), frame_array(data['spec'], f), strength, directory=directory,
                                    depth=depth, normals=data['normals'], roughness=data['roughness'],
                                    floor=floor, reference=reference, motion=data['motion'][f], overrides=overrides,
                                    resources=data['resources'])
                        packed.append(p)
                        identity = compose(p, directory=directory, depth=depth, detail=0)[..., :3]
                        max_error = max(max_error, float(np.max(abs(identity-raw))))
                        a = p[0][..., :3]*p[4][..., :3]
                        b = p[1][..., :3]*p[5][..., :3]
                        share.append(np.mean(a/np.maximum(a+b, 1e-8), axis=-1))
                    rr_depth = floor_data[0][1] if floor_on else data['depth']
                    if floor_on and not all(np.array_equal(v[1], rr_depth) for v in floor_data):
                        raise ValueError('Temporal depth fixtures require per-frame R32 RR uploads')
                    rr_diff, rr_spec, log = run_amd(folder, executable, packed, rr_depth, data['camera'])
                    composed = []
                    for f, p in enumerate(packed):
                        depth = floor_data[f][1] if floor_on else data['depth']
                        composed.append(compose(p, rr_spec[f], rr_diff[f], directory=directory, depth=depth, detail=args.detail)[..., :3])
                    composed = np.stack(composed)
                    skips = np.stack([p[6][..., :3] for p in packed])
                    measured = metrics(composed, data, skips, np.stack(share), args.score_frames, max_error)
                    spec_inputs = np.stack([p[0][..., :3] for p in packed])
                    if strength == 0:
                        baseline_spec = spec_inputs.copy()
                    changed = spec_inputs[-args.score_frames:] != baseline_spec[-args.score_frames:]
                    changed = changed[:, data['region']]
                    measured['specular_signal_change_channel_fraction'] = float(np.mean(changed))
                    measured['specular_signal_change_pixel_fraction'] = float(np.mean(np.any(changed, axis=-1)))
                    measured['specular_signal_change_observed_vs_frozen'] = bool(changed.any())
                    np.savez_compressed(folder/'preview.npz', result=composed[-1],
                        mean=composed[-args.score_frames:].mean(0),
                        mean_error=(composed[-args.score_frames:]-data['truth'][-args.score_frames:]).mean(0),
                        skip_mean=skips[-args.score_frames:].mean(0))
                    row = dict(scene=scene, floor=floor_on, variant=variant, strength=strength,
                               metrics=measured, seconds=time.monotonic()-begin, log=log.strip())
                    report['results'].append(row)
                    report['comparisons'] = compare_results(report['results'], args.prospective)
                    save_json(output/'results.json', report)
                    print(scene, floor_mode, variant, measured, flush=True)
                    if shader_identity(t.PRE) != report['candidate_shaders']:
                        raise RuntimeError('Production artifacts changed during the experiment; preserve this incomplete report')
    report['shader_dispatches'] = t.timings
    save_json(output/'results.json', report)


if __name__ == '__main__':
    main()
