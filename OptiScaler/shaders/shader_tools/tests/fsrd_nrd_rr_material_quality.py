"""Controlled material-guide ablation on the sealed64-frame15e world oracle.

Default execution prepares CPU inputs only. Existing v1 data is never edited.
All candidate RGB/hit/depth/MV/normal/camera bits are identical; only albedo RGB
changes. Material multiplication is analysis of RR output, never a noisy bypass.
This is prescribed synthetic transport plus an explicit analytic GGX reflectance
approximation, not a game capture or the title's late LUT/CB6 implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

os.environ.update(TEMP='F:/FSRD/tmp', TMP='F:/FSRD/tmp', OMP_NUM_THREADS='2',
                  OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
import numpy as np

SCHEMA = 'fsrd-world-material-guide-quality-v2'
SOURCE_SHA = '27545e6db81e5214b2c0622a57ae05efa9ca2ed8148666e86e9542c63fd9974d'
CANDIDATES = ('white', 'diffuse-only', 'specular-only', 'both')
IDENTICAL = ('spec', 'diff', 'depth', 'normals', 'motion')
HERE = Path(__file__).resolve().parent
CHECKS = 0

# Chosen before any signed material run. Inputs are linear color intentions;
# canonical stored RGB10 values are round(sqrt(linear)*1023), then decoded^2.
PALETTE = np.array([[.52, .06, .025], [.025, .12, .55], [.045, .52, .07],
                    [.55, .55, .55], [.64, .42, .055], [.025, .025, .025]], dtype=np.float64)
METALS = np.array([0., .35, .8, 1.], dtype=np.float64)


def require(value, message):
    global CHECKS
    CHECKS += 1
    if not value:
        raise AssertionError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    return sha(Path(path).read_bytes())


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def immutable(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == data, 'existing sealed CPU view is identical; never overwrite different evidence')
    else:
        path.write_bytes(data)


def put(folder, name, value):
    value = np.ascontiguousarray(value)
    data = value.tobytes()
    immutable(folder/name, data)
    return dict(file=name, bytes=len(data), sha256=sha(data), dtype=value.dtype.str, shape=list(value.shape))


def load(folder, record):
    name = Path(record['file'])
    require(name.name == str(name), 'sealed exact local payload basename')
    data = (folder/name).read_bytes()
    require(len(data) == record['bytes'] and sha(data) == record['sha256'], 'every original/derived payload length and SHA')
    return np.frombuffer(data, dtype=np.dtype(record['dtype'])).reshape(record['shape'])


def original(inputs):
    data = (inputs/'sequence.json').read_bytes()
    require(sha(data) == SOURCE_SHA, 'exact immutable v1 physical world/camera/noise/light sequence')
    value = json.loads(data)
    require(value['schema'] == 'fsrd-world-surface-motion-quality-v1' and
            value['width'] == value['height'] == 128 and value['submitted_frames'] == len(value['frames']) == 64,
            'complete fixed128x12864-frame oracle, never regenerate v1')
    metadata = value['native_replay']
    require(Path(metadata['file']).name == metadata['file'], 'sealed native metadata basename')
    data = (inputs/metadata['file']).read_bytes()
    require(len(data) == metadata['bytes'] and sha(data) == metadata['sha256'], 'original camera metadata exact')
    return value


def reference_oracle(path, expected_sha):
    # Source is explicitly supplied by the lead. Execute definitions without a
    # .pyc write in another worktree; no module main/build/GPU entry point runs.
    data = path.read_bytes()
    require(sha(data) == expected_sha, 'original generator source hash matches sealed v1 manifest')
    namespace = {'__name__':'material_quality_original_definitions', '__file__':str(path)}
    exec(compile(data, str(path), 'exec'), namespace)
    return namespace


def material_field(world, object_mask, center):
    world = np.asarray(world, dtype=np.float64)
    object_mask = np.asarray(object_mask, dtype=bool)
    local = world-np.where(object_mask[..., None], np.asarray(center, dtype=np.float64), 0.)
    # Static background world coordinates, translating object's local coords.
    # These frequencies/offsets are unrelated to v1 radiance/noise/reference.
    x = np.floor((local[..., 0]+.1732050807568877)*1.25).astype(np.int64)
    y = np.floor((local[..., 1]-.2718281828459045)*1.25).astype(np.int64)
    color_index = np.mod(x+3*y+2*object_mask, len(PALETTE))
    mx = np.floor((local[..., 0]+.3141592653589793)*.7).astype(np.int64)
    my = np.floor((local[..., 1]+.1414213562373095)*.9).astype(np.int64)
    metal_index = np.mod(mx-my+object_mask, len(METALS))
    encoded = np.rint(np.sqrt(PALETTE[color_index])*1023).astype('<u4')
    stored = encoded[..., 0] | (encoded[..., 1] << 10) | (encoded[..., 2] << 20)
    metal_u8 = np.rint(METALS[metal_index]*255).astype('u1')
    base_linear = (encoded.astype(np.float64)/1023)**2
    metal = metal_u8.astype(np.float64)/255
    material_id = (color_index+len(PALETTE)*metal_index+24*object_mask).astype('u1')
    return stored, metal_u8, base_linear, metal, material_id


def ggx_albedo(base, metal, roughness, no_v, dtype=np.float64):
    """Pinned AMD denoising.md5.5.2; no EnvBRDFApprox substitution."""
    d = np.dtype(dtype).type
    base, metal = np.asarray(base, dtype=d), np.asarray(metal, dtype=d)
    roughness, no_v = np.asarray(roughness, dtype=d), np.abs(np.asarray(no_v, dtype=d))
    alpha = roughness*roughness
    f0 = d(.04)+(base-d(.04))*metal[..., None]
    # Row-major matrix-vector products, independently evaluated below by the
    # scalar oracle; powers correspond exactly to x.xy/x.xyw and y.xy/y.xyw.
    xv = np.stack((np.ones_like(no_v), no_v, no_v*no_v*no_v), axis=-1)
    yv = np.stack((np.ones_like(alpha), alpha, alpha*alpha*alpha), axis=-1)
    x2, y2 = xv[..., :2], yv[..., :2]
    m1 = np.array([[.99044, -1.28514], [1.29678, -.755907]], dtype=d)
    m2 = np.array([[1., 2.92338, 59.4188], [20.3225, -27.0302, 222.592], [121.563, 626.13, 316.627]], dtype=d)
    m3 = np.array([[.0365463, 3.32707], [9.0632, -9.04756]], dtype=d)
    m4 = np.array([[1., 3.59685, -1.36772], [9.04401, -16.3174, 9.22949], [5.56589, 19.7886, -20.2123]], dtype=d)
    bias = np.sum((x2 @ m1.T)*y2, axis=-1)/np.sum((xv @ m2.T)*yv, axis=-1)
    scale = np.sum((x2 @ m3.T)*y2, axis=-1)/np.sum((xv @ m4.T)*yv, axis=-1)
    bias = bias*np.clip(f0[..., 1]*d(50), d(0), d(1))
    return f0*np.maximum(d(0), scale)[..., None]+np.maximum(d(0), bias)[..., None]


def ggx_scalar(base, metal, roughness, no_v):
    # Independent scalar polynomial expansion, not the vectorized matrix path.
    v, a = abs(float(no_v)), float(roughness)**2
    bias_num = .99044-1.28514*v+a*(1.29678-.755907*v)
    bias_den = 1.+2.92338*v+59.4188*v**3+a*(20.3225-27.0302*v+222.592*v**3)+a**3*(121.563+626.13*v+316.627*v**3)
    scale_num = .0365463+3.32707*v+a*(9.0632-9.04756*v)
    scale_den = 1.+3.59685*v-1.36772*v**3+a*(9.04401-16.3174*v+9.22949*v**3)+a**3*(5.56589+19.7886*v-20.2123*v**3)
    f0 = [.04+(float(c)-.04)*float(metal) for c in base]
    bias = (bias_num/bias_den)*max(0., min(1., f0[1]*50))
    return np.array([c*max(0., scale_num/scale_den)+max(0., bias) for c in f0])


def unpack_normal(words):
    u = ((words & 1023).astype(np.float64)/1023)*2-1
    v = (((words >> 10) & 1023).astype(np.float64)/1023)*2-1
    z = 1-np.abs(u)-np.abs(v)
    require(np.all(z > 0), 'v1 prescribed +Z hemisphere, no invented negative-oct decoder')
    normal = np.stack((u, v, z), axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    roughness = ((words >> 20) & 1023).astype(np.float64)/1023
    require(np.all((words >> 30) == 0), 'v1 material category0 is supported by native guide path')
    return normal, roughness


def prepare(inputs, output, oracle_path):
    v1 = original(inputs)
    oracle = reference_oracle(oracle_path, v1['generator_sha256'])
    dataset = output/'dataset'
    views = {name:output/'views'/name for name in CANDIDATES}
    for path in views.values():
        immutable(path/'native-replay.txt', (inputs/v1['native_replay']['file']).read_bytes())
    rows, previous_center = [], None
    maximum_guide_error = {'diff':0., 'spec':0.}
    for index, frame in enumerate(v1['frames']):
        require(frame['index'] == index and frame['frame'] == index+2 and frame['reset'] == (index == 0), 'unchanged temporal alignment')
        source = inputs/frame['directory']
        arrays = {name:load(source, info) for name, info in frame['payloads'].items()}
        camera = np.asarray(frame['camera'], dtype=np.float64)
        center = np.asarray(frame['object_center'], dtype=np.float64)
        pose = dict(camera=camera, center=center, projection=np.asarray(frame['projection']), rotation=np.asarray(frame['view'])[:3, :3])
        yy, xx = np.mgrid[:128, :128]
        uv = (np.stack((xx+.5, yy+.5), axis=-1)-np.asarray(frame['jitter']))/128
        geometry = oracle['trace'](uv, pose)
        require(np.array_equal(geometry['point'].astype('<f4').view('<u4'), arrays['current_world'].view('<u4')),
                'retraced original geometry exactly equals published float32 world points')
        require(np.array_equal(geometry['object'], arrays['object']), 'original object visibility unchanged')
        stored, metal_u8, base, metal, material_id = material_field(geometry['point'], geometry['object'], center)
        last_center = center if previous_center is None else previous_center
        corresponding = geometry['point']+geometry['object'][..., None]*(last_center-center)
        old_stored, old_metal, _, _, _ = material_field(corresponding, geometry['object'], last_center)
        require(np.array_equal(stored, old_stored) and np.array_equal(metal_u8, old_metal),
                'same physical point keeps exact stored material through object/camera motion')
        previous_center = center
        normal, roughness = unpack_normal(arrays['normals'])
        to_camera = camera-geometry['point']
        to_camera /= np.linalg.norm(to_camera, axis=-1, keepdims=True)
        guide_no_v = np.abs(np.sum(normal*to_camera, axis=-1))
        reference_no_v = np.abs(to_camera[..., 2])  # exact geometric normal+Z.
        captured = np.concatenate((base, metal[..., None]), axis=-1).astype('<f2')
        # Explicit synthetic RNE input packet. Actual production native-capture
        # typed-store rounding is validated by its separate GPU fixture.
        captured_f32 = captured.astype(np.float32)
        qd = base*(1-metal[..., None])
        qs = ggx_albedo(base, metal, roughness, reference_no_v)
        guide_qd = captured_f32[..., :3]*(np.float32(1)-captured_f32[..., 3:])
        guide_qs = ggx_albedo(captured_f32[..., :3], captured_f32[..., 3], roughness, guide_no_v, np.float32)
        require(np.isfinite(qd).all() and np.isfinite(qs).all() and np.all(qs >= 0), 'valid nonnegative analytic material factors')
        require(np.isfinite(guide_qd).all() and np.isfinite(guide_qs).all() and np.all(guide_qs >= 0), 'finite supported guide approximation')
        guide_words = {}
        for signal, rgb in (('diff', guide_qd), ('spec', guide_qs)):
            # Exact prepared bytes, not a claim about a future hardware typed
            # store. Half-RNE precedes R8-RNE; the upload passes words unchanged.
            half_rgb = rgb.astype('<f2').astype(np.float64)
            words = arrays[signal+'_albedo'].copy()
            words[..., :3] = np.rint(np.clip(half_rgb, 0, 1)*255).astype('u1')
            require(np.array_equal(words[..., 3], arrays[signal+'_albedo'][..., 3]), 'unused albedo alpha retained exactly')
            guide_words[signal] = words
            target = qd if signal == 'diff' else qs
            maximum_guide_error[signal] = max(maximum_guide_error[signal], float(np.max(np.abs(words[..., :3]/255-target))))
        physical = dict(stored_base=stored, stored_metal=metal_u8, base_metal=captured,
            material_id=material_id, no_v=guide_no_v.astype('<f4'),
            qd=qd.astype('<f4'), qs=qs.astype('<f4'),
            true_diff_albedo=guide_words['diff'], true_spec_albedo=guide_words['spec'])
        folder = dataset/frame['directory']
        records = {name:put(folder, name+'.bin', value) for name, value in physical.items()}
        for candidate, view in views.items():
            target = view/frame['directory']
            for name in IDENTICAL:
                source_name = 'motion_surface' if name == 'motion' else name
                info = frame['payloads'][source_name]
                immutable(target/(name+'.bin'), (source/info['file']).read_bytes())
                require(file_sha(target/(name+'.bin')) == info['sha256'], 'candidate preserves every noisy/hit/guide input byte')
            for signal in ('spec', 'diff'):
                enabled = candidate == 'both' or candidate == ('specular-only' if signal == 'spec' else 'diffuse-only')
                value = guide_words[signal] if enabled else arrays[signal+'_albedo']
                immutable(target/(signal+'_albedo.bin'), value.tobytes())
                require(file_sha(target/(signal+'_albedo.bin')) == sha(value.tobytes()), 'exact uploaded albedo candidate words')
        rows.append(dict(frame=frame['frame'], directory=frame['directory'], source_payloads=frame['payloads'], derived=records,
                         reference_factor_model='full-precision canonical RGB10^2/metalR8 + declared analytic GGX, not native LUT'))
    manifest = dict(schema=SCHEMA, source_directory=str(inputs), source_manifest_sha256=SOURCE_SHA,
        source_generator_sha256=v1['generator_sha256'], script_sha256=file_sha(Path(__file__)),
        width=128, height=128, frames=rows, submitted_frames=64, comparison_crop=v1['comparison_crop'],
        prepared_views={name:str(path) for name, path in views.items()}, candidates=list(CANDIDATES), route='dd', motion_mode='surface',
        native_replay=v1['native_replay'], source_lighting_and_noise_unchanged=True,
        material_mapping='world XY background; moving rectangle local XY; deterministic independent palette/metal tiles',
        canonical_storage='RGB10A2 encoded sqrt(baseLinear), alpha0; metalR8; captured linearRGB/metal half-RNE',
        guide_storage='linear NON_GAMMA_ALBEDO; explicit half-RNE then R8-RNE CPU uploads; unused alpha copied from v1',
        guides_are_native_lut=False, ggx_model='pinned AMD denoising.md5.5.2 rational ApproximateBRDF',
        remodulation='current Qd*RRdiff + current Qs*RRspec; unity exposure; pre-Consumer64 units; no signal divide',
        maximum_guide_vs_full_precision_factor_error=maximum_guide_error,
        native_nrd_paired=False, in_game_capture=False, path_integrated_ground_truth=False,
        compiler_executed=False, gpu_executed=False, python_checks=CHECKS)
    write_json(output/'material-sequence.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, default=Path('F:/FSRD/sol_batch/15e-quality/inputs'))
    parser.add_argument('--output', type=Path, default=Path('F:/FSRD/sol_batch/15c-rr/material-v2'))
    parser.add_argument('--oracle-source', type=Path, default=Path(__file__).resolve().parent / 'fsrd_nrd_motion_quality_oracle_v1_frozen.py')
    args = parser.parse_args()
    result = prepare(args.inputs, args.output, args.oracle_source)
    print(json.dumps({k:v for k,v in result.items() if k != 'frames'}, indent=2))


if __name__ == '__main__':
    main()
