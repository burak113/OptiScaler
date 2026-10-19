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
 if(!decision.allowed){++h.denied;h.lastOrderingFailure=decision.orderingFailure;
  const auto status=NrdBridge::GetStatus();std::cerr<<"native submission denied sdk="<<FfxApiProxy::dispatches<<" creates="<<FfxApiProxy::creates<<" frames="<<status.framesBridged<<" phase="<<status.phase<<" reason="<<status.reason<<" required="<<std::hex<<RecordedComputeLease::RequiredSubmissionFailure()<<" decision="<<decision.orderingFailure<<std::dec<<std::endl;return false;}
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
// Synthetic register-use profile only; all native shader hashes, roots,
// GUID births, pure command signature and retained current-slot proofs are real.
struct OpaqueWork {
 Host& h;NativeTitle& title;ComPtr<ID3D12RootSignature> root;ComPtr<ID3D12PipelineState> pipeline;
 ComPtr<ID3D12CommandSignature> signature;ComPtr<ID3D12Resource> arguments;
 OpaqueWork(Host& host,NativeTitle& owner):h(host),title(owner){
  D3D12_DESCRIPTOR_RANGE ranges[2]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,13,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,2,0,0,0}};
  D3D12_ROOT_PARAMETER params[2]{};for(UINT i=0;i<2;++i){params[i].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;params[i].DescriptorTable={1,&ranges[i]};}
  D3D12_ROOT_SIGNATURE_DESC desc{2,params,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE};ComPtr<ID3DBlob> blob,error;
  hr(D3D12SerializeRootSignature(&desc,D3D_ROOT_SIGNATURE_VERSION_1,&blob,&error));hr(h.device->CreateRootSignature(0,blob->GetBufferPointer(),blob->GetBufferSize(),IID_PPV_ARGS(&root)));
  rootSigParameterCount[root.Get()]=2;NativeFixtureRootCreated(root.Get(),blob->GetBufferPointer(),blob->GetBufferSize());
  const char code[]=R"(
Texture2D<float4> T0:register(t0);
Texture2D<float4> T1:register(t1);
Texture2D<float4> T2:register(t2);
Texture2D<float4> T4:register(t4);
Texture2D<float4> T5:register(t5);
Texture2D<float4> T9:register(t9);
Texture2D<float4> T12:register(t12);
RWTexture2D<float4> U0:register(u0),U1:register(u1);
[numthreads(8,8,1)]void main(uint2 p:SV_DispatchThreadID){float3 value=T0[p].rgb+T1[p].rgb+T2[p].rgb+T4[p].rgb+T5[p].rgb+T9[p].rgb+T12[p].rgb;U0[p]=float4(value,U0[p].w+1);U1[p]=float4(value,U1[p].w+1);})";
  ComPtr<ID3DBlob> shader;hr(D3DCompile(code,sizeof(code),nullptr,nullptr,nullptr,"main","cs_5_1",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&shader,&error));
  D3D12_COMPUTE_PIPELINE_STATE_DESC pd{};pd.pRootSignature=root.Get();pd.CS={shader->GetBufferPointer(),shader->GetBufferSize()};hr(h.device->CreateComputePipelineState(&pd,IID_PPV_ARGS(&pipeline)));NativeFixturePipelineCreated(pipeline.Get(),pd);
  FrameSurvey::PipelineShaderIdentity identity;need(FrameSurvey::ResolvePipelineShaderIdentity(pipeline.Get(),identity)&&identity.complete&&identity.presentStages==FrameSurvey::PipelineCS&&identity.compute[0],"opaque profile retains actual native shader identity, never a substituted title hash");
  need(NrdBridge::RegisterInterveningPipelineForTesting(pipeline.Get(),1),"explicit fixture profile selection retains real shader/stamp validation");
  for(UINT i=0;i<13;++i){D3D12_SHADER_RESOURCE_VIEW_DESC view{};view.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;view.Texture2D.MipLevels=1;auto* resource=title.noisyB[0].Get();const auto dst=Cpu(96+i);h.device->CreateShaderResourceView(resource,&view,dst);FrameSurvey::View(resource,dst,&view);}
  for(UINT i=0;i<2;++i){D3D12_UNORDERED_ACCESS_VIEW_DESC view{};view.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;view.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;const auto dst=Cpu(109+i);auto* resource=title.tex[9+i].Get();h.device->CreateUnorderedAccessView(resource,nullptr,&view,dst);FrameSurvey::View(resource,dst,&view);const auto cpu=CpuReadable(109+i);h.device->CreateUnorderedAccessView(resource,nullptr,&view,cpu);FrameSurvey::View(resource,cpu,&view);}
  const D3D12_INDIRECT_ARGUMENT_DESC argument{D3D12_INDIRECT_ARGUMENT_TYPE_DISPATCH};const D3D12_COMMAND_SIGNATURE_DESC sd{12,1,&argument,0};
  // Actual native creation trampoline, then caller-strong coverage and production
  // publication: the fixture does not pretend to install physical Release hooks.
  hr(FrameSurvey::oSignature(h.device.Get(),&sd,nullptr,IID_PPV_ARGS(&signature)));NativeFixtureRegister(signature.Get());FrameSurvey::CommandSignatureCreated(signature.Get(),sd,nullptr);
  FrameSurvey::IndirectSignatureInfo proof;need(FrameSurvey::ResolveIndirectSignature(signature.Get(),proof)&&proof.kind==FrameSurvey::IndirectSignatureKind::Dispatch&&proof.byteStride==12&&proof.birth,"actual native pure-dispatch signature metadata is live and exact");
  arguments=h.upload(0);void* mapped=nullptr;hr(arguments->Map(0,nullptr,&mapped));const UINT groups[3]={16,16,1};std::memcpy(mapped,groups,sizeof(groups));arguments->Unmap(0,nullptr);
 }
 D3D12_CPU_DESCRIPTOR_HANDLE Cpu(UINT index)const{return {title.visible->GetCPUDescriptorHandleForHeapStart().ptr+UINT64(index)*title.increment};}
 D3D12_CPU_DESCRIPTOR_HANDLE CpuReadable(UINT index)const{return {title.staging->GetCPUDescriptorHandleForHeapStart().ptr+UINT64(index)*title.increment};}
 D3D12_GPU_DESCRIPTOR_HANDLE Gpu(UINT index)const{return {title.visible->GetGPUDescriptorHandleForHeapStart().ptr+UINT64(index)*title.increment};}
 void Record(){const auto stage=NrdBridge::gService->lists.at(h.list.Get()).native[1];need(stage&&!stage->committed&&!stage->invalidated,"B is independently mandatory across the real opaque work");const auto before=stage->ownership->nativeProof->textures.size();
  h.list->SetComputeRootSignature(root.Get());h.list->SetPipelineState(pipeline.Get());h.list->SetComputeRootDescriptorTable(0,Gpu(96));h.list->SetComputeRootDescriptorTable(1,Gpu(109));const float zero[4]{};
  for(UINT i=0;i<2;++i){h.list->ClearUnorderedAccessViewFloat(Gpu(109+i),CpuReadable(109+i),title.tex[9+i].Get(),zero,0,nullptr);h.uav(title.tex[9+i].Get());}
  h.list->ExecuteIndirect(signature.Get(),1,arguments.Get(),0,nullptr,0);for(UINT i=0;i<2;++i)h.uav(title.tex[9+i].Get());
  need(!stage->invalidated&&!stage->recording->skipInvalidated&&stage->ownership->nativeProof->textures.size()==before+9&&stage->ownership->nativeProof->signatureCount==1,"actual indirect hook preserves B only after nine exact used-slot and native signature witnesses");
 }
 void MutateToB(){NrdBridgeDescriptorAdmission::Mutation mutation(true);need(mutation.Acquired(),"native plus metadata mutation is inside the actual descriptor writer gate");D3D12_UNORDERED_ACCESS_VIEW_DESC view{};view.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;view.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;h.device->CreateUnorderedAccessView(title.tex[11].Get(),nullptr,&view,Cpu(109));FrameSurvey::View(title.tex[11].Get(),Cpu(109),&view);}
 void Check(const Readback& read){const auto values=read.signal();for(size_t p=3;p<values.size();p+=4)need(values[p]==PackedVector::XMConvertFloatToHalf(1.f),"the real native indirect shader executed exactly once at every pixel");}
};
void RootChecks(Host& h,NativeTitle& title,const ComPtr<ID3D12Resource>& read){void* p=nullptr;hr(read->Map(0,nullptr,&p));const auto* words=static_cast<const UINT*>(p);
 for(UINT role=1;role<=10;++role){need(words[role*16+11]==UINT(role==1||role==10),"all native denoising originals have zero GPU executions; PrepLast and A composition execute once");}
 const UINT expected[8]={11,22,33,40,55,66,128,128};for(UINT role:{1u,10u,14u}){need(std::equal(expected,expected+8,words+role*16),"actual GPU sparse root constants/CBV/SRV/UAV/extent restored exactly");need(words[role*16+11]==1,"each surviving title shader executes exactly once");}read->Unmap(0,nullptr);}
J Positive(Host& h,NativeTitle& title,OpaqueWork* opaque=nullptr){J rows=J::array();std::array<std::shared_ptr<NrdBridge::HistoryDomain>,2> histories;std::array<ffxContext,2> contexts{};UINT firstCreates=FfxApiProxy::creates;
 for(UINT frame=1;frame<=6;++frame){const UINT before=FfxApiProxy::dispatches;title.Begin(frame);title.A();title.B();need(FfxApiProxy::dispatches==before,"raw/geometry/motion capture runs before either late Consumer without provider or title writes");
  title.ConsumerA();if(opaque)opaque->Record();title.ConsumerB();const auto& state=NrdBridge::gService->lists.at(h.list.Get());auto a=state.native[0],b=state.native[1];need(a&&b&&a->committed&&b->committed&&a->recording!=b->recording,"independent A/B transactions each commit their own exact retained token");need(FfxApiProxy::dispatches==before+2&&NrdBridge::GetStatus().active,"two real signed provider calls produce active RR-only A and B outputs");
  const auto as=a->history->rr.GetOwnedOutputSnapshot(a->owned),bs=b->history->rr.GetOwnedOutputSnapshot(b->owned);
  const std::array<Readback,2> outA{title.readback(7),title.readback(8)},outB{title.readback(11),title.readback(12)};
  const std::array<Readback,2> rrA{title.readback(as.selectedSpec,D3D12_RESOURCE_STATE_UNORDERED_ACCESS),title.readback(as.selectedDiff,D3D12_RESOURCE_STATE_UNORDERED_ACCESS)},rrB{title.readback(bs.selectedSpec,D3D12_RESOURCE_STATE_UNORDERED_ACCESS),title.readback(bs.selectedDiff,D3D12_RESOURCE_STATE_UNORDERED_ACCESS)};
  std::optional<Readback> opaqueRead;if(opaque)opaqueRead.emplace(title.readback(title.tex[9].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS));
  auto root=h.buffer(1024,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);h.barrier(title.checksum.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);h.list->CopyBufferRegion(root.Get(),0,title.checksum.Get(),0,1024);h.barrier(title.checksum.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  need(Execute(h),"complete A/B required transactions are allowed by actual descriptor/ledger submission");RootChecks(h,title,root);need(!FrameSurvey::BindingWindow(),"steady RR-only native frames keep the global binding mirror window closed");if(opaque)opaque->Check(*opaqueRead);
  UINT64 exact=0;for(UINT chain=0;chain<2;++chain)for(UINT lobe=0;lobe<2;++lobe){const auto out=(chain?outB:outA)[lobe].signal(),rr=(chain?rrB:rrA)[lobe].signal();for(size_t p=0;p<out.size();p+=4){for(UINT c=0;c<3;++c){need(std::isfinite(PackedVector::XMConvertHalfToFloat(rr[p+c])),"actual signed RR stage RGB finite");need(out[p+c]==rr[p+c],"title RGB exclusively equals this chain's actual staged RR");++exact;}need(out[p+3]==PackedVector::XMConvertFloatToHalf(lobe?11.f:9.f),"every original opaque title alpha bit survives pure RR commit");}}
  for(UINT c=0;c<2;++c){const auto stage=c?b:a;const auto provider=FfxApiProxy::records[before+c];if(frame==1){histories[c]=stage->history;contexts[c]=provider.context;}need(histories[c]==stage->history&&contexts[c]==provider.context,"continuous A/B histories and physical providers are independent and stable");need(bool(provider.flags&FFX_DENOISER_DISPATCH_RESET)==(frame==1),"only first frame resets each native A/B provider history");}
  rows.push_back({{"SL_frame",frame},{"signed_dispatches",2},{"exact_rr_rgb_words",exact},{"native_filter_gpu_executions",0},{"opaque_original_gpu_executions",opaque?1:0},{"A_context",uint64_t(uintptr_t(contexts[0]))},{"B_context",uint64_t(uintptr_t(contexts[1]))}});h.reset();
 }
 need(FfxApiProxy::creates==firstCreates+2,"six submitted A/B frames create exactly two physical SDK contexts");
 const auto dispatchBefore=FfxApiProxy::dispatches;
 // Discard an unsubmitted partial recording BEFORE testing the intentionally
 // process-sticky real Execute denial. This recovery never clears a latch.
 title.Begin(7);title.A();title.B();title.ConsumerB();
 const auto incomplete=NrdBridge::gService->lists.at(h.list.Get()).native;
 need(incomplete[0]&&!incomplete[0]->committed&&incomplete[1]&&incomplete[1]->committed,"B's successful late RR commit cannot complete A's independent missing-Consumer token");
 need(FfxApiProxy::dispatches==dispatchBefore+1,"unsubmitted canceled chain recorded only B's actual signed SDK call");
 hr(h.list->Close());NrdBridge::OnRecordingClosed(h.list.Get(),S_OK);h.reset();
 title.Begin(8);title.A();title.B();title.ConsumerA();title.ConsumerB();
 need(Execute(h),"fresh complete native A/B transactions recover after Reset discarded the incomplete recording without submission");
 need(FfxApiProxy::dispatches==dispatchBefore+3,"recovery records exactly one new actual signed call for each chain");
 for(UINT chain=0;chain<2;++chain){const auto& record=FfxApiProxy::records[dispatchBefore+1+chain];need(record.context!=contexts[chain]&&(record.flags&FFX_DENOISER_DISPATCH_RESET),"unsubmitted discarded predecessor gets physically fresh RESET history, never stale native fallback");}h.reset();
 return rows;
}
J DeliberateDeny(Host& h,NativeTitle& title,OpaqueWork* opaque){
 // Policy (claude/16-nrd-perf): an incomplete RR commit or a stale commit proof never
 // denies the title's own Execute. The batch is forwarded, no sticky latch is set and
 // the affected chain's RR history restarts with a physically fresh RESET context.
 title.Begin(1);title.A();title.B();if(opaque){title.ConsumerA();opaque->Record();}title.ConsumerB();
 const auto stages=NrdBridge::gService->lists.at(h.list.Get()).native;
 need(stages[0]&&stages[1]&&stages[1]->committed&&bool(stages[0]->committed)==bool(opaque),"independent A/B transaction completeness matches the exact isolated negative");
 if(opaque)opaque->MutateToB();
 const auto firstDispatches=FfxApiProxy::dispatches;
 need(firstDispatches==(opaque?2u:1u),"the isolated negative records exactly the expected signed providers before submission");
 const auto tickBefore=h.tick;
 need(Execute(h)&&h.denied==0,opaque?"pre-submit descriptor mutation forwards the title's own Execute; the stale proof only resets history":"a missing A Consumer forwards the title's own Execute without an A commit");
 need(h.tick==tickBefore+1,"the forwarded batch executes and publishes exactly one title fence");
 {auto& registry=RecordedComputeLease::GetRegistry();std::scoped_lock lock(registry.mutex);need(!registry.completionFailed,"a forwarded incomplete recording never latches uncertain completion");}
 need(SUCCEEDED(RecordedComputeLease::RequiredSubmissionFailure()),"forwarding never sets the process-sticky required-submission latch");
 h.reset();
 title.Begin(2);title.A();title.B();title.ConsumerA();title.ConsumerB();
 const auto recoveryBefore=FfxApiProxy::dispatches;
 need(Execute(h)&&h.denied==0,"the next complete A/B frame submits normally after a forwarded incomplete frame");
 need(FfxApiProxy::dispatches==recoveryBefore,"submission itself records no provider work");
 need(FfxApiProxy::dispatches==firstDispatches+2,"recovery records exactly one actual signed call for each chain");
 const UINT affected=opaque?1u:0u;
 const auto& record=FfxApiProxy::records[firstDispatches+affected];
 need((record.flags&FFX_DENOISER_DISPATCH_RESET)!=0,"the chain without a trustworthy commit restarts its RR history with RESET");
 h.reset();
 return {{"negative",opaque?"opaque_descriptor_mutation":"missing_A_Consumer"},{"forwarded_submissions",1},{"quarantined_recordings",0},{"quarantined_submissions",0},{"intentionally_retained_contexts",0},{"recovery_reset_chain",affected}};
}
J ConfigWiring(Host& h,NativeTitle& title){
 // SOL F01/F02 native witness: Config setter inputs -> production startup
 // storage -> per-chain RR Configure -> the actual CommitNativeTransaction
 // Decode profile and native frame parameters, on real signed provider bytes.
 need(Config::Instance()->FfxDenoiserNrdBridgeSurfaceValidFill.value_or_default()&&
      Config::Instance()->FfxDenoiserNrdBridgeLegacyMotionDepth.value_or_default(),
  "case bootstrap requested both selectors through the Config setter path");
 need(NrdBridge::gService->rrSettings.surfaceValidFill&&NrdBridge::gService->rrSettings.legacyMotionDepth,
  "production ReadStartupSettings stored both requested selectors in the installed service");
 need(NrdBridge::GetRRSettingsState().requested.surfaceValidFill&&NrdBridge::GetRRSettingsState().requested.legacyMotionDepth,
  "coordinator settings state publishes both startup requests");
 std::string error;
 auto apply=[&](bool fill,bool legacy){auto settings=NrdBridge::GetRRSettingsState().requested;
  settings.surfaceValidFill=fill;settings.legacyMotionDepth=legacy;
  need(NrdBridge::ApplyRRSettings(settings,false,error)&&error.empty(),"selector request applies through the production request path");};
 // Depth content: flat 5 in warm frames, 5/55 step in capture frames. With the
 // static fixture camera the legacy rollback must sample the warm frame's flat
 // previous-visible depth while the camera-only default predicts the current
 // step surface, so the motion depth delta separates the two provably.
 auto uploadDepth=[&](float nearValue,float farValue){
  const auto desc=title.tex[3]->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT64 size=0;
  h.device->GetCopyableFootprints(&desc,0,1,0,&fp,nullptr,nullptr,&size);
  std::vector<uint16_t> words(size_t(size)/2,0);auto* floats=reinterpret_cast<float*>(words.data());
  for(UINT y=0;y<desc.Height;++y){auto* row=floats+size_t(y)*(fp.Footprint.RowPitch/4);
   for(UINT x=0;x<desc.Width;++x)row[x]=x<desc.Width/2?nearValue:farValue;}
  const auto state=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
  auto buffer=h.buffer(size,D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);void* mapped=nullptr;hr(buffer->Map(0,nullptr,&mapped));
  std::memcpy(mapped,words.data(),size_t(size));buffer->Unmap(0,nullptr);
  h.barrier(title.tex[3].Get(),state,D3D12_RESOURCE_STATE_COPY_DEST);
  D3D12_TEXTURE_COPY_LOCATION a{},b{};a.pResource=buffer.Get();a.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;a.PlacedFootprint=fp;
  b.pResource=title.tex[3].Get();b.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;h.list->CopyTextureRegion(&b,0,0,0,&a,nullptr);
  h.barrier(title.tex[3].Get(),D3D12_RESOURCE_STATE_COPY_DEST,state);h.uploads.push_back(buffer);
 };
 // Checkerboard modes 0/1 so the raw decode reconstructs half of each lobe
 // from left/right neighbour taps (SetWords defaults both lobes to traced 2).
 auto remapModes=[&]{void* p=nullptr;hr(title.cb->Map(0,nullptr,&p));auto* w=static_cast<UINT*>(p);w[144]=1;w[145]=1;title.cb->Unmap(0,nullptr);};
 // Legacy epochs: fill stays OFF, both chains decode plain, B motion carries
 // the epoch's legacy selector.
 auto legacyFrame=[&](UINT frame,bool legacy,bool warm){
  apply(false,legacy);
  uploadDepth(5.f,warm?5.f:55.f);
  const UINT before=FfxApiProxy::dispatches;
  title.Begin(frame);remapModes();title.A();title.B();
  need(FfxApiProxy::dispatches==before,"raw/geometry/motion capture runs before either late Consumer without provider work");
  title.ConsumerA();title.ConsumerB();
  const auto& state=NrdBridge::gService->lists.at(h.list.Get());
  auto a=state.native[0],b=state.native[1];
  need(a&&b&&a->committed&&b->committed,"independent A/B transactions each commit their own exact retained token");
  const auto requested=b->history->rr.GetSettingsState().requested;
  need(!requested.surfaceValidFill&&requested.legacyMotionDepth==legacy,"per-chain RR Configure stored the requested legacy selector without fill");
  auto bRecord=FfxApiProxy::records[before+1];
  Readback spec=title.readback(static_cast<ID3D12Resource*>(bRecord.spec),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  Readback motion=title.readback(static_cast<ID3D12Resource*>(bRecord.motion),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  const bool reset=bool(bRecord.flags&FFX_DENOISER_DISPATCH_RESET);
  need(Execute(h),"complete A/B required transactions are allowed by actual descriptor/ledger submission");h.reset();
  return std::make_tuple(reset,std::move(spec),std::move(motion));
 };
 const auto [reset1,spec1,motion1]=legacyFrame(1,false,true);
 need(reset1,"first configured frame starts each chain with an actual provider reset");
 const auto [reset2,spec2,motion2]=legacyFrame(2,false,false);
 need(!reset2,"capture frame continues the epoch without a new reset");
 const auto [reset3,spec3,motion3]=legacyFrame(3,true,true);
 need(reset3,"the legacy request resets the provider history before the next capture");
 const auto [reset4,spec4,motion4]=legacyFrame(4,true,false);
 need(!reset4,"legacy capture frame continues without another reset");
 const auto [reset5,spec5,motion5]=legacyFrame(5,false,true);
 need(reset5,"clearing the legacy request resets the provider history again");
 const auto [reset6,spec6,motion6]=legacyFrame(6,false,false);
 need(!reset6,"return capture frame continues without another reset");
 need(wiringSignalDiff(spec6,spec2)["differing_words"]==0,"returning to the default legacy setting reproduces byte-identical decoded inputs");
 need(wiringMotionDiff(motion6,motion2)["depth_delta_words"]==0&&wiringMotionDiff(motion6,motion2)["xyw_words"]==0,
  "returning to the default legacy setting reproduces byte-identical motion guides");
 const auto legacyMotion=wiringMotionDiff(motion4,motion2);
 const std::string motionCounts="legacy z words="+std::to_string(legacyMotion["depth_delta_words"].get<uint64_t>())+
  " xyw words="+std::to_string(legacyMotion["xyw_words"].get<uint64_t>());
 need(legacyMotion["depth_delta_words"]>0,motionCounts.c_str());
 need(legacyMotion["xyw_words"]==0,"the legacy selector changes only the motion depth delta component");
 need(wiringSignalDiff(spec4,spec2)["differing_words"]==0,"the legacy selector alone changes no decoded RR input byte");
 // Fill dance frames: A (ReconDirect chain) always decodes plain; the PrePass
 // chain decodes GATED only while the Config-originated request is stored.
 // Decode output depends on raw+geometry only, so the gated/plain comparison
 // is exact across the two frames.
 // Fill witness: the PrePass-chain decode would accept the gated profile, but
 // the Direct (ReconDirect) chain must refuse it fail-closed. Before the F01
 // repair the selector never reached this production Decode, so the frame
 // silently decoded plain; now the stored request changes real behaviour and
 // the recorded failure names the gated profile requirement.
 apply(true,false);
 uploadDepth(5.f,55.f);
 const UINT before=FfxApiProxy::dispatches;
 title.Begin(7);remapModes();title.A();title.B();
 need(FfxApiProxy::dispatches==before,"capture runs before either late Consumer without provider work");
 title.ConsumerA();
 const auto& state=NrdBridge::gService->lists.at(h.list.Get());
 auto a=state.native[0];
 need(a&&!a->committed,(std::string("witness aNull=")+(a?"0":"1")+" reason="+NrdBridge::GetStatus().reason).c_str());
 need(NrdBridge::GetStatus().reason.find("Surface-valid fill")!=std::string::npos,
  "the Direct-chain refusal names the gated surface-valid fill requirement from the stored selector");
 need(a->history->rr.GetSettingsState().requested.surfaceValidFill,
  "the failing chain's own RR wrapper reports the Config-originated fill request stored");
 need(FfxApiProxy::dispatches==before,"the refused Direct chain records no signed provider dispatch");
 title.ConsumerB();
 need(Execute(h)&&h.denied==0,"the frame with a failed mandatory chain transaction forwards the title's own Execute");
 h.reset();
 need(FfxApiProxy::dispatches==before,"no signed provider work is recorded for the refused chain");
 need(SUCCEEDED(RecordedComputeLease::RequiredSubmissionFailure()),"the refused chain never sets the process-sticky submission latch");
 need(!NrdBridge::GetStatus().active,"the refused mandatory transaction reports the bridge inactive with its reason");
 apply(false,false);
 const auto finalState=NrdBridge::GetRRSettingsState().requested;
 need(!finalState.surfaceValidFill&&!finalState.legacyMotionDepth,"the controlled case ends with both selectors off");
 return {{"startup_selectors_stored",true},{"motion_legacy_diff",legacyMotion},
  {"gated_request_reaches_production_decode",true},{"direct_chain_fail_closed",true},
  {"restart_required_latch",false},{"forwarded_refused_frame",true},
  {"decode_source","actual production CommitNativeTransaction raw decode"},
  {"scope","native RR-only flow: production startup/request/Configure wiring, gated decode fail-closed selection and legacy motion Z on real signed provider inputs; gated vs plain decode bytes are the W2 helper fixture's proven scope; no game quality claim"}};
}
J TemporalWiring(Host& h,NativeTitle& title){
 // Actual Config/startup and service request -> both independently retained native chains.
 need(NrdBridge::GetRRSettingsState().requested.motionStability.enabled&&
      NrdBridge::GetRRSettingsState().requested.lightingValidation,
      "temporal startup selectors reach the actual installed service");
 J rows=J::array();std::string error;std::array<ffxContext,2> contexts{};
 std::array<NrdBridge::RRRecordedOutputSnapshot,2> retained;
 std::array<float,2> retainedValue{};
 const UINT firstCreates=FfxApiProxy::creates;
 float position=0;
 for(UINT frame=1;frame<=10;++frame){
  auto settings=NrdBridge::GetRRSettingsState().requested;
  settings.motionStability.enabled=frame<=8;settings.lightingValidation=frame<=8&&frame!=7;
  need(NrdBridge::ApplyRRSettings(settings,false,error)&&error.empty(),"live temporal request uses production service API");
  if(frame==4)position=.02f;
  title.SetWords();title.begin(frame);StreamlineHooks::snapshot.constants.cameraPos.x=position;title.pass(Role::PrepLast);
  const auto before=FfxApiProxy::dispatches;title.A();title.B();title.ConsumerA();title.ConsumerB();
  const auto stages=NrdBridge::gService->lists.at(h.list.Get()).native;
  need(stages[0]&&stages[1]&&stages[0]->committed&&stages[1]->committed&&FfxApiProxy::dispatches==before+2,
       "both native consumers commit only their own actual signed RR result with temporal options");
  std::array<NrdBridge::RRRecordedOutputSnapshot,2> snapshots;
  J lobes=J::array();std::array<std::array<Readback,2>,2> rr,output;
  for(UINT chain=0;chain<2;++chain){
   const auto& stage=stages[chain];const auto provider=FfxApiProxy::records[before+chain];
   if(frame==1)contexts[chain]=provider.context;
   need(provider.context==contexts[chain],"temporal toggles preserve the physical provider context");
   const bool reset=bool(provider.flags&FFX_DENOISER_DISPATCH_RESET);
   need(reset==(frame==1||frame==9),"runtime stability and G3 toggles never reset; returning to fixed scalar resets once");
   const auto state=stage->history->rr.GetSettingsState();snapshots[chain]=stage->history->rr.GetOwnedOutputSnapshot(stage->owned);
   const auto& snap=snapshots[chain];
   need(state.requested.motionStability.enabled==settings.motionStability.enabled&&
        state.requested.lightingValidation==settings.lightingValidation,"per-chain Configure stores the live requested temporal profile");
   need(snap.providerMotion==provider.motion,"snapshot owns the actual RR motion resource");
   const bool guard=settings.lightingValidation&&frame!=4;
   need(state.lightingValidationActive==guard&&state.lightingValidationLastError.empty(),"G3 is active while still, skips translation, and reports no fallback");
   need((provider.motion!=stage->inputs.motion)==guard,"only an active G3 substitutes RR's motion copy");
   if(settings.motionStability.enabled){
    const float expected=frame==1||frame==4?.5f:frame<4?.5f+.035f*(frame-1):.5f+.035f*(frame-4);
    need(std::abs(state.effective[1]-expected)<1e-5f,"both actual native chains follow the ramp and translation drop");
    need(snap.runtimeTuningValid&&snap.runtimeEffective==state.effective,"recording freezes its own per-frame effective key values");
   }else need(!snap.runtimeTuningValid,"OFF capture retains the existing fixed-profile metadata path");
   if(frame==6){retained[chain]=snap;retainedValue[chain]=snap.runtimeEffective[1];}
   if(frame>=7){need(retained[chain].providerMotion&&retained[chain].owner&&retained[chain].runtimeEffective[1]==retainedValue[chain],
       "a retained prior recording keeps its exact G3 motion and immutable runtime values across both option toggles");}
   rr[chain]={title.readback(snap.selectedSpec,D3D12_RESOURCE_STATE_UNORDERED_ACCESS),title.readback(snap.selectedDiff,D3D12_RESOURCE_STATE_UNORDERED_ACCESS)};
   output[chain]={title.readback(chain?11:7),title.readback(chain?12:8)};
   lobes.push_back({{"chain",chain},{"stability",state.effective[1]},{"guard",guard},{"reset",reset},
                    {"auxiliary_bytes",stage->history->rr.OwnedAuxiliaryBytes()}});
  }
  auto root=h.buffer(1024,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
  h.barrier(title.checksum.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
  h.list->CopyBufferRegion(root.Get(),0,title.checksum.Get(),0,1024);
  h.barrier(title.checksum.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  need(Execute(h),"temporal native transactions pass the actual required submission ledger");RootChecks(h,title,root);
  UINT64 exact=0;for(UINT chain=0;chain<2;++chain)for(UINT lobe=0;lobe<2;++lobe){
   const auto a=output[chain][lobe].signal(),b=rr[chain][lobe].signal();
   for(size_t p=0;p<a.size();p+=4){for(UINT c=0;c<3;++c){need(a[p+c]==b[p+c],"temporal control never routes noisy input around actual signed RR");++exact;}
    need(a[p+3]==PackedVector::XMConvertFloatToHalf(lobe?11.f:9.f),"temporal control preserves the title's alpha bits");}
  }
  rows.push_back({{"frame",frame},{"chains",lobes},{"exact_rr_rgb_words",exact}});h.reset();
 }
 retained={};need(FfxApiProxy::creates==firstCreates+2,"temporal integration uses exactly the original two physical native contexts");
 return {{"frames",rows},{"scope","actual native Config/startup/service/Configure/A+B/consumer/submission with signed RR; synthetic title lighting, no game IQ verdict"}};
}
J NativeDebugPresentation(Host& h,NativeTitle& title){
 // Regression: RR-only native transactions never retained their AMD debug image, so the
 // provider-native DebugView silently stayed off in game. The request goes through the
 // production path; an upscaler-style presentation must then find and record chain A's image.
 std::string error;auto settings=NrdBridge::GetRRSettingsState().requested;
 settings.nativeDebugView=FFX_API_DENOISER_DEBUG_VIEW_MODE_OVERVIEW;settings.nativeDebugViewport=0;
 need(NrdBridge::ApplyRRSettings(settings,false,error)&&error.empty(),"the native debug request applies through the production request path");
 need(NrdBridge::NativeDebugEnabled(),"the request opens the upscaler-side presentation gate");
 auto desc=title.tex[0]->GetDesc();desc.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
 D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;ComPtr<ID3D12Resource> target;
 hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&target)));
 NativeFixtureResourceCreated(target.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
 J frames=J::array();UINT presented=0;
 for(UINT frame=1;frame<=3;++frame){
  Upload(h,target.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,std::vector<uint16_t>(size_t(desc.Width)*desc.Height*4,0));
  title.Begin(frame);title.A();title.B();title.ConsumerA();title.ConsumerB();
  const auto& state=NrdBridge::gService->lists.at(h.list.Get());
  const auto a=state.native[0];
  need(a&&a->committed&&state.native[1]&&state.native[1]->committed,"both RR-only chains commit with the debug-capable contexts");
  need(a->history->rr.GetSettingsState().requested.nativeDebugView==FFX_API_DENOISER_DEBUG_VIEW_MODE_OVERVIEW,"chain A's own RR wrapper stores the debug request");
  bool retained=false;for(const auto& source:NrdBridge::gService->nativeDebugSources)retained|=source&&source->history==a->history;
  need(retained,"the committed RR-only chain A transaction retains its AMD debug image");
  std::string presentError;
  const bool shown=NrdBridge::PresentNativeDebug(h.list.Get(),target.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,presentError);
  need(presentError.empty(),("presentation reported an error: "+presentError).c_str());
  presented+=shown?1:0;
  const char* quiet=NrdBridge::gNativeDebugQuiet.load();
  need(shown,("frame "+std::to_string(frame)+" presentation skipped: "+(quiet?quiet:"(no reason recorded)")).c_str());
  Readback read=title.readback(target.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  need(Execute(h),"the frame with the debug presentation is allowed by actual descriptor/ledger submission");h.reset();
  size_t written=0;const auto values=read.signal();for(size_t p=0;p<values.size();p+=4)written+=(values[p]|values[p+1]|values[p+2])!=0;
  need(!shown||written>0,"a recorded presentation writes AMD's debug image into the target");
  frames.push_back({{"frame",frame},{"presented",shown},{"written_pixels",written}});
 }
 need(presented==3,"every frame presents chain A's AMD debug image");
 settings.nativeDebugView=-1;need(NrdBridge::ApplyRRSettings(settings,false,error)&&error.empty(),"the debug request clears");
 need(!NrdBridge::NativeDebugEnabled(),"clearing the request closes the presentation gate");
 return {{"frames",frames},{"presented",presented},
  {"scope","native RR-only flow: production debug request -> per-chain debug context -> CommitNativeTransaction retains chain A's image -> PresentNativeDebug records it on real signed provider output; no game proof"}};
}
} // namespace NativeFixture
int main(int argc,char** argv)try{
 need(argc==3||argc==4,"scratch output, actual signed AMD DLL and optional isolated case");const std::string mode=argc==4?argv[3]:"";const bool missing=mode=="--missing-consumer",mutation=mode=="--opaque-mutation",useOpaque=mode=="--opaque"||mutation,configWiring=mode=="--config-wiring",nativeDebug=mode=="--native-debug",temporal=mode=="--temporal";need(mode.empty()||missing||useOpaque||configWiring||nativeDebug||temporal,"only bounded declared native cases are accepted");NativeFixture::Bootstrap();Host h;NativeFixtureRegister(h.device.Get());NativeFixtureRegister(h.list.Get());
 g_dllPath=std::filesystem::path(argv[1])/"fixture.dll";Config::Instance()->FfxDenoiserNrdBridge.value=true;
 if(configWiring) {
  // Config setter path: the production Initialize below must consume these
  // exactly like INI startup values through ReadStartupSettings.
  Config::Instance()->FfxDenoiserNrdBridgeSurfaceValidFill.value=true;
  Config::Instance()->FfxDenoiserNrdBridgeLegacyMotionDepth.value=true;
 }
 if(temporal){Config::Instance()->FfxDenoiserNrdBridgeMotionAdaptiveStability.value=true;Config::Instance()->FfxDenoiserNrdBridgeLightingValidation.value=true;}
 NrdBridge::ConfigureStartup(true);loadProvider(argv[2]);FrameSurvey::BeginCreationTracking(false);need(FrameSurvey::Install(h.device.Get(),h.list.Get(),false),"actual native metadata registry installed");need(NrdBridge::Initialize(h.device.Get()),"actual production coordinator initialized");AttachRoots(h.list.Get());Wiring::Attach(h.list.Get());NativeDraw::Attach(h.list.Get());NrdBridge::SetNativeElisionContractForTesting(true);
 struct HookLifetime{bool active=true;void Stop()noexcept{if(!active)return;active=false;try{NativeDraw::Detach();Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();}catch(...){std::cerr<<"native hook cleanup failed after original assertion"<<std::endl;}}~HookLifetime(){Stop();}} hookLifetime;
 struct EmitLifetime{~EmitLifetime(){emitDebug={};}} emitLifetime;
 J result;{NativeFixture::NativeTitle title(h,false);
  std::optional<NativeFixture::OpaqueWork> opaque;if(useOpaque)opaque.emplace(h,title);
  struct Cleanup{Host& host;~Cleanup(){try{host.waitComplete();NrdBridge::Shutdown();const auto recording=RecordedComputeLease::Capture(host.list.Get());RecordedComputeLease::Detach(recording);RecordedComputeLease::Poll();}catch(...){std::cerr<<"native cleanup failed after original assertion"<<std::endl;}}}cleanup{h};
  try{if(temporal)result["temporal"]=NativeFixture::TemporalWiring(h,title);else if(configWiring)result["config_wiring"]=NativeFixture::ConfigWiring(h,title);else if(nativeDebug)result["native_debug"]=NativeFixture::NativeDebugPresentation(h,title);else if(missing||mutation)result=NativeFixture::DeliberateDeny(h,title,opaque?&*opaque:nullptr);else result["frames"]=NativeFixture::Positive(h,title,opaque?&*opaque:nullptr);}catch(...){const auto status=NrdBridge::GetStatus();std::cerr<<"native pre-unwind sdk="<<FfxApiProxy::dispatches<<" creates="<<FfxApiProxy::creates<<" destroys="<<FfxApiProxy::destroys<<" frames="<<status.framesBridged<<" phase="<<status.phase<<" reason="<<status.reason<<" required="<<std::hex<<RecordedComputeLease::RequiredSubmissionFailure()<<std::dec<<std::endl;if(emitDebug)emitDebug();throw;}
 }
 if(configWiring)need(FfxApiProxy::creates==FfxApiProxy::destroys&&FfxApiProxy::creates>=1,"a forwarded refused frame retires every physical provider context after fenced recording detach");
 else if(nativeDebug||temporal)need(FfxApiProxy::creates==FfxApiProxy::destroys&&FfxApiProxy::creates==2,"the debug-capable A/B provider contexts retire after fenced recording detach");
 else if(missing||mutation)need(FfxApiProxy::creates==FfxApiProxy::destroys&&FfxApiProxy::creates>=2,"forwarded negatives retire every provider context after fenced recording detach");
 else need(FfxApiProxy::creates==FfxApiProxy::destroys&&FfxApiProxy::creates==4,"all four actual native A/B provider contexts retire after fenced recording detach");hookLifetime.Stop();const auto debug=h.debugCounts();result["native_checks"]=checks;result["debug_errors"]=debug[0];result["debug_warnings"]=debug[1];result["provider_dispatches"]=FfxApiProxy::dispatches;result["contexts"]=FfxApiProxy::creates;result["provider_destroys"]=FfxApiProxy::destroys;result["missing_A_Consumer_denials"]=0;result["repeated_denials"]=h.denied;result["discard_recovery"]=!missing&&!mutation;result["required_latch"]=FAILED(RecordedComputeLease::RequiredSubmissionFailure())?1:0;result["opaque_case"]=useOpaque;result["mode"]=mode;
 result["scope"]="actual hardware/coordinator/raw/geometry/motion/signedRR/303compute+36pixel/requiredledger; synthetic shipping role/readiness and caller-strong native Release-coverage adapters, not full title startup/physical Release detour proof";
 std::ofstream(std::filesystem::path(argv[1])/(temporal?"temporal-result.json":configWiring?"config-wiring-result.json":nativeDebug?"native-debug-result.json":"native-transactions-result.json"))<<result.dump(2)<<'\n';std::cout<<"PASS native_transactions "<<checks<<'\n';return 0;
}catch(const std::exception& e){std::cerr<<"FAIL native_transactions: "<<e.what()<<std::endl;return 1;}
