"""Run the production DX12 Magnifier with deferred WARP execution and explicit hook adapters."""
from pathlib import Path
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import visual_studio


def run():
    here = Path(__file__).resolve().parent
    root = here.parents[3]
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', root / 'tools_tmp/magnifier_lifetime'))
    output = output.resolve() / 'magnifier'
    stubs = output / 'stubs'
    support = (here / 'dx12_shader_test_support.h').as_posix()
    for name in ('pch.h', 'SysUtils.h', 'Config.h', 'State.h',
                 'gpu_time/GpuTime_Dx12.h', 'resource_tracking/ResTrack_dx12.h',
                 'menu/menu_overlay_base.h', 'menu/input/input_system.h'):
        path = stubs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'#pragma once\n#include "{support}"\n', encoding='utf-8')
    executable = output / 'fsrd_magnifier_lifetime_test.exe'
    command = executable.with_suffix('.build.cmd')
    vcvars = visual_studio() / 'VC/Auxiliary/Build/vcvars64.bat'
    command.write_text(
        f'@call "{vcvars}" >nul\n@if errorlevel 1 exit /b %errorlevel%\n'
        f'@cl /nologo /std:c++20 /EHsc /O2 /I"{stubs}" '
        f'/I"{root / "OptiScaler/include"}" /I"{root / "OptiScaler"}" '
        f'"{here / "fsrd_magnifier_lifetime_test.cpp"}" '
        f'/Fe:"{executable}" /Fo:"{executable.with_suffix(".obj")}" '
        '/link d3d12.lib dxgi.lib\n', encoding='utf-8')
    subprocess.run(f'cmd /d /s /c ""{command}""', cwd=output, check=True, timeout=120)
    subprocess.run([str(executable)], check=True, timeout=60)


if __name__ == '__main__':
    run()
