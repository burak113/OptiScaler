"""Barrier-controlled populated-heap retirement using the native contention seams.

The complete production HeapInfo, indexed heap helpers, View hooks, physical
release/Birth protocol and compute lease registry execute. WARP owns every COM
object. The 100k occupied descriptor records are explicit CPU metadata setup;
no fake address reaches COM. No shader Dispatch/Execute or timing threshold.
Existing contention and release suites remain separate and unchanged.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_fsrd_frame_survey_contention as contention
from test_fsrd_nrd_release import tracked_resource_cache, tracked_resource_slots
from test_fsrd_nrd_root_restore import function

ROOT = contention.ROOT
REGISTRY_CONTROL = '0dde34cf'

CASES = r'''
struct OriginalForwardTimer {}; // No per-call timing or performance claim here.
__ADAPTER__

// These hooks still forward to actual WARP; only notifications are counted.
std::atomic<unsigned> nativeCbvCalls{0},nativeSrvCalls{0};
void progressCBV(ID3D12Device* d,const D3D12_CONSTANT_BUFFER_VIEW_DESC* p,D3D12_CPU_DESCRIPTOR_HANDLE h){++nativeCbvCalls;d->CreateConstantBufferView(p,h);}
void progressSRV(ID3D12Device* d,ID3D12Resource* r,D3D12_SHADER_RESOURCE_VIEW_DESC* p,D3D12_CPU_DESCRIPTOR_HANDLE h){++nativeSrvCalls;d->CreateShaderResourceView(r,p,h);}

template<class Predicate> bool eventually(Predicate predicate){
 const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(5);
 while(!predicate()){if(std::chrono::steady_clock::now()>=deadline)return false;std::this_thread::yield();}return true;
}
std::shared_ptr<HeapInfo> trackedHeap(Host& host,ID3D12DescriptorHeap* heap,UINT count){
 const auto description=heap->GetDesc();const auto cpu=heap->GetCPUDescriptorHandleForHeapStart().ptr;
 const auto gpu=(description.Flags&D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE)?heap->GetGPUDescriptorHandleForHeapStart().ptr:0;
 const auto stride=host.device->GetDescriptorHandleIncrementSize(description.Type);
 auto result=std::make_shared<HeapInfo>(heap,cpu,cpu+uint64_t(count)*stride,gpu,gpu?gpu+uint64_t(count)*stride:0,count,stride,description.Type);
 result->birth=NrdBridgeNativeBirth::Prepare(heap);
 need(result->birth&&result->birth->CacheAdmissible(),"real heap has a ready native birth before metadata publication");
 {std::unique_lock lock(_heapRegistryMutex);need(RegisterTrackedHeapLocked(result),"actual heap registry publishes the exact native owner");}
 return result;
}
void populatedHeapProgress(Host& host){
 constexpr UINT count=100000;
 D3D12_DESCRIPTOR_HEAP_DESC desc{};desc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;desc.NumDescriptors=count;
 ComPtr<ID3D12DescriptorHeap> nativeHeap;hr(host.device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&nativeHeap)));
 FrameSurvey::HeapCreated(host.device.Get(),nativeHeap.Get());auto retiring=trackedHeap(host,nativeHeap.Get(),count);
 auto unrelated=trackedHeap(host,host.heap.Get(),65536);
 ResourceInfo item{};item.buffer=host.texture.Get();item.birth=NrdBridgeBirth::Capture(host.texture.Get());item.format=host.srvDesc.Format;item.type=SRV;
 for(UINT index=0;index<count;++index)retiring->SetByCpuHandle(retiring->cpuStart+uint64_t(index)*retiring->increment,item);
 need(retiring->occupiedSlots.size()==count&&_trackedResources.at(item.buffer)->size()==count,"all100k actual HeapInfo descriptor slots and reverse edges are populated");
 need(item.birth&&item.birth->CacheAdmissible(),"populated metadata uses a live retained real WARP texture");
 const auto version=retiring->version.load(),generation=gHeapGeneration.load();
 const auto oldAddress=retiring->heap;
 // Select real objects before the barrier. A deliberately held Birth shard is
 // unrelated to the registry convoy being tested; do not let a random hash
 // collision, native allocation, or canonical cold bootstrap confound progress.
 const auto blockedBirthShard=NrdBridgeBirth::Registry::ShardIndex(oldAddress);
 const auto disjoint=[&](void* object){NrdBridgeBirth::AliasSnapshot aliases;const auto ticket=NrdBridgeBirth::Capture(object);
  if(!ticket||!NrdBridgeBirth::CaptureProvenAliasesForFinalZero(ticket,aliases)||!aliases.complete)return false;
  for(size_t i=0;i<aliases.count;++i)if(NrdBridgeBirth::Registry::ShardIndex(aliases.tokens[i]->Address())==blockedBirthShard)return false;return true;};
 ComPtr<ID3D12Resource> otherResource;ComPtr<ID3D12DescriptorHeap> otherHeap;
 std::vector<ComPtr<ID3D12Resource>> spareResources;std::vector<ComPtr<ID3D12DescriptorHeap>> spareHeaps;
 for(unsigned attempt=0;attempt<64&&!otherResource;++attempt){
  D3D12_RESOURCE_DESC rd{};rd.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;rd.Width=256;rd.Height=1;rd.DepthOrArraySize=rd.MipLevels=1;rd.SampleDesc.Count=1;rd.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
  D3D12_HEAP_PROPERTIES hp{};hp.Type=D3D12_HEAP_TYPE_UPLOAD;ComPtr<ID3D12Resource> resource;
  hr(host.device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&rd,D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&resource)));FrameSurvey::ResourceCreated(resource.Get(),D3D12_RESOURCE_STATE_GENERIC_READ);
  if(disjoint(resource.Get()))otherResource=std::move(resource);else spareResources.push_back(std::move(resource));
 }
 for(unsigned attempt=0;attempt<64&&!otherHeap;++attempt){D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;hd.NumDescriptors=1;ComPtr<ID3D12DescriptorHeap> heap;
  hr(host.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&heap)));FrameSurvey::HeapCreated(host.device.Get(),heap.Get());
  if(disjoint(heap.Get()))otherHeap=std::move(heap);else spareHeaps.push_back(std::move(heap));
 }
 need(otherResource&&otherHeap,"real unrelated release controls have complete aliases in disjoint Birth shards");
 auto otherOwner=trackedHeap(host,otherHeap.Get(),1);
 std::promise<void> releaseStarted;auto started=releaseStarted.get_future();
 std::atomic<bool> finished=false;std::atomic<ULONG> releaseResult=ULONG(-1);
 std::exception_ptr releasingFailure;std::array<std::exception_ptr,5> workerFailures{};
 // Hold a reachable populated stripe, not the registry. The retirement
 // winner must publish inactive/index removal before waiting for this writer.
 std::unique_lock slot(retiring->descriptorLocks[0]);
 std::thread releasing([&]{try{releaseStarted.set_value();releaseResult=hkHeapRelease(nativeHeap.Detach());}catch(...){releasingFailure=std::current_exception();}finished=true;});
 started.wait();
 const bool inactive=eventually([&]{return !retiring->active.load(std::memory_order_acquire);});
 bool beforeDrain=false,indexGone=false,cacheGone=false,releaseStillWaiting=false,storagePinned=false;
 std::atomic<bool> cbvDone=false,srvDone=false,resourceDone=false,heapDone=false,lookupDone=false;
 std::vector<std::thread> workers;
 if(inactive){
  // No callback touches the retiring heap. Every worker uses a fresh thread/TLS
  // cache, so the indexed registry cannot be hidden by a previous cache hit.
  const auto cbvBefore=nativeCbvCalls.load(),srvBefore=nativeSrvCalls.load();
  workers.emplace_back([&]{try{hkSurveyCreateConstantBufferView(host.device.Get(),&host.cbv,host.handle(0));cbvDone=true;}catch(...){workerFailures[0]=std::current_exception();}});
  workers.emplace_back([&]{try{hkSurveyCreateShaderResourceView(host.device.Get(),host.texture.Get(),&host.srvDesc,host.handle(8));srvDone=true;}catch(...){workerFailures[1]=std::current_exception();}});
  workers.emplace_back([&]{try{
   if(hkRelease(otherResource.Detach())!=0)throw std::runtime_error("unrelated native resource final count");resourceDone=true;
  }catch(...){workerFailures[2]=std::current_exception();}});
  workers.emplace_back([&]{try{
   if(hkHeapRelease(otherHeap.Detach())!=0||otherOwner->active||otherOwner->info)throw std::runtime_error("unrelated native heap did not fully retire");heapDone=true;
  }catch(...){workerFailures[3]=std::current_exception();}});
  workers.emplace_back([&]{try{
   auto current=GetHeapByCpuHandleSRV(host.handle(9).ptr);if(current!=unrelated)throw std::runtime_error("cold unrelated lookup owner mismatch");
   indexGone=!FindTrackedHeapByAddress(oldAddress);cacheGone=!GetHeapByCpuHandleCBV(retiring->cpuStart);
   if(gHeapGeneration.load()<=generation)throw std::runtime_error("retirement did not publish a new cache generation");lookupDone=true;
  }catch(...){workerFailures[4]=std::current_exception();}});
  beforeDrain=eventually([&]{return cbvDone&&srvDone&&resourceDone&&heapDone&&lookupDone;});
  releaseStillWaiting=!finished.load();
  storagePinned=bool(retiring->info)&&retiring->occupiedSlots.size()==count;
  if(beforeDrain&&(nativeCbvCalls!=cbvBefore+1||nativeSrvCalls!=srvBefore+1))workerFailures[0]=std::make_exception_ptr(std::runtime_error("native view forwarding count changed"));
 }
 // Always unblock and join before raising a failing assertion. The old source
 // therefore produces an ordinary negative artifact rather than a stuck process.
 slot.unlock();for(auto& worker:workers)worker.join();releasing.join();
 for(auto& resource:spareResources)if(hkRelease(resource.Detach())!=0)throw std::runtime_error("spare native resource final count");
 for(auto& heap:spareHeaps)if(hkHeapRelease(heap.Detach())!=0)throw std::runtime_error("spare native heap final count");
 if(releasingFailure)std::rethrow_exception(releasingFailure);for(const auto& failure:workerFailures)if(failure)std::rethrow_exception(failure);
 need(inactive,"retirement publishes inactive before descriptor-writer drain");
 need(beforeDrain&&releaseStillWaiting,"actual unrelated CBV/SRV/resource+heap Release and cold lookup finish while retiring100k heap is blocked on its reachable descriptor stripe");
 need(storagePinned,"in-flight descriptor stripe pins every old slot until admitted writer drain completes");
 need(indexGone&&cacheGone,"old heap address/range and cold TLS cache are invalid before participant drain ends");
 need(releaseResult==0&&finished&&!retiring->info&&retiring->occupiedSlots.empty(),"blocked heap finally retires exactly once and destroys all descriptor storage");
 need(retiring->version==version&&!_trackedResources.contains(item.buffer),"all100k exact old-version reverse participants are removed");
 // Stale owners may not remove a new registry publication at an identical
 // address/range. This is metadata-only setup; the opaque token is never COM-used.
 auto replacement=std::make_shared<HeapInfo>(oldAddress,retiring->cpuStart,retiring->cpuEnd,0,0,count,retiring->increment,retiring->type);
 {std::unique_lock lock(_heapRegistryMutex);need(RegisterTrackedHeapLocked(replacement),"detached old address and range can be republished as a distinct metadata owner");}
 need(!DeactivateTrackedHeap(retiring)&&FindTrackedHeapByAddress(oldAddress)==replacement&&replacement->active,"delayed stale heap cleanup preserves the current replacement owner");
 need(DeactivateTrackedHeap(replacement)&&!replacement->info,"replacement metadata drains through its own one-winner path");
 need(DeactivateTrackedHeap(unrelated)&&!unrelated->info,"unrelated registered heap metadata cleans up after progress proof");
}
int main(int argc,char**argv)try{
 need(argc==2,"one fresh output directory argument");SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);
 need(NrdBridgeNativeBirth::ConfigureRetirement(PrepareNativeRetirement,DetachNativeRetirement,NotifyNativeRetirement),"actual native retirement dispatcher configured");
 need(NrdBridgeLifetime::EnableConcurrentReleases(),"actual concurrent physical Release gate enabled");(void)RecordedComputeLease::GetRegistry();
 g_dllPath=std::filesystem::path(argv[1])/"fixture.dll";Host host;
 need(NrdBridgeNativeBirth::Ready()&&UseNrdNativeRetirement(),"progress proof uses NativeReady true and production release helper");
 Config::Instance()->FGHudfixDisableSRV.enabled=false;Config::Instance()->FGHudfixDisableUAV.enabled=false;
 o_CreateConstantBufferView=&progressCBV;o_CreateShaderResourceView=&progressSRV;
 populatedHeapProgress(host);
 need(FrameSurvey::MetadataHealthy()&&NrdBridgeBirth::Healthy(),"all retirement/progress/ABA paths preserve metadata health");
 hr(host.list->Close());
 auto* list=host.list.Detach();need(NrdBridgeRelease::Title(list,[](auto* p){return p->Release();})==0,"host list native birth retires before teardown");
 auto* root=host.root.Detach();need(NrdBridgeRelease::Title(root,[](auto* p){return p->Release();})==0,"host root native birth retires before teardown");
 need(hkHeapRelease(host.heap.Detach())==0&&hkRelease(host.buffer.Detach())==0&&hkRelease(host.texture.Detach())==0,"all remaining host resources/heaps retire through production helpers");
 ComPtr<ID3D12InfoQueue> messages;hr(host.device.As(&messages));
 unsigned errors=0,warnings=0;
 for(UINT64 i=0;i<messages->GetNumStoredMessages();++i){SIZE_T bytes=0;hr(messages->GetMessage(i,nullptr,&bytes));std::vector<std::byte> storage(bytes);auto* message=reinterpret_cast<D3D12_MESSAGE*>(storage.data());hr(messages->GetMessage(i,message,&bytes));if(message->Severity==D3D12_MESSAGE_SEVERITY_ERROR||message->Severity==D3D12_MESSAGE_SEVERITY_CORRUPTION)++errors;if(message->Severity==D3D12_MESSAGE_SEVERITY_WARNING)++warnings;}
 need(errors==0&&warnings==0,"real WARP native view/retirement progress leaves no debug errors or warnings");
 PROCESS_MEMORY_COUNTERS memory{};GetProcessMemoryInfo(GetCurrentProcess(),&memory,sizeof(memory));need(memory.PeakWorkingSetSize<2500ull*1024*1024,"native fixture remains within2.5GB process budget");
 J result{{"checks",checks},{"populated_heap_slots",100000},{"native_birth_ready",NrdBridgeNativeBirth::Ready()},{"concurrent_releases",NrdBridgeLifetime::ConcurrentReleasesEnabled()},
 {"native_cbv_calls",nativeCbvCalls.load()},{"native_srv_calls",nativeSrvCalls.load()},{"gpu_dispatches",0},{"ExecuteCommandLists_calls",0},{"synthetic_objects_passed_to_com",false},{"debug_errors",errors},{"debug_warnings",warnings},
 {"peak_working_set_bytes",memory.PeakWorkingSetSize},{"scope","actual production HeapInfo/index/View/Release bodies and NativeBirth/Lifetime/lease protocol; real WARP objects and native forwarding;100k CPU descriptor metadata records; inactive HUD/inspector seams; no physical Detours or frame/FPS claim"}};
 std::ofstream(std::filesystem::path(argv[1])/"native-result.json")<<result.dump(2)<<'\n';std::cout<<result.dump()<<'\n';return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
'''


def source_proof(header, hook_source):
    old = subprocess.check_output(['git', 'show', f'{REGISTRY_CONTROL}:OptiScaler/resource_tracking/ResTrack_dx12.h'], cwd=ROOT).decode('utf-8-sig')
    old = function(old, 'bool DeactivateAndClear()')
    drain = function(header, 'void DrainInactive()')
    # Preserve the complete stripe/participant/array-move body, byte for byte
    # after newline normalization. Only entry election and its enclosing scope move.
    old_body = old[old.index('std::array<std::unique_lock'):old.index('// Bulk descriptor storage')]
    new_body = drain[drain.index('std::array<std::unique_lock'):drain.index('// Bulk storage destruction')]
    assert old_body == new_body, 'pending writer/participant drain changed'
    helper = function(hook_source, 'static bool DeactivateTrackedHeap(')
    point = helper.index('retired->DrainInactive();')
    assert helper[:point].count('{')-helper[:point].count('}') == 1, 'drain still enclosed in registry lock scope'
    assert helper.index('current != heap') < helper.index('heap->MarkInactive()') < helper.index('retired = std::move(current)')
    assert helper.index('gHeapGeneration.fetch_add') < point
    assert 'cpu->second == slot' in helper and 'gpu->second == slot' in helper
    assert 'active.exchange(false, std::memory_order_acq_rel)' in function(header, 'bool MarkInactive()')
    return 6


def prepare(out, legacy_registry=False):
    hook_source = (ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.cpp').read_text()
    header = (ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.h').read_text()
    hud = (ROOT/'OptiScaler/hudfix/Hudfix_Dx12.h').read_text()
    proof_count = source_proof(header, hook_source)
    compiled_registry = function(hook_source, 'static bool DeactivateTrackedHeap(')
    if legacy_registry:
        old = subprocess.check_output(['git','show',f'{REGISTRY_CONTROL}:OptiScaler/resource_tracking/ResTrack_dx12.cpp'],cwd=ROOT).decode('utf-8-sig')
        old_registry = function(old, 'static bool DeactivateTrackedHeap(')
        assert hook_source.count(compiled_registry) == 1
        hook_source = hook_source.replace(compiled_registry, old_registry)
        compiled_registry = old_registry
    cpp = contention.native.CPP.split('#if __INDEXED__\n// Opaque', 1)[0]
    cpp = cpp.replace('#include <thread>', '#include <thread>\n#include <future>\n#include <functional>\n#define LOG_TRACK(...) ((void)0)')
    cpp = cpp.replace('#include "__SURVEY__"', '#include "hooks/D3D12_Hooks.h"\n#include "__SURVEY__"')
    cpp = cpp.replace('BeginCreationTracking(true)', 'BeginCreationTracking(false)').replace('hd.NumDescriptors=16', 'hd.NumDescriptors=65536')
    cpp = cpp.replace('struct State {', 'struct State {bool isShuttingDown=false;std::unordered_set<ID3D12Resource*> capturedHudlesses;')
    slot_types, _ = tracked_resource_slots(header, 'HeapInfo')
    actual_heap = function(header, 'struct HeapInfo :')+';'
    actual_heap = actual_heap.replace('{\n', '{\n    HeapInfo() = default;\n', 1)
    declarations = '\n'.join(function(hud, signature)+';' for signature in ('enum ResourceType', 'enum CaptureInfo'))
    declarations += '\n'+function(hud, 'typedef struct ResourceInfo')+' resource_info;\nusing ResourceKind=ResourceType;\nstruct HeapInfo;\n'+slot_types
    declarations += '\nNrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Tracking> _trackedResourcesMutex;\nstd::unordered_map<ID3D12Resource*,TrackedResourceSlots> _trackedResources;\n'+actual_heap
    declarations += r'''
std::shared_mutex _heapRegistryMutex;
std::vector<std::shared_ptr<HeapInfo>> fgHeaps;
std::unordered_map<void*,size_t> gHeapSlotsByAddress;
std::map<SIZE_T,size_t> gHeapCpuRanges,gHeapGpuRanges;
std::vector<size_t> gFreeHeapSlots;
struct HeapCacheTLS {unsigned genSeen=0;std::shared_ptr<HeapInfo> heap;uint64_t heapVersion=0;};
thread_local HeapCacheTLS cacheCBV,cacheSRV,cacheUAV;
std::atomic<unsigned> gHeapGeneration{1};
'''
    declarations += '\n'.join(function(hook_source, signature) for signature in (
        'static bool HeapRangeAvailableLocked(', 'static std::shared_ptr<HeapInfo> FindIndexedHeapRangeLocked(',
        'static bool RegisterTrackedHeapLocked(', 'static std::shared_ptr<HeapInfo> FindTrackedHeapByAddress(',
        'static bool DeactivateTrackedHeap(', 'static std::shared_ptr<HeapInfo> FindHeapByCpuHandle('))
    declarations += '\n'+'\n'.join(function(hook_source, signature).replace('ResTrack_Dx12::', '') for signature in (
        'std::shared_ptr<HeapInfo> ResTrack_Dx12::GetHeapByCpuHandleCBV(',
        'std::shared_ptr<HeapInfo> ResTrack_Dx12::GetHeapByCpuHandleSRV(',
        'std::shared_ptr<HeapInfo> ResTrack_Dx12::GetHeapByCpuHandleUAV('))
    first = cpp.index('enum ResourceKind {'); last = cpp.index('bool CheckResource(', first)
    cpp = cpp[:first]+declarations+'\n'+cpp[last:]
    hooks = '\n'.join(function(hook_source, 'void ResTrack_Dx12::'+name+'(').replace('ResTrack_Dx12::', '') for name in (
        'hkCreateShaderResourceView', 'hkCreateUnorderedAccessView', 'hkSurveyCreateConstantBufferView', 'hkSurveyCreateShaderResourceView', 'hkSurveyCreateUnorderedAccessView'))
    adapter = contention.ADAPTER
    old_tracker = 'namespace D3D12Hooks {inline void OnBridgeCommandListReset(ID3D12GraphicsCommandList*,ID3D12PipelineState*){}inline void OnBridgeObjectReleased(const NrdBridgeBirth::Token&)noexcept{}}'
    assert adapter.count(old_tracker) == 1
    adapter = adapter.replace(old_tracker, r'''
// This fixture records no title dispatch/root state. Coordinator and D3D tracker
// callbacks are explicit inactive integration seams, not Birth/lease substitutes.
void D3D12Hooks::OnBridgeCommandListReset(ID3D12GraphicsCommandList*,ID3D12PipelineState*){}
void D3D12Hooks::OnBridgeObjectReleased(const NrdBridgeBirth::Token&)noexcept{}
void D3D12Hooks::OnBridgeOpaqueCommand(ID3D12GraphicsCommandList*,bool)noexcept{}
namespace NrdBridge {
bool StartupEnabled()noexcept{return false;}
DispatchDisposition OriginalDispatchDisposition(ID3D12GraphicsCommandList*,DispatchKind)noexcept{return DispatchDisposition::Forward;}
void InvalidateRecordingProof(ID3D12GraphicsCommandList*,const char*)noexcept{}
}
''')
    adapter = adapter.replace('__TRACKED_SLOT_TYPES__\nNrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Tracking> _trackedResourcesMutex;\nstd::unordered_map<ID3D12Resource*,TrackedResourceSlots> _trackedResources;\n', '')
    first = adapter.index('NrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Tracking> heapPoolMutex;')
    last = adapter.index('__NATIVE_RETIREMENT__', first)
    adapter = adapter[:first]+adapter[last:]
    retirement_start = hook_source.index('struct NativeRetirementPayload\n{')
    retirement_end = hook_source.index('void* PrepareNativeRetirement(', retirement_start)
    retirement = hook_source[retirement_start:retirement_end]+'\n'+'\n'.join(function(hook_source, signature) for signature in (
        'void* PrepareNativeRetirement(', 'bool DetachNativeRetirement(', 'void NotifyNativeRetirement('))
    gates = 'static std::atomic<bool> gRRInspectorLifetimeProtection{false};\n'+function(hook_source, 'static bool NeedsNativeReleaseGate(')+'\n'+function(hook_source, 'static bool UseNrdNativeRetirement(')
    rr_helpers = tracked_resource_cache(hook_source)+'\nvoid ForgetRRRecording(void*,const NrdBridgeBirth::Token& = NrdBridgeBirth::Token()) noexcept {}\n'
    replacements = {'__RELEASE_HEADER__':(ROOT/'OptiScaler/misc/NrdBridgeRelease_Dx12.h').as_posix(),
                    '__BASELINE_FAILURE_ADAPTER__':'', '__USE_NATIVE__':gates, '__RR_RELEASE_HELPERS__':rr_helpers,
                    '__NATIVE_RETIREMENT__':retirement,
                    '__RELEASE__':function(hook_source, 'ULONG ResTrack_Dx12::hkRelease(').replace('ResTrack_Dx12::', ''),
                    '__HEAP_RELEASE__':function(hook_source, 'static ULONG STDMETHODCALLTYPE hkHeapRelease(')}
    for marker, value in replacements.items():
        assert adapter.count(marker)==1, marker
        adapter=adapter.replace(marker,value)
    cpp += CASES.replace('__ADAPTER__', adapter)
    cpp = cpp.replace('__TRACE__', (ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp').as_posix()).replace('__SURVEY__', (ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').as_posix()).replace('__INDEXED__', '1').replace('__HOOKS__', hooks)
    assert '__' not in cpp.replace('__uuidof','').replace('__LINE__','').replace('__FILE__','').replace('__func__','').replace('__declspec',''), 'unreplaced fixture placeholder'
    source=out/'heap_progress.cpp';source.write_text(cpp)
    (out/'source-proof.json').write_text(json.dumps({'checks':proof_count,'legacy_registry_control':legacy_registry,
        'compiled_registry_helper_sha256':hashlib.sha256(compiled_registry.encode()).hexdigest(),
        'control_ref':REGISTRY_CONTROL if legacy_registry else None},indent=2)+'\n')
    return source


def run(execute, legacy_registry=False):
    out=Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    if out.exists():
        raise AssertionError('fresh output directory required; preserve negatives')
    out.mkdir(parents=True)
    source=prepare(out, legacy_registry)
    if not execute:
        print('PASS source generation:', source)
        return
    stubs=out/'stubs'
    for folder in ('proxies','inputs'):
        (stubs/folder).mkdir(parents=True,exist_ok=True)
    (stubs/'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n#define LOG_INFO(...) ((void)0)\n#define LOG_ERROR(...) ((void)0)\n#define LOG_TRACK(...) ((void)0)\n')
    (stubs/'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\nnamespace Util {inline std::filesystem::path DllPath(){return g_dllPath;}}\n')
    (stubs/'inputs/NVNGX_DLSS.h').write_text('#pragma once\n#include <nvsdk_ngx.h>\n')
    (stubs/'proxies/D3D12_Proxy.h').write_text('#pragma once\n#include <d3d12.h>\nnamespace D3d12Proxy {inline auto D3D12CreateVersionedRootSignatureDeserializer_(){return &D3D12CreateVersionedRootSignatureDeserializer;}inline auto D3D12SerializeVersionedRootSignature_(){return &D3D12SerializeVersionedRootSignature;}}\n')
    exe=out/'heap_progress.exe'
    contention.compile_cpp(source,exe,('d3d12.lib','dxgi.lib','dxguid.lib','d3dcompiler.lib','bcrypt.lib','user32.lib','psapi.lib',str(ROOT/'OptiScaler/library/detours/detours.lib')),
        (stubs,ROOT/'OptiScaler',ROOT/'OptiScaler/misc',ROOT/'OptiScaler/resource_tracking',ROOT/'OptiScaler/include',ROOT/'external/streamline',ROOT/'external/nlohmann',ROOT/'external/nvngx_dlss_sdk',ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
    result=subprocess.run([str(exe),str(out)],capture_output=True,text=True,timeout=90,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    (out/'native.stdout.txt').write_text(result.stdout);(out/'native.stderr.txt').write_text(result.stderr)
    print(result.stdout,end='');print(result.stderr,end='',file=sys.stderr)
    report={'exit_code':result.returncode,'legacy_registry_control':legacy_registry,'source_proof':json.loads((out/'source-proof.json').read_text()),'source_commit':subprocess.check_output(['git','log','-1','--format=%H'],cwd=ROOT,text=True).strip(),
        'generated_cpp_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
        'production_source_sha256':{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in (
            'OptiScaler/resource_tracking/ResTrack_dx12.cpp','OptiScaler/resource_tracking/ResTrack_dx12.h','OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp')}}
    if (out/'native-result.json').exists():report['native']=json.loads((out/'native-result.json').read_text())
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');result.check_returncode()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',action='store_true')
    parser.add_argument('--legacy-registry-control',action='store_true',help='scratch-only old global-lock helper; original progress assertion must fail')
    args=parser.parse_args();run(args.run,args.legacy_registry_control)
