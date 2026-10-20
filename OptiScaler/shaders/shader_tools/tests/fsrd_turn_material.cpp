#define main PreservedRRFixtureMain
#include "nrd_bridge_rr_fixture.cpp"
#undef main

void save(Readback& r,const std::filesystem::path& file,uint32_t w,uint32_t h)
{
    uint8_t* p;hr(r.bufferResource->Map(0,nullptr,reinterpret_cast<void**>(&p)));
    std::ofstream f(file,std::ios::binary);
    for(uint32_t y=0;y<h;y++)f.write(reinterpret_cast<char*>(p+r.footprint.Offset+y*r.footprint.Footprint.RowPitch),size_t(w)*8);
    r.bufferResource->Unmap(0,nullptr);need(bool(f),"complete colour readback");
}
int main(int argc,char** argv)try
{
    need(argc==7||argc==8,"width height input-directory output-directory weight gain [--filter-only]");
    const uint32_t w=std::stoul(argv[1]),h=std::stoul(argv[2]);const float weight=std::stof(argv[5]),gain=std::stof(argv[6]);
    const std::filesystem::path out=argv[4];std::filesystem::create_directories(out);
    if(std::getenv("FSRD_COLOUR_REAL"))loadReal();
    Host host;Scene scene(host,w,h,argv[3]);host.submit();host.reset();
    Context context;context.device=host.device;context.width=w;context.height=h;
    context.descriptorStride=host.device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    Context::Slot slot;std::string error;
    need(context.EnsureTurnColour(slot,error),error.c_str());need(context.EnsureTurnMaterial(slot,error),error.c_str());
    // Actual production methods and descriptors, not a lookalike root signature.
    for(bool material:{false,true})
    {
        if(material)context.TurnMaterial(host.list.Get(),slot,scene.resources,weight,gain);
        else context.TurnColour(host.list.Get(),slot,scene.resources.spec,scene.resources.diff,weight,gain);
        context.TurnColourBarriers(host.list.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        Readback s(host,context.turnSignals[0].Get()),d(host,context.turnSignals[1].Get());host.submit();host.reset();
        save(s,out/(material?"material-spec.bin":"old-spec.bin"),w,h);save(d,out/(material?"material-diff.bin":"old-diff.bin"),w,h);
    }
    if(argc==8){host.checkDebug();std::cout<<"PASS filter-only"<<std::endl;return 0;}
    // Reuse these exact production methods for isolated pass timings; uploads excluded.
    D3D12_QUERY_HEAP_DESC q {};q.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;q.Count=48;
    ComPtr<ID3D12QueryHeap> query;hr(host.device->CreateQueryHeap(&q,IID_PPV_ARGS(&query)));
    auto values=buffer(host.device.Get(),48*8,D3D12_HEAP_TYPE_READBACK);uint64_t frequency;hr(host.queue->GetTimestampFrequency(&frequency));
    std::array<Context::Slot,24> timingSlots;
    for(auto& s:timingSlots){need(context.EnsureTurnColour(s,error),error.c_str());need(context.EnsureTurnMaterial(s,error),error.c_str());}
    for(bool material:{false,true})
    {
        std::vector<double> samples;
        for(unsigned batch=0;batch<3;batch++)
        {
            for(unsigned k=0;k<24;k++)
            {
                host.list->EndQuery(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2*k);
                if(material)context.TurnMaterial(host.list.Get(),timingSlots[k],scene.resources,weight,gain);
                else context.TurnColour(host.list.Get(),timingSlots[k],scene.resources.spec,scene.resources.diff,weight,gain);
                context.TurnColourBarriers(host.list.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
                host.list->EndQuery(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2*k+1);
            }
            host.list->ResolveQueryData(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,48,values.Get(),0);host.submit();host.reset();
            uint64_t* p;hr(values->Map(0,nullptr,reinterpret_cast<void**>(&p)));
            if(batch)for(unsigned k=0;k<24;k++)samples.push_back(double(p[2*k+1]-p[2*k])*1000/frequency);
            values->Unmap(0,nullptr);
        }
        std::sort(samples.begin(),samples.end());std::cout<<"timing material="<<material<<" median_ms="<<samples[samples.size()/2]<<std::endl;
    }
    // Source lighting survives; alpha is verified independently by the Python caller.
    for(auto pair:{std::pair(scene.resources.spec,"source-spec.bin"),std::pair(scene.resources.diff,"source-diff.bin")})
    {
        barrier(host.list.Get(),pair.first,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        Readback r(host,pair.first);barrier(host.list.Get(),pair.first,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        host.submit();host.reset();save(r,out/pair.second,w,h);
    }
    // The same actual wrapper must choose/freeze the new path only with admitted guides.
    RRWrapper wrapper;RRSettings settings;settings.turnColourFilter=true;settings.turnColourFrames=0;
    settings.turnMaterialFence=true;settings.nativeMaterialGuides=true;settings.radianceScale={true,16,256};
    for(unsigned k=0;k<5;k++)
    {
        if(k==4)settings.turnColourFilter=false;
        if(k==3)settings.turnMaterialFence=false;
        need(wrapper.Configure(settings,error),error.c_str());FrameParameters f;
        need(wrapper.PrepareFrame(camera(100+k,float(w)/h),false,f,error),error.c_str());
        f.nativeMaterialGuides=true; // Requested stays ON while admission fails at k=1.
        scene.resources.materialGuidesApplied=k!=1;
        RRRecordedOutputLease output;if(!wrapper.RecordOwned(host.list.Get(),scene.resources,f,output,error))throw std::runtime_error(error);
        auto snapshot=wrapper.GetOwnedOutputSnapshot(output);
        need(snapshot.turnMaterialFenceActive==(k==0||k==2),"actual recorded activation follows ON, missing-guide, recovered-guide and OFF states");
        host.submit();host.reset();
    }
    wrapper.DiscardRecordingHistory();RecordedComputeLease::Poll();host.checkDebug();
    std::cout<<"PASS turn_material checks="<<checks<<" provider_dispatches="<<FfxApiProxy::dispatches<<std::endl;
    return 0;
}
catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<std::endl;return 1;}
