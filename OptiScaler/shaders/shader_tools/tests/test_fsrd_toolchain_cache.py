"""Deterministic filesystem regressions for production compile_cpp caching.

Only compiler execution and vcvars discovery are substituted. Source, includes,
libraries, tool binaries, manifests, publication, copies and process locks use
real files. --verify-baseline confirms the two reported bugs at 1840cbd1.
"""
from pathlib import Path
import argparse
from contextlib import ExitStack
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
ROOT = HERE.parents[3]
MODULE_PATH = HERE.parent / 'fsrd_toolchain.py'


def load_toolchain(path):
    name = 'fsrd_cache_under_test_' + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CompilerFixture:
    """A controlled compiler consuming real input bytes, without caching policy."""
    def __init__(self, root, module_path=MODULE_PATH, create=True):
        self.root = Path(root)
        self.module_path = Path(module_path)
        self.module = load_toolchain(self.module_path)
        self.vs = self.root / 'visual_studio'
        self.tools = self.vs / 'VC/Tools/MSVC/14.50.test'
        self.bin = self.tools / 'bin/Hostx64/x64'
        self.lib = self.tools / 'lib/x64'
        self.include = self.tools / 'include'
        self.sdk = self.root / 'windows_sdk'
        self.source = self.root / 'source/helper.cpp'
        self.header = self.source.with_name('dependency.h')
        self.library = self.lib / 'dependency.lib'
        self.default_library = self.lib / 'libcmt.lib'
        self.build_log = self.root / 'builds.log'
        self.cache = self.root / 'cache'
        self.before_build = None
        self.after_output = None
        self.fail_next = False
        self.environment = {
            'PATH': str(self.bin), 'LIB': str(self.lib),
            'INCLUDE': os.pathsep.join((str(self.include), str(self.sdk / 'Include/10.0.test/ucrt'))),
            'VCToolsInstallDir': str(self.tools) + os.sep, 'VCToolsVersion': '14.50.test',
            'VCINSTALLDIR': str(self.vs / 'VC') + os.sep, 'VisualStudioVersion': '17.0',
            'WindowsSdkDir': str(self.sdk) + os.sep, 'WindowsSDKVersion': '10.0.test' + os.sep,
            'UniversalCRTSdkDir': str(self.sdk) + os.sep, 'UCRTVersion': '10.0.test',
            'VSCMD_ARG_HOST_ARCH': 'x64', 'VSCMD_ARG_TGT_ARCH': 'x64',
        }
        if create:
            files = {
                self.vs / 'VC/Auxiliary/Build/vcvars64.bat': '@fake vcvars\n',
                self.vs / 'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt': '14.50.test\n',
                self.bin / 'cl.exe': 'compiler-v1', self.bin / 'link.exe': 'linker-v1',
                self.bin / 'lib.exe': 'librarian-v1', self.library: 'library-v1',
                self.default_library: 'default-library-v1', self.header: '#define VALUE 1\n',
                self.source: '#include "dependency.h"\nint main() { return VALUE; }\n',
                self.include / 'runtime.h': 'runtime-v1',
                self.sdk / 'Include/10.0.test/ucrt/corecrt.h': 'sdk-v1',
            }
            for path, content in files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')

    def resolve_library(self, library):
        path = Path(library)
        if path.is_file():
            return path.resolve()
        for directory in self.environment['LIB'].split(os.pathsep):
            candidate = Path(directory) / library
            if candidate.is_file():
                return candidate.resolve()
        return None

    def build(self, source, output, libraries, vs_root, dependencies=None, include_dirs=(),
              link_dependencies=None, **kwargs):
        if self.before_build:
            self.before_build()
        # One append per actual compiler call; an independent process sees it too.
        with self.build_log.open('a', encoding='utf-8') as log:
            log.write(f'{os.getpid()} {threading.current_thread().name}\n')
        consumed = [self.resolve_library(library) for library in libraries]
        # Model an implicit compiler runtime dependency as well as explicit libs.
        consumed.append(self.default_library)
        image = {
            'source': Path(source).read_text(encoding='utf-8'),
            'header': self.header.read_text(encoding='utf-8'),
            'libraries': [(str(path), path.read_text(encoding='utf-8')) if path else ('unresolved', library)
                          for path, library in zip(consumed, (*libraries, 'libcmt.lib'))],
            'compiler': (self.bin / 'cl.exe').read_text(encoding='utf-8'),
            'linker': (self.bin / 'link.exe').read_text(encoding='utf-8'),
            'CL': os.environ.get('CL', ''), '_CL_': os.environ.get('_CL_', ''),
            'LINK': os.environ.get('LINK', ''), '_LINK_': os.environ.get('_LINK_', ''),
            'SDK': self.environment['WindowsSDKVersion'], 'include_dirs': list(map(str, include_dirs)),
        }
        Path(output).write_text(json.dumps(image, sort_keys=True), encoding='utf-8')
        if self.after_output:
            self.after_output()
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError('injected compiler failure after partial executable')
        if dependencies:
            Path(dependencies).write_text(json.dumps({'Data': {'Includes': [str(self.header)]}}), encoding='utf-8')
        if link_dependencies:
            # The production builder reports LINK's actually consumed libraries.
            Path(link_dependencies).write_text(json.dumps([str(path) for path in consumed if path]),
                                               encoding='utf-8')

    def install(self, cache=None):
        stack = ExitStack()
        stack.enter_context(patch.dict(os.environ, {
            'FSRD_CPP_CACHE': str(self.cache) if cache is None else str(cache),
            'CL': '', '_CL_': '', 'LINK': '', '_LINK_': '',
        }))
        stack.enter_context(patch.object(self.module, 'visual_studio', return_value=self.vs))
        stack.enter_context(patch.object(self.module, '_build', side_effect=self.build))
        if hasattr(self.module, '_toolchain_environment'):
            stack.enter_context(patch.object(self.module, '_toolchain_environment',
                                             side_effect=lambda _: {
                                                 **{key.upper(): value for key, value in self.environment.items()},
                                                 **{key: os.environ.get(key, '') for key in ('CL', '_CL_', 'LINK', '_LINK_')},
                                             }))
        return stack

    def compile(self, directory='output', libraries=None, filename='helper.exe', **kwargs):
        output = self.root / directory / filename
        self.module.compile_cpp(self.source, output,
                                (str(self.library),) if libraries is None else libraries, **kwargs)
        return output

    def count(self):
        return len(self.build_log.read_text(encoding='utf-8').splitlines()) if self.build_log.exists() else 0


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fsrd_cache_regression_')
        self.addCleanup(self.temp.cleanup)
        self.fixture = CompilerFixture(self.temp.name, MODULE_PATH)
        self.stack = self.fixture.install()
        self.addCleanup(self.stack.close)

    def test_normal_hit_and_different_destination(self):
        first = self.fixture.compile()
        content = first.read_bytes()
        self.fixture.compile()
        second = self.fixture.compile('another_destination')
        self.assertEqual(second.read_bytes(), content)
        self.assertEqual(self.fixture.count(), 1, 'normal cache hit must reuse the build')

    def test_different_executable_names_share_cache(self):
        first = self.fixture.compile(filename='first.exe').read_bytes()
        second = self.fixture.compile(filename='second.exe').read_bytes()
        self.assertEqual(first, second)
        self.assertEqual(self.fixture.count(), 1, 'output basename must not invalidate identical compiled inputs')

    def test_source_change(self):
        first = self.fixture.compile().read_bytes()
        self.fixture.source.write_text('int main() { return 2; }\n', encoding='utf-8')
        self.assertNotEqual(self.fixture.compile().read_bytes(), first)
        self.assertEqual(self.fixture.count(), 2)

    def test_include_change(self):
        first = self.fixture.compile().read_bytes()
        self.fixture.header.write_text('#define VALUE 2\n', encoding='utf-8')
        self.assertNotEqual(self.fixture.compile().read_bytes(), first)
        self.assertEqual(self.fixture.count(), 2)

    def test_include_directory_change(self):
        self.fixture.compile(include_dirs=(self.fixture.include,))
        alternate = self.fixture.root / 'alternate_include'; alternate.mkdir()
        self.fixture.compile(include_dirs=(alternate,))
        self.assertEqual(self.fixture.count(), 2)

    def test_link_library_replacement(self):
        first = self.fixture.compile().read_bytes()
        self.fixture.library.write_text('library-v2', encoding='utf-8')
        second = self.fixture.compile().read_bytes()
        self.assertNotEqual(second, first, 'same-path .lib replacement must relink')
        self.assertEqual(self.fixture.count(), 2)

    def test_named_library_search_change(self):
        first = self.fixture.compile(libraries=('dependency.lib',)).read_bytes()
        alternate = self.fixture.root / 'alternate_lib'; alternate.mkdir()
        (alternate / 'dependency.lib').write_text('alternate-library-v2', encoding='utf-8')
        self.fixture.environment['LIB'] = os.pathsep.join((str(alternate), str(self.fixture.lib)))
        self.assertNotEqual(self.fixture.compile(libraries=('dependency.lib',)).read_bytes(), first)
        self.assertEqual(self.fixture.count(), 2, 'resolved LIB-search path must participate in cache identity')

    def test_named_library_shadow_without_environment_change(self):
        earlier = self.fixture.root / 'earlier_lib'; earlier.mkdir()
        self.fixture.environment['LIB'] = os.pathsep.join((str(earlier), str(self.fixture.lib)))
        first = self.fixture.compile(libraries=('dependency.lib',)).read_bytes()
        (earlier / 'dependency.lib').write_text('new-earlier-library-v2', encoding='utf-8')
        self.assertNotEqual(self.fixture.compile(libraries=('dependency.lib',)).read_bytes(), first)
        self.assertEqual(self.fixture.count(), 2, 'new shadow library must be resolved despite unchanged LIB text')

    def test_implicit_runtime_library_change(self):
        first = self.fixture.compile().read_bytes()
        self.fixture.default_library.write_text('default-library-v2', encoding='utf-8')
        self.assertNotEqual(self.fixture.compile().read_bytes(), first)
        self.assertEqual(self.fixture.count(), 2, 'actually linked default library must be tracked')

    def test_implicit_runtime_library_shadow_without_environment_change(self):
        earlier = self.fixture.root / 'earlier_runtime'; earlier.mkdir()
        self.fixture.environment['LIB'] = os.pathsep.join((str(earlier), str(self.fixture.lib)))
        first = self.fixture.compile().read_bytes()
        replacement = earlier / 'libcmt.lib'
        replacement.write_text('shadow-runtime-v2', encoding='utf-8')
        self.fixture.default_library = replacement
        self.assertNotEqual(self.fixture.compile().read_bytes(), first)
        self.assertEqual(self.fixture.count(), 2,
                         'implicit runtime name must be re-resolved even when LIB text is unchanged')

    def test_cl_flags_change(self):
        first = self.fixture.compile().read_bytes()
        os.environ['CL'] = '/DREGRESSION=2'
        self.assertNotEqual(self.fixture.compile().read_bytes(), first)
        self.assertEqual(self.fixture.count(), 2)

    def test_appended_cl_flags_change(self):
        first = self.fixture.compile().read_bytes()
        os.environ['_CL_'] = '/DAPPENDED_REGRESSION=2'
        self.assertNotEqual(self.fixture.compile().read_bytes(), first)
        self.assertEqual(self.fixture.count(), 2, '_CL_ appended compiler options must invalidate')

    def test_link_flags_bypass(self):
        os.environ['LINK'] = '/DEBUG'
        self.fixture.compile(); self.fixture.compile()
        self.assertEqual(self.fixture.count(), 2, 'opaque linker options must conservatively bypass cache')

    def test_appended_link_flags_change_and_bypass(self):
        first = self.fixture.compile().read_bytes()
        os.environ['_LINK_'] = '/DEBUG'
        self.assertNotEqual(self.fixture.compile().read_bytes(), first,
                            '_LINK_ appended options must not reuse an older executable')
        self.fixture.compile()
        self.assertEqual(self.fixture.count(), 3, 'opaque appended linker options must bypass cache')

    def test_compiler_binary_change(self):
        first = self.fixture.compile().read_bytes()
        (self.fixture.bin / 'cl.exe').write_text('compiler-v2', encoding='utf-8')
        self.assertNotEqual(self.fixture.compile().read_bytes(), first)
        self.assertEqual(self.fixture.count(), 2)

    def test_linker_binary_change(self):
        first = self.fixture.compile().read_bytes()
        (self.fixture.bin / 'link.exe').write_text('linker-v2', encoding='utf-8')
        self.assertNotEqual(self.fixture.compile().read_bytes(), first)
        self.assertEqual(self.fixture.count(), 2)

    def test_toolset_version_change(self):
        self.fixture.compile()
        version = self.fixture.vs / 'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt'
        version.write_text('14.51.test\n', encoding='utf-8')
        self.fixture.compile()
        self.assertEqual(self.fixture.count(), 2)

    def test_sdk_identity_change(self):
        first = self.fixture.compile().read_bytes()
        self.fixture.environment['WindowsSDKVersion'] = '10.1.test' + os.sep
        self.assertNotEqual(self.fixture.compile().read_bytes(), first)
        self.assertEqual(self.fixture.count(), 2)

    def test_cache_zero_always_builds(self):
        os.environ['FSRD_CPP_CACHE'] = '0'
        self.fixture.compile(); self.fixture.compile()
        self.assertEqual(self.fixture.count(), 2)
        self.assertFalse(self.fixture.cache.exists(), 'cache=0 must bypass cache access')

    def test_unresolved_link_dependency_bypasses_cache(self):
        self.fixture.compile(libraries=('unresolved_external.lib',))
        self.fixture.compile(libraries=('unresolved_external.lib',))
        self.assertEqual(self.fixture.count(), 2, 'unresolved dependency must bypass cache reuse')

    def test_failed_build_does_not_poison_cache(self):
        self.fixture.fail_next = True
        with self.assertRaisesRegex(RuntimeError, 'injected compiler failure'):
            self.fixture.compile()
        self.assertFalse((self.fixture.root / 'output/helper.exe').exists())
        self.fixture.compile(); self.fixture.compile()
        self.assertEqual(self.fixture.count(), 2, 'failed staging must not prevent a subsequent valid hit')

    def test_library_change_during_build_is_not_published(self):
        def replace_after_compilation():
            self.fixture.library.write_text('library-raced-v2', encoding='utf-8')
            self.fixture.after_output = None
        self.fixture.after_output = replace_after_compilation
        first = self.fixture.compile().read_bytes()
        image = json.loads(first)
        self.assertEqual(image['libraries'][0][1], 'library-v1', 'compiler consumed the old library')
        self.assertFalse(list(self.fixture.cache.rglob('manifest.json')),
                         'changed build inputs must not publish a newer fingerprint for the old executable')
        self.assertNotEqual(self.fixture.compile().read_bytes(), first)
        self.fixture.compile()
        self.assertEqual(self.fixture.count(), 2, 'stable rebuild must publish and subsequently hit')

    def test_tampered_cached_executable_rebuilds(self):
        expected = self.fixture.compile().read_bytes()
        executables = list(self.fixture.cache.rglob('helper.exe'))
        self.assertEqual(len(executables), 1)
        executables[0].write_bytes(b'corrupt partial executable')
        output = self.fixture.compile('after_tampering')
        self.assertEqual(output.read_bytes(), expected, 'cached image integrity must be checked before copying')
        self.assertEqual(self.fixture.count(), 2)

    def test_damaged_manifest_rebuilds(self):
        self.fixture.compile()
        manifests = list(self.fixture.cache.rglob('manifest.json'))
        self.assertTrue(manifests, 'successful cacheable build must publish a manifest')
        for manifest in manifests:
            manifest.write_text('{incomplete', encoding='utf-8')
        self.fixture.compile(); self.fixture.compile()
        self.assertEqual(self.fixture.count(), 2, 'an incomplete entry must be replaced by a valid build')

    def test_concurrent_publication_and_reader(self):
        """Pause A at the real copy; baseline B deletes A's published file."""
        a_building, b_building, release_a, release_b = (threading.Event() for _ in range(4))
        a_copy, release_copy, copy_finished = (threading.Event() for _ in range(3))
        errors = []
        deletions = []
        actual_copy = shutil.copy2
        actual_remove = shutil.rmtree

        def before_build():
            if threading.current_thread().name == 'publisher_a':
                a_building.set()
                if not release_a.wait(10): raise RuntimeError('A build scheduling timeout')
            elif threading.current_thread().name == 'publisher_b':
                b_building.set()
                if not release_b.wait(10): raise RuntimeError('B build scheduling timeout')

        def copy(source, target, *args, **kwargs):
            if Path(target).parent == self.fixture.root / 'a':
                a_copy.set()
                if not release_copy.wait(10): raise RuntimeError('A copy scheduling timeout')
                try:
                    return actual_copy(source, target, *args, **kwargs)
                finally:
                    copy_finished.set()
            return actual_copy(source, target, *args, **kwargs)

        def remove(path, *args, **kwargs):
            published = (Path(path) / 'manifest.json').is_file()
            result = actual_remove(path, *args, **kwargs)
            if published and threading.current_thread().name == 'publisher_b':
                deletions.append(str(path))
                # Force A's copy to observe the deletion before B can republish.
                release_copy.set()
                if not copy_finished.wait(10): raise RuntimeError('deleted-reader scheduling timeout')
            return result

        def invoke(directory):
            try:
                self.fixture.compile(directory)
            except Exception as error:
                errors.append((directory, type(error).__name__, str(error)))

        self.fixture.before_build = before_build
        a = threading.Thread(target=invoke, args=('a',), name='publisher_a')
        b = threading.Thread(target=invoke, args=('b',), name='publisher_b')
        with patch.object(self.fixture.module.shutil, 'copy2', side_effect=copy), \
             patch.object(self.fixture.module.shutil, 'rmtree', side_effect=remove):
            try:
                a.start()
                self.assertTrue(a_building.wait(5), 'A must enter the compiler')
                b.start()
                simultaneous_builders = b_building.wait(.3)
                release_a.set()
                self.assertTrue(a_copy.wait(5), 'A must reach executable delivery')
                release_b.set()
                if simultaneous_builders:
                    b.join(5)
                release_copy.set()
            finally:
                release_a.set(); release_b.set(); release_copy.set()
                a.join(5)
                if b.ident is not None: b.join(5)
        self.assertFalse(a.is_alive() or b.is_alive(), 'concurrent calls must finish without deadlock')
        self.assertFalse(errors, f'concurrent build/copy failed: {errors}')
        self.assertFalse(deletions, 'a competing publisher must not delete a live shared entry')
        self.assertEqual((self.fixture.root / 'a/helper.exe').read_bytes(),
                         (self.fixture.root / 'b/helper.exe').read_bytes())
        self.assertEqual(self.fixture.count(), 1, 'same-key threads must reuse one complete publication')

    def test_separate_processes_reuse_one_publication(self):
        processes = []
        environment = dict(os.environ, PYTHONUNBUFFERED='1')
        for index in range(4):
            processes.append(subprocess.Popen([
                sys.executable, str(Path(__file__).resolve()), '--child-root', str(self.fixture.root),
                '--module', str(self.fixture.module_path), '--child-name', f'process_{index}',
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment))
        try:
            deadline = time.monotonic() + 10
            while len(list(self.fixture.root.glob('process_*.ready'))) != len(processes):
                self.assertLess(time.monotonic(), deadline, 'children must reach the shared start gate')
                time.sleep(.01)
            (self.fixture.root / 'process_start').write_text('go', encoding='utf-8')
            results = [process.communicate(timeout=15) for process in processes]
            for process, (stdout, stderr) in zip(processes, results):
                self.assertEqual(process.returncode, 0, f'child failed: {stdout}\n{stderr}')
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill(); process.wait(timeout=5)
        contents = [(self.fixture.root / f'process_{i}/helper.exe').read_bytes() for i in range(4)]
        self.assertTrue(all(content == contents[0] for content in contents))
        self.assertEqual(self.fixture.count(), 1, 'separate processes must share the complete same-key entry')
        self.fixture.compile('parent_after_children')
        self.assertEqual(self.fixture.count(), 1, 'a later reader must reuse the published process result')


def child(root, module_path, name):
    fixture = CompilerFixture(root, module_path, create=False)
    with fixture.install():
        (fixture.root / f'{name}.ready').write_text('ready', encoding='utf-8')
        deadline = time.monotonic() + 10
        while not (fixture.root / 'process_start').exists():
            if time.monotonic() > deadline: raise RuntimeError('process gate timeout')
            time.sleep(.01)
        fixture.before_build = lambda: time.sleep(.1)
        fixture.compile(name)


def verify_baseline():
    global MODULE_PATH
    with tempfile.TemporaryDirectory(prefix='fsrd_cache_baseline_') as directory:
        baseline = Path(directory) / 'fsrd_toolchain.py'
        source = subprocess.check_output([
            'git', 'show', '1840cbd1:OptiScaler/shaders/shader_tools/fsrd_toolchain.py'], cwd=ROOT)
        baseline.write_bytes(source)
        previous = MODULE_PATH
        MODULE_PATH = baseline
        try:
            cases = ('test_link_library_replacement', 'test_concurrent_publication_and_reader')
            suite = unittest.TestSuite(CacheTests(case) for case in cases)
            stream = io.StringIO()
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
            if result.errors or len(result.failures) != 2:
                raise AssertionError('both baseline defects must fail as assertions:\n' + stream.getvalue())
            messages = [message for _, message in result.failures]
            assert any('same-path .lib replacement must relink' in message for message in messages)
            assert any('concurrent build/copy failed' in message and 'FileNotFoundError' in message
                       for message in messages)
            print('PASS: baseline 1840cbd1 fails same-path .lib replacement and deterministic publication/read race')
        finally:
            MODULE_PATH = previous


def msvc_smoke():
    """Use real vcvars, LIB discovery, static librarian, compiler and linker."""
    module = load_toolchain(MODULE_PATH)
    vs = module.visual_studio()
    base = ROOT / 'tools_tmp/fsrd_cache_msvc_smoke'
    base.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='same_path_', dir=base))
    libraries = directory / 'dependency files'; libraries.mkdir()
    binaries = directory / 'executables'; binaries.mkdir()
    library_source = libraries / 'dependency.cpp'
    library_object = libraries / 'dependency.obj'
    library = libraries / 'dependency.lib'
    source = directory / 'helper.cpp'
    source.write_text('#include <cstdio>\nextern "C" int cache_dependency_value();\n'
                      'int main() { std::printf("%d\\n", cache_dependency_value()); }\n', encoding='utf-8')
    command = directory / 'make_dependency.cmd'
    command.write_text(
        f'@call "{vs / "VC/Auxiliary/Build/vcvars64.bat"}" >nul\n'
        '@if errorlevel 1 exit /b %errorlevel%\n'
        f'@cl /nologo /EHsc /O2 /c "{library_source}" /Fo:"{library_object}"\n'
        '@if errorlevel 1 exit /b %errorlevel%\n'
        f'@lib /nologo /OUT:"{library}" "{library_object}"\n', encoding='utf-8')

    def make_library(value):
        library_source.write_text(f'extern "C" int cache_dependency_value() {{ return {value}; }}\n',
                                  encoding='utf-8')
        subprocess.run(f'cmd /d /s /c ""{command}""', cwd=directory, check=True)

    output = binaries / 'helper.exe'
    # Relative to the requested output directory, including spaces: discovery
    # must resolve it before compiling in staging and quote the resulting path.
    relative_library = os.path.relpath(library, binaries)
    build_count = 0
    actual_build = module._build

    def count_build(*args, **kwargs):
        nonlocal build_count
        build_count += 1
        return actual_build(*args, **kwargs)

    with patch.dict(os.environ, {'FSRD_CPP_CACHE': str(directory / 'cache'),
                                'CL': '', '_CL_': '', 'LINK': '', '_LINK_': ''}), \
         patch.object(module, '_build', side_effect=count_build):
        make_library(17)
        module.compile_cpp(source, output, (relative_library,))
        assert subprocess.check_output([str(output)], text=True).strip() == '17', 'v1 must link real library value'
        assert list((directory / 'cache').rglob('manifest.json')), 'real build must publish a reusable cache entry'
        module.compile_cpp(source, output, (relative_library,))
        assert build_count == 1, 'unchanged actual MSVC inputs must reuse the cached executable'
        make_library(29)
        module.compile_cpp(source, output, (relative_library,))
        assert subprocess.check_output([str(output)], text=True).strip() == '29', 'same-path library v2 must relink'
        assert build_count == 2, 'same-path library replacement must require one new MSVC compile'
        module.compile_cpp(source, output, (relative_library,))
        assert build_count == 2, 'updated actual library must hit its cache on the next call'
    print(f'PASS: actual MSVC relative .lib path with spaces returned 17 -> 29, two builds/four calls; {directory}')


def main():
    global MODULE_PATH
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', type=Path, default=MODULE_PATH)
    parser.add_argument('--verify-baseline', action='store_true')
    parser.add_argument('--msvc-smoke', action='store_true')
    parser.add_argument('--child-root', type=Path)
    parser.add_argument('--child-name')
    args = parser.parse_args()
    MODULE_PATH = args.module.resolve()
    if args.child_root:
        child(args.child_root, MODULE_PATH, args.child_name)
        return
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CacheTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    print(f'PASS: {result.testsRun} production compile_cpp cache regressions')
    if args.verify_baseline:
        verify_baseline()
    if args.msvc_smoke:
        msvc_smoke()


if __name__ == '__main__':
    main()
