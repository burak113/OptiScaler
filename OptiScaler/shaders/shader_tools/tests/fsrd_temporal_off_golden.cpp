// Deterministic production RR-wrapper replay: the provider writes known lighting,
// while every real input transform, lifetime path and output commit runs on D3D12.
#define main PreservedGoldenFixtureMain
#include "nrd_bridge_rr_fixture.cpp"
#undef main

namespace {
Host* goldenHost=nullptr;
std::filesystem::path goldenOutput;
std::string goldenFrame;
struct GoldenRead
{
    ComPtr<ID3D12Resource> memory;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {};
    UINT height=0;UINT64 rowBytes=0;
    std::string name;
    GoldenRead(ID3D12Resource* source,D3D12_RESOURCE_STATES state,std::string label):name(std::move(label))
    {
        auto& host=*goldenHost;const auto desc=source->GetDesc();UINT rows;UINT64 total;
        height=desc.Height;host.device->GetCopyableFootprints(&desc,0,1,0,&footprint,&rows,&rowBytes,&total);
        memory=buffer(host.device.Get(),total,D3D12_HEAP_TYPE_READBACK);
        barrier(host.list.Get(),source,state,D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION a {},b {};a.pResource=source;a.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        b.pResource=memory.Get();b.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;b.PlacedFootprint=footprint;
        host.list->CopyTextureRegion(&b,0,0,0,&a,nullptr);
        barrier(host.list.Get(),source,D3D12_RESOURCE_STATE_COPY_SOURCE,state);
    }
    void Write()
    {
        std::ofstream file(goldenOutput/(goldenFrame+"_"+name+".bin"),std::ios::binary);
        uint8_t* p=nullptr;hr(memory->Map(0,nullptr,reinterpret_cast<void**>(&p)));
        for(UINT y=0;y<height;y++)file.write(reinterpret_cast<char*>(p+footprint.Offset+y*footprint.Footprint.RowPitch),rowBytes);
        memory->Unmap(0,nullptr);need(bool(file),"golden readback writes every unpadded row");
    }
};
std::vector<std::unique_ptr<GoldenRead>> goldenReads;
}
void GoldenSnapshot(const ffxDispatchDescDenoiser& d,const ffxDispatchDescDenoiserDirectDiffuse& diffuse,
                    const ffxDispatchDescDenoiserIndirectSpecular& specular)
{
    unsigned i=0;for(void* p:{specular.signal.input.resource,diffuse.signal.input.resource,d.linearDepth.resource,
                            d.motionVectors.resource,d.normals.resource,d.specularAlbedo.resource,d.diffuseAlbedo.resource})
        goldenReads.push_back(std::make_unique<GoldenRead>(static_cast<ID3D12Resource*>(p),
            D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,"rr_input"+std::to_string(i++)));
    std::ofstream controls(goldenOutput/(goldenFrame+"_controls.bin"),std::ios::binary);
    controls.write(reinterpret_cast<const char*>(&d)+offsetof(ffxDispatchDescDenoiser,motionVectorScale),
                   sizeof(d)-offsetof(ffxDispatchDescDenoiser,motionVectorScale));
    const UINT origins[]={diffuse.signal.checkerboardOrigin,specular.signal.checkerboardOrigin};
    controls.write(reinterpret_cast<const char*>(origins),sizeof(origins));need(bool(controls),"golden actual controls serialize");
}
int main(int argc,char** argv)try
{
    need(argc==3,"frozen captured input directory and golden result directory required");
    goldenOutput=argv[2];std::filesystem::create_directories(goldenOutput);Host host;goldenHost=&host;
    FfxApiProxy::recordPartialWrites=true;
    for(unsigned profile=0;profile<4;profile++)
    {
        Scene scene(host,128,128,argv[1]);host.submit();host.reset();RRWrapper wrapper;FrameParameters frame;std::string error;
        RRSettings settings;settings.radianceScale.enabled=bool(profile&1);settings.radianceScale.diffuse=16;
        settings.radianceScale.specular=256;settings.turnColourFilter=bool(profile&2);settings.turnBrightness=bool(profile&2);
        FfxApiProxy::mockDiffuseScale=settings.radianceScale.enabled?16.f:256.f;
        for(unsigned i=0;i<6;i++)
        {
            goldenFrame="p"+std::to_string(profile)+"_f"+std::to_string(i);
            need(wrapper.Configure(settings,error),error.c_str());auto snapshot=camera(100+i,1.f);
            if(i>=1){const float angle=.4f;snapshot.constants.cameraFwd=sl::float3(std::sin(angle),0,-std::cos(angle));
                snapshot.constants.cameraRight=sl::float3(std::cos(angle),0,std::sin(angle));snapshot.constants.cameraPos.x=.02f;}
            need(wrapper.PrepareFrame(snapshot,false,frame,error),error.c_str());
            need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
            goldenReads.push_back(std::make_unique<GoldenRead>(scene.spec(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,"title_spec"));
            goldenReads.push_back(std::make_unique<GoldenRead>(scene.diff(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,"title_diff"));
            goldenReads.push_back(std::make_unique<GoldenRead>(scene.resources.spec,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,"restored_spec"));
            goldenReads.push_back(std::make_unique<GoldenRead>(scene.resources.diff,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,"restored_diff"));
            const auto state=wrapper.GetSettingsState();
            std::ofstream trace(goldenOutput/(goldenFrame+"_trace.txt"));
            trace<<FfxApiProxy::creates<<' '<<FfxApiProxy::configures<<' '<<FfxApiProxy::dispatches<<' '
                 <<wrapper.OwnedStagingBytes()<<' '<<wrapper.OwnedAuxiliaryBytes()<<' '<<wrapper.ContextGeneration()<<'\n';
            for(float v:state.effective)trace<<std::hexfloat<<v<<' ';trace<<'\n';
            host.submit();host.reset();for(auto& r:goldenReads)r->Write();goldenReads.clear();
        }
    }
    goldenHost=nullptr;host.checkDebug();need(FfxApiProxy::creates==4&&FfxApiProxy::dispatches==24,"exactly four unchanged contexts and 24 deterministic provider dispatches");
    std::cout<<"PASS temporal OFF golden checks="<<checks<<" profiles=4 frames=24 provider=deterministic no_quality_claim=1\n";return 0;
}
catch(const std::exception& e){std::cerr<<"FAIL temporal OFF golden: "<<e.what()<<'\n';return 1;}
