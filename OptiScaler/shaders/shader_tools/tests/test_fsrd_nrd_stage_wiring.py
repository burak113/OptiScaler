"""Actual stage-publication helpers plus lexical production scope contracts.

The native CPU fixture executes StageSample, MergeStageSamples, ReportStages and
CompleteStageSample extracted verbatim from the coordinator. Recording ownership,
the existing host mutex and the logger are explicit adapters. This does not execute
the whole coordinator, D3D12, a provider, Detours or a GPU; integrated E2E tests own
those paths. --prepare-only does not locate or run a compiler.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.cpp"
RR = ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp"
HEADER = ROOT / "OptiScaler/misc/NrdBridgeStagePerf_Dx12.h"


def masked(source):
    return re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda match: re.sub(r"[^\n]", " ", match.group()), source, flags=re.S)


def function(source, signature):
    start = source.index(signature)
    code = masked(source)
    opening = code.index("{", start)
    depth = 1
    for end in range(opening + 1, len(code)):
        depth += (code[end] == "{") - (code[end] == "}")
        if not depth:
            return source[start:end + 1]
    raise AssertionError("unclosed production function: " + signature)


def scopes(source, position):
    stack = []
    for index, char in enumerate(masked(source)[:position]):
        if char == "{":
            stack.append(index)
        elif char == "}":
            assert stack, "unbalanced production scope"
            stack.pop()
    return stack


def contracts(source, rr):
    checks = []

    def need(value, meaning):
        assert value, meaning
        checks.append(meaning)

    before = function(source, "void BeforeDispatch(")
    complete = function(source, "void CompleteStageSample(")
    convert = function(source, "void Convert(")
    motion = function(source, "void FinalizeMotion(")
    dispatch = function(rr, "bool RRWrapper::Dispatch(")
    # Lexical scope evidence complements actual helper execution. No guessed
    # replica of the coordinator lifecycle is used as a behavioral oracle.
    injection = before.index("std::unique_lock injection(")
    accept = before.index("CompleteStageSample(")
    need(scopes(before, injection)[-1] not in scopes(before, accept),
         "Consumer acceptance is outside the injection-lock lifetime")
    borrows = [m.start() for m in re.finditer(r"ScopedBorrow borrow;", before)]
    need(len(borrows) == 2, "Consumer retains both original physical-borrow regions")
    for index, borrow in enumerate(borrows):
        need(scopes(before, borrow)[-1] not in scopes(before, accept),
             f"Consumer acceptance is outside physical-borrow region{index}")
    need(before.index("injectionHold.Stop();") < before.index("completeStages = staged.recording->stages;") < accept,
         "completed POD copy follows the last injection hold timer")
    need(before.index("MergeStageSamples(completeStages,consumerStages)") < accept,
         "Consumer local stage observations join the immutable completion copy")
    need("CompleteStageSample(staged.parameters.streamlineFrame,completeStages,committed)" in before,
         "collector receives captured SL identity and immutable local sample")
    need(before.index("if (ticket.cancelled) return;") < accept and
         before.index("if (!succeeded)") < accept,
         "cancelled and failed output paths return before collection")
    need(before.index("outputCommitted.load(std::memory_order_acquire)") < accept,
         "success publication additionally reads actual committed-output state")
    need(before.index("auto* consumerProfile") < injection and
         "admission,consumerProfile" in before,
         "provider and Commit receive the local Consumer sample")
    need("gStageCollector.Active()" in before and "gStageCollector.Active()" in convert,
         "sampling decisions use existing coordinator-locked sites")
    need(convert.count("MakeOwnedShared<RecordingToken>()") == 1,
         "Recon reuses exactly one existing recording allocation")
    need(convert.index("waitTimer.Stop();") < convert.index("MergeStageSamples(*profile,injectionWait)"),
         "Recon injection wait uses a private sample before shared injection ownership")
    for body, prefix in [(convert, "Recon"), (before, "Consumer")]:
        for match in re.finditer(r"ScopedBorrow borrow;", body):
            tail = body[match.start():]
            need(tail.index("physicalWait.Stop();") < tail.index("StackTimer physicalHold("),
                 prefix + " physical hold starts only after acquisition finishes")
    need(convert.index("StackTimer prepare(") < convert.index("rr.PrepareFrame(") <
         convert.index("prepare.Stop();") < convert.index("conversion.Dispatch("),
         "Recon preparation and conversion have separate truthful CPU boundaries")
    need(motion.index("ScopedBorrow borrow;") < motion.index("StackTimer physicalHold(") <
         motion.index("physicalHold.Stop();") < motion.index("MergeStageSamples("),
         "Motion hold is measured after acquisition and merged before releasing injection ownership")
    lock = complete.index("std::scoped_lock lock(gMutex)")
    publish = complete.index("gStageCollector.Publish(")
    need(scopes(complete, lock)[-1] not in scopes(complete, publish),
         "actual Publish helper runs after the coordinator lock ends")
    need(complete.index("AcceptSuccessful(") < complete.index("gStagesStopped.store(true") < publish,
         "100th successful acceptance stops already-stamped timers before publication")
    need("catch (...)" in complete, "profiling publication cannot throw into successful title recording")
    record = function(rr, "bool RRWrapper::RecordOwnedImpl(")
    commit = function(rr, "bool RRWrapper::CommitOwned(")
    dispatch = function(rr, "bool RRWrapper::Dispatch(")
    need(record.index("StackTimer provider(") < record.index("FfxApiProxy::D3D12_Dispatch("),
         "provider timer surrounds the actual native routing entry")
    need(commit.index("StackTimer outputCommit(") < commit.index("action.context->Commit("),
         "output Commit timer surrounds actual prepared GPU recording")
    need("Sample* profiling" in commit and "profiling};" in commit,
         "optional Sample pointer reaches synchronous prepared Commit without shader ABI changes")
    need("RecordOwnedImpl(list,input,frame,output,error,profiling,false)" in dispatch and
         "CommitOwned(list,output,outputSpec,outputDiff,frame,error,guard,profiling)" in dispatch,
         "the legacy dispatch path records and commits through the same timed owned stages")
    need(source.count('LOG_INFO("[NRD_BRIDGE] stages ') == 1,
         "exactly one stage log call exists")
    return checks


CPP = r'''
#define NOMINMAX
#include <windows.h>
#include "__HEADER__"
#include <cstdlib>
#include <iostream>
#include <memory>
#include <mutex>
#include <new>
#include <sstream>
#include <stdexcept>
#include <string>
using namespace NrdBridgeStagePerf;
unsigned checks=0,allocations=0,reportAllocations=0,lines=0,flushes=0,insideLocks=0;
thread_local bool meter=false,reportMeter=false;
thread_local unsigned hostDepth=0,injectionDepth=0,physicalDepth=0;
std::string lastLine;
void* operator new(size_t n){if(meter)++allocations;if(reportMeter)++reportAllocations;if(auto*p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void* operator new[](size_t n){return ::operator new(n);}
void operator delete(void*p)noexcept{std::free(p);}void operator delete[](void*p)noexcept{std::free(p);}
void operator delete(void*p,size_t)noexcept{std::free(p);}void operator delete[](void*p,size_t)noexcept{std::free(p);}
void need(bool condition,const char* why){if(!condition)throw std::runtime_error(why);++checks;}
struct HostMutex{std::mutex value;void lock(){value.lock();++hostDepth;}void unlock(){--hostDepth;value.unlock();}}gMutex;
struct RecordingToken{Sample stages{};bool needsStageSamples=false;}; // Ownership adapter, no native object.
Collector gStageCollector;
std::atomic<bool> gStagesStopped=false;
void LogStageInfo(const char*,const std::string& value){++lines;if(hostDepth||injectionDepth||physicalDepth)++insideLocks;lastLine=value;}
void FlushLogger()noexcept{++flushes;if(hostDepth||injectionDepth||physicalDepth)++insideLocks;}
#define LOG_INFO LogStageInfo
__HELPERS__
#undef LOG_INFO
void run(const std::string& name){
 if(name=="actual-merge"){
  auto recording=std::make_shared<RecordingToken>();recording->stages.stopped=&gStagesStopped;
  need(!StageSample({})&&!StageSample(recording),"null/unstamped recording has no sample");
  recording->needsStageSamples=true;need(StageSample(recording)==&recording->stages,"stamped recording uses actual POD storage");
  Sample source{},target{};source.stopped=target.stopped=&gStagesStopped;
  source.Add(Stage::ConsumerPhysicalHold,10);source.Add(Stage::ConsumerPhysicalHold,20);target.Add(Stage::ReconConvert,4);
  meter=true;MergeStageSamples(target,source);meter=false;
  need(target.stages[size_t(Stage::ConsumerPhysicalHold)].ticks==30&&target.stages[size_t(Stage::ConsumerPhysicalHold)].events==2,"actual merge preserves two physical spans and event count");
  need(target.stages[size_t(Stage::ReconConvert)].ticks==4&&source.stages[size_t(Stage::ReconConvert)].events==0,"merge retains Recon and leaves source immutable");
  source.stages[size_t(Stage::ProviderDispatch)].invalid=true;MergeStageSamples(target,source);
  need(target.stages[size_t(Stage::ProviderDispatch)].invalid,"invalid source remains explicit");
  source.stages[size_t(Stage::OutputCommit)]={UINT64_MAX,1,false};MergeStageSamples(target,source);MergeStageSamples(target,source);
  need(target.stages[size_t(Stage::OutputCommit)].invalid,"aggregate overflow cannot wrap during actual host merge");
  source.stages[size_t(Stage::ReconPrepare)]={0,UINT64_MAX,false};MergeStageSamples(target,source);MergeStageSamples(target,source);
  need(target.stages[size_t(Stage::ReconPrepare)].invalid,"event-count overflow cannot wrap");
  gStagesStopped=true;meter=true;MergeStageSamples(recording->stages,source);meter=false;
  need(!StageSample(recording)&&recording->stages.stages[size_t(Stage::ConsumerPhysicalHold)].events==0,"100-complete gate disables shared sample mutation");
 }
 else if(name=="actual-publication"){
  Sample complete{};complete.stopped=&gStagesStopped;complete.Add(Stage::ReconPrepare,10);complete.Add(Stage::ConsumerPhysicalHold,20);complete.Add(Stage::ConsumerPhysicalHold,30);
  meter=true;for(unsigned i=0;i<1000;++i){CompleteStageSample(i,complete,false);CompleteStageSample(UINT32_MAX,complete,true);}meter=false;
  need(gStageCollector.Accepted()==0&&lines==0&&flushes==0&&!gStagesStopped,"cancelled/preactive and missing frames cannot publish or stop sampling");
  meter=true;for(unsigned i=0;i<99;++i){CompleteStageSample(i,complete,true);CompleteStageSample(i,complete,true);}meter=false;
  need(gStageCollector.Accepted()==99&&lines==0&&flushes==0&&allocations==0,"actual complete helper stays allocation-free before100 and ignores duplicates");
  reportMeter=true;CompleteStageSample(99,complete,true);reportMeter=false;
  need(gStagesStopped&&gStageCollector.Accepted()==100&&lines==1&&flushes==1&&insideLocks==0,"actual reporting/flush happens once after coordinator lock release");
  need(lastLine.find("frames=100 SL_frame=0..99")!=std::string::npos&&lastLine.find("overlapping_spans_do_not_sum=1")!=std::string::npos,"actual formatter states completion/frame/time interpretation");
  need(lastLine.find("consumer_physical_hold{samples=100,events=200,")!=std::string::npos&&lastLine.find("motion_physical_hold{samples=0,events=0,")!=std::string::npos,"actual formatter distinguishes two spans and missing stages");
  need(lastLine.find("provider_scope=FfxApiProxy_D3D12_Dispatch")!=std::string::npos&&reportAllocations>0,"one-shot formatting allocation is explicit and provider scope is truthful");
  meter=true;for(unsigned i=100;i<1000;++i)CompleteStageSample(i,complete,true);meter=false;
  need(lines==1&&flushes==1&&allocations==0,"completed collector has no late allocations or duplicate log/flush");
 }
 else throw std::runtime_error("unknown case");
 need(allocations==0&&insideLocks==0,"hot actual helpers allocatezero and no reporter runs under locks");
}
int main(int argc,char**argv)try{SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);run(argc>1?argv[1]:"actual-merge");
 std::cout<<"{\"checks\":"<<checks<<",\"hot_allocations\":"<<allocations<<",\"report_allocations\":"<<reportAllocations<<",\"lines\":"<<lines<<",\"flushes\":"<<flushes<<",\"under_locks\":"<<insideLocks<<"}\n";return0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return1;}
'''.replace("return0", "return 0").replace("return1", "return 1")


def main():
    out = Path(os.environ.get("FSRD_GPU_TEST_OUTPUT", "F:/FSRD/sol_batch/15d-guides/stage-wiring-prepare"))
    out.mkdir(parents=True, exist_ok=True)
    source, rr = SOURCE.read_text(), RR.read_text()
    checks = contracts(source, rr)
    helpers = "\n".join(function(source, signature) for signature in [
        "NrdBridgeStagePerf::Sample* StageSample(", "void MergeStageSamples(",
        "void ReportStages(", "void CompleteStageSample("])
    cpp = out / "nrd_stage_wiring.cpp"
    cpp.write_text(CPP.replace("__HEADER__", HEADER.as_posix()).replace("__HELPERS__", helpers), encoding="utf-8")
    contract = {"scope": __doc__, "lexical_scope_checks": checks,
                "sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in [SOURCE, RR, HEADER, cpp]},
                "cases": ["actual-merge", "actual-publication"], "gpu_dispatches": 0}
    (out / "contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
    if "--prepare-only" in sys.argv:
        print(json.dumps({"lexical_scope_checks": len(checks), "cases": 2, "compiled": False, "executed": False}))
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fsrd_toolchain import compile_cpp
    exe = out / "nrd_stage_wiring.exe"
    build = compile_cpp(cpp, exe, (), ())
    (out / "build.json").write_text(json.dumps(build, indent=2), encoding="utf-8")
    rows = []
    for case in contract["cases"]:
        process = subprocess.run([str(exe), case], capture_output=True, text=True, timeout=20)
        (out / (case + ".log")).write_text(process.stdout + process.stderr, encoding="utf-8")
        process.check_returncode()
        row = json.loads(process.stdout)
        assert row["hot_allocations"] == 0 and row["under_locks"] == 0
        rows.append(dict(case=case, **row))
    result = {"scope": __doc__, "lexical_checks": len(checks), "native_checks": sum(row["checks"] for row in rows), "cases": rows}
    (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
