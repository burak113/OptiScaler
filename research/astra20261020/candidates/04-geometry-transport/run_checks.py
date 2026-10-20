"""One command for the meaningful CPU checks. Does not invoke GPU tools."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import numpy as np

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[3]


def run(out,quick=False):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='2',
             OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2')
    jobs=[('candidate_tests',[sys.executable,'-B','-W','error','-m','unittest','discover',
                             '-s',str(HERE/'tests'),'-p','test_*.py','-v'])]
    if not quick:
        jobs.extend([
            ('fixture_diagnostics',[sys.executable,'-B',str(HERE/'fixture_diagnostics.py'),'--out',str(out)]),
            ('phase_and_temporal_experiments',[sys.executable,'-B',str(HERE/'experiments.py'),'--out',str(out)]),
            ('gpu_fixture_export_CPU_only',[sys.executable,'-B',str(HERE/'generate_gpu_fixtures.py'),
                                           '--out',str(out/'gpu_inputs')]),
            ('transport_metrics',[sys.executable,'-B',str(HERE/'transport_experiment.py'),
                                  '--output',str(out),'--executor','root Linux CPU']),
        ])
    results=[]
    for name,command in jobs:
        start=time.perf_counter()
        with (out/f'{name}.log').open('w') as log:
            process=subprocess.run(command,cwd=REPO,env=env,stdout=log,stderr=subprocess.STDOUT)
        normalized=['python' if i==0 else s.replace(str(REPO)+os.sep,'') for i,s in enumerate(command)]
        item={'name':name,'command':normalized,'exit_code':process.returncode,
              'elapsed_seconds':time.perf_counter()-start,'executor':'root Linux CPU',
              'log_sha256':hashlib.sha256((out/f'{name}.log').read_bytes()).hexdigest()}
        results.append(item);print(json.dumps(item),flush=True)
        if process.returncode:break
    source_files=sorted([p for p in HERE.rglob('*') if p.is_file() and
                        p.suffix in ('.py','.hlsl') and 'evidence' not in p.parts])
    source_hashes={str(p.relative_to(HERE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    execution={'python':platform.python_version(),'numpy':np.__version__,
               'platform':platform.system()+' '+platform.machine(),
               'gpu_executed':False,'quick':quick,'commands':results,'source_hashes':source_hashes}
    (out/'execution.json').write_text(json.dumps(execution,indent=2,allow_nan=False)+'\n')
    return max(x['exit_code'] for x in results)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=HERE/'evidence')
    parser.add_argument('--quick',action='store_true');args=parser.parse_args()
    raise SystemExit(run(args.out,args.quick))
