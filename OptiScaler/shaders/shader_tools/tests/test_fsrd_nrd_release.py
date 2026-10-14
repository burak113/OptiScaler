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


def run():
    d3d = (ROOT/'OptiScaler/hooks/D3D12_Hooks.cpp').read_text()
    res = (ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.cpp').read_text()
    state = d3d[d3d.index('// Common'):d3d.index('// Intel Atomic Extension')]
    state = state.replace('ankerl::unordered_dense::map','std::unordered_map')
    cpp = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <vector>
#include <memory>
#include <algorithm>
#include <shared_mutex>
#include <mutex>
#include <unordered_map>
#include <unordered_set>
#include <stdexcept>
#include <iostream>
#include <atomic>
#include <chrono>
#include <future>
#include <thread>
#include <functional>
#include "__ROOT__/OptiScaler/misc/NrdBridgeLifetime_Dx12.h"
#include "__ROOT__/OptiScaler/hooks/Hook_Utils.h"
#define LOG_INFO(...) ((void)0)
__STATE__
bool gNrdBridgeDeviceWrappers=true,gNrdBridgeWrappers=true,gSurveyWrappers=true;
unsigned checks=0,releasesObserved=0,psoCleaned=0,slotsCleaned=0,leaseEnds=0;
std::atomic<unsigned> leaseBegins=0;
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
namespace FrameSurvey {
 thread_local bool internal=false;
 bool Internal() { return internal; }
 void Released(void*) { ++releasesObserved; }
}
struct HeapSlot { void ClearSlotIfMatches(size_t,ID3D12Resource*) { ++slotsCleaned; } };
struct TrackedResourceSlot { std::weak_ptr<HeapSlot> heap; size_t index=0; };
std::mutex _trackedResourcesMutex,gRRResourceStateMutex,gRRTrackedResourceMutex,gRRPsoMutex;
std::unordered_map<ID3D12Resource*,std::vector<TrackedResourceSlot>> _trackedResources;
std::unordered_set<ID3D12Resource*> gRRResourceStates,gRRResourceActivity,gRRTrackedResources,gRRResourcePsoProducers;
void CleanupRRPsoReferences(void*) { ++psoCleaned; }
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
ULONG releaseResource(ID3D12Resource* resource) { return reinterpret_cast<IUnknown*>(resource)->Release(); }
ULONG releaseUnknown(IUnknown* object) { return object->Release(); }
ULONG releasePso(ID3D12PipelineState* object) { return reinterpret_cast<IUnknown*>(object)->Release(); }
auto o_Release=&releaseResource;
auto o_CommandListRelease=&releaseUnknown;
auto o_PsoRelease=&releasePso;
bool gResourceReleaseSharesPso=false;
bool gResourceReleaseSharesCommandList=false;
ULONG (*gSharedResourceReleaseObserver)(ID3D12Resource*)=nullptr;
__RELEASE__
__COMMAND_RELEASE__
__PSO_RELEASE__
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
 { NrdBridgeLifetime::ScopedBorrow borrowed; FrameSurvey::internal=true;
  need(hkRelease(reinterpret_cast<ID3D12Resource*>(&owned))==0 && owned.destroyed,"internal bridge-owned releases bypass the title gate during borrow");
  FrameSurvey::internal=false;
 }
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

int main() try {
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
 gRRResourceStates.insert(address); gRRResourceActivity.insert(address); gRRTrackedResources.insert(address);
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
 std::cout << "PASS: " << checks << " production shared/dedicated Release checks\n";
 return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
'''
    replacements = {
        'ROOT':ROOT.as_posix(), 'STATE':state,
        'RESET':function(d3d,'void D3D12Hooks::OnBridgeCommandListReset('),
        'RELEASE':res_function(res,'hkRelease'),
        'COMMAND_RELEASE':function(res,'static ULONG STDMETHODCALLTYPE hkCommandListRelease(IUnknown* This)\n{'),
        'PSO_RELEASE':function(res,'ULONG hkPsoRelease(ID3D12PipelineState* This)\n{'),
    }
    for name, value in replacements.items():
        cpp = cpp.replace('__'+name+'__', value)
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    source, exe = out/'nrd_release.cpp', out/'nrd_release.exe'
    source.write_text(cpp)
    compile_cpp(source,exe)
    result = subprocess.run([str(exe)],check=True,capture_output=True,text=True,timeout=30)
    print(result.stdout,end='')
    checks = int(re.search(r'PASS: (\d+)',result.stdout).group(1))
    (out/'result.json').write_text(json.dumps({'native_checks':checks,
        'scope':'production dedicated/shared resource/PSO/list Release bodies and actual root-cache cleanup; threaded fake IUnknown proves exclusive-before-registry ordering, borrowed CPU lifetime, recursion, internal bypass and OFF parity'})+'\n')


if __name__ == '__main__':
    run()
