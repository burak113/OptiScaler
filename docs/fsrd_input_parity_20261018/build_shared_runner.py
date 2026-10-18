"""Compile the checked signed-RR adapter against the shared production scale pass."""
from pathlib import Path
import os
import sys
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'OptiScaler/shaders/shader_tools'))
from fsrd_toolchain import compile_cpp
out=Path('F:/FSRD/sol_batch/21-input-parity/shared-real')
out.mkdir(parents=True,exist_ok=True)
os.environ['TEMP']=os.environ['TMP']='F:/FSRD/tmp'
os.environ['FSRD_CPP_CACHE']=str(out/'cache')
compile_cpp(Path(__file__).with_name('signed_replay_runner.cpp'),out/'shared_rr.exe',
            ['d3d12.lib','dxgi.lib'],[root/'OptiScaler',root/'OptiScaler/include',
            root/'external/FidelityFX-SDK/ffx-api/include/ffx_api'])
print(out/'shared_rr.exe')
