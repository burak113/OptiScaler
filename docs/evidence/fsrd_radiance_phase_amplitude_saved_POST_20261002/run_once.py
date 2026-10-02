"""Root's single guarded CPU POST; never launches native/GPU helpers."""
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
assert not (here / 'completion.json').exists() and not (here / 'result.json').exists()
authority = json.loads((here / 'ROOT_ONCE_AUTHORIZATION.json').read_text(encoding='utf-8-sig'))
assert authority['root_authorized_once'] and authority['read_only_existing_CLOSED_bytes']
assert authority['new_GPU_or_RR_dispatches'] == 0
for pin in authority['source_pins']:
    path = Path(pin['path'])
    assert path.stat().st_size == pin['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest() == pin['sha256']
guard_path = root / 'tools_tmp/fsrd_observable_radiance_SPEC_guide_full1_quality_preparation_20261002/native_resource_guard.py'
assert hashlib.sha256(guard_path.read_bytes()).hexdigest() == '47ff642dccd74c8f8830420ccb03c898dd9c6a7363121d8584c1fa366afe8225'
spec = importlib.util.spec_from_file_location('closed_guard', guard_path)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
directory = here / 'guard'
directory.mkdir()
temporary = directory / 'TEMP'
temporary.mkdir()
env = dict(os.environ, TEMP=str(temporary), TMP=str(temporary))
env.pop('PYTHONOPTIMIZE', None)
args = [sys.executable, '-B', str(here / 'worker.py')]
receipt = guard.run_guarded(args, directory, root, env, time.monotonic() + 90)
assert receipt['actual_CLOSED'] and receipt['status'] == 'completed'
assert receipt['returncode'] == 0 and not receipt['terminated_owned_child'] and 'monitor_error' not in receipt
for pin in authority['source_pins']:
    path = Path(pin['path'])
    assert path.stat().st_size == pin['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest() == pin['sha256']
result = here / 'result.json'
with (here / 'completion.json').open('x', encoding='utf-8', newline='\n') as stream:
    json.dump({'status': 'CLOSED_ACTUAL_SAVED_CPU_POST', 'driver_PID': os.getpid(), 'guard': receipt,
               'source_unchanged': True, 'new_GPU_dispatches': 0, 'new_RR_dispatches': 0,
               'result': {'path': str(result), 'bytes': result.stat().st_size,
                          'sha256': hashlib.sha256(result.read_bytes()).hexdigest()}}, stream, indent=2)
    stream.write('\n')
print('CLOSED saved CPU POST; original candidate REJECT unchanged; GPU/RR=0')
