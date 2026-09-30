"""Exercise guard stop branches using only harmless owned Python children."""
from pathlib import Path
import json, sys
from native_resource_guard import run_guarded, available_memory

root=Path(__file__).resolve().parent/'guard_stop_checks'
if root.exists(): raise ValueError('Preserve guard stop checks')
root.mkdir(); reports=[]
args=[sys.executable,'-c','import time; time.sleep(10)']
for name,options,reason in (
    ('working_set',dict(maximum_working_set=1),'maximum_child_working_set'),
    ('timeout',dict(timeout=.3),'timeout'),
    ('not_launched',dict(minimum_available_memory=available_memory()[1]+1),None)):
    folder=root/name;folder.mkdir();result=run_guarded(args,folder,**options)
    if name=='not_launched':
        assert result['status']=='not_launched_low_available_memory' and result['child_pid'] is None
        assert not result['terminated_owned_child']
    else:
        assert result['status']=='failed_or_terminated' and result['terminated_owned_child']
        assert result['termination_reason']==reason and result['returncode'] is not None
    reports.append(dict(name=name,passed=True,**result))
(root/'results.json').write_text(json.dumps(dict(all_passed=True,checks=reports),indent=2)+'\n')
print('guard stop checks:3 passed; only owned harmless Python children')
