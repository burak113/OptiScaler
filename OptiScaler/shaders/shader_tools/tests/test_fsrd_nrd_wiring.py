"""Real COM detours and GPU restoration of every production compute binding kind.

Extracts actual detour selections, survey wrappers, D3D12 state trackers and
RestoreRoot rather than copying their logic. A synthetic shader clobbers all
state; the title shader then reads every restored argument. Coordinator and
survey observers are spies, so this tests plumbing, not discovery or real RR.
The existing 32+2 FrameSurvey wiring fixture remains a separate acceptance test.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp
from test_fsrd_nrd_root_restore import function
from test_fsrd_frame_survey_wiring import function as res_function, selected_line


def run():
    d3d = (ROOT/'OptiScaler/hooks/D3D12_Hooks.cpp').read_text()
    res = (ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.cpp').read_text()
    survey = (ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').read_text()
    header = (ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.h').read_text()
    state = d3d[d3d.index('// Common'):d3d.index('// Intel Atomic Extension')]
    state = state.replace('ankerl::unordered_dense::map', 'std::unordered_map')
    early = ('SetPipelineState', 'SetDescriptorHeaps', 'SetComputeRootSignature',
             'SetComputeRootDescriptorTable', 'SetComputeRoot32BitConstants',
             'SetComputeRoot32BitConstant', 'SetComputeRootConstantBufferView',
             'SetComputeRootShaderResourceView', 'SetComputeRootUnorderedAccessView')
    wrappers = ('SetDescriptorHeaps', 'SetComputeRootSignature',
                'SetComputeRootConstantBufferView', 'SetComputeRootShaderResourceView',
                'SetComputeRootUnorderedAccessView')
    bodies = function(d3d, 'UINT GetRootParameterCount(')+'\n'
    bodies += '\n'.join(function(d3d, 'static void hk'+name+'(') for name in early)
    bodies += '\n'+'\n'.join(function(d3d, 'static void hkSurvey'+name+'(') for name in wrappers)
    controls = '\n'.join(function(d3d, signature) for signature in (
        'static bool CaptureRootRestoreSnapshot(',
        'void D3D12Hooks::SetRootSignatureTracking(', 'bool D3D12Hooks::RootSignatureTrackingEnabled(',
        'void D3D12Hooks::OnBridgeCommandListReset(', 'bool D3D12Hooks::CanRestoreRootSignature(',
        'bool D3D12Hooks::RestoreDescriptorHeaps(', 'bool D3D12Hooks::RestorePipelineState(',
        'bool D3D12Hooks::RestoreComputeRootState(', 'bool D3D12Hooks::RestoreGraphicsRootState(',
        'void D3D12Hooks::RestoreRoot('))
    wiring = '\n'.join(res_function(res, name) for name in (
        'hkSurveySetPipelineState', 'hkSurveyDispatch', 'hkSurveyReset',
        'hkSurveySetComputeRootDescriptorTable'))
    list_hooks = res_function(res, 'HookCommandList')
    res_attach = '\n'.join(selected_line(list_hooks, 'DetourAttach(&(PVOID&) o_'+name+',')
                           for name in ('SetPipelineState', 'Dispatch', 'SetComputeRootDescriptorTable'))
    reset_attach = selected_line(list_hooks, 'o_Reset ? DetourAttach')
    res_attach += '\nconst auto resetResult = '+reset_attach[reset_attach.index('('):]
    res_attach += '\nneed(resetResult==NO_ERROR,"production reset attach");'
    d3d_attach = '\n'.join(re.search(
        r'DetourAttach\(&\(PVOID&\) s_'+name+r'\.o_earlyHook,\s*[^;]+;', d3d).group(0)
        for name in early)
    # ResTrack's real hooks are class members; relocating them into Wiring must
    # not let C++ ADL find unrelated global D3D hook functions with identical names.
    bodies = re.sub(r'\bhk(?=\w)', 'root_hk', bodies)
    d3d_attach = re.sub(r'\bhk(?=\w)', 'root_hk', d3d_attach)
    root_at = bodies.index('static void root_hkSetPipelineState(')
    root_brace = bodies.index('{', root_at)
    bodies = bodies[:root_brace+1]+'\n layerTrace.push_back({{"layer","D3D12"},{"this",uint64_t(commandList)}});'+bodies[root_brace+1:]
    # Match the actual state-wrapper selectors from device hook initialization.
    selectors = '\n'.join(selected_line(res, marker) for marker in (
        'gNrdBridgeWrappers = NrdBridge::StartupEnabled();',
        'gSurveyWrappers = Config::Instance()->FfxDenoiserFrameSurvey.value_or_default() ||'))
    device_selectors = '\n'.join(selected_line(d3d, marker) for marker in (
        'gNrdBridgeDeviceWrappers = NrdBridge::StartupEnabled();',
        'gSurveyDeviceWrappers = Config::Instance()->FfxDenoiserFrameSurvey.value_or_default() ||'))
    cpp = Path(__file__).with_name('fsrd_nrd_wiring_fixture.cpp').read_text()
    replacements = {
        'ROOT': ROOT.as_posix(), 'STATE': state, 'TRACKERS': bodies, 'CONTROL': controls,
        'WIRING': wiring, 'RES_ATTACH': res_attach, 'D3D_ATTACH': d3d_attach,
        'RES_DETACH': res_attach[:res_attach.index('const auto resetResult')].replace('DetourAttach','DetourDetach')
            +'\nDetourDetach(&(PVOID&) o_Reset, gSurveyWrappers ? hkSurveyReset : hkReset);',
        'D3D_DETACH': d3d_attach.replace('DetourAttach', 'DetourDetach'),
        'SELECTORS': selectors, 'DEVICE_SELECTORS': device_selectors,
        'INTERNAL_DECL': header[header.index('class ScopedInternal'):header.index('bool Enabled() noexcept;')],
        'INTERNAL_IMPL': '\n'.join(function(survey, signature) for signature in (
            'ScopedInternal::ScopedInternal()', 'ScopedInternal::~ScopedInternal()', 'bool Internal() noexcept')),
    }
    for key, value in replacements.items():
        cpp = cpp.replace('__'+key+'__', value)
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    source, exe = out/'nrd_wiring.cpp', out/'nrd_wiring.exe'
    source.write_text(cpp)
    compile_cpp(source, exe, ('d3d12.lib','dxgi.lib','dxguid.lib','d3dcompiler.lib',
        str(ROOT/'OptiScaler/library/detours/detours.lib')), (ROOT/'external/nlohmann',))
    subprocess.run([str(exe),str(out)], check=True, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    result = json.loads((out/'result.json').read_text())
    assert result['disabled']['bridge_callbacks'] == 0
    assert result['enabled']['restored_words'] == [11,22,33,10,12,40,55,66,77,88,99]
    assert result['enabled']['injection_did_not_change_tracking']
    assert result['enabled']['after_reset']['sparse_mask'] == [0,0,1]
    assert result['debug_layer_available'] and result['debug_error_count'] == 0
    assert result['enabled']['all_com_identities_bridge_callbacks'] == result['enabled']['bridge_callbacks']
    assert len({entry['this'] for entry in result['enabled']['hook_layers'] if entry['layer'] == 'ResTrack'}) >= 2
    result['python_checks'] = 7
    result['scope'] = ('actual production detours and state trackers/RestoreRoot with synthetic GPU work; '
                       'survey/coordinator callbacks are spies, no real RR or Cyberpunk runtime proof')
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    run()
