"""Run the complete, immutable Floor quality protocol against git 49b743d4.

Requires the existing Windows GPU/SDK toolchain and a Python with numpy. An
output directory must be new: results, native contexts and baselines are never
reused or retried. --dry-run freezes/authenticates inputs and validates the full
command plan without compiling a runner or dispatching GPU work. A dry run is
never quality acceptance. The baseline's failing absolute quality measurements
are retained as observations; every candidate gate and every infrastructure
check is mandatory. This protocol does not certify game footage or temporal
composition history reuse (the dedicated history suite remains separate).
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import struct
import subprocess
import sys
import traceback


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TESTS = HERE / 'tests'
PRE = ROOT / 'OptiScaler/shaders/fsrd_preprocess/precompile'
BASE_REF = '49b743d4'
BASE_PATH = 'OptiScaler/shaders/fsrd_preprocess/precompile'
SDK = ROOT / 'external/FidelityFX-SDK-v2/Kits/FidelityFX'
DLL = SDK / 'signedbin/amd_fidelityfx_denoiser_dx12.dll'
ARTIFACT_SUFFIXES = {'.hlsl', '.hlsli', '.cso', '.h'}
SHADERS = ('FSRDFloorSeed', 'FSRDFloor', 'FSRDInputConv', 'FSRDOutputComp')
TOOLS = {'texture': 'test_fsrd_floor_texture_quality.py',
         'disocclusion': 'test_fsrd_floor_disocclusion_quality.py',
         'holdout': 'test_fsrd_floor_quality_holdout.py',
         'replay': 'fsrd_floor_rr_replay.py'}
COUNTERS = ('validation_errors', 'validation_warnings', 'sdk_errors', 'sdk_warnings')
SCHEMA = 'fsrd_complete_floor_quality_v1'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def artifact_identity(directory):
    return {p.relative_to(directory).as_posix(): sha(p) for p in sorted(directory.rglob('*'))
            if p.is_file() and p.suffix.lower() in ARTIFACT_SUFFIXES}


def validate_artifacts(directory):
    for name in SHADERS:
        for suffix in ('.hlsl', '_Shader.cso', '_Shader.h'):
            if not (directory / (name + suffix)).is_file():
                raise ValueError(f'Missing required shader artifact: {name + suffix}')
    for cso in directory.rglob('*.cso'):
        data = cso.read_bytes()
        if not data.startswith(b'DXBC'):
            raise ValueError(f'Not a DXIL/DXBC container: {cso}')
        header = cso.with_suffix('.h')
        if not header.is_file():
            raise ValueError(f'Missing embedded bytecode header: {header}')
        body = re.search(rb'const\s+unsigned\s+char\s+\w+\s*\[\s*\]\s*=\s*\{(.*?)\};',
                         header.read_bytes(), re.S)
        if body is None or bytes(int(v, 16) for v in re.findall(rb'0x([0-9a-fA-F]{2})\b', body[1])) != data:
            raise ValueError(f'Embedded header bytes differ from CSO: {header}')


def freeze(candidate, output):
    commit = git('rev-parse', '--verify', BASE_REF + '^{commit}').decode().strip()
    if len(commit) != 40 or not commit.startswith(BASE_REF):
        raise ValueError(f'{BASE_REF} did not authenticate to its expected commit: {commit}')
    destination = output / 'frozen/candidate/precompile'
    destination.mkdir(parents=True)
    captured = {}
    for source in sorted(candidate.rglob('*')):
        if source.is_file() and source.suffix.lower() in ARTIFACT_SUFFIXES:
            relative = source.relative_to(candidate)
            data = source.read_bytes()  # Every candidate artifact is copied once.
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            captured[relative.as_posix()] = hashlib.sha256(data).hexdigest()
    if not captured or artifact_identity(candidate) != captured:
        raise ValueError('Candidate artifacts changed while their bytes were frozen')
    baseline = output / 'frozen/baseline/precompile'
    baseline.mkdir(parents=True)
    objects = {}
    tree = git('ls-tree', '-rz', commit, '--', BASE_PATH)
    for entry in tree.split(b'\0'):
        if not entry:
            continue
        metadata, name = entry.split(b'\t', 1)
        path = name.decode('utf-8')
        relative = Path(path).relative_to(BASE_PATH)
        if relative.suffix.lower() not in ARTIFACT_SUFFIXES:
            continue
        mode, kind, object_id = metadata.decode().split()
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise ValueError(f'Unsupported baseline tree entry: {path}')
        data = git('cat-file', 'blob', object_id)
        target = baseline / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        objects[relative.as_posix()] = {'git_blob': object_id, 'sha256': hashlib.sha256(data).hexdigest()}
    validate_artifacts(destination)
    validate_artifacts(baseline)
    return {'baseline_ref': BASE_REF, 'baseline_commit': commit,
            'baseline_tree': git('rev-parse', commit + ':' + BASE_PATH).decode().strip(),
            'baseline_git_blobs': objects, 'candidate_source': str(candidate),
            'candidate_directory': str(destination), 'baseline_directory': str(baseline),
            'candidate_files': captured, 'baseline_files': artifact_identity(baseline)}


def child_environment(output):
    environment = os.environ.copy()
    environment['FSRD_GPU_TEST_OUTPUT'] = str(output / 'import_gpu_jobs')
    environment['FSRD_CPP_CACHE'] = '0'
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    if not environment.get('FSRD_VS_ROOT') and Path('F:/VisualStudio/VC/Auxiliary/Build/vcvars64.bat').is_file():
        environment['FSRD_VS_ROOT'] = 'F:/VisualStudio'
    return environment


def probe_runtime(python, output):
    # Imports capture declared immutable gates; they perform no GPU work. The
    # shared helper's import output is confined to this new output subtree.
    code = """import json,sys,numpy as np
from pathlib import Path
sys.path.insert(0,sys.argv[1]); sys.path.insert(0,sys.argv[2])
import fsrd_floor_rr_replay as r
import test_fsrd_floor_texture_quality as t
import test_fsrd_floor_disocclusion_quality as d
import test_fsrd_floor_quality_holdout as h
import fsrd_toolchain as c
toolchain=c._cache_dependencies(c.visual_studio(),('d3d12.lib','dxgi.lib'),Path(sys.argv[3]))
if toolchain is None: raise RuntimeError('Cannot authenticate selected compiler/linker/libraries')
print(json.dumps(dict(python=sys.version,executable=sys.executable,base_prefix=sys.base_prefix,
numpy=np.__version__,numpy_directory=str(Path(np.__file__).parent),signature=r._signature(r.DLL),
toolchain=toolchain['identity'],texture_gates=t.GATES,texture_repeats=t.NATIVE_NOISE_REPEATS,
native_tuning=r.TUNING,
disocclusion_gates=d.GATES,disocclusion_cases=[x['name'] for x in d.cases()],
holdout_manifest=h.MANIFEST,holdout_manifest_sha256=h.MANIFEST_HASH)))
"""
    process = subprocess.run([str(python), '-c', code, str(TESTS), str(HERE), str(output)], cwd=ROOT,
                             env=child_environment(output), capture_output=True, text=True, check=True)
    runtime = json.loads(process.stdout)
    if runtime['texture_repeats'] != 3 or len(runtime['disocclusion_cases']) != 12:
        raise ValueError('Immutable full-suite protocol no longer has 3 repeats / 12 disocclusion cases')
    return runtime


def dependency_identity(runtime):
    paths = {Path(__file__).resolve(), DLL, Path(runtime['executable'])}
    for path in HERE.rglob('*'):
        if path.is_file() and path.suffix.lower() in {'.py', '.cpp', '.h', '.hpp', '.inl'}:
            paths.add(path)
    # Include every local SDK header, rather than guessing only direct includes.
    for path in SDK.rglob('*'):
        if path.is_file() and path.suffix.lower() in {'.h', '.hpp', '.inl', '.lib'}:
            paths.add(path)
    for name in ('FSRDShaderData.h', 'FSRDPreprocessor_Dx12.cpp', 'FSRDPreprocessor_Dx12.h', 'RRTraceAdditive.inl'):
        paths.update((ROOT / 'OptiScaler').rglob(name))
    for directory in (Path(runtime['numpy_directory']), Path(runtime['base_prefix'])):
        patterns = ('*.pyd', '*.dll', '*.py') if directory.name == 'numpy' else ('python*.dll',)
        for pattern in patterns:
            paths.update(directory.rglob(pattern) if directory.name == 'numpy' else directory.glob(pattern))
    paths.update(Path(path) for path in runtime['toolchain']['files'])
    # The compiler's selected system include directories also affect native
    # runners. They are part of the before/after dependency contract.
    for value in runtime['toolchain']['INCLUDE'].split(';'):
        directory = Path(value.strip('"'))
        if directory.is_dir():
            for path in directory.rglob('*'):
                if path.is_file() and path.suffix.lower() in {'.h', '.hpp', '.inl'}:
                    paths.add(path)
    for value in runtime['toolchain']['LIB'].split(';'):
        directory = Path(value.strip('"'))
        if directory.is_dir():
            paths.update(directory.glob('*.lib'))
    return {str(p.resolve()): sha(p) for p in sorted(paths)}


def worker():
    """Child-local adapter: existing CLIs and existing executable parameter."""
    tool, executable, *arguments = sys.argv[2:]
    if tool not in TOOLS:
        raise ValueError('Unknown internal quality tool')
    sys.path.insert(0, str(TESTS))
    sys.path.insert(0, str(HERE))
    if tool in ('texture', 'holdout', 'replay'):
        import fsrd_floor_rr_replay as replay
        replay.NATIVE = Path(executable).resolve()
        native = replay.build_native()  # Fresh compile once; no build cache.
        replay.run_rr = functools.partial(replay.run_rr, executable=native)
    sys.argv = [str(TESTS / TOOLS[tool]), *arguments]
    if tool == 'replay':
        replay.main()
    else:
        runpy.run_path(str(TESTS / TOOLS[tool]), run_name='__main__')


def plan(python, output, frozen):
    candidate, baseline = frozen['candidate_directory'], frozen['baseline_directory']
    result = []
    def add(name, tool, arguments, report=None, paired=None):
        result.append({'name': name, 'tool': tool,
                       'argv': [str(python), str(Path(__file__).resolve()), '--_worker', tool,
                                str(output / 'binaries' / (name + '.exe')), *map(str, arguments)],
                       'existing_cli_argv': [str(python), str(TESTS / TOOLS[tool]), *map(str, arguments)],
                       'output': str(arguments[arguments.index('--output') + 1]),
                       'report': str(report) if report else None, 'paired': paired})
    add('texture', 'texture', ['--shader-dir', candidate, '--baseline-dir', baseline, '--output', output / 'texture'],
        output / 'texture/results.json')
    for side in ('baseline', 'candidate'):
        directory = output / ('disocclusion_' + side)
        arguments = ['--baseline', baseline, '--output', directory, '--export-rr']
        if side == 'baseline':
            arguments += ['--measure']
        else:
            arguments += ['--candidate', candidate, '--baseline-report', output / 'disocclusion_baseline/results.json']
        add('disocclusion_' + side, 'disocclusion', arguments, directory / 'results.json', side)
    for side in ('baseline', 'candidate'):
        for noise in ('independent', 'correlated'):
            for variant in ('floor_on', 'floor_off'):
                directory = output / ('native_' + side) / noise / variant
                add('native_' + side + '_' + noise + '_' + variant, 'replay',
                    ['--input-npz', output / ('disocclusion_' + side) / ('bright_' + noise) / variant / 'rr_inputs.npz',
                     '--output', directory, '--linear-identity-camera', '--signals', 'both'], directory / 'metadata.json', side)
    for side in ('baseline', 'candidate'):
        directory = output / ('actual_' + side)
        arguments = ['--measure', '--baseline', baseline, '--score-actual-rr', output / ('native_' + side),
                     '--exports', output / ('disocclusion_' + side), '--output', directory]
        if side == 'candidate':
            arguments += ['--candidate', candidate, '--actual-baseline-report', output / 'actual_baseline/results.json']
        add('actual_' + side, 'disocclusion', arguments, directory / 'results.json', side)
    add('holdout', 'holdout', ['--shader-dir', candidate, '--baseline-dir', baseline, '--output', output / 'holdout'],
        output / 'holdout/results.json')
    return result


class QualityRun:
    def __init__(self, output, frozen, runtime, dependencies, commands, dry):
        self.output, self.frozen, self.runtime, self.dependencies = output, frozen, runtime, dependencies
        self.report = {'schema': SCHEMA, 'mode': 'dry_validation' if dry else 'strict_full_acceptance',
                       'accepted': False, 'completed': False, 'dry_validated': False,
                       'automatic_retries': 0, 'quality_evidence_cache': False, 'build_cache': False,
                       'frozen': frozen, 'runtime': runtime, 'dependencies_before': dependencies,
                       'command_plan': commands, 'stages': [], 'checks': [], 'baseline_quality_failures': [],
                       'evidence_files': {}, 'native_contexts': [], 'gpu_adapters': [],
                       'dispatch_provenance': {},
                       'required_coverage': {'texture_native_contexts': 54, 'texture_noise_repeats': 3,
                           'disocclusion_cases_per_side': 12, 'native_disocclusion_contexts_per_side': 4,
                           'native_disocclusion_frames_per_context': 32, 'holdout_native_contexts_per_side': 24},
                       'disclosures': [
                           'All existing fixture sources and gates are used unchanged.',
                           'Baseline absolute quality failures are observations, never silently dropped.',
                           'Candidate synthetic and actual native gates plus fresh independent holdout are all mandatory.',
                           'Existing child CLIs receive a freshly compiled executable via the existing run_rr API.',
                           'SpatialTemporalMask0 native disocclusion does not certify positive history reuse or game footage.']}

    def save(self):
        write_json(self.output / 'results.json', self.report)

    def check(self, name, passed, detail=None):
        row = {'name': name, 'passed': bool(passed)}
        if detail is not None:
            row['detail'] = detail
        self.report['checks'].append(row)

    def immutable(self):
        current = dependency_identity(self.runtime)
        self.report['dependencies_after'] = current
        changed = sorted(p for p in set(current) | set(self.dependencies) if current.get(p) != self.dependencies.get(p))
        source = artifact_identity(Path(self.frozen['candidate_source']))
        for key in ('candidate', 'baseline'):
            actual = artifact_identity(Path(self.frozen[key + '_directory']))
            if actual != self.frozen[key + '_files']:
                changed.append('frozen/' + key)
        if source != self.frozen['candidate_files']:
            changed.append('candidate source artifacts')
        self.check('immutable source/artifact/dependency boundary', not changed, changed)
        self.save()
        if changed:
            raise RuntimeError('Inputs changed; further quality comparisons are invalid: ' + ', '.join(changed))

    def remember(self, path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.output):
            raise ValueError(f'Evidence escaped fresh output directory: {path}')
        digest = sha(path)
        old = self.report['evidence_files'].get(str(path))
        if old is not None and old != digest:
            raise ValueError(f'Previously recorded evidence changed: {path}')
        self.report['evidence_files'][str(path)] = digest

    def diagnostics(self, report, name, expected=None):
        jobs = report.get('dispatches', [])
        self.check(name + ' GPU dispatch coverage', bool(jobs) and (expected is None or len(jobs) == expected), len(jobs))
        if name == 'texture':
            job_root = self.output / name / 'gpu_jobs'
            directories = {self.output / name / (side + '_shader_snapshot'): side
                           for side in ('baseline', 'candidate')}
        elif name == 'holdout':
            job_root = self.output / name / 'gpu_jobs'
            directories = {Path(self.frozen[side + '_directory']): side for side in ('baseline', 'candidate')}
        elif name in ('disocclusion_baseline', 'disocclusion_candidate', 'actual_baseline', 'actual_candidate'):
            side = name.rsplit('_', 1)[1]
            job_root = self.output / name / 'shader_jobs'
            directories = {Path(self.frozen[side + '_directory']): side}
        else:
            self.check(name + ' known dispatch provenance plan', False)
            return
        directories = {path.resolve(): side for path, side in directories.items()}
        provenance = self.report['dispatch_provenance'][name] = []
        for index, job in enumerate(jobs):
            self.check(f'{name} GPU {index} zero validation',
                       str(job.get('debug_layer')) == '1' and str(job.get('validation_errors')) == '0'
                       and str(job.get('validation_warnings')) == '0')
            adapter = job.get('adapter')
            self.check(f'{name} GPU {index} adapter disclosed', bool(adapter))
            if adapter and adapter not in self.report['gpu_adapters']:
                self.report['gpu_adapters'].append(adapter)
            # The paired texture/holdout reports combine both sides. Attribute
            # each job using the exact saved CLI input, never by hash membership
            # or an assumed boundary in the combined dispatch list.
            shader = str(job.get('shader'))
            job_path = job_root / (format(index, '03') + '_' + shader) / 'job.txt'
            row = {'index': index, 'shader': shader, 'job': str(job_path)}
            try:
                line = job_path.read_text(encoding='utf-8').splitlines()[0]
                decoder = json.JSONDecoder()
                cso_text, consumed = decoder.raw_decode(line)
                cb_text, consumed_cb = decoder.raw_decode(line[consumed:].lstrip())
                cso, cb = Path(cso_text).resolve(), Path(cb_text).resolve()
                side = directories.get(cso.parent)
                row.update(side=side, cso=str(cso), constants=str(cb), job_sha256=sha(job_path))
                fields = line[consumed:].lstrip()[consumed_cb:].split()
                dimensions = [int(value) for value in fields]
                declared_hash = self.frozen.get(str(side) + '_files', {}).get(shader + '_Shader.cso')
                valid_path = (side is not None and cso.name == shader + '_Shader.cso'
                              and cb == (job_path.parent / 'cb.bin').resolve()
                              and len(dimensions) == 5 and dimensions[:2] == list(job.get('size', []))
                              and dimensions[-1] == job.get('repetitions')
                              and cso.is_file())
                actual_hash = sha(cso) if cso.is_file() else None
                # The unchanged shared runner removes staging .bin files after
                # readback. Preserve its declared constants path honestly; the
                # retained job text and exact CSO are the provenance evidence.
                row.update(cso_sha256=actual_hash, constants_retained=cb.is_file())
                exact = valid_path and actual_hash == declared_hash == job.get('shader_sha256')
                self.check(f'{name} GPU {index} exact side and bytecode', exact, row)
                self.remember(job_path)
                if valid_path:
                    self.remember(cso)
                    if cb.is_file():
                        row['constants_sha256'] = sha(cb)
                        self.remember(cb)
            except Exception as error:
                row['error'] = str(error)
                self.check(f'{name} GPU {index} exact side and bytecode', False, row)
            provenance.append(row)

    def gates(self, report, name, required=True):
        checks = report.get('checks', [])
        self.check(name + ' nonempty immutable gate set', bool(checks))
        failed = [row for row in checks if row.get('passed') is not True]
        if required:
            # Keep every failing gate, rather than just a failed count.
            self.check(name + ' every existing gate passes', not failed, failed)
        else:
            self.report['baseline_quality_failures'].append({'suite': name, 'failed_gates': failed})

    def identity(self, identity, side, name):
        hashes = identity.get('hashes', identity) if isinstance(identity, dict) else {}
        if isinstance(identity, dict) and 'shaders' in identity:
            hashes = {}
            for shader, entries in identity['shaders'].items():
                if shader.endswith('.hlsli'):
                    hashes[shader] = entries.get('source_sha256')
                else:
                    hashes.update({shader + suffix: digest for suffix, digest in entries.items()})
        expected = self.frozen[side + '_files']
        required = {shader + suffix for shader in SHADERS for suffix in ('.hlsl', '_Shader.cso')}
        self.check(name + ' shader artifact identity', required.issubset(hashes)
                   and all(expected.get(k) == v for k, v in hashes.items()))

    def native(self, root, expected_count, frames, dimensions, expected_input=None):
        native = []
        for path in sorted(Path(root).rglob('metadata.json')):
            metadata = read_json(path)
            if metadata.get('kind') != 'actual_signed_amd_rr_gpu_readback':
                continue
            native.append(metadata)
            label = str(path.relative_to(self.output))
            self.remember(path)
            checks = (metadata.get('status') == 'passed' and metadata.get('return_code') == 0
                      and metadata.get('frames') == frames and metadata.get('dimensions') in dimensions
                      and metadata.get('passthrough') is False and metadata.get('context_lifetime') == 'sequence'
                      and metadata.get('signal_flags') == [2, 32]
                      and metadata.get('signature', {}).get('status') == 'Valid'
                      and 'Advanced Micro Devices' in metadata.get('signature', {}).get('signer', '')
                      and metadata.get('adapter', {}).get('debug_layer') is True
                      and metadata.get('dll_sha256') == self.dependencies[str(DLL.resolve())]
                      and metadata.get('python_helper_sha256') == self.dependencies[str((TESTS / TOOLS['replay']).resolve())]
                      and metadata.get('source_sha256') == self.dependencies[str((TESTS / 'fsrd_floor_rr_replay.cpp').resolve())]
                      and metadata.get('shared_runner_sha256') == self.dependencies[str((TESTS / 'fsrd_rr_runner.cpp').resolve())]
                      and metadata.get('tuning') == self.runtime['native_tuning']
                      and metadata.get('reset_frames') == [0]
                      and metadata.get('counters', {}).get('dispatches') == frames
                      and all(metadata.get('counters', {}).get(k) == 0 for k in COUNTERS))
            self.check(label + ' actual signed GPU/SDK zero diagnostics', checks, metadata.get('counters'))
            self.report['native_contexts'].append({'metadata': str(path), 'frames': frames,
                'dimensions': metadata.get('dimensions'), 'adapter': metadata.get('adapter'),
                'provider': metadata.get('provider'), 'dll_sha256': metadata.get('dll_sha256'),
                'executable': metadata.get('executable'), 'executable_sha256': metadata.get('executable_sha256'),
                'controls_sha256': metadata.get('applied_controls', {}).get('sha256'),
                'counters': metadata.get('counters')})
            projection = metadata.get('viewport', {}).get('logical_projection', metadata.get('projection'))
            near, far = .1, 1000.
            f32 = lambda value: struct.unpack('<f', struct.pack('<f', value))[0]
            expected_projection = [[.5,0,0,0],[0,.5,0,0],[0,0,f32(far/(far-near)),1],
                                   [0,0,f32(-near*far/(far-near)),0]]
            expected_view = [[int(row == column) for column in range(4)] for row in range(4)]
            self.check(label + ' matched camera/reset protocol',
                       projection == expected_projection and metadata.get('view') == expected_view
                       and metadata.get('jitters') == [[0., 0.] for _ in range(frames)])
            entries = list(metadata.get('inputs', [])) + list(metadata.get('readback', {}).values())
            entries += [metadata.get(k, {}) for k in ('applied_controls', 'logical_readback_npz', 'physical_readback_npz')]
            entries.append({'path': metadata.get('executable'), 'sha256': metadata.get('executable_sha256')})
            executable = Path(metadata.get('executable', '')).resolve()
            self.check(label + ' fresh private native executable', executable.is_relative_to(self.output / 'binaries'))
            for entry in entries:
                if not entry:
                    continue
                file = Path(entry.get('path', ''))
                self.check(label + ' artifact ' + file.name, file.is_file() and sha(file) == entry.get('sha256'))
                if file.is_file():
                    self.remember(file)
            self.check(label + ' finite actual readbacks',
                       set(metadata.get('readback', {})) == {'diffuse', 'specular'}
                       and all(e.get('finite') is True for e in metadata['readback'].values()))
            controls = metadata.get('applied_controls', {}).get('frames', [])
            self.check(label + ' full applied control trace', len(controls) == frames and all(
                row.get('frame') == index and row.get('reset') is (index == 0)
                and row.get('jitter') == [0., 0.] for index, row in enumerate(controls)))
            if expected_input:
                provenance = metadata.get('input_provenance', {})
                self.check(label + ' exact exported NPZ', isinstance(provenance, dict)
                           and provenance.get('npz') == str(Path(expected_input).resolve())
                           and provenance.get('sha256') == sha(expected_input))
        self.check(str(Path(root).relative_to(self.output)) + ' native context coverage', len(native) == expected_count, len(native))
        return native

    def validate_report(self, stage, report):
        name, side = stage['name'], stage.get('paired')
        if stage['tool'] == 'replay':
            arguments = stage['existing_cli_argv']
            native_root = Path(arguments[arguments.index('--output') + 1])
            source = Path(arguments[arguments.index('--input-npz') + 1])
            self.native(native_root, 1, 32, [[97, 65]], source)
            return
        self.check(name + ' harness source identity', report.get('test_source_sha256') == self.dependencies[str((TESTS / TOOLS[stage['tool']]).resolve())])
        declared = report.get('dependency_source_hashes', report.get('dependency_identity', {}).get('sources', {}))
        self.check(name + ' declared dependency hashes',
                   all(self.dependencies.get(str((TESTS / filename).resolve())) == digest for filename, digest in declared.items()))
        if name == 'texture':
            self.check('texture strict complete acceptance', report.get('schema') == 'fsrd_floor_texture_quality_v4'
                       and report.get('mode') == 'acceptance' and report.get('accepted') is True
                       and report.get('gates') == self.runtime['texture_gates'])
            protocol = report.get('scoring_protocol', {})
            self.check('texture fixed native repeats', protocol.get('native_runs_per_input') == {'clean': 1, 'noise': 3}
                       and protocol.get('automatic_retries') == 0)
            for key, artifact_side in (('records', 'candidate'), ('baseline_records', 'baseline')):
                rows = report.get(key, [])
                clean = {(r.get('case'), r.get('exposure')) for r in rows if r.get('stage') == 'FINAL'
                         and r.get('rr_model') == 'actual_amd_rr_frame11'}
                sequences = {(r.get('case'), r.get('repeat')) for r in rows if r.get('stage') == 'FINAL_NOISE_SEQUENCE'
                             and r.get('rr_model') == 'actual_amd_rr' and r.get('frames') == 12 and r.get('scored_frames') == list(range(6,12))}
                self.check('texture ' + artifact_side + ' full clean and three-repeat rows',
                           len(clean) == 21 and {r[1] for r in clean} == {.1, 1, 8}
                           and sequences == {(n, repeat) for n in ('flat_noise', 'woven') for repeat in range(3)})
            self.identity(report.get('shader_identity'), 'candidate', name)
            self.identity(report.get('frozen_baseline'), 'baseline', name + ' baseline')
            self.check('texture helper source identity', report.get('gpu_test_helper_sha256')
                       == self.dependencies[str((TESTS / 'run_fsrd_gpu_tests.py').resolve())])
            self.gates(report, name)
            self.diagnostics(report, name, 948)
            self.native(self.output / name, 54, 12, [[97, 73]])
        elif name.startswith('disocclusion_'):
            baseline = side == 'baseline'
            self.check(name + ' full12 protocol', report.get('schema') == 'fsrd-floor-disocclusion-v2'
                       and report.get('mode') == ('measure' if baseline else 'acceptance')
                       and report.get('gates') == self.runtime['disocclusion_gates']
                       and report.get('dimensions') == [97, 65] and report.get('frames') == 32
                       and len(report.get('records', [])) == 12
                       and {r['case']['name'] for r in report['records']} == set(self.runtime['disocclusion_cases']))
            self.identity(report.get('shader_identity'), side, name)
            self.gates(report, name, not baseline)
            self.diagnostics(report, name, 3840)
            if not baseline:
                self.check(name + ' strict suite acceptance', report.get('accepted') is True)
                self.paired_reports(name, 'disocclusion_baseline', report,
                                    ('test_source_sha256', 'dependency_identity', 'fixture_source_sha256', 'gates', 'dimensions', 'frames'))
        elif name.startswith('actual_'):
            self.check(name + ' actual full composition protocol', report.get('schema') == 'fsrd-floor-disocclusion-v2'
                       and report.get('mode') == 'actual_final_measurement'
                       and report.get('rr_kind') == 'actual_signed_amd_rr_final'
                       and report.get('camera_protocol') == 'matched_seed_rays_perspective'
                       and report.get('gates') == self.runtime['disocclusion_gates']
                       and len(report.get('records', [])) == 2 and len(report.get('native_sequences', [])) == 4
                       and {r['case']['name'] for r in report['records']} == {'bright_independent', 'bright_correlated'})
            self.identity(report.get('composition_identity'), side, name)
            self.identity(report.get('exported_shader_identity'), side, name + ' export')
            self.gates(report, name, side == 'candidate')
            self.diagnostics(report, name, 128)
            if side == 'candidate':
                self.paired_reports(name, 'actual_baseline', report,
                                    ('test_source_sha256', 'dependency_identity', 'gates', 'camera_protocol'))
        elif name == 'holdout':
            self.check('holdout fresh complete strict acceptance', report.get('schema') == 'fsrd_floor_quality_holdout_v1'
                       and report.get('completed') is True and report.get('mode') == 'acceptance'
                       and report.get('accepted') is True and report.get('native_enabled') is True
                       and report.get('manifest_sha256') == self.runtime['holdout_manifest_sha256']
                       and report.get('manifest') == self.runtime['holdout_manifest']
                       and len(report.get('native_metadata', [])) == 24
                       and len(report.get('baseline_native_metadata', [])) == 24)
            self.identity(report.get('shader_identity'), 'candidate', name)
            self.identity(report.get('frozen_baseline'), 'baseline', name + ' baseline')
            self.gates(report, name)
            self.diagnostics(report, name)
            self.native(self.output / name, 48, 32, [[113, 79], [80, 61]])

    def paired_reports(self, name, baseline, report, keys):
        previous = read_json(self.output / baseline / 'results.json')
        self.check(name + ' unchanged paired fixtures/gates/dependencies', all(report.get(k) == previous.get(k) for k in keys)
                   and {r['case']['name']: r['input_sha256'] for r in report['records']}
                   == {r['case']['name']: r['input_sha256'] for r in previous['records']})

    def execute(self, stage):
        self.immutable()
        if stage['name'] == 'holdout':
            self.unchanged_evidence()
            failed = [check['name'] for check in self.report['checks'] if not check['passed']]
            if failed:
                self.report['stages'].append({'name': 'holdout', 'status': 'blocked_by_failed_primary_checks',
                    'started': False, 'failed_primary_checks': failed})
                self.check('holdout eligibility: every primary required check passes', False, failed)
                self.report.update(accepted=False, completed=False, holdout_started=False,
                    stop_reason='Primary quality/infrastructure checks failed; independent holdout was not started')
                self.save()
                print('FAILED CLOSED BEFORE HOLDOUT: primary checks failed; ' + str(self.output / 'results.json'), flush=True)
                return False
        missing = [Path(stage['argv'][index + 1]) for index, value in enumerate(stage['argv'])
                   if value in ('--baseline-report', '--actual-baseline-report', '--input-npz')
                   and not Path(stage['argv'][index + 1]).is_file()]
        log = self.output / 'logs' / (stage['name'] + '.log')
        log.parent.mkdir(exist_ok=True)
        state = {'name': stage['name'], 'argv': stage['argv'], 'log': str(log), 'status': 'running'}
        self.report['stages'].append(state)
        self.save()
        if missing:
            state.update(status='blocked_by_missing_fresh_evidence', missing=[str(p) for p in missing])
            self.check(stage['name'] + ' upstream evidence exists', False, state['missing'])
            self.save()
            return
        print('START ' + stage['name'], flush=True)
        with log.open('w', encoding='utf-8') as stream:
            process = subprocess.run(stage['argv'], cwd=ROOT, env=child_environment(Path(stage['output'])),
                                     stdout=stream, stderr=subprocess.STDOUT)
        state.update(return_code=process.returncode, status='finished', report=stage['report'])
        self.check(stage['name'] + ' subprocess exit zero', process.returncode == 0, process.returncode)
        self.immutable()
        try:
            report = read_json(stage['report'])
            self.validate_report(stage, report)
        except Exception as error:
            state['validation_error'] = str(error)
            self.check(stage['name'] + ' complete evidence validation', False, traceback.format_exc())
        # Preserve the reports, exported/scored arrays and executable identities.
        roots = [Path(stage['output'])]
        if stage['tool'] == 'replay':
            roots.append(Path(stage['report']).parent)
        for directory in roots:
            for path in sorted(directory.rglob('*')):
                if path.is_file() and path.suffix.lower() in {'.json', '.npz', '.exe'}:
                    self.remember(path)
        self.remember(log)
        self.save()
        print('FINISH ' + stage['name'] + ' exit=' + str(process.returncode), flush=True)
        return True

    def unchanged_evidence(self):
        changed = [path for path, digest in self.report['evidence_files'].items()
                   if not Path(path).is_file() or sha(path) != digest]
        self.check('all previously recorded evidence remains unchanged', not changed, changed)

    def finish(self):
        self.immutable()
        self.unchanged_evidence()
        self.check('all required actual contexts executed', len(self.report['native_contexts']) == 110,
                   len(self.report['native_contexts']))
        contexts = {row['metadata']: row for row in self.report['native_contexts']}
        for noise in ('independent', 'correlated'):
            for variant in ('floor_on', 'floor_off'):
                rows = [contexts.get(str(self.output / ('native_' + side) / noise / variant / 'metadata.json'))
                        for side in ('baseline', 'candidate')]
                self.check(f'paired actual {noise}/{variant} identical controls/provider',
                           all(row is not None for row in rows) and all(rows[0].get(key) == rows[1].get(key)
                               for key in ('controls_sha256', 'adapter', 'provider', 'dll_sha256', 'frames', 'dimensions')))
        self.report['completed'] = True
        self.report['accepted'] = all(check['passed'] for check in self.report['checks'])
        self.save()
        failed = [check for check in self.report['checks'] if not check['passed']]
        print(f"{'ACCEPTED' if not failed else 'FAILED'}: {len(failed)} strict failures; {self.output / 'results.json'}", flush=True)
        return 0 if not failed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--candidate-dir', type=Path, default=PRE, help='Candidate precompile artifacts to freeze once')
    parser.add_argument('--output', type=Path, required=True, help='Fresh, nonexistent deterministic output subtree')
    runtime = ROOT / '.venv/Scripts/python.exe'
    parser.add_argument('--python', type=Path, default=runtime if runtime.is_file() else Path(sys.executable),
                        help='Existing Python/numpy runtime; no packages are installed')
    parser.add_argument('--dry-run', action='store_true', help='Freeze/authenticate and validate plan only; never accept or dispatch')
    args = parser.parse_args()
    output, candidate, python = args.output.resolve(), args.candidate_dir.resolve(), args.python.resolve()
    if output.exists():
        parser.error('Output already exists; fresh evidence requires a new subtree')
    if not candidate.is_dir() or not python.is_file() or not DLL.is_file():
        parser.error('Candidate directory, runtime interpreter and signed AMD DLL are required')
    if output.is_relative_to(candidate) or candidate.is_relative_to(output):
        parser.error('Output and candidate directory must be disjoint')
    output.mkdir(parents=True)
    run = None
    try:
        frozen = freeze(candidate, output)
        runtime = probe_runtime(python, output)
        dependencies = dependency_identity(runtime)
        commands = plan(python, output, frozen)
        run = QualityRun(output, frozen, runtime, dependencies, commands, args.dry_run)
        run.save()
        run.immutable()
        if args.dry_run:
            run.report['dry_validated'] = True
            run.report['completed'] = True
            run.save()
            print(f'DRY VALIDATED (never accepted): {len(commands)} full stages; {output / "results.json"}', flush=True)
            return 0
        for command in commands:
            if run.execute(command) is False:
                return 1
        return run.finish()
    except Exception as error:
        if run is not None:
            run.report['accepted'] = False
            run.report['fatal_error'] = str(error)
            run.report['fatal_traceback'] = traceback.format_exc()
            run.save()
        else:
            write_json(output / 'results.json', {'schema': SCHEMA, 'accepted': False, 'completed': False,
                       'mode': 'dry_validation' if args.dry_run else 'strict_full_acceptance',
                       'fatal_error': str(error), 'fatal_traceback': traceback.format_exc()})
        print(f'FAILED CLOSED: {error}; {output / "results.json"}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--_worker':
        worker()
    else:
        raise SystemExit(main())
