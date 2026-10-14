"""CPU execution of production resource creation wrappers and device transactions.

The CPU phase uses SDK virtual calls over independent fake COM surfaces. Set
FSRD_RESOURCE_CREATION_NATIVE_DEVICES=1 under the GPU lock to create actual RX/WARP
resources and CBVs. Production Register/index/CBV callbacks resolve a synthetic
b6 layout. No dispatch, real detour patching or game creation variant is proven.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp
from test_fsrd_nrd_root_restore import function


METHODS = (
    ('CreateReservedResource', 30, 'base', False, False),
    ('CreateCommittedResource1', 53, 'v4', False, False),
    ('CreateReservedResource1', 55, 'v4', False, False),
    ('CreateCommittedResource2', 69, 'v8', False, False),
    ('CreatePlacedResource1', 70, 'v8', False, True),
    ('CreateCommittedResource3', 76, 'v10', True, False),
    ('CreatePlacedResource2', 77, 'v10', True, True),
    ('CreateReservedResource2', 78, 'v10', True, False),
    ('CreateCommittedResource', 27, 'base', False, False),
    ('CreatePlacedResource', 29, 'base', False, True),
)

CPP = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <iostream>
#include <map>
#include <mutex>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "__ROOT__/OptiScaler/hooks/Hook_Utils.h"
#include "__ROOT__/OptiScaler/resource_tracking/FrameSurvey_Dx12.h"
#include "__ROOT__/OptiScaler/resource_tracking/FrameSurveyBufferRanges.h"
#define LOG_DEBUG(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
#define LOG_FUNC(...) ((void)0)
unsigned checks=0;
void need(bool ok,const char* why){if(!ok)throw std::runtime_error(why);++checks;}
namespace FrameSurvey {
thread_local bool gInternal=false;
thread_local unsigned gRecordingDepth=0;
std::atomic<bool> gTracking=false,gEnabled=false,gSurveyBindings=false,gBindingWindow=true,gMetadataHealthy=true;
std::recursive_mutex gLifetimeMutex;
uint64_t gNextResource=0;
unsigned stateCalls=0,layoutCalls=0;
struct MetadataMutation {};
void MetadataFailed(const char*){gMetadataHealthy.store(false);}
__REGISTRY__
__MIRROR__
__META_FUNCTIONS__
__CREATION_CALLBACKS__
void ResourceCreated(ID3D12Resource* p,D3D12_RESOURCE_STATES state,ID3D12Heap* heap,uint64_t offset) noexcept {
 ++stateCalls; ActualResourceCreated(p,state,heap,offset);
}
void ResourceCreatedWithLayout(ID3D12Resource* p,D3D12_BARRIER_LAYOUT layout,ID3D12Heap* heap,uint64_t offset) noexcept {
 ++layoutCalls; ActualResourceCreatedWithLayout(p,layout,heap,offset);
}
void clean(){gResources.clear();gAddresses.clear();gBufferAddresses=FrameSurveyMetadata::BufferAddressIndex{};
 gViews.clear();gHeaps.clear();gCpuHeaps.clear();gRootLayouts.clear();gMirror.clear();stateCalls=layoutCalls=0;gMetadataHealthy=true;}
}
struct Flag {bool value=false;bool value_or_default() const{return value;}};
struct Config {Flag FfxDenoiserFrameSurvey,UESpoofIntelAtomics64,FGDisableHUDFix;
 static Config* Instance(){static Config c;return &c;}};
enum class FGInput {None,Upscaler};enum class FGOutput {None,DLSSG};enum class SwapchainInteropApi {None};
struct State {FGInput activeFgInput=FGInput::None;FGOutput activeFgOutput=FGOutput::None;
 SwapchainInteropApi swapchainInteropApi=SwapchainInteropApi::None;ID3D12Device* currentD3D12Device=nullptr;
 static State& Instance(){static State state;return state;}};
bool bridgeStartup=false;unsigned initializeCalls=0,unavailableCalls=0,listHookCalls=0,resourceHookCalls=0,resourceUnhookCalls=0;
namespace NrdBridge {bool StartupEnabled(){return bridgeStartup;}bool Initialize(ID3D12Device*){++initializeCalls;return true;}
 void ReportUnavailable(const char*){++unavailableCalls;}}
namespace NrdBridgeDevice {Microsoft::WRL::ComPtr<ID3D12Device> Native(ID3D12Device* p){return Microsoft::WRL::ComPtr<ID3D12Device>(p);}
 bool Selected(ID3D12Device*,ID3D12Device*){return true;}}
namespace ResTrack_Dx12 {void HookDevice(ID3D12Device*){++resourceHookCalls;}void ReleaseDeviceHooks(){++resourceUnhookCalls;}}
namespace StreamlineProxy {bool LoadStreamline(){return false;}void InitWithD3D12(ID3D12Device*){}}
void HookToCommandList(ID3D12Device*){++listHookCalls;}
__TYPES__
__GLOBALS__
bool _skipCommitedResource=false,skipPlacedResource=false;
struct UE_D3D12_RESOURCE_DESC {bool bRequires64BitAtomicSupport=false;};
namespace IGDExtProxy {
 template<class... Args> HRESULT CreateCommitedResource(Args...){throw std::runtime_error("Unexpected Intel path");}
 template<class... Args> HRESULT CreatePlacedResource(Args...){throw std::runtime_error("Unexpected Intel path");}
}
struct FakeResource final: ID3D12Resource {
 ULONG refs=1;unsigned descriptions=0,addresses=0;uint64_t va=0x100000;
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID,void** p) override{if(p)*p=nullptr;return E_NOINTERFACE;}
 ULONG STDMETHODCALLTYPE AddRef() override{return ++refs;}ULONG STDMETHODCALLTYPE Release() override{return --refs;}
 HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID,UINT*,void*) override{return E_FAIL;}
 HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID,UINT,const void*) override{return S_OK;}
 HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID,const IUnknown*) override{return S_OK;}
 HRESULT STDMETHODCALLTYPE SetName(LPCWSTR) override{return S_OK;}
 HRESULT STDMETHODCALLTYPE GetDevice(REFIID,void**) override{return E_FAIL;}
 HRESULT STDMETHODCALLTYPE Map(UINT,const D3D12_RANGE*,void**) override{return E_FAIL;}
 void STDMETHODCALLTYPE Unmap(UINT,const D3D12_RANGE*) override{}
 D3D12_RESOURCE_DESC STDMETHODCALLTYPE GetDesc() override{++descriptions;D3D12_RESOURCE_DESC d{};
 d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;d.Width=4096;d.Height=1;d.DepthOrArraySize=1;d.MipLevels=1;return d;}
 D3D12_GPU_VIRTUAL_ADDRESS STDMETHODCALLTYPE GetGPUVirtualAddress() override{++addresses;return va;}
 HRESULT STDMETHODCALLTYPE WriteToSubresource(UINT,const D3D12_BOX*,const void*,UINT,UINT) override{return E_FAIL;}
 HRESULT STDMETHODCALLTYPE ReadFromSubresource(void*,UINT,UINT,UINT,const D3D12_BOX*) override{return E_FAIL;}
 HRESULT STDMETHODCALLTYPE GetHeapProperties(D3D12_HEAP_PROPERTIES*,D3D12_HEAP_FLAGS*) override{return E_FAIL;}
} resource;
struct FakeDevice;
struct Interface {PVOID* table=nullptr;FakeDevice* owner=nullptr;};
struct FakeDevice {
 std::array<PVOID,79> table{},table4{},table8{},table10{};
 Interface base{table.data(),this},v4{table4.data(),this},v8{table8.data(),this},v10{table10.data(),this};
 unsigned version=10,refs=1,queries=0,modernQueries=0;
 FakeDevice();void apply(PVOID native,PVOID replacement){for(auto* surface:{&table,&table4,&table8,&table10})
 for(auto& entry:*surface)if(entry==native)entry=replacement;}
};
FakeDevice* currentDevice=nullptr;
HRESULT WINAPI NativeQI(IUnknown* p,REFIID id,void** out){auto& d=*reinterpret_cast<Interface*>(p)->owner;++d.queries;*out=nullptr;
 if(id==__uuidof(ID3D12Device4)||id==__uuidof(ID3D12Device8)||id==__uuidof(ID3D12Device10))++d.modernQueries;
 if(id==__uuidof(ID3D12Device4)&&d.version>=4)*out=&d.v4;
 else if(id==__uuidof(ID3D12Device8)&&d.version>=8)*out=&d.v8;
 else if(id==__uuidof(ID3D12Device10)&&d.version>=10)*out=&d.v10;
 else if(id==__uuidof(ID3D12Device1)||id==__uuidof(ID3D12Device)||id==__uuidof(IUnknown))*out=&d.base;
 if(!*out)return E_NOINTERFACE;++d.refs;return S_OK;
}
ULONG WINAPI NativeAdd(IUnknown* p){return ++reinterpret_cast<Interface*>(p)->owner->refs;}
ULONG WINAPI NativeRelease(IUnknown* p){return --reinterpret_cast<Interface*>(p)->owner->refs;}
std::atomic<unsigned> uniqueEntries[5]{};
void WINAPI NativeSampler(ID3D12Device*,const D3D12_SAMPLER_DESC*,D3D12_CPU_DESCRIPTOR_HANDLE){++uniqueEntries[0];}
HRESULT WINAPI NativeFeature(ID3D12Device*,D3D12_FEATURE,void*,UINT){++uniqueEntries[1];return S_OK;}
HRESULT WINAPI NativeRoot(ID3D12Device*,UINT,const void*,SIZE_T,REFIID,void**){++uniqueEntries[2];return S_OK;}
HRESULT WINAPI NativeResidency(ID3D12Device1*,UINT,ID3D12Pageable* const*,const D3D12_RESIDENCY_PRIORITY*){++uniqueEntries[3];return S_OK;}
void WINAPI NativeAllocation(ID3D12Device*,D3D12_RESOURCE_ALLOCATION_INFO*,UINT,UINT,D3D12_RESOURCE_DESC*){++uniqueEntries[4];}
void WINAPI hkCreateSampler(ID3D12Device*,const D3D12_SAMPLER_DESC*,D3D12_CPU_DESCRIPTOR_HANDLE){}
HRESULT WINAPI hkCheckFeatureSupport(ID3D12Device*,D3D12_FEATURE,void*,UINT){return S_OK;}
HRESULT WINAPI hkCreateRootSignature(ID3D12Device*,UINT,const void*,SIZE_T,REFIID,void**){return S_OK;}
HRESULT WINAPI hkSurveyCreateRootSignature(ID3D12Device*,UINT,const void*,SIZE_T,REFIID,void**){return S_OK;}
HRESULT WINAPI hkSetResidencyPriority(ID3D12Device1*,UINT,ID3D12Pageable* const*,const D3D12_RESIDENCY_PRIORITY*){return S_OK;}
void WINAPI hkGetResourceAllocationInfo(ID3D12Device*,D3D12_RESOURCE_ALLOCATION_INFO*,UINT,UINT,D3D12_RESOURCE_DESC*){}
ULONG WINAPI hkD3D12DeviceRelease(IUnknown* p){return NativeRelease(p);}
struct Pending {PVOID* target;PVOID native,hook;bool attach;};std::vector<Pending> pending;
unsigned beginCalls=0,attachCalls=0,detachCalls=0,commitCalls=0,abortCalls=0;
unsigned failAttach=0,failDetach=0;bool failCommit=false;
LONG WINAPI DetourTransactionBegin(){++beginCalls;pending.clear();return NO_ERROR;}
LONG WINAPI DetourUpdateThread(HANDLE){return NO_ERROR;}
LONG WINAPI DetourAttach(PVOID* p,PVOID h){++attachCalls;if(attachCalls==failAttach)return ERROR_INVALID_FUNCTION;
 pending.push_back({p,*p,h,true});return NO_ERROR;}
LONG WINAPI DetourDetach(PVOID* p,PVOID h){++detachCalls;if(detachCalls==failDetach)return ERROR_INVALID_FUNCTION;
 pending.push_back({p,*p,h,false});return NO_ERROR;}
LONG WINAPI DetourTransactionAbort(){++abortCalls;pending.clear();return NO_ERROR;}
LONG WINAPI DetourTransactionCommit(){++commitCalls;if(failCommit){pending.clear();return ERROR_ACCESS_DENIED;}
 if(currentDevice)for(const auto& item:pending)currentDevice->apply(item.attach?item.native:item.hook,item.attach?item.hook:item.native);
 pending.clear();return NO_ERROR;}
__RESOURCE_WRAPPERS__
__INSTALL_HELPERS__
__HOOK_DEVICE__
__UNHOOK_DEVICE__
struct D3D12Hooks {static void Unhook();};PVOID o_D3D12CreateDevice=reinterpret_cast<PVOID>(1);
__UNHOOK_ALL__
__ABI_ASSERTS__
template<class T> uint64_t arg(T value){if constexpr(std::is_pointer_v<T>)return reinterpret_cast<uintptr_t>(value);
 else return static_cast<uint64_t>(value);}
std::array<unsigned,10> nativeCalls{};
std::array<std::vector<uint64_t>,10> expected;
HRESULT nativeResult=S_OK;bool nullResult=false,throwNative=false,forwardModern=false,forwardBase=false;
HRESULT finish(unsigned index,void** out,std::vector<uint64_t> args){++nativeCalls[index];need(args==expected[index],"Native ABI/arguments/This forwarded unchanged");
 if(throwNative)throw std::runtime_error("native test exception");if(out)*out=nullResult?nullptr:static_cast<ID3D12Resource*>(&resource);return nativeResult;}
__NATIVE_METHODS__
FakeDevice::FakeDevice(){table[0]=reinterpret_cast<PVOID>(NativeQI);table[1]=reinterpret_cast<PVOID>(NativeAdd);table[2]=reinterpret_cast<PVOID>(NativeRelease);
 table[13]=reinterpret_cast<PVOID>(NativeFeature);table[16]=reinterpret_cast<PVOID>(NativeRoot);table[22]=reinterpret_cast<PVOID>(NativeSampler);
 table[25]=reinterpret_cast<PVOID>(NativeAllocation);table[46]=reinterpret_cast<PVOID>(NativeResidency);
 __POPULATE_TABLE__
 table4=table8=table10=table;}
void needModernNative(FakeDevice& d){__CHECK_NATIVE_TABLE__}
D3D12_HEAP_PROPERTIES hp{};D3D12_RESOURCE_DESC desc{};D3D12_RESOURCE_DESC1 desc1{};D3D12_CLEAR_VALUE clear{};
auto* heap=reinterpret_cast<ID3D12Heap*>(0x123400);auto* session=reinterpret_cast<ID3D12ProtectedResourceSession*>(0x234500);
const DXGI_FORMAT formats[]={DXGI_FORMAT_R32_FLOAT,DXGI_FORMAT_R16_FLOAT};constexpr UINT64 heapOffset=0x10000;
const D3D12_RESOURCE_STATES state=D3D12_RESOURCE_STATE_VERTEX_AND_CONSTANT_BUFFER;
const D3D12_BARRIER_LAYOUT layout=D3D12_BARRIER_LAYOUT_GENERIC_READ;
const IID& riid=__uuidof(ID3D12Resource);
void prepareExpected(FakeDevice& d){__EXPECTED__}
HRESULT invoke(unsigned method,FakeDevice& d,void** out){switch(method){__INVOKE__default:throw std::runtime_error("method index");}}
void resetGlobals(){ResetSurveyResourceCreationHooks();o_CreateSampler=nullptr;o_CheckFeatureSupport=nullptr;o_CreateRootSignature=nullptr;
 o_CreateCommittedResource=nullptr;o_CreatePlacedResource=nullptr;o_SetResidencyPriority=nullptr;o_D3D12DeviceRelease=nullptr;o_GetResourceAllocationInfo=nullptr;
 gSurveyDeviceWrappers=gNrdBridgeDeviceWrappers=false;beginCalls=attachCalls=detachCalls=commitCalls=abortCalls=0;failAttach=failDetach=0;failCommit=false;
 listHookCalls=resourceHookCalls=resourceUnhookCalls=0;initializeCalls=unavailableCalls=0;nativeCalls.fill(0);
 nativeResult=S_OK;nullResult=throwNative=forwardModern=forwardBase=false;bridgeStartup=false;Config::Instance()->FfxDenoiserFrameSurvey.value=false;
 FrameSurvey::gTracking=false;FrameSurvey::gSurveyBindings=false;FrameSurvey::clean();}
void install(FakeDevice& d,bool survey=true,bool bridge=false){currentDevice=&d;State::Instance().currentD3D12Device=reinterpret_cast<ID3D12Device*>(&d.base);
 Config::Instance()->FfxDenoiserFrameSurvey.value=survey;bridgeStartup=bridge;HookToDevice(reinterpret_cast<ID3D12Device*>(&d.base));prepareExpected(d);}
void needAllClear(){need(!o_CreateReservedResource&&!o_CreateCommittedResource1&&!o_CreateReservedResource1&&!o_CreateCommittedResource2&&
 !o_CreatePlacedResource1&&!o_CreateCommittedResource3&&!o_CreatePlacedResource2&&!o_CreateReservedResource2,"All eight modern/reserved targets cleared");}
void cbvProof(){using namespace FrameSurvey;auto* root=reinterpret_cast<ID3D12RootSignature*>(0x456700);
 auto* list=reinterpret_cast<ID3D12GraphicsCommandList*>(0x567800);auto& r=gMirror[list].compute;r.object=root;
 r.views[3]={D3D12_DESCRIPTOR_RANGE_TYPE_CBV,resource.va+256};auto& l=gRootLayouts[root];l.complete=true;
 l.computeDescriptors[3]={D3D12_DESCRIPTOR_RANGE_TYPE_CBV,6,0};BoundConstantBuffer out;ConstantBufferDiagnostic diagnostic;
 need(ResolveComputeConstantBuffer(list,6,0,1216,out,&diagnostic)&&out.resource==&resource&&out.offset==256&&out.size==3840&&out.resourceGeneration,
 "Actual creation registry/index resolves synthetic Consumer b6/space0 with exact 1216-byte coverage");
 need(!ResolveComputeConstantBuffer(list,6,1,1216,out,&diagnostic),"Wrong b6 register space remains rejected");}
void realDevices();
int main(int argc,char** argv){try{
 resetGlobals();{FakeDevice d;install(d,false);need(d.modernQueries==0&&attachCalls==4,"Startup OFF keeps only four preexisting device detours and no modern QI");needAllClear();
 void* out=nullptr;invoke(5,d,&out);need(nativeCalls[5]==1&&FrameSurvey::gResources.empty()&&!FrameSurvey::stateCalls&&!FrameSurvey::layoutCalls,"OFF modern native creation executes once without metadata");}
 for(unsigned version:{0u,4u,8u,10u}){resetGlobals();FakeDevice d;d.version=version;install(d);
 if(!o_CreateSampler)std::cerr<<"Rejected version="<<version<<" attach="<<attachCalls<<" commit="<<commitCalls<<"\n";
 need(attachCalls==8+(version==0?1:version==4?3:version==8?5:8)&&commitCalls==1,"Only advertised creation variants join the existing device transaction");
 need(d.refs==1&&d.modernQueries==3,"All three interface probes release balanced independent COM surfaces");
 UnhookDevice();needAllClear();needModernNative(d);need(commitCalls==2,"Device teardown commits removal of advertised creation methods");}
 resetGlobals();FakeDevice d;install(d,true,true);need(initializeCalls==1&&gNrdBridgeDeviceWrappers&&attachCalls==16,"Bridge startup also selects all eight creation detours");
 for(unsigned index=0;index<10;++index){FrameSurvey::clean();nativeCalls.fill(0);void* out=nullptr;
 need(invoke(index,d,&out)==S_OK&&out==&resource&&nativeCalls[index]==1,"Each SDK virtual resource API forwards native once");
 const bool enhanced=index>=5&&index<=7;const bool placed=index==4||index==6||index==9;
 need(FrameSurvey::stateCalls==unsigned(!enhanced)&&FrameSurvey::layoutCalls==unsigned(enhanced),"Each creation emits exactly one correct callback family");
 const auto& r=FrameSurvey::gResources.at(&resource);need(r.initialKnown==!enhanced&&(!r.initialKnown||r.initial==state),"Enhanced layouts never fabricate legacy initial states");
 need(r.heap==(placed?reinterpret_cast<uintptr_t>(heap):0)&&r.offset==(placed?heapOffset:0),"Placed heap and offset survive creation metadata");cbvProof();
 for(unsigned mode=0;mode<3;++mode){FrameSurvey::clean();nativeCalls.fill(0);out=nullptr;nativeResult=mode==0?E_FAIL:S_OK;nullResult=mode==1;
 need(invoke(index,d,mode==2?nullptr:&out)==nativeResult&&nativeCalls[index]==1,"Failure/null-result/null-output preserves native result and one call");
 need(FrameSurvey::gResources.empty()&&!FrameSurvey::stateCalls&&!FrameSurvey::layoutCalls,"Failure and missing result do not invent creation metadata");}
 nativeResult=S_OK;nullResult=false;FrameSurvey::clean();nativeCalls.fill(0);{FrameSurvey::ScopedInternal internal;invoke(index,d,&out);
 need(nativeCalls[index]==1&&FrameSurvey::gResources.empty()&&!FrameSurvey::stateCalls&&!FrameSurvey::layoutCalls,"Internal creation forwards once with zero metadata callbacks");}
 need(!FrameSurvey::Internal()&&gSurveyResourceCreationDepth==0,"Creation TLS restores after internal work");}
 FrameSurvey::clean();nativeCalls.fill(0);forwardModern=forwardBase=true;void* out=nullptr;
 need(invoke(5,d,&out)==S_OK&&nativeCalls[5]==1&&nativeCalls[3]==1&&nativeCalls[8]==1,"Real modern-to-legacy forwarding visits each native implementation once");
 need(FrameSurvey::stateCalls==0&&FrameSurvey::layoutCalls==1&&!FrameSurvey::gResources.at(&resource).initialKnown,"Nested older hooks cannot overwrite outer enhanced metadata");
 forwardModern=forwardBase=false;FrameSurvey::clean();throwNative=true;try{invoke(0,d,&out);need(false,"Native throw must propagate");}catch(const std::runtime_error& e){need(std::string(e.what())=="native test exception","Native exception preserved");}
 need(gSurveyResourceCreationDepth==0&&!FrameSurvey::Internal(),"Creation depth unwinds after a native exception");throwNative=false;invoke(0,d,&out);
 need(FrameSurvey::stateCalls==1,"The next title creation is observed after exception unwind");
 failDetach=detachCalls+9;UnhookDevice();need(abortCalls==1&&o_CreateCommittedResource3,"Partial detach failure aborts and retains original targets");failDetach=0;
 D3D12Hooks::Unhook();needAllClear();needModernNative(d);need(d.table10[76]==reinterpret_cast<PVOID>(NativeCreateCommittedResource3),"Global teardown restores new native entries");
 for(unsigned which=0;which<3;++which){resetGlobals();FakeDevice a;if(which==0)a.table10[76]=a.table[27];
 else if(which==1)a.table10[77]=a.table10[78];else a.table8[69]=nullptr;install(a,true,true);
 need(beginCalls==0&&attachCalls==0&&!o_CreateSampler,"ABI alias or missing advertised slot rejects the whole installation before any detour");
 needAllClear();need(!FrameSurvey::MetadataHealthy()&&unavailableCalls==1&&a.refs==1,"Unsafe creation coverage reports unavailable with balanced references");}
 for(unsigned failure=0;failure<2;++failure){resetGlobals();FakeDevice a;failAttach=failure==0?13:0;failCommit=failure==1;install(a,true,true);
 needAllClear();need(!o_CreateSampler&&!FrameSurvey::MetadataHealthy()&&unavailableCalls==1,"Attach and commit failures clear all captures and fail closed");
 need(abortCalls==unsigned(failure==0)&&commitCalls==unsigned(failure==1),"Partial attachment is aborted; commit failures are not reported as installed");
 FrameSurvey::clean();invoke(5,a,&out);need(nativeCalls[5]==1&&FrameSurvey::gResources.empty(),"Failed installation leaves modern native execution unchanged");}
 if(argc>1&&std::string(argv[1])=="--native-devices")realDevices();
 std::cout<<"PASS: "<<checks<<" actual creation/ABI/transaction/index checks\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
__REAL_DEVICES__
'''

REAL = r'''
using Microsoft::WRL::ComPtr;
std::array<PVOID,10> realEntries{};std::array<unsigned,10> realCalls{};
__REAL_SPIES__
void checkHR(HRESULT result,const char* where){if(FAILED(result)){std::cerr<<where<<" HRESULT=0x"<<std::hex<<unsigned(result)<<std::dec<<"\n";
 throw std::runtime_error(where);}++checks;}
void deviceRun(IDXGIAdapter* adapter,const char* label){resetGlobals();currentDevice=nullptr;
 ComPtr<ID3D12Device> device;checkHR(D3D12CreateDevice(adapter,D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)),"Native D3D12 device");
 State::Instance().currentD3D12Device=device.Get();Config::Instance()->FfxDenoiserFrameSurvey.value=true;
 HookToDevice(device.Get());if(!o_CreateSampler){std::cerr<<label<<" production alias/null preflight rejected native interfaces\n";
 throw std::runtime_error("Native production device selection rejected");}
 need(commitCalls==1&&FrameSurvey::MetadataHealthy(),"Actual available native device entries stage in one production installation transaction");
 ComPtr<ID3D12Device4> v4;ComPtr<ID3D12Device8> v8;ComPtr<ID3D12Device10> v10;
 device.As(&v4);device.As(&v8);device.As(&v10);
 __SAVE_REAL_ENTRIES__
 D3D12_FEATURE_DATA_D3D12_OPTIONS options{};checkHR(device->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS,&options,sizeof(options)),"Native tiled options");
 D3D12_HEAP_PROPERTIES properties{};properties.Type=D3D12_HEAP_TYPE_DEFAULT;
 D3D12_RESOURCE_DESC nativeDesc{};nativeDesc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;nativeDesc.Width=65536;nativeDesc.Height=1;
 nativeDesc.DepthOrArraySize=1;nativeDesc.MipLevels=1;nativeDesc.SampleDesc.Count=1;nativeDesc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
 D3D12_RESOURCE_DESC1 nativeDesc1{};memcpy(&nativeDesc1,&nativeDesc,sizeof(nativeDesc));
 D3D12_HEAP_DESC heapDescription{};heapDescription.SizeInBytes=65536;heapDescription.Properties=properties;
 heapDescription.Flags=D3D12_HEAP_FLAG_ALLOW_ONLY_BUFFERS;
 ComPtr<ID3D12Heap> placedHeap;checkHR(device->CreateHeap(&heapDescription,IID_PPV_ARGS(&placedHeap)),"Native placed heap");
 D3D12_DESCRIPTOR_HEAP_DESC descriptorDescription{};descriptorDescription.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
 descriptorDescription.NumDescriptors=1;descriptorDescription.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
 ComPtr<ID3D12DescriptorHeap> cbvHeap;checkHR(device->CreateDescriptorHeap(&descriptorDescription,IID_PPV_ARGS(&cbvHeap)),"Native CBV heap");
 const char* names[]={__METHOD_NAMES__};
 for(unsigned index=0;index<10;++index){
 if(!realEntries[index]){std::cout<<label<<" variant="<<names[index]<<" unavailable-interface\n";continue;}
 if((index==0||index==2||index==7)&&options.TiledResourcesTier==D3D12_TILED_RESOURCES_TIER_NOT_SUPPORTED){
 std::cout<<label<<" variant="<<names[index]<<" unavailable-tiled-resource-feature\n";continue;}
 FrameSurvey::clean();realCalls.fill(0);void* pointer=nullptr;HRESULT result=E_UNEXPECTED;
 switch(index){__REAL_INVOKE__}
 ComPtr<ID3D12Resource> created;created.Attach(static_cast<ID3D12Resource*>(pointer));
 if(FAILED(result)){ComPtr<ID3D12InfoQueue> queue;if(SUCCEEDED(device.As(&queue)))for(UINT64 m=0;m<queue->GetNumStoredMessages();++m){
 SIZE_T length=0;queue->GetMessage(m,nullptr,&length);std::vector<uint8_t> bytes(length);auto* msg=reinterpret_cast<D3D12_MESSAGE*>(bytes.data());
 if(SUCCEEDED(queue->GetMessage(m,msg,&length)))std::cerr<<label<<" debug "<<msg->pDescription<<"\n";}
 std::cerr<<label<<" variant="<<names[index]<<" HRESULT=0x"<<std::hex<<unsigned(result)<<std::dec<<"\n";}
 checkHR(result,"Native selected creation variant");need(created&&realCalls[index]==1,"Real selected API forwards exactly one native resource creation");
 const bool enhanced=index>=5&&index<=7;const bool placed=index==4||index==6||index==9;
 need(FrameSurvey::stateCalls==unsigned(!enhanced)&&FrameSurvey::layoutCalls==unsigned(enhanced),"Real creation uses one correct state/layout callback");
 const auto& registered=FrameSurvey::gResources.at(created.Get());need(registered.initialKnown==!enhanced&&registered.va==created->GetGPUVirtualAddress(),"Real buffer enters address index without guessed layout state");
 need(registered.heap==(placed?reinterpret_cast<uintptr_t>(placedHeap.Get()):0)&&registered.offset==0,"Real placed heap is tracked exactly");
 FrameSurvey::HeapCreated(device.Get(),cbvHeap.Get());D3D12_CONSTANT_BUFFER_VIEW_DESC cbv{registered.va+256,1280};
 device->CreateConstantBufferView(&cbv,cbvHeap->GetCPUDescriptorHandleForHeapStart());
 FrameSurvey::View(cbvHeap->GetCPUDescriptorHandleForHeapStart(),&cbv);
 auto* root=reinterpret_cast<ID3D12RootSignature*>(0x456700);auto* list=reinterpret_cast<ID3D12GraphicsCommandList*>(0x567800);
 auto& mirror=FrameSurvey::gMirror[list];mirror.compute.object=root;mirror.compute.tables[3]=cbvHeap->GetGPUDescriptorHandleForHeapStart().ptr;mirror.heaps={cbvHeap.Get()};
 auto& rootLayout=FrameSurvey::gRootLayouts[root];rootLayout.complete=true;rootLayout.computeVisibleTables.insert(3);
 rootLayout.tables[3]={{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,0,1,6,0}};
 FrameSurvey::BoundConstantBuffer resolved;FrameSurvey::ConstantBufferDiagnostic diagnostic;
 need(FrameSurvey::ResolveComputeConstantBuffer(list,6,0,1216,resolved,&diagnostic)&&resolved.resource==created.Get()&&resolved.offset==256&&
 resolved.size==1280&&resolved.descriptorHeap==cbvHeap.Get(),"Real API-created buffer resolves exact 1280-byte native table CBV at offset 256 for Consumer b6");
 need(!FrameSurvey::ResolveComputeConstantBuffer(list,6,0,1281,resolved,&diagnostic),"Native 1280-byte descriptor cannot prove a larger constant span");
 std::cout<<label<<" variant="<<names[index]<<" native=1 metadata=1 cbv=1280 offset=256\n";
 FrameSurvey::clean();created.Reset();
 }
 if(v4){FrameSurvey::clean();realCalls.fill(0);void* invalid=nullptr;
 const auto result=hkSurveyCreateCommittedResource1(v4.Get(),&properties,D3D12_HEAP_FLAG_ALLOW_ONLY_BUFFERS,&nativeDesc,
 D3D12_RESOURCE_STATE_COMMON,nullptr,nullptr,__uuidof(ID3D12Resource),&invalid);
 if(invalid)static_cast<ID3D12Resource*>(invalid)->Release();
 need(result==E_INVALIDARG&&realCalls[1]==1&&!FrameSurvey::stateCalls&&!FrameSurvey::layoutCalls&&FrameSurvey::gResources.empty(),
 "Real invalid committed heap flags preserve HRESULT/native-once and emit no metadata");}
 if(v10){FrameSurvey::clean();realCalls.fill(0);void* invalid=nullptr;
 const auto result=hkSurveyCreateCommittedResource3(v10.Get(),&properties,D3D12_HEAP_FLAG_NONE,&nativeDesc1,
 D3D12_BARRIER_LAYOUT_COMMON,nullptr,nullptr,0,nullptr,__uuidof(ID3D12Resource),&invalid);
 if(invalid)static_cast<ID3D12Resource*>(invalid)->Release();
 need(result==E_INVALIDARG&&realCalls[5]==1&&!FrameSurvey::stateCalls&&!FrameSurvey::layoutCalls&&FrameSurvey::gResources.empty(),
 "Real invalid buffer layout preserves HRESULT/native-once and emits no guessed-state metadata");}
 __RESTORE_REAL_ENTRIES__
 D3D12Hooks::Unhook();needAllClear();need(commitCalls==2,"Real entry teardown stages all selected modern removals");
}
void realDevices(){ComPtr<ID3D12Debug> debug;if(SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug))))debug->EnableDebugLayer();
 ComPtr<IDXGIFactory6> factory;checkHR(CreateDXGIFactory2(0,IID_PPV_ARGS(&factory)),"DXGI factory");
 ComPtr<IDXGIAdapter1> hardware;for(UINT i=0;;++i){ComPtr<IDXGIAdapter1> candidate;
 if(factory->EnumAdapterByGpuPreference(i,DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,IID_PPV_ARGS(&candidate))==DXGI_ERROR_NOT_FOUND)break;
 DXGI_ADAPTER_DESC1 d{};candidate->GetDesc1(&d);if(!(d.Flags&DXGI_ADAPTER_FLAG_SOFTWARE)&&d.VendorId==0x1002){hardware=candidate;break;}}
 need(bool(hardware),"AMD hardware adapter is available for required native coverage");DXGI_ADAPTER_DESC1 hardwareDescription{};hardware->GetDesc1(&hardwareDescription);
 std::wcout<<L"Hardware adapter: "<<hardwareDescription.Description<<L"\n";deviceRun(hardware.Get(),"RX9070");
 ComPtr<IDXGIAdapter> warp;checkHR(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)),"WARP adapter");deviceRun(warp.Get(),"WARP");
}
'''


def run():
    hooks = (ROOT/'OptiScaler/hooks/D3D12_Hooks.cpp').read_text()
    survey = (ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').read_text()
    wrappers = '\n'.join(function(hooks, 'static HRESULT '+name+'(') for name in (
        'hkCreateCommittedResource', 'hkCreatePlacedResource',
        *(f'hkSurvey{method}' for method, *_ in METHODS)))
    scope = hooks[hooks.index('static thread_local unsigned gSurveyResourceCreationDepth'):hooks.index('VALIDATE_HOOK(hkSurveyCreateCommittedResource,')]
    types = re.findall(r'^using PFN_(?:Create\w+|CheckFeatureSupport|SetResidencyPriority|Release) =[^;]+;', hooks, re.M)
    types = [value for value in types if 'ID3D12DeviceFactory' not in value]
    allocation = hooks[hooks.index('typedef void(STDMETHODCALLTYPE* PFN_GetResourceAllocationInfo)'):hooks.index('typedef decltype(&D3D12GetInterface)')]
    original_names = {method for method, *_ in METHODS}|{'CreateSampler','CheckFeatureSupport','SetResidencyPriority','CreateRootSignature','GetResourceAllocationInfo'}
    globals_ = '\n'.join(line for line in hooks.splitlines() if any(line.startswith('static PFN_'+name+' o_') for name in original_names))
    globals_ += '\nstatic PFN_Release o_D3D12DeviceRelease=nullptr;\nstatic bool gSurveyDeviceWrappers=false,gNrdBridgeDeviceWrappers=false;\n'
    helpers = '\n'.join(function(hooks, signature) for signature in (
        'static void ResetSurveyResourceCreationHooks(', 'static bool SelectSurveyResourceCreationHooks(',
        'template <typename PFN> static LONG ChangeSurveyResourceCreationHook(', 'static LONG ChangeSurveyResourceCreationHooks('))
    natives, expected, calls, populate = [], [], [], []
    for index, (method, slot, surface, enhanced, placed) in enumerate(METHODS):
        wrapper = function(hooks, 'static HRESULT hkSurvey'+method+'(')
        signature = wrapper[:wrapper.index('{')].replace('hkSurvey'+method, 'Native'+method)
        arguments = re.findall(r'([A-Za-z_]\w*)\s*(?:,|\))', signature[signature.index('(')+1:])
        values = ','.join('reinterpret_cast<uintptr_t>(&'+a+')' if a in ('riid', 'riidResource') else 'arg('+a+')' for a in arguments)
        nested = ''
        if method == 'CreateCommittedResource3':
            nested = '''if(forwardModern){expected[3].back()=arg(ppvResource);auto* owner=reinterpret_cast<Interface*>(device)->owner;
              hkSurveyCreateCommittedResource2(reinterpret_cast<ID3D12Device8*>(&owner->v8),pHeapProperties,HeapFlags,pDesc,
              D3D12_RESOURCE_STATE_VERTEX_AND_CONSTANT_BUFFER,pOptimizedClearValue,pProtectedSession,riidResource,ppvResource);}'''
        elif method == 'CreateCommittedResource2':
            nested = '''if(forwardBase){expected[8].back()=arg(ppvResource);auto* owner=reinterpret_cast<Interface*>(device)->owner;D3D12_RESOURCE_DESC legacy{};
              expected[8][3]=arg(&legacy);hkSurveyCreateCommittedResource(reinterpret_cast<ID3D12Device*>(&owner->base),pHeapProperties,
              HeapFlags,&legacy,InitialResourceState,pOptimizedClearValue,riidResource,ppvResource);}'''
        natives.append(signature+'{\n'+nested+f'\nreturn finish({index},ppvResource,{{{values}}});\n}}')
        device_type = re.search(r'\((ID3D12Device\d*)\*', signature).group(1)
        mapping = {'device':f'reinterpret_cast<{device_type}*>(&d.{surface})', 'pHeapProperties':'&hp',
                   'HeapFlags':'D3D12_HEAP_FLAG_ALLOW_ALL_BUFFERS_AND_TEXTURES', 'pDesc':'&desc1' if 'D3D12_RESOURCE_DESC1*' in signature else '&desc',
                   'InitialState':'state','InitialResourceState':'state','InitialLayout':'layout','pOptimizedClearValue':'&clear',
                   'pProtectedSession':'session','NumCastableFormats':'UINT32(2)','pCastableFormats':'formats',
                   'riidResource':'riid','riid':'riid','ppvResource':'out','pHeap':'heap','HeapOffset':'heapOffset'}
        args = ','.join(mapping[name] for name in arguments)
        calls.append(f'case {index}:expected[{index}].back()=arg(out);return {mapping["device"]}->{method}({args.split(",",1)[1]});')
        expected_values = ','.join('reinterpret_cast<uintptr_t>(&riid)' if name in ('riid','riidResource') else
            ('0' if name == 'ppvResource' else 'arg('+mapping[name]+')') for name in arguments)
        expected.append(f'expected[{index}]={{{expected_values}}};')
        populate.append(f'table[{slot}]=reinterpret_cast<PVOID>(Native{method});')
    # Native functions follow the hook declarations, but the fake vtable constructor
    # and test invocation still use the SDK's actual virtual call ABI and offsets.
    registry = survey[survey.index('struct Resource\n'):survey.index('struct RootState\n')]
    mirror = survey[survey.index('struct Mirror\n'):survey.index('struct MirrorReferences\n')]
    metadata = '\n'.join(function(survey, signature) for signature in (
        'bool BindingTracking() noexcept', 'bool Tracking() noexcept', 'bool MetadataHealthy() noexcept',
        'void MetadataHookFailed(', 'bool Internal() noexcept', 'ScopedInternal::ScopedInternal()',
        'ScopedInternal::~ScopedInternal()', 'void BeginCreationTracking(', 'Resource& Register(',
        'bool ValidComputeRange(', 'bool UniqueComputeMapping(', 'bool ResolveBufferAddress(',
        'bool ResolveComputeConstantBuffer(', 'void HeapCreated(',
        'void View(D3D12_CPU_DESCRIPTOR_HANDLE handle, const D3D12_CONSTANT_BUFFER_VIEW_DESC* desc)'))
    callbacks = '\n'.join(function(survey, 'void '+name+'(').replace('void '+name+'(', 'void Actual'+name+'(')
        for name in ('ResourceCreated', 'ResourceCreatedWithLayout'))
    replacements = dict(ROOT=ROOT.as_posix(), REGISTRY=registry, MIRROR=mirror, META_FUNCTIONS=metadata,
        CREATION_CALLBACKS=callbacks, TYPES='\n'.join(types)+allocation, GLOBALS=globals_, RESOURCE_WRAPPERS=scope+wrappers,
        INSTALL_HELPERS=helpers, HOOK_DEVICE=function(hooks,'static void HookToDevice(ID3D12Device* InDevice)\n'),
        UNHOOK_DEVICE=function(hooks,'static void UnhookDevice()\n'), UNHOOK_ALL=function(hooks,'void D3D12Hooks::Unhook()'),
        ABI_ASSERTS='\n'.join(f'static_assert(std::is_same_v<decltype(&hkSurvey{method}),PFN_{method}>);' for method,*_ in METHODS),
        NATIVE_METHODS='\n'.join(natives), POPULATE_TABLE='\n'.join(populate), EXPECTED='\n'.join(expected), INVOKE='\n'.join(calls))
    replacements['CHECK_NATIVE_TABLE'] = '\n'.join(f'need(d.{"table" if surface=="base" else "table"+surface[1:]}[{slot}]==reinterpret_cast<PVOID>(Native{method}),"Every modern/reserved native slot is restored after teardown");'
        for method,slot,surface,*_ in METHODS[:8])
    real_spies, real_save, real_restore, real_calls = [], [], [], []
    for index, (method, slot, surface, enhanced, placed) in enumerate(METHODS):
        wrapper = function(hooks, 'static HRESULT hkSurvey'+method+'(')
        signature = wrapper[:wrapper.index('{')].replace('hkSurvey'+method, 'RealNative'+method)
        arguments = re.findall(r'([A-Za-z_]\w*)\s*(?:,|\))', signature[signature.index('(')+1:])
        real_spies.append(signature+'{++realCalls['+str(index)+'];return reinterpret_cast<PFN_'+method+'>(realEntries['+str(index)+'])('+','.join(arguments)+');}')
        real_save.append(f'realEntries[{index}]=reinterpret_cast<PVOID>(o_{method});if(o_{method})o_{method}=RealNative{method};')
        real_restore.append(f'o_{method}=reinterpret_cast<PFN_{method}>(realEntries[{index}]);')
        mapping = {'device':('device' if surface=='base' else surface)+'.Get()', 'pHeapProperties':'&properties',
            'HeapFlags':'D3D12_HEAP_FLAG_NONE','pDesc':'&nativeDesc1' if 'D3D12_RESOURCE_DESC1*' in signature else '&nativeDesc',
            'InitialState':'D3D12_RESOURCE_STATE_COMMON','InitialResourceState':'D3D12_RESOURCE_STATE_COMMON','InitialLayout':'D3D12_BARRIER_LAYOUT_UNDEFINED',
            'pOptimizedClearValue':'nullptr','pProtectedSession':'nullptr','NumCastableFormats':'0','pCastableFormats':'nullptr',
            'riidResource':'__uuidof(ID3D12Resource)','riid':'__uuidof(ID3D12Resource)','ppvResource':'&pointer','pHeap':'placedHeap.Get()','HeapOffset':'0'}
        real_calls.append(f'case {index}:result=hkSurvey{method}('+','.join(mapping[name] for name in arguments)+');break;')
    real = REAL.replace('__REAL_SPIES__','\n'.join(real_spies)).replace('__SAVE_REAL_ENTRIES__','\n'.join(real_save))
    real = real.replace('__RESTORE_REAL_ENTRIES__','\n'.join(real_restore)).replace('__REAL_INVOKE__','\n'.join(real_calls))
    replacements['REAL_DEVICES'] = real.replace('__METHOD_NAMES__',','.join(json.dumps(item[0]) for item in METHODS))
    cpp = CPP
    for name,value in replacements.items():
        cpp = cpp.replace('__'+name+'__', value)
    assert not re.search(r'__[A-Z_]+__',cpp)
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    file, exe = out/'resource_creation.cpp', out/'resource_creation.exe'
    file.write_text(cpp)
    compile_cpp(file, exe,libraries=('d3d12.lib','dxgi.lib'))
    native_devices = os.environ.get('FSRD_RESOURCE_CREATION_NATIVE_DEVICES') == '1'
    result = subprocess.run([str(exe),*(['--native-devices'] if native_devices else [])],capture_output=True,text=True)
    (out/'native-output.json').write_text(json.dumps(dict(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr),indent=2)+'\n')
    if result.returncode:
        raise RuntimeError(result.stderr)
    checks = int(re.search(r'PASS: (\d+)',result.stdout).group(1))
    data = dict(native_checks=checks, methods=[item[0] for item in METHODS],native_devices=native_devices,
        coverage='actual resource wrappers/device selection/install/teardown and FrameSurvey creation/index/CBV resolver; SDK virtual calls over independent CPU COM adapters plus optional RX/WARP resource creation; detour transactions are spies; CBV native creation and metadata callback are explicit; root layout is synthetic; no dispatch or game creation subcase proof')
    (out/'result.json').write_text(json.dumps(data,indent=2)+'\n')
    print(result.stdout,end='')


if __name__ == '__main__':
    run()
