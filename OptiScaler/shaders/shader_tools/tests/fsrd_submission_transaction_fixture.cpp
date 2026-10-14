#define NOMINMAX
#define FSRD_RECORDED_COMPUTE_LEASE_TEST
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <vector>
#include <json.hpp>
#include "__ROOT__/OptiScaler/misc/RecordedComputeLease_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgeNativeBirth_Dx12.h"
#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/RRTraceFence.h"
using Microsoft::WRL::ComPtr;
using J=nlohmann::json;
std::atomic<unsigned> checks=0;
std::atomic<const char*> stage="initialization";
void need(bool ok,const char* text) { ++checks;if(!ok){std::fprintf(stderr,"[TRANSACTION_ASSERT] stage=%s checks=%u %s\n",stage.load(),checks.load(),text);std::fflush(stderr);throw std::runtime_error(text);} }
void hr(HRESULT result) { need(SUCCEEDED(result),"HRESULT succeeds"); }
std::atomic<bool> denyAllocations=false;
std::atomic<unsigned> deniedAllocations=0;
void* operator new(size_t bytes){if(denyAllocations.load()){++deniedAllocations;throw std::bad_alloc();}if(auto* p=std::malloc(bytes?bytes:1))return p;throw std::bad_alloc();}
void operator delete(void* p) noexcept {std::free(p);}
void operator delete(void* p,size_t) noexcept {std::free(p);}
void* operator new[](size_t bytes){return ::operator new(bytes);}
void operator delete[](void* p) noexcept {::operator delete(p);}
std::array<const char*,1024> events{};
std::atomic<size_t> eventCount=0;
void event(const char* name){const auto at=eventCount.fetch_add(1);if(at<events.size())events[at]=name;}
bool registryFree(){auto& r=RecordedComputeLease::GetRegistry();if(!r.mutex.try_lock())return false;r.mutex.unlock();return true;}
// Called only after fixture publishers/native work have drained; uses the actual
// teardown seam so bounded Poll intrusive membership cannot survive a test reset.
void resetRegistry(){RecordedComputeLease::ResetRegistryForTesting();eventCount=0;}
namespace FrameSurvey {
thread_local unsigned transactionDepth=0;
struct ObservedMutex {
 std::mutex native;
 std::atomic<unsigned> attempts=0,acquisitions=0;
 HANDLE attempted=CreateEventW(nullptr,TRUE,FALSE,nullptr);
 ~ObservedMutex(){if(attempted)CloseHandle(attempted);}
 void lock(){++attempts;SetEvent(attempted);native.lock();++acquisitions;++transactionDepth;}
 void unlock(){--transactionDepth;native.unlock();}
};
ObservedMutex transaction;
std::atomic<bool> recorder=false;
std::atomic<unsigned> submitted=0,metadataFailures=0;
ObservedMutex& SubmissionMutex(){return transaction;}
bool Enabled() noexcept {return recorder.load();}
bool Internal() noexcept {return false;}
void Submit(ID3D12CommandQueue*,UINT,ID3D12CommandList* const*) noexcept {if(Enabled()){if(!transactionDepth)std::abort();++submitted;}}
void MetadataHookFailed(const char*) noexcept {++metadataFailures;}
void FlushMetadataFailure() noexcept {}
}
namespace NrdBridgeNativeBirth {bool ObserveReleaseCoverage(IUnknown*) noexcept {return false;}}
enum FG_ResourceType {FixtureResource};
struct FixtureFG {bool active=false,ready=false;ID3D12CommandQueue* queue=nullptr;bool IsActive(){return active;}bool IsPaused(){return false;}size_t GetIndex(){return 0;}void SetResourceReady(FG_ResourceType){ready=true;}void SetCommandQueue(FG_ResourceType,ID3D12CommandQueue* value){queue=value;}};
struct State {FixtureFG* currentFG=nullptr;static State& Instance(){static State state;return state;}};
std::mutex _resourceCommandListMutex;
std::set<void*> _notFoundCmdLists;
std::array<std::unordered_map<FG_ResourceType,void*>,4> _resCmdList;
bool gNrdBridgeWrappers=true;
#define LOG_TRACK(...) ((void)0)
#define LOG_DEBUG(...) ((void)0)
#define LOG_WARN(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
struct ResTrack_Dx12 {
 static std::shared_ptr<RecordedComputeLease::Submission> BeforeComputeSubmission(ID3D12CommandQueue*,UINT,ID3D12CommandList* const*,RecordedComputeLease::SubmissionDecision* =nullptr) noexcept;
 static void hkExecuteCommandLists(ID3D12CommandQueue*,UINT,ID3D12CommandList* const*);
 static void hkSurveyExecuteCommandLists(ID3D12CommandQueue*,UINT,ID3D12CommandList* const*);
};
void OriginalExecute(ID3D12CommandQueue* queue,UINT count,ID3D12CommandList* const* lists){queue->ExecuteCommandLists(count,lists);}
auto o_ExecuteCommandLists=OriginalExecute;
__PRODUCTION__
__FAKE_COM__

std::atomic<bool> spyRegistryChecks=true;
struct SpyList:FakeList {
 unsigned queries=0;
 bool aliasLookupOnly=false;
 NrdBridgeNativeBirth::NativeStamp stamp{};
 explicit SpyList(FakeDevice* device):FakeList(device){}
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid,void** out) override {++queries;if(spyRegistryChecks)need(registryFree(),"strong selection native/canonical QI runs outside registry lock");return FakeList::QueryInterface(iid,out);}
 ULONG STDMETHODCALLTYPE Release() override {if(spyRegistryChecks)need(registryFree(),"temporary canonical Release runs outside registry lock");return FakeList::Release();}
 HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID guid,UINT* bytes,void* out) override {
  if(guid!=NrdBridgeNativeBirth::InstanceGuid||!stamp.instanceStamp)return DXGI_ERROR_NOT_FOUND;
  if(!bytes||*bytes<sizeof(stamp))return E_INVALIDARG;*bytes=sizeof(stamp);std::memcpy(out,&stamp,sizeof(stamp));return S_OK;
 }
 HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID guid,UINT bytes,const void* data) override {
  if(guid!=NrdBridgeNativeBirth::InstanceGuid||bytes!=sizeof(stamp))return E_INVALIDARG;std::memcpy(&stamp,data,bytes);return S_OK;
 }
};
struct AliasOnlyProxy:ProxyList {
 explicit AliasOnlyProxy(ID3D12GraphicsCommandList* list):ProxyList(list){}
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid,void** out) override {if(iid==nativeIid){*out=nullptr;return E_NOINTERFACE;}return ProxyList::QueryInterface(iid,out);}
};
static thread_local int retirementPayload;
void* retirementFactory() noexcept {return &retirementPayload;}
bool retirementDetach(void*,const NrdBridgeBirth::Token&) noexcept {return true;}
void retirementNotify(void*) noexcept {}
void configureMetadataBirth(){need(NrdBridgeNativeBirth::ConfigureRetirement(retirementFactory,retirementDetach,retirementNotify),"metadata-only native GUID dispatcher is explicitly registered");}
void markBeforeTrack(ID3D12GraphicsCommandList* list){if(NrdBridgeNativeBirth::Ready()){const auto birth=NrdBridgeNativeBirth::Prepare(list);need(birth&&birth->CacheAdmissible(),"owned command list has an exact native GUID birth");need(NrdBridgeBirth::MarkRecordingMayExist(birth),"monotonic marker is set before fixture Track, matching production Retain");}}
void track(ID3D12GraphicsCommandList* list,const std::shared_ptr<void>& lease,RecordedComputeLease::SubmissionCallbacks callbacks={}){markBeforeTrack(list);ComPtr<IUnknown> canonical;hr(list->QueryInterface(IID_PPV_ARGS(&canonical)));need(RecordedComputeLease::Track(canonical.Get(),{list,canonical.Get()},lease,{},std::move(callbacks)),"actual ledger records retained work before Close submission");}
void submit(ID3D12CommandQueue* queue,ID3D12CommandList* list){ResTrack_Dx12::hkSurveyExecuteCommandLists(queue,1,&list);}
struct Domain {
 std::mutex mutex;
 RecordedComputeLease::FencePointPtr completion;
 uint64_t latest=0;
 bool pending=false;
 std::atomic<unsigned> before=0,published=0,failed=0;
 RecordedComputeLease::SubmissionCallbacks callbacks(){RecordedComputeLease::SubmissionCallbacks result;
  result.beforeSubmit=[this](const auto& info){++before;need(FrameSurvey::transactionDepth==1,"retained Before runs inside full submission transaction");RecordedComputeLease::FencePointPtr predecessor;{std::lock_guard lock(mutex);if(pending&&latest!=info.submissionId){RecordedComputeLease::DenySubmission(E_FAIL);return false;}predecessor=completion;latest=info.submissionId;pending=true;}return SUCCEEDED(RecordedComputeLease::WaitForFence(info.queue,predecessor));};
  result.fencePublished=[this](const auto& info,const auto& point){need(FrameSurvey::transactionDepth==1,"exact publication remains inside full submission transaction");need(point&&point->IsPublished(),"published dependency is a real successfully signalled fence");RecordedComputeLease::FencePointPtr retired;{std::lock_guard lock(mutex);if(latest==info.submissionId){retired=std::move(completion);completion=point;pending=false;}}++published;};
  result.failed=[this](const auto&,auto){++failed;};return result;
 }
};
struct SignalPause {
 HANDLE entered=CreateEventW(nullptr,TRUE,FALSE,nullptr);
 Domain* domain=nullptr;
 std::atomic<bool> armed=false;
 ~SignalPause(){if(entered)CloseHandle(entered);}
 void waitForContendingSubmit(){if(!armed.exchange(false))return;need(FrameSurvey::transactionDepth==1,"first Signal owns the full transaction");ResetEvent(FrameSurvey::transaction.attempted);SetEvent(entered);need(WaitForSingleObject(FrameSurvey::transaction.attempted,5000)==WAIT_OBJECT_0,"second submitting thread attempts transaction while first Signal is parked");need(domain->before==1,"second thread cannot run Before while prerequisite publication is pending");}
};
struct PausedFakeQueue:FakeQueue {SignalPause* pause=nullptr;explicit PausedFakeQueue(FakeDevice* device):FakeQueue(device){}HRESULT STDMETHODCALLTYPE Signal(ID3D12Fence* fence,UINT64 value) override {if(pause)pause->waitForContendingSubmit();return FakeQueue::Signal(fence,value);}};
struct PausedNativeQueue:ObservedQueue {SignalPause* pause=nullptr;explicit PausedNativeQueue(ID3D12CommandQueue* queue):ObservedQueue(queue){}HRESULT STDMETHODCALLTYPE Signal(ID3D12Fence* fence,UINT64 value) override {if(pause)pause->waitForContendingSubmit();return ObservedQueue::Signal(fence,value);}};
J cpuTests(){
 stage="strong selector";resetRegistry();ComPtr<FakeDevice> device;device.Attach(new FakeDevice);
 ComPtr<SpyList> a,b;a.Attach(new SpyList(device.Get()));b.Attach(new SpyList(device.Get()));
 ComPtr<PausedFakeQueue> qa,qb;qa.Attach(new PausedFakeQueue(device.Get()));qb.Attach(new PausedFakeQueue(device.Get()));
 ID3D12CommandList* raw=a.Get();need(!HasRetainedSubmissionParticipant(0,nullptr),"empty batch has no retained participant");need(HasRetainedSubmissionParticipant(1,nullptr),"missing batch storage conservatively locks");ID3D12CommandList* nil=nullptr;need(HasRetainedSubmissionParticipant(1,&nil),"missing list identity conservatively locks");
 need(!HasRetainedSubmissionParticipant(1,&raw),"healthy exact untracked canonical list skips global transaction");
 auto lease=std::make_shared<unsigned>(1);track(a.Get(),lease);need(HasRetainedSubmissionParticipant(1,&raw),"any recorded lease preserves transaction even without callbacks");
 ComPtr<ProxyList> proxy;proxy.Attach(new ProxyList(a.Get()));ID3D12CommandList* alias=proxy.Get();need(HasRetainedSubmissionParticipant(1,&alias),"native unwrapping resolves retained canonical participant for a new alias");
 ComPtr<AliasOnlyProxy> aliasOnly;aliasOnly.Attach(new AliasOnlyProxy(a.Get()));need(RecordedComputeLease::Track(a.Get(),{aliasOnly.Get()},lease),"recorded alias fallback exists independently of incoming canonical identity");alias=aliasOnly.Get();need(HasRetainedSubmissionParticipant(1,&alias),"exact strong alias fallback preserves recorded work");
 auto releasing=RecordedComputeLease::BeginRelease(a.Get());need(HasRetainedSubmissionParticipant(1,&raw),"recording in Release gap conservatively preserves transaction");RecordedComputeLease::EndRelease(releasing,false);
 b->failIdentity=true;raw=b.Get();need(HasRetainedSubmissionParticipant(1,&raw),"failed canonical QI conservatively locks");b->failIdentity=false;raw=a.Get();RecordedComputeLease::FailCompletion();need(HasRetainedSubmissionParticipant(1,&raw),"completion uncertainty cannot drop retained transaction");
 stage="untracked bypass";spyRegistryChecks=false;resetRegistry();const auto noParticipantLocks=FrameSurvey::transaction.acquisitions.load();HANDLE done=CreateEventW(nullptr,TRUE,FALSE,nullptr);FrameSurvey::transaction.lock();std::jthread untracked([&]{submit(qb.Get(),b.Get());SetEvent(done);});const auto untrackedResult=WaitForSingleObject(done,1000);FrameSurvey::transaction.unlock();untracked.join();CloseHandle(done);need(untrackedResult==WAIT_OBJECT_0&&FrameSurvey::transaction.acquisitions==noParticipantLocks+1,"untracked original Execute completes while another thread holds global transaction");
 stage="recorder serialization";FrameSurvey::recorder=true;done=CreateEventW(nullptr,TRUE,FALSE,nullptr);FrameSurvey::transaction.lock();ResetEvent(FrameSurvey::transaction.attempted);std::jthread recorded([&]{submit(qb.Get(),b.Get());SetEvent(done);});const auto attempted=WaitForSingleObject(FrameSurvey::transaction.attempted,1000);const auto recorderDone=WaitForSingleObject(done,0);FrameSurvey::transaction.unlock();recorded.join();CloseHandle(done);need(attempted==WAIT_OBJECT_0&&recorderDone==WAIT_TIMEOUT&&FrameSurvey::submitted==1,"recorder Enabled retains transaction for untracked work");FrameSurvey::recorder=false;
 unsigned threaded=0;
 for(bool sameQueue:{true,false}){stage=sameQueue?"same queue transaction":"cross queue transaction";resetRegistry();Domain domain;SignalPause pause;pause.domain=&domain;pause.armed=true;qa->pause=&pause;track(a.Get(),lease,domain.callbacks());track(b.Get(),lease,domain.callbacks());const auto firstExecutions=qa->executions,secondExecutions=(sameQueue?qa:qb)->executions;std::exception_ptr error;std::jthread first([&]{try{submit(qa.Get(),a.Get());}catch(...){error=std::current_exception();}});need(WaitForSingleObject(pause.entered,5000)==WAIT_OBJECT_0,"first original executes before intentionally parked Signal");submit((sameQueue?qa:qb).Get(),b.Get());first.join();qa->pause=nullptr;if(error)std::rethrow_exception(error);need(domain.before==2&&domain.published==2&&!domain.failed&&RecordedComputeLease::Available(),"same-history two-thread submissions publish both fences without transient pending denial");need(qa->executions==firstExecutions+(sameQueue?2:1)&&(!sameQueue?qb->executions==secondExecutions+1:true),"every accepted original Execute occurs exactly once");++threaded;}
 stage="failed Signal";resetRegistry();Domain failed;qa->failSignal=true;track(a.Get(),lease,failed.callbacks());track(b.Get(),lease,failed.callbacks());submit(qa.Get(),a.Get());const auto deniedBefore=qb->executions;submit(qb.Get(),b.Get());need(failed.before==2&&failed.failed==2&&!failed.published&&qb->executions==deniedBefore,"failed first Signal denies later shared original and publishes no old dependency");qa->failSignal=false;
 stage="snapshot OOM";resetRegistry();Domain oom;track(a.Get(),lease,oom.callbacks());track(b.Get(),lease,oom.callbacks());denyAllocations=true;submit(qa.Get(),a.Get());denyAllocations=false;const auto oomBefore=qb->executions;submit(qb.Get(),b.Get());need(deniedAllocations>0&&oom.failed==2&&!oom.published&&qb->executions==oomBefore,"snapshot OOM does not publish a point and later dependent original is denied");
 stage="native GUID marker";spyRegistryChecks=true;resetRegistry();configureMetadataBirth();raw=a.Get();const auto native=NrdBridgeNativeBirth::Prepare(a.Get());need(native&&native->CacheAdmissible()&&!native->RecordingMayExist(),"fresh owned native GUID identity is unmarked");const auto queries=a->queries;denyAllocations=true;const bool hot=HasRetainedSubmissionParticipant(1,&raw);denyAllocations=false;need(!hot&&a->queries==queries,"exact admissible unmarked native list requires no COM or allocation for selection");
 markBeforeTrack(a.Get());need(native->RecordingMayExist()&&HasRetainedSubmissionParticipant(1,&raw)==false,"marked but healthy exact empty registry is checked rather than assumed a participant");const auto markedQueries=a->queries;need(markedQueries>queries,"marked list resolves strong native/canonical identity");track(a.Get(),lease);RecordedComputeLease::Detach(RecordedComputeLease::Capture(a.Get()));need(native->RecordingMayExist()&&!HasRetainedSubmissionParticipant(1,&raw),"Reset-like detach never clears monotonic physical marker");
 {NrdBridgeBirth::ScopedRelease release(native);const auto before=a->queries;need(HasRetainedSubmissionParticipant(1,&raw)&&a->queries>before,"native physical Release gap cannot take cached fastnegative");}
 need(!FrameSurvey::metadataFailures,"metadata-only GUID protocol remains healthy");resetRegistry();return {{"native_checks",checks.load()},{"threaded_same_history_cases",threaded},{"native_release_coverage_proved",false},{"native_birth_scope","actual GUID protocol on fake COM, metadata-only retirement adapter"},{"strong_identity_outside_registry",true},{"old_recorded_work_without_recorder",true},{"snapshot_and_signal_failure_denials",true}};
}

struct NativeHost {
 ComPtr<ID3D12Device> device;ComPtr<ID3D12InfoQueue> info;
 std::array<ComPtr<ID3D12CommandQueue>,2> native;
 std::array<ComPtr<PausedNativeQueue>,2> queues;
 std::array<ComPtr<ID3D12CommandAllocator>,2> allocators;
 std::array<ComPtr<ID3D12GraphicsCommandList>,2> lists;
 std::vector<ComPtr<ID3D12Resource>> resources;
 std::vector<ComPtr<ID3D12Fence>> gates;
 ComPtr<ID3D12Fence> drain;
 NativeHost(){ComPtr<ID3D12Debug> debug;hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)));debug->EnableDebugLayer();ComPtr<IDXGIFactory4> factory;ComPtr<IDXGIAdapter> warp;hr(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)));hr(D3D12CreateDevice(warp.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)));hr(device.As(&info));hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&drain)));for(unsigned i=0;i<2;++i){D3D12_COMMAND_QUEUE_DESC desc{};hr(device->CreateCommandQueue(&desc,IID_PPV_ARGS(&native[i])));queues[i].Attach(new PausedNativeQueue(native[i].Get()));hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocators[i])));hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocators[i].Get(),nullptr,IID_PPV_ARGS(&lists[i])));}}
 ~NativeHost(){for(auto& gate:gates)gate->Signal(1);for(unsigned i=0;i<2;++i){if(FAILED(native[i]->Signal(drain.Get(),i+1)))continue;const auto end=GetTickCount64()+15000;while(drain->GetCompletedValue()<i+1&&GetTickCount64()<end)Sleep(1);}resetRegistry();}
 ComPtr<ID3D12Resource> buffer(D3D12_HEAP_TYPE type){D3D12_HEAP_PROPERTIES heap{};heap.Type=type;D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;desc.Width=256;desc.Height=desc.DepthOrArraySize=desc.MipLevels=desc.SampleDesc.Count=1;desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;ComPtr<ID3D12Resource> value;hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,type==D3D12_HEAP_TYPE_UPLOAD?D3D12_RESOURCE_STATE_GENERIC_READ:type==D3D12_HEAP_TYPE_READBACK?D3D12_RESOURCE_STATE_COPY_DEST:D3D12_RESOURCE_STATE_COMMON,nullptr,IID_PPV_ARGS(&value)));resources.push_back(value);return value;}
 void wait(const RecordedComputeLease::FencePointPtr& point){need(point&&point->IsPublished(),"native final point is actually published");const auto end=GetTickCount64()+15000;while(point->fence->GetCompletedValue()<point->value&&GetTickCount64()<end)Sleep(1);need(point->fence->GetCompletedValue()==point->value,"native exact submission completes");}
};
J gpuTests(){stage="native two queue transaction";resetRegistry();NativeHost host;Domain domain;SignalPause pause;pause.domain=&domain;auto upload=host.buffer(D3D12_HEAP_TYPE_UPLOAD),owned=host.buffer(D3D12_HEAP_TYPE_DEFAULT),read=host.buffer(D3D12_HEAP_TYPE_READBACK);void* bytes=nullptr;hr(upload->Map(0,nullptr,&bytes));*static_cast<UINT*>(bytes)=0x13e5a17u;upload->Unmap(0,nullptr);host.lists[0]->CopyBufferRegion(owned.Get(),0,upload.Get(),0,4);D3D12_RESOURCE_BARRIER barrier{};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;barrier.Transition={owned.Get(),D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_COMMON};host.lists[0]->ResourceBarrier(1,&barrier);hr(host.lists[0]->Close());host.lists[1]->CopyBufferRegion(read.Get(),0,owned.Get(),0,4);hr(host.lists[1]->Close());
 auto lease=std::make_shared<std::array<ComPtr<ID3D12Resource>,3>>();(*lease)[0]=upload;(*lease)[1]=owned;(*lease)[2]=read;track(host.lists[0].Get(),lease,domain.callbacks());track(host.lists[1].Get(),lease,domain.callbacks());ComPtr<ID3D12Fence> gate;hr(host.device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&gate)));host.gates.push_back(gate);hr(host.native[0]->Wait(gate.Get(),1));pause.armed=true;host.queues[0]->pause=&pause;std::exception_ptr error;std::jthread first([&]{try{submit(host.queues[0].Get(),host.lists[0].Get());}catch(...){error=std::current_exception();}});need(WaitForSingleObject(pause.entered,5000)==WAIT_OBJECT_0,"real native original executes before parked real Signal forwarding");const auto begin=eventCount.load();submit(host.queues[1].Get(),host.lists[1].Get());first.join();host.queues[0]->pause=nullptr;if(error)std::rethrow_exception(error);need(domain.before==2&&domain.published==2&&!domain.failed,"real two-thread shared domain preserves both publications");need(host.queues[0]->executions==1&&host.queues[1]->executions==1&&host.queues[1]->waits==1,"one native original per thread and actual cross-queue dependency Wait");
 bool sawWait=false,sawExecute=false,sawSignal=false;for(size_t i=begin;i<eventCount&&i<events.size();++i){const std::string_view name=events[i];if(name=="RealWait")sawWait=true;if(name=="RealExecute"){need(sawWait,"dependent native Wait precedes original Execute");sawExecute=true;}if(name=="RealSignal"&&sawExecute)sawSignal=true;}need(sawWait&&sawExecute&&sawSignal,"dependent native Wait/Execute/Signal all forward in order");need(domain.completion->fence->GetCompletedValue()==0,"same submitting thread returns with producer GPU gate closed");hr(gate->Signal(1));host.wait(domain.completion);hr(read->Map(0,nullptr,&bytes));need(*static_cast<UINT*>(bytes)==0x13e5a17u,"dependent native GPU copy sees exact newly submitted producer bytes");read->Unmap(0,nullptr);
 unsigned errors=0,warnings=0;for(UINT64 i=0;i<host.info->GetNumStoredMessages();++i){SIZE_T size=0;host.info->GetMessage(i,nullptr,&size);std::vector<unsigned char> data(size);auto* message=reinterpret_cast<D3D12_MESSAGE*>(data.data());host.info->GetMessage(i,message,&size);if(message->Severity<=D3D12_MESSAGE_SEVERITY_ERROR)++errors;else if(message->Severity==D3D12_MESSAGE_SEVERITY_WARNING)++warnings;if(message->Severity<=D3D12_MESSAGE_SEVERITY_WARNING)std::fprintf(stderr,"D3D12 %u: %s\n",message->ID,message->pDescription);}need(!errors&&!warnings,"real threaded multi-queue debug layer is clean");return {{"native_checks",checks.load()},{"real_queues",2},{"submission_threads",2},{"original_executes",2},{"native_gpu_waits",1},{"gate_progress_without_cpu_wait_in_hook",true},{"exact_gpu_value",0x13e5a17u},{"debug_errors",errors},{"debug_warnings",warnings},{"native_birth_dispatcher_ready",NrdBridgeNativeBirth::Ready()},{"native_release_coverage_proved",false}};
}
int main(int argc,char** argv)try{auto result=(argc>1&&std::string(argv[1])=="gpu")?gpuTests():cpuTests();std::cout<<result.dump()<<'\n';return 0;}catch(const std::exception& error){std::fprintf(stderr,"[TRANSACTION_FAILURE] %s\n",error.what());return 1;}
