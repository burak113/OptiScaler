"""Actual native-instance helper with deterministic native byte-data adapters.

CPU-only. FakeNative models ID3D12Object byte getter/setter and address reuse;
no runtime D3D12 object, actual hook detour, native COM or GPU claim is made.
Separate negative processes preserve the irreversible metadata health latch.
"""
from pathlib import Path
import json
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp
ROOT = Path(__file__).resolve().parents[4]

CPP = r'''
#define NOMINMAX
#include <windows.h>
#include "__ROOT__/OptiScaler/misc/NrdBridgeNativeBirth_Dx12.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <atomic>
#include <condition_variable>
#include <cstring>
#include <functional>
#include <iostream>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
unsigned checks=0;
void need(bool value,const char* message){if(!value)throw std::runtime_error(message);++checks;}
std::atomic<unsigned> nativeUnderGuard=0,observerUnderGuard=0,factoryUnderGuard=0,notifyUnderGuard=0;
std::atomic<unsigned> factories=0,notifications=0,detachCalls=0,healthFailures=0,titleRefs=0;
bool failFactory=false;
namespace FrameSurvey {
 void MetadataHookFailed(const char*) noexcept { if(NrdBridgeBirth::InMetadataScope())++observerUnderGuard;++healthFailures; }
}
struct Payload { std::array<NrdBridgeBirth::Token,32> retired;size_t count=0; };
std::atomic<Payload*> lastFactory=nullptr;
void* makePayload() noexcept {
 if(NrdBridgeBirth::InMetadataScope())++factoryUnderGuard;
 ++factories;if(failFactory)return nullptr;
 auto* payload=new(std::nothrow) Payload;lastFactory.store(payload);return payload;
}
bool detach(void* state,const NrdBridgeBirth::Token& node) noexcept {
 ++detachCalls;auto* payload=static_cast<Payload*>(state);
 if(!NrdBridgeBirth::InMetadataAction()||!payload||payload->count==payload->retired.size())return false;
 payload->retired[payload->count++]=node;return true;
}
void notify(void* state) noexcept {
 if(NrdBridgeBirth::InMetadataScope())++notifyUnderGuard;
 ++notifications;delete static_cast<Payload*>(state);
}
struct NativeData { std::mutex mutex;bool present=false;NrdBridgeNativeBirth::NativeStamp value; };
struct FakeNative {
 std::shared_ptr<NativeData> data=std::make_shared<NativeData>();
 std::atomic<unsigned> reads=0,writes=0;
 HRESULT readResult=S_OK,writeResult=S_OK;UINT returnedSize=sizeof(NrdBridgeNativeBirth::NativeStamp);
 std::function<void()> afterRead,beforeWrite;
 HRESULT GetPrivateData(REFGUID guid,UINT* bytes,void* output){
  if(NrdBridgeBirth::InMetadataScope())++nativeUnderGuard;
  ++reads;if(guid!=NrdBridgeNativeBirth::InstanceGuid)return E_INVALIDARG;
  bool present=false;NrdBridgeNativeBirth::NativeStamp value;
  {std::lock_guard lock(data->mutex);present=data->present;value=data->value;}
  if(afterRead)afterRead();
  if(FAILED(readResult))return readResult;
  if(!present)return DXGI_ERROR_NOT_FOUND;
  if(*bytes<returnedSize){*bytes=returnedSize;return DXGI_ERROR_MORE_DATA;}
  *bytes=returnedSize;std::memcpy(output,&value,std::min(size_t(returnedSize),sizeof(value)));return S_OK;
 }
 HRESULT SetPrivateData(REFGUID guid,UINT bytes,const void* input){
  if(NrdBridgeBirth::InMetadataScope())++nativeUnderGuard;
  ++writes;if(beforeWrite)beforeWrite();
  if(FAILED(writeResult))return writeResult;
  if(guid!=NrdBridgeNativeBirth::InstanceGuid||bytes!=sizeof(NrdBridgeNativeBirth::NativeStamp))return E_INVALIDARG;
  std::lock_guard lock(data->mutex);data->present=true;std::memcpy(&data->value,input,sizeof(data->value));return S_OK;
 }
 ULONG AddRef(){++titleRefs;return 2;}ULONG Release(){++titleRefs;return 1;}
};
struct Gate{
 std::mutex mutex;std::condition_variable cv;bool entered=false,open=false;
 void wait(){std::unique_lock lock(mutex);entered=true;cv.notify_all();cv.wait(lock,[&]{return open;});}
 bool reached(){std::unique_lock lock(mutex);return cv.wait_for(lock,std::chrono::seconds(2),[&]{return entered;});}
 void release(){std::lock_guard lock(mutex);open=true;cv.notify_all();}
};
void positive(){
 std::array<FakeNative,5> objects;
 std::array<NrdBridgeBirth::Token,5> tokens;
 for(unsigned i=0;i<4;++i)tokens[i]=NrdBridgeNativeBirth::Receiver(&objects[i]);
 const auto initialFactories=factories.load();const auto initialReads=objects[0].reads.load();
 for(unsigned i=0;i<10000;++i)if(NrdBridgeNativeBirth::Receiver(&objects[0])!=tokens[0])throw std::runtime_error("hot receiver token changed");
 need(factories==initialFactories&&objects[0].reads==initialReads,"four-entry hot receiver performs no native read or retirement allocation");
 need(NrdBridgeNativeBirth::Detail::receiverCache.size()==4,"cache has exactly four entries shared across receiver types");
 for(unsigned i=0;i<4;++i)need(tokens[i]&&tokens[i]->Admissible()&&objects[i].writes==1,"first native election becomes ready after one byte stamp write");
 const auto interned=NrdBridgeNativeBirth::Prepare(&objects[0]);
 need(interned==tokens[0]&&interned->Sequence()==tokens[0]->Sequence()&&objects[0].writes==1,"interned same native GUID preserves sequence and physical stamp");
 FakeNative alias;alias.data=objects[0].data;const auto aliasNode=NrdBridgeNativeBirth::Prepare(&alias);
 need(aliasNode&&aliasNode->InstanceStamp()==tokens[0]->InstanceStamp()&&aliasNode->Sequence()!=tokens[0]->Sequence(),"native data shared by proven aliases preserves physical identity without pointer equality");
 {NrdBridgeBirth::ScopedRelease release(tokens[0]);need(aliasNode->ReleasesInFlight()==1&&!NrdBridgeBirth::CacheAdmissible(aliasNode),"alias shares physical release counter");}
 need(aliasNode->ReleasesInFlight()==0&&aliasNode->CacheAdmissible(),"completed native release restores cache eligibility");
 tokens[4]=NrdBridgeNativeBirth::Receiver(&objects[4]);const auto beforeEvicted=objects[0].reads.load();
 need(NrdBridgeNativeBirth::Receiver(&objects[0])==tokens[0]&&objects[0].reads>beforeEvicted,"fifth receiver evicts an entry and verifies its native stamp on reuse");
 {
  NrdBridgeBirth::ScopedRelease release(tokens[0]);const auto reads=objects[0].reads.load();
  need(NrdBridgeNativeBirth::Receiver(&objects[0])==tokens[0]&&objects[0].reads==reads+1,"in-flight Release prevents a cached receiver from skipping native identity verification");
 }
 FakeNative stale;Gate getter;std::atomic<bool> firstRead=true;
 stale.afterRead=[&]{if(firstRead.exchange(false))getter.wait();};
 NrdBridgeBirth::Token delayed;
 std::thread oldRead([&]{delayed=NrdBridgeNativeBirth::Prepare(&stale);});
 const bool gotZero=getter.reached();const auto winner=NrdBridgeNativeBirth::Prepare(&stale);getter.release();oldRead.join();
 need(gotZero&&winner&&delayed==winner&&stale.writes==1,"stale zero with captured nil loses exact election and re-observes winner without a second write");
 FakeNative initializer;Gate writer,reader;std::atomic<bool> firstWrite=true,readerBlock=false;
 initializer.beforeWrite=[&]{if(firstWrite.exchange(false))writer.wait();};
 NrdBridgeBirth::Token elected,readPending;
 std::thread initialize([&]{elected=NrdBridgeNativeBirth::Prepare(&initializer);});
 const bool started=writer.reached();const auto pending=NrdBridgeBirth::Capture(&initializer);
 initializer.afterRead=[&]{if(readerBlock.exchange(false))reader.wait();};readerBlock=true;
 std::thread observe([&]{readPending=NrdBridgeNativeBirth::Prepare(&initializer);});
 const bool pendingRead=reader.reached();writer.release();initialize.join();reader.release();observe.join();
 need(started&&pendingRead&&pending&&pending->Ready()&&elected==pending&&readPending==pending&&initializer.writes==1,"zero read captured initializing before getter reuses same candidate after writer finishes");
 FakeNative retiredInitializer;Gate heldWriter,heldReader;std::atomic<bool> oneWrite=true,oneRead=false;
 retiredInitializer.beforeWrite=[&]{if(oneWrite.exchange(false))heldWriter.wait();};
 NrdBridgeBirth::Token initializedAgain,observedAgain;
 std::thread initialWriter([&]{initializedAgain=NrdBridgeNativeBirth::Prepare(&retiredInitializer);});
 const bool initialPending=heldWriter.reached();const auto priorCandidate=NrdBridgeBirth::Capture(&retiredInitializer);
 retiredInitializer.afterRead=[&]{if(oneRead.exchange(false))heldReader.wait();};oneRead=true;
 std::thread initialReader([&]{observedAgain=NrdBridgeNativeBirth::Prepare(&retiredInitializer);});
 const bool oldZero=heldReader.reached();bool preRetired=false;
 {NrdBridgeNativeBirth::RetirementScope effects;preRetired=NrdBridgeBirth::RetireCurrentInstance(priorCandidate);}
 heldWriter.release();initialWriter.join();heldReader.release();initialReader.join();
 need(initialPending&&oldZero&&preRetired&&initializedAgain&&observedAgain==initializedAgain&&initializedAgain!=priorCandidate&&initializedAgain->InstanceStamp()==priorCandidate->InstanceStamp()&&retiredInitializer.writes==1,"retired pending sequence cannot authorize stale zero but written native stamp is safely re-observed");
 bool finalRetired=false;
 {NrdBridgeNativeBirth::RetirementScope effects;finalRetired=NrdBridgeBirth::RetireCurrentInstance(priorCandidate);}
 need(finalRetired&&!initializedAgain->Live()&&!NrdBridgeBirth::Capture(&retiredInitializer),"actual zero old ticket retires current new sequence with SAME physical native stamp");
 FakeNative recycled;const auto old=NrdBridgeNativeBirth::Receiver(&recycled);NrdBridgeBirth::Token fresh;
 {NrdBridgeBirth::ScopedRelease release(old);
  recycled.data=std::make_shared<NativeData>(); // Native allocation recycled before old post-zero callback.
  fresh=NrdBridgeNativeBirth::Receiver(&recycled);
  need(fresh&&fresh!=old&&fresh->InstanceStamp()!=old->InstanceStamp()&&!old->Live(),"in-flight old release forces zero read and fresh stamp for reused address");
  NrdBridgeNativeBirth::RetirementScope effects;
  need(!NrdBridgeBirth::RetireCurrentInstance(old)&&fresh->Live(),"old physical-final ticket cannot retire recycled address with DIFFERENT native stamp");
 }
 need(fresh->CacheAdmissible(),"new physical instance is independently cache eligible after old release returns");
 FakeNative foreign;foreign.data->present=true;foreign.data->value={~NrdBridgeNativeBirth::Detail::ProcessNonce(),123};
 const auto foreignFresh=NrdBridgeNativeBirth::Prepare(&foreign);
 need(foreignFresh&&foreignFresh->Ready()&&foreign.writes==1&&foreign.data->value.processNonce==NrdBridgeNativeBirth::Detail::ProcessNonce(),"foreign session nonce elects a current process physical stamp");
 need(NrdBridgeBirth::Healthy()&&healthFailures==0,"all valid cold/hot/interleaved protocols preserve metadata health");
 need(nativeUnderGuard==0&&observerUnderGuard==0&&factoryUnderGuard==0&&notifyUnderGuard==0,"native methods/factories/observers/owner drain never run under Birth locks");
 need(titleRefs==0,"native byte stamps retain zero title COM references");
 need(factories==notifications,"every successful retirement payload drains exactly once outside guards");
}
void negative(const std::string& kind){
 FakeNative object;
 if(kind=="factory"){
  failFactory=true;need(!NrdBridgeNativeBirth::Prepare(&object)&&object.reads==0&&object.writes==0,"factory failure denies native operation before metadata mutation");
 }else if(kind=="read"){
  object.readResult=E_FAIL;need(!NrdBridgeNativeBirth::Prepare(&object)&&object.reads==1&&object.writes==0,"failed native GUID getter fails closed without native stamp write");
 }else if(kind=="write"){
  object.writeResult=E_OUTOFMEMORY;need(!NrdBridgeNativeBirth::Prepare(&object),"failed GUID write cannot return an admissible receiver");
  const auto failed=NrdBridgeBirth::Capture(&object);need(failed&&failed->Failed()&&!failed->Ready()&&!failed->CacheAdmissible(),"failed initializer remains rejected by all cached/borrow gates");
 }else if(kind=="size"){
  object.data->present=true;object.returnedSize=8;need(!NrdBridgeNativeBirth::Prepare(&object)&&object.writes==0,"malformed reserved data size is rejected without overwrite");
 }else if(kind=="missing-scope"){
  const auto node=NrdBridgeNativeBirth::Prepare(&object);need(bool(node),"negative control begins with valid receiver");
  const auto changed=NrdBridgeBirth::ObserveInstance(&object,NrdBridgeBirth::AllocateInstanceStamp());
  need(!changed&&!NrdBridgeBirth::Healthy()&&healthFailures==0,"missing retirement scope fails inside action but queues observer until outside");
  NrdBridgeNativeBirth::FlushFailure();need(healthFailures==1,"queued missing-scope failure observer drains outside Birth lock");
 }else if(kind=="under-guard"){
  const auto node=NrdBridgeNativeBirth::Prepare(&object);const auto reads=object.reads.load();
  {NrdBridgeBirth::CurrentGuard guard(node);need(!NrdBridgeNativeBirth::Prepare(&object)&&object.reads==reads&&healthFailures==0,"getter attempted under Birth guard is denied without native calls/observer reentry");}
  NrdBridgeNativeBirth::FlushFailure();need(healthFailures==1,"guard failure observer runs only after guard ends");
 }else if(kind=="wrong-lifetime"){
  const auto node=NrdBridgeNativeBirth::Prepare(&object);const auto drained=notifications.load();
  auto scope=std::make_unique<NrdBridgeNativeBirth::RetirementScope>();auto* pinned=lastFactory.load();
  {NrdBridgeBirth::CurrentGuard guard(node);scope.reset();need(notifications==drained&&healthFailures==0,"wrong lexical lifetime pins payload and queues diagnostics rather than destroying under guard");}
  NrdBridgeNativeBirth::FlushFailure();need(healthFailures==1,"bad lexical scope diagnostic is deferred outside guard");delete pinned;
 }else throw std::runtime_error("unknown negative case");
 need(!NrdBridgeBirth::Healthy()&&healthFailures>=1,"negative protocol failure irreversibly latches metadata health");
 need(nativeUnderGuard==0&&observerUnderGuard==0&&factoryUnderGuard==0&&notifyUnderGuard==0,"negative cases cannot run native or failure observers under metadata guard");
 need(!NrdBridgeNativeBirth::Receiver(&object)&&!NrdBridgeNativeBirth::Prepare(&object),"latched failure denies later native receiver publication");
}
int main(int argc,char**argv)try{
 SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);
 const std::string kind=argc>1?argv[1]:"positive";
 if(kind=="off"){
  FakeNative object;need(!NrdBridgeNativeBirth::Prepare(&object,false)&&!NrdBridgeNativeBirth::Receiver(&object,false),"startup OFF preserves no native birth work");
  need(NrdBridgeBirth::Detail::constructedRegistries==0&&factories==0&&object.reads==0&&object.writes==0,"OFF constructs no registry/factory and performs no native private-data methods");
 }else{
  need(NrdBridgeNativeBirth::ConfigureRetirement(makePayload,detach,notify),"cold dispatcher registration succeeds");
  need(NrdBridgeNativeBirth::ConfigureRetirement(makePayload,detach,notify),"same cold dispatcher registration is idempotent");
  if(kind=="positive")positive();else negative(kind);
 }
 std::cout<<"{\"checks\":"<<checks<<",\"nativeCallsUnderBirth\":"<<nativeUnderGuard<<",\"failureObserversUnderBirth\":"<<observerUnderGuard<<",\"titleAddRefRelease\":"<<titleRefs<<"}\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}
'''

def main():
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(os.environ.get('TEMP', '.')) / 'fsrd_native_birth'
    out.mkdir(parents=True, exist_ok=True)
    source = out / 'native_birth.cpp'
    source.write_text(CPP.replace('__ROOT__', ROOT.as_posix()), encoding='utf-8')
    executable = out / 'native_birth.exe'
    includes = []
    protocol_root = os.environ.get('FSRD_BIRTH_PROTOCOL_ROOT')
    if protocol_root:
        includes.append(str(Path(protocol_root).resolve() / 'OptiScaler/misc'))
    build = compile_cpp(source, executable, libraries=['bcrypt.lib'], include_dirs=includes)
    (out / 'build.json').write_text(json.dumps(build, indent=2), encoding='utf-8')
    results = {}
    for case in ['off', 'positive', 'factory', 'read', 'write', 'size', 'missing-scope', 'under-guard', 'wrong-lifetime']:
        run = subprocess.run([str(executable), case], capture_output=True, text=True, timeout=30)
        (out / f'{case}.stdout.txt').write_text(run.stdout, encoding='utf-8')
        (out / f'{case}.stderr.txt').write_text(run.stderr, encoding='utf-8')
        results[case] = {'returncode': run.returncode, 'stdout': run.stdout, 'stderr': run.stderr}
        (out / 'result.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        run.check_returncode()
        results[case]['evidence'] = json.loads(run.stdout)
    result = {'checks': sum(item['evidence']['checks'] for item in results.values()), 'cases': results,
              'scope': 'actual helper; fake native byte data; CPU only, no native COM/GPU/detour'}
    (out / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))

if __name__ == '__main__':
    main()
