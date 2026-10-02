"""Root-only single fixed-operator CPU quality decision on existing CLOSED f63 bytes."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import sys

if sys.flags.optimize or not __debug__:
    raise RuntimeError('optimized Python prohibited')
import numpy as np
assert np.__version__ == '2.3.5'

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / 'endpoint_once'
OLD = ROOT / 'tools_tmp/fsrd_observable_radiance_SPEC_guide_full1_quality_preparation_20261002'
RUN = OLD / 'runtime_once'
POST = ROOT / 'tools_tmp/fsrd_radiance_phase_amplitude_saved_POST_20261002'
W, H, N, FRAME = 128, 80, 64, 63
pins, used = {}, {}

def record(path):
    path = Path(path).resolve()
    return {'path': str(path), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

def add(pin):
    key = str(Path(pin['path']).resolve())
    assert key not in pins or pins[key] == pin, 'conflicting pin'
    pins[key] = pin

def read(path):
    path = Path(path).resolve()
    key = str(path)
    assert key in pins, 'unqualified input: ' + key
    data = path.read_bytes()
    actual = {'path': key, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    assert actual == pins[key], 'changed input: ' + key
    used[key] = actual
    return data

def load(path):
    return json.loads(read(path).decode('utf-8-sig'))

# The previous POST is terminal before any radiance bytes are consumed here.
receipt = record(POST / 'completion.json')
assert receipt['sha256'] == '902d27426fe4cdbf4eef6991489a7e3ae3467daccfa651f5ede7ff7614cbfed0'
add(receipt)
previous = load(receipt['path'])
assert previous['status'] == 'CLOSED_ACTUAL_SAVED_CPU_POST'
g = previous['guard']
assert g['actual_CLOSED'] and g['returncode'] == 0 and not g['terminated_owned_child'] and 'monitor_error' not in g
add(previous['result'])
saved_post = load(previous['result']['path'])
assert saved_post['rejection_unchanged'] and saved_post['consumed_pins_before_after_equal']
for pin in saved_post['consumed_pins']:
    add(pin)
completion = load(OLD / 'root_actual_completion.json')
for stage in completion['stages']:
    assert stage['all_ordinary_CLOSED'] and stage['source_input_before_after_equal']
    add(stage['result'])
    proof = load(stage['result']['path'])
    assert proof['all_children_CLOSED'] and not proof['failed_prefix_work_unknown']
    for pin in proof['before'] + proof['prerequisite_pins'] + proof['outputs']:
        add(pin)

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

# Original frozen scoring function; import does not call its guarded main/stages.
sys.path.insert(0, str(OLD))
read(OLD / 'common.py')
read(OLD / 'worker.py')
metrics = module('frozen_quality_metrics', OLD / 'worker.py')
authority = json.loads((HERE / 'ROOT_ONCE_AUTHORIZATION.json').read_text(encoding='utf-8-sig'))
for pin in authority['source_pins']:
    assert record(pin['path']) == pin
operator = module('fixed_collaborative_operator', HERE / 'collaborative_filter.py')

def half4(path, frames=1):
    data = read(path)
    assert len(data) == frames * W * H * 8
    value = np.frombuffer(data, '<f2').reshape(frames, H, W, 4).astype(np.float64)
    assert np.isfinite(value[..., :3]).all()
    return value

producer = load(RUN / 'produce/producer.json')
assembly = load(RUN / 'assemble/assembly.json')
case = producer['cases'][0]
def factor(slot):
    data = read(case['inputs'][slot]['path'])
    assert len(data) == N * W * H * 4
    code = np.frombuffer(data, 'u1').reshape(N, H, W, 4)[FRAME, ..., :3]
    return (code.astype('<f4') / np.float32(255)).astype('<f2').astype(np.float64)

qs, qd = factor(3), factor(4)
cv = RUN / 'assemble/converter_jobs/63'
source = half4(cv / 'rawC.bin')[0, ..., :3]
assert np.all(source >= 0) and np.all(source < 65504)
baselines = {arm: half4(RUN / 'endpoint/compositions' / arm / '63/TOTAL/out0.bin')[0, ..., :3]
             for arm in ('A1', 'A2')}
depth = np.frombuffer(read(Path(assembly['data']) / 'depth.bin'), '<f4').reshape(H, W).astype(np.float64)
packed = np.frombuffer(read(cv / 'out3.bin'), '<u4').reshape(H, W)
roughness = ((packed >> 20) & 1023).astype(np.int32)
material = (packed >> 30).astype(np.int32)
# Current OctahedralEncode uses -1 signs at zero XY: (0,0,-1) encodes UV(0,0).
# The historically qualified constant fixture's packed RG0 decodes to (0,0,-1).
assert np.all((packed & 1023) == 0) and np.all(((packed >> 10) & 1023) == 0)
assert np.all(depth == depth[0, 0]) and depth[0, 0] > 0
normals = np.zeros((H, W, 3), dtype=np.float64)
normals[..., 2] = -1
gradient = np.zeros((H, W, 2), dtype=np.float64)
valid = np.isfinite(depth) & (depth > 0)
truth_bytes = read(Path(assembly['truth']) / 'TOTAL.bin')
truth = np.frombuffer(truth_bytes, '<f8').reshape(N, H, W, 4)[FRAME:FRAME+1]
assert np.isfinite(truth).all()

candidate, diagnostics = operator.apply_frame(np, source, qs, qd, baselines['A1'], valid,
        linear_depth=depth, normals=normals, depth_gradient=gradient,
        roughness_codes=roughness, material_codes=material)
assert candidate.shape == (H, W, 3) and np.isfinite(candidate).all()
assert np.all(candidate >= 0) and np.all(candidate < 65504)
assert np.array_equal(candidate, candidate.astype('<f2').astype(np.float64)), 'candidate must declare actual modeled HALF store'
# Valid output is a replacement. Invalid fallback must be paired to EACH baseline.
candidate2, diagnostics2 = operator.apply_frame(np, source, qs, qd, baselines['A2'], valid,
        linear_depth=depth, normals=normals, depth_gradient=gradient,
        roughness_codes=roughness, material_codes=material)
assert candidate2.shape == candidate.shape and np.isfinite(candidate2).all()
assert np.all(candidate2 >= 0) and np.all(candidate2 < 65504)
assert np.array_equal(candidate2, candidate2.astype('<f2').astype(np.float64))

regions = {'WHOLE': (0, W), 'STATIC_CLEAN': (0, 32), 'ANIM_CLEAN': (32, 64),
           'STATIC_NOISY': (64, 96), 'ANIM_NOISY': (96, 128)}

def score_row(value, lo, hi):
    result = metrics.metrics(np, value[None], truth, lo, hi)
    for kind, frequency, idx in (('illumination', 1 / 16, np.arange(H)),
                                 ('material', 1 / 8, np.arange(lo, hi))):
        v, t = value[:, lo:hi], truth[0, :, lo:hi, :3]
        axis = 1 if kind == 'illumination' else 0
        v, t = v.mean(axis=axis), t.mean(axis=axis)
        carrier = np.exp(-2j * np.pi * frequency * idx)
        denominator = np.einsum('ic,i->c', t - t.mean(axis=0), carrier)
        numerator = np.einsum('ic,i->c', v - v.mean(axis=0), carrier)
        amplitudes, signed_phases = [], []
        for channel in range(3):
            if abs(denominator[channel]) < 1e-12:
                amplitudes.append(None)
                signed_phases.append(None)
            else:
                q = numerator[channel] / denominator[channel]
                assert abs(q.real - result['carriers'][kind]['gain_RGB'][0][channel]) <= 1e-12
                amplitudes.append(float(abs(q)))
                signed_phases.append(float(np.angle(q)))
        result['carriers'][kind]['amplitude_RGB'] = [amplitudes]
        result['carriers'][kind]['signed_phase_rad_RGB'] = [signed_phases]
    return result

rows, pairs = {}, []
for arm, value, diag in (('A1', candidate, diagnostics), ('A2', candidate2, diagnostics2)):
    rows[arm] = {'baseline': {}, 'candidate': {}, 'operator_diagnostics': diag,
                 'actually_changed_pixels': int(np.count_nonzero(np.any(value != baselines[arm], axis=2)))}
    for region, (lo, hi) in regions.items():
        rows[arm]['baseline'][region] = score_row(baselines[arm], lo, hi)
        rows[arm]['candidate'][region] = score_row(value, lo, hi)
    detail = all(metrics.detail_ok(rows[arm]['candidate'][region]) for region in ('STATIC_CLEAN', 'ANIM_CLEAN'))
    failures = [] if detail else ['absolute_clean_detail']
    necessary_quality = True
    for region in regions:
        a, b = rows[arm]['baseline'][region], rows[arm]['candidate'][region]
        if not b['material_error'] < a['material_error']:
            necessary_quality = False
            failures.append(region + '/material_no_strict_improvement')
        if b['rmse'] > a['rmse']:
            necessary_quality = False
            failures.append(region + '/physical_rmse_worse')
        if any(abs(x) > abs(y) for x, y in zip(b['bias_rgb'], a['bias_rgb'])):
            necessary_quality = False
            failures.append(region + '/absolute_RGB_bias_worse')
    pairs.append({'baseline': arm, 'detail_PASS': detail,
                  'endpoint_necessary_quality_PASS': necessary_quality,
                  'combined_endpoint_PASS': detail and necessary_quality,
                  'failures': failures})
    rgba = np.ones((H, W, 4), dtype='<f2')
    rgba[..., :3] = value
    with (OUT / (arm + '_candidate_f63_RGBA16.bin')).open('xb') as stream:
        stream.write(rgba.tobytes())

detail_pass = all(p['detail_PASS'] for p in pairs)
all_pass = all(p['combined_endpoint_PASS'] for p in pairs)
status = ('REJECT_FIXED_COLLABORATIVE_ILLUMINATION_DETAIL' if not detail_pass else
          'REJECT_FIXED_COLLABORATIVE_ILLUMINATION_ENDPOINT_QUALITY' if not all_pass else
          'ENDPOINT_PASS_INCONCLUSIVE_REQUIRE_ALL64_AND_IMPLEMENTATION')
for path, pin in used.items():
    assert record(path) == pin
for pin in authority['source_pins']:
    assert record(pin['path']) == pin
with (OUT / 'result.json').open('x', encoding='utf-8', newline='\n') as stream:
    json.dump({'status': status, 'frame': FRAME, 'rows': rows, 'pairs': pairs,
               'continuation_permitted': all_pass, 'all64_quality_PASS': None,
               'paired_candidate_equal': bool(np.array_equal(candidate, candidate2)),
               'temporal_efficacy': None, 'actual_GPU_candidate': False,
               'scope': 'one fixed CPU operator/modelled HALF output; two paired ACTUAL existing unchanged-CSO baselines f63; physical truth score-only. No SDK/guide/parameter changes.',
               'rejected_radiance_guide_decision_unchanged': True,
               'used_pins_before_after_equal': True, 'used_pins': list(used.values()),
               'PID': os.getpid(), 'numpy_version': np.__version__}, stream, indent=2, allow_nan=False)
    stream.write('\n')
