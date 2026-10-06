"""Windows tool discovery shared by the FSRD shader/build/test entry points."""
from pathlib import Path
from contextlib import contextmanager
import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time


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
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _toolchain_environment(vs_root):
    """Read the environment the actual x64 compiler and linker will inherit."""
    vcvars = vs_root/'VC/Auxiliary/Build/vcvars64.bat'
    result = subprocess.run(f'cmd /d /u /s /c ""{vcvars}" >nul && set"',
                            capture_output=True, check=True)
    environment = {}
    for line in result.stdout.decode('utf-16-le').splitlines():
        name, separator, value = line.partition('=')
        if separator and name:
            environment[name.upper()] = value
    return environment


def _resolve_library(library, directories, build_dir):
    name = str(library)
    if len(name) >= 2 and name[0] == name[-1] == '"':
        name = name[1:-1]
    # Response files and linker switches may change the effective search rules.
    if not name or name.startswith(('/', '@', '-')) or '"' in name:
        return None
    path = Path(name)
    if not path.suffix:
        path = path.with_suffix('.lib')
    if path.suffix.lower() != '.lib':
        return None
    candidates = [path] if path.is_absolute() else [build_dir/path]
    if not path.is_absolute() and path.parent == Path('.'):
        candidates.extend(directory/path for directory in directories)
    return next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)


def _cache_dependencies(vs_root, libraries, build_dir):
    """Resolve and fingerprint explicit libraries and the selected toolchain, or bypass."""
    try:
        environment = _toolchain_environment(vs_root)
        required = ('PATH', 'LIB', 'INCLUDE', 'VCTOOLSINSTALLDIR', 'VCTOOLSVERSION',
                    'WINDOWSSDKDIR', 'WINDOWSSDKVERSION', 'UNIVERSALCRTSDKDIR', 'UCRTVERSION')
        if any(not environment.get(name) for name in required):
            return None
        # These can inject response files, forced includes, /LIBPATH, or replacement tools.
        if any(environment.get(name, '').strip() for name in ('CL', '_CL_', 'LINK', '_LINK_')):
            return None
        compiler = shutil.which('cl.exe', path=environment['PATH'])
        linker = shutil.which('link.exe', path=environment['PATH'])
        if not compiler or not linker:
            return None
        compiler, linker = Path(compiler).resolve(), Path(linker).resolve()
        # CL uses the linker beside its selected compiler tools.
        if compiler.parent != linker.parent:
            return None
        library_dirs = tuple(Path(p.strip('"')) for p in environment['LIB'].split(';') if p)
        include_paths = tuple(Path(p.strip('"')) for p in environment['INCLUDE'].split(';') if p)
        if any(not path.is_absolute() for path in (*library_dirs, *include_paths)):
            return None
        library_dirs = tuple(path.resolve() for path in library_dirs)
        resolved = tuple(_resolve_library(library, library_dirs, build_dir) for library in libraries)
        if any(library is None for library in resolved):
            return None
        tool_files = [compiler, linker, vs_root/'VC/Auxiliary/Build/vcvars64.bat']
        toolset = vs_root/'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt'
        if toolset.is_file():
            tool_files.append(toolset)
        for name in ('c1xx.dll', 'c2.dll', 'mspdbcore.dll', 'mspdb140.dll'):
            if (compiler.parent/name).is_file():
                tool_files.append(compiler.parent/name)
        files = {str(path.resolve()): _sha256(path) for path in (*tool_files, *resolved)}
        identity = {name: environment[name] for name in required}
        identity.update(compiler=str(compiler), linker=str(linker), files=files,
                        LIBPATH=environment.get('LIBPATH', ''))
        return {'identity': identity, 'files': files, 'libraries': resolved,
                'library_dirs': library_dirs, 'environment': environment}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


_thread_locks = {}
_thread_locks_guard = threading.Lock()


@contextmanager
def _cache_lock(path):
    """Own an entire cache transaction across threads and processes.

    Never unlink the lock file: existing waiters must all lock the same file object.
    OS locks release automatically when a crashed process closes its handle.
    """
    path = Path(path).resolve()
    with _thread_locks_guard:
        thread_lock = _thread_locks.setdefault(os.path.normcase(str(path)), threading.Lock())
    with thread_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a+b') as stream:
            if os.name == 'nt':
                import msvcrt
                while True:
                    try:
                        stream.seek(0)
                        # Byte-range locks can extend beyond EOF; do not write before locking.
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError as error:
                        if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                            raise
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _atomic_copy(source, output):
    descriptor, temporary = tempfile.mkstemp(prefix='.' + output.name + '_', suffix='.tmp', dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def _library_argument(library):
    # Canonical paths need one pair of quotes. Preserve existing linker/response
    # syntax on bypassed builds, including /LIBPATH:"directory with spaces".
    value = str(library)
    return value if '"' in value else f'"{value}"'


def _build(source, output, libraries, vs_root, dependencies=None, include_dirs=(), link_dependencies=None,
           build_environment=None, build_dir=None):
    vcvars = vs_root/'VC/Auxiliary/Build/vcvars64.bat'
    command = output.with_suffix('.build.cmd')
    compiler = (shutil.which('cl.exe', path=build_environment['PATH']) if build_environment else None)
    prefix = '@chcp 65001 >nul\n'
    if not build_environment:
        prefix += f'@call "{vcvars}" >nul\n@if errorlevel 1 exit /b %errorlevel%\n'
    prefix += f'@"{compiler}"' if compiler else '@cl'
    command.write_text(
        prefix + ' /nologo /std:c++20 /EHsc /O2 '
        + ''.join(f'/I"{directory}" ' for directory in include_dirs)
        + f'"{source}" '
        f'/Fe:"{output}" /Fo:"{output.with_suffix(".obj")}" '
        + (f'/sourceDependencies "{dependencies}" ' if dependencies else '')
        + ('/link ' + ' '.join(_library_argument(library) for library in libraries)
           + (' /VERBOSE:LIB' if link_dependencies else '') if libraries or link_dependencies else '')
        + '\n', encoding='utf-8')
    if not link_dependencies:
        subprocess.run(f'cmd /d /s /c ""{command}""', cwd=build_dir or output.parent, check=True, env=build_environment)
        return
    result = subprocess.run(f'cmd /d /s /c ""{command}""', cwd=build_dir or output.parent, env=build_environment,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', errors='replace')
    if result.returncode:
        print(result.stdout, end='')
        result.check_returncode()
    # MSVC may be localized even with VSLANG=1033. Paths in /VERBOSE:LIB are invariant.
    paths = set(re.findall(r'(?im)((?:[a-z]:[\\/]|\\\\)[^\r\n]+\.lib)(?=[:\s(]|$)', result.stdout))
    linked = [str(Path(path).resolve()) for path in paths if Path(path).is_file()]
    Path(link_dependencies).write_text(json.dumps(sorted(linked) if len(linked) == len(paths) else []), encoding='utf-8')
    for line in result.stdout.splitlines():
        if re.search(r'\b(?:warning|error) [A-Z]+\d+', line):
            print(line)


def _valid_entry(entry, dependencies, build_dir):
    try:
        recorded = json.loads((entry/'manifest.json').read_text(encoding='utf-8'))
        if not isinstance(recorded, dict) or recorded.get('version') != 2:
            return None
        files = recorded.get('files')
        search = recorded.get('library_search')
        executable_hash = recorded.get('executable')
        if not isinstance(files, dict) or not files or not isinstance(search, list) or not isinstance(executable_hash, str):
            return None
        if any(not isinstance(path, str) or not isinstance(digest, str) for path, digest in files.items()):
            return None
        if any(not Path(path).is_file() or _sha256(path) != digest for path, digest in files.items()):
            return None
        for library in search:
            if not isinstance(library, dict) or not isinstance(library.get('name'), str) or \
                    not isinstance(library.get('path'), str):
                return None
            if _resolve_library(library['name'], dependencies['library_dirs'], build_dir) != Path(library['path']):
                return None
        cached = entry/'helper.exe'
        if not cached.is_file() or _sha256(cached) != executable_hash:
            return None
        return executable_hash
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _stable_files(paths, before, started):
    files = {}
    for path in set(Path(p).resolve() for p in paths):
        first = path.stat()
        digest = _sha256(path)
        second = path.stat()
        if (first.st_size, first.st_mtime_ns, first.st_ctime_ns) != \
                (second.st_size, second.st_mtime_ns, second.st_ctime_ns):
            return None
        if max(second.st_mtime_ns, second.st_ctime_ns) >= started:
            return None
        if str(path) in before and digest != before[str(path)]:
            return None
        files[str(path)] = digest
    return files


def compile_cpp(source, output, libraries=(), include_dirs=()):
    """Build an x64 test helper, reusing an earlier build of exactly the same inputs.

    Entries are owned through validation, publication and copying. Source/include files,
    resolved explicit and default libraries, compiler/linker tools and the vcvars-selected
    SDK identity must match. Unreliable dependency resolution bypasses the cache.
    FSRD_CPP_CACHE=0 always rebuilds; FSRD_CPP_CACHE=<dir> moves the cache.
    """
    output = Path(output).resolve()
    source = Path(source).resolve()
    include_dirs = tuple(str(Path(directory).resolve()) for directory in include_dirs)
    output.parent.mkdir(parents=True, exist_ok=True)
    vs_root = visual_studio()
    setting = os.environ.get('FSRD_CPP_CACHE', '')
    if setting == '0':
        _build(source, output, libraries, vs_root, include_dirs=include_dirs)
        return
    libraries = tuple(libraries)
    build_dir = output.parent
    dependencies = _cache_dependencies(vs_root, libraries, build_dir)
    if dependencies is None:
        _build(source, output, libraries, vs_root, include_dirs=include_dirs)
        return
    before = dict(dependencies['files'])
    before[str(source)] = _sha256(source)
    before[str(Path(__file__).resolve())] = _sha256(__file__)
    key = hashlib.sha256(json.dumps([
        before, str(source), list(libraries), list(include_dirs), dependencies['identity']],
        sort_keys=True).encode()).hexdigest()[:32]
    cache = Path(setting) if setting else Path(__file__).resolve().parents[3]/'tools_tmp/fsrd_cpp_cache'
    cache = cache.resolve()
    entry = cache/key
    with _cache_lock(cache/'.locks'/(key + '.lock')):
        executable_hash = _valid_entry(entry, dependencies, build_dir)
        if executable_hash is None:
            staging = Path(tempfile.mkdtemp(prefix=key + '_', dir=cache))
            try:
                built = staging/'helper.exe'
                started = time.time_ns()
                _build(source, built, dependencies['libraries'], vs_root, staging/'dependencies.json', include_dirs,
                       link_dependencies=staging/'link_dependencies.json',
                       build_environment=dependencies['environment'], build_dir=build_dir)
                try:
                    includes = json.loads((staging/'dependencies.json').read_text(encoding='utf-8'))['Data']['Includes']
                    linked = json.loads((staging/'link_dependencies.json').read_text(encoding='utf-8'))
                    explicit = set(dependencies['libraries'])
                    search = []
                    for library in set(Path(p).resolve() for p in linked) - explicit:
                        if _resolve_library(library.name, dependencies['library_dirs'], build_dir) != library:
                            raise ValueError('Unreliable default library search')
                        search.append({'name': library.name, 'path': str(library)})
                    files = _stable_files([*before, *includes, *linked], before, started) if linked else None
                except (OSError, ValueError, KeyError, TypeError):
                    files = None
                if files is None:
                    _atomic_copy(built, output)
                    return
                executable_hash = _sha256(built)
                try:
                    (staging/'manifest.json').write_text(json.dumps({
                        'version': 2, 'files': files, 'library_search': search, 'executable': executable_hash,
                    }, indent=1), encoding='utf-8')
                    if entry.exists():
                        shutil.rmtree(entry)
                    os.replace(staging, entry)
                except OSError:
                    # A cache publication failure must not discard a successful build.
                    _atomic_copy(built, output)
                    return
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
        if not output.is_file() or _sha256(output) != executable_hash:
            _atomic_copy(entry/'helper.exe', output)
