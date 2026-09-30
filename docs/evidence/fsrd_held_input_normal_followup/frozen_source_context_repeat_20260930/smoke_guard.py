from pathlib import Path
import json, sys
from native_resource_guard import run_guarded, available_memory

folder = Path(__file__).resolve().parent/'guard_smoke'
folder.mkdir()
result = run_guarded([sys.executable, '-c', 'import time; print("guard smoke"); time.sleep(.6)'], folder, timeout=10)
assert result['status']=='completed' and result['returncode']==0
assert result['samples']>0 and result['peak_observed_working_set_bytes']>0
assert not result['terminated_owned_child'] and (folder/'stdout.log').read_text().strip()=='guard smoke'
print(json.dumps(result))
