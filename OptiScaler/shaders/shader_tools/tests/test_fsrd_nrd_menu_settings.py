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
    'FfxDenoiserNrdBridgeUseCustomRR': ('NrdBridgeUseCustomRR', 'Bool'),
    'FfxDenoiserNrdBridgeMotionDepthMode': ('NrdBridgeMotionDepthMode', 'Bool'),
    'FfxDenoiserNrdBridgeMaterialIDs': ('NrdBridgeMaterialIDs', 'Bool'),
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
__FFX_DEBUG_CONTRACT__
namespace FSRDSignals {constexpr int Auto=0;}
namespace NrdBridge {
__RR_CONTRACT__
bool startup=false,runtime=true,camera=false,accept=true;unsigned applyCalls=0,resetCalls=0,statusCalls=0;
RRSettings last{};bool lastCamera=false;RRSettingsState state;
enum class DebugMode {Off,RawSignals,RRInputs};DebugMode conversionDebug=DebugMode::Off;
struct Status {std::string phase="Active",reason="test",resources;};
bool StartupEnabled(){return startup;}bool RuntimeEnabled(){return runtime;}
void SetRuntimeEnabled(bool value){runtime=value;}
Status GetStatus(){++statusCalls;return {};}
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
bool Checkbox(const char* name,bool* value){labels.push_back(name);auto it=bools.find(name);
 if(isDisabled()||it==bools.end())return false;bool next=it->second;bools.erase(it);bool changed=*value!=next;*value=next;return changed;}
bool SliderFloat(const char* name,float* value,float minimum,float maximum){labels.push_back(name);auto it=floats.find(name);
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
void drawBridge(Config* config){__BRIDGE_PANEL__}
int main(){try{
 Config cfg;Config::active=&cfg;cfg.load("[FSR-RR]\nUnrelated=keep\n[Other]\nNrdBridgeUseCustomRR=untouched\n");
 need(!cfg.FfxDenoiserNrdBridgeUseCustomRR.value_or_default()&&!cfg.FfxDenoiserNrdBridgeMotionDepthMode.value_or_default(),"Both new experiments default OFF");
 need(ReadNrdBridgeRRSettings(cfg).overrideMask==0,"Missing options preserve AMD baseline rather than fork slider defaults");
 NrdBridge::startup=false;ImGui::frame();drawBridge(&cfg);
 need(!NrdBridge::statusCalls&&!NrdBridge::applyCalls&&ImGui::labels.empty(),"Startup OFF never enters bridge panel or applies settings");
 NrdBridge::startup=true;ImGui::frame();ImGui::headers["CP77 NRD bridge"]=false;drawBridge(&cfg);
 need(!NrdBridge::statusCalls&&!NrdBridge::applyCalls,"Closed bridge panel does no runtime settings work");
 ImGui::frame();drawBridge(&cfg);
 need(ImGui::hasLabel("Use custom RR tuning##NrdBridge")&&ImGui::hasLabel("Camera-projected depth delta (experimental)"),"Startup-selected bridge exposes controls without any upscaler owner");
 need(!NrdBridge::applyCalls&&!ImGui::rrTables&&ImGui::hasText("not available yet"),"Idle controls do not apply/query provider defaults or invent effective numbers");
 for(const char* term:{"Specular lighting","Diffuse lighting","Hit distance","Normal + roughness","Linear VIEWZ","Motion + jitter","Albedo guides","Consumer output encoding","Unused title inputs"})
 need(ImGui::hasText(term),"Every supported/unused input has a human-readable row");
 need(ImGui::hasText("303")&&ImGui::hasText("1212")&&ImGui::hasText("factor 64")&&ImGui::hasText("previous-frame depth"),"Map explains exact Consumer encoding and baseline motion depth");
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
 need(NrdBridge::lastCamera&&NrdBridge::camera&&ImGui::hasText("predicts previous-camera depth"),"Motion experiment and input map use accepted runtime mode");
 saved=cfg.save();reload.load(saved);need(reload.FfxDenoiserNrdBridgeMotionDepthMode.value_or_default(),"Motion experiment survives save/reload");
 NrdBridge::state.ready=true;NrdBridge::state.defaults={.8f,.8f,40000,8,.6f,.1f,0,100};NrdBridge::state.effective=desired;
 ImGui::frame();drawBridge(&cfg);need(ImGui::rrTables==1&&ImGui::hasText("0.25")&&ImGui::hasText("0.8")&&ImGui::hasText("30000"),"Effective and queried baseline numbers appear only when ready");
 NrdBridge::accept=false;const bool priorCamera=NrdBridge::camera;
 ImGui::frame();ImGui::bools["Camera-projected depth delta (experimental)"]=false;drawBridge(&cfg);
 need(ImGui::hasText("Settings not applied")&&NrdBridge::camera==priorCamera,"Rejected snapshot reports failure and leaves effective runtime mode unchanged");
 NrdBridge::accept=true;ImGui::frame();ImGui::buttons["Reset AMD Tuning"]=true;drawBridge(&cfg);
 need(!cfg.FfxDenoiserNrdBridgeUseCustomRR.value_or_default()&&NrdBridge::last.overrideMask==0&&!ImGui::hasText("Settings not applied"),"Bridge AMD reset returns to baseline and clears apply error");
 cfg.FfxDenoiserNrdBridgeMotionDepthMode=true;cfg.FfxDenoiserNrdBridgeUseCustomRR=true;NrdBridge::camera=true;NrdBridge::runtime=true;
 unsigned before=NrdBridge::applyCalls;cfg.ResetFfxDenoiserSettings();
 need(!NrdBridge::runtime&&!cfg.FfxDenoiserNrdBridgeEnabled.value_or_default(),"Full reset turns runtime bridge OFF immediately");
 need(NrdBridge::applyCalls==before+1&&!NrdBridge::last.overrideMask&&!NrdBridge::lastCamera&&!NrdBridge::camera,"Actual full reset clears the coherent RR/motion snapshot");
 need(!cfg.FfxDenoiserNrdBridgeUseCustomRR.value_or_default()&&!cfg.FfxDenoiserNrdBridgeMotionDepthMode.value_or_default(),"Full reset restores both new OFF defaults");
 saved=cfg.save();reload.load(saved);need(!reload.FfxDenoiserNrdBridgeMotionDepthMode.value_or_default()&&!reload.FfxDenoiserNrdBridgeUseCustomRR.value_or_default()&&!reload.FfxDenoiserNrdBridgeEnabled.value_or_default(),"Full reset persists safe OFF state across reload");
 NrdBridge::startup=false;before=NrdBridge::applyCalls;cfg.ResetFfxDenoiserSettings();need(NrdBridge::applyCalls==before,"Full reset with startup OFF makes no new snapshot apply call");
 cfg.load("[FSR-RR]\nNrdBridgeUseCustomRR=invalid\nNrdBridgeMotionDepthMode=auto\n");
 need(!cfg.FfxDenoiserNrdBridgeMotionDepthMode.value_or_default()&&!cfg.FfxDenoiserNrdBridgeUseCustomRR.value_or_default(),"Invalid/missing new booleans remain OFF");
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
 std::cout<<"PASS: "<<checks<<" actual NRD menu/INI/reset checks\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
'''


def run():
    header=(ROOT/'OptiScaler/Config.h').read_text()
    config=(ROOT/'OptiScaler/Config.cpp').read_text()
    menu=(ROOT/'OptiScaler/menu/menu_common.cpp').read_text()
    rr=(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.h').read_text()
    if 'struct RRSettings\n' in rr:
        contract='\n'.join(function(rr,'struct '+name+'\n')+';' for name in ('RRSettings','RRSettingsState'))
        contract_origin='actual public RR header'
    else:
        # Approved public POD is an explicit runtime-spy boundary until lead merges
        # its new header. No provider configuration/history algorithm is reproduced.
        contract='struct RRSettings {uint32_t overrideMask=0;std::array<float,8> values{};int32_t nativeDebugView=-1;uint32_t nativeDebugViewport=0;bool preserveNativeMaterialIDs=false;};\nstruct RRSettingsState {bool ready=false;RRSettings requested{};std::array<float,8> defaults{},effective{};};'
        contract_origin='explicit approved API spy POD; integrated replay reads actual header'
    loads=[];saves=[];resets=[]
    for field,(key,kind) in KEYS.items():
        load=re.findall(r'^\s*'+field+r'\.set_from_config\(read'+kind+r'\("FSR-RR", "'+key+r'"\)\);',config,re.M)
        save=re.search(r'ini.SetValue\("FSR-RR", "'+key+r'",\s*Get'+kind+r'Value\(Instance\(\)->'+field+r'\.value_for_config\(\)\)\.c_str\(\)\);',config)
        assert len(load)==1 and save,(field,key)
        loads.extend(load);saves.append(save.group());resets.append(field+'.reset();')
    render=function(menu,'void MenuCommon::RenderDenoiserSettings(')
    marker='if (NrdBridge::StartupEnabled() && ImGui::CollapsingHeader("CP77 NRD bridge"))'
    panel=function(render,marker)
    assert render.index(marker)<render.index('if (choice.fsrRR)')
    assert 'currentFeature' not in panel and 'ffxActive' not in panel and 'choice.fsrRR' not in panel
    template=(ROOT/'OptiScaler.ini').read_text()
    for key in ('NrdBridgeUseCustomRR','NrdBridgeMotionDepthMode','NrdBridgeMaterialIDs'):
        assert len(re.findall(r'^'+key+r'=false\s*$',template,re.M))==1,key
    assert len(re.findall(r'^NrdBridgeNativeDebugView=-1\s*$',template,re.M))==1
    assert len(re.findall(r'^NrdBridgeNativeDebugViewport=0\s*$',template,re.M))==1
    ffx=(ROOT/'OptiScaler/include/fsr-rr/ffx_denoiser.h').read_text()
    enum=function(ffx,'typedef enum FfxApiDenoiserDebugViewMode')+' FfxApiDenoiserDebugViewMode;'
    maximum=re.search(r'^#define FFX_API_DENOISER_DEBUG_VIEW_MAX_VIEWPORTS \d+',ffx,re.M).group()
    assert 'FFX_API_DENOISER_DEBUG_VIEW_MODE_OVERVIEW = 0' in enum
    assert 'FFX_API_DENOISER_DEBUG_VIEW_MODE_FULLSCREEN_VIEWPORT = 1' in enum
    replacements=dict(SIMPLEINI=(ROOT/'external/simpleini/SimpleIni.h').as_posix(),
        CUSTOM=header[header.index('enum HasDefaultValue'):header.index('constexpr inline int UnboundKey')],
        RR_CONTRACT=contract,CONFIG_FIELDS='\n'.join(re.findall(r'^\s*CustomOptional<[^\n]+>\s+FfxDenoiser\w+[^;\n]*;',header,re.M)),
        FFX_DEBUG_CONTRACT=maximum+'\n'+enum,
        SERIALIZERS='\n'.join(function(config,signature) for signature in ('static inline bool isFloat(', 'static inline bool isInteger(', 'std::string GetBoolValue(', 'std::string GetFloatValue(', 'std::string GetIntValue(std::optional<int> value)')),
        READERS='\n'.join(function(config,'std::optional<'+kind+'> Config::read'+name+'(') for kind,name in (('std::string','String'),('bool','Bool'),('float','Float'),('int','Int'))),
        RESET_KEYS='\n'.join(resets),LOAD_KEYS='\n'.join(loads),SAVE_KEYS='\n'.join(saves),
        RESET_ALL=function(config,'bool Config::ResetFfxDenoiserSettings('),
        MENU_HELPERS='\n'.join(function(menu,signature) for signature in ('static bool DrawAmdRRTuning(', 'static bool DrawNrdBridgeNativeDebug(', 'static NrdBridge::RRSettings ReadNrdBridgeRRSettings(', 'static void DrawNrdBridgeRRTuning(', 'static void DrawNrdBridgeInputMap(')),BRIDGE_PANEL=panel)
    cpp=CPP
    for key,value in replacements.items():cpp=cpp.replace('__'+key+'__',value)
    assert not re.search(r'__[A-Z_]+__',cpp)
    out=Path(os.environ['FSRD_GPU_TEST_OUTPUT']);out.mkdir(parents=True,exist_ok=True)
    file,exe=out/'nrd_menu_settings.cpp',out/'nrd_menu_settings.exe';file.write_text(cpp)
    compile_cpp(file,exe)
    result=subprocess.run([str(exe)],capture_output=True,text=True)
    (out/'native-output.json').write_text(json.dumps(dict(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr),indent=2)+'\n')
    if result.returncode:raise RuntimeError(result.stderr)
    print(result.stdout,end='')
    checks=int(re.search(r'PASS: (\d+)',result.stdout).group(1))
    (out/'result.json').write_text(json.dumps(dict(native_checks=checks,python_checks=10,api_contract=contract_origin,
        scope='actual menu helpers/panel, complete Config reset and actual INI parsing/serialization; ImGui/runtime are API spies, no provider/GPU/history implementation claim'),indent=2)+'\n')


if __name__=='__main__':run()
