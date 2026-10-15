// NEW actual-host transaction proof. Synthetic shipping-role/profile selection
// is explicit; native D3D, GUID/Birth metadata, private shaders and AMD are real.
namespace NativeFixture {
struct Retirement { FrameSurvey::RetirementEffects effects; };
void* Factory() noexcept { auto* p=new(std::nothrow) Retirement;if(p&&!FrameSurvey::PrepareRetirementEffects(p->effects)){delete p;return nullptr;}return p; }
bool Detach(void* p,const NrdBridgeBirth::Token& token) noexcept {return p&&FrameSurvey::DetachReleaseMetadata(token,static_cast<Retirement*>(p)->effects);}
void Notify(void* p) noexcept {auto* value=static_cast<Retirement*>(p);FrameSurvey::NotifyRelease(value->effects);delete value;}
void Bootstrap() {
 need(NrdBridgeNativeBirth::ConfigureRetirement(Factory,Detach,Notify),"real native retirement metadata dispatcher configured");
 need(NrdBridgeNativeBirth::Ready()&&NrdBridgeLifetime::EnableConcurrentReleases(),"real native Ready and exclusive physical Borrow mode active");
}
void Upload(Host& h,ID3D12Resource* target,D3D12_RESOURCE_STATES state,const std::vector<uint16_t>& words) {
 const auto desc=target->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT64 size=0;
 h.device->GetCopyableFootprints(&desc,0,1,0,&fp,nullptr,nullptr,&size);auto buffer=h.buffer(size,D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
 void* mapped=nullptr;hr(buffer->Map(0,nullptr,&mapped));std::memset(mapped,0,size_t(size));
 for(UINT y=0;y<desc.Height;++y)std::memcpy(static_cast<uint8_t*>(mapped)+size_t(y)*fp.Footprint.RowPitch,words.data()+size_t(y)*desc.Width*4,size_t(desc.Width)*8);
 buffer->Unmap(0,nullptr);h.barrier(target,state,D3D12_RESOURCE_STATE_COPY_DEST);
 D3D12_TEXTURE_COPY_LOCATION a{},b{};a.pResource=buffer.Get();a.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;a.PlacedFootprint=fp;b.pResource=target;b.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
 h.list->CopyTextureRegion(&b,0,0,0,&a,nullptr);h.barrier(target,D3D12_RESOURCE_STATE_COPY_DEST,state);h.uploads.push_back(buffer);
}
bool Execute(Host& h,bool close=true) {
 if(close){const HRESULT result=h.list->Close();hr(result);NrdBridge::OnRecordingClosed(h.list.Get(),result);}
 NrdBridgeDescriptorAdmission::Submission admission(true);need(admission.Acquired(),"actual descriptor admission closes and drains native writers before proof");
 ID3D12CommandList* list=h.list.Get();RecordedComputeLease::SubmissionDecision decision;
 auto batch=ResTrack_Dx12::BeforeComputeSubmission(h.queue.Get(),1,&list,&decision);
 if(!decision.allowed){++h.denied;h.lastOrderingFailure=decision.orderingFailure;return false;}
 h.queue->ExecuteCommandLists(1,&list);RecordedComputeLease::AfterSubmission(batch);hr(h.queue->Signal(h.fence.Get(),++h.tick));
 h.waitComplete();return true;
}
const char graphicsShader[]=R"(
cbuffer C:register(b0){uint C0,C1,C2,P3,P4,C5,P6,P7;};
cbuffer B:register(b6){uint4 Words[96];};cbuffer Extent:register(b8){uint Width,Height;};
StructuredBuffer<uint> RootSRV:register(t0,space1);RWStructuredBuffer<uint> Checks:register(u0,space1);
Texture2D<float4> D:register(t11);Texture2D<float4> S:register(t12);SamplerState PointS:register(s0);
float4 VS(uint id:SV_VertexID):SV_Position {return float4(id==2?3:-1,id==1?3:-1,0,1);}
float3 Decode(float3 c){return Words[9].x==0?c:max(float3(c.x-c.z+c.y,c.x+c.z,c.x-c.z-c.y),0);}
float4 PS(float4 p:SV_Position):SV_Target {
 float3 s=Decode(S.Load(int3(uint2(p.xy),0)).rgb),d=Decode(D.Load(int3(uint2(p.xy),0)).rgb);
 if(all(uint2(p.xy)==0)){
  uint b=14*16;Checks[b]=C0;Checks[b+1]=C1;Checks[b+2]=C2;Checks[b+3]=C5;Checks[b+4]=Words[0].x;Checks[b+5]=RootSRV[0];Checks[b+6]=Width;Checks[b+7]=Height;
  Checks[b+8]=asuint(s.x);Checks[b+9]=14;Checks[b+10]=asuint(Decode(S.SampleLevel(PointS,float2(.5/Width,.5/Height),0).rgb).x);InterlockedAdd(Checks[b+11],1);
 }
 return float4(s+d,1);
})";
struct NativeTitle:Title {
 std::array<ComPtr<ID3D12DescriptorHeap>,2> oldHeaps;
 std::array<ComPtr<ID3D12Resource>,2> noisyB;ComPtr<ID3D12Resource> color;
 ComPtr<ID3D12DescriptorHeap> rtv;ComPtr<ID3D12RootSignature> graphicsRoot;ComPtr<ID3D12PipelineState> graphics;
 NativeTitle(Host& h,bool table):Title(h,128,128,true,table,false) {
  oldHeaps={staging,visible};D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;hd.NumDescriptors=128;
  hr(h.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&staging)));hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;hr(h.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&visible)));
  NativeFixtureHeapCreated(h.device.Get(),staging.Get());NativeFixtureHeapCreated(h.device.Get(),visible.Get());views();
  for(UINT role=1;role<=10;++role)NrdBridge::RegisterPipelineRoleForTesting(pso[role].Get(),Role(role),true);
  for(UINT lobe=0;lobe<2;++lobe){const auto desc=tex[0]->GetDesc();D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
   hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,nullptr,IID_PPV_ARGS(&noisyB[lobe])));
   NativeFixtureResourceCreated(noisyB[lobe].Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
   auto values=raw[lobe];for(size_t p=0;p<values.size();p+=4)for(UINT c=0;c<3;++c)values[p+c]=PackedVector::XMConvertFloatToHalf(PackedVector::XMConvertHalfToFloat(values[p+c])*.5f);
   Upload(h,noisyB[lobe].Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,values);
  }
  for(UINT i=0;i<8;++i)for(UINT tableBase:{64u,72u}){auto* resource=i==0?noisyB[0].Get():i==1?noisyB[1].Get():i==2?(tableBase==72?tex[6].Get():tex[2].Get()):i==3?(tableBase==72?tex[2].Get():tex[3].Get()):tex[3].Get();
   D3D12_SHADER_RESOURCE_VIEW_DESC view{};view.Format=resource->GetDesc().Format;view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;view.Texture2D.MipLevels=1;
   const D3D12_CPU_DESCRIPTOR_HANDLE dst{visible->GetCPUDescriptorHandleForHeapStart().ptr+UINT64(tableBase+i)*increment};h.device->CreateShaderResourceView(resource,&view,dst);FrameSurvey::View(resource,dst,&view);
  }
  for(UINT lobe=0;lobe<2;++lobe){D3D12_SHADER_RESOURCE_VIEW_DESC view{};view.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;view.Texture2D.MipLevels=1;
   auto* resource=tex[lobe?11:12].Get();const D3D12_CPU_DESCRIPTOR_HANDLE dst{visible->GetCPUDescriptorHandleForHeapStart().ptr+UINT64(83+lobe)*increment};h.device->CreateShaderResourceView(resource,&view,dst);FrameSurvey::View(resource,dst,&view);}
  D3D12_DESCRIPTOR_RANGE ranges[2]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,5,8,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_SAMPLER,1,0,0,0}};
  D3D12_ROOT_PARAMETER parameters[25]{};for(UINT i=0;i<25;++i){parameters[i].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;parameters[i].Constants={200+i,0,1};}
  parameters[0].Constants={0,0,8};parameters[2].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV;parameters[2].Descriptor={6,0};
  parameters[3].ParameterType=D3D12_ROOT_PARAMETER_TYPE_SRV;parameters[3].Descriptor={0,1};parameters[4].ParameterType=D3D12_ROOT_PARAMETER_TYPE_UAV;parameters[4].Descriptor={0,1};
  parameters[6].Constants={8,0,2};parameters[7].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;parameters[7].DescriptorTable={1,&ranges[1]};parameters[24].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;parameters[24].DescriptorTable={1,&ranges[0]};
  D3D12_ROOT_SIGNATURE_DESC signature{25,parameters,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE};ComPtr<ID3DBlob> bytes,error;hr(D3D12SerializeRootSignature(&signature,D3D_ROOT_SIGNATURE_VERSION_1,&bytes,&error));
  hr(h.device->CreateRootSignature(0,bytes->GetBufferPointer(),bytes->GetBufferSize(),IID_PPV_ARGS(&graphicsRoot)));rootSigParameterCount[graphicsRoot.Get()]=25;NativeFixtureRootCreated(graphicsRoot.Get(),bytes->GetBufferPointer(),bytes->GetBufferSize());
  ComPtr<ID3DBlob> vs,ps;hr(D3DCompile(graphicsShader,sizeof(graphicsShader),nullptr,nullptr,nullptr,"VS","vs_5_1",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&vs,&error));hr(D3DCompile(graphicsShader,sizeof(graphicsShader),nullptr,nullptr,nullptr,"PS","ps_5_1",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&ps,&error));
  D3D12_GRAPHICS_PIPELINE_STATE_DESC pd{};pd.pRootSignature=graphicsRoot.Get();pd.VS={vs->GetBufferPointer(),vs->GetBufferSize()};pd.PS={ps->GetBufferPointer(),ps->GetBufferSize()};pd.BlendState.RenderTarget[0].RenderTargetWriteMask=D3D12_COLOR_WRITE_ENABLE_ALL;pd.BlendState.RenderTarget[0].SrcBlend=pd.BlendState.RenderTarget[0].SrcBlendAlpha=D3D12_BLEND_ONE;pd.BlendState.RenderTarget[0].DestBlend=pd.BlendState.RenderTarget[0].DestBlendAlpha=D3D12_BLEND_ZERO;pd.BlendState.RenderTarget[0].BlendOp=pd.BlendState.RenderTarget[0].BlendOpAlpha=D3D12_BLEND_OP_ADD;pd.SampleMask=UINT_MAX;
  pd.RasterizerState.FillMode=D3D12_FILL_MODE_SOLID;pd.RasterizerState.CullMode=D3D12_CULL_MODE_NONE;pd.DepthStencilState.DepthEnable=false;pd.DepthStencilState.DepthFunc=D3D12_COMPARISON_FUNC_ALWAYS;pd.DepthStencilState.StencilEnable=false;pd.PrimitiveTopologyType=D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;pd.NumRenderTargets=1;pd.RTVFormats[0]=DXGI_FORMAT_R16G16B16A16_FLOAT;pd.SampleDesc.Count=1;
  hr(h.device->CreateGraphicsPipelineState(&pd,IID_PPV_ARGS(&graphics)));NativeFixturePipelineCreated(graphics.Get(),pd);
  NrdBridge::OnGraphicsPipelineCreated(graphics.Get(),"051b199b86af56c7bae475bc150a7e5572b53daa44b117e473295100d9c38cc4"); // Explicit shipping-role attestation adapter only.
  auto desc=tex[0]->GetDesc();desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;D3D12_HEAP_PROPERTIES hp{};hp.Type=D3D12_HEAP_TYPE_DEFAULT;
  hr(h.device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_RENDER_TARGET,nullptr,IID_PPV_ARGS(&color)));
  hd={};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_RTV;hd.NumDescriptors=1;hr(h.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&rtv)));h.device->CreateRenderTargetView(color.Get(),nullptr,rtv->GetCPUDescriptorHandleForHeapStart());
  for(UINT index:{7u,8u,11u,12u}){std::vector<uint16_t> values(size_t(width)*height*4);for(size_t p=0;p<values.size();p+=4){values[p]=0x7e00;values[p+1]=0x7e00;values[p+2]=0x7e00;values[p+3]=PackedVector::XMConvertFloatToHalf(index==7||index==11?9.f:11.f);}Upload(h,tex[index].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,values);}
 }
 void SetWords(UINT aCodec=0,UINT bCodec=0){void* p=nullptr;hr(cb->Map(0,nullptr,&p));auto* w=static_cast<UINT*>(p);w[303]=aCodec;w[36]=bCodec;w[118]=width;w[119]=height;w[144]=w[145]=2;cb->Unmap(0,nullptr);codecBits=aCodec;}
 void Begin(UINT frame){SetWords();begin(frame);if(tableConstants)bindConstants(cb.Get(),127);pass(Role::PrepLast);}
 void Compute(Role role,UINT srv,UINT uav){h.list->SetPipelineState(pso[UINT(role)].Get());h.list->SetComputeRootDescriptorTable(1,{visible->GetGPUDescriptorHandleForHeapStart().ptr+UINT64(srv)*increment});h.list->SetComputeRootDescriptorTable(5,{visible->GetGPUDescriptorHandleForHeapStart().ptr+UINT64(uav)*increment});h.list->Dispatch(16,16,1);h.uav(checksum.Get());}
 void A(){Compute(Role::Recon,0,8);Compute(Role::PrePass,0,24);Compute(Role::Temporal,16,24);Compute(Role::Chain3,0,24);Compute(Role::HistSave,0,24);Compute(Role::HistFix,0,24);Compute(Role::Clamp,0,24);for(UINT i=0;i<3;++i)Compute(Role::ATrous,0,i==2?32:24);}
 void B(){Compute(Role::PrePass,64,24);Compute(Role::Temporal,72,24);Compute(Role::Clamp,64,24);for(UINT i=0;i<2;++i)Compute(Role::ATrous,64,40);}
 void ConsumerA(){Compute(Role::Consumer,0,48);}
 void ConsumerB(){h.barrier(tex[11].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);h.barrier(tex[12].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
  h.list->SetGraphicsRootSignature(graphicsRoot.Get());h.list->SetPipelineState(graphics.Get());const UINT roots[3]={11,22,33},extent[2]={width,height};h.list->SetGraphicsRoot32BitConstants(0,3,roots,0);h.list->SetGraphicsRoot32BitConstant(0,40,5);h.list->SetGraphicsRootConstantBufferView(2,cb->GetGPUVirtualAddress());h.list->SetGraphicsRootShaderResourceView(3,rootSrv->GetGPUVirtualAddress());h.list->SetGraphicsRootUnorderedAccessView(4,checksum->GetGPUVirtualAddress());h.list->SetGraphicsRoot32BitConstants(6,2,extent,0);h.list->SetGraphicsRootDescriptorTable(7,sampler->GetGPUDescriptorHandleForHeapStart());h.list->SetGraphicsRootDescriptorTable(24,{visible->GetGPUDescriptorHandleForHeapStart().ptr+UINT64(80)*increment});
  const auto target=rtv->GetCPUDescriptorHandleForHeapStart();h.list->OMSetRenderTargets(1,&target,FALSE,nullptr);const D3D12_VIEWPORT viewport{0,0,float(width),float(height),0,1};const D3D12_RECT rect{0,0,LONG(width),LONG(height)};h.list->RSSetViewports(1,&viewport);h.list->RSSetScissorRects(1,&rect);h.list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);h.list->DrawInstanced(3,1,0,0);h.uav(checksum.Get());
  h.barrier(tex[11].Get(),D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);h.barrier(tex[12].Get(),D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
 }
};
void RootChecks(Host& h,NativeTitle& title,const ComPtr<ID3D12Resource>& read){void* p=nullptr;hr(read->Map(0,nullptr,&p));const auto* words=static_cast<const UINT*>(p);
 for(UINT role=1;role<=10;++role){need(words[role*16+11]==UINT(role==1||role==10),"all native denoising originals have zero GPU executions; PrepLast and A composition execute once");}
 const UINT expected[8]={11,22,33,40,55,66,128,128};for(UINT role:{1u,10u,14u}){need(std::equal(expected,expected+8,words+role*16),"actual GPU sparse root constants/CBV/SRV/UAV/extent restored exactly");need(words[role*16+11]==1,"each surviving title shader executes exactly once");}read->Unmap(0,nullptr);}
J Positive(Host& h,NativeTitle& title){J rows=J::array();std::array<std::shared_ptr<NrdBridge::HistoryDomain>,2> histories;std::array<ffxContext,2> contexts{};UINT firstCreates=FfxApiProxy::creates;
 for(UINT frame=1;frame<=6;++frame){const UINT before=FfxApiProxy::dispatches;title.Begin(frame);title.A();title.B();need(FfxApiProxy::dispatches==before,"raw/geometry/motion capture runs before either late Consumer without provider or title writes");
  title.ConsumerA();title.ConsumerB();const auto& state=NrdBridge::gService->lists.at(h.list.Get());auto a=state.native[0],b=state.native[1];need(a&&b&&a->committed&&b->committed&&a->recording!=b->recording,"independent A/B transactions each commit their own exact retained token");need(FfxApiProxy::dispatches==before+2&&NrdBridge::GetStatus().active,"two real signed provider calls produce active RR-only A and B outputs");
  const auto as=a->history->rr.GetOwnedOutputSnapshot(a->owned),bs=b->history->rr.GetOwnedOutputSnapshot(b->owned);
  const std::array<Readback,2> outA{title.readback(7),title.readback(8)},outB{title.readback(11),title.readback(12)};
  const std::array<Readback,2> rrA{title.readback(as.selectedSpec,D3D12_RESOURCE_STATE_UNORDERED_ACCESS),title.readback(as.selectedDiff,D3D12_RESOURCE_STATE_UNORDERED_ACCESS)},rrB{title.readback(bs.selectedSpec,D3D12_RESOURCE_STATE_UNORDERED_ACCESS),title.readback(bs.selectedDiff,D3D12_RESOURCE_STATE_UNORDERED_ACCESS)};
  auto root=h.buffer(1024,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);h.barrier(title.checksum.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);h.list->CopyBufferRegion(root.Get(),0,title.checksum.Get(),0,1024);h.barrier(title.checksum.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  need(Execute(h),"complete A/B required transactions are allowed by actual descriptor/ledger submission");RootChecks(h,title,root);
  UINT64 exact=0;for(UINT chain=0;chain<2;++chain)for(UINT lobe=0;lobe<2;++lobe){const auto out=(chain?outB:outA)[lobe].signal(),rr=(chain?rrB:rrA)[lobe].signal();for(size_t p=0;p<out.size();p+=4){for(UINT c=0;c<3;++c){need(std::isfinite(PackedVector::XMConvertHalfToFloat(rr[p+c])),"actual signed RR stage RGB finite");need(out[p+c]==rr[p+c],"title RGB exclusively equals this chain's actual staged RR");++exact;}need(out[p+3]==PackedVector::XMConvertFloatToHalf(lobe?11.f:9.f),"every original opaque title alpha bit survives pure RR commit");}}
  for(UINT c=0;c<2;++c){const auto stage=c?b:a;const auto provider=FfxApiProxy::records[before+c];if(frame==1){histories[c]=stage->history;contexts[c]=provider.context;}need(histories[c]==stage->history&&contexts[c]==provider.context,"continuous A/B histories and physical providers are independent and stable");need(bool(provider.flags&FFX_DENOISER_DISPATCH_RESET)==(frame==1),"only first frame resets each native A/B provider history");}
  rows.push_back({{"SL_frame",frame},{"signed_dispatches",2},{"exact_rr_rgb_words",exact},{"native_filter_gpu_executions",0},{"A_context",uint64_t(uintptr_t(contexts[0]))},{"B_context",uint64_t(uintptr_t(contexts[1]))}});h.reset();
 }
 need(FfxApiProxy::creates==firstCreates+2,"six submitted A/B frames create exactly two physical SDK contexts");
 const auto deniedBefore=h.denied,dispatchBefore=FfxApiProxy::dispatches;
 title.Begin(7);title.A();title.B();title.ConsumerB();
 const auto incomplete=NrdBridge::gService->lists.at(h.list.Get()).native;
 need(incomplete[0]&&!incomplete[0]->committed&&incomplete[1]&&incomplete[1]->committed,"B's successful late RR commit cannot complete A's independent missing-Consumer token");
 need(!Execute(h)&&h.denied==deniedBefore+1&&FAILED(h.lastOrderingFailure),"actual beforeSubmit explicitly denies original native Execute for missing A Consumer");
 need(FfxApiProxy::dispatches==dispatchBefore+1,"incomplete denied chain recorded only B's actual signed SDK call");h.reset();
 title.Begin(8);title.A();title.B();title.ConsumerA();title.ConsumerB();
 need(Execute(h),"fresh complete native A/B transactions recover after discarded incomplete recording");
 need(FfxApiProxy::dispatches==dispatchBefore+3,"recovery records exactly one new actual signed call for each chain");
 for(UINT chain=0;chain<2;++chain){const auto& record=FfxApiProxy::records[dispatchBefore+1+chain];need(record.context!=contexts[chain]&&(record.flags&FFX_DENOISER_DISPATCH_RESET),"unsubmitted discarded predecessor gets physically fresh RESET history, never stale native fallback");}h.reset();
 return rows;
}
}
int main(int argc,char** argv)try{
 need(argc==3,"scratch output and actual signed AMD DLL");NativeFixture::Bootstrap();Host h;NativeFixtureRegister(h.device.Get());NativeFixtureRegister(h.list.Get());
 g_dllPath=std::filesystem::path(argv[1])/"fixture.dll";Config::Instance()->FfxDenoiserNrdBridge.value=true;NrdBridge::ConfigureStartup(true);loadProvider(argv[2]);FrameSurvey::BeginCreationTracking(false);need(FrameSurvey::Install(h.device.Get(),h.list.Get(),false),"actual native metadata registry installed");need(NrdBridge::Initialize(h.device.Get()),"actual production coordinator initialized");AttachRoots(h.list.Get());Wiring::Attach(h.list.Get());NativeDraw::Attach(h.list.Get());NrdBridge::SetNativeElisionContractForTesting(true);
 J result;{NativeFixture::NativeTitle title(h,false);result["frames"]=NativeFixture::Positive(h,title);NrdBridge::Shutdown();RecordedComputeLease::Poll();}
 need(FfxApiProxy::creates==FfxApiProxy::destroys,"all actual native A/B provider contexts retire after fenced recording detach");NativeDraw::Detach();Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();const auto debug=h.debugCounts();result["native_checks"]=checks;result["debug_errors"]=debug[0];result["debug_warnings"]=debug[1];result["provider_dispatches"]=FfxApiProxy::dispatches;result["contexts"]=FfxApiProxy::creates;result["missing_A_Consumer_denials"]=h.denied;result["discard_recovery"]=true;
 result["scope"]="actual hardware/coordinator/raw/geometry/motion/signedRR/303compute+36pixel/requiredledger; synthetic shipping role/readiness and caller-strong native Release-coverage adapters, not full title startup/physical Release detour proof";
 std::ofstream(std::filesystem::path(argv[1])/"native-transactions-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS native_transactions "<<checks<<'\n';return 0;
}catch(const std::exception& e){std::cerr<<"FAIL native_transactions: "<<e.what()<<std::endl;if(emitDebug)emitDebug();return 1;}
