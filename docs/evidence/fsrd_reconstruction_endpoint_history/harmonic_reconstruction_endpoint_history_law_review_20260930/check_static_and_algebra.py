"""Independent pre-score text/pin/header/rational algebra audit. No model/analyzer imports."""
from pathlib import Path
from fractions import Fraction as F
import ast, hashlib, json, struct, zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PREP = ROOT / 'tools_tmp/harmonic_reconstruction_endpoint_history_feasibility_20260930'
V2 = ROOT / 'tools_tmp/harmonic_response_coefficient_history_feasibility_v2_20260930'

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))

def text(p):
    return Path(p).read_text(encoding='utf-8-sig')

def transform(base, operations):
    records = []
    for op in operations:
        count = base.count(op['before'])
        expected = op.get('occurrences', 1)
        assert count == expected, (op['label'], count, expected)
        base = base.replace(op['before'], op['after'])
        records.append(dict(label=op['label'], matched=count))
    return base, records

model_whitelist = read(PREP / 'source_implementation_whitelist.json')
analysis_whitelist = read(PREP / 'analysis_implementation_whitelist.json')
assert sha(model_whitelist['frozen_V2_model']['path']) == model_whitelist['frozen_V2_model']['sha256']
model_text, model_ops = transform(text(V2 / 'model.py'), model_whitelist['operations'])
model_text += model_whitelist['suffix_only']
assert model_text == text(PREP / 'model.py')
assert sha(PREP / 'model.py') == model_whitelist['new_model_SHA'] == '3f807416726e6bd1e11c3f6b16e9259151dbd4b0a8232ca28f37cca01ca94126'
assert sha(PREP / 'frozen_V2_model.py.txt') == sha(V2 / 'model.py')
assert sha(analysis_whitelist['original_analyzer']['path']) == analysis_whitelist['original_analyzer']['sha256']
analysis_text, analysis_ops = transform(text(V2 / 'analyze.py'), analysis_whitelist['operations'])
assert analysis_text == text(PREP / 'analyze.py')
operator_import = analysis_whitelist['operator_import_replacement_only']
assert text(V2 / 'known_operators.py').count(operator_import['before']) == 1
assert text(V2 / 'known_operators.py').replace(operator_import['before'], operator_import['after']) == text(PREP / 'known_operators.py')
assert sha(V2 / 'known_operators.py') == analysis_whitelist['unchanged_24_known_operator_generator_SHA']
assert text(V2 / 'selfchecks.py').split('def run():')[0] == text(PREP / 'frozen_operator_helpers.py')
known_yields = sum(isinstance(node, ast.Yield) for node in ast.walk(ast.parse(text(PREP / 'known_operators.py'))))
assert known_yields == 24

freeze = read(PREP / 'pre_cpu_freeze.json')
assert sha(PREP / 'pre_cpu_freeze.json') == '9d5e3e66255a684e4941cbbfc59379f713f4ae36a7d7ce93348b592af90cb48f'
assert (PREP / 'pre_cpu_freeze.json').read_bytes() == (PREP / 'pre_score_freeze.json').read_bytes()
source_checks = [dict(path=p, expected=h, actual=sha(p)) for p, h in freeze['sources'].items()]
assert len(source_checks) == 61 and all(r['actual'] == r['expected'] for r in source_checks)
v2_freeze = read(V2 / 'pre_score_freeze.json')
auth = read(PREP / 'source_authentication.json')
assert len(auth['rows']) == 6
assert sha(PREP / 'source_authentication.json') == sha(V2 / 'source_authentication.json')
native_input_pins = []
headers = []
for row in auth['rows']:
    folder = ROOT / 'tools_tmp' / ('native_continuous_harmonic_fresh_retry_20260930' if row['scene'] == 'material' else 'native_continuous_harmonic_remaining_20260930') / 'evidence'
    npz = folder / row['scene'] / 'sequences.npz'
    controls = folder / row['scene'] / 'observed/frame_controls.txt'
    for p in (npz, controls):
        key = str(p)
        assert key in freeze['sources'] and key in v2_freeze['sources']
        assert freeze['sources'][key] == v2_freeze['sources'][key] == sha(p)
        native_input_pins.append(dict(scene=row['scene'], path=key, sha256=sha(p)))
    assert sha(npz) == row['NPZ_sha256']
    # Inspect only NPY metadata headers; do not read pixel arrays or clean-reference data.
    with zipfile.ZipFile(npz) as archive:
        arrays = {}
        for name in ('observed', 'pilot', 'pilot_response', 'baseline', 'harmonic', 'active'):
            with archive.open(name + '.npy') as stream:
                assert stream.read(6) == b'\x93NUMPY'
                version = tuple(stream.read(2))
                size = struct.unpack('<H' if version[0] == 1 else '<I', stream.read(2 if version[0] == 1 else 4))[0]
                header = ast.literal_eval(stream.read(size).decode('latin1').strip())
                arrays[name] = header
        assert all(arrays[name]['descr'] == '<f4' for name in ('observed', 'pilot', 'pilot_response', 'baseline', 'harmonic'))
        assert arrays['active']['descr'] == '|b1'
        headers.append(dict(scene=row['scene'], headers_only=arrays))

math = []
for n in range(1, 17):
    t = list(range(n))
    if n == 1:
        weights = [F(1)]
    else:
        center = F(n - 1, 2)
        denominator = sum((F(i) - center) ** 2 for i in t)
        weights = [F(1, n) + (F(i) - center) * (F(n - 1) - center) / denominator for i in t]
    zeroth = sum(weights)
    first = sum(w * i for w, i in zip(weights, t))
    gain = sum(w * w for w in weights)
    expected_gain = F(1) if n == 1 else F(2 * (2 * n - 1), n * (n + 1))
    assert zeroth == 1 and first == n - 1 and gain == expected_gain
    quadratic_bias = sum(w * i * i for w, i in zip(weights, t)) - (n - 1) ** 2
    assert quadratic_bias == -F((n - 1) * (n - 2), 6)
    math.append(dict(n=n, weights=[str(w) for w in weights], sum=str(zeroth), first_moment=str(first),
                     nominal_IID_variance_gain=str(gain), endpoint_quadratic_unit_coefficient_bias=str(quadratic_bias)))
weights16 = [F(x) for x in math[-1]['weights']]
step_partial_sums = [sum(weights16[-k:]) for k in range(1, 17)]
assert max(step_partial_sums) == F(22, 17) and step_partial_sums.index(max(step_partial_sums)) + 1 == 11

correction_path = PREP / 'preparation_seal_correction.json'
correction_sha = sha(correction_path)
assert correction_sha == 'a121fe8c3e4edf352435f86cfdd4e3685ad9cd44882a0bc29630f4e04465e501'
result = dict(
    schema='endpoint-law-independent-static-rational-review-checks-v1',
    status='passed_no_model_analyzer_or_known_operator_execution',
    model_whitelist_exact=True, model_operations=model_ops,
    analyzer_whitelist_exact=True, analyzer_operations=analysis_ops,
    operator_generator_exact_except_single_import=True, helper_prefix_exact=True, known_operator_static_yield_count=known_yields,
    freeze_alias_byte_exact=True, frozen_source_pin_count=len(source_checks), frozen_source_pins_all_equal=True,
    source_checks=source_checks, native_input_pins=native_input_pins, native_input_headers_only=headers,
    source_authentication_byte_hash_equal_to_V2=True,
    exact_rational_weight_checks=math,
    n16_step_algebra=dict(current_frame_only_step_gain=str(step_partial_sums[0]),
        largest_positive_step_gain=str(max(step_partial_sums)), newest_observations_after_step_at_max=11,
        overshoot_fraction=str(max(step_partial_sums)-1), negative_weight_sum=str(sum(w for w in weights16 if w<0)),
        absolute_weight_sum=str(sum(abs(w) for w in weights16)),
        scope='Pure algebra for an uncut coefficient step in fixed/transported coordinates; no scene/operator scoring.'),
    correction_pin=dict(path=str(correction_path), sha256=correction_sha),
    model_analyzer_imports=0, known_operator_calls=0, cohort_scores=0, native_GPU_calls=0,
    inspected_array_data=False, inspected_clean_reference_headers=False, quality_accepted=False)
(HERE / 'checks.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
print(json.dumps(dict(status=result['status'], frozen_sources=len(source_checks), native_rows=len(headers),
    whitelist_model=True, whitelist_analyzer=True, static_known_yields=known_yields,
    n16_gain=math[-1]['nominal_IID_variance_gain'], n16_max_uncut_step_gain=str(max(step_partial_sums)), scores=0)))
