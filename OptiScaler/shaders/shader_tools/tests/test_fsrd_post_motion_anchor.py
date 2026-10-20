"""Post-motion level anchor (task 25 T3 ii) GPU fixture + static wiring guard.

Run through lead_ops/run_task_test.py. What it guards, and why:
  1) binding_counts(): every anchor ComputeState is initialised with exactly the SRV/UAV counts its shader
     declares and its dispatch binds (ComputeState puts the UAV table at heap index numSrvs, so a mismatch moves
     u0 onto an unwritten descriptor - the colour-track audit's HIGH finding, guarded here for these passes too).
  2) the OFF gate: the dispatcher returns before any allocation, barrier or dispatch when the option is off, and
     the call site cannot run on a debug frame; no EXISTING shader source or CSO may change (the anchor only adds
     shaders), so the OFF path of every earlier pass is byte-identical by construction.
  3) the behaviour + cost fixture (fsrd_post_motion_anchor.cpp): the box mean, the recall, the band cap, the
     reject guard (an oversized excess keeps gain 1), strength 0 as a no-op, and the interleaved cost at
    1505x847 and 2560x1440.
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

PASSES = (('StatsRecall', 'FSRDPostMotionAnchorStatsRecall.hlsl'),
          ('Gain', 'FSRDPostMotionAnchorGain.hlsl'),
          ('Apply', 'FSRDPostMotionAnchorApply.hlsl'))
SHADER_NAME = {'StatsRecall': 'm_postMotionStatsRecallShader', 'Gain': 'm_postMotionGainShader',
               'Apply': 'm_postMotionApplyShader'}
ARRAYS = {'StatsRecall': ('statsInputs', 'statsOutputs'), 'Gain': ('gainInputs', 'gainOutputs'),
          'Apply': ('applyInputs', 'applyOutputs')}


def binding_counts():
    cpp = (ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp').read_text(encoding='utf-8')
    pre = ROOT / 'OptiScaler/shaders/fsrd_preprocess/precompile'
    checks = []
    for name, shader in PASSES:
        text = (pre / shader).read_text(encoding='utf-8')
        srvs = text.count('register(t')
        uavs = text.count('register(u')
        marker = f'{SHADER_NAME[name]}.Initialize('
        start = cpp.index(marker)
        call = cpp[start:cpp.index(');', start)]
        declared = [int(x) for x in call.split(',')[-3:-1]]
        # The dispatch's arrays are anchored after this pass's own initialisation: an unanchored search finds the
        # post-flick pass's identically named arrays (a test bug the colour-track guard hit).
        def array_len(array):
            astart = cpp.index(f'ID3D12Resource* {array}[] {{', start)
            body = cpp[astart:cpp.index('};', astart)]
            return body.count(',') + 1
        checks.append(dict(pass_name=name, shader=shader, declared_srvs=srvs, declared_uavs=uavs,
                           initialized_srvs=declared[0], initialized_uavs=declared[1],
                           bound_inputs=array_len(ARRAYS[name][0]), bound_outputs=array_len(ARRAYS[name][1])))
    assert all(c['declared_srvs'] == c['initialized_srvs'] == c['bound_inputs'] and
               c['declared_uavs'] == c['initialized_uavs'] == c['bound_outputs'] for c in checks), checks
    return checks


def off_gate():
    """The OFF path: an early return before any allocation, and no change to any shader that already existed."""
    cpp = (ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp').read_text(encoding='utf-8')
    body = cpp[cpp.index('void DispatchPostMotionAnchor('):]
    body = body[:body.index('\n    }\n')]
    head = body[:body.index('if (!EnsurePostMotionAnchor')]
    assert 'if (!desc.PostMotionAnchor)' in head and 'return;' in head, 'the off path returns early'
    for forbidden in ('CreateTexture2D', 'AddBarrier', 'Dispatch(', 'Initialize('):
        assert forbidden not in head, f'the off path must not reach {forbidden}'
    assert 'if (!desc.PostMotionAnchor) return false;' in cpp, 'the frame gate refuses an off request'
    # No existing shader may change: the anchor adds three new sources/CSOs and touches nothing else, which is what
    # makes every earlier pass's OFF path byte-identical. New files are the three anchor sources and their CSOs.
    changed = subprocess.run(['git', '-C', str(ROOT), 'diff', '--name-only', 'HEAD'],
                             capture_output=True, text=True, check=True).stdout.split()
    allowed_existing = {'OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp',
                        'OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.h',
                        'OptiScaler/shaders/shader_tools/build_fsrd_shader.py',
                        'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp',
                        'OptiScaler/menu/menu_common.cpp', 'OptiScaler/Config.cpp', 'OptiScaler/Config.h'}
    # The anchor's OWN three shaders are allowed to change once they are tracked (the first version of this check
    # only saw them as new files; an audit fix later edited them, which is legitimate iteration on the feature's own
    # sources - what must never change is a shader from an earlier feature, and that is what the check still guards).
    for anchor in ('StatsRecall', 'Gain', 'Apply'):
        for suffix in ('.hlsl', '_Shader.cso', '_Shader.h'):
            allowed_existing.add('OptiScaler/shaders/fsrd_preprocess/precompile/FSRDPostMotionAnchor' + anchor + suffix)
    offenders = [f for f in changed if 'precompile' in f and f not in allowed_existing]
    assert not offenders, f'an existing shader source or CSO changed: {offenders}'
    return dict(changed_files=changed, offenders=offenders)


def main():
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    assert not (out / 'job.json').exists(), 'Fresh output directory required'
    (out / 'pch.h').write_text('#pragma once\n')
    consumer = out / 'consumer.cso'
    subprocess.run([str(dxc()), '-T', 'cs_6_2', '-E', 'CSMain', '-O3', '-force-rootsig-ver', 'rootsig_1_0',
                    str(HERE / 'nrd_bridge_consumer_fixture.hlsl'), '-Fo', str(consumer)], check=True)
    (out / 'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[] = {' +
                                           ','.join(str(x) for x in consumer.read_bytes()) + '};\n')
    # DEBUG ONLY (SA7 scratch): a copy of the statistics/recall shader that dumps its recall intermediates, so a
    # failing recall can be read off instead of guessed. The production shader is not touched.
    debug_source = Path('F:/FSRD/sol_batch/25-postflick-level/scratch/sa7/debug/FSRDPostMotionAnchorStatsRecallDbg.hlsl')
    debug_cso = out / 'anchor_debug.cso'
    if debug_source.exists():
        subprocess.run([str(dxc()), '-T', 'cs_6_2', '-E', 'CSMain', '-enable-16bit-types', '-O3', '-Qstrip_debug',
                        '-Qstrip_reflect', '-I', str(ROOT / 'OptiScaler/shaders/fsrd_preprocess/precompile'),
                        str(debug_source), '-Fo', str(debug_cso)], check=True)
    else:
        debug_cso.write_bytes(b'')
    (out / 'post_motion_anchor_debug_shader.h').write_text(
        'const unsigned char FSRDPostMotionAnchorStatsRecallDbg_cso[] = {' +
        ','.join(str(x) for x in debug_cso.read_bytes()) + ',0};\n')
    exe = out / 'post-motion-anchor.exe'
    compile_cpp(HERE / 'fsrd_post_motion_anchor.cpp', exe, ['d3d12.lib', 'dxgi.lib', 'd3dcompiler.lib'],
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
    run = subprocess.run([str(exe), str(out / 'job.json')], capture_output=True, text=True, timeout=900,
                         creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    (out / 'stdout.log').write_text(run.stdout)
    (out / 'stderr.log').write_text(run.stderr)
    print(run.stdout, flush=True)
    if run.returncode:
        print(run.stderr, flush=True)
    run.check_returncode()
    assert 'PASS checks=' in run.stdout and 'debug_errors=0 debug_warnings=0' in run.stdout
    costs = [line for line in run.stdout.splitlines() if line.startswith('anchor cost at ')]
    bindings = binding_counts()
    gate = off_gate()
    (out / 'result.json').write_text(json.dumps(dict(
        passed=True, seconds=time.perf_counter() - start, exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
        costs=costs, bindings=bindings, off_gate=gate,
        scope='production anchor CSOs (stats/recall, gain, apply) on synthetic frames in the production '
              'conventions; no capture, no real RR, no in-game claim'), indent=2) + '\n')
    print(json.dumps(dict(passed=True, output=str(out), costs=costs)), flush=True)


if __name__ == '__main__':
    main()
