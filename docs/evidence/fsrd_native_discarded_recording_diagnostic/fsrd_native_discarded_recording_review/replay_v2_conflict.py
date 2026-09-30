"""CPU only: replay preserved SIMULATED conflict against the pinned V2 helper."""
from pathlib import Path
import hashlib,importlib.util,json
P=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/tools_tmp/fsrd_native_discarded_recording_diagnostic_20260930/native_work_accounting.py')
assert hashlib.sha256(P.read_bytes()).hexdigest()=='a5c73e7db0a9e33cb8fc9e70c6a8fe651e83682544b7414d9fa711cda6c4446c'
s=importlib.util.spec_from_file_location('pinned_accounting_v2',P)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
r=m.derive(Path(__file__).resolve().parent/'SIMULATED_V2_conflicting_accounting_unit_input',
           {'child_pid':1,'status':'completed','returncode':0},{'tag':'SIMULATED_conflicting_indices'})
assert r['successful_API_RR_recordings_confirmed']==65
assert r['final_stdout_counters']['successful_API_RR_recordings']==64
assert r['evidence_disagreements'] and not r['incomplete_child_native_work_may_exceed_confirmed_lower_bounds']
print(json.dumps({'SIMULATED_NOT_NATIVE_EVIDENCE':True,'verified_v2_conflict':True,'own_GPU_native_calls':0}))
