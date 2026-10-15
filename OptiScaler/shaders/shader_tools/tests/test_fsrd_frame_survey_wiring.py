"""Exercise actual ResTrack Reset/Close/submit detour selection on WARP.

The prior fixture directly drove lifecycle callbacks and missed the two wrong
attach targets. This fixture compiles those production attach/detach call sites
and survey wrappers, then uses real COM calls without manual lifecycle callbacks.
Other pass/view callbacks still use the existing controlled-content fixture.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import test_fsrd_frame_survey as fixture
from resource_limits import memory_guard, peak_bytes

ROOT = fixture.ROOT


def function(source, name):
    at = source.index(f'ResTrack_Dx12::{name}(')
    start = source.rfind('\n', 0, at)+1
    brace = source.index('{', at)
    depth = 1; end = brace+1
    while depth:
        depth += (source[end] == '{')-(source[end] == '}')
        end += 1
    return source[start:end].replace('ResTrack_Dx12::', '')


def selected_line(source, marker):
    rows = [row.strip() for row in source.splitlines() if marker in row and not row.strip().startswith('//')]
    if len(rows) != 1:
        raise AssertionError(f'Expected one production attach site: {marker}')
    return rows[0]


def run():
    memory_guard()
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/frame_survey/wiring'))
    output.mkdir(parents=True, exist_ok=True)
    source = (ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.cpp').read_text()
    list_hooks = function(source, 'HookCommandList')
    queue_hooks = function(source, 'HookToQueue')
    detach = function(source, 'ReleaseDeviceHooks')
    reset = selected_line(list_hooks, 'o_Reset ? DetourAttach')
    submit = selected_line(queue_hooks, 'DetourAttach(&(PVOID&) o_ExecuteCommandLists,')
    close = selected_line(list_hooks, 'DetourAttach(&(PVOID&) o_Close,')
    # Preserve the actual conditional expressions, including an accidental
    # selection of the old hook: that must fail the runtime capture below.
    reset = 'const auto resetResult = '+reset[reset.index('('):]
    submit = 'const auto submitResult = o_ExecuteCommandLists ? '+submit
    wrappers = '\n'.join(function(source, name) for name in ('hkSurveyReset', 'hkSurveyClose', 'hkSurveyExecuteCommandLists'))
    wiring = r'''
namespace LifecycleWiring {
bool gSurveyWrappers=true;
bool gNrdBridgeWrappers=false;
namespace NrdBridge { inline void OnReset(ID3D12GraphicsCommandList*, ID3D12PipelineState*) {} }
struct D3D12Hooks { static void OnBridgeCommandListReset(ID3D12GraphicsCommandList*, ID3D12PipelineState*) {} };
using ResetFn=HRESULT(*)(ID3D12GraphicsCommandList*,ID3D12CommandAllocator*,ID3D12PipelineState*);
using CloseFn=HRESULT(*)(ID3D12GraphicsCommandList*);
using SubmitFn=void(*)(ID3D12CommandQueue*,UINT,ID3D12CommandList* const*);
ResetFn o_Reset=nullptr; CloseFn o_Close=nullptr; SubmitFn o_ExecuteCommandLists=nullptr;
HRESULT hkReset(ID3D12GraphicsCommandList* list,ID3D12CommandAllocator* allocator,ID3D12PipelineState* pso) {
 const auto result=o_Reset(list,allocator,pso); if(SUCCEEDED(result)) RRTraceFence::ResetSucceeded(list); return result;
}
HRESULT hkClose(ID3D12GraphicsCommandList* list) { return o_Close(list); }
void hkExecuteCommandLists(ID3D12CommandQueue* queue,UINT count,ID3D12CommandList* const* lists) {
 auto tickets=RRTraceFence::BeforeSubmission(queue,count,lists);
 o_ExecuteCommandLists(queue,count,lists); RRTraceFence::AfterSubmission(queue,tickets);
}
__WRAPPERS__
void Attach(ID3D12GraphicsCommandList* list,ID3D12CommandQueue* queue) {
 auto** lt=*reinterpret_cast<void***>(list); auto** qt=*reinterpret_cast<void***>(queue);
 o_Reset=reinterpret_cast<ResetFn>(lt[10]); o_Close=reinterpret_cast<CloseFn>(lt[9]);
 o_ExecuteCommandLists=reinterpret_cast<SubmitFn>(qt[10]);
 if(DetourTransactionBegin()!=NO_ERROR || DetourUpdateThread(GetCurrentThread())!=NO_ERROR) throw std::runtime_error("wiring transaction");
 __RESET__
 __SUBMIT__
 __CLOSE__
 if(resetResult!=NO_ERROR || submitResult!=NO_ERROR || DetourTransactionCommit()!=NO_ERROR) throw std::runtime_error("wiring attach");
}
void Detach() {
 DetourTransactionBegin(); DetourUpdateThread(GetCurrentThread());
 __DETACH__
 DetourTransactionCommit();
}
}
'''
    detach_lines = '\n'.join(selected_line(detach, f'DetourDetach(&(PVOID&) o_{name},') for name in ('Reset', 'Close', 'ExecuteCommandLists'))
    for key, value in [('WRAPPERS', wrappers), ('RESET', reset), ('SUBMIT', submit), ('CLOSE', close), ('DETACH', detach_lines)]:
        wiring = wiring.replace('__'+key+'__', value)
    cpp = '#include "misc/NrdBridgeTitleCallbacks_Dx12.h"\n'+fixture.CPP.replace('struct Host {', wiring+'\nstruct Host {')
    start = cpp.index('  ComPtr<IDXGIAdapter1> chosen;'); end = cpp.index('  need(bool(chosen)', start)
    cpp = cpp[:start]+'  ComPtr<IDXGIAdapter1> chosen; hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&chosen))); adapter="WARP";\n'+cpp[end:]
    cpp = cpp.replace(' FrameSurvey::Submit(queue.Get(),1,&cmd);', '')
    cpp = cpp.replace('  auto tickets=RRTraceFence::BeforeSubmission(queue.Get(),1,&cmd);\n', '')
    cpp = cpp.replace(' RRTraceFence::AfterSubmission(queue.Get(),tickets);', '')
    cpp = cpp.replace(' RRTraceFence::ResetSucceeded(list.Get());', '')
    cpp = cpp.replace('  FrameSurvey::Reset(list.Get(),nullptr); uploads.clear();', '  uploads.clear();')
    cpp = cpp.replace(' need(FrameSurvey::Request(64,32),', ' hr(h.list->Close());\n need(FrameSurvey::Request(64,32),')
    cpp = cpp.replace(' FrameSurvey::Reset(h.list.Get(),nullptr);', ' hr(h.alloc->Reset()); hr(h.list->Reset(h.alloc.Get(),nullptr));')
    cpp = cpp.replace(' FrameSurvey::Close(h.list.Get(),S_OK);', '')
    cpp = cpp.replace(' need(FrameSurvey::Install(host.dev.Get(),host.list.Get()),"optional hooks install");',
                      ' need(FrameSurvey::Install(host.dev.Get(),host.list.Get()),"optional hooks install");\n LifecycleWiring::Attach(host.list.Get(),host.queue.Get());')
    cpp = cpp.replace(' result["frame"]=frameTest(host); result["aliasing"]=aliasTest(host);',
                      ' result["frame"]=frameTest(host); LifecycleWiring::Detach();')
    # The pipeline-library/early-binding case needs a hardware driver (WARP has no pipeline libraries).
    cpp = cpp.replace(' result["early_binding"]=earlyBindingTest(host);\n', '')
    cpp = cpp.replace(' result["timings"]={timing(host,1505,847),timing(host,2560,1440)};', ' result["timings"]=J::array();')
    cpp = cpp.replace('"synthetic_D3D12_hardware_fixture_not_Cyberpunk"', '"production_lifecycle_detour_calls_WARP_not_Cyberpunk"')
    cpp = cpp.replace('__TRACE__', (ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp').as_posix()).replace(
        '__SURVEY__', (ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').as_posix()).replace('IID_PPV_ARGS_Helper(&blob)', '&blob')
    source_file = output/'fixture.cpp'; source_file.write_text(cpp)
    stubs = output/'stubs'
    (stubs/'proxies').mkdir(parents=True, exist_ok=True)
    (stubs/'inputs').mkdir(exist_ok=True)
    (stubs/'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n#define LOG_INFO(...) ((void)0)\n#define LOG_ERROR(...) ((void)0)\n')
    (stubs/'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\nnamespace Util { inline std::filesystem::path DllPath() { return g_dllPath; } }\n')
    (stubs/'inputs/NVNGX_DLSS.h').write_text('#pragma once\n#include <nvsdk_ngx.h>\n')
    (stubs/'proxies/D3D12_Proxy.h').write_text('#pragma once\n#include <d3d12.h>\nnamespace D3d12Proxy { inline auto D3D12CreateVersionedRootSignatureDeserializer_() { return &D3D12CreateVersionedRootSignatureDeserializer; } inline auto D3D12SerializeVersionedRootSignature_() { return &D3D12SerializeVersionedRootSignature; } }\n')
    exe = output/'fixture.exe'
    fixture.compile_cpp(source_file, exe, ('d3d12.lib','dxgi.lib','dxguid.lib','d3dcompiler.lib','bcrypt.lib','user32.lib','psapi.lib',
                         str(ROOT/'OptiScaler/library/detours/detours.lib')),
                        (stubs,ROOT/'OptiScaler',ROOT/'OptiScaler/include',ROOT/'external/streamline', ROOT/'external/nlohmann',ROOT/'external/nvngx_dlss_sdk',
                         ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
    subprocess.run([str(exe),str(output)], check=True, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    row = json.loads((output/'host-result.json').read_text())
    manifest = json.loads((Path(row['frame']['capture'])/'capture.json').read_text())
    assert manifest['complete'] and manifest['recorded_frames'] == 1 and len(manifest['batches']) == 1
    assert not manifest['coverage_gaps'].get('list_without_observed_reset', 0)
    row['python_checks_passed'] = 2
    row['python_peak_working_set_bytes'] = peak_bytes()
    (output/'host-result.json').write_text(json.dumps(row,indent=2)+'\n')
    print(json.dumps(row))


if __name__ == '__main__':
    run()
