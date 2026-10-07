"""GPU Floor disocclusion evidence with independent clean textured truth.

--measure is evidence only, never acceptance. Acceptance requires a frozen
49b743d4 report and a distinct candidate, and always runs all disclosed and
holdout cases. Production FloorSeed, five Floor passes, packing and composition
execute on D3D12. The deliberately labelled synthetic RR is a surface-guided
spatial filter of actual packed signals; it never receives clean truth or
subtracts current Skip. Floor/reference/Skip metrics remain separately visible.
The main sequence uses synthetic RR. --score-actual-rr verifies saved native
AMD RR readbacks and composes them through the production output shader; those
partial measurements remain separate evidence and cannot certify game quality.
"""
from pathlib import Path
import argparse
import hashlib
import inspect
import json
import subprocess
import sys

import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_alpha_common as c


BASE = '49b743d4'
SCHEMA = 'fsrd-floor-disocclusion-v2'
SHADER_PATH = 'OptiScaler/shaders/fsrd_preprocess/precompile'
DEFAULT_BASELINE = t.ROOT / 'tools_tmp/floor_quality_49b743d4/baseline/precompile'
DEFAULT_OUTPUT = t.ROOT / 'tools_tmp/floor_quality_49b743d4/disocclusion_baseline'
W, H, FRAMES = 97, 65, 32
LUMA = np.array([.2126, .7152, .0722], np.float32)

# Declared before candidate tuning. All errors are divided by the known incident
# illumination level, not by a candidate output statistic. Relative comparison
# alone cannot pass: absolute bounds and texture/noise/instant-step gates apply.
GATES = dict(targeted_reduction=.30, reveal_rmse=.08, reveal_p95=.15,
             temporal_std=.030, residual_change_p95=.080, bias=.05,
             texture_gain_min=.85, texture_gain_max=1.12,
             noise_regression=1.05, noise_input_ratio=.80,
             lighting_step_relative_error=.06, exposure_relative_error=.03,
             ordinary_fraction_min=.95, skip_fraction_min=.05,
             first_reveal_rmse=.09, reveal_rgb_p99=.25,
             rgb_change_rms=.10, reveal_rgb_bias=.06,
             clean_temporal_std=.0025, clean_change_p95=.010,
             guard_temporal_allowance=.0005, guard_change_allowance=.001)


GAIN_REGRESSION_CONTRACT = dict(version='fsrd_texture_gain_regression_v3',
    target_gain=1.0, allowance=0.01, bounded_errors=['under', 'over'],
    cross_sign_budget_transfer=False,
    scope='synthetic and actual-native primary overall texture gain and first two reveal-age gains')


def dependency_identity():
    here = Path(__file__).resolve().parent
    names = ('run_fsrd_gpu_tests.py', 'fsrd_alpha_common.py', 'fsrd_gpu_runner.cpp',
             'fsrd_floor_rr_replay.py', 'fsrd_rr_runner.cpp')
    return dict(python=sys.version, numpy=np.__version__,
                sources={name: hashlib.sha256((here / name).read_bytes()).hexdigest() for name in names})


def cases():
    rows = []
    for name, level in [('dark', .025), ('bright', .7), ('hdr', 12000.)]:
        for noise in ('independent', 'correlated'):
            rows.append(dict(name=name + '_' + noise, level=level, noise=noise,
                             seed=91713, polarity='bright_reveal', control='stable', holdout=False))
    rows += [dict(name='dark_reveal', level=.7, noise='independent', seed=61519,
                  polarity='dark_reveal', control='stable', holdout=False),
             dict(name='true_lighting_step', level=.7, noise='none', seed=51791,
                  polarity='bright_reveal', control='step', holdout=False),
             dict(name='exposure', level=.7, noise='independent', seed=91813,
                  polarity='bright_reveal', control='exposure', holdout=False),
             dict(name='clean_texture', level=.7, noise='none', seed=80157,
                  polarity='bright_reveal', control='stable', holdout=False)]
    for name, noise, seed, polarity in [('holdout_bright', 'correlated', 21877, 'bright_reveal'),
                                          ('holdout_dark', 'independent', 71833, 'dark_reveal')]:
        rows.append(dict(name=name, level=.18, noise=noise, seed=seed,
                         polarity=polarity, control='stable', holdout=True))
    return rows


def luminance(a):
    return np.asarray(a)[..., :3] @ LUMA


def shifted(a, dx, dy):
    """Clamp at fixture extent; validity is handled by the geometry mask."""
    yi = np.clip(np.arange(a.shape[0]) + dy, 0, a.shape[0] - 1)
    xi = np.clip(np.arange(a.shape[1]) + dx, 0, a.shape[1] - 1)
    return a[yi[:, None], xi[None, :]]


def texture(seed):
    """A multitone woven/printed material, including independently rastered ink.

    It is procedural clean truth, not a photograph or an input reconstructed from
    the algorithm under test. One-pixel yarn, four-pixel tiles, curved colour
    strokes and 5x7 text all occur in the revealed area, precluding flat fixtures.
    """
    y, x = np.indices((H, W), dtype=np.float32)
    phase = (seed % 197) / 197.
    weave = (.12 * np.sin(x * 1.13 + phase) * np.cos(y * .91)
             + .06 * ((x.astype(int) % 4 == 0).astype(float) - (y.astype(int) % 5 == 0).astype(float))
             + .11 * np.sin(x * .13 + y * .07 + phase))
    tile = .08 * ((x.astype(int) // 4 + y.astype(int) // 5) % 2 * 2 - 1)
    a = np.stack([.57 + weave + tile,
                  .61 + .8 * weave - .3 * tile,
                  .53 + .6 * weave + .7 * tile], axis=-1)
    bits = np.array(list('11110100011000111110100011000111110')) == '1'
    ink = np.zeros((H, W), bool)
    for row in (15, 32, 49):
        for col in range(12, 85, 8):
            ink[row:row + 7, col:col + 5] |= bits.reshape(7, 5)
    a[ink] *= .35
    return np.clip(a, .08, .9).astype(np.float32), ink


def fixture(case):
    a, ink = texture(case['seed'])
    y, x = np.indices((H, W))
    roi = (x >= 39) & (x <= 81) & (y >= 9) & (y <= 57)
    quiet = (x >= 9) & (x <= 28) & (y >= 10) & (y <= 56)
    frames = []
    age = np.full((H, W), -1, np.int16)
    previous = np.ones((H, W), bool)
    rng = np.random.default_rng(case['seed'])
    for f in range(FRAMES):
        # A moving comb-shaped plate exposes narrow textured strips before they
        # join the broad background. Slots have only 5..9 same-depth 5x5 taps.
        edge = 37 + max(f - 4, 0) * 2
        fingers = np.where(y % 7 == 3, 8, np.where(y % 7 == 4, 5, 0))
        boundary = edge + fingers + (np.sin(y * .21) * 2).astype(int)
        occluded = x > boundary
        revealed = previous & ~occluded
        age[~occluded] += 1
        age[revealed] = 0
        age[occluded] = -1
        previous = occluded
        illumination = (1.7 if f >= 20 else 1.) if case['control'] == 'step' else 1.
        exposure = (.5 if f < 12 else 2. if f < 22 else 1.) if case['control'] == 'exposure' else 1.
        bg_scale = .22 if case['polarity'] == 'dark_reveal' else 1.
        fg_scale = 1.6 if case['polarity'] == 'dark_reveal' else .045
        clean = a * (case['level'] * bg_scale * illumination)
        clean[occluded] = case['level'] * fg_scale * np.array([.9, .8, .7])
        clean *= exposure
        noisy = clean.copy()
        if case['noise'] != 'none':
            noise = rng.normal(size=(H, W, 3)).astype(np.float32)
            if case['noise'] == 'correlated':
                # Independent frames, spatially correlated samples. No history
                # or clean signal feeds the stochastic generator.
                noise = sum(shifted(noise, dx, dy) for dx, dy in
                            ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))) / np.sqrt(5.)
            noisy += noise * (.065 * case['level'] * bg_scale * exposure)
        noisy = np.maximum(noisy, 0)
        depth = np.where(occluded, 4., 10.).astype(np.float32)
        normals = t.rgba(W, H, (0, 0, -1))
        normals[occluded, :3] = (0, .6, -.8)
        albedo = c.rgba(a)
        albedo[occluded, :3] = (.14, .19, .23)
        motion = t.rgba(W, H, (0, 0, 0), 1)
        motion[occluded, 0] = -2 / W if f > 4 else 0
        motion[revealed, 3] = 0
        bias = t.rgba(W, H, (0, 0, 0))
        bias[occluded, :3] = .6
        support = sum(shifted((~occluded).astype(np.int16), dx, dy)
                      for dx in range(-2, 3) for dy in range(-2, 3))
        frames.append(dict(clean=c.rgba(clean), raw=c.rgba(noisy), depth=depth,
                           normals=normals, albedo=albedo, motion=motion, bias=bias,
                           visible=~occluded, age=age.copy(), support=support,
                           exposure=exposure, scale=case['level'] * bg_scale * illumination,
                           illumination=illumination, roi=roi, quiet=quiet, ink=ink))
    return frames


def authenticate_baseline(directory):
    """Frozen baseline must contain the actual committed production DXIL."""
    directory = Path(directory).resolve()
    if directory == t.PRE.resolve():
        raise ValueError('Current production directory cannot be the baseline')
    result = {}
    for name in ('FSRDFloorSeed', 'FSRDFloor', 'FSRDInputConv', 'FSRDOutputComp'):
        for suffix in ('.hlsl', '_Shader.cso'):
            path = directory / (name + suffix)
            original = subprocess.check_output(['git', 'show', f'{BASE}:{SHADER_PATH}/{path.name}'], cwd=t.ROOT)
            actual = path.read_bytes()
            compared = (lambda x: x.replace(b'\r\n', b'\n')) if suffix == '.hlsl' else (lambda x: x)
            if compared(actual) != compared(original):
                raise ValueError(f'Baseline {path.name} differs from {BASE}')
            result[path.name] = hashlib.sha256(actual).hexdigest()
    return result


def synthetic_rr(signal, depth, albedo):
    """Explicit fake RR: actual signal only, five same-surface spatial taps.

    No clean truth, current Skip, measured Floor, or candidate identity enters
    this model. It is intentionally current-frame so lighting lag cannot be
    hidden by an invented temporal denoiser.
    """
    total = np.ones((H, W, 1), np.float32)
    result = signal[..., :3].copy()
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        z = shifted(depth, dx, dy)
        material = np.max(np.abs(shifted(albedo[..., :3], dx, dy) - albedo[..., :3]), axis=-1)
        weight = ((np.abs(z - depth) < .01) & (material < .25))[..., None] * .5
        result += shifted(signal[..., :3], dx, dy) * weight
        total += weight
    out = signal.copy()
    out[..., :3] = result / total
    return out


def seed_floor(raw, albedo, depth, normals, directory):
    """Keep historical four-SRV Floor and immutable-reference candidates explicit.

    Seed RGB/uncertainty is captured once. Every candidate Floor scale receives
    that same seed reference, never an output from an earlier filtering pass.
    """
    h, w = raw.shape[:2]
    values = dict(InvProjMatrix=np.eye(4).ravel(), RenderSize=[w, h, 1 / w, 1 / h],
                  NearPlane=.1, FarPlane=10000, Flags=1, FloorEnabled=1)
    floor, linear, guide, reference = t.dispatch('FSRDFloorSeed', values,
        [raw, normals, depth, depth, albedo], [10, 41, 10, 10], (w, h), directory=directory)
    reference_bound = 'InDetailReference' in (directory / 'FSRDFloor.hlsl').read_text(encoding='utf-8')
    for step in (1, 2, 4, 8, 16):
        inputs = [floor, linear, guide, albedo]
        if reference_bound:
            inputs.append(reference)
        floor = t.dispatch('FSRDFloor', dict(DstTexSize=[w, h, 1 / w, 1 / h], StepSize=step),
                           inputs, [10], (w, h), directory=directory)[0]
    return floor, linear, reference


def residual_source(data, floor, reference, material, directory, enabled, model=None):
    """Accounting oracle only; clean truth never enters this source estimate.

    The fixture fixes roughness .45, full modulation, valid material albedos,
    no emission/responsivity/half/unsupported flags, and a nonzero bias only on
    the foreground. Route selection is read back from actual conversion. An
    unknown source/model expression fails closed rather than assuming raw.
    """
    raw = np.clip(data['raw'].astype(np.float16).astype(np.float32)[..., :3], 0, 65500.)
    source = raw.copy()
    weight = np.zeros(raw.shape[:2], np.float32)
    text = (directory / 'FSRDInputConv.hlsl').read_text(encoding='utf-8')
    if 'const float3 residualSource' not in text or not enabled:
        return c.rgba(source), weight, 'original_raw_source'
    compact = ''.join(text.split())
    required = ('floorModel.a>=0.5f', 'any(materialSlope>0.0f)',
                'specularStrength==1.0f&&diffuseStrength==1.0f')
    reference_source = ('constfloat3residualSource=lerp(rawColor,FloorRadiance(detailReference.rgb),sourceWeight);' in compact
                        and 'smoothstep(0.005f,0.025f,detailReference.a/max(rawLuma,1e-5f))' in compact)
    floor_source = ('constfloat3residualSource=lerp(rawColor,spatialFloor,sourceWeight);' in compact
                    and 'smoothstep(0.005f,0.025f,detailReference.a/max(GetLuminance(FloorRadiance(detailReference.rgb)),1e-5f))' in compact)
    model_text = ''.join((directory / 'FSRDFloorModel.hlsli').read_text(encoding='utf-8').split())
    channel_source = ('constfloatplaneConfidence=FloorPlaneConfidence(floorModel);' in compact
                      and 'constfloatmodelSourceWeight=ordinaryNoiseModel&&(any(materialSlope>0.0f)||planeConfidence>0.0f)&&detailReference.a>=0.0f' in compact
                      and 'constfloat3sourceWeight=modelSourceWeight*max(all(materialSlope>0.0f)?1.0f:0.0f,planeConfidence);' in compact
                      and 'floatFloorPlaneConfidence(float4model){returnmodel.a>=2.0f?saturate(model.a-2.0f):0.0f;}' in model_text
                      and 'floatFloorClippingNoiseRatio(float4model){returnmodel.a<2.0f?max(model.a-1.0f,0.0f):0.0f;}' in model_text)
    if 'constfloat3sourceWeight=' in compact and not channel_source:
        raise ValueError('Unknown per-channel filtered residual-source contract')
    if reference_source == floor_source or not all(token in compact for token in required) or 'model.x>-99.0f?exp2(model.x):0.0f' not in model_text:
        raise ValueError('Unknown filtered residual-source accounting contract')
    model = getattr(floor, '_floor_model', None) if model is None else model
    if model is None or np.asarray(model).shape != (*raw.shape[:2], 4):
        raise ValueError('Filtered-source conversion lacks its actual Floor model')
    model = np.asarray(model, np.float32)
    plane = np.where(model[..., 3] >= 2., np.clip(model[..., 3] - 2., 0, 1), 0) if channel_source else np.zeros(raw.shape[:2], np.float32)
    positive = model[..., :3] > -99.
    ref = np.clip(np.asarray(reference)[..., :3], 0, 65500.)
    albedo = data['albedo'].astype(np.float16).astype(np.float32)[..., :3]
    valid = (np.isfinite(model).all(axis=-1) & (model[..., 3] >= .5)
             & (np.any(positive, axis=-1) | (plane > 0))
             & np.isfinite(reference).all(axis=-1) & (reference[..., 3] >= 0)
             & (material < .1) & (data['bias'][..., 0] == 0)
             & (albedo >= 0).all(axis=-1) & (albedo <= 1.001).all(axis=-1)
             & (luminance(albedo) >= .02))
    ratio = reference[..., 3] / np.maximum(luminance(ref if floor_source else raw), 1e-5)
    u = np.clip((ratio - .005) / .020, 0, 1)
    weight[valid] = (u * u * (3 - 2 * u))[valid]
    if channel_source:
        # One source decision for all channels: a partial-channel model keeps raw.
        weight = np.repeat(weight[..., None] * np.maximum(positive.all(axis=-1).astype(np.float32),
                                                           plane)[..., None], 3, axis=-1)
    # Only the ordinary, positive-roughness fixture may use this oracle. On its
    # eligible pixels production spatialFloor is exactly the captured Floor.
    endpoint = np.clip(np.asarray(floor)[..., :3], 0, 65500.) if floor_source else ref
    source += (endpoint - raw) * (weight if channel_source else weight[..., None])
    return c.rgba(source), weight, ('trusted_material_per_channel_plane_source' if channel_source
                                   else 'trusted_material_floor_source' if floor_source
                                   else 'trusted_material_filtered_source')


def model_tags(model, directory):
    model = np.asarray(model)
    plane_header = 'float FloorPlaneConfidence' in (directory / 'FSRDFloorModel.hlsli').read_text(encoding='utf-8') if (directory / 'FSRDFloorModel.hlsli').exists() else False
    plane = np.where(model[..., 3] >= 2., np.clip(model[..., 3] - 2., 0, 1), 0) if plane_header else np.zeros(model.shape[:2], np.float32)
    kind = np.zeros(model.shape[:2], np.uint8)
    kind[model[..., 3] >= .5] = 2  # valid zero slope / clipping-noise payload
    kind[(model[..., 3] >= .5) & np.any(model[..., :3] > -99., axis=-1)] = 1
    if plane_header:
        kind[model[..., 3] >= 2.] = 3
    return plane.astype(np.float32), kind


def _validated_current_source(saved, frames, enabled):
    """Validate the raw-class certificate against original current observations.

    These fixtures use full modulation, positive roughness, no unsupported or
    responsivity flags, and a constant .08 specular albedo. Both an ordinary
    model surface and an already selected screen may carry the certificate.
    Seed Reference retains C19 colour and uncertainty. Only marked packed
    Reference/Skip RGB consume safe original Raw once; native RR remains the
    separate, unchanged history submission.
    """
    skip = np.asarray(saved['skip'])
    marked = skip[..., 3] == -1.
    source = np.zeros_like(skip[..., :3])
    if not np.any(marked):
        return marked, source
    required = ('floor_model', 'reference', 'packed_reference', 'material', 'input')
    if not enabled or not all(key in saved for key in required):
        raise ValueError('Marked current source lacks enabled Floor and independent model/reference captures')
    model, reference, packed_reference = (np.asarray(saved[key]) for key in required[:3])
    material = np.asarray(saved['material'])
    original_raw = np.stack([data['raw'] for data in frames])
    captured_input = np.asarray(saved['input'])
    if (model.shape != skip.shape or reference.shape != skip.shape
            or packed_reference.shape != skip.shape or material.shape != marked.shape
            or original_raw.shape != skip.shape or captured_input.shape != skip.shape):
        raise ValueError('Marked current-source capture shapes differ')
    bias = np.stack([data['bias'][..., 0] for data in frames])
    albedo = np.stack([data['albedo'][..., :3] for data in frames]).astype(np.float16).astype(np.float32)
    specular = float(np.float16(.08))
    safe_raw = np.clip(original_raw[..., :3], 0, 65500.).astype(np.float16).astype(np.float32)
    safe_packed_reference = np.clip(packed_reference[..., :3], 0, 65500.).astype(np.float16).astype(np.float32)
    # Material alpha is decoded R10G10B10A2_UNORM, not an FP16 payload.
    ordinary_or_selected = ((material == 0.) | (material == np.float32(1 / 3)))
    eligible = (np.isfinite(model).all(axis=-1) & (model[..., 3] >= .5)
                & np.all(model[..., :3] == -101., axis=-1)
                & np.isfinite(original_raw).all(axis=-1) & np.isfinite(captured_input).all(axis=-1)
                & np.all(captured_input == original_raw, axis=-1)
                & np.isfinite(reference).all(axis=-1) & (reference[..., 3] >= 0)
                & np.all(reference[..., :3] >= 0, axis=-1)
                & np.isfinite(packed_reference).all(axis=-1) & (packed_reference[..., 3] >= 0)
                & np.all(packed_reference[..., :3] >= 0, axis=-1)
                & np.all(packed_reference[..., :3] == safe_packed_reference, axis=-1)
                & np.all(packed_reference[..., :3] == safe_raw, axis=-1)
                & (packed_reference[..., 3] == reference[..., 3].astype(np.float16).astype(np.float32))
                & np.isfinite(skip).all(axis=-1)
                & np.all(skip[..., :3] == safe_packed_reference, axis=-1)
                & ordinary_or_selected & (bias == 0.)
                & np.isfinite(albedo).all(axis=-1) & np.all(albedo >= 0., axis=-1)
                & np.all(albedo <= 1.001, axis=-1) & (luminance(albedo) >= .02)
                & np.all(albedo + specular <= 1., axis=-1))
    if np.any(marked & ~eligible):
        f, y, x = np.argwhere(marked & ~eligible)[0]
        raise ValueError('Marked current source lacks a safe original current-Raw certificate: '
            + json.dumps(dict(frame=int(f), xy=[int(x), int(y)], model=model[f, y, x].tolist(),
                reference=reference[f, y, x].tolist(), packed_reference=packed_reference[f, y, x].tolist(),
                original_raw=original_raw[f, y, x].tolist(), captured_input=captured_input[f, y, x].tolist(),
                expected_safe_raw=safe_raw[f, y, x].tolist(),
                skip=skip[f, y, x].tolist(), material=float(material[f, y, x]))))
    source[marked] = safe_raw[marked]
    return marked, source


def _consume_current_source(remodulated, skip, marked):
    """Pre-recovery consumer colour; the marked native copy is not added."""
    original = remodulated + skip[..., :3]
    return np.where(marked[..., None], skip[..., :3], original)


def _current_source_activity(marked, actual_rr, mask, normalization):
    """Disclose ignored actual RR activity without treating it as final colour."""
    ignored = marked & mask
    normalized = actual_rr / normalization

    def summarize(selected, region, signal):
        samples = int(selected.sum())
        return dict(marked_samples=samples, samples=int(region.sum()),
                    marked_fraction=samples / max(int(region.sum()), 1),
                    ignored_actual_rr_rgb_rms=(np.sqrt(np.mean(signal[selected] ** 2, axis=0)).tolist()
                                               if samples else [0., 0., 0.]),
                    ignored_actual_rr_abs_max=float(np.max(np.abs(signal[selected]))) if samples else 0.)

    result = summarize(ignored, mask, normalized)
    result['per_frame'] = [dict(frame=f, **summarize(ignored[f], mask[f], normalized[f]))
                           for f in range(marked.shape[0])]
    return result


def verify_source_accounting(saved, packed, frames, directory, enabled):
    """Verify the explicit filtered target, separately from truth-quality gates."""
    marked, current_source = _validated_current_source(saved, frames, enabled)
    filtered = 'const float3 residualSource' in (directory / 'FSRDInputConv.hlsl').read_text(encoding='utf-8')
    if not filtered or not enabled:
        return dict(contract='original_raw_source', filtered_source_verified=False)
    if not all(key in saved for key in ('residual_source', 'source_weight', 'floor_model')):
        raise ValueError('Filtered-source export lacks explicit target/model/weight')
    worst, samples = 0., 0
    for f, data in enumerate(frames):
        target, weight, contract = residual_source(data, saved['floor'][f], saved['reference'][f],
            saved['material'][f], directory, enabled, saved['floor_model'][f])
        if not np.array_equal(target, saved['residual_source'][f]) or not np.array_equal(weight, saved['source_weight'][f]):
            raise ValueError('Exported filtered source cannot be independently reconstructed')
        if 'plane_confidence' in saved:
            plane, tag = model_tags(saved['floor_model'][f], directory)
            if not np.array_equal(plane, saved['plane_confidence'][f]) or not np.array_equal(tag, saved['model_kind'][f]):
                raise ValueError('Captured model plane confidence/tag differs from its explicit header contract')
        mask = data['visible'] & ((saved['material'][f] < .1) | marked[f])
        # Positive residual storage retains a crossing Floor estimate. This
        # disclosed term is not a quality allowance: metrics still use clean truth.
        expected = np.maximum(target[..., :3], saved['floor'][f, ..., :3])
        # The already existing zero-slope branch compensates truncated noise by
        # lowering only Skip; its positive residual still uses the original F.
        # Include that declared term in accounting, never in clean truth.
        model = saved['floor_model'][f]
        flat = ((model[..., 3] >= .5) & np.all(model[..., :3] <= -99., axis=-1)
                & mask & ~marked[f])
        if np.any(flat):
            conversion = ''.join((directory / 'FSRDInputConv.hlsl').read_text(encoding='utf-8').split())
            multiplicative = 'if(ordinaryNoiseModel&&!any(materialSlope>0.0f))floorColor.rgb*=1.0f-min(0.15f*max(floorModel.a-1.0f,0.0f),0.05f);' in conversion
            common_rgb = ('if(ordinaryNoiseModel&&detailReference.a>=0.0f&&!any(materialSlope>0.0f))'
                          '{constfloatclippingBias=0.15f*max(floorModel.a-1.0f,0.0f)*GetLuminance(floorColor.rgb);'
                          'floorColor.rgb=max(floorColor.rgb-min(clippingBias,0.05f*floorColor.rgb),0.0f);}') in conversion
            plane_rgb = ('if(ordinaryNoiseModel&&detailReference.a>=0.0f&&planeConfidence==0.0f&&!any(materialSlope>0.0f))'
                         '{constfloatclippingBias=0.15f*FloorClippingNoiseRatio(floorModel)*GetLuminance(floorColor.rgb);'
                         'floorColor.rgb=max(floorColor.rgb-min(clippingBias,0.05f*floorColor.rgb),0.0f);}') in conversion
            if sum((multiplicative, common_rgb, plane_rgb)) != 1:
                raise ValueError('Unknown zero-slope source-accounting compensation')
            original_floor = saved['floor'][f, ..., :3]
            sigma_ratio = .15 * np.maximum(model[..., 3] - 1., 0)
            if plane_rgb:
                plane, _ = model_tags(model, directory)
                flat &= plane == 0
                sigma_ratio = .15 * np.where(model[..., 3] < 2., np.maximum(model[..., 3] - 1., 0), 0)
            if common_rgb or plane_rgb:
                flat &= saved['reference'][f, ..., 3] >= 0
                correction = np.minimum((sigma_ratio * luminance(original_floor))[..., None], .05 * original_floor)
            else:
                correction = original_floor * np.minimum(sigma_ratio, .05)[..., None]
            expected[flat] -= correction[flat]
        expected[marked[f]] = current_source[f][marked[f]]
        remodulated = (packed['diffuse'][f, ..., :3] * packed['diffuse_albedo'][f, ..., :3]
                       + packed['specular'][f, ..., :3] * packed['specular_albedo'][f, ..., :3])
        reconstructed = _consume_current_source(remodulated, saved['skip'][f], marked[f])
        error = np.abs(reconstructed - expected)
        bound = .002 * np.maximum(expected, 0) + 2e-5
        if np.any(error[mask] > bound[mask]):
            bad = (error > bound) & mask[..., None]
            y, x, channel = np.argwhere(bad)[np.argmax(error[bad])]
            raise ValueError('Packed signals/Skip do not reconstruct the explicit filtered target within FP16 tolerance: '
                + json.dumps(dict(frame=f, xy=[int(x), int(y)], channel=int(channel),
                    expected=expected[y, x].tolist(), reconstructed=reconstructed[y, x].tolist(),
                    target=target[y, x].tolist(), weight=np.asarray(weight[y, x]).tolist(),
                    floor=saved['floor'][f, y, x].tolist(), model=saved['floor_model'][f, y, x].tolist())))
        worst = max(worst, float(np.max(error[mask]) / (data['scale'] * data['exposure'])))
        samples += int(mask.sum())
    return dict(contract=contract, filtered_source_verified=True,
                max_illumination_normalized_accounting_error=worst, samples=samples,
                storage_tolerance='0.002 * expected_channel + 0.00002',
                marked_current_source_samples=int(marked.sum()),
                marked_current_source_samples_per_frame=marked.sum(axis=(1, 2)).tolist(),
                current_source_contract='Skip.A=-1 consumes safe FP16 original current Raw once; packed Reference/Skip RGB must match that independent observation while Seed Reference retains legacy colour/uncertainty; native RR remains an unconsumed history copy on marked lanes',
                crossing_contract='unmarked: target + positive(Floor-target) minus declared zero-slope sigma compensation; quality always scored against clean truth')


def gpu_sequence(frames, directory, enabled, export=None):
    arrays = {k: [] for k in ('final', 'reference', 'packed_reference', 'floor', 'skip', 'material', 'input',
                             'residual_source', 'source_weight', 'floor_model', 'plane_confidence', 'model_kind')}
    rr_arrays = {k: [] for k in ('diffuse', 'specular', 'depth', 'motion', 'normals', 'diffuse_albedo', 'specular_albedo')}
    history = None
    for f, data in enumerate(frames):
        if enabled:
            floor, depth, reference = seed_floor(data['raw'], data['albedo'], data['depth'],
                                                 data['normals'], directory)
        else:
            floor = np.zeros_like(data['raw'])
            reference = np.zeros_like(data['raw'])
            depth = data['depth']
        packed = c.convert(data['raw'], data['albedo'], t.rgba(W, H, (.08, .08, .08)),
                           directory=directory, depth=depth, normals=data['normals'],
                           roughness=np.full((H, W), .45, np.float32), floor=floor if enabled else None,
                           reference=reference, motion=data['motion'],
                           overrides=dict(Flags=(1 << 1) | (1 << 4) | (1 << 5) | (1 << 15) |
                                          ((1 << 7) if enabled else 0)), resources={8: data['bias']})
        dd = synthetic_rr(packed[1], depth, packed[5])
        ss = synthetic_rr(packed[0], depth, packed[4])
        cb = dict(DstTexSize=[W, H, 1 / W, 1 / H], Flags=1 << 3,
                  DetailPreservation=1 if enabled else 0, RecoveryMask=1,
                  FloorHandoverAnchorClamp=4, FloorHandoverCorrelationMix=1,
                  LumaRecovery=1, ChromaRecovery=1, SpecularAlbedoDemodulation=1,
                  DiffuseAlbedoModulation=1, DemodDivisorFloor=.008,
                  SpatialTemporalMask=0, WriteHistory=1, HistoryValid=int(history is not None))
        inputs = [ss, packed[4], dd, packed[5], packed[6], packed[3], packed[7], depth,
                  packed[2], t.rgba(W, H, (-1, -1, -1), -1) if history is None else history[1],
                  np.zeros((H, W, 4), np.uint32) if history is None else history[2]]
        history = t.dispatch('FSRDOutputComp', cb, inputs, [10, 10, 3], (W, H), directory=directory)
        model = getattr(floor, '_floor_model', None)
        target, source_weight, source_contract = residual_source(data, floor, reference, packed[3][..., 3], directory, enabled)
        saved_model = np.zeros_like(floor) if model is None else model
        plane, kind = model_tags(saved_model, directory)
        for key, value in dict(final=history[0], reference=reference, packed_reference=packed[7], floor=floor,
                               skip=packed[6], material=packed[3][..., 3], input=data['raw'],
                               residual_source=target, source_weight=source_weight,
                               floor_model=saved_model, plane_confidence=plane, model_kind=kind).items():
            arrays[key].append(value)
        if export:
            for key, value in dict(diffuse=packed[1], specular=packed[0], depth=depth,
                                   motion=packed[2], normals=packed[3], diffuse_albedo=packed[5],
                                   specular_albedo=packed[4]).items():
                rr_arrays[key].append(value)
        if (f + 1) % 8 == 0:
            print(f'  {directory.name} Floor={int(enabled)} frame {f + 1}/{FRAMES}', flush=True)
    arrays = {k: np.stack(v) for k, v in arrays.items()}
    if export:
        exported_packed = {k: np.stack(v) for k, v in rr_arrays.items()}
        export.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(export / 'rr_inputs.npz', **exported_packed)
        np.savez_compressed(export / 'floor_readback.npz', **arrays)
        accounting = verify_source_accounting(arrays, exported_packed, frames, directory, enabled)
        (export / 'source_accounting.json').write_text(json.dumps(accounting, indent=2), encoding='utf-8')
        np.savez_compressed(export / 'scoring_fixture.npz', clean=np.stack([d['clean'] for d in frames]),
                            age=np.stack([d['age'] for d in frames]), visible=np.stack([d['visible'] for d in frames]),
                            support=np.stack([d['support'] for d in frames]), roi=frames[0]['roi'], quiet=frames[0]['quiet'],
                            exposure=np.array([d['exposure'] for d in frames]), scale=np.array([d['scale'] for d in frames]))
    return arrays


def metrics(array, frames, case):
    truth = np.stack([d['clean'][..., :3] / d['exposure'] for d in frames])
    observed = array[..., :3] / np.array([d['exposure'] for d in frames])[:, None, None, None]
    scale = np.array([d['scale'] for d in frames])[:, None, None]
    residual = (luminance(observed) - luminance(truth)) / scale
    rgb_error = (observed - truth) / scale[..., None]
    visible = np.stack([d['visible'] for d in frames])
    age = np.stack([d['age'] for d in frames])
    roi = frames[0]['roi']
    reveal = visible & roi & (age >= 0) & (age <= 3)
    near = visible & roi & (age >= 0) & (age <= 8)
    edge = reveal & (np.stack([d['support'] for d in frames]) <= 9)
    pair = near[1:] & visible[:-1] & roi
    delta = np.diff(residual, axis=0)[pair]
    rgb_delta = np.diff(rgb_error, axis=0)[pair]
    count = near.sum(axis=0)
    mean = np.sum(np.where(near, residual, 0), axis=0) / np.maximum(count, 1)
    variance = np.sum(np.where(near, (residual - mean) ** 2, 0), axis=0) / np.maximum(count, 1)
    timed = count >= 4
    quiet = np.broadcast_to(frames[0]['quiet'], residual.shape)
    # Contrast after averaging only valid observations of a world-space pixel.
    count_all = visible.sum(axis=0)
    m = np.sum(np.where(visible[..., None], observed / scale[..., None], 0), axis=0) / count_all[..., None].clip(1)
    q = np.sum(np.where(visible[..., None], truth / scale[..., None], 0), axis=0) / count_all[..., None].clip(1)
    texture_mask = roi & (count_all >= 4)
    signal = q[texture_mask] - q[texture_mask].mean(axis=0)
    output = m[texture_mask] - m[texture_mask].mean(axis=0)
    gain = float(np.sum(signal * output) / np.maximum(np.sum(signal * signal), 1e-20))
    first = [float(np.sqrt(np.mean(rgb_error[visible & roi & (age == n)] ** 2))) for n in range(6)]
    first_gain = []
    for n in range(6):
        mask = visible & roi & (age == n)
        target = (truth / scale[..., None])[mask]
        got = (observed / scale[..., None])[mask]
        target = target - target.mean(axis=0)
        got = got - got.mean(axis=0)
        first_gain.append(float(np.sum(target * got) / max(np.sum(target * target), 1e-20)))
    value = dict(reveal_rmse=float(np.sqrt(np.mean(rgb_error[reveal] ** 2))),
                 reveal_p95=float(np.percentile(np.abs(residual[reveal]), 95)),
                 reveal_bias=float(np.mean(residual[reveal])),
                 reveal_rgb_bias=np.mean(rgb_error[reveal], axis=0).tolist(),
                 reveal_rgb_p99=float(np.percentile(np.abs(rgb_error[reveal]), 99)),
                 targeted_edge_rmse=float(np.sqrt(np.mean(rgb_error[edge] ** 2))),
                 targeted_edge_samples=int(edge.sum()),
                 temporal_std=float(np.sqrt(np.mean(variance[timed]))),
                 residual_change_p95=float(np.percentile(np.abs(delta), 95)),
                 residual_change_rms=float(np.sqrt(np.mean(delta ** 2))),
                 rgb_residual_change_rms=float(np.sqrt(np.mean(rgb_delta ** 2))),
                 quiet_rmse=float(np.sqrt(np.mean(rgb_error[quiet] ** 2))),
                 quiet_temporal_std=float(np.std(residual[:, frames[0]['quiet']], axis=0).mean()),
                 texture_gain=gain, reveal_age_rmse=first, reveal_age_texture_gain=first_gain,
                 texture_samples=int(texture_mask.sum()), reveal_samples=int(reveal.sum()))
    if case['control'] == 'step':
        mask = frames[0]['quiet']
        observed_step = float(np.mean(luminance(observed[20])[mask] - luminance(observed[19])[mask]))
        clean_step = float(np.mean(luminance(truth[20])[mask] - luminance(truth[19])[mask]))
        value['lighting_step_relative_error'] = abs(observed_step - clean_step) / abs(clean_step)
    if case['control'] == 'exposure':
        mask = frames[0]['quiet']
        value['exposure_relative_error'] = max(abs(float(np.mean(residual[f, mask] - residual[f - 1, mask]))) for f in (12, 22))
    if not all(np.isfinite(v) for v in value.values() if np.isscalar(v)):
        raise RuntimeError('Nonfinite or empty disocclusion metric')
    return value


def texture_gain_not_regressed(candidate, baseline):
    """Bound attenuation and excess contrast separately against known truth."""
    return bool(np.isfinite(candidate) and np.isfinite(baseline) and
                min(baseline, 1.) - .01 <= candidate <= max(baseline, 1.) + .01)


def texture_gain_regression_cpu_checks():
    """Protocol properties independent of production outputs or fixture truth."""
    checks = 0
    def expect(name, passed):
        nonlocal checks
        checks += 1
        if not bool(passed):
            raise AssertionError('Texture gain regression contract: ' + name)
    expect('exact truth allowed against excess baseline', texture_gain_not_regressed(1., 1.02))
    expect('legacy demanded excess contrast', not (1. >= 1.02 - .01))
    expect('excess cannot finance attenuation', not texture_gain_not_regressed(.98, 1.12))
    expect('attenuation cannot finance excess', not texture_gain_not_regressed(1.02, .88))
    for baseline in (.88, .90, .98, 1.):
        lower = baseline - .01
        expect('old lower bound retained', texture_gain_not_regressed(lower, baseline))
        expect('old lower bound still rejects outside',
               not texture_gain_not_regressed(float(np.nextafter(lower, -np.inf)), baseline))
    expect('new excess guard rejects legacy pass', not texture_gain_not_regressed(1.015, .98))
    expect('legacy lower accepted excess', 1.015 >= .98 - .01)
    for baseline in (.90, 1., 1.02):
        lower, upper = min(baseline, 1.) - .01, max(baseline, 1.) + .01
        expect('stored lower boundary passes', texture_gain_not_regressed(lower, baseline))
        expect('stored upper boundary passes', texture_gain_not_regressed(upper, baseline))
        expect('nextafter below lower rejects',
               not texture_gain_not_regressed(float(np.nextafter(lower, -np.inf)), baseline))
        expect('nextafter above upper rejects',
               not texture_gain_not_regressed(float(np.nextafter(upper, np.inf)), baseline))
    for bad in (np.nan, np.inf, -np.inf):
        expect('nonfinite candidate rejects', not texture_gain_not_regressed(bad, 1.))
        expect('nonfinite baseline rejects', not texture_gain_not_regressed(1., bad))
        expect('two nonfinite gains reject', not texture_gain_not_regressed(bad, bad))
    return dict(passed=True, checks=checks, gpu_dispatches=0,
                contract_version=GAIN_REGRESSION_CONTRACT['version'])


def gain_regression_legacy_diagnostics(rows, baseline_rows=None):
    """Retain measured gains and old outcomes without using them for acceptance."""
    old = {r['case']['name']: r for r in baseline_rows or []}
    records = []
    for row in rows:
        name = row['case']['name']
        candidate = row['floor_on']['final']
        base = old.get(name)
        baseline = base['floor_on']['final'] if base else None
        gains = [('overall', candidate['texture_gain'], baseline['texture_gain'] if baseline else None)]
        gains += [(f'age{age}', candidate['reveal_age_texture_gain'][age],
                   baseline['reveal_age_texture_gain'][age] if baseline else None) for age in range(2)]
        record = dict(case=name, comparison_evaluated=base is not None,
            measured_gains=[dict(scope=scope, candidate=value, baseline=previous,
                legacy_one_sided_passed=bool(value >= previous - .01) if previous is not None else None)
                for scope, value, previous in gains])
        if baseline:
            record['legacy_no_texture_regression_passed'] = bool(candidate['texture_gain'] >= baseline['texture_gain'] - .01)
            record['legacy_no_chromatic_or_immediate_reveal_regression_passed'] = bool(
                candidate['rgb_residual_change_rms'] <= baseline['rgb_residual_change_rms'] * 1.02 + .001 and
                all(a <= z * 1.02 + .001 for a, z in zip(candidate['reveal_age_rmse'][:2], baseline['reveal_age_rmse'][:2])) and
                all(a >= z - .01 for a, z in zip(candidate['reveal_age_texture_gain'][:2], baseline['reveal_age_texture_gain'][:2])))
        records.append(record)
    return dict(version='fsrd_texture_gain_regression_v1_one_sided', quality_scored=False,
                affects_acceptance=False, allowance=0.01, records=records)


def evaluate(rows, baseline_rows=None, *, target_centered_gain_regression=False):
    checks = []
    def check(name, passed, **values):
        checks.append(dict(name=name, passed=bool(passed), **values))
    old = {r['case']['name']: r for r in baseline_rows or []}
    for row in rows:
        name = row['case']['name']
        m = row['floor_on']['final']
        base = old.get(name)
        check(name + ' textured reveal has targeted support', m['targeted_edge_samples'] >= 100 and m['texture_samples'] >= 500)
        check(name + ' ordinary Floor route remains active', row['ordinary_fraction'] >= GATES['ordinary_fraction_min'] and row['skip_fraction'] >= GATES['skip_fraction_min'], ordinary_fraction=row['ordinary_fraction'], skip_fraction=row['skip_fraction'])
        for key, bound in [('reveal_rmse', GATES['reveal_rmse']), ('reveal_p95', GATES['reveal_p95']),
                           ('temporal_std', GATES['temporal_std']), ('residual_change_p95', GATES['residual_change_p95'])]:
            check(name + ' absolute ' + key, m[key] <= bound, measured=m[key], bound=bound)
        if name == 'clean_texture':
            check(name + ' clean illumination stable', m['temporal_std'] <= GATES['clean_temporal_std'] and m['residual_change_p95'] <= GATES['clean_change_p95'])
        check(name + ' reveal bias', abs(m['reveal_bias']) <= GATES['bias'], measured=m['reveal_bias'])
        check(name + ' chromatic transient bounds', max(abs(v) for v in m['reveal_rgb_bias']) <= GATES['reveal_rgb_bias'] and m['reveal_rgb_p99'] <= GATES['reveal_rgb_p99'] and m['rgb_residual_change_rms'] <= GATES['rgb_change_rms'])
        check(name + ' texture retained', GATES['texture_gain_min'] <= m['texture_gain'] <= GATES['texture_gain_max'], measured=m['texture_gain'])
        check(name + ' first-frame texture and error retained', max(m['reveal_age_rmse'][:2]) <= GATES['first_reveal_rmse'] and min(m['reveal_age_texture_gain'][:2]) >= GATES['texture_gain_min'] and max(m['reveal_age_texture_gain'][:2]) <= GATES['texture_gain_max'], age_rmse=m['reveal_age_rmse'][:2], age_texture=m['reveal_age_texture_gain'][:2])
        check(name + ' boundary keeps ordinary Floor', row['targeted_ordinary_fraction'] >= GATES['ordinary_fraction_min'] and row['ordinary_min_frame'] >= GATES['ordinary_fraction_min'] and row['targeted_skip_fraction'] >= GATES['skip_fraction_min'])
        if row['case']['noise'] != 'none':
            check(name + ' noise suppressed', m['quiet_rmse'] <= row['floor_on']['input']['quiet_rmse'] * GATES['noise_input_ratio'])
        if row['case']['control'] == 'step':
            check(name + ' no extra frame lighting-step lag', m['lighting_step_relative_error'] <= GATES['lighting_step_relative_error'], measured=m['lighting_step_relative_error'])
        if row['case']['control'] == 'exposure':
            check(name + ' exposure invariant', m['exposure_relative_error'] <= GATES['exposure_relative_error'], measured=m['exposure_relative_error'])
        if base:
            b = base['floor_on']['final']
            check(name + ' no texture regression', texture_gain_not_regressed(m['texture_gain'], b['texture_gain']) if target_centered_gain_regression else m['texture_gain'] >= b['texture_gain'] - .01)
            check(name + ' no noise regression', m['quiet_rmse'] <= b['quiet_rmse'] * GATES['noise_regression'] + .001)
            check(name + ' no chromatic or immediate-reveal regression', m['rgb_residual_change_rms'] <= b['rgb_residual_change_rms'] * 1.02 + .001 and all(a <= z * 1.02 + .001 for a, z in zip(m['reveal_age_rmse'][:2], b['reveal_age_rmse'][:2])) and all(texture_gain_not_regressed(a, z) if target_centered_gain_regression else a >= z - .01 for a, z in zip(m['reveal_age_texture_gain'][:2], b['reveal_age_texture_gain'][:2])))
            targeted = name == 'clean_texture' or (row['case']['noise'] != 'none' and
                (b['temporal_std'] > GATES['temporal_std'] or b['residual_change_p95'] > GATES['residual_change_p95']))
            if targeted:
                check(name + ' targeted flicker reduced at least 30%', m['temporal_std'] <= b['temporal_std'] * (1 - GATES['targeted_reduction']) and m['residual_change_p95'] <= b['residual_change_p95'] * (1 - GATES['targeted_reduction']), baseline_std=b['temporal_std'], candidate_std=m['temporal_std'], baseline_change=b['residual_change_p95'], candidate_change=m['residual_change_p95'])
                check(name + ' Floor bypass itself improves', row['floor_on']['skip']['residual_change_p95'] <= base['floor_on']['skip']['residual_change_p95'] * (1 - GATES['targeted_reduction']))
            else:
                check(name + ' guard flicker does not regress', m['temporal_std'] <= b['temporal_std'] + GATES['guard_temporal_allowance'] and m['residual_change_p95'] <= b['residual_change_p95'] + GATES['guard_change_allowance'])
        elif baseline_rows is not None:
            raise ValueError('Missing mandatory frozen case: ' + name)
    return checks


def fixture_identity(frames, case):
    digest = hashlib.sha256(json.dumps(case, sort_keys=True).encode())
    for frame in frames:
        for key in sorted(frame):
            array = np.ascontiguousarray(frame[key])
            digest.update(key.encode())
            digest.update(str(array.dtype).encode())
            digest.update(str(array.shape).encode())
            digest.update(array.tobytes())
    return digest.hexdigest()


def stage_trace(stages, frames):
    """Contributions and truth-relative RGB at reveal ages 0..10 and quiet control."""
    visible = np.stack([d['visible'] for d in frames])
    age = np.stack([d['age'] for d in frames])
    roi, quiet = frames[0]['roi'], frames[0]['quiet']
    normalization = np.array([d['exposure'] * d['scale'] for d in frames])[:, None, None, None]
    truth = np.stack([d['clean'][..., :3] for d in frames]) / normalization
    normalized = {key: value[..., :3] / normalization for key, value in stages.items()}
    rows = []
    for n in range(11):
        mask = visible & roi & (age == n)
        active_frames = mask.sum(axis=(1, 2)) > 0
        control = np.broadcast_to(quiet, age.shape) & active_frames[:, None, None]
        item = dict(age=n, samples=int(mask.sum()), clean_rgb=truth[mask].mean(axis=0).tolist(),
                    stable_clean_rgb=truth[control].mean(axis=0).tolist(), revealed={}, stable={})
        for key, value in normalized.items():
            item['revealed'][key] = dict(rgb=value[mask].mean(axis=0).tolist(),
                                         minus_clean_rgb=(value - truth)[mask].mean(axis=0).tolist())
            item['stable'][key] = dict(rgb=value[control].mean(axis=0).tolist(),
                                       minus_clean_rgb=(value - truth)[control].mean(axis=0).tolist())
        rows.append(item)
    return rows


def score_actual_rr(args):
    """Compose native DD/IS readbacks without substituting synthetic RR or truth.

    Native input/readback hashes are checked against the saved actual packing.
    Early exports omitted converted reference alpha; those are reconstituted by
    the original conversion shader, requiring exact equality of every recorded
    production signal/guide/Skip before its reference may be used.
    """
    if not args.measure or args.exports is None:
        raise ValueError('Actual FINAL scoring needs --measure and --exports; partial native evidence cannot accept the full suite')
    export_root = args.exports.resolve()
    replay_root = args.score_actual_rr.resolve()
    model = json.loads((export_root / 'results.json').read_text())
    dependencies = dependency_identity()
    if 'dependency_identity' in model and model['dependency_identity'] != dependencies:
        raise ValueError('Native composition and exported pipeline require immutable matching dependencies')
    model_rows = {r['case']['name']: r for r in model['records']}
    directory = (args.candidate or args.baseline).resolve()
    identity = c.shader_identity(directory)
    for shader in ('FSRDInputConv', 'FSRDOutputComp'):
        if identity[shader + '_Shader.cso'] != model['shader_identity'][shader + '_Shader.cso']:
            raise ValueError('Native exports need their original conversion/composition bytecode: ' + shader)
    names = args.case or ['bright_independent', 'bright_correlated']
    if len(names) != len(set(names)) or any(name not in model_rows for name in names):
        raise ValueError('Native evidence lacks a requested case')
    old = None
    if args.actual_baseline_report:
        old = json.loads(args.actual_baseline_report.read_text())
        if old['schema'] != SCHEMA or old['gates'] != GATES or old['rr_kind'] != 'actual_signed_amd_rr_final' or old.get('gain_regression_contract') != GAIN_REGRESSION_CONTRACT:
            raise ValueError('Wrong actual-RR comparison report')
        if old.get('test_source_sha256') != hashlib.sha256(Path(__file__).read_bytes()).hexdigest() or old.get('dependency_identity') != dependencies:
            raise ValueError('Actual baseline and candidate require identical harness and dependency provenance')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    t.OUT = out / 'shader_jobs'
    t.OUT.mkdir(exist_ok=True)
    t.runner = out / 'fsrd_gpu_runner.exe'
    t.build_runner()
    runner_identity = hashlib.sha256(t.runner.read_bytes()).hexdigest()
    harness = Path(__file__).read_bytes()
    (out / 'harness_source.py').write_bytes(harness)
    rows, native, camera_protocol = [], [], None
    for name in names:
        print('ACTUAL FINAL ' + name, flush=True)
        row = dict(model_rows[name])
        case = row['case']
        frames = fixture(case)
        if row['input_sha256'] != fixture_identity(frames, case):
            raise ValueError('Native exports and scoring fixture differ')
        finals = {}
        for variant, enabled in [('floor_on', True), ('floor_off', False)]:
            location = export_root / name / variant
            replay = replay_root / case['noise'] / variant
            with np.load(location / 'rr_inputs.npz') as archive:
                packed = {k: archive[k].copy() for k in archive.files}
            with np.load(location / 'floor_readback.npz') as archive:
                saved = {k: archive[k].copy() for k in archive.files}
            row.setdefault('source_accounting', {})[variant] = verify_source_accounting(saved, packed, frames, directory, enabled)
            with np.load(replay / 'readback.npz') as archive:
                readback = {k: archive[k].copy() for k in archive.files}
            meta = json.loads((replay / 'metadata.json').read_text())
            if meta['kind'] != 'actual_signed_amd_rr_gpu_readback' or meta['status'] != 'passed' or meta['passthrough'] or meta['frames'] != FRAMES or meta['dimensions'] != [W, H] or meta['signature']['status'] != 'Valid' or meta['context_lifetime'] != 'sequence' or meta['signal_flags'] != [2, 32] or not meta['adapter']['debug_layer']:
                raise ValueError('Native readback is not a valid persistent AMD RR sequence')
            if meta['counters'] != dict(dispatches=FRAMES, validation_errors=0, validation_warnings=0, sdk_errors=0, sdk_warnings=0):
                raise ValueError('Native sequence diagnostics are not clean')
            projection = np.asarray(meta['projection'], np.float32)
            matched = np.array([[.5, 0, 0, 0], [0, .5, 0, 0],
                                [0, 0, 1000 / 999.9, 1], [0, 0, -100 / 999.9, 0]], np.float32)
            protocol = ('identity_api_only_prior_diagnostic' if np.array_equal(projection, np.eye(4))
                        else 'matched_seed_rays_perspective' if np.array_equal(projection, matched) else None)
            if not np.array_equal(meta['view'], np.eye(4)) or np.any(meta['jitters']) or protocol is None:
                raise ValueError('Native camera does not match an explicitly supported fixture protocol')
            if camera_protocol is not None and camera_protocol != protocol:
                raise ValueError('Native cases use inconsistent camera protocols')
            camera_protocol = protocol
            from fsrd_floor_rr_replay import pack_normals
            encoded = dict(depth=packed['depth'].astype('<f4'), motion=packed['motion'].astype('<f2'),
                           normal=pack_normals(packed['normals']),
                           diffuse_albedo=np.rint(packed['diffuse_albedo'].astype(np.float64) * 255).astype('u1'),
                           specular_albedo=np.rint(packed['specular_albedo'].astype(np.float64) * 255).astype('u1'),
                           diffuse=packed['diffuse'].astype('<f2'), specular=packed['specular'].astype('<f2'))
            for entry in meta['inputs']:
                if hashlib.sha256(encoded[entry['name']].tobytes()).hexdigest() != entry['sha256']:
                    raise ValueError('Actual RR did not consume the exported production input: ' + entry['name'])
            for key in ('diffuse', 'specular'):
                if readback[key].shape != (FRAMES, H, W, 4) or not np.isfinite(readback[key]).all() or hashlib.sha256(readback[key].astype('<f2').tobytes()).hexdigest() != meta['readback'][key]['sha256']:
                    raise ValueError('Native GPU readback hash or shape differs: ' + key)
            native.append(dict(case=name, variant=variant, metadata=str(replay / 'metadata.json'),
                               dll_sha256=meta['dll_sha256'], readback=meta['readback'], counters=meta['counters']))
            history, outputs = None, []
            for f, data in enumerate(frames):
                if 'packed_reference' in saved:
                    reference = saved['packed_reference'][f]
                else:
                    reconstructed = c.convert(data['raw'], data['albedo'], t.rgba(W, H, (.08, .08, .08)),
                        directory=directory, depth=packed['depth'][f], normals=data['normals'],
                        roughness=np.full((H, W), .45, np.float32),
                        floor=saved['floor'][f] if enabled else None, reference=saved['reference'][f],
                        motion=data['motion'], overrides=dict(Flags=(1 << 1) | (1 << 4) | (1 << 5) | (1 << 15) | ((1 << 7) if enabled else 0)), resources={8: data['bias']})
                    for i, key in [(0, 'specular'), (1, 'diffuse'), (2, 'motion'), (3, 'normals'), (4, 'specular_albedo'), (5, 'diffuse_albedo')]:
                        if not np.array_equal(reconstructed[i], packed[key][f]):
                            raise ValueError('Original packed input cannot be reconstructed exactly: ' + key)
                    if not np.array_equal(reconstructed[6], saved['skip'][f]):
                        raise ValueError('Original Skip cannot be reconstructed exactly')
                    reference = reconstructed[7]
                zero = t.rgba(W, H, (0, 0, 0))
                cb = dict(DstTexSize=[W, H, 1 / W, 1 / H], Flags=1 << 3,
                          DetailPreservation=1 if enabled else 0, RecoveryMask=1,
                          FloorHandoverAnchorClamp=4, FloorHandoverCorrelationMix=1,
                          LumaRecovery=1, ChromaRecovery=1, SpecularAlbedoDemodulation=1,
                          DiffuseAlbedoModulation=1, DemodDivisorFloor=.008,
                          SpatialTemporalMask=0, WriteHistory=1, HistoryValid=int(history is not None))
                inputs = [readback['specular'][f], packed['specular_albedo'][f],
                          readback['diffuse'][f], packed['diffuse_albedo'][f], saved['skip'][f],
                          packed['normals'][f], reference, packed['depth'][f], packed['motion'][f],
                          t.rgba(W, H, (-1, -1, -1), -1) if history is None else history[1],
                          np.zeros((H, W, 4), np.uint32) if history is None else history[2],
                          zero, zero, np.zeros((H, W, 2), np.float32), zero,
                          packed['specular'][f], packed['diffuse'][f]]
                history = t.dispatch('FSRDOutputComp', cb, inputs, [10, 10, 3], (W, H), directory=directory)
                outputs.append(history[0])
            finals[variant] = np.stack(outputs)
            rr_signal = readback['diffuse'][..., :3] * packed['diffuse_albedo'][..., :3] + readback['specular'][..., :3] * packed['specular_albedo'][..., :3]
            packed_signal = packed['diffuse'][..., :3] * packed['diffuse_albedo'][..., :3] + packed['specular'][..., :3] * packed['specular_albedo'][..., :3]
            marked, current_source = _validated_current_source(saved, frames, enabled)
            stages = dict(raw=saved['input'], seed_reference=saved['reference'], floor_base=saved['floor'],
                          skip=saved['skip'], packed_remodulated_signal=packed_signal,
                          packing_identity=_consume_current_source(packed_signal, saved['skip'], marked),
                          actual_rr_remodulated_signal=rr_signal,
                          actual_precomposition=_consume_current_source(rr_signal, saved['skip'], marked),
                          actual_final=finals[variant])
            if 'residual_source' in saved:
                stages['explicit_residual_source'] = saved['residual_source']
                stages['explicit_current_source'] = np.where(marked[..., None], current_source,
                                                             saved['residual_source'][..., :3])
            visible_roi = np.stack([d['visible'] & d['roi'] for d in frames])
            reveal_roi = np.stack([d['visible'] & d['roi'] & (d['age'] >= 0) & (d['age'] <= 3) for d in frames])
            normalization = np.array([d['scale'] * d['exposure'] for d in frames])[:, None, None, None]
            activity = {}
            for label, mask in [('visible_roi', visible_roi), ('reveal_age0_3', reveal_roi)]:
                normalized_signal = (packed_signal / normalization)[mask]
                activity[label] = dict(samples=int(mask.sum()),
                    nonzero_signal_pixel_fraction=float(np.mean(np.any(packed_signal[mask] != 0, axis=-1))),
                    remodulated_signal_rgb_rms=np.sqrt(np.mean(normalized_signal ** 2, axis=0)).tolist(),
                    remodulated_signal_abs_max=float(np.max(np.abs(normalized_signal))))
                activity[label]['current_source_marker'] = _current_source_activity(marked, rr_signal, mask, normalization)
                if 'source_weight' in saved:
                    weights = saved['source_weight'][mask]
                    activity[label]['source_weight_mean'] = float(np.mean(weights))
                    activity[label]['fully_filtered_fraction'] = float(np.mean(np.all(weights >= 1., axis=-1) if weights.ndim == 2 else weights >= 1.))
                    if weights.ndim == 2:
                        activity[label]['source_weight_rgb_mean'] = np.mean(weights, axis=0).tolist()
                if 'plane_confidence' in saved:
                    activity[label]['plane_confidence_mean'] = float(np.mean(saved['plane_confidence'][mask]))
                    activity[label]['model_kind_fraction'] = {str(tag): float(np.mean(saved['model_kind'][mask] == tag)) for tag in range(4)}
            row.setdefault('packing_signal_activity', {})[variant] = activity
            row.setdefault('actual_stage_quality', {})[variant] = {
                key: metrics(value, frames, case) for key, value in stages.items()
                if key not in ('packed_remodulated_signal', 'actual_rr_remodulated_signal')}
            row.setdefault('actual_reveal_rgb_trace', {})[variant] = stage_trace(stages, frames)
            np.savez_compressed(out / (name + '_' + variant + '_actual_final.npz'), final=finals[variant])
            components = out / (name + '_' + variant + '_unconsumed_history_copy_components.npz')
            np.savez_compressed(components, marked_current_source=marked,
                packed_warm_rr_remodulated_signal=packed_signal, actual_warm_rr_remodulated_signal=rr_signal,
                unconsumed_history_copy_packing_sum=packed_signal + saved['skip'][..., :3],
                unconsumed_history_copy_actual_sum=rr_signal + saved['skip'][..., :3])
            row.setdefault('unconsumed_history_copy_diagnostics', {})[variant] = dict(
                path=str(components), sha256=hashlib.sha256(components.read_bytes()).hexdigest(),
                quality_scored=False,
                consumption='On marked lanes these component sums are unconsumed history copies, not physical closure or FINAL; unmarked lanes retain the original sum.')
        row['floor_on'] = dict(row['floor_on'], final=metrics(finals['floor_on'], frames, case))
        row['floor_off'] = dict(final=metrics(finals['floor_off'], frames, case))
        row['floor_induced_temporal_std_excess'] = row['floor_on']['final']['temporal_std'] - row['floor_off']['final']['temporal_std']
        rows.append(row)
        print(json.dumps(dict(case=name, final=row['floor_on']['final'], floor_off=row['floor_off']['final'])), flush=True)
    if c.shader_identity(directory) != identity or any(str(d.get('debug_layer')) != '1' or str(d.get('validation_errors')) != '0' or str(d.get('validation_warnings')) != '0' or d['shader_sha256'] != identity[d['shader'] + '_Shader.cso'] for d in t.timings):
        raise ValueError('Composition diagnostics or immutable shader identity failed')
    if dependency_identity() != dependencies or hashlib.sha256(t.runner.read_bytes()).hexdigest() != runner_identity or Path(__file__).read_bytes() != harness:
        raise ValueError('Harness, dependency, or executable changed during native evidence composition')
    if old and {r['case']['name']: r['input_sha256'] for r in old['records']} != {r['case']['name']: r['input_sha256'] for r in rows}:
        raise ValueError('Actual candidate and baseline use different input fixtures')
    if old and old.get('camera_protocol', 'identity_api_only_prior_diagnostic') != camera_protocol:
        raise ValueError('Actual candidate and baseline use different native cameras')
    report = dict(schema=SCHEMA, mode='actual_final_measurement', acceptance_evaluated=False, accepted=False,
                  rr_kind='actual_signed_amd_rr_final', gates=GATES, composition_identity=identity,
                  gain_regression_contract=GAIN_REGRESSION_CONTRACT,
                  gain_regression_cpu_checks=texture_gain_regression_cpu_checks(),
                  gain_regression_legacy_diagnostics=gain_regression_legacy_diagnostics(rows, old['records'] if old else None),
                  test_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  dependency_identity=dependencies, gpu_runner_sha256=runner_identity,
                  model_kind_contract={'0': 'disabled', '1': 'albedo slope', '2': 'zero slope noise payload', '3': 'spatial plane confidence payload'},
                  camera_protocol=camera_protocol,
                  exported_shader_identity=model['shader_identity'], records=rows, native_sequences=native,
                  checks=evaluate(rows, old['records'] if old else None, target_centered_gain_regression=True), dispatches=t.timings,
                  history_contract='SpatialTemporalMask0; independent composition_temporal suite still required')
    (out / 'results.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    print('ACTUAL FINAL MEASURE ONLY: ' + str(out / 'results.json'), flush=True)


def run(args):
    gain_contract_cpu_checks = texture_gain_regression_cpu_checks()
    if args.score_actual_rr:
        return score_actual_rr(args)
    baseline = args.baseline.resolve()
    dependencies = dependency_identity()
    baseline_identity = authenticate_baseline(baseline)
    directory = (args.candidate or baseline).resolve()
    if not args.measure and (args.candidate is None or directory == baseline or args.baseline_report is None):
        raise ValueError('Acceptance needs --candidate distinct from frozen baseline and --baseline-report; use --measure for evidence only')
    selected = cases()
    if args.case:
        if not args.measure:
            raise ValueError('Acceptance cannot omit cases')
        selected = [r for r in selected if r['name'] in args.case]
        if len(selected) != len(set(args.case)):
            raise ValueError('Unknown or duplicated --case')
    old = None
    if args.baseline_report:
        old = json.loads(args.baseline_report.read_text())
        source_hash = hashlib.sha256((inspect.getsource(texture) + inspect.getsource(fixture)).encode()).hexdigest()
        if old['schema'] != SCHEMA or old['gates'] != GATES or old.get('gain_regression_contract') != GAIN_REGRESSION_CONTRACT or old['baseline_identity'] != baseline_identity or old['shader_identity'] != c.shader_identity(baseline) or len(old['records']) != len(cases()) or old['fixture_source_sha256'] != source_hash or old['dimensions'] != [W, H] or old['frames'] != FRAMES:
            raise ValueError('Baseline evidence is incomplete, stale, or from different gates/shaders')
        if 'test_source_sha256' in old and old['test_source_sha256'] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
            raise ValueError('Fresh baseline and candidate require identical harness provenance')
        if 'dependency_identity' in old and old['dependency_identity'] != dependencies:
            raise ValueError('Fresh baseline and candidate require identical dependency provenance')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    t.OUT = out / 'shader_jobs'
    t.OUT.mkdir(exist_ok=True)
    t.runner = out / 'fsrd_gpu_runner.exe'
    t.build_runner()
    runner_identity = hashlib.sha256(t.runner.read_bytes()).hexdigest()
    harness = Path(__file__).read_bytes()
    (out / 'harness_source.py').write_bytes(harness)
    rows = []
    report = dict(schema=SCHEMA, mode='measure' if args.measure else 'acceptance',
                  acceptance_evaluated=not args.measure, accepted=False, baseline_commit=BASE,
                  baseline_identity=baseline_identity, shader_identity=c.shader_identity(directory),
                  dimensions=[W, H], frames=FRAMES, gates=GATES,
                  gain_regression_contract=GAIN_REGRESSION_CONTRACT,
                  gain_regression_cpu_checks=gain_contract_cpu_checks,
                  gain_regression_legacy_diagnostics=gain_regression_legacy_diagnostics(rows),
                  test_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  dependency_identity=dependencies, gpu_runner_sha256=runner_identity,
                  model_kind_contract={'0': 'disabled', '1': 'albedo slope', '2': 'zero slope noise payload', '3': 'spatial plane confidence payload'},
                  rr_kind='synthetic_surface_guided_spatial_model_not_AMD_RR',
                  fixture_source_sha256=hashlib.sha256((inspect.getsource(texture) + inspect.getsource(fixture)).encode()).hexdigest(),
                  stale_history_rejection_proved=False,
                  history_contract='SpatialTemporalMask=0 isolates spatial Floor; run test_fsrd_composition_temporal.py separately for positive reuse and stale rejection',
                  truth_enters_GPU=False, records=rows)
    for case in selected:
        print('CASE ' + case['name'], flush=True)
        frames = fixture(case)
        on = gpu_sequence(frames, directory, True, out / case['name'] / 'floor_on' if args.export_rr else None)
        off = gpu_sequence(frames, directory, False, out / case['name'] / 'floor_off' if args.export_rr else None)
        region = np.stack([d['visible'] & d['roi'] & (d['age'] >= 0) & (d['age'] <= 8) for d in frames])
        targeted = np.stack([d['visible'] & d['roi'] & (d['age'] == 0) & (d['support'] <= 9) for d in frames])
        skip_ratio = luminance(on['skip']) / np.maximum(luminance(np.stack([d['clean'] for d in frames])), 1e-20)
        row = dict(case=case, input_sha256=fixture_identity(frames, case),
                   floor_on={k: metrics(on[k], frames, case) for k in ('final', 'reference', 'floor', 'skip', 'input')},
                   floor_off=dict(final=metrics(off['final'], frames, case)),
                   ordinary_fraction=float(np.mean(on['material'][region] < .1)),
                   targeted_ordinary_fraction=float(np.mean(on['material'][targeted] < .1)),
                   ordinary_min_frame=min(float(np.mean(on['material'][f][mask] < .1)) for f, mask in enumerate(targeted) if np.any(mask)),
                   targeted_skip_fraction=float(np.mean(skip_ratio[targeted])),
                   skip_fraction=float(np.mean(skip_ratio[region])))
        # Expose Floor-induced oscillation relative to off, without claiming that
        # an independent stochastic variance difference proves pixelwise cause.
        row['floor_induced_temporal_std_excess'] = row['floor_on']['final']['temporal_std'] - row['floor_off']['final']['temporal_std']
        rows.append(row)
        report['checks'] = evaluate(rows, old['records'] if old else None, target_centered_gain_regression=True)
        report['gain_regression_legacy_diagnostics'] = gain_regression_legacy_diagnostics(rows, old['records'] if old else None)
        (out / 'results.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
        print(json.dumps(dict(case=case['name'], final=row['floor_on']['final'], floor_off=row['floor_off']['final'], skip_change=row['floor_on']['skip']['residual_change_p95'], ordinary_fraction=row['ordinary_fraction'], skip_fraction=row['skip_fraction'])), flush=True)
    if old:
        old_hashes = {r['case']['name']: r['input_sha256'] for r in old['records']}
        if any(old_hashes[r['case']['name']] != r['input_sha256'] for r in rows):
            raise ValueError('Candidate inputs differ from frozen baseline')
    for dispatch in t.timings:
        if str(dispatch.get('debug_layer')) != '1' or str(dispatch.get('validation_errors')) != '0' or str(dispatch.get('validation_warnings')) != '0':
            raise RuntimeError('GPU validation was not clean')
        if dispatch['shader_sha256'] != report['shader_identity'][dispatch['shader'] + '_Shader.cso']:
            raise RuntimeError('Shader changed during the evidence run')
    if c.shader_identity(directory) != report['shader_identity']:
        raise RuntimeError('Shader source or bytecode changed during the evidence run')
    if dependency_identity() != dependencies or hashlib.sha256(t.runner.read_bytes()).hexdigest() != runner_identity or Path(__file__).read_bytes() != harness:
        raise RuntimeError('Harness, dependencies, or executable changed during the evidence run')
    report['dispatches'] = t.timings
    report['accepted'] = not args.measure and all(q['passed'] for q in report['checks'])
    (out / 'results.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    print(('MEASURE ONLY; acceptance not evaluated' if args.measure else 'ACCEPTED' if report['accepted'] else 'REJECTED') + ': ' + str(out / 'results.json'), flush=True)
    if not args.measure and not report['accepted']:
        raise AssertionError('Floor disocclusion quality acceptance failed; see results.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=DEFAULT_BASELINE)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--baseline-report', type=Path)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--measure', action='store_true')
    parser.add_argument('--export-rr', action='store_true', help='Export unmodified production packing readbacks for the actual AMD replay helper')
    parser.add_argument('--case', action='append')
    parser.add_argument('--score-actual-rr', type=Path, help='Compose existing actual native readbacks under this replay root')
    parser.add_argument('--exports', type=Path, help='Original production packing exports for actual FINAL scoring')
    parser.add_argument('--actual-baseline-report', type=Path, help='Matching actual FINAL baseline report for fixed-gate comparisons')
    run(parser.parse_args())
