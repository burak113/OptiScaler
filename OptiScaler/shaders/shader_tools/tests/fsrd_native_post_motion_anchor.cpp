// Native route regression: actual RRWrapper RecordOwned/CommitOwned and actual anchor CSOs.
// The provider is the existing fixture's deterministic mock. We measure the actual
// GPU resource handed to that provider, so a disconnected native option cannot pass.
#include <filesystem>
#include <fstream>
#include <json.hpp>
#define main OriginalRRFixtureMain
#include "nrd_bridge_rr_fixture.cpp"
#undef main

struct PhysicalReadback
{
    ComPtr<ID3D12Resource> resource;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    uint32_t width=0,height=0;
    PhysicalReadback(Host& host,ID3D12Resource* image)
    {
        need(image!=nullptr,"physical provider witness is available");
        const auto d=image->GetDesc();width=uint32_t(d.Width);height=d.Height;
        need(d.Format==DXGI_FORMAT_R16G16B16A16_FLOAT,"physical witness retains RGBA16F");
        UINT rows;UINT64 rowBytes,total;
        host.device->GetCopyableFootprints(&d,0,1,0,&footprint,&rows,&rowBytes,&total);
        resource=buffer(host.device.Get(),total,D3D12_HEAP_TYPE_READBACK);
        barrier(host.list.Get(),image,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION source{},target{};
        source.pResource=image;source.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        target.pResource=resource.Get();target.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;target.PlacedFootprint=footprint;
        host.list->CopyTextureRegion(&target,0,0,0,&source,nullptr);
        barrier(host.list.Get(),image,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    }
    std::vector<uint16_t> values()
    {
        uint8_t* data=nullptr;hr(resource->Map(0,nullptr,reinterpret_cast<void**>(&data)));
        std::vector<uint16_t> result(size_t(width)*height*4);
        for(uint32_t y=0;y<height;++y)std::memcpy(result.data()+size_t(y)*width*4,
            data+footprint.Offset+uint64_t(y)*footprint.Footprint.RowPitch,size_t(width)*8);
        resource->Unmap(0,nullptr);return result;
    }
};

static Host* providerBoundaryHost=nullptr;
static std::unique_ptr<PhysicalReadback> providerBoundarySpec,providerBoundaryDiff;
static bool forceNativeOptionOff=false;
static std::vector<uint16_t> jointOffSelectedSpec;
// Invoked by one test-only callback inside the existing mock-provider seam,
// after native scaling and before RR output writes/restoration. All production
// bridge/helper methods and actual shader binaries remain unchanged.
void NativeProviderBoundary(ID3D12GraphicsCommandList* list,ID3D12Resource* spec,ID3D12Resource* diff)
{
    if(!providerBoundaryHost)return;
    need(providerBoundaryHost->list.Get()==list,"provider witness is copied on the exact native recording");
    providerBoundarySpec=std::make_unique<PhysicalReadback>(*providerBoundaryHost,spec);
    providerBoundaryDiff=std::make_unique<PhysicalReadback>(*providerBoundaryHost,diff);
}

static SLConstantsSnapshot nativeCamera(uint32_t token,uint32_t width,uint32_t height,float yawDegrees=0.0f)
{
    auto snapshot=camera(token,width/float(height));
    const float a=yawDegrees*XM_PI/180.f,c=std::cos(a),s=std::sin(a);
    snapshot.constants.cameraRight=sl::float3(c,0,s);
    snapshot.constants.cameraUp=sl::float3(0,1,0);
    snapshot.constants.cameraFwd=sl::float3(s,0,-c);
    return snapshot;
}

static void paintInputs(Host& host,Scene& scene,float factor)
{
    auto* spec=static_cast<ID3D12Resource*>(scene.resources.spec);
    auto* diff=static_cast<ID3D12Resource*>(scene.resources.diff);
    for(auto* r:{spec,diff})barrier(host.list.Get(),r,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    ClearPair(host.list.Get(),spec,diff,{.025f*factor,.025f*factor,.025f*factor,5.f},
        {.125f*factor,.125f*factor,.125f*factor,5.f});
    for(auto* r:{spec,diff})barrier(host.list.Get(),r,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
}
static void paintVerticalGuides(Host& host,Scene& scene)
{
    auto* target=static_cast<ID3D12Resource*>(scene.resources.normals);const auto d=target->GetDesc();
    const uint32_t value=512u|(1023u<<10)|(1u<<30); // world +Y, zero roughness, material1
    std::vector<uint32_t> data(size_t(scene.width)*scene.height,value);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT rows;UINT64 rowBytes,total;
    host.device->GetCopyableFootprints(&d,0,1,0,&fp,&rows,&rowBytes,&total);
    auto upload=buffer(host.device.Get(),total,D3D12_HEAP_TYPE_UPLOAD);
    uint8_t* p=nullptr;hr(upload->Map(0,nullptr,reinterpret_cast<void**>(&p)));
    for(uint32_t y=0;y<scene.height;++y)std::memcpy(p+fp.Offset+uint64_t(y)*fp.Footprint.RowPitch,
        data.data()+size_t(y)*scene.width,size_t(scene.width)*4);
    upload->Unmap(0,nullptr);
    barrier(host.list.Get(),target,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_TEXTURE_COPY_LOCATION src{},dst{};src.pResource=upload.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=fp;
    dst.pResource=target;dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;host.list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
    barrier(host.list.Get(),target,D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    scene.uploads.push_back(upload);
}

static double meanRgb(const std::vector<uint16_t>& words)
{
    double sum=0;for(size_t p=0;p<words.size()/4;++p)for(unsigned c=0;c<3;++c)
        sum+=PackedVector::XMConvertHalfToFloat(words[p*4+c]);
    return sum/double(words.size()/4*3);
}
static void alphaEquals(const std::vector<uint16_t>& words,float value)
{
    const auto half=PackedVector::XMConvertFloatToHalf(value);
    for(size_t p=0;p<words.size()/4;++p)need(words[p*4+3]==half,"every physical-input alpha remains exact");
}

static nlohmann::json runSequence(Host& host,bool enabled,bool shared=false,bool nzr=false)
{
    const auto savedMockSpec=FfxApiProxy::mockSpec,savedMockDiff=FfxApiProxy::mockDiff;
    const auto savedSpecScale=FfxApiProxy::mockSpecularScale,savedDiffScale=FfxApiProxy::mockDiffuseScale;
    if(nzr)
    {
        // Keep mock RR in the physical noisy-input range. A hundred-times
        // brighter mock triggers the legitimate RR-fallback saturation and
        // makes the selected result insensitive to the anchor input.
        FfxApiProxy::mockSpec={.020f,.030f,.040f,5.5f};
        FfxApiProxy::mockDiff={.110f,.120f,.130f,9.5f};
        FfxApiProxy::mockSpecularScale=256.f;FfxApiProxy::mockDiffuseScale=16.f;
    }
    Scene scene(host,64,64,{},true);if(nzr)paintVerticalGuides(host,scene);host.submit();host.reset();
    RRWrapper rr;RRSettings settings;settings.postMotionAnchor=enabled&&!forceNativeOptionOff;
    settings.postMotionAnchorStrength=1.f;
    if(shared){settings.radianceScale={true,16u,256u};settings.motionStability.enabled=true;settings.lightingValidation=true;}
    if(nzr)
    {
        settings.flatAlbedo.enabled=true;settings.flatAlbedo.temporal=false;
        settings.flatAlbedo.reflectionHistory=true;settings.flatAlbedo.rrFallback=true;settings.flatAlbedo.diffuseRR=true;
        settings.flatAlbedo.verticalMode=2;settings.flatAlbedo.verticalStrength=.5f;
    }
    std::string error;need(rr.Configure(settings,error),error.c_str());
    nlohmann::json result={{"enabled",enabled},{"frames",nlohmann::json::array()}};
    bool corrected=false;
    for(unsigned i=0;i<39;++i)
    {
        if(enabled&&i==36)
        {
            const auto before=rr.OwnedAuxiliaryBytes();
            settings.postMotionAnchorStrength=0.f;need(rr.Configure(settings,error),error.c_str());
            need(rr.OwnedAuxiliaryBytes()<before,"strength-zero effective disable releases the completed native anchor graph");
            settings.postMotionAnchorStrength=1.f;need(rr.Configure(settings,error),error.c_str());
        }
        const float yaw=i==32?8.f:0.f;
        const float factor=i>=32?1.2f:1.f;
        const bool reset=i==38;
        paintInputs(host,scene,factor);
        PhysicalReadback titleSpecBefore(host,static_cast<ID3D12Resource*>(scene.resources.spec));
        PhysicalReadback titleDiffBefore(host,static_cast<ID3D12Resource*>(scene.resources.diff));
        FrameParameters frame;need(rr.PrepareFrame(nativeCamera(1000+i,64,64,yaw),reset,frame,error),error.c_str());
        RRRecordedOutputLease output;
        providerBoundaryHost=&host;providerBoundarySpec.reset();providerBoundaryDiff.reset();
        need(rr.RecordOwned(host.list.Get(),scene.resources,frame,output,error),error.c_str());
        providerBoundaryHost=nullptr;
        need(providerBoundarySpec&&providerBoundaryDiff,"mock-provider callback captures actual scaled inputs at dispatch time");
        const auto witness=rr.GetOwnedOutputSnapshot(output);
        need(!witness.postMotionAnchorFallback,witness.postMotionAnchorError.c_str());
        need(witness.providerPhysicalSpec&&witness.providerPhysicalDiff,"trace publishes the actual physical pair");
        if(nzr)need(witness.flatAlbedoActive&&!witness.flatAlbedoFallback,"joint native anchor/NZR route executes the actual recovery graph");
        need(witness.postMotionAnchorGain==(witness.postMotionAnchorActive?output->lease->inputAnchor.gain:nullptr),
            "native trace publishes the exact active-only gain image");
        PhysicalReadback titleSpec(host,static_cast<ID3D12Resource*>(scene.resources.spec));
        PhysicalReadback titleDiff(host,static_cast<ID3D12Resource*>(scene.resources.diff));
        PhysicalReadback physicalSpec(host,witness.providerPhysicalSpec),physicalDiff(host,witness.providerPhysicalDiff);
        PhysicalReadback dispatchedSpec(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastSpecular.signal.input.resource));
        PhysicalReadback dispatchedDiff(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastDiffuse.signal.input.resource));
        Readback rawSpec(host,witness.rawSpec),rawDiff(host,witness.rawDiff);
        Readback selectedSpec(host,witness.selectedSpec),selectedDiff(host,witness.selectedDiff);
        need(rr.CommitOwned(host.list.Get(),output,scene.spec(),scene.diff(),frame,error),error.c_str());
        Readback nativeSpec(host,scene.spec()),nativeDiff(host,scene.diff());
        host.submit();host.checkDebug();host.info->ClearStoredMessages();
        const auto ts=titleSpec.values(),td=titleDiff.values(),ps=physicalSpec.values(),pd=physicalDiff.values();
        const auto restoredSpec=dispatchedSpec.values(),restoredDiff=dispatchedDiff.values();
        const auto ds=providerBoundarySpec->values(),dd=providerBoundaryDiff->values();
        alphaEquals(ts,5.f);alphaEquals(td,5.f);alphaEquals(ps,5.f);alphaEquals(pd,5.f);
        need(static_cast<ID3D12Resource*>(FfxApiProxy::lastSpecular.signal.input.resource)==witness.providerPhysicalSpec&&
            static_cast<ID3D12Resource*>(FfxApiProxy::lastDiffuse.signal.input.resource)==witness.providerPhysicalDiff,
            "actual provider resource identity matches the physical trace witness");
        need(restoredSpec==ps&&restoredDiff==pd,"RecordOwned restores provider resources to exact physical units");
        // The independent callback copies are recorded AT the provider boundary,
        // before RecordOwned restores the inputs. They must contain the published
        // corrected physical pair times the exact existing radiance scales.
        for(size_t p=0;p<ps.size()/4;++p)for(unsigned c=0;c<3;++c)
        {
            need(ds[p*4+c]==PackedVector::XMConvertFloatToHalf(PackedVector::XMConvertHalfToFloat(ps[p*4+c])*witness.providerSpecularRadianceScale),
                "actual provider spec resource consumes the physical trace pair");
            need(dd[p*4+c]==PackedVector::XMConvertFloatToHalf(PackedVector::XMConvertHalfToFloat(pd[p*4+c])*witness.providerDiffuseRadianceScale),
                "actual provider diffuse resource consumes the physical trace pair");
        }
        const auto originalSpec=titleSpecBefore.values(),originalDiff=titleDiffBefore.values();
        need(ts==originalSpec,"native anchor leaves every original specular input word immutable");
        need(td==originalDiff,"native anchor leaves every original diffuse input word immutable");
        if(i==32)std::cout<<"clear_quantization enabled="<<enabled<<" diffuse_actual_half="<<originalDiff[0]
            <<" diffuse_cpu_nearest_half="<<PackedVector::XMConvertFloatToHalf(.125f*factor)
            <<" original_equal_after="<<(td==originalDiff)<<'\n';
        const double ratio=(meanRgb(ps)+meanRgb(pd))/(meanRgb(ts)+meanRgb(td));
        if(!enabled)
        {
            need(ps==ts&&pd==td,"native option OFF is bit-identical at the provider's physical inputs");
            need(!output->lease->inputAnchor.owner,"OFF retains no anchor owner/graph/descriptor resources");
        }
        if(i<32||reset||(enabled&&i>=36))need(ps==ts&&pd==td,"settled/reset/effective-toggle frame never applies an unmeasured correction");
        if(enabled&&i==36)need(!witness.postMotionAnchorActive&&!output->lease->inputAnchor.refresh,
            "zero-to-one strength toggle within one frame clears old ring/arming before any frame gap can hide the regression");
        if(enabled&&i==34)
        {
            need(witness.postMotionAnchorActive,"actual native option activates after the return motion");
            need(witness.providerPhysicalSpec!=scene.resources.spec&&witness.providerPhysicalDiff!=scene.resources.diff,
                "active native route selects owned physical copies");
            need(ratio<.99&&ratio>=.79,"settled pre-motion GPU keyframe produces a bounded actual provider-input correction");
            corrected=true;
        }
        if(reset)need(!witness.postMotionAnchorActive,"explicit reset clears native post-motion arming");
        nativeSpec.consumerRoundtrip(selectedSpec,64,64,false,.75f);
        nativeDiff.consumerRoundtrip(selectedDiff,64,64,false,2.f);
        if(nzr)
        {
            const auto selected=selectedSpec.values(64,64);
            need(selectedDiff.values(64,64)==rawDiff.values(64,64),"user diffuse-RR bypass stays exact while anchor and glass policy run together");
            if(i==34)
            {
                need(selected!=rawSpec.values(64,64),"positive joint control must visibly exercise NZR instead of a raw-RR bypass");
                if(!enabled)jointOffSelectedSpec=selected;
                else need(!jointOffSelectedSpec.empty()&&selected!=jointOffSelectedSpec,
                    "with constant mock RR, changed joint selected RGB proves NZR reads the corrected anchor input");
            }
        }
        result["frames"].push_back({{"i",i},{"active",witness.postMotionAnchorActive},{"ratio",ratio},
            {"auxiliary_bytes",rr.OwnedAuxiliaryBytes()},{"staging_bytes",rr.OwnedStagingBytes()}});
        host.reset();
    }
    need(!enabled||corrected,"ON sequence must demonstrate a real GPU correction reaching the provider");
    // Exercise OFF -> ON and a changed physical extent in the same wrapper.
    settings.postMotionAnchor=false;need(rr.Configure(settings,error),error.c_str());
    settings.postMotionAnchor=true;need(rr.Configure(settings,error),error.c_str());
    Scene resized(host,96,72,{},true);if(nzr)paintVerticalGuides(host,resized);host.submit();host.reset();
    FrameParameters frame;need(rr.PrepareFrame(nativeCamera(1100,96,72),false,frame,error),error.c_str());
    RRRecordedOutputLease output;need(rr.RecordOwned(host.list.Get(),resized.resources,frame,output,error),error.c_str());
    const auto witness=rr.GetOwnedOutputSnapshot(output);
    need(witness.width==96&&witness.height==72&&!witness.postMotionAnchorActive&&!witness.postMotionAnchorFallback,
        "toggle plus DRS creates a fresh native history at the actual extent");
    PhysicalReadback original(host,static_cast<ID3D12Resource*>(resized.resources.diff)),physical(host,witness.providerPhysicalDiff);
    need(rr.CommitOwned(host.list.Get(),output,resized.spec(),resized.diff(),frame,error),error.c_str());
    host.submit();host.checkDebug();host.info->ClearStoredMessages();
    need(original.values()==physical.values(),"DRS/toggle first frame is physically byte-identical");
    host.reset();
    FfxApiProxy::mockSpec=savedMockSpec;FfxApiProxy::mockDiff=savedMockDiff;
    FfxApiProxy::mockSpecularScale=savedSpecScale;FfxApiProxy::mockDiffuseScale=savedDiffScale;
    return result;
}

#ifndef FSRD_NATIVE_ANCHOR_NO_MAIN
int main(int argc,char** argv) try
{
    need(argc==2||argc==3,"output folder and optional force-OFF mutant argument required");
    forceNativeOptionOff=argc==3&&std::string(argv[2])=="--force-native-option-off-mutant";
    const auto out=std::filesystem::path(argv[1]);std::filesystem::create_directories(out);
    Host host;FfxApiProxy::recordPartialWrites=true;
    nlohmann::json result;result["off"]=runSequence(host,false);result["on"]=runSequence(host,true);
    result["d16_g2_g3_off"]=runSequence(host,false,true);result["d16_g2_g3_on"]=runSequence(host,true,true);
    result["joint_nzr_glass_off"]=runSequence(host,false,true,true);result["joint_nzr_glass_on"]=runSequence(host,true,true,true);
    hr(host.list->Close());RecordedComputeLease::Poll();host.checkDebug();
    need(FfxApiProxy::creates==FfxApiProxy::destroys,"native anchor context create/destroy balance");
    result["checks"]=checks;result["scope"]="Actual native option/Prepare/RecordInputs/provider-input binding/physical trace/CommitOwned with mock provider. No real-AMD quality claim.";
    {std::ofstream f(out/"native_anchor_result.json");f<<result.dump(2);}
    std::cout<<"PASS native_post_motion_anchor frames=240 checks="<<checks<<" debug_errors=0 debug_warnings=0\n";
    return 0;
}
catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}
#endif
