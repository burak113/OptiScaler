"""Actual native option -> physical provider input -> native commit regression.

Default data is synthetic 64x64 plus a 96x72 DRS check; no game capture or task
folder is needed. Run using the normal GPU-test wrapper, which serializes GPU
work and supplies FSRD_GPU_TEST_OUTPUT. The provider is the existing mock; the
actual production GPU anchor passes and provider-input resource are tested.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=Path(os.environ.get('FSRD_NATIVE_ANCHOR_SOURCE_ROOT',str(HERE.parents[3]))).resolve()
TOOLS=ROOT/'OptiScaler/shaders/shader_tools'
if not (TOOLS/'fsrd_toolchain.py').is_file():
    TOOLS=Path(os.environ['FSRD_NATIVE_ANCHOR_TEST_ROOT'])/'OptiScaler/shaders/shader_tools'
sys.path.insert(0,str(TOOLS))
from fsrd_toolchain import compile_cpp,dxc


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    out=Path(os.environ['FSRD_GPU_TEST_OUTPUT']).resolve();out.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('FSRD_CPP_CACHE',str(out/'cpp_cache'))
    (out/'pch.h').write_text('#pragma once\n')
    tests=ROOT/'OptiScaler/shaders/shader_tools/tests'
    if not tests.is_dir():
        # A source overlay may deliberately contain only production fsrd files.
        tests=Path(os.environ['FSRD_NATIVE_ANCHOR_TEST_ROOT'])/'OptiScaler/shaders/shader_tools/tests'
    fixture=tests/'nrd_bridge_rr_fixture.cpp'
    actual=ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp'
    text=fixture.read_text(encoding='utf-8')
    needle='#include "../../fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp"'
    assert text.count(needle)==1
    text=text.replace(needle,'#include "'+actual.as_posix()+'"',1)
    callback='void RecordTestProviderWrites(ID3D12GraphicsCommandList* list, ID3D12Resource* spec, ID3D12Resource* diff)\n{'
    assert text.count(callback)==1
    text=text.replace(callback,'void NativeProviderBoundary(ID3D12GraphicsCommandList*,ID3D12Resource*,ID3D12Resource*);\n'+callback+
        '\n    NativeProviderBoundary(list,static_cast<ID3D12Resource*>(FfxApiProxy::lastSpecular.signal.input.resource),'+
        'static_cast<ID3D12Resource*>(FfxApiProxy::lastDiffuse.signal.input.resource));',1)
    timing_no_debug=os.environ.get('FSRD_NATIVE_ANCHOR_TIMING_NO_DEBUG')=='1'
    if timing_no_debug:
        debug='ComPtr<ID3D12Debug> debug; hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug))); debug->EnableDebugLayer();'
        assert text.count(debug)==1 and text.count('hr(device.As(&info));')==1
        text=text.replace(debug,'// Timing-only host: D3D12 debug layer is not enabled.',1)
        text=text.replace('hr(device.As(&info));','// No InfoQueue is requested for the timing-only device.',1)
        text=text.replace('void checkDebug()\n    {','void checkDebug()\n    {\n        if(!info) return;',1)
    (out/'nrd_bridge_rr_fixture.cpp').write_text(text,encoding='utf-8')
    source=Path(os.environ.get('FSRD_NATIVE_ANCHOR_FIXTURE_CPP',str(HERE/'fsrd_native_post_motion_anchor.cpp')))
    (out/source.name).write_bytes(source.read_bytes())
    consumer=out/'consumer.cso'
    skip_build=os.environ.get('FSRD_NATIVE_ANCHOR_SKIP_BUILD')=='1'
    if not skip_build:
        subprocess.run([str(dxc()),'-T','cs_6_2','-E','CSMain','-O3','-force-rootsig-ver','rootsig_1_0',
            str(tests/'nrd_bridge_consumer_fixture.hlsl'),'-Fo',str(consumer)],check=True)
    (out/'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[] = {'+
        ','.join(str(x) for x in consumer.read_bytes())+'};\n')
    include=[out,HERE,tests,ROOT/'OptiScaler/shaders/fsrd_preprocess',ROOT/'OptiScaler',ROOT/'OptiScaler/include']
    dependencies=Path(os.environ.get('FSRD_NATIVE_ANCHOR_TEST_ROOT',str(ROOT))).resolve()
    if dependencies!=ROOT:
        include.extend([dependencies/'OptiScaler/shaders/fsrd_preprocess',dependencies/'OptiScaler',dependencies/'OptiScaler/include'])
    include.extend(dependencies/p for p in ('external/vulkan/include','external/nvngx_dlss_sdk',
        'external/xess/inc/xess','external/xess/inc/xell','external/xess/inc/xess_fg',
        'external/FidelityFX-SDK/ffx-api/include/ffx_api','external/simpleini',
        'external/unordered_dense/include','external/spdlog/include','external/freetype',
        'external/streamline','external/streamline1','external/nvapi','external/nlohmann',
        'external/fakenvapi','external/magic_enum/include/magic_enum','external/AntiLag2-SDK','external/latencyflex'))
    exe=out/'native-post-motion-anchor.exe'
    if not skip_build:
        compile_cpp(out/source.name,exe,['d3d12.lib','dxgi.lib','d3dcompiler.lib'],include)
    production=ROOT/'OptiScaler/shaders/fsrd_preprocess'
    files=[actual,production/'FSRDNrdBridgeRR_Dx12.h',production/'FSRDNrdPostMotionAnchor_Dx12.h',
           production/'FSRDPostMotionAnchorConstants.h']
    for stem in ('FSRDNrdPostMotionAnchorStatsRecall','FSRDNrdPostMotionAnchorGain','FSRDPostMotionAnchorApply','FSRDNrdBridgePureCommit'):
        files.extend([production/'precompile'/(stem+'_Shader.h'),production/'precompile'/(stem+'_Shader.cso')])
    pinned={str(p):sha(p) for p in files}
    build_manifest=dict(exe_sha256=sha(exe),source_hashes=pinned,fixture_sha256=sha(fixture),
        generated_fixture_sha256=sha(out/'nrd_bridge_rr_fixture.cpp'),test_sha256=sha(source),timing_no_debug=timing_no_debug)
    if skip_build:
        assert build_manifest==json.loads((out/'build_manifest.json').read_text()),'skip-build inputs differ from the built fixture'
    else:
        (out/'build_manifest.json').write_text(json.dumps(build_manifest,indent=2))
    if os.environ.get('FSRD_NATIVE_ANCHOR_BUILD_ONLY')=='1':
        print(json.dumps(dict(built=True,output=str(out),exe_sha256=sha(exe))),flush=True)
        return
    started=time.perf_counter()
    run=subprocess.run([str(exe),str(out)],capture_output=True,text=True,timeout=300,
        creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    (out/'stdout.log').write_text(run.stdout);(out/'stderr.log').write_text(run.stderr)
    print(run.stdout,flush=True)
    if run.returncode:print(run.stderr,flush=True)
    run.check_returncode()
    assert 'PASS native_post_motion_anchor frames=240 checks=' in run.stdout
    assert 'debug_errors=0 debug_warnings=0' in run.stdout
    mutant=subprocess.run([str(exe),str(out/'force_off_mutant'),'--force-native-option-off-mutant'],capture_output=True,text=True,timeout=300,
        creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    (out/'mutant.stdout.log').write_text(mutant.stdout);(out/'mutant.stderr.log').write_text(mutant.stderr)
    assert mutant.returncode!=0 and 'actual native option activates after the return motion' in mutant.stderr,mutant.stderr
    print('PASS power check: native-option-OFF mutant fails the real provider-input correction invariant',flush=True)
    assert pinned=={str(p):sha(p) for p in files},'production inputs changed during the test'
    (out/'result.json').write_text(json.dumps(dict(passed=True,seconds=time.perf_counter()-started,
        exe_sha256=sha(exe),source_hashes=pinned,fixture_sha256=sha(fixture),fixture_adaptation='absolute bridge include plus one GPU input-copy callback in mock provider seam; all production/native method bodies unchanged',
        mutant_required_failure=True,scope='Actual native RRSettings Configure/RecordOwned/anchor GPU passes/provider-input resource/physical trace/CommitOwned with mock provider; legacy256, D16/S256+G2/G3, and user NZR+Glass Blend joint pair; INI/menu mapping and actual AMD quality are separate checks'),indent=2))
    print(json.dumps(dict(passed=True,output=str(out))),flush=True)


if __name__=='__main__':main()
