"""Focused source-extracted RESET-reference ABI/config/memory CPU contract.

No D3D device, provider DLL, queue, shader or SDK context is created. Preparation,
compilation and execution are separate explicit phases; root owns execution.
This does not validate PrepareSnapshot GPU leases, SDK resource return states,
cross-queue scheduling, in-memory module bytes or image quality.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
HELPER = ROOT / 'OptiScaler/upscalers/fsr31/FSRDFullContextReference_Dx12.h'
FEATURE = ROOT / 'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp'
sys.path.insert(0, str(HERE.parent))
from fsrd_toolchain import compile_cpp

CPP = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <ffx_denoiser.h>
#include <json.hpp>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include "full_context_reference_pure.inc"
using Json = nlohmann::json;
void Need(bool value,const char* message) { if (!value) throw std::runtime_error(message); }
struct ConfigureCall { uint64_t key,count; ffxContext context; std::array<uint8_t,8> words {}; };
struct FfxApiProxy
{
    inline static std::vector<ConfigureCall> calls;
    inline static uint64_t failKey=0,total=201129984,aliasable=133234688;
    inline static ffxReturnCode_t memoryCode=FFX_API_RETURN_OK;
    inline static ffxContext expectedContext=reinterpret_cast<ffxContext>(uintptr_t(0x9990));
    inline static bool sawNull=false,sawActual=false;
    static ffxReturnCode_t D3D12_Configure(ffxContext* context,const ffxConfigureDescHeader* header)
    {
        Need(context && *context==expectedContext,"configure did not use private context");
        Need(header && header->type==FFX_API_CONFIGURE_DESC_TYPE_DENOISER_KEYVALUE,"configure type wrong");
        auto& desc=*reinterpret_cast<const ffxConfigureDescDenoiserKeyValue*>(header);
        Need(desc.count==1 && desc.data,"typed configure count/data invalid");
        ConfigureCall call {desc.key,desc.count,*context};
        std::memcpy(call.words.data(),desc.data,desc.key==7 ? 8 : 4); calls.push_back(call);
        return desc.key==failKey ? FFX_API_RETURN_ERROR_RUNTIME_ERROR : FFX_API_RETURN_OK;
    }
    static ffxReturnCode_t QueryDenoiserAttestedRouteDx12(ffxContext route,ffxContext* context,ffxQueryDescHeader* header)
    {
        Need(route==expectedContext,"memory query escaped frozen route");
        Need(header && header->type==FFX_API_QUERY_DESC_TYPE_DENOISER_GPU_MEMORY_USAGE,"memory query type wrong");
        auto& desc=*reinterpret_cast<ffxQueryDescDenoiserGetGPUMemoryUsage*>(header);
        Need(desc.device==reinterpret_cast<void*>(uintptr_t(0x1110)),"memory query device missing");
        Need(desc.maxRenderSize.width==1505 && desc.maxRenderSize.height==847 &&
             desc.signalFlags==34 && !desc.checkerboardSignalFlags && !desc.flags,"memory query create fields changed");
        if (!context)
        {
            sawNull=true;
            Need(header->pNext && header->pNext->type==FFX_API_DESC_TYPE_OVERRIDE_VERSION,"planned provider override missing");
            Need(reinterpret_cast<const ffxOverrideVersion*>(header->pNext)->versionId==0x101020000ull,"planned provider differs");
        }
        else { sawActual=true; Need(*context==expectedContext && !header->pNext,"actual query context/override wrong"); }
        Need(desc.gpuMemoryUsage,"memory output missing");
        desc.gpuMemoryUsage->totalUsageInBytes=total; desc.gpuMemoryUsage->aliasableUsageInBytes=aliasable;
        return memoryCode;
    }
};
struct ReferenceConfiguration { std::array<float,6> tuning {}; FfxApiFloatBounds debugDepthBounds {}; };
struct ExtractedReference
{
    using Configuration=ReferenceConfiguration;
    using Json=nlohmann::json;
    ffxContext m_context=FfxApiProxy::expectedContext;
    bool m_configured=false;
    std::array<float,6> m_appliedTuning {};
    FfxApiFloatBounds m_appliedDebugDepthBounds {};
    Configuration m_config;
    static uint64_t Address(const void* p) noexcept { return uint64_t(reinterpret_cast<uintptr_t>(p)); }
#include "full_context_reference_configure.inc"
#include "full_context_reference_memory.inc"
};
FfxApiResource Binding(unsigned ordinal)
{
    FfxApiResource result {};
    result.resource=reinterpret_cast<void*>(uintptr_t(0x1000+ordinal*0x100));
    result.state=ordinal<7 ? FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ : FFX_API_RESOURCE_STATE_UNORDERED_ACCESS;
    result.description.type=FFX_API_RESOURCE_TYPE_TEXTURE2D;
    result.description.format=4; result.description.width=1505; result.description.height=847;
    result.description.depth=1; result.description.mipCount=1; result.description.usage=FFX_API_RESOURCE_USAGE_UAV;
    return result;
}
int main() try
{
    using namespace FSRD::FullContextReference;
    static_assert(sizeof(ffxDispatchDescDenoiser)==448 && ControlOffset==264 && ControlBytes==184 && FlagsOffset==180);
    static_assert(offsetof(ffxDispatchDescDenoiser,frameIndex)==440 && offsetof(ffxDispatchDescDenoiser,flags)==444);
    ffxDispatchDescDenoiser primary {},reference {};
    ffxDispatchDescDenoiserDirectDiffuse diffuse {},referenceDiffuse {};
    ffxDispatchDescDenoiserIndirectSpecular specular {},referenceSpecular {};
    primary.header.type=FFX_API_DISPATCH_DESC_TYPE_DENOISER;
    primary.header.pNext=&diffuse.header;
    primary.commandList=reinterpret_cast<void*>(uintptr_t(0x4440));
    diffuse.header.type=FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE; diffuse.header.pNext=&specular.header;
    specular.header.type=FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR;
    primary.linearDepth=Binding(0); primary.motionVectors=Binding(1); primary.normals=Binding(2);
    primary.specularAlbedo=Binding(3); primary.diffuseAlbedo=Binding(4);
    diffuse.signal.input=Binding(5); specular.signal.input=Binding(6);
    diffuse.signal.output=Binding(7); specular.signal.output=Binding(8);
    auto* controls=reinterpret_cast<uint8_t*>(&primary)+ControlOffset;
    for (size_t i=0;i<ControlBytes;++i) controls[i]=uint8_t(i*37+19);
    primary.frameIndex=7162; primary.flags=2;
    const auto savedPrimary=primary; const auto savedDiffuse=diffuse; const auto savedSpecular=specular;
    std::array<ID3D12Resource*,7> clones {};
    for (size_t i=0;i<clones.size();++i) clones[i]=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x10000+i*0x100));
    auto* outputDiffuse=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x20000));
    auto* outputSpecular=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x21000));
    RebuildResetDispatch(primary,diffuse,specular,clones,outputDiffuse,outputSpecular,reference,referenceDiffuse,referenceSpecular);
    Need(OnlyResetControlChanged(primary,reference),"original184 byte RESET-only witness rejected");
    Need(reference.header.pNext==&referenceDiffuse.header && referenceDiffuse.header.pNext==&referenceSpecular.header &&
         !referenceSpecular.header.pNext,"descriptor chain borrowed primary/local pointers");
    Need(reference.header.type==primary.header.type && reference.commandList==primary.commandList &&
         referenceDiffuse.header.type==diffuse.header.type && referenceSpecular.header.type==specular.header.type,
         "typed header/list metadata changed");
    const std::array<FfxApiResource,9> before {primary.linearDepth,primary.motionVectors,primary.normals,
        primary.specularAlbedo,primary.diffuseAlbedo,diffuse.signal.input,specular.signal.input,diffuse.signal.output,specular.signal.output};
    const std::array<FfxApiResource,9> after {reference.linearDepth,reference.motionVectors,reference.normals,
        reference.specularAlbedo,reference.diffuseAlbedo,referenceDiffuse.signal.input,referenceSpecular.signal.input,
        referenceDiffuse.signal.output,referenceSpecular.signal.output};
    for (size_t i=0;i<after.size();++i)
    {
        const auto* wanted=i<7 ? clones[i] : i==7 ? outputDiffuse : outputSpecular;
        Need(after[i].resource==wanted && after[i].resource!=before[i].resource,"one of nine pointer substitutions missing");
        Need(after[i].state==before[i].state && FfxDescription(after[i].description)==FfxDescription(before[i].description),
             "replacement changed actual FFX description/state");
    }
    Need(!std::memcmp(&primary,&savedPrimary,sizeof(primary)) && !std::memcmp(&diffuse,&savedDiffuse,sizeof(diffuse)) &&
         !std::memcmp(&specular,&savedSpecular,sizeof(specular)),"helper changed original descriptor/controls");
    unsigned rejected=0;
    for (size_t i=0;i<FlagsOffset;++i)
    {
        auto changed=reference; (reinterpret_cast<uint8_t*>(&changed)+ControlOffset)[i]^=1;
        Need(!OnlyResetControlChanged(primary,changed),"non-RESET byte mutation accepted"); ++rejected;
    }
    for (const auto flags : {0u,1u,2u,4u,7u})
    { auto changed=reference; changed.flags=flags; Need(!OnlyResetControlChanged(primary,changed),"wrong flags accepted"); ++rejected; }
    auto alreadyReset=primary; alreadyReset.flags=3;
    RebuildResetDispatch(alreadyReset,diffuse,specular,clones,outputDiffuse,outputSpecular,reference,referenceDiffuse,referenceSpecular);
    Need(OnlyResetControlChanged(alreadyReset,reference) && reference.flags==3,"already-reset primary changed");
    Need(ControlWordsHex(primary).size()==368 && ControlWordsHex(reference).substr(360)=="03000000","native witness wireformat wrong");
    D3D12_RESOURCE_DESC native {};
    native.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D; native.Alignment=65536; native.Width=1505; native.Height=847;
    native.DepthOrArraySize=native.MipLevels=1; native.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;
    native.SampleDesc.Count=1; native.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
    Need(SameNativeDescription(native,native),"same native contract rejected");
    auto n=native; n.Width=128; Need(!SameNativeDescription(native,n),"cropped native width accepted");
    n=native; n.Alignment=0; Need(!SameNativeDescription(native,n),"native alignment change accepted");
    n=native; n.MipLevels=2; Need(!SameNativeDescription(native,n),"native mip change accepted");
    n=native; n.Format=DXGI_FORMAT_R8G8B8A8_UNORM; Need(!SameNativeDescription(native,n),"native format change accepted");
    Need(ValidMemoryCounters(201129984,133234688) && ValidMemoryCounters(1,0),"valid memory counters rejected");
    Need(!ValidMemoryCounters(0,0) && !ValidMemoryCounters(1,2) && !ValidMemoryCounters(UINT64_MAX,65536) &&
         !ValidMemoryCounters(uint64_t(-200998912ll),65536) && !ValidMemoryCounters(1ull<<63,0),"invalid/underflow memory counters accepted");
    ExtractedReference host; ReferenceConfiguration config {{.5f,.5f,40000.f,40.f,.5f,.1f},{0.f,1024.f}};
    host.Configure(config); Need(FfxApiProxy::calls.size()==7,"first configure did not send keys1..7");
    for (size_t i=0;i<7;++i)
    {
        const auto& call=FfxApiProxy::calls[i]; Need(call.key==i+1 && call.count==1,"configuration key/count changed");
        Need(!std::memcmp(call.words.data(),i<6 ? static_cast<const void*>(&config.tuning[i]) : &config.debugDepthBounds,i<6 ? 4 : 8),
             "typed configuration data changed");
    }
    host.Configure(config); Need(FfxApiProxy::calls.size()==7,"unchanged tuning resubmitted");
    config.tuning[2]=39999; host.Configure(config);
    Need(FfxApiProxy::calls.size()==8 && FfxApiProxy::calls.back().key==3,"changed tuning key not applied privately");
    FfxApiProxy::failKey=4; config.tuning[3]=41; bool configureFailed=false;
    try { host.Configure(config); } catch (const std::exception&) { configureFailed=true; }
    Need(configureFailed && host.m_appliedTuning[3]==40,"failed configure committed private cache");
    ffxQueryDescDenoiserGetGPUMemoryUsage query {}; FfxApiEffectMemoryUsage usage {};
    query.header.type=FFX_API_QUERY_DESC_TYPE_DENOISER_GPU_MEMORY_USAGE; query.device=reinterpret_cast<void*>(uintptr_t(0x1110));
    query.maxRenderSize={1505,847}; query.signalFlags=34; query.gpuMemoryUsage=&usage;
    ffxOverrideVersion version {}; version.header.type=FFX_API_DESC_TYPE_OVERRIDE_VERSION; version.versionId=0x101020000ull;
    query.header.pNext=&version.header;
    auto memory=ExtractedReference::QueryMemoryWithDevice(host.m_context,nullptr,query,usage);
    Need(memory["available"]==true && memory["provider_override"]==version.versionId &&
         memory["total_usage_bytes"]==201129984,"planned pinned memory receipt wrong");
    query.header.pNext=nullptr; FfxApiProxy::total=uint64_t(-200998912ll); FfxApiProxy::aliasable=65536;
    memory=ExtractedReference::QueryMemoryWithDevice(host.m_context,&host.m_context,query,usage);
    Need(memory["available"]==false && memory["total_usage_bytes"].is_null() &&
         memory["raw_reported_total_usage_bytes"]==uint64_t(-200998912ll),"RC_OK wrapped actual usage misreported");
    FfxApiProxy::total=0; FfxApiProxy::aliasable=0;
    memory=ExtractedReference::QueryMemoryWithDevice(host.m_context,&host.m_context,query,usage);
    Need(memory["available"]==false && memory["total_usage_bytes"].is_null(),"zero actual memory reported valid");
    FfxApiProxy::total=1; FfxApiProxy::aliasable=2;
    memory=ExtractedReference::QueryMemoryWithDevice(host.m_context,&host.m_context,query,usage);
    Need(memory["available"]==false,"aliasable subset violation reported valid");
    FfxApiProxy::total=100; FfxApiProxy::aliasable=10; FfxApiProxy::memoryCode=FFX_API_RETURN_ERROR_RUNTIME_ERROR;
    memory=ExtractedReference::QueryMemoryWithDevice(host.m_context,&host.m_context,query,usage);
    Need(memory["available"]==false && memory["total_usage_bytes"].is_null(),"failed SDK memory call reported valid");
    Need(FfxApiProxy::sawNull && FfxApiProxy::sawActual,"expected/actual typed query paths not covered");
    std::cout<<Json{{"schema","fsrd-full-context-reference-controls-cpu-v1"},{"status","PASS"},
        {"original_control_bytes",184},{"native_dispatch_bytes",448},{"negative_control_cases",rejected},
        {"pointer_substitutions",9},{"configure_keys_count1",7},{"gpu_work",0},{"SDK_dispatches",0},
        {"limitations","Source-extracted pure controls/config/memory; no PrepareSnapshot leases or GPU SDK behavior validated"}}.dump(2)<<'\n';
    return 0;
}
catch (const std::exception& error) { std::cerr<<error.what()<<'\n'; return 1; }
'''


def method(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    level = 1
    end = brace + 1
    while level:
        if source[end] == '{':
            level += 1
        elif source[end] == '}':
            level -= 1
        end += 1
    return source[start:end]


def structural_checks(helper, feature):
    preparation = method(helper, 'bool PrepareSnapshot(')
    assert preparation.index('ValidateBindings(') < preparation.index('RecordFullInputSnapshot(')
    assert preparation.index('if (!retain || !retain(m_storage->owner))') < preparation.index('RecordFullInputSnapshot(')
    assert preparation.index('RetainComputeDispatch(device, list, frameLease)') < preparation.index('RecordFullInputSnapshot(')
    assert 'frameLease->sources[i] = original' in preparation
    storage = method(helper, 'void CreateStorage(')
    assert 'plannedVersion.versionId = c.providerId' in storage
    assert storage.index('query.header.pNext = &plannedVersion.header') < storage.index('QueryMemoryWithDevice(c.primaryContext, nullptr')
    assert storage.index('query.header.pNext = nullptr') < storage.index('m_memory["actual_after_creation"]')
    assert 'nativeBytes + usage.totalUsageInBytes + PrimaryBudgetHeadroom' in storage
    assert 'const auto initial = i < inputs.size() ? ReadState : D3D12_RESOURCE_STATE_UNORDERED_ACCESS' in storage
    assert 'storage->owner = std::shared_ptr<FfxContextOwner>(lifetime, lifetime->owner.get())' in storage
    lifetime = method(helper, '~ContextLifetime()')
    assert lifetime.index('owner.reset()') < lifetime.index('FreeLibrary(module)')
    dispatch = method(feature, 'RRResult FSRDFeatureDx12::DispatchDenoiser(')
    assert dispatch.index('SnapshotGameTraceDispatch(dispatchDesc)') < dispatch.index('PrepareFullContextReference(InCommandList, dispatchDesc)')
    assert dispatch.index('PrepareFullContextReference(InCommandList, dispatchDesc)') < dispatch.index('FfxApiProxy::D3D12_Dispatch(&_pDenoiserCtx')
    prepare = method(feature, 'void FSRDFeatureDx12::PrepareFullContextReference(')
    assert 'WantsFullContextReference()' in prepare and 'HasAdmittedGameTraceFrame()' in prepare
    assert 'InvalidateDenoiserHistory' not in prepare and 'ClassifyRayRegenerationFailure' not in prepare
    evaluate = method(feature, 'RRResult FSRDFeatureDx12::EvaluateRayRegeneration(')
    assert evaluate.index('DispatchComposition(InCommandList, compDesc)') < evaluate.index('ExecuteResetReference(InCommandList, _pDenoiserCtx)')
    assert evaluate.index('ExecuteResetReference(InCommandList, _pDenoiserCtx)') < evaluate.index('CompleteGameTraceFrame(InCommandList,denoiserDesc')
    return {'status': 'PASS_SOURCE_ASSERTIONS', 'count': 17,
            'limitation': 'Structural checks do not replace source review or GPU execution'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    phase = parser.add_mutually_exclusive_group(required=True)
    phase.add_argument('--prepare-only', action='store_true')
    phase.add_argument('--compile-only', action='store_true')
    phase.add_argument('--cpu-only', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.drive.upper() != 'F:':
        raise ValueError('Generated CPU contract fixtures must stay on F:')
    helper = HELPER.read_text(encoding='utf-8-sig')
    feature = FEATURE.read_text(encoding='utf-8-sig')
    source_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (HELPER, FEATURE, Path(__file__))}
    output.mkdir(parents=True, exist_ok=True)
    prepared = output / 'prepared.json'
    exe = output / 'fsrd_full_context_reference_controls.exe'
    if args.prepare_only:
        checks = structural_checks(helper, feature)
        pure = helper[helper.index('namespace FSRD::FullContextReference'):helper.index('// Diagnostic only:')]
        (output / 'full_context_reference_pure.inc').write_text(pure, encoding='utf-8')
        (output / 'full_context_reference_configure.inc').write_text(method(helper, 'void Configure('), encoding='utf-8')
        (output / 'full_context_reference_memory.inc').write_text(method(helper, 'static Json QueryMemoryWithDevice('), encoding='utf-8')
        (output / 'fsrd_full_context_reference_controls.cpp').write_text(CPP, encoding='utf-8')
        report = {'schema': 'fsrd-full-context-reference-controls-prepared-v1', 'status': 'PREPARED_ONLY',
                  'source_hashes': source_hashes, 'structural_checks': checks, 'GPU_work': 0, 'compiles': 0, 'executions': 0}
        prepared.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2))
    else:
        report = json.loads(prepared.read_text())
        if report['source_hashes'] != source_hashes:
            raise RuntimeError('Source changed after fixture preparation; prepare a new fixture before compiling/running')
        if args.compile_only:
            compile_cpp(output / 'fsrd_full_context_reference_controls.cpp', exe,
                        include_dirs=(output, ROOT / 'external/nlohmann',
                                      ROOT / 'external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include'))
            print(json.dumps({'status': 'COMPILED_ONLY', 'exe': str(exe), 'GPU_work': 0, 'executions': 0}))
        else:
            result = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
            receipt = json.loads(result.stdout)
            receipt['source_hashes'] = source_hashes
            (output / 'controls_cpu_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
            print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
