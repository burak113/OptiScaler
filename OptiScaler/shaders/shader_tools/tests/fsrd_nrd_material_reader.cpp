// Explicit title shader/readiness adapters. Real D3D12, native metadata,
// production capture/admission, signed AMD RR and GPU readbacks.
struct MaterialReaderTitle {
 NativeMaterialTitle& writer; ComPtr<ID3D12PipelineState> pso,unknown;
 UINT dispatches=0; bool bad=false;
 MaterialReaderTitle(NativeMaterialTitle& w):writer(w){
  const char code[]=R"(
Texture2D<float4> Base:register(t7);Texture2D<float4> Params:register(t9);
RWStructuredBuffer<uint> Check:register(u0,space1);
[numthreads(1,1,1)]void main(){Check[13]=(uint)round(Base.Load(int3(0,0,0)).r*1023);
Check[14]=(uint)round(Params.Load(int3(0,0,0)).g*65535);InterlockedAdd(Check[15],1);})";
  ComPtr<ID3DBlob> cs,error;hr(D3DCompile(code,sizeof(code),nullptr,nullptr,nullptr,"main","cs_5_1",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&cs,&error));
  D3D12_COMPUTE_PIPELINE_STATE_DESC d{};d.pRootSignature=w.root.Get();d.CS={cs->GetBufferPointer(),cs->GetBufferSize()};
  for(auto* target:{std::addressof(pso),std::addressof(unknown)}){hr(w.h.device->CreateComputePipelineState(&d,IID_PPV_ARGS(target->GetAddressOf())));NativeFixturePipelineCreated(target->Get(),d);}
  NrdBridge::RegisterPipelineRoleForTesting(pso.Get(),NrdBridge::Role::MaterialRead,true);
 }
 void dispatch(bool recognized=true,bool badProfile=false){
  writer.bind(badProfile);writer.h.list->SetPipelineState(recognized?pso.Get():unknown.Get());
  writer.h.list->Dispatch(1,1,1);writer.h.uav(writer.check.Get());++dispatches;bad=badProfile;
 }
 void validate(ID3D12Resource* read){void* mapped=nullptr;hr(read->Map(0,nullptr,&mapped));const auto* p=static_cast<const UINT*>(mapped);
  need(p[13]==128&&p[14]==(bad?UINT(std::lround(512.f/1023*65535)):77u*257)&&p[15]==dispatches,
       "original reader still reads exact t7/t9 and UAV after injected capture restores roots/heaps/PSO");read->Unmap(0,nullptr);}
};

int main(int argc,char** argv)try{
 need(argc==3,"output directory and signed provider required");
 NativeFixture::Bootstrap();Host h;NativeFixtureRegister(h.device.Get());NativeFixtureRegister(h.list.Get());
 g_dllPath=std::filesystem::path(argv[1])/"fixture.dll";Config::Instance()->FfxDenoiserNrdBridge.value=true;
 NrdBridge::ConfigureStartup(true);loadProvider(argv[2]);FrameSurvey::BeginCreationTracking(false);
 need(FrameSurvey::Install(h.device.Get(),h.list.Get(),false),"native metadata install");need(NrdBridge::Initialize(h.device.Get()),"coordinator initialize");
 AttachRoots(h.list.Get());Wiring::Attach(h.list.Get());NativeDraw::Attach(h.list.Get());NrdBridge::SetNativeElisionContractForTesting(true);
 const std::string hash="88c255d29535f9153f7101c32be4f58682675fb8391c94efc135fd6959875e6d";
 need(NrdBridge::IdentifyRole(hash)==NrdBridge::Role::MaterialRead,"exact reader hash admitted");
 need(NrdBridge::IdentifyRole(hash.substr(0,8))==NrdBridge::Role::None&&NrdBridge::IdentifyRole(hash.substr(0,63)+"0")==NrdBridge::Role::None,"reader prefix and changed hash rejected");
 J rows=J::array();
 {
  NativeFixture::NativeTitle title(h,false);NativeMaterialTitle writer(title,true);MaterialReaderTitle reader(writer);
  auto alternate=writer.texture(DXGI_FORMAT_R10G10B10A2_UNORM,false);writer.upload(alternate.Get(),writer.baseWords.data());
  auto shared=writer.texture(DXGI_FORMAT_R10G10B10A2_UNORM,false,D3D12_HEAP_FLAG_SHARED);
  NrdBridge::RRSettings settings;settings.nativeMaterialGuides=true;std::string error;need(NrdBridge::ApplyRRSettings(settings,false,error),"enable material guides");
  const std::array<const char*,19> modes={"no_reader","reader_no_local_barriers","unrelated_placed_alias","direct_alias","global_alias","opaque_work","source_transition","reader_bad_profile","writer_bad_profile","option_off","option_on","recording_reset","cancellation","different_source","second_writer","second_reader","combined_read_state","unknown_shader","shared_alias"};
  for(UINT frame=0;frame<modes.size();++frame){
   const std::string mode=modes[frame];const bool expected=frame==1||frame==2||frame==10||frame==15||frame==16;
   const auto combined=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
   if(mode=="combined_read_state"){
    for(auto* r:{writer.base.Get(),writer.params.Get()})h.barrier(r,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,combined);
    need(NativeFixture::Execute(h),"source transitions complete in a separate prolog recording");h.reset();
   }
   if(frame==9||frame==10){settings.nativeMaterialGuides=frame==10;need(NrdBridge::ApplyRRSettings(settings,false,error),"material toggle applies");}
   writer.start();reader.dispatches=0;const auto before=NrdBridge::GetStatus();
   if(frame)reader.dispatch(mode!="unknown_shader",mode=="reader_bad_profile");
   if(mode=="option_off"||mode=="unknown_shader")need(NrdBridge::GetStatus().nativeMaterialReaderSnapshots==before.nativeMaterialReaderSnapshots,"OFF and unknown PSO perform no optional capture");
   if(mode=="direct_alias"||mode=="global_alias"||mode=="shared_alias"){
    D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_ALIASING;
    b.Aliasing={nullptr,mode=="direct_alias"?writer.base.Get():mode=="shared_alias"?shared.Get():nullptr};h.list->ResourceBarrier(1,&b);
   }
   if(mode=="opaque_work")NrdBridge::InvalidateRecordingProof(h.list.Get(),"fixture opaque work");
   if(mode=="source_transition"){
    h.barrier(writer.base.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_SOURCE);
    h.barrier(writer.base.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
   }
   if(mode=="recording_reset"){
    const auto read=writer.captureCheck();need(NativeFixture::Execute(h),"early snapshot submission completes before reset");reader.validate(read.Get());
    h.reset();writer.start();reader.dispatches=0;
   }
   if(mode=="cancellation"){
    settings.nativeMaterialGuides=false;need(NrdBridge::ApplyRRSettings(settings,false,error),"cancel early material recording");
    settings.nativeMaterialGuides=true;need(NrdBridge::ApplyRRSettings(settings,false,error),"re-enable requires fresh material reader");
   }
   // Use a separate descriptor heap: modifying a shader-visible descriptor in place
   // before submission would retroactively change the earlier GPU reader as well.
   ComPtr<ID3D12DescriptorHeap> oldHeap;
   if(mode=="different_source"){
    oldHeap=writer.heap;const auto hd=oldHeap->GetDesc();hr(h.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&writer.heap)));
    NativeFixtureHeapCreated(h.device.Get(),writer.heap.Get());
    for(UINT i=0;i<8;++i)writer.srv(i,i==7?alternate.Get():title.tex[0].Get());
    writer.srv(8,title.tex[0].Get());writer.srv(9,writer.params.Get());writer.srv(10,title.tex[0].Get());writer.srv(11,writer.base.Get());
    for(UINT i=0;i<5;++i){D3D12_UNORDERED_ACCESS_VIEW_DESC d{};auto* r=i==4?title.tex[2].Get():title.tex[9].Get();
     d.Format=r->GetDesc().Format;d.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
     D3D12_CPU_DESCRIPTOR_HANDLE at{writer.heap->GetCPUDescriptorHandleForHeapStart().ptr+UINT64(16+i)*title.increment};
     h.device->CreateUnorderedAccessView(r,nullptr,&d,at);FrameSurvey::View(r,at,&d);}
   }
   if(mode=="second_reader")reader.dispatch();
   writer.dispatch(false,false,mode=="writer_bad_profile",mode=="unrelated_placed_alias"?title.tex[2].Get():nullptr);
   if(mode=="second_writer")writer.dispatch(false);
   const auto status=NrdBridge::GetStatus();const bool captured=bool(NrdBridge::gService->lists.at(h.list.Get()).pendingMaterial.snapshot);
   std::cout<<"reader mode="<<mode<<" captured="<<captured<<" expected="<<expected<<" reason="<<status.nativeMaterialCaptureReason<<" reader="<<status.nativeMaterialReaderReason<<std::endl;
   need(captured==expected,"early reader admission follows exact recording/source/invalidation contract");
   if(expected)need(status.nativeMaterialCaptureReason=="captured_from_reader","successful no-local-barrier case uses early snapshot");
   title.Begin(frame+1);title.A();title.ConsumerA();auto stage=NrdBridge::gService->lists.at(h.list.Get()).native[0];
   need(stage&&stage->committed,"actual native A transaction commits");need(NrdBridge::GetStatus().nativeMaterialGuidesActive==expected,"RR material active reflects actual current admission");
   need(FfxApiProxy::lastDispatch.diffuseAlbedo.resource==stage->inputs.diffAlbedo&&FfxApiProxy::lastDispatch.specularAlbedo.resource==stage->inputs.specAlbedo,"signed AMD provider consumes exact readback guide resources");
   const auto d=title.readback(stage->inputs.diffAlbedo,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),s=title.readback(stage->inputs.specAlbedo,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
   const auto state=mode=="combined_read_state"?combined:D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
   const auto base=title.readback(writer.base.Get(),state),params=title.readback(writer.params.Get(),state);
   const auto check=writer.captureCheck();
   need(NativeFixture::Execute(h),"native material recording submitted");writer.validateCheck(check.Get());if(reader.dispatches)reader.validate(check.Get());
   const auto db=materialBytes(d,4),sb=materialBytes(s,4),bb=materialBytes(base,4),pb=materialBytes(params,4);
   need(std::memcmp(bb.data(),writer.baseWords.data(),bb.size())==0&&pb==writer.parameterBytes,"material source bytes unchanged");
   size_t nonwhite=0;for(size_t i=0;i<db.size();++i)if(i%4!=3)nonwhite+=db[i]!=255;
   need((nonwhite>0)==expected,"GPU guide pixels are colored exactly on accepted reader cases");
   materialSave(std::filesystem::path(argv[1])/(mode+"-diff.bin"),db);materialSave(std::filesystem::path(argv[1])/(mode+"-spec.bin"),sb);
   rows.push_back({{"mode",mode},{"material_applied",expected},{"nonwhite_diffuse_components",nonwhite},{"capture_reason",status.nativeMaterialCaptureReason},{"reader_reason",status.nativeMaterialReaderReason}});
   if(oldHeap)writer.heap=oldHeap;h.reset();
   if(mode=="combined_read_state"){
    for(auto* r:{writer.base.Get(),writer.params.Get()})h.barrier(r,combined,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    need(NativeFixture::Execute(h),"combined state restored outside next reader recording");h.reset();
   }
  }
  need(titleTransitions==0,"early material capture emits no borrowed title source transitions");
  titleTextures.erase(alternate.Get());titleTextures.erase(shared.Get());
  h.waitComplete();NrdBridge::Shutdown();auto recording=RecordedComputeLease::Capture(h.list.Get());RecordedComputeLease::Detach(recording);RecordedComputeLease::Poll();
 }
 NativeDraw::Detach();Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();const auto debug=h.debugCounts();
 need(FfxApiProxy::creates==FfxApiProxy::destroys,"all signed provider contexts retire");
 J result={{"frames",rows},{"native_checks",checks},{"debug_errors",debug[0]},{"debug_warnings",debug[1]},{"borrowed_title_transitions",titleTransitions},{"dispatches",FfxApiProxy::dispatches},{"contexts",FfxApiProxy::creates},{"destroyed",FfxApiProxy::destroys},{"synthetic_title_psos_and_readiness",true},{"game_quality_proof",false}};
 std::ofstream(std::filesystem::path(argv[1])/"material-reader-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS material_reader "<<checks<<std::endl;return 0;
}catch(const std::exception& e){std::cerr<<"FAIL material_reader: "<<e.what()<<std::endl;return 1;}
