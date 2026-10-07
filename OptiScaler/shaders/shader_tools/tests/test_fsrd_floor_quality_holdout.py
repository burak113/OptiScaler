"""Independent, predeclared Floor holdout, executing production D3D12 DXIL.

Frozen measurement (this never accepts a build)::
    python test_fsrd_floor_quality_holdout.py --shader-dir FROZEN --measure --output OUT
Candidate acceptance, after the production owner freezes its candidate::
    python test_fsrd_floor_quality_holdout.py --baseline-dir FROZEN --output OUT

Radiance truth and motion are analytic, nonperiodic fields, never shader output.
The controlled noisy RR reference is an OFFLINE, leave-one-out, same-surface
average of actual converted noisy lobes. It uses future frames, has no access to
truth or Skip, and does not model AMD RR. Its support is reported at each frame.
The clean controlled RR reference is a declared spatial blur of actual clean
lobes. The signed AMD provider also executes when its replay helper is available;
an attempted native replay failure is fatal, never a silent reference fallback.
Every scored ROI/frame must retain ordinary material type zero and positive Skip.
Acceptance thresholds below were fixed before candidate results were observed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

import numpy as np
import run_fsrd_gpu_tests as t
from fsrd_alpha_common import conversion_cb


BASE_COMMIT = '49b743d4'
BASE_PATH = 'OptiScaler/shaders/fsrd_preprocess/precompile'
DEFAULT_OUTPUT = t.ROOT / 'tools_tmp/floor_quality_49b743d4/holdout_current'
SHADERS = ('FSRDFloorSeed', 'FSRDFloor', 'FSRDInputConv', 'FSRDOutputComp')
SEEDS = (120011, 120023, 120041)
DIMENSIONS = ((113, 79), (80, 61))
EXPOSURES = (.03, 12.)
FRAMES, WARMUP = 32, 8
FLOOR_STEPS = (1, 2, 4, 8, 16)
LUMA = np.array([.2126, .7152, .0722], np.float64)
# IMMUTABLE acceptance contract. A measurement report does not waive these gates.
GATES = dict(clean_contrast_min_percent=95., clean_contrast_max_percent=105.,
             clean_signal_nrmse_max_percent=2., clean_detail_nrmse_max_percent=10.,
             clean_channel_bias_max_percent=.5,
             noisy_contrast_min_percent=90., noisy_contrast_max_percent=105.,
             noisy_channel_bias_max_percent=1., stable_noise_remaining_max_percent=70.,
             targeted_error_baseline_max_ratio=.8, guard_baseline_max_ratio=1.02,
             fp16_signal_rms_allowance_percent=.2, ordinary_skip_min_signal_percent=10.,
             volume_retention_min_percent=90., lighting_step_gain_min_percent=90.,
             lighting_step_gain_max_percent=110., min_roi_pixels=24,
             invalid_history_exact_fresh=True)
MANIFEST = dict(seeds=SEEDS, dimensions=DIMENSIONS, exposures=EXPOSURES,
                frames=FRAMES, warmup=WARMUP, score_reveal_immediately=True,
                occluder_speed_pixels_per_frame=.37, reverse_at_frame=20,
                depth_layers=[3., 13.], roughness=.57, floor_steps=FLOOR_STEPS,
                noise_common_relative_sigma=.085, noise_rgb_relative_sigma=.06,
                random_generator='numpy_PCG64_SeedSequence_seed_frame',
                directions=['dark_to_bright', 'bright_to_dark'],
                truth='analytic_chirped_material_1px_strokes_anisotropic_light',
                controlled_rr='offline_leave_one_out_surface_corresponding_actual_packed_lobes',
                controlled_rr_uses_future=True, clean_rr='clamped_2pass_121_spatial_blur',
                volume_attribution='paired_volume_on_minus_volume_off_with_RR_lobes_erased',
                local_transient_window_pixels=[3, 3], reveal_age_frames=[0, 1, 2],
                gates=GATES)
MANIFEST_HASH = hashlib.sha256(json.dumps(MANIFEST, sort_keys=True).encode()).hexdigest()


def rgba(rgb, alpha=0):
    rgb = np.asarray(rgb, np.float32)
    if rgb.ndim == 2:
        rgb = np.repeat(rgb[..., None], 3, axis=-1)
    return np.concatenate((rgb, np.full((*rgb.shape[:-1], 1), alpha, np.float32)), axis=-1)


def gpu_dispatch(*args, **kwargs):
    result = t.dispatch(*args, **kwargs)
    diagnostics = t.timings[-1]
    if (diagnostics.get('debug_layer') != '1' or diagnostics.get('validation_errors') != '0'
            or diagnostics.get('validation_warnings') != '0'):
        raise RuntimeError(f'Production DXIL dispatch lacks clean D3D12 validation: {diagnostics}')
    return result


def array_identity(arrays):
    digest = hashlib.sha256()
    for array in arrays:
        array = np.ascontiguousarray(array)
        digest.update(str(array.shape).encode()); digest.update(array.dtype.str.encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def noisy_raw(scene, seed, frame):
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed, frame])))
    raw = scene['truth'].copy()
    noise = .085*rng.normal(size=(*raw.shape[:2], 1))+.06*rng.normal(size=raw[..., :3].shape)
    raw[..., :3] = np.maximum(raw[..., :3]*(1+noise), 0)
    return raw


def smooth(image, passes=2):
    """Declared reference operation, with clamped boundaries and no wrap."""
    out = np.asarray(image, np.float64).copy()
    for _ in range(passes):
        pad = np.pad(out, ((0, 0), (1, 1), (0, 0)), mode='edge')
        out = (pad[:, :-2] + 2 * pad[:, 1:-1] + pad[:, 2:]) / 4
        pad = np.pad(out, ((1, 1), (0, 0), (0, 0)), mode='edge')
        out = (pad[:-2] + 2 * pad[1:-1] + pad[2:]) / 4
    return out.astype(np.float32)


def displacement(frame):
    travel = min(max(frame - (WARMUP - 1), 0), 12)
    if frame >= 20:
        travel = 12 - (frame - 19)
    return -.37 * travel


def material(x, y, width, height, foreground=False):
    phases = (0., 1.19, 2.63)
    # Chirps, noninteger frequencies and a curved stroke prevent shift/wrap and
    # periodic-checker shortcuts. Dark strokes are genuine material structure.
    p = .41*x + .69*y + .006*x*x - .004*y*y + .003*x*y
    q = 1.02*x - .28*y + .0023*x*y
    r = .19*x + 1.17*y + .0061*y*y
    rgb = np.stack([.49 + .12*np.sin(p+ph) + .07*np.cos(q-ph)
                    + .045*np.sin(r+2*ph) for ph in phases], axis=-1)
    stroke = (np.abs(x-(.31*width+.11*y+2.3*np.sin(.12*y))) <= .5)
    stroke |= (np.abs(y-(.62*height+.07*x)) <= .5) & (x > .18*width) & (x < .43*width)
    rgb[stroke] *= .19
    if foreground:
        rgb *= np.array([.78, .95, .68])
    return rgb.astype(np.float32)


def scene_sequence(width, height, exposure, direction):
    y, x = np.indices((height, width), dtype=np.float64)
    crop = (x >= 4) & (x < width-4) & (y >= 4) & (y < height-4)
    fg_scale, bg_scale = ((.31, 1.) if direction == 'dark_to_bright' else (1., .31))
    light = .73 + .18*x/width + .11*y/height + .045*np.sin(.018*x+.024*y)
    light += .10*np.exp(-((x-.68*width)/(.38*width))**2-((y-.29*height)/(.18*height))**2)
    background = material(x, y, width, height)*bg_scale
    previous_coverage = None
    age = np.full((height, width), -100, np.int32)
    scenes = []
    for frame in range(FRAMES):
        move = displacement(frame)
        edge = .47*width + .21*(y-.5*height) + move
        coverage = np.clip(edge+.5-x, 0, 1)
        foreground = material(x-move, y, width, height, True)*fg_scale
        albedo = foreground*coverage[..., None]+background*(1-coverage[..., None])
        truth = albedo*light[..., None]*exposure
        owns_fg = coverage >= .5
        normals = np.broadcast_to(np.array([-.13, .08, -.988], np.float32), (height, width, 3)).copy()
        normals[owns_fg] = [.23, .11, -.967]
        normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
        depth = np.where(owns_fg, 3., 13.).astype(np.float32)
        motion = np.zeros((height, width, 4), np.float32)
        if frame:
            motion[owns_fg, 0] = (displacement(frame-1)-move)/width
        reveal = np.zeros_like(crop) if previous_coverage is None else coverage < previous_coverage-1e-5
        age = np.where(reveal, 0, age+1)
        regions = dict(stable=crop & ((x < .26*width) | (x > .70*width)),
                       edge=crop & (np.abs(x-edge) <= 2),
                       revealed=crop & (age >= 0) & (age <= 2))
        scenes.append(dict(frame=frame, truth=rgba(truth), diffuse_albedo=rgba(albedo),
                           specular_albedo=t.rgba(width, height, (.04, .04, .04)),
                           normals=rgba(normals), depth=depth, motion=motion,
                           roughness=np.full((height, width), .57, np.float32),
                           regions=regions, coverage=coverage, owns_fg=owns_fg,
                           reveal_age=age.copy(), displacement=move))
        previous_coverage = coverage
    return scenes


def seed_pack(raw, scene, directory):
    h, w = raw.shape[:2]
    seeded, linear, guide, reference = gpu_dispatch('FSRDFloorSeed',
        dict(InvProjMatrix=np.eye(4).ravel(), RenderSize=[w, h, 1/w, 1/h],
             NearPlane=.1, FarPlane=1000., Flags=1, FloorEnabled=1),
        [raw, scene['normals'], scene['depth'], scene['depth'], scene['diffuse_albedo']],
        [10, 41, 10, 10], (w, h), directory=directory)
    floor = seeded
    floor_has_seed_reference = 'InDetailReference' in (Path(directory)/'FSRDFloor.hlsl').read_text(encoding='utf-8')
    for step in FLOOR_STEPS:
        floor_inputs = [floor, linear, guide, scene['diffuse_albedo']]
        if floor_has_seed_reference:
            # Current production's immutable seed reference is a fifth SRV.
            # Frozen 49b743d4 keeps its original four-resource dispatch unchanged.
            floor_inputs.append(reference)
        floor = gpu_dispatch('FSRDFloor', dict(DstTexSize=[w, h, 1/w, 1/h], StepSize=step),
            floor_inputs, [10], (w, h), directory=directory)[0]
    zero = t.rgba(w, h, (0, 0, 0))
    packed = gpu_dispatch('FSRDInputConv', conversion_cb(w, h, floor=True, FarPlane=1000.,
        FloorDetailPreservation=1, SpecularAlbedoDemodulation=1, DiffuseAlbedoModulation=1,
        RecoveryMask=1, BiasMaskStrength=1, AdditiveLightSplit=0),
        [raw, linear, scene['motion'], scene['normals'], scene['roughness'], scene['depth'],
         scene['diffuse_albedo'], scene['specular_albedo'], zero, floor, zero, zero,
         zero, zero, scene['depth'], zero, reference],
        [10, 10, 10, 24, 28, 28, 10, 10], (w, h), directory=directory)
    return dict(packed=packed, floor=floor, seed=seeded, linear=linear)


def compose(chain, specular, diffuse, directory, poison=False):
    packed = chain['packed']; h, w = packed[0].shape[:2]
    motion = packed[2].copy()
    history = t.rgba(w, h, (60000, 100, 50000), 60000 if poison else -1)
    metadata = np.full((h, w, 4), 0xffffffff if poison else 0, np.uint32)
    if poison:
        motion[..., 3] = 0  # Explicit invalid-MV rejection, including reveal pixels.
    cb = dict(DstTexSize=[w, h, 1/w, 1/h], Flags=1 << 3, DetailPreservation=1,
              SpecularAlbedoDemodulation=1, DiffuseAlbedoModulation=1, RecoveryMask=1,
              FloorHandoverAnchorClamp=4, FloorHandoverCorrelationMix=1, LumaRecovery=1,
              ChromaRecovery=1, HistoryValid=int(poison), WriteHistory=1,
              SpatialTemporalMask=0, UnsupportedAlbedoRecovery=0, DemodDivisorFloor=.008)
    return gpu_dispatch('FSRDOutputComp', cb,
        [specular, packed[4], diffuse, packed[5], packed[6], packed[3], packed[7], chain['linear'],
         motion, history, metadata], [10], (w, h), directory=directory)[0]


def sample_x(array, offset):
    """Bilinear X sampling with explicit validity; never periodic movement."""
    h, w = array.shape[:2]
    x = np.arange(w, dtype=np.float64)[None, :] + offset
    x = np.broadcast_to(x, (h, w))
    valid = (x >= 0) & (x <= w-1)
    lo = np.clip(np.floor(x).astype(int), 0, w-1); hi = np.minimum(lo+1, w-1)
    f = (x-np.floor(x))[..., None]
    rows = np.arange(h)[:, None]
    return array[rows, lo]*(1-f)+array[rows, hi]*f, valid


def reference_rr(chains, scenes):
    """Offline LOO reference, averaging real packed signals with guide checks."""
    result, counts = [], []
    for frame, scene in enumerate(scenes):
        current = chains[frame]['packed']
        spec = np.zeros_like(current[0], np.float64); diff = np.zeros_like(current[1], np.float64)
        count = np.zeros(scene['coverage'].shape, np.int32)
        for other, old in enumerate(scenes):
            if other == frame:
                continue
            offset = np.where(scene['owns_fg'], old['displacement']-scene['displacement'], 0.)
            old_coverage, valid = sample_x(old['coverage'][..., None], offset)
            # Mixed edge samples need the same mixture. Pure layers need matching
            # ownership, depth and material coordinates before any signal average.
            valid &= np.abs(old_coverage[..., 0]-scene['coverage']) <= .035
            old_normal, inside = sample_x(chains[other]['packed'][3], offset)
            valid &= inside & (np.abs(old_normal[..., 3]-current[3][..., 3]) < 1e-6)
            valid &= np.abs(old_normal[..., 2]-current[3][..., 2]) < .01
            valid &= np.all(np.abs(old_normal[..., :2]-current[3][..., :2]) <= .01, axis=-1)
            old_depth, inside = sample_x(chains[other]['linear'][..., None], offset)
            valid &= inside & (np.abs(old_depth[..., 0]-chains[frame]['linear']) <= .01*np.abs(chains[frame]['linear']))
            old_albedo, inside = sample_x(chains[other]['packed'][5], offset)
            valid &= inside & np.all(np.abs(old_albedo[..., :3]-current[5][..., :3]) <= .035, axis=-1)
            for slot, target in ((0, spec), (1, diff)):
                value, inside = sample_x(chains[other]['packed'][slot], offset)
                target += value*valid[..., None]
            count += valid
        # Zero-support reference returns the actual lobe, explicitly disclosed.
        # It never reads clean truth, Floor or Skip to manufacture a residual.
        divisor = np.maximum(count, 1)[..., None]
        spec = np.where((count > 0)[..., None], spec/divisor, current[0])
        diff = np.where((count > 0)[..., None], diff/divisor, current[1])
        spec[..., 3] = current[0][..., 3]; diff[..., 3] = current[1][..., 3]
        result.append((spec.astype(np.float32), diff.astype(np.float32)))
        counts.append(count)
    return result, counts


def rms(value):
    return float(np.sqrt(np.mean(np.asarray(value, np.float64)**2)))


def quality(image, truth, mask):
    out, clean = image[..., :3].astype(np.float64), truth[..., :3].astype(np.float64)
    error = out-clean; signal = max(rms(clean[mask]), 1e-20)
    bias = error[mask].mean(axis=0)
    detail = clean-smooth(clean, 4); detail_rms = max(rms(detail[mask]), 1e-20)
    output_detail = out-smooth(out, 4)
    gain = 100*float(np.mean(output_detail[mask]*detail[mask]))/(detail_rms**2)
    # Error is normalized by high-frequency truth, not DC illumination variance.
    # Channel bias is separately gated so subtracting it cannot hide colour loss.
    local = smooth(error*error, 1)
    return dict(pixel_count=int(mask.sum()), signal_rms=signal, detail_rms=detail_rms,
                signal_nrmse_percent=100*rms(error[mask])/signal,
                detail_nrmse_percent=100*rms((error-bias)[mask])/detail_rms,
                texture_gain_percent=gain, contrast_error_percent=abs(gain-100),
                channel_mean_bias=bias.tolist(), channel_mean_bias_percent=(100*bias/signal).tolist(),
                maximum_channel_bias_percent=100*float(np.max(np.abs(bias)))/signal,
                rgb_abs_error_p95_percent=100*float(np.percentile(np.abs(error[mask]), 95))/signal,
                local_transient_p95_percent=100*float(np.percentile(np.sqrt(np.mean(local[mask], axis=-1)), 95))/signal,
                local_transient_max_percent=100*float(np.max(np.sqrt(np.mean(local[mask], axis=-1))))/signal)


def residual_change(image, truth, previous_image, previous_truth, scene, old_scene, mask):
    # Form residual first, then reproject it. Warping colour without truth would
    # count genuine movement/lighting changes as temporal denoiser error.
    error = image[..., :3]-truth[..., :3]
    old_error = previous_image[..., :3]-previous_truth[..., :3]
    offset = np.where(scene['owns_fg'], old_scene['displacement']-scene['displacement'], 0.)
    warped, valid = sample_x(old_error, offset)
    old_coverage, inside = sample_x(old_scene['coverage'][..., None], offset)
    valid &= inside & (np.abs(old_coverage[..., 0]-scene['coverage']) <= .035)
    stable = mask & valid
    signal = max(rms(truth[..., :3][mask]), 1e-20)
    # Immediate reveal remains scored with the same-screen previous residual,
    # explicitly labelled separately from the valid reprojected residual metric.
    delta = error-old_error
    result = dict(residual_change_rgb_percent=100*rms(delta[mask])/signal,
                  residual_change_luma_percent=100*rms((delta@LUMA)[mask])/signal,
                  valid_reprojection_pixels=int(stable.sum()))
    if stable.any():
        difference = error-warped
        result.update(reprojected_residual_change_rgb_percent=100*rms(difference[stable])/signal,
                      reprojected_residual_change_luma_percent=100*rms((difference@LUMA)[stable])/signal)
    return result


def routing(chain, scene, mask):
    packed = chain['packed']
    return dict(ordinary_material_mask_zero=bool(np.all(packed[3][..., 3][mask] == 0)),
                selected_surface_percent=100*float(np.mean(packed[3][..., 3][mask] > 0)),
                skip_signal_percent=100*rms(packed[6][..., :3][mask])/max(rms(scene['truth'][..., :3][mask]), 1e-20),
                positive_skip_pixels_percent=100*float(np.mean(np.all(packed[6][..., :3][mask] > 0, axis=-1))))


def record_frames(outputs, raws, chains, scenes, descriptor, model, counts=None, clean=False):
    rows = []
    for frame in range(FRAMES):
        scene = scenes[frame]
        for region, mask in scene['regions'].items():
            # Warmup excludes stable/edge only. First partial reveal is scored on
            # its first frame and ages0/1/2, with no retrospective exclusion.
            if not mask.any() or (frame < WARMUP and region != 'revealed'):
                continue
            row = dict(**descriptor, frame=frame, region=region, model=model, clean=clean,
                       **quality(outputs[frame], scene['truth'], mask), **routing(chains[frame], scene, mask))
            if not clean:
                before = quality(raws[frame], scene['truth'], mask)
                row['input_signal_nrmse_percent'] = before['signal_nrmse_percent']
                row['noise_remaining_percent'] = 100*row['signal_nrmse_percent']/max(before['signal_nrmse_percent'], 1e-20)
            if counts is not None:
                row.update(reference_support_min=int(counts[frame][mask].min()),
                           reference_support_p05=float(np.percentile(counts[frame][mask], 5)),
                           reference_support_max=int(counts[frame][mask].max()),
                           reference_zero_support_pixels=int(np.sum(counts[frame][mask] == 0)))
            if frame:
                row.update(residual_change(outputs[frame], scene['truth'], outputs[frame-1],
                           scenes[frame-1]['truth'], scene, scenes[frame-1], mask))
            if region == 'revealed':
                for age in range(3):
                    age_mask = mask & (scene['reveal_age'] == age)
                    if age_mask.any():
                        row[f'reveal_age_{age}'] = quality(outputs[frame], scene['truth'], age_mask)
            rows.append(row)
    return rows


def native_rr(chains, scenes, output, replay):
    packed = [chain['packed'] for chain in chains]
    results = replay.run_rr(output, diffuse=np.stack([p[1] for p in packed]),
        specular=np.stack([p[0] for p in packed]), depth=np.stack([c['linear'] for c in chains]),
        motion=np.stack([p[2] for p in packed]), normals=np.stack([p[3] for p in packed]),
        diffuse_albedo=np.stack([p[5] for p in packed]), specular_albedo=np.stack([p[4] for p in packed]),
        view=np.eye(4), projection=replay.linear_identity_projection(),
        depth_bounds=(0, 1024), tuning=True, pad_native=True)
    return [(results['specular'][f], results['diffuse'][f]) for f in range(FRAMES)], results['metadata']


def guard_volume(directory, width, height, exposure):
    y, x = np.indices((height, width), dtype=np.float32)
    base = .3+.08*x/width+.04*y/height
    volume = .17*np.exp(-((x-.53*width)/(.31*width))**2-((y-.43*height)/(.23*height))**2)
    mask = np.zeros((height, width), bool); mask[5:-5, 5:-5] = True
    scene = dict(normals=t.rgba(width, height, (0, 0, -1)), depth=np.full((height, width), 13, np.float32),
                 diffuse_albedo=t.rgba(width, height, (.5, .5, .5)),
                 specular_albedo=t.rgba(width, height, (.04, .04, .04)),
                 roughness=np.full((height, width), .57, np.float32), motion=t.rgba(width, height, (0, 0, 0)))
    finals, truths, rows = [], [], []
    for frame in (0, 1):
        truth = rgba((base*(1 if frame == 0 else 1.4)+volume)*exposure)
        no_volume = rgba(base*(1 if frame == 0 else 1.4)*exposure)
        scene['truth'] = truth
        chain = seed_pack(truth, scene, directory)
        zero = t.rgba(width, height, (0, 0, 0))
        final = compose(chain, zero, zero, directory)
        no_volume_chain = seed_pack(no_volume, scene, directory)
        no_volume_final = compose(no_volume_chain, zero, zero, directory)
        row = dict(family='volume_lighting_guard', dimensions=[width, height], exposure=exposure,
                   direction='static', seed=0, frame=frame, region='stable', model='rr_erased_lobes', clean=True,
                   **quality(final, truth, mask), **routing(chain, scene, mask))
        volume_truth = truth[..., :3]-no_volume[..., :3]
        volume_output = final[..., :3]-no_volume_final[..., :3]
        row['volume_retention_percent'] = 100*float(np.mean(volume_output[mask]*volume_truth[mask]))/max(float(np.mean(volume_truth[mask]**2)), 1e-20)
        row['volume_component_signal_nrmse_percent'] = 100*rms((volume_output-volume_truth)[mask])/max(rms(volume_truth[mask]), 1e-20)
        finals.append(final); truths.append(truth); rows.append(row)
    gain = 100*float((finals[1][..., :3]-finals[0][..., :3])[mask].mean())/float((truths[1][..., :3]-truths[0][..., :3])[mask].mean())
    for row in rows:
        row['lighting_step_gain_percent'] = gain
    return rows


def run_directory(directory, evidence, replay):
    evidence.mkdir(parents=True, exist_ok=True)
    rows, native_metadata, input_identity = [], [], {}
    for width, height in DIMENSIONS:
        for exposure in EXPOSURES:
            for direction in MANIFEST['directions']:
                descriptor = dict(family='chirp_strokes_partial_reveal', dimensions=[width, height],
                                  exposure=exposure, direction=direction, seed=0)
                scenes = scene_sequence(width, height, exposure, direction)
                scene_label = f'{width}x{height}_{exposure:g}_{direction}'
                input_identity[scene_label] = {key: array_identity([scene[key] for scene in scenes])
                    for key in ('truth', 'diffuse_albedo', 'specular_albedo', 'normals', 'depth', 'motion', 'roughness', 'coverage')}
                clean_chains = [seed_pack(scene['truth'], scene, directory) for scene in scenes]
                clean_outputs = [compose(chain, smooth(chain['packed'][0]), smooth(chain['packed'][1]), directory)
                                 for chain in clean_chains]
                rows += record_frames(clean_outputs, [s['truth'] for s in scenes], clean_chains, scenes,
                                      descriptor, 'controlled_clean_spatial_rr', clean=True)
                for seed in SEEDS:
                    descriptor = dict(descriptor, seed=seed)
                    raws, chains = [], []
                    for frame, scene in enumerate(scenes):
                        raw = noisy_raw(scene, seed, frame)
                        raws.append(raw); chains.append(seed_pack(raw, scene, directory))
                    input_identity[scene_label][f'raw_seed_{seed}'] = array_identity(raws)
                    signals, counts = reference_rr(chains, scenes)
                    outputs = [compose(chain, spec, diff, directory) for chain, (spec, diff) in zip(chains, signals)]
                    current_rows = record_frames(outputs, raws, chains, scenes, descriptor,
                                                 'controlled_noisy_offline_loo_rr', counts)
                    for row in current_rows:
                        frame = row['frame']; mask = scenes[frame]['regions'][row['region']]
                        # Corresponding published guides and routing must match;
                        # the reference cannot exploit a clean/noisy plan change.
                        row['clean_noisy_signal_plan_equal'] = (
                            np.array_equal(chains[frame]['packed'][3][mask], clean_chains[frame]['packed'][3][mask])
                            and all(np.array_equal(chains[frame]['packed'][slot][..., :3][mask],
                                clean_chains[frame]['packed'][slot][..., :3][mask]) for slot in (4, 5)))
                    rows += current_rows
                    poison_frame = WARMUP
                    poisoned = compose(chains[poison_frame], *signals[poison_frame], directory, poison=True)
                    poison_mask = scenes[poison_frame]['regions']['edge'] | scenes[poison_frame]['regions']['revealed']
                    rows.append(dict(**descriptor, frame=poison_frame, region='invalid_history',
                        model='controlled_noisy_offline_loo_rr', clean=False,
                        history_scope='ordinary_inactive_history_isolation_control',
                        invalid_history_exact_fresh=bool(np.array_equal(poisoned[poison_mask], outputs[poison_frame][poison_mask]))))
                    if replay is not None:
                        label = f'{width}x{height}_{exposure:g}_{direction}_{seed}'
                        native_signals, metadata = native_rr(chains, scenes, evidence/('native_'+label), replay)
                        native_outputs = [compose(chain, spec, diff, directory) for chain, (spec, diff) in zip(chains, native_signals)]
                        native_rows = record_frames(native_outputs, raws, chains, scenes, descriptor, 'actual_signed_amd_rr')
                        rows += native_rows
                        native_metadata.append(dict(case=descriptor, metadata=metadata))
                        # Full arrays permit independent visual/metric review.
                        np.savez_compressed(evidence/(label+'.npz'), truth=np.stack([s['truth'] for s in scenes]),
                            raw=np.stack(raws), controlled=np.stack(outputs), native=np.stack(native_outputs),
                            skip=np.stack([c['packed'][6] for c in chains]), material=np.stack([c['packed'][3] for c in chains]))
                    print(f'holdout {width}x{height} exposure={exposure:g} {direction} seed={seed}', flush=True)
            rows += guard_volume(directory, width, height, exposure)
    return rows, native_metadata, input_identity


def shader_identity(directory, frozen=False):
    directory = Path(directory).resolve()
    if frozen and directory == t.PRE.resolve():
        raise ValueError('Frozen baseline must use a separate directory')
    identity = {}
    for name in SHADERS:
        for suffix in ('.hlsl', '_Shader.cso'):
            path = directory/(name+suffix); data = path.read_bytes()
            if frozen:
                base = subprocess.check_output(['git', 'show', f'{BASE_COMMIT}:{BASE_PATH}/{path.name}'], cwd=t.ROOT)
                lhs, rhs = (data.replace(b'\r\n', b'\n'), base.replace(b'\r\n', b'\n')) if suffix == '.hlsl' else (data, base)
                if lhs != rhs:
                    raise ValueError(f'{path} is not frozen {BASE_COMMIT} content')
            identity[path.name] = hashlib.sha256(data).hexdigest()
    for path in sorted(directory.glob('*.hlsli')):
        if frozen:
            base = subprocess.check_output(['git', 'show', f'{BASE_COMMIT}:{BASE_PATH}/{path.name}'], cwd=t.ROOT)
            if path.read_bytes().replace(b'\r\n', b'\n') != base.replace(b'\r\n', b'\n'):
                raise ValueError(f'{path} is not frozen {BASE_COMMIT} include content')
        identity[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(directory=str(directory), commit=BASE_COMMIT if frozen else None, hashes=identity)


def row_key(row):
    return tuple(json.dumps(row.get(key), sort_keys=True) for key in
                 ('family', 'dimensions', 'exposure', 'direction', 'seed', 'frame', 'region', 'model'))


def evaluate(rows, baseline, native_enabled):
    old = {row_key(row): row for row in baseline}; checks = []
    def check(row, name, passed, measured=None, limit=None):
        checks.append(dict(case=row_key(row), check=name, passed=bool(passed), measured=measured, limit=limit))
    for row in rows:
        if row['region'] == 'invalid_history':
            check(row, 'invalid motion poisoned history equals fresh', row['invalid_history_exact_fresh'])
            continue
        check(row, 'nonempty meaningful ROI', row['pixel_count'] >= GATES['min_roi_pixels'], row['pixel_count'], GATES['min_roi_pixels'])
        check(row, 'ordinary material type zero', row['ordinary_material_mask_zero'])
        check(row, 'positive Skip present', row['positive_skip_pixels_percent'] >= 99., row['positive_skip_pixels_percent'], 99.)
        check(row, 'substantial Floor Skip', row['skip_signal_percent'] >= GATES['ordinary_skip_min_signal_percent'],
              row['skip_signal_percent'], GATES['ordinary_skip_min_signal_percent'])
        if row['family'] == 'volume_lighting_guard':
            check(row, 'RR erased volume preserved', row['volume_retention_percent'] >= GATES['volume_retention_min_percent'],
                  row['volume_retention_percent'], GATES['volume_retention_min_percent'])
            check(row, 'lighting step gain', GATES['lighting_step_gain_min_percent'] <= row['lighting_step_gain_percent'] <= GATES['lighting_step_gain_max_percent'],
                  row['lighting_step_gain_percent'], [GATES['lighting_step_gain_min_percent'], GATES['lighting_step_gain_max_percent']])
        else:
            prefix = 'clean' if row['clean'] else 'noisy'
            check(row, prefix+' texture contrast', GATES[prefix+'_contrast_min_percent'] <= row['texture_gain_percent'] <= GATES[prefix+'_contrast_max_percent'],
                  row['texture_gain_percent'], [GATES[prefix+'_contrast_min_percent'], GATES[prefix+'_contrast_max_percent']])
            check(row, prefix+' per-channel bias', row['maximum_channel_bias_percent'] <= GATES[prefix+'_channel_bias_max_percent'],
                  row['maximum_channel_bias_percent'], GATES[prefix+'_channel_bias_max_percent'])
            if row['clean']:
                for metric, gate in (('signal_nrmse_percent', 'clean_signal_nrmse_max_percent'),
                                     ('detail_nrmse_percent', 'clean_detail_nrmse_max_percent')):
                    check(row, 'clean '+metric, row[metric] <= GATES[gate], row[metric], GATES[gate])
            elif row['region'] == 'stable':
                check(row, 'useful independent input noise suppression', row['noise_remaining_percent'] <= GATES['stable_noise_remaining_max_percent'],
                      row['noise_remaining_percent'], GATES['stable_noise_remaining_max_percent'])
            if row['model'] == 'controlled_noisy_offline_loo_rr':
                check(row, 'same clean noisy signal plan', row['clean_noisy_signal_plan_equal'])
            for age in range(3):
                detail = row.get(f'reveal_age_{age}')
                if detail:
                    check(row, f'immediate reveal age{age} channel bias', detail['maximum_channel_bias_percent'] <= GATES[prefix+'_channel_bias_max_percent'],
                          detail['maximum_channel_bias_percent'], GATES[prefix+'_channel_bias_max_percent'])
                    if row['clean']:
                        check(row, f'immediate reveal age{age} signal accuracy', detail['signal_nrmse_percent'] <= GATES['clean_signal_nrmse_max_percent'],
                              detail['signal_nrmse_percent'], GATES['clean_signal_nrmse_max_percent'])
        previous = old.get(row_key(row))
        check(row, 'matching frozen baseline row', previous is not None)
        if previous is not None:
            # Guards operate per frame/ROI. FP16 allowance is an explicitly
            # additive .2% of that ROI's independent truth signal RMS.
            for metric in ('signal_nrmse_percent', 'detail_nrmse_percent', 'contrast_error_percent',
                           'maximum_channel_bias_percent', 'rgb_abs_error_p95_percent',
                           'local_transient_p95_percent', 'local_transient_max_percent',
                           'residual_change_rgb_percent', 'residual_change_luma_percent',
                           'reprojected_residual_change_rgb_percent', 'reprojected_residual_change_luma_percent'):
                if metric not in row or metric not in previous:
                    continue
                allowance = GATES['fp16_signal_rms_allowance_percent']
                if metric == 'detail_nrmse_percent':
                    allowance *= row['signal_rms']/row['detail_rms']
                elif metric == 'contrast_error_percent':
                    allowance = 1.  # Explicit one percentage-point gain tolerance.
                limit = GATES['guard_baseline_max_ratio']*previous[metric]+allowance
                check(row, 'baseline per-frame guard '+metric, row[metric] <= limit, row[metric], limit)
            for age in range(3):
                new_reveal, old_reveal = row.get(f'reveal_age_{age}'), previous.get(f'reveal_age_{age}')
                if new_reveal is None or old_reveal is None:
                    continue
                for metric in ('signal_nrmse_percent', 'maximum_channel_bias_percent',
                               'rgb_abs_error_p95_percent', 'local_transient_p95_percent', 'local_transient_max_percent'):
                    limit = GATES['guard_baseline_max_ratio']*old_reveal[metric]+GATES['fp16_signal_rms_allowance_percent']
                    check(row, f'immediate reveal age{age} baseline guard '+metric, new_reveal[metric] <= limit, new_reveal[metric], limit)
    # Worst-frame errors for each family/ROI/model avoid average masking. The
    # 20% improvement has no FP16 allowance and cannot be bought by regressions
    # in another frame, direction, exposure, seed or ROI.
    groups = {}
    for row in rows:
        if 'pixel_count' not in row or row['family'] != 'chirp_strokes_partial_reveal':
            continue
        key = tuple(json.dumps(row[k], sort_keys=True) for k in ('dimensions', 'exposure', 'direction', 'seed', 'region', 'model'))
        groups.setdefault(key, []).append(row)
    for grouped in groups.values():
        row = grouped[0]; matched = [old.get(row_key(v)) for v in grouped]
        if not all(v is not None for v in matched):
            continue
        metric = 'detail_nrmse_percent' if row['clean'] else 'residual_change_rgb_percent'
        current = max(v.get(metric, 0.) for v in grouped); previous = max(v.get(metric, 0.) for v in matched)
        # Target only clean families that failed the declared absolute blur
        # gate. Every noisy family must materially improve temporal residuals.
        target = (not row['clean']) or previous > GATES['clean_detail_nrmse_max_percent']
        if target:
            limit = GATES['targeted_error_baseline_max_ratio']*previous
            check(row, 'targeted worst-frame '+metric, current <= limit, current, limit)
            if not row['clean'] and row['region'] in ('edge', 'revealed'):
                metric = 'local_transient_p95_percent'
                current = max(v[metric] for v in grouped); previous = max(v[metric] for v in matched)
                limit = GATES['targeted_error_baseline_max_ratio']*previous
                check(row, 'targeted worst-frame local transient p95', current <= limit, current, limit)
    if native_enabled:
        check(dict(family='native_coverage'), 'actual provider covers all heldout noisy sequences',
              len({tuple(row[k] if not isinstance(row[k], list) else tuple(row[k]) for k in
                         ('dimensions', 'exposure', 'direction', 'seed')) for row in rows if row.get('model') == 'actual_signed_amd_rr'}) == 24)
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shader-dir', type=Path, default=t.PRE)
    parser.add_argument('--baseline-dir', type=Path)
    parser.add_argument('--baseline-results', type=Path, help='Reuse authenticated complete frozen measurement JSON')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--measure', action='store_true', help='Measurement only; accepted always false')
    args = parser.parse_args()
    if not args.measure and args.baseline_dir is None:
        parser.error('Acceptance requires --baseline-dir; --measure never accepts')
    args.output = args.output.resolve(); args.output.mkdir(parents=True, exist_ok=True)
    args.shader_dir = args.shader_dir.resolve()
    source_identity = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    dependencies = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ('run_fsrd_gpu_tests.py', 'fsrd_alpha_common.py', 'fsrd_gpu_runner.cpp',
                     'fsrd_floor_rr_replay.py', 'fsrd_floor_rr_replay.cpp', 'fsrd_rr_runner.cpp')}
    result_path = args.output/'results.json'
    result_path.write_text(json.dumps(dict(schema='fsrd_floor_quality_holdout_v1', completed=False,
        accepted=False, manifest_sha256=MANIFEST_HASH, test_source_sha256=source_identity),
        sort_keys=True)+'\n', encoding='utf-8')
    frozen_measurement = args.shader_dir != t.PRE.resolve() and args.measure
    identity_before = shader_identity(args.shader_dir, frozen=frozen_measurement)
    baseline_identity = None
    if args.baseline_dir:
        args.baseline_dir = args.baseline_dir.resolve()
        if args.baseline_dir == args.shader_dir:
            parser.error('Candidate and frozen baseline directories must differ')
        baseline_identity = shader_identity(args.baseline_dir, frozen=True)
    import fsrd_floor_rr_replay as replay_module
    replay = replay_module if replay_module.DLL.is_file() else None
    # Availability is recorded. If native is present, all paired sequences must
    # execute it; there is deliberately no switch that disables its failed gates.
    t.OUT = args.output/'gpu_jobs'; t.OUT.mkdir(exist_ok=True)
    t.runner = args.output/'fsrd_gpu_runner.exe'; t.build_runner()
    baseline, baseline_native, baseline_inputs = [], [], {}
    if args.baseline_results:
        if baseline_identity is None:
            parser.error('--baseline-results also requires --baseline-dir')
        previous = json.loads(args.baseline_results.read_text(encoding='utf-8'))
        if (previous.get('manifest_sha256') != MANIFEST_HASH or previous.get('test_source_sha256') != source_identity
                or previous.get('dependency_source_hashes') != dependencies
                or previous.get('shader_identity') != baseline_identity
                or previous.get('native_enabled') != (replay is not None) or not previous.get('completed')):
            raise ValueError('Cached baseline has wrong fixtures, frozen shader hashes, native plan, or incomplete run')
        baseline, baseline_native, baseline_inputs = previous['records'], previous['native_metadata'], previous['input_identity']
    elif baseline_identity is not None:
        baseline, baseline_native, baseline_inputs = run_directory(args.baseline_dir, args.output/'baseline_evidence', replay)
    rows, native_metadata, input_identity = run_directory(args.shader_dir, args.output/'candidate_evidence', replay)
    if baseline_inputs and baseline_inputs != input_identity:
        raise RuntimeError('Candidate and frozen baseline generated input hashes differ')
    if shader_identity(args.shader_dir, frozen=frozen_measurement) != identity_before:
        raise RuntimeError('Candidate shader/source artifacts changed during the heldout run')
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != source_identity:
        raise RuntimeError('Heldout fixture/test source changed during measurement')
    if baseline_identity and shader_identity(args.baseline_dir, frozen=True) != baseline_identity:
        raise RuntimeError('Frozen baseline artifacts changed during the heldout run')
    checks = evaluate(rows, baseline, replay is not None)
    failed = [check for check in checks if not check['passed']]
    result = dict(schema='fsrd_floor_quality_holdout_v1', completed=True,
                  mode='measure_only' if args.measure else 'acceptance', accepted=not args.measure and not failed,
                  manifest=MANIFEST, manifest_sha256=MANIFEST_HASH, shader_identity=identity_before,
                  test_source_sha256=source_identity,
                  dependency_source_hashes=dependencies, input_identity=input_identity,
                  gpu_runner_source_sha256=hashlib.sha256(t.source.read_bytes()).hexdigest(),
                  gpu_runner_sha256=hashlib.sha256(t.runner.read_bytes()).hexdigest(),
                  native_enabled=replay is not None, native_metadata=native_metadata,
                  native_unavailable_reason=None if replay else 'Signed AMD DLL missing; controlled reference coverage only',
                  frozen_baseline=baseline_identity, baseline_records=baseline, baseline_native_metadata=baseline_native,
                  records=rows, checks=checks,
                  dispatches=[{key: value for key, value in record.items() if key in
                               ('shader', 'size', 'repetitions', 'shader_sha256', 'adapter', 'debug_layer',
                                'validation_errors', 'validation_warnings')} for record in t.timings],
                  disclosures=['Controlled noisy RR uses future same-surface frames and excludes current frame.',
                               'Independent truth is analytic radiance, not shader output.',
                               'First partial reveal and local reveal ages0/1/2 are scored immediately.',
                               'Ordinary routing/Skip gates prevent compatibility handover bypass.',
                               'History poison is an ordinary inactive-history isolation control; positive handover history requires the separate composition_temporal suite.',
                               'Native RR uses the exact perspective ray equivalent of shader linear-identity reconstruction; extents below64 use disclosed inactive physical padding and logical output crop.'])
    path = result_path
    # Wall duration is operational logging, not part of deterministic evidence.
    for provider_record in result['native_metadata']+result['baseline_native_metadata']:
        provider_record['metadata'].pop('seconds', None)
    path.write_text(json.dumps(result, indent=2, allow_nan=False, sort_keys=True)+'\n', encoding='utf-8')
    print(f'{"MEASUREMENT ONLY" if args.measure else "ACCEPTANCE"}: {len(checks)-len(failed)}/{len(checks)} gates; {len(t.timings)} GPU dispatches; {path}', flush=True)
    if failed and not args.measure:
        raise AssertionError(f'{len(failed)} immutable heldout acceptance gates failed; inspect {path}')


if __name__ == '__main__':
    main()
