"""NEW actual-host A/B RR-only transactions. Source preparation is compiler-free.

Shipping shader-role/readiness and caller-strong Release-coverage bootstraps are
explicit adapters. Native GUIDs/hashes/Birth metadata, actual D3D/AMD work and
retained descriptor submission checks are not replaced. No title/game proof.
"""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import os
import sys
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(HERE), str(HERE.parent)]
import test_fsrd_nrd_e2e as baseline
from test_fsrd_nrd_bridge_rr import bounded_run, DLL
from fsrd_toolchain import compile_cpp

PREFIX = r'''#include "fixture_support.h"
#include <resource_tracking/FrameSurvey_Dx12.h>
#include "__ROOT__/OptiScaler/misc/NrdBridgeNativeBirth_Dx12.h"
#include <unordered_set>
#include <mutex>
#include <stdexcept>
std::mutex nativeFixtureMutex;
std::unordered_set<IUnknown*> nativeFixtureKnown;
void NativeFixtureRegister(IUnknown* object) {
 if(!object)throw std::runtime_error("fixture native bootstrap rejects NULL");
 Microsoft::WRL::ComPtr<IUnknown> canonical;
 if(FAILED(object->QueryInterface(IID_PPV_ARGS(&canonical)))||!canonical)throw std::runtime_error("native canonical identity unavailable");
 // Caller holds real strong owners. No native call/ref destruction under this lock.
 {std::scoped_lock lock(nativeFixtureMutex);nativeFixtureKnown.insert(object);nativeFixtureKnown.insert(canonical.Get());}
}
bool NativeFixtureCoverage(IUnknown* object) noexcept {
 std::scoped_lock lock(nativeFixtureMutex);return object&&nativeFixtureKnown.contains(object);
}
void NativeFixtureResourceCreated(ID3D12Resource* object,D3D12_RESOURCE_STATES state,ID3D12Heap* heap=nullptr,uint64_t offset=0) noexcept {
 try{NativeFixtureRegister(object);FrameSurvey::ResourceCreated(object,state,heap,offset);}catch(...){FrameSurvey::MetadataHookFailed("fixture native resource bootstrap failed");}
}
void NativeFixtureRootCreated(ID3D12RootSignature* object,const void* bytes,size_t length) noexcept {
 try{
  NativeFixtureRegister(object);const auto birth=NrdBridgeNativeBirth::Prepare(object);
  Microsoft::WRL::ComPtr<ID3D12VersionedRootSignatureDeserializer> parsed;
  if(!birth||FAILED(D3D12CreateVersionedRootSignatureDeserializer(bytes,length,IID_PPV_ARGS(&parsed))))throw std::runtime_error("actual serialized root/count unavailable");
  const auto* native=parsed->GetUnconvertedRootSignatureDesc();
  struct RootCountWitness{uint64_t stamp;UINT count,version;} count{birth->InstanceStamp(),native->Version==D3D_ROOT_SIGNATURE_VERSION_1_0?native->Desc_1_0.NumParameters:native->Desc_1_1.NumParameters,1};
  constexpr GUID guid={0x72304b14,0x1a2e,0x46be,{0xae,0xdc,0x22,0x50,0x50,0x4d,0xc9,0x64}};
  if(FAILED(object->SetPrivateData(guid,sizeof(count),&count)))throw std::runtime_error("native creation count witness write failed");
  FrameSurvey::RootCreated(object,bytes,length);
 }catch(...){FrameSurvey::MetadataHookFailed("fixture native root bootstrap failed");}
}
void NativeFixtureHeapCreated(ID3D12Device* device,ID3D12DescriptorHeap* heap) noexcept {
 try{NativeFixtureRegister(heap);FrameSurvey::HeapCreated(device,heap);}catch(...){FrameSurvey::MetadataHookFailed("fixture native heap bootstrap failed");}
}
void NativeFixturePipelineCreated(ID3D12PipelineState* object,const D3D12_COMPUTE_PIPELINE_STATE_DESC& description) noexcept {
 try{NativeFixtureRegister(object);FrameSurvey::PipelineCreated(object,description);}catch(...){FrameSurvey::MetadataHookFailed("fixture native compute bootstrap failed");}
}
void NativeFixturePipelineCreated(ID3D12PipelineState* object,const D3D12_GRAPHICS_PIPELINE_STATE_DESC& description) noexcept {
 try{NativeFixtureRegister(object);FrameSurvey::PipelineCreated(object,description);}catch(...){FrameSurvey::MetadataHookFailed("fixture native graphics bootstrap failed");}
}
#define main PreservedNativeE2EMain
'''
DRAW = r'''
namespace NativeDraw {
using Wiring::gNrdBridgeWrappers;
using DrawFn=void(WINAPI*)(ID3D12GraphicsCommandList*,UINT,UINT,UINT,UINT);
DrawFn o_DrawInstanced=nullptr;
void hkDrawInstanced(ID3D12GraphicsCommandList* list,UINT vertices,UINT instances,UINT first,UINT instance){o_DrawInstanced(list,vertices,instances,first,instance);}
__ACTUAL_DRAW_BODY__
void Attach(ID3D12GraphicsCommandList* list){auto** table=*reinterpret_cast<void***>(list);o_DrawInstanced=reinterpret_cast<DrawFn>(table[12]);hr(DetourTransactionBegin());hr(DetourUpdateThread(GetCurrentThread()));need(DetourAttach(&(PVOID&)o_DrawInstanced,hkSurveyDrawInstanced)==NO_ERROR,"actual title Draw detour attached");need(DetourTransactionCommit()==NO_ERROR,"actual Draw observer committed");}
void Detach(){hr(DetourTransactionBegin());hr(DetourUpdateThread(GetCurrentThread()));need(DetourDetach(&(PVOID&)o_DrawInstanced,hkSurveyDrawInstanced)==NO_ERROR,"actual Draw detour detached");need(DetourTransactionCommit()==NO_ERROR,"Draw observer detached");}
}
'''

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(out):
    out.mkdir(parents=True, exist_ok=True)
    calls, original = [], baseline.compile_cpp
    baseline.compile_cpp = lambda *args, **kwargs: calls.append((args, kwargs))
    try:
        baseline.build(out)
    finally:
        baseline.compile_cpp = original
    assert len(calls) == 1
    args, kwargs = calls[0]
    source = Path(args[0]).read_text()
    # These wrappers witness REAL caller-owned interfaces and then invoke the
    # actual production metadata functions, including native GUID election.
    for name in ('ResourceCreated', 'RootCreated', 'HeapCreated', 'PipelineCreated'):
        source = source.replace('FrameSurvey::' + name + '(', 'NativeFixture' + name + '(')
    old = baseline.method(source, 'bool ObserveReleaseCoverage(')
    source = source.replace(old, 'bool ObserveReleaseCoverage(IUnknown* object) noexcept { return NativeFixtureCoverage(object); }')
    res = (ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.cpp').read_text()
    draw = DRAW.replace('__ACTUAL_DRAW_BODY__', baseline.res_function(res, 'hkSurveyDrawInstanced'))
    fixture = HERE/'fsrd_nrd_native_transactions.cpp'
    path, exe = out/'native_transactions.cpp', out/'native_transactions.exe'
    path.write_text(PREFIX.replace('__ROOT__', ROOT.as_posix()) + source + '\n#undef main\n' + draw + fixture.read_text())
    manifest = dict(schema='native-transactions-source-v1', compiler_executed=False, native_executed=False, gpu_executed=False,
                    generated_cpp_sha256=sha(path), fixture_sha256=sha(fixture), driver_sha256=sha(__file__),
                    shipping_readiness=False, explicit_role_readiness_adapter=True,
                    native_birth_ready=True, native_physical_detours_proved=False,
                    original_fixture_sha256=sha(HERE/'fsrd_nrd_e2e_fixture.cpp'))
    (out/'source-preparation.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return exe, (path, exe, *args[2:]), kwargs


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    out = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15e-quality/tests/native-transactions'))
    exe, command, keywords = prepare(out)
    if args.prepare_only:
        print(json.dumps(dict(source=str(command[0]), compiler_executed=False, native_executed=False)))
        return
    compile_cpp(*command, **keywords)
    _, peak, elapsed, log = bounded_run([str(exe), str(out), str(DLL)], out/'native_run')
    value = json.loads((out/'native-transactions-result.json').read_text())
    assert value['debug_errors'] == value['debug_warnings'] == 0
    assert value['provider_dispatches'] == 12 and value['contexts'] == 2
    assert len(value['frames']) == 6
    assert [row['SL_frame'] for row in value['frames']] == list(range(1, 7))
    assert all(row['signed_dispatches'] == 2 and row['native_filter_gpu_executions'] == 0 for row in value['frames'])
    assert all(row['exact_rr_rgb_words'] == 128*128*12 for row in value['frames'])
    value.update(python_checks=6, elapsed_seconds=elapsed, peak_resident_bytes=peak, native_log=str(log),
                 source_sha256=sha(command[0]), exe_sha256=sha(exe), provider_sha256=sha(DLL))
    (out/'native-transactions-result.json').write_text(json.dumps(value, indent=2)+'\n')
    print(json.dumps(value, indent=2))


if __name__ == '__main__':
    run()
