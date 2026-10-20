// Appended to the existing real-WARP Host/OwnedBridgeFixture by the local runner.
// The actual production recorder/copy/fence/Map code executes; provider outputs,
// selection decisions and scale metadata below are explicit controlled adapters.
// No actual AMD SDK, native title hook, image-quality oracle or scale round trip.
uint16_t ObservationCanary(uint32_t x,uint32_t y,uint32_t channel,uint32_t lobe,uint32_t phase)
{
    static constexpr uint16_t alpha[] {0x7e01u,0x7c01u,0x8000u,0x0001u,0x0000u};
    if(channel==3) return alpha[(x+3*y+lobe+phase)%5u];
    return uint16_t(0x3000u+0x0100u*lobe+0x0800u*phase+(x+3*y+channel)%512u);
}
void UploadObservationCanary(Host& h,ID3D12Resource* texture,uint32_t lobe,uint32_t phase)
{
    const auto desc=texture->GetDesc();
    check(desc.Format==DXGI_FORMAT_R16G16B16A16_FLOAT,"canary source format");
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp {}; UINT64 bytes=0;
    h.device->GetCopyableFootprints(&desc,0,1,0,&fp,nullptr,nullptr,&bytes);
    D3D12_HEAP_PROPERTIES heap {};heap.Type=D3D12_HEAP_TYPE_UPLOAD;
    auto bd=ReadbackDesc(bytes);ComPtr<ID3D12Resource> upload;
    hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&bd,D3D12_RESOURCE_STATE_GENERIC_READ,
        nullptr,IID_PPV_ARGS(&upload)));
    void* mapped=nullptr;D3D12_RANGE empty {0,0};hr(upload->Map(0,&empty,&mapped));
    memset(mapped,0xcd,size_t(bytes));
    for(UINT y=0;y<desc.Height;++y)for(UINT x=0;x<desc.Width;++x)for(UINT c=0;c<4;++c)
    {
        const auto value=ObservationCanary(x,y,c,lobe,phase);
        memcpy(static_cast<uint8_t*>(mapped)+fp.Offset+y*fp.Footprint.RowPitch+(x*4+c)*2,&value,2);
    }
    upload->Unmap(0,nullptr);
    D3D12_RESOURCE_BARRIER barrier {};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition={texture,0,srv,D3D12_RESOURCE_STATE_COPY_DEST};h.list->ResourceBarrier(1,&barrier);
    D3D12_TEXTURE_COPY_LOCATION source {},destination {};
    source.pResource=upload.Get();source.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;source.PlacedFootprint=fp;
    destination.pResource=texture;destination.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    h.list->CopyTextureRegion(&destination,0,0,0,&source,nullptr);
    std::swap(barrier.Transition.StateBefore,barrier.Transition.StateAfter);h.list->ResourceBarrier(1,&barrier);
    // Preserve every upload until this recording actually completes; a second
    // Host::Fill would prematurely clear uploads of earlier recorded commands.
    h.uploads.push_back(std::move(upload));
}
void InitializeObservationSession(Trace& trace,Host& h,const std::shared_ptr<OwnedBridgeFixture>& owner)
{
    // First post-provider call only claims the owner and wakes the disk worker.
    // No early payload exists yet, so it must return before admission.
    auto output=owner->Snapshot(h,0);output.owner=owner;
    const auto initial=trace.RecordBridgeOwned(h.device.Get(),h.list.Get(),Identity(),owner->Converted(h),owner,
        Parameters(),sl::Constants{},100,2,{},output,Witness());
    check(!initial,"startup unexpectedly published an absent early observation");
    Await([] {std::scoped_lock lock(Global().mutex);return Global().current&&Global().current->initialized;},
        "native observation session did not initialize");
}
std::weak_ptr<void> EarlyObservation(Host& h,const NrdBridge::ConvertedResources& input)
{
    return Trace::RecordNativeObservationInputs(h.device.Get(),h.list.Get(),input,input,
        11,20,7,1,500,100,true);
}
int main(int argc,char** argv) try
{
    need(argc==2,"output directory required");const auto root=std::filesystem::path(argv[1]);
    g_dllPath=root/"test_OptiScaler.dll";
    Json result {{"scope","actual_production_recorder_WARP_copies_fences_Map; controlled_output_selection_scale_adapters"},
        {"actual_sdk_dispatches",0},{"scale_roundtrip_executed",false},{"quality_accepted",false}};
    Host h(137,0,0,131);auto owner=std::make_shared<OwnedBridgeFixture>(h);
    {
        Trace trace;g_testFailHeapAllocation.store(true);
        const auto off=Trace::RecordNativeObservationInputs(nullptr,nullptr,{}, {},0,0,0,0,0,0,false);
        g_testFailHeapAllocation.store(false);
        check(off.expired(),"OFF touched native resources or created an observation");
        check(!Trace::WantsNativeObservations(),"native observations enabled by default");
        result["off_no_allocation_or_native_access"]=true;
    }
    for(bool protectedPath:{false,true})
    {
        Trace trace;auto request=Request(root);request.nativeObservations=true;
        request.regionMode=Trace::Request::RegionMode::Square;request.x=7;request.y=1;request.size=128;
        check(Trace::RequestStart(request),"observation request");
        result[protectedPath?"protected_capture":"raw_capture"]=Trace::GetStatus().folder;
        InitializeObservationSession(trace,h,owner);
        h.Fill(0);const auto input=owner->Converted(h);
        for(uint32_t lobe=0;lobe<2;++lobe)UploadObservationCanary(h,owner->inputs[lobe].Get(),lobe,0);
        auto early=EarlyObservation(h,input);check(!early.expired(),"early input capture rejected");
        const auto earlyFrame=std::static_pointer_cast<Frame>(early.lock());
        check(earlyFrame&&earlyFrame->discarded&&!earlyFrame->sealed,"unadopted early input became publishable");
        check(earlyFrame->gpuBytes!=0,"early words lack charged readback storage");
        // This is an explicit synthetic overwrite, not a simulated scaling pass.
        // It makes a misplaced late physical-input snapshot observably wrong.
        for(uint32_t lobe=0;lobe<2;++lobe)UploadObservationCanary(h,owner->inputs[lobe].Get(),lobe,1);
        owner->FillStages(h);
        auto output=owner->Snapshot(h,0,protectedPath);output.owner=owner;
        output.nativeObservationInputs=early;output.resetEpoch=1;
        output.specularSelection=output.diffuseSelection=protectedPath?
            FSRDNrdObservation::SelectionPath::LobeRecovery:FSRDNrdObservation::SelectionPath::RawRR;
        output.recoveryActive=protectedPath;
        output.providerDiffuseRadianceScale=16;output.providerSpecularRadianceScale=256;output.providerRadianceScale=0;
        NrdBridge::RRSettingsState settings;settings.requested.radianceScale.enabled=true;
        auto token=trace.RecordBridgeOwned(h.device.Get(),h.list.Get(),Identity(),input,owner,Parameters(),
            sl::Constants{},100,2,settings,output,Witness());
        check(bool(token),"same-recording early observation not adopted");
        check(token.get()==earlyFrame.get(),"adoption duplicated the early frame/fence");
        const auto frame=std::static_pointer_cast<Frame>(token);
        uint64_t charged=0;for(const auto& image:frame->surveyImages)charged+=image.allocationBytes;
        check(frame->gpuBytes==charged,"early readbacks charged twice or omitted");
        for(size_t lobe=0;lobe<2;++lobe)
        {
            auto* selected=lobe==0?output.selectedSpec:output.selectedDiff;
            owner->Copy(h,selected,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,owner->title[lobe].Get());
        }
        output.outputCommitted=true;
        const std::array<Trace::Source,2> targets {{{owner->title[0].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS},
            {owner->title[1].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS}}};
        check(trace.CompleteBridgeFrame(token,h.list.Get(),Identity(),targets,output,{}),"late observation commit rejected");
        h.Execute();Saved(1);h.Reset();token.reset();trace.Poll();Trace::RequestStop();Closed();Published(1);
        h.NoGpuErrors();
    }
    {
        Trace trace;auto request=Request(root);request.nativeObservations=true;
        check(Trace::RequestStart(request),"stale epoch request");InitializeObservationSession(trace,h,owner);
        h.Fill(0);owner->FillStages(h);const auto input=owner->Converted(h);auto early=EarlyObservation(h,input);
        check(!early.expired(),"stale epoch setup");auto output=owner->Snapshot(h,0);output.owner=owner;
        output.nativeObservationInputs=early;output.resetEpoch=2;
        output.specularSelection=output.diffuseSelection=FSRDNrdObservation::SelectionPath::RawRR;
        const auto rejected=trace.RecordBridgeOwned(h.device.Get(),h.list.Get(),Identity(),input,owner,
            Parameters(),sl::Constants{},100,2,{},output,Witness());
        check(!rejected,"early observation adopted across reset epoch");
        h.Discard();trace.Poll();Trace::RequestStop();Closed();
        check(Trace::GetStatus().captured==0,"stale early frame reached publication");
        result["stale_epoch_rejected_before_publication"]=true;
    }
    h.NoGpuErrors();result["checks"]=bridgeChecks;result["debug_errors"]=0;result["debug_warnings"]=0;
    RRTraceAdditiveIO::WriteText(root/"review-native-observation-gpu.json",result.dump(2));
    std::cout<<result.dump(2)<<'\n';return 0;
}
catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
