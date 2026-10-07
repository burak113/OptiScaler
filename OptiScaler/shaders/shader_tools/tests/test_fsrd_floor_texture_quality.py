"""Ordinary Floor texture/noise evidence using actual production D3D12 DXIL.

The clean fields below are independently defined radiance truth.  Seed, all five
Floor passes, conversion and composition execute on the GPU. Actual AMD RR is
the primary FINAL quality model. Each synthetic RR control or deliberately hard
stress model is labelled. Identity RR is only an accounting control.

Measure frozen baseline without accepting it::
    python test_fsrd_floor_texture_quality.py --shader-dir PATH --measure --output PATH

Accept current against frozen baseline::
    python test_fsrd_floor_texture_quality.py --baseline-dir PATH --output PATH

Ordinary rough surfaces retain a positive Skip signal. Native RR receives the
actual converted lobes. The synthetic offline temporal control excludes the
tested frame and never subtracts measured Skip or its error. Consequently noise
leaking through current Floor/Skip remains visible in the final image.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess

import numpy as np
import run_fsrd_gpu_tests as t
from fsrd_alpha_common import conversion_cb


BASE_COMMIT = '49b743d4'
BASE_PATH = 'OptiScaler/shaders/fsrd_preprocess/precompile'
DEFAULT_OUTPUT = t.ROOT / 'tools_tmp/floor_quality_49b743d4/texture_current'
FLOOR_STEPS = (1, 2, 4, 8, 16)
NATIVE_NOISE_REPEATS = 3  # fixed protocol, all runs reported/scored; never retry until pass
WIDTH, HEIGHT = 97, 73  # odd extents exercise dispatch tails too
NOISE_SEEDS = (902711, 163819, 770231, 461417, 293651, 611953,
               809321, 457207, 691133, 152989, 283903, 557017)

# These numerical requirements are deliberately independent of baseline quality.
# They must not be relaxed to make a candidate pass.
GATES = dict(clean_detail_retention_min_percent=95.0,
             clean_signal_nrmse_max_percent=2.0,
             clean_detail_nrmse_max_percent=10.0,
             clean_channel_bias_max_percent=0.5,
             clean_envelope_overshoot_max_percent=1.0,
             noise_remaining_max_percent=70.0,
             noise_baseline_remaining_max_percent=70.0,
             noise_regression_max_percent=100.0,
             identity_signal_nrmse_max_percent=2.0,
             ordinary_skip_min_signal_percent=10.0,
             ordinary_surface_min_percent=99.0,
             clean_baseline_rmse_remaining_max_percent=80.0)


def rgba(rgb, alpha=0):
    rgb = np.asarray(rgb, np.float32)
    if rgb.ndim == 2:
        rgb = np.repeat(rgb[..., None], 3, axis=-1)
    return np.concatenate((rgb, np.full((*rgb.shape[:-1], 1), alpha, np.float32)), axis=-1)


def blur(image, passes=2):
    """Declared synthetic spatial RR: separable 1-2-1, clamped boundaries."""
    out = np.asarray(image, np.float32).copy()
    for _ in range(passes):
        p = np.pad(out, ((1, 1), (1, 1), (0, 0)), mode='edge')
        out = ((p[1:-1, :-2] + 2*p[1:-1, 1:-1] + p[1:-1, 2:])/4)
        p = np.pad(out, ((1, 1), (0, 0), (0, 0)), mode='edge')
        out = (p[:-2] + 2*p[1:-1] + p[2:])/4
    return out


def fixture(name, exposure=1.0):
    """Known texture truth: no reference pixels come from a shader output."""
    y, x = np.indices((HEIGHT, WIDTH), dtype=np.float32)
    nx, ny = x/(WIDTH-1), y/(HEIGHT-1)
    # Smooth curved illumination is shared with geometric/albedo cases. It avoids
    # testing only a constant irradiance that a local average solves trivially.
    illumination = .86 + .12*nx + .07*ny + .04*np.cos(nx*3.1+ny*2.7)
    material = np.full((HEIGHT, WIDTH, 3), .5, np.float32)
    depth = np.full((HEIGHT, WIDTH), 10, np.float32)
    normals = t.rgba(WIDTH, HEIGHT, (0, 0, -1))
    if name == 'stripes':
        rgb = np.stack([.46+.15*np.sin(x*np.pi/2+phase)
                        for phase in (0, .45, .9)], axis=-1)
    elif name == 'checker':
        checker = ((x.astype(int)//3+y.astype(int)//3) % 2)*2-1
        rgb = .46 + checker[..., None]*np.array([.14, .11, .08], np.float32)
    elif name in ('woven', 'illumination_texture', 'oblique', 'depth_discontinuity'):
        rgb = np.stack([.46+.09*np.sin(1.14*x+.17*y+phase)
                        +.06*np.cos(.93*y-.21*x-phase)
                        +.035*np.sin(.43*x+.71*y+.013*x*y+phase)
                        for phase in (0, 1.3, 2.7)], axis=-1)
        if name == 'illumination_texture':
            # The detail exists in lighting, while the material guide stays fixed.
            rgb *= illumination[..., None]
        if name == 'oblique':
            depth = (8+.042*x+.027*y).astype(np.float32)
            normals = t.rgba(WIDTH, HEIGHT, (.21, -.14, -.967))
        elif name == 'depth_discontinuity':
            edge = x >= WIDTH//2
            depth[edge] = 17
            rgb[edge] *= np.array([.72, .83, .91], np.float32)
    elif name == 'albedo_texture':
        material = np.stack([.46+.13*np.sin(.83*x+.11*y+phase)
                             +.06*np.cos(.71*y-.18*x-phase)
                             for phase in (0, 1.1, 2.2)], axis=-1)
        rgb = material*illumination[..., None]
    elif name == 'flat_noise':
        rgb = np.stack([.42*illumination, .47*illumination, .52*illumination], axis=-1)
    else:
        raise ValueError(name)
    # These fixtures are material textures whose original title albedo represents
    # their detail. The fixed-albedo illumination fixture deliberately exercises
    # production screen selection and is never counted as ordinary Floor proof.
    if name in ('stripes', 'checker', 'woven', 'oblique', 'depth_discontinuity'):
        material = .5 + .85*(rgb-.46)
    mask = np.zeros((HEIGHT, WIDTH), bool)
    mask[8:-8, 8:-8] = True
    # Separate local bands make erased regions visible in per-family metrics.
    regions = {'interior': mask}
    if name == 'depth_discontinuity':
        boundary = mask.copy(); boundary[:, :WIDTH//2-3] = False
        boundary[:, WIDTH//2+3:] = False
        regions['depth_boundary'] = boundary
    return dict(name=name, exposure=exposure, truth=rgba(rgb*exposure),
                diffuse_albedo=rgba(material), specular_albedo=t.rgba(WIDTH, HEIGHT, (.04, .04, .04)),
                depth=depth, normals=normals,
                roughness=np.full((HEIGHT, WIDTH), .55, np.float32), regions=regions)


def seed_and_pack(raw, scene, directory):
    directory = Path(directory).resolve()
    h, w = raw.shape[:2]
    values = dict(InvProjMatrix=np.eye(4).ravel(), RenderSize=[w, h, 1/w, 1/h],
                  NearPlane=.1, FarPlane=1000, Flags=1, FloorEnabled=1)
    seeded, linear, guide, reference = t.dispatch('FSRDFloorSeed', values,
        [raw, scene['normals'], scene['depth'], scene['depth'], scene['diffuse_albedo']],
        [10, 41, 10, 10], (w, h), directory=directory)
    floor = seeded
    floor_reference = t.floor_has_detail_reference(directory)
    for step in FLOOR_STEPS:
        floor_inputs = [floor, linear, guide, scene['diffuse_albedo']]
        if floor_reference:
            floor_inputs.append(reference)
        floor = t.dispatch('FSRDFloor', dict(DstTexSize=[w, h, 1/w, 1/h], StepSize=step),
            floor_inputs, [10], (w, h), directory=directory)[0]
    zero = t.rgba(w, h, (0, 0, 0))
    # Explicit controls are identical for current and frozen shader directories.
    cb = conversion_cb(w, h, floor=True, indirect=True, FarPlane=1000,
                       SpecularAlbedoDemodulation=1, DiffuseAlbedoModulation=1,
                       RecoveryMask=1, BiasMaskStrength=1, AdditiveLightSplit=0)
    packed = t.dispatch('FSRDInputConv', cb,
        [raw, linear, zero, scene['normals'], scene['roughness'], scene['depth'],
         scene['diffuse_albedo'], scene['specular_albedo'], zero, floor, zero, zero,
         zero, zero, scene['depth'], zero, reference],
        [10, 10, 10, 24, 28, 28, 10, 10], (w, h), directory=directory)
    return dict(seed=seeded, floor=floor, linear=linear, reference=reference, packed=packed)


def compose(chain, directory, specular, diffuse):
    packed = chain['packed']; h, w = packed[0].shape[:2]
    cb = dict(DstTexSize=[w, h, 1/w, 1/h], Flags=1 << 3, DetailPreservation=1,
              SpecularAlbedoDemodulation=1, DiffuseAlbedoModulation=1, RecoveryMask=1,
              FloorHandoverAnchorClamp=4, FloorHandoverCorrelationMix=1,
              LumaRecovery=1, ChromaRecovery=1, WriteHistory=0)
    return t.dispatch('FSRDOutputComp', cb,
        [specular, packed[4], diffuse, packed[5], packed[6], packed[3], packed[7], chain['linear']],
        [10], (w, h), directory=directory)[0]


def metrics(image, truth, mask):
    out = image[..., :3][mask].astype(np.float64)
    clean = truth[..., :3][mask].astype(np.float64)
    difference = out-clean
    signal_rms = max(float(np.sqrt(np.mean(clean*clean))), 1e-20)
    centered = clean-clean.mean(axis=0)
    detail_rms = max(float(np.sqrt(np.mean(centered*centered))), 1e-20)
    out_centered = out-out.mean(axis=0)
    bias = difference.mean(axis=0)
    detail_error = difference-bias
    overshoot = np.maximum(np.maximum(out-clean.max(axis=0), clean.min(axis=0)-out), 0)
    return dict(rmse=float(np.sqrt(np.mean(difference*difference))),
                signal_nrmse_percent=100*float(np.sqrt(np.mean(difference*difference)))/signal_rms,
                detail_nrmse_percent=100*float(np.sqrt(np.mean(detail_error*detail_error)))/detail_rms,
                detail_retained_percent=100*float(np.mean(out_centered*centered))/(detail_rms*detail_rms),
                channel_bias_percent=(100*bias/signal_rms).tolist(),
                maximum_channel_bias_percent=100*float(np.max(np.abs(bias)))/signal_rms,
                envelope_overshoot_percent=100*float(overshoot.max())/signal_rms,
                signal_rms=signal_rms, detail_rms=detail_rms)


def array_sha256(array):
    """Content identity includes shape and dtype; NPZ container bytes need not match."""
    array = np.ascontiguousarray(array)
    digest = hashlib.sha256()
    digest.update(json.dumps(dict(shape=list(array.shape), dtype=array.dtype.str),
                             sort_keys=True).encode('ascii'))
    digest.update(array.tobytes())
    return digest.hexdigest()


def baseline_identity(directory):
    """Authenticate frozen DXIL/source; a current copy cannot be its own baseline."""
    directory = Path(directory).resolve()
    if directory == t.PRE.resolve():
        raise ValueError('A baseline must use a separate frozen directory')
    records = {}
    for name in ('FSRDFloorSeed', 'FSRDFloor', 'FSRDInputConv', 'FSRDOutputComp'):
        records[name] = {}
        for suffix in ('.hlsl', '_Shader.cso'):
            path = directory/(name+suffix)
            frozen = subprocess.check_output(['git', 'show', f'{BASE_COMMIT}:{BASE_PATH}/{path.name}'], cwd=t.ROOT)
            actual = path.read_bytes()
            if suffix == '.hlsl':
                frozen, actual = frozen.replace(b'\r\n', b'\n'), actual.replace(b'\r\n', b'\n')
            if frozen != actual:
                raise ValueError(f'{path} is not authenticated {BASE_COMMIT} content')
            records[name][suffix] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(directory.glob('*.hlsli')):
        frozen = subprocess.check_output(['git', 'show', f'{BASE_COMMIT}:{BASE_PATH}/{path.name}'], cwd=t.ROOT)
        if frozen.replace(b'\r\n', b'\n') != path.read_bytes().replace(b'\r\n', b'\n'):
            raise ValueError(f'{path} is not authenticated {BASE_COMMIT} shared source')
        records[path.name] = dict(source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return dict(commit=BASE_COMMIT, directory=str(directory), shaders=records)


def shader_identity(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(directory).glob('*')) if p.suffix in ('.hlsl', '.hlsli', '.cso')}


def snapshot_shaders(source, destination):
    """Copy a complete candidate or baseline once, then authenticate every byte.

    Candidate snapshots may contain new shaders; only --baseline-dir is required
    to authenticate to BASE_COMMIT. Both sides dispatch immutable copied artifacts.
    """
    source, destination = Path(source).resolve(), Path(destination).resolve()
    before = shader_identity(source)
    required = {name+suffix for name in ('FSRDFloorSeed', 'FSRDFloor', 'FSRDInputConv', 'FSRDOutputComp')
                for suffix in ('.hlsl', '_Shader.cso')}
    required.update(('FSRDFloorCommon.hlsli', 'FSRDPreprocessCommon.hlsli'))
    if not required.issubset(before):
        raise ValueError(f'Incomplete shader artifact directory: {source}')
    for name in before:
        if name.endswith('.cso') and (source/name).read_bytes()[:4] != b'DXBC':
            raise ValueError(f'Invalid DXIL container: {source/name}')
    if destination.exists():
        if shader_identity(destination) != before:
            raise ValueError(f'Evidence output already contains different shaders; use a fresh output: {destination}')
    else:
        destination.mkdir(parents=True)
        for name in before:
            path = destination/name
            path.write_bytes((source/name).read_bytes())
            os.chmod(path, 0o444)
    if shader_identity(source) != before or shader_identity(destination) != before:
        raise RuntimeError('Shader artifacts changed while their evidence snapshot was being created')
    manifest = dict(source_directory=str(source), snapshot_directory=str(destination),
                    immutable=True, files=before)
    (destination/'snapshot_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def routing_metrics(chain, scene, mask):
    packed = chain['packed']; skip = packed[6][..., :3][mask]
    return dict(skip_signal_percent=100*float(np.sqrt(np.mean(skip*skip)))/
                float(np.sqrt(np.mean(scene['truth'][..., :3][mask]**2))),
                ordinary_surface_percent=100*float(np.mean(packed[3][..., 3][mask] == 0)))


def replay_actual(chains, evidence):
    from fsrd_floor_rr_replay import run_rr, linear_identity_projection
    arrays = dict(diffuse=np.stack([c['packed'][1] for c in chains]),
                  specular=np.stack([c['packed'][0] for c in chains]),
                  depth=np.stack([c['linear'] for c in chains]),
                  motion=np.stack([c['packed'][2] for c in chains]),
                  normals=np.stack([c['packed'][3] for c in chains]),
                  diffuse_albedo=np.stack([c['packed'][5] for c in chains]),
                  specular_albedo=np.stack([c['packed'][4] for c in chains]),
                  view=np.eye(4, dtype=np.float32), projection=linear_identity_projection(.1,1000))
    evidence.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(evidence/'converted_inputs.npz', **arrays)
    rr = run_rr(evidence, **arrays, pad_native=True)
    meta = rr['metadata']
    if meta.get('status') != 'passed' or not meta.get('adapter', {}).get('debug_layer'):
        raise RuntimeError('Actual RR provenance/debug validation is not complete')
    if any(meta.get('counters', {}).get(key) != 0 for key in
           ('validation_errors', 'validation_warnings', 'sdk_errors', 'sdk_warnings')):
        raise RuntimeError(f'Actual RR validation was not clean: {evidence}')
    return rr


def run_directory(directory, evidence, actual=True, exposures=(.1, 1.0, 8.0), cases=None):
    directory = Path(directory).resolve(); evidence.mkdir(parents=True, exist_ok=True)
    records = []
    for name in cases or ('stripes', 'checker', 'woven', 'albedo_texture', 'illumination_texture',
                         'oblique', 'depth_discontinuity'):
        for exposure in exposures:
            scene = fixture(name, exposure)
            chain = seed_and_pack(scene['truth'], scene, directory)
            packed = chain['packed']
            outputs = {
                'identity_rr_control': compose(chain, directory, packed[0], packed[1]),
                'synthetic_spatial_rr_2pass': compose(chain, directory, blur(packed[0]), blur(packed[1]))}
            if actual:
                rr = replay_actual([chain]*12, evidence/f'{name}_exposure_{exposure}_actual_rr')
                outputs['actual_amd_rr_frame11'] = compose(chain, directory, rr['specular'][-1], rr['diffuse'][-1])
            for region, mask in scene['regions'].items():
                for model, image in outputs.items():
                    stage = 'FINAL_HARD_DIAGNOSTIC' if model == 'synthetic_spatial_rr_2pass' else 'FINAL'
                    records.append(dict(case=name, exposure=exposure, region=region, stage=stage,
                                        rr_model=model, **metrics(image, scene['truth'], mask)))
                for label, image in (('seed', chain['seed']), ('floor_after_five_passes', chain['floor'])):
                    records.append(dict(case=name, exposure=exposure, region=region, stage='FLOOR_ONLY_DIAGNOSTIC',
                                        rr_model='none', output=label, **metrics(image, scene['truth'], mask)))
                records.append(dict(case=name, exposure=exposure, region=region, stage='ROUTING_DIAGNOSTIC',
                                    expected_ordinary=name != 'illumination_texture',
                                    **routing_metrics(chain, scene, mask)))
            if exposure == 1:
                np.savez_compressed(evidence/(name+'.npz'), truth=scene['truth'], floor=chain['floor'],
                                    seed=chain['seed'], skip=packed[6], **outputs)
    for name in ('flat_noise', 'woven'):
        scene = fixture(name)
        chains, raw_frames = [], []
        for frame, seed in enumerate(NOISE_SEEDS):
            rng = np.random.default_rng(seed)
            raw = scene['truth'].copy()
            # A new independent field in every frame. Mixed RGB/common-mode noise
            # catches luminance-only filters that leave chromatic flicker untouched.
            noise = rng.normal(0, .032, (HEIGHT, WIDTH, 1)) + rng.normal(0, .022, (HEIGHT, WIDTH, 3))
            raw[..., :3] = np.maximum(raw[..., :3]+noise.astype(np.float32), 0)
            chain = seed_and_pack(raw, scene, directory)
            chains.append(chain); raw_frames.append(raw)
            records.append(dict(case=name, frame=frame, seed=seed, exposure=1, region='interior',
                                stage='ROUTING_DIAGNOSTIC', expected_ordinary=True,
                                **routing_metrics(chain, scene, scene['regions']['interior'])))
        replays = ([replay_actual(chains, evidence/f'{name}_noise_actual_rr_repeat{repeat}')
                    for repeat in range(NATIVE_NOISE_REPEATS)] if actual else [])
        models = {('synthetic_offline_leave_one_out_temporal_rr', None): []}
        if actual:
            for repeat in range(NATIVE_NOISE_REPEATS):
                models[('actual_amd_rr', repeat)] = []
        for frame, chain in enumerate(chains):
            # Excluding the tested frame makes the temporal estimate independent
            # of its noise. There is no subtraction of measured current Skip.
            other = [c for i, c in enumerate(chains) if i != frame]
            spec = np.mean([c['packed'][0] for c in other], axis=0)
            diff = np.mean([c['packed'][1] for c in other], axis=0)
            models[('synthetic_offline_leave_one_out_temporal_rr', None)].append(compose(chain, directory, spec, diff))
            for repeat, replay in enumerate(replays):
                models[('actual_amd_rr', repeat)].append(compose(chain, directory, replay['specular'][frame], replay['diffuse'][frame]))
        for (model, repeat), frames in models.items():
            for frame, final in enumerate(frames):
                raw = raw_frames[frame]
                mask = scene['regions']['interior']
                before = metrics(raw, scene['truth'], mask)
                # Actual RR warmup is explicit; the last six frames are scored.
                stage = 'FINAL_NOISE' if model == 'actual_amd_rr' and frame >= 6 else 'FINAL_NOISE_DIAGNOSTIC'
                row = dict(case=name, frame=frame, seed=NOISE_SEEDS[frame], exposure=1, region='interior', stage=stage,
                           rr_model=model, repeat=repeat, **metrics(final, scene['truth'], mask))
                row['raw_rmse'] = before['rmse']; row['remaining_noise_error_percent'] = 100*row['rmse']/before['rmse']
                records.append(row)
            mask = scene['regions']['interior']
            variation = lambda images: float(np.sqrt(np.mean(np.var(np.stack(images)[6:, mask, :3], axis=0))))
            stage = 'FINAL_NOISE_SEQUENCE' if model == 'actual_amd_rr' else 'FINAL_NOISE_SEQUENCE_DIAGNOSTIC'
            row = dict(case=name, exposure=1, region='interior', stage=stage,
                       rr_model=model, repeat=repeat, frames=len(frames), scored_frames=list(range(6,12)),
                       final_variation=variation(frames), raw_variation=variation(raw_frames),
                       floor_variation=variation([c['floor'] for c in chains]),
                       **metrics(np.mean(frames[6:], axis=0), scene['truth'], mask))
            row['remaining_variation_percent'] = 100*row['final_variation']/row['raw_variation']
            if model == 'actual_amd_rr':
                # A zero-delta control can only resolve overlapping native ranges
                # if every relevant full-frame stage is exactly equal on all fixed
                # paired runs. Metric equality alone is insufficient.
                stage_arrays = {label: np.stack([c[label] for c in chains])
                                for label in ('seed', 'floor', 'linear', 'reference')}
                stage_arrays.update({f'packed_{index}': np.stack([c['packed'][index] for c in chains])
                                     for index in range(len(chains[0]['packed']))})
                stage_arrays.update(native_diffuse=replays[repeat]['diffuse'],
                                    native_specular=replays[repeat]['specular'],
                                    final_composition=np.stack(frames))
                row['stage_array_sha256'] = {label: array_sha256(array)
                                             for label, array in stage_arrays.items()}
            records.append(row)
        np.savez_compressed(evidence/(name+'_noise.npz'), truth=scene['truth'], noisy=np.stack(raw_frames),
                            floor=np.stack([c['floor'] for c in chains]),
                            **{key[0]+('' if key[1] is None else f'_repeat{key[1]}'): np.stack(value)
                               for key,value in models.items()})
    return records


def record_key(row):
    return tuple(row.get(k) for k in ('case', 'exposure', 'region', 'stage', 'rr_model', 'frame', 'output', 'repeat'))


def evaluate(records, baseline):
    old = {record_key(row): row for row in baseline}
    checks = []
    def check(name, passed, **values):
        checks.append(dict(name=name, passed=bool(passed), **values))
    for row in records:
        label = f"{row['case']} exposure={row['exposure']} {row.get('region', '')} {row['stage']} {row.get('rr_model', '')}"
        if row.get('repeat') is not None:
            label += f" repeat={row['repeat']}"
        if row['stage'] == 'FINAL' and row['rr_model'] == 'actual_amd_rr_frame11':
            for metric, limit, lower in (
                ('detail_retained_percent', GATES['clean_detail_retention_min_percent'], True),
                ('signal_nrmse_percent', GATES['clean_signal_nrmse_max_percent'], False),
                ('detail_nrmse_percent', GATES['clean_detail_nrmse_max_percent'], False),
                ('maximum_channel_bias_percent', GATES['clean_channel_bias_max_percent'], False),
                ('envelope_overshoot_percent', GATES['clean_envelope_overshoot_max_percent'], False)):
                check(label+' '+metric, row[metric] >= limit if lower else row[metric] <= limit,
                      measured=row[metric], limit=limit)
            previous = old.get(record_key(row))
            check(label+' frozen clean baseline present', previous is not None)
            if previous is not None and (previous['signal_nrmse_percent'] > 2 or previous['detail_retained_percent'] < 95):
                ratio = 100*row['rmse']/max(previous['rmse'], 1e-20)
                check(label+' material reduction of demonstrated clean defect',
                      ratio <= GATES['clean_baseline_rmse_remaining_max_percent'],
                      measured=ratio, limit=GATES['clean_baseline_rmse_remaining_max_percent'])
        elif row['stage'] == 'FINAL' and row['rr_model'] == 'identity_rr_control':
            check(label+' closure', row['signal_nrmse_percent'] <= GATES['identity_signal_nrmse_max_percent'],
                  measured=row['signal_nrmse_percent'], limit=GATES['identity_signal_nrmse_max_percent'])
        elif row['stage'] == 'ROUTING_DIAGNOSTIC' and row.get('expected_ordinary'):
            check(label+' ordinary Floor exercised', row['skip_signal_percent'] >= GATES['ordinary_skip_min_signal_percent'],
                  measured=row['skip_signal_percent'], limit=GATES['ordinary_skip_min_signal_percent'])
            check(label+' ordinary material routing', row['ordinary_surface_percent'] >= GATES['ordinary_surface_min_percent'],
                  measured=row['ordinary_surface_percent'], limit=GATES['ordinary_surface_min_percent'])
        elif row['stage'] in ('FINAL_NOISE', 'FINAL_NOISE_SEQUENCE'):
            metric = 'rmse' if row['stage'] == 'FINAL_NOISE' else 'final_variation'
            remaining = 'remaining_noise_error_percent' if metric == 'rmse' else 'remaining_variation_percent'
            check(label+' useful input noise suppression', row[remaining] <= GATES['noise_remaining_max_percent'],
                  measured=row[remaining], limit=GATES['noise_remaining_max_percent'])
            check(label+' preserves known clean structure', row['detail_retained_percent'] >= 95,
                  measured=row['detail_retained_percent'], limit=95)
            check(label+' bounded noisy-image channel bias', row['maximum_channel_bias_percent'] <= .5,
                  measured=row['maximum_channel_bias_percent'], limit=.5)
            previous = old.get(record_key(row))
            check(label+' frozen baseline present', previous is not None)
            if previous is not None:
                ratio = 100*row[metric]/max(previous[metric], 1e-20)
                check(label+' no noise regression', ratio <= GATES['noise_regression_max_percent'],
                      measured=ratio, limit=GATES['noise_regression_max_percent'])
                if row['case'] == 'woven':
                    check(label+' material noise improvement over frozen baseline',
                          ratio <= GATES['noise_baseline_remaining_max_percent'],
                          measured=ratio, limit=GATES['noise_baseline_remaining_max_percent'])
    return checks


def repeat_evidence(records, baseline):
    """Report native repeat spread; no averaging replaces an individual gate."""
    evidence = []
    for case in ('flat_noise', 'woven'):
        select = lambda rows: [r for r in rows if r['case'] == case
                               and r['stage'] == 'FINAL_NOISE_SEQUENCE' and r['rr_model'] == 'actual_amd_rr']
        current, old = select(records), select(baseline)
        row = dict(case=case, candidate=current, baseline=old,
                   fixed_runs=NATIVE_NOISE_REPEATS, retries=0, individual_gates_mandatory=True)
        current_by_repeat = {r.get('repeat'): r for r in current}
        old_by_repeat = {r.get('repeat'): r for r in old}
        required_repeats = set(range(NATIVE_NOISE_REPEATS))
        exact_stages = (set(current_by_repeat) == set(old_by_repeat) == required_repeats
                        and all(current_by_repeat[i].get('stage_array_sha256')
                                and current_by_repeat[i]['stage_array_sha256'] ==
                                    old_by_repeat[i].get('stage_array_sha256')
                                for i in required_repeats))
        row['all_paired_full_pipeline_arrays_byte_identical'] = bool(exact_stages)
        for metric in ('rmse', 'final_variation'):
            c = [r[metric] for r in current]; b = [r[metric] for r in old]
            if c and b:
                overlap = min(c) <= max(b) and max(c) >= min(b)
                decision = ('verified_byte_identical_unchanged' if exact_stages else
                            'uncertain_at_native_repeat_scale' if overlap else
                            'clear_regression' if min(c) > max(b) else 'clear_non_regression')
                row[metric] = dict(candidate_range=[min(c),max(c)], baseline_range=[min(b),max(b)], decision=decision)
        evidence.append(row)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shader-dir', type=Path, default=t.PRE)
    parser.add_argument('--baseline-dir', type=Path)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--measure', action='store_true', help='Report quality failures without accepting this build')
    parser.add_argument('--synthetic-only', action='store_true', help='Measurement-only synthetic diagnostics; actual RR unavailable is never acceptance')
    parser.add_argument('--quick', action='store_true', help='Measurement-only small primary subset at exposure 1')
    args = parser.parse_args()
    args.output = args.output.resolve(); args.output.mkdir(parents=True, exist_ok=True)
    args.shader_dir = args.shader_dir.resolve()
    if not args.measure and args.baseline_dir is None:
        parser.error('Acceptance requires --baseline-dir; use --measure for non-acceptance reporting')
    if (args.synthetic_only or args.quick) and not args.measure:
        parser.error('--synthetic-only and --quick are measurement-only; acceptance runs the full actual RR suite')
    t.OUT = args.output/'gpu_jobs'; t.OUT.mkdir(exist_ok=True)
    t.runner = args.output/'fsrd_gpu_runner.exe'; t.build_runner()
    candidate_snapshot = snapshot_shaders(args.shader_dir, args.output/'candidate_shader_snapshot')
    args.shader_dir = Path(candidate_snapshot['snapshot_directory'])
    baseline, baseline_id = [], None
    baseline_snapshot = None
    if args.baseline_dir:
        args.baseline_dir = args.baseline_dir.resolve()
        if args.baseline_dir == Path(candidate_snapshot['source_directory']):
            parser.error('Candidate and frozen baseline must use different directories')
        baseline_id = baseline_identity(args.baseline_dir)
        baseline_snapshot = snapshot_shaders(args.baseline_dir, args.output/'baseline_shader_snapshot')
        args.baseline_dir = Path(baseline_snapshot['snapshot_directory'])
        baseline = run_directory(args.baseline_dir, args.output/'baseline_evidence', actual=not args.synthetic_only,
                                 exposures=(1,) if args.quick else (.1,1,8),
                                 cases=('albedo_texture', 'depth_discontinuity') if args.quick else None)
    records = run_directory(args.shader_dir, args.output/'candidate_evidence', actual=not args.synthetic_only,
                            exposures=(1,) if args.quick else (.1,1,8),
                            cases=('albedo_texture', 'depth_discontinuity') if args.quick else None)
    checks = evaluate(records, baseline)
    for snapshot in (candidate_snapshot, baseline_snapshot):
        if snapshot is not None:
            checks.append(dict(name=f"immutable shader snapshot {snapshot['snapshot_directory']}",
                               passed=shader_identity(snapshot['snapshot_directory']) == snapshot['files']))
    native_repeats = repeat_evidence(records, baseline)
    for case in native_repeats:
        for metric in ('rmse', 'final_variation'):
            if metric in case:
                checks.append(dict(name=f"{case['case']} {metric} native repeats resolve no-regression decision",
                                   passed=case[metric]['decision'] != 'uncertain_at_native_repeat_scale',
                                   **case[metric]))
    for index, job in enumerate(t.timings):
        checks.append(dict(name=f'production GPU dispatch {index} clean D3D12 validation',
                           passed=(job.get('debug_layer') == '1' and job.get('validation_errors') == '0'
                                   and job.get('validation_warnings') == '0')))
    result = dict(schema='fsrd_floor_texture_quality_v4', mode='measure_only' if args.measure else 'acceptance',
                  accepted=(not args.measure and all(c['passed'] for c in checks)), gates=GATES,
                  test_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  gpu_test_helper_sha256=hashlib.sha256(Path(t.__file__).read_bytes()).hexdigest(),
                  rr_disclosure='Actual signed AMD RR is the primary FINAL quality evidence; identity and synthetic spatial/offline temporal models are explicitly labelled controls and diagnostics.',
                  fixtures=dict(width=WIDTH, height=HEIGHT, exposures=[.1, 1, 8], seeds=list(NOISE_SEEDS),
                                floor_steps=list(FLOOR_STEPS), roughness=.55, noise_common_sigma=.032,
                                noise_independent_rgb_sigma=.022, spatial_rr_blur_passes=2),
                  scoring_protocol=dict(clean_static_frame=11, noise_warmup_frames=list(range(6)),
                                        noise_scored_frames=list(range(6,12)), native_runs_per_input=dict(clean=1, noise=NATIVE_NOISE_REPEATS),
                                        automatic_retries=0, synthetic_temporal='offline leave-one-out frame average',
                                        camera_contract='identity view and matched perspective P00=P11=.5 reproduce source identity-InvProj linear-depth rescaled rays',
                                        native_padding='explicit pad_native=True; logical pixels/ROI unchanged, added guards inactive',
                                        superseded_native_camera='Earlier implicit 60-degree and explicit identity native projections are invalid acceptance references'),
                  shader_directory=str(args.shader_dir), shader_identity=shader_identity(args.shader_dir),
                  candidate_shader_snapshot=candidate_snapshot, baseline_shader_snapshot=baseline_snapshot,
                  frozen_baseline=baseline_id, baseline_records=baseline, records=records,
                  native_repeat_evidence=native_repeats,
                  checks=checks, dispatches=t.timings)
    destination = args.output/'results.json'
    destination.write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    failed = [c for c in checks if not c['passed']]
    print(f"{'MEASUREMENT ONLY' if args.measure else 'ACCEPTANCE'}: {len(checks)-len(failed)}/{len(checks)} gates; {len(t.timings)} GPU dispatches; {destination}")
    for row in records:
        if row['exposure'] == 1 and row['stage'] in ('FINAL', 'FINAL_NOISE_SEQUENCE'):
            print(json.dumps(row, allow_nan=False))
    if failed and not args.measure:
        raise AssertionError(f'{len(failed)} frozen texture/noise gates failed; see {destination}')


if __name__ == '__main__':
    main()
