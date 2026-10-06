"""Portable fence-state and WARP queue/reset integration contracts."""
from pathlib import Path
import os, subprocess, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp


def run():
    here=Path(__file__).resolve().parent
    output=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT',str(here.parents[3]/'tools_tmp/alpha_lifetime'))).resolve()
    output.mkdir(parents=True,exist_ok=True)
    for name in ('fsrd_additive_fence_state_test','fsrd_additive_fence_test'):
        executable=output/(name+'.exe')
        compile_cpp(here/(name+'.cpp'),executable,('d3d12.lib','dxgi.lib'))
        subprocess.run([str(executable)],check=True)


if __name__=='__main__': run()
