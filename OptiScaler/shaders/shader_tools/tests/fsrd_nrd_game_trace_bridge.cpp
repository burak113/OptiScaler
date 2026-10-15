// Appended to the unchanged original Trace fixture Host. Controlled words only:
// real recorder/copies/fence/Map/publication; output lease/provider witness are
// explicit CPU adapters. No AMD SDK call, title detour or image-quality oracle.
unsigned bridgeChecks = 0;
void check(bool value, const char* message) { ++bridgeChecks; need(value,message); }
struct OwnedBridgeFixture
{
    std::array<ComPtr<ID3D12Resource>,4> stages;
    std::array<ComPtr<ID3D12Resource>,7> inputs;
    ComPtr<ID3D12Resource> flag;
    std::array<ComPtr<ID3D12Resource>,2> title;
    explicit OwnedBridgeFixture(Host& h)
    {
        inputs = {h.textures[0],h.textures[1],h.textures[6],h.textures[7],h.textures[5],h.textures[2],h.textures[3]};
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC d {}; d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        d.Width = h.renderWidth; d.Height = h.renderHeight; d.DepthOrArraySize = d.MipLevels = 1;
        d.SampleDesc.Count = 1; d.Format = DXGI_FORMAT_R16G16B16A16_FLOAT; d.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        for (auto& resource : stages) hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,
            D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&resource)));
        for (auto& resource : title) hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,
            D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&resource)));
        d = ReadbackDesc(1536); d.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,D3D12_RESOURCE_STATE_COMMON,nullptr,IID_PPV_ARGS(&flag)));
    }
    NrdBridge::ConvertedResources Converted(Host& h)
    {
        return {inputs[0].Get(),inputs[1].Get(),inputs[2].Get(),inputs[3].Get(),inputs[4].Get(),inputs[5].Get(),inputs[6].Get(),
            h.renderWidth,h.renderHeight};
    }
    NrdBridge::RRRecordedOutputSnapshot Snapshot(Host& h,unsigned frame,bool separate=false)
    {
        NrdBridge::RRRecordedOutputSnapshot out;
        out.rawSpec=stages[0].Get(); out.rawDiff=stages[1].Get();
        out.selectedSpec=stages[separate ? 2 : 0].Get(); out.selectedDiff=stages[separate ? 3 : 1].Get();
        out.recording=h.list.Get(); out.frameSL=100+frame; out.frameIndex=500+frame;
        out.width=h.renderWidth; out.height=h.renderHeight; out.contextGeneration=7; out.recordingId=20+frame;
        out.providerVersionId=12; out.providerApiVersion=12; out.providerSignalFlags=3;
        const char name[]="CPU adapter; no actual provider"; memcpy(out.providerName.data(),name,sizeof(name));
        ffxDispatchDescDenoiser dispatch {};
        dispatch.renderSize={h.renderWidth,h.renderHeight}; dispatch.frameIndex=out.frameIndex;
        dispatch.flags=frame==0 ? FFX_DENOISER_DISPATCH_RESET : 0;
        dispatch.motionVectorScale={1,1,1}; dispatch.jitterOffsets={-0.0f,.25f};
        memcpy(out.providerControl.data(),reinterpret_cast<const uint8_t*>(&dispatch)+264,184);
        return out;
    }
    void Copy(Host& h,ID3D12Resource* src,D3D12_RESOURCE_STATES srcState,ID3D12Resource* dst)
    {
        D3D12_RESOURCE_BARRIER barriers[2] {};
        barriers[0].Type=barriers[1].Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barriers[0].Transition={src,0,srcState,D3D12_RESOURCE_STATE_COPY_SOURCE};
        barriers[1].Transition={dst,0,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_DEST};
        h.list->ResourceBarrier(2,barriers); h.list->CopyResource(dst,src);
        for (auto& barrier:barriers) std::swap(barrier.Transition.StateBefore,barrier.Transition.StateAfter);
        h.list->ResourceBarrier(2,barriers);
    }
    void FillStages(Host& h)
    {
        for (size_t i=0;i<stages.size();++i) Copy(h,inputs[i&1].Get(),srv,stages[i].Get());
        // Actual private flag GPU buffer; production Trace copies byte1212 only.
        D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_UPLOAD;
        auto d=ReadbackDesc(1536); ComPtr<ID3D12Resource> upload;
        hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&upload)));
        void* data=nullptr; D3D12_RANGE empty {0,0}; hr(upload->Map(0,&empty,&data)); memset(data,0,1536);
        const uint32_t nativeFlag=1; memcpy(static_cast<uint8_t*>(data)+1212,&nativeFlag,4); upload->Unmap(0,nullptr);
        D3D12_RESOURCE_BARRIER barrier {}; barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition={flag.Get(),0,D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COPY_DEST}; h.list->ResourceBarrier(1,&barrier);
        h.list->CopyBufferRegion(flag.Get(),0,upload.Get(),0,1536);
        std::swap(barrier.Transition.StateBefore,barrier.Transition.StateAfter);h.list->ResourceBarrier(1,&barrier);
        h.uploads.push_back(std::move(upload));
    }
};
Trace::BridgeIdentity Identity(unsigned frame=0,uint64_t domain=11)
{ return {domain,20+frame,1+frame,4,3,100+frame}; }
NrdBridge::FrameParameters Parameters(unsigned frame=0)
{
    NrdBridge::FrameParameters p;
    p.camera.view=p.camera.inverseView=p.camera.projection=DirectX::XMMatrixIdentity();
    p.camera.viewSource=p.camera.projectionSource=FSRDCamera::Source::StreamlineMatrix;
    p.streamlineFrame=100+frame;p.frameIndex=500+frame;p.reset=frame==0;p.previousValid=frame!=0;
    p.jitter={-0.0f,.25f}; p.previousJitter={.125f,-.25f};p.depthSign=-1.f;
    return p;
}
Trace::BridgeProviderBinaryIdentity Witness()
{
    // Deliberately unavailable: this fixture must NEVER qualify as signed SDK replay.
    return {R"({"schema_version":1,"attested":false,"failure":"CPU output adapter; no provider call"})"};
}
Trace::BridgeFrameToken Owned(Trace& trace,Host& h,const std::shared_ptr<OwnedBridgeFixture>& owner,
    unsigned frame=0,bool separate=false,Trace::BridgeIdentity id=Identity())
{
    auto output=owner->Snapshot(h,frame,separate); output.owner=owner;
    sl::Constants sl;
    sl.clipToPrevClip[0].x=-0.0f;
    return trace.RecordBridgeOwned(h.device.Get(),h.list.Get(),id,owner->Converted(h),owner,Parameters(frame),sl,100+frame,2,
        NrdBridge::RRSettingsState{},output,Witness());
}
Trace::BridgeFrameToken Admit(Trace& trace,Host& h,const std::shared_ptr<OwnedBridgeFixture>& owner,unsigned frame=0,bool separate=false)
{
    Trace::BridgeFrameToken token;
    Await([&]{token=Owned(trace,h,owner,frame,separate,Identity(frame));return bool(token)||!Trace::IsActive();},"bridge admission did not initialize");
    return token;
}
Trace::Request Request(const std::filesystem::path& root)
{
    Trace::Request request;request.capturePath=Trace::Request::CapturePath::NrdBridge;
    request.regionMode=Trace::Request::RegionMode::FullRender;request.outputRoot=root.string();return request;
}
int main(int argc,char** argv) try
{
    need(argc==2,"output directory required");const auto root=std::filesystem::path(argv[1]);
    g_dllPath=root/"test_OptiScaler.dll";Json result={{"scope","real_WARP_trace_copy_fence_Map_publication; CPU_RR_output_and_commit_adapter; no_AMD_SDK"}};
    Host h(128);auto owner=std::make_shared<OwnedBridgeFixture>(h);
    {
        Trace trace;g_testFailHeapAllocation.store(true);
        auto token=trace.RecordBridgeOwned(nullptr,nullptr,{}, {}, {}, {},sl::Constants{},0,0,{}, {}, {});
        g_testFailHeapAllocation.store(false);check(!token,"OFF performed allocation/native access");
    }
    auto request=Request(root);
    {
        Trace trace;check(Trace::RequestStart(request),"bridge request");
        check(Trace::IsNrdBridgeCaptureActive(),"bridge atomic path gate missing");
        check(!Trace::TakeNrdBridgeHistoryResetRequest(),"ordinary arm requested a history reset");
        check(!h.Sources(trace),"legacy source owner stole bridge request");
        const auto folder=Trace::GetStatus().folder;result["capture"]=folder;
        for (unsigned frame=0;frame<2;++frame)
        {
            h.Fill(frame);owner->FillStages(h);
            auto token=Admit(trace,h,owner,frame);check(bool(token),"bridge owned stage rejected");
            auto f=std::static_pointer_cast<Frame>(token);
            check(f->bridgeRoles[7]==f->bridgeRoles[9]&&f->bridgeRoles[8]==f->bridgeRoles[10],"raw/selected alias not deduplicated");
            check(f->surveyImages.size()==12,"alias stage allocation count wrong");
            check(f->bridgeMetadata["frame_parameters"]["jitter"][0]==0x80000000u,"negative-zero typed jitter bits lost");
            check(f->bridgeMetadata["frame_parameters"]["streamline"]["clip_to_previous_clip"][0]==0x80000000u,"SL reprojection bits lost");
            check(!Owned(trace,h,owner,frame,false,Identity(frame,99)),"foreign chain joined selected capture");
            check(f->bridgeIdentity.domain==11,"foreign chain overwrote identity");
            Trace::BridgeSkippedDispatch skip;skip.sequence=1;skip.role=uint32_t(NrdBridge::Role::Temporal);
            skip.shaderKnown=true;skip.shaderSha256[0]=0xaa;skip.dimensionsKnown=true;skip.groups={16,16,1};
            trace.RecordBridgeSkipped(token,h.list.Get(),Identity(frame),skip);
            for (size_t i=0;i<2;++i)owner->Copy(h,owner->stages[i].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,owner->title[i].Get());
            auto output=owner->Snapshot(h,frame);output.owner=owner;output.outputCommitted=true;
            output.encodingFlag=owner->flag.Get();output.nativeEncodingCaptured=true;
            std::array<Trace::Source,2> targets {{{owner->title[0].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS},
                {owner->title[1].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS}}};
            NrdBridge::TitleSignalConstants sourceConstants;sourceConstants.address=owner->flag->GetGPUVirtualAddress();
            sourceConstants.wordIndex=frame==0 ? 36 : 303;
            check(trace.CompleteBridgeFrame(token,h.list.Get(),Identity(frame),targets,output,sourceConstants),"matched commit rejected");
            check(f->sealed,"bridge frame not sealed");
            check(!trace.CompleteBridgeFrame(token,h.list.Get(),Identity(frame),targets,output,sourceConstants),"duplicate commit recorded twice");
            for (const auto& retained:f->ticket->resources)
                check(retained.Get()!=static_cast<IUnknown*>(owner->title[0].Get())&&retained.Get()!=static_cast<IUnknown*>(owner->title[1].Get()),"borrowed title target AddRef retained");
            h.Execute();Saved(frame+1);h.Reset();token.reset();f.reset();trace.Poll();
        }
        Trace::RequestStop();Closed();Published(2);
        check(Trace::GetStatus().manifestPublished==2,"bridge immutable prefix unpublished");
    }
    {
        Trace trace;auto reset=Request(root);reset.bridgeWaitForReset=true;reset.frameCount=64;reset.bridgeDomain=11;reset.delaySeconds=1;
        check(Trace::RequestStart(reset),"explicit reset request");
        check(!Trace::TakeNrdBridgeHistoryResetRequest(11),"reset issued before owner/disk/delay ready");
        check(!Owned(trace,h,owner),"uninitialized explicit request admitted");
        Await([]{std::scoped_lock lock(Global().mutex);return Global().current->initialized;},"reset disk initialization");
        check(!Trace::TakeNrdBridgeHistoryResetRequest(99),"wrong domain took reset intent");
        Await([]{std::scoped_lock lock(Global().mutex);return GetTickCount64()>=Global().current->startTick;},"reset delay");
        const auto before=bridgeAllocations;bridgeCountAllocations=true;
        const bool first=Trace::TakeNrdBridgeHistoryResetRequest(11),second=Trace::TakeNrdBridgeHistoryResetRequest(11);
        bridgeCountAllocations=false;
        check(first&&!second,"explicit reset intent was not exactly once");check(bridgeAllocations==before,"ready reset take allocated");
        check(!Owned(trace,h,owner,1,false,Identity(1)),"nonRESET provider frame admitted into reset capture");
        check(Trace::GetStatus().phase=="waiting_reset"&&Trace::GetStatus().recorded==0,"waitRESET state/payload false");
        auto token=Owned(trace,h,owner);check(bool(token),"actual RESET controls not admitted");
        auto f=std::static_pointer_cast<Frame>(token);check(f->info.reset,"capture RESET not from actual control words");
        trace.CancelBridgeFrame(token,"reset handshake scope finished");h.Discard();token.reset();f.reset();Closed();trace.Poll();
    }
    {
        Trace trace;check(Trace::RequestStart(request),"missing commit request");
        auto token=Admit(trace,h,owner);check(bool(token),"missing commit setup");
        trace.CancelBridgeFrame(token,"cancelled exact recording");h.Discard();token.reset();Closed();trace.Poll();
        check(Trace::GetStatus().manifestPublished==0,"cancelled frame published");
    }
    {
        Trace trace;check(Trace::RequestStart(request),"wrong commit identity request");
        auto token=Admit(trace,h,owner);check(bool(token),"wrong identity setup");
        auto out=owner->Snapshot(h,0);out.owner=owner;out.outputCommitted=true;
        auto id=Identity();++id.recordingGeneration;
        std::array<Trace::Source,2> targets {{{owner->title[0].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS},{owner->title[1].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS}}};
        check(!trace.CompleteBridgeFrame(token,h.list.Get(),id,targets,out,NrdBridge::TitleSignalConstants{}),"late old-generation commit accepted");
        h.Discard();token.reset();Closed();trace.Poll();check(Trace::GetStatus().manifestPublished==0,"old generation published");
    }
    {
        Trace trace;check(Trace::RequestStart(request),"skip bound request");auto token=Admit(trace,h,owner);check(bool(token),"skip setup");
        Trace::BridgeSkippedDispatch event;
        for(unsigned i=1;i<=64;++i){event.sequence=i;trace.RecordBridgeSkipped(token,h.list.Get(),Identity(),event);}
        auto f=std::static_pointer_cast<Frame>(token);check(f->bridgeMetadata["skipped_original_dispatches"].size()==64,"bounded skip metadata lost");
        event.sequence=65;trace.RecordBridgeSkipped(token,h.list.Get(),Identity(),event);
        check(Trace::GetStatus().message.find("bound/order")!=std::string::npos,"skip overflow silently truncated");
        h.Discard();token.reset();f.reset();Closed();trace.Poll();
    }
    {
        // Actual native layout queries, no readback allocations/trace commands at over-budget admission.
        Host large(2560,0,0,1440);auto big=std::make_shared<OwnedBridgeFixture>(large);Trace trace;
        check(Trace::RequestStart(request),"large request");uint64_t before=0;{std::scoped_lock lock(Global().mutex);before=Global().gpuBytes;}
        auto token=Admit(trace,large,big,0,true);check(!token,"309MiB distinct recovery frame passed 256MiB cap");
        {std::scoped_lock lock(Global().mutex);check(Global().gpuBytes==before,"over-budget trace allocated readbacks");}
        check(Trace::GetStatus().recorded==0,"over-budget trace recorded a frame");
        check(Trace::GetStatus().message.find("frame readback preflight")!=std::string::npos,"budget diagnostic missing");
        large.Discard();Closed();trace.Poll();large.NoGpuErrors();
    }
    h.NoGpuErrors();result["native_checks"]=bridgeChecks;result["gpu_backend"]="WARP";
    result["actual_sdk_dispatches"]=0;result["debug_errors"]=0;result["debug_warnings"]=0;
    RRTraceAdditiveIO::WriteText(root/"bridge-trace-result.json",result.dump(2));
    std::cout<<"NRD_BRIDGE_TRACE PASS "<<bridgeChecks<<"\n";return 0;
}
catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
