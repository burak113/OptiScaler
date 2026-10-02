"""Root-only saved-byte attribution of the CLOSED P/native recovery, no candidate rerun."""
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
OUT = HERE / 'post_once'
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

PARENT = ROOT / 'tools_tmp/fsrd_collaborative_illumination_residual_quality_preparation_20261002'
pc = record(PARENT / 'endpoint_once/completion.json')
assert pc['sha256'] == 'd535d4de91b2e5df592cc2ffc775d064e48dfdd5803a041105372dfb54af201e'
add(pc)
pclosed = load(pc['path'])
assert pclosed['status'] == 'CLOSED_ACTUAL_FIXED_CPU_ENDPOINT'
pg = pclosed['guard']
assert pg['actual_CLOSED'] and pg['returncode'] == 0 and not pg['terminated_owned_child'] and 'monitor_error' not in pg
add(pclosed['result'])
presult = load(pclosed['result']['path'])
assert presult['status'] == 'REJECT_FIXED_COLLABORATIVE_ILLUMINATION_ENDPOINT_QUALITY'
assert not presult['continuation_permitted'] and presult['all64_quality_PASS'] is None
assert presult['paired_candidate_equal'] and presult['used_pins_before_after_equal']
pr = record(PARENT / 'ROOT_actual_quality_receipt.json')
assert pr['sha256'] == 'dc2ab7a84fa2fc4bc568b94971d783074738dc086d677d4ac6099f3be4453df9'
add(pr)
pmetadata = load(pr['path'])
assert pmetadata['status'] == 'CLOSED_ACTUAL_ONE_FIXED_CPU_QUALITY_REJECT'
assert not pmetadata['continuation_permitted']
for pin in pmetadata['artifacts']:
    add(pin)

RECOVERY = ROOT / 'tools_tmp/fsrd_P_native_statistical_recovery_quality_preparation_20261002'
rc = record(RECOVERY / 'endpoint_once/completion.json')
assert rc['sha256'] == '1f14ed71aa7d92929e07dffc86bb03062a78e9940d075caa26489bb2b68ff5d1'
add(rc)
recovery_closed = load(rc['path'])
assert recovery_closed['status'] == 'CLOSED_ACTUAL_FIXED_CPU_ENDPOINT'
rg = recovery_closed['guard']
assert rg['actual_CLOSED'] and rg['returncode'] == 0 and not rg['terminated_owned_child'] and 'monitor_error' not in rg
add(recovery_closed['result'])
recovery_result = load(recovery_closed['result']['path'])
assert recovery_result['status'] == 'REJECT_FIXED_P_NATIVE_RECOVERY_ENDPOINT_QUALITY'
assert not recovery_result['continuation_permitted'] and recovery_result['all64_quality_PASS'] is None
rr = record(RECOVERY / 'ROOT_actual_quality_receipt.json')
assert rr['sha256'] == '28c07644c8c7a6ddd86061ebd17d97cc86af5448aabf923d986362a09a8b90c3'
add(rr)
recovery_metadata = load(rr['path'])
for pin in recovery_metadata['artifacts']:
    add(pin)
for arm in ('A1', 'A2'):
    diag = recovery_result['rows'][arm]['operator_diagnostics']
    assert diag['recovered_pixels'] == W*H and diag['fallback_pixels'] == 0
    assert diag['unsupported_stencils'] == 0 and diag['arithmetic_rejected_pixels'] == 0

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
attribution = module('fixed_saved_component_attribution', HERE / 'attribution.py')

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
# Saved rejected P is a reference operand, never a newly accepted whole output.
referenceP = half4(PARENT / 'endpoint_once/A1_candidate_f63_RGBA16.bin')[0, ..., :3]
referenceP2 = half4(PARENT / 'endpoint_once/A2_candidate_f63_RGBA16.bin')[0, ..., :3]
assert np.array_equal(referenceP, referenceP2)
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

regions = {'WHOLE': (0,W), 'STATIC_CLEAN': (0,32), 'ANIM_CLEAN': (32,64),
           'STATIC_NOISY': (64,96), 'ANIM_NOISY': (96,128)}
rows = {}
for arm in ('A1','A2'):
    saved_T = half4(RECOVERY / ('endpoint_once/' + arm + '_candidate_f63_RGBA16.bin'))[0,...,:3]
    report = attribution.attribute_frame(np, source, qs, qd, referenceP, baselines[arm],
        saved_T, truth[0,...,:3], valid, linear_depth=depth, normals=normals,
        depth_gradient=gradient, roughness_codes=roughness, material_codes=material,
        regions=regions, closed_fallback_pixels=recovery_result['rows'][arm]['operator_diagnostics']['fallback_pixels'])
    assert report['mean_supported_pixels'] == W*H and report['actual_candidate_rejection_unchanged']
    for region in regions:
        row = report['rows'][region]
        frozen = recovery_result['rows'][arm]
        assert abs(np.sqrt(row['actual_T_MSE']) - frozen['candidate'][region]['rmse']) <= 1e-12
        assert abs(np.sqrt(row['actual_T_material_error_squared']) - frozen['candidate'][region]['material_error']) <= 1e-12
        assert abs(row['pixel_error_gram']['RMS'][0] - frozen['baseline'][region]['rmse']) <= 1e-12
        assert abs(row['material_profile_gram']['RMS'][0] - frozen['baseline'][region]['material_error']) <= 1e-12
        assert abs(row['pixel_MSE_closure_residual']) <= 1e-15
        assert abs(row['material_MSE_closure_residual']) <= 1e-15
        assert row['pointwise_identity_max_abs'] <= 1e-12
        for kind in ('material','illumination'):
            carrier = row['carriers'][kind]
            assert not any(carrier['reference_zero_RGB'])
            assert max(abs(x) for x in carrier['numerator_closure_Re_RGB']) <= 1e-12
            assert max(abs(x) for x in carrier['numerator_closure_Im_RGB']) <= 1e-12
            for label, source_kind in (('BASE','baseline'),('T','candidate')):
                actual = carrier['contributions'][label]
                old = frozen[source_kind][region]['carriers'][kind]
                for c, value in enumerate(actual):
                    assert abs(value['Re'] - old['gain_RGB'][0][c]) <= 1e-12
                    assert abs(abs(np.arctan2(value['Im'],value['Re'])) - old['phase_RGB'][0][c]) <= 1e-12
    rows[arm] = report
for path, pin in used.items():
    assert record(path) == pin
for pin in authority['source_pins']:
    assert record(pin['path']) == pin
with (OUT / 'result.json').open('x',encoding='utf-8',newline='\n') as stream:
    json.dump({'status':'CLOSED_SAVED_COMPONENT_ATTRIBUTION_ONLY_REJECT_UNCHANGED',
        'frame':FRAME,'rows':rows,'PID':os.getpid(),'numpy_version':np.__version__,
        'new_quality_candidates':0,'new_candidate_executions':0,'new_GPU':0,'new_RR':0,
        'no_HH_or_weight_recomputation':True,'recovery_rejection_unchanged':True,
        'P_full_output_rejection_unchanged':True,'remainder_includes_HALF_rounding':True,
        'used_pins_before_after_equal':True,'used_pins':list(used.values()),
        'scope':'Exact B=M*muD only; H=SAVED T-R-B; error Gram/profile/carrier decomposition of two already CLOSED actual CPU outputs. No new quality acceptance, noise calibration or game stain inference.'},
        stream,indent=2,allow_nan=False)
    stream.write('\n')