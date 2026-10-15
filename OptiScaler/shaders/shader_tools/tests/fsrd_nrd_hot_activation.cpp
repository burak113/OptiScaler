// Actual-host hot activation, including a native-style CBV table at parameter0.
// Shader-role and caller-strong Release coverage remain explicit fixture adapters.
#include <future>
struct TableZeroTitle : NativeFixture::NativeTitle
{
    ComPtr<ID3D12RootSignature> retainedRoot;
    std::array<ComPtr<ID3D12PipelineState>,11> retainedPipelines;
    TableZeroTitle(Host& h) : NativeTitle(h,false)
    {
        retainedRoot=root; retainedPipelines=pso;
        D3D12_DESCRIPTOR_RANGE ranges[]={{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,16,0,0,0},
            {D3D12_DESCRIPTOR_RANGE_TYPE_SRV,UINT_MAX,0,0,0},
            {D3D12_DESCRIPTOR_RANGE_TYPE_UAV,5,0,0,0},
            {D3D12_DESCRIPTOR_RANGE_TYPE_SAMPLER,1,0,0,0}};
        D3D12_ROOT_PARAMETER p[32]{};
        for(UINT i=0;i<32;++i){p[i].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;p[i].Constants={200+i,2,1};}
        for(auto pair:std::array<std::array<UINT,2>,4>{{{0,0},{1,1},{5,2},{7,3}}})
        {p[pair[0]].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;p[pair[0]].DescriptorTable={1,&ranges[pair[1]]};}
        p[3].ParameterType=D3D12_ROOT_PARAMETER_TYPE_SRV;p[3].Descriptor={0,1};
        p[4].ParameterType=D3D12_ROOT_PARAMETER_TYPE_UAV;p[4].Descriptor={0,1};
        p[6].Constants={8,2,2};p[8].Constants={0,2,8};
        D3D12_ROOT_SIGNATURE_DESC desc{32,p,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE};
        ComPtr<ID3DBlob> bytes,error;hr(D3D12SerializeRootSignature(&desc,D3D_ROOT_SIGNATURE_VERSION_1,&bytes,&error));
        hr(h.device->CreateRootSignature(0,bytes->GetBufferPointer(),bytes->GetBufferSize(),IID_PPV_ARGS(&root)));
        NativeFixtureRootCreated(root.Get(),bytes->GetBufferPointer(),bytes->GetBufferSize());
        std::string code=titleShader;
        for(const auto& change:std::array<std::pair<std::string,std::string>,2>{{
            {"cbuffer Root:register(b0)","cbuffer Root:register(b0,space2)"},
            {"cbuffer Extent:register(b8)","cbuffer Extent:register(b8,space2)"}}})
        {const auto at=code.find(change.first);need(at!=std::string::npos,"bounded fixture shader root relocation");code.replace(at,change.first.size(),change.second);}
        for(UINT role=1;role<=10;++role)
        {
            ComPtr<ID3DBlob> shader;const auto number=std::to_string(role);
            const D3D_SHADER_MACRO defines[]={{"ROLE",number.c_str()},{nullptr,nullptr}};
            hr(D3DCompile(code.data(),code.size(),nullptr,defines,nullptr,"main","cs_5_1",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&shader,&error));
            D3D12_COMPUTE_PIPELINE_STATE_DESC pd{};pd.pRootSignature=root.Get();pd.CS={shader->GetBufferPointer(),shader->GetBufferSize()};
            hr(h.device->CreateComputePipelineState(&pd,IID_PPV_ARGS(&pso[role])));NativeFixturePipelineCreated(pso[role].Get(),pd);
            NrdBridge::RegisterPipelineRoleForTesting(pso[role].Get(),Role(role),true);
        }
    }
    void Begin(UINT frame)
    {
        SetWords();StreamlineHooks::snapshot=camera(frame,width,height);
        NrdBridge::OnTitleTag(h.list.Get(),"MotionVectors",tex[6].Get());
        auto zero=h.upload(0,1024);h.barrier(checksum.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_DEST);
        h.list->CopyBufferRegion(checksum.Get(),0,zero.Get(),0,1024);h.barrier(checksum.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);h.uploads.push_back(zero);
        h.list->SetComputeRootSignature(root.Get());ID3D12DescriptorHeap* heaps[]={visible.Get(),sampler.Get()};h.list->SetDescriptorHeaps(2,heaps);
        const UINT first[]={11,22,33},extent[]={width,height};h.list->SetComputeRoot32BitConstants(8,3,first,0);h.list->SetComputeRoot32BitConstant(8,40,5);
        const D3D12_CONSTANT_BUFFER_VIEW_DESC cbv{cb->GetGPUVirtualAddress(),1536};
        const D3D12_CPU_DESCRIPTOR_HANDLE cpu{visible->GetCPUDescriptorHandleForHeapStart().ptr+UINT64(102)*increment};
        h.device->CreateConstantBufferView(&cbv,cpu);FrameSurvey::View(cpu,&cbv);
        h.list->SetComputeRootDescriptorTable(0,{visible->GetGPUDescriptorHandleForHeapStart().ptr+UINT64(96)*increment});
        h.list->SetComputeRootShaderResourceView(3,rootSrv->GetGPUVirtualAddress());h.list->SetComputeRootUnorderedAccessView(4,checksum->GetGPUVirtualAddress());
        h.list->SetComputeRoot32BitConstants(6,2,extent,0);h.list->SetComputeRootDescriptorTable(7,sampler->GetGPUDescriptorHandleForHeapStart());
        pass(Role::PrepLast);
    }
};

struct ColdPureIndirect
{
    Host& h;ComPtr<ID3D12PipelineState> pipeline;ComPtr<ID3D12CommandSignature> signature;
    ComPtr<ID3D12Resource> arguments;
    ColdPureIndirect(Host& host,NativeFixture::NativeTitle& title):h(host)
    {
        const char code[]=R"(RWStructuredBuffer<uint> Checks:register(u0,space1);
[numthreads(1,1,1)]void main(){InterlockedAdd(Checks[13*16+11],1);})";
        ComPtr<ID3DBlob> shader,error;hr(D3DCompile(code,sizeof(code),nullptr,nullptr,nullptr,"main","cs_5_1",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&shader,&error));
        D3D12_COMPUTE_PIPELINE_STATE_DESC pd{};pd.pRootSignature=title.root.Get();pd.CS={shader->GetBufferPointer(),shader->GetBufferSize()};
        hr(h.device->CreateComputePipelineState(&pd,IID_PPV_ARGS(&pipeline)));NativeFixturePipelineCreated(pipeline.Get(),pd);
        const D3D12_INDIRECT_ARGUMENT_DESC argument{D3D12_INDIRECT_ARGUMENT_TYPE_DISPATCH};
        const D3D12_COMMAND_SIGNATURE_DESC desc{12,1,&argument,0};
        hr(FrameSurvey::oSignature(h.device.Get(),&desc,nullptr,IID_PPV_ARGS(&signature)));
        NativeFixtureRegister(signature.Get());FrameSurvey::CommandSignatureCreated(signature.Get(),desc,nullptr);
        arguments=h.upload(0);void* mapped=nullptr;hr(arguments->Map(0,nullptr,&mapped));const UINT groups[]={1,1,1};
        std::memcpy(mapped,groups,sizeof(groups));arguments->Unmap(0,nullptr);
    }
    void Record()
    {
        h.list->SetPipelineState(pipeline.Get());
        FrameSurvey::ComputeBindings before;need(D3D12Hooks::GetComputeBindingsForBridge(h.list.Get(),before),
            "native prefix has a complete current root/heap snapshot before pure indirect");
        h.list->ExecuteIndirect(signature.Get(),1,arguments.Get(),0,nullptr,0);
        FrameSurvey::ComputeBindings after;need(D3D12Hooks::GetComputeBindingsForBridge(h.list.Get(),after)&&
            after.root==before.root&&after.heaps==before.heaps&&after.tables.size()==before.tables.size()&&
            std::equal(after.tables.begin(),after.tables.end(),before.tables.begin(),[](const auto& a,const auto& b){return a.first==b.first&&a.second.ptr==b.second.ptr;})&&
            after.views.size()==before.views.size()&&std::equal(after.views.begin(),after.views.end(),before.views.begin(),
                [](const auto& a,const auto& b){return a.parameter==b.parameter&&a.kind==b.kind&&a.address==b.address;}),
            "execution-only indirect before RR activation preserves the unchanged native root/heaps/tables");
    }
};

template<class T> J HotActivation(Host& h,T& title)
{
    ColdPureIndirect cold(h,title);
    // The user was already playing with RR OFF when the menu enabled it.
    for(UINT frame=1;frame<=3;++frame)
    {
        title.Begin(frame);title.A();title.B();title.ConsumerA();title.ConsumerB();
        need(!D3D12Hooks::CanRestoreRootSignature(h.list.Get())&&D3D12Hooks::ComputeRestoreFailureReason()&&
             std::string(D3D12Hooks::ComputeRestoreFailureReason())=="restore_configuration_disabled",
             "OFF prefix diagnoses the actual cold restore flags without preparing RR");
        need(RecordedComputeLease::RequiredSubmissionFailure()==S_OK&&!NrdBridge::GetStatus().nativeHistoryDirty,
             "native-only prefix cannot create a mandatory RR failure");
        need(NativeFixture::Execute(h),"native prefix submits before hot activation");h.reset();
    }
    J rows=J::array();std::array<ffxContext,2> contexts{};
    for(UINT frame=4;frame<=5;++frame)
    {
        title.Begin(frame);
        {
            std::promise<void> locked,completed;auto held=locked.get_future(),done=completed.get_future();
            std::atomic<bool> timedOut=false;
            std::jthread holder([&]{std::scoped_lock lock(NrdBridge::gInjectionMutex);locked.set_value();
                if(done.wait_for(std::chrono::seconds(5))!=std::future_status::ready)timedOut=true;});
            held.wait();cold.Record();completed.set_value();holder.join();
            need(!timedOut,"pre-Recon execution-only indirect makes progress while another thread owns the injection mutex");
            h.uav(title.checksum.Get());
        }
        if(frame==4)
        {
            // Bind the complete Recon while still OFF; enabling does not rely on
            // another root setter or Reset to seed the upcoming native source.
            h.list->SetPipelineState(title.pso[UINT(Role::Recon)].Get());
            h.list->SetComputeRootDescriptorTable(1,title.visible->GetGPUDescriptorHandleForHeapStart());
            h.list->SetComputeRootDescriptorTable(5,{title.visible->GetGPUDescriptorHandleForHeapStart().ptr+UINT64(8)*title.increment});
            NrdBridge::SetRuntimeEnabled(true);
            need(Config::Instance()->RestoreComputeSignature.value_or_default()&&Config::Instance()->ExtendedStateRestore.value_or_default(),
                 "menu enable admits both previously false restore configuration flags");
            need(D3D12Hooks::CanRestoreRootSignature(h.list.Get())&&!D3D12Hooks::ComputeRestoreFailureReason(),
                 "hot enable clears the cold restore failure without another native setter");
            h.list->Dispatch(16,16,1);h.uav(title.checksum.Get());
            title.Compute(Role::PrePass,0,24);title.Compute(Role::Temporal,16,24);title.Compute(Role::Chain3,0,24);
            title.Compute(Role::HistSave,0,24);title.Compute(Role::HistFix,0,24);title.Compute(Role::Clamp,0,24);
            for(UINT i=0;i<3;++i)title.Compute(Role::ATrous,0,i==2?32:24);
        }
        else title.A();
        title.B();title.ConsumerA();title.ConsumerB();
        const auto state=NrdBridge::gService->lists.at(h.list.Get()).native;
        need(state[0]&&state[1]&&state[0]->committed&&state[1]->committed&&NrdBridge::GetStatus().active,
             "hot activation commits independent current A/B RR transactions");
        auto read=h.buffer(1024,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
        h.barrier(title.checksum.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
        h.list->CopyBufferRegion(read.Get(),0,title.checksum.Get(),0,1024);h.barrier(title.checksum.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        need(NativeFixture::Execute(h),"hot activated native A/B batch passes original queue admission");
        NativeFixture::RootChecks(h,title,read);
        void* mapped=nullptr;hr(read->Map(0,nullptr,&mapped));
        need(static_cast<const UINT*>(mapped)[13*16+11]==1,
             "cold pure indirect forwards exactly once and executes on the actual GPU");read->Unmap(0,nullptr);
        for(UINT chain=0;chain<2;++chain)
        {
            const auto& provider=FfxApiProxy::records[(frame-4)*2+chain];
            if(frame==4)contexts[chain]=provider.context;
            need(provider.context==contexts[chain]&&bool(provider.flags&FFX_DENOISER_DISPATCH_RESET)==(frame==4),
                 "hot activation creates separate RESET histories and continues them next frame");
        }
        rows.push_back({{"SL_frame",frame},{"native_filter_gpu_executions",0},{"signed_dispatches",2}});h.reset();
    }
    NrdBridge::SetRuntimeEnabled(false);
    need(NrdBridge::RuntimeEnabled()&&NrdBridge::GetStatus().runtimeDisablePending&&NrdBridge::GetStatus().nativeHistoryDirty,
         "after native omission a menu OFF request never resumes native NRD");
    return rows;
}

int main(int argc,char** argv)try
{
    need(argc==4,"scratch output, signed AMD provider and root/table/table0 mode");const std::string mode=argv[3];
    const bool indirectNegative=mode=="native-indirect",negative=mode=="missing-table"||indirectNegative;
    need(mode=="root"||mode=="table"||mode=="table0"||negative,"bounded hot activation mode");
    NativeFixture::Bootstrap();Host h;NativeFixtureRegister(h.device.Get());NativeFixtureRegister(h.list.Get());
    g_dllPath=std::filesystem::path(argv[1])/"fixture.dll";
    Config::Instance()->FfxDenoiserNrdBridge.value=true;Config::Instance()->FfxDenoiserNrdBridgeEnabled.value=false;
    Config::Instance()->RestoreComputeSignature.value=false;Config::Instance()->ExtendedStateRestore.value=false;
    NrdBridge::ConfigureStartup(true);loadProvider(argv[2]);FrameSurvey::BeginCreationTracking(false);
    need(FrameSurvey::Install(h.device.Get(),h.list.Get(),false)&&NrdBridge::Initialize(h.device.Get()),"actual cold coordinator/metadata startup with runtime OFF");
    AttachRoots(h.list.Get());Wiring::Attach(h.list.Get());NativeDraw::Attach(h.list.Get());NrdBridge::SetNativeElisionContractForTesting(true);
    struct Hooks{~Hooks(){NativeDraw::Detach();Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();}}hooks;
    struct DebugCleanup{~DebugCleanup(){emitDebug={};}}debugCleanup;
    J result;
    {
        std::unique_ptr<NativeFixture::NativeTitle> ordinary;std::unique_ptr<TableZeroTitle> table0;
        if(mode=="table0")table0=std::make_unique<TableZeroTitle>(h);else ordinary=std::make_unique<NativeFixture::NativeTitle>(h,mode=="table");
        struct Cleanup{Host& h;~Cleanup(){h.waitComplete();NrdBridge::Shutdown();RecordedComputeLease::Detach(RecordedComputeLease::Capture(h.list.Get()));RecordedComputeLease::Poll();}}cleanup{h};
        if(negative)
        {
            auto& title=*ordinary;std::optional<ColdPureIndirect> indirect;
            if(indirectNegative)indirect.emplace(h,title);
            title.Begin(1);
            h.list->SetPipelineState(title.pso[UINT(Role::Recon)].Get());
            h.list->SetComputeRootDescriptorTable(1,title.visible->GetGPUDescriptorHandleForHeapStart());
            h.list->SetComputeRootDescriptorTable(5,{title.visible->GetGPUDescriptorHandleForHeapStart().ptr+UINT64(8)*title.increment});
            NrdBridge::SetRuntimeEnabled(true);
            if(indirectNegative)
                h.list->ExecuteIndirect(indirect->signature.Get(),1,indirect->arguments.Get(),0,nullptr,0);
            else
            {
                // Missing-observer control: native bindings remain valid, but
                // an unproven restore row must still deny this batch.
                {std::unique_lock lock(rootStatesMutex);rootStates.at(h.list.Get())[5].type=RootEntryType::Invalid;}
                h.list->Dispatch(16,16,1);
            }
            const auto status=NrdBridge::GetStatus();
            need(status.reason.find(indirectNegative?"unsupported_native_indirect role=2":"gate=compute_restore reason=native_p1_or_p5_table_missing")!=std::string::npos,
                 "initial required-admission failure identifies its exact gate and restoration cause");
            need(RecordedComputeLease::RequiredSubmissionFailure()==E_FAIL&&FfxApiProxy::dispatches==0,
                 "diagnostic reporting preserves exact fatal submission policy before any provider call");
            need(!NativeFixture::Execute(h)&&h.tick==0&&h.denied==1,
                 "diagnostic negative cannot forward incomplete original GPU work");
            result["failure_reason"]=status.reason;
        }
        else result["frames"]=table0?HotActivation(h,*table0):HotActivation(h,*ordinary);
    }
    need(FfxApiProxy::creates==(negative?0u:2u)&&FfxApiProxy::destroys==(negative?0u:2u)&&FfxApiProxy::dispatches==(negative?0u:4u),"hot activation owns only the expected fenced signed contexts");
    const auto debug=h.debugCounts();result["native_checks"]=checks;result["debug_errors"]=debug[0];result["debug_warnings"]=debug[1];
    result["provider_dispatches"]=FfxApiProxy::dispatches;result["native_submissions"]=h.tick;result["mode"]=mode;
    result["scope"]="actual coordinator/native GPU detours/raw/two signed RR domains/hot enable; explicit shipping-role/Release adapters; table0 is a synthetic 32-parameter unbounded-SRV root, not the exact game root blob or decorated game COM surface";
    std::ofstream(std::filesystem::path(argv[1])/"hot-activation-result.json")<<result.dump(2)<<'\n';
    std::cout<<"PASS hot_activation "<<checks<<'\n';return 0;
}
catch(const std::exception& error)
{
    const auto state=NrdBridge::GetStatus();std::cerr<<"FAIL hot_activation: "<<error.what()<<" phase="<<state.phase<<" reason="<<state.reason<<'\n';return 1;
}
