#include <d3dcompiler.h>
#include "precompile/FSRDNrdBridgePureCommit_Shader.h"
#include "precompile/FSRDNrdBridgeCommit_Shader.h" // ABI comparison only; never dispatched.

static void PureRootProof()
{
    ComPtr<ID3DBlob> pure,legacy;
    hr(D3DGetBlobPart(FSRDNrdBridgePureCommit_cso,sizeof(FSRDNrdBridgePureCommit_cso),D3D_BLOB_ROOT_SIGNATURE,0,&pure));
    hr(D3DGetBlobPart(FSRDNrdBridgeCommit_cso,sizeof(FSRDNrdBridgeCommit_cso),D3D_BLOB_ROOT_SIGNATURE,0,&legacy));
    need(pure->GetBufferSize()==legacy->GetBufferSize() &&
        std::memcmp(pure->GetBufferPointer(),legacy->GetBufferPointer(),pure->GetBufferSize())==0,"pure root ABI differs from retired legacy root");
    ComPtr<ID3D12VersionedRootSignatureDeserializer> reader;
    hr(D3D12CreateVersionedRootSignatureDeserializer(pure->GetBufferPointer(),pure->GetBufferSize(),IID_PPV_ARGS(&reader)));
    const D3D12_VERSIONED_ROOT_SIGNATURE_DESC* versioned=nullptr;
    hr(reader->GetRootSignatureDescAtVersion(D3D_ROOT_SIGNATURE_VERSION_1_0,&versioned));
    const auto& root=versioned->Desc_1_0;
    need(root.NumParameters==4 && root.NumStaticSamplers==0,"pure commit root parameter/sampler ABI");
    need(root.pParameters[0].ParameterType==D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS &&
        root.pParameters[0].Constants.Num32BitValues==5 && root.pParameters[0].Constants.ShaderRegister==0,
        "pure commit fiveDWORD b0 ABI");
    for(unsigned i=1;i<3;++i){const auto& table=root.pParameters[i];
        need(table.ParameterType==D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE && table.DescriptorTable.NumDescriptorRanges==1,"pure two separate tables");
        const auto& range=table.DescriptorTable.pDescriptorRanges[0];
        need(range.NumDescriptors==2 && range.BaseShaderRegister==0 && range.RegisterSpace==0 &&
            range.RangeType==(i==1?D3D12_DESCRIPTOR_RANGE_TYPE_SRV:D3D12_DESCRIPTOR_RANGE_TYPE_UAV),"pure exact twoSRV/twoUAV ABI");}
    need(root.pParameters[3].ParameterType==D3D12_ROOT_PARAMETER_TYPE_CBV &&
        root.pParameters[3].Descriptor.ShaderRegister==6 && root.pParameters[3].Descriptor.RegisterSpace==0,"pure b6space0 rootCBV ABI");
}

static void PureSetFlag(ID3D12Resource* buffer,uint32_t word)
{
    void* pointer=nullptr;D3D12_RANGE empty{0,0};hr(buffer->Map(0,&empty,&pointer));
    std::memset(pointer,0,1536);static_cast<uint32_t*>(pointer)[303]=word;buffer->Unmap(0,nullptr);
}

template<class Action> static void PureSubmitClosed(Fixture& fixture,Action afterClose)
{
    hr(fixture.list->Close());afterClose();
    ID3D12CommandList* lists[]{fixture.list.Get()};
    auto lease=RecordedComputeLease::BeforeSubmission(fixture.queue.Get(),{fixture.listIdentity.Get()});
    fixture.queue->ExecuteCommandLists(1,lists);RecordedComputeLease::AfterSubmission(lease);
    hr(fixture.queue->Signal(fixture.fence.Get(),++fixture.fenceValue));
    hr(fixture.fence->SetEventOnCompletion(fixture.fenceValue,fixture.event));
    need(WaitForSingleObject(fixture.event,30000)==WAIT_OBJECT_0,"pure commit GPU completion timeout");RecordedComputeLease::Poll();
}

int main(int argc,char** argv) try
{
    need(argc==2,"pure commit fixture requires output directory");const fs::path directory(argv[1]);
    constexpr uint32_t width=33,height=17;Fixture fixture(true);PureRootProof();
    ComPtr<ID3D12RootSignature> root;ComPtr<ID3D12PipelineState> pso;
    hr(fixture.device->CreateRootSignature(0,FSRDNrdBridgePureCommit_cso,sizeof(FSRDNrdBridgePureCommit_cso),IID_PPV_ARGS(&root)));
    D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline{};pipeline.pRootSignature=root.Get();
    pipeline.CS={FSRDNrdBridgePureCommit_cso,sizeof(FSRDNrdBridgePureCommit_cso)};
    hr(fixture.device->CreateComputePipelineState(&pipeline,IID_PPV_ARGS(&pso)));
    auto stageSpecBytes=load(directory/"stage-spec.bin"),stageDiffBytes=load(directory/"stage-diff.bin");
    auto stageSpec=fixture.Texture(width,height,DXGI_FORMAT_R16G16B16A16_FLOAT,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&stageSpecBytes);
    auto stageDiff=fixture.Texture(width,height,DXGI_FORMAT_R16G16B16A16_FLOAT,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&stageDiffBytes);
    NrdBridge::SignalFlagCapture capture;std::string error;need(capture.Initialize(fixture.device.Get(),error),error.c_str());
    auto first=fixture.Buffer(1536,D3D12_HEAP_TYPE_UPLOAD),second=fixture.Buffer(1536,D3D12_HEAP_TYPE_UPLOAD);
    PureSetFlag(first.Get(),0);PureSetFlag(second.Get(),0);fixture.Submit();fixture.Reset();
    struct Case{uint32_t binding,flag,encoding;};
    const std::array<Case,10> cases{{{0,0,0},{0,0,1},{1,0,1},{1,1,0},{1,0x80000000u,0},{1,0x7fc00000u,0},
        {2,0,1},{2,1,0},{2,0x80000000u,0},{2,0x7fc00000u,0}}};
    constexpr std::array<uint32_t,6> coefficients{0u,0x3ec00000u,0x3f800000u,0x7fc12345u,0x7f800000u,0xff800000u};
    uint64_t comparedWords=0,completed=0,nativeFlags=0;
    for(const auto test:cases)for(const auto coefficient:coefficients)for(unsigned perturbation=0;perturbation<5;++perturbation)
    {
        const auto encoding=test.binding?(test.flag!=0u):test.encoding;
        const auto specBytes=load(directory/("title"+std::to_string(perturbation)+"-spec.bin"));
        const auto diffBytes=load(directory/("title"+std::to_string(perturbation)+"-diff.bin"));
        auto titleSpec=fixture.Texture(width,height,DXGI_FORMAT_R16G16B16A16_FLOAT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,&specBytes);
        auto titleDiff=fixture.Texture(width,height,DXGI_FORMAT_R16G16B16A16_FLOAT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,&diffBytes);
        D3D12_DESCRIPTOR_HEAP_DESC heapDesc{};heapDesc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        heapDesc.NumDescriptors=4;heapDesc.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        ComPtr<ID3D12DescriptorHeap> heap;hr(fixture.device->CreateDescriptorHeap(&heapDesc,IID_PPV_ARGS(&heap)));
        const auto stride=fixture.device->GetDescriptorHandleIncrementSize(heapDesc.Type);auto cpu=heap->GetCPUDescriptorHandleForHeapStart();
        for(auto* source:{stageSpec.Get(),stageDiff.Get()}){D3D12_SHADER_RESOURCE_VIEW_DESC srv{};srv.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;
            srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;srv.Texture2D.MipLevels=1;srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            fixture.device->CreateShaderResourceView(source,&srv,cpu);cpu.ptr+=stride;}
        for(auto* destination:{titleSpec.Get(),titleDiff.Get()}){D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};uav.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;
            uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;fixture.device->CreateUnorderedAccessView(destination,nullptr,&uav,cpu);cpu.ptr+=stride;}
        NrdBridge::SignalFlagSnapshot shadow;ComPtr<ID3D12DescriptorHeap> nativeHeap;
        if(test.binding)
        {
            PureSetFlag(first.Get(),test.flag?0u:1u);PureSetFlag(second.Get(),test.flag?0u:1u);
            NrdBridge::TitleSignalConstants constants{nullptr,first->GetGPUVirtualAddress()};
            if(test.binding==2){auto desc=heapDesc;desc.NumDescriptors=1;
                hr(fixture.device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&nativeHeap)));
                D3D12_CONSTANT_BUFFER_VIEW_DESC cbv{first->GetGPUVirtualAddress(),1536};
                fixture.device->CreateConstantBufferView(&cbv,nativeHeap->GetCPUDescriptorHandleForHeapStart());
                constants.nativeHeap=nativeHeap.Get();constants.cbvHandle=nativeHeap->GetGPUDescriptorHandleForHeapStart();}
            need(NrdBridge::ValidateTitleSignalConstants(constants,fixture.device.Get(),error),error.c_str());
            need(shadow.Initialize(fixture.device.Get(),error),error.c_str());capture.Record(fixture.list.Get(),constants,shadow);++nativeFlags;
        }
        fixture.list->SetPipelineState(pso.Get());fixture.list->SetComputeRootSignature(root.Get());
        ID3D12DescriptorHeap* active[]{heap.Get()};fixture.list->SetDescriptorHeaps(1,active);
        const uint32_t words[]{width,height,test.encoding,test.binding?1u:0u,coefficient};
        fixture.list->SetComputeRoot32BitConstants(0,5,words,0);
        auto gpu=heap->GetGPUDescriptorHandleForHeapStart();fixture.list->SetComputeRootDescriptorTable(1,gpu);
        gpu.ptr+=2u*stride;fixture.list->SetComputeRootDescriptorTable(2,gpu);
        fixture.list->SetComputeRootConstantBufferView(3,test.binding?shadow.resource->GetGPUVirtualAddress():first->GetGPUVirtualAddress());
        fixture.list->Dispatch((width+7)/8,(height+7)/8,1);if(test.binding)shadow.Transition(fixture.list.Get(),false);
        auto specRead=fixture.Snapshot(titleSpec.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        auto diffRead=fixture.Snapshot(titleDiff.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        PureSubmitClosed(fixture,[&]{
            // The old table buffer deliberately stays WRONG: only the descriptor
            // replacement, performed after Close, can select the expected flag.
            if(test.binding==2){PureSetFlag(second.Get(),test.flag);
                D3D12_CONSTANT_BUFFER_VIEW_DESC cbv{second->GetGPUVirtualAddress(),1536};
                fixture.device->CreateConstantBufferView(&cbv,nativeHeap->GetCPUDescriptorHandleForHeapStart());}
            else PureSetFlag(first.Get(),test.flag);});
        const auto actualSpec=specRead.Data(),actualDiff=diffRead.Data();
        const auto expectedSpec=load(directory/("expected"+std::to_string(encoding)+"-spec.bin"));
        const auto expectedDiff=load(directory/("expected"+std::to_string(encoding)+"-diff.bin"));
        for(const auto pair:{std::pair{&actualSpec,&expectedSpec},std::pair{&actualDiff,&expectedDiff}})
        {need(pair.first->size()==pair.second->size(),"pure output byte count");const auto* a=reinterpret_cast<const uint16_t*>(pair.first->data());
            const auto* b=reinterpret_cast<const uint16_t*>(pair.second->data());for(size_t i=0;i<pair.first->size()/2;++i)
                {if(a[i]!=b[i])std::cerr<<"case="<<completed<<" binding="<<test.binding<<" flag="<<test.flag
                    <<" coefficient="<<coefficient<<" perturbation="<<perturbation<<" word="<<i
                    <<" actual="<<a[i]<<" expected="<<b[i]<<'\n';
                 need(a[i]==b[i],"pure commit changed fixed RR RGB or opaque title alpha");++comparedWords;}}
        ++completed;fixture.Reset();
    }
    need(completed==300 && nativeFlags==240 && comparedWords==uint64_t(300)*width*height*8,"pure complete prescribed test matrix");
    hr(fixture.list->Close());fixture.Validate();
    std::cout<<"pure_commit PASS checks="<<checks<<" cases="<<completed<<" gpu_flag_captures="<<nativeFlags
        <<" exact_rgba_words="<<comparedWords<<" native_rgb_variants=5 coefficient_bitpatterns=6 closed_root_cbv_update=1 closed_table_replacement=1 legacy_root_abi_exact=1\n";
    return 0;
}
catch(const std::exception& error){std::cerr<<"pure_commit FAIL checks="<<checks<<": "<<error.what()<<'\n';return 1;}
