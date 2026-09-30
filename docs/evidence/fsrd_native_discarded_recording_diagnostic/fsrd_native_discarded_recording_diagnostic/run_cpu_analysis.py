"""Run the frozen descriptive analysis once; no native/GPU executable is invoked."""
from pathlib import Path
import datetime,hashlib,json,subprocess,sys
HERE=Path(__file__).resolve().parent
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def main():
    prep=json.loads((HERE/'preparation_completion_manifest_v3.json').read_text())
    expected=next(r for r in prep['files']if Path(r['path'])==HERE/'analyze.py')
    assert identity(HERE/'analyze.py')==expected
    command=[sys.executable,str(HERE/'analyze.py')]
    started=datetime.datetime.now(datetime.timezone.utc).isoformat()
    result=subprocess.run(command,cwd=HERE,capture_output=True,timeout=240,check=False)
    for name,data in(('CPU_analysis.stdout.bin',result.stdout),('CPU_analysis.stderr.bin',result.stderr)):
        with(HERE/name).open('xb')as f:f.write(data)
    save(HERE/'CPU_analysis_command.json',{'schema':'frozen-CPU-analysis-execution-v1','command':command,'cwd':str(HERE),
        'started_UTC':started,'finished_UTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'returncode':result.returncode,
        'frozen_analysis':identity(HERE/'analyze.py'),'stdout':identity(HERE/'CPU_analysis.stdout.bin'),'stderr':identity(HERE/'CPU_analysis.stderr.bin'),
        'new_native_contexts':0,'new_API_RR_recordings':0,'new_queued_RR_dispatches':0})
    print(result.stdout.decode(errors='replace'),end='')
    assert result.returncode==0,result.stderr.decode(errors='replace')
if __name__=='__main__':main()
