"""CPU regressions for the production FrameSurvey descriptor catalog primitives.

No D3D12 device, fake COM methods, GPU commands, or timing pass thresholds.
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
#include <windows.h>
#include <algorithm>
#include <barrier>
#include <future>
#include <iostream>
#include <numeric>
#include <thread>
#include <vector>
#include <json.hpp>
#include "resource_tracking/FrameSurveyConcurrentMetadata.h"
using namespace FrameSurveyMetadata;
std::atomic<uint64_t> checks{0};
void need(bool yes,const char* message){if(!yes)throw std::runtime_error(message);++checks;}
using SlotMutex=NrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Metadata>;
void recursion(){
 RecursiveSharedMutex a,b;
 {std::unique_lock first(a);need(a.try_lock(),"recursive unique try-lock");a.unlock();
  {std::shared_lock nested(a);need(a.try_lock_shared(),"shared nested under unique");a.unlock_shared();}
  {std::unique_lock unrelated(b);std::shared_lock nested(b);}
 }
 {std::shared_lock first(a);need(a.try_lock_shared(),"recursive shared try-lock");a.unlock_shared();
  bool rejected=false;try{a.lock();}catch(const std::logic_error&){rejected=true;}
  need(rejected,"shared-to-unique upgrade is rejected instead of deadlocking");
 }
 {std::scoped_lock both(a,b);}
 std::promise<void> entered,finished;auto e=entered.get_future(),f=finished.get_future();std::jthread worker;
 {std::shared_lock shared(a);worker=std::jthread([&]{entered.set_value();std::unique_lock writer(a);finished.set_value();});
  e.wait();need(f.wait_for(std::chrono::milliseconds(20))==std::future_status::timeout,"writer drains an active shared scope");}
 f.wait();worker.join();need(a.try_lock(),"writer unlock retires its recursion slot");a.unlock();
 std::promise<void> readEntered,readFinished;auto re=readEntered.get_future(),rf=readFinished.get_future();
 {std::unique_lock exclusive(a);worker=std::jthread([&]{readEntered.set_value();std::shared_lock reader(a);readFinished.set_value();});
  re.wait();need(rf.wait_for(std::chrono::milliseconds(20))==std::future_status::timeout,"shared writers cannot enter a lifecycle exclusive scope");}
 rf.wait();worker.join();
}
void handles(){
 DescriptorHandles set;std::vector<uint64_t> wanted;
 for(uint64_t i=1;i<=4096;++i){const auto key=i*32;need(set.insert(key),"new reverse slot");need(!set.insert(key),"duplicate reverse slot");wanted.push_back(key);}
 std::vector<uint64_t> actual(set.begin(),set.end());need(actual==wanted,"reverse traversal keeps original numeric order");
 DescriptorHandles copy(set);DescriptorHandles moved(std::move(copy));need(copy.empty()&&moved.size()==4096,"move transfers exact reverse size");
 DescriptorHandles assigned;assigned=moved;need(assigned.size()==moved.size(),"copy assignment retains all shard buckets");
 for(auto key:wanted){need(assigned.contains(key),"copied bucket contains original key");need(assigned.erase(key)==1,"exact reverse erase");need(!assigned.contains(key),"erased reverse slot absent");}
 need(assigned.empty()&&moved.size()==4096,"copy edits never affect source");
 while(!moved.empty())moved.erase(moved.begin());need(moved.begin()==moved.end(),"release-style ordered erase drains every bucket");
 DescriptorHandles retiring(set);uint64_t key=0;size_t removed=0;
 while(retiring.PopAny(key)){need(set.contains(key),"unordered lifecycle pop returns only an original indexed slot");++removed;}
 need(removed==wanted.size()&&retiring.empty(),"lifecycle cursor drains all buckets once without sorted merging");
 for(auto value:wanted)retiring.insert(value);
 removed=0;while(retiring.PopAny(key))++removed;
 need(removed==wanted.size(),"repopulated reverse buckets remain discoverable after cursor wrap");
}
struct Value{uint64_t generation=0,owner=0;};
void parallel(){
 RecursiveSharedMutex catalog;std::array<SlotMutex,DescriptorShards> slots;
 DescriptorMap<Value> views;DescriptorHandles resource,heap;
 constexpr size_t threads=16,count=4096;
 std::barrier start(threads);std::vector<std::jthread> workers;
 std::atomic<bool> invalid{false};
 for(size_t t=0;t<threads;++t)workers.emplace_back([&,t]{start.arrive_and_wait();
  for(size_t i=0;i<count;++i){const uint64_t key=(t*count+i+1)*32;
   std::shared_lock lifetime(catalog);std::scoped_lock slot(slots[DescriptorShard(key)]);
   auto [it,inserted]=views.emplace(key,Value{t+1,1});if(!inserted||it->second.generation!=t+1)invalid=true;
   resource.insert(key);heap.insert(key);
  }
 });workers.clear();need(!invalid,"16 simultaneous descriptor writers preserve per-slot generation");
 {std::unique_lock lifetime(catalog);need(views.size()==threads*count&&resource.size()==views.size()&&heap.size()==views.size(),"shared resource and shared heap reverse buckets retain all concurrent writes");
  size_t read=0;for(const auto& [key,value]:views){need(resource.contains(key)&&heap.contains(key)&&value.owner==1,"exclusive reader sees complete map and reverse sets");++read;}
  need(read==views.size(),"descriptor map iteration traverses every shard exactly once");
 }
 workers.clear();std::barrier copyStart(threads);
 for(size_t t=0;t<threads;++t)workers.emplace_back([&,t]{copyStart.arrive_and_wait();
  for(size_t i=0;i<count;++i){const uint64_t src=(t*count+i+1)*32,dst=(threads*count+t*count+i+1)*32;
   std::shared_lock lifetime(catalog);const auto s=DescriptorShard(src),d=DescriptorShard(dst);
   std::unique_lock first(slots[std::min(s,d)]);std::unique_lock<SlotMutex> second;
   if(s!=d)second=std::unique_lock<SlotMutex>(slots[std::max(s,d)]);
   const auto value=views.at(src);views.emplace(dst,value);resource.insert(dst);heap.insert(dst);
   if(views.at(src).generation!=t+1||views.at(dst).generation!=t+1)invalid=true;
  }
 });workers.clear();need(!invalid,"ordered dual-shard copies preserve source and destination identity");
 {std::unique_lock lifetime(catalog);need(views.size()==threads*count*2&&resource.size()==views.size()&&heap.size()==views.size(),"exclusive read waits for all multi-shard copy writers");}
 std::barrier eraseStart(threads);workers.clear();
 for(size_t t=0;t<threads;++t)workers.emplace_back([&,t]{eraseStart.arrive_and_wait();
  for(size_t i=0;i<count;++i){const auto key=(t*count+i+1)*32;
   std::shared_lock lifetime(catalog);std::scoped_lock slot(slots[DescriptorShard(key)]);
   views.erase(key);resource.erase(key);heap.erase(key);
  }
 });workers.clear();
 {std::unique_lock lifetime(catalog);need(views.size()==threads*count&&resource.size()==views.size()&&heap.size()==views.size(),"tombstones remove exactly their current ownership buckets");
  while(!resource.empty()){const auto key=*resource.begin();resource.erase(key);heap.erase(key);views.erase(key);}
  need(views.empty()&&heap.empty(),"exclusive lifecycle release drains all remaining indexed slots");
 }
}
int main()try{
 SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);
 NrdBridgePerf::Configure([](const NrdBridgePerf::Report&)noexcept{});NrdBridgePerf::ConsumerFrame(1);
 recursion();handles();parallel();
 RecursiveSharedMutex catalog;std::promise<void> ownerReady,beginWait;
 auto ready=ownerReady.get_future(),release=beginWait.get_future();
 std::jthread owner([&]{std::shared_lock held(catalog);ownerReady.set_value();release.wait();Sleep(20);});ready.wait();
 {NrdBridgePerf::Scope scope(NrdBridgePerf::Hook::ConstantBufferView,true);beginWait.set_value();std::unique_lock held(catalog);}
 owner.join();
 const auto& measured=NrdBridgePerf::Detail::Get().hooks[size_t(NrdBridgePerf::Hook::ConstantBufferView)];
 need(measured.calls.load()==1,"native hook profiler records one outer primitive scope");
 need(measured.waitTicks[size_t(NrdBridgePerf::WaitKind::Metadata)].load()>0,"catalog lock acquisition contributes measured metadata wait ticks");
 std::cout<<nlohmann::json{{"checks",checks.load()},{"concurrent_threads",16},{"parallel_slots",131072},{"gpu_work",false}}.dump()<<'\n';return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
'''


def run():
    out = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/13a-lifetime/tests/shards'))
    out.mkdir(parents=True, exist_ok=True)
    source, exe = out/'metadata_shards.cpp', out/'metadata_shards.exe'
    source.write_text(CPP, encoding='utf-8')
    compile_cpp(source, exe, (), (ROOT/'OptiScaler', ROOT/'external/nlohmann'))
    result = subprocess.run([str(exe)], capture_output=True, text=True, check=False, timeout=60)
    (out/'native.log').write_text(result.stdout+result.stderr)
    result.check_returncode()
    report = json.loads(result.stdout)
    (out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(result.stdout, end='')


if __name__ == '__main__':
    run()
