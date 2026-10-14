"""Actual Title and NativeBirth, with real IUnknown/ID3D12Object C++ ABI seams.

The objects implement canonical QI and share a native byte store/refcount.
Coverage and native Release forwarding are explicit CPU detour adapters;
catalog detach/notify and recorded-lease counters are explicit CPU seams.
No native D3D12 object, installed detour, title/game, queue or GPU claim.
FSRD_CANONICAL_HEADER_ROOT selects an immutable old-header control.
--prepare-only does not compile/run; --expect-old-failure preserves the exact
old final-canonical-Release metadata safety assertion as a negative control.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]

CPP = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include "__HEADERS__/NrdBridgeNativeBirth_Dx12.h"
#include "__HEADERS__/NrdBridgeLifetime_Dx12.h"
__CANONICAL_STACK__
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
unsigned checks=0;void need(bool ok,const char* text){if(!ok)throw std::runtime_error(text);++checks;}
thread_local bool meter=false;std::atomic<unsigned> allocations=0;
void* operator new(size_t n){if(meter)++allocations;if(auto* p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void operator delete(void* p)noexcept{std::free(p);}void operator delete(void* p,size_t)noexcept{std::free(p);}
void* operator new[](size_t n){return ::operator new(n);}void operator delete[](void* p)noexcept{std::free(p);}void operator delete[](void* p,size_t)noexcept{std::free(p);}
std::atomic<unsigned> nativeUnderMetadata=0,nativeCalls=0,qiCalls=0,privateReads=0,privateWrites=0,failures=0,drains=0;
std::array<std::atomic<unsigned>,2> kindTouches{};
void native(){++nativeCalls;if(NrdBridgeBirth::InMetadataScope())++nativeUnderMetadata;}
namespace FrameSurvey{thread_local bool owned=false;bool OwnedRelease()noexcept{return owned;}void MetadataHookFailed(const char*)noexcept{++failures;}void FlushMetadataFailure()noexcept{}}
namespace RecordedComputeLease{
 struct Ticket{bool valid=false;};std::atomic<unsigned> beginCalls=0,endCalls=0;
 Ticket BeginRelease(void*){++beginCalls;return {};}
 void EndRelease(const Ticket&,bool){++endCalls;}
}
__TITLE__
using Token=NrdBridgeBirth::Token;
std::mutex catalogMutex;std::unordered_map<void*,Token> rows;
struct Effects{std::array<Token,64> retired;size_t used=0;};
void* factory()noexcept{native();return new(std::nothrow)Effects;}
bool detach(void* p,const Token& t)noexcept{
 auto& e=*static_cast<Effects*>(p);if(!NrdBridgeBirth::InMetadataAction()||e.used==e.retired.size())return false;e.retired[e.used++]=t;
 std::lock_guard lock(catalogMutex);const auto r=rows.find(t->Address());if(r!=rows.end()&&r->second==t)rows.erase(r);return true;
}
void notify(void* p)noexcept{native();++drains;delete static_cast<Effects*>(p);}
void publish(const Token& t){need(t&&t->Address(),"strong prepare returns addressed typed token");NrdBridgeBirth::CurrentGuard g(t);need(g.MatchesCurrent(),"typed publication matches current token");std::lock_guard lock(catalogMutex);rows[t->Address()]=t;}
struct Gate{std::mutex mutex;std::condition_variable cv;bool entered=false,open=false;
 void wait(){std::unique_lock l(mutex);entered=true;cv.notify_all();cv.wait(l,[&]{return open;});}
 bool reached(){std::unique_lock l(mutex);return cv.wait_for(l,std::chrono::seconds(2),[&]{return entered;});}
 void release(){std::lock_guard l(mutex);open=true;cv.notify_all();}
};
struct Physical{std::atomic<ULONG>refs{1};std::mutex mutex;bool stamped=false;NrdBridgeNativeBirth::NativeStamp stamp{};Gate* setter=nullptr;HRESULT writeResult=S_OK;};
struct Typed;
struct Canonical: IUnknown{
 std::shared_ptr<Physical> physical;Typed* typed=nullptr;IUnknown* forwarded=nullptr;bool covered=false;std::atomic<unsigned> releases=0;
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID,void**)override;
 ULONG STDMETHODCALLTYPE AddRef()override{native();return ++physical->refs;}
 ULONG raw(){native();++kindTouches[0];++releases;return forwarded?forwarded->Release():--physical->refs;}
 static ULONG original(IUnknown* p){return static_cast<Canonical*>(p)->raw();}
 ULONG STDMETHODCALLTYPE Release()override{return covered?NrdBridgeRelease::Title(static_cast<IUnknown*>(this),original):raw();}
};
struct Typed: ID3D12Object{
 std::shared_ptr<Physical> physical=std::make_shared<Physical>();Canonical* canonical=nullptr;IUnknown* forwarded=nullptr;bool covered=false;std::atomic<unsigned> releases=0;
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid,void** out)override{
  native();++qiCalls;if(!out)return E_POINTER;*out=nullptr;
  if(iid==IID_IUnknown){*out=canonical;canonical->AddRef();return S_OK;}
  if(iid==__uuidof(ID3D12Object)){*out=static_cast<ID3D12Object*>(this);AddRef();return S_OK;}return E_NOINTERFACE;
 }
 ULONG STDMETHODCALLTYPE AddRef()override{native();return ++physical->refs;}
 ULONG raw(){native();++kindTouches[1];++releases;return forwarded?forwarded->Release():--physical->refs;}
 static ULONG original(ID3D12Object* p){return static_cast<Typed*>(p)->raw();}
 ULONG STDMETHODCALLTYPE Release()override{return covered?NrdBridgeRelease::Title(static_cast<ID3D12Object*>(this),original):raw();}
 HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID guid,UINT* n,void* out)override{
  native();++privateReads;if(guid!=NrdBridgeNativeBirth::InstanceGuid)return DXGI_ERROR_NOT_FOUND;std::lock_guard l(physical->mutex);
  if(!physical->stamped)return DXGI_ERROR_NOT_FOUND;if(*n<sizeof(physical->stamp)){*n=sizeof(physical->stamp);return DXGI_ERROR_MORE_DATA;}
  *n=sizeof(physical->stamp);std::memcpy(out,&physical->stamp,sizeof(physical->stamp));return S_OK;
 }
 HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID guid,UINT n,const void* in)override{
  native();++privateWrites;if(physical->setter)physical->setter->wait();if(FAILED(physical->writeResult))return physical->writeResult;if(guid!=NrdBridgeNativeBirth::InstanceGuid||n!=sizeof(physical->stamp))return E_INVALIDARG;
  std::lock_guard l(physical->mutex);physical->stamped=true;std::memcpy(&physical->stamp,in,n);return S_OK;
 }
 HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID,const IUnknown*)override{return E_NOTIMPL;}
 HRESULT STDMETHODCALLTYPE SetName(LPCWSTR)override{return S_OK;}
};
struct Forwarded: IUnknown{
 std::shared_ptr<Physical> physical;Typed* typed=nullptr;Canonical* canonical=nullptr;std::atomic<unsigned> releases=0;
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid,void** out)override{
  native();++qiCalls;if(!out)return E_POINTER;*out=nullptr;
  if(iid==IID_IUnknown){*out=canonical;canonical->AddRef();return S_OK;}
  if(iid==__uuidof(ID3D12Object)){*out=static_cast<ID3D12Object*>(typed);typed->AddRef();return S_OK;}return E_NOINTERFACE;
 }
 ULONG STDMETHODCALLTYPE AddRef()override{native();return ++physical->refs;}
 ULONG raw(){native();++releases;return --physical->refs;}
 static ULONG original(IUnknown* p){return static_cast<Forwarded*>(p)->raw();}
 ULONG STDMETHODCALLTYPE Release()override{return NrdBridgeRelease::Title(static_cast<IUnknown*>(this),original);}
};
HRESULT Canonical::QueryInterface(REFIID iid,void** out){native();++qiCalls;if(!out)return E_POINTER;*out=nullptr;
 if(iid==IID_IUnknown){*out=static_cast<IUnknown*>(this);AddRef();return S_OK;}
 if(iid==__uuidof(ID3D12Object)){*out=static_cast<ID3D12Object*>(typed);typed->AddRef();return S_OK;}return E_NOINTERFACE;
}
Typed* currentTyped=nullptr;Canonical* currentCanonical=nullptr;bool denyCanonical=false,denyTyped=false;
bool NrdBridgeNativeBirth::ObserveReleaseCoverage(IUnknown* p)noexcept{
 native();const auto entry=(*reinterpret_cast<void***>(p))[2];
 if(entry==(*reinterpret_cast<void***>(currentCanonical))[2]){if(denyCanonical)return false;static_cast<Canonical*>(p)->covered=true;return true;}
 if(entry==(*reinterpret_cast<void***>(currentTyped))[2]){if(denyTyped)return false;static_cast<Typed*>(static_cast<ID3D12Object*>(p))->covered=true;return true;}return false;
}
struct Pair{Typed typed;Canonical canonical;Pair(){typed.canonical=&canonical;canonical.typed=&typed;canonical.physical=typed.physical;currentTyped=&typed;currentCanonical=&canonical;}};
void finalCanonical(){
 Pair pair;pair.typed.covered=pair.canonical.covered=true;
 const auto birth=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&pair.typed));publish(birth);
 need(birth->Address()==static_cast<ID3D12Object*>(&pair.typed),"token retains exact typed ObjectAddress despite distinct canonical pointer");
 IUnknown* later=nullptr;need(SUCCEEDED(pair.typed.QueryInterface(IID_IUnknown,reinterpret_cast<void**>(&later)))&&later==&pair.canonical,"later canonical QI returns stable distinct IUnknown");
 need(pair.typed.Release()==1&&birth->Live(),"typed nonfinal Release cannot retire still-live physical identity");
 need(later->Release()==0,"canonical caller performs actual final Release");
 need(!birth->Live()&&!rows.contains(birth->Address()),"final canonical IUnknown alias must retire typed metadata");
 need(!NrdBridgeBirth::Capture(&pair.canonical),"final canonical retirement removes canonical node too");
}
void concurrentAliases(){
 Pair pair;Typed other;other.physical=pair.typed.physical;other.canonical=&pair.canonical;pair.typed.physical->refs=2;
 Gate setter;pair.typed.physical->setter=&setter;Token a,b;
 std::thread first([&]{a=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&pair.typed));});const bool entered=setter.reached();if(!entered){setter.release();first.join();}need(entered,"first typed alias reached private cookie writer");
 b=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&other));
 const bool pending=b&&b->Address()==static_cast<ID3D12Object*>(&other)&&b->Initializing()&&!b->CacheAdmissible();setter.release();first.join();pair.typed.physical->setter=nullptr;
 need(pending,"concurrent typed initializing alias is quarantined until successful writer");
 need(a&&b&&a->InstanceStamp()==b->InstanceStamp()&&privateWrites==1,"canonical election gives concurrent typed tearoffs one physical cookie");
 need(a->Ready()&&b->Ready()&&a->CacheAdmissible()&&b->CacheAdmissible(),"successful writer finalizes all exact pending physical aliases outside locks");
}
void knownWarm(){
 Pair pair;pair.typed.covered=pair.canonical.covered=true;const auto t=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&pair.typed));need(t&&t->Ready(),"known warm token prepared");
 pair.typed.physical->refs=2001;const auto beforeQ=qiCalls.load(),beforeG=privateReads.load(),beforeL=RecordedComputeLease::beginCalls.load();allocations=0;meter=true;
 for(unsigned i=0;i<1000;++i)pair.typed.Release();meter=false;
 need(qiCalls==beforeQ&&privateReads==beforeG&&allocations==0&&RecordedComputeLease::beginCalls==beforeL,"known unmarked warm Release performs zero QI/getter/allocation/lease lookup");
 need(pair.typed.releases==2000&&pair.typed.physical->refs==1001,"1000 warm calls perform exactly 1000 probes and 1000 caller decrements");
}
void recoveredAlias(){
 Pair pair;pair.typed.covered=pair.canonical.covered=true;
 pair.typed.physical->stamped=true;pair.typed.physical->stamp={NrdBridgeNativeBirth::Detail::ProcessNonce(),NrdBridgeBirth::AllocateInstanceStamp()};
 Token t;{NrdBridgeNativeBirth::RetirementScope e;t=NrdBridgeBirth::ObserveInstance(&pair.typed,pair.typed.physical->stamp.instanceStamp);}publish(t);
 need(!NrdBridgeBirth::Capture(&pair.canonical),"already intercepted cold canonical alias begins without ticket");
 need(pair.canonical.Release()==0&&!t->Live()&&!rows.contains(&pair.typed),"cold strong existing-GUID recovery retires tracked typed object before final alias death");
 need(privateWrites==0,"Release recovery never elects or writes a synthetic stamp");
}
void failedWriter(){
 Pair pair;Typed other;other.physical=pair.typed.physical;other.canonical=&pair.canonical;pair.typed.physical->refs=2;
 Gate setter;pair.typed.physical->setter=&setter;pair.typed.physical->writeResult=E_FAIL;Token a,b;
 std::thread first([&]{a=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&pair.typed));});const bool entered=setter.reached();if(!entered){setter.release();first.join();}need(entered,"failed writer entered native setter");
 b=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&other));const bool pending=b&&b->Initializing()&&!b->CacheAdmissible();setter.release();first.join();
 need(pending,"typed alias stayed initializing before failed native writer finished");
 need(!a&&!NrdBridgeBirth::Healthy()&&b&&!b->Ready()&&!b->CacheAdmissible(),"failed canonical writer never admits a pending typed alias");
 need(privateWrites==1&&!pair.typed.physical->stamped,"failed writer cannot leave a successful synthetic native cookie");
}
void pendingRelease(){
 Pair pair;need(NrdBridgeLifetime::EnableConcurrentReleases(),"concurrent generation-aware release mode enabled");
 const auto t=NrdBridgeNativeBirth::Receiver(static_cast<ID3D12Object*>(&pair.typed));need(t&&t->CacheAdmissible(),"typed receiver cache warmed");
 pair.typed.physical->refs=2;Gate probe;ULONG result=0;unsigned calls=0;
 std::thread worker([&]{result=NrdBridgeRelease::Title(static_cast<IUnknown*>(&pair.canonical),[&](IUnknown* p){if(++calls==1)probe.wait();return Canonical::original(p);});});
 const bool entered=probe.reached();if(!entered){probe.release();worker.join();}need(entered,"native nonfinal release probe paused with physical counter live");
 const auto beforeQ=qiCalls.load(),beforeG=privateReads.load();const auto same=NrdBridgeNativeBirth::Receiver(static_cast<ID3D12Object*>(&pair.typed));
 const bool denied=same==t&&!same->CacheAdmissible()&&qiCalls>beforeQ&&privateReads>beforeG;probe.release();worker.join();
 need(denied,"pending alias Release rejects warmed cache and forces strong native validation");
 need(result==1&&t->Live()&&t->CacheAdmissible(),"nonfinal native Release leaves exact typed identity reusable afterward");
}
void currentSequence(){
 Pair pair;const auto old=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&pair.typed));publish(old);Token newer;unsigned calls=0;
 const auto result=NrdBridgeRelease::Title(static_cast<ID3D12Object*>(&pair.typed),[&](ID3D12Object* p){
  if(++calls==2){NrdBridgeNativeBirth::RetirementScope e;newer=NrdBridgeBirth::ObserveInstance(p,old->InstanceStamp());publish(newer);}
  return Typed::original(p);
 });
 need(newer&&newer!=old&&newer->InstanceStamp()==old->InstanceStamp(),"same physical cookie reobserved with a new logical sequence after pre-retire");
 need(result==0&&!old->Live()&&!newer->Live()&&rows.empty(),"actual final Release retires newest same-cookie typed sequence and canonical aliases");
}
void recycledAddress(){
 Pair pair;const auto old=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&pair.typed));publish(old);Token fresh;unsigned calls=0;
 const auto result=NrdBridgeRelease::Title(static_cast<ID3D12Object*>(&pair.typed),[&](ID3D12Object* p){
  const auto value=Typed::original(p);if(++calls==2){pair.typed.physical=std::make_shared<Physical>();pair.canonical.physical=pair.typed.physical;fresh=NrdBridgeNativeBirth::Prepare(p);publish(fresh);}return value;
 });
 need(result==0&&fresh&&fresh->InstanceStamp()!=old->InstanceStamp()&&fresh->Live()&&rows.at(&pair.typed)==fresh,"late old physical-final callback preserves new canonical/typed cookie at recycled addresses");
 need(NrdBridgeBirth::Capture(&pair.canonical)->InstanceStamp()==fresh->InstanceStamp(),"recycled canonical node retains the fresh physical cookie");
}
void missingForwarded(){
 Pair pair;Forwarded inner;inner.physical=pair.typed.physical;inner.typed=&pair.typed;inner.canonical=&pair.canonical;
 pair.typed.covered=pair.canonical.covered=true;pair.typed.forwarded=pair.canonical.forwarded=&inner;
 need(pair.canonical.Release()==0&&pair.typed.physical->refs==0,"forwarded different-This original caller still reaches exactly one physical final Release");
 need(privateWrites==0&&rows.empty()&&NrdBridgeBirth::Healthy(),"missing-cookie forwarded recovery neither synthesizes birth nor fails healthy metadata");
 need(qiCalls>1&&qiCalls<128&&inner.releases<256,"same active inner This recovery terminates without suppressing forwarded native Release");
}
void warmReceiverBorrow(){
 Pair pair;const auto token=NrdBridgeNativeBirth::Receiver(static_cast<ID3D12Object*>(&pair.typed));need(token&&token->CacheAdmissible(),"receiver canonical identity warmed before legacy Borrow");
 const auto beforeNative=nativeCalls.load(),beforeQ=qiCalls.load(),beforeG=privateReads.load();unsigned coverage=0;Token cached,covered;allocations=0;
 {NrdBridgeLifetime::ScopedBorrow borrow;need(borrow.Acquired(),"legacy Borrow remains an ordinary physical gate");meter=true;
  cached=NrdBridgeNativeBirth::Receiver(static_cast<ID3D12Object*>(&pair.typed));
  covered=NrdBridgeNativeBirth::ReceiverWithReleaseCoverage(static_cast<ID3D12Object*>(&pair.typed),[&](auto*)noexcept{++coverage;return true;});meter=false;}
 need(cached==token&&covered==token&&coverage==0&&nativeCalls==beforeNative&&qiCalls==beforeQ&&privateReads==beforeG&&allocations==0,"valid warmed receivers under legacy Borrow perform zero native/bootstrap/allocation work");
}
void recoveryStack(){
#ifdef FSRD_CANONICAL_RECOVERY_STACK
 Pair pair;std::array<std::optional<NrdBridgeNativeBirth::Detail::RecoveryScope>,8> scopes;std::array<unsigned,9> addresses{};
 const auto before=failures.load();allocations=0;meter=true;
 for(unsigned i=0;i<scopes.size();++i)scopes[i].emplace(reinterpret_cast<IUnknown*>(&addresses[i]));
 NrdBridgeNativeBirth::Detail::RecoveryScope repeated(reinterpret_cast<IUnknown*>(&addresses[3]));
 const bool bounded=NrdBridgeNativeBirth::Detail::recoveryDepth==8&&!repeated.Entered();
 NrdBridgeNativeBirth::Detail::RecoveryScope overflow(reinterpret_cast<IUnknown*>(&addresses[8]));
 const bool denied=!overflow.Entered()&&NrdBridgeNativeBirth::Detail::recoveryDepth==8;
 for(unsigned i=unsigned(scopes.size());i;--i)scopes[i-1].reset();meter=false;
 need(bounded&&denied&&failures==before+1&&!NrdBridgeBirth::Healthy(),"eight unrelated recovery addresses fit; same-address recursion skips and a ninth fails closed");
 need(allocations==0&&NrdBridgeNativeBirth::Detail::recoveryDepth==0,"bounded recovery TLS stack allocates nothing and fully unwinds");
#else
 throw std::runtime_error("recovery stack is absent from immutable old-header final-only control");
#endif
}
void disabledHelpers(){
 Pair pair;unsigned coverage=0;allocations=0;meter=true;
 const auto a=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&pair.typed),false);
 const auto b=NrdBridgeNativeBirth::Receiver(static_cast<ID3D12Object*>(&pair.typed),false);
 const auto c=NrdBridgeNativeBirth::ReceiverWithReleaseCoverage(static_cast<ID3D12Object*>(&pair.typed),[&](auto*)noexcept{++coverage;return true;},false);meter=false;
 need(!a&&!b&&!c&&coverage==0&&nativeCalls==0&&qiCalls==0&&privateReads==0&&privateWrites==0&&allocations==0&&drains==0,"startup-OFF helpers allocate, dispatch, query, cover, and publish nothing");
}
int main(int argc,char** argv)try{
 SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);const std::string mode=argc>1?argv[1]:"final";
 if(mode!="off")need(NrdBridgeNativeBirth::ConfigureRetirement(factory,detach,notify),"native dispatcher configured");
 if(mode=="final")finalCanonical();else if(mode=="parallel")concurrentAliases();else if(mode=="warm")knownWarm();else if(mode=="recover")recoveredAlias();
 else if(mode=="off")disabledHelpers();else if(mode=="warm-receiver")warmReceiverBorrow();else if(mode=="recovery-stack")recoveryStack();
 else if(mode=="failed-writer")failedWriter();else if(mode=="pending-release")pendingRelease();else if(mode=="current-sequence")currentSequence();else if(mode=="recycled")recycledAddress();else if(mode=="forwarded")missingForwarded();
 else if(mode=="unsupported"){Pair p;denyCanonical=true;const auto t=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&p.typed));need(!t&&!NrdBridgeBirth::Healthy()&&rows.empty(),"unsupported canonical Release coverage denies weak birth admission");}
 else if(mode=="unsupported-typed"){Pair p;denyTyped=true;const auto t=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&p.typed));need(!t&&qiCalls==0&&privateReads==0&&privateWrites==0&&!NrdBridgeBirth::Healthy()&&rows.empty(),"unsupported typed Release denies canonical QI and weak publication");}
 else if(mode=="legacy-borrow"){Pair p;NrdBridgeLifetime::ScopedBorrow borrow(true);need(borrow.Acquired(),"legacy borrow acquired");const auto t=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&p.typed));need(!t&&qiCalls==0&&privateReads==0&&privateWrites==0&&!NrdBridgeBirth::Healthy(),"cold COM canonical bootstrap fails before QI under legacy Borrow without gate exemption");}
 else if(mode=="owned"){Pair p;FrameSurvey::owned=true;const auto t=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&p.typed));need(!t&&qiCalls==0&&privateReads==0&&privateWrites==0&&rows.empty(),"genuine owned source publishes no title birth or native canonical work");
 const auto r=NrdBridgeNativeBirth::Receiver(static_cast<ID3D12Object*>(&p.typed));unsigned coverage=0;const auto c=NrdBridgeNativeBirth::ReceiverWithReleaseCoverage(static_cast<ID3D12Object*>(&p.typed),[&](auto*)noexcept{++coverage;return true;});need(!r&&!c&&coverage==0&&nativeCalls==0,"owned receiver paths also bypass canonical queries and release coverage");}
 else throw std::runtime_error("unknown case");
 need(nativeUnderMetadata==0,"all native QI/private data/Release/factory/drain calls occur outside Birth guards");
 std::cout<<"{\"case\":\""<<mode<<"\",\"checks\":"<<checks<<",\"nativeUnderMetadata\":"<<nativeUnderMetadata<<",\"qi\":"<<qiCalls<<",\"writes\":"<<privateWrites<<"}\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}
'''


def generate(out):
    headers = Path(os.environ.get('FSRD_CANONICAL_HEADER_ROOT', ROOT/'OptiScaler/misc')).resolve()
    release = (headers/'NrdBridgeRelease_Dx12.h').read_text()
    title = release[release.index('namespace NrdBridgeRelease'):]
    source = CPP.replace('__HEADERS__', headers.as_posix()).replace('__TITLE__', title)
    stack = '#define FSRD_CANONICAL_RECOVERY_STACK 1' if 'class RecoveryScope' in (headers/'NrdBridgeNativeBirth_Dx12.h').read_text() else ''
    source = source.replace('__CANONICAL_STACK__', stack)
    assert '__TITLE__' not in source and '__CANONICAL_STACK__' not in source
    out.mkdir(parents=True, exist_ok=True)
    target = out/'canonical_alias.cpp'
    target.write_text(source, encoding='utf-8')
    contract = {'scope': __doc__, 'headers': str(headers), 'body_sha256': hashlib.sha256(title.encode()).hexdigest(),
                'header_sha256': {name: hashlib.sha256((headers/name).read_bytes()).hexdigest() for name in
                                  ['NrdBridgeNativeBirth_Dx12.h', 'NrdBridgeRelease_Dx12.h', 'NrdBridgeBirth_Dx12.h']},
                'lease_seam': 'explicit count-only Begin/End, no actual ledger/queue claim',
                'coverage_seam': 'explicit native Release forwarding adapter, no installed detours',
                'interface_contract': 'actual C++ IUnknown/ID3D12Object ABI; canonical identity stable and native refcounts/private byte store shared',
                'unsupported_boundary': 'never-observed noncanonical interface implementations cannot be promised interception; canonical and creator typed entries are covered before weak publication',
                'legacy_borrow_policy': 'cold real-COM bootstrap fails before QI without any physical gate exemption; validated warm receiver remains native-free'}
    (out/'contract.json').write_text(json.dumps(contract, indent=2), encoding='utf-8')
    return target, contract


def run():
    out = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', ROOT/'canonical_alias_output'))
    source, contract = generate(out)
    if '--prepare-only' in sys.argv:
        print(json.dumps({'source': str(source), 'title_sha256': contract['body_sha256'], 'compiled': False, 'executed': False}))
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fsrd_toolchain import compile_cpp
    exe=out/'canonical_alias.exe'
    build=compile_cpp(source, exe, ('bcrypt.lib', 'dxguid.lib'), (ROOT/'OptiScaler',))
    (out/'build.json').write_text(json.dumps(build, indent=2), encoding='utf-8')
    results=[]
    cases=['final'] if '--expect-old-failure' in sys.argv else ['final','parallel','warm','recover','unsupported','owned','legacy-borrow','failed-writer','pending-release','current-sequence','recycled','forwarded','off','warm-receiver','recovery-stack','unsupported-typed']
    for case in cases:
        result=subprocess.run([str(exe),case], capture_output=True, text=True, timeout=20)
        (out/(case+'.log')).write_text(result.stdout+result.stderr, encoding='utf-8')
        if '--expect-old-failure' in sys.argv:
            assert result.returncode==1 and 'final canonical IUnknown alias must retire typed metadata' in result.stderr
            values={'case':case, 'expected_failure':True, 'exit_code':result.returncode, 'assertion':result.stderr.strip()}
        else:
            result.check_returncode();values=json.loads(result.stdout);assert values['nativeUnderMetadata']==0
        results.append(values)
    answer={'scope':contract['scope'], 'cases':results, 'old_control': '--expect-old-failure' in sys.argv}
    (out/'result.json').write_text(json.dumps(answer, indent=2), encoding='utf-8')
    print(json.dumps(answer, indent=2))


if __name__=='__main__':
    run()
