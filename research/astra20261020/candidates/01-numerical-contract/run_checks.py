"""One CPU acceptance command, with exact commands, durations and exit statuses.

Frozen package checks are rerun to prove the candidate did not change its base.
No DLL/GPU driver or compiler is launched. Evidence is written only here or to
the explicitly selected --output directory.
"""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
PACKAGE=HERE.parents[1]
REPO=PACKAGE.parents[1]
REL=HERE.relative_to(REPO).as_posix()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=HERE/'evidence')
    args=parser.parse_args();args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(HERE),OMP_NUM_THREADS='2',
             OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2')
    jobs=[('package',['python','-B','research/astra20261020/validate_package.py'],0),
          ('baseline',['python','-B','research/astra20261020/run_cpu.py'],0),
          ('artifact',['python','-B','OptiScaler/shaders/shader_tools/tests/test_fsrd_shader_artifact_contract.py','--skip-compile'],0),
          ('candidate_tests',['python','-B','-m','unittest','discover','-s',REL+'/tests','-v'],0),
          ('adversary_controls',['python','-B',REL+'/adversary_controls.py'],0),
          ('overlap_recovery',['python','-B',REL+'/adversary_controls.py','--recover-overlap'],0),
          ('inventory',['python','-B',REL+'/inventory.py','--output',str(args.output)],0),
          ('calibration',['python','-B',REL+'/calibrate.py','--output',str(args.output)],0),
          ('gpu_inputs',['python','-B',REL+'/gpu_inputs.py','--output',str(args.output)],0),
          ('adapter_patch',['python','-B',REL+'/verify_adapter.py'],0),
          ('known_bad_quality_gate',['python','-B','research/astra20261020/portable/colour/compare.py','--quality-gate'],1)]
    jobs.extend(('mutant_'+name,['python','-B',REL+'/mutants.py',name],1)
                for name in ('wrong_uv','nearest','old_normal','missing_high','premature_rounding'))
    records=[];overall=True
    for name,command,expected in jobs:
        start=time.monotonic()
        result=subprocess.run(command,cwd=REPO,env=env,capture_output=True,text=True)
        elapsed=time.monotonic()-start
        log=result.stdout+result.stderr
        # Keep delivery relocatable; the user's extraction path is not evidence.
        log=log.replace(str(REPO),'<repo>')
        (args.output/(name+'.log')).write_text(log)
        output_label=args.output.relative_to(REPO).as_posix() if args.output.is_relative_to(REPO) else str(args.output)
        display=[(output_label if v==str(args.output) else v) for v in command]
        record={'name':name,'command':display,'working_directory':'repository root',
                'exit_code':result.returncode,'expected_exit_code':expected,
                'elapsed_seconds':elapsed,'executor':'root local Linux CPU',
                'log':name+'.log','passed':result.returncode==expected}
        records.append(record);overall &= record['passed']
        (args.output/'run_records.json').write_text(json.dumps(records,indent=2,allow_nan=False)+'\n')
        print(f"{name}: exit={result.returncode} expected={expected} elapsed={elapsed:.3f}s",flush=True)
        if not record['passed']:
            print(log[-5000:],flush=True)
            break
    return 0 if overall else 1


if __name__=='__main__':raise SystemExit(main())
