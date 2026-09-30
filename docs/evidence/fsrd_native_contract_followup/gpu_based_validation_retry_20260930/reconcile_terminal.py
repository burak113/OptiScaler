"""Reconcile stale running metadata after handle loss; do not infer exit cause."""
from pathlib import Path
import hashlib,json,subprocess
folder=Path(__file__).resolve().parent;out=folder/'evidence';target=out/'terminal_reconciliation.json'
if target.exists():raise ValueError('Preserve reconciliation')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
raw=out/'results.json';before=sha(raw);record=json.loads(raw.read_text())
probe=subprocess.run(['powershell','-NoProfile','-Command',"Get-Process | Where-Object ProcessName -eq 'gpu_validation_runner' | Select-Object Id,Path | ConvertTo-Json"],capture_output=True,text=True,timeout=20)
if probe.returncode or probe.stdout.strip():raise ValueError('Validation process still present or inspection failed')
logs={p.name:dict(size=p.stat().st_size,sha256=sha(p)) for p in out.glob('*.log')}
outputs={p.name:dict(size=p.stat().st_size,sha256=sha(p)) for p in out.glob('*.bin')}
stdout=(out/'stdout.log').read_text()
result=dict(schema='gpu-validation-stale-state-terminal-reconciliation-v1',quality_accepted=False,status='process_absent_without_validation_result',
    original_results_sha256=before,original_results_preserved=True,script_sha256=sha(Path(__file__)),
    recorded_child_pid=record['process_id'],process_probe_returncode=probe.returncode,process_probe_stdout=probe.stdout,
    tool_handles_missing=[4513,89719],created_context_confirmed_by_post_create_version_line='version_query_result=6 requested_api=4202496' in stdout,
    completed_native_dispatches=0,completed_native_contexts=0,log_identities=logs,output_identities=outputs,
    last_observed_free_physical_memory_kib=448528,last_observed_total_physical_memory_kib=16697804,
    stop_requested=True,stop_command_completion_verified=False,external_stop_file_exists=(out/'external_stop.json').exists(),
    native_exit_code_unknown=True,exit_cause_unknown=True,
    limitations=['All output/controls files are empty and no final native validation summary is retained.','Memory pressure was observed, but the actual exit cause/Stop-Process completion is unproven.','Do not report validation passed or detected SDK/D3D failure.','Do not restart this memory-heavy instrumented helper merely because metadata still says running.'])
target.write_text(json.dumps(result,indent=2)+'\n')
if sha(raw)!=before:raise ValueError('Original running snapshot changed')
print(result['status'])
