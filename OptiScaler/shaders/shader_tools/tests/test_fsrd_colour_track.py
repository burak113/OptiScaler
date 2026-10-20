"""Post-RR colour tracking (task 25 T2) GPU fixture: run through lead_ops/run_task_test.py.

The fixture drives the three production colour-track CSOs and the production composition CSO on synthetic frames,
and compares the production composition against the BASE composition CSO compiled from f97d5d040 - the OFF-path
byte-identity claim. That base source is read out of git at that exact commit, so the test keeps its reference
after this branch is committed (never HEAD, which would follow the change under test).
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))
from fsrd_toolchain import compile_cpp, dxc  # noqa: E402

BASE_COMMIT = 'f97d5d040'
BASE_SOURCE = 'OptiScaler/shaders/fsrd_preprocess/precompile/FSRDOutputComp.hlsl'


def binding_counts():
    """Static guard for the wiring bug the first audit found: every ComputeState must be initialised with exactly the
    SRV/UAV counts its shader declares and its dispatch binds, because ComputeState puts the UAV descriptor table at
    heap index numSrvs - a mismatch silently moves u0 onto an unwritten descriptor (the correction then lands
    nowhere, or on a foreign texture). Read from the sources, so the check follows the code."""
    cpp = (ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp').read_text(encoding='utf-8')
    pre = ROOT / 'OptiScaler/shaders/fsrd_preprocess/precompile'
    checks = []
    for name, shader in (('Stats', 'FSRDColourTrackStats.hlsl'), ('Track', 'FSRDColourTrackTrack.hlsl'),
                         ('Apply', 'FSRDColourTrackApply.hlsl')):
        text = (pre / shader).read_text(encoding='utf-8')
        srvs = text.count('register(t')
        uavs = text.count('register(u')
        marker = f'm_colourTrack{name}Shader.Initialize('
        start = cpp.index(marker)
        call = cpp[start:cpp.index(');', start)]
        declared = [int(x) for x in call.split(',')[-3:-1]]
        dispatch_marker = f'm_colourTrack{name}Shader.Dispatch('
        dstart = cpp.index(dispatch_marker)
        dcall = cpp[dstart:cpp.index(');', dstart)]
        bound_inputs = dcall.count('.Get()') if False else None
        # The dispatch's input/output arrays are named per pass in the source; count their elements.
        array_names = {'Stats': ('statsInputs', 'statsOutputs'), 'Track': ('trackInputs', 'trackOutputs'),
                       'Apply': ('applyInputs', 'applyOutputs')}[name]
        def array_len(array, after):
            # Anchor the search after this pass's own Initialize call: the post-flick pass names its arrays
            # applyInputs/applyOutputs too, and an unanchored search finds those (a test bug, not a wiring bug).
            astart = cpp.index(f'ID3D12Resource* {array}[] {{', after)
            body = cpp[astart:cpp.index('};', astart)]
            return body.count(',') + 1
        checks.append(dict(pass_name=name, shader=shader, declared_srvs=srvs, declared_uavs=uavs,
                           initialized_srvs=declared[0], initialized_uavs=declared[1],
                           bound_inputs=array_len(array_names[0], start),
                           bound_outputs=array_len(array_names[1], start)))
    assert all(c['declared_srvs'] == c['initialized_srvs'] == c['bound_inputs'] and
               c['declared_uavs'] == c['initialized_uavs'] == c['bound_outputs'] for c in checks), checks
    # The composition writes the tracker's target at FULL resolution (the stats pass box-averages it to quarter res).
    assert '.OutTarget = colourTrackFrame ? m_colourTrackInput.Get() : nullptr' in cpp, 'composition target binding'
    return checks


def main():
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    assert not (out / 'job.json').exists(), 'Fresh output directory required'
    (out / 'pch.h').write_text('#pragma once\n')
    # The shared fixture pulls in the production bridge translation unit, which needs the same two generated
    # headers the flat-albedo runner produces: an empty pch and the native consumer shader bytes.
    consumer = out / 'consumer.cso'
    subprocess.run([str(dxc()), '-T', 'cs_6_2', '-E', 'CSMain', '-O3', '-force-rootsig-ver', 'rootsig_1_0',
                    str(HERE / 'nrd_bridge_consumer_fixture.hlsl'), '-Fo', str(consumer)], check=True)
    (out / 'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[] = {' +
                                           ','.join(str(x) for x in consumer.read_bytes()) + '};\n')

    # The base composition source at the pinned commit. A missing commit or file is a hard failure: a fixture
    # that silently skips its OFF reference would prove nothing.
    base_source = subprocess.run(['git', '-C', str(ROOT), 'show', f'{BASE_COMMIT}:{BASE_SOURCE}'],
                                 capture_output=True, text=True, check=True).stdout
    assert 'FLAGS_COLOUR_TRACK_TARGET' not in base_source, 'the base source is the pre-change composition shader'
    assert 'OutTarget' not in base_source, 'the base source has no colour-track target'
    (out / 'base_comp.hlsl').write_text(base_source, encoding='utf-8')
    base_cso = out / 'base_comp.cso'
    subprocess.run([str(dxc()), '-T', 'cs_6_2', '-E', 'CSMain', '-enable-16bit-types', '-O3', '-Qstrip_debug',
                    '-Qstrip_reflect', '-I', str(HERE.parent.parent / 'fsrd_preprocess' / 'precompile'),
                    str(out / 'base_comp.hlsl'), '-Fo', str(base_cso)], check=True)
    (out / 'base_comp_shader.h').write_text(
        'const unsigned char BaseOutputComp_cso[] = {' +
        ','.join(str(x) for x in base_cso.read_bytes()) + '};\n')

    exe = out / 'colour-track.exe'
    compile_cpp(HERE / 'fsrd_colour_track.cpp', exe, ['d3d12.lib', 'dxgi.lib', 'd3dcompiler.lib'],
                [out, ROOT / 'OptiScaler', ROOT / 'OptiScaler/include', ROOT / 'external/vulkan/include',
             ROOT / 'external/nvngx_dlss_sdk', ROOT / 'external/xess/inc/xess', ROOT / 'external/xess/inc/xell',
             ROOT / 'external/xess/inc/xess_fg', ROOT / 'external/FidelityFX-SDK/ffx-api/include/ffx_api',
             ROOT / 'external/simpleini', ROOT / 'external/unordered_dense/include', ROOT / 'external/spdlog/include',
             ROOT / 'external/freetype', ROOT / 'external/streamline', ROOT / 'external/streamline1',
             ROOT / 'external/nvapi', ROOT / 'external/nlohmann', ROOT / 'external/fakenvapi',
             ROOT / 'external/magic_enum/include/magic_enum', ROOT / 'external/AntiLag2-SDK',
             ROOT / 'external/latencyflex'])
    (out / 'job.json').write_text(json.dumps({'width': 1505, 'height': 847}) + '\n')
    start = time.perf_counter()
    run = subprocess.run([str(exe), str(out / 'job.json')], capture_output=True, text=True, timeout=600,
                         creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    (out / 'stdout.log').write_text(run.stdout)
    (out / 'stderr.log').write_text(run.stderr)
    print(run.stdout, flush=True)
    if run.returncode:
        print(run.stderr, flush=True)
    run.check_returncode()
    assert 'PASS checks=' in run.stdout and 'debug_errors=0 debug_warnings=0' in run.stdout
    costs = {}
    for line in run.stdout.splitlines():
        if line.startswith('colour-track cost at '):
            size = line.split(' at ')[1].split(':')[0]
            costs[size] = line
    bindings = binding_counts()
    (out / 'result.json').write_text(json.dumps(dict(
        passed=True, seconds=time.perf_counter() - start, exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
        base_commit=BASE_COMMIT, costs=costs, bindings=bindings,
        scope='production colour-track CSOs + production composition CSO vs the base composition CSO (f97d5d040) on '
              'synthetic frames in the production conventions; no capture, no real RR, no in-game claim'),
        indent=2) + '\n')
    print(json.dumps(dict(passed=True, output=str(out), costs=costs)), flush=True)


if __name__ == '__main__':
    main()
