from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'tools_tmp/harmonic_reconstruction_endpoint_history_feasibility_20260930'
OUT = ROOT / 'tools_tmp/endpoint_root_cpu_authorization_20260930.json'

def sha(path):
    d = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            d.update(block)
    return d.hexdigest()

def identity(path):
    path = Path(path)
    return dict(path=str(path), bytes=path.stat().st_size, sha256=sha(path))

def check(row):
    path = Path(row['path'])
    if not path.is_absolute():
        path = ROOT / path
    assert sha(path) == row['sha256'], str(path)
    if 'bytes' in row:
        assert path.stat().st_size == row['bytes'], str(path)

assert not OUT.exists(), 'Preserve authorization'
assert len(sys.argv) == 3, 'Independent law-review path and pinned SHA required'
review_path = Path(sys.argv[1])
assert sha(review_path) == sys.argv[2]
assert sha(HERE/'model.py') == '3f807416726e6bd1e11c3f6b16e9259151dbd4b0a8232ca28f37cca01ca94126'
assert sha(HERE/'pre_cpu_freeze.json') == '9d5e3e66255a684e4941cbbfc59379f713f4ae36a7d7ce93348b592af90cb48f'
assert (HERE/'pre_cpu_freeze.json').read_bytes() == (HERE/'pre_score_freeze.json').read_bytes()
seal_path = HERE/'preparation_completion_manifest_corrected.json'
assert sha(seal_path) == '6979acdd171d29b7fa60c766b33a1ad44a3285c3e786c28e26c4d3fa1d71f52e'
seal = json.loads(seal_path.read_text())
assert seal['self_entry_excluded'] and seal['original_invalid_manifest_preserved']
assert seal['no_cohort_or_known_operator_scores'] and seal['native_GPU_calls'] == 0
assert len(seal['files']) == 21 and len(seal['external_source_files']) == 61
for row in seal['files'] + seal['external_source_files']:
    check(row)
    assert Path(row['path']).resolve() != seal_path.resolve()
freeze = json.loads((HERE/'pre_cpu_freeze.json').read_text())
assert len(freeze['sources']) == 61
for path, digest in freeze['sources'].items():
    assert sha(path) == digest, path
assert not (HERE/'results.json').exists()
assert not list(HERE.glob('*_outputs.npz'))
ready = json.loads((HERE/'preparation_ready.json').read_text())
assert ready['cohort_known_operator_scores_run'] == 0 and not ready['quality_accepted']
result = dict(
    schema='endpoint-root-single-candidate-CPU-score-authorization-v1',
    scope='Six previously saved matching native response rows and the same24 constructed operators; CPU only, one frozen candidate, no tuning.',
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    model=identity(HERE/'model.py'), pre_cpu_freeze=identity(HERE/'pre_cpu_freeze.json'),
    corrected_preparation_seal=identity(seal_path), independent_law_review=identity(review_path),
    verified_preparation_records=21, verified_source_records=61,
    root_law_findings=[
        'Current reconstruction C is formed in existing dtype before canonical float64 fit.',
        'Inclusive endpoint OLS16 shifts only source-basis beta; n1 retains current C bytes before unchanged DC application.',
        'Endpoint weights preserve constants and affine coefficients only in transported canonical coordinates.',
        'IID nominal squared-weight gain31/136 is algebra, not confidence or measured SDK covariance.',
        'Existing source cuts, eligibility, exactB invalid fallback and final DC per-pixel fallback remain unchanged.',
        'Phase mismatch, nonlinear motion/acceleration, negative-weight step overshoot and shared bias remain explicit failure risks.'
    ],
    native_GPU_authorized=False, runtime_game_changes_authorized=False,
    threshold_changes_authorized=False, additional_candidate_sweep_authorized=False,
    new_native_contexts=0, new_API_RR_recordings=0, quality_accepted=False,
    script=identity(Path(__file__)),
)
assert result['branch'] == 'ffxD-experimental-alpha'
OUT.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(authorization=identity(OUT), verified_records=82, new_native_work=0)))
