// Compile and execute the actual production serializer helpers extracted by
// metadata_compile_checks.py. These POD adapters do not simulate D3D12 execution.
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <memory>
#include <string>
#include <vector>
#include "external/nlohmann/json.hpp"
#include "OptiScaler/shaders/fsrd_preprocess/FSRDNrdObservationContract.h"
#include "OptiScaler/shaders/fsrd_preprocess/FSRDNrdSupportContract.h"
using Json = nlohmann::json;
constexpr uint32_t DXGI_FORMAT_R16G16B16A16_FLOAT = 10;
constexpr uint32_t DXGI_FORMAT_R10G10B10A2_UNORM = 24;
constexpr uint32_t DXGI_FORMAT_R32_FLOAT = 41;
constexpr uint32_t DXGI_FORMAT_R8_UINT = 62;
struct ID3D12Resource {};
struct Image
{
    uint32_t sourceWidth=17, sourceHeight=12, width=5, height=3, cropX=3, cropY=2;
    uint32_t format=10, bpp=8, readbackCropX=0, readbackCropY=0;
    struct Placed
    {
        uint64_t Offset=0;
        struct FootprintType { uint32_t Width=5, Height=3, Depth=1, RowPitch=256, Format=10; } Footprint;
    } footprint;
    uint64_t footprintBytes=552, allocationBytes=65536;
};
struct Session
{
    struct Status { std::string captureId="portable-metadata-fixture"; } status;
    uint32_t rw=17, rh=12;
};
#include "production_observation_state.inc"
struct Frame
{
    std::unique_ptr<NativeObservationState> observations;
    std::vector<Image> surveyImages;
    std::vector<std::string> surveyKeys;
    std::array<size_t,14> bridgeRoles {};
};
struct CpuPayload
{
    std::string filename;
    std::vector<uint8_t> bytes;
    int kind=0;
    size_t slot=0;
};
struct CpuFrame { Json row; std::vector<CpuPayload> payloads; };
namespace NrdBridge
{
struct RRRecordedOutputSnapshot
{
    float providerSpecularRadianceScale=256, providerDiffuseRadianceScale=16;
    FSRDNrdObservation::SelectionPath specularSelection=FSRDNrdObservation::SelectionPath::RawRR;
    FSRDNrdObservation::SelectionPath diffuseSelection=FSRDNrdObservation::SelectionPath::RawRR;
};
struct FrameParameters { float depthSign=-1; };
}
namespace FSRDGameTraceBridgeMetadata
{
uint32_t Bits(float value) { uint32_t bits; std::memcpy(&bits,&value,4); return bits; }
}
#include "production_copy_footprint.inc"
#include "production_observation_helpers.inc"

int checks=0, failures=0;
void Check(bool value, const char* message)
{
    ++checks;
    if (!value) { ++failures; std::cerr << "FAIL: " << message << '\n'; }
}
size_t Add(Frame& f, const std::string& name, uint32_t format=10, uint32_t bpp=8)
{
    Image image; image.format=format; image.bpp=bpp; image.footprint.Footprint.Format=format;
    image.footprintBytes=512+5*bpp;
    f.surveyImages.push_back(image); f.surveyKeys.push_back(name); return f.surveyImages.size()-1;
}
Frame Make(bool protectedRoute)
{
    Frame f; f.observations=std::make_unique<NativeObservationState>();
    auto& o=*f.observations; o.stamp={11,500,1,7,1}; o.recordingId=20; o.frameSL=4000; o.actualReset=true;
    Add(f,"native_source_specular"); Add(f,"native_source_diffuse"); o.physicalRoles={0,1,0,1};
    constexpr std::array<const char*,11> names {"input_specular","input_diffuse","input_depth","input_motion",
        "input_normal_roughness","input_specular_albedo","input_diffuse_albedo","raw_rr_specular","raw_rr_diffuse",
        "selected_rr_specular","selected_rr_diffuse"};
    for (size_t i=0;i<names.size();++i)
    {
        if (!protectedRoute && i>=9) { f.bridgeRoles[i]=f.bridgeRoles[i-2]; continue; }
        const uint32_t format=i==2 ? 41u : i==4 ? 24u : i==5 || i==6 ? 28u : 10u;
        f.bridgeRoles[i]=Add(f,names[i],format,format==10 ? 8u : 4u);
    }
    return f;
}
CpuFrame Packet(Frame& f, const Session& s, const NrdBridge::RRRecordedOutputSnapshot& output,
    size_t validity=SIZE_MAX, size_t sums=SIZE_MAX)
{
    CpuFrame packet;
    packet.row["native_observations"]=NativeObservationMetadata(f,s,output,{},SIZE_MAX,SIZE_MAX,validity,sums);
    for (size_t i=0;i<f.surveyImages.size();++i)
    {
        const auto& image=f.surveyImages[i];
        std::vector<uint8_t> bytes(size_t(image.width)*image.height*image.bpp,0);
        // Opaque NaN alpha payload and negative zero survive the equality guard.
        if (image.bpp==8) for (size_t p=0;p<bytes.size();p+=8) { bytes[p+6]=1; bytes[p+7]=0x7e; }
        packet.payloads.push_back({f.surveyKeys[i]+".bin",std::move(bytes),0,i});
    }
    return packet;
}
template<class Callable> void MustThrow(Callable action, const char* message)
{
    bool rejected=false;
    try { action(); } catch (const std::exception&) { rejected=true; }
    Check(rejected,message);
}
int main()
{
    Session s;
    for (const bool protectedRoute : {false,true})
    {
        auto f=Make(protectedRoute); NrdBridge::RRRecordedOutputSnapshot output;
        if (protectedRoute) output.specularSelection=output.diffuseSelection=FSRDNrdObservation::SelectionPath::LobeRecovery;
        auto packet=Packet(f,s,output);
        Check(!packet.row["native_observations"]["authority"]["specular"]["raw_authority_valid"].get<bool>(),"unfrozen authority unavailable");
        CompleteNativeObservationMetadata(f,packet);
        const auto& meta=packet.row["native_observations"];
        Check(meta["capture_id"]==s.status.captureId,"capture identity serialized");
        Check(meta["stamp"]["reset_epoch"]==1 && meta["stamp"]["resource_epoch"]==7,"epochs serialized");
        Check(meta["support"]["valid"]==false && meta["support"]["reason_bits"]==3,"native support stays invalid");
        Check(meta["unknown"]["title_crop_origin"].is_string(),"native origin is explicit unknown");
        for (const char* lobe : {"specular","diffuse"})
        {
            const auto& authority=meta["authority"][lobe];
            Check(authority["equality_guard"]==1,"complete opaque payload equality");
            Check(authority["raw_authority_valid"]==!protectedRoute,"actual selection controls authority");
            Check(authority["raw_edit_eligible"]==false,"support cannot be bypassed by authority");
            const auto& surface=meta["surfaces"][std::string("raw_rr_")+lobe];
            Check(surface["payload_layout"]["row_pitch"]==40 && surface["copy_footprint"]["row_pitch"]==256,"tight vs GPU pitch retained");
            Check(surface["payload_layout"]["bytes"]==120,"tight payload byte count");
            Check(surface["crop_origin"]==Json::array({3,2}),"nonzero crop retained");
            Check(surface["allocation_extent"]==Json::array({17,12}),"source allocation retained");
            Check(surface["scale"]["provider_multiplier"]==(std::string(lobe)=="specular" ? 256 : 16),"actual per-lobe scale retained");
        }
        Check(meta["surfaces"]["anchor_sums"]["availability"]=="missing","inactive carry is missing");
        Check(meta["surfaces"]["depth_validity"]["availability"]=="missing","absent raw validity is missing");
        packet.payloads.clear(); CompleteNativeObservationMetadata(f,packet);
        Check(packet.row["native_observations"]["authority"]["specular"]["raw_authority_valid"]==false,"missing bytes deny authority");
    }
    {
        auto f=Make(false); auto validity=Add(f,"bridge_depth_validity",62,1); auto sums=Add(f,"post_motion_anchor_sums",0,1);
        auto& image=f.surveyImages[sums]; image.width=image.sourceWidth=32; image.height=image.sourceHeight=1;
        image.cropX=image.cropY=0; image.footprint.Footprint={32,1,1,32,0}; image.footprintBytes=32;
        auto packet=Packet(f,s,{},validity,sums); const auto& surfaces=packet.row["native_observations"]["surfaces"];
        Check(surfaces["depth_validity"]["encoding"]==8,"R8 original classification encoded");
        Check(surfaces["anchor_sums"]["encoding"]==5 && surfaces["anchor_sums"]["captured_extent"]==Json::array({8,1}),"eight original carry words");
        Check(surfaces["anchor_sums"]["payload_layout"]["bytes"]==32,"carry byte length");
    }
    {
        auto f=Make(false); NrdBridge::RRRecordedOutputSnapshot output;
        output.providerDiffuseRadianceScale=3;
        MustThrow([&] { Packet(f,s,output); },"non-power-of-two scale rejected");
        output.providerDiffuseRadianceScale=16;
        f.surveyImages[f.bridgeRoles[7]].format=24;
        MustThrow([&] { Packet(f,s,output); },"role/format mismatch rejected");
        f.surveyImages[f.bridgeRoles[7]].format=10;
        f.surveyImages[0].cropX=14;
        MustThrow([&] { Packet(f,s,output); },"invalid origin rejected");
    }
    std::cout << "checks=" << checks << " failures=" << failures << '\n';
    return failures ? 1 : 0;
}
