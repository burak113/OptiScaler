// NEW test-only copy of sealed world-motion body SHA ba873fd2505b05b4a4dd11b9068d60907b3461da3a5830a18385089fe25624c3.
#include "fsrd_nrd_rr_specular_route_adapter.h"
// New independent research harness. Existing complete RR regression main and
// assertions stay untouched and must still be scheduled separately.
#define main NrdExistingRRRegressionMain
#include "nrd_bridge_rr_fixture.cpp"
#undef main
#include <json.hpp>
#include <iomanip>
#include "../../../misc/NrdBridgeNativeBirth_Dx12.h"
// Honest wrapper-only application adapter. Native birth is not configured here;
// invoking coverage would be an unexpected unsupported path, never success.
static unsigned unexpectedNativeCoverage=0;
bool NrdBridgeNativeBirth::ObserveReleaseCoverage(IUnknown*) noexcept {++unexpectedNativeCoverage;return false;}

namespace WorldMotionQuality
{
using J=nlohmann::json;
struct Pose
{
    uint32_t frame=0,index=0,unused=0;
    bool reset=false;
    std::array<float,16> view{},projection{};
    std::array<float,3> position{};
    std::array<float,2> jitter{};
};
std::string prefix(uint32_t frame)
{ std::ostringstream out;out<<"frame"<<std::setw(3)<<std::setfill('0')<<frame;return out.str(); }
SLConstantsSnapshot snapshot(const Pose& pose,uint32_t width,uint32_t height)
{
    auto value=camera(pose.frame,float(width)/height,.05f);
    auto& c=value.constants;
    for(unsigned row=0;row<4;++row)c.cameraViewToClip[row]={pose.projection[row],pose.projection[4+row],pose.projection[8+row],pose.projection[12+row]};
    c.cameraRight={pose.view[0],pose.view[1],pose.view[2]};
    c.cameraUp={pose.view[4],pose.view[5],pose.view[6]};
    c.cameraFwd={-pose.view[8],-pose.view[9],-pose.view[10]};
    c.cameraPos={pose.position[0],pose.position[1],pose.position[2]};
    c.cameraFOV=2.f*std::atan(1.f/pose.projection[5]);
    c.cameraNear=.05f;c.cameraFar=0;c.mvecScale={1,1};
    c.jitterOffset={pose.jitter[0],pose.jitter[1]};c.motionVectorsJittered=sl::Boolean::eFalse;
    c.reset=pose.reset?sl::Boolean::eTrue:sl::Boolean::eFalse;
    return value;
}
std::vector<uint8_t> read(const std::filesystem::path& path)
{
    std::ifstream file(path,std::ios::binary|std::ios::ate);need(bool(file),"world replay sealed input exists");
    const auto length=file.tellg();need(length>=0&&length<=2*1024*1024,"world replay input byte size bounded");
    std::vector<uint8_t> result(static_cast<size_t>(length));file.seekg(0);file.read(reinterpret_cast<char*>(result.data()),result.size());
    need(file.gcount()==result.size(),"world replay reads every input byte");return result;
}
struct Capture
{
    ComPtr<ID3D12Resource> bufferResource;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    uint32_t width=0,height=0,bpp=0;
    Capture(Host& host,ID3D12Resource* source,D3D12_RESOURCE_STATES state,unsigned bytesPerPixel)
    {
        const auto desc=source->GetDesc();width=uint32_t(desc.Width);height=desc.Height;bpp=bytesPerPixel;
        UINT64 total=0;host.device->GetCopyableFootprints(&desc,0,1,0,&footprint,nullptr,nullptr,&total);
        bufferResource=buffer(host.device.Get(),total,D3D12_HEAP_TYPE_READBACK);
        barrier(host.list.Get(),source,state,D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION from{},to{};from.pResource=source;from.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        to.pResource=bufferResource.Get();to.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;to.PlacedFootprint=footprint;
        host.list->CopyTextureRegion(&to,0,0,0,&from,nullptr);
        barrier(host.list.Get(),source,D3D12_RESOURCE_STATE_COPY_SOURCE,state);
    }
    std::vector<uint8_t> bytes()
    {
        uint8_t* data=nullptr;hr(bufferResource->Map(0,nullptr,reinterpret_cast<void**>(&data)));
        std::vector<uint8_t> result(size_t(width)*height*bpp);
        for(uint32_t y=0;y<height;++y)std::memcpy(result.data()+size_t(y)*width*bpp,
            data+footprint.Offset+size_t(y)*footprint.Footprint.RowPitch,size_t(width)*bpp);
        bufferResource->Unmap(0,nullptr);return result;
    }
    void exact(const std::filesystem::path& path){need(bytes()==read(path),"every current actual GPU input/guide byte equals its sealed CPU payload");}
    void save(const std::filesystem::path& path){const auto data=bytes();std::ofstream file(path,std::ios::binary);file.write(reinterpret_cast<const char*>(data.data()),data.size());need(bool(file),"world replay readback evidence write");}
};
std::array<uint32_t,8> words(const std::array<float,8>& value)
{std::array<uint32_t,8> result{};std::memcpy(result.data(),value.data(),sizeof(result));return result;}
int run(int argc,char** argv)
{
    std::cout.setf(std::ios::unitbuf);
    need(argc==6,"world replay expects input view, output, route, settings file or DEFAULT, count limit or ALL");
    const std::filesystem::path inputs=argv[1],output=argv[2];
    const std::string route=argv[3];need(route=="dd"||route=="id","world replay diffuse route explicit");
    std::filesystem::create_directories(output);
    std::ifstream text(inputs/"native-replay.txt");need(bool(text),"sealed native camera table exists");
    unsigned count=0,width=0,height=0;text>>count>>width>>height;
    need(count>=56&&count<=96&&width==128&&height==128,"bounded continuous world-surface sequence128x128");
    std::vector<Pose> poses(count);
    for(auto& p:poses){unsigned reset=0;text>>p.frame>>p.index>>p.unused>>reset;p.reset=reset!=0;for(auto& v:p.view)text>>v;for(auto& v:p.projection)text>>v;for(auto& v:p.position)text>>v;for(auto& v:p.jitter)text>>v;need(bool(text),"complete native world-pose camera record");}
    const bool probe=std::string(argv[4])=="DEFAULT";
    const unsigned frames=std::string(argv[5])=="ALL"?count:unsigned(std::stoul(argv[5]));
    need(frames>=1&&frames<=count&&(!probe||frames==1),"default probe has one disposable sample, measured histories are bounded");
    RRSettings settings;
    if(!probe){settings.overrideMask=0x7fu;std::ifstream values(argv[4]);for(auto& v:settings.values)values>>v;need(bool(values),"shared exact effective settings snapshot exists");}
    loadReal();SpecularRouteResearch::Install();need(FfxApiProxy::real,"world replay loads actual signed AMD exports");
    FfxApiProxy::useIndirectDiffuseResearch=route=="id";
    Host host;need(!NrdBridgeNativeBirth::Ready(),"standalone wrapper adapter explicitly has unconfigured native retirement");auto wrapper=std::make_unique<RRWrapper>();std::string error;
    need(wrapper->Configure(settings,error),error.c_str());
    ComPtr<ID3D12QueryHeap> queries;D3D12_QUERY_HEAP_DESC query{};query.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;query.Count=2;
    hr(host.device->CreateQueryHeap(&query,IID_PPV_ARGS(&queries)));auto timing=buffer(host.device.Get(),16,D3D12_HEAP_TYPE_READBACK);
    UINT64 frequency=0;hr(host.queue->GetTimestampFrequency(&frequency));need(frequency>0,"world replay native timestamp frequency");
    RRSettingsState initial{};uint64_t staging=0,auxiliary=0;J rows=J::array();
    for(unsigned index=0;index<frames;++index)
    {
        const auto& p=poses[index];need(p.frame==index+2&&p.index==index&&p.reset==(index==0),"consecutive submitted camera samples with first-only reset");
        const auto folder=inputs/prefix(p.frame),destination=output/prefix(p.frame);std::filesystem::create_directories(destination);
        Scene scene(host,width,height,folder);
        ConsumerBuffer constants(host);constants.flag(0);
        NativeTableConsumer consumer(host,scene.spec(),scene.diff(),width,height);consumer.Overwrite(host.device.Get(),constants.constants().address);
        FrameParameters frame;need(wrapper->PrepareFrame(snapshot(p,width,height),p.reset,frame,error),error.c_str());frame.outputConstants=constants.constants();
        need(frame.frameIndex==index&&frame.reset==(index==0)&&frame.previousValid==(index!=0),"wrapper history commits each previous sample without hidden resets");
        XMFLOAT4X4 view,projection;XMStoreFloat4x4(&view,frame.camera.view);XMStoreFloat4x4(&projection,frame.camera.projection);
        for(unsigned i=0;i<16;++i){need(std::abs(reinterpret_cast<float*>(&view)[i]-p.view[i])<=2e-6f,"actual wrapper view equals independently sealed world camera");need(std::abs(reinterpret_cast<float*>(&projection)[i]-p.projection[i])<=2e-6f,"actual wrapper projection equals sealed world pinhole");}
        host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
        need(wrapper->Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
        host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
        consumer.Record(host);
        const auto expectedSignals=(route=="id"?FFX_DENOISER_SIGNAL_INDIRECT_DIFFUSE:FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE)|FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR;
        need(FfxApiProxy::lastCreate.signalFlags==expectedSignals&&expectedSignals==(route=="id"?0x30u:0x22u),"exact DD0x22 or researchID0x30 create signal mask");
        need(FfxApiProxy::lastDiffuse.header.type==(route=="id"?FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE:FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE)&&FfxApiProxy::lastSpecular.header.type==FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR&&!FfxApiProxy::lastSpecular.header.pNext,"actual SDK ordered diffuse then IS descriptor chain");
        need(FfxApiProxy::lastDiffuse.signal.input.resource==scene.resources.diff&&FfxApiProxy::lastSpecular.signal.input.resource==scene.resources.spec,"all noisy lighting reaches signed RR without bypass");
        const std::array<void*,5> guides{scene.resources.linearDepth,scene.resources.motion,scene.resources.normals,scene.resources.specAlbedo,scene.resources.diffAlbedo};
        const std::array<const FfxApiResource*,5> descriptors{&FfxApiProxy::lastDispatch.linearDepth,&FfxApiProxy::lastDispatch.motionVectors,&FfxApiProxy::lastDispatch.normals,&FfxApiProxy::lastDispatch.specularAlbedo,&FfxApiProxy::lastDispatch.diffuseAlbedo};
        for(unsigned i=0;i<5;++i)need(descriptors[i]->resource==guides[i]&&descriptors[i]->state==FFX_API_RESOURCE_STATE_COMPUTE_READ,"current five exact SDK guide bindings are COMPUTE_READ");
        need(FfxApiProxy::lastDiffuse.signal.input.state==FFX_API_RESOURCE_STATE_COMPUTE_READ&&FfxApiProxy::lastSpecular.signal.input.state==FFX_API_RESOURCE_STATE_COMPUTE_READ,"actual noisy signals are COMPUTE_READ");
        need(FfxApiProxy::lastDiffuse.signal.output.state==FFX_API_RESOURCE_STATE_UNORDERED_ACCESS&&FfxApiProxy::lastSpecular.signal.output.state==FFX_API_RESOURCE_STATE_UNORDERED_ACCESS&&FfxApiProxy::lastDiffuse.signal.output.resource!=scene.diff()&&FfxApiProxy::lastSpecular.signal.output.resource!=scene.spec(),"signed provider writes owned UAV staging");
        need(scene.spec()->AddRef()==2&&scene.spec()->Release()==1&&scene.diff()->AddRef()==2&&scene.diff()->Release()==1,"wrapper never persistently AddRefs borrowed title output pair");
        need(FfxApiProxy::lastDispatch.motionVectorScale.x==1&&FfxApiProxy::lastDispatch.motionVectorScale.y==1&&FfxApiProxy::lastDispatch.motionVectorScale.z==1,"all oracle motion axes use unit SDK scales");
        need(bool(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)==(index==0),"signed provider receives first-only reset");
        need(wrapper->ContextGeneration()==1&&FfxApiProxy::creates==1&&FfxApiProxy::dispatches==index+1,"one physical signed provider context and one RR dispatch per frame");
        const auto current=wrapper->GetSettingsState();need(current.ready,"actual provider settings ready");
        if(index==0){initial=current;staging=wrapper->OwnedStagingBytes();auxiliary=wrapper->OwnedAuxiliaryBytes();}
        need(words(current.effective)==words(initial.effective),"whole history uses one coherent effective settings snapshot");
        if(!probe)need(words(current.effective)==words(settings.values),"every candidate uses exact common effective provider settings");
        need(wrapper->OwnedStagingBytes()==staging&&wrapper->OwnedAuxiliaryBytes()==auxiliary,"no steady-state owned pool growth");
        std::array<std::unique_ptr<Capture>,7> inputCaptures;
        for(unsigned i=0;i<7;++i)inputCaptures[i]=std::make_unique<Capture>(host,scene.textures[i].Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,i<2||i==3?8:4);
        Readback outSpec(host,scene.spec()),outDiff(host,scene.diff());
        Readback stageSpec(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastSpecular.signal.output.resource)),stageDiff(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastDiffuse.signal.output.resource));
        Readback consumerSpec(host,consumer.spec.Get()),consumerDiff(host,consumer.diff.Get());
        host.list->ResolveQueryData(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,timing.Get(),0);
        const bool last=index+1==frames;
        if(last)
        {
            ComPtr<ID3D12Fence> gate;hr(host.device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&gate)));
            struct Drain {Host& host;ID3D12Fence* fence;bool active=true;~Drain(){if(active){fence->Signal(1);try{host.finish();}catch(...){std::cerr<<"cleanup drain failed after original error\n";}}}} drain{host,gate.Get()};
            hr(host.queue->Wait(gate.Get(),1));wrapper.reset();need(FfxApiProxy::destroys==0,"last recorded lease retains SDK context after wrapper destruction before Execute");
            host.submit(false);auto record=RecordedComputeLease::Capture(host.list.Get());need(bool(record),"actual final recording has retained leases");RecordedComputeLease::Detach(record);record.reset();RecordedComputeLease::Poll();need(FfxApiProxy::destroys==0,"uncompleted gated native submission retains SDK context after Reset-like detach");
            hr(gate->Signal(1));host.finish();drain.active=false;need(FfxApiProxy::destroys==1&&FfxApiProxy::live.empty(),"real context destroyed exactly once after native completion");
        }
        else host.submit();
        // Save completed outputs before any diagnostic assertion can terminate.
        outSpec.verify(destination/"spec.bin",width,height);outDiff.verify(destination/"diff.bin",width,height);
        inputCaptures[3]->save(destination/"motion.bin");
        const std::array<const char*,7> names{"spec","diff","depth","motion","normals","spec_albedo","diff_albedo"};
        for(unsigned i=0;i<7;++i)inputCaptures[i]->exact(folder/(std::string(names[i])+".bin"));
        outSpec.consumerRoundtrip(stageSpec,width,height,false,.75f);outDiff.consumerRoundtrip(stageDiff,width,height,false,2.f);
        consumerSpec.consumerGpuRoundtrip(outSpec,stageSpec,width,height,false);consumerDiff.consumerGpuRoundtrip(outDiff,stageDiff,width,height,false);need(consumer.Flag()==0,"actual Consumer reads exact native RGB flag0");
        host.checkDebug();UINT64* ticks=nullptr;hr(timing->Map(0,nullptr,reinterpret_cast<void**>(&ticks)));need(ticks[1]>=ticks[0],"native RR interval timestamps ordered");const double gpuMs=double(ticks[1]-ticks[0])*1000./frequency;timing->Unmap(0,nullptr);
        rows.push_back({{"frame",p.frame},{"reset",index==0},{"current_gpu_guides_exact",true},{"gpu_rr_commit_ms",gpuMs}});host.reset();
    }
    hr(host.list->Close());host.checkDebug();need(FfxApiProxy::creates==1&&FfxApiProxy::destroys==1&&FfxApiProxy::dispatches==frames,"fresh history balanced actual create/dispatch/destroy counts");
    need(FfxApiProxy::nativeDebugDispatches==0&&!FfxApiProxy::badCreateChains&&!FfxApiProxy::badConfigureLayouts&&!FfxApiProxy::badDefaults,"no hidden debug path or SDK descriptor/default-layout failure");
    need(!unexpectedNativeCoverage,"unconfigured native Release adapter is never mistaken for supported coverage");
    J result={{"schema","fsrd-world-motion-native-replay-v1"},{"route",route},{"probe",probe},{"checks",checks},{"frames",rows},{"creates",1},{"destroys",1},{"dispatches",frames},{"debug_errors",0},{"debug_warnings",0},{"default_words",words(initial.defaults)},{"effective_words",words(initial.effective)},{"owned_staging_bytes",staging},{"owned_auxiliary_bytes",auxiliary},{"provider_version_id",FfxApiProxy::lastOverride},{"signal_flags",FfxApiProxy::lastCreate.signalFlags},{"diffuse_descriptor_type",FfxApiProxy::lastDiffuse.header.type},{"specular_descriptor_type",FfxApiProxy::lastSpecular.header.type},{"native_birth_ready",NrdBridgeNativeBirth::Ready()},{"scope","real signed AMD + production RRWrapper/commit + actual Consumer and fresh GPU guides; preconverted independent world oracle; hook/proxy adapters; no production coordinator/native-Z conversion/game-NRD quality claim"}};
    SpecularRouteResearch::Check(SpecularRouteResearch::creates==1 && SpecularRouteResearch::dispatches==frames,"actual provider route adapter observes every create/dispatch");
    result["research"]={{"specular_route",SpecularRouteResearch::direct?"ds":"is"},{"actual_provider_signal_flags",SpecularRouteResearch::actualSignals},{"actual_provider_specular_type",SpecularRouteResearch::actualSpecularType},{"actual_provider_creates",SpecularRouteResearch::creates},{"actual_provider_dispatches",SpecularRouteResearch::dispatches},{"adapter_checks",SpecularRouteResearch::checks},{"original_body_sha256","ba873fd2505b05b4a4dd11b9068d60907b3461da3a5830a18385089fe25624c3"},{"semantic_scope","same physical indirect GGX radiance intentionally routed asDS for model isolation; no production parity claim"}};
    std::ofstream(output/"native-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS world_motion checks="<<checks<<" frames="<<frames<<'\n';return 0;
}
}
int main(int argc,char** argv) try{SpecularRouteResearch::Check(argc==7,"specular route replay adds explicit final is|ds argument");const std::string route=argv[6];SpecularRouteResearch::Check(route=="is"||route=="ds","explicit provider specular route");SpecularRouteResearch::direct=route=="ds";return WorldMotionQuality::run(argc-1,argv);}
catch(const std::exception& error){std::cerr<<"world motion replay failure: "<<error.what()<<'\n';return 1;}
