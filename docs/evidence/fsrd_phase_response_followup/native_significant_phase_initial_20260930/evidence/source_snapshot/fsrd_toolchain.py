"""Windows tool discovery shared by the FSRD shader/build/test entry points."""
from pathlib import Path
import os
import shutil
import subprocess


def executable(value, name):
    path = Path(value).expanduser() if value else None
    if path and path.is_file():
        return path.resolve()
    found = shutil.which(value or name)
    if found:
        return Path(found).resolve()
    raise RuntimeError(f"Cannot find {name}: {value or 'not on PATH'}")


def visual_studio():
    override = os.environ.get('FSRD_VS_ROOT')
    if override:
        root = Path(override).resolve()
    else:
        program_files = os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
        locator = Path(program_files)/'Microsoft Visual Studio/Installer/vswhere.exe'
        if not locator.is_file():
            raise RuntimeError('Install Visual Studio C++ tools or set FSRD_VS_ROOT.')
        result = subprocess.check_output([
            str(locator), '-latest', '-products', '*', '-requires',
            'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
            '-property', 'installationPath'], text=True).strip()
        if not result:
            raise RuntimeError('No Visual Studio installation with x64 C++ tools found.')
        root = Path(result)
    if not (root/'VC/Auxiliary/Build/vcvars64.bat').is_file():
        raise RuntimeError(f'Missing x64 MSVC environment under {root}')
    return root


def dxc(explicit=None):
    override = explicit or os.environ.get('FSRD_DXC')
    if override or shutil.which('dxc.exe'):
        return executable(override, 'dxc.exe')
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                       r'SOFTWARE\Microsoft\Windows Kits\Installed Roots', 0,
                       winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
        sdk = Path(winreg.QueryValueEx(key, 'KitsRoot10')[0])
    candidates = list((sdk/'bin').glob('10.*/x64/dxc.exe'))
    if not candidates:
        raise RuntimeError('Install Windows SDK DXC or set FSRD_DXC.')
    return max(candidates, key=lambda p: tuple(map(int, p.parents[1].name.split('.'))))


def msbuild(explicit=None):
    override = explicit or os.environ.get('FSRD_MSBUILD')
    if override:
        return executable(override, 'MSBuild.exe')
    return executable(str(visual_studio()/'MSBuild/Current/Bin/MSBuild.exe'), 'MSBuild.exe')


def compile_cpp(source, output, libraries=()):
    """Build x64 test helpers with all intermediates alongside their output."""
    output.parent.mkdir(parents=True, exist_ok=True)
    vcvars = visual_studio()/'VC/Auxiliary/Build/vcvars64.bat'
    command = output.with_suffix('.build.cmd')
    command.write_text(
        f'@call "{vcvars}" >nul\n@if errorlevel 1 exit /b %errorlevel%\n'
        f'@cl /nologo /std:c++20 /EHsc /O2 "{source}" '
        f'/Fe:"{output}" /Fo:"{output.with_suffix(".obj")}" '
        + ('/link ' + ' '.join(libraries) if libraries else '') + '\n', encoding='utf-8')
    subprocess.run(f'cmd /d /s /c ""{command}""', cwd=output.parent, check=True)
