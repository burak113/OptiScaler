"""Run once the frozen V2 CPU analyzer and retain actual console bytes."""
from pathlib import Path
import datetime,hashlib,json,subprocess,sys
HERE=Path(__file__).resolve().parent
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def main():
    freeze=json.loads((HERE/'remaining_v2_pre_native_freeze.json').read_text());p=HERE/'analyze_combined_v2.py'
    expected=next(r for r in freeze['files']if Path(r['path'])==p);assert identity(p)==expected
    command=[sys.executable,str(p)];started=datetime.datetime.now(datetime.timezone.utc).isoformat()
    r=subprocess.run(command,cwd=HERE,capture_output=True,timeout=240,check=False)
    for name,data in(('combined_CPU_analysis.stdout.bin',r.stdout),('combined_CPU_analysis.stderr.bin',r.stderr)):
        with(HERE/name).open('xb')as f:f.write(data)
    record={'schema':'frozen-combined-V2-CPU-analysis-execution-v1','command':command,'cwd':str(HERE),'started_UTC':started,
        'finished_UTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'returncode':r.returncode,'frozen_analysis':identity(p),
        'stdout':identity(HERE/'combined_CPU_analysis.stdout.bin'),'stderr':identity(HERE/'combined_CPU_analysis.stderr.bin'),'new_native_contexts':0,'new_API_RR_recordings':0}
    with(HERE/'combined_CPU_analysis_command.json').open('x',encoding='utf-8',newline='\n')as f:json.dump(record,f,indent=2,allow_nan=False);f.write('\n')
    print(r.stdout.decode(errors='replace'),end='');assert r.returncode==0,r.stderr.decode(errors='replace')
if __name__=='__main__':main()
