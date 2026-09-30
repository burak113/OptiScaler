"""Compile only the owned isolated H2 runner; never execute it."""
from pathlib import Path
import os,sys
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha');HERE=Path(__file__).resolve().parent
os.environ['TEMP']=str(ROOT/'tools_tmp/native_compile_temp_20260930');os.environ['TMP']=os.environ['TEMP']
sys.path.insert(0,str(ROOT/'OptiScaler/shaders/shader_tools'))
from fsrd_toolchain import compile_cpp
compile_cpp(HERE/'fsrd_rr_discard.cpp',HERE/'fsrd_rr_discard.exe',('d3d12.lib','dxgi.lib'))
