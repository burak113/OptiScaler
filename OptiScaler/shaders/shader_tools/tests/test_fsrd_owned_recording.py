"""CPU execution of complete production NGX owned helpers and actual survey hooks.

Provider/device calls are adapters that invoke production PSO/Dispatch/CBV/root
wrappers. Real ScopedInternal, root tracking controls, mirror and CBV metadata
functions verify that ordinary owned work forwards without recording metadata.
No real GPU, device installer, AMD dispatch timing or in-game performance claim.
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
from test_fsrd_frame_survey_wiring import function as member


CPP = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <compare>
#include <functional>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <set>
#include <span>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include "__ROOT__/OptiScaler/misc/NrdBridgePerf_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgeLifetime_Dx12.h"
__INDEX_HEADER__
#include <vector>
#define LOG_DEBUG(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
#define LOG_WARN(...) ((void)0)
#define LOG_INFO(...) ((void)0)
#define NVSDK_NGX_API
unsigned checks=0;
void need(bool ok,const char* message){if(!ok)throw std::runtime_error(message);++checks;}
unsigned nativePso=0,nativeDispatch=0,nativeCbv=0,nativeRoot=0,nativeHeaps=0,rootWrites=0;
unsigned titleInputs=0,passes=0,bridgeCallbacks=0,scopeWork=0;
std::vector<std::string> order;
namespace NrdBridge { inline bool StartupEnabled(){return true;} }
namespace StreamlineHooks { struct PerfConstants { uint32_t frameIndex=1; }; inline auto getSLConstantsSnapshot(){return PerfConstants{};} }
namespace FrameSurvey {
thread_local bool gInternal=false;
thread_local unsigned gRecordingDepth=0;
__INTERNAL_DECL__
__INTERNAL_IMPL__
bool gTracking=true,gSurveyBindings=true,gBindingWindow=false;
bool Tracking(){return gTracking;} bool BindingTracking(){return gSurveyBindings||gBindingWindow;}
bool Recording(){return false;}
struct MetadataMutation {};
void MetadataFailed(const char* message){throw std::runtime_error(message);}
void Fail(const char* message){throw std::runtime_error(message);}
struct RootLayout {};
struct RecordRoot{uint64_t identity=0;RootLayout layout;std::map<uint32_t,uint64_t> tables;std::map<uint32_t,std::pair<uint32_t,uint64_t>> views;};
struct List{int pso=0;RecordRoot compute,graphics;std::vector<ID3D12DescriptorHeap*> heaps;};
struct Service{std::unordered_map<ID3D12GraphicsCommandList*,List> lists;};
std::unique_ptr<Service> gService=std::make_unique<Service>();
std::mutex gRecordMutex;
List& GetList(ID3D12GraphicsCommandList* list){return gService->lists[list];}
RootLayout ReadRoot(ID3D12RootSignature*){return {};}
int ReadPipeline(ID3D12PipelineState*){return 0;}
__MIRROR__
struct BoundConstantBuffer {ID3D12Resource* resource=nullptr;uint64_t address=0,offset=0,size=0,resourceGeneration=0;};
struct Resource{uint64_t id=0,va=0;ID3D12Resource* object=nullptr;D3D12_RESOURCE_DESC desc{};std::set<uint64_t> handles;};
struct ViewInfo{ID3D12Resource* object=nullptr;uint64_t resource=0;uint32_t kind=0,format=0,subresource=0;bool snapshotSupported=false;uint64_t descriptorCpu=0,rootVa=0,constantBytes=0,descriptorHeap=0;bool heapKnown=false;};
struct Heap{ID3D12DescriptorHeap* object=nullptr;std::set<uint64_t> views;};
std::unordered_map<ID3D12Resource*,Resource> gResources;
std::unordered_map<uint64_t,ViewInfo> gViews;
std::unordered_map<ID3D12DescriptorHeap*,Heap> gHeaps;
__INDEX_DECL__
std::mutex gLifetimeMutex;
Heap* HeapAtCpu(uint64_t){auto* key=reinterpret_cast<ID3D12DescriptorHeap*>(5);auto& heap=gHeaps[key];heap.object=key;return &heap;}
__VIEW_INDICES__
__BUFFER_RESOLVE__
__MIRROR_CALLBACKS__
__CBV_VIEW__
void Pass(ID3D12GraphicsCommandList*,const char*,std::array<uint64_t,3>){if(!Internal())++passes;}
void SnapshotWrites(ID3D12GraphicsCommandList*){if(!Internal())++passes;}
}
namespace NrdBridge {
void OnSetPipeline(ID3D12GraphicsCommandList*,ID3D12PipelineState*){++bridgeCallbacks;}
void BeforeDispatch(ID3D12GraphicsCommandList*){++bridgeCallbacks;}
void AfterDispatch(ID3D12GraphicsCommandList*){++bridgeCallbacks;}
}
#include "__ROOT__/OptiScaler/misc/NrdBridgeTitleCallbacks_Dx12.h"
namespace Wiring {
bool gNrdBridgeWrappers=true;
void originalPso(ID3D12GraphicsCommandList*,ID3D12PipelineState*){++nativePso;}
void originalDispatch(ID3D12GraphicsCommandList*,UINT,UINT,UINT){++nativeDispatch;}
void originalCbv(ID3D12Device*,const D3D12_CONSTANT_BUFFER_VIEW_DESC*,D3D12_CPU_DESCRIPTOR_HANDLE){++nativeCbv;}
auto o_SetPipelineState=&originalPso;auto o_Dispatch=&originalDispatch;auto o_CreateConstantBufferView=&originalCbv;
void hkSetPipelineState(ID3D12GraphicsCommandList* list,ID3D12PipelineState* pso){originalPso(list,pso);}
void hkDispatch(ID3D12GraphicsCommandList* list,UINT x,UINT y,UINT z){originalDispatch(list,x,y,z);}
__SURVEY_WRAPPERS__
}
bool isUpscalerActive=false,gNrdBridgeDeviceWrappers=true;
thread_local bool isNrdBridgeInjection=false;
struct D3D12Hooks {
static void SetRootSignatureTracking(bool);static bool RootSignatureTrackingEnabled();
static inline bool canRestore=true;
static void HookToCommandListLate(ID3D12GraphicsCommandList*){}
static bool CanRestoreRootSignature(ID3D12GraphicsCommandList*){return canRestore;}
static void RestoreRoot(ID3D12GraphicsCommandList*){need(FrameSurvey::Internal(),"restoration stays inside owned scope");}
};
__ROOT_CONTROLS__
void hkSetComputeRootConstantBufferView(ID3D12GraphicsCommandList*,UINT,D3D12_GPU_VIRTUAL_ADDRESS){++nativeRoot;if(D3D12Hooks::RootSignatureTrackingEnabled())++rootWrites;}
void hkSetDescriptorHeaps(ID3D12GraphicsCommandList*,UINT,ID3D12DescriptorHeap* const*){++nativeHeaps;if(D3D12Hooks::RootSignatureTrackingEnabled())++rootWrites;}
__ROOT_WRAPPERS__
__OWNED_SCOPE__
enum NVSDK_NGX_Result{NVSDK_NGX_Result_Success=0,NVSDK_NGX_Result_Fail=1,NVSDK_NGX_Result_FAIL_FeatureNotFound=2,NVSDK_NGX_Result_FAIL_FeatureNotSupported=3};
enum NVSDK_NGX_Feature{NVSDK_NGX_Feature_SuperSampling=1,NVSDK_NGX_Feature_RayReconstruction=2,NVSDK_NGX_Feature_FrameGeneration=3};
struct NVSDK_NGX_Handle{uint32_t Id;};
using PFN_NVSDK_NGX_ProgressCallback=void(*)();
struct NVSDK_NGX_Parameter{template<class T>NVSDK_NGX_Result Get(const char*,T*){return NVSDK_NGX_Result_Fail;}template<class T>void Set(const char*,T){}};
namespace FrameSurvey {void Evaluate(ID3D12GraphicsCommandList*,unsigned,const NVSDK_NGX_Parameter*){need(!Internal(),"export observes external title inputs before owned helper");++titleInputs;order.push_back("title");}}
enum class Upscaler{FFX,FFX_on12,FSR21,FSR_RR,DLSSD};
enum class FGInput{None,Upscaler};enum class FGNvngxReplacement{None,Other};enum class ApiUpscalerInput{DLSS_DX12};constexpr int DX12=12;
template<class T>struct Setting{T data{};T value_or_default()const{return data;}};
struct Config {
Setting<bool> RestoreComputeSignature{true},RestoreGraphicSignature{false},OutputScalingEnabled{false},DLSSEnabled{true},FfxDenoiserFrameSurvey{true};
Setting<Upscaler> Dx12Upscaler{Upscaler::FFX};std::optional<unsigned> SkipFirstFrames;
static Config* Instance(){static Config cfg;return &cfg;}
};
struct feature_version{int major,minor,patch;auto operator<=>(const feature_version&)const=default;};
struct FSRDRuntimeSnapshot{bool gameNativeRequested=false;};
ID3D12GraphicsCommandList* testList=reinterpret_cast<ID3D12GraphicsCommandList*>(1);
ID3D12Device* D3D12Device=reinterpret_cast<ID3D12Device*>(2);
bool initSuccess=true,evalSuccess=true,throwInit=false,throwEvaluate=false,throwFallback=false,missingFeature=false,ensureDevice=true,changeSuccess=true,changeThrows=false;
unsigned nested=0;std::function<void()> nestedCall;
void nativeWork(const char* label){
 if(std::string(label)!="external") need(!FrameSurvey::OwnedRelease(),"ordinary owned recording preserves native Release lifetime protection");
 ++scopeWork;order.push_back(label);
 D3D12_CONSTANT_BUFFER_VIEW_DESC desc{0x10000,256};
 Wiring::hkSurveyCreateConstantBufferView(D3D12Device,&desc,{0x20000});
 Wiring::hkSurveySetPipelineState(testList,reinterpret_cast<ID3D12PipelineState*>(3));
 hkSurveySetComputeRootConstantBufferView(testList,0,0x10000);
 ID3D12DescriptorHeap* heap=reinterpret_cast<ID3D12DescriptorHeap*>(5);hkSurveySetDescriptorHeaps(testList,1,&heap);
 Wiring::hkSurveyDispatch(testList,1,1,1);
}
struct IFeature_Dx12 {
~IFeature_Dx12(){need(FrameSurvey::Internal(),"owned failed-context destruction stays internal");order.push_back("destroy");}
bool Init(ID3D12Device*,ID3D12GraphicsCommandList*,NVSDK_NGX_Parameter*){nativeWork("init");if(throwInit)throw std::runtime_error("init exception");return initSuccess;}
Upscaler GetUpscalerType(){return Upscaler::FFX;}bool UsesRecordedComputeLifetime(){return true;}feature_version Version(){return{3,1,0};}
bool UpdateOutputResolution(NVSDK_NGX_Parameter*){return false;}bool IsInited(){return initSuccess;}const char* Name(){return "fixture";}
void OnEvaluationStarting(NVSDK_NGX_Parameter*){nativeWork("start");}
bool Evaluate(ID3D12GraphicsCommandList*,NVSDK_NGX_Parameter*){nativeWork("evaluate");if(nestedCall){auto callback=std::move(nestedCall);callback();}if(throwEvaluate)throw std::runtime_error("eval exception");return evalSuccess;}
bool EvaluateFallback(ID3D12GraphicsCommandList*,NVSDK_NGX_Parameter*){nativeWork("fallback");if(throwFallback)throw std::runtime_error("fallback exception");return true;}
void OnEvaluationFinished(bool){nativeWork("finish");}bool ReadRayRegenerationDiagnostics(FSRDRuntimeSnapshot&){return false;}
};
template<class T>struct ContextData{std::unique_ptr<T> feature;NVSDK_NGX_Feature featureID=NVSDK_NGX_Feature_SuperSampling;Upscaler featureKey=Upscaler::FFX;unsigned changeBackendCounter=0;bool evaluationFailed=false;};
std::unordered_map<uint32_t,ContextData<IFeature_Dx12>> Dx12Contexts;
std::unordered_map<uint32_t,NVSDK_NGX_Feature> HandleToFeature;
struct State {
int api=0;ApiUpscalerInput currentInputApiName=ApiUpscalerInput::DLSS_DX12;std::optional<ApiUpscalerInput> setInputApiName;std::optional<bool> autoExposure;
Upscaler newBackend=Upscaler::FFX;FGInput activeFgInput=FGInput::None;FGNvngxReplacement activeFgNvngx=FGNvngxReplacement::None;
std::unordered_map<uint32_t,bool> changeBackend;IFeature_Dx12* currentFeature=nullptr;bool fgChanged=false;int dlssgDetectedInterpolationCount=0;
static State& Instance(){static State state;return state;}
};
constexpr uint32_t DLSS_MOD_ID_OFFSET=1000000,NVNGX_PROVIDER_ID_OFFSET=2000000;unsigned evalCounter=0;
struct IFeature{static uint32_t GetNextHandleId(){static uint32_t id=DLSS_MOD_ID_OFFSET;return id++;}};
Upscaler GetUpscalerBackend(){return Upscaler::FFX;}const char* UpscalerDisplayName(Upscaler){return "fixture";}
bool EnsureD3D12Device(ID3D12GraphicsCommandList*){return ensureDevice;}
struct FeatureProvider_Dx12 {
static bool GetFeature(Upscaler,uint32_t,NVSDK_NGX_Parameter*,std::unique_ptr<IFeature_Dx12>* out){nativeWork("get");if(missingFeature)return false;*out=std::make_unique<IFeature_Dx12>();return true;}
static bool ChangeFeature(Upscaler,ID3D12Device*,ID3D12GraphicsCommandList*,uint32_t,NVSDK_NGX_Parameter*,ContextData<IFeature_Dx12>*){nativeWork("change");if(changeThrows)throw std::runtime_error("change exception");return changeSuccess;}
};
struct UpscalerInputsDx12{static void Reset(){nativeWork("reset");}static void UpscaleStart(ID3D12GraphicsCommandList*,NVSDK_NGX_Parameter*,IFeature_Dx12*){nativeWork("input");}static void UpscaleEnd(ID3D12GraphicsCommandList*,NVSDK_NGX_Parameter*,IFeature_Dx12*){nativeWork("input end");}};
struct FSR3FG{static void SetUpscalerInputs(ID3D12GraphicsCommandList*,NVSDK_NGX_Parameter*,IFeature_Dx12*){nativeWork("FG input");}};
struct ScopedSkipHeapCapture{};
enum class ImGuiToastType{Warning,Error};struct Notification{ImGuiToastType type;int ms;const char* text;};namespace ImGui{void InsertNotification(Notification){}}
NVSDK_NGX_Result passthrough(ID3D12GraphicsCommandList*,const NVSDK_NGX_Handle*,NVSDK_NGX_Parameter*,PFN_NVSDK_NGX_ProgressCallback){nativeWork("passthrough");return NVSDK_NGX_Result_Success;}
struct NVNGXProxy{static auto D3D12_EvaluateFeature(){return &passthrough;}};
struct Nvngx_FG{static NVSDK_NGX_Result D3D12_EvaluateFeature(ID3D12GraphicsCommandList* l,const NVSDK_NGX_Handle* h,NVSDK_NGX_Parameter* p,PFN_NVSDK_NGX_ProgressCallback c){return passthrough(l,h,p,c);}};
struct ReflexHooks{static void setDlssgFrameCount(int){}};
__CREATE_HELPER__
__EVALUATE_HELPER__
__EVALUATE_EXPORT__
void resetEvidence(){nativePso=nativeDispatch=nativeCbv=nativeRoot=nativeHeaps=rootWrites=passes=bridgeCallbacks=scopeWork=0;FrameSurvey::gMirror.clear();__MIRROR_INDEX_CLEAR__for(auto& [key,resource]:FrameSurvey::gResources)resource.handles.clear();for(auto& [key,heap]:FrameSurvey::gHeaps)heap.views.clear();FrameSurvey::gViews.clear();order.clear();}
void checkOwned(const char* message){
 need(scopeWork>0,message);need(nativePso==scopeWork&&nativeDispatch==scopeWork&&nativeCbv==scopeWork&&nativeRoot==scopeWork&&nativeHeaps==scopeWork,"each actual owned wrapper forwards exactly once");
 need(FrameSurvey::gMirror.empty()&&FrameSurvey::gViews.empty()&&passes==0&&bridgeCallbacks==0&&rootWrites==0,"owned recording leaves metadata/bridge/root snapshots untouched");
}
void checkUnwound(){need(!FrameSurvey::Internal()&&D3D12Hooks::RootSignatureTrackingEnabled(),"both production TLS guards restore external recording");}
int main()try{
 FrameSurvey::Resource resource;resource.id=1;resource.va=0x10000;resource.object=reinterpret_cast<ID3D12Resource*>(6);resource.desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;resource.desc.Width=4096;
 FrameSurvey::gResources[resource.object]=resource;__INDEX_SETUP__NVSDK_NGX_Parameter params;NVSDK_NGX_Handle* handle=nullptr;
 need(TryCreateOptiFeature(testList,NVSDK_NGX_Feature_RayReconstruction,&params,&handle)==NVSDK_NGX_Result_Success,"complete actual RR creation helper succeeds");checkOwned("owned creation issued native adapter work");checkUnwound();HandleToFeature[handle->Id]=NVSDK_NGX_Feature_RayReconstruction;
 resetEvidence();const auto inputs=titleInputs;
 need(NVSDK_NGX_D3D12_EvaluateFeature(testList,handle,&params,nullptr)==NVSDK_NGX_Result_Success,"complete actual exported Evaluate reaches owned RR helper");
 need(titleInputs==inputs+1&&!order.empty()&&order.front()=="title","title input capture occurs before all owned recording");checkOwned("ordinary evaluation issued native work");checkUnwound();
 resetEvidence();auto missing=NVSDK_NGX_Handle{handle->Id+900};need(TryEvaluateOptiFeature(testList,&missing,&params,nullptr)==NVSDK_NGX_Result_FAIL_FeatureNotFound,"missing context early return");checkUnwound();need(scopeWork==0,"missing context records no GPU work");
 Config::Instance()->SkipFirstFrames=100000;resetEvidence();need(TryEvaluateOptiFeature(testList,handle,&params,nullptr)==NVSDK_NGX_Result_Success,"configured first-frame early return");checkUnwound();need(scopeWork==0,"skipped evaluation records no GPU work");Config::Instance()->SkipFirstFrames.reset();
 D3D12Hooks::canRestore=false;need(TryEvaluateOptiFeature(testList,handle,&params,nullptr)==NVSDK_NGX_Result_Fail,"missing restore early return");checkUnwound();D3D12Hooks::canRestore=true;
 resetEvidence();throwEvaluate=true;need(TryEvaluateOptiFeature(testList,handle,&params,nullptr)==NVSDK_NGX_Result_Success,"caught evaluation exception reaches owned native fallback");checkOwned("fallback recorded native work");checkUnwound();throwEvaluate=false;
 resetEvidence();evalSuccess=false;throwFallback=true;bool threw=false;try{TryEvaluateOptiFeature(testList,handle,&params,nullptr);}catch(const std::exception&){threw=true;}need(threw,"fallback exception escapes complete helper");checkOwned("throwing fallback recorded native work");checkUnwound();evalSuccess=true;throwFallback=false;
 resetEvidence();State::Instance().changeBackend[handle->Id]=true;changeThrows=true;threw=false;try{TryEvaluateOptiFeature(testList,handle,&params,nullptr);}catch(const std::exception&){threw=true;}need(threw,"backend recreation exception escapes");checkOwned("throwing recreation records internal work");checkUnwound();changeThrows=false;State::Instance().changeBackend[handle->Id]=false;
 resetEvidence();{FrameSurvey::ScopedInternal outer;D3D12Hooks::SetRootSignatureTracking(false);need(TryEvaluateOptiFeature(testList,handle,&params,nullptr)==NVSDK_NGX_Result_Success,"nested complete helper succeeds");need(FrameSurvey::Internal()&&!D3D12Hooks::RootSignatureTrackingEnabled(),"nested helper preserves both enclosing TLS guards");checkOwned("nested helper issued work");}D3D12Hooks::SetRootSignatureTracking(true);checkUnwound();
 resetEvidence();{FrameSurvey::ScopedInternal mainOwned;D3D12Hooks::SetRootSignatureTracking(false);
 std::thread titleThread([]{need(!FrameSurvey::Internal()&&D3D12Hooks::RootSignatureTrackingEnabled(),"worker title TLS remains external while main thread records owned work");nativeWork("external");});titleThread.join();
 need(FrameSurvey::Internal()&&!D3D12Hooks::RootSignatureTrackingEnabled(),"external worker preserves enclosing owned TLS");}D3D12Hooks::SetRootSignatureTracking(true);checkUnwound();
 need(FrameSurvey::gMirror.size()==1&&FrameSurvey::gViews.size()==1&&bridgeCallbacks==3&&rootWrites==2,"external title callbacks still update real mirror/CBV metadata and bridge spies");need(nativeDispatch==1&&nativePso==1&&nativeCbv==1&&nativeRoot==1&&nativeHeaps==1,"external title wrapper forwards once");
 resetEvidence();NVSDK_NGX_Handle* upscaler=nullptr;
 need(TryCreateOptiFeature(testList,NVSDK_NGX_Feature_SuperSampling,&params,&upscaler)==NVSDK_NGX_Result_Success,"complete ordinary SuperSampling creation helper succeeds");checkOwned("ordinary upscaler creation records only owned work");checkUnwound();HandleToFeature[upscaler->Id]=NVSDK_NGX_Feature_SuperSampling;
 resetEvidence();need(NVSDK_NGX_D3D12_EvaluateFeature(testList,upscaler,&params,nullptr)==NVSDK_NGX_Result_Success,"complete ordinary upscaler export/helper succeeds");checkOwned("ordinary upscaler work remains excluded even with FrameSurvey true");checkUnwound();
 resetEvidence();NVSDK_NGX_Handle nativeHandle{42};HandleToFeature[nativeHandle.Id]=NVSDK_NGX_Feature_SuperSampling;
 need(NVSDK_NGX_D3D12_EvaluateFeature(testList,&nativeHandle,&params,nullptr)==NVSDK_NGX_Result_Success,"native DLSS passthrough still uses original export branch");
 need(scopeWork==1&&nativeDispatch==1&&FrameSurvey::gMirror.size()==1&&FrameSurvey::gViews.size()==1&&bridgeCallbacks==3,"native passthrough is outside OptiScaler-owned helper scope");checkUnwound();
 resetEvidence();gNrdBridgeDeviceWrappers=false;Wiring::gNrdBridgeWrappers=false;FrameSurvey::gTracking=false;FrameSurvey::gSurveyBindings=false;Config::Instance()->FfxDenoiserFrameSurvey.data=false;
 const auto offInputs=titleInputs;need(NVSDK_NGX_D3D12_EvaluateFeature(testList,upscaler,&params,nullptr)==NVSDK_NGX_Result_Success,"startup OFF ordinary upscaler remains operational");checkOwned("OFF forwards owned existing work without new survey metadata");checkUnwound();need(titleInputs==offInputs,"OFF records no title survey input callback");
 gNrdBridgeDeviceWrappers=true;Wiring::gNrdBridgeWrappers=true;FrameSurvey::gTracking=true;FrameSurvey::gSurveyBindings=true;Config::Instance()->FfxDenoiserFrameSurvey.data=true;
 for(int mode=0;mode<4;++mode){
  resetEvidence();NVSDK_NGX_Handle* created=nullptr;missingFeature=mode==0;ensureDevice=mode!=1;initSuccess=mode!=2;throwInit=mode==3;threw=false;
  NVSDK_NGX_Result result=NVSDK_NGX_Result_Success;try{result=TryCreateOptiFeature(testList,NVSDK_NGX_Feature_RayReconstruction,&params,&created);}catch(const std::exception&){threw=true;}
  need(mode==3?threw:result!=NVSDK_NGX_Result_Success,"actual creation failure/throw path rejects context");checkOwned("failed creation forwards only owned native work");checkUnwound();
  if(created){FrameSurvey::ScopedInternal cleanup;Dx12Contexts.erase(created->Id);delete created;}
 }
 missingFeature=false;ensureDevice=true;initSuccess=true;throwInit=false;
 {FrameSurvey::ScopedInternal cleanup;Dx12Contexts.clear();}delete handle;delete upscaler;
 std::cout<<"PASS: "<<checks<<" actual owned recording checks\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
'''


def run():
    base = ROOT/'OptiScaler'
    source = (base/'inputs/NVNGX_DLSS_Dx12.cpp').read_text()
    survey = (base/'resource_tracking/FrameSurvey_Dx12.cpp').read_text()
    header = (base/'resource_tracking/FrameSurvey_Dx12.h').read_text()
    track = (base/'resource_tracking/ResTrack_dx12.cpp').read_text()
    d3d = (base/'hooks/D3D12_Hooks.cpp').read_text()
    replacements = {
        'ROOT': ROOT.as_posix(),
        'INDEX_HEADER': '#include "'+(base/'resource_tracking/FrameSurveyBufferRanges.h').as_posix()+'"' if (base/'resource_tracking/FrameSurveyBufferRanges.h').exists() else '',
        'INDEX_DECL': 'FrameSurveyMetadata::BufferAddressIndex gBufferAddresses;' if 'gBufferAddresses' in survey else '',
        'INDEX_SETUP': 'FrameSurvey::gBufferAddresses.Insert(resource.va,resource.desc.Width,resource.id,resource.object);' if 'gBufferAddresses' in survey else '',
        'VIEW_INDICES': '\n'.join(function(survey, signature) for signature in ('void EraseView(', 'void IndexView(')) if 'void EraseView(' in survey else '',
        'MIRROR_INDEX_CLEAR': 'FrameSurvey::gMirrorOwners.clear();' if 'gMirrorOwners' in survey else '',
        'OWNED_SCOPE': function(source, 'class ScopedOptiFeatureRecording')+';',
        'CREATE_HELPER': function(source, 'static NVSDK_NGX_Result TryCreateOptiFeature('),
        'EVALUATE_HELPER': function(source, 'static NVSDK_NGX_Result TryEvaluateOptiFeature('),
        'EVALUATE_EXPORT': function(source, 'NVSDK_NGX_API NVSDK_NGX_Result NVSDK_NGX_D3D12_EvaluateFeature('),
        'INTERNAL_DECL': header[header.index('class ScopedInternal'):header.index('bool Enabled() noexcept;')],
        'INTERNAL_IMPL': '\n'.join(function(survey, signature) for signature in ('ScopedInternal::ScopedInternal()', 'ScopedInternal::~ScopedInternal()', 'ScopedRecording::ScopedRecording()', 'ScopedRecording::~ScopedRecording()', 'bool OwnedRelease() noexcept', 'bool Internal() noexcept')),
        'MIRROR': survey[survey.index('struct Mirror'):survey.index('bool Seed(ID3D12GraphicsCommandList*')],
        'MIRROR_CALLBACKS': '\n'.join(function(survey, signature) for signature in ('void SetPipeline(', 'void RootBinding(', 'void DescriptorHeaps(', 'void RootView(', 'void Table(')),
        'CBV_VIEW': function(survey, 'void View(D3D12_CPU_DESCRIPTOR_HANDLE handle, const D3D12_CONSTANT_BUFFER_VIEW_DESC* desc)'),
        'BUFFER_RESOLVE': function(header, 'struct ConstantBufferDiagnostic')+';\n'+function(survey, 'bool ResolveBufferAddress('),
        'SURVEY_WRAPPERS': '\n'.join(member(track, name) for name in ('hkSurveySetPipelineState', 'hkSurveyDispatch', 'hkSurveyCreateConstantBufferView')),
        'ROOT_CONTROLS': '\n'.join(function(d3d, signature) for signature in ('void D3D12Hooks::SetRootSignatureTracking(', 'bool D3D12Hooks::RootSignatureTrackingEnabled(')),
        'ROOT_WRAPPERS': '\n'.join(function(d3d, signature) for signature in ('static void hkSurveySetComputeRootConstantBufferView(', 'static void hkSurveySetDescriptorHeaps(')),
    }
    cpp = CPP.replace("__ROOT__", ROOT.as_posix())
    for key, value in replacements.items():
        cpp = cpp.replace('__'+key+'__', value)
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    file, exe = out/'owned_recording.cpp', out/'owned_recording.exe'
    file.write_text(cpp)
    compile_cpp(file, exe)
    result = subprocess.run([str(exe)], capture_output=True, text=True)
    (out/'native-output.json').write_text(json.dumps(dict(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr), indent=2)+'\n')
    if result.returncode:
        raise RuntimeError(result.stderr)
    checks = int(re.search(r'PASS: (\d+)', result.stdout).group(1))
    data = dict(native_checks=checks, scope='complete actual owned Create/Evaluate helpers and exported Evaluate, actual survey/root hook bodies, real metadata callbacks/ScopedInternal/root TLS; provider/device/native calls are CPU adapters; no GPU timing')
    (out/'result.json').write_text(json.dumps(data, indent=2)+'\n')
    print(result.stdout, end='')


if __name__ == '__main__':
    run()
