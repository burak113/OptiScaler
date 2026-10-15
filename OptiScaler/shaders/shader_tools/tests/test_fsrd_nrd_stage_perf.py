"""Actual StagePerf header: POD/clock/one-shot/zero-allocation CPU controls.

The Windows clock symbols are counted wrappers (native mode forwards actual QPC;
deterministic mode supplies declared ticks/failures). Host serialization is an
explicit existing-mutex adapter. No title, COM, D3D12, shader or GPU work occurs.
--prepare-only writes source/hash contracts without locating a compiler.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
CASES = ["preactive", "hundred", "duplicates", "missing", "timers", "clock-failure",
         "overflow", "publish", "thread-serialized", "hold-boundary", "stopped",
         "frequency-failure", "real-clock"]

CPP = r'''
#define NOMINMAX
#include <windows.h>
BOOL WINAPI CountedStageCounter(LARGE_INTEGER*);
BOOL WINAPI CountedStageFrequency(LARGE_INTEGER*);
#define QueryPerformanceCounter CountedStageCounter
#define QueryPerformanceFrequency CountedStageFrequency
#include "__HEADER__"
#undef QueryPerformanceCounter
#undef QueryPerformanceFrequency
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <new>
#include <stdexcept>
#include <string>
#include <thread>
using namespace NrdBridgeStagePerf;
std::atomic<unsigned> checks=0,allocations=0,qpcCalls=0,qpfCalls=0,callbacks=0,callbackUnderLock=0;
std::atomic<uint64_t> clockTick=1000;
thread_local bool meter=false;
thread_local unsigned hostDepth=0;
bool fakeClock=true,failClock=false,failFrequency=false;
void* operator new(size_t n){if(meter)++allocations;if(auto*p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void* operator new[](size_t n){return ::operator new(n);}
void operator delete(void*p)noexcept{std::free(p);}void operator delete[](void*p)noexcept{std::free(p);}
void operator delete(void*p,size_t)noexcept{std::free(p);}void operator delete[](void*p,size_t)noexcept{std::free(p);}
BOOL WINAPI CountedStageCounter(LARGE_INTEGER* value){++qpcCalls;if(failClock)return FALSE;
 if(!fakeClock)return ::QueryPerformanceCounter(value);value->QuadPart=clockTick.fetch_add(100);return TRUE;}
BOOL WINAPI CountedStageFrequency(LARGE_INTEGER* value){++qpfCalls;if(failFrequency)return FALSE;
 if(!fakeClock)return ::QueryPerformanceFrequency(value);value->QuadPart=1000;return TRUE;}
void need(bool value,const char* text){if(!value)throw std::runtime_error(text);++checks;}
void report(const Report&)noexcept{if(hostDepth)++callbackUnderLock;++callbacks;}
struct HostLock{
 std::mutex& native;explicit HostLock(std::mutex& m):native(m){native.lock();++hostDepth;}
 ~HostLock(){--hostDepth;native.unlock();}
};
Sample sample(uint64_t ticks){Sample s{};need(s.Add(Stage::ConsumerRRDispatch,ticks),"declared stage observation admitted");return s;}
void finish(Collector& c,Report& r,const Sample& s,unsigned first=0){
 for(unsigned i=first;i<100;++i)need(c.AcceptSuccessful(i,s,true,r)==(i==99),"report emitted exactly at100th unique successful frame");
}
void run(const std::string& mode){
 if(mode=="preactive"){
  Collector c;Report r{};Sample s{};r.frequency=777;meter=true;
  for(unsigned i=0;i<1000;++i){StackTimer timer(nullptr,Stage::ReconConvert);need(!c.AcceptSuccessful(i,s,false,r),"cancelled/preactive never admitted");need(!c.AcceptSuccessful(UINT32_MAX,s,true,r),"missing SL id never admitted");}
  meter=false;need(c.Active()&&c.Accepted()==0&&r.frequency==777,"preactive collector/output unchanged");
  need(qpcCalls==0&&qpfCalls==0&&allocations==0&&callbacks==0,"preactive/no sample does zero clocks,allocations,callbacks");
 }
 else if(mode=="hundred"){
  Collector c;Report r{};meter=true;
  for(unsigned i=0;i<100;++i){auto s=sample(i+1);if(i%2)need(s.Add(Stage::ProviderDispatch,i+1),"sparse provider observed");
   need(c.AcceptSuccessful(i,s,true,r)==(i==99),"fixed100 includes SL frame0");}
  meter=false;const auto& all=r.stages[size_t(Stage::ConsumerRRDispatch)];const auto& sparse=r.stages[size_t(Stage::ProviderDispatch)];
  need(!c.Active()&&c.Accepted()==100&&r.frames==100&&r.firstSL==0&&r.lastSL==99,"exact framebound and accepted identity order");
  need(all.observedSamples==100&&all.events==100&&all.totalTicks==5050&&all.maxTicks==100&&all.p95Ticks==95,"independent1..100 closed-form mean/max/nearest-rank p95");
  need(all.MeanMs(r.frequency)==50.5&&all.MaxMs(r.frequency)==100&&all.P95Ms(r.frequency)==95,"frequency conversion exact");
  need(sparse.observedSamples==50&&sparse.events==50&&sparse.totalTicks==2550&&sparse.maxTicks==100&&sparse.p95Ticks==96,"missing provider stages excluded rather than zero-filled");
  need(r.stages[size_t(Stage::MotionPhysicalHold)].observedSamples==0&&allocations==0&&qpfCalls==1,"all-missing remains explicit and report sort allocateszero");
  for(unsigned i=100;i<1000;++i)need(!c.AcceptSuccessful(i,sample(1),true,r),"collector cannot overflow100");
  need(c.Accepted()==100&&qpfCalls==1,"completion is one-shot and never requeries clock frequency");
 }
 else if(mode=="duplicates"){
  Collector c;Report r{};auto s=sample(10);need(!c.AcceptSuccessful(42,s,true,r),"first accepted is not yet ready");
  auto poison=sample(999999);for(unsigned i=0;i<1000;++i)need(!c.AcceptSuccessful(42,poison,true,r),"duplicate frame cannot poison original stage");
  need(!c.AcceptSuccessful(5,poison,false,r)&&!c.AcceptSuccessful(UINT32_MAX,poison,true,r),"cancelled/missing skip");
  need(!c.AcceptSuccessful(5,s,true,r),"same id after cancellation is eligible");unsigned ready=0;
  for(unsigned i=0;i<100;++i)if(i!=5&&i!=42)ready+=c.AcceptSuccessful(i,s,true,r);
  need(ready==1&&c.Accepted()==100&&r.stages[size_t(Stage::ConsumerRRDispatch)].totalTicks==1000,"only100successful unique originals counted");
 }
 else if(mode=="missing"){
  Collector c;Report r{};
  for(unsigned i=0;i<100;++i){Sample s{};if(i<4)need(s.Add(Stage::ReconPrepare,(i+1)*10),"four sparse observations");
   if(i==4)need(s.Add(Stage::OutputCommit,0),"observed zero ticks is valid");c.AcceptSuccessful(i,s,true,r);}
  const auto& sparse=r.stages[size_t(Stage::ReconPrepare)];need(sparse.observedSamples==4&&sparse.totalTicks==100&&sparse.MeanMs(r.frequency)==25&&sparse.p95Ticks==40,"sparse denominator uses4,not100");
  need(r.stages[size_t(Stage::OutputCommit)].observedSamples==1&&r.stages[size_t(Stage::OutputCommit)].events==1,"zero duration differs from missing stage");
 }
 else if(mode=="timers"){
  Sample s{};meter=true;{StackTimer outer(&s,Stage::ConsumerRRDispatch);{StackTimer inner(&s,Stage::ProviderDispatch);need(inner.Stop(),"explicit Stop measures");need(!inner.Stop(),"secondStop no duplicate");}}
  meter=false;need(s.stages[size_t(Stage::ConsumerRRDispatch)].ticks==300&&s.stages[size_t(Stage::ProviderDispatch)].ticks==100,"nested elapsed scopes retained independently,never summed");
  need(s.stages[size_t(Stage::ProviderDispatch)].events==1&&qpcCalls==4&&allocations==0,"destructor after Stop no clock/heap/event");
 }
 else if(mode=="clock-failure"){
  Sample s{};failClock=true;{StackTimer t(&s,Stage::ReconPrepare);}failClock=false;
  need(s.stages[size_t(Stage::ReconPrepare)].invalid&&s.stages[size_t(Stage::ReconPrepare)].events==0,"clock failure never fabricates zero observation");
  {StackTimer t(&s,Stage::ProviderDispatch);clockTick=1;need(!t.Stop(),"counter rollback rejected");}
  Collector c;Report r{};finish(c,r,s);need(r.stages[size_t(Stage::ReconPrepare)].invalidSamples==100&&r.stages[size_t(Stage::ProviderDispatch)].invalidSamples==100,"invalid spans reported separately from missing");
 }
 else if(mode=="overflow"){
  Sample invalid{};need(invalid.Add(Stage::ReconPrepare,UINT64_MAX),"largest representable single span");need(!invalid.Add(Stage::ReconPrepare,1),"per-recording tick addition never wraps");
  need(!invalid.Add(Stage::Count,1),"invalid stage id cannot index array");
  Sample large{};need(large.Add(Stage::ProviderDispatch,UINT64_MAX-1),"large valid span");
  Collector c;Report r{};for(unsigned i=0;i<100;++i){auto s=i==0?invalid:Sample{};if(i<2)s.stages[size_t(Stage::ProviderDispatch)]=large.stages[size_t(Stage::ProviderDispatch)];c.AcceptSuccessful(i,s,true,r);}
  const auto& total=r.stages[size_t(Stage::ProviderDispatch)];need(total.saturated&&total.totalTicks==UINT64_MAX&&total.observedSamples==2&&total.events==2,"aggregate overflow saturates with explicitinvalidtotal flag");
  need(total.MeanMs(r.frequency)==0&&r.stages[size_t(Stage::ReconPrepare)].invalidSamples==1,"overflow cannot produce a misleading finite mean");
 }
 else if(mode=="publish"){
  Collector c,other;Report r{};r.frames=100;r.collector=&c;need(!c.Publish(r,report),"preactive forged report cannot publish");
  std::mutex host;auto s=sample(1);{HostLock lock(host);finish(c,r,s);need(callbacks==0,"Accept can never invoke a callback under host lock");}
  need(!other.Publish(r,report)&&!c.Publish(r,nullptr),"wrongcollector/nullreporter cannot consume publication");
  meter=true;need(c.Publish(r,report),"complete report explicitly published outsidehostlock");need(!c.Publish(r,report),"copied report cannot publishtwice");meter=false;
  need(callbacks==1&&callbackUnderLock==0&&allocations==0,"singleoutside callback/noallocation");
 }
 else if(mode=="thread-serialized"){
  Collector c;Report r{};std::mutex host;std::array<std::thread,8> threads;allocations=0;
  for(unsigned t=0;t<8;++t)threads[t]=std::thread([&,t]{meter=true;for(unsigned i=0;i<100;++i){const auto id=(i+t*17)%100;Sample s{};s.Add(Stage::OutputCommit,id+1);Report local{};bool ready;
    {HostLock lock(host);ready=c.AcceptSuccessful(id,s,true,local);if(ready)r=local;}if(ready)c.Publish(local,report);}meter=false;});
  for(auto& t:threads)t.join();need(c.Accepted()==100&&callbacks==1&&callbackUnderLock==0&&allocations==0,"existing external lock serializes800 attempts without internalmutex/allocations");
  need(r.stages[size_t(Stage::OutputCommit)].totalTicks==5050&&r.stages[size_t(Stage::OutputCommit)].p95Ticks==95,"threadorder does not corrupt accepted100unique statistics");
  std::array<std::thread,8> again;for(auto& t:again)t=std::thread([&]{c.Publish(r,report);});for(auto& t:again)t.join();need(callbacks==1,"publication is atomic even copied across threads");
 }
 else if(mode=="hold-boundary"){
  struct Borrow{~Borrow(){clockTick+=1000;}};Sample s{};
  {Borrow borrow;StackTimer hold(&s,Stage::ConsumerPhysicalHold);clockTick+=500;}
  need(s.stages[size_t(Stage::ConsumerPhysicalHold)].ticks==600,"hold timer endsbefore borrow destructor overhead");
  Collector c;Report r{};finish(c,r,s);s.stages[size_t(Stage::ConsumerPhysicalHold)].ticks=999999;
  need(r.stages[size_t(Stage::ConsumerPhysicalHold)].totalTicks==60000,"complete samples copied,not borrowed or later-mutated");
 }
 else if(mode=="stopped"){
  Sample s{};std::atomic<bool> stopped=false;s.stopped=&stopped;unsigned before;
  {StackTimer t(&s,Stage::ProviderDispatch);stopped=true;before=qpcCalls;need(!t.Stop(),"alreadyinflight timer skipsafterglobalcompletion");}
  {StackTimer t(&s,Stage::ConsumerRRDispatch);}need(!s.Add(Stage::OutputCommit,1),"late stamped recording cannot mutate afterstop");
  need(qpcCalls==before&&s.stages[size_t(Stage::ProviderDispatch)].events==0,"post100 performsnoQPCanddoesnotpublishpartialspan");
 }
 else if(mode=="frequency-failure"){
  failFrequency=true;Collector c;Report r{};finish(c,r,sample(10));need(r.frequency==0&&r.frames==100,"failedfrequency leaves explicit unavailable timebase");
  need(r.stages[size_t(Stage::ConsumerRRDispatch)].MeanMs(r.frequency)==0,"unavailable frequency cannot dividebyzero");
 }
 else if(mode=="real-clock"){
  fakeClock=false;Sample s{};{StackTimer t(&s,Stage::ReconConvert);volatile uint64_t work=0;for(unsigned i=0;i<10000;++i)work=work+i;}
  need(qpcCalls==2&&s.stages[size_t(Stage::ReconConvert)].events==1&&!s.stages[size_t(Stage::ReconConvert)].invalid,"actualWindowsQPC forwards through counted facade");
  Collector c;Report r{};finish(c,r,s);need(r.frequency>0&&qpfCalls==1,"actualnativeWindowsfrequency atone-shot completion");
 }
 else throw std::runtime_error("unknown case");
}
int main(int argc,char**argv)try{SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);const std::string mode=argc>1?argv[1]:"hundred";run(mode);
 std::cout<<"{\"case\":\""<<mode<<"\",\"checks\":"<<checks.load()<<",\"allocations\":"<<allocations.load()<<",\"qpc\":"<<qpcCalls.load()<<",\"qpf\":"<<qpfCalls.load()<<",\"callbacks\":"<<callbacks.load()<<",\"callback_under_host_lock\":"<<callbackUnderLock.load()<<"}\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
'''


def main():
    out = Path(os.environ.get("FSRD_GPU_TEST_OUTPUT", "F:/FSRD/sol_batch/15d-guides/stage-perf-prepare"))
    out.mkdir(parents=True, exist_ok=True)
    header = ROOT / "OptiScaler/misc/NrdBridgeStagePerf_Dx12.h"
    source = out / "nrd_stage_perf.cpp"
    source.write_text(CPP.replace("__HEADER__", header.as_posix()), encoding="utf-8")
    contract = {"scope": __doc__, "cases": CASES, "header": str(header),
                "header_sha256": hashlib.sha256(header.read_bytes()).hexdigest(),
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "sample_capacity": 100, "native_d3d12": False, "gpu_dispatches": 0}
    (out / "contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
    if "--prepare-only" in sys.argv:
        print(json.dumps({"source": str(source), "cases": len(CASES), "compiled": False, "executed": False}))
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fsrd_toolchain import compile_cpp
    exe = out / "nrd_stage_perf.exe"
    build = compile_cpp(source, exe, (), ())
    (out / "build.json").write_text(json.dumps(build, indent=2), encoding="utf-8")
    results = []
    for case in CASES:
        process = subprocess.run([str(exe), case], capture_output=True, text=True, timeout=20)
        (out / (case + ".log")).write_text(process.stdout + process.stderr, encoding="utf-8")
        process.check_returncode()
        row = json.loads(process.stdout)
        assert row["allocations"] == 0 and row["callback_under_host_lock"] == 0
        results.append(row)
    result = {"scope": __doc__, "checks": sum(row["checks"] for row in results), "cases": results}
    (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
