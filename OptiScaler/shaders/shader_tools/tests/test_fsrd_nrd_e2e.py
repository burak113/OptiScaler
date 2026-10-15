"""Actual NRD coordinator + conversion + signed AMD RR + native detour restoration.

Run through lead_ops/run_task_test.py to hold the shared GPU lock. Creation
callbacks and SL snapshots are fixture adapters; actual compute detours, table
resolution, coordinator, conversion, RR wrapper and state restoration are used.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp
from test_fsrd_nrd_root_restore import function
from test_fsrd_frame_survey_wiring import function as res_function, selected_line
from test_fsrd_nrd_bridge_rr import bounded_run, DLL


def method(source, signature):
    """Extract the actual definition, past declarations and aggregate default arguments."""
    search = 0
    while True:
        start = source.index(signature, search)
        opening = source.index('(', start)
        level = 1
        end_parameters = opening + 1
        while level:
            character = source[end_parameters]
            level += (character == '(') - (character == ')')
            end_parameters += 1
        brace = source.index('{', end_parameters)
        declaration = source.find(';', end_parameters, brace)
        if declaration != -1:
            search = declaration + 1
            continue
        break
    level = 1
    end = brace + 1
    while level:
        character = source[end]
        level += (character == '{') - (character == '}')
        end += 1
    return source[start:end]


def build(out):
    d3d = (ROOT / 'OptiScaler/hooks/D3D12_Hooks.cpp').read_text()
    res = (ROOT / 'OptiScaler/resource_tracking/ResTrack_dx12.cpp').read_text()
    stubs = out / 'stubs'
    for name in ('hooks', 'inputs', 'proxies', 'resource_tracking'):
        (stubs / name).mkdir(parents=True, exist_ok=True)
    support = Path(__file__).with_name('nrd_bridge_rr_test_support.h').read_text()
    support = support[:support.index('struct ResTrack_Dx12')]
    support = support.replace('"../../../misc/RecordedComputeLease_Dx12.h"',
                              '"' + (ROOT / 'OptiScaler/misc/RecordedComputeLease_Dx12.h').as_posix() + '"')
    support = support.replace('struct FfxApiProxy', 'struct ProviderExports')
    support = support.replace('static inline bool real = false, initAvailable = true, rejectDispatch = false;',
                              'static inline bool real = false, initAvailable = true, rejectDispatch = false;\n'
                              '    static inline bool partialFailure = false;\n'
                              '    static inline void (*afterRealDispatch)() = nullptr;\n'
                              '    struct Record { ffxContext context; void* list; void* spec; void* diff; void* depth; void* motion; uint32_t flags; };\n'
                              '    static inline std::vector<Record> records;')
    record_marker = '        ++dispatches;'
    assert support.count(record_marker) == 1
    support = support.replace(record_marker, record_marker + '\n'
        '        records.push_back({*context,lastDispatch.commandList,lastSpecular.signal.input.resource,'
        'lastDiffuse.signal.input.resource,lastDispatch.linearDepth.resource,lastDispatch.motionVectors.resource,lastDispatch.flags});')
    dispatch_end = '        if (real && dispatches < 4) std::fprintf(stderr,"real dispatch end code=%u\\n",unsigned(result));'
    assert support.count(dispatch_end) == 1
    support = support.replace(dispatch_end, dispatch_end + '\n'
        '        if (real && afterRealDispatch) afterRealDispatch();\n'
        '        if (real && partialFailure && result == FFX_API_RETURN_OK) return FFX_API_RETURN_ERROR_RUNTIME_ERROR;')
    proxy = (ROOT / 'OptiScaler/proxies/FfxApi_Proxy.h').read_text()
    enum = proxy[proxy.index('enum class FFXStructType'):proxy.index('// The denoiser DLL')]
    routes = '\n'.join(method(proxy, signature) for signature in (
        'static void RecordContextType(', 'static std::optional<FFXStructType> TakeContextType(',
        'static void RestoreContextType(', 'static FFXStructType GetType(', 'static FFXStructType GetIndirectType(',
        'static ffxReturnCode_t D3D12_CreateContext(', 'static ffxReturnCode_t D3D12_DestroyContext(',
        'static ffxReturnCode_t D3D12_DestroyRouted(', 'static ffxReturnCode_t D3D12_Configure(',
        'static ffxReturnCode_t D3D12_Query(', 'static ffxReturnCode_t D3D12_Dispatch('))
    support += '''
#include <optional>
#include <mutex>
#include <ffx_framegeneration.h>
#include <ffx_upscale.h>
#define FFX_API_EFFECT_ID_FGSC_VK 0x00040000u
#define LOG_DEBUG(...) ((void)0)
namespace FfxDenoiserRouteAttestation { struct ContextRecord {}; }
struct WitnessAdapter {
 std::shared_ptr<FfxDenoiserRouteAttestation::ContextRecord> Take(uintptr_t) { return {}; }
 void Restore(const std::shared_ptr<FfxDenoiserRouteAttestation::ContextRecord>&) {}
 void Completed(const std::shared_ptr<FfxDenoiserRouteAttestation::ContextRecord>&) {}
};
struct FfxModule {
 HMODULE dll=nullptr;
 bool skipCreateCalls=false,skipQueryCalls=false,skipConfigureCalls=false,skipDispatchCalls=false;
 decltype(&ProviderExports::D3D12_CreateContext) CreateContext=&ProviderExports::D3D12_CreateContext;
 decltype(&ProviderExports::D3D12_DestroyContext) DestroyContext=&ProviderExports::D3D12_DestroyContext;
 decltype(&ProviderExports::D3D12_Query) Query=&ProviderExports::D3D12_Query;
 decltype(&ProviderExports::D3D12_Configure) Configure=&ProviderExports::D3D12_Configure;
 decltype(&ProviderExports::D3D12_Dispatch) Dispatch=&ProviderExports::D3D12_Dispatch;
};
''' + enum + '''
struct FfxApiProxy : ProviderExports {
 inline static FfxModule denoiser_dx12,main_dx12,upscaling_dx12,fg_dx12,radiance_dx12;
 inline static std::unordered_map<ffxContext,FFXStructType> contextToType;
 inline static std::mutex contextToTypeMutex;
 inline static WitnessAdapter denoiserRouteWitnesses;
 inline static bool _skipDestroyCalls=false;
 inline static std::array<unsigned,5> routed{};
 inline static unsigned wrongRoute=0;
 static void CheckRoute(const char* route) { if(std::string(route)!="denoiser_dx12") ++wrongRoute; }
 static ffxReturnCode_t CreateDenoiserWitnessed(FfxModule& module,const char* route,ffxContext* context,ffxCreateContextDescHeader* desc,const ffxAllocationCallbacks* cb) {
  CheckRoute(route); ++routed[0]; return module.CreateContext(context,desc,cb);
 }
 static ffxReturnCode_t ConfigureDenoiserWitnessed(FfxModule& module,const char* route,ffxContext* context,const ffxConfigureDescHeader* desc) {
  CheckRoute(route); ++routed[1]; return module.Configure(context,desc);
 }
 static ffxReturnCode_t QueryDenoiserWitnessed(FfxModule& module,const char* route,ffxContext* context,ffxQueryDescHeader* desc) {
  CheckRoute(route); ++routed[2]; return module.Query(context,desc);
 }
 static ffxReturnCode_t DispatchDenoiserWitnessed(FfxModule& module,const char* route,ffxContext* context,const ffxDispatchDescHeader* desc) {
  CheckRoute(route); ++routed[3]; return module.Dispatch(context,desc);
 }
 static ffxReturnCode_t DestroyDenoiserWitnessed(FfxModule& module,const char* route,ffxContext* context,const ffxAllocationCallbacks* cb,
  const std::shared_ptr<FfxDenoiserRouteAttestation::ContextRecord>&) {
  CheckRoute(route); ++routed[4]; return module.DestroyContext(context,cb);
 }
''' + routes + '\n};\n'
    lease = Path(__file__).with_name('dx12_shader_test_support.h').read_text()
    retention = lease[lease.index('struct ResTrack_Dx12'):]
    retention = retention.replace('std::function<void(ID3D12CommandQueue*)> beforeSubmit = {})',
        'std::function<void(ID3D12CommandQueue*)> beforeSubmit = {},\n'
        '                                     RecordedComputeLease::SubmissionCallbacks callbacks = {})')
    retention = retention.replace('lease, std::move(beforeSubmit));',
        'lease, std::move(beforeSubmit), std::move(callbacks));')
    assert 'SubmissionCallbacks callbacks' in retention
    before_submission = method(res, 'std::shared_ptr<RecordedComputeLease::Submission> ResTrack_Dx12::BeforeComputeSubmission(')
    declaration = before_submission[:before_submission.index('{')].replace('ResTrack_Dx12::', '').strip()
    last = retention.rindex('};')
    retention = retention[:last] + '    static ' + declaration + ';\n' + retention[last:]
    support += retention + '\n' + before_submission
    support += '''
#define LOG_WARN(...) ((void)0)
#define LOG_TRACE(...) ((void)0)
struct Setting { bool value=false; bool value_or_default() const { return value; } void set_volatile_value(bool next) { value=next; } };
struct Config {
 Setting FfxDenoiserNrdBridge{false}, FfxDenoiserNrdBridgeEnabled{true}, FfxDenoiserFrameSurvey{false};
 Setting RestoreComputeSignature{true}, RestoreGraphicSignature{false}, ExtendedStateRestore{true};
 static Config* Instance() { static Config value; return &value; }
};
struct State { bool isShuttingDown=false; static State& Instance() { static State value; return value; } };
inline std::filesystem::path g_dllPath;
namespace Util {
 inline bool CheckForRealObject(std::string,IUnknown*,IUnknown**) { return false; }
 inline std::filesystem::path DllPath() { return g_dllPath; }
 inline std::filesystem::path ExePath() { return L"cyberpunk2077.exe"; }
}
struct StreamlineHooks {
 static inline SLConstantsSnapshot snapshot;
 static SLConstantsSnapshot getSLConstantsSnapshot() { return snapshot; }
};
'''
    support = '#include <filesystem>\n#include <vector>\n' + support
    (stubs / 'fixture_support.h').write_text(support)
    for name in ('pch.h', 'Config.h', 'State.h', 'Util.h', 'hooks/Streamline_Hooks.h',
                 'proxies/FfxApi_Proxy.h', 'resource_tracking/ResTrack_Dx12.h'):
        (stubs / name).write_text('#pragma once\n#include "fixture_support.h"\n')
    (stubs / 'Logger.h').write_text('#pragma once\ninline void FlushLogger() noexcept {}\n')
    (stubs / 'inputs/NVNGX_DLSS.h').write_text('#pragma once\n#include <nvsdk_ngx.h>\n')
    (stubs / 'proxies/D3D12_Proxy.h').write_text('''#pragma once
#include <d3d12.h>
namespace D3d12Proxy {
 inline auto D3D12CreateVersionedRootSignatureDeserializer_() { return &D3D12CreateVersionedRootSignatureDeserializer; }
 inline auto D3D12SerializeVersionedRootSignature_() { return &D3D12SerializeVersionedRootSignature; }
}
''')
    extra = ''
    controls_names = (
        'void D3D12Hooks::SetRootSignatureTracking(', 'bool D3D12Hooks::RootSignatureTrackingEnabled(',
        'static bool CaptureRootRestoreSnapshot(',
        'void D3D12Hooks::OnBridgeCommandListReset(', 'bool D3D12Hooks::CanRestoreRootSignature(',
        'bool D3D12Hooks::RestoreDescriptorHeaps(', 'bool D3D12Hooks::RestorePipelineState(',
        'bool D3D12Hooks::RestoreComputeRootState(', 'bool D3D12Hooks::RestoreGraphicsRootState(',
        'void D3D12Hooks::RestoreRoot(')
    if 'bool D3D12Hooks::GetComputeBindingsForBridge(' in d3d:
        controls_names += ('bool D3D12Hooks::GetComputeBindingsForBridge(',)
        extra = 'static bool GetComputeBindingsForBridge(ID3D12GraphicsCommandList*,FrameSurvey::ComputeBindings&) noexcept;'
    declaration = '''#pragma once
#include <resource_tracking/FrameSurvey_Dx12.h>
struct D3D12RootRestoreSnapshot;
struct D3D12Hooks {
 static void SetRootSignatureTracking(bool);
 static bool RootSignatureTrackingEnabled();
 static void OnBridgeCommandListReset(ID3D12GraphicsCommandList*,ID3D12PipelineState*);
 static bool CanRestoreRootSignature(ID3D12GraphicsCommandList*);
 static bool RestoreDescriptorHeaps(ID3D12GraphicsCommandList*,const D3D12RootRestoreSnapshot&);
 static bool RestorePipelineState(ID3D12GraphicsCommandList*,const D3D12RootRestoreSnapshot&);
 static bool RestoreComputeRootState(ID3D12GraphicsCommandList*,const D3D12RootRestoreSnapshot&);
 static bool RestoreGraphicsRootState(ID3D12GraphicsCommandList*,const D3D12RootRestoreSnapshot&);
 static void RestoreRoot(ID3D12GraphicsCommandList*);
''' + extra + '\n};\n'
    (stubs / 'hooks/D3D12_Hooks.h').write_text(declaration)
    early = ('SetPipelineState', 'SetDescriptorHeaps', 'SetComputeRootSignature',
             'SetComputeRootDescriptorTable', 'SetComputeRoot32BitConstants',
             'SetComputeRoot32BitConstant', 'SetComputeRootConstantBufferView',
             'SetComputeRootShaderResourceView', 'SetComputeRootUnorderedAccessView')
    wrappers = ('SetDescriptorHeaps', 'SetComputeRootSignature', 'SetComputeRootConstantBufferView',
                'SetComputeRootShaderResourceView', 'SetComputeRootUnorderedAccessView')
    bodies = method(d3d, 'UINT GetRootParameterCount(') + '\n'
    bodies += '\n'.join(function(d3d, 'static void hk' + name + '(') for name in early)
    bodies += '\n' + '\n'.join(function(d3d, 'static void hkSurvey' + name + '(') for name in wrappers)
    bodies = re.sub(r'\bhk(?=\w)', 'root_hk', bodies)
    controls = '\n'.join(function(d3d, signature) for signature in controls_names)
    restore_at = controls.index('void D3D12Hooks::RestoreRoot(')
    brace = controls.index('{', restore_at)
    controls = controls[:brace + 1] + '\n ++restores;\n' + controls[brace + 1:]
    wiring = '\n'.join(res_function(res, name) for name in (
        'hkSurveySetPipelineState', 'hkSurveyDispatch', 'hkSurveyReset',
        'hkSurveySetComputeRootDescriptorTable', 'hkSurveyResourceBarrier'))
    dispatch_at = wiring.index('void hkSurveyDispatch(')
    brace = wiring.index('{', dispatch_at)
    wiring = wiring[:brace + 1] + '\n recordDispatch(This,FrameSurvey::Internal());\n' + wiring[brace + 1:]
    barrier_at = wiring.index('void hkSurveyResourceBarrier(')
    brace = wiring.index('{', barrier_at)
    wiring = wiring[:brace + 1] + '\n auditBarriers(This,NumBarriers,pBarriers,FrameSurvey::Internal());\n' + wiring[brace + 1:]
    hooks = res_function(res, 'HookCommandList')
    attachments = []
    for name in ('SetPipelineState', 'Dispatch', 'SetComputeRootDescriptorTable', 'ResourceBarrier'):
        # Production may guard a native slot with a conditional expression. Take
        # its actual balanced API call, rather than a dangling fallback suffix.
        selected = selected_line(hooks, 'DetourAttach(&(PVOID&) o_' + name + ',')
        start = selected.index('DetourAttach(')
        opening = selected.index('(', start)
        depth, end = 1, opening + 1
        while depth:
            depth += (selected[end] == '(') - (selected[end] == ')')
            end += 1
        call = selected[start:end]
        attachments.append(f'need(o_{name} && {call}==NO_ERROR,"actual native {name} slot and detour attachment");')
    attach = '\n'.join(attachments)
    detach = attach.replace('DetourAttach', 'DetourDetach')
    reset = selected_line(hooks, 'o_Reset ? DetourAttach')
    attach += '\nconst auto resetResult = ' + reset[reset.index('('):]
    attach += '\nneed(resetResult==NO_ERROR,"production reset detour attach");'
    detach += '\nDetourDetach(&(PVOID&) o_Reset, gSurveyWrappers ? hkSurveyReset : hkReset);'
    roots_attach = '\n'.join(re.search(
        r'DetourAttach\(&\(PVOID&\) s_' + name + r'\.o_earlyHook,\s*[^;]+;', d3d).group(0)
        for name in early)
    roots_attach = re.sub(r'\bhk(?=\w)', 'root_hk', roots_attach)
    roots_attach = '\n'.join('need(' + call + '==NO_ERROR,"root attach ' + name + '");'
                             for name, call in zip(early, (part.strip() for part in roots_attach.split(';') if part.strip())))
    cpp = Path(__file__).with_name('fsrd_nrd_e2e_fixture.cpp').read_text()
    replacements = dict(
        ROOT=ROOT.as_posix(), STATE=d3d[d3d.index('// Common'):d3d.index('// Intel Atomic Extension')]
            .replace('ankerl::unordered_dense::map', 'std::unordered_map'),
        TRACKERS=bodies, CONTROL=controls, WIRING=wiring,
        RES_ATTACH=attach, RES_DETACH=detach, D3D_ATTACH=roots_attach,
        D3D_DETACH=roots_attach.replace('DetourAttach', 'DetourDetach'),
        SELECTORS='\n'.join(selected_line(res, marker) for marker in (
            'gNrdBridgeWrappers = NrdBridge::StartupEnabled();',
            'gSurveyWrappers = Config::Instance()->FfxDenoiserFrameSurvey.value_or_default() ||')),
        DEVICE_SELECTORS='\n'.join(selected_line(d3d, marker) for marker in (
            'gNrdBridgeDeviceWrappers = NrdBridge::StartupEnabled();',
            'gSurveyDeviceWrappers = Config::Instance()->FfxDenoiserFrameSurvey.value_or_default() ||')))
    for key, value in replacements.items():
        cpp = cpp.replace('__' + key + '__', value)
    assert '__ROOT__' not in cpp
    source = out / 'nrd_e2e.cpp'
    source.write_text(cpp)
    exe = out / 'nrd_e2e.exe'
    os.environ['FSRD_CPP_CACHE'] = str(out / 'cache')
    compile_cpp(source, exe, ('d3d12.lib', 'dxgi.lib', 'dxguid.lib', 'd3dcompiler.lib',
        'bcrypt.lib', 'user32.lib', 'psapi.lib', str(ROOT / 'OptiScaler/library/detours/detours.lib')),
        (stubs, ROOT / 'OptiScaler', ROOT / 'OptiScaler/include', ROOT / 'external/nlohmann',
         ROOT / 'external/nvngx_dlss_sdk', ROOT / 'external/streamline',
         ROOT / 'external/FidelityFX-SDK/ffx-api/include/ffx_api', ROOT / 'OptiScaler/shaders/fsrd_preprocess'))
    return exe


def validate_guide_pingpong(value):
    guide = value['guide_pingpong']
    assert guide['submitted_frames'] == guide['provider_dispatches'] == 8
    assert guide['physical_provider_creates'] == guide['reset_frames'] == 1
    assert guide['active_every_frame'] and guide['same_history_domain'] and guide['same_signal_profile_generation']
    assert [frame['provider_reset'] for frame in guide['frames']] == [True] + [False] * 7
    assert [frame['gpu_current_linear_depth'] for frame in guide['frames']] == [-7, -5] * 4
    assert [frame['gpu_motion_depth_delta'] for frame in guide['frames']] == [0, -2, 2, -2, 2, -2, 2, -2]
    assert value['debug_errors'] == value['debug_warnings'] == 0
    return 7


def quality_replay(exe, out):
    from fsrd_nrd_quality_replay import write_sequence, compare, export_crops
    inputs = out / 'quality_input'
    manifest = write_sequence(inputs)
    runs = {}
    for mode in ('off', 'on'):
        directory = out / ('quality_' + mode)
        directory.mkdir(parents=True, exist_ok=True)
        text, peak, elapsed, log = bounded_run([str(exe), str(directory), str(DLL), '--quality-' + mode], directory / 'native_run')
        value = json.loads((directory / 'quality-result.json').read_text())
        replay = value['quality_replay']
        assert replay['submitted_frames'] == manifest['submitted_frames']
        assert replay['physical_provider_creates'] == replay['provider_resets'] == 1
        assert replay['same_history_domain'] and replay['native_current_guides_every_pixel']
        assert replay['camera_projected_depth_delta'] == (mode == 'on')
        assert [frame['provider_reset'] for frame in replay['frames']] == [True] + [False] * (len(replay['frames']) - 1)
        assert value['debug_errors'] == value['debug_warnings'] == 0
        value.update(elapsed_seconds=elapsed, peak_resident_bytes=peak, native_log=str(log),
                     dll=str(DLL), dll_sha256=hashlib.sha256(DLL.read_bytes()).hexdigest(), python_checks=6)
        (directory / 'quality-result.json').write_text(json.dumps(value, indent=2) + '\n')
        runs[mode] = value
    metrics = compare(inputs, out / 'quality_off', out / 'quality_on')
    crops = export_crops(inputs, out / 'quality_off', out / 'quality_on', metrics, out / 'quality_crops')
    result = dict(runs=runs, metrics=metrics, same_frame_crops=crops, python_checks=12,
                  scope='production bridge and actual signed AMD on the same synthetic camera/signal sequence; no game NRD paired or game FPS claim')
    (out / 'quality-comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    report = Path(os.environ.get('FSRD_NRD_E2E_REPORT', f'E:/FSRD/sol_batch/{out.parents[1].name}'))
    report.mkdir(parents=True, exist_ok=True)
    (report / 'quality-comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


def native_motion_quality(exe, out):
    from fsrd_nrd_native_motion_e2e_inputs import prepare
    inputs = Path(os.environ.get('FSRD_NRD_NATIVE_MOTION_ORACLE_INPUT', 'F:/FSRD/sol_batch/15e-quality/inputs'))
    manifest = prepare(inputs, out / 'native_motion_input')
    runs = {}
    for mode, flag in (('baseline', '--native-motion-quality-baseline'), ('on', '--native-motion-quality'),
                       ('table', '--native-motion-quality-table')):
        directory = out / ('native_motion_' + mode)
        directory.mkdir(parents=True, exist_ok=True)
        text, peak, elapsed, log = bounded_run([str(exe), str(directory), str(DLL), flag], directory / 'native_run')
        value = json.loads((directory / 'native-motion-quality-result.json').read_text(encoding='utf-8'))
        native = value['native_motion_quality']
        assert native['submitted_quality_frames'] == len(native['frames']) == manifest['submitted_frames'] == 64
        assert native['same_history_context'] and native['first_only_quality_reset']
        assert native['current_prepass_r32_t4_every_pixel'] and native['native_enabled'] == (mode != 'baseline')
        assert native['table_binding'] == (mode == 'table')
        assert native['full_native_shadow_256_bytes'] == native['post_capture_cancel_recovered'] == (mode != 'baseline')
        assert native['warmed_shadow_bytes'] > 0 if mode != 'baseline' else native['warmed_shadow_bytes'] == 0
        assert [frame['reset'] for frame in native['frames']] == [True] + [False] * 63
        assert [frame['camera_fallback'] for frame in native['frames']] == [i == 24 for i in range(64)]
        assert value['debug_errors'] == value['debug_warnings'] == 0
        value.update(elapsed_seconds=elapsed, peak_resident_bytes=peak, native_log=str(log),
                     dll_sha256=hashlib.sha256(DLL.read_bytes()).hexdigest(), python_checks=9)
        (directory / 'native-motion-quality-result.json').write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
        runs[mode] = value
    result = dict(runs=runs, python_checks=27, input_manifest_sha256=hashlib.sha256((out / 'native_motion_input' / 'sequence.json').read_bytes()).hexdigest(),
                  scope='actual production coordinator/detours/NativeTemporalCapture/conversion/signed RR/Consumer on synthetic native-codec world oracle; native title world-mode not tested; physical native Release coverage separate')
    (out / 'native-motion-quality-comparison.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(result=str(out / 'native-motion-quality-comparison.json'), python_checks=27), indent=2))


def native_material_guides(exe, out):
    from fsrd_nrd_native_material_e2e import validate
    runs = {}
    for mode, flag in (('off', '--native-material-guides-off'), ('on', '--native-material-guides')):
        directory = out / ('native_material_' + mode)
        directory.mkdir(parents=True, exist_ok=True)
        text, peak, elapsed, log = bounded_run([str(exe), str(directory), str(DLL), flag], directory / 'native_run')
        value = json.loads((directory / 'native-material-result.json').read_text(encoding='utf-8'))
        count = validate(directory, value)
        value.update(python_checks=count, elapsed_seconds=elapsed, peak_resident_bytes=peak, native_log=str(log),
                     dll_sha256=hashlib.sha256(DLL.read_bytes()).hexdigest())
        (directory / 'native-material-result.json').write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
        runs[mode] = value
    result = dict(runs=runs, python_checks=sum(v['python_checks'] for v in runs.values()),
                  scope='actual production material-before-writer capture/state/generation admission/conversion/signed RR/restore; synthetic title writer and legacy creation/lifetime adapters; no game quality claim')
    (out / 'native-material-comparison.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(result=str(out / 'native-material-comparison.json'), python_checks=result['python_checks']), indent=2))


def validate_rr_only_policy(value):
    trace = value['rr_only_policy']
    checks = 0

    def require(condition):
        nonlocal checks
        assert condition
        checks += 1

    require(trace['binding'] in ('root VA', 'native table'))
    require(trace['submitted_frames'] == len(trace['frames']) == 88)
    require(trace['physical_provider_creates'] == 1 and trace['provider_resets'] == 2)
    require(trace['same_history_context'] and trace['noisy_input_identity'] and trace['both_lobes_only_rr'])
    require(trace['admission_gap_requests'] == trace['closed_list_requests'] == 2)
    require(trace['native_nan_rgb_frames'] == 30)
    require(trace['extra_provider_configures'] == trace['extra_owned_bytes'] == 0)
    require(value['debug_errors'] == value['debug_warnings'] == 0)
    requests = ['zero', 'fraction', 'one', 'nan', 'infinity']
    for mode in range(2):
        rows = trace['frames'][mode*44:(mode+1)*44]
        require([row['source_frame'] for row in rows] == list(range(2, 46)))
        require([row['frame'] for row in rows] == list(range(2+mode*44, 46+mode*44)))
        require([row['encoding'] for row in rows] == [('RGB', 'YCoCg')[mode]]*44)
        require([row['provider_reset'] for row in rows] == [True]+[False]*43)
        for index, row in enumerate(rows):
            require(row['request'] == requests[index % len(requests)])
            require(row['effective_strength'] == 0.)
            require(row['native_rgb_variant'] == index % 3)
            require(row['admission_gap_request'] == (index == 17))
            require(row['closed_list_request'] == (index == 5))
            stats = row['statistics']
            require(stats['finite_rgb'] == stats['rgb_values'] == 128*128*6)
            require(stats['native_alpha_values'] == 128*128*2)
            require(stats['rr_reference_matches'] == stats['different_from_native_rgb'] == 128*128*6)
            require(stats['native_nonfinite_rgb_values'] == (128*128*6 if index % 3 == 1 else 0))
    return checks


def rr_only_policy_replay(exe, out):
    from fsrd_nrd_quality_replay import write_sequence
    inputs = out / 'rr_only_policy_input'
    manifest = write_sequence(inputs)
    assert manifest['submitted_frames'] == 44
    sealed_hash = hashlib.sha256((inputs/'sequence.json').read_bytes()).hexdigest()
    runs = {}
    for binding in ('root', 'table'):
        directory = out / ('rr_only_policy_' + binding)
        directory.mkdir(parents=True, exist_ok=True)
        selector = '--rr-only-policy' if binding == 'root' else '--rr-only-policy-table'
        text, peak, elapsed, log = bounded_run([str(exe), str(directory), str(DLL), selector], directory/'native_run')
        value = json.loads((directory/'rr-only-policy-result.json').read_text())
        checks = validate_rr_only_policy(value)
        assert value['rr_only_policy']['input_manifest_sha256'] == sealed_hash
        assert value['rr_only_policy']['binding'] == ('root VA' if binding == 'root' else 'native table')
        value.update(python_checks=checks+2, elapsed_seconds=elapsed, peak_resident_bytes=peak,
                     native_log=str(log), dll=str(DLL), dll_sha256=hashlib.sha256(DLL.read_bytes()).hexdigest())
        (directory/'rr-only-policy-result.json').write_text(json.dumps(value, indent=2)+'\n')
        runs[binding] = value
    result = dict(runs=runs, input_manifest_sha256=sealed_hash,
                  python_checks=1+sum(run['python_checks'] for run in runs.values()),
                  scope='signed RR/production bridge: both lobes exclusively use staged RR under finite/NaN native-RGB poison; opaque alpha and live native word303 codec only; native NRD dispatch suppression not claimed')
    (out/'rr-only-policy-comparison.json').write_text(json.dumps(result, indent=2)+'\n')
    report = Path(os.environ.get('FSRD_NRD_E2E_REPORT', f'E:/FSRD/sol_batch/{out.parents[1].name}'))
    report.mkdir(parents=True, exist_ok=True)
    (report/'rr-only-policy-comparison.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def run():
    out = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/12e-e2e/tests/e2e'))
    out.mkdir(parents=True, exist_ok=True)
    exe = build(out)
    if '--compile-only' in sys.argv:
        print(json.dumps({'compile_only': True, 'executable': str(exe)}))
        return
    if '--rr-only-policy-only' in sys.argv:
        print(json.dumps(rr_only_policy_replay(exe, out), indent=2))
        return
    if '--native-material-guides-only' in sys.argv:
        native_material_guides(exe, out)
        return
    if '--native-motion-quality-only' in sys.argv:
        native_motion_quality(exe, out)
        return
    if '--quality-only' in sys.argv:
        quality_replay(exe, out)
        return
    if '--guide-pingpong-only' in sys.argv:
        text, peak, elapsed, log = bounded_run([str(exe), str(out), str(DLL), '--guide-pingpong'], out / 'guide_pingpong')
        value = json.loads((out / 'guide-pingpong-result.json').read_text())
        value.update(python_checks=validate_guide_pingpong(value), elapsed_seconds=elapsed, peak_resident_bytes=peak, native_log=str(log))
        (out / 'guide-pingpong-result.json').write_text(json.dumps(value, indent=2) + '\n')
        print(json.dumps(value, indent=2))
        return
    if '--submission-failure-only' in sys.argv:
        text, peak, elapsed, log = bounded_run([str(exe), str(out), str(DLL), '--submission-failure'], out / 'submission_failure')
        fault = json.loads((out / 'submission-failure-result.json').read_text())
        assert fault['submission_failure']['dependent_original_executes'] == 0 and fault['submission_failure']['dependent_denied']
        assert fault['debug_errors'] == 0 and fault['debug_warnings'] == 0
        fault.update(python_checks=2, elapsed_seconds=elapsed, peak_resident_bytes=peak, native_log=str(log))
        (out / 'submission-failure-result.json').write_text(json.dumps(fault, indent=2) + '\n')
        print(json.dumps(fault, indent=2))
        return
    if '--cbv-lifetime-only' in sys.argv:
        text, peak, elapsed, log = bounded_run([str(exe), str(out), str(DLL), '--cbv-lifetime'], out / 'cbv_lifetime')
        value = json.loads((out / 'cbv-lifetime-result.json').read_text())
        assert value['cbv_lifetime']['dead_com_calls'] == 0 and value['cbv_lifetime']['physical_final_reference_count'] == 0
        assert value['debug_errors'] == 0 and value['debug_warnings'] == 0
        value.update(python_checks=2, elapsed_seconds=elapsed, peak_resident_bytes=peak, native_log=str(log))
        (out / 'cbv-lifetime-result.json').write_text(json.dumps(value, indent=2) + '\n')
        print(json.dumps(value, indent=2))
        return
    off_text, off_peak, off_elapsed, off_log = bounded_run([str(exe), str(out), str(DLL), '--startup-off'], out / 'startup_off')
    configured_off = json.loads((out / 'startup-off-result.json').read_text())
    assert configured_off['startup_off'] == {'provider_creates': 0, 'provider_dispatches': 0, 'restore_calls': 0, 'nrdsentinel_untouched': True}
    assert configured_off['debug_errors'] == 0 and configured_off['debug_warnings'] == 0
    text, peak, elapsed, log = bounded_run([str(exe), str(out), str(DLL)], out / 'e2e')
    result = json.loads((out / 'result.json').read_text())
    assert result['raw']['exact_rgb'] and result['raw']['alpha_zero']
    assert result['rr']['finite_values'] == result['rr']['total_values']
    assert result['runtime_off']['provider_dispatches'] == 0 and result['runtime_off']['internal_detour_calls'] == 0
    assert result['debug_errors'] == 0 and result['debug_warnings'] == 0
    fault_text, fault_peak, fault_elapsed, fault_log = bounded_run([str(exe), str(out), str(DLL), '--submission-failure'], out / 'submission_failure')
    fault = json.loads((out / 'submission-failure-result.json').read_text())
    assert fault['submission_failure']['dependent_original_executes'] == 0 and fault['submission_failure']['dependent_denied']
    assert fault['debug_errors'] == 0 and fault['debug_warnings'] == 0
    cbv_text, cbv_peak, cbv_elapsed, cbv_log = bounded_run([str(exe), str(out), str(DLL), '--cbv-lifetime'], out / 'cbv_lifetime')
    cbv = json.loads((out / 'cbv-lifetime-result.json').read_text())
    assert cbv['cbv_lifetime']['dead_com_calls'] == 0 and cbv['cbv_lifetime']['physical_final_reference_count'] == 0
    assert cbv['debug_errors'] == 0 and cbv['debug_warnings'] == 0
    guide_text, guide_peak, guide_elapsed, guide_log = bounded_run([str(exe), str(out), str(DLL), '--guide-pingpong'], out / 'guide_pingpong')
    guide = json.loads((out / 'guide-pingpong-result.json').read_text())
    guide_checks = validate_guide_pingpong(guide)
    policy = rr_only_policy_replay(exe, out)
    result.update(python_checks=10+guide_checks+policy['python_checks'], rr_only_policy=policy,
                  guide_pingpong=dict(**guide, elapsed_seconds=guide_elapsed, peak_resident_bytes=guide_peak, native_log=str(guide_log)),
                  cbv_lifetime=dict(**cbv, elapsed_seconds=cbv_elapsed, peak_resident_bytes=cbv_peak, native_log=str(cbv_log)),
                  submission_failure=dict(**fault, elapsed_seconds=fault_elapsed, peak_resident_bytes=fault_peak, native_log=str(fault_log)), elapsed_seconds=elapsed, peak_resident_bytes=peak, native_log=str(log),
                  configured_startup_off=dict(**configured_off, elapsed_seconds=off_elapsed, peak_resident_bytes=off_peak, native_log=str(off_log)),
                  dll=str(DLL), dll_sha256=hashlib.sha256(DLL.read_bytes()).hexdigest(),
                  scope=('production FrameSurvey/coordinator/conversion/RRWrapper, actual D3D12 compute detours and '
                         'RestoreRoot, production FfxApiProxy routing/context-map functions, signed AMD exports; '
                         'creation/SL/lease/module-loader/witness adapters; no full application loader '
                         'or Cyberpunk runtime/image-quality claim'))
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    report = Path(os.environ.get('FSRD_NRD_E2E_REPORT', f'E:/FSRD/sol_batch/{out.parents[1].name}'))
    report.mkdir(parents=True, exist_ok=True)
    (report / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    run()
