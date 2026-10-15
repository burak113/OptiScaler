#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <json.hpp>
#include <array>
#include <map>
#include <vector>
#include <string>
#include <functional>
#include <mutex>
#include <iostream>
#include <stdexcept>
#include "__ROOT__/OptiScaler/misc/NrdBridgeLifetime_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgePerf_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgeTitleCallbacks_Dx12.h"
using Json=nlohmann::json;
unsigned checks=0;
void need(bool value,const char* message) { if(!value) throw std::runtime_error(message); ++checks; }
std::vector<std::string> events;
void event(const std::string& value) { events.push_back(value); }
bool startup=true, suppress=false, recording=false, proof=true, poisoned=false, partial=false;
unsigned originalDispatch=0,legacyDispatch=0,originalBundle=0,originalClear=0,originalPredicate=0,originalIndirect=0;
std::function<void()> effect;
void sideEffect() { if(effect) { auto action=std::move(effect); effect={}; action(); } }
namespace NrdBridge {
__ENUMS__
bool StartupEnabled() noexcept { return startup; }
void BeforeDispatch(ID3D12GraphicsCommandList*) noexcept { event("before"); }
void AfterDispatch(ID3D12GraphicsCommandList*) noexcept { event("after"); }
DispatchDisposition OriginalDispatchDisposition(ID3D12GraphicsCommandList*,DispatchKind kind) noexcept {
 event(kind==DispatchKind::Direct?"query.direct":kind==DispatchKind::Bundle?"query.bundle":"query.indirect");
 if(kind!=DispatchKind::Direct) { poisoned|=partial; proof=false; }
 return suppress?DispatchDisposition::Suppress:DispatchDisposition::Forward;
}
void InvalidateRecordingProof(ID3D12GraphicsCommandList*,const char*) noexcept { event("invalidate"); proof=false;poisoned|=partial; }
}
namespace D3D12Hooks {
void OnBridgeOpaqueCommand(ID3D12GraphicsCommandList*,bool bundle) noexcept { event(bundle?"cache.bundle":"cache.indirect");proof=false; }
void OnBridgeCommandListClearState(ID3D12GraphicsCommandList*,ID3D12PipelineState*) noexcept { event("cache.clear");proof=false; }
void OnBridgeSetPredication(ID3D12GraphicsCommandList*,bool enabled) noexcept { event(enabled?"cache.predicate.on":"cache.predicate.off"); }
}
namespace FrameSurvey {
thread_local bool gInternal=false;
__INTERNAL__
bool Internal() noexcept { return gInternal; }
bool Tracking() noexcept { return true; }
bool Recording() noexcept { return recording; }
struct RootRow { std::map<UINT,unsigned> views; };
struct List { RootRow graphics,compute; uint64_t lastPass=0; std::vector<Json> passes; } list;
std::mutex gRecordMutex;
const GUID SignatureId={};const GUID SignatureLayoutId={1};
List& GetList(ID3D12GraphicsCommandList*) { return list; }
void Count(const char*) {}
void Fail(const char* message) { throw std::runtime_error(message); }
template<size_t N> void Pass(ID3D12GraphicsCommandList*,const char* kind,const std::array<uint64_t,N>&) {
 event(std::string("pass.")+kind);++list.lastPass;list.passes.push_back(Json::object());
}
void SnapshotWrites(ID3D12GraphicsCommandList*) { event("snapshot"); }
void RootBinding(ID3D12GraphicsCommandList*,bool graphics,ID3D12RootSignature*) { event(graphics?"mirror.graphics":"mirror.compute"); }
void DescriptorHeaps(ID3D12GraphicsCommandList*,UINT,ID3D12DescriptorHeap* const*) { event("mirror.heaps"); }
void SetPipeline(ID3D12GraphicsCommandList*,ID3D12PipelineState*) { event("mirror.pipeline"); }
bool CopyBuffer(ID3D12GraphicsCommandList*,List&,ID3D12Resource*,const std::string&,uint64_t,uint64_t) { return false; }
void STDMETHODCALLTYPE nativeIndirect(ID3D12GraphicsCommandList*,ID3D12CommandSignature*,UINT,ID3D12Resource*,UINT64,ID3D12Resource*,UINT64) {
 ++originalIndirect;event("native.indirect");sideEffect();
}
auto oIndirect=&nativeIndirect;
__INDIRECT__
}
namespace Hooks {
bool gNrdBridgeWrappers=true;
void STDMETHODCALLTYPE nativeDispatch(ID3D12GraphicsCommandList*,UINT,UINT,UINT) { ++originalDispatch;event("native.dispatch");sideEffect(); }
void STDMETHODCALLTYPE nativeClear(ID3D12GraphicsCommandList*,ID3D12PipelineState*) { ++originalClear;event("native.clear");sideEffect(); }
void STDMETHODCALLTYPE nativePredicate(ID3D12GraphicsCommandList*,ID3D12Resource*,UINT64,D3D12_PREDICATION_OP) {
 ++originalPredicate;event("native.predicate");sideEffect();
}
auto o_Dispatch=&nativeDispatch;auto o_ClearState=&nativeClear;auto o_SetPredication=&nativePredicate;
void hkDispatch(ID3D12GraphicsCommandList* cmd,UINT x,UINT y,UINT z) { ++legacyDispatch;event("legacy.dispatch");o_Dispatch(cmd,x,y,z); }
void hkExecuteBundle(ID3D12GraphicsCommandList*,ID3D12GraphicsCommandList*) { ++originalBundle;event("native.bundle");sideEffect(); }
__HOOKS__
}
void reset() {
 events.clear();effect={};startup=Hooks::gNrdBridgeWrappers=true;suppress=false;recording=false;proof=true;poisoned=partial=false;
 FrameSurvey::gInternal=false;FrameSurvey::list={};originalDispatch=legacyDispatch=originalBundle=originalClear=originalPredicate=originalIndirect=0;
}
unsigned count(const char* name) { return unsigned(std::count(events.begin(),events.end(),name)); }
int main() { try {
 auto* cmd=reinterpret_cast<ID3D12GraphicsCommandList*>(0x10000);
 auto* alias=reinterpret_cast<ID3D12GraphicsCommandList*>(0x20000);
 reset();Hooks::hkSurveyDispatch(cmd,4,5,1);
 need(events==std::vector<std::string>{"before","query.direct","pass.Dispatch","legacy.dispatch","native.dispatch","snapshot","after"},"forward exact order");
 need(originalDispatch==1 && legacyDispatch==1,"forward original once");
 reset();suppress=true;Hooks::hkSurveyDispatch(cmd,4,5,1);
 need(events==std::vector<std::string>{"before","query.direct","pass.DispatchSkipped","after"},"suppression truthfully records public invocation");
 need(originalDispatch==0 && legacyDispatch==0 && count("snapshot")==0,"suppression records no native dispatch or output snapshot");
 reset();suppress=true;startup=Hooks::gNrdBridgeWrappers=false;Hooks::hkSurveyDispatch(cmd,4,5,1);
 need(originalDispatch==1 && count("query.direct")==0 && count("before")==0 && count("after")==0,"startup off cannot suppress");
 reset();suppress=true;FrameSurvey::gInternal=true;Hooks::hkSurveyDispatch(cmd,1,1,1);
 need(events==std::vector<std::string>{"native.dispatch"},"owned/internal work bypasses title observation");
 reset();suppress=true;{NrdBridgeTitleCallbacks::Scope scope(NrdBridgeTitleCallbacks::Method::Dispatch,true);Hooks::hkSurveyDispatch(alias,1,1,1);}
 need(originalDispatch==1 && count("query.direct")==0 && count("snapshot")==0,"nested decorator forwards native once without a second observation");
 reset();effect=[&]{Hooks::hkSurveyDispatch(alias,1,1,1);};Hooks::hkSurveyDispatch(cmd,1,1,1);
 need(originalDispatch==2 && count("query.direct")==1 && count("snapshot")==1 && count("before")==1,"two COM forwarding identities one logical observation");
 for(unsigned a=0;a<unsigned(NrdBridgeTitleCallbacks::Method::Count);++a)
  for(unsigned b=0;b<unsigned(NrdBridgeTitleCallbacks::Method::Count);++b) {
   NrdBridgeTitleCallbacks::Scope outer(static_cast<NrdBridgeTitleCallbacks::Method>(a),true);
   NrdBridgeTitleCallbacks::Scope inner(static_cast<NrdBridgeTitleCallbacks::Method>(b),true);
   need(inner.Nested()==(a==b),"method-specific nesting preserves legitimate cross-method calls");
  }
 reset();suppress=true;{NrdBridgeTitleCallbacks::Scope scope(NrdBridgeTitleCallbacks::Method::Pipeline,true);Hooks::hkSurveyDispatch(cmd,1,1,1);}
 need(count("query.direct")==1 && originalDispatch==0,"pipeline nesting does not hide an independent dispatch");
 reset();partial=true;effect=[] {proof=true;};Hooks::hkBridgeClearState(cmd,nullptr);
 need(originalClear==1 && poisoned && !proof && count("invalidate")==2,"ClearState seals proof after nested pipeline repopulation");
 need(count("mirror.graphics")==1 && count("mirror.compute")==1 && count("mirror.heaps")==1 && count("mirror.pipeline")==1,"ClearState clears metadata without recording Reset");
 reset();FrameSurvey::gInternal=true;Hooks::hkBridgeClearState(cmd,nullptr);
 need(events==std::vector<std::string>{"native.clear"},"internal ClearState is not a title invalidation");
 reset();partial=true;effect=[] {proof=true;};Hooks::hkBridgeSetPredication(cmd,reinterpret_cast<ID3D12Resource*>(0xdead0000),128,D3D12_PREDICATION_OP_NOT_EQUAL_ZERO);
 need(originalPredicate==1 && poisoned && !proof && count("invalidate")==2 && count("cache.predicate.on")==1,"non-null predication invalidates before and after native forwarding");
 reset();partial=true;Hooks::hkBridgeSetPredication(cmd,nullptr,0,D3D12_PREDICATION_OP_EQUAL_ZERO);
 need(originalPredicate==1 && !poisoned && proof && count("invalidate")==0 && count("cache.predicate.off")==1,"null predication is benign known OFF");
 reset();partial=true;suppress=true;effect=[] {proof=true;};Hooks::hkSurveyExecuteBundle(cmd,alias);
 need(originalBundle==1 && count("query.bundle")==1 && poisoned && !proof,"opaque bundle always forwards even a hostile suppression reply");
 need(count("cache.bundle")==2 && count("invalidate")==1 && count("snapshot")==1,"bundle reseals after nested state and snapshots only executed work");
 reset();FrameSurvey::gInternal=true;Hooks::hkSurveyExecuteBundle(cmd,alias);
 need(events==std::vector<std::string>{"native.bundle"},"internal bundle bypass");
 reset();partial=true;suppress=true;effect=[] {proof=true;};FrameSurvey::Indirect(cmd,nullptr,7,nullptr,16,nullptr,0);
 need(originalIndirect==1 && count("query.indirect")==1 && poisoned && !proof,"unknown/mixed indirect is never suppressed");
 need(count("cache.indirect")==2 && count("invalidate")==1 && count("snapshot")==1,"indirect invalidates stale root proof before and after forwarding");
 reset();FrameSurvey::gInternal=true;FrameSurvey::Indirect(cmd,nullptr,1,nullptr,0,nullptr,0);
 need(events==std::vector<std::string>{"native.indirect"},"owned indirect bypasses public tracking");
 reset();{NrdBridgeTitleCallbacks::Scope scope(NrdBridgeTitleCallbacks::Method::Indirect,true);FrameSurvey::Indirect(alias,nullptr,1,nullptr,0,nullptr,0);}
 need(originalIndirect==1 && count("query.indirect")==0 && count("snapshot")==0,"indirect decorator is observed once");
 reset();recording=true;partial=true;need(NrdBridgeLifetime::EnableConcurrentReleases(),"actual lifetime gate enabled for denied nested borrow control");
 {NrdBridgeLifetime::ScopedRelease release(true);FrameSurvey::Indirect(cmd,nullptr,1,nullptr,0,nullptr,0);}
 need(originalIndirect==1 && poisoned && count("query.indirect")==1 && count("snapshot")==0,"denied recorder borrow cannot bypass irreversible-skip invalidation");
 std::cout<<Json{{"checks",checks},{"cases",19},{"method_pairs",unsigned(NrdBridgeTitleCallbacks::Method::Count)*unsigned(NrdBridgeTitleCallbacks::Method::Count)},
  {"scope","actual production hook bodies and method/lifetime guards; CPU observer/native-call spies, no GPU or provider"}}.dump()<<'\n';return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;} }
