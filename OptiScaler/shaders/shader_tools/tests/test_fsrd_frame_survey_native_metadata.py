"""Activated native metadata source, actual Birth dispatcher, opaque POD emulation.

Every legacy65 assertion is retained. No opaque pointer reaches COM: the coverage
facade aborts if a cold native getter is accidentally required. Genuine native
object forwarding, driver cost and GUID publication use the separate WARP fixture.
"""
from pathlib import Path
import argparse
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

MASK_EXTRA = r"""
 {
 // Immutable heap bounds: every legal position is included; remaining/invalid
 // ranges conservatively require all shards. Opaque callbacks below are POD-only.
 using Mask=FrameSurveyMetadata::DescriptorShardMask;
 const auto shards=FrameSurveyMetadata::DescriptorShards;
 need(Mask{}.Count()==0&&Mask::All().Count()==shards,"empty and full mask cover exactly the compiled shard domain");
 const auto singleMask=Mask::ForRange(0x18000000,1,32);
 need(singleMask.Count()==1&&singleMask.Contains(FrameSurveyMetadata::DescriptorShard(0x18000000)),"single legal position omits every unreachable shard");
 for(const uint64_t count:std::array<uint64_t,5>{1,8,32,128,1024}){
  const auto mask=Mask::ForRange(0x18100000,count,32);need(mask.Count()<=std::min<uint64_t>(count,shards),"finite legal range uses only its possible descriptor shards");
  for(uint64_t slot=0;slot<count;++slot)need(mask.Contains(FrameSurveyMetadata::DescriptorShard(0x18100000+slot*32)),"every legal descriptor index is included");
 }
 need(Mask::ForRange(0x18200000,4096,1).Count()==shards,"remaining positions beyond cold1024 cap conservatively require all shards");
 const auto maximum=std::numeric_limits<uint64_t>::max();
 need(Mask::ForRange(maximum-31,2,32).Count()==shards&&Mask::ForRange(0x1000,maximum,32).Count()==shards,"address and extent overflow both require all shards");
 need(Mask::ForRange(0,1,32).Count()==shards&&Mask::ForRange(0x1000,0,32).Count()==shards&&Mask::ForRange(0x1000,1,0).Count()==shards,"invalid zero CPU/count/increment conservatively require all shards");
 need(FrameSurvey::HeapDescriptorShards(ph.cpu,32,ph.increment,D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER).Count()==0,"identity-only SAMPLER has no resource descriptor domain even at identical numeric CPU addresses");
 need(FrameSurvey::HeapDescriptorShards(ph.cpu,1,ph.increment,D3D12_DESCRIPTOR_HEAP_TYPE_RTV).Count()==1&&FrameSurvey::HeapDescriptorShards(ph.cpu,1,ph.increment,D3D12_DESCRIPTOR_HEAP_TYPE_DSV).Count()==shards,"RTV legal positions are bounded; unsupported domains stay conservative");
 FrameSurvey::NativeHeapNode fallbackNode;need(fallbackNode.legalDescriptorShards.Count()==shards,"unprepared native node fallback retains full coverage");
 struct MaskLockState{std::array<unsigned,FrameSurveyMetadata::DescriptorShards> calls{};const void* watched=nullptr;std::promise<void>* reached=nullptr;bool signaled=false;};
 const auto installMaskHook=[](MaskLockState& state){
  FrameSurveyMetadata::gDescriptorLockTestHook={&state,+[](void* raw,const void* mutex){auto& value=*static_cast<MaskLockState*>(raw);for(size_t shard=0;shard<FrameSurveyMetadata::DescriptorShards;++shard)if(mutex==&FrameSurvey::gViewMutexes[shard])++value.calls[shard];if(mutex==value.watched&&value.reached&&!value.signaled){value.signaled=true;value.reached->set_value();}}};
 };
 auto* maskHeap=reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(0x130000));auto maskBirth=born(maskHeap,301);
 auto maskPrepared=heap(maskHeap);maskPrepared.cpu=0x18300000;maskPrepared.gpu=0x19300000;maskPrepared.description.NumDescriptors=1;
 need(FrameSurvey::PublishHeapMetadata(maskPrepared,maskBirth),"prepared small heap publishes cold legal mask");
 auto maskOwner=FrameSurvey::gNativeHeaps.Find(maskHeap);need(maskOwner&&maskOwner->legalDescriptorShards.Count()==1,"prepared native heap bound is immutable and exact");
 FrameSurvey::View(t,{maskPrepared.cpu+1},&srv);need(!FrameSurvey::gViews.contains(maskPrepared.cpu+1)&&maskOwner->views->empty(),"misaligned metadata-only view never attaches an unreachable heap slot");
 size_t unreachable=0;while(maskOwner->legalDescriptorShards.Contains(unreachable))++unreachable;
 MaskLockState skippedState;FrameSurvey::RetirementEffects maskEffects;std::promise<void> skippedDone;auto skippedFuture=skippedDone.get_future();std::exception_ptr skippedError;std::jthread skippedWorker;bool skippedCompleted=false;
 {
  std::unique_lock unreachableLock(FrameSurvey::gViewMutexes[unreachable]);
  skippedWorker=std::jthread([&]{try{installMaskHook(skippedState);retire(maskBirth,maskEffects);FrameSurveyMetadata::gDescriptorLockTestHook={};}catch(...){skippedError=std::current_exception();}skippedDone.set_value();});
  skippedCompleted=skippedFuture.wait_for(std::chrono::seconds(1))==std::future_status::ready;
 }
 skippedWorker.join();if(skippedError)std::rethrow_exception(skippedError);
 need(skippedCompleted,"empty heap retirement completes while an unreachable descriptor shard is held");
 for(size_t shard=0;shard<shards;++shard)need(skippedState.calls[shard]==unsigned(maskOwner->legalDescriptorShards.Contains(shard)),"heap retirement visits exactly its legal immutable shard set");
 // Actual View pauses AFTER liveness/range validation while its legal slot is
 // held, BEFORE reverse insertion. Empty buckets must not bypass this lock.
 auto* pendingHeap=reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(0x140000));auto pendingBirth=born(pendingHeap,302);
 auto pendingPrepared=heap(pendingHeap);pendingPrepared.cpu=0x18400000;pendingPrepared.gpu=0x19400000;pendingPrepared.description.NumDescriptors=1;
 need(FrameSurvey::PublishHeapMetadata(pendingPrepared,pendingBirth),"pending-writer heap publication");auto pendingOwner=FrameSurvey::gNativeHeaps.Find(pendingHeap);
 const auto reachable=FrameSurveyMetadata::DescriptorShard(pendingPrepared.cpu);
 std::promise<void> publisherEntered,publisherResume,retireEntered,retireDone;auto publisherEnteredFuture=publisherEntered.get_future();auto resumeFuture=publisherResume.get_future().share();auto retireEnteredFuture=retireEntered.get_future(),retireDoneFuture=retireDone.get_future();
 struct PublishPause{std::promise<void>* entered;std::shared_future<void>* resume;};PublishPause pause{&publisherEntered,&resumeFuture};
 std::exception_ptr publisherError,retireError;FrameSurvey::RetirementEffects pendingEffects;MaskLockState pendingState;pendingState.watched=&FrameSurvey::gViewMutexes[reachable];pendingState.reached=&retireEntered;
 std::jthread publisher([&]{try{FrameSurvey::gNativeViewPublishTestHook={&pause,+[](void* raw,const void*){auto& value=*static_cast<PublishPause*>(raw);value.entered->set_value();value.resume->wait();}};FrameSurvey::View(t,{pendingPrepared.cpu},&srv);FrameSurvey::gNativeViewPublishTestHook={};}catch(...){publisherError=std::current_exception();}});
 const bool prechecked=publisherEnteredFuture.wait_for(std::chrono::seconds(1))==std::future_status::ready;
 std::jthread retiring;bool attempted=false,blocked=false,emptyWhilePaused=false;
 if(prechecked){
  emptyWhilePaused=pendingOwner->views->empty();
  retiring=std::jthread([&]{try{installMaskHook(pendingState);retire(pendingBirth,pendingEffects);FrameSurveyMetadata::gDescriptorLockTestHook={};}catch(...){retireError=std::current_exception();}retireDone.set_value();});
  attempted=retireEnteredFuture.wait_for(std::chrono::seconds(1))==std::future_status::ready;
  blocked=retireDoneFuture.wait_for(std::chrono::milliseconds(20))!=std::future_status::ready;
 }
 publisherResume.set_value();publisher.join();if(retiring.joinable())retiring.join();if(publisherError)std::rethrow_exception(publisherError);if(retireError)std::rethrow_exception(retireError);
 need(prechecked&&emptyWhilePaused&&attempted&&blocked,"final retirement waits the reachable EMPTY shard while an actual validated View owns it before insertion");
 need(!pendingBirth->Live()&&!FrameSurvey::gViews.contains(pendingPrepared.cpu)&&pendingOwner->views->empty()&&FrameSurvey::MetadataHealthy(),"paused late insertion is drained exactly and never resurrects a dead heap view");
 for(size_t shard=0;shard<shards;++shard)need(pendingState.calls[shard]==unsigned(pendingOwner->legalDescriptorShards.Contains(shard)),"pending writer preserves exact legal-only retirement coverage");
 // Resource descriptor addresses remain arbitrary: every shard must be drained.
 auto* maskResource=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x150000));auto maskResourceBirth=born(maskResource,303);auto maskResourcePrepared=pt;maskResourcePrepared.object=maskResource;
 need(FrameSurvey::PublishResourceMetadata(maskResourcePrepared,maskResourceBirth),"arbitrary resource owner metadata publication");FrameSurvey::View(maskResource,{ph.cpu+40*ph.increment},&srv);FrameSurvey::View(maskResource,{ph.cpu+42*ph.increment},&srv);
 MaskLockState resourceState;FrameSurvey::RetirementEffects resourceEffects;installMaskHook(resourceState);retire(maskResourceBirth,resourceEffects);FrameSurveyMetadata::gDescriptorLockTestHook={};
 for(size_t shard=0;shard<shards;++shard)need(resourceState.calls[shard]==1,"resource retirement retains ALL descriptor-shard coverage regardless of occupied buckets");
 need(!FrameSurvey::gViews.contains(ph.cpu+40*ph.increment)&&!FrameSurvey::gViews.contains(ph.cpu+42*ph.increment),"resource all-shard cleanup removes both exact owned views");
 }
"""

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

 // Differential contract against the established full field equality before
 // this optimization; opaque metadata owners are never COM references.
 const auto sourceView=FrameSurvey::gViews.at(aliasSource.ptr);const auto owner=FrameSurvey::gNativeHeaps.Find(h);
 auto expectedCopy=sourceView;expectedCopy.descriptorCpu=aliasDestination.ptr;expectedCopy.descriptorHeap=uint64_t(reinterpret_cast<uintptr_t>(h));expectedCopy.heapKnown=true;expectedCopy.heapOwner=owner;
 const auto established=[](const FrameSurvey::ViewInfo& a,const FrameSurvey::ViewInfo& b){
  return a.object==b.object&&a.resource==b.resource&&a.kind==b.kind&&a.format==b.format&&a.subresource==b.subresource&&a.snapshotSupported==b.snapshotSupported&&a.descriptorCpu==b.descriptorCpu&&a.descriptorGpu==b.descriptorGpu&&a.descriptorHeap==b.descriptorHeap&&a.rootVa==b.rootVa&&a.descriptorIndex==b.descriptorIndex&&a.rootIndex==b.rootIndex&&a.heapKnown==b.heapKnown&&a.constantBytes==b.constantBytes&&a.resourceOwner==b.resourceOwner&&a.heapOwner==b.heapOwner;
 };
 need(FrameSurvey::SameCopiedView(expectedCopy,sourceView,aliasDestination.ptr,owner)&&established(expectedCopy,expectedCopy),"exact no-op predicate matches established whole-view field contract");
 for(unsigned field=0;field<16;++field){auto different=expectedCopy;
  switch(field){case 0:different.object=t;break;case 1:++different.resource;break;case 2:++different.kind;break;case 3:++different.format;break;case 4:++different.subresource;break;case 5:different.snapshotSupported=!different.snapshotSupported;break;case 6:++different.descriptorCpu;break;case 7:++different.descriptorGpu;break;case 8:++different.descriptorHeap;break;case 9:++different.rootVa;break;case 10:++different.descriptorIndex;break;case 11:++different.rootIndex;break;case 12:different.heapKnown=false;break;case 13:++different.constantBytes;break;case 14:different.resourceOwner.reset();break;case 15:different.heapOwner.reset();break;}
  need(!established(different,expectedCopy)&&!FrameSurvey::SameCopiedView(different,sourceView,aliasDestination.ptr,owner),"every changed established metadata field prevents no-op copy elision");
 }
 FrameSurvey::View(aliasDestination,static_cast<const D3D12_CONSTANT_BUFFER_VIEW_DESC*>(nullptr));FrameSurvey::gCopyViewSnapshotsForTesting=0;
 FrameSurvey::NativeCopyDescriptors(ph.increment,1,&aliasDestination,nullptr,1,&aliasSource,nullptr,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 for(unsigned repeat=0;repeat<8;++repeat)FrameSurvey::NativeCopyDescriptors(ph.increment,1,&aliasDestination,nullptr,1,&aliasSource,nullptr,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 need(FrameSurvey::gCopyViewSnapshotsForTesting==1,"identical repeated native copies avoid temporary shared metadata pin traffic");
 auto changedCbv=cv;changedCbv.BufferLocation+=256;changedCbv.SizeInBytes+=256;FrameSurvey::View(aliasSource,&changedCbv);
 FrameSurvey::NativeCopyDescriptors(ph.increment,1,&aliasDestination,nullptr,1,&aliasSource,nullptr,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 need(FrameSurvey::gViews.at(aliasDestination.ptr).rootVa==changedCbv.BufferLocation&&FrameSurvey::gViews.at(aliasDestination.ptr).constantBytes==changedCbv.SizeInBytes&&FrameSurvey::gCopyViewSnapshotsForTesting==2,"changed actual CBV declaration replaces destination rather than incorrectly eliding copy");
 FrameSurvey::View(aliasSource,&cv);FrameSurvey::NativeCopyDescriptors(ph.increment,1,&aliasDestination,nullptr,1,&aliasSource,nullptr,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 // Finite prepared root allows the original finite proof API too; the actual
 // slot/buffer resolver must still wait for snapshot EX during this control.
 auto* finiteRoot=reinterpret_cast<ID3D12RootSignature*>(uintptr_t(0xb0000));auto finiteBirth=born(finiteRoot,209);
 auto finiteLayout=std::make_shared<FrameSurvey::RootLayout>();finiteLayout->complete=true;finiteLayout->hash="synthetic_finite_contract";finiteLayout->computeVisibleTables={1,2};finiteLayout->computeTables={1,2};
 finiteLayout->tables[1]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,0,1,0,0}};finiteLayout->tables[2]={{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,0,1,6,0}};
 need(FrameSurvey::PublishRootMetadata({finiteRoot,finiteLayout},finiteBirth),"finite POD proof root published without native getter");
 auto finiteBindings=bindings;finiteBindings.root=finiteRoot;finiteBindings.rootBirth=finiteBirth;
 need(FrameSurvey::SeedComputeBindings(c,finiteBindings),"finite current proof bindings seeded");
 std::promise<void> podDone,slotEntered,slotDone;auto podFuture=podDone.get_future(),slotStarted=slotEntered.get_future(),slotFuture=slotDone.get_future();std::atomic<bool> podPassed{false},slotPassed{false};std::jthread podReader,slotReader;
 {
  FrameSurvey::NativeSnapshotShared longCopy;
  podReader=std::jthread([&]{NrdBridgeLifetime::ScopedBorrow borrow;FrameSurvey::BoundConstantBinding explicitProof,mirrorProof;podPassed=borrow.Acquired()&&FrameSurvey::ComputeTableBindingMatches(c,1,D3D12_DESCRIPTOR_RANGE_TYPE_SRV,0,0,0)&&FrameSurvey::ResolveComputeConstantBinding(finiteBindings,6,0,explicitProof)&&FrameSurvey::ResolveComputeConstantBinding(c,6,0,mirrorProof)&&explicitProof.descriptor.ptr==mirrorProof.descriptor.ptr;podDone.set_value();});
  slotReader=std::jthread([&]{NrdBridgeLifetime::ScopedBorrow borrow;const bool acquired=borrow.Acquired();slotEntered.set_value();FrameSurvey::BoundConstantBuffer value;slotPassed=acquired&&FrameSurvey::ResolveComputeConstantBuffer(c,6,0,1216,value);slotDone.set_value();});
  slotStarted.wait();need(podFuture.wait_for(std::chrono::seconds(2))==std::future_status::ready,"three actual POD-only proof APIs finish while long-copy snapshot SH is held");
  need(slotFuture.wait_for(std::chrono::milliseconds(20))==std::future_status::timeout,"actual resource/slot CBV resolver still drains snapshot EX");
 }
 podReader.join();slotReader.join();need(podPassed&&slotPassed,"POD proofs and deferred complete slot proof return exact current native binding");
 need(FrameSurvey::SeedComputeBindings(c,bindings),"original unbounded bindings restored after finite proof control");FrameSurvey::RetirementEffects finiteEffects;retire(finiteBirth,finiteEffects);FrameSurvey::NotifyRelease(finiteEffects);

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
replace_once(' // Failed metadata mutation under a guard is latched there and handled outside it.', MASK_EXTRA+EXTRA+'\n // Failed metadata mutation under a guard is latched there and handled outside it.')
replace_once('"source","actual_FrameSurvey_methods_with_actual_Birth_registry_metadata_emulation"',
             '"source","actual_native_active_FrameSurvey_methods_with_actual_Birth_dispatcher_metadata_emulation"')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--descriptor-shards', type=int, choices=(32,128,256), default=256)
    args = parser.parse_args()
    legacy.run(DRIVER, f'native-metadata-heap-mask{args.descriptor_shards}-cpu.json', '#include <future>\n#define FSRD_NRD_BRIDGE_TEST\n#define FSRD_NRD_BRIDGE_TEST_HEAP_MASK\n', descriptor_shards=args.descriptor_shards)
