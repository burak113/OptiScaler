"""Execute production startup/reset/device-rebind seams in fresh processes.

Uses actual CustomOptional, complete ResetFfxDenoiserSettings, canonical device
helper/private-QI unwrap, coordinator lifecycle/runtime functions and the real
HookToDevice/ResTrack HookDevice prefixes before native detour installation.
Provider/history storage and device creation entry points are CPU adapters.
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


CPP = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <wrl/client.h>
#include <filesystem>
#include <atomic>
#include <mutex>
#include <memory>
#include <unordered_map>
#include <optional>
#include <concepts>
#include <string>
#include <vector>
#include <thread>
#include <iostream>
#include <stdexcept>
#include <cctype>
#define LOG_INFO(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
#define LOG_DEBUG(...) ((void)0)
#define LOG_WARN(...) ((void)0)
unsigned checks=0;
void need(bool value,const char* message) { if(!value) throw std::runtime_error(message); ++checks; }
std::filesystem::path executable;
GUID streamlineRiid {};
namespace Util { std::filesystem::path ExePath(){return executable;} __UNWRAP__ }
#include "__ROOT__/OptiScaler/misc/NrdBridgeDevice_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgePerf_Dx12.h"
#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Types.h"
#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.h"
#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.h"
#include <algorithm>
#include <format>
__OPTIONAL__
namespace FSRDSignals { constexpr int Auto=0; }
struct Config {
 __DECLARATIONS__
 static Config* Instance(){static Config config;return &config;}
 bool ResetFfxDenoiserSettings();
};
__RESET__
void FlushLogger() noexcept {}
bool gNrdBridgeWrappers=false,gSurveyWrappers=false;
void checkObserverPublication();
bool observerPublicationSerialized=true;
unsigned refreshCalls=0; ID3D12Device* refreshed=nullptr; bool refreshAvailable=true;
struct ResTrack_Dx12 {
 static void HookDevice(ID3D12Device*);
 static bool RefreshComputeHookDevice(ID3D12Device* device,const char** reason=nullptr) noexcept {
  need(gNrdBridgeWrappers && gSurveyWrappers,"refresh sees latched bridge/survey detour selection");
  if(reason) *reason="Selected title device has unsupported native compute hook entries; restart required";
  ++refreshCalls; refreshed=device; return refreshAvailable;
 }
};
namespace FrameSurvey {
 thread_local unsigned internalDepth=0;
 bool Internal(){return internalDepth!=0;}
 struct ScopedInternal { ScopedInternal(){++internalDepth;} ~ScopedInternal(){--internalDepth;} };
 unsigned observers=0,creationTracking=0; bool window=false;
 template<class F> void SetPipelineObserver(F) {++observers;checkObserverPublication();}
 template<class F> void SetGraphicsPipelineObserver(F) {++observers;checkObserverPublication();}
 template<class F> void SetReleaseObserver(F) {}
 template<class F> void SetBirthReleaseObserver(F) {}
 void SetBindingWindow(bool value) {window=value;}
 void BeginCreationTracking(bool) {++creationTracking;}
 void MetadataHookFailed(const char*) noexcept {}
}
unsigned serviceDestructions=0; bool destructionUnlocked=true,destructionInternal=true;
void checkDestruction();
namespace NrdBridge {
struct RecordingToken {
 std::atomic<bool> submitted{false},outputCommitted{false},abandoned{false},commitRequired{false},skipInvalidated{false},submissionRetained{false};
 std::atomic<const char*> invalidationGate{nullptr};
};
struct HistoryDomain { std::atomic<bool> uncertain{false},discardPending{false}; };
struct NativeTransaction {
 std::shared_ptr<HistoryDomain> history; std::shared_ptr<RecordingToken> recording;
 std::atomic<bool> committed{false},invalidated{false};
};
struct NativeDebugSource;
struct ListState {
 bool converted=false,motionReady=false,ownedReady=false;
 std::shared_ptr<RecordingToken> recording; std::shared_ptr<HistoryDomain> history;
 std::array<std::shared_ptr<NativeTransaction>,4> native;
};
struct Cache { bool valid=false; bool Valid()const{return valid;} };
struct Service {
 Microsoft::WRL::ComPtr<ID3D12Device> device; Status status; Cache cache;
 std::unordered_map<void*,unsigned> roles; std::unordered_map<void*,ListState> lists;
 void* pendingList=nullptr; uint64_t resetSerial=1,cancellationSerial=1;
 bool window=false,windowSawRecon=false; unsigned windowPresents=0,retryPresents=0,attempts=0,failures=0;
 bool discardRequested=false; std::array<std::shared_ptr<NativeDebugSource>,4> nativeDebugSources;
 unsigned nextNativeDebugSource=0; unsigned nativeDebugLastLag=UINT32_MAX;
 RRSettings rrSettings; RRSettingsState rrSettingsState; bool cameraProjectedDepthDelta=false;
 ~Service(){checkDestruction();}
};
std::atomic<bool> gNativeDebug{false},gNativeMaterials{false},gNativeTransactions{false};
std::atomic<const char*> gStartupFailure{nullptr};
enum class NativeRetirementStartup { LegacyAdapter, Ready, Failed };
unsigned applyRRSettingsCalls=0; RRSettings lastAppliedRRSettings; bool lastAppliedCameraDepth=false;
// The real ApplyRRSettings drives live histories; this lifecycle fixture records the
// reset-path apply call and accepts it, so ResetFfxDenoiserSettings' best-effort
// settings publication stays observable.
bool ApplyRRSettings(const RRSettings& settings,bool cameraProjectedDepthDelta,std::string& error) noexcept {
 ++applyRRSettingsCalls; lastAppliedRRSettings=settings; lastAppliedCameraDepth=cameraProjectedDepthDelta;
 error.clear(); return true;
}
using RetiredDebugSources = std::array<std::shared_ptr<NativeDebugSource>,4>;
std::mutex gMutex,gInjectionMutex,gWindowMutex;
std::shared_ptr<Service> gService;
std::atomic<bool> gInstalled{false},gRuntime{false};
std::atomic<int> gStartupSelection{-1};
std::string gUnavailableReason;
void OnPipelineCreated(ID3D12PipelineState*,const char*) noexcept {} void OnReleased(void*) noexcept {}
void OnGraphicsPipelineCreated(ID3D12PipelineState*,const char*) noexcept {}
void OnBirthReleased(const NrdBridgeBirth::Token&) noexcept {}
void CoordinatorException(const char*){}
void RefreshNativeTransactions(const Service&) noexcept {}
void ClearNativeDebugSources(Service& owner, RetiredDebugSources& retired) noexcept
{
 for (size_t i=0;i<owner.nativeDebugSources.size();++i)
  if (owner.nativeDebugSources[i]) retired[i] = std::move(owner.nativeDebugSources[i]);
 owner.nextNativeDebugSource = 0; owner.nativeDebugLastLag = UINT32_MAX;
}
__COORDINATOR__
unsigned tags=0,presents=0,work=0;
void OnTitleTag(ID3D12GraphicsCommandList*,const char*,ID3D12Resource*) noexcept {++tags;}
void OnPresent() noexcept {++presents;}
void dispatchGate(){ __DISPATCH_GUARD__ ++work; }
}
void checkObserverPublication() {
 bool state=false,serial=false;
 std::thread probe([&] {
  state=NrdBridge::gMutex.try_lock(); if(state) NrdBridge::gMutex.unlock();
  serial=NrdBridge::gInjectionMutex.try_lock(); if(serial) NrdBridge::gInjectionMutex.unlock();
 }); probe.join();observerPublicationSerialized &= state && !serial;
}
void checkDestruction() {
 ++serviceDestructions; destructionInternal &= FrameSurvey::Internal();
 bool state=false,serial=false;
 std::thread probe([&] {
  state=NrdBridge::gMutex.try_lock(); if(state) NrdBridge::gMutex.unlock();
  serial=NrdBridge::gInjectionMutex.try_lock(); if(serial) NrdBridge::gInjectionMutex.unlock();
 }); probe.join(); destructionUnlocked &= state && serial;
}
enum class FGInput {None,NvngxFG};
struct State {
 bool creatingD3DDevice=false; ID3D12Device* currentD3D12Device=nullptr; FGInput activeFgInput=FGInput::None;
 static State& Instance(){static State state;return state;}
};
using PVOID=void*;
void* o_CreateSampler=reinterpret_cast<void*>(1);
bool gNrdBridgeDeviceWrappers=false,gSurveyDeviceWrappers=false;
void* o_CreateDescriptorHeap=reinterpret_cast<void*>(2);
__RESTRACK_HOOK__
__DEVICE_HOOK__
unsigned originals=0;
HRESULT originalDevice(IUnknown*,D3D_FEATURE_LEVEL,REFIID,void**){++originals;return S_FALSE;}
HRESULT originalFactory(void*,IUnknown*,D3D_FEATURE_LEVEL,REFIID,void**){++originals;return S_FALSE;}
auto o_D3D12CreateDevice=&originalDevice;
auto o_CreateDevice=&originalFactory;
bool _creatingD3D12Device=false;
HRESULT internalCreate(IUnknown* pAdapter,D3D_FEATURE_LEVEL MinimumFeatureLevel,REFIID riid,void** ppDevice) {
 __CREATE_GUARD__
 return E_NOTIMPL;
}
HRESULT internalFactory(void* pFactory,IUnknown* pAdapter,D3D_FEATURE_LEVEL MinimumFeatureLevel,REFIID riid,void** ppDevice) {
 __FACTORY_GUARD__
 return E_NOTIMPL;
}
void captureDevice(HRESULT result,void** ppDevice,D3D_FEATURE_LEVEL MinimumFeatureLevel,bool nonPrimaryGpu) {
 __CAPTURE_PREFIX__
  HookToDevice(State::Instance().currentD3D12Device);
 }
}
void bootstrap(){ __BOOTSTRAP__ }
__SERIALIZER__
namespace sl { enum class RenderAPI{eD3D12}; constexpr unsigned kBufferTypeMotionVectors=1; }
struct Resource{void* native;}; struct Tag{unsigned type;Resource* resource;};
enum class RRTagSource{SetTag};
void probeSLResourceTag(Tag,unsigned,unsigned,RRTagSource){}
void tag(){
 const auto renderApi=sl::RenderAPI::eD3D12; const unsigned i=0,viewport=0;
 void* cmdBuffer=reinterpret_cast<void*>(3); Resource resource{reinterpret_cast<void*>(4)};
 Tag tags[]={{sl::kBufferTypeMotionVectors,&resource}};
 __TAG_BLOCK__
}
void present(UINT Flags){ __PRESENT__ }
namespace ImGui { bool CollapsingHeader(const char*){return true;} }
bool menuAvailable(){ __MENU_GUARD__ return true; return false; }
struct FakeDevice: IUnknown {
 ULONG refs=1; FakeDevice* native=nullptr; unsigned queries=0;
 ID3D12Device* device(){return reinterpret_cast<ID3D12Device*>(static_cast<IUnknown*>(this));}
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid,void** out) override {
  ++queries; *out=nullptr;
  if(riid==streamlineRiid && native) { *out=static_cast<IUnknown*>(native);native->AddRef();return S_OK; }
  if(riid==IID_IUnknown || riid==__uuidof(ID3D12Device)) {
   *out=static_cast<IUnknown*>(this);AddRef();return S_OK;
  } return E_NOINTERFACE;
 }
 ULONG STDMETHODCALLTYPE AddRef() override {return ++refs;}
 ULONG STDMETHODCALLTYPE Release() override {return --refs;}
};
int main(int argc,char** argv) try {
 need(argc==3,"executable and startup selection arguments");
 executable=std::filesystem::path("F:/fixture")/argv[1];
 auto* config=Config::Instance(); const bool enabled=std::string(argv[2])=="on";
 const bool supported=std::string(argv[1])=="cyberpunk2077.exe"||std::string(argv[1])=="CYBERPUNK2077.EXE";
 need(!NrdBridge::StartupEnabled(),"pre-bootstrap calls are inert and cannot select startup");
 config->FfxDenoiserNrdBridge=true;
 need(!NrdBridge::StartupEnabled(),"config reads before explicit bootstrap do not poison latch");
 config->FfxDenoiserNrdBridge=enabled; bootstrap();
 need(NrdBridge::SupportedExecutable()==supported,"actual executable filename gate");
 need(NrdBridge::StartupEnabled()==(enabled&&supported),"bootstrap latches configured executable selection");
 FakeDevice first,proxy,other,nextProxy,third; proxy.native=&first;nextProxy.native=&other;
 State::Instance().currentD3D12Device=proxy.device();
 if(!enabled || !supported) {
  need(!NrdBridge::Initialize(first.device()),"configured OFF/non-title process creates no coordinator");
  HookToDevice(proxy.device()); ResTrack_Dx12::HookDevice(proxy.device());tag();present(0);
  need(!NrdBridge::gService && !NrdBridge::gInstalled && refreshCalls==0,"OFF enters only already installed legacy hook path");
  need(NrdBridge::tags==0 && NrdBridge::presents==0 && !menuAvailable(),"OFF preserves inert SL/Present/menu routing");
  config->FfxDenoiserNrdBridge=true;NrdBridge::ConfigureStartup(true);
  need(!NrdBridge::StartupEnabled() && !NrdBridge::Initialize(first.device()),"live config cannot install hooks after OFF bootstrap");
  config->ResetFfxDenoiserSettings();
  need(!NrdBridge::RuntimeEnabled() && config->FfxDenoiserNrdBridgeEnabled.value_for_config()==false,"OFF ResetAll persists runtime OFF");
  need(serviceDestructions==0,"OFF allocated no service");
 } else {
  HookToDevice(proxy.device());
  need(refreshCalls==1 && refreshed==first.device(),"real root hook forwards normalized selected device before installed fast return");
  need(NrdBridge::gService && NrdBridge::gService->device.Get()==first.device(),"coordinator stores native device after Streamline private QI");
  auto* owner=NrdBridge::gService.get();owner->roles[reinterpret_cast<void*>(7)]=9;owner->cache.valid=true;
  need(NrdBridge::Initialize(proxy.device()) && NrdBridge::gService.get()==owner && owner->roles.size()==1 && owner->cache.Valid(),"canonical alias preserves roles and cache");
  const auto observed=FrameSurvey::observers;
  ResTrack_Dx12::HookDevice(proxy.device());
  need(NrdBridge::gService.get()==owner && FrameSurvey::observers==observed,"second actual metadata initializer preserves native service");
  const auto priorRefresh=refreshCalls;
  HookToDevice(other.device());ResTrack_Dx12::HookDevice(other.device());
  need(refreshCalls==priorRefresh && NrdBridge::gService.get()==owner,"auxiliary device cannot replace selected title service");
  { FrameSurvey::ScopedInternal internal;
   State::Instance().currentD3D12Device=other.device();HookToDevice(other.device());ResTrack_Dx12::HookDevice(other.device());
   need(!NrdBridge::Initialize(other.device()),"internal SDK initialization cannot replace service");
   need(internalCreate(nullptr,D3D_FEATURE_LEVEL_12_0,IID_IUnknown,nullptr)==S_FALSE && internalFactory(nullptr,nullptr,D3D_FEATURE_LEVEL_12_0,IID_IUnknown,nullptr)==S_FALSE,"actual internal create guards reach original entries");
  }
  need(refreshCalls==priorRefresh && NrdBridge::gService.get()==owner && originals==2,"internal entry bypass leaves captured selection and owner unchanged");
  State::Instance().currentD3D12Device=proxy.device();State::Instance().creatingD3DDevice=true;
  need(internalCreate(nullptr,D3D_FEATURE_LEVEL_12_0,IID_IUnknown,nullptr)==S_FALSE && internalFactory(nullptr,nullptr,D3D_FEATURE_LEVEL_12_0,IID_IUnknown,nullptr)==S_FALSE,"auxiliary capability/SDK creation scope bypasses capture");
  State::Instance().creatingD3DDevice=false;
  void* next=nextProxy.device();captureDevice(E_FAIL,&next,D3D_FEATURE_LEVEL_12_0,false);
  captureDevice(S_OK,&next,D3D_FEATURE_LEVEL_1_0_CORE,false);captureDevice(S_OK,&next,D3D_FEATURE_LEVEL_12_0,true);
  need(State::Instance().currentD3D12Device==proxy.device() && refreshCalls==priorRefresh,"actual capture gate rejects failed/core/non-primary devices");
  captureDevice(S_OK,&next,D3D_FEATURE_LEVEL_12_0,false);
  need(State::Instance().currentD3D12Device==nextProxy.device() && refreshCalls==priorRefresh+1 && refreshed==other.device(),"successful selected title-device creation reaches refresh despite installed hooks");
  need(NrdBridge::gService && NrdBridge::gService->device.Get()==other.device() && NrdBridge::gService->roles.empty() && !NrdBridge::gService->cache.Valid(),"new canonical device replaces stale owner and rediscovery state");
  need(serviceDestructions==1 && destructionUnlocked && destructionInternal && observerPublicationSerialized,"old service destruction occurs outside locks while observer publication remains lifecycle serialized");
  refreshAvailable=false;State::Instance().currentD3D12Device=third.device();HookToDevice(third.device());
  auto status=NrdBridge::GetStatus();
  need(!NrdBridge::gService && !NrdBridge::RuntimeEnabled() && status.installed && !status.active && status.phase=="Inactive" && status.reason.find("compute hook")!=std::string::npos,"unsupported replacement safely retires old owner and gives concrete inactive menu reason");
  need(config->FfxDenoiserNrdBridgeEnabled.value_or_default(),"temporary device failure preserves persisted runtime preference");
  refreshAvailable=true;HookToDevice(third.device());
  need(NrdBridge::gService && NrdBridge::gService->device.Get()==third.device() && NrdBridge::gUnavailableReason.empty(),"supported replacement reinitializes and clears unavailable reason");
  owner=NrdBridge::gService.get();owner->cache.valid=true;owner->status.active=true;owner->status.nativeMaterialGuidesActive=true;owner->pendingList=reinterpret_cast<void*>(9);
  auto& pendingListState=owner->lists[owner->pendingList];pendingListState={true,true};
  pendingListState.recording=std::make_shared<NrdBridge::RecordingToken>();pendingListState.recording->commitRequired.store(true);
  pendingListState.history=std::make_shared<NrdBridge::HistoryDomain>();
  pendingListState.native[0]=std::make_shared<NrdBridge::NativeTransaction>();
  pendingListState.native[0]->recording=std::make_shared<NrdBridge::RecordingToken>();
  pendingListState.native[0]->history=std::make_shared<NrdBridge::HistoryDomain>();
  pendingListState.native[1]=std::make_shared<NrdBridge::NativeTransaction>();
  pendingListState.native[1]->recording=std::make_shared<NrdBridge::RecordingToken>();
  pendingListState.native[1]->history=std::make_shared<NrdBridge::HistoryDomain>();
  pendingListState.native[1]->committed.store(true); // An already committed stage must not be re-invalidated.
  const auto serial=owner->resetSerial;
  config->ResetFfxDenoiserSettings();NrdBridge::dispatchGate();
  need(!config->FfxDenoiserNrdBridge.value_or_default() && config->FfxDenoiserNrdBridgeEnabled.value_for_config()==false && GetBoolValue(config->FfxDenoiserNrdBridgeEnabled.value_for_config())=="false","complete actual ResetAll clears next-start key and serializes runtime false");
  need(NrdBridge::StartupEnabled() && NrdBridge::gInstalled && NrdBridge::gService.get()==owner,"ResetAll preserves installed startup selection and service");
  need(!NrdBridge::RuntimeEnabled() && !owner->status.active && !FrameSurvey::window && !owner->pendingList && !owner->lists.begin()->second.converted && owner->resetSerial>serial && NrdBridge::work==0,"ResetAll immediately cancels pending injections and closes binding window");
  need(!owner->status.nativeMaterialGuidesActive && owner->discardRequested &&
   pendingListState.native[0]->invalidated && pendingListState.native[0]->recording->skipInvalidated.load() &&
   pendingListState.native[0]->history->uncertain.load() && pendingListState.native[0]->history->discardPending.load() &&
   !pendingListState.native[1]->invalidated && pendingListState.recording->skipInvalidated.load() &&
   pendingListState.history->uncertain.load() && owner->cancellationSerial>serial,
   "ResetAll invalidates every uncommitted native stage, spares the committed one, marks required recordings skipped and latches the discard request");
  tag();present(DXGI_PRESENT_TEST);present(0);
  need(NrdBridge::tags==1 && NrdBridge::presents==1 && menuAvailable(),"actual SL/Present/menu predicates remain available after ResetAll and exclude TEST Presents");
  NrdBridge::ConfigureStartup(false);need(NrdBridge::StartupEnabled(),"later bootstrap cannot remove installed selection");
  config->RestoreComputeSignature=false;config->ExtendedStateRestore=false;
  config->FfxDenoiserNrdBridgeEnabled=true;NrdBridge::SetRuntimeEnabled(true);
  need(NrdBridge::RuntimeEnabled() && config->RestoreComputeSignature.value_or_default() && config->ExtendedStateRestore.value_or_default(),"menu re-enable after ResetAll restores forced prerequisites and runtime");
  NrdBridge::Shutdown();
  need(!NrdBridge::gService && !NrdBridge::gInstalled && !NrdBridge::RuntimeEnabled() && destructionUnlocked && destructionInternal,"shutdown safely releases all service owners outside coordinator locks");
 }
 need(first.refs==1 && proxy.refs==1 && other.refs==1 && nextProxy.refs==1 && third.refs==1,"normalization/rebind/shutdown balance every fake COM reference");
 std::cout<<checks<<'\n';return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
'''


def run():
    base = ROOT/'OptiScaler'
    bridge = (base/'shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.cpp').read_text()
    cfg, hdr = (base/'Config.cpp').read_text(), (base/'Config.h').read_text()
    device, track = (base/'hooks/D3D12_Hooks.cpp').read_text(), (base/'resource_tracking/ResTrack_dx12.cpp').read_text()
    bootstrap = (base/'dllmain.cpp').read_text()
    init = 'NrdBridge::ConfigureStartup(Config::Instance()->FfxDenoiserNrdBridge.value_or_default());'
    source_checks = 0
    def check(ok, detail):
        nonlocal source_checks
        assert ok, detail
        source_checks += 1
    check(bootstrap.count(init) == 1, "explicit bootstrap appears once")
    check(bootstrap.index(init) < bootstrap.index('CheckQuirks(possibleNvidia);'), "bootstrap precedes restore prerequisites")
    check(bootstrap.index('CheckQuirks(possibleNvidia);') < bootstrap.index('CheckWorkingMode();', bootstrap.index(init)), "prerequisites precede hook attachment")
    reset = function(cfg, 'bool Config::ResetFfxDenoiserSettings()')
    fields = set(re.findall(r'\b(FfxDenoiser\w+)\b', reset)) | {'RestoreComputeSignature', 'ExtendedStateRestore'}
    rows_by_key = {key: [line.strip() for line in hdr.splitlines() if re.search(r'CustomOptional<[^;]+>\s+'+key+r'\b', line)] for key in sorted(fields)}
    check(all(len(rows)==1 for rows in rows_by_key.values()), rows_by_key)
    declarations = [rows[0] for rows in rows_by_key.values()]
    root_hook = function(device, 'static void HookToDevice(ID3D12Device* InDevice)\n{')
    root_hook = root_hook[:root_hook.index('    // hudless')] + '}\n'
    metadata_hook = function(track, 'void ResTrack_Dx12::HookDevice(ID3D12Device* device)')
    metadata_hook = metadata_hook[:metadata_hook.index('    bool initializeTracking')] + '}\n'
    create = function(device, 'static HRESULT hkD3D12CreateDevice(')
    create_guard = create[create.index('{')+1:create.index('    LOG_DEBUG')]
    factory = function(device, 'static HRESULT hkCreateDevice(')
    at = factory.index('    if (_creatingD3D12Device')
    end = factory.index('\n#ifdef ENABLE_DEBUG_LAYER_DX12', at)
    factory_guard = factory[at:end].replace('        LOG_DEBUG("Calling from hkD3D12CreateDevice, calling original CreateDevice");\n', '')
    capture_at = create.index('    if (result == S_OK')
    capture_end = create.index('        if (desc.VendorId', capture_at)
    capture = create[capture_at:capture_end].replace('        LOG_DEBUG("Device captured: {0:X}", (size_t) *ppDevice);\n', '')
    sl = (base/'hooks/Streamline_Hooks.cpp').read_text()
    pattern = (r'if \(renderApi == sl::RenderAPI::eD3D12\)\s*\{\s*probeSLResourceTag\([^;]+;\s*'
               r'if \(NrdBridge::StartupEnabled\(\) && tags\[i\]\.type == sl::kBufferTypeMotionVectors\)\s*'
               r'NrdBridge::OnTitleTag\([^;]+;')
    blocks = re.findall(pattern, sl)
    check(len(blocks) == 1, "actual SL routing block")
    present = [line.strip() for line in (base/'menu/menu_overlay_dx.cpp').read_text().splitlines() if 'NrdBridge::OnPresent();' in line]
    check(len(present) == 1, "actual Present callback predicate")
    menu = (base/'menu/menu_common.cpp').read_text()
    menu_guard = [line.strip() for line in menu.splitlines() if 'if (NrdBridge::StartupEnabled() && ImGui::CollapsingHeader(' in line]
    check(len(menu_guard) == 1, "actual menu callback predicate")
    after = function(bridge, 'void AfterDispatch(')
    replacements = {
        'ROOT': ROOT.as_posix(),
        'UNWRAP': function((base/'Util.cpp').read_text(), 'bool Util::CheckForRealObject(').replace('Util::', ''),
        'OPTIONAL': hdr[hdr.index('enum HasDefaultValue'):hdr.index('constexpr inline int UnboundKey')],
        'DECLARATIONS': '\n'.join(declarations), 'RESET': reset,
        'COORDINATOR': '\n'.join(function(bridge, sig) for sig in (
            'void PublishBindingWindow()', 'void RequireRestoreFlags()',
            'template<class Configuration> RRSettings ReadStartupSettings(const Configuration& config)',
            'template<class Configuration> bool ReadStartupCameraDepth(const Configuration& config)',
            'void InvalidateSkippedRecording(ListState& list, const char* gate="recording_invalidated") noexcept',
            'void DropPending(Service& owner, RetiredDebugSources& retired)',
            'void StartWindow(Service& owner)',
            'bool SupportedExecutable() noexcept',
            'template<class Tracker> NativeRetirementStartup ConfigureNativeRetirement() noexcept',
            'void ConfigureStartup(bool enabled) noexcept',
            'bool StartupEnabled() noexcept', 'bool Initialize(ID3D12Device* device) noexcept',
            'void Shutdown() noexcept', 'void ReportUnavailable(const char* reason) noexcept',
            'Status GetStatus()',
            'void SetRuntimeEnabled(bool enabled) noexcept', 'bool RuntimeEnabled() noexcept')),
        'DEVICE_HOOK': root_hook, 'RESTRACK_HOOK': metadata_hook,
        'DISPATCH_GUARD': after[after.index('    if ('):after.index('return;')+7],
        'CREATE_GUARD': create_guard, 'FACTORY_GUARD': factory_guard,
        'CAPTURE_PREFIX': capture, 'BOOTSTRAP': init,
        'SERIALIZER': function(cfg, 'std::string GetBoolValue('),
        'TAG_BLOCK': blocks[0]+'\n}', 'PRESENT': present[0], 'MENU_GUARD': menu_guard[0],
    }
    cpp = CPP
    for key, value in replacements.items():
        cpp = cpp.replace('__'+key+'__', value)
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    stubs = out/'stubs'
    stubs.mkdir(exist_ok=True)
    (stubs/'Util.h').write_text('#pragma once\n#include <unknwn.h>\n#include <string>\nnamespace Util { bool CheckForRealObject(std::string,IUnknown*,IUnknown**); }\n')
    source, exe = out/'nrd_startup.cpp', out/'nrd_startup.exe'
    source.write_text(cpp)
    compile_cpp(source, exe, ('ole32.lib', 'dxguid.lib'), (stubs, ROOT / 'OptiScaler', ROOT / 'external/streamline', ROOT / 'external/streamline1'))
    rows = []
    for name, selection in (('cyberpunk2077.exe','on'), ('CYBERPUNK2077.EXE','on'),
                            ('cyberpunk2077.exe','off'), ('CYBERPUNK2077.EXE','off'),
                            ('cyberpunk.exe','on'), ('cyberpunk2077.exe.bak','on')):
        result = subprocess.run([str(exe), name, selection], capture_output=True, text=True)
        (out/f"{name}-{selection}.json").write_text(json.dumps(dict(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr), indent=2)+'\n')
        if result.returncode:
            raise RuntimeError(f"{name} startup={selection} exit={result.returncode}: {result.stderr}")
        rows.append(dict(executable=name, startup=selection, native_checks=int(result.stdout.strip())))
    data = dict(native_checks=sum(row['native_checks'] for row in rows), python_checks=source_checks, cases=rows,
                scope='actual startup/lifecycle/runtime/reset/canonical unwrap and hook/capture prefixes; fake COM devices/service provider storage; no GPU or complete device detour installer')
    (out/'result.json').write_text(json.dumps(data, indent=2)+'\n')
    print(json.dumps(data, indent=2))


if __name__ == '__main__':
    run()
