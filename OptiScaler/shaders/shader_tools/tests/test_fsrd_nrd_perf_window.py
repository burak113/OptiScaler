"""Production interval-index correctness and first-100-render-frame hook sampler."""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT/'OptiScaler/shaders/shader_tools'))
from fsrd_toolchain import compile_cpp

CPP = r'''
#define NOMINMAX
#include "resource_tracking/FrameSurveyBufferRanges.h"
#include "misc/NrdBridgePerf_Dx12.h"
#include <json.hpp>
#include <chrono>
#include <iostream>
#include <fstream>
#include <random>
#include <stdexcept>
#include <thread>
#include <vector>
#include <psapi.h>
using J = nlohmann::json;
unsigned checks=0;
void need(bool ok,const char* text) { if(!ok) throw std::runtime_error(text); ++checks; }
void* object(uint64_t id) { return reinterpret_cast<void*>(uintptr_t(id*16)); }
J intervals() {
 using I = FrameSurveyMetadata::BufferAddressIndex;
 I index; index.Insert(4096,65536,1,object(1)); index.Insert(8192,256,2,object(2));
 auto found=index.Find(9216); need(found.matches==1 && found.object==object(1),"older spanning interval survives a nearer short buffer start");
 need(index.Find(8192).matches==2 && !index.Find(8192).object,"overlapping distinct starts fail uniqueness");
 index.Insert(4096,4096,3,object(3)); need(index.Size()==3 && index.Find(4608).matches==2,"equal starts keep both live generations");
 index.Erase(4096,1); need(index.Find(4608).object==object(3),"releasing one equal-start alias retains the other generation");
 index.Erase(4096,1); need(index.Size()==2,"duplicate stale release cannot erase a newer owner");
 index.Erase(4096,3); need(!index.Find(4608).object,"last owner removal rejects stale VA");
 index.Clear(); index.Insert(UINT64_MAX-511,1024,9,object(9));
 need(index.Find(UINT64_MAX).object==object(9),"overflowing mathematical end clamps to the GPU address domain without wrap");
 need(!index.Find(UINT64_MAX-512).object,"address before overflowing interval is outside");
 index.Insert(0,1024,10,object(10)); index.Insert(100,0,11,object(11));
 index.Insert(100,1024,0,object(12)); index.Insert(100,1024,12,nullptr);
 need(index.Size()==1,"invalid zero interval identities never enter the index"); index.Clear();
 struct Interval { uint64_t start,bytes,id; };
 std::vector<Interval> live; std::mt19937_64 random(0xa1797172);
 unsigned differential=0;
 for(uint64_t step=1;step<=12000;++step) {
  if(!live.empty() && random()%3==0) {
   const auto position=size_t(random()%live.size()); auto old=live[position];
   index.Erase(old.start,old.id); live.erase(live.begin()+position);
  } else {
   const uint64_t start=256*(1+random()%8192),bytes=1+random()%4096;
   index.Insert(start,bytes,step,object(step)); live.push_back({start,bytes,step});
  }
  need(index.Size()==live.size(),"interval insert/delete cardinality matches independent live set");
  for(unsigned query=0;query<4;++query) {
   const auto address=uint64_t(random()%(256*8193)); unsigned matches=0; uint64_t owner=0;
   for(const auto& interval:live) if(address>=interval.start && address-interval.start<interval.bytes) { ++matches; owner=interval.id; }
   const auto actual=index.Find(address);
   need(actual.matches==std::min(2u,matches),"random interval query matches independent linear reference");
   need(matches==1 ? actual.object==object(owner) && actual.generation==owner : !actual.object && !actual.generation,
     "random query retains exact unique generation and fails closed for ambiguity"); ++differential;
  }
 }
 index.Clear(); constexpr uint64_t n=100000; const auto start=std::chrono::steady_clock::now();
 for(uint64_t i=1;i<=n;++i) index.Insert(0x100000000ull+i*65536,4096,i,object(i));
 const auto created=std::chrono::steady_clock::now(); size_t visits=0,maximum=0;
 for(uint64_t i=1;i<=n;++i) {
  const auto actual=index.Find(0x100000000ull+i*65536+1536);
  need(actual.object==object(i) && actual.matches==1,"100k monotonic buffers resolve their exact owner");
  visits+=actual.visited; maximum=std::max(maximum,actual.visited);
 }
 const auto queried=std::chrono::steady_clock::now();
 need(maximum<128,"100k disjoint buffer lookup visits fewer than128 nodes rather than100k resources");
 for(uint64_t i=1;i<=n;++i) index.Erase(0x100000000ull+i*65536,i);
 const auto erased=std::chrono::steady_clock::now(); need(!index.Size() && !index.Find(0x100010000ull).object,"100k final releases empty the interval index");
 auto ms=[](auto first,auto last){return std::chrono::duration<double,std::milli>(last-first).count();};
 return {{"random_reference_queries",differential},{"live_scale",n},{"mean_nodes_visited",double(visits)/n},
   {"max_nodes_visited",maximum},{"insert_ms",ms(start,created)},{"lookup_ms",ms(created,queried)},{"erase_ms",ms(queried,erased)}};
}
NrdBridgePerf::Report reported;
std::atomic<unsigned> reports{0};
void sink(const NrdBridgePerf::Report& value) noexcept { reported=value; reports.fetch_add(1,std::memory_order_release); }
J sampler() {
 using H=NrdBridgePerf::Hook; using S=NrdBridgePerf::Scope;
 need(!NrdBridgePerf::Detail::configured.load(),"startup OFF sampler is unconfigured");
 { S ignored(H::Release,false); } NrdBridgePerf::ConsumerFrame(8);
 need(!NrdBridgePerf::Detail::configured.load(),"startup OFF scope/frame marker never allocates sampler state");
 NrdBridgePerf::Configure(sink); NrdBridgePerf::ConsumerFrame(UINT32_MAX);
 need(!NrdBridgePerf::Detail::collecting.load(),"unknown SL frame does not start recording");
 for(uint32_t menu=0;menu<500;++menu) { NrdBridgePerf::RenderedFrame(menu); S ignored(H::Release,true); }
 need(!NrdBridgePerf::Detail::collecting.load() && !reports.load(),"menu/upscaler evaluations cannot arm or report gameplay profiling");
 need(NrdBridgePerf::NeedsConsumerFrames(),"configured sampler still waits for the title Consumer");
 NrdBridgePerf::ConsumerFrame(10);
 NrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Metadata> metadata;
 std::atomic<bool> held{false},attempt{false};
 std::thread holder([&]{metadata.lock();held.store(true,std::memory_order_release);
   while(!attempt.load(std::memory_order_acquire)) std::this_thread::yield();
   std::this_thread::sleep_for(std::chrono::milliseconds(12));metadata.unlock();});
 while(!held.load(std::memory_order_acquire)) std::this_thread::yield();
 { S outer(H::ConstantBufferView,true); { S nested(H::ConstantBufferView,true); } { S other(H::Release,true); }
   attempt.store(true,std::memory_order_release);metadata.lock();metadata.unlock(); }
 holder.join();
 try { S scope(H::ShaderResourceView,true); throw std::runtime_error("expected"); } catch(const std::runtime_error&) {}
 { S internal(H::UnorderedAccessView,false); }
 std::array<std::thread,4> workers;
 for(auto& worker:workers) worker=std::thread([]{for(unsigned i=0;i<1000;++i) { S scope(H::Release,true); }});
 for(auto& worker:workers) worker.join();
 for(uint32_t frame=10;frame<110;++frame) {
  NrdBridgePerf::ConsumerFrame(frame); NrdBridgePerf::ConsumerFrame(frame); NrdBridgePerf::ConsumerFrame(10); // repeated/older eval/FG id
  { S scope(H::UnorderedAccessView,true); }
 }
 need(!reports.load(),"100 rendered entries and duplicate/older frame ids do not close the100th interval early");
 std::atomic<bool> entered{false},finish{false};
 std::thread outstanding([&]{ S scope(H::Release,true); entered.store(true,std::memory_order_release);
   while(!finish.load(std::memory_order_acquire)) std::this_thread::yield(); });
 while(!entered.load(std::memory_order_acquire)) std::this_thread::yield();
 NrdBridgePerf::ConsumerFrame(109); NrdBridgePerf::ConsumerFrame(108);
 need(!reports.load() && NrdBridgePerf::Detail::collecting.load(),"FG/repeated latest snapshot cannot truncate hooks of the100th rendered frame");
 NrdBridgePerf::ConsumerFrame(110);
 need(!reports.load() && !NrdBridgePerf::Detail::collecting.load(),"101st rendered entry closes100 complete intervals and waits for in-flight hooks");
 finish.store(true,std::memory_order_release); outstanding.join();
 need(reports.load(std::memory_order_acquire)==1,"last outstanding hook emits exactly one completed100-frame report");
 need(reported.frames==100 && reported.firstFrame==10 && reported.lastFrame==109,"report owns exactly100 distinct rendered SL frames");
 need(reported.ConsumerTimeValid() && reported.consumerIntervalTicks>0,"the same100 complete Consumer intervals freeze a valid native QPC span");
 need(reported.consumerIntervalTicks>=reported.hooks[size_t(H::ConstantBufferView)].waitTicks[size_t(NrdBridgePerf::WaitKind::Metadata)],"Consumer span includes the earlier real contended metadata interval");
 NrdBridgePerf::Report formula;need(!formula.ConsumerTimeValid() && formula.ConsumerElapsedMs()==0 && formula.AverageConsumerIntervalMs()==0 && formula.ConsumerIntervalsPerSecond()==0,"missing Consumer clock data remains explicitly unavailable");
 formula.frames=100;formula.frequency=10000000;formula.consumerIntervalTicks=80000000;
 need(formula.ConsumerTimeValid() && formula.ConsumerElapsedMs()==8000 && formula.AverageConsumerIntervalMs()==80 && formula.ConsumerIntervalsPerSecond()==12.5,"100 Consumer intervals over8seconds yield80ms and12.5intervals/s, not doubled FG FPS");
 formula.frequency=0;need(!formula.ConsumerTimeValid() && formula.ConsumerElapsedMs()==0 && formula.AverageConsumerIntervalMs()==0 && formula.ConsumerIntervalsPerSecond()==0,"missing clock frequency never creates a duration or rate");
 formula.frequency=10000000;formula.consumerIntervalTicks=0;need(!formula.ConsumerTimeValid() && formula.ConsumerElapsedMs()==0 && formula.AverageConsumerIntervalMs()==0 && formula.ConsumerIntervalsPerSecond()==0,"failed or empty clock span remains unavailable with a valid frequency");
 formula.consumerIntervalTicks=80000000;formula.frames=0;need(!formula.ConsumerTimeValid() && formula.ConsumerIntervalsPerSecond()==0,"empty interval denominator never creates a rate");
 const auto frozenConsumerTicks=reported.consumerIntervalTicks;
 need(reported.hooks[size_t(H::ConstantBufferView)].calls==1,"nested physical forwarding counts once");
 need(reported.hooks[size_t(H::ShaderResourceView)].calls==1,"exception path records its completed hook");
 need(reported.hooks[size_t(H::UnorderedAccessView)].calls==100,"internal calls are excluded from exact title hook totals");
 need(reported.hooks[size_t(H::Release)].calls==4002,"concurrent title hooks, distinct nested hook and final draining hook are counted exactly");
 need(reported.frequency>0 && reported.AverageUs(H::Release)>0,"hook averages use measured QPC duration/frequency");
 need(reported.AverageWaitUs(H::ConstantBufferView,NrdBridgePerf::WaitKind::Metadata)>=1000.0,"contended metadata wait is measured separately inside its physical CBV hook");
 need(reported.AverageWaitUs(H::ConstantBufferView)<=reported.AverageUs(H::ConstantBufferView),"categorized waits fit within measured hook elapsed time");
 need(reported.AverageWaitUs(H::Release,NrdBridgePerf::WaitKind::Metadata)==0.0,"nested distinct Release does not inherit the outer CBV metadata wait");
 need(NrdBridgePerf::Detail::currentWaits==nullptr,"thread-local wait recording ends with its physical hook");
 need(!NrdBridgePerf::NeedsConsumerFrames(),"finished gameplay sampler no longer needs Consumer frame lookups");
 for(uint32_t i=110;i<500;++i) { NrdBridgePerf::ConsumerFrame(i); S ignored(H::Release,true); }
 NrdBridgePerf::Configure(sink);
 need(reports.load()==1 && !NrdBridgePerf::Detail::collecting.load(),"profiling stops after one report and cannot restart on repeated configuration");
 need(reported.consumerIntervalTicks==frozenConsumerTicks && NrdBridgePerf::Detail::Get().consumerIntervalTicks==frozenConsumerTicks,"later/repeated entries and report draining cannot extend the frozen Consumer clock");
 J averages=J::array(); for(size_t i=0;i<size_t(H::Count);++i) averages.push_back({{"calls",reported.hooks[i].calls},{"avg_us",reported.AverageUs(H(i))},{"lock_wait_avg_us",reported.AverageWaitUs(H(i))},{"metadata_wait_avg_us",reported.AverageWaitUs(H(i),NrdBridgePerf::WaitKind::Metadata)}});
 return {{"reports",reports.load()},{"frames",reported.frames},{"first_sl_frame",reported.firstFrame},{"last_sl_frame",reported.lastFrame},
  {"frequency",reported.frequency},{"consumer_time_valid",reported.ConsumerTimeValid()},{"consumer_elapsed_ms",reported.ConsumerElapsedMs()},
  {"consumer_avg_interval_ms",reported.AverageConsumerIntervalMs()},{"consumer_intervals_per_second",reported.ConsumerIntervalsPerSecond()},
  {"cadence_scope","CPU Consumer recording cadence; no GPU or FG/display FPS"},{"hook_samples",averages},{"scope","real production sampler; synthetic rendered frame ids and host work"}};
}
int main(int argc,char** argv) try {
 need(argc==2,"output path"); J result={{"intervals",intervals()},{"sampler",sampler()}};
 PROCESS_MEMORY_COUNTERS memory{}; need(GetProcessMemoryInfo(GetCurrentProcess(),&memory,sizeof(memory))!=0,"peak RSS measured");
 need(memory.PeakWorkingSetSize<(uint64_t(5)<<29),"native RSS below2.5GiB");
 result["peak_working_set_bytes"]=memory.PeakWorkingSetSize; result["native_checks"]=checks;
 std::ofstream(argv[1])<<result.dump(2)<<'\n'; std::cout<<result.dump()<<'\n'; return 0;
} catch(const std::exception& error) { std::cerr<<error.what()<<'\n'; return 1; }
'''


def run():
    output = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    output.mkdir(parents=True, exist_ok=True)
    source, exe = output/'perf_window.cpp', output/'perf_window.exe'
    source.write_text(CPP, encoding='utf-8')
    compile_cpp(source, exe, ('psapi.lib',), (ROOT/'OptiScaler', ROOT/'external/nlohmann'))
    subprocess.run([str(exe), str(output/'result.json')], check=True,
                   creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    result = json.loads((output/'result.json').read_text())
    assert result['sampler']['reports'] == 1
    assert result['sampler']['frames'] == 100
    assert result['intervals']['live_scale'] == 100000
    assert result['intervals']['max_nodes_visited'] < 128
    result['python_checks'] = 4
    (output/'result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'native_checks':result['native_checks'], 'python_checks':4,
                      'scope':'real production interval index and perf sampler, no GPU work'}))


if __name__ == '__main__':
    run()
