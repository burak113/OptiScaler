"""One explicit call-entry/egress-gap SIM; no real query or executable."""
from pathlib import Path
import json
from query_accounting import derive
HERE=Path(__file__).resolve().parent
source=HERE/'SIMULATED_CPU/complete6/stdout.log'
lines=source.read_bytes().splitlines(keepends=True)
folder=HERE/'SIMULATED_pending_entry';folder.mkdir(exist_ok=False)
# boot, metadata, create_start, create_return, firstquery_start only.
(folder/'stdout.log').write_bytes(b''.join(lines[:5]));(folder/'stderr.log').write_bytes(b'')
result=derive(folder,dict(child_pid=123,status='failed_or_terminated',returncode=1))
assert result['counts_lower_bound']['created']==1
assert result['counts_lower_bound']['query_entry']==1
assert result['counts_lower_bound']['query_returned']==result['counts_lower_bound']['query_ok']==0
assert result['pending_entry_not_completed_API']=='query'and result['totals_unknown']and not result['exact_returned_totals']
with(HERE/'CPU_pending_entry_check.json').open('x',encoding='utf-8',newline='\n')as f:
 json.dump(dict(SIMULATED=True,passed=True,actual_queries_GPU_native=0,result=result),f,indent=2);f.write('\n')
print('SIMULATED pending-entry gap passed; actual query0')
