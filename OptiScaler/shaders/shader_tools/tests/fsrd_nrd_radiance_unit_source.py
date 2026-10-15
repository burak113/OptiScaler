"""Seal native-dim V3 units from V1 without changing the old oracle or files.

Noisy RGB is divided by64 and rounded to half exactly once. Reference/ghost
RGB uses exact float32 power-of-two unit conversion. Every other payload and
camera byte is linked read-only. These units are a counterfactual, not a game
capture or an attestation of the NN's intended absolute domain.
"""
from copy import deepcopy
from pathlib import Path
import json
import numpy as np

SCHEMA = 'fsrd-world-surface-radiance-unit-v3'
UNIT_SCALE = 1 / 64
V3_SCALES = (1., 4., 16., 64., 256.)


def convert_signal(source):
    if source.dtype != np.dtype('<f2') or source.ndim != 3 or source.shape[-1] != 4:
        raise ValueError('V3 requires original half RGBA')
    rgb = source[..., :3].astype(np.float32)
    if not np.isfinite(rgb).all() or not (rgb >= 0).all():
        raise ValueError('V3 source RGB must be finite/nonnegative')
    exact = rgb * np.float32(UNIT_SCALE)
    rounded = exact.astype('<f2')
    result = source.copy()
    result[..., :3] = rounded
    if not np.array_equal(result.view(np.uint16)[..., 3], source.view(np.uint16)[..., 3]):
        raise AssertionError('V3 unit conversion changed alpha')
    error = rounded.astype(np.float32) - exact
    roundtrip_error = rounded.astype(np.float32) * np.float32(64) - rgb
    stats = dict(rgb_components=int(rgb.size), first_quantization='IEEE nearest-even half once',
        changed_rgb_components=int(np.count_nonzero(error)),
        nonzero_to_zero_components=int(((exact > 0) & (rounded == 0)).sum()),
        exact_unit_min_positive=float(exact[exact > 0].min()) if np.any(exact > 0) else None,
        rounded_min_positive=float(rounded[rounded > 0].min()) if np.any(rounded > 0) else None,
        max_absolute_unit_error=float(np.max(np.abs(error))),
        sum_squared_unit_error=float(np.sum(error.astype(np.float64)**2)),
        max_absolute_v1_unit_roundtrip_error=float(np.max(np.abs(roundtrip_error))),
        source_rgb_max=float(rgb.max()), alpha_words_unchanged=True)
    return result, stats


def seal_unit_source(replay, inputs, original, output, source_sha, require, write_immutable, file_sha):
    output.mkdir(parents=True, exist_ok=True)
    manifest = deepcopy(original)
    manifest['schema'] = SCHEMA
    manifest['source'] = 'counterfactual unit conversion of immutable analytic V1; not a new game or reference capture'
    manifest['radiance_unit_conversion'] = dict(source_manifest_sha256=source_sha,
        scale=UNIT_SCALE, inverse_scale=64,
        noisy_rgb='half input /64 then nearest-even half once; alpha words exact',
        reference_and_ghost_rgb='exact float32 input-half /64; no half quantization of truth',
        guides_camera_and_masks='original V1 bytes',
        consumer_scope='native unity-exposure Consumer64 cancels unit change apart from the disclosed first noisy-half quantization')
    statistics = []
    for before, frame in zip(original['frames'], manifest['frames']):
        origin, destination = inputs / before['directory'], output / frame['directory']
        destination.mkdir(exist_ok=True)
        for name, record in before['payloads'].items():
            target = destination / record['file']
            if name in ('spec', 'diff'):
                source = replay.load(origin, record)
                array, stats = convert_signal(source)
                write_immutable(target, array.tobytes())
                frame['payloads'][name].update(bytes=array.nbytes, dtype=array.dtype.str,
                    shape=list(array.shape), sha256=file_sha(target))
                statistics.append(dict(frame=frame['frame'], signal=name, **stats))
            elif name.startswith('reference_') or name.startswith('ghost_'):
                source = replay.load(origin, record)
                exact = source.astype('<f4') * np.float32(UNIT_SCALE)
                require(np.array_equal(exact.astype(np.float64) * 64, source.astype(np.float64)),
                        'reference/ghost unit conversion is exact without half quantization')
                write_immutable(target, exact.tobytes())
                frame['payloads'][name].update(bytes=exact.nbytes, dtype=exact.dtype.str,
                    shape=list(exact.shape), sha256=file_sha(target))
            else:
                replay.link(origin / record['file'], target)
    replay.link(inputs / original['native_replay']['file'], output / original['native_replay']['file'])
    manifest['first_noisy_half_quantization'] = statistics
    packed = (json.dumps(manifest, indent=2, allow_nan=False) + '\n').encode('utf-8')
    write_immutable(output / 'sequence.json', packed)
    return manifest


def validate_unit_source(replay, inputs, manifest, v1_inputs, original, source_sha, require, file_sha):
    require(manifest['schema'] == SCHEMA, 'explicit V3 schema; old V1 oracle is not relabeled')
    require(manifest['radiance_unit_conversion']['source_manifest_sha256'] == source_sha,
            'V3 is derived from the exact original V1 manifest')
    require(manifest['submitted_frames'] == len(manifest['frames']) == 64,
            'complete64-frame native-dim unit source')
    require(manifest['native_replay'] == original['native_replay'] and
            file_sha(inputs / original['native_replay']['file']) == original['native_replay']['sha256'],
            'every native camera-table byte remains original')
    for before, frame in zip(original['frames'], manifest['frames']):
        require({k: v for k, v in frame.items() if k != 'payloads'} ==
                {k: v for k, v in before.items() if k != 'payloads'}, 'same frame/camera/jitter/reset/object geometry')
        for name, record in frame['payloads'].items():
            array = replay.load(inputs / frame['directory'], record)
            original_record = before['payloads'][name]
            original_array = replay.load(v1_inputs / before['directory'], original_record)
            if name in ('spec', 'diff'):
                expected, _ = convert_signal(original_array)
                require(array.tobytes() == expected.tobytes(), 'V3 noisy RGB exact one-time conversion and identical alpha words')
            elif name.startswith('reference_') or name.startswith('ghost_'):
                require(array.dtype == np.dtype('<f4') and
                        np.array_equal(array.astype(np.float64) * 64, original_array.astype(np.float64)),
                        'V3 reference/ghost RGB stays exact in canonical V1 units')
            else:
                require(record == original_record and array.tobytes() == original_array.tobytes(),
                        'all non-radiance payload bytes and records remain original')
    return manifest
