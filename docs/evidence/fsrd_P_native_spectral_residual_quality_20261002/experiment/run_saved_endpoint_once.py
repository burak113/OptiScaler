"""Root once-only guarded fixed P/native spectral residual recovery endpoint."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import sys
import time

if sys.flags.optimize or not __debug__:
    raise RuntimeError('optimized Python prohibited')
here = Path(__file__).resolve().parent
root = here.parent.parent
out = here / 'endpoint_once'
assert not out.exists(), 'fixed endpoint already attempted; no retry'
authority = json.loads((here / 'ROOT_ONCE_AUTHORIZATION.json').read_text(encoding='utf-8-sig'))
assert authority['root_authorized_once'] and authority['fixed_operator_no_sweep']
assert authority['new_GPU_or_RR_dispatches'] == 0 and authority['frame'] == 63
for pin in authority['source_pins']:
    path = Path(pin['path'])
    assert path.stat().st_size == pin['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest() == pin['sha256']
guard_path = root / 'tools_tmp/fsrd_observable_radiance_SPEC_guide_full1_quality_preparation_20261002/native_resource_guard.py'
assert hashlib.sha256(guard_path.read_bytes()).hexdigest() == '47ff642dccd74c8f8830420ccb03c898dd9c6a7363121d8584c1fa366afe8225'
spec = importlib.util.spec_from_file_location('fixed_owned_guard', guard_path)
guard_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard_module)
out.mkdir()
guard_directory = out / 'guard'
guard_directory.mkdir()
temporary = guard_directory / 'TEMP'
temporary.mkdir()
env = dict(os.environ, TEMP=str(temporary), TMP=str(temporary))
env.pop('PYTHONOPTIMIZE', None)
args = [sys.executable, '-B', str(here / 'saved_endpoint_once.py')]
guard = guard_module.run_guarded(args, guard_directory, root, env, time.monotonic() + 240)
assert guard['actual_CLOSED'] and guard['status'] == 'completed'
assert guard['returncode'] == 0 and not guard['terminated_owned_child'] and 'monitor_error' not in guard
assert json.loads((guard_directory / 'resource_guard.json').read_text(encoding='utf-8')) == guard
result = out / 'result.json'
value = json.loads(result.read_text(encoding='utf-8'))
assert value['PID'] == guard['child_pid']
for pin in authority['source_pins']:
    path = Path(pin['path'])
    assert path.stat().st_size == pin['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest() == pin['sha256']
with (out / 'completion.json').open('x', encoding='utf-8', newline='\n') as stream:
    json.dump({'status': 'CLOSED_ACTUAL_FIXED_CPU_ENDPOINT', 'quality_decision': value['status'],
               'driver_PID': os.getpid(), 'guard': guard, 'source_unchanged': True,
               'new_GPU_dispatches': 0, 'new_RR_dispatches': 0,
               'result': {'path': str(result), 'bytes': result.stat().st_size,
                          'sha256': hashlib.sha256(result.read_bytes()).hexdigest()}}, stream, indent=2)
    stream.write('\n')
print(value['status'])
