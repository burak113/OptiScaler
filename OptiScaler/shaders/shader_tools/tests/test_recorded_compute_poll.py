"""Actual lease Poll regression: installed SDK fake COM, CPU only.

No device/shader/GPU job. Run through run_task_test --cpu after the lead grants
the compiler slot. --prepare-only writes the generated source without compiling.
The queue, membership, ownership and callback code is the production header.
"""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp, visual_studio, _toolchain_environment
from test_recorded_compute_submission import methods


def fake_com(sdk):
    base = r'''
#define OBJECT_BASE(IFACE) \
 std::atomic<ULONG> refs{1}; \
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid,void** out)override{observeNative();*out=nullptr; \
  if(iid!=IID_IUnknown&&iid!=__uuidof(IFACE))return E_NOINTERFACE;*out=static_cast<IFACE*>(this);AddRef();return S_OK;} \
 ULONG STDMETHODCALLTYPE AddRef()override{observeNative();return ++refs;} \
 ULONG STDMETHODCALLTYPE Release()override{observeNative();const auto value=--refs;if(!value)delete this;return value;} \
 HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID,UINT*,void*)override{return E_NOTIMPL;} \
 HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID,UINT,const void*)override{return E_NOTIMPL;} \
 HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID,const IUnknown*)override{return E_NOTIMPL;} \
 HRESULT STDMETHODCALLTYPE SetName(LPCWSTR)override{return S_OK;}
#define CHILD_DEVICE \
 IUnknown* owner; \
 HRESULT STDMETHODCALLTYPE GetDevice(REFIID iid,void** out)override{observeNative();return owner->QueryInterface(iid,out);}
struct FakeFence:ID3D12Fence{
 OBJECT_BASE(ID3D12Fence) CHILD_DEVICE
 std::atomic<UINT64> completed{0};std::atomic<unsigned> queries{0};std::atomic<Pause*> pause{nullptr};
 FakeFence(IUnknown* device,UINT64 value):owner(device),completed(value){owner->AddRef();}
 ~FakeFence(){observeOwned();++fencesDestroyed;owner->Release();}
'''
    fence = methods(sdk, 'ID3D12Fence', {
        'GetCompletedValue': '{observeNative();++queries;++fenceQueries;if(auto* p=pause.load())p->enter();return completed.load();}',
        'Signal': '{observeNative();completed.store(Value);return S_OK;}',
    })
    queue = methods(sdk, 'ID3D12CommandQueue', {
        'Signal': '{observeNative();++signals;if(failSignal.load())return E_FAIL;if(completeSignal.load())return pFence->Signal(Value);return S_OK;}',
        'Wait': '{observeNative();++waits;return S_OK;}',
    })
    device = methods(sdk, 'ID3D12Device', {
        'CreateFence': '{observeNative();++creates;if(failFence.load())return E_FAIL;*ppFence=new FakeFence(this,InitialValue);return S_OK;}',
    })
    return base + fence + r'''
};
struct FakeQueue:ID3D12CommandQueue{
 OBJECT_BASE(ID3D12CommandQueue) CHILD_DEVICE
 std::atomic<bool> completeSignal{false},failSignal{false};std::atomic<unsigned> signals{0},waits{0};
 explicit FakeQueue(IUnknown* device):owner(device){owner->AddRef();}
 ~FakeQueue(){observeOwned();owner->Release();}
''' + queue + r'''
};
struct FakeDevice:ID3D12Device{
 OBJECT_BASE(ID3D12Device)
 std::atomic<bool> failFence{false};std::atomic<unsigned> creates{0};
 ~FakeDevice(){observeOwned();}
''' + device + r'''
};
struct Identity:IUnknown{
 std::atomic<ULONG> refs{1};
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid,void** out)override{observeNative();*out=nullptr;if(iid!=IID_IUnknown)return E_NOINTERFACE;*out=this;AddRef();return S_OK;}
 ULONG STDMETHODCALLTYPE AddRef()override{observeNative();return ++refs;}
 ULONG STDMETHODCALLTYPE Release()override{observeNative();const auto value=--refs;if(!value)delete this;return value;}
 ~Identity(){observeOwned();}
};
'''


PREAMBLE = r'''
#define NOMINMAX
#define FSRD_RECORDED_COMPUTE_LEASE_TEST
#include <d3d12.h>
#include <wrl/client.h>
#include <array>
#include <atomic>
#include <barrier>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <malloc.h>
#include <new>
#include <stdexcept>
#include <thread>
#include <vector>
#include "misc/RecordedComputeLease_Dx12.h"
namespace L=RecordedComputeLease;
using Microsoft::WRL::ComPtr;
std::atomic<unsigned> checks{0},allocations{0},deallocations{0},denied{0};
std::atomic<unsigned> nativeInside{0},ownedInside{0},memoryInside{0},ownersDestroyed{0},fencesDestroyed{0},fenceQueries{0};
// A same-thread probe is used only in serial cases. Concurrent correctness uses
// explicit rendezvous and exact counts, never a false "other thread owns lock".
thread_local bool serialProbe=false,denyMemory=false;
bool registryFree(){auto& r=L::GetRegistry();if(!r.mutex.try_lock())return false;r.mutex.unlock();return true;}
void observeNative(){if(serialProbe&&!registryFree())++nativeInside;}
void observeOwned(){if(serialProbe&&!registryFree())++ownedInside;}
void observeMemory(){if(serialProbe&&!registryFree())++memoryInside;}
void* operator new(size_t bytes){++allocations;if(denyMemory){++denied;throw std::bad_alloc();}observeMemory();if(auto* p=std::malloc(bytes?bytes:1))return p;throw std::bad_alloc();}
void operator delete(void* p)noexcept{if(p){++deallocations;observeMemory();}std::free(p);}
void operator delete(void* p,size_t)noexcept{::operator delete(p);}
void* operator new[](size_t bytes){return ::operator new(bytes);}
void operator delete[](void* p)noexcept{::operator delete(p);}
void operator delete[](void* p,size_t)noexcept{::operator delete(p);}
void* operator new(size_t bytes,std::align_val_t align){++allocations;if(denyMemory){++denied;throw std::bad_alloc();}observeMemory();if(auto* p=_aligned_malloc(bytes?bytes:1,size_t(align)))return p;throw std::bad_alloc();}
void operator delete(void* p,std::align_val_t)noexcept{if(p){++deallocations;observeMemory();}_aligned_free(p);}
void operator delete(void* p,size_t,std::align_val_t align)noexcept{::operator delete(p,align);}
void* operator new[](size_t bytes,std::align_val_t align){return ::operator new(bytes,align);}
void operator delete[](void* p,std::align_val_t align)noexcept{::operator delete(p,align);}
void need(bool value,const char* text){if(!value)throw std::runtime_error(text);++checks;}
struct Pause{
 std::mutex mutex;std::condition_variable ready;unsigned entered=0;bool open=false;
 void enter(){std::unique_lock lock(mutex);++entered;ready.notify_all();ready.wait(lock,[&]{return open;});}
 bool wait(unsigned count){std::unique_lock lock(mutex);return ready.wait_for(lock,std::chrono::seconds(5),[&]{return entered>=count;});}
 void release(){std::lock_guard lock(mutex);open=true;ready.notify_all();}
};
struct ProbeScope{bool priorSerial=serialProbe,priorDeny=denyMemory;explicit ProbeScope(bool serial=true,bool deny=true){serialProbe=serial;denyMemory=deny;}~ProbeScope(){serialProbe=priorSerial;denyMemory=priorDeny;}};
void checkedPoll(){const auto a=allocations.load(),d=denied.load();{ProbeScope scope;L::Poll();}need(allocations==a&&denied==d,"Poll has no heap allocation, including completed-owner retirement");need(!nativeInside&&!ownedInside&&!memoryInside,"serial Poll native calls/memory/last owners are outside Registry mutex");}
'''


TESTS = r'''
struct Owner{
 ComPtr<IUnknown> owned;
 Owner(){owned.Attach(new Identity);}
 ~Owner(){observeOwned();++ownersDestroyed;}
};
struct Environment{
 ComPtr<FakeDevice> device;ComPtr<FakeQueue> queue;ComPtr<Identity> identity;std::shared_ptr<Owner> lease;
 explicit Environment(L::SubmissionCallbacks callbacks={}){
  L::ResetRegistryForTesting();device.Attach(new FakeDevice);queue.Attach(new FakeQueue(device.Get()));identity.Attach(new Identity);lease=std::make_shared<Owner>();
  need(L::Track(identity.Get(),{identity.Get()},lease,{},std::move(callbacks)),"actual recording retained");
 }
 ~Environment(){L::ResetRegistryForTesting();}
 std::shared_ptr<L::Submission> before(){
  IUnknown* source[]{identity.Get()};const L::IdentityRange identities{source,1,
   [](const void* context,size_t i,IUnknown** out)->HRESULT{auto* value=static_cast<IUnknown* const*>(context)[i];*out=value;value->AddRef();return S_OK;},
   [](const void* context,size_t i)->void*{return static_cast<IUnknown* const*>(context)[i];}};
  auto s=L::BeforeSubmission(queue.Get(),identities);need(bool(s),"actual submission registered");return s;
 }
 void detach(){auto rec=L::Capture(identity.Get());L::Detach(rec);}
};
void validate(){auto& r=L::GetRegistry();std::lock_guard lock(r.mutex);size_t count=0;L::Submission* previous=nullptr;
 for(size_t i=0;i<r.submissions.size();++i)need(r.submissions[i]&&r.submissions[i]->registrySlot==i,"ownership slot matches exact node after swaps");
 for(auto* s=r.pollHead;s;s=s->pollNext){need(++count<=r.publishedCount,"publication queue is acyclic and count-bounded");need(s->pollPrevious==previous&&s->pollQueued&&s->signalPublished&&L::Detail::RegisteredLocked(r,*s),"queue exact ownership and bidirectional links");previous=s;}
 need(count==r.publishedCount&&previous==r.pollTail,"head/tail and published count agree");
}
void boundedFairBacklog(){
 Environment e;constexpr size_t n=4097;std::vector<std::shared_ptr<L::Submission>> work;work.reserve(n);
 for(size_t i=0;i<n;++i){auto s=e.before();L::AfterSubmission(s);work.push_back(std::move(s));}
 validate();need(L::GetRegistry().publishedCount==n,"large published backlog exists without imposing an unsafe owner cap");
 for(auto& s:work)static_cast<FakeFence*>(s->fence.Get())->queries=0;
 const auto before=fenceQueries.load();checkedPoll();need(fenceQueries==before+L::PollBudget,"one Poll visits exactly64 published nodes in a4097 backlog");
 for(size_t round=1;round<(n+L::PollBudget-1)/L::PollBudget;++round)checkedPoll();
 for(const auto& s:work)need(static_cast<FakeFence*>(s->fence.Get())->queries>=1,"round-robin eventually visits every finite-backlog fence");
 // Alternating completion creates middle removals, displaced vector slots and
 // a surviving suffix; device-removed sentinels use the same proven retirement.
 for(size_t i=0;i<n;++i)if(i%2==0)static_cast<FakeFence*>(work[i]->fence.Get())->completed=(i%4==0?UINT64_MAX:1);
 for(size_t round=0;round<(n+L::PollBudget-1)/L::PollBudget+2;++round)checkedPoll();
 validate();for(size_t i=0;i<n;++i)need((work[i]->registrySlot==L::Submission::Unregistered)==(i%2==0),"middle/tail swaps retire exactly completed or device-removed instances");
 for(auto& s:work)static_cast<FakeFence*>(s->fence.Get())->completed=1;
 const auto remaining=L::GetRegistry().publishedCount;
 for(size_t round=0;round<(remaining+L::PollBudget-1)/L::PollBudget;++round)checkedPoll();
 validate();need(L::GetRegistry().submissions.empty()&&!L::GetRegistry().completionFailed,"all finite-backlog owners eventually retire without global scans or failure");
}
void unpublishedAndFailures(){
 Environment e;std::vector<std::shared_ptr<L::Submission>> unpublished;unpublished.reserve(1025);
 for(unsigned i=0;i<1025;++i)unpublished.push_back(e.before());
 need(L::GetRegistry().publishedCount==0,"unpublished intents never enter completion queue");const auto q=fenceQueries.load();checkedPoll();need(fenceQueries==q&&L::GetRegistry().submissions.size()==1025,"unpublished backlog is pinned without fence queries");
 auto live=e.before();L::AfterSubmission(live);static_cast<FakeFence*>(live->fence.Get())->completed=1;checkedPoll();
 need(L::GetRegistry().submissions.size()==1025&&live->registrySlot==L::Submission::Unregistered,"published tail retires while all unpublished slots remain pinned");validate();
 for(unsigned mode=0;mode<2;++mode){
  L::ResetRegistryForTesting();e.lease=std::make_shared<Owner>();need(L::Track(e.identity.Get(),{e.identity.Get()},e.lease),"quarantine recording");
  e.device->failFence=mode==0;e.queue->failSignal=mode==1;auto s=e.before();L::AfterSubmission(s);const auto query=fenceQueries.load();checkedPoll();
  need(!s->signalPublished&&!s->pollQueued&&L::GetRegistry().publishedCount==0&&L::GetRegistry().submissions.size()==1,"failed fence or Signal preserves unpublished ownership");
  need(fenceQueries==query&&!L::Available(),"uncertain intent is never queried and future admission fails closed");
  e.detach();need(bool(L::Capture(e.identity.Get())),"uncertain recording stays pinned through detach");
  e.device->failFence=false;e.queue->failSignal=false;
 }
 // Reset detaches every old POD link before owners can die outside the mutex.
 L::ResetRegistryForTesting();need(L::GetRegistry().submissions.empty()&&!L::GetRegistry().pollHead&&!L::GetRegistry().pollTail&&!L::GetRegistry().publishedCount,"guarded fixture reset clears ownership and queue links");
}
void lastOwnerOutside(){
 Environment e;e.queue->completeSignal=true;auto s=e.before();L::AfterSubmission(s);std::weak_ptr<Owner> weak=e.lease;e.detach();e.lease.reset();s.reset();
 const auto destroyed=ownersDestroyed.load(),fences=fencesDestroyed.load();need(!weak.expired(),"submission retains sole lease through completion");checkedPoll();
 need(weak.expired()&&ownersDestroyed==destroyed+1&&fencesDestroyed==fences+1,"last submission owner destroys lease and native fence once outside Registry mutex");
}
void latePublication(){
 Environment e;auto first=e.before();L::AfterSubmission(first);auto later=e.before();auto* fence=static_cast<FakeFence*>(first->fence.Get());Pause pause;fence->pause=&pause;
 std::thread poller([&]{ProbeScope guard(false);L::Poll();});const bool entered=pause.wait(1);const bool unlocked=registryFree();
 e.queue->completeSignal=true;L::AfterSubmission(later);auto* laterFence=static_cast<FakeFence*>(later->fence.Get());pause.release();poller.join();fence->pause=nullptr;
 need(entered&&unlocked,"native completion query leaves Registry available for another publication");need(laterFence->queries==0&&later->pollQueued,"late published node waits for next bounded snapshot");
 checkedPoll();need(later->registrySlot==L::Submission::Unregistered&&first->pollQueued,"next snapshot retires only the completed late publication");validate();
}
void concurrentSameSnapshot(){
 Environment e;e.queue->completeSignal=true;auto s=e.before();L::AfterSubmission(s);auto* fence=static_cast<FakeFence*>(s->fence.Get());Pause pause;fence->pause=&pause;
 std::weak_ptr<Owner> weak=e.lease;e.detach();e.lease.reset();s.reset();const auto destroyed=ownersDestroyed.load(),fences=fencesDestroyed.load(),denies=denied.load();
 std::thread a([&]{ProbeScope guard(false);L::Poll();}),b([&]{ProbeScope guard(false);L::Poll();});const bool entered=pause.wait(2),unlocked=registryFree();pause.release();a.join();b.join();
 need(entered&&unlocked,"two native queries can overlap while metadata remains available");need(weak.expired()&&ownersDestroyed==destroyed+1&&fencesDestroyed==fences+1,"concurrent duplicate snapshots retire exactly once and keep native owner pinned");
 need(denied==denies&&!L::GetRegistry().completionFailed&&L::GetRegistry().submissions.empty(),"concurrent Poll allocates nothing and stale exact slots are harmless");validate();
}
void concurrentBacklog(){
 Environment e;std::vector<std::shared_ptr<L::Submission>> work;work.reserve(513);
 for(unsigned i=0;i<513;++i){auto s=e.before();L::AfterSubmission(s);work.push_back(std::move(s));}
 for(auto& s:work)static_cast<FakeFence*>(s->fence.Get())->completed=1;
 std::barrier start(8);std::array<std::thread,8> workers;const auto denies=denied.load();
 for(auto& thread:workers)thread=std::thread([&]{start.arrive_and_wait();ProbeScope guard(false);for(unsigned i=0;i<16;++i)L::Poll();});
 for(auto& thread:workers)thread.join();validate();
 need(L::GetRegistry().submissions.empty()&&!L::GetRegistry().completionFailed&&denied==denies,"eight overlapping bounded Poll workers safely retire513 exact displaced slots without allocation");
 for(const auto& s:work)need(s->registrySlot==L::Submission::Unregistered&&!s->pollQueued,"every concurrently retired node has no live membership");
}
void resetLastOwnersOutside(){
 Environment e;auto s=e.before();L::AfterSubmission(s);std::weak_ptr<Owner> weak=e.lease;e.lease.reset();s.reset();const auto destroyed=ownersDestroyed.load(),fences=fencesDestroyed.load();
 {ProbeScope scope(true,false);L::ResetRegistryForTesting();}
 need(weak.expired()&&ownersDestroyed==destroyed+1&&fencesDestroyed==fences+1,"fixture reset detaches and destroys last native/lease owners only outside Registry mutex");
 need(!nativeInside&&!ownedInside&&!memoryInside,"fixture reset may allocate empty staging outside but never allocates/destroys/calls native while locked");
}
void publicationCallbackRace(){
 Pause callback;std::atomic<unsigned> published{0},failed{0};std::atomic<bool> callbackOwnerAlive{false};std::weak_ptr<Owner> weak;
 L::SubmissionCallbacks callbacks;callbacks.fencePublished=[&](const auto&,const auto& point){++published;need(point&&point->IsPublished(),"callback receives already published lightweight fence");callback.enter();callbackOwnerAlive=!weak.expired();};
 callbacks.failed=[&](const auto&,auto){++failed;};Environment e(callbacks);e.queue->completeSignal=true;auto s=e.before();weak=e.lease;e.detach();e.lease.reset();
 std::thread publisher([hold=s]{L::AfterSubmission(hold);});s.reset();const bool entered=callback.wait(1);const bool unlocked=registryFree();checkedPoll();const bool pinned=!weak.expired();
 callback.release();publisher.join();need(entered&&unlocked&&pinned&&callbackOwnerAlive,"Poll can retire registry ownership while active publisher/callback pins every lease");
 need(published==1&&!failed&&weak.expired()&&L::GetRegistry().submissions.empty(),"publication callback completes exactly once without ownership cycle");
}
void participantsAndReset(){
 Environment e;Identity unknown;need(L::HasSubmissionParticipant(e.identity.Get(),nullptr),"canonical retained participant requires serialization");need(L::HasSubmissionParticipant(&unknown,e.identity.Get()),"strongly resolved alias retains participant");
 need(L::HasSubmissionParticipant(nullptr,nullptr),"unknown identity conservatively requires serialization");need(!L::HasSubmissionParticipant(&unknown,&unknown),"healthy exact nonparticipant can bypass transaction serialization");
 auto rec=L::BeginRelease(e.identity.Get());need(L::HasSubmissionParticipant(&unknown,e.identity.Get()),"Release gap remains participant");L::EndRelease(rec,false);e.detach();rec.reset();
 need(!L::HasSubmissionParticipant(e.identity.Get(),e.identity.Get()),"exact fully detached generation is no longer a participant");L::FailCompletion();need(L::HasSubmissionParticipant(&unknown,&unknown),"failed snapshot/completion conservatively requires serialization");
 L::ResetRegistryForTesting();e.lease=std::make_shared<Owner>();need(L::Track(e.identity.Get(),{e.identity.Get()},e.lease),"reset re-registers recording");auto old=e.before();L::AfterSubmission(old);L::ResetRegistryForTesting();
 need(old->registrySlot==L::Submission::Unregistered&&!old->pollQueued&&!old->pollPrevious&&!old->pollNext,"held old fixture ticket has no stranded publication links after reset");
 need(L::Track(e.identity.Get(),{e.identity.Get()},e.lease),"new fixture generation after queue reset");e.queue->completeSignal=true;auto fresh=e.before();L::AfterSubmission(fresh);checkedPoll();
 need(fresh->registrySlot==L::Submission::Unregistered&&L::GetRegistry().submissions.empty(),"post-reset fresh publication cannot follow old raw pointers");
}
int main()try{
 L::ResetRegistryForTesting();need(L::PollBudget==64,"fixed production completion budget is64");checkedPoll();
 boundedFairBacklog();unpublishedAndFailures();lastOwnerOutside();latePublication();concurrentSameSnapshot();concurrentBacklog();resetLastOwnersOutside();publicationCallbackRace();participantsAndReset();
 need(!nativeInside&&!ownedInside&&!memoryInside&&!denied,"all serial lock probes and allocation-free Poll checks remain clean");
 std::cout<<"{\"checks\":"<<checks<<",\"poll_budget\":"<<L::PollBudget<<",\"large_backlog\":4097,\"unpublished_backlog\":1025,\"native_inside_registry\":"<<nativeInside<<",\"owned_inside_registry\":"<<ownedInside<<",\"memory_inside_registry\":"<<memoryInside<<",\"poll_denied_allocations\":"<<denied<<",\"scope\":\"actual header; installed SDK fake COM; CPU only\"}\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
'''


def run():
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/13b-inputs/tests/recorded_poll'))
    output.mkdir(parents=True, exist_ok=True)
    env = _toolchain_environment(visual_studio())
    sdk = next(Path(path) / 'd3d12.h' for path in env['INCLUDE'].split(';')
               if (Path(path) / 'd3d12.h').is_file()).read_text()
    source = output / 'recorded_poll.cpp'
    source.write_bytes((PREAMBLE + fake_com(sdk) + TESTS).replace('\r\n', '\n').replace('\n', '\r\n').encode())
    if '--prepare-only' in sys.argv:
        print(json.dumps({'prepared': str(source), 'compiled': False, 'run': False}))
        return
    os.environ['FSRD_CPP_CACHE'] = str(output / 'cache')
    exe = output / 'recorded_poll.exe'
    compile_cpp(source, exe, ('d3d12.lib', 'dxgi.lib', 'dxguid.lib'), (ROOT / 'OptiScaler',))
    result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=45)
    (output / 'native.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f'Lease Poll fixture failed ({result.returncode}): {result.stdout} {result.stderr}')
    values = json.loads(result.stdout)
    assert values['poll_budget'] == 64 and values['large_backlog'] == 4097
    assert values['unpublished_backlog'] == 1025
    assert all(values[key] == 0 for key in ('native_inside_registry', 'owned_inside_registry',
                                          'memory_inside_registry', 'poll_denied_allocations'))
    values['python_checks'] = 3
    (output / 'result.json').write_text(json.dumps(values, indent=2) + '\n')
    print(json.dumps(values, indent=2))


if __name__ == '__main__':
    run()
