"""Actual verified NativeReceiver headers over the canonical COM ABI CPU seams.

No installed Detours/native D3D12/game/provider/queue/GPU claim. The eight
distinct canonical/typed pairs intentionally exceed the real four-entry TLS.
--expect-miss-cold runs only the warm fanout proof against immutable f015 headers.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fsrd_nrd_canonical_alias import CPP as CANONICAL_CPP

CASES = ["fanout", "legacy-global-miss", "synthetic", "noncom", "third-alias",
         "pending", "inflight", "mark-inflight-unverified", "new-sequence", "recycled", "recycled-failed",
         "metadata-miss", "metadata-hit", "off", "owned"]

EXTRA = r'''
std::atomic<unsigned> coverageCalls=0;
void clearReceiverTls(){
 for(auto& entry:NrdBridgeNativeBirth::Detail::receiverCache)entry={};
}
void fanout(bool legacyBorrow){
 std::array<Pair,8> objects;std::array<Token,8> tokens;unsigned callerCoverage=0;
 for(unsigned i=0;i<objects.size();++i){
  tokens[i]=NrdBridgeNativeBirth::ReceiverWithReleaseCoverage(static_cast<ID3D12Object*>(&objects[i].typed),[&](auto* p)noexcept{++callerCoverage;return NrdBridgeNativeBirth::ObserveReleaseCoverage(p);});
  need(tokens[i]&&tokens[i]->Address()==&objects[i].typed,"first native proof preserves each exact typed address");
#ifdef FSRD_NATIVE_RECEIVER_VERIFIED
  const auto canonical=NrdBridgeBirth::Capture(&objects[i].canonical);
  need(tokens[i]->NativeReceiverVerified()&&canonical&&canonical->NativeReceiverVerified()&&canonical!=tokens[i],"successful COM proof certifies two distinct exact canonical/typed nodes");
#endif
 }
 const auto beforeQ=qiCalls.load(),beforeG=privateReads.load(),beforeW=privateWrites.load(),beforeN=nativeCalls.load(),beforeC=coverageCalls.load(),beforeCaller=callerCoverage;
 unsigned misses=0;allocations=0;std::optional<NrdBridgeLifetime::ScopedBorrow> borrow;
 if(legacyBorrow)borrow.emplace();
 meter=true;
 for(unsigned round=0;round<32;++round)for(unsigned i=0;i<objects.size();++i){
  const auto p=static_cast<ID3D12Object*>(&objects[i].typed);
  bool inTls=false;for(const auto& hit:NrdBridgeNativeBirth::Detail::receiverCache)if(hit.address==p)inTls=true;
  if(!inTls)++misses;
  const auto t=round%2?NrdBridgeNativeBirth::ReceiverWithReleaseCoverage(p,[&](auto* s)noexcept{++callerCoverage;return NrdBridgeNativeBirth::ObserveReleaseCoverage(s);}):NrdBridgeNativeBirth::Receiver(p);
  need(t==tokens[i],"verified global miss returns exact existing current typed token");
 }
 meter=false;
 need(misses==256,"eight-object rounds are actual four-entry TLS misses");
 need(qiCalls==beforeQ&&privateReads==beforeG&&privateWrites==beforeW&&nativeCalls==beforeN&&coverageCalls==beforeC&&callerCoverage==beforeCaller,"8 COM receivers after TLS eviction must make zero QI/GUID/coverage calls");
 need(allocations==0,"256 verified global misses allocate no C++ storage");
 if(legacyBorrow)need(borrow->Acquired()&&NrdBridgeBirth::Healthy(),"verified metadata-only misses preserve ordinary legacy Borrow with no gate exemption");
}
#ifdef FSRD_NATIVE_RECEIVER_VERIFIED
struct ByteObject{
 bool stamped=false;NrdBridgeNativeBirth::NativeStamp stamp{};
 HRESULT GetPrivateData(REFGUID guid,UINT* size,void* out){native();++privateReads;if(guid!=NrdBridgeNativeBirth::InstanceGuid||!stamped)return DXGI_ERROR_NOT_FOUND;*size=sizeof(stamp);std::memcpy(out,&stamp,sizeof(stamp));return S_OK;}
 HRESULT SetPrivateData(REFGUID guid,UINT size,const void* in){native();++privateWrites;if(guid!=NrdBridgeNativeBirth::InstanceGuid||size!=sizeof(stamp))return E_INVALIDARG;std::memcpy(&stamp,in,size);stamped=true;return S_OK;}
};
void synthetic(){
 Pair pair;pair.typed.physical->stamped=true;pair.typed.physical->stamp={NrdBridgeNativeBirth::Detail::ProcessNonce(),NrdBridgeBirth::AllocateInstanceStamp()};Token t,c;
 {NrdBridgeNativeBirth::RetirementScope e;t=NrdBridgeBirth::ObserveInstance(&pair.typed,pair.typed.physical->stamp.instanceStamp);c=NrdBridgeBirth::LinkAlias(t->InstanceStamp(),&pair.canonical);}
 need(t&&c&&t->CacheAdmissible()&&c->CacheAdmissible()&&!t->NativeReceiverVerified()&&!c->NativeReceiverVerified(),"generic Observe/LinkAlias never manufacture exact native proof");
 clearReceiverTls();const auto q=qiCalls.load(),g=privateReads.load(),v=coverageCalls.load(),w=privateWrites.load();
 const auto actual=NrdBridgeNativeBirth::Receiver(static_cast<ID3D12Object*>(&pair.typed));
 need(actual==t&&qiCalls>q&&privateReads>g&&coverageCalls>v&&privateWrites==w,"unmarked synthetic metadata must use native existing-GUID attestation");
 need(t->NativeReceiverVerified()&&c->NativeReceiverVerified(),"COM re-attestation marks both exact current nodes");
}
void noncom(){
 ByteObject object;const auto t=NrdBridgeNativeBirth::Prepare(&object);
 need(t&&t->Ready()&&!t->NativeReceiverVerified()&&qiCalls==0&&coverageCalls==0,"non-COM byte protocol never certifies COM native receiver coverage");
 clearReceiverTls();const auto g=privateReads.load();need(NrdBridgeNativeBirth::Receiver(&object)==t&&privateReads>g&&!t->NativeReceiverVerified(),"non-COM global miss remains on existing cold byte protocol");
}
struct Third:Typed{
 static inline volatile ULONG tag=0;
 static ULONG thirdOriginal(ID3D12Object* p){return static_cast<Third*>(p)->raw()+tag;}
 ULONG STDMETHODCALLTYPE Release()override{return NrdBridgeRelease::Title(static_cast<ID3D12Object*>(this),thirdOriginal);}
};
void thirdAlias(){
 Pair pair;const auto t=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&pair.typed));Third third;third.physical=pair.typed.physical;third.canonical=&pair.canonical;Token alias;
 {NrdBridgeNativeBirth::RetirementScope e;alias=NrdBridgeBirth::LinkAlias(t->InstanceStamp(),static_cast<ID3D12Object*>(&third));}
 need(t->NativeReceiverVerified()&&alias&&alias->CacheAdmissible()&&!alias->NativeReceiverVerified(),"third same-cookie alias does not inherit a physical-wide proof");
 clearReceiverTls();const auto q=qiCalls.load(),g=privateReads.load(),c=coverageCalls.load();unsigned caller=0;
 const auto denied=NrdBridgeNativeBirth::ReceiverWithReleaseCoverage(static_cast<ID3D12Object*>(&third),[&](auto* p)noexcept{++caller;return NrdBridgeNativeBirth::ObserveReleaseCoverage(p);});
 need(!denied&&caller==1&&coverageCalls==c+1&&qiCalls==q&&privateReads==g&&NrdBridgeBirth::Healthy(),"uncovered third native entry remains cold and fails caller coverage before QI");
}
void pendingProof(){
 Pair pair;Typed other;other.physical=pair.typed.physical;other.canonical=&pair.canonical;pair.typed.physical->refs=2;Gate setter;pair.typed.physical->setter=&setter;Token a,b;
 std::thread first([&]{a=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&pair.typed));});const bool entered=setter.reached();if(!entered){setter.release();first.join();}need(entered,"canonical native setter paused during initializer");
 b=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&other));const bool quarantined=b&&b->Initializing()&&!b->NativeReceiverVerified();setter.release();first.join();pair.typed.physical->setter=nullptr;
 need(quarantined&&a&&a->NativeReceiverVerified()&&b->Ready()&&!b->NativeReceiverVerified(),"FinishPendingAliases makes ready but never certifies an unobserved pending typed proof");
 clearReceiverTls();const auto q=qiCalls.load(),g=privateReads.load();const auto ready=NrdBridgeNativeBirth::Receiver(static_cast<ID3D12Object*>(&other));
 need(ready==b&&qiCalls>q&&privateReads>g&&b->NativeReceiverVerified(),"ready pending alias requires successful COM re-attestation before global proof");
}
void inFlightProof(){
 Pair pair;const auto t=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&pair.typed));clearReceiverTls();const auto q=qiCalls.load(),g=privateReads.load();
 {NrdBridgeBirth::ScopedRelease pending(t);const auto actual=NrdBridgeNativeBirth::Receiver(static_cast<ID3D12Object*>(&pair.typed));
  need(actual==t&&qiCalls>q&&privateReads>g&&!actual->CacheAdmissible(),"physical pending Release denies verified global cache and forces native protocol");}
 need(t->CacheAdmissible()&&NrdBridgeBirth::Healthy(),"in-flight false negative does not poison healthy metadata");
}
void unverifiedInFlightProof(){
 Pair pair;pair.typed.physical->stamped=true;pair.typed.physical->stamp={NrdBridgeNativeBirth::Detail::ProcessNonce(),NrdBridgeBirth::AllocateInstanceStamp()};Token t,c;
 {NrdBridgeNativeBirth::RetirementScope e;t=NrdBridgeBirth::ObserveInstance(&pair.typed,pair.typed.physical->stamp.instanceStamp);c=NrdBridgeBirth::LinkAlias(t->InstanceStamp(),&pair.canonical);}
 need(t&&c&&t->CacheAdmissible()&&c->CacheAdmissible()&&!t->NativeReceiverVerified()&&!c->NativeReceiverVerified(),"inflight marker control begins with two ready unverified generic nodes");
 clearReceiverTls();const auto q=qiCalls.load(),g=privateReads.load(),v=coverageCalls.load(),w=privateWrites.load();
 {NrdBridgeBirth::ScopedRelease pending(t);
  need(!t->CacheAdmissible()&&!c->CacheAdmissible(),"pending physical Release blocks borrow admission on both exact aliases");
  const auto actual=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&pair.typed));
  need(actual==t&&qiCalls>q&&privateReads>g&&coverageCalls>v&&privateWrites==w,"inflight unverified control executes actual cold COM existing-GUID proof");
  need(!t->NativeReceiverVerified()&&!c->NativeReceiverVerified()&&!t->CacheAdmissible()&&!c->CacheAdmissible()&&NrdBridgeBirth::Healthy(),"denied exact-current Mark keeps both witnesses false without health failure");}
 need(t->CacheAdmissible()&&c->CacheAdmissible()&&!t->NativeReceiverVerified()&&!c->NativeReceiverVerified()&&NrdBridgeBirth::Healthy(),"ending pending Release restores admission without manufacturing verification");
 clearReceiverTls();const auto freshQ=qiCalls.load(),freshG=privateReads.load(),freshV=coverageCalls.load();unsigned caller=0;
 const auto current=NrdBridgeNativeBirth::ReceiverWithReleaseCoverage(static_cast<ID3D12Object*>(&pair.typed),[&](auto* p)noexcept{++caller;return NrdBridgeNativeBirth::ObserveReleaseCoverage(p);});
 need(current==t&&caller==1&&qiCalls>freshQ&&privateReads>freshG&&coverageCalls>freshV&&privateWrites==w,"after pending count reaches zero the global miss must re-attest instead of reusing false witnesses");
 need(t->NativeReceiverVerified()&&c->NativeReceiverVerified()&&NrdBridgeBirth::Healthy(),"successful retry certifies both exact nodes after pending Release ends");
 clearReceiverTls();const auto warmN=nativeCalls.load(),warmQ=qiCalls.load(),warmG=privateReads.load(),warmV=coverageCalls.load();caller=0;allocations=0;meter=true;
 const auto warmed=NrdBridgeNativeBirth::ReceiverWithReleaseCoverage(static_cast<ID3D12Object*>(&pair.typed),[&](auto* p)noexcept{++caller;return NrdBridgeNativeBirth::ObserveReleaseCoverage(p);});meter=false;
 need(warmed==t&&nativeCalls==warmN&&qiCalls==warmQ&&privateReads==warmG&&privateWrites==w&&coverageCalls==warmV&&caller==0&&allocations==0,"fresh successful proof permits the next actual TLS miss with zero native/query/coverage/allocation work");
}
void newSequence(){
 Pair pair;const auto old=NrdBridgeNativeBirth::Prepare(static_cast<ID3D12Object*>(&pair.typed));Token fresh;
 {NrdBridgeNativeBirth::RetirementScope e;{NrdBridgeBirth::CurrentGuard g(old);need(g.Retire(),"old exact sequence pre-retired");}fresh=NrdBridgeBirth::ObserveInstance(&pair.typed,old->InstanceStamp());}
 need(fresh&&fresh!=old&&fresh->InstanceStamp()==old->InstanceStamp()&&!fresh->NativeReceiverVerified()&&!old->Live(),"same-cookie new logical sequence never inherits verified witness");
 clearReceiverTls();const auto q=qiCalls.load(),g=privateReads.load();const auto current=NrdBridgeNativeBirth::Receiver(static_cast<ID3D12Object*>(&pair.typed));
 need(current==fresh&&qiCalls>q&&privateReads>g&&fresh->NativeReceiverVerified(),"same-cookie fresh sequence is re-attested through COM before reuse");
}
void recycledProof(bool fail){
 Pair pair;const auto old=NrdBridgeNativeBirth::Receiver(static_cast<ID3D12Object*>(&pair.typed));
 need(pair.typed.Release()==0&&!old->Live(),"actual Title final0 retires verified old canonical and typed nodes");
 pair.typed.physical=std::make_shared<Physical>();pair.canonical.physical=pair.typed.physical;if(fail)pair.typed.physical->writeResult=E_FAIL;
 const auto q=qiCalls.load(),g=privateReads.load();const auto current=NrdBridgeNativeBirth::Receiver(static_cast<ID3D12Object*>(&pair.typed));
 if(fail){const auto failed=NrdBridgeBirth::Capture(&pair.canonical);need(!current&&failed&&!failed->Ready()&&!failed->NativeReceiverVerified()&&!NrdBridgeBirth::Healthy()&&qiCalls>q&&privateReads>g,"failed recycled-instance writer cannot reuse an old verified node or mark failed new node");}
 else need(current&&current!=old&&current->InstanceStamp()!=old->InstanceStamp()&&current->NativeReceiverVerified()&&qiCalls>q&&privateReads>g,"different-cookie address reuse forces native proof before marking new generation");
}
void metadataProof(bool hit){
 Pair pair;const auto t=NrdBridgeNativeBirth::Receiver(static_cast<ID3D12Object*>(&pair.typed));if(!hit)clearReceiverTls();const auto n=nativeCalls.load(),q=qiCalls.load(),g=privateReads.load();Token actual;
 {NrdBridgeBirth::CurrentGuard guard(t);need(guard.MatchesCurrent(),"metadata guard holds exact current receiver");actual=NrdBridgeNativeBirth::Receiver(static_cast<ID3D12Object*>(&pair.typed));}
 need(nativeCalls==n&&qiCalls==q&&privateReads==g,"metadata receiver lookup never enters native COM");
 if(hit)need(actual==t&&NrdBridgeBirth::Healthy(),"existing four-entry TLS hits stay metadata-only and unchanged");
 else need(!actual&&!NrdBridgeBirth::Healthy(),"global TLS miss cannot capture/wait beneath metadata guard and preserves cold fail policy");
}
#endif
void disabledProof(bool owned){
 Pair pair;FrameSurvey::owned=owned;unsigned calls=0;allocations=0;meter=true;
 const auto a=NrdBridgeNativeBirth::Receiver(static_cast<ID3D12Object*>(&pair.typed),owned);
 const auto b=NrdBridgeNativeBirth::ReceiverWithReleaseCoverage(static_cast<ID3D12Object*>(&pair.typed),[&](auto*)noexcept{++calls;return true;},owned);meter=false;
 need(!a&&!b&&calls==0&&nativeCalls==0&&qiCalls==0&&privateReads==0&&allocations==0&&NrdBridgeBirth::Detail::constructedRegistries==0,"OFF/owned bypass occurs before TLS/global registry and native work");
}
int main(int argc,char** argv)try{
 SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);const std::string mode=argc>1?argv[1]:"fanout";
 if(mode!="off"&&mode!="owned")need(NrdBridgeNativeBirth::ConfigureRetirement(factory,detach,notify),"actual native dispatcher configured");
 if(mode=="fanout")fanout(false);else if(mode=="legacy-global-miss")fanout(true);
#ifdef FSRD_NATIVE_RECEIVER_VERIFIED
 else if(mode=="synthetic")synthetic();else if(mode=="noncom")noncom();else if(mode=="third-alias")thirdAlias();
 else if(mode=="pending")pendingProof();else if(mode=="inflight")inFlightProof();else if(mode=="mark-inflight-unverified")unverifiedInFlightProof();else if(mode=="new-sequence")newSequence();
 else if(mode=="recycled")recycledProof(false);else if(mode=="recycled-failed")recycledProof(true);
 else if(mode=="metadata-miss")metadataProof(false);else if(mode=="metadata-hit")metadataProof(true);
#endif
 else if(mode=="off")disabledProof(false);else if(mode=="owned")disabledProof(true);else throw std::runtime_error("case requires current verified-receiver header");
 need(nativeUnderMetadata==0,"native proof/query/Release remains outside metadata");
 std::cout<<"{\"case\":\""<<mode<<"\",\"checks\":"<<checks<<",\"nativeUnderMetadata\":"<<nativeUnderMetadata<<",\"qi\":"<<qiCalls<<",\"get\":"<<privateReads<<",\"coverage\":"<<coverageCalls<<",\"allocations\":"<<allocations<<"}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}
'''


def generate(out):
    headers = Path(os.environ.get("FSRD_VERIFIED_HEADER_ROOT", ROOT/"OptiScaler/misc")).resolve()
    native = (headers/"NrdBridgeNativeBirth_Dx12.h").read_text()
    release = (headers/"NrdBridgeRelease_Dx12.h").read_text()
    title = release[release.index("namespace NrdBridgeRelease"):]
    support = CANONICAL_CPP[:CANONICAL_CPP.index("int main(")]
    support = support.replace("bool NrdBridgeNativeBirth::ObserveReleaseCoverage(IUnknown* p)noexcept{\n native();",
                              "bool NrdBridgeNativeBirth::ObserveReleaseCoverage(IUnknown* p)noexcept{\n native();++coverageCalls;")
    support = support.replace("Typed* currentTyped=nullptr;", "extern std::atomic<unsigned> coverageCalls;\nTyped* currentTyped=nullptr;")
    assert "native();++coverageCalls;" in support
    source = (support+EXTRA).replace("__HEADERS__", headers.as_posix()).replace("__TITLE__", title)
    flags = "#define FSRD_NATIVE_RECEIVER_VERIFIED 1" if "nativeReceiverVerified_" in (headers/"NrdBridgeBirth_Dx12.h").read_text() else ""
    if "class RecoveryScope" in native:
        flags += "\n#define FSRD_CANONICAL_RECOVERY_STACK 1"
    source = source.replace("__CANONICAL_STACK__", flags)
    assert "__TITLE__" not in source and "__CANONICAL_STACK__" not in source
    out.mkdir(parents=True, exist_ok=True)
    target = out/"native_receiver_verified.cpp"
    target.write_text(source, encoding="utf-8")
    contract = {"scope": __doc__, "headers": str(headers), "cases": CASES,
                "header_sha256": {n: hashlib.sha256((headers/n).read_bytes()).hexdigest() for n in
                                  ["NrdBridgeBirth_Dx12.h", "NrdBridgeNativeBirth_Dx12.h", "NrdBridgeRelease_Dx12.h"]},
                "actual_title_sha256": hashlib.sha256(title.encode()).hexdigest(),
                "source_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "unchanged_canonical_fixture": True, "unchanged_born_fixture": True,
                "four_entry_hit_logic_changed": False, "real_native_d3d12_or_gpu": False}
    (out/"contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
    return target, contract


def run():
    out = Path(os.environ.get("FSRD_GPU_TEST_OUTPUT", ROOT/"native_receiver_verified_output"))
    source, contract = generate(out)
    if "--prepare-only" in sys.argv:
        print(json.dumps({"source": str(source), "cases": len(CASES), "compiled": False, "executed": False}))
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fsrd_toolchain import compile_cpp
    exe = out/"native_receiver_verified.exe"
    build = compile_cpp(source, exe, ("bcrypt.lib", "dxguid.lib"), (ROOT/"OptiScaler",))
    (out/"build.json").write_text(json.dumps(build, indent=2), encoding="utf-8")
    results = []
    for case in ["fanout"] if "--expect-miss-cold" in sys.argv else CASES:
        result = subprocess.run([str(exe), case], capture_output=True, text=True, timeout=30)
        (out/(case+".log")).write_text(result.stdout+result.stderr, encoding="utf-8")
        if "--expect-miss-cold" in sys.argv:
            assert result.returncode == 1 and "8 COM receivers after TLS eviction must make zero QI/GUID/coverage calls" in result.stderr
            values = {"case": case, "expected_failure": True, "exit_code": result.returncode, "assertion": result.stderr.strip()}
        else:
            result.check_returncode()
            values = json.loads(result.stdout)
            assert values["nativeUnderMetadata"] == 0
        results.append(values)
    result = {"scope": contract["scope"], "checks": sum(r.get("checks", 0) for r in results),
              "cases": results, "old_control": "--expect-miss-cold" in sys.argv}
    (out/"result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run()