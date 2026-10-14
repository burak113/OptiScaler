// Research only: retain the complete existing production-wrapper fixture and
// its native signed-provider proxy seam. Its original main/assertions are not
// altered; the separately scheduled baseline regression still executes them.
#define main NrdExistingWrapperRegressionMain
#include "nrd_bridge_rr_fixture.cpp"
#undef main
#include "radiance_gain_shader.h"
#include <iomanip>
#include <map>

namespace NrdConditioningResearch
{
struct Pose
{
    uint32_t frame=0,key=0,repeat=0;
    bool reset=false;
    std::array<float,16> view{},projection{};
    std::array<float,3> position{};
    std::array<float,2> jitter{};
};
std::string prefix(uint32_t frame)
{
    std::ostringstream text;text<<"frame"<<std::setw(3)<<std::setfill('0')<<frame;
    return text.str();
}
SLConstantsSnapshot snapshot(const Pose& pose,uint32_t width,uint32_t height)
{
    auto result=camera(pose.frame,float(width)/height,.05f);
    auto& value=result.constants;
    for(unsigned row=0;row<4;++row)
        value.cameraViewToClip[row]=sl::float4(pose.projection[row],pose.projection[4+row],
            pose.projection[8+row],pose.projection[12+row]);
    value.cameraRight={pose.view[0],pose.view[1],pose.view[2]};
    value.cameraUp={pose.view[4],pose.view[5],pose.view[6]};
    value.cameraFwd={-pose.view[8],-pose.view[9],-pose.view[10]};
    value.cameraPos={pose.position[0],pose.position[1],pose.position[2]};
    value.cameraFOV=2.f*std::atan(1.f/pose.projection[5]);
    value.cameraNear=.05f;value.cameraFar=0;
    value.mvecScale={1,1};value.jitterOffset={pose.jitter[0],pose.jitter[1]};
    value.motionVectorsJittered=sl::Boolean::eFalse;
    value.reset=pose.reset?sl::Boolean::eTrue:sl::Boolean::eFalse;
    return result;
}
std::vector<uint8_t> readBytes(const std::filesystem::path& path)
{
    std::ifstream input(path,std::ios::binary|std::ios::ate);
    need(bool(input),"research sealed input missing");
    const auto size=input.tellg();need(size>=0,"research sealed input size");
    std::vector<uint8_t> bytes(static_cast<size_t>(size));input.seekg(0);
    input.read(reinterpret_cast<char*>(bytes.data()),bytes.size());
    need(input.gcount()==bytes.size(),"research sealed input short read");return bytes;
}
struct Capture
{
    ComPtr<ID3D12Resource> storage;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    uint32_t width=0,height=0,bytesPerPixel=0;
    Capture(Host& host,ID3D12Resource* resource,D3D12_RESOURCE_STATES state,unsigned bpp)
    {
        const auto desc=resource->GetDesc();width=uint32_t(desc.Width);height=desc.Height;bytesPerPixel=bpp;
        UINT rows;UINT64 rowBytes,total;
        host.device->GetCopyableFootprints(&desc,0,1,0,&footprint,&rows,&rowBytes,&total);
        storage=buffer(host.device.Get(),total,D3D12_HEAP_TYPE_READBACK);
        barrier(host.list.Get(),resource,state,D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION source{},target{};
        source.pResource=resource;source.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        target.pResource=storage.Get();target.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;target.PlacedFootprint=footprint;
        host.list->CopyTextureRegion(&target,0,0,0,&source,nullptr);
        barrier(host.list.Get(),resource,D3D12_RESOURCE_STATE_COPY_SOURCE,state);
    }
    std::vector<uint8_t> bytes() const
    {
        uint8_t* data=nullptr;hr(storage->Map(0,nullptr,reinterpret_cast<void**>(&data)));
        std::vector<uint8_t> result(size_t(width)*height*bytesPerPixel);
        for(uint32_t y=0;y<height;++y)
            std::memcpy(result.data()+size_t(y)*width*bytesPerPixel,
                data+footprint.Offset+size_t(y)*footprint.Footprint.RowPitch,size_t(width)*bytesPerPixel);
        storage->Unmap(0,nullptr);return result;
    }
    void save(const std::filesystem::path& path) const
    {
        const auto data=bytes();std::ofstream output(path,std::ios::binary);
        output.write(reinterpret_cast<const char*>(data.data()),data.size());need(bool(output),"research capture write");
    }
    void exact(const std::filesystem::path& path) const
    {need(bytes()==readBytes(path),"actual GPU guide/source bits remain identical to sealed shared input");}
};
struct GainKernel
{
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12RootSignature> root;
    ComPtr<ID3D12PipelineState> pso;
    explicit GainKernel(ID3D12Device* source) : device(source)
    {
        hr(device->CreateRootSignature(0,RadianceGainShaderBytes,sizeof(RadianceGainShaderBytes),IID_PPV_ARGS(&root)));
        D3D12_COMPUTE_PIPELINE_STATE_DESC desc{};desc.pRootSignature=root.Get();
        desc.CS={RadianceGainShaderBytes,sizeof(RadianceGainShaderBytes)};
        hr(device->CreateComputePipelineState(&desc,IID_PPV_ARGS(&pso)));
    }
};
struct GainRecording
{
    std::shared_ptr<GainKernel> kernel;
    ComPtr<ID3D12DescriptorHeap> heap;
    ComPtr<ID3D12Resource> source,target;
};
ComPtr<ID3D12Resource> halfTarget(ID3D12Device* device,uint32_t width,uint32_t height)
{
    D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width=width;desc.Height=height;desc.DepthOrArraySize=desc.MipLevels=1;desc.SampleDesc.Count=1;
    desc.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
    ComPtr<ID3D12Resource> result;
    hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
        nullptr,IID_PPV_ARGS(&result)));return result;
}
void gain(Host& host,const std::shared_ptr<GainKernel>& kernel,ID3D12Resource* source,ID3D12Resource* target,float value)
{
    need(source!=target && std::isfinite(value) && value>0,"research gain uses distinct owned resources and fixed finite gain");
    auto owner=MakeOwnedShared<GainRecording>();owner->kernel=kernel;owner->source=source;owner->target=target;
    D3D12_DESCRIPTOR_HEAP_DESC desc{};desc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    desc.NumDescriptors=2;desc.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    hr(host.device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&owner->heap)));
    auto cpu=owner->heap->GetCPUDescriptorHandleForHeapStart();auto gpu=owner->heap->GetGPUDescriptorHandleForHeapStart();
    const auto stride=host.device->GetDescriptorHandleIncrementSize(desc.Type);
    D3D12_SHADER_RESOURCE_VIEW_DESC srv{};srv.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;
    srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    srv.Texture2D.MipLevels=1;host.device->CreateShaderResourceView(source,&srv,cpu);cpu.ptr+=stride;
    D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};uav.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
    host.device->CreateUnorderedAccessView(target,nullptr,&uav,cpu);
    need(ResTrack_Dx12::RetainComputeDispatch(host.device.Get(),host.list.Get(),owner),"research gain retains complete owned GPU work");
    ID3D12DescriptorHeap* heaps[]={owner->heap.Get()};host.list->SetDescriptorHeaps(1,heaps);
    host.list->SetComputeRootSignature(kernel->root.Get());host.list->SetPipelineState(kernel->pso.Get());
    uint32_t bits;std::memcpy(&bits,&value,sizeof(bits));
    const auto resource=target->GetDesc();const uint32_t constants[]={uint32_t(resource.Width),resource.Height,bits,0};
    host.list->SetComputeRoot32BitConstants(0,4,constants,0);host.list->SetComputeRootDescriptorTable(1,gpu);
    gpu.ptr+=stride;host.list->SetComputeRootDescriptorTable(2,gpu);
    host.list->Dispatch((uint32_t(resource.Width)+7)/8,(resource.Height+7)/8,1);
    D3D12_RESOURCE_BARRIER done{};done.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;done.UAV.pResource=target;
    host.list->ResourceBarrier(1,&done);
}
void halfGainIdentity(const Capture& source,const Capture& target,float gainValue)
{
    const auto before=source.bytes(),after=target.bytes();need(before.size()==after.size(),"gain capture size identity");
    uint64_t matched=0,alpha=0,finite=0;
    for(size_t p=0;p<before.size()/8;++p)
    {
        for(unsigned c=0;c<4;++c)
        {
            uint16_t a,b;std::memcpy(&a,before.data()+p*8+c*2,2);std::memcpy(&b,after.data()+p*8+c*2,2);
            finite+=std::isfinite(PackedVector::XMConvertHalfToFloat(b));
            if(c<3)matched+=b==PackedVector::XMConvertFloatToHalf(PackedVector::XMConvertHalfToFloat(a)*gainValue);
            else alpha+=a==b;
        }
    }
    need(matched==before.size()/8*3,"GPU fixed RGB gain matches independent nearest-even half bits including subnormals");
    need(alpha==before.size()/8,"GPU gain preserves every alpha/hit-distance bit");
    need(finite==before.size()/2,"GPU gain produces finite RGB and alpha");
}
void stagedHitIdentity(const Capture& input,const Capture& staged)
{
    const auto before=input.bytes(),after=staged.bytes();need(before.size()==after.size(),"staged hit capture size identity");
    uint64_t matched=0,valid=0;
    for(size_t p=0;p<before.size()/8;++p)
    {
        uint16_t a,b;std::memcpy(&a,before.data()+p*8+6,2);std::memcpy(&b,after.data()+p*8+6,2);
        const float hit=PackedVector::XMConvertHalfToFloat(a);
        matched+=a==b;valid+=std::isfinite(hit) && hit>0;
    }
    need(matched==before.size()/8,"actual signed SDK preserves every input hit-alpha bit in owned staged output");
    need(valid==before.size()/8,"every shared active signal hit/metric alpha is finite and strictly positive");
}
struct AlphaArea
{
    uint64_t samples=0,exact=0,finite=0,zero=0,negative=0;
    double sum=0,minimum=std::numeric_limits<double>::infinity(),maximum=-std::numeric_limits<double>::infinity();
    uint32_t mismatchX=UINT32_MAX,mismatchY=UINT32_MAX;
    uint16_t firstInput=0,firstOutput=0;
    std::map<uint16_t,uint64_t> histogram;
    void add(uint16_t source,uint16_t target,uint32_t x,uint32_t y)
    {
        ++samples;exact+=source==target;++histogram[target];
        const float value=PackedVector::XMConvertHalfToFloat(target);
        if(std::isfinite(value)){++finite;sum+=value;minimum=std::min(minimum,double(value));maximum=std::max(maximum,double(value));}
        zero+=(target&0x7fffu)==0;negative+=std::isfinite(value) && value<0;
        if(source!=target && mismatchX==UINT32_MAX){mismatchX=x;mismatchY=y;firstInput=source;firstOutput=target;}
    }
    void write(std::ostream& out) const
    {
        out<<"{\"samples\":"<<samples<<",\"exact_input_words\":"<<exact<<",\"mismatched_words\":"<<samples-exact
            <<",\"finite\":"<<finite<<",\"zero\":"<<zero<<",\"negative\":"<<negative<<",\"mean\":";
        if(finite)out<<sum/finite;else out<<"null";
        out<<",\"minimum\":";if(finite)out<<minimum;else out<<"null";
        out<<",\"maximum\":";if(finite)out<<maximum;else out<<"null";
        out<<",\"first_mismatch_xy\":["<<mismatchX<<','<<mismatchY<<"],\"first_input_word\":"<<firstInput
            <<",\"first_output_word\":"<<firstOutput<<",\"histogram\":[";
        unsigned i=0;for(const auto& [word,count]:histogram){if(i++)out<<',';out<<'['<<word<<','<<count<<']';}out<<"]}";
    }
};
void stagedAlphaDiagnostic(const Capture& source,const Capture& target,std::ostream& out)
{
    const auto before=source.bytes(),after=target.bytes();need(before.size()==after.size(),"stage-alpha diagnostic exact buffer extent");
    AlphaArea all,interior,padding;
    for(uint32_t y=0;y<source.height;++y)for(uint32_t x=0;x<source.width;++x)
    {
        const auto offset=(size_t(y)*source.width+x)*8+6;uint16_t a,b;
        std::memcpy(&a,before.data()+offset,2);std::memcpy(&b,after.data()+offset,2);
        all.add(a,b,x,y);
        if(x>=16 && x<source.width-16 && y>=16 && y<source.height-16)interior.add(a,b,x,y);else padding.add(a,b,x,y);
    }
    out<<"{\"all\":";all.write(out);out<<",\"interior\":";interior.write(out);out<<",\"excluded_padding\":";padding.write(out);out<<'}';
    std::cout<<"stage_alpha_diag exact="<<all.exact<<" mismatched="<<all.samples-all.exact<<" finite="<<all.finite
        <<" first_xy="<<all.mismatchX<<','<<all.mismatchY<<" first_input_word="<<all.firstInput<<" first_output_word="<<all.firstOutput<<'\n';
}
// Optional calibration, entirely in this research executable. The production
// wrapper has already retained Context/slot owners before calling this adapter;
// input gain recordings and the local Scene retain owned input textures. Copy
// commands add no title ownership or writes and restore exact public SDK states.
static PfnFfxDispatch actualSignedDispatch=nullptr;
static ID3D12QueryHeap* initializationQueries=nullptr;
static std::array<ID3D12Resource*,2> borrowedTitleOutputs{};
static uint64_t initializationBatches=0,initializationCopies=0,initializationBytes=0;
ffxReturnCode_t initializeStageAndDispatch(ffxContext* context,const ffxDispatchDescHeader* header)
{
    if(!actualSignedDispatch || !initializationQueries || !header || header->type!=FFX_API_DISPATCH_DESC_TYPE_DENOISER || !header->pNext)
        return FFX_API_RETURN_ERROR_PARAMETER;
    const auto& dispatch=*reinterpret_cast<const ffxDispatchDescDenoiser*>(header);
    const auto& diffuse=*reinterpret_cast<const ffxDispatchDescDenoiserDirectDiffuse*>(header->pNext);
    if((diffuse.header.type!=FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE &&
        diffuse.header.type!=FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE) || !diffuse.header.pNext)
        return FFX_API_RETURN_ERROR_PARAMETER;
    const auto& specular=*reinterpret_cast<const ffxDispatchDescDenoiserIndirectSpecular*>(diffuse.header.pNext);
    if(specular.header.type!=FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR || specular.header.pNext)
        return FFX_API_RETURN_ERROR_PARAMETER;
    auto* list=static_cast<ID3D12GraphicsCommandList*>(dispatch.commandList);
    const std::array<const FfxApiDenoiserSignal*,2> signals{&diffuse.signal,&specular.signal};
    // Validate both descriptors before recording even the first calibration copy.
    for(const auto* signal:signals)
    {
        auto* source=static_cast<ID3D12Resource*>(signal->input.resource);
        auto* target=static_cast<ID3D12Resource*>(signal->output.resource);
        if(!list || !source || !target || source==target || target==borrowedTitleOutputs[0] || target==borrowedTitleOutputs[1] ||
            signal->input.state!=FFX_API_RESOURCE_STATE_COMPUTE_READ || signal->output.state!=FFX_API_RESOURCE_STATE_UNORDERED_ACCESS)
            return FFX_API_RETURN_ERROR_PARAMETER;
        const auto in=source->GetDesc(),out=target->GetDesc();
        if(in.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D || out.Dimension!=in.Dimension ||
            in.Format!=DXGI_FORMAT_R16G16B16A16_FLOAT || out.Format!=in.Format || in.Width!=out.Width || in.Height!=out.Height ||
            in.MipLevels!=1 || out.MipLevels!=1 || in.DepthOrArraySize!=1 || out.DepthOrArraySize!=1 ||
            in.SampleDesc.Count!=1 || out.SampleDesc.Count!=1 || in.SampleDesc.Quality!=out.SampleDesc.Quality ||
            in.Alignment!=out.Alignment || in.Layout!=out.Layout || in.Flags!=out.Flags ||
            signal->input.description.format!=signal->output.description.format ||
            signal->input.description.type!=signal->output.description.type ||
            signal->input.description.width!=in.Width || signal->input.description.height!=in.Height ||
            signal->output.description.width!=out.Width || signal->output.description.height!=out.Height)
            return FFX_API_RETURN_ERROR_PARAMETER;
    }
    list->EndQuery(initializationQueries,D3D12_QUERY_TYPE_TIMESTAMP,5);
    for(const auto* signal:signals)
    {
        auto* source=static_cast<ID3D12Resource*>(signal->input.resource);
        auto* target=static_cast<ID3D12Resource*>(signal->output.resource);
        barrier(list,source,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_SOURCE);
        barrier(list,target,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_DEST);
        list->CopyResource(target,source);
        barrier(list,target,D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        barrier(list,source,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        ++initializationCopies;const auto desc=source->GetDesc();initializationBytes+=desc.Width*desc.Height*8;
    }
    ++initializationBatches;list->EndQuery(initializationQueries,D3D12_QUERY_TYPE_TIMESTAMP,6);
    return actualSignedDispatch(context,header);
}
std::array<uint32_t,8> floatWords(const std::array<float,8>& source)
{std::array<uint32_t,8> words{};std::memcpy(words.data(),source.data(),sizeof(words));return words;}
void writeWords(std::ostream& out,const std::array<float,8>& values)
{
    const auto words=floatWords(values);out<<'[';
    for(unsigned i=0;i<words.size();++i){if(i)out<<',';out<<words[i];}out<<']';
}
struct ResultFrame
{
    Pose pose;double inputMs=0,initializationMs=0,rrMs=0,inverseMs=0,consumerMs=0;
    uint32_t flags=0;bool reset=false,previousValid=false;
};
int run(int argc,char** argv)
{
    std::filesystem::path input,output,settingsPath;bool indirect=false,probe=false,initializeStage=true;float fixedGain=1;
    for(int i=1;i<argc;++i)
    {
        const std::string arg=argv[i];
        if(arg=="--probe-defaults")probe=true;
        else if(arg=="--initialize-staged-rgba")initializeStage=true;
        else if(arg=="--uninitialized-staged-rgba")initializeStage=false;
        else if(arg=="--sequence" && i+1<argc)input=argv[++i];
        else if(arg=="--output" && i+1<argc)output=argv[++i];
        else if(arg=="--settings" && i+1<argc)settingsPath=argv[++i];
        else if(arg=="--route" && i+1<argc){const std::string route=argv[++i];need(route=="dd" || route=="id","known research diffuse route");indirect=route=="id";}
        else if(arg=="--gain" && i+1<argc)fixedGain=std::stof(argv[++i]);
        else throw std::runtime_error("unknown or incomplete research argument");
    }
    need(!input.empty() && !output.empty(),"research sequence/output paths required");
    need(fixedGain==1.f || fixedGain==.25f || fixedGain==4.f,"only predeclared fixed gains admitted");
    need(!probe || (!indirect && fixedGain==1.f && settingsPath.empty()),"defaults probe is disposable DD gain1");
    std::filesystem::create_directories(output);
    std::ifstream meta(input/"native-replay.txt");need(bool(meta),"research sealed native metadata missing");
    unsigned count,width,height;meta>>count>>width>>height;
    need(bool(meta) && count==44 && width==128 && height==128,"exact immutable 44-frame128x128 research sequence");
    std::vector<Pose> poses(count);
    for(auto& pose:poses)
    {
        unsigned reset;meta>>pose.frame>>pose.key>>pose.repeat>>reset;pose.reset=reset!=0;
        for(auto& v:pose.view)meta>>v;for(auto& v:pose.projection)meta>>v;
        for(auto& v:pose.position)meta>>v;for(auto& v:pose.jitter)meta>>v;
        need(bool(meta),"sealed research camera record complete");
    }
    RRSettings settings;
    if(!settingsPath.empty())
    {
        settings.overrideMask=0x7fu;std::ifstream values(settingsPath);for(auto& v:settings.values)values>>v;
        need(bool(values),"common eight-float research settings complete");std::string error;
        need(ValidateRRSettings(settings,error),error.c_str());
    }
    else need(probe,"all measured candidates require identical explicit effective defaults snapshot");
    loadReal();need(FfxApiProxy::real,"research must execute actual signed AMD exports");
    FfxApiProxy::useIndirectDiffuseResearch=indirect;
    Host host;auto kernel=MakeOwnedShared<GainKernel>(host.device.Get());
    auto wrapper=std::make_unique<RRWrapper>();std::string error;need(wrapper->Configure(settings,error),error.c_str());
    ComPtr<ID3D12QueryHeap> queries;D3D12_QUERY_HEAP_DESC queryDesc{};queryDesc.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;queryDesc.Count=initializeStage?7:5;
    hr(host.device->CreateQueryHeap(&queryDesc,IID_PPV_ARGS(&queries)));auto timing=buffer(host.device.Get(),queryDesc.Count*8,D3D12_HEAP_TYPE_READBACK);
    if(initializeStage)
    {
        actualSignedDispatch=FfxApiProxy::dispatchFunction;initializationQueries=queries.Get();
        FfxApiProxy::dispatchFunction=&initializeStageAndDispatch;
    }
    UINT64 frequency;hr(host.queue->GetTimestampFrequency(&frequency));need(frequency>0,"native timestamp frequency valid");
    RRSettingsState initialSettings{};uint64_t warmedStaging=0,warmedAuxiliary=0;std::vector<ResultFrame> results;
    const unsigned frames=probe?1u:count;
    for(unsigned index=0;index<frames;++index)
    {
        const auto& pose=poses[index];const auto frameDir=input/prefix(pose.frame);
        const auto outputDir=output/prefix(pose.frame);std::filesystem::create_directories(outputDir);
        Scene scene(host,width,height,frameDir);
        auto scaledSpec=halfTarget(host.device.Get(),width,height),scaledDiff=halfTarget(host.device.Get(),width,height);
        auto inverseSpec=halfTarget(host.device.Get(),width,height),inverseDiff=halfTarget(host.device.Get(),width,height);
        host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
        gain(host,kernel,scene.resources.spec,scaledSpec.Get(),fixedGain);
        gain(host,kernel,scene.resources.diff,scaledDiff.Get(),fixedGain);
        for(auto* resource:{scaledSpec.Get(),scaledDiff.Get()})
            barrier(host.list.Get(),resource,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
        auto converted=scene.resources;converted.spec=scaledSpec.Get();converted.diff=scaledDiff.Get();
        FrameParameters frame;need(wrapper->PrepareFrame(snapshot(pose,width,height),pose.reset,frame,error),error.c_str());
        need(frame.reset==(index==0) && frame.previousValid==(index!=0) && frame.frameIndex==index,
            "each physically fresh history resets exactly first frame and retains all consecutive samples");
        XMFLOAT4X4 view,projection;XMStoreFloat4x4(&view,frame.camera.view);XMStoreFloat4x4(&projection,frame.camera.projection);
        for(unsigned n=0;n<16;++n)
        {
            need(std::abs(reinterpret_cast<float*>(&view)[n]-pose.view[n])<=2.e-6f,"actual wrapper view matches immutable camera oracle");
            need(std::abs(reinterpret_cast<float*>(&projection)[n]-pose.projection[n])<=2.e-6f,"actual wrapper projection matches immutable oracle");
        }
        borrowedTitleOutputs={scene.spec(),scene.diff()};
        need(wrapper->Dispatch(host.list.Get(),converted,scene.spec(),scene.diff(),frame,error),error.c_str());
        borrowedTitleOutputs={};
        need(initializationBatches==(initializeStage?index+1:0) && initializationCopies==(initializeStage?(index+1)*2:0),
            "optional test-only initialization copies both owned SDK outputs exactly once before every real dispatch");
        const auto expectedFlags=(indirect?FFX_DENOISER_SIGNAL_INDIRECT_DIFFUSE:FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE)|FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR;
        need(FfxApiProxy::lastCreate.signalFlags==expectedFlags,"actual fresh provider context has exactly requested DD-ID plus IS flags");
        need(FfxApiProxy::lastDiffuse.header.type==(indirect?FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE:
            FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE) && FfxApiProxy::lastSpecular.header.type==FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR,
            "actual forwarded signed-provider ordered dispatch types match route");
        need(!FfxApiProxy::lastSpecular.header.pNext && FfxApiProxy::nativeDebugDispatches==0,"research has only two signals and native debug disabled");
        for(auto* guide:{&FfxApiProxy::lastDispatch.linearDepth,&FfxApiProxy::lastDispatch.motionVectors,
            &FfxApiProxy::lastDispatch.normals,&FfxApiProxy::lastDispatch.specularAlbedo,&FfxApiProxy::lastDispatch.diffuseAlbedo})
            need(guide->state==FFX_API_RESOURCE_STATE_COMPUTE_READ,"research guides remain actual SDK COMPUTE_READ");
        need(FfxApiProxy::lastDispatch.linearDepth.resource==converted.linearDepth &&
            FfxApiProxy::lastDispatch.motionVectors.resource==converted.motion &&
            FfxApiProxy::lastDispatch.normals.resource==converted.normals &&
            FfxApiProxy::lastDispatch.specularAlbedo.resource==converted.specAlbedo &&
            FfxApiProxy::lastDispatch.diffuseAlbedo.resource==converted.diffAlbedo,
            "actual signed-provider dispatch binds the five exact shared oracle guide resources");
        need(FfxApiProxy::lastDiffuse.signal.input.state==FFX_API_RESOURCE_STATE_COMPUTE_READ &&
            FfxApiProxy::lastSpecular.signal.input.state==FFX_API_RESOURCE_STATE_COMPUTE_READ &&
            FfxApiProxy::lastDiffuse.signal.output.state==FFX_API_RESOURCE_STATE_UNORDERED_ACCESS &&
            FfxApiProxy::lastSpecular.signal.output.state==FFX_API_RESOURCE_STATE_UNORDERED_ACCESS,
            "actual SDK signals use compute-read inputs and UAV staged outputs");
        need(FfxApiProxy::lastDispatch.motionVectorScale.x==1 && FfxApiProxy::lastDispatch.motionVectorScale.y==1 &&
            FfxApiProxy::lastDispatch.motionVectorScale.z==1 && FfxApiProxy::lastDispatch.renderSize.width==width &&
            FfxApiProxy::lastDispatch.renderSize.height==height,"common normalized2.5D motion and exact render size reach SDK");
        need(FfxApiProxy::lastDiffuse.signal.input.resource==scaledDiff.Get() && FfxApiProxy::lastSpecular.signal.input.resource==scaledSpec.Get(),
            "every noisy RGB sample enters actual RR through GPU-conditioned owned inputs");
        need(FfxApiProxy::lastDiffuse.signal.output.resource!=scene.diff() && FfxApiProxy::lastSpecular.signal.output.resource!=scene.spec(),
            "signed provider writes owned staging rather than borrowed title outputs");
        need(scene.spec()->AddRef()==2 && scene.spec()->Release()==1 && scene.diff()->AddRef()==2 && scene.diff()->Release()==1,
            "actual wrapper never persistently AddRefs borrowed destination pair");
        const auto state=wrapper->GetSettingsState();need(state.ready,"actual context settings queried and applied");
        if(index==0){initialSettings=state;warmedStaging=wrapper->OwnedStagingBytes();warmedAuxiliary=wrapper->OwnedAuxiliaryBytes();}
        need(floatWords(state.effective)==floatWords(initialSettings.effective) && state.requested.overrideMask==settings.overrideMask,
            "effective provider settings remain constant throughout each complete history");
        if(!probe)need(floatWords(state.effective)==floatWords(settings.values),"candidate uses exact common effective eight-float snapshot");
        need(wrapper->ContextGeneration()==1 && FfxApiProxy::creates==1,"each candidate has one physically fresh context and no hidden recreation");
        need(wrapper->OwnedStagingBytes()==warmedStaging && wrapper->OwnedAuxiliaryBytes()==warmedAuxiliary,
            "actual wrapper reuses warm staging and auxiliary pool during immutable sequence");
        need(bool(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)==(index==0),"signed SDK receives first-only reset");
        need((FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_NON_GAMMA_ALBEDO)!=0,"matched linear albedo convention");
        host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2);
        for(auto* resource:{scene.spec(),scene.diff()})
            barrier(host.list.Get(),resource,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        gain(host,kernel,scene.spec(),inverseSpec.Get(),1.f/fixedGain);
        gain(host,kernel,scene.diff(),inverseDiff.Get(),1.f/fixedGain);
        for(auto* resource:{scene.spec(),scene.diff()})
            barrier(host.list.Get(),resource,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,3);
        ConsumerBuffer constants(host);constants.flag(0);NativeTableConsumer consumer(host,inverseSpec.Get(),inverseDiff.Get(),width,height);
        consumer.Overwrite(host.device.Get(),constants.constants().address);consumer.Record(host);
        host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,4);
        host.list->ResolveQueryData(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,queryDesc.Count,timing.Get(),0);
        const auto shaderRead=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,ua=D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
        Capture originalSpec(host,scene.resources.spec,shaderRead,8),originalDiff(host,scene.resources.diff,shaderRead,8);
        Capture conditionedSpec(host,scaledSpec.Get(),shaderRead,8),conditionedDiff(host,scaledDiff.Get(),shaderRead,8);
        Capture stagedSpec(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastSpecular.signal.output.resource),ua,8);
        Capture stagedDiff(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastDiffuse.signal.output.resource),ua,8);
        Capture committedSpec(host,scene.spec(),ua,8),committedDiff(host,scene.diff(),ua,8);
        Capture finalSpec(host,inverseSpec.Get(),ua,8),finalDiff(host,inverseDiff.Get(),ua,8);
        const std::array<const char*,5> guideNames{"depth","motion","normals","spec_albedo","diff_albedo"};
        std::array<std::unique_ptr<Capture>,5> guides;
        for(unsigned guide=0;guide<5;++guide)guides[guide]=std::make_unique<Capture>(host,scene.textures[guide+2].Get(),shaderRead,guide==1?8:4);
        Readback committedSpecCheck(host,scene.spec()),committedDiffCheck(host,scene.diff());
        Readback finalSpecCheck(host,inverseSpec.Get()),finalDiffCheck(host,inverseDiff.Get());
        Readback consumerSpec(host,consumer.spec.Get()),consumerDiff(host,consumer.diff.Get());
        Capture consumerSpecData(host,consumer.spec.Get(),ua,16),consumerDiffData(host,consumer.diff.Get(),ua,16);
        const bool last=index+1==frames;
        if(last)
        {
            // Actual final recording owns its SDK context. Destroy the wrapper
            // before Execute, then detach while a queue gate prevents completion.
            ComPtr<ID3D12Fence> gate;hr(host.device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&gate)));
            struct ReleaseGate{ID3D12Fence* fence;~ReleaseGate(){fence->Signal(1);}} release{gate.Get()};
            hr(host.queue->Wait(gate.Get(),1));wrapper.reset();
            need(FfxApiProxy::destroys==0 && FfxApiProxy::live.size()==1,"recorded lease retains real context after wrapper destruction before Execute");
            host.submit(false);auto recording=RecordedComputeLease::Capture(host.list.Get());RecordedComputeLease::Detach(recording);recording.reset();
            RecordedComputeLease::Poll();need(FfxApiProxy::destroys==0,"blocked actual submission retains context after recording detach");
            hr(gate->Signal(1));host.finish();
            need(FfxApiProxy::destroys==1 && FfxApiProxy::live.empty(),"real context destroys exactly once only after final GPU completion");
        }
        else host.submit();
        // Preserve all completed raw evidence before any diagnostic assertion
        // can terminate this process. No captured failure artifact is replaced.
        for(unsigned guide=0;guide<5;++guide)
            guides[guide]->save(outputDir/(std::string("guide_")+guideNames[guide]+".bin"));
        conditionedSpec.save(outputDir/"conditioned_spec.bin");conditionedDiff.save(outputDir/"conditioned_diff.bin");
        stagedSpec.save(outputDir/"rr_stage_spec.bin");stagedDiff.save(outputDir/"rr_stage_diff.bin");
        committedSpec.save(outputDir/"rr_committed_spec.bin");committedDiff.save(outputDir/"rr_committed_diff.bin");
        finalSpec.save(outputDir/"spec.bin");finalDiff.save(outputDir/"diff.bin");
        consumerSpecData.save(outputDir/"consumer_spec.bin");consumerDiffData.save(outputDir/"consumer_diff.bin");
        host.checkDebug();
        originalSpec.exact(frameDir/"spec.bin");originalDiff.exact(frameDir/"diff.bin");
        halfGainIdentity(originalSpec,conditionedSpec,fixedGain);halfGainIdentity(originalDiff,conditionedDiff,fixedGain);
        halfGainIdentity(committedSpec,finalSpec,1.f/fixedGain);halfGainIdentity(committedDiff,finalDiff,1.f/fixedGain);
        for(unsigned guide=0;guide<5;++guide)guides[guide]->exact(frameDir/(std::string(guideNames[guide])+".bin"));
        committedSpecCheck.verify(outputDir/"checked_committed_spec.rgba16f",width,height);
        committedDiffCheck.verify(outputDir/"checked_committed_diff.rgba16f",width,height);
        finalSpecCheck.verify(outputDir/"checked_final_spec.rgba16f",width,height);
        finalDiffCheck.verify(outputDir/"checked_final_diff.rgba16f",width,height);
        consumerSpec.consumerGpuRoundtrip(finalSpecCheck,finalSpecCheck,width,height,false);
        consumerDiff.consumerGpuRoundtrip(finalDiffCheck,finalDiffCheck,width,height,false);
        need(consumer.Flag()==0,"actual Consumer executes RGB branch after reciprocal inverse with unity exposure");
        std::ofstream diagnostic(outputDir/"stage-alpha-diagnostic.json");diagnostic<<std::setprecision(17);
        diagnostic<<"{\"frame\":"<<pose.frame<<",\"route\":\""<<(indirect?"id":"dd")<<"\",\"gain\":"<<fixedGain
            <<",\"signal_flags\":"<<FfxApiProxy::lastCreate.signalFlags<<",\"render_rect\":[0,0,"
            <<FfxApiProxy::lastDispatch.renderSize.width<<','<<FfxApiProxy::lastDispatch.renderSize.height
            <<"],\"context_max_render\":["<<FfxApiProxy::lastCreate.maxRenderSize.width<<','<<FfxApiProxy::lastCreate.maxRenderSize.height
            <<"],\"spec_output_extent\":["<<FfxApiProxy::lastSpecular.signal.output.description.width<<','<<FfxApiProxy::lastSpecular.signal.output.description.height
            <<"],\"diff_output_extent\":["<<FfxApiProxy::lastDiffuse.signal.output.description.width<<','<<FfxApiProxy::lastDiffuse.signal.output.description.height
            <<"],\"checkerboard_flags\":"<<FfxApiProxy::lastCreate.checkerboardSignalFlags
            <<",\"linear_depth_bounds\":["<<FfxApiProxy::lastDispatch.linearDepthBounds.min<<','<<FfxApiProxy::lastDispatch.linearDepthBounds.max
            <<"],\"core_input_gain_guide_opaque_alpha_consumer_checks_passed\":true,\"debug_errors\":0,\"debug_warnings\":0"
            <<",\"creates\":"<<FfxApiProxy::creates<<",\"destroys\":"<<FfxApiProxy::destroys
            <<",\"test_only_stage_initialization\":"<<(initializeStage?"true":"false")
            <<",\"stage_initialization_copies\":"<<initializationCopies<<",\"stage_initialization_bytes\":"<<initializationBytes
            <<",\"spec_input_api_state\":"<<FfxApiProxy::lastSpecular.signal.input.state
            <<",\"diff_input_api_state\":"<<FfxApiProxy::lastDiffuse.signal.input.state
            <<",\"spec_output_api_state\":"<<FfxApiProxy::lastSpecular.signal.output.state
            <<",\"diff_output_api_state\":"<<FfxApiProxy::lastDiffuse.signal.output.state
            <<",\"native_source_state\":"<<D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE
            <<",\"native_output_state\":"<<D3D12_RESOURCE_STATE_UNORDERED_ACCESS
            <<",\"native_state_evidence\":\"owned gain producer explicitly records UA-to-NPS; SDK call requires COMPUTE_READ; copy restores NPS/UA; strict D3D12 layer validates actual barriers\""
            <<",\"public_sdk_contract\":\"ID/IS A output Preserved (or input if passthrough); diagnostic tests input-word identity interpretation\""
            <<",\"private_sdk_dispatch_rects\":\"not observable through public dispatch adapter\",\"spec\":";
        stagedAlphaDiagnostic(conditionedSpec,stagedSpec,diagnostic);diagnostic<<",\"diff\":";
        stagedAlphaDiagnostic(conditionedDiff,stagedDiff,diagnostic);diagnostic<<"}\n";diagnostic.close();
        need(bool(diagnostic),"stage-alpha diagnostic evidence write completed before strict assertion");
        // Keep the original strict interpretation in this focused diagnostic;
        // any mismatch remains a negative result until independently reviewed.
        stagedHitIdentity(conditionedSpec,stagedSpec);stagedHitIdentity(conditionedDiff,stagedDiff);
        host.reset();
        UINT64* ticks=nullptr;hr(timing->Map(0,nullptr,reinterpret_cast<void**>(&ticks)));
        for(unsigned n=1;n<5;++n)need(ticks[n]>=ticks[n-1],"ordered GPU timestamp sequence");
        ResultFrame result;result.pose=pose;result.flags=FfxApiProxy::lastDispatch.flags;result.reset=frame.reset;result.previousValid=frame.previousValid;
        if(initializeStage)
        {
            need(ticks[5]>=ticks[1] && ticks[6]>=ticks[5] && ticks[2]>=ticks[6],"stage initialization timestamp interval is inside actual SDK dispatch window");
            result.initializationMs=double(ticks[6]-ticks[5])*1000/frequency;
        }
        result.inputMs=double(ticks[1]-ticks[0])*1000/frequency;result.rrMs=double(ticks[2]-ticks[1])*1000/frequency-result.initializationMs;
        result.inverseMs=double(ticks[3]-ticks[2])*1000/frequency;result.consumerMs=double(ticks[4]-ticks[3])*1000/frequency;
        timing->Unmap(0,nullptr);results.push_back(result);
    }
    host.checkDebug();need(FfxApiProxy::badCreateChains==0 && FfxApiProxy::badConfigureLayouts==0 && FfxApiProxy::badDefaults==0,
        "real context descriptor lifetime/default application/layout invariants retained");
    need(FfxApiProxy::creates==1 && FfxApiProxy::destroys==1 && FfxApiProxy::dispatches==frames,"exact signed-provider fresh context and sample counts");
    if(initializeStage)FfxApiProxy::dispatchFunction=actualSignedDispatch;
    std::ofstream json(output/"native-result.json");json<<std::setprecision(17);
    json<<"{\"schema\":\"fsrd-rr-conditioning-native-v1\",\"route\":\""<<(indirect?"id":"dd")<<"\",\"gain\":"<<fixedGain
        <<",\"defaults_probe\":"<<(probe?"true":"false")<<",\"checks\":"<<checks<<",\"creates\":"<<FfxApiProxy::creates
        <<",\"destroys\":"<<FfxApiProxy::destroys<<",\"dispatches\":"<<FfxApiProxy::dispatches
        <<",\"defaults\":"<<FfxApiProxy::defaults<<",\"configures\":"<<FfxApiProxy::configures
        <<",\"debug_errors\":0,\"debug_warnings\":0,\"native_debug_dispatches\":0,\"signal_flags\":"<<FfxApiProxy::lastCreate.signalFlags
        <<",\"diffuse_dispatch_type\":"<<FfxApiProxy::lastDiffuse.header.type<<",\"specular_dispatch_type\":"<<FfxApiProxy::lastSpecular.header.type
        <<",\"provider_version_id\":"<<FfxApiProxy::lastOverride<<",\"provider_api_version\":"<<FFX_DENOISER_VERSION
        <<",\"requested_mask\":"<<settings.overrideMask<<",\"default_words\":";writeWords(json,initialSettings.defaults);
    json<<",\"effective_words\":";writeWords(json,initialSettings.effective);
    json<<",\"owned_staging_bytes\":"<<warmedStaging<<",\"owned_auxiliary_bytes\":"<<warmedAuxiliary
        <<",\"test_only_stage_initialization\":"<<(initializeStage?"true":"false")
        <<",\"stage_initialization_copies\":"<<initializationCopies<<",\"stage_initialization_bytes\":"<<initializationBytes
        <<",\"timing_scope\":\"owned_RGB_gain_then_optional_test_only_stage_CopyResource_then_RR_RGB_commit_then_inverse_then_original_Consumer_GPU; initialization_separate; uploads_readbacks_CPU_setup_excluded\",\"frames\":[";
    for(unsigned i=0;i<results.size();++i)
    {
        if(i)json<<',';const auto& value=results[i];
        json<<"{\"frame\":"<<value.pose.frame<<",\"key_pose\":"<<value.pose.key<<",\"repeat\":"<<value.pose.repeat
            <<",\"reset\":"<<(value.reset?"true":"false")<<",\"previous_valid\":"<<(value.previousValid?"true":"false")
            <<",\"dispatch_flags\":"<<value.flags<<",\"input_gain_ms\":"<<value.inputMs<<",\"rr_stage_commit_ms\":"<<value.rrMs
            <<",\"staging_initialization_ms\":"<<value.initializationMs
            <<",\"inverse_gain_ms\":"<<value.inverseMs<<",\"consumer_ms\":"<<value.consumerMs
            <<",\"total_ms\":"<<value.inputMs+value.initializationMs+value.rrMs+value.inverseMs+value.consumerMs<<'}';
    }
    json<<"]}\n";need(bool(json),"research native result write");
    std::cout<<"research_checks="<<checks<<" frames="<<frames<<" route="<<(indirect?"id":"dd")<<" gain="<<fixedGain
        <<" creates="<<FfxApiProxy::creates<<" destroys="<<FfxApiProxy::destroys<<" debug_errors=0 debug_warnings=0\n";return 0;
}
}
int main(int argc,char** argv) try{return NrdConditioningResearch::run(argc,argv);}
catch(const std::exception& error){std::cerr<<"research failure: "<<error.what()<<'\n';return 1;}
