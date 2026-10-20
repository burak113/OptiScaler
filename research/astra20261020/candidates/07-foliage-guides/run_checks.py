"""One-command CPU acceptance and reproduction of the job07 research bundle.

No GPU/runtime/DLL is invoked. Expected-failing controls count as detected only
when their intended assertion/verdict is present. Rerun output stays separate
from the delivered evidence and immutable BASE masks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import numpy as np

HERE=Path(__file__).resolve().parent
PACKAGE=HERE.parent.parent
REPO=PACKAGE.parent.parent


def rel(path):
    path=Path(path).resolve()
    return path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else path.name


def source_hashes():
    paths=list((HERE/'src').glob('*.py'))+[HERE/'run_benchmark.py', HERE/'analyze_captures.py',
        HERE/'experiments/protocol.json',HERE/'run_checks.py']
    paths+=list((HERE/'tests').glob('test_*.py'))
    return {p.relative_to(HERE).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=HERE/'evidence/reproduction')
    parser.add_argument('--skip-benchmark',action='store_true',help='Run contracts/recorded diagnostics; do not claim full-sweep reproduction from this mode.')
    parser.add_argument('--executor',default='local CPU rerun')
    args=parser.parse_args()
    output=args.output_dir.resolve()
    if output==HERE/'evidence' or not output.is_relative_to(HERE):
        parser.error('Choose a separate output directory inside this candidate folder.')
    output.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2')
    before=source_hashes()
    runs=[]
    t_all=time.monotonic()

    def run(name,argv,cwd=REPO,expected=0,marker=None,json_verdict=None):
        started=time.monotonic()
        process=subprocess.run(argv,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (output/(name+'.txt')).write_text(process.stdout)
        good=process.returncode==expected and (marker is None or marker in process.stdout)
        if json_verdict is not None:
            try: good=good and json_verdict(json.loads(process.stdout))
            except (ValueError,KeyError,TypeError): good=False
        command=' '.join('python' if a==sys.executable else rel(a) if a.startswith(str(REPO)) else a for a in argv)
        runs.append({'name':name,'command':command,'cwd':rel(cwd),'exit_code':process.returncode,
                     'expected_exit_code':expected,'expected_marker':marker,'elapsed_seconds':time.monotonic()-started,
                     'pass':bool(good),'log':rel(output/(name+'.txt')),'executor':args.executor})
        print(name, 'PASS' if good else 'FAIL', 'exit',process.returncode,flush=True)
        if not good:
            print(process.stdout[-4000:],flush=True)
            raise RuntimeError(name+' failed; original exit/trace preserved')

    failure=None
    try:
        run('frozen_package',[sys.executable,str(PACKAGE/'validate_package.py')])
        run('frozen_cpu_suites',[sys.executable,str(PACKAGE/'run_cpu.py')])
        run('candidate_and_review_contracts',[sys.executable,'-B','-m','unittest','discover','-s',str(HERE/'tests'),'-v'])
        run('known_bad_colour_gate',[sys.executable,'-B','compare.py','--quality-gate'],cwd=PACKAGE/'portable/colour',expected=1,
            json_verdict=lambda x:x['edges']['verdict']=='rejected_halo_regression' and x['edges']['worse_cases']>0)
        run('blind_detail_mutant',[sys.executable,str(HERE/'review/blind_calibration.py'),'--mutant-ignore-detail','--output',str(output/'blind_mutant.json')],
            expected=1,marker='MUTANT CAUGHT: noise-only scoring accepts destroyed facade detail')
        run('crop_clamp_mutant',[sys.executable,str(HERE/'tests/test_candidate_contract.py'),'--mutant-clamp-history'],
            expected=1,marker='FAILED')
        # Copies are checked against source arrays by the read-only analyzer;
        # original mask files are never recomputed from candidate values.
        shutil.copytree(HERE/'evidence/base_masks',output/'base_masks',dirs_exist_ok=True)
        run('captured_diagnostics',[sys.executable,str(HERE/'analyze_captures.py'),'--with-candidate','--executor',args.executor,'--output-dir',str(output)])
        if not args.skip_benchmark:
            run('frozen_synthetic_sweep',[sys.executable,str(HERE/'run_benchmark.py'),'--executor',args.executor,'--output',str(output/'synthetic_benchmark.json')])
            expected=json.loads((HERE/'evidence/synthetic_benchmark.json').read_text())
            actual=json.loads((output/'synthetic_benchmark.json').read_text())
            for key in ('protocol_sha256','source_sha256','case_count','decoder_calibration','identifiability_collision','cases','input_groups','summary','summary_unique_inputs'):
                if expected[key]!=actual[key]:
                    raise AssertionError('Frozen experiment reproduction differs in '+key)
            runs.append({'name':'full_sweep_matches_recorded_evidence','pass':True,'scope':'Exact cases and numeric summaries; executor/timing may differ','executor':args.executor})
        if source_hashes()!=before:
            raise AssertionError('Sources changed during execution; this run does not attest a single revision')
    except Exception as exc:
        failure=str(exc)
    receipt={'schema':'job07.cpu_verification.v1','executor':args.executor,'python':sys.version.split()[0],
             'numpy':np.__version__,'gpu_executed':False,'full_benchmark_executed':not args.skip_benchmark,
             'source_sha256_before':before,'source_sha256_after':source_hashes(),
             'elapsed_seconds':time.monotonic()-t_all,'runs':runs,'pass':failure is None,'failure':failure}
    (output/'verification.json').write_text(json.dumps(receipt,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'pass':receipt['pass'],'full_benchmark_executed':not args.skip_benchmark,
                      'elapsed_seconds':receipt['elapsed_seconds'],'receipt':rel(output/'verification.json')},indent=2),flush=True)
    return 0 if failure is None else 1


if __name__=='__main__':
    raise SystemExit(main())
