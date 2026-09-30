"""Retry the same instrumented binary with persistent logs and a longer watchdog."""
from pathlib import Path
import hashlib,json,re,subprocess,time
ROOT=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    folder=Path(__file__).resolve().parent;out=folder/'evidence'
    if out.exists():raise ValueError('Preserve retry')
    out.mkdir();prior=ROOT/'tools_tmp/gpu_based_validation_20260930/evidence'
    previous=json.loads((prior/'results.json').read_text())
    if previous['status']!='process_exception' or '300 seconds' not in previous['error']:raise ValueError('Unexpected prior outcome')
    exe=prior/'gpu_validation_runner.exe'
    if sha(exe)!=previous['runner_sha256']:raise ValueError('Instrumented binary changed')
    rows=(prior/'job.txt').read_text().splitlines();job=out/'job.txt'
    job.write_text('\n'.join(rows[:-1]+[f'"{(out/"diffuse.bin").as_posix()}" "{(out/"specular.bin").as_posix()}"'])+'\n')
    (out/'frame_controls.txt').write_bytes((prior/'frame_controls.txt').read_bytes())
    result=dict(previous_attempt_path=str(prior/'results.json'),previous_attempt_sha256=sha(prior/'results.json'),
        schema='same-instrumented-binary-gpu-validation-watchdog-retry-v1',status='running',quality_accepted=False,
        runner_path=str(exe),runner_sha256=sha(exe),source_sha256=previous['generated_source_sha256'],
        script_sha256=sha(__file__),job_sha256=sha(job),source_input_identities=previous['source_input_identities'],
        provider_sha256=previous['provider_sha256'],native_dispatches=0,completed_contexts=0,
        previous_complete_dispatches=0,previous_context_creation_completion_unknown=True,
        watchdog_seconds=900,changed='Only watchdog300->900 and persistent stdout/stderr files; same executable/job semantics64frames/tuning1',
        limitations=['Instrumentation changes shader execution; no same-original-binary repeatability or image-quality claim.','Watchdog expiration is not a detected validation error.','Previous timed-out capture_output attempt did not retain partial stdout/stderr.'])
    def save():(out/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    start=time.monotonic();save()
    with (out/'stdout.log').open('w',encoding='utf-8') as stdout,(out/'stderr.log').open('w',encoding='utf-8') as stderr:
        p=subprocess.Popen([str(exe),str(job)],stdout=stdout,stderr=stderr)
        result['process_id']=p.pid;save()
        try:p.wait(timeout=900)
        except subprocess.TimeoutExpired:
            p.kill();p.wait();result['status']='watchdog_timeout_no_quality_result'
        else:result['status']='process_finished_pending_validation'
    log=(out/'stdout.log').read_text()+(out/'stderr.log').read_text();(out/'runner.log').write_text(log,encoding='utf-8')
    result.update(returncode=p.returncode,elapsed_seconds=time.monotonic()-start,
        log_sha256=sha(out/'runner.log'),gpu_based_validation_reported='gpu_based_validation=1' in log)
    matches=re.search(r'dispatches=(\d+) validation_errors=(\d+) validation_warnings=(\d+) sdk_errors=(\d+) sdk_warnings=(\d+)',log)
    if matches:
        result['native_dispatches']=int(matches[1]);result['completed_contexts']=int(matches[1]=='64')
        result['validation_counts']={k:int(v) for k,v in zip(('d3d_errors','d3d_warnings','sdk_errors','sdk_warnings'),matches.groups()[1:])}
        result['status']='completed_diagnostic_not_solution' if p.returncode==0 else 'native_validation_failed'
    result['output_identities']={n:dict(size=(out/n).stat().st_size,sha256=sha(out/n)) for n in ('diffuse.bin','specular.bin','dispatch_controls.bin') if (out/n).exists()}
    result['applied_controls_equal_reference']=(out/'dispatch_controls.bin').exists() and sha(out/'dispatch_controls.bin')==previous.get('reference_applied_controls_sha256','7e0b704eea9b7035dddab1517f4dd9bd4ee2a7e0d6fb04e90f4d8ec4a2b5d3f0')
    result['runner_unchanged']=sha(exe)==result['runner_sha256'];save()
    print(json.dumps({k:result.get(k) for k in ('status','native_dispatches','validation_counts','elapsed_seconds')}),flush=True)
if __name__=='__main__':main()
