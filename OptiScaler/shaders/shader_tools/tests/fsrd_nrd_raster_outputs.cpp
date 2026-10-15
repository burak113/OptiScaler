// Actual-host B outputs with the game's RTV|UAV flags. Profile selection and
// caller-strong Release coverage are explicit fixture adapters as in NativeFixture.
struct NativeRasterWork
{
    Host& h; NativeFixture::NativeTitle& title;
    ComPtr<ID3D12PipelineState> pipeline;
    NativeRasterWork(Host& host,NativeFixture::NativeTitle& owner):h(host),title(owner)
    {
        NativeFixtureResourceCreated(title.color.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET);
        NativeFixtureHeapCreated(h.device.Get(),title.rtv.Get());
        D3D12_RENDER_TARGET_VIEW_DESC view{};view.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;view.ViewDimension=D3D12_RTV_DIMENSION_TEXTURE2D;
        FrameSurvey::View(title.color.Get(),title.rtv->GetCPUDescriptorHandleForHeapStart(),&view);
        const char code[]=R"(
float4 VS(uint id:SV_VertexID):SV_Position{return float4(id==2?3:-1,id==1?3:-1,0,1);}
float4 PS():SV_Target{return float4(.0625,.25,.5,1);})";
        ComPtr<ID3DBlob> vs,ps,error;
        hr(D3DCompile(code,sizeof(code),nullptr,nullptr,nullptr,"VS","vs_5_1",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&vs,&error));
        hr(D3DCompile(code,sizeof(code),nullptr,nullptr,nullptr,"PS","ps_5_1",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&ps,&error));
        D3D12_GRAPHICS_PIPELINE_STATE_DESC pd{};pd.pRootSignature=title.graphicsRoot.Get();
        pd.VS={vs->GetBufferPointer(),vs->GetBufferSize()};pd.PS={ps->GetBufferPointer(),ps->GetBufferSize()};
        pd.BlendState.RenderTarget[0].RenderTargetWriteMask=D3D12_COLOR_WRITE_ENABLE_ALL;
        pd.BlendState.RenderTarget[0].SrcBlend=pd.BlendState.RenderTarget[0].SrcBlendAlpha=D3D12_BLEND_ONE;
        pd.BlendState.RenderTarget[0].DestBlend=pd.BlendState.RenderTarget[0].DestBlendAlpha=D3D12_BLEND_ZERO;
        pd.BlendState.RenderTarget[0].BlendOp=pd.BlendState.RenderTarget[0].BlendOpAlpha=D3D12_BLEND_OP_ADD;
        pd.SampleMask=UINT_MAX;pd.RasterizerState.FillMode=D3D12_FILL_MODE_SOLID;pd.RasterizerState.CullMode=D3D12_CULL_MODE_NONE;
        pd.DepthStencilState.DepthEnable=false;pd.DepthStencilState.DepthFunc=D3D12_COMPARISON_FUNC_ALWAYS;
        pd.DepthStencilState.StencilEnable=false;pd.PrimitiveTopologyType=D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
        pd.NumRenderTargets=1;pd.RTVFormats[0]=view.Format;pd.SampleDesc.Count=1;
        hr(h.device->CreateGraphicsPipelineState(&pd,IID_PPV_ARGS(&pipeline)));NativeFixturePipelineCreated(pipeline.Get(),pd);
        need(NrdBridge::RegisterInterveningPipelineForTesting(pipeline.Get(),2),"explicit resource-free graphics profile keeps the real native stage hashes");
    }
    void Bind(bool conflict=false,bool contiguous=false)
    {
        h.list->SetGraphicsRootSignature(title.graphicsRoot.Get());h.list->SetPipelineState(pipeline.Get());
        const auto target=title.rtv->GetCPUDescriptorHandleForHeapStart();
        if(conflict)
        {
            D3D12_RENDER_TARGET_VIEW_DESC view{};view.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;view.ViewDimension=D3D12_RTV_DIMENSION_TEXTURE2D;
            h.device->CreateRenderTargetView(title.tex[11].Get(),&view,target);FrameSurvey::View(title.tex[11].Get(),target,&view);
            h.barrier(title.tex[11].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_RENDER_TARGET);
        }
        h.list->OMSetRenderTargets(1,&target,contiguous,nullptr);
        const D3D12_VIEWPORT viewport{0,0,float(title.width),float(title.height),0,1};
        const D3D12_RECT rect{0,0,LONG(title.width),LONG(title.height)};
        h.list->RSSetViewports(1,&viewport);h.list->RSSetScissorRects(1,&rect);h.list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    }
};

int main(int argc,char** argv)try
{
    need(argc==4,"scratch output, signed AMD provider and raster mode");const std::string mode=argv[3];
    const bool conflict=mode=="conflict"||mode=="rebind",missing=mode=="missing",negative=conflict||missing;
    need(mode=="safe"||mode=="reuse"||mode=="contiguous"||mode=="early"||mode=="repeat"||negative,"bounded raster mode");
    NativeFixture::Bootstrap();Host h;NativeFixtureRegister(h.device.Get());NativeFixtureRegister(h.list.Get());
    g_dllPath=std::filesystem::path(argv[1])/"fixture.dll";
    Config::Instance()->FfxDenoiserNrdBridge.value=true;Config::Instance()->FfxDenoiserNrdBridgeEnabled.value=true;
    NrdBridge::ConfigureStartup(true);loadProvider(argv[2]);FrameSurvey::BeginCreationTracking(false);
    need(FrameSurvey::Install(h.device.Get(),h.list.Get(),false)&&NrdBridge::Initialize(h.device.Get()),"native coordinator starts without a survey recording");
    AttachRoots(h.list.Get());Wiring::Attach(h.list.Get());NativeDraw::Attach(h.list.Get());NativeRaster::Attach(h.list.Get());
    NrdBridge::SetNativeElisionContractForTesting(true);
    struct Hooks{~Hooks(){NativeRaster::Detach();NativeDraw::Detach();Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();}}hooks;
    struct DebugCleanup{~DebugCleanup(){emitDebug={};}}debugCleanup;
    J frames=J::array();std::string failure;
    {
        NativeFixture::NativeTitle title(h,false);NativeRasterWork work(h,title);
        struct Cleanup{Host& host;~Cleanup(){host.waitComplete();NrdBridge::Shutdown();RecordedComputeLease::Detach(RecordedComputeLease::Capture(host.list.Get()));RecordedComputeLease::Poll();}}cleanup{h};
        for(UINT frame=1;frame<=(negative?1u:2u);++frame)
        {
            need((title.tex[11]->GetDesc().Flags&D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET)&&
                 (title.tex[12]->GetDesc().Flags&D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),"B outputs match the actual game's RTV|UAV creation flags");
            if(mode=="early")work.Bind();
            title.Begin(frame);title.A();title.B();title.ConsumerA();
            if(mode=="early")h.list->SetPipelineState(work.pipeline.Get());
            else
            {
                if(mode=="rebind")work.Bind();
                work.Bind(conflict,mode=="contiguous");
            }
            if(missing)FrameSurvey::ForgetRenderTargets(h.list.Get()); // Explicit missing-observer control.
            if(mode=="reuse")
            {
                // RTV descriptors are consumed at OMSetRenderTargets. Reusing its
                // CPU slot now must not change the already recorded output binding.
                D3D12_RENDER_TARGET_VIEW_DESC view{};view.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;view.ViewDimension=D3D12_RTV_DIMENSION_TEXTURE2D;
                const auto target=title.rtv->GetCPUDescriptorHandleForHeapStart();
                h.device->CreateRenderTargetView(title.tex[11].Get(),&view,target);FrameSurvey::View(title.tex[11].Get(),target,&view);
            }
            h.list->DrawInstanced(3,1,0,0);
            if(mode=="repeat")for(UINT draw=1;draw<48;++draw){work.Bind();h.list->DrawInstanced(3,1,0,0);}
            const auto b=NrdBridge::gService->lists.at(h.list.Get()).native[1];
            if(negative)
            {
                need(b->invalidated&&b->recording->skipInvalidated,"overlapping or unknown raster outputs invalidate the required transaction");
                need(std::string(b->recording->invalidationGate.load())==(missing?"raster_outputs_unknown":"raster_output_overlap"),
                     "the exact retained submission diagnostic distinguishes missing output metadata from an actual B overlap");
                if(conflict)h.barrier(title.tex[11].Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
                need(!NativeFixture::Execute(h)&&h.denied==1,"overlapping graphics output denies the original GPU batch");
                failure=NrdBridge::GetStatus().reason;break;
            }
            need(!b->invalidated&&!b->recording->skipInvalidated,"RTV capability alone cannot invalidate B when the actual draw output is disjoint");
            need(b->ownership->nativeProof->rasterOutputCount==1,"repeated draws and equivalent OM rebinds retain one exact output set");
            auto image=title.readback(title.color.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET);
            if(mode=="reuse")
            {
                D3D12_RENDER_TARGET_VIEW_DESC view{};view.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;view.ViewDimension=D3D12_RTV_DIMENSION_TEXTURE2D;
                const auto target=title.rtv->GetCPUDescriptorHandleForHeapStart();
                h.device->CreateRenderTargetView(title.color.Get(),&view,target);FrameSurvey::View(title.color.Get(),target,&view);
            }
            title.ConsumerB();
            need(NrdBridge::GetStatus().active&&b->committed,"B's late pixel Consumer still commits its independent RR output");
            auto roots=h.buffer(1024,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
            h.barrier(title.checksum.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
            h.list->CopyBufferRegion(roots.Get(),0,title.checksum.Get(),0,1024);
            h.barrier(title.checksum.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            need(NativeFixture::Execute(h),"disjoint RTV draws and both RR chains pass actual synchronized submission admission");
            NativeFixture::RootChecks(h,title,roots);
            const auto pixels=image.signal();const UINT expected[]={0x2c00,0x3400,0x3800,0x3c00};
            for(size_t i=0;i<pixels.size();++i)need(pixels[i]==expected[i%4],"the surviving native graphics shader executed on the GPU with its bind-time RTV");
            frames.push_back({{"SL_frame",frame},{"signed_dispatches",2},{"native_filter_gpu_executions",0}});h.reset();
        }
    }
    NrdBridge::Shutdown();RecordedComputeLease::Poll();
    if(!negative)need(FfxApiProxy::creates==FfxApiProxy::destroys,"all fence-completed raster fixture RR contexts retire");
    const auto debug=h.debugCounts();
    J out={{"native_checks",checks},{"frames",frames},{"provider_dispatches",FfxApiProxy::dispatches},
           {"native_submissions",h.tick},{"failure_reason",failure},{"debug_errors",debug[0]},{"debug_warnings",debug[1]}};
    std::ofstream(std::filesystem::path(argv[1])/"raster-outputs-result.json")<<out.dump(2)<<'\n';
    std::cout<<out.dump(2)<<std::endl;return debug[0]||debug[1]?1:0;
}
catch(const std::exception& e){std::cerr<<"NRD raster outputs failure: "<<e.what()<<std::endl;return 1;}
