"""Read-only POST of already CLOSED radiance-guide bytes; no GPU/SDK/shader calls."""
from pathlib import Path
import hashlib
import json
import os
import sys
if sys.flags.optimize or not __debug__:
    raise RuntimeError('optimized Python prohibited')
import numpy as np

assert np.__version__ == '2.3.5'

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OLD = ROOT / 'tools_tmp/fsrd_observable_radiance_SPEC_guide_full1_quality_preparation_20261002'
RUN = OLD / 'runtime_once'
W, H, N = 128, 80, 64
ARMS = ('A1', 'B1', 'B2', 'A2')
REGIONS = {'STATIC_CLEAN': (0, 32), 'ANIM_CLEAN': (32, 64)}
pins, consumed = {}, {}

def record(path):
    path = Path(path).resolve()
    return {'path': str(path), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

def add(pin):
    key = str(Path(pin['path']).resolve())
    assert key not in pins or pins[key] == pin, 'conflicting historical pin'
    pins[key] = pin

def read(path):
    path = Path(path).resolve()
    key = str(path)
    assert key in pins, 'not historically pinned: ' + key
    data = path.read_bytes()
    actual = {'path': key, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    assert actual == pins[key], 'historical bytes changed: ' + key
    consumed[key] = actual
    return data

def load(path):
    return json.loads(read(path).decode('utf-8-sig'))

completion_path = OLD / 'root_actual_completion.json'
completion_pin = record(completion_path)
assert completion_pin['sha256'] == '419cc7d2e87d6cd66cf5c7a2828f166638cedcaa1af0fc139e278e5baa547211'
add(completion_pin)
completion = load(completion_path)
assert completion['decision'].startswith('REJECT') or 'REJECT' in completion['status']
for stage in completion['stages']:
    assert stage['all_ordinary_CLOSED'] and stage['source_input_before_after_equal']
    add(stage['result'])
    evidence = load(stage['result']['path'])
    assert evidence['all_children_CLOSED'] and not evidence['failed_prefix_work_unknown']
    for child in evidence['children']:
        guard = child['guard']
        assert child['actual_CLOSED'] and guard['actual_CLOSED']
        assert guard['returncode'] == 0 and not guard['terminated_owned_child']
        assert 'monitor_error' not in guard
    for pin in evidence['before'] + evidence['prerequisite_pins'] + evidence['outputs']:
        add(pin)

score = load(RUN / 'score_endpoint/score.json')
assert score['status'] == 'REJECT_FIXED_SOURCE_RADIANCE_GUIDE_DETAIL'
assert not score['continuation_permitted'] and not score['quality_PASS']
assembly = load(RUN / 'assemble/assembly.json')
producer = load(RUN / 'produce/producer.json')
precision = load(ROOT / 'tools_tmp/fsrd_joint_vs_independent_lobes_saved_CPU_POST_independent_SOURCE_review_20261002/precision_SOURCE/shader_metadata_check.json')
assert precision['native_low_precision'] and precision['t1_t3_textureLoad'] == 'f16'

def half(path, frames=1):
    data = read(path)
    assert len(data) == frames * W * H * 8
    value = np.frombuffer(data, '<f2').reshape(frames, H, W, 4)[..., :3]
    assert np.isfinite(value).all() and (value >= 0).all()
    return value

def unorm(path):
    data = read(path)
    assert len(data) == N * W * H * 4
    codes = np.frombuffer(data, 'u1').reshape(N, H, W, 4)[..., :3]
    # Current native-half typed load: R8 UNORM RN32 -> HALF -> promoted arithmetic.
    return (codes.astype('<f4') / np.float32(255)).astype('<f2').astype(np.float64)

truth_bytes = read(Path(assembly['truth']) / 'TOTAL.bin')
truth = np.frombuffer(truth_bytes, '<f8').reshape(N, H, W, 4)[..., :3]
assert np.isfinite(truth).all()
inputs = producer['cases'][0]['inputs']
qs, qd = unorm(inputs[3]['path']), unorm(inputs[4]['path'])
cv_s, cv_d = half(inputs[6]['path'], N), half(inputs[5]['path'], N)
native = {arm: {lobe: half(RUN / 'native/outputs' / arm / (lobe + '.bin'), N)
                for lobe in ('specular', 'diffuse')} for arm in ARMS}

def coefficient(value, region, kind):
    lo, hi = REGIONS[region]
    value = value[:, lo:hi, :]
    if kind == 'illumination':
        profile, idx, frequency = value.mean(axis=1), np.arange(H), 1 / 16
    else:
        profile, idx, frequency = value.mean(axis=0), np.arange(lo, hi), 1 / 8
    carrier = np.exp(-2j * np.pi * frequency * idx)
    return np.einsum('ic,i->c', profile - profile.mean(axis=0), carrier)

def measure(value, reference, region):
    result = {}
    for kind in ('illumination', 'material'):
        denominator = coefficient(reference, region, kind)
        assert np.all(np.abs(denominator) > 1e-12), 'zero reference carrier'
        ratio = coefficient(value, region, kind) / denominator
        result[kind] = {'in_phase_RGB': ratio.real.tolist(),
                        'quadrature_RGB': ratio.imag.tolist(),
                        'amplitude_RGB': np.abs(ratio).tolist(),
                        'signed_phase_rad_RGB': np.angle(ratio).tolist(),
                        'abs_phase_rad_RGB': np.abs(np.angle(ratio)).tolist()}
    return result

def row(value, reference):
    return {region: measure(value, reference, region) for region in REGIONS}

frames, endpoint_differences = [], {}
for frame in range(N):
    cv_path = RUN / 'assemble/converter_jobs' / f'{frame:02d}'
    raw = half(cv_path / 'rawC.bin')[0].astype(np.float64)
    skip = half(cv_path / 'out6.bin')[0].astype(np.float64)
    # A diagnostic physical-domain expression; no simulated GPU composition is claimed.
    converted = cv_s[frame].astype(np.float64) * qs[frame]
    converted += cv_d[frame].astype(np.float64) * qd[frame] + skip
    saved = {'frame': frame, 'source_HALF': row(raw, truth[frame]),
             'converter_original_factor_proxy': row(converted, truth[frame]), 'arms': {}}
    for arm in ARMS:
        weighted = native[arm]['specular'][frame].astype(np.float64) * qs[frame]
        weighted += native[arm]['diffuse'][frame].astype(np.float64) * qd[frame] + skip
        saved['arms'][arm] = {'native_original_factor_proxy': row(weighted, truth[frame])}
        if frame == 63:
            actual = half(RUN / 'endpoint/compositions' / arm / '63/TOTAL/out0.bin')[0].astype(np.float64)
            actual_row = row(actual, truth[frame])
            saved['arms'][arm]['actual_current_CSO_composition'] = actual_row
            for region in REGIONS:
                for kind in ('illumination', 'material'):
                    historical = score['rows'][arm]['ENDPOINT63'][region]['TOTAL']['carriers'][kind]
                    assert np.allclose(actual_row[region][kind]['in_phase_RGB'], historical['gain_RGB'][0], rtol=0, atol=1e-12)
                    assert np.allclose(actual_row[region][kind]['abs_phase_rad_RGB'], historical['phase_RGB'][0], rtol=0, atol=1e-12)
            endpoint_differences[arm] = {'proxy_vs_actual_max_abs': float(np.max(np.abs(weighted - actual))),
                                        'proxy_vs_actual_rmse': float(np.sqrt(np.mean((weighted - actual) ** 2))),
                                        'comparison_scope': 'all pixels f63; proxy is not a shader execution'}
    frames.append(saved)

for key, pin in consumed.items():
    assert record(key) == pin, 'consumed bytes changed after POST'
result = {'status': 'CLOSED_SAVED_CPU_POST_PHASE_AMPLITUDE',
          'original_candidate_decision': score['status'], 'rejection_unchanged': True,
          'new_GPU_dispatches': 0, 'new_RR_dispatches': 0, 'new_contexts': 0,
          'metric_definition': 'old gain_RGB=Re(O/T); amplitude_RGB=abs(O/T); phase=arg(O/T). Spatial fundamental: light 1/16 cycles/pixel, material 1/8. No alignment or fitting.',
          'native_proxy_definition': 'stored native SPEC * ORIGINAL SPEC R8 UNORM RN32-to-HALF factor + native DIFF * ORIGINAL DIFF typed factor + original converter Skip, float64 diagnostic arithmetic',
          'scope': 'source, converter/native proxy all64; actual current CSO composition f63 only; clean regions only. No all64 composition, acceptance, opaque internal-stage attribution or lobe-physics claim.',
          'frames': frames, 'endpoint_proxy_vs_actual': endpoint_differences,
          'consumed_pins_before_after_equal': True, 'consumed_pins': list(consumed.values()),
          'python': sys.version, 'numpy_version': np.__version__, 'worker_PID': os.getpid()}
with (HERE / 'result.json').open('x', encoding='utf-8', newline='\n') as stream:
    json.dump(result, stream, indent=2, allow_nan=False)
    stream.write('\n')
