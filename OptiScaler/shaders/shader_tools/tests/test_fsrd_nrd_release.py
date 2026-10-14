"""Execute dedicated/shared-IUnknown production Release paths before final destruction.

The object has only IUnknown's vtable: command-list cache cleanup must use its
address and must never dereference it as a D3D12 list/resource/PSO.
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
from test_fsrd_frame_survey_wiring import function as res_function


def function_with_defaults(source, signature, body_prefix=''):
    """Extract a whole method after its parameter list, including `{}` defaults."""
    start = source.index(signature)
    opening = source.index('(', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == '(') - (source[end] == ')')
        end += 1
    brace = source.index('{', end)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:brace+1] + body_prefix + source[brace+1:end]


def birth_gate_and_generic(source):
    start = source.index('static bool UseNrdNativeRetirement()')
    sticky = source.find('static std::atomic<bool> gRRInspectorLifetimeProtection')
    if sticky >= 0:
        start = min(start, sticky)
    end = source.index('static void PublishComputeHookAvailability()', start)
    body = source[start:end]
    if 'using PFN_BirthRelease' not in body:
        typedef = re.search(r'using PFN_BirthRelease\s*=\s*[^;]+;', source)
        assert typedef, 'actual native Release function-pointer alias missing'
        body = typedef.group(0) + '\n' + body
    return body


def tracked_resource_cache(source):
    if 'static void EraseRRTrackedResourceLocked(' not in source:
        return ''
    start = source.index('struct RRTrackedResourceViews')
    end = source.index('struct RRCommandListMarkerState', start)
    return source[start:end]


ENTRY_PROBE = r'''
#define NOMINMAX
#include <d3d12.h>
#include <dxgi1_6.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <json.hpp>
#include <iostream>
#include <sstream>
#include <stdexcept>
using Microsoft::WRL::ComPtr;
using J=nlohmann::json;
void hr(HRESULT value){if(FAILED(value))throw std::runtime_error("D3D12 HRESULT "+std::to_string(value));}
std::string utf8(const wchar_t* text){int size=WideCharToMultiByte(CP_UTF8,0,text,-1,nullptr,0,nullptr,nullptr);std::string out(size,0);WideCharToMultiByte(CP_UTF8,0,text,-1,out.data(),size,nullptr,nullptr);out.pop_back();return out;}
uintptr_t releaseEntry(IUnknown* object){return uintptr_t((*reinterpret_cast<void***>(object))[2]);}
std::string address(uintptr_t value){std::ostringstream out;out<<"0x"<<std::hex<<value;return out.str();}
J probe(IDXGIAdapter* adapter,const std::string& name){
 ComPtr<ID3D12Device> device;hr(D3D12CreateDevice(adapter,D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)));
 D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;desc.Width=256;desc.Height=desc.DepthOrArraySize=desc.MipLevels=desc.SampleDesc.Count=1;desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
 ComPtr<ID3D12Resource> resource;hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_COMMON,nullptr,IID_PPV_ARGS(&resource)));
 ComPtr<ID3D12DescriptorHeap> descriptors;D3D12_DESCRIPTOR_HEAP_DESC hdesc{};hdesc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;hdesc.NumDescriptors=4;hdesc.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;hr(device->CreateDescriptorHeap(&hdesc,IID_PPV_ARGS(&descriptors)));
 ComPtr<ID3DBlob> rootBlob,error,shader;D3D12_ROOT_SIGNATURE_DESC rdesc{};hr(D3D12SerializeRootSignature(&rdesc,D3D_ROOT_SIGNATURE_VERSION_1,&rootBlob,&error));ComPtr<ID3D12RootSignature> root;hr(device->CreateRootSignature(0,rootBlob->GetBufferPointer(),rootBlob->GetBufferSize(),IID_PPV_ARGS(&root)));
 const char hlsl[]="[numthreads(1,1,1)] void main() {}";hr(D3DCompile(hlsl,sizeof(hlsl)-1,nullptr,nullptr,nullptr,"main","cs_5_0",0,0,&shader,&error));D3D12_COMPUTE_PIPELINE_STATE_DESC pdesc{};pdesc.pRootSignature=root.Get();pdesc.CS={shader->GetBufferPointer(),shader->GetBufferSize()};ComPtr<ID3D12PipelineState> pso;hr(device->CreateComputePipelineState(&pdesc,IID_PPV_ARGS(&pso)));
 ComPtr<ID3D12CommandAllocator> directAllocator,computeAllocator;ComPtr<ID3D12GraphicsCommandList> direct,compute;hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&directAllocator)));hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COMPUTE,IID_PPV_ARGS(&computeAllocator)));hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,directAllocator.Get(),nullptr,IID_PPV_ARGS(&direct)));hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_COMPUTE,computeAllocator.Get(),nullptr,IID_PPV_ARGS(&compute)));hr(direct->Close());hr(compute->Close());
 const auto r=releaseEntry(resource.Get()),h=releaseEntry(descriptors.Get()),p=releaseEntry(pso.Get()),d=releaseEntry(direct.Get()),c=releaseEntry(compute.Get());
 return {{"adapter",name},{"debug_layer_enabled",false},{"entries",{{"resource",address(r)},{"descriptor_heap",address(h)},{"pso",address(p)},{"direct_list",address(d)},{"compute_list",address(c)}}},{"resource_heap_equal",r==h},{"resource_pso_equal",r==p},{"resource_direct_list_equal",r==d},{"heap_pso_equal",h==p},{"heap_direct_list_equal",h==d},{"heap_compute_list_equal",h==c},{"direct_compute_list_equal",d==c}};
}
int main()try{ComPtr<IDXGIFactory4> factory;hr(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));ComPtr<IDXGIAdapter1> hardware;std::string hardwareName;for(UINT index=0;;++index){ComPtr<IDXGIAdapter1> adapter;if(factory->EnumAdapters1(index,&adapter)==DXGI_ERROR_NOT_FOUND)break;DXGI_ADAPTER_DESC1 desc{};hr(adapter->GetDesc1(&desc));const auto name=utf8(desc.Description);if(!(desc.Flags&DXGI_ADAPTER_FLAG_SOFTWARE)&&desc.VendorId==0x1002&&name.find("9070")!=std::string::npos){hardware=adapter;hardwareName=name;break;}}if(!hardware)throw std::runtime_error("RX9070 adapter not found");ComPtr<IDXGIAdapter> warp;hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)));J out={{"scope","actual native D3D12 vtable addresses without debug wrappers; objects created and released, no Dispatch/Execute"},{"adapters",J::array({probe(hardware.Get(),hardwareName),probe(warp.Get(),"WARP")})}};std::cout<<out.dump(2)<<'\n';return 0;}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
'''


def entries():
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    source, exe = out/'heap_release_entries.cpp', out/'heap_release_entries.exe'
    source.write_text(ENTRY_PROBE)
    compile_cpp(source, exe, ('d3d12.lib', 'dxgi.lib', 'dxguid.lib', 'd3dcompiler.lib'), (ROOT/'external/nlohmann',))
    result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
    (out/'native.log').write_text(result.stdout + result.stderr)
    result.check_returncode()
    values = json.loads(result.stdout)
    (out/'result.json').write_text(json.dumps(values, indent=2)+'\n')
    print(result.stdout, end='')


def run():
    d3d = (ROOT/'OptiScaler/hooks/D3D12_Hooks.cpp').read_text()
    resource_source = Path(os.environ.get('FSRD_RELEASE_RESOURCE_SOURCE',ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.cpp'))
    res = resource_source.read_text()
    survey = (ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').read_text()
    res_header = Path(os.environ.get('FSRD_RELEASE_RESOURCE_HEADER',ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.h')).read_text()
    teardown = function(res, 'void ResTrack_Dx12::ReleaseDeviceHooks()')
    detach_begin = teardown.index('    if (o_Release != nullptr &&')
    detach_end = teardown.index('    if (o_PsoRelease != nullptr)', detach_begin)
    reset_begin = teardown.index('    o_Release = nullptr;')
    reset_end = teardown.index('    gComputeExecuteEntry = nullptr;', reset_begin)
    state = d3d[d3d.index('// Common'):d3d.index('// Intel Atomic Extension')]
    state = state.replace('ankerl::unordered_dense::map','std::unordered_map')
    cpp = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <array>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include "__ROOT__/OptiScaler/include/d3dx/d3dx12.h"
#include "__ROOT__/OptiScaler/include/detours/detours.h"
#include <vector>
#include <memory>
#include <algorithm>
#include <shared_mutex>
#include <mutex>
#include <unordered_map>
#include <unordered_set>
#include <map>
#include <stdexcept>
#include <iostream>
#include <atomic>
#include <chrono>
#include <future>
#include <thread>
#include <functional>
#include <utility>
#include "__ROOT__/OptiScaler/misc/NrdBridgeBirth_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgeNativeBirth_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgeLifetime_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgePerf_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgeOwned_Dx12.h"
#include "__ROOT__/OptiScaler/hooks/Hook_Utils.h"
#define LOG_INFO(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
namespace NrdBridgeNativeBirth { bool ObserveReleaseCoverage(IUnknown*) noexcept; }
bool gNrdBridgeDeviceWrappers=true,gNrdBridgeWrappers=true,gSurveyWrappers=true;
__STATE__
unsigned checks=0,releasesObserved=0,psoCleaned=0,slotsCleaned=0,leaseEnds=0;
std::atomic<unsigned> leaseBegins=0;
PVOID gResourceReleaseEntry=nullptr,gHeapReleaseEntry=nullptr,gCommandListReleaseEntry=nullptr,gPsoReleaseEntry=nullptr;
bool gHeapOwnsReleaseHook=false,gResourceReleaseSharesHeap=false,gResourceReleaseSharesBirth=false;
std::atomic<bool> gHeapReleaseSharesResource=false;
std::recursive_mutex gReleaseHookInstallMutex;
unsigned nativeAttaches=0;
enum class InstallFailure { None,Begin,Update,Attach,Commit };
InstallFailure installFailure=InstallFailure::None;
bool adapterTransactions=false;
unsigned installBegins=0,installUpdates=0,installCommits=0,installAborts=0;
constexpr LONG installError=ERROR_INVALID_OPERATION;
LONG countedDetourBegin(){++installBegins;if(installFailure==InstallFailure::Begin)return installError;return adapterTransactions?NO_ERROR:DetourTransactionBegin();}
LONG countedDetourUpdate(HANDLE thread){++installUpdates;if(installFailure==InstallFailure::Update)return installError;return adapterTransactions?NO_ERROR:DetourUpdateThread(thread);}
LONG countedDetourAttach(PVOID* pointer,PVOID target){++nativeAttaches;if(installFailure==InstallFailure::Attach)return installError;return adapterTransactions?NO_ERROR:DetourAttach(pointer,target);}
LONG countedDetourAbort(){++installAborts;return adapterTransactions?NO_ERROR:DetourTransactionAbort();}
LONG countedDetourCommit(){++installCommits;if(installFailure==InstallFailure::Commit){countedDetourAbort();return installError;}return adapterTransactions?NO_ERROR:DetourTransactionCommit();}
namespace FrameSurvey {
 std::atomic<bool> metadataHealthy=true;unsigned unavailableReports=0;bool reportOutsideInstaller=true;std::string unavailableReason;
 bool MetadataHealthy() noexcept {return metadataHealthy.load(std::memory_order_acquire);}
 // Health/status seam: production's atomic latch is implemented in FrameSurvey; no coordinator shutdown occurs.
 void MetadataHookFailed(const char* reason) noexcept {metadataHealthy.store(false,std::memory_order_release);++unavailableReports;unavailableReason=reason;bool unlocked=false;std::thread probe([&]{unlocked=gReleaseHookInstallMutex.try_lock();if(unlocked)gReleaseHookInstallMutex.unlock();});probe.join();reportOutsideInstaller=reportOutsideInstaller&&unlocked;}
 void FlushMetadataFailure() noexcept {}
}
void need(bool ok,const char* message) { if(!ok) throw std::runtime_error(message); ++checks; }
struct D3D12Hooks { static void OnBridgeCommandListReset(ID3D12GraphicsCommandList*,ID3D12PipelineState*); };
__RESET__
struct State {
 bool isShuttingDown=false;
 std::unordered_set<ID3D12Resource*> capturedHudlesses;
 static State& Instance() { static State state; return state; }
};
namespace RecordedComputeLease {
 int BeginRelease(void*) { ++leaseBegins; return 1; }
 void EndRelease(int,bool) { ++leaseEnds; }
}
// Actual Birth/NativeBirth are intentionally unconfigured here. These existing
// legacy exclusive-gate/borrow assertions are supplemented by release_birth.
__BIRTH_RELEASE_HELPERS__
std::mutex heapMetadataMutex;
std::unordered_set<void*> heapMetadata;
void* nativeWatchedHeap=nullptr;unsigned nativeWatchedNotifications=0;
unsigned heapPublications=0;
namespace FrameSurvey {
 thread_local bool gInternal=false;
 thread_local unsigned gRecordingDepth=0;
 __INTERNAL_IMPL__
 std::function<void()> releasePause;
 void Released(void* address) noexcept { if(OwnedRelease())return;++releasesObserved;if(releasePause)releasePause();if(address==nativeWatchedHeap)++nativeWatchedNotifications;std::scoped_lock lock(heapMetadataMutex);heapMetadata.erase(address); }
 void HeapCreated(ID3D12Device*,ID3D12DescriptorHeap* heap) noexcept {if(Internal())return;++heapPublications;std::scoped_lock lock(heapMetadataMutex);heapMetadata.insert(heap);}
}
struct HeapSlot { void ClearSlotIfMatches(size_t,ID3D12Resource*) { ++slotsCleaned; } };
struct TrackedResourceSlot { std::weak_ptr<HeapSlot> heap; size_t index=0; uint64_t heapVersion=0; };
std::mutex _trackedResourcesMutex,gRRResourceStateMutex,gRRPsoMutex;
std::unordered_map<ID3D12Resource*,std::vector<TrackedResourceSlot>> _trackedResources;
std::unordered_set<ID3D12Resource*> gRRResourceStates,gRRResourceActivity,gRRResourcePsoProducers;
__TRACKED_RESOURCE_CACHE__
void CleanupRRPsoReferences(void*) { ++psoCleaned; }
// Optional inspector recording-proof catalog is outside the legacy lifetime fixture.
void ForgetRRRecording(void*,const NrdBridgeBirth::Token& = NrdBridgeBirth::Token()) noexcept {}
void CleanupRRResourcePsoProducersLocked(ID3D12Resource* resource) {gRRResourcePsoProducers.erase(resource);}
// Registry scaffolding is an adapter; the full production DeactivateAndClear body follows.
struct HeapInfo {
 static constexpr size_t DESCRIPTOR_LOCK_STRIPE_COUNT=2;
 std::array<std::shared_mutex,DESCRIPTOR_LOCK_STRIPE_COUNT> descriptorLocks;
 ID3D12DescriptorHeap* heap=nullptr;NrdBridgeBirth::Token birth;SIZE_T cpuStart=0,cpuEnd=0,gpuStart=0,gpuEnd=0;std::atomic<bool> active=true;std::atomic<uint64_t> version=19;
 struct Info {ID3D12Resource* buffer=nullptr;uint64_t lastUsedFrame=0;};std::shared_ptr<Info[]> info;
 std::mutex occupiedSlotsMutex;std::unordered_set<UINT> occupiedSlots;
 UINT numDescriptors=1;
 __HEAP_DEACTIVATE__
};
std::shared_mutex _heapRegistryMutex;
std::vector<std::shared_ptr<HeapInfo>> fgHeaps;
std::atomic<unsigned> gHeapGeneration=0;
std::unordered_map<void*,size_t> gHeapSlotsByAddress;
std::map<SIZE_T,size_t> gHeapCpuRanges,gHeapGpuRanges;
std::vector<size_t> gFreeHeapSlots;
__HEAP_REGISTRY_HELPERS__
void seedHeapRegistry(const std::shared_ptr<HeapInfo>& info){if(!info->cpuStart){info->cpuStart=SIZE_T(info->heap);info->cpuEnd=info->cpuStart+32;}std::unique_lock lock(_heapRegistryMutex);__REGISTER_HEAP_BODY__}
struct Probe : IUnknown {
 std::atomic<ULONG> refs=1;
 std::atomic<bool> destroyed=false;
 std::atomic<unsigned> probeAdds=0;
 bool expectClean=true;
 std::function<void()> beforeRelease;
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID,void**) override { return E_NOINTERFACE; }
 ULONG STDMETHODCALLTYPE AddRef() override { ++probeAdds; return ++refs; }
 ULONG STDMETHODCALLTYPE Release() override {
  if(beforeRelease) { auto once=std::move(beforeRelease); once(); }
  const auto left=--refs;
  if(!left) {
   auto* list=reinterpret_cast<ID3D12GraphicsCommandList*>(this);
   if(expectClean) {
    need(!signatures.contains(list) && !rootStates.contains(list) && !bridgeComputeRoots.contains(list),"root signatures/arguments removed before actual destroy");
    need(!descriptorHeaps.contains(list) && !pipelineStates.contains(list),"heap/PSO snapshots removed before actual destroy");
   }
   destroyed=true;
  }
  return left;
 }
};
unsigned resourceOriginalCalls=0,heapOriginalCalls=0;
std::function<void()> heapFinalGap;
ULONG releaseResource(ID3D12Resource* resource) {++resourceOriginalCalls;const auto left=reinterpret_cast<IUnknown*>(resource)->Release();if(!left && heapFinalGap)heapFinalGap();return left;}
ULONG releaseUnknown(IUnknown* object) { return object->Release(); }
ULONG releasePso(ID3D12PipelineState* object) { return reinterpret_cast<IUnknown*>(object)->Release(); }
ULONG releaseHeap(ID3D12DescriptorHeap* object) {++heapOriginalCalls;const auto left=reinterpret_cast<IUnknown*>(object)->Release();if(!left && heapFinalGap)heapFinalGap();return left;}
auto o_Release=&releaseResource;
auto o_CommandListRelease=&releaseUnknown;
auto o_PsoRelease=&releasePso;
auto o_HeapRelease=&releaseHeap;
using PFN_Release=decltype(o_Release);using PFN_HeapRelease=decltype(o_HeapRelease);
bool gResourceReleaseSharesPso=false;
bool gResourceReleaseSharesCommandList=false;
ULONG (*gSharedResourceReleaseObserver)(ID3D12Resource*)=nullptr;
__BIRTH_GATE_AND_GENERIC__
__HEAP_SHARED_CLEANUP__
__RELEASE__
__COMMAND_RELEASE__
__PSO_RELEASE__
__HEAP_RELEASE__
__HEAP_INSTALL__
__HEAP_COVERAGE__
struct ResTrack_Dx12 {
 static void HookResource(ID3D12Device*);
 static HRESULT hkCreateDescriptorHeap(ID3D12Device*,D3D12_DESCRIPTOR_HEAP_DESC*,REFIID,void**);
 static HRESULT hkSurveyCreateDescriptorHeap(ID3D12Device*,D3D12_DESCRIPTOR_HEAP_DESC*,REFIID,void**);
 static bool ObserveBridgeObjectRelease(IUnknown*) noexcept;
};
__BIRTH_COVERAGE__
__RESOURCE_INSTALL__
// The legacy creation seam returns its real or synthetic test heap unchanged.
HRESULT heapCreationResult=S_OK;void* heapCreationObject=nullptr;unsigned legacyHeapCreations=0;
HRESULT ResTrack_Dx12::hkCreateDescriptorHeap(ID3D12Device*,D3D12_DESCRIPTOR_HEAP_DESC*,REFIID,void** out){++legacyHeapCreations;if(out)*out=heapCreationObject;return heapCreationResult;}
__HEAP_PUBLICATION__
void seed(Probe& object) {
 auto* list=reinterpret_cast<ID3D12GraphicsCommandList*>(&object);
 signatures[list]={SignatureEntryType::Compute,reinterpret_cast<ID3D12RootSignature*>(2)};
 rootStates[list].resize(10); rootStates[list][0].Data={1,2,3}; rootStates[list][0].ValidConstants={1,0,1};
 bridgeComputeRoots[list]=reinterpret_cast<ID3D12RootSignature*>(2);
 DescriptorHeap heap; heap.NumDescriptorHeaps=1; heap.Heaps[0]=reinterpret_cast<ID3D12DescriptorHeap*>(3); descriptorHeaps[list]=heap;
 pipelineStates[list]=reinterpret_cast<ID3D12PipelineState*>(4);
}
void clear() { signatures.clear(); rootStates.clear(); bridgeComputeRoots.clear(); descriptorHeaps.clear(); pipelineStates.clear(); }
template<class Release> void releaseRace(Release release,bool snapshot=true) {
 Probe object; if(snapshot) seed(object);
 std::promise<void> started,completed;
 auto start=started.get_future(),done=completed.get_future();
 std::atomic<ULONG> result=ULONG(-1); std::exception_ptr failure;
 const auto before=leaseBegins.load(); std::jthread worker;
 {
  NrdBridgeLifetime::ScopedBorrow borrowed;
  worker=std::jthread([&] {
   started.set_value();
   try { result=release(object); } catch(...) { failure=std::current_exception(); }
   completed.set_value();
  });
  start.wait();
  need(done.wait_for(std::chrono::milliseconds(50))==std::future_status::timeout,"final Release waits for active borrowed CPU use");
  need(object.refs==1 && !object.destroyed && object.probeAdds==0,"shared borrow adds no title AddRef and blocks the original probe");
  bool reverseIndexFree=false;
  std::thread lockProbe([&] { reverseIndexFree=_trackedResourcesMutex.try_lock(); if(reverseIndexFree) _trackedResourcesMutex.unlock(); });
  lockProbe.join();
  need(reverseIndexFree && leaseBegins==before,"exclusive gate precedes lease and tracked-resource locks");
  { NrdBridgeLifetime::ScopedBorrow nested; need(object.refs==1,"same-thread nested borrow is safe"); }
 }
 need(done.wait_for(std::chrono::seconds(2))==std::future_status::ready,"final Release proceeds promptly after borrow ends");
 worker.join(); if(failure) std::rethrow_exception(failure);
 need(result==0 && object.destroyed && object.refs==0 && object.probeAdds==1,"actual production Release destroys once with its existing temporary probe only");
 clear();
}
struct OwnedMember {
 Probe* object;
 ~OwnedMember() {
  need(FrameSurvey::Internal(), "custom deleter guards automatic owned COM-member destruction");
  need(hkRelease(reinterpret_cast<ID3D12Resource*>(object))==0, "owned member Release succeeds inside a shared borrow");
 }
};
struct OwnedHolder { OwnedMember member; explicit OwnedHolder(Probe* object):member{object} {} };
void lifetimeTests() {
 gNrdBridgeWrappers=gNrdBridgeDeviceWrappers=gSurveyWrappers=true;
 gResourceReleaseSharesCommandList=gResourceReleaseSharesPso=false;
 releaseRace([](Probe& object) { return hkRelease(reinterpret_cast<ID3D12Resource*>(&object)); });
 releaseRace([](Probe& object) { return hkCommandListRelease(&object); });
 releaseRace([](Probe& object) { return hkPsoRelease(reinterpret_cast<ID3D12PipelineState*>(&object)); },false);
 gResourceReleaseSharesCommandList=true;
 releaseRace([](Probe& object) { return hkCommandListRelease(&object); });
 gResourceReleaseSharesPso=true;
 releaseRace([](Probe& object) { return hkPsoRelease(reinterpret_cast<ID3D12PipelineState*>(&object)); });
 gResourceReleaseSharesCommandList=gResourceReleaseSharesPso=false;
 Probe outer,inner;
 outer.beforeRelease=[&] { need(hkPsoRelease(reinterpret_cast<ID3D12PipelineState*>(&inner))==0,"nested runtime Release uses the same-thread exclusive gate"); };
 need(hkPsoRelease(reinterpret_cast<ID3D12PipelineState*>(&outer))==0 && outer.destroyed && inner.destroyed,"recursive physical releases complete without a gate deadlock");
 Probe owned;
 { NrdBridgeLifetime::ScopedBorrow borrowed; FrameSurvey::gInternal=true;
  need(hkRelease(reinterpret_cast<ID3D12Resource*>(&owned))==0 && owned.destroyed,"internal bridge-owned releases bypass the title gate during borrow");
  FrameSurvey::gInternal=false;
 }
 Probe deferredOwned;
 auto holder=NrdBridge::MakeOwnedShared<OwnedHolder>(&deferredOwned);
 { NrdBridgeLifetime::ScopedBorrow borrowed; holder.reset(); }
 need(deferredOwned.destroyed && !FrameSurvey::Internal(), "asynchronous last owned reference restores the original internal guard");
 Probe nestedOwned;
 { FrameSurvey::ScopedInternal previous;
  auto nested=NrdBridge::MakeOwnedShared<OwnedHolder>(&nestedOwned); nested.reset();
  need(FrameSurvey::Internal(), "owned deleter preserves an already active internal scope");
 }
 need(nestedOwned.destroyed && !FrameSurvey::Internal(), "nested owned destruction restores outer scope correctly");
 Probe shuttingDown; shuttingDown.expectClean=false; State::Instance().isShuttingDown=true;
 std::promise<void> shutdownStarted,shutdownCompleted;
 auto shutdownStart=shutdownStarted.get_future(),shutdownDone=shutdownCompleted.get_future(); std::jthread shutdownWorker;
 { NrdBridgeLifetime::ScopedBorrow borrowed;
  shutdownWorker=std::jthread([&] { shutdownStarted.set_value(); hkRelease(reinterpret_cast<ID3D12Resource*>(&shuttingDown)); shutdownCompleted.set_value(); });
  shutdownStart.wait();
  need(shutdownDone.wait_for(std::chrono::milliseconds(50))==std::future_status::timeout && !shuttingDown.destroyed,
       "shutdown's physical Release still waits for an in-flight borrowed CPU operation");
 }
 need(shutdownDone.wait_for(std::chrono::seconds(2))==std::future_status::ready,"shutdown Release proceeds after in-flight borrow finishes");
 shutdownWorker.join(); State::Instance().isShuttingDown=false;
 need(shuttingDown.destroyed && shuttingDown.probeAdds==0,"shutdown preserves its original direct physical Release path");
 Probe off; off.expectClean=false; gNrdBridgeWrappers=gNrdBridgeDeviceWrappers=false;
 std::promise<void> completed; auto done=completed.get_future(); std::jthread worker;
 { NrdBridgeLifetime::ScopedBorrow borrowed;
  worker=std::jthread([&] { hkRelease(reinterpret_cast<ID3D12Resource*>(&off)); completed.set_value(); });
  need(done.wait_for(std::chrono::seconds(2))==std::future_status::ready,"startup OFF performs no bridge gate lock");
 }
 worker.join(); need(off.destroyed,"startup OFF preserves physical final Release"); clear();
}

std::shared_ptr<HeapInfo> seedHeap(Probe& object,bool tracked=true){
 auto* heap=reinterpret_cast<ID3D12DescriptorHeap*>(&object);object.expectClean=false;
 {std::scoped_lock lock(heapMetadataMutex);heapMetadata.insert(heap);}
 if(!tracked)return{};
 auto info=std::make_shared<HeapInfo>();info->heap=heap;info->info=std::make_shared<HeapInfo::Info[]>(1);info->info[0].buffer=reinterpret_cast<ID3D12Resource*>(&object);info->occupiedSlots.insert(0);
 _trackedResources[info->info[0].buffer]={{std::weak_ptr<HeapSlot>{},0,info->version.load()}};
 seedHeapRegistry(info);return info;
}
bool heapMetadataLive(void* address){std::scoped_lock lock(heapMetadataMutex);return heapMetadata.contains(address);}
void clearHeaps(){std::unique_lock lock(_heapRegistryMutex);fgHeaps.clear();gHeapSlotsByAddress.clear();gHeapCpuRanges.clear();gHeapGpuRanges.clear();gFreeHeapSlots.clear();lock.unlock();std::scoped_lock metadata(heapMetadataMutex);heapMetadata.clear();_trackedResources.clear();heapFinalGap={};}
void heapReleaseRace(bool tracked,bool shared=false,bool viaResource=false){
 gHeapReleaseSharesResource=shared;
 Probe object;auto info=seedHeap(object,tracked);auto* address=reinterpret_cast<ID3D12DescriptorHeap*>(&object);
 const auto original=heapOriginalCalls,rawResource=resourceOriginalCalls,observed=releasesObserved,generation=gHeapGeneration.load();
 std::promise<void> started,completed;auto start=started.get_future(),done=completed.get_future();std::jthread worker;std::exception_ptr error;ULONG result=99;
 {NrdBridgeLifetime::ScopedBorrow borrowed;worker=std::jthread([&]{started.set_value();try{result=viaResource?hkRelease(reinterpret_cast<ID3D12Resource*>(address)):hkHeapRelease(address);}catch(...){error=std::current_exception();}completed.set_value();});start.wait();
  need(done.wait_for(std::chrono::milliseconds(50))==std::future_status::timeout,"heap final Release waits for borrowed native flag reader");
  need(object.refs==1 && !object.destroyed && object.probeAdds==0 && heapOriginalCalls==original,"heap borrow holds no title AddRef and blocks even the legacy probe");
  bool locksFree=false;std::thread probe([&]{if(_heapRegistryMutex.try_lock()){locksFree=_trackedResourcesMutex.try_lock();if(locksFree)_trackedResourcesMutex.unlock();_heapRegistryMutex.unlock();}});probe.join();need(locksFree,"heap exclusive borrow gate precedes heap registry and reverse-index locks");
  need(heapMetadataLive(address) && (!tracked || info->active.load()),"heap metadata stays valid throughout active borrow");}
 need(done.wait_for(std::chrono::seconds(2))==std::future_status::ready,"heap final Release proceeds after borrow ends");worker.join();if(error)std::rethrow_exception(error);
 need(result==0 && object.destroyed && object.refs==0,"actual heap Release destroys once");if(shared)need(object.probeAdds==1 && heapOriginalCalls==original && resourceOriginalCalls==rawResource+2,"shared heap/resource observer uses one universal probe and one original trampoline without heap recursion");else need(object.probeAdds==(tracked?1u:0u) && heapOriginalCalls==original+(tracked?2u:1u),"known heap keeps only legacy temporary probe; untracked heap adds no ref/probe");
 need(!heapMetadataLive(address) && releasesObserved==observed+1,"heap discovery metadata invalidates exactly once before gate reopens");
 if(tracked){need(!info->active.load() && !info->info && !_trackedResources.contains(reinterpret_cast<ID3D12Resource*>(&object)),"actual heap deactivation clears descriptor info and reverse resource links");need(gHeapGeneration==generation+1,"known heap generation advances once");}
 else need(gHeapGeneration==generation,"untracked bridge cleanup leaves legacy heap generation unchanged");clearHeaps();
}
void heapFinalGapRace(bool tracked,bool shared=false){
 gHeapReleaseSharesResource=shared;
 Probe object;auto info=seedHeap(object,tracked);auto* address=reinterpret_cast<ID3D12DescriptorHeap*>(&object);
 std::promise<void> physicalGap,leaveGap,readerStarted,readerCompleted;auto atGap=physicalGap.get_future(),leave=leaveGap.get_future(),reading=readerStarted.get_future(),read=readerCompleted.get_future();std::exception_ptr error;bool cleanOnRead=false;
 heapFinalGap=[&]{physicalGap.set_value();leave.wait();};std::jthread releaser([&]{try{hkHeapRelease(address);}catch(...){error=std::current_exception();}});
 need(atGap.wait_for(std::chrono::seconds(2))==std::future_status::ready,"heap trampoline reached post-final physical release gap");need(object.destroyed && object.refs==0,"physical heap is already destroyed in the gap");
 need(heapMetadataLive(address)==(!tracked && !shared),"generic shared/tracked metadata is pre-final, dedicated untracked metadata awaits post-original cleanup");
 std::jthread reader([&]{readerStarted.set_value();NrdBridgeLifetime::ScopedBorrow borrow;cleanOnRead=!heapMetadataLive(address)&&(!tracked||(!info->active.load()&&!info->info));readerCompleted.set_value();});reading.wait();
 need(read.wait_for(std::chrono::milliseconds(50))==std::future_status::timeout,"borrow cannot resume between physical heap destroy and metadata cleanup");leaveGap.set_value();releaser.join();if(error)std::rethrow_exception(error);need(read.wait_for(std::chrono::seconds(2))==std::future_status::ready,"borrow resumes after post-final heap cleanup");reader.join();need(cleanOnRead,"resumed reader rejects dead heap via fully cleaned registry");clearHeaps();
}
void heapTests(){
 gNrdBridgeWrappers=gNrdBridgeDeviceWrappers=gSurveyWrappers=true;
 heapReleaseRace(true);heapReleaseRace(false);heapFinalGapRace(true);heapFinalGapRace(false);
 for(bool viaResource:{false,true}){heapReleaseRace(true,true,viaResource);heapReleaseRace(false,true,viaResource);}heapFinalGapRace(true,true);heapFinalGapRace(false,true);gHeapReleaseSharesResource=false;
 Probe held;held.refs=2;auto info=seedHeap(held);auto* address=reinterpret_cast<ID3D12DescriptorHeap*>(&held);const auto observed=releasesObserved,generation=gHeapGeneration.load();
 need(hkHeapRelease(address)==1 && !held.destroyed && info->active && info->info && heapMetadataLive(address),"nonfinal heap release preserves every descriptor/metadata record");need(releasesObserved==observed && gHeapGeneration==generation,"nonfinal heap has no invalidation callback or generation change");need(hkHeapRelease(address)==0 && held.destroyed && !info->active && !heapMetadataLive(address),"later final heap release cleans the retained heap exactly once");clearHeaps();
 Probe owned;owned.expectClean=false;const auto internalObserved=releasesObserved;std::promise<void> completed;auto done=completed.get_future();std::jthread ownedWorker;
 {NrdBridgeLifetime::ScopedBorrow borrow;ownedWorker=std::jthread([&]{FrameSurvey::ScopedInternal internal;hkHeapRelease(reinterpret_cast<ID3D12DescriptorHeap*>(&owned));completed.set_value();});need(done.wait_for(std::chrono::seconds(2))==std::future_status::ready,"owned internal heap can release while another thread borrows title heaps");}
 ownedWorker.join();need(owned.destroyed && owned.probeAdds==0 && releasesObserved==internalObserved,"owned heap preserves internal bypass and adds no title observer/probe");
 Probe sharedOwned;sharedOwned.expectClean=false;gHeapReleaseSharesResource=true;const auto sharedObserved=releasesObserved;std::promise<void> sharedCompleted;auto sharedDone=sharedCompleted.get_future();std::jthread sharedWorker;
 {NrdBridgeLifetime::ScopedBorrow borrow;sharedWorker=std::jthread([&]{FrameSurvey::ScopedInternal internal;hkHeapRelease(reinterpret_cast<ID3D12DescriptorHeap*>(&sharedOwned));sharedCompleted.set_value();});need(sharedDone.wait_for(std::chrono::seconds(2))==std::future_status::ready,"owned shared native heap bypasses the title borrow gate during intrinsic deletion");}sharedWorker.join();need(sharedOwned.destroyed&&sharedOwned.refs==0&&sharedOwned.probeAdds==1&&releasesObserved==sharedObserved,"owned shared heap keeps only the existing generic temporary probe without a title observer or retained ref");gHeapReleaseSharesResource=false;
 for(bool tracked:{false,true}){Probe off;auto offInfo=seedHeap(off,tracked);address=reinterpret_cast<ID3D12DescriptorHeap*>(&off);gNrdBridgeWrappers=gNrdBridgeDeviceWrappers=gSurveyWrappers=false;const auto count=releasesObserved,original=heapOriginalCalls;std::promise<void> complete;auto completedOff=complete.get_future();std::jthread worker;
  {NrdBridgeLifetime::ScopedBorrow borrow;worker=std::jthread([&]{hkHeapRelease(address);complete.set_value();});need(completedOff.wait_for(std::chrono::seconds(2))==std::future_status::ready,"default OFF heap Release acquires no bridge borrow gate");}worker.join();need(off.destroyed && off.probeAdds==(tracked?1u:0u) && heapOriginalCalls==original+(tracked?2u:1u),"default OFF retains exact legacy heap probe/original counts");need(releasesObserved==count && heapMetadataLive(address),"default OFF adds no bridge cleanup callback");if(tracked)need(!offInfo->active && !offInfo->info,"default OFF preserves existing foreground heap deactivation");clearHeaps();}
 for(bool tracked:{false,true}){Probe off;auto offInfo=seedHeap(off,tracked);address=reinterpret_cast<ID3D12DescriptorHeap*>(&off);gHeapReleaseSharesResource=true;const auto count=releasesObserved,raw=resourceOriginalCalls;std::promise<void> complete;auto completedOff=complete.get_future();std::jthread worker;
  {NrdBridgeLifetime::ScopedBorrow borrow;worker=std::jthread([&]{hkHeapRelease(address);complete.set_value();});need(completedOff.wait_for(std::chrono::seconds(2))==std::future_status::ready,"default OFF shared heap/resource Release has no bridge borrow gate");}worker.join();need(off.destroyed && off.probeAdds==1 && resourceOriginalCalls==raw+2,"default OFF shared native entry keeps one generic resource probe and one trampoline owner");need(releasesObserved==count && heapMetadataLive(address),"default OFF shared native entry adds no NRD invalidation callback");if(tracked)need(!offInfo->active && !offInfo->info,"default OFF shared native entry preserves foreground heap deactivation");clearHeaps();}gHeapReleaseSharesResource=false;
 gNrdBridgeWrappers=gNrdBridgeDeviceWrappers=gSurveyWrappers=true;
}

void clearInstallState(){FrameSurvey::metadataHealthy=true;o_Release=nullptr;o_HeapRelease=nullptr;gHeapReleaseSharesResource=false;gResourceReleaseSharesHeap=gHeapOwnsReleaseHook=false;gResourceReleaseSharesCommandList=gResourceReleaseSharesPso=false;gSharedResourceReleaseObserver=nullptr;gResourceReleaseEntry=gHeapReleaseEntry=gCommandListReleaseEntry=gPsoReleaseEntry=nullptr;nativeAttaches=installBegins=installUpdates=installCommits=installAborts=0;}
void checkFailedStages(InstallFailure stage){need(installBegins==1,"installer begins one transaction");need(installUpdates==(stage==InstallFailure::Begin?0u:1u),"failed Begin does not update another transaction");need(nativeAttaches==((stage==InstallFailure::Begin||stage==InstallFailure::Update)?0u:1u),"failed Begin/Update never attempt a detour attach");need(installCommits==(stage==InstallFailure::Commit?1u:0u),"failed preparation never commits a partial transaction");need(installAborts==(stage==InstallFailure::Begin?0u:1u),"only an owned transaction is aborted on failure");}
void publishHeap(ID3D12DescriptorHeap* heap,bool admitted){heapCreationObject=heap;const auto publications=heapPublications,legacy=legacyHeapCreations;void* result=nullptr;D3D12_DESCRIPTOR_HEAP_DESC desc{};need(ResTrack_Dx12::hkSurveyCreateDescriptorHeap(nullptr,&desc,IID_ID3D12DescriptorHeap,&result)==S_OK&&result==heap&&legacyHeapCreations==legacy+1,"actual survey heap wrapper preserves its original creation/result exactly once");need(heapPublications==publications+(admitted?1u:0u)&&heapMetadataLive(heap)==admitted,"actual survey heap wrapper publishes only safely observed native heaps in bridge mode");if(admitted){std::scoped_lock lock(heapMetadataMutex);heapMetadata.erase(heap);}}
void installerTests(){
 Probe object;object.expectClean=false;auto* heap=reinterpret_cast<ID3D12DescriptorHeap*>(&object);const auto entry=(*reinterpret_cast<PVOID**>(heap))[2];adapterTransactions=true;
 for(auto stage:{InstallFailure::Begin,InstallFailure::Update,InstallFailure::Attach,InstallFailure::Commit}){clearInstallState();installFailure=stage;const auto reported=FrameSurvey::unavailableReports;EnsureHeapReleaseHook(heap);checkFailedStages(stage);need(!o_HeapRelease&&!gHeapReleaseEntry&&!gHeapOwnsReleaseHook&&!gHeapReleaseSharesResource,"failed dedicated heap installer leaves no unsafe observer/trampoline alias");need(FrameSurvey::unavailableReports==reported+1&&!FrameSurvey::MetadataHealthy()&&!FrameSurvey::unavailableReason.empty()&&FrameSurvey::reportOutsideInstaller,"heap installer failure reports inactive reason after releasing installer mutex");need(!HeapReleaseObserverCovers(heap),"failed dedicated heap installer cannot cover a borrowed native heap");publishHeap(heap,false);}
 clearInstallState();installFailure=InstallFailure::Begin;gResourceReleaseEntry=entry;o_Release=&releaseResource;gSharedResourceReleaseObserver=&hkRelease;const auto reported=FrameSurvey::unavailableReports;EnsureHeapReleaseHook(heap);need(!nativeAttaches&&!installBegins&&gHeapReleaseSharesResource&&!gHeapOwnsReleaseHook&&o_HeapRelease,"installed generic resource entry admits the same heap without a second detour even when a new Begin would fail");need(HeapReleaseObserverCovers(heap)&&FrameSurvey::unavailableReports==reported&&FrameSurvey::MetadataHealthy(),"generic resource coverage remains admissible without a false failure");publishHeap(heap,true);installFailure=InstallFailure::None;
 for(bool pso:{false,true}){clearInstallState();if(pso)gPsoReleaseEntry=entry;else gCommandListReleaseEntry=entry;const auto before=FrameSurvey::unavailableReports;EnsureHeapReleaseHook(heap);need(!nativeAttaches&&!installBegins&&!o_HeapRelease&&!HeapReleaseObserverCovers(heap),"unsupported existing PSO/list observer never receives a second heap detour or borrowed capture");need(FrameSurvey::unavailableReports==before+1&&FrameSurvey::reportOutsideInstaller,"unsupported shared observer fails closed outside installer mutex");publishHeap(heap,false);}
 clearInstallState();o_HeapRelease=&releaseHeap;gHeapReleaseEntry=reinterpret_cast<PVOID>(1);gHeapOwnsReleaseHook=true;const auto mismatchReported=FrameSurvey::unavailableReports;EnsureHeapReleaseHook(heap);need(!nativeAttaches&&FrameSurvey::unavailableReports==mismatchReported+1&&!HeapReleaseObserverCovers(heap),"different native heap implementation cannot reuse an unrelated trampoline");publishHeap(heap,false);
 clearInstallState();gNrdBridgeWrappers=false;installFailure=InstallFailure::Begin;const auto offReported=FrameSurvey::unavailableReports;EnsureHeapReleaseHook(heap);need(FrameSurvey::unavailableReports==offReported,"startup OFF installer adds no NRD shutdown diagnostic");publishHeap(heap,true);gNrdBridgeWrappers=true;
 clearInstallState();adapterTransactions=false;installFailure=InstallFailure::None;o_Release=&releaseResource;o_HeapRelease=&releaseHeap;gSharedResourceReleaseObserver=&hkRelease;need(object.refs==1&&!object.destroyed&&!object.probeAdds,"installer/admission metadata probes retain no title heap reference");
}

void nativeInstallerFailures(ID3D12Device* device,ID3D12DescriptorHeap* heap){
 for(auto stage:{InstallFailure::Begin,InstallFailure::Update,InstallFailure::Attach,InstallFailure::Commit}){
  clearInstallState();installFailure=stage;const auto heapReported=FrameSurvey::unavailableReports;EnsureHeapReleaseHook(heap);checkFailedStages(stage);need(!o_HeapRelease&&!gHeapReleaseEntry&&!gHeapOwnsReleaseHook&&!HeapReleaseObserverCovers(heap),"actual native heap installer failure retires its alias and rejects borrowed capture");need(FrameSurvey::unavailableReports==heapReported+1&&!FrameSurvey::MetadataHealthy()&&FrameSurvey::reportOutsideInstaller,"actual native heap installer failure publishes inactive diagnostic without lock inversion");publishHeap(heap,false);
  clearInstallState();const auto resourceReported=FrameSurvey::unavailableReports;ResTrack_Dx12::HookResource(device);checkFailedStages(stage);need(!o_Release&&!gResourceReleaseEntry&&!gSharedResourceReleaseObserver&&!HeapReleaseObserverCovers(heap),"actual native generic resource installer failure retires all observer aliases and rejects capture");need(FrameSurvey::unavailableReports==resourceReported+1&&!FrameSurvey::MetadataHealthy()&&FrameSurvey::reportOutsideInstaller,"actual native resource installer failure publishes inactive diagnostic after unlocked temporary release");publishHeap(heap,false);
 }
 clearInstallState();installFailure=InstallFailure::None;
}

void nativeSharedTests(){
 using Microsoft::WRL::ComPtr;const auto hr=[](HRESULT value){need(SUCCEEDED(value),"native D3D12/Detours call succeeded");};
 ComPtr<IDXGIFactory4> factory;hr(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));ComPtr<IDXGIAdapter1> hardware;for(UINT index=0;;++index){ComPtr<IDXGIAdapter1> adapter;if(factory->EnumAdapters1(index,&adapter)==DXGI_ERROR_NOT_FOUND)break;DXGI_ADAPTER_DESC1 desc{};hr(adapter->GetDesc1(&desc));if(!(desc.Flags&DXGI_ADAPTER_FLAG_SOFTWARE)&&desc.VendorId==0x1002&&std::wstring(desc.Description).find(L"9070")!=std::wstring::npos){hardware=adapter;break;}}need(bool(hardware),"native shared routing tests use RX9070");ComPtr<IDXGIAdapter> warp;hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)));
 for(auto* adapter:{static_cast<IDXGIAdapter*>(hardware.Get()),warp.Get()})for(bool heapFirst:{false,true}){
  clearHeaps();gNrdBridgeWrappers=gNrdBridgeDeviceWrappers=gSurveyWrappers=true;gHeapReleaseSharesResource=gResourceReleaseSharesHeap=gHeapOwnsReleaseHook=false;gResourceReleaseSharesCommandList=gResourceReleaseSharesPso=false;gSharedResourceReleaseObserver=nullptr;gResourceReleaseEntry=gHeapReleaseEntry=gCommandListReleaseEntry=gPsoReleaseEntry=nullptr;o_Release=nullptr;o_HeapRelease=nullptr;nativeAttaches=0;
  ComPtr<ID3D12Device> device;hr(D3D12CreateDevice(adapter,D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)));ComPtr<ID3D12Resource> resource;auto desc=CD3DX12_RESOURCE_DESC::Buffer(256);auto props=CD3DX12_HEAP_PROPERTIES(D3D12_HEAP_TYPE_UPLOAD);hr(device->CreateCommittedResource(&props,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&resource)));ComPtr<ID3D12DescriptorHeap> heap;D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.NumDescriptors=4;hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;hr(device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&heap)));
  if(!heapFirst)nativeInstallerFailures(device.Get(),heap.Get());
  need((*reinterpret_cast<PVOID**>(resource.Get()))[2]==(*reinterpret_cast<PVOID**>(heap.Get()))[2],"actual native resource/descriptor heap use one physical Release entry");
  if(heapFirst){EnsureHeapReleaseHook(heap.Get());ResTrack_Dx12::HookResource(device.Get());}else{ResTrack_Dx12::HookResource(device.Get());EnsureHeapReleaseHook(heap.Get());}
  need(nativeAttaches==1 && gHeapReleaseSharesResource && bool(o_HeapRelease) && bool(o_Release),"actual production installers attach one native detour for both creation orders");need(gHeapOwnsReleaseHook==heapFirst && gResourceReleaseSharesHeap==heapFirst,"native detour ownership/trampoline follows actual first installer");
  need(HeapReleaseObserverCovers(heap.Get()),"both native installer orders prove final Release coverage before borrowed heap admission");publishHeap(heap.Get(),true);
  auto info=std::make_shared<HeapInfo>();info->heap=heap.Get();info->info=std::make_shared<HeapInfo::Info[]>(1);info->info[0].buffer=resource.Get();info->occupiedSlots.insert(0);seedHeapRegistry(info);_trackedResources[resource.Get()]={{std::weak_ptr<HeapSlot>{},0,info->version.load()}};nativeWatchedHeap=heap.Get();nativeWatchedNotifications=0;heapMetadata.insert(heap.Get());const auto generation=gHeapGeneration.load();
  heap.Reset();need(!info->active && !info->info && !heapMetadataLive(nativeWatchedHeap) && !_trackedResources.contains(resource.Get()),"real detoured native heap final Release deactivates FG/bridge registries before destruction");need(nativeWatchedNotifications==1 && gHeapGeneration==generation+1,"real shared entry observes heap once without a double-detour chain or recursion");resource.Reset();nativeWatchedHeap=nullptr;
  need(DetourTransactionBegin()==NO_ERROR && DetourUpdateThread(GetCurrentThread())==NO_ERROR,"native teardown transaction starts");
  __RESOURCE_DETACH__
  need(DetourTransactionCommit()==NO_ERROR,"actual resource teardown detaches only its owned native entry");
  __RESOURCE_RESET__
  need(!o_Release && !gSharedResourceReleaseObserver && !gHeapReleaseSharesResource && !gResourceReleaseSharesHeap,"actual resource teardown clears shared observer routing");
  if(heapFirst){need(gHeapOwnsReleaseHook && o_HeapRelease && gHeapReleaseEntry,"heap-first teardown keeps its legacy heap-owned trampoline alive");ComPtr<ID3D12DescriptorHeap> late;hr(device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&late)));auto lateInfo=std::make_shared<HeapInfo>();lateInfo->heap=late.Get();lateInfo->info=std::make_shared<HeapInfo::Info[]>(1);seedHeapRegistry(lateInfo);nativeWatchedHeap=late.Get();nativeWatchedNotifications=0;heapMetadata.insert(late.Get());late.Reset();need(!lateInfo->active && !lateInfo->info && nativeWatchedNotifications==1 && !heapMetadataLive(nativeWatchedHeap),"remaining legacy heap owner still deactivates a real native heap after resource teardown");nativeWatchedHeap=nullptr;need(DetourTransactionBegin()==NO_ERROR && DetourUpdateThread(GetCurrentThread())==NO_ERROR,"final legacy owner detach starts");need(DetourDetach(reinterpret_cast<PVOID*>(&o_HeapRelease),reinterpret_cast<PVOID>(hkHeapRelease))==NO_ERROR,"legacy heap owner detaches exactly once");need(DetourTransactionCommit()==NO_ERROR,"legacy heap owner detach commits");}
  else need(!o_HeapRelease && !gHeapReleaseEntry,"resource-first teardown clears retired heap alias before freed trampoline can be reused");
  o_Release=&releaseResource;o_HeapRelease=&releaseHeap;gHeapReleaseSharesResource=gResourceReleaseSharesHeap=gHeapOwnsReleaseHook=false;gResourceReleaseEntry=gHeapReleaseEntry=nullptr;gSharedResourceReleaseObserver=&hkRelease;clearHeaps();
 }
 std::cout<<"PASS: "<<checks<<" actual native shared Release installer/cleanup checks\n";
}
int main(int argc,char** argv) try {
 if(argc>1 && std::string(argv[1])=="native-shared"){nativeSharedTests();return 0;}
 gSharedResourceReleaseObserver=&hkRelease;
 for(bool shared:{false,true}) {
  Probe object; seed(object); gResourceReleaseSharesCommandList=shared;
  const auto observed=releasesObserved,leaseBefore=leaseEnds;
  need(hkCommandListRelease(&object)==0 && object.destroyed,"final command-list release destroys object");
  need(releasesObserved==observed+1,"release observer fires once on dedicated/shared path");
  need(leaseEnds==leaseBefore+1,"release lease closes exactly once on dedicated/shared path");
  clear();
 }
 Probe held; held.refs=2; seed(held); gResourceReleaseSharesCommandList=true;
 auto* list=reinterpret_cast<ID3D12GraphicsCommandList*>(&held);
 const auto observed=releasesObserved;
 need(hkCommandListRelease(&held)==1 && !held.destroyed,"nonfinal release does not destroy object");
 need(signatures.contains(list) && rootStates.contains(list) && descriptorHeaps.contains(list),"nonfinal release preserves all title bindings");
 need(releasesObserved==observed,"nonfinal release does not report invalidation");
 need(hkCommandListRelease(&held)==0 && held.destroyed,"later final shared release cleans before destroy");
 Probe resource; seed(resource);
 auto* address=reinterpret_cast<ID3D12Resource*>(&resource);
 auto heap=std::make_shared<HeapSlot>(); _trackedResources[address]={{heap,5}};
 gRRResourceStates.insert(address); gRRResourceActivity.insert(address); SeedFixtureRRCache(address);
 gRRResourcePsoProducers.insert(address); State::Instance().capturedHudlesses.insert(address);
 const auto slots=slotsCleaned;
 need(hkRelease(address)==0 && resource.destroyed,"same resource entry accepts an IUnknown-only address");
 need(!_trackedResources.contains(address) && !gRRResourceStates.contains(address) && !gRRResourceActivity.contains(address) &&
      !gRRTrackedResources.contains(address) && !gRRResourcePsoProducers.contains(address),"existing resource metadata still cleaned");
 need(!State::Instance().capturedHudlesses.contains(address) && slotsCleaned==slots+1,"existing hudless/descriptor cleanup retained");
 Probe off; off.expectClean=false; seed(off); gNrdBridgeWrappers=gNrdBridgeDeviceWrappers=false;
 list=reinterpret_cast<ID3D12GraphicsCommandList*>(&off);
 need(hkRelease(reinterpret_cast<ID3D12Resource*>(&off))==0 && off.destroyed,"disabled release path still destroys normally");
 need(signatures.contains(list) && rootStates.contains(list) && descriptorHeaps.contains(list),"NrdBridge=false retains original root-cache behavior");
 clear();
 lifetimeTests();
 const auto baselineChecks=checks;need(baselineChecks==88,"all 88 original resource/list/PSO lifetime checks remain intact");
 {
  gNrdBridgeWrappers=gNrdBridgeDeviceWrappers=gSurveyWrappers=true;
  Probe retainedTitle; retainedTitle.expectClean=true; seed(retainedTitle);
  const auto observedBefore=releasesObserved;
  std::promise<void> entered,done; auto enteredFuture=entered.get_future(),doneFuture=done.get_future();
  std::atomic<ULONG> remaining{99}; std::jthread worker;
  {
   NrdBridgeLifetime::ScopedBorrow borrowedTitle;
   worker=std::jthread([&]{ FrameSurvey::ScopedRecording recording;
    need(FrameSurvey::Internal() && !FrameSurvey::OwnedRelease(),"metadata-only owned recording preserves title final Release gate");
    entered.set_value(); remaining.store(hkRelease(reinterpret_cast<ID3D12Resource*>(&retainedTitle))); done.set_value(); });
   enteredFuture.wait();
   need(doneFuture.wait_for(std::chrono::milliseconds(30))==std::future_status::timeout,"retained title final reference waits for another thread's bridge borrow");
   need(!retainedTitle.destroyed && remaining.load()==99,"retained title remains physically alive until borrow ends");
  }
  doneFuture.wait(); worker.join();
  need(remaining.load()==0 && retainedTitle.destroyed && releasesObserved==observedBefore+1,"protected title tag reset invalidates metadata before its physical final release");
 }
 heapTests();installerTests();
 {
  gNrdBridgeWrappers=gNrdBridgeDeviceWrappers=gSurveyWrappers=true;
  Probe pausedTitle;seed(pausedTitle);const auto observedBefore=releasesObserved;
  std::promise<void> entered,resume;auto arrived=entered.get_future(),resumed=resume.get_future();
  FrameSurvey::releasePause=[&]{entered.set_value();resumed.wait();};
  std::jthread releasing([&]{hkRelease(reinterpret_cast<ID3D12Resource*>(&pausedTitle));});
  arrived.wait();
  const bool reverseFree=_trackedResourcesMutex.try_lock();
  if(reverseFree)_trackedResourcesMutex.unlock();
  const bool physicallyAlive=!pausedTitle.destroyed && pausedTitle.refs==1;
  resume.set_value();releasing.join();FrameSurvey::releasePause={};
  need(reverseFree,"long survey/coordinator release callback does not hold the descriptor reverse-index mutex");
  need(physicallyAlive,"shortened reverse-index section keeps the caller reference alive throughout final invalidation");
  need(pausedTitle.destroyed && pausedTitle.refs==0 && releasesObserved==observedBefore+1,"paused final cleanup still destroys and invalidates exactly once");
 }
 std::cout << "PASS: " << checks << " production shared/dedicated Release checks\n";
 return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
'''
    def instrument_installer(signature):
        body = function(res, signature)
        for original, adapter in (
            ('DetourTransactionBegin', 'countedDetourBegin'),
            ('DetourUpdateThread', 'countedDetourUpdate'),
            ('DetourAttach', 'countedDetourAttach'),
            ('DetourTransactionCommit', 'countedDetourCommit'),
            ('DetourTransactionAbort', 'countedDetourAbort'),
        ):
            body = body.replace(original + '(', adapter + '(')
        return body

    replacements = {
        'ROOT':ROOT.as_posix(), 'STATE':state,
        'INTERNAL_IMPL':'\n'.join(function(survey,s) for s in ('ScopedInternal::ScopedInternal()', 'ScopedInternal::~ScopedInternal()', 'ScopedRecording::ScopedRecording()', 'ScopedRecording::~ScopedRecording()', 'bool OwnedRelease() noexcept', 'bool Internal() noexcept')),
        'RESET':function(d3d,'void D3D12Hooks::OnBridgeCommandListReset('),
        'RELEASE':res_function(res,'hkRelease'),
        'COMMAND_RELEASE':function(res,'static ULONG STDMETHODCALLTYPE hkCommandListRelease(IUnknown* This)\n{'),
        'PSO_RELEASE':function(res,'ULONG hkPsoRelease(ID3D12PipelineState* This)\n{'),
        'HEAP_RELEASE':function(res,'static ULONG STDMETHODCALLTYPE hkHeapRelease(ID3D12DescriptorHeap* This)\n{'),
        'HEAP_DEACTIVATE':function(res_header,'bool DeactivateAndClear()'),
        'HEAP_SHARED_CLEANUP':function(res,'static void DeactivateSharedHeap(void* address)'),
        'HEAP_REGISTRY_HELPERS':'\n'.join(function(res,signature) for signature in (
            'static bool HeapRangeAvailableLocked(', 'static std::shared_ptr<HeapInfo> FindIndexedHeapRangeLocked(',
            'static bool RegisterTrackedHeapLocked(', 'static std::shared_ptr<HeapInfo> FindTrackedHeapByAddress(',
            'static bool DeactivateTrackedHeap(')) if 'static bool RegisterTrackedHeapLocked(' in res else '',
        'REGISTER_HEAP_BODY':'need(RegisterTrackedHeapLocked(info),"fixture registers indexed live heap");' if 'static bool RegisterTrackedHeapLocked(' in res else 'fgHeaps.push_back(info);',
        'HEAP_INSTALL':instrument_installer('static void EnsureHeapReleaseHook(ID3D12DescriptorHeap* heap)'),
        'HEAP_COVERAGE':function(res,'static bool HeapReleaseObserverCovers(ID3D12DescriptorHeap* heap)'),
        'RESOURCE_INSTALL':instrument_installer('void ResTrack_Dx12::HookResource(ID3D12Device* InDevice)'),
        'HEAP_PUBLICATION':function(res,'HRESULT ResTrack_Dx12::hkSurveyCreateDescriptorHeap('),
        'RESOURCE_DETACH':teardown[detach_begin:detach_end],
        'RESOURCE_RESET':teardown[reset_begin:reset_end],
    }
    cache = tracked_resource_cache(res)
    if cache:
        replacements['TRACKED_RESOURCE_CACHE'] = cache + r'''
// CPU creator seam supplies the metadata normally prepared from a strong resource.
void SeedFixtureRRCache(ID3D12Resource* resource)
{
 std::scoped_lock lock(gRRTrackedResourceMutex);
 EraseRRTrackedResourceLocked(resource);
 auto& row=gRRTrackedResources[resource];row.desc.Width=1505;row.desc.Height=847;
 row.version=gRRNextResourceVersion.fetch_add(1,std::memory_order_relaxed);
 gRRResourceSizeIndex[{row.desc.Width,row.desc.Height}].insert(resource);
}
'''
    else:
        replacements['TRACKED_RESOURCE_CACHE'] = r'''
std::mutex gRRTrackedResourceMutex;
std::unordered_set<ID3D12Resource*> gRRTrackedResources;
void SeedFixtureRRCache(ID3D12Resource* resource){gRRTrackedResources.insert(resource);}
'''
    if 'static bool UseNrdNativeRetirement()' in res:
        release_header = (ROOT/'OptiScaler/misc/NrdBridgeRelease_Dx12.h').read_text()
        replacements.update({
            'BIRTH_RELEASE_HELPERS':release_header[release_header.index('namespace NrdBridgeRelease'):],
            'BIRTH_GATE_AND_GENERIC':birth_gate_and_generic(res),
            'BIRTH_COVERAGE':instrument_installer('bool ResTrack_Dx12::ObserveBridgeObjectRelease(')
                + '\n' + function(res,'bool NrdBridgeNativeBirth::ObserveReleaseCoverage('),
        })
    else:
        # Immutable pre-birth baseline sources have no such hooks/helper calls.
        replacements.update({name:'' for name in ('BIRTH_RELEASE_HELPERS','BIRTH_GATE_AND_GENERIC')})
        replacements['BIRTH_COVERAGE'] = r'''
// CPU coverage seam for the immutable pre-birth baseline. Actual Ready remains
// unconfigured; if queried, coverage uses installed native entries only.
bool NrdBridgeNativeBirth::ObserveReleaseCoverage(IUnknown* object) noexcept
{
 if(!object || !NrdBridgeNativeBirth::Ready() || FrameSurvey::OwnedRelease()) return false;
 const PVOID entry=(*reinterpret_cast<PVOID**>(object))[2];
 return (entry==gResourceReleaseEntry && o_Release) || (entry==gHeapReleaseEntry && o_HeapRelease) ||
        (entry==gPsoReleaseEntry && o_PsoRelease) || (entry==gCommandListReleaseEntry && o_CommandListRelease);
}
'''
    for name, value in replacements.items():
        cpp = cpp.replace('__'+name+'__', value)
    if 'static bool NeedsNativeReleaseGate()' in res:
        control = r'''
void stickyOwnedTests()
{
 const bool bridge=gNrdBridgeWrappers,device=gNrdBridgeDeviceWrappers;
 const bool previousSticky=gRRInspectorLifetimeProtection.exchange(true);
 gNrdBridgeWrappers=gNrdBridgeDeviceWrappers=false;
 need(!NrdBridgeNativeBirth::Ready()&&!NrdBridgeLifetime::ConcurrentReleasesEnabled(),"sticky owned control executes actual legacy unconfigured birth/lifetime mode");
 Probe owned;
 {FrameSurvey::ScopedInternal internal;
  need(!NeedsNativeReleaseGate(),"sticky inspector still excludes bridge-owned releases from the legacy physical gate");
  NrdBridgeLifetime::ScopedBorrow borrowed;
  auto holder=NrdBridge::MakeOwnedShared<OwnedHolder>(&owned);holder.reset();}
 need(owned.destroyed&&!FrameSurvey::Internal(),"sticky inspector owned deleter safely completes inside same-thread legacy borrow");
 {FrameSurvey::ScopedRecording recording;
  need(!FrameSurvey::OwnedRelease()&&NeedsNativeReleaseGate(),"sticky inspector preserves physical title protection during metadata-only owned recording");}
 releaseRace([](Probe& object){return hkRelease(reinterpret_cast<ID3D12Resource*>(&object));},false);
 gRRInspectorLifetimeProtection.store(previousSticky);
 gNrdBridgeWrappers=bridge;gNrdBridgeDeviceWrappers=device;
}
'''
        cpp = cpp.replace('int main(int argc,char** argv)',control+'\nint main(int argc,char** argv)',1)
        cpp = cpp.replace(' heapTests();installerTests();',' heapTests();installerTests();stickyOwnedTests();',1)
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    source, exe = out/'nrd_release.cpp', out/'nrd_release.exe'
    source.write_text(cpp)
    if os.environ.get('FSRD_RELEASE_GENERATE_ONLY') == '1':
        return source
    compile_cpp(source,exe,('d3d12.lib','dxgi.lib','dxguid.lib',str(ROOT/'OptiScaler/library/detours/detours.lib')),(ROOT/'OptiScaler',))
    command = [str(exe)] + (['native-shared'] if '--native-shared' in sys.argv else [])
    result = subprocess.run(command,check=False,capture_output=True,text=True,timeout=30)
    (out/'native.log').write_text(result.stdout + result.stderr)
    result.check_returncode()
    print(result.stdout,end='')
    checks = int(re.search(r'PASS: (\d+)',result.stdout).group(1))
    (out/'result.json').write_text(json.dumps({'native_checks':checks,
        'preserved_original_checks':88 if '--native-shared' not in sys.argv else None,'scope':
        ('actual RX9070 and WARP native resource/heap Release entry, actual Detours and production resource/heap installers/teardown for both creation orders; injected four transaction failures, actual survey publication wrapper with legacy creation seam; actual release/heap deactivation bodies, FG/FrameSurvey metadata adapters' if '--native-shared' in sys.argv else '88 original checks retained; production dedicated/shared resource/PSO/list/heap Release bodies, actual heap deactivation/root-cache cleanup/admission wrapper; registry and transaction adapters plus threaded fake IUnknown prove gate-before-lock order, no retained title AddRef, final metadata-gap exclusion, owned bypass, OFF parity and fail-closed installer admission')})+'\n')


if __name__ == '__main__':
    entries() if '--entries' in sys.argv else run()
