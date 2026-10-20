"""Single CPU entry point. An expected-failure mutant must fail to be killed.

From repository root:
  python -B research/astra20261020/candidates/06-moving-bottle/run.py
No Windows, AMD RR runtime, GPU build, network or optional plotting dependency.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
EVIDENCE=HERE/"evidence"


def portable_log(text):
    """Redact only machine-specific traceback prefixes, never measurements."""
    text=text.replace(str(ROOT)+os.sep, "")
    numpy_root=Path(importlib.util.find_spec("numpy").origin).parent
    text=text.replace(str(numpy_root), "<numpy>")
    return "\n".join(line.rstrip(" \t") for line in text.split("\n"))


def run_command(label, args, expected_exit=0):
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1",OMP_NUM_THREADS="2",OPENBLAS_NUM_THREADS="2",MKL_NUM_THREADS="2")
    start=time.monotonic()
    process=subprocess.run([sys.executable,"-B",*args],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    elapsed=time.monotonic()-start
    output=portable_log(process.stdout)
    log=EVIDENCE/(label+".txt");log.write_text(output)
    row={"label":label,"command":"python -B "+" ".join(args),"exit_code":process.returncode,
         "expected_exit_code":expected_exit,"expectation_met":process.returncode==expected_exit,
         "elapsed_seconds":elapsed,"log":log.relative_to(ROOT).as_posix(),
         "log_sha256":hashlib.sha256(log.read_bytes()).hexdigest(),"executor":"root CPU runner, Linux",
         "log_path_sanitization":"Repository absolute prefix removed; NumPy install prefix replaced by <numpy>; trailing whitespace stripped; metrics, exit status and assertions unchanged"}
    print(json.dumps(row),flush=True)
    if process.returncode!=expected_exit:
        print(output[-12000:],flush=True)
    return row


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--skip-baseline",action="store_true",help="During development only; final evidence uses the full run")
    args=p.parse_args()
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    base="research/astra20261020/"
    candidate=base+"candidates/06-moving-bottle/"
    jobs=[("package_validation_final",[base+"validate_package.py"],0)]
    if not args.skip_baseline:
        jobs.append(("baseline_cpu_final",[base+"run_cpu.py"],0))
    jobs += [("candidate_tests",["-m","unittest","discover","-s",candidate+"tests","-v"],0),
             ("mutant_ignore_crop",[candidate+"tests/test_tracer.py","--mutate-ignore-crop"],1),
             ("synthetic_experiments_run",[candidate+"synthetic_experiments.py","--output",candidate+"evidence/synthetic_results.json"],0),
             ("recorded_analysis_run",[candidate+"recorded_analysis.py"],0),
             ("preservation_run",[candidate+"preservation.py"],0),
             ("inventory_run",[candidate+"inventory.py"],0),
             ("visual_render_run",[candidate+"render_evidence.py"],0),
             ("package_validation_after",[base+"validate_package.py"],0)]
    runs=[]
    for label,command,expected in jobs:
        row=run_command(label,command,expected);runs.append(row)
        if not row["expectation_met"]:
            break
    summary={"schema":"astra.job06.cpu_run.v1","python":platform.python_version(),
        "numpy":importlib.metadata.version("numpy"),"platform":platform.system()+" "+platform.machine(),
        "gpu_executed":False,"baseline_skipped":args.skip_baseline,"runs":runs,
        "passed":all(row["expectation_met"] for row in runs) and len(runs)==len(jobs),
        "elapsed_seconds":sum(row["elapsed_seconds"] for row in runs)}
    (EVIDENCE/"cpu_runs.json").write_text(json.dumps(summary,indent=2,allow_nan=False)+"\n")
    raise SystemExit(0 if summary["passed"] else 1)


if __name__=="__main__":main()
