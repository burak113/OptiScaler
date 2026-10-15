// Included after the unchanged Title/quality helpers. This is a synthetic title
// writer adapter; capture, provenance, conversion, RR and restoration are real.
const char materialTitleShader[]=R"(
cbuffer Sparse:register(b0){uint C0,C1,C2,P3,P4,C5,P6,P7;};
cbuffer TitleBufferWords:register(b6){uint4 Words[96];};
cbuffer Extent:register(b8){uint Width,Height;};
Texture2D<float4> S0:register(t0); Texture2D<float4> Params:register(t9);
RWTexture2D<float4> Normal:register(u4);
StructuredBuffer<uint> RootSRV:register(t0,space1);
RWStructuredBuffer<uint> Check:register(u0,space1); SamplerState Samp:register(s0);
// t7 is deliberately NOT read by the original title writer. The optional
// bridge must not read it while its state is pixel-only or unknown.
[numthreads(8,8,1)]void main(uint3 p:SV_DispatchThreadID){if(any(p.xy>=uint2(Width,Height)))return;
 if(all(p.xy==0)){Check[0]=C0;Check[1]=C1;Check[2]=C2;Check[3]=C5;Check[4]=Words[0].x;
 Check[5]=RootSRV[0];Check[6]=Width;Check[7]=Height;Check[8]=(uint)round(S0.Load(int3(0,0,0)).x*65536);
 Check[9]=(uint)round(Params.Load(int3(0,0,0)).r*65535);Check[10]=(uint)round(Normal[uint2(0,0)].b*1023);
 InterlockedAdd(Check[11],1);Check[12]=(uint)round(S0.SampleLevel(Samp,float2(.5/Width,.5/Height),0).x*65536);}}
)";

struct NativeMaterialTitle {
 Title& title; Host& h; ComPtr<ID3D12Resource> base,params,originalNormal,check;
 ComPtr<ID3D12RootSignature> root; ComPtr<ID3D12PipelineState> pso;
 ComPtr<ID3D12DescriptorHeap> heap;
 std::vector<uint32_t> baseWords,normalWords;std::vector<uint8_t> parameterBytes;
 UINT lastParam=0,dispatchCount=0;
 ~NativeMaterialTitle(){titleTextures.erase(base.Get());titleTextures.erase(params.Get());titleTextures.erase(originalNormal.Get());}
 ComPtr<ID3D12Resource> texture(DXGI_FORMAT format,bool uav){
  D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;d.Width=title.width;d.Height=title.height;
  d.DepthOrArraySize=d.MipLevels=d.SampleDesc.Count=1;d.Format=format;d.Flags=uav?D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS:D3D12_RESOURCE_FLAG_NONE;
  D3D12_HEAP_PROPERTIES hp{};hp.Type=D3D12_HEAP_TYPE_DEFAULT;ComPtr<ID3D12Resource> r;
  hr(h.device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&r)));
  titleTextures.insert(r.Get());FrameSurvey::ResourceCreated(r.Get(),D3D12_RESOURCE_STATE_COPY_DEST);return r;
 }
 void upload(ID3D12Resource* r,const void* values){
  const auto d=r->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT64 bytes=0;h.device->GetCopyableFootprints(&d,0,1,0,&fp,nullptr,nullptr,&bytes);
  auto source=h.buffer(bytes,D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);void* mapped=nullptr;hr(source->Map(0,nullptr,&mapped));
  for(UINT y=0;y<title.height;++y)std::memcpy(static_cast<uint8_t*>(mapped)+size_t(y)*fp.Footprint.RowPitch,static_cast<const uint8_t*>(values)+size_t(y)*title.width*4,size_t(title.width)*4);
  source->Unmap(0,nullptr);D3D12_TEXTURE_COPY_LOCATION src{},dst{};src.pResource=source.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=fp;
  dst.pResource=r;dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;h.list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);h.barrier(r,D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);h.uploads.push_back(source);
 }
 void srv(UINT slot,ID3D12Resource* r){D3D12_SHADER_RESOURCE_VIEW_DESC d{};d.Format=r->GetDesc().Format;d.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;d.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;d.Texture2D.MipLevels=1;
  D3D12_CPU_DESCRIPTOR_HANDLE at{heap->GetCPUDescriptorHandleForHeapStart().ptr+UINT64(slot)*title.increment};h.device->CreateShaderResourceView(r,&d,at);FrameSurvey::View(r,at,&d);}
 NativeMaterialTitle(Title& t):title(t),h(t.h){
  base=texture(DXGI_FORMAT_R10G10B10A2_UNORM,false);params=texture(DXGI_FORMAT_R8G8B8A8_UNORM,false);
  originalNormal=title.tex[2];title.tex[2]=texture(DXGI_FORMAT_R10G10B10A2_UNORM,true);title.views();
  const size_t pixels=size_t(title.width)*title.height;baseWords.resize(pixels);normalWords.resize(pixels);parameterBytes.resize(pixels*4);
  constexpr UINT colors[4][3]={{128,512,896},{896,256,384},{384,896,128},{640,384,768}};
  for(UINT y=0;y<title.height;++y)for(UINT x=0;x<title.width;++x){const auto i=size_t(y)*title.width+x;const auto c=(x*4/title.width);const auto* rgb=colors[c];
   baseWords[i]=rgb[0]|(rgb[1]<<10)|(rgb[2]<<20);normalWords[i]=512u|(512u<<10)|((y<title.height/2?512u:800u)<<20)|(c<<30);
   parameterBytes[i*4]=x<title.width/2?0:153;parameterBytes[i*4+1]=77;parameterBytes[i*4+2]=191;parameterBytes[i*4+3]=255;}
  upload(base.Get(),baseWords.data());upload(params.Get(),parameterBytes.data());upload(title.tex[2].Get(),normalWords.data());
  check=h.buffer(256,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,true);
  D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;hd.NumDescriptors=24;hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
  hr(h.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&heap)));FrameSurvey::HeapCreated(h.device.Get(),heap.Get());
  for(UINT i=0;i<8;++i)srv(i,i==7?base.Get():title.tex[0].Get());srv(8,title.tex[0].Get());srv(9,params.Get());srv(10,title.tex[0].Get());srv(11,base.Get());
  for(UINT i=0;i<5;++i){D3D12_UNORDERED_ACCESS_VIEW_DESC d{};auto* r=i==4?title.tex[2].Get():title.tex[9].Get();d.Format=r->GetDesc().Format;d.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
   D3D12_CPU_DESCRIPTOR_HANDLE at{heap->GetCPUDescriptorHandleForHeapStart().ptr+UINT64(16+i)*title.increment};h.device->CreateUnorderedAccessView(r,nullptr,&d,at);FrameSurvey::View(r,at,&d);}
  D3D12_DESCRIPTOR_RANGE ranges[]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,8,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,2,8,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,5,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_SAMPLER,1,0,0,0}};
  D3D12_ROOT_PARAMETER p[9]{};p[0].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;p[0].Constants={0,0,8};
  p[1].ParameterType=p[2].ParameterType=p[5].ParameterType=p[7].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
  p[1].DescriptorTable={1,&ranges[0]};p[2].DescriptorTable={1,&ranges[1]};p[5].DescriptorTable={1,&ranges[2]};p[7].DescriptorTable={1,&ranges[3]};
  p[3].ParameterType=D3D12_ROOT_PARAMETER_TYPE_SRV;p[3].Descriptor={0,1};p[4].ParameterType=D3D12_ROOT_PARAMETER_TYPE_UAV;p[4].Descriptor={0,1};
  p[6].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;p[6].Constants={8,0,2};p[8].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV;p[8].Descriptor={6,0};
  D3D12_ROOT_SIGNATURE_DESC rd{9,p,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE};ComPtr<ID3DBlob> blob,error,cs;hr(D3D12SerializeRootSignature(&rd,D3D_ROOT_SIGNATURE_VERSION_1,&blob,&error));
  hr(h.device->CreateRootSignature(0,blob->GetBufferPointer(),blob->GetBufferSize(),IID_PPV_ARGS(&root)));rootSigParameterCount[root.Get()]=9;FrameSurvey::RootCreated(root.Get(),blob->GetBufferPointer(),blob->GetBufferSize());
  const auto code=D3DCompile(materialTitleShader,sizeof(materialTitleShader),nullptr,nullptr,nullptr,"main","cs_5_1",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&cs,&error);
  if(FAILED(code)&&error)std::cerr<<static_cast<const char*>(error->GetBufferPointer())<<'\n';hr(code);D3D12_COMPUTE_PIPELINE_STATE_DESC pd{};pd.pRootSignature=root.Get();pd.CS={cs->GetBufferPointer(),cs->GetBufferSize()};
  hr(h.device->CreateComputePipelineState(&pd,IID_PPV_ARGS(&pso)));FrameSurvey::PipelineCreated(pso.Get(),pd);NrdBridge::RegisterPipelineRoleForTesting(pso.Get(),NrdBridge::Role::MaterialGuide);
 }
 void start(){auto zero=h.upload(0,256);h.barrier(check.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_DEST);h.list->CopyBufferRegion(check.Get(),0,zero.Get(),0,256);h.barrier(check.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);h.uploads.push_back(zero);dispatchCount=0;}
 void dispatch(bool known,bool pixelOnly=false,bool badProfile=false){
  if(known)for(auto* r:{base.Get(),params.Get()}){h.barrier(r,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_SOURCE);h.barrier(r,D3D12_RESOURCE_STATE_COPY_SOURCE,pixelOnly&&r==base.Get()?D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE:D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);}
  h.barrier(title.tex[2].Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  h.list->SetComputeRootSignature(root.Get());ID3D12DescriptorHeap* heaps[]={heap.Get(),title.sampler.Get()};h.list->SetDescriptorHeaps(2,heaps);
  const UINT first[]={11,22,30},dims[]={title.width,title.height};h.list->SetComputeRoot32BitConstants(0,3,first,0);h.list->SetComputeRoot32BitConstant(0,40,5);h.list->SetComputeRoot32BitConstant(0,33,2);
  const auto gpu=heap->GetGPUDescriptorHandleForHeapStart();h.list->SetComputeRootDescriptorTable(1,gpu);h.list->SetComputeRootDescriptorTable(2,{gpu.ptr+UINT64(badProfile?10:8)*title.increment});
  h.list->SetComputeRootShaderResourceView(3,title.rootSrv->GetGPUVirtualAddress());h.list->SetComputeRootUnorderedAccessView(4,check->GetGPUVirtualAddress());h.list->SetComputeRootDescriptorTable(5,{gpu.ptr+UINT64(16)*title.increment});
  h.list->SetComputeRoot32BitConstants(6,2,dims,0);h.list->SetComputeRootDescriptorTable(7,title.sampler->GetGPUDescriptorHandleForHeapStart());h.list->SetComputeRootConstantBufferView(8,title.cb->GetGPUVirtualAddress());h.list->SetPipelineState(pso.Get());
  h.list->Dispatch((title.width+7)/8,(title.height+7)/8,1);h.uav(check.Get());++dispatchCount;lastParam=badProfile?UINT(std::lround((128.f/1023)*65535)):0;
  h.barrier(title.tex[2].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  if(pixelOnly)h.barrier(base.Get(),D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
 }
 ComPtr<ID3D12Resource> captureCheck(){auto read=h.buffer(256,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);h.barrier(check.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);h.list->CopyBufferRegion(read.Get(),0,check.Get(),0,256);h.barrier(check.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);return read;}
 void validateCheck(ID3D12Resource* read){void* mapped=nullptr;hr(read->Map(0,nullptr,&mapped));const auto* p=static_cast<const UINT*>(mapped);const UINT expected[]={11,22,33,40,55,66,title.width,title.height,2048,lastParam,512,dispatchCount,2048};
  need(std::equal(std::begin(expected),std::end(expected),p),"original material writer GPU reads exact sparse roots/b6/two SRV tables/u4/both heaps/PSO after capture restoration");read->Unmap(0,nullptr);}
};

std::vector<uint8_t> materialBytes(const Readback& read,UINT bytesPerPixel){void* data=nullptr;hr(read.resource->Map(0,nullptr,&data));std::vector<uint8_t> bytes(size_t(read.width)*read.height*bytesPerPixel);
 for(UINT y=0;y<read.height;++y)std::memcpy(bytes.data()+size_t(y)*read.width*bytesPerPixel,static_cast<uint8_t*>(data)+size_t(y)*read.footprint.Footprint.RowPitch,size_t(read.width)*bytesPerPixel);read.resource->Unmap(0,nullptr);return bytes;}
void materialSave(const std::filesystem::path& path,const std::vector<uint8_t>& bytes){std::ofstream f(path,std::ios::binary);f.write(reinterpret_cast<const char*>(bytes.data()),std::streamsize(bytes.size()));f.flush();need(bool(f),"material E2E exports exact GPU provenance bytes");}

void nativeMaterialGuideCase(Host& h,Title& title,J& result,const std::filesystem::path& output,bool enabled){
 NativeMaterialTitle writer(title);NrdBridge::RRSettings settings;settings.nativeMaterialGuides=enabled;std::string error;need(NrdBridge::ApplyRRSettings(settings,false,error),"optional native material configuration applies before discovery");
 const auto initialCreates=FfxApiProxy::creates,initialDispatch=FfxApiProxy::dispatches;writer.start();writer.dispatch(false);need(!NrdBridge::gService->lists.at(h.list.Get()).pendingMaterial.snapshot,"cold writer with unknown source states records no optional capture");
 title.frame(1);const auto discoveryWriter=writer.captureCheck();need(title.sentinel(title.finish()),"material discovery frame runs untouched original NRD");writer.validateCheck(discoveryWriter.Get());
 need(NrdBridge::gService->cache.Valid()&&FfxApiProxy::dispatches==initialDispatch,"material adapter discovers the full original NRD chain before RR");
 std::shared_ptr<NrdBridge::HistoryDomain> history;void* providerContext=nullptr;bool previousApplied=false;uint64_t warmBytes=0;J frames=J::array();
 for(UINT frame=2;frame<=8;++frame){const bool known=frame!=2,pixelOnly=frame==5,badFinal=frame==7;const bool applied=enabled&&known&&!pixelOnly&&!badFinal;
  const auto before=FfxApiProxy::dispatches,beforeRestores=restores;const auto failures=NrdBridge::gService->failures;writer.start();const auto internalBefore=detourDispatches[uint64_t(h.list.Get())][1];
  writer.dispatch(known,pixelOnly);auto& stage=NrdBridge::gService->lists.at(h.list.Get());const bool firstCapture=enabled&&known&&!pixelOnly;
  need(bool(stage.pendingMaterial.snapshot)==firstCapture,"optional GPU material capture requires current readable state evidence in this recording");
  need(detourDispatches[uint64_t(h.list.Get())][1]==internalBefore+unsigned(firstCapture)&&restores==beforeRestores+unsigned(firstCapture),"unknown/pixel-only/OFF writer records zero hidden read/restore and supported writer records exactly one capture");
  if(firstCapture){need(stage.pendingMaterial.normal==title.tex[2].Get()&&stage.pendingMaterial.normalGeneration!=0,"material snapshot is stamped with the exact native normal resource generation");warmBytes=NrdBridge::gService->nativeMaterialCapture.OwnedAuxiliaryBytes();need(warmBytes>0,"optional material capture owns a measured private snapshot");}
  if(badFinal){writer.dispatch(false,false,true);need(!NrdBridge::gService->lists.at(h.list.Get()).pendingMaterial.snapshot,"recognized unsupported later writer tombstones an earlier successful material snapshot");}
  title.frame(frame);const auto& state=NrdBridge::gService->lists.at(h.list.Get());
  need(FfxApiProxy::dispatches==before+1&&NrdBridge::GetStatus().active,"supported original NRD chain reaches actual signed RR despite optional white fallback");
  need(NrdBridge::GetStatus().nativeMaterialGuidesActive==applied&&state.parameters.nativeMaterialGuides==enabled,"visible status reports actual same-frame material admission rather than the requested toggle");
  need(NrdBridge::gService->failures==failures&&NrdBridge::GetStatus().reason.empty(),"optional unknown/bad material profile neither spends failure budget nor makes the bridge inactive");
  need(restores==beforeRestores+3+unsigned(firstCapture),"each material-enabled injection and all existing Recon/motion/RR injections restore title roots exactly");
  const auto record=FfxApiProxy::records.back();const bool reset=(record.flags&FFX_DENOISER_DISPATCH_RESET)!=0;const bool expectedReset=frame==2||(enabled&&applied!=previousApplied);
  need(reset==expectedReset,"white/true material transitions reset once while a stable cue path preserves RR history");
  if(frame==2){history=state.history;providerContext=record.context;}else need(history==state.history&&providerContext==record.context,"optional cue fallback preserves the same actual signed context and causal history domain");
  std::optional<Readback> snapshot;if(applied){need(state.material.normalGeneration==state.chain.Bindings()[2].resourceGeneration,"Recon accepts only the exact captured normal metadata generation");snapshot=title.readback(NrdBridge::NativeMaterialCapture::Resource(state.material.snapshot),D3D12_RESOURCE_STATE_COMMON);}
  const std::array<Readback,2> guides{title.readback(state.inputs.specAlbedo,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),title.readback(state.inputs.diffAlbedo,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE)};
  const std::array<Readback,2> converted{title.readback(state.inputs.spec,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),title.readback(state.inputs.diff,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE)};
  const auto nativeBase=title.readback(writer.base.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),nativeParams=title.readback(writer.params.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),nativeNormal=title.readback(title.tex[2].Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  const auto writerCheck=writer.captureCheck();const auto capture=title.capture();h.submit();const auto rgb=title.validate(capture);title.rrChecks(rgb);writer.validateCheck(writerCheck.Get());
  need(converted[0].signal()==title.raw[0]&&converted[1].signal()==title.raw[1],"material cue integration never divides, recolors or bypasses noisy Recon RGB/hit-distance alpha");
  const auto base=materialBytes(nativeBase,4),params=materialBytes(nativeParams,4),normal=materialBytes(nativeNormal,4);
  need(std::memcmp(base.data(),writer.baseWords.data(),base.size())==0&&params==writer.parameterBytes&&std::memcmp(normal.data(),writer.normalWords.data(),normal.size())==0,"all borrowed material and native normal source bytes remain unchanged after capture/conversion/RR");
  const auto prefix=std::string("frame")+std::to_string(frame);materialSave(output/(prefix+"-spec-guide.bin"),materialBytes(guides[0],4));materialSave(output/(prefix+"-diff-guide.bin"),materialBytes(guides[1],4));
  materialSave(output/(prefix+"-base.bin"),base);materialSave(output/(prefix+"-params.bin"),params);materialSave(output/(prefix+"-normal.bin"),normal);if(snapshot)materialSave(output/(prefix+"-snapshot.bin"),materialBytes(*snapshot,8));
  need(enabled||NrdBridge::gService->nativeMaterialCapture.OwnedAuxiliaryBytes()==0,"default OFF allocates no native material capture context or snapshot");
  frames.push_back({{"frame",frame},{"material_applied",applied},{"reset",reset},{"unknown_states",!known},{"pixel_only",pixelOnly},{"later_bad_profile",badFinal},{"snapshot",bool(snapshot)},{"active",true}});previousApplied=applied;h.reset();
 }
 if(enabled){writer.start();writer.dispatch(true);title.recon(9);need(NrdBridge::gService->lists.at(h.list.Get()).converted&&NrdBridge::GetStatus().nativeMaterialGuidesActive,"cancellation case has coherently converted real material cues");
  const auto before=FfxApiProxy::dispatches;settings.nativeMaterialGuides=false;need(NrdBridge::ApplyRRSettings(settings,false,error),"material toggle cancels the current recording coherently");title.tail();const auto canceledWriter=writer.captureCheck();need(title.sentinel(title.finish()),"canceled material frame leaves original title NRD sentinel and alpha untouched");need(FfxApiProxy::dispatches==before&&!NrdBridge::GetStatus().nativeMaterialGuidesActive,"canceled recording never reaches signed RR or republishes material Active");writer.validateCheck(canceledWriter.Get());
  writer.start();writer.dispatch(true);title.frame(10);need(!NrdBridge::GetStatus().nativeMaterialGuidesActive&&(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET),"OFF recovery uses white and a coherent RESET");title.rrChecks(title.finish());
  settings.nativeMaterialGuides=true;need(NrdBridge::ApplyRRSettings(settings,false,error),"material capture re-enables coherently");writer.start();writer.dispatch(true);title.frame(11);need(NrdBridge::GetStatus().nativeMaterialGuidesActive&&(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET),"ON recovery recaptures current material and resets the changed cue history");title.rrChecks(title.finish());
 }
 need(titleTransitions==0,"bridge never transitions borrowed title material or normal resources");need(FfxApiProxy::creates==initialCreates+1,"material toggles/fallbacks never recreate the actual physical signed provider context");
 result["native_material_guides"]={{"enabled",enabled},{"frames",frames},{"same_history_context",true},{"default_off_no_capture_allocation",!enabled},{"warm_snapshot_bytes",warmBytes},{"state_unknown_white",true},{"pixel_only_no_read",true},{"later_writer_tombstone",true},{"coherent_cancel_recovery",enabled},{"noisy_rgb_alpha_unchanged",true},{"borrowed_source_bytes_exact",true},{"borrowed_title_transitions",titleTransitions},{"native_title_writer_hash_is_adapter",true}};
}
