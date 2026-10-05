"""Run production SR input preparation and RR handoff code with controlled inputs.

The NGX, D3D12 and dispatch boundaries are substituted. Region resolution, SR
validation, descriptor binding, RR refusal classification and standalone SR
dispatch gating are extracted from the production sources unchanged.
"""
from pathlib import Path
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]


def method(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


PREAMBLE = r'''
#include "FSRInputAlignment.h"
#include "FSRDResultClassification.h"
#include <cassert>
#include <cmath>
#include <iostream>
#include <limits>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
using FSRD::RRResult;
#define LOG_DEBUG(...) ((void)0)
#define LOG_WARN(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
#define LOG_FUNC(...) ((void)0)
constexpr int NVSDK_NGX_Result_Success=0;
constexpr int D3D12_RESOURCE_DIMENSION_TEXTURE2D=2;
constexpr int FFX_UPSCALE_ENABLE_DISPLAY_RESOLUTION_MOTION_VECTORS=1;
constexpr int FFX_API_RESOURCE_STATE_COMPUTE_READ=1;
constexpr int FFX_API_RESOURCE_STATE_UNORDERED_ACCESS=2;
constexpr int FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ=3;
constexpr int FFX_API_DISPATCH_DESC_TYPE_UPSCALE=1;
#define KEY(name) constexpr const char* name=#name
KEY(NVSDK_NGX_Parameter_Color); KEY(NVSDK_NGX_Parameter_Depth);
KEY(NVSDK_NGX_Parameter_MotionVectors); KEY(NVSDK_NGX_Parameter_Output);
KEY(NVSDK_NGX_Parameter_Reset); KEY(NVSDK_NGX_Parameter_MV_Scale_X);
KEY(NVSDK_NGX_Parameter_MV_Scale_Y); KEY(NVSDK_NGX_Parameter_ExposureTexture);
KEY(NVSDK_NGX_Parameter_DLSS_Input_Color_Subrect_Base_X);
KEY(NVSDK_NGX_Parameter_DLSS_Input_Color_Subrect_Base_Y);
KEY(NVSDK_NGX_Parameter_DLSS_Input_Depth_Subrect_Base_X);
KEY(NVSDK_NGX_Parameter_DLSS_Input_Depth_Subrect_Base_Y);
KEY(NVSDK_NGX_Parameter_DLSS_Input_MV_SubrectBase_X);
KEY(NVSDK_NGX_Parameter_DLSS_Input_MV_SubrectBase_Y);
KEY(NVSDK_NGX_Parameter_DLSS_Input_Bias_Current_Color_Mask);
namespace OptiKeys { KEY(FSR_TransparencyAndComp); KEY(FSR_Reactive); }
struct D3D12_RESOURCE_DESC {
    uint64_t Width=0; uint32_t Height=0; int Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    int DepthOrArraySize=1; struct { int Count=1; } SampleDesc;
};
struct ID3D12Resource {
    D3D12_RESOURCE_DESC desc; int format=0;
    ID3D12Resource(uint64_t w, uint32_t h, int f=0) : desc{w,h},format(f) {}
    D3D12_RESOURCE_DESC GetDesc() { return desc; }
};
struct ID3D12GraphicsCommandList {};
struct NVSDK_NGX_Parameter {
    std::map<std::string,ID3D12Resource*> resources;
    std::map<std::string,uint32_t> integers;
    std::map<std::string,float> floats;
    int Get(const char* key,ID3D12Resource** out) const {
        auto it=resources.find(key); if(it==resources.end()) return 1; *out=it->second; return 0;
    }
    int Get(const char* key,uint32_t* out) const {
        auto it=integers.find(key); if(it==integers.end()) return 1; *out=it->second; return 0;
    }
    int Get(const char* key,float* out) const {
        auto it=floats.find(key); if(it==floats.end()) return 1; *out=it->second; return 0;
    }
};
template<class T> bool TryGetNGXVoidPointer(const NVSDK_NGX_Parameter& p,const char* key,T*& out)
{ return p.Get(key,&out)==0 && out!=nullptr; }
template<class T> bool TryGetLoggedResource(const NVSDK_NGX_Parameter& p,const char* key,T*& out)
{ return TryGetNGXVoidPointer(p,key,out); }
struct Config {
    struct Optional { std::optional<bool> value; auto value_for_config_ignore_default() { return value; }
        void set_volatile_value(bool v) { value=v; } } DADepthIsLinear;
    static Config* Instance() { static Config value; return &value; }
};
struct State {
    bool autoExposure=false; std::map<unsigned,bool> changeBackend;
    static State& Instance() { static State value; return value; }
};
unsigned resourceBindings=0;
struct TestResource { void* resource=nullptr; struct { int format=0; } description; int state=0; };
TestResource ffxApiGetResourceDX12(ID3D12Resource* resource,int state)
{ ++resourceBindings; return {resource,{resource?resource->format:0},state}; }
void ffxResolveTypelessFormat(int&) {}
struct ffxDispatchDescUpscale {
    struct { int type=0; } header; ID3D12GraphicsCommandList* commandList=nullptr;
    TestResource color,motionVectors,depth,output,reactive,transparencyAndComposition,exposure;
    FSRInputAlignment::Extent renderSize,upscaleSize;
    struct { float x=1,y=1; } motionVectorScale;
    bool reset=false;
};
struct FSR31FeatureDx12 {
    enum class UpscalerInputMode { OriginalColor,RRComposition,Bypassed };
    struct InputResources { ID3D12Resource* Color=nullptr; ID3D12Resource* MotionVectors=nullptr;
        ID3D12Resource* Depth=nullptr; ID3D12Resource* TransparencyMask=nullptr;
        ID3D12Resource* ReactiveMask=nullptr; ID3D12Resource* DlssBiasMaskFallback=nullptr;
        ID3D12Resource* ExposureMap=nullptr; } _inputBuffers;
    ID3D12Resource* _upscalerOutput=nullptr;
    struct { uint32_t flags=0; } _upscaleCtxDesc;
    bool lowRes=true,autoExposure=true,inited=true,_isInReset=false;
    bool _hasColor=false,_hasDepth=false,_hasMV=false,_hasExposure=false,_hasTM=false;
    bool _accessToReactiveMask=false,_hasOutput=false;
    long _frameCount=0;
    FSRInputAlignment::Extent render{640,360},display{1280,720},output{1280,720};
    unsigned dispatches=0,maskWork=0,barrierWork=0,historyInvalidations=0;
    ffxDispatchDescUpscale lastDispatch;
    bool deviceLost=false;
    struct { unsigned Id=1; } handle;
    auto* Handle() { return &handle; }
    bool LowResMV() { return lowRes; } bool AutoExposure() { return autoExposure; }
    bool IsInited() { return inited; }
    uint32_t DisplayWidth() { return display.width; } uint32_t DisplayHeight() { return display.height; }
    struct VersionInfo { int major=4; };
    VersionInfo Version() { return {}; }
    void ConfigureUpscaler(const NVSDK_NGX_Parameter& p,ffxDispatchDescUpscale& d) {
        d.renderSize=render; d.upscaleSize=output;
        p.Get(NVSDK_NGX_Parameter_MV_Scale_X,&d.motionVectorScale.x);
        p.Get(NVSDK_NGX_Parameter_MV_Scale_Y,&d.motionVectorScale.y);
    }
    void GetReactiveAndTransparencyMasks(ID3D12GraphicsCommandList*,InputResources&) { ++maskWork; }
    bool DispatchUpscaler(ID3D12GraphicsCommandList*,const ffxDispatchDescUpscale& d)
    { ++dispatches; lastDispatch=d; return true; }
    struct ScopedConfigurableBarriers { FSR31FeatureDx12& f;
        ScopedConfigurableBarriers(FSR31FeatureDx12& feature,ID3D12GraphicsCommandList*) : f(feature) { ++f.barrierWork; }
        ~ScopedConfigurableBarriers() { ++f.barrierWork; } };
    void InvalidateDenoiserHistory() { ++historyInvalidations; }
    RRResult ClassifyRayRegenerationFailure(ffxReturnCode_t code,bool dynamic)
    { return FSRD::ClassifyRRApiFailure(code,dynamic,deviceLost); }
    bool PrepareUpscalerInput(ID3D12GraphicsCommandList*,const NVSDK_NGX_Parameter&,ffxDispatchDescUpscale&,
        UpscalerInputMode=UpscalerInputMode::OriginalColor);
    bool SetUpscalerTarget(ID3D12GraphicsCommandList*,const NVSDK_NGX_Parameter&);
    bool EvaluateInternal(ID3D12GraphicsCommandList*,NVSDK_NGX_Parameter*);
    RRResult RRPrepare(ID3D12GraphicsCommandList* InCommandList,const NVSDK_NGX_Parameter& inParams,
                       ffxDispatchDescUpscale& upscalerDesc,bool isUpscaleBypassed,bool isDenoiseBypassed) {
        auto& state=State::Instance();
        RR_PREPARE
        return RRResult::Success;
    }
    struct Converter { ID3D12Resource* composition=nullptr;
        ID3D12Resource* GetCompositionOutput() { return composition; } } converter;
    Converter* FSRDConvShader=&converter;
    RRResult BindComposition(bool isDenoiserReady,ffxDispatchDescUpscale& upscalerDesc,
                             UpscalerInputMode upscalerInputMode=UpscalerInputMode::RRComposition) {
        RR_BIND_COMPOSITION
        return RRResult::Success;
    }
};
unsigned checks=0;
void need(bool condition,const char* label) { ++checks; if(!condition) throw std::runtime_error(label); }
struct Scenario {
    FSR31FeatureDx12 feature; NVSDK_NGX_Parameter params; ID3D12GraphicsCommandList list;
    ID3D12Resource color{704,392,11},depth{704,392,22},motion{704,392,33},output{1280,720,44};
    ID3D12Resource composition{640,360,55},signedLinearDepth{640,360,66};
    Scenario() {
        params.resources={{NVSDK_NGX_Parameter_Color,&color},{NVSDK_NGX_Parameter_Depth,&depth},
            {NVSDK_NGX_Parameter_MotionVectors,&motion},{NVSDK_NGX_Parameter_Output,&output}};
        params.floats={{NVSDK_NGX_Parameter_MV_Scale_X,-2.0f},{NVSDK_NGX_Parameter_MV_Scale_Y,3.0f}};
        feature.converter.composition=&composition;
        State::Instance().changeBackend.clear(); resourceBindings=0;
    }
    void displayMotion() {
        feature.lowRes=false;
        feature._upscaleCtxDesc.flags=FFX_UPSCALE_ENABLE_DISPLAY_RESOLUTION_MOTION_VECTORS;
        motion.desc.Width=1344; motion.desc.Height=752;
    }
};
'''

MAIN = r'''
int main() try {
    using Mode=FSR31FeatureDx12::UpscalerInputMode;
    using namespace FSRInputAlignment;
    for(bool displayMotion : {false,true}) {
        Scenario s; if(displayMotion) s.displayMotion();
        ffxDispatchDescUpscale d;
        need(s.feature.PrepareUpscalerInput(&s.list,s.params,d),"zero-origin SR accepted");
        need(d.depth.resource==&s.depth && d.depth.description.format==22,"game encoded depth preserved");
        need(d.motionVectors.resource==&s.motion && d.motionVectors.description.format==33,"game MV preserved");
        need(d.motionVectorScale.x==-2 && d.motionVectorScale.y==3,"signed MV scale preserved");
        need(s.feature.BindComposition(true,d)==RRResult::Success,"production handoff accepts ready composition");
        need(d.color.resource==&s.composition && d.color.state==FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ,
            "production handoff localizes color with correct state");
        need(d.depth.resource==&s.depth && d.depth.resource!=&s.signedLinearDepth,"RR signed depth never bound to SR");
        need(d.motionVectors.resource==&s.motion && d.motionVectorScale.x==-2 && d.motionVectorScale.y==3,
            "composition binding preserves original MV contract");
        need(s.feature.EvaluateInternal(&s.list,&s.params) && s.feature.dispatches==1,"standalone zero-origin SR dispatches");
    }
    // A source that physically contains its declared offset must never be read at zero by SR.
    for(bool displayMotion : {false,true}) for(bool depthOffset : {false,true}) for(bool yAxis : {false,true}) {
        Scenario s; if(displayMotion) s.displayMotion();
        const char* key=depthOffset ? (yAxis ? NVSDK_NGX_Parameter_DLSS_Input_Depth_Subrect_Base_Y :
            NVSDK_NGX_Parameter_DLSS_Input_Depth_Subrect_Base_X) :
            (yAxis ? NVSDK_NGX_Parameter_DLSS_Input_MV_SubrectBase_Y : NVSDK_NGX_Parameter_DLSS_Input_MV_SubrectBase_X);
        s.params.integers[key]=yAxis?32:64;
        ffxDispatchDescUpscale d;
        need(!s.feature.PrepareUpscalerInput(&s.list,s.params,d,Mode::RRComposition),"RR/SR nonzero guide refused");
        need(resourceBindings==0 && s.feature.maskWork==0,"refusal records no input binding/mask work");
        need(!s.feature.EvaluateInternal(&s.list,&s.params) && s.feature.dispatches==0 && s.feature.barrierWork==0,
            "SR fallback refuses same unsupported guide before barriers/dispatch");
        need(s.feature.RRPrepare(&s.list,s.params,d,false,false)==RRResult::RetryableInputFailure,
            "actual RR preparation refusal classified retryable");
        need(s.feature.historyInvalidations==1,"RR refusal invalidates temporal history");
        s.feature.deviceLost=true;
        need(s.feature.RRPrepare(&s.list,s.params,d,false,false)==RRResult::DeviceLost,"device loss overrides input refusal");
        s.feature.deviceLost=false; State::Instance().changeBackend[1]=true;
        need(s.feature.RRPrepare(&s.list,s.params,d,false,false)==RRResult::NeedsRecreation,"backend recreation retained");
        need(s.feature.RRPrepare(&s.list,s.params,d,true,false)==RRResult::Success,"RR debug bypass retains guide origins");
    }
    for(bool displayMotion : {false,true}) {
        Scenario s; if(displayMotion) s.displayMotion();
        s.motion.desc.Width=displayMotion?1280:640; s.motion.desc.Height=displayMotion?720:360;
        s.params.integers[NVSDK_NGX_Parameter_DLSS_Input_MV_SubrectBase_X]=64;
        s.params.integers[NVSDK_NGX_Parameter_DLSS_Input_MV_SubrectBase_Y]=32;
        auto effective=ResolveMotionRegion({64,32},s.feature.render,s.feature.display,s.feature.lowRes,
            s.motion.desc.Width,s.motion.desc.Height);
        need(effective.correction==MotionCorrection::ZeroOrigin && effective.origin.x==0 && effective.origin.y==0,
            "prelocalized MV override resolves zero origin");
        need(effective.displayResolution==displayMotion,"prelocalized MV retains logical resolution");
        ffxDispatchDescUpscale d;
        need(s.feature.PrepareUpscalerInput(&s.list,s.params,d),"compatible prelocalized MV accepted by SR");
        need(d.motionVectorScale.x==-2 && d.motionVectorScale.y==3,"prelocalized MV preserves game scale");
    }
    {
        Scenario s; s.displayMotion(); s.motion.desc.Width=640; s.motion.desc.Height=360;
        s.params.integers[NVSDK_NGX_Parameter_DLSS_Input_MV_SubrectBase_X]=64;
        auto effective=ResolveMotionRegion({64,0},s.feature.render,s.feature.display,false,640,360);
        need(effective.correction==MotionCorrection::RenderResolution && !effective.displayResolution &&
            effective.extent.width==640 && effective.origin.x==0,"Streamline render-local correction preserved");
        ffxDispatchDescUpscale d;
        need(!s.feature.PrepareUpscalerInput(&s.list,s.params,d),"render-local MV refused with display SR context");
        need(s.feature.RRPrepare(&s.list,s.params,d,false,false)==RRResult::RetryableInputFailure,"resolution refusal retryable");
        need(s.feature.RRPrepare(&s.list,s.params,d,true,false)==RRResult::Success,"SR bypass allows render-local RR guides");
    }
    {
        Scenario s; s.params.integers[NVSDK_NGX_Parameter_DLSS_Input_Color_Subrect_Base_X]=64;
        s.params.integers[NVSDK_NGX_Parameter_DLSS_Input_Color_Subrect_Base_Y]=32;
        ffxDispatchDescUpscale d;
        need(!s.feature.PrepareUpscalerInput(&s.list,s.params,d),"original color offset refused");
        need(!s.feature.EvaluateInternal(&s.list,&s.params) && s.feature.dispatches==0,"SR fallback color offset never dispatches");
        need(s.feature.RRPrepare(&s.list,s.params,d,false,false)==RRResult::Success,"RR composition localizes original color offset");
        need(s.feature.RRPrepare(&s.list,s.params,d,false,true)==RRResult::RetryableInputFailure,"RR raw-color path enforces origin");
        need(s.feature.BindComposition(false,d)==RRResult::RetryableInputFailure && d.color.resource==&s.color,
            "prepared composition contract refuses missing RR result before SR binding");
        need(s.feature.BindComposition(false,d,Mode::OriginalColor)==RRResult::Success && d.color.resource==&s.color,
            "original-color contract retains original binding");
        s.feature.converter.composition=nullptr;
        need(s.feature.BindComposition(true,d)==RRResult::RetryableInputFailure,"missing composition resource refused");
        s.feature.converter.composition=&s.composition;
        need(s.feature.BindComposition(true,d)==RRResult::Success && d.color.resource==&s.composition,
            "composition replaces offset original color");
    }
    for(unsigned invalid=0;invalid!=7;++invalid) {
        Scenario s;
        if(invalid==0) s.depth.desc.Width=639;
        if(invalid==1) s.motion.desc.Height=359;
        if(invalid==2) s.output.desc.Width=1279;
        if(invalid==3) s.feature.output.height=0;
        if(invalid==4) s.color.desc.DepthOrArraySize=2;
        if(invalid==5) s.depth.desc.SampleDesc.Count=2;
        if(invalid==6) s.feature.render.width=0;
        ffxDispatchDescUpscale d;
        need(!s.feature.PrepareUpscalerInput(&s.list,s.params,d),"invalid physical extent or texture shape refused");
        need(resourceBindings==0 && s.feature.maskWork==0,"invalid extent has no GPU recording");
    }
    {
        Scenario s; s.displayMotion(); s.params.resources.erase(NVSDK_NGX_Parameter_Depth);
        s.params.integers[NVSDK_NGX_Parameter_DLSS_Input_Depth_Subrect_Base_X]=64;
        ffxDispatchDescUpscale d;
        need(s.feature.PrepareUpscalerInput(&s.list,s.params,d),"unbound optional display-MV depth origin irrelevant");
        need(d.depth.resource==nullptr,"absent optional depth stays absent");
    }
    need(!CoversRegion(0xffffffffu,0xffffffffu,{0xffffffffu,0xffffffffu},{1,1}),"offset sums never wrap");
    auto stale=ResolveMotionRegion({64,32},{640,360},{1280,720},true,704,392);
    need(stale.origin.x==64 && stale.origin.y==32 && stale.correction==MotionCorrection::None,
        "real atlas origin never erased");
    FSRD::RRRetryPolicy retry;
    retry.Record(RRResult::RetryableInputFailure);
    need(!retry.IsLatched() && retry.CanAttempt(),"unsupported origins remain retryable");
    retry.Record(RRResult::Success); need(retry.Result()==RRResult::Success,"corrected source recovers");
    std::cout<<"SR alignment: "<<checks<<" production helper/preparation/handoff checks passed\n";
    return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
'''


def run():
    sr = (ROOT / "OptiScaler/upscalers/fsr31/FSR31Feature_Dx12.cpp").read_text(encoding="utf-8-sig")
    rr = (ROOT / "OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp").read_text(encoding="utf-8-sig")
    rr_evaluate = method(rr, "RRResult FSRDFeatureDx12::EvaluateRayRegeneration(")
    prepare_start = rr_evaluate.index("const UpscalerInputMode upscalerInputMode")
    prepare_end = rr_evaluate.index("// Optional, configurable resource barriers", prepare_start)
    bind_start = rr_evaluate.index("// Preparation may admit an offset original color", rr_evaluate.index("// Upscaler start."))
    bind_end = rr_evaluate.index("upscalerDesc.reset", bind_start)
    preamble = PREAMBLE.replace("RR_PREPARE", rr_evaluate[prepare_start:prepare_end])
    preamble = preamble.replace("RR_BIND_COMPOSITION", rr_evaluate[bind_start:bind_end])
    methods = "\n\n".join(method(sr, signature) for signature in (
        "bool FSR31FeatureDx12::PrepareUpscalerInput(",
        "bool FSR31FeatureDx12::SetUpscalerTarget(",
        "bool FSR31FeatureDx12::EvaluateInternal(",
    ))
    out = Path(os.environ.get("FSRD_GPU_TEST_OUTPUT", ROOT / "tools_tmp/fsrd_sr_alignment/tests")) / "sr_alignment"
    out.mkdir(parents=True, exist_ok=True)
    source = out / "fsrd_sr_alignment_test.cpp"
    source.write_text(preamble + methods + MAIN, encoding="utf-8")
    exe = source.with_suffix(".exe")
    compile_cpp(source, exe, include_dirs=(ROOT / "OptiScaler/upscalers/fsr31",
        ROOT / "external/FidelityFX-SDK/ffx-api/include/ffx_api"))
    subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    run()
