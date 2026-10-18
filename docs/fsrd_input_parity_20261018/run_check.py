import os
import subprocess
import sys
import time
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
root=Path(__file__).resolve().parents[2]
name=sys.argv[1]
gpu=len(sys.argv)>2 and sys.argv[2]=='gpu'
run_id=str(time.time_ns())
out=Path('F:/FSRD/sol_batch/21-input-parity/tests')/name/run_id
out.mkdir(parents=True,exist_ok=True)
os.environ.update(TEMP='F:/FSRD/tmp',TMP='F:/FSRD/tmp',PYTHONPATH='F:/FSRD/tmp/pyshim',
    FSRD_GPU_TEST_OUTPUT=str(out),FSRD_CPP_CACHE=str(out/'cache'),
    FSRD_NRD_RR_REPORT=str(Path('E:/FSRD/sol_batch/21-input-parity/tests')/name/run_id),
    OPENBLAS_NUM_THREADS='2',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
script=root/'OptiScaler/shaders/shader_tools/tests'/name
args=[sys.executable,str(script)]+sys.argv[3:]
def run():
    t=time.perf_counter()
    p=subprocess.run(args,cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace',
                     creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS|subprocess.CREATE_NO_WINDOW,timeout=600)
    log=p.stdout+p.stderr
    (out/'wrapper.log').write_text(log,encoding='utf-8')
    (Path('E:/FSRD/sol_batch/21-input-parity')/(name+'.log')).write_text(log,encoding='utf-8')
    print(name,'EXIT',p.returncode,'SECONDS',round(time.perf_counter()-t,3),flush=True)
    print(log[-9000:])
    return p.returncode
if gpu:
    sys.path.insert(0,'F:/FSRD/sol_batch')
    from gpu_lock import gpu_lock
    with gpu_lock('21-input-parity'):
        result=run()
else:
    result=run()
sys.exit(result)
