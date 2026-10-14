"""CPU regression for metadata birth tickets; no D3D device, shaders or GPU work.

Run via run_task_test.py --cpu after the lead releases the compiler slot.
The source includes the production header, not a copied implementation.
"""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

CPP = r'''
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <atomic>
std::atomic<unsigned> qpcCalls{0};
BOOL WINAPI BirthFixtureQpc(LARGE_INTEGER* value)noexcept{++qpcCalls;return ::QueryPerformanceCounter(value);}
#define QueryPerformanceCounter BirthFixtureQpc
#include "misc/NrdBridgeBirth_Dx12.h"
#undef QueryPerformanceCounter
#include <barrier>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <future>
#include <iostream>
#include <shared_mutex>
#include <stdexcept>
#include <thread>
#include <vector>
namespace B=NrdBridgeBirth;
std::atomic<unsigned> allocations{0},checks{0},nativeInside{0},ownedInside{0},ownedDestroyed{0};
void* operator new(std::size_t size){allocations.fetch_add(1);if(auto* p=std::malloc(size))return p;throw std::bad_alloc();}
void operator delete(void* p)noexcept{std::free(p);}
void operator delete(void* p,std::size_t)noexcept{std::free(p);}
void need(bool value,const char* text){if(!value)throw std::runtime_error(text);checks.fetch_add(1);}
void* address(uintptr_t value){return reinterpret_cast<void*>(value);}
struct Native{
 std::atomic<int> refs{1},adds{0},releases{0},destroyed{0};
 int add(){if(B::InMetadataScope())++nativeInside;++adds;return ++refs;}
 int release(){if(B::InMetadataScope())++nativeInside;++releases;const int count=--refs;if(!count)++destroyed;return count;}
};
struct Owned{
 Native* object=nullptr;
 explicit Owned(Native* native=nullptr):object(native){}
 ~Owned(){if(B::InMetadataScope())++ownedInside;if(object)object->release();++ownedDestroyed;}
};
struct Effects{
 std::unordered_map<void*,uint64_t> metadata;
 unsigned detached=0,published=0;
 bool recursiveRead=false;
 B::Registry* registry=nullptr;
 std::shared_ptr<Owned> currentOwner,detachedOwner;
};
bool detach(void* state,const B::Token& old)noexcept{
 auto& effects=*static_cast<Effects*>(state);
 if(!B::InMetadataScope()||!B::InMetadataAction()||old->Live())return false;
 if(effects.recursiveRead){
  if(effects.registry->Capture(old->Address())!=old)return false;
  B::CurrentGuard nested(old);if(nested.MatchesCurrent()||nested.Retire(detach,state))return false;
 }
 const auto found=effects.metadata.find(old->Address());
 if(found!=effects.metadata.end()&&found->second==old->Sequence())effects.metadata.erase(found);
 if(effects.currentOwner){if(effects.detachedOwner)return false;effects.detachedOwner=std::move(effects.currentOwner);}
 ++effects.detached;return true;
}
bool publish(void* state,const B::Token& fresh)noexcept{
 auto& effects=*static_cast<Effects*>(state);
 if(!B::InMetadataScope()||!B::InMetadataAction()||!fresh->Live())return false;
 try{effects.metadata[fresh->Address()]=fresh->Sequence();++effects.published;return true;}catch(...){return false;}
}
void basics(){
 const auto first=B::Detail::constructedRegistries.load(),before=allocations.load();
 need(!B::Capture(address(1),false),"startup OFF capture is empty");
 need(!B::PublishFresh(address(1),1,detach,publish,nullptr,false),"startup OFF publish is empty");
 need(B::Detail::constructedRegistries==first&&allocations==before,"startup OFF never constructs registry or allocates");
 B::Registry registry;Effects effects;effects.registry=&registry;effects.recursiveRead=true;
 const auto missBefore=allocations.load();need(!registry.Capture(address(1)),"unknown capture is empty");
 need(allocations==missBefore&&registry.LiveCountForTesting()==0,"unknown capture never allocates an entry");
 auto token=registry.PublishFresh(address(0x1000),1,detach,publish,&effects);
 need(token&&token->Live()&&token->InstanceStamp()==1&&effects.detached==0,"first authoritative birth publishes once");
 const auto captureBefore=allocations.load();
 {B::CurrentGuard guard(token);need(guard.MatchesCurrent(),"current ticket accepted");need(registry.Capture(token->Address())==token,"same metadata shard reentry is safe");}
 need(allocations==captureBefore,"warm capture and current guard have no heap allocation");
 B::Token held=token;need(held==token&&registry.ObserveExisting(held),"strong metadata-only token remains current");
 auto interned=registry.ObserveInstance(token->Address(),1,detach,publish,&effects);
 need(interned==token&&interned->Sequence()==token->Sequence()&&effects.detached==0,"interned root and repeated PSO observation preserve live instance");
 {B::CurrentGuard guard(token);need(guard.Retire(detach,&effects),"final current birth retires");need(!guard.Retire(detach,&effects),"same-guard retirement is idempotent");}
 need(!held->Live()&&effects.detached==1&&registry.LiveCountForTesting()==0,"retired token survives only as metadata and map is bounded");
 need(!registry.ObserveExisting(held),"stale observation never revives old birth");
 {B::CurrentGuard late(held);need(!late.MatchesCurrent()&&!late.Retire(detach,&effects),"post-final duplicate cannot notify twice");}
 need(registry.Healthy()&&effects.detached==1,"recursive metadata reads preserve health and exact callback count");
}
void reuseAndNotifications(){
 B::Registry registry;Effects effects;effects.registry=&registry;void* object=address(0x2000);
 auto old=registry.PublishFresh(object,10,detach,publish,&effects);
 Native ownedNative;effects.currentOwner=std::make_shared<Owned>(&ownedNative);const auto count=ownedDestroyed.load();
 auto fresh=registry.PublishFresh(object,11,detach,publish,&effects);
 need(fresh&&fresh!=old&&fresh->Sequence()!=old->Sequence()&&!old->Live(),"physical address reuse has a distinct stamped birth");
 need(effects.detached==1&&effects.metadata[object]==fresh->Sequence(),"old POD metadata detaches before fresh publication");
 need(effects.detachedOwner&&ownedDestroyed==count&&ownedInside==0,"detached owned state is pinned without destruction under shard");
 {B::CurrentGuard post(old);need(!post.Retire(detach,&effects),"late old result0 skips new metadata");}
 need(effects.metadata[object]==fresh->Sequence()&&effects.detached==1,"late retirement preserves fresh role/list owner");
 // Notifications are OUTSIDE helper scope and use the old sequence. A coordinator
 // may cancel old cache epochs, but cannot erase a role/list carrying the new one.
 need(!B::InMetadataScope(),"notification delivery is outside metadata lock");
 if(effects.metadata[object]==old->Sequence())effects.metadata.erase(object);
 need(effects.metadata[object]==fresh->Sequence(),"delayed birth-aware notification preserves new PSO role/list");
 effects.detachedOwner.reset();need(ownedDestroyed==count+1&&ownedInside==0,"owned garbage dies only after metadata scope");
 need(ownedNative.refs==0&&ownedNative.releases==1&&ownedNative.destroyed==1,"detached owned COM destruction performs native release only outside shard");
 {B::CurrentGuard guard(fresh);need(guard.Retire(detach,&effects),"new instance later retires normally");}
 need(registry.LiveCountForTesting()==0,"reuse does not leak retired catalog entries");
}
void probeAndAliases(){
 B::Registry registry;Effects a,b;a.registry=b.registry=&registry;Native object;object.refs=2;
 const auto first=registry.ObserveInstance(address(0x3000),30,detach,publish,&a);
 // A known typed alias uses its own captured ticket. The existing lease identity
 // map supplies the alias batch; the helper performs no QueryInterface/AddRef.
 const auto alias=registry.ObserveInstance(address(0x3008),30,detach,publish,&b);
 const std::array<B::Token,2> tickets{first,alias};
 const auto warm=allocations.load();
 {B::ScopedRelease pending(first);need(first->ReleasesInFlight()==1&&alias->ReleasesInFlight()==1&&!B::CacheAdmissible(alias),"proven native aliases share pending physical release counter");
  object.add();const auto probe1=object.release();need(probe1==2,"nonfinal caller probe count exact");
  need(object.release()==1&&first->Live()&&alias->Live()&&!a.detached&&!b.detached,"nonfinal release preserves all metadata");}
 need(allocations==warm&&first->ReleasesInFlight()==0&&B::CacheAdmissible(alias),"warm native release scope allocates no metadata and restores alias admission");
 {B::ScopedRelease pending(alias);object.add();const auto probe2=object.release();need(probe2==1,"single final caller pre-probe is observed");
  for(size_t i=0;i<tickets.size();++i){B::CurrentGuard guard(tickets[i]);need(guard.Retire(detach,i?static_cast<void*>(&b):static_cast<void*>(&a)),"known alias old ticket retires");}
  need(object.release()==0&&object.destroyed==1,"native caller final count and destruction are exact");
  for(size_t i=0;i<tickets.size();++i)need(!registry.RetireCurrentInstance(tickets[i],detach,i?static_cast<void*>(&b):static_cast<void*>(&a)),"post0 known alias batch is idempotent");}
 need(object.adds==2&&object.releases==4&&nativeInside==0,"only existing temporary probes call native COM outside metadata guards");
 need(!first->Live()&&!alias->Live()&&registry.LiveCountForTesting()==0,"typed aliases leave no stale live metadata");
}
void missedPreFinal(){
 B::Registry registry;Effects effects;effects.registry=&registry;Native object;object.refs=2;
 auto token=registry.PublishFresh(address(0x4000),40,detach,publish,&effects);
 std::shared_mutex gate;std::barrier afterAdds(2),afterProbes(2);
 std::promise<void> atZero,finishZero;auto zero=atZero.get_future();auto finish=finishZero.get_future().share();
 std::atomic<int> probes[2]{},results[2]{};
 auto release=[&](int index){
  std::shared_lock physical(gate);auto captured=registry.Capture(token->Address());B::ScopedRelease pending(captured);
  object.add();afterAdds.arrive_and_wait();probes[index]=object.release();afterProbes.arrive_and_wait();
  results[index]=object.release();if(results[index]==0){atZero.set_value();finish.wait();registry.RetireCurrentInstance(captured,detach,&effects);}
 };
 std::jthread one(release,0),two(release,1);need(zero.wait_for(std::chrono::seconds(2))==std::future_status::ready,"parallel same-object releases reached actual0");
 auto borrowed=std::async(std::launch::async,[&]{std::unique_lock physical(gate);return !registry.Capture(token->Address())&&!token->Live();});
 need(borrowed.wait_for(std::chrono::milliseconds(30))==std::future_status::timeout,"borrow stays excluded over physical0/post-cleanup gap");
 need(probes[0]>1&&probes[1]>1&&effects.detached==0,"both pre-probes miss final under legitimate concurrent callers");
 finishZero.set_value();one.join();two.join();need(borrowed.get(),"resumed borrow observes completed old-generation retirement");
 need(effects.detached==1&&object.refs==0&&object.destroyed==1&&object.adds==2&&object.releases==4,"post0 closes missed pre-final with one retirement and exact COM sequence");
 need(token->ReleasesInFlight()==0,"both parallel release scopes end after final physical cleanup");
}
void internedDuringFinal(){
 B::Registry registry;Effects effects;effects.registry=&registry;void* root=address(0x4100);Native object;
 auto old=registry.PublishFresh(root,41,detach,publish,&effects);B::Token reobserved;
 {B::ScopedRelease outer(old);object.add();need(object.release()==1,"old final pre-probe exact");
  {B::CurrentGuard guard(old);need(guard.Retire(detach,&effects),"old logical sequence retires before final native call");}
  // A legal native interned Create returns the same object with one NEW caller ref.
  need(object.add()==2,"interned native create retains its own caller reference");
  reobserved=registry.ObserveInstance(root,41,detach,publish,&effects);
  need(reobserved&&reobserved!=old&&reobserved->Sequence()!=old->Sequence()&&reobserved->InstanceStamp()==old->InstanceStamp(),"same physical stamp after pre-retire creates a fresh logical observation");
  need(reobserved->ReleasesInFlight()==1&&!B::CacheAdmissible(reobserved),"reobserved sequence inherits original physical release in flight");
  {B::ScopedRelease nested(reobserved);need(old->ReleasesInFlight()==2,"both logical sequences count the same physical pending releases");
   object.add();need(object.release()==2&&object.release()==1,"intervening interned caller releases nonfinally");}
  need(reobserved->ReleasesInFlight()==1&&object.release()==0,"original caller finally destroys shared physical instance");
  need(registry.RetireCurrentInstance(old,detach,&effects),"actual0 old ticket retires CURRENT same-stamp logical sequence");
  need(!reobserved->Live()&&effects.detached==2&&effects.metadata.empty(),"physical final cleanup removes reobserved root/role/list metadata");
  need(!registry.RetireCurrentInstance(old,detach,&effects),"repeat physical final notification is idempotent");}
 need(old->ReleasesInFlight()==0&&reobserved->ReleasesInFlight()==0&&object.adds==3&&object.releases==4&&object.destroyed==1,"interned counterexample keeps exact native create/probe/release sequence");
 // A different native instance may reuse the address before old post0 cleanup.
 auto reusedOld=registry.PublishFresh(root,42,detach,publish,&effects);Native oldNative,newNative;
 {B::ScopedRelease pending(reusedOld);oldNative.add();need(oldNative.release()==1,"recycled old pre-probe exact");
  {B::CurrentGuard guard(reusedOld);need(guard.Retire(detach,&effects),"recycled old logical metadata pre-retires");}
  need(oldNative.release()==0,"old physical allocation destroyed before new native create");
  auto recycled=registry.PublishFresh(root,43,detach,publish,&effects);
  need(recycled&&recycled->InstanceStamp()!=reusedOld->InstanceStamp()&&recycled->ReleasesInFlight()==0&&B::CacheAdmissible(recycled),"verified new GUID instance has independent metadata and release counter");
  need(!registry.RetireCurrentInstance(reusedOld,detach,&effects)&&recycled->Live()&&effects.metadata[root]==recycled->Sequence(),"old post0 physically-stamped cleanup preserves genuinely recycled allocation");
  {B::CurrentGuard guard(recycled);need(guard.Retire(detach,&effects),"recycled native instance cleans its own metadata");}
  need(newNative.release()==0,"recycled native owner eventually releases its own caller ref");}
 need(registry.LiveCountForTesting()==0&&registry.Healthy(),"interned and recycled regressions leave no live tombstones");
}
void firstStampElection(){
 B::Registry registry;Effects effects;effects.registry=&registry;void* object=address(0x4200);
 auto candidate=registry.ComparePublish(object,{},420,detach,publish,&effects);
 need(candidate&&candidate->Initializing()&&!candidate->Ready()&&!B::CacheAdmissible(candidate),"first native stamp election publishes an inadmissible initializing candidate");
 {B::CurrentGuard guard(candidate);need(guard.MatchesCurrent()&&!guard.AdmitsBorrow(),"initializing birth cannot admit any borrowed COM use");}
 need(!registry.ComparePublish(object,{},421,detach,publish,&effects)&&registry.Healthy()&&registry.Capture(object)==candidate,"stale zero/native CAS loser cannot replace another candidate");
 need(!registry.ObserveInitializing(candidate,false)&&registry.ObserveInitializing(candidate,true),"zero native read reuse requires initializing flag captured BEFORE that read");
 const bool capturedInitializing=candidate->Initializing();
 need(registry.Finalize(candidate,true)&&candidate->Ready()&&B::CacheAdmissible(candidate),"successful native stamp write completes admission without waiting");
 need(registry.ObserveInitializing(candidate,capturedInitializing),"stale zero read may reuse still-current candidate after winner finalized");
 need(registry.ObserveInstance(object,420,detach,publish,&effects)==candidate,"nonzero interned stamp preserves elected birth after completion");
 {B::CurrentGuard guard(candidate);need(guard.Retire(detach,&effects),"completed candidate retires normally");}
 auto replacement=registry.ComparePublish(object,{},422,detach,publish,&effects);
 need(replacement&&replacement!=candidate&&!registry.ObserveInitializing(candidate,true),"stale initializing snapshot cannot alias a new current native election");
 {B::CurrentGuard guard(replacement);need(guard.Retire(detach,&effects),"Release may retire an initializing metadata candidate");}
 need(!registry.Finalize(replacement,true)&&!replacement->Live(),"late successful stamp completion cannot revive retired candidate");
 B::Registry failed;Effects failure;
 auto bad=failed.ComparePublish(address(0x4300),{},430,detach,publish,&failure);
 need(!failed.Finalize(bad,false)&&bad->Failed()&&!bad->Initializing()&&!failed.Healthy()&&!B::CacheAdmissible(bad),"native stamp write failure finalizes pending state and latches metadata failure");
 need(!failed.ObserveInitializing(bad,true)&&!failed.Finalize(bad,true),"failed initialization cannot be admitted or later healed silently");
 {B::CurrentGuard guard(bad);guard.Retire(detach,&failure);}
 need(!bad->Live()&&failed.LiveCountForTesting()==0&&failure.detached==1,"failed metadata still performs one required POD detachment");
 // Two creators read zero before either election, then compete without waiting.
 B::Registry concurrent;Effects contenders;std::barrier zeros(2);std::array<B::Token,2> winners;
 auto elect=[&](size_t index){auto expected=concurrent.Capture(address(0x4400));zeros.arrive_and_wait();winners[index]=concurrent.ComparePublish(address(0x4400),expected,440+index,detach,publish,&contenders);};
 std::jthread a(elect,0),b(elect,1);a.join();b.join();
 need(bool(winners[0])!=bool(winners[1])&&contenders.published==1&&concurrent.Healthy(),"concurrent zero readers elect exactly one candidate with no unbounded wait");
 auto winner=winners[0]?winners[0]:winners[1];
 need(concurrent.Finalize(winner,true)&&concurrent.Capture(winner->Address())==winner,"first-stamp winner completes unique current birth");
 {B::CurrentGuard guard(winner);need(guard.Retire(detach,&contenders),"concurrent winner metadata retires exactly once");}
}
void crossNestedNonfinal(){
 B::Registry registry;Effects a,b;auto ta=registry.PublishFresh(address(0x4500),450,detach,publish,&a);
 auto tb=registry.PublishFresh(address(0x4600),460,detach,publish,&b);Native na,nb;na.refs=nb.refs=3;
 std::barrier nested(2);
 auto run=[&](Native& outer,const B::Token& outerTicket,Native& child,const B::Token& childTicket){
  B::ScopedRelease pending(outerTicket);outer.add();need(outer.release()>1,"cross-nested outer pre-probe is nonfinal");nested.arrive_and_wait();
  {B::ScopedRelease childPending(childTicket);child.add();need(child.release()>1&&child.release()>0,"cross-object nested native release is also nonfinal");}
  need(outer.release()>0,"cross-nested outer caller release remains nonfinal");
 };
 auto one=std::async(std::launch::async,[&]{run(na,ta,nb,tb);});
 auto two=std::async(std::launch::async,[&]{run(nb,tb,na,ta);});
 need(one.wait_for(std::chrono::seconds(2))==std::future_status::ready&&two.wait_for(std::chrono::seconds(2))==std::future_status::ready,"native A-to-B/B-to-A release nests have no metadata lock cycle");one.get();two.get();
 need(na.refs==1&&nb.refs==1&&na.adds==2&&nb.adds==2&&na.releases==4&&nb.releases==4&&!a.detached&&!b.detached&&B::CacheAdmissible(ta)&&B::CacheAdmissible(tb),"nonfinal cross-nesting preserves exact COM calls and live metadata");
 {B::ScopedRelease pending(ta);need(na.release()==0&&registry.RetireCurrentInstance(ta,detach,&a),"A final owned caller cleans after nested nonfinal release");}
 {B::ScopedRelease pending(tb);need(nb.release()==0&&registry.RetireCurrentInstance(tb,detach,&b),"B final owned caller cleans after nested nonfinal release");}
 const auto before=allocations.load();{B::ScopedRelease ownedOrUnknown({});need(!ownedOrUnknown.Ticket(),"owned/internal/unknown route does not synthesize title metadata or native probe");}
 need(allocations==before&&registry.LiveCountForTesting()==0&&nativeInside==0,"owned nested path has no metadata allocation or native call under a registry lock");
}
struct ParallelState{std::promise<void> entered;std::shared_future<void> finish;};
bool waitDetach(void* state,const B::Token& old)noexcept{
 auto& item=*static_cast<ParallelState*>(state);if(old->Live()||!B::InMetadataScope())return false;
 item.entered.set_value();item.finish.wait();return true;
}
void independentShards(){
 B::Registry registry;Effects a,b;void* x=address(0x5000);uintptr_t candidate=0x5100;
 while(B::Registry::ShardIndex(address(candidate))==B::Registry::ShardIndex(x))candidate+=16;
 auto first=registry.PublishFresh(x,50,detach,publish,&a),second=registry.PublishFresh(address(candidate),51,detach,publish,&b);
 std::promise<void> finish;ParallelState item;item.finish=finish.get_future().share();auto entered=item.entered.get_future();
 auto blocked=std::async(std::launch::async,[&]{B::CurrentGuard guard(first);return guard.Retire(waitDetach,&item);});
 need(entered.wait_for(std::chrono::seconds(2))==std::future_status::ready,"first shard entered POD detach callback");
 auto other=std::async(std::launch::async,[&]{B::CurrentGuard guard(second);return guard.Retire(detach,&b);});
 need(other.wait_for(std::chrono::seconds(2))==std::future_status::ready&&other.get(),"independent metadata retirement is not globally serialized");
 finish.set_value();need(blocked.get()&&registry.Healthy(),"blocked shard finishes without cross-shard cycle");
}
void stagedProvenAliases(){
 B::Registry registry;Effects effects;effects.registry=&registry;void* a=address(0xc000);void* b=address(0xc008);
 auto first=registry.ObserveInstance(a,12000,detach,publish,&effects);B::AliasSnapshot snapshot;
 const auto warm=allocations.load();
 need(registry.CaptureProvenAliasesForFinalZero(first,snapshot)&&snapshot.complete&&snapshot.count==1&&snapshot.tokens[0]==first,"normal native instance enumerates exactly one proven alias");
 need(allocations==warm&&!B::InMetadataScope(),"bounded alias snapshot is allocation-free and ends every index/registry guard before caller use");
 auto alias=registry.ObserveInstance(b,12000,detach,publish,&effects);
 need(registry.CaptureProvenAliasesForFinalZero(first,snapshot)&&snapshot.count==2,"same native GUID records both proven address aliases");
 {B::CurrentGuard current(first);need(current.Retire(detach,&effects),"old logical alias pre-retires exactly");}
 auto reobserved=registry.ObserveInstance(a,12000,detach,publish,&effects);
 need(reobserved&&reobserved!=first&&registry.CaptureProvenAliasesForFinalZero(first,snapshot)&&snapshot.count==2,"old native ticket snapshots new current same-GUID logical alias");
 bool sawNew=false,sawOld=false;for(size_t i=0;i<snapshot.count;++i){sawNew|=snapshot.tokens[i]==reobserved;sawOld|=snapshot.tokens[i]==first;}
 need(sawNew&&!sawOld,"proven-alias index replaces stale logical token without historical duplicates");
 auto recycled=registry.ObserveInstance(b,12001,detach,publish,&effects);
 need(recycled&&recycled->Live()&&!alias->Live(),"one old captured alias address can carry a genuinely different native GUID");
 need(registry.RetireProvenAliases(snapshot,detach,&effects)==1,"staged old-physical final cleanup retires matching current alias only");
 need(!reobserved->Live()&&recycled->Live()&&effects.metadata.size()==1&&effects.metadata[b]==recycled->Sequence(),"old GUID snapshot preserves recycled same address metadata and descriptor role");
 need(registry.RetireProvenAliases(snapshot,detach,&effects)==0,"repeat proven-alias staged retirement is idempotent");
 need(registry.CaptureProvenAliasesForFinalZero(first,snapshot)&&snapshot.count==0&&snapshot.complete,"retired physical metadata retains no live alias tombstone");
 snapshot.Reset();{B::CurrentGuard current(recycled);need(current.Retire(detach,&effects),"recycled alias owner retires its own new GUID");}
 need(registry.LiveCountForTesting()==0&&registry.Healthy()&&effects.detached==4,"alias reuse and reobserve callback counts remain exact");
}
void aliasCapAndPruning(){
 B::Registry rotating;Effects effects;auto anchor=rotating.ObserveInstance(address(0xd000),13000,detach,publish,&effects);B::AliasSnapshot snapshot;
 for(uint64_t index=0;index!=192;++index){
  auto alias=rotating.ObserveInstance(address(0xd100+index*256),13000,detach,publish,&effects);
  need(alias&&rotating.CaptureProvenAliasesForFinalZero(anchor,snapshot)&&snapshot.count==2,"same live GUID admits rotating native aliases without historical weak-slot growth");
  {B::CurrentGuard current(alias);need(current.Retire(detach,&effects),"rotating logical alias removes exact weak slot");}
 }
 need(rotating.CaptureProvenAliasesForFinalZero(anchor,snapshot)&&snapshot.count==1&&rotating.WeakPhysicalCountForTesting()==1,"cold alias pruning remains bounded to current proven aliases");
 {B::CurrentGuard current(anchor);need(current.Retire(detach,&effects),"native anchor metadata eventually retires");}
 B::Registry capped;Effects capEffects;std::array<B::Token,B::AliasSnapshot::Capacity> tokens;
 for(size_t index=0;index!=tokens.size();++index){tokens[index]=capped.ObserveInstance(address(0xe000+index*256),14000,detach,publish,&capEffects);need(bool(tokens[index]),"every supported proven alias publishes");}
 need(capped.CaptureProvenAliasesForFinalZero(tokens[0],snapshot)&&snapshot.count==B::AliasSnapshot::Capacity&&snapshot.complete,"bounded final snapshot covers all 64 supported proven aliases");
 auto overflow=capped.ObserveInstance(address(0x100000),14000,detach,publish,&capEffects);
 need(!overflow&&!capped.Healthy()&&!B::CacheAdmissible(tokens[0])&&capped.LiveCountForTesting()==B::AliasSnapshot::Capacity,"alias-cap overflow fails closed without publishing or deleting an existing alias");
 need(capped.CaptureProvenAliasesForFinalZero(tokens[0],snapshot)&&snapshot.complete&&snapshot.count==64,"failed health still captures every existing alias for required cleanup");
 capped.RetireProvenAliases(snapshot,detach,&capEffects);
 for(const auto& token:tokens)need(!token->Live(),"fail-closed metadata still attempts each bounded alias final retirement");
 need(capped.LiveCountForTesting()==0&&capEffects.detached==64&&capEffects.metadata.empty(),"alias overflow leaves no live metadata after staged cleanup");
}
void concurrentAliasFinalReseed(){
 B::Registry registry;Effects effects;Native object;object.refs=2;
 auto old=registry.ObserveInstance(address(0xf000),15000,detach,publish,&effects);
 std::barrier captured(3),reseeded(3),adds(2),probesDone(2);std::atomic<int> probes[2]{},results[2]{};std::atomic<unsigned> finalAliases{0},retired{0};
 auto release=[&](size_t index){
  auto ticket=registry.Capture(old->Address());B::ScopedRelease pending(ticket);captured.arrive_and_wait();reseeded.arrive_and_wait();
  object.add();adds.arrive_and_wait();probes[index]=object.release();probesDone.arrive_and_wait();results[index]=object.release();
  if(!results[index]){B::AliasSnapshot aliases;need(registry.CaptureProvenAliasesForFinalZero(ticket,aliases)&&aliases.complete,"actual0 snapshots physical aliases using pre-native strong metadata ticket");
   finalAliases=unsigned(aliases.count);retired=unsigned(registry.RetireProvenAliases(aliases,detach,&effects));}
 };
 std::jthread a(release,0),b(release,1);captured.arrive_and_wait();
 need(old->ReleasesInFlight()==2,"both native callers captured and counted before logical reseed");
 // Exercise logical-generation ABA while both title callers still own valid
 // native refs. Earlier exact logical retirement is independent of physical0.
 {B::CurrentGuard current(old);need(current.Retire(detach,&effects),"earlier logical token detaches while native caller refs remain valid");}
 auto fresh=registry.ObserveInstance(old->Address(),15000,detach,publish,&effects);
 auto alias=registry.ObserveInstance(address(0xf008),15000,detach,publish,&effects);
 need(fresh&&fresh!=old&&fresh->ReleasesInFlight()==2&&alias->ReleasesInFlight()==2&&!B::CacheAdmissible(fresh),"new same-GUID sequence and alias inherit both pending native releases");
 reseeded.arrive_and_wait();a.join();b.join();
 need(probes[0]>1&&probes[1]>1&&((results[0]==0&&results[1]==1)||(results[0]==1&&results[1]==0)),"parallel native probes both miss pre-final yet exactly one actual caller returns0");
 need(finalAliases==2&&retired==2&&!fresh->Live()&&!alias->Live()&&effects.detached==3&&effects.metadata.empty(),"post0 old ticket retires ALL current same-GUID aliases/new logical generation");
 need(object.adds==2&&object.releases==4&&object.destroyed==1&&old->ReleasesInFlight()==0&&registry.LiveCountForTesting()==0,"alias final-reseed proof preserves exact native caller/probe counts and scope balance");
}
void aliasIndexNotHeldByCallback(){
 B::Registry registry;Effects effects;void* a=address(0x110000);uintptr_t value=0x110100;
 while(B::Registry::ShardIndex(a)==B::Registry::ShardIndex(address(value)))value+=16;
 auto token=registry.ObserveInstance(a,16000,detach,publish,&effects);
 std::promise<void> finish;ParallelState item;item.finish=finish.get_future().share();auto entered=item.entered.get_future();
 auto old=std::async(std::launch::async,[&]{B::CurrentGuard current(token);return current.Retire(waitDetach,&item);});
 need(entered.wait_for(std::chrono::seconds(2))==std::future_status::ready,"exact retirement entered POD callback after removing weak alias slot");
 auto creation=std::async(std::launch::async,[&]{return registry.ObserveInstance(address(value),16000,detach,publish,&effects);});
 need(creation.wait_for(std::chrono::seconds(2))==std::future_status::ready,"same-physical GUID cold alias publication proceeds while another alias POD callback is paused");
 auto fresh=creation.get();finish.set_value();need(old.get()&&fresh&&registry.Healthy(),"metadata callback never holds physical alias index lock");
 // waitDetach deliberately owns no component POD map; finish its model cleanup.
 effects.metadata.erase(token->Address());B::AliasSnapshot aliases;
 need(registry.CaptureProvenAliasesForFinalZero(token,aliases)&&aliases.count==1&&aliases.tokens[0]==fresh,"staged snapshot finds current alias after independent publication");
 need(registry.RetireProvenAliases(aliases,detach,&effects)==1,"staged callback executes after all alias index locks ended");
}
void recordingPhysicalMarker(){
 const auto offAlloc=allocations.load(),offRegistries=B::Detail::constructedRegistries.load();
 need(!B::MarkRecordingMayExist({},false)&&!B::MarkRecordingMayExist({}),"startup OFF/unknown marker never synthesizes a recording-capable birth");
 need(allocations==offAlloc&&B::Detail::constructedRegistries==offRegistries,"startup OFF/unknown marker has no global registry allocation");
 B::Registry registry;Effects effects;auto first=registry.ObserveInstance(address(0x130000),18000,detach,publish,&effects);
 B::AliasSnapshot aliases;need(first&&!first->RecordingMayExist()&&registry.CaptureProvenAliasesForFinalZero(first,aliases)&&aliases.count==1,"normal one-alias resource/heap/PSO starts with no possible title-list recording");
 const auto warm=allocations.load();first->MarkRecordingMayExist(false);
 need(!first->RecordingMayExist()&&allocations==warm,"disabled marker leaves known physical metadata unchanged without allocation");
 need(B::MarkRecordingMayExist(first)&&first->RecordingMayExist()&&allocations==warm,"pre-Track title-list marker is metadata-only atomic with no lock/allocation");
 const auto failedTrack=[]()noexcept{return false;};
 need(!failedTrack()&&first->RecordingMayExist(),"failed Track leaves an allowed monotonic false positive instead of clearing recording capability");
 std::array<B::Token,B::AliasSnapshot::Capacity> physical;physical[0]=first;
 for(size_t index=1;index!=physical.size();++index){physical[index]=registry.ObserveInstance(address(0x130000+index*256),18000,detach,publish,&effects);need(physical[index]&&physical[index]->RecordingMayExist(),"all 64 same-native-GUID aliases inherit existing recording capability");}
 {B::CurrentGuard old(first);need(old.Retire(detach,&effects),"logical title-list retirement does not erase physical capability");}
 auto reborn=registry.ObserveInstance(first->Address(),18000,detach,publish,&effects);
 need(reborn&&reborn!=first&&reborn->RecordingMayExist()&&first->RecordingMayExist(),"same native GUID logical re-observation inherits monotonic recording flag");
 auto recycled=registry.ObserveInstance(physical[1]->Address(),18001,detach,publish,&effects);
 need(recycled&&!recycled->RecordingMayExist()&&physical[1]->RecordingMayExist(),"genuinely recycled different native stamp starts false without clearing old physical state");
 need(registry.CaptureProvenAliasesForFinalZero(first,aliases)&&aliases.count==63,"recording marker alias snapshot omits recycled different-GUID address");
 registry.RetireProvenAliases(aliases,detach,&effects);
 need(first->RecordingMayExist()&&reborn->RecordingMayExist(),"final logical metadata retirement never clears the monotonic shared marker");
 {B::CurrentGuard fresh(recycled);need(fresh.Retire(detach,&effects),"recycled non-recording physical owner retires normally");}
 need(registry.LiveCountForTesting()==0&&registry.Healthy(),"recording marker does not retain catalog entries or title COM references");
}
void bounded(){
 B::Registry registry;Effects effects;
 for(uint64_t index=1;index<=4096;++index){
  auto token=registry.PublishFresh(address(0x100000+index*256),index+100,detach,publish,&effects);
  need(bool(token),"bounded catalog publishes authoritative instance");B::CurrentGuard guard(token);need(guard.Retire(detach,&effects),"bounded catalog removes final instance");
 }
 need(registry.LiveCountForTesting()==0&&effects.detached==4096&&effects.metadata.empty(),"catalog does not retain historical address tombstones");
 need(registry.WeakPhysicalCountForTesting()<=64,"cold cursor bounds expired physical metadata under steady births/finals");
 // A burst can leave weak tombstones after hot Release; only cold births prune.
 B::Registry burst;Effects batch;std::vector<B::Token> retired;retired.reserve(4096);
 for(uint64_t index=1;index<=4096;++index)retired.push_back(burst.PublishFresh(address(0x500000+index*256),5000+index,detach,publish,&batch));
 for(auto& token:retired){B::CurrentGuard guard(token);guard.Retire(detach,&batch);}
 need(burst.LiveCountForTesting()==0&&burst.WeakPhysicalCountForTesting()==4096,"hot final retirement never sweeps or locks physical weak index");
 retired.clear();
 for(uint64_t index=1;index<=1024;++index){auto token=burst.PublishFresh(address(0x900000+index*256),10000+index,detach,publish,&batch);B::CurrentGuard guard(token);guard.Retire(detach,&batch);}
 need(burst.LiveCountForTesting()==0&&burst.WeakPhysicalCountForTesting()<=64,"bounded eight-entry cold pruning removes expired burst without historical growth");
}
Effects processEffects;
void processFacade(){
 processEffects.registry=&B::ProcessRegistry();
 need(B::ConfigureActions({detach,publish,&processEffects})&&B::ConfigureActions({detach,publish,&processEffects}),"process dispatcher installs once and identical cold registration is idempotent");
 const auto stamp=B::AllocateInstanceStamp(),next=B::AllocateInstanceStamp();
 need(stamp&&next>stamp,"native helper receives shared monotonic nonzero process stamps");
 auto token=B::ComparePublish(address(0xa000),{},stamp);
 need(token&&B::ObserveInitializing(token,true)&&!B::CacheAdmissible(token),"action-free native cold election uses required registered POD callbacks");
 need(B::Finalize(token,true)&&B::ObserveExisting(token)&&B::Healthy(),"action-free native stamp completion is admissible");
 auto alias=B::LinkAlias(stamp,address(0xa008));
 {B::ScopedRelease pending(alias);need(token->ReleasesInFlight()==1&&!B::CacheAdmissible(token),"explicit reserved-GUID alias shares counter in process facade");}
 need(B::ObserveInstance(token->Address(),stamp)==token,"action-free interned observation preserves logical identity");
 {B::CurrentGuard guard(token);need(guard.Retire(),"registered exact-sequence pre-retirement callback is available");}
 need(B::RetireCurrentInstance(alias)&&!B::RetireCurrentInstance(alias),"registered actual0 alias retirement is idempotent");
 need(processEffects.metadata.empty()&&B::ProcessRegistry().LiveCountForTesting()==0,"registered POD callbacks remove all explicitly retired aliases");
 auto native=B::ObserveInstance(address(0xa100),next),nativeAlias=B::LinkAlias(next,address(0xa108));B::AliasSnapshot aliases;
 need(native&&nativeAlias&&B::CaptureProvenAliasesForFinalZero(native,aliases)&&aliases.complete&&aliases.count==2,"registered native facade exposes bounded proven alias tokens/count/complete");
 need(B::RetireProvenAliases(aliases)==2&&processEffects.metadata.empty(),"registered alias staged retirement invokes required POD dispatcher outside index guards");
 std::atomic<uint64_t> exhausted{UINT64_MAX};
 need(!B::Detail::AllocateMonotonic(exhausted)&&!B::Detail::AllocateMonotonic(exhausted)&&exhausted==UINT64_MAX,"process/sequence allocator never wraps or reuses exhausted IDs");
 B::Registry unconfigured;need(!unconfigured.Actions().detachOld&&!unconfigured.Healthy(),"missing registered cleanup dispatcher fails closed instead of silently omitting detach");
}
NrdBridgePerf::Report measuredProfile;
std::atomic<unsigned> profileReports{0};
void captureProfile(const NrdBridgePerf::Report& report)noexcept{measuredProfile=report;++profileReports;}
struct ProfileEffects{Effects effects;bool frozen=false;};
bool profileDetach(void* state,const B::Token& token)noexcept{
 auto& data=*static_cast<ProfileEffects*>(state);auto* waits=NrdBridgePerf::Detail::currentWaits;
 if(!waits||!B::InMetadataAction())return false;
 const auto before=(*waits)[size_t(NrdBridgePerf::WaitKind::Metadata)];const auto clocks=qpcCalls.load();
 // Deliberately pause only the POD callback. Its time/QPC calls must not leak
 // into the lock-acquisition profiler after each mutex has been acquired.
 std::this_thread::sleep_for(std::chrono::milliseconds(5));
 data.frozen=(*waits)[size_t(NrdBridgePerf::WaitKind::Metadata)]==before&&qpcCalls==clocks;
 return data.frozen&&detach(&data.effects,token);
}
void birthWaitProfiling(){
 namespace P=NrdBridgePerf;B::Registry registry;Effects effects;void* a=address(0x120000);
 const auto off=qpcCalls.load();auto token=registry.ObserveInstance(a,17000,detach,publish,&effects);B::AliasSnapshot aliases;
 {P::Scope disabled(P::Hook::Release,true);registry.Capture(a);registry.CaptureProvenAliasesForFinalZero(token,aliases);}
 need(!P::Detail::configured&&!P::Detail::collecting&&qpcCalls==off,"profiling default OFF adds no QPC call for address/cold-physical/alias lock acquisitions");
 P::Configure(captureProfile);P::ConsumerFrame(7);
 need(P::Detail::configured&&P::Detail::collecting&&!profileReports,"profiling ON requires actual configured Consumer gameplay interval");
 const auto outside=qpcCalls.load();registry.Capture(a);registry.CaptureProvenAliasesForFinalZero(token,aliases);
 need(qpcCalls==outside,"armed sampler outside a measured physical hook adds no mutex QPC overhead");
 {P::Scope measured(P::Hook::Release,true);auto clocks=qpcCalls.load();registry.Capture(a);
  need(qpcCalls==clocks+2,"address registry acquisition is measured exactly once");
  clocks=qpcCalls.load();registry.CaptureProvenAliasesForFinalZero(token,aliases);
  need(qpcCalls==clocks+2,"per-physical alias snapshot acquisition is measured exactly once");
  clocks=qpcCalls.load();auto fresh=registry.ObserveInstance(address(0x120100),17001,detach,publish,&effects);
  need(fresh&&qpcCalls==clocks+6,"cold publication profiles only physical-index/address/alias mutex acquisitions");
  {B::CurrentGuard current(fresh);need(current.Retire(detach,&effects),"profiled cold birth retires normally");}}
 // A real queued address acquisition contributes Metadata wait to Release.
 std::promise<void> entered,finish,start;auto held=entered.get_future();auto done=finish.get_future().share();auto begun=start.get_future();
 auto holder=std::async(std::launch::async,[&]{B::CurrentGuard current(token);entered.set_value();done.wait();});
 need(held.wait_for(std::chrono::seconds(2))==std::future_status::ready,"profiling fixture holds actual production address mutex");
 auto unlock=std::async(std::launch::async,[&]{begun.wait();std::this_thread::sleep_for(std::chrono::milliseconds(30));finish.set_value();});
 {P::Scope measured(P::Hook::Release,true);start.set_value();need(registry.Capture(a)==token,"profiled acquisition waits for and observes current metadata");}
 holder.get();unlock.get();
 ProfileEffects final;final.effects.metadata[a]=token->Sequence();
 {P::Scope measured(P::Hook::Release,true);B::CurrentGuard current(token);need(current.Retire(profileDetach,&final),"POD retirement callback keeps acquisition counters/QPC frozen while it is paused");}
 need(final.frozen&&registry.Healthy(),"metadata profiler excludes protected callback duration");
 for(uint32_t frame=8;frame<=107;++frame)P::ConsumerFrame(frame);
 const auto& sample=measuredProfile.hooks[size_t(P::Hook::Release)];
 need(profileReports==1&&measuredProfile.frames==100&&sample.calls==3&&sample.waitTicks[size_t(P::WaitKind::Metadata)]>0,"Release report includes actual Birth contention over one hundred Consumer intervals");
 need(sample.waitTicks[size_t(P::WaitKind::Metadata)]<=sample.ticks,"mutex acquisition wait cannot exceed measured physical hook duration");
 const auto ended=qpcCalls.load();{P::Scope after(P::Hook::Release,true);registry.Capture(a);registry.CaptureProvenAliasesForFinalZero(token,aliases);}
 need(qpcCalls==ended&&!P::Detail::collecting&&profileReports==1,"completed one-shot profiler restores inert no-QPC Birth lock path");
}
struct Cross{B::Registry* registry;void* other;};
bool crossCapture(void* state,const B::Token&)noexcept{
 auto& cross=*static_cast<Cross*>(state);return !cross.registry->Capture(cross.other)&&!cross.registry->Healthy();
}
void hazards(){
 B::Registry registry;Effects effects;void* a=address(0x7000);uintptr_t b=0x7100;
 while(B::Registry::ShardIndex(address(b))==B::Registry::ShardIndex(a))b+=16;
 auto token=registry.PublishFresh(a,70,detach,publish,&effects);Cross cross{&registry,address(b)};
 {B::CurrentGuard guard(token);need(!guard.Retire(crossCapture,&cross),"cross-shard metadata callback latches failure instead of waiting");}
 need(!registry.Healthy()&&!token->Live(),"cross-shard hazard fails closed without resurrecting retired object");
 B::Registry recursive;Effects nested;
 auto current=recursive.PublishFresh(address(0x8000),80,detach,publish,&nested);
 struct Reentrant{B::Registry* registry;Effects* effects;};Reentrant reentry{&recursive,&nested};
 auto callback=+[](void* state,const B::Token& old)noexcept{
  auto& data=*static_cast<Reentrant*>(state);return !data.registry->PublishFresh(old->Address(),81,detach,publish,data.effects);
 };
 {B::CurrentGuard guard(current);need(!guard.Retire(callback,&reentry),"publication from inside detach is rejected");}
 need(!recursive.Healthy(),"metadata callbacks cannot reenter instance mutation and hide partial cleanup");
 B::Registry missing;need(!missing.PublishFresh(address(0x9000),0,detach,publish,&nested)&&!missing.Healthy(),"missing native instance stamp fails closed");
}
int main(int argc,char** argv)try{
 need(argc==2,"output JSON path");basics();reuseAndNotifications();probeAndAliases();missedPreFinal();internedDuringFinal();firstStampElection();crossNestedNonfinal();independentShards();stagedProvenAliases();aliasCapAndPruning();concurrentAliasFinalReseed();aliasIndexNotHeldByCallback();recordingPhysicalMarker();bounded();processFacade();hazards();birthWaitProfiling();
 need(nativeInside==0&&ownedInside==0,"all executed native calls and owned destruction remain outside metadata scope");
 const auto result=std::string("{\"native_checks\":")+std::to_string(checks.load())+",\"shards\":64,\"bounded_births\":4096,\"burst_births\":4096,\"cold_prune_budget\":8,\"proven_alias_cap\":64,\"profile_reports\":"+std::to_string(profileReports.load())+",\"metadata_wait_ticks\":"+std::to_string(measuredProfile.hooks[size_t(NrdBridgePerf::Hook::Release)].waitTicks[size_t(NrdBridgePerf::WaitKind::Metadata)])+",\"native_calls_inside_scope\":0,\"owned_destruction_inside_scope\":0,\"gpu_work\":false}";
 std::ofstream(argv[1])<<result<<'\n';std::cout<<result<<'\n';return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
'''


GATE_CPP = r'''
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include "misc/NrdBridgeBirth_Dx12.h"
#include "misc/NrdBridgeLifetime_Dx12.h"
#include <barrier>
#include <chrono>
#include <fstream>
#include <future>
#include <iostream>
#include <stdexcept>
#include <thread>
namespace B=NrdBridgeBirth;
namespace L=NrdBridgeLifetime;
std::atomic<unsigned> checks{0},weakGetters{0};
void need(bool value,const char* message){if(!value)throw std::runtime_error(message);++checks;}
void titleWeakGetter(const L::ScopedBorrow& borrow){if(borrow.Acquired())++weakGetters;}
void nestedBorrowDenied(){
 {L::ScopedBorrow disabled(false);need(disabled.Acquired()&&!L::Detail::borrowDepth&&!L::Detail::releaseDepth,"startup OFF scope touches no gate or depth");}
 {L::ScopedBorrow borrow;need(borrow.Acquired()&&L::Detail::borrowDepth==1,"outer strong CPU borrow acquires exclusive gate");
  {L::ScopedBorrow nested;need(nested.Acquired()&&L::Detail::borrowDepth==2,"same-thread borrow reentry inherits existing exclusive protection");}
  {L::ScopedRelease owned(false);need(!L::Detail::releaseDepth,"owned/native-internal release bypass does not attempt a gate upgrade");
   L::ScopedBorrow inherited;need(inherited.Acquired(),"owned release under an existing borrow retains its protection");}}
 need(!L::Detail::borrowDepth&&!L::Detail::releaseDepth,"ordinary borrow nesting balances depth");
 {L::ScopedRelease external(true);need(L::Detail::releaseDepth==1,"external native release enters shared lifetime gate");
  {L::ScopedBorrow denied;titleWeakGetter(denied);need(!denied.Acquired()&&!L::Detail::borrowDepth,"new nested CPU borrow inside external release is denied without depth inflation");}
  {L::ScopedRelease child(true);L::ScopedBorrow denied;titleWeakGetter(denied);need(!denied.Acquired()&&L::Detail::releaseDepth==2&&!L::Detail::borrowDepth,"nested native release cannot silently gain exclusive borrowed protection");}}
 need(!weakGetters&&!L::Detail::borrowDepth&&!L::Detail::releaseDepth,"denied bridge path skips every title weak getter and balances scopes");
}
void independentNativeReleases(){
 std::promise<void> entered,finish;auto begun=entered.get_future();auto done=finish.get_future().share();
 auto destructor=std::async(std::launch::async,[&]{L::ScopedRelease release(true);entered.set_value();done.wait();});
 need(begun.wait_for(std::chrono::seconds(2))==std::future_status::ready,"native final destructor holds an external release scope");
 auto other=std::async(std::launch::async,[]{L::ScopedRelease release(true);return L::Detail::releaseDepth==1;});
 need(other.wait_for(std::chrono::seconds(2))==std::future_status::ready&&other.get(),"independent native release proceeds while another native destructor is active");
 auto borrower=std::async(std::launch::async,[]{L::ScopedBorrow borrow;return borrow.Acquired();});
 need(borrower.wait_for(std::chrono::milliseconds(30))==std::future_status::timeout,"strong title CPU borrow remains excluded during an active native release");
 finish.set_value();destructor.get();need(borrower.get(),"borrow resumes after every physical release scope completes");
}
void crossNestedNativeReleases(){
 std::barrier native(2);std::atomic<unsigned> completed{0};
 auto body=[&]{L::ScopedRelease outer(true);native.arrive_and_wait();
  {L::ScopedRelease child(true);L::ScopedBorrow denied;titleWeakGetter(denied);need(!denied.Acquired(),"cross-nested native release denies weak borrow");}
  ++completed;};
 auto a=std::async(std::launch::async,body),b=std::async(std::launch::async,body);
 need(a.wait_for(std::chrono::seconds(2))==std::future_status::ready&&b.wait_for(std::chrono::seconds(2))==std::future_status::ready,"A-to-B/B-to-A native release nests complete on real production gate without cycles");
 a.get();b.get();need(completed==2&&!weakGetters,"both native nests finish without touching a borrowed title object");
}
bool pod(void*,const B::Token& token)noexcept{return B::InMetadataScope()&&bool(token);}
void nativeDestructorWorkerCreate(){
 B::Registry registry;std::atomic<unsigned> nativeCalls{0};
 auto destructor=std::async(std::launch::async,[&]{L::ScopedRelease external(true);
  auto creator=std::async(std::launch::async,[&]{
   // The native Create return holds its caller reference. Its cold description
   // and birth publication need no weak borrow or Release-to-Borrow upgrade.
   need(!B::InMetadataScope()&&!L::Detail::borrowDepth,"native creation getter uses returned strong ref outside metadata scope");++nativeCalls;
   auto token=registry.PublishFresh(reinterpret_cast<void*>(0xb000),11000,pod,pod,nullptr);
   {B::CurrentGuard current(token);need(current.MatchesCurrent()&&registry.Healthy(),"worker publishes POD creation metadata using caller-owned native reference");}
   {B::CurrentGuard current(token);need(current.Retire(pod,nullptr),"worker metadata ownership remains independently retireable");}
   return bool(token);});
  need(creator.wait_for(std::chrono::seconds(2))==std::future_status::ready&&creator.get(),"native destructor can join creator worker without a weak-borrow gate cycle");return true;});
 need(destructor.wait_for(std::chrono::seconds(3))==std::future_status::ready&&destructor.get()&&nativeCalls==1,"outer physical release and worker create both complete");
}
int main(int argc,char** argv)try{
 need(argc==2,"gate result path");need(!L::ConcurrentReleasesEnabled(),"production gate starts in legacy mode before protocol installation");
 {L::ScopedRelease legacy(true);L::ScopedBorrow inherited;need(inherited.Acquired(),"legacy nested borrow inherits outer exclusive Release protection");
  need(!L::EnableConcurrentReleases(),"gate flip refuses an active caller borrow/release scope");}
 need(B::ConfigureActions({pod,pod,nullptr}),"POD birth retirement dispatcher installs before gate flip");
 need(L::EnableConcurrentReleases()&&L::ConcurrentReleasesEnabled(),"production gate enables concurrent Release only after explicit bootstrap");
 nestedBorrowDenied();independentNativeReleases();crossNestedNativeReleases();nativeDestructorWorkerCreate();
 need(!weakGetters,"all denied nested bridge paths skip title weak COM access");
 const auto result=std::string("{\"gate_checks\":")+std::to_string(checks.load())+",\"weak_getters_after_denied_borrow\":0,\"production_lifetime_header\":true,\"gpu_work\":false}";
 std::ofstream(argv[1])<<result<<'\n';std::cout<<result<<'\n';return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
'''


def run_gate(output):
    """Run only after integration provides ScopedBorrow.Acquired and inverse gate."""
    source, exe = output/'nrd_birth_gate.cpp', output/'nrd_birth_gate.exe'
    source.write_text(GATE_CPP, encoding='utf-8')
    compile_cpp(source, exe, (), (ROOT/'OptiScaler',))
    subprocess.run([str(exe), str(output/'gate-result.json')], check=True, timeout=30,
                   creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    result = json.loads((output/'gate-result.json').read_text())
    assert result['gate_checks'] >= 24 and result['weak_getters_after_denied_borrow'] == 0
    assert result['production_lifetime_header'] is True and result['gpu_work'] is False
    result['python_checks'] = 2
    (output/'gate-result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))


def run():
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/13b-inputs/tests/nrd_birth'))
    output.mkdir(parents=True, exist_ok=True)
    if '--lifetime-gate' in sys.argv:
        run_gate(output)
        return
    source, exe = output/'nrd_birth.cpp', output/'nrd_birth.exe'
    source.write_text(CPP, encoding='utf-8')
    compile_cpp(source, exe, (), (ROOT/'OptiScaler',))
    subprocess.run([str(exe), str(output/'result.json')], check=True, timeout=30,
                   creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    result = json.loads((output/'result.json').read_text())
    assert result['native_checks'] >= 8200
    assert result['shards'] == 64 and result['bounded_births'] == 4096
    assert result['burst_births'] == 4096 and result['cold_prune_budget'] == 8
    assert result['proven_alias_cap'] == 64 and result['profile_reports'] == 1 and result['metadata_wait_ticks'] > 0
    assert result['native_calls_inside_scope'] == 0 and result['owned_destruction_inside_scope'] == 0
    assert result['gpu_work'] is False
    result['python_checks'] = 6
    (output/'result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    run()
