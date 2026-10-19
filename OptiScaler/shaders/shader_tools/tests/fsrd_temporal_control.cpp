#define main PreservedRRFixtureMain
#include "nrd_bridge_rr_fixture.cpp"
#undef main
#include <iomanip>
#include <chrono>

struct FSRDLightingGuardTestAccess
{
    static const void* Generation(const FSRDNrdLightingGuardDx12::Lease& w){return w?w->state.get():nullptr;}
    static ID3D12Resource* Change(const FSRDNrdLightingGuardDx12::Lease& w){return w->state->change.Get();}
    static std::array<ID3D12Resource*,3> History(const FSRDNrdLightingGuardDx12::Lease& w,uint32_t frame)
    {return {w->state->meanVar[frame&1].Get(),w->state->fast[frame&1].Get(),w->state->tile[frame&1].Get()};}
    static std::array<ID3D12Resource*,3> Stats(const FSRDNrdLightingGuardDx12& g,uint32_t frame)
    {
        if(!g.state_)return {};
        return {g.state_->meanVar[frame&1].Get(),g.state_->fast[frame&1].Get(),g.state_->tile[frame&1].Get()};
    }
};
struct GuardReadback
{
    ComPtr<ID3D12Resource> memory;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {};
    uint32_t width=0,height=0,bpp=0;
    GuardReadback(Host& host,ID3D12Resource* source)
    {
        auto desc=source->GetDesc();width=uint32_t(desc.Width);height=desc.Height;
        bpp=desc.Format==DXGI_FORMAT_R32G32B32A32_FLOAT?16:desc.Format==DXGI_FORMAT_R32_UINT?4:8;
        UINT rows;UINT64 bytes,total;host.device->GetCopyableFootprints(&desc,0,1,0,&footprint,&rows,&bytes,&total);
        memory=buffer(host.device.Get(),total,D3D12_HEAP_TYPE_READBACK);
        barrier(host.list.Get(),source,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION a {},b {};a.pResource=source;a.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        b.pResource=memory.Get();b.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;b.PlacedFootprint=footprint;
        host.list->CopyTextureRegion(&b,0,0,0,&a,nullptr);
        barrier(host.list.Get(),source,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    }
    void Write(std::ofstream& out)
    {
        uint8_t* data;hr(memory->Map(0,nullptr,reinterpret_cast<void**>(&data)));
        for(uint32_t y=0;y<height;y++)out.write(reinterpret_cast<char*>(data+footprint.Offset+y*footprint.Footprint.RowPitch),size_t(width)*bpp);
        memory->Unmap(0,nullptr);need(bool(out),"complete guard readback stream");
    }
};
ComPtr<ID3D12Resource> UploadGuard(Host& host,ID3D12Resource* resource,std::ifstream& input)
{
    auto desc=resource->GetDesc();uint32_t w=uint32_t(desc.Width),h=desc.Height;
    unsigned bpp=desc.Format==DXGI_FORMAT_R32_FLOAT?4:8;std::vector<uint8_t> data(size_t(w)*h*bpp);
    input.read(reinterpret_cast<char*>(data.data()),data.size());need(input.gcount()==data.size(),"complete published input frame");
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {};UINT rows;UINT64 bytes,total;
    host.device->GetCopyableFootprints(&desc,0,1,0,&footprint,&rows,&bytes,&total);
    auto upload=buffer(host.device.Get(),total,D3D12_HEAP_TYPE_UPLOAD);uint8_t* mapped;hr(upload->Map(0,nullptr,reinterpret_cast<void**>(&mapped)));
    for(uint32_t y=0;y<h;y++)std::memcpy(mapped+footprint.Offset+y*footprint.Footprint.RowPitch,data.data()+size_t(y)*w*bpp,size_t(w)*bpp);
    upload->Unmap(0,nullptr);
    barrier(host.list.Get(),resource,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_TEXTURE_COPY_LOCATION a {},b {};a.pResource=resource;a.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    b.pResource=upload.Get();b.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;b.PlacedFootprint=footprint;
    host.list->CopyTextureRegion(&a,0,0,0,&b,nullptr);
    barrier(host.list.Get(),resource,D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    return upload;
}
double Quantile(std::vector<double> x,double q){std::sort(x.begin(),x.end());return x[size_t(q*(x.size()-1))];}
void GuardTiming(Host& host,uint32_t width,uint32_t height,const std::filesystem::path& files={})
{
    Scene scene(host,width,height,files);host.submit();host.reset();FSRDNrdLightingGuardDx12 guard;
    D3D12_QUERY_HEAP_DESC query {};query.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;query.Count=96;
    ComPtr<ID3D12QueryHeap> heap;hr(host.device->CreateQueryHeap(&query,IID_PPV_ARGS(&heap)));
    auto readback=buffer(host.device.Get(),96*sizeof(uint64_t),D3D12_HEAP_TYPE_READBACK);
    uint64_t frequency;hr(host.queue->GetTimestampFrequency(&frequency));std::vector<double> cpu,productionCpu,gpu,statsGpu,applyGpu;uint32_t timingFrame=0;
    for(uint32_t batch=0;batch<13;batch++)
    {
        std::vector<FSRDNrdLightingGuardDx12::Lease> leases;std::array<double,16> durations {};
        for(uint32_t k=0;k<16;k++)
        {
            FSRDNrdLightingGuardDx12::Lease work;std::string error;
            host.list->EndQuery(heap.Get(),D3D12_QUERY_TYPE_TIMESTAMP,6*k);
            auto start=std::chrono::steady_clock::now();
            need(guard.Before(host.device.Get(),host.list.Get(),width,height,timingFrame++,scene.resources.diff,scene.resources.spec,
                scene.resources.motion,scene.resources.linearDepth,work,error,.1f,.6703613f,65504.f,heap.Get(),6*k+1),error.c_str());
            durations[k]=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-start).count();
            host.list->EndQuery(heap.Get(),D3D12_QUERY_TYPE_TIMESTAMP,6*k+5);leases.push_back(std::move(work));
        }
        host.list->ResolveQueryData(heap.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,96,readback.Get(),0);host.submit();host.reset();
        uint64_t* values;hr(readback->Map(0,nullptr,reinterpret_cast<void**>(&values)));
        if(batch>=4)for(uint32_t k=0;k<16;k++){cpu.push_back(durations[k]);gpu.push_back(double(values[6*k+5]-values[6*k])*1e6/frequency);
            statsGpu.push_back(double(values[6*k+2]-values[6*k+1])*1e6/frequency);
            applyGpu.push_back(double(values[6*k+4]-values[6*k+3])*1e6/frequency);}
        readback->Unmap(0,nullptr);leases.clear();
        // Separate production path: no timestamp calls in Before, same warm images and 16 retained slots.
        for(uint32_t k=0;k<16;k++)
        {
            FSRDNrdLightingGuardDx12::Lease work;std::string error;auto start=std::chrono::steady_clock::now();
            need(guard.Before(host.device.Get(),host.list.Get(),width,height,timingFrame++,scene.resources.diff,scene.resources.spec,
                scene.resources.motion,scene.resources.linearDepth,work,error,.1f,.6703613f,65504.f),error.c_str());
            const double us=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-start).count();
            if(batch>=4)productionCpu.push_back(us);leases.push_back(std::move(work));
        }
        host.submit();host.reset();
    }
    std::cout<<"lighting_guard_timing width="<<width<<" height="<<height<<" samples="<<gpu.size()<<" batches=9 repeats=16 warm_batches=4"
        <<" cpu_us_p50="<<Quantile(productionCpu,.5)<<" cpu_us_p90="<<Quantile(productionCpu,.9)
        <<" marker_cpu_us_p50="<<Quantile(cpu,.5)<<" marker_cpu_us_p90="<<Quantile(cpu,.9)<<" gpu_us_p50="<<Quantile(gpu,.5)
        <<" gpu_us_p90="<<Quantile(gpu,.9)<<" stats_gpu_us_p50="<<Quantile(statsGpu,.5)<<" stats_gpu_us_p90="<<Quantile(statsGpu,.9)
        <<" apply_gpu_us_p50="<<Quantile(applyGpu,.5)<<" apply_gpu_us_p90="<<Quantile(applyGpu,.9)<<" allocated_image_bytes="<<guard.ImageBytes()<<'\n';
}
void MotionStabilityTiming(Host& host,uint32_t width,uint32_t height,const std::filesystem::path& input)
{
    std::shared_ptr<Context> context;std::string error;
    need(CreateContext(host.device.Get(),width,height,context,error),error.c_str());
    struct CameraSample { DirectX::XMMATRIX previous,current;DirectX::XMFLOAT3 position,oldPosition;bool valid; };
    const auto bytes=std::filesystem::file_size(input);need(bytes&&bytes%(39*4)==0,"packed camera-pair timing input");
    std::ifstream stream(input,std::ios::binary);std::vector<CameraSample> cameras;
    for(size_t k=0;k<bytes/(39*4);k++)
    {
        std::array<float,39> words;stream.read(reinterpret_cast<char*>(words.data()),sizeof(words));need(bool(stream),"camera sample complete");
        DirectX::XMFLOAT4X4 a,b;std::memcpy(&a,words.data(),64);std::memcpy(&b,words.data()+16,64);
        cameras.push_back({DirectX::XMLoadFloat4x4(&a),DirectX::XMLoadFloat4x4(&b),
            {words[32],words[33],words[34]},{words[35],words[36],words[37]},words[38]!=0});
    }
    std::vector<double> changing,unchanged,combined;
    for(unsigned mode=0;mode<2;mode++)for(unsigned i=0;i<12000;i++)
    {
        const float value=mode?.5f:(i&1?.5f:.85f);
        const auto start=std::chrono::steady_clock::now();
        need(context->ApplyMotionStability(value,error),error.c_str());
        const double us=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-start).count();
        if(i>=2000)(mode?unchanged:changing).push_back(us);
    }
    MotionStabilitySettings settings;settings.enabled=true;double checksum=0;
    for(unsigned i=0;i<12000;i++)
    {
        const auto& sample=cameras[i%cameras.size()];const auto start=std::chrono::steady_clock::now();
        const float degrees=CameraTurnDegrees(sample.previous,sample.current);
        const float dx=sample.position.x-sample.oldPosition.x,dy=sample.position.y-sample.oldPosition.y,dz=sample.position.z-sample.oldPosition.z;
        const float metres=std::sqrt(dx*dx+dy*dy+dz*dz);
        const float value=NextMotionStability(settings,context->configuredValues[1],sample.valid,degrees,metres);
        need(context->ApplyMotionStability(value,error),error.c_str());
        const double us=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-start).count();
        if(i>=2000)combined.push_back(us);checksum+=value;
    }
    std::cout<<"motion_stability_timing width="<<width<<" height="<<height<<" samples=10000 warm=2000"
        <<" changing_cpu_us_p50="<<Quantile(changing,.5)<<" changing_cpu_us_p90="<<Quantile(changing,.9)
        <<" unchanged_cpu_us_p50="<<Quantile(unchanged,.5)<<" unchanged_cpu_us_p90="<<Quantile(unchanged,.9)
        <<" captured_camera_pairs="<<cameras.size()<<" combined_cpu_us_p50="<<Quantile(combined,.5)
        <<" combined_cpu_us_p90="<<Quantile(combined,.9)<<" checksum="<<checksum<<" gpu_dispatches=0\n";
}
void GuardThresholdValidation()
{
    RRWrapper wrapper;std::string error;RRSettings settings;
    settings.motionStability.rotationDegrees=std::numeric_limits<float>::quiet_NaN();
    settings.motionStability.translationMetres=std::numeric_limits<float>::quiet_NaN();
    need(ValidateRRSettings(settings,error)&&wrapper.Configure(settings,error),
         "both new options OFF continue to ignore unused camera threshold storage");
    for(bool translation:{false,true})for(float value:{std::numeric_limits<float>::quiet_NaN(),
        std::numeric_limits<float>::infinity(),-1.f,0.f,181.f})
    {
        settings=RRSettings{};settings.lightingValidation=true;
        (translation?settings.motionStability.translationMetres:settings.motionStability.rotationDegrees)=value;
        need(!ValidateRRSettings(settings,error)&&!wrapper.Configure(settings,error),
             "G3 alone rejects invalid camera thresholds even while G2 is disabled");
    }
    settings=RRSettings{};settings.lightingValidation=true;
    settings.motionStability.still=std::numeric_limits<float>::quiet_NaN();
    settings.motionStability.ramp=std::numeric_limits<float>::quiet_NaN();
    need(ValidateRRSettings(settings,error)&&wrapper.Configure(settings,error),
         "G3 alone ignores G2-only unused stability fields while validating its own thresholds");
}
void GuardOwnedMotionAliases(Host& host)
{
    Scene scene(host,64,64);host.submit();host.reset();
    for(bool privateMotion:{false,true})
    {
        RRWrapper wrapper;RRSettings settings;settings.lightingValidation=true;std::string error;
        need(wrapper.Configure(settings,error),error.c_str());FrameParameters frame;RRRecordedOutputLease output;
        need(wrapper.PrepareFrame(camera(privateMotion?202:201),false,frame,error),error.c_str());
        need(wrapper.RecordOwned(host.list.Get(),scene.resources,frame,output,error),error.c_str());
        const auto snapshot=wrapper.GetOwnedOutputSnapshot(output);
        need(snapshot.providerMotion&&snapshot.providerMotion!=scene.resources.motion,
             "enabled G3 snapshot freezes actual private provider motion");
        auto target=privateMotion?snapshot.providerMotion:scene.resources.motion;
        need(!wrapper.CommitOwned(host.list.Get(),output,target,scene.diff(),frame,error),
             privateMotion?"owned commit rejects private provider motion target":"owned commit rejects canonical motion target while G3 is enabled");
        need(error.find("alias")!=std::string::npos,"motion target rejection preserves explicit alias reason");
        host.submit();host.reset();
    }
    std::cout<<"PASS canonical/private G3 motion commit alias protection checks="<<checks<<" provider=mock production_gpu_guard=1\n";
}
void GuardGenerationLifetime(Host& host,const std::filesystem::path& output)
{
    Scene scene(host,64,64);host.submit();host.reset();RRWrapper wrapper;FrameParameters frame;std::string error;
    RRSettings settings;settings.lightingValidation=true;need(wrapper.Configure(settings,error),error.c_str());
    RRRecordedOutputLease first,second;need(wrapper.PrepareFrame(camera(100),false,frame,error),error.c_str());
    need(wrapper.RecordOwned(host.list.Get(),scene.resources,frame,first,error),error.c_str());
    {
        FSRDNrdLightingGuardDx12 inactive;FSRDNrdLightingGuardDx12::Lease unused;
        for(const auto control:std::array<std::array<float,3>,4>{{{{-.1f,1,1000}},{{.1f,0,1000}},
            {{.1f,1,65505}},{{.1f,std::numeric_limits<float>::quiet_NaN(),1000}}}})
        {
            need(!inactive.Before(host.device.Get(),host.list.Get(),64,64,0,scene.resources.diff,scene.resources.spec,
                scene.resources.motion,scene.resources.linearDepth,unused,error,control[0],control[1],control[2]),
                "unsupported rejection controls must fail before GPU recording");
            need(!unused&&inactive.ImageBytes()==0,"invalid control fallback must allocate no detector images");
        }
    }
    const uint32_t firstFrame=frame.frameIndex;const auto firstWork=first->lease->lightingGuard;
    const auto oldGeneration=FSRDLightingGuardTestAccess::Generation(firstWork);
    const auto oldImages=FSRDLightingGuardTestAccess::History(firstWork,firstFrame);
    need(oldGeneration&&firstWork->Motion(),"first pending recording owns its actual detector generation");
    wrapper.DiscardRecordingHistory();
    need(!wrapper.GetSettingsState().lightingValidationActive&&wrapper.OwnedAuxiliaryBytes()==0,
         "discard retires the front detector while the old recording retains its images");
    need(wrapper.PrepareFrame(camera(101),false,frame,error)&&frame.reset,"fresh physical provider starts with RESET");
    need(wrapper.RecordOwned(host.list.Get(),scene.resources,frame,second,error),error.c_str());
    const auto secondWork=second->lease->lightingGuard;
    const auto newImages=FSRDLightingGuardTestAccess::History(secondWork,frame.frameIndex);
    need(FSRDLightingGuardTestAccess::Generation(secondWork)!=oldGeneration,
         "new physical provider must never reuse a discarded pending detector generation");
    for(unsigned j=0;j<3;j++)need(oldImages[j]!=newImages[j],"all pending old statistics images are independent of fresh provider scratch");
    need(firstWork->Motion()!=secondWork->Motion(),"pending old motion stays independently owned");
    auto oldChange=FSRDLightingGuardTestAccess::Change(firstWork),newChange=FSRDLightingGuardTestAccess::Change(secondWork);
    need(oldChange&&newChange&&oldChange!=newChange,"pending generations own separate positive-support scratch maps");
    GuardReadback oldChangeReadback(host,oldChange),newChangeReadback(host,newChange);
    std::array<std::unique_ptr<GuardReadback>,6> readbacks;
    for(unsigned j=0;j<3;j++){readbacks[j]=std::make_unique<GuardReadback>(host,oldImages[j]);readbacks[j+3]=std::make_unique<GuardReadback>(host,newImages[j]);}
    settings.lightingValidation=false;need(wrapper.Configure(settings,error),error.c_str());wrapper.DiscardRecordingHistory();
    need(firstWork->Motion()->GetDesc().Width==64&&secondWork->Motion()->GetDesc().Height==64,
         "both pending generations survive toggling OFF and dropping every front context before submission");
    need(oldChange->GetDesc().Width==8&&newChange->GetDesc().Height==8,
         "positive-support scratch survives front context destruction with the pending work");
    host.submit();host.reset();std::filesystem::create_directories(output);
    {std::ofstream f(output/"old-change.bin",std::ios::binary);oldChangeReadback.Write(f);}
    {std::ofstream f(output/"new-change.bin",std::ios::binary);newChangeReadback.Write(f);}
    for(unsigned j=0;j<6;j++){std::ofstream f(output/("retained"+std::to_string(j)+".bin"),std::ios::binary);readbacks[j]->Write(f);}
    std::cout<<"PASS pending detector generation lifetime checks="<<checks<<" generations=2 independent_history_images=6 independent_change_maps=2\n";
}
int main(int argc,char** argv)
{
    try
    {
        Host host;
        if(argc==2&&std::string(argv[1])=="--alias")
        {GuardThresholdValidation();GuardOwnedMotionAliases(host);host.checkDebug();return 0;}
        if(argc==3&&std::string(argv[1])=="--lifetime")
        {GuardGenerationLifetime(host,argv[2]);host.checkDebug();return 0;}
        if(argc==3&&std::string(argv[1])=="--motion-timing")
        {loadReal();MotionStabilityTiming(host,1505,847,argv[2]);MotionStabilityTiming(host,2560,1440,argv[2]);host.checkDebug();std::cout<<"PASS actual SDK motion-stability Configure timing checks="<<checks<<'\n';return 0;}
        if(argc==2&&std::string(argv[1])=="--timing")
        {GuardTiming(host,1505,847);GuardTiming(host,2560,1440);host.checkDebug();std::cout<<"PASS guard timing checks="<<checks<<'\n';return 0;}
        if(argc==4&&std::string(argv[1])=="--timing-files")
        {GuardTiming(host,1505,847,argv[2]);GuardTiming(host,2560,1440,argv[3]);host.checkDebug();std::cout<<"PASS captured-input guard timing checks="<<checks<<'\n';return 0;}
        need(argc==2,"job path required");std::ifstream job(argv[1]);uint32_t w,h,n;job>>w>>h>>n;
        std::array<std::string,4> paths;for(auto& p:paths)job>>std::quoted(p);std::string controlsPath,outPath;job>>std::quoted(controlsPath)>>std::quoted(outPath);
        need(bool(job)&&w&&h&&n,"valid guard job");std::filesystem::create_directories(outPath);
        std::array<std::ifstream,4> inputs;for(unsigned k=0;k<4;k++){inputs[k].open(paths[k],std::ios::binary);need(bool(inputs[k]),"input stream opens");}
        std::ifstream controls(controlsPath);std::ofstream motionOut(std::filesystem::path(outPath)/"motion.bin",std::ios::binary);
        std::array<std::ofstream,3> stats;unsigned k=0;for(const char* name:{"meanvar.bin","fast.bin","tile.bin"})stats[k++].open(std::filesystem::path(outPath)/name,std::ios::binary);
        Scene scene(host,w,h);host.submit();host.reset();FSRDNrdLightingGuardDx12 guard;
        uint64_t peak=0;
        for(uint32_t i=0;i<n;i++)
        {
            uint32_t frame,moving,reset;float disocc,qyy,farDepth;controls>>frame>>moving>>reset>>disocc>>qyy>>farDepth;need(bool(controls),"control stream complete");
            std::array<ComPtr<ID3D12Resource>,4> uploads;
            std::array<ID3D12Resource*,4> resources {scene.resources.diff,scene.resources.spec,scene.resources.motion,scene.resources.linearDepth};
            for(unsigned j=0;j<4;j++)uploads[j]=UploadGuard(host,resources[j],inputs[j]);
            FSRDNrdLightingGuardDx12::Lease work;std::string error;
            if(reset)guard.Invalidate();
            if(moving)guard.Invalidate();
            else need(guard.Before(host.device.Get(),host.list.Get(),w,h,frame,resources[0],resources[1],resources[2],resources[3],work,error,disocc,qyy,farDepth),error.c_str());
            GuardReadback motion(host,work?work->Motion():resources[2]);
            std::array<std::unique_ptr<GuardReadback>,3> readbacks;
            const auto native=FSRDLightingGuardTestAccess::Stats(guard,frame);
            if(work)for(unsigned j=0;j<3;j++)readbacks[j]=std::make_unique<GuardReadback>(host,native[j]);
            host.submit();host.reset();motion.Write(motionOut);
            for(unsigned j=0;j<3;j++)
            {
                if(readbacks[j])readbacks[j]->Write(stats[j]);
                else {size_t cells=size_t((w+31)/32*4)*((h+31)/32*4);size_t bytes=j==0?cells*16:j==1?cells*8:cells/16*4;std::vector<char> zero(bytes);stats[j].write(zero.data(),bytes);}
            }
            peak=std::max(peak,guard.ImageBytes());
        }
        host.checkDebug();std::cout<<"PASS guard frames="<<n<<" checks="<<checks<<" peak_image_bytes="<<peak<<'\n';return 0;
    }
    catch(const std::exception& e){std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;}
}
