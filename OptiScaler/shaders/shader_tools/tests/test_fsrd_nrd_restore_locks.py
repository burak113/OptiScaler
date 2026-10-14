"""Actual restore bodies with blocked native seams and concurrent title trackers.

CPU-only. Native setters are deliberate blocking/recording adapters. Existing
GPU wiring/E2E assertions remain separate and unchanged. No timing gain is
inferred from the bounded concurrency deadline.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp
from test_fsrd_nrd_root_restore import function

ROOT = Path(__file__).resolve().parents[4]

CPP = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include "__ROOT__/OptiScaler/misc/NrdBridgePerf_Dx12.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <vector>
#include <unordered_map>
#include <mutex>
#include <shared_mutex>
#include <thread>
#include <future>
#include <condition_variable>
#include <iostream>
#include <stdexcept>
#include <type_traits>
#include "__ROOT__/OptiScaler/hooks/Hook_Utils.h"
#define LOG_ERROR(...) ((void)0)
#define LOG_WARN(...) ((void)0)
#define LOG_TRACE(...) ((void)0)
namespace FrameSurvey {
 thread_local bool internalScope=false; bool Internal() { return internalScope; }
 void RootBinding(ID3D12GraphicsCommandList*,bool,ID3D12RootSignature*) {}
 void RootView(ID3D12GraphicsCommandList*,bool,UINT,D3D12_DESCRIPTOR_RANGE_TYPE,D3D12_GPU_VIRTUAL_ADDRESS) {}
}
bool gNrdBridgeDeviceWrappers=true,gSurveyDeviceWrappers=false;
__STATE__
struct Option{bool current=true;bool value_or_default()const{return current;}};
struct Config{Option RestoreComputeSignature,RestoreGraphicSignature,ExtendedStateRestore;
 static Config* Instance(){static Config config;return &config;}};
struct D3D12Hooks{
 static bool CanRestoreRootSignature(ID3D12GraphicsCommandList*);
 static bool RestoreDescriptorHeaps(ID3D12GraphicsCommandList*,const D3D12RootRestoreSnapshot&);
 static bool RestorePipelineState(ID3D12GraphicsCommandList*,const D3D12RootRestoreSnapshot&);
 static bool RestoreComputeRootState(ID3D12GraphicsCommandList*,const D3D12RootRestoreSnapshot&);
 static bool RestoreGraphicsRootState(ID3D12GraphicsCommandList*,const D3D12RootRestoreSnapshot&);
 static void RestoreRoot(ID3D12GraphicsCommandList*);
};
enum class Block{None,Heaps,Signature,Arguments,Pipeline};
struct Call{std::string name;UINT parameter=0,offset=0;std::vector<uint64_t> words;};
std::vector<Call> calls;
auto* watched=reinterpret_cast<ID3D12GraphicsCommandList*>(uintptr_t(0x1000));
auto* independent=reinterpret_cast<ID3D12GraphicsCommandList*>(uintptr_t(0x2000));
auto* root=reinterpret_cast<ID3D12RootSignature*>(uintptr_t(0x3000));
auto* heap=reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(0x4000));
auto* pipeline=reinterpret_cast<ID3D12PipelineState*>(uintptr_t(0x5000));
std::mutex blockMutex;std::condition_variable blockCondition;
Block blocked=Block::None;bool entered=false,released=false;
void blockNative(ID3D12GraphicsCommandList* list,Block kind){
 if(list!=watched||blocked!=kind)return;
 std::unique_lock lock(blockMutex);entered=true;blockCondition.notify_all();
 blockCondition.wait(lock,[]{return released;});
}
void heaps(ID3D12GraphicsCommandList* list,UINT count,ID3D12DescriptorHeap*const* values){
 blockNative(list,Block::Heaps);if(list!=watched)return;Call call{"heaps"};
 for(UINT i=0;i<count;++i)call.words.push_back(uintptr_t(values[i]));calls.push_back(std::move(call));
}
void pso(ID3D12GraphicsCommandList* list,ID3D12PipelineState* value){blockNative(list,Block::Pipeline);if(list==watched)calls.push_back({"pso",0,0,{uintptr_t(value)}});}
void signature(ID3D12GraphicsCommandList* list,ID3D12RootSignature* value){blockNative(list,Block::Signature);if(list==watched)calls.push_back({"compute.signature",0,0,{uintptr_t(value)}});}
void graphicsSignature(ID3D12GraphicsCommandList* list,ID3D12RootSignature* value){blockNative(list,Block::Signature);if(list==watched)calls.push_back({"graphics.signature",0,0,{uintptr_t(value)}});}
void table(ID3D12GraphicsCommandList* list,UINT parameter,D3D12_GPU_DESCRIPTOR_HANDLE value){blockNative(list,Block::Arguments);if(list==watched)calls.push_back({"table",parameter,0,{value.ptr}});}
void many(ID3D12GraphicsCommandList* list,UINT parameter,UINT count,const void* data,UINT offset){
 blockNative(list,Block::Arguments);if(list!=watched)return;Call call{"many",parameter,offset};
 const auto* values=static_cast<const uint32_t*>(data);for(UINT i=0;i<count;++i)call.words.push_back(values[i]);calls.push_back(std::move(call));
}
void one(ID3D12GraphicsCommandList* list,UINT parameter,UINT value,UINT offset){blockNative(list,Block::Arguments);if(list==watched)calls.push_back({"one",parameter,offset,{value}});}
void cbv(ID3D12GraphicsCommandList* list,UINT parameter,D3D12_GPU_VIRTUAL_ADDRESS value){blockNative(list,Block::Arguments);if(list==watched)calls.push_back({"cbv",parameter,0,{value}});}
void srv(ID3D12GraphicsCommandList* list,UINT parameter,D3D12_GPU_VIRTUAL_ADDRESS value){blockNative(list,Block::Arguments);if(list==watched)calls.push_back({"srv",parameter,0,{value}});}
void uav(ID3D12GraphicsCommandList* list,UINT parameter,D3D12_GPU_VIRTUAL_ADDRESS value){blockNative(list,Block::Arguments);if(list==watched)calls.push_back({"uav",parameter,0,{value}});}
__TRACKERS__
__RESTORE__
unsigned checks=0;
void need(bool condition,const char* message){if(!condition)throw std::runtime_error(message);++checks;}
void initialize(){
 s_SetDescriptorHeaps={heaps,heaps};s_SetPipelineState={pso,pso};
 s_SetComputeRootSignature={signature,signature};s_SetGraphicsRootSignature={graphicsSignature,graphicsSignature};
 s_SetComputeRootDescriptorTable={table,table};s_SetGraphicsRootDescriptorTable={table,table};
 s_SetComputeRoot32BitConstants={many,many};s_SetGraphicsRoot32BitConstants={many,many};
 s_SetComputeRoot32BitConstant={one,one};s_SetGraphicsRoot32BitConstant={one,one};
 s_SetComputeRootConstantBufferView={cbv,cbv};s_SetGraphicsRootConstantBufferView={cbv,cbv};
 s_SetComputeRootShaderResourceView={srv,srv};s_SetGraphicsRootShaderResourceView={srv,srv};
 s_SetComputeRootUnorderedAccessView={uav,uav};s_SetGraphicsRootUnorderedAccessView={uav,uav};
 rootSigParameterCount[root]=7;signatures[watched]={SignatureEntryType::Compute,root};
 descriptorHeaps[watched]={1,{heap,nullptr}};pipelineStates[watched]=pipeline;rootStates[watched].clear();rootStates[watched].resize(7);
 auto& values=rootStates[watched];
 values[1].type=values[5].type=RootEntryType::Table;values[1].rootDescriptorTable.ptr=101;values[5].rootDescriptorTable.ptr=505;
 MergeBridgeConstants(values[2],0,4,std::array<uint32_t,4>{11,99,33,66}.data());
 MergeBridgeConstants(values[2],5,2,std::array<uint32_t,2>{77,88}.data());
 values[3].type=RootEntryType::CBV;values[3].bufferLocation=0x8000;
 values[4].type=RootEntryType::SRV;values[4].bufferLocation=0x9000;
 values[6].type=RootEntryType::UAV;values[6].bufferLocation=0xa000;
}
void verifyBytes(){
 need(calls.size()==10,"restore emits every original native binding exactly once, including sparse constant ranges");
 need(calls[0].name=="heaps"&&calls[0].words==std::vector<uint64_t>{uintptr_t(heap)}&&calls[1].name=="compute.signature"&&calls[1].words[0]==uintptr_t(root)&&calls.back().name=="pso"&&calls.back().words[0]==uintptr_t(pipeline),"descriptor/signature/arguments/PSO order and raw pointer identity survive");
 need(calls[2].name=="table"&&calls[2].parameter==1&&calls[2].words==std::vector<uint64_t>{101}&&calls[7].name=="table"&&calls[7].parameter==5&&calls[7].words[0]==505&&calls[8].name=="uav"&&calls[8].parameter==6&&calls[8].words[0]==0xa000,"root parameter/table/UAV mapping remains exact");
 need(calls[3].name=="many"&&calls[3].parameter==2&&calls[3].offset==0&&calls[3].words==std::vector<uint64_t>{11,99,33,66}&&calls[4].offset==5&&calls[4].words==std::vector<uint64_t>{77,88},"deep snapshot preserves every constant DWORD and unset sparse gap");
 need(calls[5].name=="cbv"&&calls[5].parameter==3&&calls[5].words[0]==0x8000&&calls[6].name=="srv"&&calls[6].parameter==4&&calls[6].words[0]==0x9000,"root descriptors survive native blocking and producer mutation");
}
void blockedCase(Block kind){
 initialize();calls.clear();blocked=kind;entered=released=false;
 std::exception_ptr restoreError;
 std::thread restore([&]{try{isNrdBridgeInjection=true;D3D12Hooks::RestoreRoot(watched);}catch(...){restoreError=std::current_exception();}});
 bool reached=false;{std::unique_lock lock(blockMutex);reached=blockCondition.wait_for(lock,std::chrono::seconds(2),[]{return entered;});}
 std::promise<void> progress;auto done=progress.get_future();
 std::thread writer([&]{
  // Actual independent-list tracker bodies acquire all four global tracker locks.
  hkSetComputeRootSignature(independent,root);hkSetDescriptorHeaps(independent,1,&heap);hkSetPipelineState(independent,pipeline);
  const uint32_t word=123;hkSetComputeRoot32BitConstants(independent,2,1,&word,0);
  // Direct cache mutation proves snapshot ownership; it is not an allowed title
  // recording concurrently on the same command list.
  {std::unique_lock lock(rootStatesMutex);rootStates[watched].clear();}
  {std::unique_lock lock(descriptorHeapsMutex);descriptorHeaps[watched]={};}
  {std::unique_lock lock(pipelineStatesMutex);pipelineStates[watched]=nullptr;}
  {std::unique_lock lock(rootSignatureMutex);signatures[watched]={};}
  progress.set_value();
 });
 const bool progressed=done.wait_for(std::chrono::seconds(2))==std::future_status::ready;
 {std::lock_guard lock(blockMutex);released=true;}blockCondition.notify_all();writer.join();restore.join();
 if(restoreError)std::rethrow_exception(restoreError);
 need(reached,"deliberately blocked original native setter was reached");
 need(progressed,"independent title tracker writes finish while original native setter remains blocked");
 need(rootStates[independent][2].Data==std::vector<uint32_t>{123},"independent actual tracker data survives blocked restore");
 verifyBytes();
}
NrdBridgePerf::Report profilerReport;bool profilerReported=false;
void rootProfilerCases(){
 using H=NrdBridgePerf::Hook;
 blocked=Block::None;initialize();isNrdBridgeInjection=false;
 Config::Instance()->RestoreComputeSignature.current=true;Config::Instance()->RestoreGraphicSignature.current=true;
 NrdBridgePerf::Configure(+[](const NrdBridgePerf::Report& report)noexcept{profilerReport=report;profilerReported=true;});
 NrdBridgePerf::ConsumerFrame(1000);
 auto invoke=[&]{
  hkSetComputeRootSignature(watched,root);hkSetComputeRootSignatureLate(watched,root);
  hkSetGraphicsRootSignature(watched,root);hkSetGraphicsRootSignatureLate(watched,root);
  const uint32_t words[]={111,222};
  hkSetComputeRoot32BitConstants(watched,2,2,words,0);hkSetComputeRoot32BitConstantsLate(watched,2,2,words,0);
  hkSetComputeRoot32BitConstant(watched,2,333,1);hkSetComputeRoot32BitConstantLate(watched,2,333,1);
  hkSetGraphicsRoot32BitConstants(watched,2,2,words,0);hkSetGraphicsRoot32BitConstantsLate(watched,2,2,words,0);
  hkSetGraphicsRoot32BitConstant(watched,2,333,1);hkSetGraphicsRoot32BitConstantLate(watched,2,333,1);
  hkSetComputeRootConstantBufferView(watched,3,0x8000);hkSetComputeRootConstantBufferViewLate(watched,3,0x8000);
  hkSetComputeRootShaderResourceView(watched,4,0x9000);hkSetComputeRootShaderResourceViewLate(watched,4,0x9000);
  hkSetComputeRootUnorderedAccessView(watched,6,0xa000);hkSetComputeRootUnorderedAccessViewLate(watched,6,0xa000);
  hkSetGraphicsRootConstantBufferView(watched,3,0x8000);hkSetGraphicsRootConstantBufferViewLate(watched,3,0x8000);
  hkSetGraphicsRootShaderResourceView(watched,4,0x9000);hkSetGraphicsRootShaderResourceViewLate(watched,4,0x9000);
  hkSetGraphicsRootUnorderedAccessView(watched,6,0xa000);hkSetGraphicsRootUnorderedAccessViewLate(watched,6,0xa000);
  hkSurveySetComputeRootSignature(watched,root);hkSurveySetGraphicsRootSignature(watched,root);
  hkSurveySetComputeRootConstantBufferView(watched,3,0x8000);
  hkSurveySetComputeRootShaderResourceView(watched,4,0x9000);
  hkSurveySetComputeRootUnorderedAccessView(watched,6,0xa000);
 };
 gNrdBridgeDeviceWrappers=false;calls.clear();invoke();
 need(calls.size()==29,"startup OFF profiling preserves all29 original native setter calls");
 gNrdBridgeDeviceWrappers=true;FrameSurvey::internalScope=true;isNrdBridgeInjection=true;calls.clear();invoke();
 need(calls.size()==29,"internal injection preserves all29 original native setter calls");
 for(auto hook:{H::RootSignature,H::RootConstants,H::RootView})
  need(NrdBridgePerf::Detail::Get().hooks[size_t(hook)].calls.load()==0,"startup OFF and internal callbacks never enter gameplay profiler");
 FrameSurvey::internalScope=false;isNrdBridgeInjection=false;calls.clear();invoke();
 need(calls.size()==29,"profiling active external callbacks preserve every original native call");
 need(NrdBridgePerf::Detail::Get().hooks[size_t(H::RootSignature)].calls.load()==6,"signature scopes include survey metadata and deduplicate delegated early body");
 need(NrdBridgePerf::Detail::Get().hooks[size_t(H::RootConstants)].calls.load()==8,"all early/late compute/graphics constant setter scopes measured once");
 need(NrdBridgePerf::Detail::Get().hooks[size_t(H::RootView)].calls.load()==15,"view scopes include survey metadata and deduplicate delegated early body");
 s_SetComputeRootSignature.o_earlyHook=+[](ID3D12GraphicsCommandList* list,ID3D12RootSignature* value){hkSetComputeRootSignatureLate(list,value);};
 calls.clear();hkSurveySetComputeRootSignature(watched,root);
 need(calls.size()==1&&calls[0].name=="compute.signature","survey-to-early-to-late native forwarding calls final original setter exactly once");
 need(NrdBridgePerf::Detail::Get().hooks[size_t(H::RootSignature)].calls.load()==7,"same-Hook physical forwarding has one profiler sample across three wrapper bodies");
 for(uint32_t frame=1001;frame<=1100;++frame)NrdBridgePerf::ConsumerFrame(frame);
 need(profilerReported&&profilerReport.frames==100,"production gameplay sampler publishes all root samples at its real100-interval boundary");
 uint64_t measured=0;
 for(auto hook:{H::RootSignature,H::RootConstants,H::RootView}){
  const auto& sample=profilerReport.hooks[size_t(hook)];measured+=sample.calls;
  need(sample.waitTicks[size_t(NrdBridgePerf::WaitKind::Tracking)]<=sample.ticks,"tracking acquisition wait remains within inclusive native/hook duration");
 }
 need(measured==30,"exact root sample total excludes startup OFF/internal calls and nested physical aliases");
 need(NrdBridgePerf::Detail::Get().inFlight.load()==0&&!NrdBridgePerf::Detail::currentWaits,"scopes restore profiling thread state after every title callback");
}
int main()try{
 SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);
 static_assert(std::is_trivially_destructible_v<D3D12RootRestoreSnapshot>);
 for(auto kind:{Block::Heaps,Block::Signature,Block::Arguments,Block::Pipeline})blockedCase(kind);
 blocked=Block::None;initialize();calls.clear();Config::Instance()->RestoreComputeSignature.current=false;Config::Instance()->RestoreGraphicSignature.current=false;
 isNrdBridgeInjection=false;D3D12Hooks::RestoreRoot(watched);need(calls.empty(),"disabled restore flags retain exact no-setter legacy behavior");
 isNrdBridgeInjection=true;Config::Instance()->ExtendedStateRestore.current=false;D3D12Hooks::RestoreRoot(watched);verifyBytes();
 Config::Instance()->RestoreComputeSignature.current=true;Config::Instance()->ExtendedStateRestore.current=true;isNrdBridgeInjection=false;
 need(D3D12Hooks::CanRestoreRootSignature(watched),"complete legal snapshot passes bridge preflight");
 rootStates[watched][2].Data.resize(65);need(!D3D12Hooks::CanRestoreRootSignature(watched),"oversized constant cache rejects before bridge admission without truncation");
 calls.clear();D3D12Hooks::RestoreRoot(watched);need(calls.empty(),"invalid snapshot never partially replays title state");
 initialize();rootStates[watched].resize(65);need(!D3D12Hooks::CanRestoreRootSignature(watched),"oversized root parameter cache rejects before bridge admission");
 rootStates[watched].clear();initialize();rootStates[watched][2]={};rootStates[watched][2].type=RootEntryType::Constant;rootStates[watched][2].Data={321};rootStates[watched][2].DestOffset=4;
 gNrdBridgeDeviceWrappers=false;calls.clear();D3D12Hooks::RestoreRoot(watched);
 need(calls[3].name=="one"&&calls[3].offset==4&&calls[3].words==std::vector<uint64_t>{321},"startup OFF retains original single-value offset mapping");
 signatures[watched].type=SignatureEntryType::Graphics;calls.clear();D3D12Hooks::RestoreRoot(watched);need(calls[1].name=="graphics.signature"&&calls[3].name=="one"&&calls[3].offset==4,"graphics snapshot replay keeps original signature and argument family");
 Config::Instance()->ExtendedStateRestore.current=false;calls.clear();D3D12Hooks::RestoreRoot(watched);need(calls.size()==1&&calls[0].name=="graphics.signature","nonextended restoration sets only original root signature");
 rootProfilerCases();
 std::cout<<"PASS: "<<checks<<" actual restore snapshot/concurrent tracker/profiling checks; snapshot_bytes="<<sizeof(D3D12RootRestoreSnapshot)<<'\n';return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
'''


def run():
    source = (ROOT/'OptiScaler/hooks/D3D12_Hooks.cpp').read_text()
    state = source[source.index('// Common'):source.index('// Intel Atomic Extension')]
    state = state.replace('ankerl::unordered_dense::map', 'std::unordered_map')
    names = re.findall(r'static void (hk(?:Survey)?Set(?:Compute|Graphics)Root(?:Signature|32BitConstants?|ConstantBufferView|ShaderResourceView|UnorderedAccessView)(?:Late)?)\(', source)
    assert len(names) == 29
    signatures = ('UINT GetRootParameterCount(', 'static void hkSetDescriptorHeaps(',
                  'static void hkSetPipelineState(') + tuple('static void ' + name + '(' for name in names)
    trackers = '\n'.join(function(source, signature) for signature in signatures)
    restore = '\n'.join(function(source, signature) for signature in (
        'static bool CaptureRootRestoreSnapshot(', 'bool D3D12Hooks::CanRestoreRootSignature(',
        'bool D3D12Hooks::RestoreDescriptorHeaps(', 'bool D3D12Hooks::RestorePipelineState(',
        'bool D3D12Hooks::RestoreComputeRootState(', 'bool D3D12Hooks::RestoreGraphicsRootState(',
        'void D3D12Hooks::RestoreRoot('))
    cpp = CPP.replace('__ROOT__', ROOT.as_posix()).replace('__STATE__', state).replace('__TRACKERS__', trackers).replace('__RESTORE__', restore)
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    file, exe = out/'restore_locks.cpp', out/'restore_locks.exe'
    file.write_text(cpp)
    if os.environ.get('FSRD_RESTORE_GENERATE_ONLY') == '1':
        return file
    compile_cpp(file, exe)
    result = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
    print(result.stdout, end='')
    (out/'result.json').write_text(json.dumps({'checks': int(result.stdout.split()[1]),
        'scope': 'actual production capture/restore/trackers, blocking native CPU adapters, no COM/GPU lifetime or timing-gain claim',
        'output': result.stdout}, indent=2))


if __name__ == '__main__':
    run()
