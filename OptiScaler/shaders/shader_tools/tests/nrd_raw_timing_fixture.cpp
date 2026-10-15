// Required two-resolution timings and untouched A-regression entry point.
#include "raw_b_fixture_support.cpp"
namespace RawTiming
{
using namespace NrdBridge;
struct Source
{
    std::array<ComPtr<ID3D12Resource>,7> textures;
    ComPtr<ID3D12DescriptorHeap> heap;
    ComPtr<ID3D12Resource> constants;
    RawSignalSource raw;
    Source(Fixture& f,uint32_t w,uint32_t h)
    {
        const size_t pixels=size_t(w)*h;
        auto makeHalf=[&](unsigned i,std::array<uint16_t,4> value,D3D12_RESOURCE_STATES state)
        {
            std::vector<char> bytes(pixels*8);for(size_t p=0;p<pixels;++p)memcpy(bytes.data()+p*8,value.data(),8);
            textures[i]=f.Texture(w,h,DXGI_FORMAT_R16G16B16A16_FLOAT,state,&bytes);
        };
        makeHalf(0,{0x3c00,0x3800,0x3400,0x4500},D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        makeHalf(1,{0x3a00,0x3800,0x3400,0x4700},D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        {std::vector<uint32_t> words(pixels,512u|(512u<<10u)|(307u<<20u));std::vector<char> bytes(pixels*4);memcpy(bytes.data(),words.data(),bytes.size());textures[2]=f.Texture(w,h,DXGI_FORMAT_R10G10B10A2_UNORM,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&bytes);}
        {std::vector<float> words(pixels,5);std::vector<char> bytes(pixels*4);memcpy(bytes.data(),words.data(),bytes.size());textures[3]=f.Texture(w,h,DXGI_FORMAT_R32_FLOAT,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&bytes);}
        makeHalf(4,{0,0,0,0x3c00},D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        makeHalf(5,{0x3800,0x3400,0x3a00,0x3400},D3D12_RESOURCE_STATE_COMMON);
        {std::vector<uint16_t> words(pixels,0x34cd);std::vector<char> bytes(pixels*2);memcpy(bytes.data(),words.data(),bytes.size());textures[6]=RawFixture::TextureR16(f,w,h,bytes);}
        for(unsigned i=0;i<5;++i)gNrdGuideInputs.insert(textures[i].Get());for(unsigned i=5;i<7;++i)gNrdOwnedMaterials.insert(textures[i].Get());
        D3D12_DESCRIPTOR_HEAP_DESC desc{};desc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;desc.NumDescriptors=2;desc.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        hr(f.device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&heap)));auto cpu=heap->GetCPUDescriptorHandleForHeapStart();const auto stride=f.device->GetDescriptorHandleIncrementSize(desc.Type);
        for(unsigned i=0;i<2;++i)
        {
            D3D12_SHADER_RESOURCE_VIEW_DESC view{};view.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
            view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;view.Texture2D.MipLevels=1;f.device->CreateShaderResourceView(textures[i].Get(),&view,cpu);cpu.ptr+=stride;
        }
        constants=f.Buffer(1536,D3D12_HEAP_TYPE_UPLOAD);raw.nativeHeap=heap.Get();raw.specSrv=heap->GetGPUDescriptorHandleForHeapStart();raw.diffSrv=raw.specSrv;raw.diffSrv.ptr+=stride;
        raw.nativeConstants.address=constants->GetGPUVirtualAddress();raw.width=w;raw.height=h;
    }
};
struct Bench
{
    Source source;
    RawSignalSnapshotPass raw;
    ConversionPass conversion;
    FrameParameters frame;
    ComPtr<ID3D12QueryHeap> queries;
    ComPtr<ID3D12Resource> timestamps;
    Bench(Fixture& f,uint32_t w,uint32_t h,const fs::path& path):source(f,w,h)
    {
        uint32_t unused;frame=ReadFrame(path,unused);frame.nativeMaterialGuides=true;frame.preserveNativeMaterialIDs=true;
        std::string error;need(raw.Initialize(f.device.Get(),w,h,error),error.c_str());need(conversion.Initialize(f.device.Get(),w,h,error),error.c_str());
        D3D12_QUERY_HEAP_DESC desc{};desc.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;desc.Count=6;hr(f.device->CreateQueryHeap(&desc,IID_PPV_ARGS(&queries)));timestamps=f.Buffer(48,D3D12_HEAP_TYPE_READBACK);
    }
};
void Run(Fixture& f,const fs::path& output)
{
    std::ofstream csv(output/"raw-timestamps.csv");need(bool(csv),"timing CSV open");csv<<std::setprecision(17)<<"width,height,profile,sample,capture_ms,geometry_ms,decode_ms,owned_bytes,owned_slots\n";
    uint64_t frequency=0;hr(f.queue->GetTimestampFrequency(&frequency));need(frequency>0,"actual queue timestamp frequency");
    std::vector<std::shared_ptr<Bench>> retained;uint32_t frameId=0;
    for(const auto extent:{std::pair{1505u,847u},std::pair{2560u,1440u}})
    {
        auto bench=std::make_shared<Bench>(f,extent.first,extent.second,output/(std::to_string(extent.first)+"x"+std::to_string(extent.second)));retained.push_back(bench);
        for(unsigned profile=0;profile<3;++profile)
        {
            bench->source.raw.profile=profile?NativeRawProfile::PrePass:NativeRawProfile::ReconDirect;
            RawPrePassFixture::Constants(bench->source.constants.Get(),0,0,extent.first,extent.second,profile==2?0:2,profile==2?1:2,0);
            uint64_t warmBytes=0;uint32_t warmSlots=0;
            for(unsigned repeat=0;repeat<11;++repeat)
            {
                auto& frame=bench->frame;frame.streamlineFrame=20000+frameId;frame.frameIndex=frameId++;frame.reset=true;
                RawSignalLease lease;ConvertedResources resources;std::string error;
                f.list->EndQuery(bench->queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
                need(bench->raw.Capture(f.list.Get(),bench->source.raw,frame.streamlineFrame,frame.frameIndex,lease,error),error.c_str());
                f.list->EndQuery(bench->queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
                ConversionInputs inputs;inputs.reconSpec=reinterpret_cast<ID3D12Resource*>(uintptr_t(1));inputs.reconDiff=reinterpret_cast<ID3D12Resource*>(uintptr_t(3));
                inputs.normals=bench->source.textures[2].Get();inputs.viewDepth=bench->source.textures[3].Get();inputs.nativeMaterial=bench->source.textures[5].Get();inputs.nativeMaterialRoughness=bench->source.textures[6].Get();
                f.list->EndQuery(bench->queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2);
                need(bench->conversion.DispatchGeometry(f.list.Get(),inputs,frame,lease,resources,error),error.c_str());
                f.list->EndQuery(bench->queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,3);
                f.list->EndQuery(bench->queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,4);
                need(bench->raw.Decode(f.list.Get(),lease,resources,bench->source.raw.nativeConstants,error),error.c_str());
                f.list->EndQuery(bench->queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,5);
                f.list->ResolveQueryData(bench->queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,6,bench->timestamps.Get(),0);
                f.Submit();f.Reset();need(SUCCEEDED(RecordedComputeLease::RequiredSubmissionFailure()),"timing raw GPU status valid at every completed fence");
                if(!repeat){warmBytes=bench->raw.OwnedBytes();warmSlots=bench->raw.OwnedSlots();}
                need(bench->raw.OwnedBytes()==warmBytes&&bench->raw.OwnedSlots()==warmSlots,"no timing pool allocation after first warmup");
                void* data=nullptr;D3D12_RANGE read{0,48};hr(bench->timestamps->Map(0,&read,&data));uint64_t values[6];memcpy(values,data,48);D3D12_RANGE empty{0,0};bench->timestamps->Unmap(0,&empty);
                for(unsigned pair=0;pair<3;++pair)need(values[pair*2+1]>=values[pair*2],"ordered native GPU timestamps");
                if(repeat>=2)csv<<extent.first<<','<<extent.second<<','<<(profile==0?"A":profile==1?"B-full":"B-checker")<<','<<repeat-2<<','
                    <<double(values[1]-values[0])*1000/frequency<<','<<double(values[3]-values[2])*1000/frequency<<','<<double(values[5]-values[4])*1000/frequency<<','<<warmBytes<<','<<warmSlots<<'\n';
            }
        }
    }
    csv.close();need(bool(csv),"GPU timestamp CSV flushed");need(f.fence->GetCompletedValue()>=f.fenceValue&&RecordedComputeLease::GetRegistry().recordings.empty()&&RecordedComputeLease::GetRegistry().submissions.empty(),"all timing native GPU work and status observers completed");
    std::cout<<"timing warmups=2 measured=9 resolutions=2 profiles=3 provider_calls=0 native_nrd_calls=0 gpu_based_validation=0\n";
}
}
int main(int argc,char** argv)
{
    try
    {
        if(argc==3&&std::string(argv[1])=="--a-regression")return RawAStandaloneMain(2,argv+1);
        need(argc==2,"timing fixture expects output/config directory");Fixture fixture(false);RawTiming::Run(fixture,argv[1]);hr(fixture.list->Close());fixture.Validate();std::cout<<"PASS raw_timing_checks="<<checks<<'\n';return 0;
    }
    catch(const std::exception& error){std::cerr<<"FAIL raw_timing "<<error.what()<<'\n';return 1;}
}
