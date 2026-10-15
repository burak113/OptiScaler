"""Actual metadata-only capture-slot budget, no COM/device/GPU execution.

The family is created before hot allocation meters. A tiny resource destructor
adapter checks C++ field order; native helper destruction is covered separately.
--prepare-only writes source/contracts without a compiler.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
CASES = ["off", "capacity", "move", "bytes", "unwind", "field-order", "parallel", "retained"]
CPP = r'''
#include "__HEADER__"
#include <windows.h>
#include <array>
#include <cstdlib>
#include <iostream>
#include <new>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
using namespace NrdBridgeCaptureBudget;
std::atomic<unsigned> checks=0,allocations=0;
thread_local bool meter=false;
void* operator new(size_t n){if(meter)++allocations;if(auto*p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void* operator new[](size_t n){return ::operator new(n);}
void operator delete(void*p)noexcept{std::free(p);}void operator delete[](void*p)noexcept{std::free(p);}
void operator delete(void*p,size_t)noexcept{std::free(p);}void operator delete[](void*p,size_t)noexcept{std::free(p);}
void need(bool value,const char* why){if(!value)throw std::runtime_error(why);++checks;}
void run(const std::string& mode){
 if(mode=="off"){
  meter=true;{Permit empty;need(!empty&&!Permit::TryAcquire({}),"empty/OFF has no family or permit");need(!empty.SetBytes(65536),"unreserved bytes denied");}meter=false;
 }
 else if(mode=="capacity"){
  auto family=std::make_shared<Family>();std::array<std::optional<Permit>,32> held;meter=true;
  for(auto& permit:held){permit.emplace(Permit::TryAcquire(family));need(bool(*permit)&&permit->SetBytes(65536),"each of32 reservations owns one allocation");}
  need(family->allocatedSlots==32&&family->allocatedBytes==32*65536,"family accounts all32 allocated/reserved slots");
  for(unsigned i=0;i<10000;++i)need(!Permit::TryAcquire(family),"33rd reservation cannot cross context cap");
  for(auto& permit:held)permit.reset();meter=false;
  need(family->allocatedSlots==0&&family->allocatedBytes==0,"all slots return both counters");
 }
 else if(mode=="move"){
  auto family=std::make_shared<Family>();meter=true;{auto first=Permit::TryAcquire(family);need(first.SetBytes(123),"first allocation bytes accepted");
   {Permit second(std::move(first));need(!first&&bool(second)&&family->allocatedSlots==1&&family->allocatedBytes==123,"move transfers exactly one reservation");}
   need(family->allocatedSlots==0&&family->allocatedBytes==0,"moved owner releases once");}meter=false;
 }
 else if(mode=="bytes"){
  auto family=std::make_shared<Family>();meter=true;{auto first=Permit::TryAcquire(family),second=Permit::TryAcquire(family);
   need(!first.SetBytes(0)&&!first.SetBytes(UINT64_MAX),"invalid native allocation info cannot poison bytes");
   need(first.SetBytes(UINT64_MAX-2)&&!first.SetBytes(1),"allocation bytes commit onlyonce");
   need(!second.SetBytes(3)&&family->allocatedBytes==UINT64_MAX-2,"sum overflow fails without wrapping");
   need(second.SetBytes(1)&&family->allocatedBytes==UINT64_MAX-1,"rejected attempt leaves permit usable");}meter=false;
  need(family->allocatedBytes==0&&family->allocatedSlots==0,"large metadata-only byte counters unwind exactly");
 }
 else if(mode=="unwind"){
  auto family=std::make_shared<Family>();meter=true;
  try{auto permit=Permit::TryAcquire(family);need(permit.SetBytes(65536),"failed candidate first reserves");throw 7;}catch(int value){need(value==7,"declared failure reached");}
  meter=false;need(family->allocatedSlots==0&&family->allocatedBytes==0,"failed creation unwinds its reservation");
 }
 else if(mode=="field-order"){
  auto family=std::make_shared<Family>();bool resourceReleased=false;
  struct Resource{Family* family;bool* released;~Resource(){need(family->allocatedSlots==1&&family->allocatedBytes==65536,"native-owner adapter dies before permit accounting");*released=true;}};
  struct Slot{Permit permit;Resource resource;Slot(Permit&& p,Family* f,bool* flag):permit(std::move(p)),resource{f,flag}{}};
  meter=true;{auto permit=Permit::TryAcquire(family);need(permit.SetBytes(65536),"slot resource metadata committed");Slot slot(std::move(permit),family.get(),&resourceReleased);}meter=false;
  need(resourceReleased&&family->allocatedSlots==0&&family->allocatedBytes==0,"reservation returned onlyafter resource destructor");
 }
 else if(mode=="parallel"){
  auto family=std::make_shared<Family>();std::atomic<unsigned> ready=0,success=0,denied=0;
  auto worker=[&]{std::array<std::optional<Permit>,32> permits;meter=true;for(auto& permit:permits){auto p=Permit::TryAcquire(family);if(p){need(p.SetBytes(64),"concurrent reserved bytes commit");permit.emplace(std::move(p));++success;}else ++denied;}
   ++ready;while(ready.load(std::memory_order_acquire)!=2)std::this_thread::yield();need(family->allocatedSlots<=32,"concurrent family cap never exceeded");for(auto& permit:permits)permit.reset();meter=false;};
  std::thread a(worker),b(worker);a.join();b.join();need(success==32&&denied==32&&family->allocatedSlots==0&&family->allocatedBytes==0,"two concurrent contexts share32permits and retire all");
 }
 else if(mode=="retained"){
  auto family=std::make_shared<Family>();struct Slot{Permit permit;explicit Slot(Permit&& p):permit(std::move(p)){}};
  std::array<std::shared_ptr<Slot>,32> cache,leases;
  for(unsigned i=0;i<32;++i){auto permit=Permit::TryAcquire(family);need(permit.SetBytes(65536),"context slot owns its reservation");cache[i]=std::make_shared<Slot>(std::move(permit));leases[i]=cache[i];}
  meter=true;for(auto& slot:cache)slot.reset();need(family->allocatedSlots==32,"cache retirement preserves all pending snapshots");
  for(unsigned i=1;i<32;++i)leases[i].reset();need(family->allocatedSlots==1&&family->allocatedBytes==65536,"later-idle snapshots immediatelyreturn allocated slots");
  leases[0].reset();meter=false;need(family->allocatedSlots==0&&family->allocatedBytes==0,"final old snapshot retires family allocation");
 }
 else throw std::runtime_error("unknown case");
 need(allocations==0,"actual budget hot path allocated no C++ heap memory");
}
int main(int argc,char**argv)try{SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);run(argc>1?argv[1]:"capacity");std::cout<<"{\"checks\":"<<checks.load()<<",\"hot_allocations\":"<<allocations.load()<<"}\n";return 0;}
catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
'''


def main():
    out = Path(os.environ.get("FSRD_GPU_TEST_OUTPUT", "F:/FSRD/sol_batch/15d-guides/capture-budget-prepare"))
    out.mkdir(parents=True, exist_ok=True)
    header = ROOT / "OptiScaler/misc/NrdBridgeCaptureSlotBudget_Dx12.h"
    source = out / "capture_budget.cpp"
    source.write_text(CPP.replace("__HEADER__", header.as_posix()), encoding="utf-8")
    contract = dict(scope=__doc__, cases=CASES, capacity=32, gpu_dispatches=0,
                    sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in [header, source]})
    (out / "contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
    if "--prepare-only" in sys.argv:
        print(json.dumps(dict(cases=len(CASES), compiled=False, executed=False)))
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fsrd_toolchain import compile_cpp
    exe = out / "capture_budget.exe"
    compile_cpp(source, exe, (), ())
    rows = []
    for case in CASES:
        result = subprocess.run([str(exe), case], capture_output=True, text=True, timeout=20)
        (out / (case + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        result.check_returncode()
        row = json.loads(result.stdout)
        assert row["hot_allocations"] == 0
        rows.append(dict(case=case, **row))
    value = dict(cases=rows, checks=sum(row["checks"] for row in rows), scope=__doc__)
    (out / "result.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
