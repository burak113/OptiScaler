"""Windows tool discovery shared by the FSRD shader/build/test entry points."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile


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


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _build(source, output, libraries, vs_root, dependencies=None, include_dirs=()):
    vcvars = vs_root/'VC/Auxiliary/Build/vcvars64.bat'
    command = output.with_suffix('.build.cmd')
    command.write_text(
        f'@call "{vcvars}" >nul\n@if errorlevel 1 exit /b %errorlevel%\n'
        f'@cl /nologo /std:c++20 /EHsc /O2 '
        + ''.join(f'/I"{directory}" ' for directory in include_dirs)
        + f'"{source}" '
        f'/Fe:"{output}" /Fo:"{output.with_suffix(".obj")}" '
        + (f'/sourceDependencies "{dependencies}" ' if dependencies else '')
        + ('/link ' + ' '.join(libraries) if libraries else '') + '\n', encoding='utf-8')
    subprocess.run(f'cmd /d /s /c ""{command}""', cwd=output.parent, check=True)


def compile_cpp(source, output, libraries=(), include_dirs=()):
    """Build an x64 test helper, reusing an earlier build of exactly the same inputs.

    A cached executable is used only when the source, every file the compiler included
    (recorded by /sourceDependencies), the libraries, CL and the MSVC toolset all hash the
    same, so an executable from another checkout or an edited header is never reused.
    FSRD_CPP_CACHE=0 always rebuilds; FSRD_CPP_CACHE=<dir> moves the cache.
    """
    output = Path(output)
    source = Path(source).resolve()
    include_dirs = tuple(str(Path(directory).resolve()) for directory in include_dirs)
    output.parent.mkdir(parents=True, exist_ok=True)
    vs_root = visual_studio()
    setting = os.environ.get('FSRD_CPP_CACHE', '')
    if setting == '0':
        _build(source, output, libraries, vs_root, include_dirs=include_dirs)
        return
    toolset = vs_root/'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt'
    key = hashlib.sha256(json.dumps([
        _sha256(source), str(source), list(libraries), list(include_dirs), os.environ.get('CL', ''), str(vs_root),
        toolset.read_text(encoding='utf-8').strip() if toolset.is_file() else '',
        _sha256(__file__)]).encode()).hexdigest()[:32]
    cache = Path(setting) if setting else Path(__file__).resolve().parents[3]/'tools_tmp/fsrd_cpp_cache'
    entry = cache/key
    manifest = entry/'manifest.json'
    cached = entry/output.name
    try:
        recorded = json.loads(manifest.read_text(encoding='utf-8'))
        valid = cached.is_file() and all(Path(p).is_file() and _sha256(p) == h for p, h in recorded.items())
    except (OSError, ValueError):
        valid = False
    if not valid:
        cache.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=key + '_', dir=cache))
        try:
            built = staging/output.name
            _build(source, built, libraries, vs_root, staging/'dependencies.json', include_dirs)
            includes = json.loads((staging/'dependencies.json').read_text(encoding='utf-8'))['Data']['Includes']
            files = {str(Path(p).resolve()): _sha256(p) for p in [source, *includes]}
            (staging/'manifest.json').write_text(json.dumps(files, indent=1), encoding='utf-8')
            shutil.rmtree(entry, ignore_errors=True)
            try:
                os.replace(staging, entry)
            except OSError:
                # A parallel validation published the same key first; use our own build.
                shutil.copy2(built, output)
                return
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    if not output.is_file() or _sha256(output) != _sha256(cached):
        shutil.copy2(cached, output)
