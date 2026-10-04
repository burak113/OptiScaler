from pathlib import Path
import os, subprocess, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

def run():
    root=Path(__file__).resolve().parents[4]
    out=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT',root/'tools_tmp/fsrd_menu_20261004/tests'))/'signal_policy'
    exe=out/'fsrd_signal_policy_test.exe'
    compile_cpp(Path(__file__).with_name('fsrd_signal_policy_test.cpp'),exe)
    subprocess.run([str(exe)],check=True)

if __name__=='__main__': run()
