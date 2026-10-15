// Prefixed with the original actual-D3D Fixture and production conversion .cpp.
// Only app/hook adapters are substituted. Source objects, recorded leases,
// submissions, readbacks, descriptor/root layouts and debug validation are real.
static ULONG ParamsReferences(ID3D12Resource* resource)
{ const auto count = resource->AddRef(); resource->Release(); return count; }

static NrdBridge::FrameParameters ParamsFrame(uint32_t width, uint32_t height)
{
    NrdBridge::FrameParameters frame;
    frame.reset = true; frame.previousValid = false; frame.nearPlane = .01f;
    frame.farPlane = 65504.0f; frame.depthSign = -1; frame.preserveNativeMaterialIDs = true;
    const float sy = 1.0f / std::tan(3.14159265358979323846f / 6.0f);
    frame.camera.view = frame.camera.inverseView = DirectX::XMMatrixIdentity();
    frame.camera.projection = DirectX::XMMatrixSet(sy/(float(width)/height),0,0,0,
        0,sy,0,0, 0,0,0,frame.nearPlane, 0,0,-1,0);
    frame.camera.isRightHanded = true;
    frame.camera.viewSource = frame.camera.projectionSource = FSRDCamera::Source::StreamlineMatrix;
    return frame;
}

static void SaveParamsOutputs(Fixture& fixture, const fs::path& directory,
                              const std::string& prefix, const NrdBridge::ConvertedResources& resources)
{
    const std::array<ID3D12Resource*,7> outputs {resources.spec,resources.diff,resources.normals,
        resources.linearDepth,resources.motion,resources.specAlbedo,resources.diffAlbedo};
    const std::array<const char*,7> names {"spec","diff","nr","depth","motion","spec-albedo","diff-albedo"};
    std::array<Readback,7> reads;
    for (size_t i=0;i<reads.size();++i)
        reads[i]=fixture.Snapshot(outputs[i],D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    fixture.Submit();
    for (size_t i=0;i<reads.size();++i) save(directory/(prefix+"-"+names[i]+".bin"),reads[i].Data());
    fixture.Reset();
}

static void ParamsTimings(Fixture& fixture,uint32_t width,uint32_t height)
{
    constexpr UINT samples=12;
    std::vector<char> rgba8(size_t(width)*height*4),rgba16(size_t(width)*height*8);
    auto base=fixture.Texture(width,height,DXGI_FORMAT_R10G10B10A2_UNORM,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&rgba8);
    auto params=fixture.Texture(width,height,DXGI_FORMAT_R8G8B8A8_UNORM,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&rgba8);
    auto spec=fixture.Texture(width,height,DXGI_FORMAT_R16G16B16A16_FLOAT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,&rgba16);
    auto diff=fixture.Texture(width,height,DXGI_FORMAT_R16G16B16A16_FLOAT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,&rgba16);
    auto nr=fixture.Texture(width,height,DXGI_FORMAT_R10G10B10A2_UNORM,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&rgba8);
    auto depth=fixture.Texture(width,height,DXGI_FORMAT_R32_FLOAT,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&rgba8);
    auto motion=fixture.Texture(width,height,DXGI_FORMAT_R16G16B16A16_FLOAT,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&rgba16);
    NrdBridge::NativeMaterialCapture capture; NrdBridge::ConversionPass conversion;std::string error;
    need(capture.InitializeParams(fixture.device.Get(),width,height,error),error.c_str());
    need(conversion.Initialize(fixture.device.Get(),width,height,error),error.c_str());
    auto frame=ParamsFrame(width,height);frame.nativeMaterialGuides=true;
    D3D12_QUERY_HEAP_DESC queryDesc{};queryDesc.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;queryDesc.Count=samples*4;
    ComPtr<ID3D12QueryHeap> query;hr(fixture.device->CreateQueryHeap(&queryDesc,IID_PPV_ARGS(&query)));
    auto readback=fixture.Buffer(samples*4*sizeof(uint64_t),D3D12_HEAP_TYPE_READBACK);
    for(UINT i=0;i<samples;++i)
    {
        NrdBridge::NativeMaterialCapture::SnapshotLease snapshot;
        fixture.list->EndQuery(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,i*4);
        need(capture.CaptureParams(fixture.list.Get(),base.Get(),params.Get(),snapshot,error),error.c_str());
        fixture.list->EndQuery(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,i*4+1);
        NrdBridge::ConversionInputs inputs {spec.Get(),diff.Get(),nr.Get(),depth.Get(),motion.Get(),
            capture.Resource(snapshot),capture.RoughnessResource(snapshot)};
        NrdBridge::ConvertedResources output;
        fixture.list->EndQuery(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,i*4+2);
        need(conversion.Dispatch(fixture.list.Get(),inputs,frame,output,error),error.c_str());
        fixture.list->EndQuery(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,i*4+3);
    }
    fixture.list->ResolveQueryData(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,samples*4,readback.Get(),0);
    fixture.Submit();uint64_t frequency=0;hr(fixture.queue->GetTimestampFrequency(&frequency));need(frequency!=0,"timestamp frequency missing");
    void* mapped=nullptr;D3D12_RANGE range{0,samples*4*sizeof(uint64_t)};hr(readback->Map(0,&range,&mapped));
    const auto* ticks=static_cast<const uint64_t*>(mapped);
    std::cout<<"PARAMS_TIMING {\"width\":"<<width<<",\"height\":"<<height<<",\"warmup\":4,\"capture_owned_bytes\":"
             <<capture.OwnedAuxiliaryBytes()<<",\"conversion_owned_bytes\":"<<conversion.OwnedTextureBytes()<<",\"capture_ms\":[";
    for(UINT i=0;i<samples;++i){need(ticks[i*4+1]>ticks[i*4],"capture timestamp invalid");if(i)std::cout<<',';
        std::cout<<std::setprecision(10)<<double(ticks[i*4+1]-ticks[i*4])*1000.0/double(frequency);}
    std::cout<<"],\"conversion_ms\":[";
    for(UINT i=0;i<samples;++i){need(ticks[i*4+3]>ticks[i*4+2],"conversion timestamp invalid");if(i)std::cout<<',';
        std::cout<<std::setprecision(10)<<double(ticks[i*4+3]-ticks[i*4+2])*1000.0/double(frequency);}
    std::cout<<"]}\n";const D3D12_RANGE empty{0,0};readback->Unmap(0,&empty);fixture.Reset();
}

int main(int argc,char** argv) try
{
    need(argc==2,"materialParams fixture requires output directory");const fs::path directory(argv[1]);
    constexpr uint32_t width=127,height=65;Fixture fixture(true);std::string error;
    const auto baseBytes=load(directory/"base.bin"),paramsBytes=load(directory/"params.bin");
    auto base=fixture.Texture(width,height,DXGI_FORMAT_R10G10B10A2_UNORM,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&baseBytes);
    auto params=fixture.Texture(width,height,DXGI_FORMAT_R8G8B8A8_UNORM,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&paramsBytes);
    const auto baseRefs=ParamsReferences(base.Get()),paramsRefs=ParamsReferences(params.Get());
    NrdBridge::NativeMaterialCapture capture;
    need(capture.Initialize(fixture.device.Get(),width,height,error),error.c_str());
    NrdBridge::NativeMaterialCapture::SnapshotLease legacy,snapshot;
    need(capture.Capture(fixture.list.Get(),base.Get(),params.Get(),legacy,error),error.c_str());
    need(!capture.RoughnessResource(legacy),"legacy Capture unexpectedly acquired new roughness resource");
    need(capture.InitializeParams(fixture.device.Get(),width,height,error),error.c_str());
    need(capture.CaptureParams(fixture.list.Get(),base.Get(),params.Get(),snapshot,error),error.c_str());
    auto* roughness=capture.RoughnessResource(snapshot);
    need(roughness && roughness!=capture.Resource(snapshot),"roughness capture output missing/aliased");
    const auto roughnessDesc=roughness->GetDesc();
    need(roughnessDesc.Format==DXGI_FORMAT_R16_FLOAT && roughnessDesc.Width==width && roughnessDesc.Height==height,
        "roughness capture format/shape changed");
    std::vector<NrdBridge::NativeMaterialCapture::SnapshotLease> budgetSnapshots;
    std::vector<ID3D12Resource*> baseIdentities{capture.Resource(snapshot)},roughnessIdentities{roughness};
    auto allocationBytes=[&](ID3D12Resource* resource){const auto desc=resource->GetDesc();
        const auto result=fixture.device->GetResourceAllocationInfo(0,1,&desc);need(result.SizeInBytes!=UINT64_MAX,"native allocation bytes invalid");
        return result.SizeInBytes;};
    uint64_t expectedBytes=allocationBytes(capture.Resource(legacy))+allocationBytes(capture.Resource(snapshot))+allocationBytes(roughness);
    // One legacy snapshot remains live across profile replacement. Thirty-one
    // paired slots and that legacy slot must share the same 32-slot family.
    for(uint32_t i=0;i<30;++i)
    {
        NrdBridge::NativeMaterialCapture::SnapshotLease extra;
        need(capture.CaptureParams(fixture.list.Get(),base.Get(),params.Get(),extra,error),error.c_str());
        auto* baseResource=capture.Resource(extra);auto* roughResource=capture.RoughnessResource(extra);
        need(baseResource && roughResource && baseResource!=roughResource,"paired slot missing output");
        need(std::find(baseIdentities.begin(),baseIdentities.end(),baseResource)==baseIdentities.end(),"in-flight paired base slot reused");
        need(std::find(roughnessIdentities.begin(),roughnessIdentities.end(),roughResource)==roughnessIdentities.end(),"in-flight paired roughness slot reused");
        baseIdentities.push_back(baseResource);roughnessIdentities.push_back(roughResource);
        expectedBytes+=allocationBytes(baseResource)+allocationBytes(roughResource);budgetSnapshots.push_back(std::move(extra));
    }
    need(gParamsCaptureDispatches==32,"expected exactly one dispatch for each legacy/paired snapshot");
    need(capture.OwnedAuxiliaryBytes()==expectedBytes,"paired family bytes differ from actual native allocation sums");
    const auto beforeFull=gParamsCaptureDispatches,barriersFull=gNrdAuditedBarriers;
    NrdBridge::NativeMaterialCapture::SnapshotLease exhausted;
    need(!capture.CaptureParams(fixture.list.Get(),base.Get(),params.Get(),exhausted,error) && !exhausted,"33rd family slot admitted");
    need(gParamsCaptureDispatches==beforeFull && gNrdAuditedBarriers==barriersFull,"exhaustion recorded GPU work");
    auto legacyRead=fixture.Snapshot(capture.Resource(legacy),D3D12_RESOURCE_STATE_COMMON);
    auto materialRead=fixture.Snapshot(capture.Resource(snapshot),D3D12_RESOURCE_STATE_COMMON);
    auto roughnessRead=fixture.Snapshot(roughness,D3D12_RESOURCE_STATE_COMMON);
    auto baseRead=fixture.Snapshot(base.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    auto paramsRead=fixture.Snapshot(params.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    fixture.Submit();
    save(directory/"legacy-base-metal.bin",legacyRead.Data());save(directory/"params-base-metal.bin",materialRead.Data());
    save(directory/"params-roughness.bin",roughnessRead.Data());
    need(baseRead.Data()==baseBytes && paramsRead.Data()==paramsBytes,"capture modified source bytes");
    need(ParamsReferences(base.Get())==baseRefs && ParamsReferences(params.Get())==paramsRefs,"capture retained title source COM");
    std::weak_ptr<void> retainedExtra=budgetSnapshots.front();budgetSnapshots.clear();
    need(!retainedExtra.expired(),"caller release lost actual executable capture lease");
    need(capture.OwnedAuxiliaryBytes()==expectedBytes,"caller release prematurely returned allocated slot permit");
    fixture.Reset();
    need(retainedExtra.expired(),"successful completed Reset retained a capture lease");
    need(capture.OwnedAuxiliaryBytes()==expectedBytes,"Reset prematurely returned idle allocated slot permits");
    std::array<ComPtr<ID3D12Resource>,5> textures;
    const std::array<const char*,5> names{"spec","diff","nr","depth","motion"};
    const std::array<DXGI_FORMAT,5> formats{DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,
        DXGI_FORMAT_R10G10B10A2_UNORM,DXGI_FORMAT_R32_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT};
    for(size_t i=0;i<textures.size();++i)
    {
        auto bytes=load(directory/(std::string(names[i])+".bin"));
        textures[i]=fixture.Texture(width,height,formats[i],i<2?D3D12_RESOURCE_STATE_UNORDERED_ACCESS:
            D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&bytes);
        (i<2?gNrdReconInputs:gNrdGuideInputs).insert(textures[i].Get());
    }
    gNrdOwnedMaterials.insert(capture.Resource(snapshot));gNrdOwnedMaterials.insert(capture.Resource(legacy));
    gNrdOwnedMaterials.insert(roughness);
    NrdBridge::ConversionPass conversion;need(conversion.Initialize(fixture.device.Get(),width,height,error),error.c_str());
    const NrdBridge::ConversionInputs plain{textures[0].Get(),textures[1].Get(),textures[2].Get(),textures[3].Get(),textures[4].Get()};
    auto frame=ParamsFrame(width,height);frame.nativeMaterialGuides=true;
    auto malformed=fixture.Texture(width,height,DXGI_FORMAT_R32_FLOAT,D3D12_RESOURCE_STATE_COMMON);
    auto badExtent=fixture.Texture(width+1,height,DXGI_FORMAT_R16_FLOAT,D3D12_RESOURCE_STATE_COMMON);
    for(auto* bad:{malformed.Get(),badExtent.Get()})
    {
        auto inputs=plain;inputs.nativeMaterial=capture.Resource(snapshot);inputs.nativeMaterialRoughness=bad;
        NrdBridge::ConvertedResources rejected;const auto barriers=gNrdAuditedBarriers,allocations=gNrdDescriptorAllocations;
        need(!conversion.Dispatch(fixture.list.Get(),inputs,frame,rejected,error) && !rejected.spec,"malformed roughness admitted");
        need(gNrdAuditedBarriers==barriers && gNrdDescriptorAllocations==allocations &&
            !RecordedComputeLease::Capture(fixture.list.Get()),"malformed roughness recorded or retained work");
    }
    for(const std::string mode:{"white","legacy","params","off-ignored","fallback"})
    {
        conversion.ResetHistory();auto inputs=plain;auto currentFrame=frame;
        if(mode=="white") currentFrame.nativeMaterialGuides=false;
        else inputs.nativeMaterial=capture.Resource(snapshot);
        if(mode=="params") inputs.nativeMaterialRoughness=roughness;
        if(mode=="off-ignored") {currentFrame.nativeMaterialGuides=false;inputs.nativeMaterialRoughness=malformed.Get();}
        std::array<ULONG,5> references{};
        for(size_t i=0;i<textures.size();++i) references[i]=ParamsReferences(textures[i].Get());
        NrdBridge::ConvertedResources output;const auto barriers=gNrdMaterialBarriers;
        need(conversion.Dispatch(fixture.list.Get(),inputs,currentFrame,output,error),error.c_str());
        need(RecordedComputeLease::Capture(fixture.list.Get())!=nullptr,"actual conversion recording lease missing");
        const uint32_t expectedBarriers=mode=="params"?4u:((mode=="legacy" || mode=="fallback")?2u:0u);
        need(gNrdMaterialBarriers-barriers==expectedBarriers,"owned capture COMMON/SRV/COMMON transition count wrong");
        SaveParamsOutputs(fixture,directory,mode,output);
        for(size_t i=0;i<textures.size();++i)need(ParamsReferences(textures[i].Get())==references[i],"conversion retained borrowed title COM");
        need(RecordedComputeLease::GetRegistry().recordings.empty() && RecordedComputeLease::GetRegistry().submissions.empty(),
            "actual recorded lease registry did not retire after successful Reset");
    }
    legacy.reset();snapshot.reset();gNrdOwnedMaterials.clear();gNrdReconInputs.clear();gNrdGuideInputs.clear();
    need(capture.InitializeParams(fixture.device.Get(),width+1,height,error),error.c_str());
    need(capture.OwnedAuxiliaryBytes()==0,"retired idle paired/legacy slot destruction did not return all permits");
    ParamsTimings(fixture,1505,847);ParamsTimings(fixture,2560,1440);
    hr(fixture.list->Close());fixture.Validate();
    std::cout<<"material_params_native_checks="<<checks<<"\n";return 0;
}
catch(const std::exception& exception){std::cerr<<exception.what()<<"\n";return 1;}
