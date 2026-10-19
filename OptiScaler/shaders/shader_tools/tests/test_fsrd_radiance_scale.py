"""Actual shared DXIL/host pass, lifetime pool, states, half/alpha roundtrip."""
from pathlib import Path
import os
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp
sys.path.insert(0,'F:/FSRD/sol_batch')
from gpu_lock import gpu_lock
out=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT','F:/FSRD/sol_batch/21-input-parity/shared-gpu'))
out.mkdir(parents=True,exist_ok=True)
os.environ['FSRD_CPP_CACHE']=str(out/'cache')
os.environ['TEMP']=os.environ['TMP']='F:/FSRD/tmp'
exe=out/'fsrd_radiance_scale.exe'
compile_cpp(Path(__file__).with_name('fsrd_radiance_scale.cpp'),exe,['d3d12.lib','dxgi.lib'],
            [ROOT/'OptiScaler',ROOT/'OptiScaler/include',ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'])
with gpu_lock(os.environ.get('FSRD_GPU_TEST_OWNER','21-input-parity')):
    result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=120)
(out/'result.log').write_text(result.stdout+result.stderr)
print(result.stdout+result.stderr)
sys.exit(result.returncode)
