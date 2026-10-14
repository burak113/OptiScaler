"""Activated native metadata source, actual Birth dispatcher, opaque POD emulation.

Every legacy65 assertion is retained. No opaque pointer reaches COM: the coverage
facade aborts if a cold native getter is accidentally required. Genuine native
object forwarding, driver cost and GUID publication use the separate WARP fixture.
"""
from pathlib import Path
import test_fsrd_frame_survey_birth_metadata as legacy

DRIVER = legacy.DRIVER

def replace_once(old, new):
    global DRIVER
    assert DRIVER.count(old) == 1, old[:100]
    DRIVER = DRIVER.replace(old, new, 1)

replace_once('thread_local FrameSurvey::RetirementEffects* currentEffects=nullptr;', r"""
thread_local FrameSurvey::RetirementEffects* currentEffects=nullptr;
void* activeFactory()noexcept {return currentEffects;}
bool activeDetach(void* payload,const NrdBridgeBirth::Token& birth)noexcept {
 if(payload!=currentEffects||!NrdBridgeBirth::InMetadataAction())std::terminate();
 return FrameSurvey::DetachReleaseMetadata(birth,*static_cast<FrameSurvey::RetirementEffects*>(payload));
}
void activeNotify(void* payload)noexcept {
 if(payload!=currentEffects||NrdBridgeBirth::InMetadataScope())std::terminate();
 // The caller owns this pure test payload and explicitly drains notification
 // later to retain every old delayed-observer assertion.
}
""")
replace_once('need(!NrdBridgeNativeBirth::Ready(),"native helper intentionally unconfigured: no opaque address may reach COM");',
             'need(!NrdBridgeNativeBirth::Ready(),"native dispatcher starts unconfigured");')
replace_once('need(NrdBridgeBirth::ConfigureActions({detach,identity,nullptr}),"actual process registry dispatcher configured");',
             'need(NrdBridgeNativeBirth::ConfigureRetirement(activeFactory,activeDetach,activeNotify)&&NrdBridgeNativeBirth::Ready(),"actual native dispatcher activates hot metadata with pure caller-owned effects");')
replace_once('{NrdBridgeBirth::CurrentGuard guard(old);need(guard.Retire(),"actual current guard invokes pure FrameSurvey detach");}',
             '{NrdBridgeNativeBirth::RetirementScope retirement;need(retirement.Valid(),"actual native retirement TLS payload is installed before guard");NrdBridgeBirth::CurrentGuard guard(old);need(guard.Retire(),"actual current guard invokes pure FrameSurvey detach");}')

EXTRA = r"""
 // All these callbacks execute the activated production fast path, never an
 // emulated alternate implementation. Only descriptions/addresses are POD.
 need(FrameSurvey::NativeTracking()&&FrameSurvey::gNativeResources.Find(a)&&FrameSurvey::gNativeHeaps.Find(h),"native mode publishes pinned immutable metadata nodes");
 need(FrameSurvey::gViews.at(ph.cpu).resourceOwner&&FrameSurvey::gViews.at(ph.cpu).heapOwner,"native slots pin pure metadata owners without COM references");
 auto unknownSource=D3D12_CPU_DESCRIPTOR_HANDLE{ph.cpu+20*ph.increment};
 auto unknownDestination=D3D12_CPU_DESCRIPTOR_HANDLE{ph.cpu+21*ph.increment};
 D3D12_CONSTANT_BUFFER_VIEW_DESC unknown{0x990000,1536};FrameSurvey::View(unknownSource,&unknown);
 need(FrameSurvey::gViews.contains(unknownSource.ptr)&&!FrameSurvey::gViews.at(unknownSource.ptr).object,"unknown CBV retains aligned native declaration only");
 FrameSurvey::NativeCopyDescriptors(ph.increment,1,&unknownDestination,nullptr,1,&unknownSource,nullptr,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 need(FrameSurvey::gViews.contains(unknownDestination.ptr)&&FrameSurvey::gViews.at(unknownDestination.ptr).rootVa==unknown.BufferLocation&&!FrameSurvey::gViews.at(unknownDestination.ptr).resourceOwner,"unknown declaration copy uses heap freshness independently of resource ownership");
 auto unknownBindings=bindings;unknownBindings.tables[1].second={ph.gpu+21*ph.increment};
 need(FrameSurvey::SeedComputeBindings(c,unknownBindings),"unknown declaration current native table seeds");
 FrameSurvey::BoundConstantBuffer unknownBuffer;FrameSurvey::BoundConstantBinding unknownNative;
 need(!FrameSurvey::ResolveComputeConstantBuffer(c,6,0,1216,unknownBuffer),"diagnostic CBV never guesses unknown resource owner");
 need(FrameSurvey::ResolveComputeConstantBinding(unknownBindings,6,0,unknownNative)&&unknownNative.descriptor.ptr==ph.gpu+21*ph.increment,"native volatile CB6 admission is independent of diagnostic GPUVA ownership");
 FrameSurvey::View(unknownSource,static_cast<const D3D12_CONSTANT_BUFFER_VIEW_DESC*>(nullptr));
 FrameSurvey::NativeCopyDescriptors(ph.increment,1,&unknownDestination,nullptr,1,&unknownSource,nullptr,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 need(!FrameSurvey::gViews.contains(unknownDestination.ptr),"unknown copy source tombstones a previously valid declaration");
 FrameSurvey::View({ph.cpu+ph.increment},&cv);
 auto aliasDestination=D3D12_CPU_DESCRIPTOR_HANDLE{ph.cpu+22*ph.increment};
 auto aliasSource=D3D12_CPU_DESCRIPTOR_HANDLE{ph.cpu+ph.increment};
 FrameSurvey::NativeCopyDescriptors(ph.increment,1,&aliasDestination,nullptr,1,&aliasSource,nullptr,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 FrameSurvey::NativeCopyDescriptors(ph.increment,1,&aliasDestination,nullptr,1,&aliasDestination,nullptr,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 need(FrameSurvey::gViews.at(aliasDestination.ptr).object==a&&FrameSurvey::gViews.at(aliasDestination.ptr).resourceOwner==FrameSurvey::gNativeResources.Find(a),"same-slot copy snapshots exact owners before mutation");
 auto* overlapBuffer=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x80000));auto overlapBufferBirth=born(overlapBuffer,206);
 auto bufferOverlap=buffer(overlapBuffer,pa.address+256);need(FrameSurvey::PublishResourceMetadata(bufferOverlap,overlapBufferBirth),"overlapping live placed-buffer interval publication");
 D3D12_CONSTANT_BUFFER_VIEW_DESC ambiguous{pa.address+256,1536};FrameSurvey::View(unknownSource,&ambiguous);
 need(!FrameSurvey::gViews.at(unknownSource.ptr).object,"live original birth does not preserve a stale unique VA owner after interval version change");
 FrameSurvey::RetirementEffects overlapBufferEffects;retire(overlapBufferBirth,overlapBufferEffects);FrameSurvey::NotifyRelease(overlapBufferEffects);
 FrameSurvey::View(unknownSource,&ambiguous);
 need(FrameSurvey::gViews.at(unknownSource.ptr).object==a,"exact interval retirement restores unique diagnostic ownership");
 auto* overlapHeap=reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(0x90000));auto overlapHeapBirth=born(overlapHeap,207);
 auto typedOverlap=ph;typedOverlap.object=overlapHeap;need(FrameSurvey::PublishHeapMetadata(typedOverlap,overlapHeapBirth),"adversarial same-type overlapping numeric heap interval publication");
 FrameSurvey::View(unknownSource,&cv);need(!FrameSurvey::gViews.contains(unknownSource.ptr),"ambiguous heap lookup tombstones destination instead of reusing cached owner");
 FrameSurvey::RetirementEffects overlapHeapEffects;retire(overlapHeapBirth,overlapHeapEffects);FrameSurvey::NotifyRelease(overlapHeapEffects);
 FrameSurvey::View(unknownSource,&cv);need(FrameSurvey::gViews.at(unknownSource.ptr).heapOwner==FrameSurvey::gNativeHeaps.Find(h),"exact overlapping heap retirement restores original typed interval");
 auto cached=FrameSurvey::NativeResource(a);need(bool(cached),"resource cache contains current exact birth");
 {NrdBridgeBirth::ScopedRelease pending(fresh);need(!FrameSurvey::NativeResource(a)&&!FrameSurvey::NativeNodeCurrent(cached),"metadata cache cannot bypass actual shared physical release-in-flight counter");}
 need(FrameSurvey::NativeResource(a)==cached,"same-instance nonfinal completion restores admissible cached node");
 {
  NrdBridgeBirth::ScopedRelease pending(fresh);
  FrameSurvey::View(aliasSource,&cv);FrameSurvey::NativeCopyDescriptors(ph.increment,1,&aliasDestination,nullptr,1,&aliasSource,nullptr,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  need(FrameSurvey::NativeViewMetadataFresh(FrameSurvey::gViews.at(aliasDestination.ptr))&&!FrameSurvey::NativeViewFresh(FrameSurvey::gViews.at(aliasDestination.ptr)),"nonfinal resource release preserves pure descriptor metadata but cannot admit native borrow");
 }
 need(FrameSurvey::NativeViewFresh(FrameSurvey::gViews.at(aliasDestination.ptr)),"copied resource descriptor becomes borrow-admissible after nonfinal release completion without recopy");
 {
  NrdBridgeBirth::ScopedRelease pending(newHeap);
  FrameSurvey::View(aliasSource,&cv);FrameSurvey::NativeCopyDescriptors(ph.increment,1,&aliasDestination,nullptr,1,&aliasSource,nullptr,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  need(FrameSurvey::NativeViewMetadataFresh(FrameSurvey::gViews.at(aliasDestination.ptr))&&!FrameSurvey::NativeViewFresh(FrameSurvey::gViews.at(aliasDestination.ptr)),"nonfinal heap release preserves pure descriptor metadata but cannot admit native borrow");
 }
 need(FrameSurvey::NativeViewFresh(FrameSurvey::gViews.at(aliasDestination.ptr)),"copied heap descriptor becomes borrow-admissible after nonfinal release completion without recopy");
 // Hold only the OLD global catalog. Native create/copy callbacks must finish
 // before it is released, proving no hidden catalog dependency in the hot path.
 std::promise<void> hotDone;auto hotFuture=hotDone.get_future();std::atomic<bool> hotPassed{false};std::jthread hot;
 {
  std::unique_lock oldCatalog(FrameSurvey::gLifetimeMutex);
  hot=std::jthread([&]{try{
   FrameSurvey::View(unknownSource,&cv);FrameSurvey::View(t,{ph.cpu},&srv);
   FrameSurvey::NativeCopyDescriptors(ph.increment,1,&unknownDestination,nullptr,1,&unknownSource,nullptr,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
   hotPassed=FrameSurvey::gViews.at(unknownDestination.ptr).object==a;
  }catch(...){}hotDone.set_value();});
  need(hotFuture.wait_for(std::chrono::seconds(2))==std::future_status::ready,"native CBV/SRV/Copy finish while old catalog is held exclusively");
 }
 hot.join();need(hotPassed,"catalog-independent hot callbacks preserve exact current ownership");
 // A long-copy SH scope must not exclude unrelated lifecycle SH retirement.
 auto* separate=reinterpret_cast<ID3D12Resource*>(uintptr_t(0xa0000));auto separateBirth=born(separate,208);
 auto separateDescription=buffer(separate,0xb00000);need(FrameSurvey::PublishResourceMetadata(separateDescription,separateBirth),"unrelated native resource POD publication");
 std::promise<void> retireDone;auto retireFuture=retireDone.get_future();FrameSurvey::RetirementEffects separateEffects;std::jthread retiring;
 {
  FrameSurvey::NativeSnapshotShared longCopy;
  retiring=std::jthread([&]{retire(separateBirth,separateEffects);retireDone.set_value();});
  need(retireFuture.wait_for(std::chrono::seconds(2))==std::future_status::ready,"unrelated final retirement is admitted during whole-copy snapshot SH");
 }
 retiring.join();FrameSurvey::NotifyRelease(separateEffects);
 need(!FrameSurvey::gResources.contains(separate)&&!FrameSurvey::gNativeResources.Find(separate),"retirement clears both cold and pinned identity stores");
 // Whole-operation readers remain excluded, and partial allocation failure is
 // latched BEFORE the last writer releases its snapshot scope.
 need(FrameSurvey::SeedComputeBindings(c,bindings),"current bindings restored before partial-copy fault");
 std::promise<void> readerEntered,readerDone;auto entered=readerEntered.get_future(),done=readerDone.get_future();
 std::atomic<bool> partialAccepted{true},recorderRejected{false};std::jthread reader,recorder;
 std::promise<void> recorderEntered,recorderDone;auto recorderStarted=recorderEntered.get_future(),recorderFinished=recorderDone.get_future();
 FrameSurvey::gService=std::make_unique<FrameSurvey::Service>();FrameSurvey::gEnabled.store(true);FrameSurvey::gRecording.store(true);
 FrameSurvey::gService->lists[c].id=++FrameSurvey::gNextList;
 {
  FrameSurvey::NativeSnapshotShared writer;
  reader=std::jthread([&]{readerEntered.set_value();FrameSurvey::BoundConstantBuffer value;partialAccepted=FrameSurvey::ResolveComputeConstantBuffer(c,6,0,1216,value);readerDone.set_value();});
  recorder=std::jthread([&]{
   std::scoped_lock record(FrameSurvey::gRecordMutex);recorderEntered.set_value();
   FrameSurvey::List list;const bool seeded=FrameSurvey::Seed(c,list);J unresolved=J::array();auto potential=FrameSurvey::Bindings(list,false,unresolved);
   D3D12_CPU_DESCRIPTOR_HANDLE target{ph.cpu};FrameSurvey::RenderTargets(c,1,&target,FALSE);
   D3D12_RESOURCE_BARRIER barrier{};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
   barrier.Transition={t,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE};
   FrameSurvey::Barrier(c,1,&barrier);
   recorderRejected=!seeded&&potential.empty()&&FrameSurvey::gService->lists[c].targets.empty()&&FrameSurvey::gRecording.load()&&!FrameSurvey::Recording();
   recorderDone.set_value();
  });
  entered.wait();recorderStarted.wait();need(done.wait_for(std::chrono::milliseconds(20))==std::future_status::timeout,"POD reader drains the complete copy snapshot rather than seeing individual slot fragments");
  need(recorderFinished.wait_for(std::chrono::milliseconds(20))==std::future_status::timeout,"recorder holding gRecord also waits whole-copy EX drain");
  UINT one=1;auto destination=D3D12_CPU_DESCRIPTOR_HANDLE{ph.cpu+30*ph.increment};auto source=D3D12_CPU_DESCRIPTOR_HANDLE{ph.cpu};
  FrameSurvey::gViewFailureAfterReverseForTesting=true;
  try{FrameSurvey::NativeCopyDescriptors(ph.increment,1,&destination,&one,1,&source,&one,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);need(false,"injected post-reverse insertion must throw");}catch(const std::bad_alloc&){}
  need(!FrameSurvey::MetadataHealthy(),"actual mutation unwind latches metadata failure while outer SH still holds");
  need(FrameSurvey::gNativeResources.Find(t)->handles->contains(destination.ptr)&&!FrameSurvey::gViews.contains(destination.ptr),"fault occurs after real reverse insertion and before view emplace; orphan cannot be traversed");
 }
 done.wait();recorderFinished.wait();reader.join();recorder.join();
 need(!partialAccepted,"waiting reader fails closed after partial mutation instead of accepting old live metadata");
 need(recorderRejected,"Seed/Bindings/RTV/Barrier recheck health after EX while gRecording remains true and never traverse orphan reverse slot");
 FrameSurvey::gRecording.store(false);
 // Failed mutation is followed only by teardown: captures from this epoch may
 // never become eligible merely because the physical Birth remains live.
 const auto oldEpoch=FrameSurvey::gNativeMetadataEpoch.load();auto epochPinned=FrameSurvey::gNativeResources.Find(a);
 FrameSurvey::Shutdown();need(FrameSurvey::gNativeMetadataEpoch.load()!=oldEpoch&&!FrameSurvey::NativeNodeCurrent(epochPinned),"metadata shutdown invalidates cached nodes even while physical birth remains live");
 FrameSurvey::BeginCreationTracking(false);FrameSurvey::SetBindingWindow(true);
 need(FrameSurvey::PublishResourceMetadata(pa,fresh)&&FrameSurvey::gNativeResources.Find(a)!=epochPinned,"restart publishes new metadata node for unchanged native instance birth");
"""
replace_once(' // Failed metadata mutation under a guard is latched there and handled outside it.', EXTRA+'\n // Failed metadata mutation under a guard is latched there and handled outside it.')
replace_once('"source","actual_FrameSurvey_methods_with_actual_Birth_registry_metadata_emulation"',
             '"source","actual_native_active_FrameSurvey_methods_with_actual_Birth_dispatcher_metadata_emulation"')

if __name__ == '__main__':
    legacy.run(DRIVER, 'native-metadata-active-cpu.json', '#include <future>\n#define FSRD_NRD_BRIDGE_TEST\n')
