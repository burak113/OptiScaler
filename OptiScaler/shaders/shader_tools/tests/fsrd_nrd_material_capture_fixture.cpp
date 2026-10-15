// The driver prefixes the existing native D3D fixture's texture/submission code.
// Native GPU objects and the full RecordedComputeLease registry are real. Hook
// adapters are explicit; this does not test detour installation/NativeBirth.
#include "material_guides_shader.h"
#include "material_quantization_shader.h"

template<class T> static std::vector<char> MaterialBytes(const std::vector<T>& values)
{
    std::vector<char> bytes(values.size()*sizeof(T));
    memcpy(bytes.data(),values.data(),bytes.size()); return bytes;
}
static ULONG MaterialReferences(ID3D12Resource* resource)
{ const auto count = resource->AddRef(); resource->Release(); return count; }

static void MaterialGuides(Fixture& fixture, ID3D12Resource* material, const fs::path& output,
                           uint32_t width, uint32_t height, const std::string& prefix = {})
{
    const auto nrBytes = load(output/"normal.bin"), noVBytes = load(output/"nov.bin");
    auto nr = fixture.Texture(width,height,DXGI_FORMAT_R32G32B32A32_FLOAT,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&nrBytes);
    auto noV = fixture.Texture(width,height,DXGI_FORMAT_R32_FLOAT,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&noVBytes);
    auto diff = fixture.Texture(width,height,DXGI_FORMAT_R32G32B32A32_FLOAT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    auto spec = fixture.Texture(width,height,DXGI_FORMAT_R32G32B32A32_FLOAT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    ComPtr<ID3D12RootSignature> root; ComPtr<ID3D12PipelineState> pso;
    hr(fixture.device->CreateRootSignature(0,MaterialGuidesShader,sizeof(MaterialGuidesShader),IID_PPV_ARGS(&root)));
    D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline {}; pipeline.pRootSignature = root.Get();
    pipeline.CS = {MaterialGuidesShader,sizeof(MaterialGuidesShader)};
    hr(fixture.device->CreateComputePipelineState(&pipeline,IID_PPV_ARGS(&pso)));
    D3D12_DESCRIPTOR_HEAP_DESC desc {}; desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE; desc.NumDescriptors = 5;
    ComPtr<ID3D12DescriptorHeap> heap; hr(fixture.device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&heap)));
    const auto stride = fixture.device->GetDescriptorHandleIncrementSize(desc.Type);
    auto cpu = heap->GetCPUDescriptorHandleForHeapStart();
    for (auto* input : {material,nr.Get(),noV.Get()})
    {
        D3D12_SHADER_RESOURCE_VIEW_DESC srv {}; srv.Format = input->GetDesc().Format;
        srv.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D; srv.Texture2D.MipLevels = 1;
        srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        fixture.device->CreateShaderResourceView(input,&srv,cpu); cpu.ptr += stride;
    }
    for (auto* target : {diff.Get(),spec.Get()})
    {
        D3D12_UNORDERED_ACCESS_VIEW_DESC uav {}; uav.Format = target->GetDesc().Format;
        uav.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
        fixture.device->CreateUnorderedAccessView(target,nullptr,&uav,cpu); cpu.ptr += stride;
    }
    fixture.list->SetPipelineState(pso.Get()); fixture.list->SetComputeRootSignature(root.Get());
    ID3D12DescriptorHeap* heaps[] = {heap.Get()}; fixture.list->SetDescriptorHeaps(1,heaps);
    const uint32_t extent[] = {width,height}; fixture.list->SetComputeRoot32BitConstants(0,2,extent,0);
    auto gpu = heap->GetGPUDescriptorHandleForHeapStart(); fixture.list->SetComputeRootDescriptorTable(1,gpu);
    gpu.ptr += uint64_t(stride)*3; fixture.list->SetComputeRootDescriptorTable(2,gpu);
    fixture.list->Dispatch((width+7)/8,(height+7)/8,1);
    auto diffRead = fixture.Snapshot(diff.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    auto specRead = fixture.Snapshot(spec.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    fixture.Submit(); save(output/(prefix+"diffuse.bin"),diffRead.Data()); save(output/(prefix+"specular.bin"),specRead.Data());
    fixture.Reset();
}


static void MaterialQuantization(Fixture& fixture,const fs::path& output)
{
    uint32_t width=0,height=0;std::ifstream size(output/"quantization-size.txt");size>>width>>height;
    need(bool(size) && width>0 && height>0,"quantizer extent missing");
    const auto bytes=load(output/"quantization-input.bin");
    need(bytes.size()==uint64_t(width)*height*16,"quantizer input byte count mismatch");
    auto input=fixture.Texture(width,height,DXGI_FORMAT_R32G32B32A32_FLOAT,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&bytes);
    auto full=fixture.Texture(width,height,DXGI_FORMAT_R32G32B32A32_FLOAT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    auto half=fixture.Texture(width,height,DXGI_FORMAT_R16G16B16A16_FLOAT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    ComPtr<ID3D12RootSignature> root;ComPtr<ID3D12PipelineState> pso;
    hr(fixture.device->CreateRootSignature(0,MaterialQuantizationShader,sizeof(MaterialQuantizationShader),IID_PPV_ARGS(&root)));
    D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline {};pipeline.pRootSignature=root.Get();
    pipeline.CS={MaterialQuantizationShader,sizeof(MaterialQuantizationShader)};
    hr(fixture.device->CreateComputePipelineState(&pipeline,IID_PPV_ARGS(&pso)));
    D3D12_DESCRIPTOR_HEAP_DESC desc {};desc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    desc.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;desc.NumDescriptors=3;
    ComPtr<ID3D12DescriptorHeap> heap;hr(fixture.device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&heap)));
    const auto stride=fixture.device->GetDescriptorHandleIncrementSize(desc.Type);
    auto cpu=heap->GetCPUDescriptorHandleForHeapStart();
    D3D12_SHADER_RESOURCE_VIEW_DESC srv {};srv.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
    srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;srv.Texture2D.MipLevels=1;
    srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    fixture.device->CreateShaderResourceView(input.Get(),&srv,cpu);cpu.ptr+=stride;
    for(auto* target:{full.Get(),half.Get()})
    {
        D3D12_UNORDERED_ACCESS_VIEW_DESC uav {};uav.Format=target->GetDesc().Format;
        uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
        fixture.device->CreateUnorderedAccessView(target,nullptr,&uav,cpu);cpu.ptr+=stride;
    }
    fixture.list->SetPipelineState(pso.Get());fixture.list->SetComputeRootSignature(root.Get());
    ID3D12DescriptorHeap* heaps[]={heap.Get()};fixture.list->SetDescriptorHeaps(1,heaps);
    const uint32_t extent[]={width,height};fixture.list->SetComputeRoot32BitConstants(0,2,extent,0);
    auto gpu=heap->GetGPUDescriptorHandleForHeapStart();fixture.list->SetComputeRootDescriptorTable(1,gpu);
    gpu.ptr+=stride;fixture.list->SetComputeRootDescriptorTable(2,gpu);
    fixture.list->Dispatch((width+7)/8,(height+7)/8,1);
    auto fullRead=fixture.Snapshot(full.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    auto halfRead=fixture.Snapshot(half.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    fixture.Submit();save(output/"quantization-float.bin",fullRead.Data());save(output/"quantization-half.bin",halfRead.Data());
    fixture.Reset();
}

static void MaterialTimings(Fixture& fixture,uint32_t width,uint32_t height)
{
    constexpr UINT samples=12;
    auto baseBytes=MaterialBytes(std::vector<uint32_t>(size_t(width)*height,0x355a93ffu));
    auto paramsBytes=MaterialBytes(std::vector<uint32_t>(size_t(width)*height,0xe34b7f80u));
    auto base=fixture.Texture(width,height,DXGI_FORMAT_R10G10B10A2_UNORM,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&baseBytes);
    auto params=fixture.Texture(width,height,DXGI_FORMAT_R8G8B8A8_UNORM,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&paramsBytes);
    gMaterialTitleSources.insert(base.Get()); gMaterialTitleSources.insert(params.Get());
    NrdBridge::NativeMaterialCapture capture; std::string error;
    need(capture.Initialize(fixture.device.Get(),width,height,error),error.c_str());
    D3D12_QUERY_HEAP_DESC queryDesc {}; queryDesc.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP; queryDesc.Count=samples*2;
    ComPtr<ID3D12QueryHeap> query;hr(fixture.device->CreateQueryHeap(&queryDesc,IID_PPV_ARGS(&query)));
    auto buffer=fixture.Buffer(samples*2*sizeof(uint64_t),D3D12_HEAP_TYPE_READBACK);
    for(UINT i=0;i<samples;++i)
    {
        NrdBridge::NativeMaterialCapture::SnapshotLease lease;
        fixture.list->EndQuery(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,i*2);
        need(capture.Capture(fixture.list.Get(),base.Get(),params.Get(),lease,error),error.c_str());
        fixture.list->EndQuery(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,i*2+1);
    }
    fixture.list->ResolveQueryData(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,samples*2,buffer.Get(),0);
    fixture.Submit();uint64_t frequency=0;hr(fixture.queue->GetTimestampFrequency(&frequency));need(frequency>0,"timestamp frequency missing");
    void* mapped=nullptr;D3D12_RANGE range{0,samples*2*sizeof(uint64_t)};hr(buffer->Map(0,&range,&mapped));
    auto* ticks=static_cast<const uint64_t*>(mapped);
    std::cout<<"MATERIAL_TIMING {\"width\":"<<width<<",\"height\":"<<height
             <<",\"warmup\":4,\"owned_bytes\":"<<capture.OwnedAuxiliaryBytes()<<",\"gpu_ms\":[";
    for(UINT i=0;i<samples;++i){need(ticks[i*2+1]>ticks[i*2],"nonpositive GPU timestamp");if(i)std::cout<<',';
        std::cout<<std::setprecision(10)<<double(ticks[i*2+1]-ticks[i*2])*1000.0/double(frequency);}
    std::cout<<"]}\n";const D3D12_RANGE empty{0,0};buffer->Unmap(0,&empty);
    fixture.Reset();gMaterialTitleSources.erase(base.Get());gMaterialTitleSources.erase(params.Get());
}

static void MaterialKnownStates(Fixture& fixture,NrdBridge::NativeMaterialCapture& capture,
                                const fs::path& output,uint32_t width,uint32_t height)
{
    using Capture=NrdBridge::NativeMaterialCapture;
    constexpr auto nps=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    const std::array<Capture::SourceStates,6> cases {{{D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE},
        {D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COMMON},
        {D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_UNORDERED_ACCESS},
        {D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,nps},{D3D12_RESOURCE_STATE_GENERIC_READ,nps},
        {D3D12_RESOURCE_STATES(D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|nps),nps}}};
    const auto baseBytes=load(output/"base.bin"),paramsBytes=load(output/"params.bin"),expected=load(output/"material.bin");
    for(const auto& states : cases)
    {
        auto base=fixture.Texture(width,height,DXGI_FORMAT_R10G10B10A2_UNORM,states[0],&baseBytes);
        auto params=fixture.Texture(width,height,DXGI_FORMAT_R8G8B8A8_UNORM,states[1],&paramsBytes);
        gMaterialTitleSources.insert(base.Get());gMaterialTitleSources.insert(params.Get());
        gMaterialSourceStates={{base.Get(),states[0]},{params.Get(),states[1]}};
        gMaterialAllowKnownSourceBarriers=true;
        const auto transitions=gMaterialSourceTransitions,uavBarriers=gMaterialSourceUavBarriers;
        const auto barriers=gMaterialPrivateBarriers,dispatches=gMaterialDispatches;
        const auto baseRefs=MaterialReferences(base.Get()),paramsRefs=MaterialReferences(params.Get());
        Capture::SnapshotLease lease;std::string error;
        RecordedComputeLease::SetHooksAvailable(false,false);
        need(!capture.Capture(fixture.list.Get(),base.Get(),params.Get(),states,lease,error),"known-state capture ignored failed lease");
        need(!lease && gMaterialPrivateBarriers==barriers && gMaterialDispatches==dispatches,
             "failed known-state retain recorded title/owned commands");
        RecordedComputeLease::SetHooksAvailable(true,true);
        need(capture.Capture(fixture.list.Get(),base.Get(),params.Get(),states,lease,error),error.c_str());
        unsigned changed=0,uavs=0;
        for(auto state:states){changed+=!(state&nps);uavs+=state==D3D12_RESOURCE_STATE_UNORDERED_ACCESS;}
        need(gMaterialSourceTransitions-transitions==changed*2,"every changed source has one enter and exact restore");
        need(gMaterialSourceUavBarriers-uavBarriers==uavs,"every UAV source has explicit ordering before transition");
        need(gMaterialSourceStates.at(base.Get())==states[0] && gMaterialSourceStates.at(params.Get())==states[1],
             "capture did not restore both exact title states");
        need(MaterialReferences(base.Get())==baseRefs && MaterialReferences(params.Get())==paramsRefs,
             "known-state capture retained a title source COM owner");
        const auto beforeReject=gMaterialPrivateBarriers;
        Capture::SnapshotLease invalid;
        need(!capture.Capture(fixture.list.Get(),base.Get(),params.Get(),
             {D3D12_RESOURCE_STATE_RENDER_TARGET,nps},invalid,error),"unsupported source state admitted");
        need(!invalid && gMaterialPrivateBarriers==beforeReject && gMaterialDispatches==dispatches+1,
             "unsupported exact state recorded GPU work");
        auto read=fixture.Snapshot(capture.Resource(lease),D3D12_RESOURCE_STATE_COMMON);
        auto baseRead=fixture.Snapshot(base.Get(),states[0]),paramsRead=fixture.Snapshot(params.Get(),states[1]);
        std::weak_ptr<void> deferred=lease;lease.reset();
        need(!deferred.expired(),"known-state snapshot was not retained for executable recording");
        fixture.Submit();
        need(read.Data()==expected,"temporary source states changed captured material numerics");
        need(baseRead.Data()==baseBytes && paramsRead.Data()==paramsBytes,"known-state capture altered title pixels");
        need(!deferred.expired(),"completed fence dropped still-executable known-state snapshot");
        fixture.Reset();need(deferred.expired(),"successful Reset did not retire known-state lease");
        gMaterialAllowKnownSourceBarriers=false;gMaterialSourceStates.clear();
        gMaterialTitleSources.erase(base.Get());gMaterialTitleSources.erase(params.Get());
    }
}

int main(int argc, char** argv) try
{
    need(argc == 2,"material fixture needs an output directory"); const fs::path output(argv[1]);
    constexpr uint32_t width = 127, height = 65; Fixture fixture(true);
    const auto baseBytes = load(output/"base.bin"), paramsBytes = load(output/"params.bin");
    auto base = fixture.Texture(width,height,DXGI_FORMAT_R10G10B10A2_UNORM,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&baseBytes);
    auto params = fixture.Texture(width,height,DXGI_FORMAT_R8G8B8A8_UNORM,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&paramsBytes);
    gMaterialTitleSources = {base.Get(),params.Get()};
    const auto baseRefs = MaterialReferences(base.Get()), paramsRefs = MaterialReferences(params.Get());
    NrdBridge::NativeMaterialCapture capture; std::string error;
    need(capture.OwnedAuxiliaryBytes()==0,"construction allocated material resources");
    need(!capture.Initialize(nullptr,width,height,error),"null initialization admitted");
    need(!capture.Initialize(fixture.device.Get(),0,height,error),"zero extent admitted");
    need(!capture.Initialize(fixture.device.Get(),UINT32_MAX,height,error),"oversized extent admitted");
    need(capture.Initialize(fixture.device.Get(),width,height,error),error.c_str());
    need(capture.OwnedAuxiliaryBytes()==0,"initialization allocated a snapshot before Capture");
    NrdBridge::NativeMaterialCapture::SnapshotLease current;
    const auto before = gMaterialDispatches;
    need(!capture.Capture(nullptr,base.Get(),params.Get(),current,error),"null list admitted");
    need(!capture.Capture(fixture.list.Get(),nullptr,params.Get(),current,error),"null source admitted");
    need(!capture.Capture(fixture.list.Get(),params.Get(),base.Get(),current,error),"swapped formats admitted");
    auto badExtent = fixture.Texture(width+1,height,DXGI_FORMAT_R10G10B10A2_UNORM,
                                    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    need(!capture.Capture(fixture.list.Get(),badExtent.Get(),params.Get(),current,error),"wrong extent admitted");
    need(gMaterialDispatches==before && !current,"invalid source recorded a material pass");
    RecordedComputeLease::SetHooksAvailable(false,false);
    need(!capture.Capture(fixture.list.Get(),base.Get(),params.Get(),current,error),"missing GPU lease admitted");
    need(gMaterialDispatches==before && !current,"failed GPU lease recorded a material pass");
    RecordedComputeLease::SetHooksAvailable(true,true);
    std::vector<NrdBridge::NativeMaterialCapture::SnapshotLease> leases;
    std::vector<ID3D12Resource*> identities;
    for (uint32_t i=0;i<32;++i)
    {
        need(capture.Capture(fixture.list.Get(),base.Get(),params.Get(),current,error),error.c_str());
        auto* resource = capture.Resource(current); need(resource != nullptr,"material output missing");
        need(std::find(identities.begin(),identities.end(),resource)==identities.end(),"in-flight material slot reused");
        need(resource->GetDesc().Format==DXGI_FORMAT_R16G16B16A16_FLOAT,"snapshot format changed");
        identities.push_back(resource); leases.push_back(std::move(current));
    }
    const auto beforeExhausted = gMaterialDispatches;
    need(!capture.Capture(fixture.list.Get(),base.Get(),params.Get(),current,error),"33rd in-flight slot admitted");
    need(gMaterialDispatches==beforeExhausted && !current,"exhaustion recorded GPU work");
    need(capture.OwnedAuxiliaryBytes()>uint64_t(width)*height*8,"snapshot allocation bytes omitted");
    auto read = fixture.Snapshot(capture.Resource(leases.front()),D3D12_RESOURCE_STATE_COMMON);
    auto titleBaseRead = fixture.Snapshot(base.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    auto titleParamsRead = fixture.Snapshot(params.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    std::weak_ptr<void> deferred = leases.front(); leases.clear();
    need(!deferred.expired(),"caller reset destroyed an executable GPU snapshot");
    need(MaterialReferences(base.Get())==baseRefs && MaterialReferences(params.Get())==paramsRefs,
         "capture retained a borrowed title texture");
    fixture.Submit();
    need(!deferred.expired(),"fence-only completion destroyed an executable GPU snapshot");
    save(output/"material.bin",read.Data());
    need(titleBaseRead.Data()==baseBytes && titleParamsRead.Data()==paramsBytes,"material capture changed title input bytes");
    fixture.Reset(); need(deferred.expired(),"completed successful Reset did not retire material lease");
    need(capture.Capture(fixture.list.Get(),base.Get(),params.Get(),current,error),error.c_str());
    need(capture.Resource(current)==identities.front(),"retired material slot was not recycled");
    MaterialGuides(fixture,capture.Resource(current),output,width,height);
    current.reset();
    auto malformedBytes = load(output/"invalid-material.bin");
    auto malformed = fixture.Texture(width,height,DXGI_FORMAT_R16G16B16A16_FLOAT,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&malformedBytes);
    MaterialGuides(fixture,malformed.Get(),output,width,height,"invalid-");
    need(MaterialReferences(base.Get())==baseRefs && MaterialReferences(params.Get())==paramsRefs,
         "guidance path changed title refcounts");
    need(gMaterialSourceBarriers==0,"material capture transitioned title source");
    need(gMaterialDispatches==33,"unexpected production material dispatch count");
    need(RecordedComputeLease::GetRegistry().recordings.empty() &&
         RecordedComputeLease::GetRegistry().submissions.empty(),"material recording leases leaked");
    MaterialKnownStates(fixture,capture,output,width,height);
    need(RecordedComputeLease::GetRegistry().recordings.empty() &&
         RecordedComputeLease::GetRegistry().submissions.empty(),"known-state recording leases leaked");
    MaterialQuantization(fixture,output);
    MaterialTimings(fixture,1505,847);
    MaterialTimings(fixture,2560,1440);
    fixture.Validate();
    std::cout << "PASS " << checks << " native_material_checks dispatches=" << gMaterialDispatches
              << " audited_private_barriers=" << gMaterialPrivateBarriers << "\n";
    return 0;
}
catch(const std::exception& exception)
{ std::cerr << "FAIL " << checks << " " << exception.what() << "\n"; return 1; }
