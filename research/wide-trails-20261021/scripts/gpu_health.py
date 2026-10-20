import sys,subprocess,json
from pathlib import Path
sys.path[:0]=['E:/FSRD/rrlab','F:/FSRD/sol_batch']
from gpu_lock import gpu_lock
O=Path(__file__).parent;fixture=Path('F:/FSRD/sol_batch/31-material-trails/tests/colour-final')
with gpu_lock('32-small-health'):
 r=subprocess.run([str(fixture/'turn_material.exe'),'65','67',str(fixture/'boundary/inputs'),str(O/'health-gpu'),'1','1','--filter-only'],capture_output=True,text=True,timeout=30)
(O/'health-small.log').write_text(r.stdout+r.stderr);r.check_returncode()
assert 'debug_errors=0 debug_warnings=0' in r.stdout
print(r.stdout,flush=True)
from rrlab.captures import Capture
from rrlab import runner
result=runner.run(Capture('c37d'),'d16+hook:E:/FSRD/sol_batch/31-material-trails/gpu_old_hook.py+rep32',frames=range(4),force=True,owner='32-small-AMD-health')
import numpy as np
assert np.isfinite(result.diffuse).all() and np.isfinite(result.specular).all()
(O/'health-provider.json').write_text(json.dumps(result.meta,indent=2));print('PASS tiny production shader and four fresh signed AMD RR frames',flush=True)
