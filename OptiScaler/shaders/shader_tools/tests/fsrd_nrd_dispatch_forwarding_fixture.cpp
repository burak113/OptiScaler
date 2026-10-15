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
bool startup=true, suppress=false, recording=false, proof=true, poisoned=false, partial=false, preserveIndirect=false;
unsigned originalDispatch=0,legacyDispatch=0,originalBundle=0,originalClear=0,originalPredicate=0,originalIndirect=0;
unsigned originalDraw=0,originalIndexed=0,legacyDraw=0,legacyIndexed=0,physicalDraw=0;
bool drawDecorator=false;std::array<uint64_t,6> drawArguments{},passArguments{};
std::function<void()> effect;
void sideEffect() { if(effect) { auto action=std::move(effect); effect={}; action(); } }
namespace NrdBridge {
__ENUMS__
bool StartupEnabled() noexcept { return startup; }
void BeforeDispatch(ID3D12GraphicsCommandList*) noexcept { event("before"); }
void AfterDispatch(ID3D12GraphicsCommandList*) noexcept { event("after"); }
void BeforeGraphicsConsumer(ID3D12GraphicsCommandList*) noexcept { event("graphics.before"); }
bool PreserveIndirectRecording(ID3D12GraphicsCommandList*,ID3D12CommandSignature*) noexcept { event("preserve.indirect");return preserveIndirect; }
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
template<size_t N> void Pass(ID3D12GraphicsCommandList*,const char* kind,const std::array<uint64_t,N>& args) {
 passArguments.fill(0);std::copy(args.begin(),args.end(),passArguments.begin());
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
void STDMETHODCALLTYPE nativeDraw(ID3D12GraphicsCommandList*,UINT vertices,UINT instances,UINT startVertex,UINT startInstance){
 ++originalDraw;event("native.draw");drawArguments={vertices,instances,startVertex,startInstance,0,0};
 if(drawDecorator&&effect){sideEffect();return;}++physicalDraw;sideEffect();
}
void STDMETHODCALLTYPE nativeIndexed(ID3D12GraphicsCommandList*,UINT indices,UINT instances,UINT startIndex,INT baseVertex,UINT startInstance){
 ++originalIndexed;event("native.indexed");drawArguments={indices,instances,startIndex,uint64_t(int64_t(baseVertex)),startInstance,0};
 if(drawDecorator&&effect){sideEffect();return;}++physicalDraw;sideEffect();
}
auto o_DrawInstanced=&nativeDraw;auto o_DrawIndexedInstanced=&nativeIndexed;
void hkDrawInstanced(ID3D12GraphicsCommandList* cmd,UINT a,UINT b,UINT c,UINT d){++legacyDraw;event("legacy.draw");o_DrawInstanced(cmd,a,b,c,d);}
void hkDrawIndexedInstanced(ID3D12GraphicsCommandList* cmd,UINT a,UINT b,UINT c,INT d,UINT e){++legacyIndexed;event("legacy.indexed");o_DrawIndexedInstanced(cmd,a,b,c,d,e);}
void hkDispatch(ID3D12GraphicsCommandList* cmd,UINT x,UINT y,UINT z) { ++legacyDispatch;event("legacy.dispatch");o_Dispatch(cmd,x,y,z); }
void hkExecuteBundle(ID3D12GraphicsCommandList*,ID3D12GraphicsCommandList*) { ++originalBundle;event("native.bundle");sideEffect(); }
__HOOKS__
}
void reset() {
 events.clear();effect={};startup=Hooks::gNrdBridgeWrappers=true;suppress=false;recording=false;proof=true;poisoned=partial=preserveIndirect=false;
 FrameSurvey::gInternal=false;FrameSurvey::list={};originalDispatch=legacyDispatch=originalBundle=originalClear=originalPredicate=originalIndirect=0;
 originalDraw=originalIndexed=legacyDraw=legacyIndexed=physicalDraw=0;drawDecorator=false;drawArguments.fill(0);passArguments.fill(0);
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
 reset();partial=true;effect=[] {proof=true;};Hooks::hkBridgeSetPredication(cmd,reinterpret_cast<ID3D12Resource*>(uintptr_t(0xdead0000)),128,D3D12_PREDICATION_OP_NOT_EQUAL_ZERO);
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
 reset();preserveIndirect=true;partial=true;FrameSurvey::Indirect(cmd,nullptr,3,nullptr,0,nullptr,0);
 need(originalIndirect==1&&count("preserve.indirect")==1&&count("query.indirect")==0,"proved pure indirect still forwards once without generic poisoning");
 need(proof&&!poisoned&&count("cache.indirect")==0&&count("mirror.compute")==0&&count("mirror.graphics")==0&&count("mirror.heaps")==0&&count("mirror.pipeline")==0,"proved pure indirect preserves exact D3D and mirror bindings");
 need(count("pass.ExecuteIndirect")==1&&count("snapshot")==1,"preserved invocation retains exactly one executed recorder observation");
 reset();preserveIndirect=true;FrameSurvey::gInternal=true;FrameSurvey::Indirect(cmd,nullptr,1,nullptr,0,nullptr,0);
 need(originalIndirect==1&&count("preserve.indirect")==0,"internal indirect never asks native graph preservation");
 reset();preserveIndirect=true;{NrdBridgeTitleCallbacks::Scope scope(NrdBridgeTitleCallbacks::Method::Indirect,true);FrameSurvey::Indirect(alias,nullptr,1,nullptr,0,nullptr,0);}
 need(originalIndirect==1&&count("preserve.indirect")==0,"nested indirect decorator does not duplicate preservation query");
 unsigned graphicsCases=0;
 for(bool indexed:{false,true}){
  reset();suppress=true;
  const auto call=[&](ID3D12GraphicsCommandList* target){if(indexed)Hooks::hkSurveyDrawIndexedInstanced(target,7,2,11,-5,13);else Hooks::hkSurveyDrawInstanced(target,7,2,11,13);};
  call(cmd);
  const std::vector<std::string> expected=indexed?std::vector<std::string>{"graphics.before","pass.DrawIndexedInstanced","legacy.indexed","native.indexed","snapshot"}:std::vector<std::string>{"graphics.before","pass.DrawInstanced","legacy.draw","native.draw","snapshot"};
  need(events==expected&&physicalDraw==1&&count("query.direct")==0,"both graphics draws always forward once after exactly one observer/pass");
  need(drawArguments==passArguments&&drawArguments[0]==7&&drawArguments[1]==2&&(indexed?drawArguments[3]==uint64_t(int64_t(-5)):drawArguments[3]==13),"actual recorded draw arguments including signed base vertex are unchanged");++graphicsCases;
  reset();FrameSurvey::gInternal=true;call(cmd);
  need(physicalDraw==1&&count("graphics.before")==0&&count("snapshot")==0&&legacyDraw+legacyIndexed==0,"internal draws forward only native and do not revisit title consumer");++graphicsCases;
  reset();drawDecorator=true;effect=[&]{call(alias);};call(cmd);
  need(physicalDraw==1&&originalDraw+originalIndexed==2&&count("graphics.before")==1&&count("snapshot")==1,"same-method COM decorator aliases reach one final native draw and one logical observer");++graphicsCases;
 }
 reset();startup=Hooks::gNrdBridgeWrappers=false;Hooks::hkSurveyDrawInstanced(cmd,1,1,0,0);
 need(physicalDraw==1&&count("graphics.before")==0&&count("pass.DrawInstanced")==1,"startup-OFF draw preserves original recorder path without bridge observer");++graphicsCases;
 reset();effect=[&]{Hooks::hkSurveyDrawIndexedInstanced(alias,3,1,0,0,0);};Hooks::hkSurveyDrawInstanced(cmd,3,1,0,0);
 need(physicalDraw==2&&count("graphics.before")==2&&count("pass.DrawInstanced")==1&&count("pass.DrawIndexedInstanced")==1,"legitimate cross-method nested draws remain separately observed");++graphicsCases;
 reset();recording=true;partial=true;need(NrdBridgeLifetime::EnableConcurrentReleases(),"actual lifetime gate enabled for denied nested borrow control");
 {NrdBridgeLifetime::ScopedRelease release(true);FrameSurvey::Indirect(cmd,nullptr,1,nullptr,0,nullptr,0);}
 need(originalIndirect==1 && poisoned && count("query.indirect")==1 && count("snapshot")==0,"denied recorder borrow cannot bypass irreversible-skip invalidation");
 reset();recording=true;partial=true;preserveIndirect=true;NrdBridgeLifetime::EnableConcurrentReleases();
 {NrdBridgeLifetime::ScopedRelease release(true);FrameSurvey::Indirect(cmd,nullptr,1,nullptr,0,nullptr,0);}
 need(originalIndirect==1&&poisoned&&!proof&&count("query.indirect")==0&&count("snapshot")==0,"even prior preservation cannot bypass an unavailable recorder borrow");
 std::cout<<Json{{"checks",checks},{"cases",23+graphicsCases},{"graphics_cases",graphicsCases},{"method_pairs",unsigned(NrdBridgeTitleCallbacks::Method::Count)*unsigned(NrdBridgeTitleCallbacks::Method::Count)},
  {"scope","actual production hook bodies and method/lifetime guards; CPU observer/native-call spies, no GPU or provider"}}.dump()<<'\n';return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;} }
