"""Execute actual NRD menu controls, immutable payload construction and INI reset.

ImGui and bridge runtime APIs are spies. Actual CustomOptional/parsers/serializers,
complete ResetAll and menu bodies verify UI-to-runtime wiring and persistence.
Provider Configure/history serialization is tested separately by the RR fixture.
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

KEYS = {
    'FfxDenoiserNrdBridgeLightingValidation': ('NrdBridgeLightingValidation', 'Bool'),
    'FfxDenoiserNrdBridgeMotionAdaptiveStability': ('NrdBridgeMotionAdaptiveStability', 'Bool'),
    'FfxDenoiserNrdBridgeStillStability': ('NrdBridgeStillStability', 'Float'),
    'FfxDenoiserNrdBridgeMovingStability': ('NrdBridgeMovingStability', 'Float'),
    'FfxDenoiserNrdBridgeStabilityRotation': ('NrdBridgeStabilityRotationDegrees', 'Float'),
    'FfxDenoiserNrdBridgeStabilityTranslation': ('NrdBridgeStabilityTranslationMetres', 'Float'),
    'FfxDenoiserNrdBridgeStabilityRamp': ('NrdBridgeStabilityRampUp', 'Float'),

    'FfxDenoiserRecoveryFlatAlbedo': ('RecoveryFlatAlbedo', 'Bool'),
    'FfxDenoiserRecoveryFlatAlbedoStrength': ('RecoveryFlatAlbedoStrength', 'Float'),
    'FfxDenoiserRecoveryFlatRoughness': ('RecoveryFlatRoughness', 'Int'),
    'FfxDenoiserRecoveryFlatAnchor': ('RecoveryFlatAnchor', 'Float'),
    'FfxDenoiserRecoveryFlatMix': ('RecoveryFlatMix', 'Float'),
    'FfxDenoiserRecoveryFlatTemporal': ('RecoveryFlatTemporal', 'Bool'),
    'FfxDenoiserRecoveryFlatHistoryLength': ('RecoveryFlatHistoryLength', 'Int'),
    'FfxDenoiserRecoveryFlatTemporalDenoise': ('RecoveryFlatTemporalDenoise', 'Float'),
    'FfxDenoiserRecoveryFlatRRFallback': ('RecoveryFlatRRFallback', 'Bool'),
    'FfxDenoiserRecoveryFlatDiffuseRR': ('RecoveryFlatDiffuseRR', 'Bool'),
    'FfxDenoiserRecoveryFlatReflectionHistory': ('RecoveryFlatReflectionHistory', 'Bool'),
    'FfxDenoiserRecoveryFlatReflectionDetail': ('RecoveryFlatReflectionDetail', 'Float'),
    'FfxDenoiserRecoveryFlatReflectionPolish': ('RecoveryFlatReflectionPolish', 'Float'),
    'FfxDenoiserRadianceScaleExperiment': ('RadianceScaleExperiment', 'Bool'),
    'FfxDenoiserRadianceScaleDiffuse': ('RadianceScaleDiffuse', 'Int'),
    'FfxDenoiserRadianceScaleSpecular': ('RadianceScaleSpecular', 'Int'),
    'FfxDenoiserNrdBridgeUseCustomRR': ('NrdBridgeUseCustomRR', 'Bool'),
    'FfxDenoiserNrdBridgeMotionDepthMode': ('NrdBridgeMotionDepthMode', 'Bool'),
    'FfxDenoiserNrdBridgeLegacyMotionDepth': ('NrdBridgeLegacyMotionDepth', 'Bool'),
    'FfxDenoiserNrdBridgeNativeTemporalMotion': ('NrdBridgeNativeTemporalMotion', 'Bool'),
    'FfxDenoiserNrdBridgeNativeMaterialGuides': ('NrdBridgeNativeMaterialGuides', 'Bool'),
    'FfxDenoiserNrdBridgeMaterialIDs': ('NrdBridgeMaterialIDs', 'Bool'),
    'FfxDenoiserNrdBridgeSurfaceValidFill': ('NrdBridgeSurfaceValidFill', 'Bool'),
    'FfxDenoiserNrdBridgeTurnColour': ('NrdBridgeTurnColourFilter', 'Bool'),
    'FfxDenoiserNrdBridgeTurnColourFrames': ('NrdBridgeTurnColourFrames', 'Float'),
    'FfxDenoiserNrdBridgeTurnColourDegrees': ('NrdBridgeTurnColourDegrees', 'Float'),
    'FfxDenoiserNrdBridgeTurnBrightness': ('NrdBridgeTurnBrightness', 'Bool'),
    'FfxDenoiserNrdBridgeTurnBrightnessAmount': ('NrdBridgeTurnBrightnessAmount', 'Float'),
    'FfxDenoiserNrdBridgeTurnBrightnessFrames': ('NrdBridgeTurnBrightnessFrames', 'Float'),
    'FfxDenoiserNrdBridgeLobeRecovery': ('NrdBridgeLobeRecovery', 'Bool'),
    'FfxDenoiserNrdBridgeRecoverySpecular': ('NrdBridgeRecoverySpecular', 'Float'),
    'FfxDenoiserNrdBridgeRecoveryDiffuse': ('NrdBridgeRecoveryDiffuse', 'Float'),
    'FfxDenoiserNrdBridgeEnabled': ('NrdBridgeEnabled', 'Bool'),
    'FfxDenoiserUseAmdDefaults': ('UseAmdDefaults', 'Bool'),
    'FfxDenoiserCrossBlNormStr': ('CrossBilateralNormalStrength', 'Float'),
    'FfxDenoiserStabilityBias': ('TemporalStabilityBias', 'Float'),
    'FfxDenoiserMaxRadiance': ('MaxRadiance', 'Float'),
    'FfxDenoiserRadianceClip': ('RadianceClipDeviation', 'Float'),
    'FfxDenoiserGaussKernRelax': ('GaussianKernelRelaxation', 'Float'),
    'FfxDenoiserDisocThreshold': ('DisocclusionThreshold', 'Float'),
    'FfxDenoiserNrdBridgeNativeDebugView': ('NrdBridgeNativeDebugView', 'Int'),
    'FfxDenoiserNrdBridgeNativeDebugViewport': ('NrdBridgeNativeDebugViewport', 'Int'),
}

CPP = r'''
#define SI_NO_CONVERSION
#include "__SIMPLEINI__"
#include <algorithm>
#include <array>
#include <cctype>
#include <concepts>
#include <cmath>
#include <limits>
#include <cstdint>
#include <cstdarg>
#include <cstdio>
#include <format>
#include <iostream>
#include <map>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#define LOG_WARN(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
constexpr int VK_F9=120;
unsigned checks=0;
void need(bool ok,const char* message){if(!ok)throw std::runtime_error(message);++checks;}
__CUSTOM__
__SCALE_POLICY__
__FFX_DEBUG_CONTRACT__
namespace FSRDSignals {constexpr int Auto=0;}
namespace NrdBridge {
__RR_CONTRACT__
bool startup=false,runtime=true,camera=false,accept=true,guidesActive=false;unsigned applyCalls=0,resetCalls=0,statusCalls=0;
RRSettings last{};bool lastCamera=false;RRSettingsState state;
enum class DebugMode {Off,RawSignals,RRInputs};DebugMode conversionDebug=DebugMode::Off;
__STATUS_CONTRACT__
Status statusCounters;
bool StartupEnabled(){return startup;}bool RuntimeEnabled(){return runtime;}
void SetRuntimeEnabled(bool value){runtime=value;}
Status GetStatus(){++statusCalls;auto value=statusCounters;value.nativeMaterialGuidesActive=guidesActive;return value;}
void RequestHistoryReset(){++resetCalls;}
DebugMode GetDebugMode(){return conversionDebug;}void SetDebugMode(DebugMode value){conversionDebug=value;}
bool ApplyRRSettings(const RRSettings& settings,bool motion,std::string& error) noexcept {
 ++applyCalls;last=settings;lastCamera=motion;
 if(!accept){error="rejected test snapshot";return false;}
 error.clear();state.requested=settings;camera=motion;return true;
}
RRSettingsState GetRRSettingsState() noexcept{return state;}
bool CameraProjectedDepthEnabled() noexcept{return camera;}
}
CSimpleIniA ini;
__SERIALIZERS__
struct Config {
__CONFIG_FIELDS__
static Config* active;static Config* Instance(){return active;}
std::vector<std::string> _log;
std::optional<std::string> readString(std::string,std::string,bool lowercase=false);
std::optional<bool> readBool(std::string,std::string);
std::optional<float> readFloat(std::string,std::string);
std::optional<int> readInt(std::string,std::string);
bool ResetFfxDenoiserSettings();
void load(const std::string& data){ini.Reset();need(ini.LoadData(data)>=0,"SimpleIni loads fixture");__RESET_KEYS__ __LOAD_KEYS__}
std::string save(){__SAVE_KEYS__ std::string data;need(ini.Save(data)>=0,"SimpleIni serializes production keys");return data;}
};Config* Config::active=nullptr;
__READERS__
__RESET_ALL__
constexpr int ImGuiTableFlags_Borders=1,ImGuiTableFlags_Resizable=2;
struct ScopedIndent {};
namespace ImGui {
std::map<std::string,bool> bools;std::map<std::string,float> floats;std::map<std::string,int> combos;std::map<std::string,bool> buttons,headers;
std::vector<bool> disabled;std::vector<std::string> labels,text;unsigned rrTables=0;
bool hovered=false;
bool isDisabled(){return !disabled.empty()&&disabled.back();}
bool CollapsingHeader(const char* name){labels.push_back(name);auto it=headers.find(name);return it==headers.end()||it->second;}
bool TreeNode(const char* name){return CollapsingHeader(name);} void TreePop(){}
bool SliderInt(const char* name,int* value,int minimum,int maximum){labels.push_back(name);auto it=combos.find(name);
 if(isDisabled()||it==combos.end())return false;need(it->second>=minimum&&it->second<=maximum,"integer UI range");
 *value=it->second;combos.erase(it);return true;}
bool Checkbox(const char* name,bool* value){labels.push_back(name);auto it=bools.find(name);
 if(isDisabled()||it==bools.end())return false;bool next=it->second;bools.erase(it);bool changed=*value!=next;*value=next;return changed;}
bool SliderFloat(const char* name,float* value,float minimum,float maximum,const char* =nullptr){labels.push_back(name);auto it=floats.find(name);
 if(isDisabled()||it==floats.end())return false;need(it->second>=minimum&&it->second<=maximum,"UI input stays inside actual slider range");
 *value=it->second;floats.erase(it);return true;}
bool Button(const char* name){labels.push_back(name);return !isDisabled()&&buttons.erase(name)!=0;}
bool IsItemHovered(){return hovered;}
void SetTooltip(const char* format,...){char buffer[2048];va_list args;va_start(args,format);vsnprintf(buffer,sizeof(buffer),format,args);va_end(args);text.push_back(buffer);}
void BeginDisabled(bool value){disabled.push_back(isDisabled()||value);}void EndDisabled(){disabled.pop_back();}
void PushID(const char*){}void PopID(){}
bool combo(const char* name,int* value,int count){labels.push_back(name);auto found=combos.find(name);
 if(isDisabled()||found==combos.end())return false;need(found->second>=0&&found->second<count,"Combo selection uses supported entry range");
 const bool changed=*value!=found->second;*value=found->second;combos.erase(found);return changed;}
bool Combo(const char* name,int* value,const char* items){int count=0;for(auto p=items;*p;p+=std::char_traits<char>::length(p)+1)++count;return combo(name,value,count);}
bool Combo(const char* name,int* value,const char* const[],int count){return combo(name,value,count);}
void capture(const char* format,va_list args){char buffer[2048];vsnprintf(buffer,sizeof(buffer),format,args);text.push_back(buffer);}
void TextWrapped(const char* format,...){va_list args;va_start(args,format);capture(format,args);va_end(args);}
void TextDisabled(const char* format,...){va_list args;va_start(args,format);capture(format,args);va_end(args);}
void Text(const char* format,...){va_list args;va_start(args,format);capture(format,args);va_end(args);}
void TextUnformatted(const char* value){text.push_back(value);}
bool BeginTable(const char* name,int,int){if(std::string(name)=="NrdBridgeRRValues")++rrTables;return true;}
void TableSetupColumn(const char*){}void TableHeadersRow(){}void TableNextRow(){}void TableNextColumn(){}void EndTable(){}
void frame(){bools.clear();floats.clear();combos.clear();buttons.clear();headers.clear();labels.clear();text.clear();rrTables=0;hovered=false;need(disabled.empty(),"UI disabled scopes are balanced");}
bool hasText(const std::string& term){return std::any_of(text.begin(),text.end(),[&](const auto& s){return s.find(term)!=s.npos;});}
bool hasLabel(const std::string& term){return std::find(labels.begin(),labels.end(),term)!=labels.end();}
}
__MENU_HELPERS__
template<class T> concept RetiredNativeOutputBlendConfig = requires(T value) { value.FfxDenoiserNrdBridgeNativeSpecularBlend; };
void drawBridge(Config* config){__BRIDGE_PANEL__}
int main(){try{
 Config cfg;Config::active=&cfg;cfg.load("[FSR-RR]\nUnrelated=keep\n[Other]\nNrdBridgeUseCustomRR=untouched\n");
 need(!cfg.FfxDenoiserNrdBridgeUseCustomRR.value_or_default()&&!cfg.FfxDenoiserNrdBridgeMotionDepthMode.value_or_default()&&
      !cfg.FfxDenoiserNrdBridgeLegacyMotionDepth.value_or_default()&&!ReadNrdBridgeRRSettings(cfg).legacyMotionDepth,
      "Both motion experiments and the legacy rollback default OFF in Config and the applied snapshot");
 need(ReadNrdBridgeRRSettings(cfg).overrideMask==0,"Missing options preserve AMD baseline rather than fork slider defaults");
 NrdBridge::startup=false;ImGui::frame();drawBridge(&cfg);
 need(!NrdBridge::statusCalls&&!NrdBridge::applyCalls&&ImGui::labels.empty(),"Startup OFF never enters bridge panel or applies settings");
 NrdBridge::startup=true;ImGui::frame();ImGui::headers["CP77 NRD bridge"]=false;drawBridge(&cfg);
 need(!NrdBridge::statusCalls&&!NrdBridge::applyCalls,"Closed bridge panel does no runtime settings work");
 ImGui::frame();drawBridge(&cfg);
 need(ImGui::hasLabel("Use custom RR tuning##NrdBridge")&&ImGui::hasLabel("Camera-projected depth delta (experimental)")&&
      ImGui::hasLabel("Legacy previous-visible-depth motion Z (A/B rollback)"),"Startup-selected bridge exposes controls without any upscaler owner");
 need(!NrdBridge::applyCalls&&!ImGui::rrTables&&ImGui::hasText("not available yet"),"Idle controls do not apply/query provider defaults or invent effective numbers");
 for(const char* term:{"Specular lighting","Diffuse lighting","Hit distance","Normal + roughness","Linear VIEWZ","Motion + jitter","Albedo guides","Consumer output encoding","Unused title inputs"})
 need(ImGui::hasText(term),"Every supported/unused input has a human-readable row");
 need(ImGui::hasText("303")&&ImGui::hasText("1212")&&ImGui::hasText("factor 64")&&ImGui::hasText("camera-only estimate"),"Map explains exact Consumer encoding and the camera-only default motion depth");
 need(ImGui::hasText("confirmed by the downstream material compositor")&&ImGui::hasText("does not divide it again")&&ImGui::hasText("omitting material cues"),
 "Map explains attested demodulation, material remodulation and white-guide limits");
 need(!ImGui::hasText("already-demodulated")&&!ImGui::hasText("albedo division is needed"),
 "Map preserves uncertainty instead of asserting proven demodulation or albedo matching");
 need(ImGui::hasText("Owned raw A/B noisy")&&ImGui::hasText("captured before native filters"),"Lighting map identifies owned unfiltered raw sources");
 need(ImGui::hasText("Bridge-owned depth is built")&&ImGui::hasText("object motion is not reconstructed")&&ImGui::hasText("not a confidence mask"),"Geometry map does not depend on native NRD depth/history outputs and states the camera-only provenance limits");
 need(ImGui::hasText("control 2 preserves full-rate")&&ImGui::hasText("controls 0/1 reconstruct only missing"),"Checkerboard map explains local GPU reconstruction without altering present samples");
 need(ImGui::hasText("current game modes remain unknown until a completed recording"),"Checkerboard runtime modes require actual completed Trace evidence");
 need(ImGui::hasText("Native NRD denoised RGB, temporal history and confidence are not used")&&!ImGui::hasText("checkerboard controls have no equivalent"),"Map excludes native denoised data while acknowledging consumed checkerboard controls");
 ImGui::frame();ImGui::floats["Max Radiance"]=100;drawBridge(&cfg);need(!NrdBridge::applyCalls&&cfg.FfxDenoiserMaxRadiance.value_or_default()==40000,"OFF custom tuning ignores disabled slider edits");
 ImGui::frame();ImGui::bools["Use custom RR tuning##NrdBridge"]=true;
 ImGui::floats={{"Cross Bilateral Normal Strength",.25f},{"Temporal Stability Bias",.6f},{"Max Radiance",30000},
 {"Radiance Clip Deviation",12},{"Gaussian Kernel Relaxation",.4f},{"Disocclusion Threshold",.2f}};
 drawBridge(&cfg);need(NrdBridge::applyCalls==1&&NrdBridge::last.overrideMask==0x3f,"One frame publishes one coherent six-scalar override snapshot");
 const std::array<float,8> desired{.25f,.6f,30000,12,.4f,.2f,0,0};
 need(NrdBridge::last.values==desired&&!NrdBridge::lastCamera,"Provider key order is exact and unused bounds are not enabled");
 auto saved=cfg.save();Config reload;Config::active=&reload;reload.load(saved);
 need(ReadNrdBridgeRRSettings(reload).overrideMask==0x3f&&ReadNrdBridgeRRSettings(reload).values==desired,"Menu values/custom enable survive actual save/reload");
 need(std::string(ini.GetValue("FSR-RR","Unrelated",""))=="keep"&&std::string(ini.GetValue("Other","NrdBridgeUseCustomRR",""))=="untouched","Other settings and sections survive save/reload");
 Config::active=&cfg;ImGui::frame();ImGui::bools["Use AMD Default Tuning"]=true;drawBridge(&cfg);
 need(NrdBridge::applyCalls==2&&NrdBridge::last.overrideMask==0&&cfg.FfxDenoiserMaxRadiance.value_or_default()==30000,"AMD reference switch applies mask0 while retaining custom values");
 ImGui::frame();ImGui::bools["Use AMD Default Tuning"]=false;drawBridge(&cfg);need(NrdBridge::last.values==desired,"Switching back restores all stored overrides");
 ImGui::frame();ImGui::bools["Camera-projected depth delta (experimental)"]=true;drawBridge(&cfg);
 need(NrdBridge::lastCamera&&NrdBridge::camera&&ImGui::hasText("camera-only estimate"),"Motion experiment applies one accepted runtime mode; the map states the camera-only default it shares");
 saved=cfg.save();reload.load(saved);need(reload.FfxDenoiserNrdBridgeMotionDepthMode.value_or_default(),"Motion experiment survives save/reload");
 ImGui::frame();ImGui::bools["Legacy previous-visible-depth motion Z (A/B rollback)"]=true;drawBridge(&cfg);
 need(ReadNrdBridgeRRSettings(cfg).legacyMotionDepth&&NrdBridge::last.legacyMotionDepth&&ImGui::hasText("old occluder"),"Legacy rollback applies once and the map names its occluder failure mode");
 saved=cfg.save();reload.load(saved);need(reload.FfxDenoiserNrdBridgeLegacyMotionDepth.value_or_default()&&ReadNrdBridgeRRSettings(reload).legacyMotionDepth,"Legacy rollback survives production serializer and reload");
 {Config malformed;malformed.load("[FSR-RR]\nNrdBridgeLegacyMotionDepth=invalid\n");need(!ReadNrdBridgeRRSettings(malformed).legacyMotionDepth,"Malformed legacy rollback key stays OFF");}
 ImGui::frame();ImGui::bools["Legacy previous-visible-depth motion Z (A/B rollback)"]=false;drawBridge(&cfg);
 need(!cfg.FfxDenoiserNrdBridgeLegacyMotionDepth.value_or_default()&&!NrdBridge::last.legacyMotionDepth&&ImGui::hasText("camera-only estimate"),"Legacy rollback returns to the camera-only default through the checkbox");
 NrdBridge::state.ready=true;NrdBridge::state.defaults={.8f,.8f,40000,8,.6f,.1f,0,100};NrdBridge::state.effective=desired;
 ImGui::frame();drawBridge(&cfg);need(ImGui::rrTables==1&&ImGui::hasText("0.25")&&ImGui::hasText("0.8")&&ImGui::hasText("30000"),"Effective and queried baseline numbers appear only when ready");
 NrdBridge::accept=false;const bool priorCamera=NrdBridge::camera;
 ImGui::frame();ImGui::bools["Camera-projected depth delta (experimental)"]=false;drawBridge(&cfg);
 need(ImGui::hasText("Settings not applied")&&NrdBridge::camera==priorCamera,"Rejected snapshot reports failure and leaves effective runtime mode unchanged");
 NrdBridge::accept=true;ImGui::frame();ImGui::buttons["Reset AMD Tuning"]=true;drawBridge(&cfg);
 need(!cfg.FfxDenoiserNrdBridgeUseCustomRR.value_or_default()&&NrdBridge::last.overrideMask==0&&!ImGui::hasText("Settings not applied"),"Bridge AMD reset returns to baseline and clears apply error");
 cfg.FfxDenoiserNrdBridgeMotionDepthMode=true;cfg.FfxDenoiserNrdBridgeLegacyMotionDepth=true;cfg.FfxDenoiserNrdBridgeUseCustomRR=true;NrdBridge::camera=true;NrdBridge::runtime=true;
 unsigned before=NrdBridge::applyCalls;cfg.ResetFfxDenoiserSettings();
 need(!NrdBridge::runtime&&!cfg.FfxDenoiserNrdBridgeEnabled.value_or_default(),"Full reset turns runtime bridge OFF immediately");
 need(NrdBridge::applyCalls==before+1&&!NrdBridge::last.overrideMask&&!NrdBridge::lastCamera&&!NrdBridge::last.legacyMotionDepth&&!NrdBridge::camera,"Actual full reset clears the coherent RR/motion snapshot including the legacy rollback");
 need(!cfg.FfxDenoiserNrdBridgeUseCustomRR.value_or_default()&&!cfg.FfxDenoiserNrdBridgeMotionDepthMode.value_or_default()&&!cfg.FfxDenoiserNrdBridgeLegacyMotionDepth.value_or_default(),"Full reset restores both new OFF defaults plus the legacy rollback OFF");
 saved=cfg.save();reload.load(saved);need(!reload.FfxDenoiserNrdBridgeMotionDepthMode.value_or_default()&&!reload.FfxDenoiserNrdBridgeLegacyMotionDepth.value_or_default()&&!reload.FfxDenoiserNrdBridgeUseCustomRR.value_or_default()&&!reload.FfxDenoiserNrdBridgeEnabled.value_or_default(),"Full reset persists safe OFF state across reload");
 NrdBridge::startup=false;before=NrdBridge::applyCalls;cfg.ResetFfxDenoiserSettings();need(NrdBridge::applyCalls==before,"Full reset with startup OFF makes no new snapshot apply call");
 cfg.load("[FSR-RR]\nNrdBridgeUseCustomRR=invalid\nNrdBridgeMotionDepthMode=auto\nNrdBridgeLegacyMotionDepth=maybe\n");
 need(!cfg.FfxDenoiserNrdBridgeMotionDepthMode.value_or_default()&&!cfg.FfxDenoiserNrdBridgeUseCustomRR.value_or_default()&&!cfg.FfxDenoiserNrdBridgeLegacyMotionDepth.value_or_default(),"Invalid/missing new booleans remain OFF");
 ImGui::frame();cfg.FfxDenoiserNrdBridgeUseCustomRR=true;ImGui::buttons["Reset AMD Tuning"]=true;
 need(DrawAmdRRTuning(&cfg)&&cfg.FfxDenoiserNrdBridgeUseCustomRR.value_or_default(),"Ordinary RR reset does not change bridge-only custom-enable preference");
 NrdBridge::startup=true;cfg.load("[FSR-RR]\n");
 need(cfg.FfxDenoiserNrdBridgeNativeDebugView.value_or_default()==-1&&ReadNrdBridgeRRSettings(cfg).nativeDebugView==-1,
 "Native DebugView defaults OFF with integration sentinel, not AMD overview0");
 ImGui::frame();before=NrdBridge::applyCalls;ImGui::combos["AMD native fullscreen viewport"]=7;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before,"OFF native debug keeps viewport edit disabled and publishes no new snapshot");
 ImGui::frame();NrdBridge::conversionDebug=NrdBridge::DebugMode::RawSignals;ImGui::combos["AMD RR native DebugView"]=1;drawBridge(&cfg);
 need(NrdBridge::last.nativeDebugView==FFX_API_DENOISER_DEBUG_VIEW_MODE_OVERVIEW&&NrdBridge::last.overrideMask==0,
 "AMD overview selection publishes actual SDK enum independently of custom tuning");
 need(NrdBridge::conversionDebug==NrdBridge::DebugMode::Off&&ImGui::hasText("after the upscaler evaluates"),
 "Native debug clears raw conversion view and explains direct provider-color display");
 ImGui::frame();before=NrdBridge::applyCalls;ImGui::combos["Bridge conversion debug"]=2;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before&&NrdBridge::conversionDebug==NrdBridge::DebugMode::Off,
 "Raw/RRInputs controls cannot override an active native provider view");
 ImGui::frame();ImGui::combos["AMD RR native DebugView"]=2;ImGui::combos["AMD native fullscreen viewport"]=11;drawBridge(&cfg);
 need(NrdBridge::last.nativeDebugView==FFX_API_DENOISER_DEBUG_VIEW_MODE_FULLSCREEN_VIEWPORT&&NrdBridge::last.nativeDebugViewport==11,
 "Fullscreen selection and viewport11 publish coherently using actual supported constants");
 saved=cfg.save();reload.load(saved);auto debugReload=ReadNrdBridgeRRSettings(reload);
 need(debugReload.nativeDebugView==FFX_API_DENOISER_DEBUG_VIEW_MODE_FULLSCREEN_VIEWPORT&&debugReload.nativeDebugViewport==11,
 "Native provider view and viewport survive actual INI save/reload");
 for(int value:{-7,27}){cfg.FfxDenoiserNrdBridgeNativeDebugViewport=value;
 need(ReadNrdBridgeRRSettings(cfg).nativeDebugViewport==uint32_t(value<0?0:11),"INI viewport is bounded to actual MAX_VIEWPORTS");}
 ImGui::frame();ImGui::combos["AMD RR native DebugView"]=0;drawBridge(&cfg);
 need(NrdBridge::last.nativeDebugView==-1,"Off selection publishes integration disable sentinel");
 cfg.FfxDenoiserNrdBridgeNativeDebugView=1;cfg.FfxDenoiserNrdBridgeNativeDebugViewport=8;cfg.ResetFfxDenoiserSettings();
 need(cfg.FfxDenoiserNrdBridgeNativeDebugView.value_or_default()==-1&&cfg.FfxDenoiserNrdBridgeNativeDebugViewport.value_or_default()==0&&
 NrdBridge::last.nativeDebugView==-1,"Full reset disables native debug in both Config and coherent runtime payload");
 saved=cfg.save();reload.load(saved);need(ReadNrdBridgeRRSettings(reload).nativeDebugView==-1,"Native debug remains OFF after reset/save/reload");
 cfg.load("[FSR-RR]\nNrdBridgeNativeDebugView=invalid\nNrdBridgeNativeDebugViewport=auto\n");
 need(ReadNrdBridgeRRSettings(cfg).nativeDebugView==-1&&ReadNrdBridgeRRSettings(cfg).nativeDebugViewport==0,"Malformed native debug keys use safe defaults");
 cfg.load("[FSR-RR]\n");NrdBridge::accept=true;ImGui::frame();before=NrdBridge::applyCalls;drawBridge(&cfg);
 need(!cfg.FfxDenoiserNrdBridgeMaterialIDs.value_or_default()&&!ReadNrdBridgeRRSettings(cfg).preserveNativeMaterialIDs,
 "Material experiment defaults OFF in Config and coherent POD");
 need(NrdBridge::applyCalls==before&&ImGui::hasText("material ID 0"),"OFF material control emits no new apply and maps baseline alpha0");
 need(ImGui::hasText("shared with ordinary FSR-RR")&&ImGui::hasText("latest submitted RR frame")&&ImGui::hasText("SR runs before the current NRD chain"),
 "UI explains shared tuning persistence and native provider diagnostic frame lag");
 ImGui::frame();ImGui::hovered=true;ImGui::bools["Preserve native material IDs (experimental)"]=true;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before+1&&NrdBridge::last.preserveNativeMaterialIDs&&NrdBridge::last.overrideMask==0&&!NrdBridge::lastCamera,
 "Material-only change publishes coherent bool independently of scalar/motion switches");
 need(ImGui::hasText("A/B hypothesis")&&ImGui::hasText("have not been measured")&&ImGui::hasText("four normalized native material categories"),
 "Material tooltip/map distinguish requested categories from unmeasured game alpha/flags");
 saved=cfg.save();reload.load(saved);need(ReadNrdBridgeRRSettings(reload).preserveNativeMaterialIDs,"Material A/B choice survives actual save/reload");
 NrdBridge::state.requested.preserveNativeMaterialIDs=false;ImGui::frame();drawBridge(&cfg);
 need(ImGui::hasText("material ID 0")&&!ImGui::hasText("Requested experimental A"),"Input map uses runtime requested snapshot rather than stale Config true");
 cfg.ResetFfxDenoiserSettings();need(!cfg.FfxDenoiserNrdBridgeMaterialIDs.value_or_default()&&!NrdBridge::last.preserveNativeMaterialIDs,
 "Complete reset disables material experiment in Config and runtime POD");
 saved=cfg.save();reload.load(saved);need(!ReadNrdBridgeRRSettings(reload).preserveNativeMaterialIDs,"Reset/save/reload retains material OFF default");
 cfg.load("[FSR-RR]\nNrdBridgeMaterialIDs=invalid\n");need(!ReadNrdBridgeRRSettings(cfg).preserveNativeMaterialIDs,"Malformed material key remains OFF");
 cfg.load("[FSR-RR]\n");NrdBridge::accept=true;ImGui::frame();before=NrdBridge::applyCalls;drawBridge(&cfg);
 need(!RetiredNativeOutputBlendConfig<Config>,"Retired native-output mixing has no Config storage");
 need(!ImGui::hasLabel("NRD reference specular blend (experimental)")&&!ImGui::hasText("Applied NRD reference specular blend")&&
 !ImGui::hasText("NRD-assisted hybrid")&&NrdBridge::applyCalls==before,
 "Removed output-mixing control has no menu, applied readout or idle runtime action");
 for(const char* value:{"1","0.5","-5","nan","inf","auto","invalid"}) {
  cfg.load(std::string("[FSR-RR]\nNrdBridgeNativeSpecularBlend=")+value+"\nUnrelated=keep\n[Other]\nNrdBridgeNativeSpecularBlend=untouched\n");
  ImGui::frame();before=NrdBridge::applyCalls;ImGui::floats["NRD reference specular blend (experimental)"]=1.f;drawBridge(&cfg);
  need(!ImGui::hasLabel("NRD reference specular blend (experimental)")&&NrdBridge::applyCalls==before&&
  ReadNrdBridgeRRSettings(cfg).nativeSpecularBlend==0.f,
  "Every saved legacy value and attempted retired slider edit is ignored; menu snapshot stays zero");
  saved=cfg.save();need(ini.GetValue("FSR-RR","NrdBridgeNativeSpecularBlend")==nullptr,
  "Actual production save cleanup deletes the deprecated bridge key including nonzero values");
  need(std::string(ini.GetValue("FSR-RR","Unrelated",""))=="keep"&&
  std::string(ini.GetValue("Other","NrdBridgeNativeSpecularBlend",""))=="untouched",
  "Retired-key cleanup preserves unrelated values and the same spelling in other sections");
  reload.load(saved);need(ReadNrdBridgeRRSettings(reload).nativeSpecularBlend==0.f,
  "Legacy-key save/reload cannot re-enable native-output mixing");
 }
 cfg.load("[fsr-rr]\nnrdbridgenativespecularblend=1\n");saved=cfg.save();
 need(ini.GetValue("FSR-RR","NrdBridgeNativeSpecularBlend")==nullptr,
 "Actual retired-key cleanup also removes case-insensitive saved nonzero values");
 cfg.load("[FSR-RR]\nNrdBridgeNativeSpecularBlend=0.75\n");before=NrdBridge::applyCalls;cfg.ResetFfxDenoiserSettings();
 need(NrdBridge::applyCalls==before+1&&NrdBridge::last.nativeSpecularBlend==0.f&&!NrdBridge::runtime,
 "Full reset after a saved nonzero value emits zero in the coherent API snapshot and disables runtime");
 saved=cfg.save();reload.load(saved);need(ini.GetValue("FSR-RR","NrdBridgeNativeSpecularBlend")==nullptr&&
 ReadNrdBridgeRRSettings(reload).nativeSpecularBlend==0.f&&ReadNrdBridgeRRSettings(reload).nativeMaterialGuides,
 "Reset/save/reload removes the retired key while retaining the user-requested native-albedo default");
 cfg.load("[FSR-RR]\n");ImGui::frame();before=NrdBridge::applyCalls;drawBridge(&cfg);
 need(!ReadNrdBridgeRRSettings(cfg).nativeTemporalMotion&&NrdBridge::applyCalls==before,
 "Native motion defaults OFF and idle controls do not change runtime");
 ImGui::frame();ImGui::bools["Native NRD surface reprojection (experimental)"]=true;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before+1&&NrdBridge::last.nativeTemporalMotion&&NrdBridge::last.overrideMask==0,
 "Native motion publishes one coherent independent accepted runtime setting");
 saved=cfg.save();reload.load(saved);need(ReadNrdBridgeRRSettings(reload).nativeTemporalMotion,
 "Native motion survives production serializer and reload");
 ImGui::frame();drawBridge(&cfg);need(ImGui::hasText("Optional native surface reprojection")&&ImGui::hasText("Native NRD history is not read"),
 "Input map describes copied native formula with owned depth and no native history");
 cfg.ResetFfxDenoiserSettings();need(!ReadNrdBridgeRRSettings(cfg).nativeTemporalMotion&&!NrdBridge::last.nativeTemporalMotion,
 "Full reset disables native motion in Config and applied snapshot");
 cfg.load("[FSR-RR]\nNrdBridgeNativeTemporalMotion=invalid\n");need(!ReadNrdBridgeRRSettings(cfg).nativeTemporalMotion,
 "Malformed native motion setting stays OFF");
 cfg.load("[FSR-RR]\n");ImGui::frame();before=NrdBridge::applyCalls;drawBridge(&cfg);
 need(ReadNrdBridgeRRSettings(cfg).nativeMaterialGuides&&NrdBridge::applyCalls==before,
 "User-requested native albedo guidance defaults ON without idle apply");
 need(!NrdBridge::RRSettings{}.nativeMaterialGuides,"Direct RRSettings API keeps its neutral false default independently of Config policy");
 ImGui::frame();ImGui::bools["Native material albedo guides (experimental)"]=false;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before+1&&!NrdBridge::last.nativeMaterialGuides,
 "Native guides can be explicitly disabled by one coherent snapshot despite the new ON default");
 saved=cfg.save();reload.load(saved);need(!ReadNrdBridgeRRSettings(reload).nativeMaterialGuides,
 "Explicit white-guide preference survives actual save/reload instead of being replaced by the ON default");
 before=NrdBridge::applyCalls;
 ImGui::frame();ImGui::bools["Native material albedo guides (experimental)"]=true;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before+1&&NrdBridge::last.nativeMaterialGuides&&NrdBridge::last.overrideMask==0,
 "Native material guidance is an independent coherent runtime snapshot");
 saved=cfg.save();reload.load(saved);need(ReadNrdBridgeRRSettings(reload).nativeMaterialGuides,
 "Native material guidance survives actual serialization/reload");
 ImGui::frame();drawBridge(&cfg);need(ImGui::hasText("waiting for matching writer/state proof"),"Requested native guides show effective white fallback until proven");
 NrdBridge::guidesActive=true;ImGui::frame();drawBridge(&cfg);need(ImGui::hasText("Proven same-writer guides")&&ImGui::hasText("Unknown source state/material"),
 "Native input map documents actual material model and guarded white fallback");
 cfg.ResetFfxDenoiserSettings();need(ReadNrdBridgeRRSettings(cfg).nativeMaterialGuides&&NrdBridge::last.nativeMaterialGuides,
 "Full reset restores the user-requested native albedo ON default in Config and runtime");
 saved=cfg.save();reload.load(saved);need(ReadNrdBridgeRRSettings(reload).nativeMaterialGuides,
 "Reset/save/reload preserves native albedo ON while the runtime bridge remains OFF after complete reset");
 cfg.load("[FSR-RR]\nNrdBridgeNativeMaterialGuides=invalid\n");need(ReadNrdBridgeRRSettings(cfg).nativeMaterialGuides,
 "Invalid native material key uses the user-requested ON default with guarded white fallback");

 cfg.load("[FSR-RR]\n");NrdBridge::accept=true;ImGui::frame();before=NrdBridge::applyCalls;drawBridge(&cfg);
 const auto recoveryDefaults=ReadNrdBridgeRRSettings(cfg);
 need(!cfg.FfxDenoiserNrdBridgeLobeRecovery.value_or_default()&&!recoveryDefaults.lobeRecovery&&
 recoveryDefaults.recoverySpecular==1.f&&recoveryDefaults.recoveryDiffuse==1.f,
 "Separate lobe recovery defaults OFF with two strength1 values in actual Config and public POD");
 need(ImGui::hasLabel("Separate lobe detail recovery (experimental)")&&
 ImGui::hasLabel("Bridge specular detail strength")&&ImGui::hasLabel("Bridge diffuse detail strength")&&NrdBridge::applyCalls==before,
 "Idle bridge recovery exposes its independent controls without applying a snapshot");
 ImGui::frame();ImGui::floats["Bridge specular detail strength"]=.25f;ImGui::floats["Bridge diffuse detail strength"]=.75f;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before&&cfg.FfxDenoiserNrdBridgeRecoverySpecular.value_or_default()==1.f&&
 cfg.FfxDenoiserNrdBridgeRecoveryDiffuse.value_or_default()==1.f,
 "OFF lobe recovery disables both sliders, preserves preferences and makes no new runtime call");
 cfg.FfxDenoiserRecoverySpecular=false;cfg.FfxDenoiserRecoveryDiffuse=true;
 cfg.FfxDenoiserRecoverySpecularStrength=.125f;cfg.FfxDenoiserRecoveryDiffuseStrength=.875f;
 ImGui::frame();ImGui::hovered=true;ImGui::bools["Separate lobe detail recovery (experimental)"]=true;
 ImGui::floats["Bridge specular detail strength"]=.375f;ImGui::floats["Bridge diffuse detail strength"]=.625f;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before+1&&NrdBridge::last.lobeRecovery&&NrdBridge::last.recoverySpecular==.375f&&
 NrdBridge::last.recoveryDiffuse==.625f&&NrdBridge::last.overrideMask==0,
 "One UI frame publishes recovery enable and both strengths as one coherent snapshot independently of AMD custom tuning");
 need(!cfg.FfxDenoiserRecoverySpecular.value_or_default()&&cfg.FfxDenoiserRecoveryDiffuse.value_or_default()&&
 cfg.FfxDenoiserRecoverySpecularStrength.value_or_default()==.125f&&cfg.FfxDenoiserRecoveryDiffuseStrength.value_or_default()==.875f,
 "Bridge recovery controls leave the ordinary combined-path recovery preferences unchanged");
 need(ImGui::hasText("noise-gated detail")&&ImGui::hasText("temporal warm-up")&&ImGui::hasText("disocclusion rejection")&&
 ImGui::hasText("local anchor")&&ImGui::hasText("All noisy lighting still goes through RR"),
 "Recovery tooltip states gating, temporal rejection and original RR input routing");
 need(ImGui::hasText("Requested lobe recovery: On (specular 0.375, diffuse 0.625)")&&
 ImGui::hasText("do not confirm recovery ran")&&!ImGui::hasText("Active lobe recovery"),
 "Requested-only recovery label does not claim the graph ran on a Consumer");
 need(ImGui::hasText("raw RR before lobe detail recovery")&&!ImGui::hasText("NRD reference blend"),
 "Provider native debug explains the remaining post-RR detail path without advertising retired output mixing");
 saved=cfg.save();reload.load(saved);auto recoveryReload=ReadNrdBridgeRRSettings(reload);
 need(recoveryReload.lobeRecovery&&recoveryReload.recoverySpecular==.375f&&recoveryReload.recoveryDiffuse==.625f,
 "Recovery enable and both strengths survive actual production INI save/reload");
 ImGui::frame();ImGui::buttons["Reset AMD Tuning"]=true;
 need(DrawAmdRRTuning(&cfg)&&cfg.FfxDenoiserNrdBridgeLobeRecovery.value_or_default()&&
 cfg.FfxDenoiserNrdBridgeRecoverySpecular.value_or_default()==.375f&&cfg.FfxDenoiserNrdBridgeRecoveryDiffuse.value_or_default()==.625f,
 "Ordinary AMD tuning reset preserves independent bridge lobe recovery preferences");
 ImGui::frame();ImGui::floats["Bridge specular detail strength"]=0.f;drawBridge(&cfg);
 need(NrdBridge::last.lobeRecovery&&NrdBridge::last.recoverySpecular==0.f&&NrdBridge::last.recoveryDiffuse==.625f,
 "Zero specular strength is preserved in the coherent per-lobe recovery payload");
 ImGui::frame();ImGui::floats["Bridge diffuse detail strength"]=0.f;drawBridge(&cfg);
 need(NrdBridge::last.lobeRecovery&&NrdBridge::last.recoverySpecular==0.f&&NrdBridge::last.recoveryDiffuse==0.f&&
 ImGui::hasText("both zero skip recovery work"),
 "Both zero strengths remain exact requested zeros and the map explains the graph bypass, without a UI-spy GPU-work claim");
 saved=cfg.save();reload.load(saved);recoveryReload=ReadNrdBridgeRRSettings(reload);
 need(recoveryReload.lobeRecovery&&recoveryReload.recoverySpecular==0.f&&recoveryReload.recoveryDiffuse==0.f,
 "Both exact zero strengths survive save/reload without reverting to defaults");
 NrdBridge::accept=false;ImGui::frame();ImGui::bools["Separate lobe detail recovery (experimental)"]=false;drawBridge(&cfg);
 need(!cfg.FfxDenoiserNrdBridgeLobeRecovery.value_or_default()&&NrdBridge::state.requested.lobeRecovery&&
 ImGui::hasText("Settings not applied")&&ImGui::hasText("Requested lobe recovery: On"),
 "Rejected recovery update retains the accepted requested runtime label and reports the error");
 NrdBridge::accept=true;ImGui::frame();drawBridge(&cfg);
 need(ImGui::hasText("Requested separate lobe recovery")&&!ImGui::hasText("Separate lobe detail recovery is requested off"),
 "Recovery input map follows accepted requested state rather than a rejected stored Config edit");
 for(const auto [value,expected]:std::array<std::array<float,2>,7>{{{-5.f,0.f},{2.f,1.f},{.125f,.125f},{0.f,0.f},
 {std::numeric_limits<float>::quiet_NaN(),1.f},{std::numeric_limits<float>::infinity(),1.f},{-std::numeric_limits<float>::infinity(),1.f}}}) {
  cfg.FfxDenoiserNrdBridgeRecoverySpecular=value;cfg.FfxDenoiserNrdBridgeRecoveryDiffuse=value;
  const auto settings=ReadNrdBridgeRRSettings(cfg);
  need(settings.recoverySpecular==expected&&settings.recoveryDiffuse==expected,
  "Actual RR normalization helper clamps finite snapshot inputs and defaults nonfinite strengths to1");
 }
 cfg.load("[FSR-RR]\nNrdBridgeLobeRecovery=true\nNrdBridgeRecoverySpecular=-3\nNrdBridgeRecoveryDiffuse=2\n");
 need(cfg.FfxDenoiserNrdBridgeRecoverySpecular.value_or_default()==0.f&&cfg.FfxDenoiserNrdBridgeRecoveryDiffuse.value_or_default()==1.f,
 "Actual Config load normalizes stored finite strengths before publication");
 saved=cfg.save();reload.load(saved);need(ReadNrdBridgeRRSettings(reload).recoverySpecular==0.f&&
 ReadNrdBridgeRRSettings(reload).recoveryDiffuse==1.f,"Clamped Config values persist normalized across save/reload");
 for(const char* invalid:{"invalid","nan","inf","-inf","1e999","auto"}) {
  cfg.load(std::string("[FSR-RR]\nNrdBridgeRecoverySpecular=")+invalid+"\nNrdBridgeRecoveryDiffuse="+invalid+"\n");
  const auto settings=ReadNrdBridgeRRSettings(cfg);
  need(cfg.FfxDenoiserNrdBridgeRecoverySpecular.value_or_default()==1.f&&
  cfg.FfxDenoiserNrdBridgeRecoveryDiffuse.value_or_default()==1.f&&settings.recoverySpecular==1.f&&settings.recoveryDiffuse==1.f,
  "Malformed/nonfinite Config recovery strengths use default1 without enabling the feature");
 }
 cfg.load("[FSR-RR]\nNrdBridgeLobeRecovery=invalid\n");need(!ReadNrdBridgeRRSettings(cfg).lobeRecovery,
 "Malformed recovery boolean keeps the feature OFF");
 cfg.FfxDenoiserNrdBridgeLobeRecovery=true;cfg.FfxDenoiserNrdBridgeRecoverySpecular=.25f;cfg.FfxDenoiserNrdBridgeRecoveryDiffuse=.5f;
 cfg.ResetFfxDenoiserSettings();recoveryReload=ReadNrdBridgeRRSettings(cfg);
 need(!recoveryReload.lobeRecovery&&recoveryReload.recoverySpecular==1.f&&recoveryReload.recoveryDiffuse==1.f&&
 !NrdBridge::last.lobeRecovery&&NrdBridge::last.recoverySpecular==1.f&&NrdBridge::last.recoveryDiffuse==1.f,
 "Complete production reset restores recovery OFF and both strength1 values in Config and the coherent runtime payload");
 saved=cfg.save();reload.load(saved);recoveryReload=ReadNrdBridgeRRSettings(reload);
 need(!recoveryReload.lobeRecovery&&recoveryReload.recoverySpecular==1.f&&recoveryReload.recoveryDiffuse==1.f,
 "Full reset/save/reload preserves recovery OFF and strength1 defaults");
 ImGui::frame();drawBridge(&cfg);need(ImGui::hasText("Separate lobe detail recovery is requested off")&&
 ImGui::hasText("Ordinary FSR-RR Recovery controls are independent"),
 "Input map distinguishes the new bridge recovery from the ordinary combined-path Recovery settings");

 cfg.load("[FSR-RR]\n");NrdBridge::state.requested={};NrdBridge::state.ready=false;
 NrdBridge::state.lobeRecoveryActive=true;NrdBridge::state.lobeRecoveryFallback=true;
 ImGui::frame();drawBridge(&cfg);
 need(ImGui::hasText("Lobe recovery: Off.")&&!ImGui::hasText("Graph ran and committed")&&!ImGui::hasText("Lobe recovery: Fallback"),
 "Requested OFF takes precedence over stale last-Consumer recovery observations");
 NrdBridge::state.requested.lobeRecovery=true;NrdBridge::state.lobeRecoveryActive=false;NrdBridge::state.lobeRecoveryFallback=false;
 ImGui::frame();drawBridge(&cfg);
 need(ImGui::hasText("Lobe recovery: Requested; waiting for a successful Consumer commit.")&&
 !ImGui::hasText("Graph ran and committed"),"Before first Consumer the UI shows requested/waiting, independently of provider readiness");
 NrdBridge::state.ready=true;ImGui::frame();drawBridge(&cfg);
 need(ImGui::hasText("waiting for a successful Consumer commit.")&&!ImGui::hasText("Graph ran and committed"),
 "Queried provider readiness alone never implies the optional recovery graph ran");
 NrdBridge::state.lobeRecoveryActive=true;ImGui::frame();drawBridge(&cfg);
 need(ImGui::hasText("Graph ran and committed on the last successful Consumer")&&
 ImGui::hasText("Per-pixel gates can still leave pixels unchanged")&&!ImGui::hasText("Lobe recovery: Fallback"),
 "Actual cached graph success is distinguished from a claim that every pixel received correction");
 NrdBridge::state.lobeRecoveryActive=false;NrdBridge::state.lobeRecoveryFallback=true;ImGui::frame();drawBridge(&cfg);
 need(ImGui::hasText("Lobe recovery: Fallback on the last successful Consumer")&&
 ImGui::hasText("RR passed through without lobe recovery")&&!ImGui::hasText("Graph ran and committed"),
 "Actual cached optional-graph fallback is visible and describes retained RR");
 NrdBridge::state.requested.nativeDebugView=0;NrdBridge::state.lobeRecoveryActive=true;ImGui::frame();drawBridge(&cfg);
 need(ImGui::hasText("native AMD DebugView bypasses it and shows raw RR")&&
 !ImGui::hasText("Graph ran and committed")&&!ImGui::hasText("Lobe recovery: Fallback"),
 "Requested native AMD DebugView explicitly bypasses recovery even with an older cached observation");
 NrdBridge::state.requested.nativeDebugView=-1;NrdBridge::state.requested.recoverySpecular=0.f;
 NrdBridge::state.requested.recoveryDiffuse=0.f;ImGui::frame();drawBridge(&cfg);
 need(ImGui::hasText("both strengths are zero, so the graph is skipped")&&
 !ImGui::hasText("Graph ran and committed")&&!ImGui::hasText("Lobe recovery: Fallback"),
 "Both accepted zero strengths show a skipped graph rather than a stale active/fallback observation");
 NrdBridge::state.requested.recoveryDiffuse=.5f;NrdBridge::state.lobeRecoveryFallback=false;
 ImGui::frame();drawBridge(&cfg);need(ImGui::hasText("Graph ran and committed on the last successful Consumer"),
 "A single zero lobe does not hide a successful graph for the remaining nonzero lobe");
 ImGui::frame();ImGui::hovered=true;drawBridge(&cfg);
 need(ImGui::hasText("Adds GPU work and temporary VRAM")&&ImGui::hasText("cost depends on resolution and hardware"),
 "Experimental recovery tooltip explains variable GPU/VRAM cost without a hardware-independent timing claim");

 cfg.load("[FSR-RR]\n");NrdBridge::state.requested.nativeMaterialGuides=true;NrdBridge::guidesActive=false;
 NrdBridge::statusCounters.nativeMaterialAttempts=101;NrdBridge::statusCounters.nativeMaterialSnapshots=59;
 NrdBridge::statusCounters.nativeMaterialFramesApplied=43;NrdBridge::statusCounters.nativeMaterialUnknownState=31;
 NrdBridge::statusCounters.nativeMaterialKnownPSR=17;NrdBridge::statusCounters.nativeMaterialUnsupportedState=19;
 NrdBridge::statusCounters.nativeMaterialCaptureFailures=13;NrdBridge::statusCounters.nativeMaterialModeResets=7;
 ImGui::frame();ImGui::hovered=true;drawBridge(&cfg);
 need(ImGui::hasText("Native albedo: Requested; white fallback until a matching capture is admitted.")&&
 ImGui::hasText("Default on; disabling requests white guides")&&ImGui::hasText("Separate lobe detail recovery stays off by default"),
 "Native-albedo default ON is explained without mistaking a request for admitted native guidance");
 need(ImGui::hasText("Native-guide Recon frames: 43")&&ImGui::hasText("Captured snapshots: 59 / attempts: 101"),
 "Status counter wiring distinguishes successful capture candidates from Recon frames actually supplied native guides");
 need(ImGui::hasText("unknown state: 31; unsupported state: 19; capture failure: 13")&&
 ImGui::hasText("pixel-only read state: 17; availability history resets: 7"),
 "All eight actual public Status counters map to their distinct informational/fallback meanings");
 need(ImGui::hasText("not colored-pixel coverage")&&ImGui::hasText("do not include every rejected attempt")&&
 ImGui::hasText("pixel-only read state is informational"),
 "Capture totals are not misrepresented as exhaustive white/native pixel coverage or PSR failures");
 NrdBridge::guidesActive=true;ImGui::frame();drawBridge(&cfg);
 need(ImGui::hasText("A matching native guide snapshot was admitted for the latest reported Recon")&&
 !ImGui::hasText("Native albedo: Requested; white fallback"),
 "Actual cached material admission is distinguished from pending white fallback");
 NrdBridge::state.requested.nativeMaterialGuides=false;ImGui::frame();drawBridge(&cfg);
 need(ImGui::hasText("Native albedo: Disabled; white guides requested.")&&
 !ImGui::hasText("A matching native guide snapshot was admitted for the latest reported Recon"),
 "Accepted runtime disable takes precedence over stale Config ON or prior material-admission observation");
 {Config malformed;malformed.load("[FSR-RR]\nNrdBridgeSurfaceValidFill=invalid\n");
  need(!ReadNrdBridgeRRSettings(malformed).surfaceValidFill,"Malformed INI-only fill selector stays OFF");}
 cfg.load("[FSR-RR]\nNrdBridgeSurfaceValidFill=true\n");
 need(cfg.FfxDenoiserNrdBridgeSurfaceValidFill.value_or_default()&&ReadNrdBridgeRRSettings(cfg).surfaceValidFill,
 "INI-only D02 fill selector parses through the actual key statements into the rebuilt snapshot");
 ImGui::frame();before=NrdBridge::applyCalls;ImGui::bools["Native NRD surface reprojection (experimental)"]=true;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before+1&&NrdBridge::last.surfaceValidFill,
 "An unrelated menu change re-applies the snapshot without dropping the INI-only fill selector");
 saved=cfg.save();reload.load(saved);
 need(reload.FfxDenoiserNrdBridgeSurfaceValidFill.value_or_default()&&ReadNrdBridgeRRSettings(reload).surfaceValidFill,
 "Fill selector survives the production serializer and reload");
 ImGui::frame();ImGui::bools["Native NRD surface reprojection (experimental)"]=false;drawBridge(&cfg);
 need(NrdBridge::last.surfaceValidFill,"Disabling the unrelated control still forwards the stored fill request");
 ImGui::hovered=false;before=NrdBridge::applyCalls;cfg.ResetFfxDenoiserSettings();
 need(!cfg.FfxDenoiserNrdBridgeSurfaceValidFill.value_or_default()&&!NrdBridge::last.surfaceValidFill,
 "Full reset returns the INI-only fill selector to the documented OFF default");
 saved=cfg.save();reload.load(saved);
 need(!reload.FfxDenoiserNrdBridgeSurfaceValidFill.value_or_default(),"Fill OFF default persists after reset/save/reload");
 NrdBridge::statusCounters.stagingRetainedBytes=524288;NrdBridge::statusCounters.stagingRetainedSlots=4;
 NrdBridge::statusCounters.stagingRetainedPeakBytes=524288;NrdBridge::statusCounters.stagingRetiredTotalBytes=1048576;
 NrdBridge::statusCounters.stagingRejections=1;NrdBridge::statusCounters.recoveryGraphBytes=2097152;
 NrdBridge::statusCounters.recoveryFamilyRetainedPeakBytes=4194304;NrdBridge::statusCounters.recoverySlots=2;
 ImGui::frame();drawBridge(&cfg);
 need(ImGui::hasText("Owned RR memory: staging retained 524288 bytes in 4 slot pair(s) (peak 524288, retired total 1048576, rejected 1)")&&
 ImGui::hasText("lobe recovery graph 2097152 bytes (family peak 4194304 bytes)")&&
 ImGui::hasText("Provider-internal and resident VRAM are unknown, not measured"),
 "P05 live owned-memory counters are consumed from the actual service status snapshot");
 NrdBridge::statusCounters.stagingRetainedBytes=0;NrdBridge::statusCounters.stagingRetainedSlots=0;
 NrdBridge::statusCounters.recoveryGraphBytes=0;NrdBridge::statusCounters.recoverySlots=0;
 ImGui::frame();drawBridge(&cfg);
 need(!ImGui::hasText("Owned RR memory:"),"an idle or disabled bridge publishes no owned-memory line");

 // Reflection-polish controls must run through the actual menu and actual serializers.
 Config::active=&cfg;NrdBridge::startup=true;NrdBridge::accept=true;
 cfg.load("[FSR-RR]\nRecoveryFlatAlbedo=true\nRecoveryFlatTemporal=false\nRecoveryFlatReflectionHistory=true\nRecoveryFlatReflectionPolish=auto\n");
 auto flat=NrdBridge::ReadFlatAlbedoSettings(cfg);
 need(flat.enabled&&!flat.temporal&&flat.reflectionHistory&&flat.reflectionPolish==0.f,
 "Polish auto defaults OFF without changing explicit Temporal false or Reflection history true");
 ImGui::frame();before=NrdBridge::applyCalls;ImGui::floats["Reflection polish##NrdFlat"]=.5f;drawBridge(&cfg);
 need(ImGui::hasLabel("Reflection polish##NrdFlat")&&NrdBridge::applyCalls==before+1&&
 cfg.FfxDenoiserRecoveryFlatReflectionPolish.value_or_default()==.5f&&NrdBridge::last.flatAlbedo.reflectionPolish==.5f,
 "Actual polish slider publishes one coherent half-strength Config/runtime snapshot");
 saved=cfg.save();reload.load(saved);
 need(NrdBridge::ReadFlatAlbedoSettings(reload).reflectionPolish==.5f&&!NrdBridge::ReadFlatAlbedoSettings(reload).temporal,
 "Half-strength polish and explicit Temporal false survive actual save/reload");
 for(float value:{0.f,1.f}) {
  ImGui::frame();before=NrdBridge::applyCalls;ImGui::floats["Reflection polish##NrdFlat"]=value;drawBridge(&cfg);
  need(NrdBridge::applyCalls==before+1&&NrdBridge::last.flatAlbedo.reflectionPolish==value,
  "Both slider endpoints publish exactly; zero remains the v4 escape value");
 }
 for(const auto [value,expected]:std::array<std::array<float,2>,7>{{{-2.f,0.f},{2.f,1.f},{.5f,.5f},{0.f,0.f},
 {std::numeric_limits<float>::quiet_NaN(),0.f},{std::numeric_limits<float>::infinity(),0.f},{-std::numeric_limits<float>::infinity(),0.f}}}) {
  cfg.FfxDenoiserRecoveryFlatReflectionPolish=value;
  need(NrdBridge::ReadFlatAlbedoSettings(cfg).reflectionPolish==expected,"Polish snapshot bounds finite values and fails nonfinite values to OFF");
 }
 for(const char* text:{"invalid","nan","inf","-inf","1e999","auto"}) {
  cfg.load(std::string("[FSR-RR]\nRecoveryFlatReflectionPolish=")+text+"\n");
  need(NrdBridge::ReadFlatAlbedoSettings(cfg).reflectionPolish==0.f,"Malformed/nonfinite INI polish never enables the new GPU path");
 }
 cfg.FfxDenoiserRecoveryFlatReflectionPolish=1.f;cfg.FfxDenoiserRecoveryFlatReflectionHistory=true;
 cfg.ResetFfxDenoiserSettings();
 need(cfg.FfxDenoiserRecoveryFlatReflectionPolish.value_or_default()==0.f&&
 NrdBridge::ReadFlatAlbedoSettings(cfg).reflectionPolish==0.f&&NrdBridge::last.flatAlbedo.reflectionPolish==0.f,
 "Full production reset clears polish in Config and the coherent runtime payload");
 saved=cfg.save();reload.load(saved);need(NrdBridge::ReadFlatAlbedoSettings(reload).reflectionPolish==0.f,
 "Polish OFF reset survives actual save/reload");
 cfg.load("[FSR-RR]\nRadianceScaleExperiment=false\nRadianceScaleDiffuse=16\nRadianceScaleSpecular=256\n");
 ImGui::frame();before=NrdBridge::applyCalls;drawBridge(&cfg);
 need(!ReadNrdBridgeRRSettings(cfg).radianceScale.enabled&&NrdBridge::applyCalls==before,
 "Shared radiance scale stays OFF and idle UI does not reconfigure the provider");
 ImGui::frame();ImGui::bools["Shared RR radiance scale (experimental)"]=true;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before+1&&NrdBridge::last.radianceScale.enabled&&
 NrdBridge::last.radianceScale.diffuse==16&&NrdBridge::last.radianceScale.specular==256,
 "Shared scale checkbox sends the coherent per-lobe candidate");
 ImGui::frame();ImGui::combos["Diffuse input scale##SharedRR"]=0;drawBridge(&cfg);
 need(NrdBridge::last.radianceScale.diffuse==1&&NrdBridge::last.radianceScale.specular==256,
 "Diffuse scale changes only its lobe in the runtime snapshot");
 saved=cfg.save();reload.load(saved);
 need(ReadNrdBridgeRRSettings(reload).radianceScale==ReadNrdBridgeRRSettings(cfg).radianceScale,
 "Shared enabled/scales survive actual INI save and reload");
 for(const char* text:{"3","-1","0","4097","invalid","nan"}) {
  cfg.load(std::string("[FSR-RR]\nRadianceScaleDiffuse=")+text+"\nRadianceScaleSpecular="+text+"\n");
  const auto scales=ReadNrdBridgeRRSettings(cfg).radianceScale;
  need(scales.diffuse==16&&scales.specular==256&&!scales.enabled,
  "Malformed/non-power scales normalize to the disabled default candidate");
 }
 cfg.FfxDenoiserRadianceScaleExperiment=true;cfg.FfxDenoiserRadianceScaleDiffuse=1;
 cfg.ResetFfxDenoiserSettings();
 need(!ReadNrdBridgeRRSettings(cfg).radianceScale.enabled&&!NrdBridge::last.radianceScale.enabled,
 "Full reset clears shared experiment in Config and the bridge runtime");

 // Turn colour filter: default OFF, menu publishes one coherent snapshot, INI round trip, clamps, reset.
 cfg.load("[FSR-RR]\nNrdBridgeTurnColourFilter=auto\nNrdBridgeTurnColourFrames=auto\nNrdBridgeTurnColourDegrees=auto\n");
 NrdBridge::RRSettings turn;NrdBridge::ReadTurnColourSettings(cfg,turn);
 need(!turn.turnColourFilter&&turn.turnColourFrames==30.f&&turn.turnColourDegrees==3.f,"Turn colour auto defaults OFF, 30 frames, 3 degrees");
 ImGui::frame();before=NrdBridge::applyCalls;ImGui::floats["Turn colour fade frames##NrdBridge"]=60.f;drawBridge(&cfg);
 need(ImGui::hasLabel("Turn colour filter##NrdBridge")&&ImGui::hasLabel("Turn colour fade frames##NrdBridge")&&
 NrdBridge::applyCalls==before&&cfg.FfxDenoiserNrdBridgeTurnColourFrames.value_or_default()==30.f,
 "Turn colour sliders are disabled while the filter is OFF");
 ImGui::frame();before=NrdBridge::applyCalls;ImGui::bools["Turn colour filter##NrdBridge"]=true;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before+1&&cfg.FfxDenoiserNrdBridgeTurnColour.value_or_default()&&NrdBridge::last.turnColourFilter&&
 NrdBridge::last.turnColourFrames==30.f&&NrdBridge::last.turnColourDegrees==3.f,"Actual checkbox publishes the filter with default fade");
 ImGui::frame();before=NrdBridge::applyCalls;ImGui::floats["Turn colour fade frames##NrdBridge"]=45.f;
 ImGui::floats["Turn speed threshold (deg/frame)##NrdBridge"]=6.f;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before+1&&NrdBridge::last.turnColourFilter&&NrdBridge::last.turnColourFrames==45.f&&
 NrdBridge::last.turnColourDegrees==6.f,"Both turn sliders publish in one snapshot");
 saved=cfg.save();reload.load(saved);NrdBridge::RRSettings turnReload;NrdBridge::ReadTurnColourSettings(reload,turnReload);
 need(turnReload.turnColourFilter&&turnReload.turnColourFrames==45.f&&turnReload.turnColourDegrees==6.f,"Turn colour survives actual save/reload");
 for(const auto [frames,degrees,expectedFrames,expectedDegrees]:std::array<std::array<float,4>,4>{{{-5.f,0.f,0.f,.1f},{1000.f,500.f,600.f,180.f},
 {std::numeric_limits<float>::quiet_NaN(),std::numeric_limits<float>::infinity(),30.f,3.f},{0.f,3.f,0.f,3.f}}}) {
  cfg.FfxDenoiserNrdBridgeTurnColourFrames=frames;cfg.FfxDenoiserNrdBridgeTurnColourDegrees=degrees;
  NrdBridge::RRSettings bounded;NrdBridge::ReadTurnColourSettings(cfg,bounded);
  need(bounded.turnColourFrames==expectedFrames&&bounded.turnColourDegrees==expectedDegrees,"Turn colour snapshot clamps finite and resets nonfinite values");
 }
 cfg.ResetFfxDenoiserSettings();NrdBridge::RRSettings turnReset;NrdBridge::ReadTurnColourSettings(cfg,turnReset);
 need(!cfg.FfxDenoiserNrdBridgeTurnColour.value_or_default()&&!turnReset.turnColourFilter&&turnReset.turnColourFrames==30.f&&
 !NrdBridge::last.turnColourFilter,"Full production reset turns the filter OFF in Config and runtime payload");

 // Turn brightness correction: default OFF, independent of the colour filter, shares the turn threshold.
 cfg.load("[FSR-RR]\nNrdBridgeTurnBrightness=auto\nNrdBridgeTurnBrightnessAmount=auto\nNrdBridgeTurnBrightnessFrames=auto\n");
 NrdBridge::RRSettings bright;NrdBridge::ReadTurnColourSettings(cfg,bright);
 need(!bright.turnBrightness&&bright.turnBrightnessAmount==.15f&&bright.turnBrightnessFrames==12.f&&!bright.turnColourFilter,
 "Turn brightness auto defaults OFF, 0.15, 12 frames");
 ImGui::frame();before=NrdBridge::applyCalls;ImGui::floats["Turn brightness amount##NrdBridge"]=.3f;
 ImGui::floats["Turn speed threshold (deg/frame)##NrdBridge"]=5.f;drawBridge(&cfg);
 need(ImGui::hasLabel("Turn brightness correction##NrdBridge")&&ImGui::hasLabel("Turn brightness frames##NrdBridge")&&
 NrdBridge::applyCalls==before&&cfg.FfxDenoiserNrdBridgeTurnBrightnessAmount.value_or_default()==.15f&&
 cfg.FfxDenoiserNrdBridgeTurnColourDegrees.value_or_default()==3.f,"Brightness sliders and the shared threshold stay disabled while both are OFF");
 ImGui::frame();before=NrdBridge::applyCalls;ImGui::bools["Turn brightness correction##NrdBridge"]=true;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before+1&&NrdBridge::last.turnBrightness&&!NrdBridge::last.turnColourFilter&&
 NrdBridge::last.turnBrightnessAmount==.15f&&NrdBridge::last.turnBrightnessFrames==12.f,"Brightness checkbox publishes alone");
 ImGui::frame();before=NrdBridge::applyCalls;ImGui::floats["Turn brightness amount##NrdBridge"]=.25f;
 ImGui::floats["Turn brightness frames##NrdBridge"]=20.f;ImGui::floats["Turn speed threshold (deg/frame)##NrdBridge"]=5.f;
 ImGui::floats["Turn colour fade frames##NrdBridge"]=60.f;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before+1&&NrdBridge::last.turnBrightnessAmount==.25f&&NrdBridge::last.turnBrightnessFrames==20.f&&
 NrdBridge::last.turnColourDegrees==5.f&&NrdBridge::last.turnColourFrames==30.f,
 "Brightness sliders and the shared threshold publish; the colour fade stays disabled while the colour filter is OFF");
 saved=cfg.save();reload.load(saved);NrdBridge::RRSettings brightReload;NrdBridge::ReadTurnColourSettings(reload,brightReload);
 need(brightReload.turnBrightness&&brightReload.turnBrightnessAmount==.25f&&brightReload.turnBrightnessFrames==20.f&&
 brightReload.turnColourDegrees==5.f,"Turn brightness survives actual save/reload");
 for(const auto [amount,frames,expectedAmount,expectedFrames]:std::array<std::array<float,4>,4>{{{-1.f,0.f,0.f,1.f},{2.f,500.f,.5f,120.f},
 {std::numeric_limits<float>::quiet_NaN(),std::numeric_limits<float>::infinity(),.15f,12.f},{.2f,8.f,.2f,8.f}}}) {
  cfg.FfxDenoiserNrdBridgeTurnBrightnessAmount=amount;cfg.FfxDenoiserNrdBridgeTurnBrightnessFrames=frames;
  NrdBridge::RRSettings bounded;NrdBridge::ReadTurnColourSettings(cfg,bounded);
  need(bounded.turnBrightnessAmount==expectedAmount&&bounded.turnBrightnessFrames==expectedFrames,
  "Turn brightness snapshot clamps finite and resets nonfinite values");
 }
 cfg.ResetFfxDenoiserSettings();NrdBridge::RRSettings brightReset;NrdBridge::ReadTurnColourSettings(cfg,brightReset);
 need(!cfg.FfxDenoiserNrdBridgeTurnBrightness.value_or_default()&&!brightReset.turnBrightness&&brightReset.turnBrightnessAmount==.15f&&
 !NrdBridge::last.turnBrightness,"Full production reset turns the brightness correction OFF in Config and runtime payload");
 // G3 is independent of adaptive stability and persists through the actual INI path.
 cfg.load("[FSR-RR]\n");
 need(!NrdBridge::ReadLightingValidation(cfg)&&!ReadNrdBridgeRRSettings(cfg).lightingValidation,
 "Lighting validation defaults OFF in both startup-compatible reader and menu snapshot");
 ImGui::frame();before=NrdBridge::applyCalls;ImGui::bools["Lighting-change history validation (experimental)"]=true;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before+1&&NrdBridge::last.lightingValidation&&!NrdBridge::last.motionStability.enabled,
 "Lighting validation checkbox works independently of motion-adaptive stability");
 saved=cfg.save();reload.load(saved);need(NrdBridge::ReadLightingValidation(reload),"Lighting validation survives INI serialization/reload");
 cfg.ResetFfxDenoiserSettings();need(!NrdBridge::last.lightingValidation&&!NrdBridge::ReadLightingValidation(cfg),
 "Full reset disables lighting validation in Config and runtime");
 // G2 actual menu, startup-compatible reader, persistence and fail-closed parameters.
 cfg.load("[FSR-RR]\n");
 auto temporal=NrdBridge::ReadMotionStabilitySettings(cfg);
 need(!temporal.enabled&&temporal.still==.85f&&temporal.moving==.5f&&temporal.ramp==.035f,
 "Motion stability defaults OFF with the calibrated schedule");
 ImGui::frame();before=NrdBridge::applyCalls;ImGui::floats["Still stability##MotionRR"]=.9f;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before&&cfg.FfxDenoiserNrdBridgeStillStability.value_or_default()==.85f,
 "Motion stability parameters are inert while OFF");
 ImGui::frame();ImGui::bools["Motion-adaptive RR stability (experimental)"]=true;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before+1&&NrdBridge::last.motionStability.enabled&&
 NrdBridge::last.motionStability.still==.85f,"Motion checkbox sends a coherent runtime snapshot");
 ImGui::frame();before=NrdBridge::applyCalls;ImGui::floats["Walking threshold (m/frame)##MotionRR"]=.005f;
 ImGui::floats["Still ramp per frame##MotionRR"]=.05f;drawBridge(&cfg);
 need(NrdBridge::applyCalls==before+1&&NrdBridge::last.motionStability.translationMetres==.005f&&
 NrdBridge::last.motionStability.ramp==.05f,"Walking and ramp controls publish together");
 saved=cfg.save();reload.load(saved);
 need(NrdBridge::ReadMotionStabilitySettings(reload)==NrdBridge::last.motionStability,
 "All motion stability settings survive production INI save and reload");
 cfg.FfxDenoiserNrdBridgeStillStability=.1f;
 cfg.FfxDenoiserNrdBridgeMovingStability=std::numeric_limits<float>::quiet_NaN();
 need(NrdBridge::ValidMotionStability(NrdBridge::ReadMotionStabilitySettings(cfg)),
 "Nonfinite moving stability is bounded by the requested still stability");
 cfg.ResetFfxDenoiserSettings();
 need(!NrdBridge::ReadMotionStabilitySettings(cfg).enabled&&!NrdBridge::last.motionStability.enabled,
 "Full reset turns adaptive stability OFF in Config and runtime");
 std::cout<<"PASS: "<<checks<<" actual NRD menu/INI/reset checks\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
'''


def run():
    header=(ROOT/'OptiScaler/Config.h').read_text()
    config=(ROOT/'OptiScaler/Config.cpp').read_text()
    menu=(ROOT/'OptiScaler/menu/menu_common.cpp').read_text()
    rr=(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.h').read_text()
    bridge=(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.h').read_text()
    assert 'struct RRSettings\n' in rr
    contract='\n'.join(function(rr,'struct '+name+'\n')+';' for name in ('FlatAlbedoSettings','RRSettings','RRSettingsState'))
    contract+='\n'+function(rr,'template<class Configuration> inline FlatAlbedoSettings ReadFlatAlbedoSettings(')
    contract+='\n'+function(rr,'template<class Configuration> inline void ReadTurnColourSettings(')
    contract_origin='actual public RR header; actual public Status header'
    contract+='\n'+function(rr,'static inline float NormalizeLobeRecoveryStrength(')
    # D06/D07 recovery tiers/reasons plus the exact production name definitions:
    # the sliced recovery panel calls NrdBridge::LobeRecoveryFallbackReasonName.
    rr_cpp=(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp').read_text()
    contract+='\n'+rr[rr.index('enum class LobeRecoveryTier'):rr.index('// Optional graph budgets')]
    contract+='\n'.join(function(rr_cpp,'const char* '+name+'(') for name in ('LobeRecoveryTierName','LobeRecoveryFallbackReasonName'))
    loads=[];saves=[];resets=[]
    for field,(key,kind) in KEYS.items():
        load=re.findall(r'^\s*'+field+r'\.set_from_config\([^;\n]*read'+kind+r'\("FSR-RR", "'+key+r'"\)[^;\n]*\);',config,re.M)
        save=re.search(r'ini.SetValue\("FSR-RR", "'+key+r'",\s*Get'+kind+r'Value\(Instance\(\)->'+field+r'\.value_for_config\(\)\)\.c_str\(\)\);',config)
        assert len(load)==1 and save,(field,key)
        loads.extend(load);saves.append(save.group());resets.append(field+'.reset();')
    cleanup=re.search(r'ini\.Delete\("FSR-RR", "NrdBridgeNativeSpecularBlend"\);',config)
    assert cleanup and 'FfxDenoiserNrdBridgeNativeSpecularBlend' not in header
    assert 'FfxDenoiserNrdBridgeNativeSpecularBlend' not in menu and 'NormalizeNativeSpecularBlend' not in menu
    saves.append(cleanup.group())
    render=function(menu,'void MenuCommon::RenderDenoiserSettings(')
    marker='if (NrdBridge::StartupEnabled() && ImGui::CollapsingHeader("CP77 NRD bridge"))'
    panel=function(render,marker)
    assert render.index(marker)<render.index('if (choice.fsrRR)')
    assert 'currentFeature' not in panel and 'ffxActive' not in panel and 'choice.fsrRR' not in panel
    template=(ROOT/'OptiScaler.ini').read_text()
    for key in ('NrdBridgeUseCustomRR','NrdBridgeMotionDepthMode','NrdBridgeLegacyMotionDepth','NrdBridgeMaterialIDs','NrdBridgeNativeTemporalMotion','NrdBridgeLobeRecovery'):
        assert len(re.findall(r'^'+key+r'=false\s*$',template,re.M))==1,key
    assert len(re.findall(r'^NrdBridgeNativeMaterialGuides=true\s*$',template,re.M))==1
    assert len(re.findall(r'^NrdBridgeNativeDebugView=-1\s*$',template,re.M))==1
    assert len(re.findall(r'^NrdBridgeNativeDebugViewport=0\s*$',template,re.M))==1
    assert not re.search(r'^NrdBridgeNativeSpecularBlend=',template,re.M)
    # The D02/WP08 fill selector is deliberately INI-usable but not listed in the
    # shipped template; pin that documented INI-only status.
    assert not re.search(r'^NrdBridgeSurfaceValidFill=',template,re.M)
    for key in ('NrdBridgeRecoverySpecular','NrdBridgeRecoveryDiffuse'):
        assert len(re.findall(r'^'+key+r'=1\.0\s*$',template,re.M))==1,key
    ffx=(ROOT/'OptiScaler/include/fsr-rr/ffx_denoiser.h').read_text()
    enum=function(ffx,'typedef enum FfxApiDenoiserDebugViewMode')+' FfxApiDenoiserDebugViewMode;'
    maximum=re.search(r'^#define FFX_API_DENOISER_DEBUG_VIEW_MAX_VIEWPORTS \d+',ffx,re.M).group()
    assert 'FFX_API_DENOISER_DEBUG_VIEW_MODE_OVERVIEW = 0' in enum
    assert 'FFX_API_DENOISER_DEBUG_VIEW_MODE_FULLSCREEN_VIEWPORT = 1' in enum
    replacements=dict(SIMPLEINI=(ROOT/'external/simpleini/SimpleIni.h').as_posix(),
        CUSTOM=header[header.index('enum HasDefaultValue'):header.index('constexpr inline int UnboundKey')],
        RR_CONTRACT=contract,STATUS_CONTRACT=function(bridge,'struct Status\n')+';',CONFIG_FIELDS='\n'.join(re.findall(r'^\s*CustomOptional<[^\n]+>\s+FfxDenoiser\w+[^;\n]*;',header,re.M)),
        FFX_DEBUG_CONTRACT=maximum+'\n'+enum,
        SERIALIZERS='\n'.join(function(config,signature) for signature in ('static inline bool isFloat(', 'static inline bool isInteger(', 'static inline std::optional<float> NormalizeNrdBridgeRecoverySetting(', 'std::string GetBoolValue(', 'std::string GetFloatValue(', 'std::string GetIntValue(std::optional<int> value)')),
        READERS='\n'.join(function(config,'std::optional<'+kind+'> Config::read'+name+'(') for kind,name in (('std::string','String'),('bool','Bool'),('float','Float'),('int','Int'))),
        RESET_KEYS='\n'.join(resets),LOAD_KEYS='\n'.join(loads),SAVE_KEYS='\n'.join(saves),
        RESET_ALL=function(config,'bool Config::ResetFfxDenoiserSettings('),
        MENU_HELPERS='\n'.join(function(menu,signature) for signature in ('static bool DrawSharedRRRadianceScale(', 'static bool DrawNrdBridgeMotionStability(', 'static bool DrawNrdBridgeTurnColour(', 'static bool DrawAmdRRTuning(', 'static bool DrawNrdBridgeNativeDebug(', 'static bool DrawNrdBridgeLobeRecovery(', 'static void DrawNrdBridgeNativeMaterialStatus(', 'static NrdBridge::RRSettings ReadNrdBridgeRRSettings(', 'static void DrawNrdBridgeRRTuning(', 'static void DrawNrdBridgeInputMap(')),BRIDGE_PANEL=panel)
    replacements['SCALE_POLICY']=(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDRadianceScale.h').read_text().replace('#pragma once','')
    replacements['SCALE_POLICY']+='\n'+(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDNrdTemporalControl.h').read_text().replace('#pragma once','')
    cpp=CPP
    for key,value in replacements.items():cpp=cpp.replace('__'+key+'__',value)
    assert not re.search(r'__[A-Z_]+__',cpp)
    out=Path(os.environ['FSRD_GPU_TEST_OUTPUT']);out.mkdir(parents=True,exist_ok=True)
    file,exe=out/'nrd_menu_settings.cpp',out/'nrd_menu_settings.exe';file.write_text(cpp)
    if '--prepare-only' in sys.argv:
        print(json.dumps(dict(prepared=str(file),api_contract=contract_origin,checks=cpp.count('need(')-1,
            scope='source generation only; no native compiler, executable, provider or GPU work'),indent=2))
        return
    compile_cpp(file,exe)
    result=subprocess.run([str(exe)],capture_output=True,text=True)
    (out/'native-output.json').write_text(json.dumps(dict(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr),indent=2)+'\n')
    if result.returncode:raise RuntimeError(result.stderr)
    print(result.stdout,end='')
    checks=int(re.search(r'PASS: (\d+)',result.stdout).group(1))
    (out/'result.json').write_text(json.dumps(dict(native_checks=checks,python_checks=11,api_contract=contract_origin,
        scope='actual menu helpers/panel, complete Config reset and actual INI parsing/serialization; ImGui/runtime are API spies, no provider/GPU/history implementation claim'),indent=2)+'\n')


if __name__=='__main__':run()
