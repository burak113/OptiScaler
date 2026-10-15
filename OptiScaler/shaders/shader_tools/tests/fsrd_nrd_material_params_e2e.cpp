// Appended after the untouched production E2E fixture by the NEW driver.
// Material writer PSO/hash are synthetic adapters; actual hooks/coordinator,
// paired CaptureParams, ConversionPass, RRWrapper and signed provider run.
namespace ParamsHost
{
using States=std::array<D3D12_RESOURCE_STATES,2>;
constexpr auto NPS=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
constexpr auto PS=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
constexpr auto UA=D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
struct Seen {ID3D12Resource* resource;D3D12_RESOURCE_BARRIER_TYPE type;D3D12_RESOURCE_STATES before,after;};
static std::array<ID3D12Resource*,2> activeSources{};
static std::array<Seen,8> seen{};
static unsigned seenCount=0,unexpectedTitle=0;
void audit(const D3D12_RESOURCE_BARRIER& value) noexcept
{
 auto* resource=value.Type==D3D12_RESOURCE_BARRIER_TYPE_TRANSITION?value.Transition.pResource:
  value.Type==D3D12_RESOURCE_BARRIER_TYPE_UAV?value.UAV.pResource:nullptr;
 if(!resource||!titleTextures.contains(resource))return;
 if(std::find(activeSources.begin(),activeSources.end(),resource)==activeSources.end())
 {++unexpectedTitle;return;}
 if(seenCount==seen.size()){++unexpectedTitle;return;}
 seen[seenCount++]={resource,value.Type,value.Type==D3D12_RESOURCE_BARRIER_TYPE_TRANSITION?value.Transition.StateBefore:D3D12_RESOURCE_STATE_COMMON,
  value.Type==D3D12_RESOURCE_BARRIER_TYPE_TRANSITION?value.Transition.StateAfter:D3D12_RESOURCE_STATE_COMMON};
}
struct Writer
{
 NativeMaterialTitle native;
 ComPtr<ID3D12PipelineState> previousPso;
 States actual{NPS,NPS};
 explicit Writer(Title& title):native(title)
 {
  // The legacy synthetic constructor has already recorded uploads to its first
  // source pair. Drain them before replacing that pair with UAV-capable sources.
  native.h.submit();native.h.reset();
  auto oldBase=std::move(native.base),oldParams=std::move(native.params);
  for(auto* source:{oldBase.Get(),oldParams.Get()}){titleTextures.erase(source);FrameSurvey::Released(source);}
  native.base=native.texture(DXGI_FORMAT_R10G10B10A2_UNORM,true);
  native.params=native.texture(DXGI_FORMAT_R8G8B8A8_UNORM,true);
  for(size_t pixel=0;pixel<native.parameterBytes.size()/4;++pixel)
   native.parameterBytes[pixel*4+1]=uint8_t((pixel*13+(pixel/title.width)*17)%256);
  native.upload(native.base.Get(),native.baseWords.data());native.upload(native.params.Get(),native.parameterBytes.data());
  native.srv(7,native.base.Get());native.srv(11,native.base.Get());native.srv(9,native.params.Get());
  // Original Dispatch never consumes the t7/t9 guides, so a PSR-only source is
  // legal for it. Keep all root/PSO/heap/UAV/CBV checks in the original shader.
  std::string shader=materialTitleShader;
  const std::string from="Check[9]=(uint)round(Params.Load(int3(0,0,0)).r*65535);";
  const auto at=shader.find(from);need(at!=std::string::npos,"new writer removes only its unused-guide checksum read");shader.replace(at,from.size(),"Check[9]=0;");
  ComPtr<ID3DBlob> cs,error;const auto compiled=D3DCompile(shader.data(),shader.size(),nullptr,nullptr,nullptr,"main","cs_5_1",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&cs,&error);
  if(FAILED(compiled)&&error)std::cerr<<static_cast<const char*>(error->GetBufferPointer())<<std::endl;hr(compiled);
  D3D12_COMPUTE_PIPELINE_STATE_DESC desc{};desc.pRootSignature=native.root.Get();desc.CS={cs->GetBufferPointer(),cs->GetBufferSize()};
  previousPso=native.pso;hr(native.h.device->CreateComputePipelineState(&desc,IID_PPV_ARGS(&native.pso)));
  FrameSurvey::PipelineCreated(native.pso.Get(),desc);NrdBridge::RegisterPipelineRoleForTesting(native.pso.Get(),Role::MaterialGuide);
 }
 void states(const States& next)
 {
  for(unsigned i=0;i<2;++i){auto* source=i?native.params.Get():native.base.Get();
   // Explicit transitions in this exact recording attest the incoming state;
   // none is fabricated by the metadata adapter or inferred from the last list.
   native.h.barrier(source,actual[i],D3D12_RESOURCE_STATE_COPY_SOURCE);
   native.h.barrier(source,D3D12_RESOURCE_STATE_COPY_SOURCE,next[i]);actual[i]=next[i];}
 }
 unsigned dispatch(bool expectedCapture)
 {
  auto& h=native.h;auto& title=native.title;
  h.barrier(title.tex[2].Get(),NPS,UA);
  h.list->SetComputeRootSignature(native.root.Get());ID3D12DescriptorHeap* heaps[]={native.heap.Get(),title.sampler.Get()};h.list->SetDescriptorHeaps(2,heaps);
  const UINT first[]={11,22,30},dimensions[]={title.width,title.height};h.list->SetComputeRoot32BitConstants(0,3,first,0);h.list->SetComputeRoot32BitConstant(0,40,5);h.list->SetComputeRoot32BitConstant(0,33,2);
  const auto base=native.heap->GetGPUDescriptorHandleForHeapStart();h.list->SetComputeRootDescriptorTable(1,base);h.list->SetComputeRootDescriptorTable(2,{base.ptr+UINT64(8)*title.increment});
  h.list->SetComputeRootShaderResourceView(3,title.rootSrv->GetGPUVirtualAddress());h.list->SetComputeRootUnorderedAccessView(4,native.check->GetGPUVirtualAddress());h.list->SetComputeRootDescriptorTable(5,{base.ptr+UINT64(16)*title.increment});
  h.list->SetComputeRoot32BitConstants(6,2,dimensions,0);h.list->SetComputeRootDescriptorTable(7,title.sampler->GetGPUDescriptorHandleForHeapStart());h.list->SetComputeRootConstantBufferView(8,title.cb->GetGPUVirtualAddress());h.list->SetPipelineState(native.pso.Get());
  activeSources={native.base.Get(),native.params.Get()};seenCount=0;
  const auto hidden=detourDispatches[uint64_t(h.list.Get())][1];h.list->Dispatch((title.width+7)/8,(title.height+7)/8,1);
  const auto internal=detourDispatches[uint64_t(h.list.Get())][1]-hidden;activeSources={};
  need(internal==unsigned(expectedCapture),"current known-state admission records exactly one Params capture, and optional fallback records zero hidden dispatches");
  unsigned transitions=0,uavs=0;
  for(unsigned i=0;i<2;++i)
  {
   auto* source=i?native.params.Get():native.base.Get();unsigned forward=0,reverse=0,sourceUav=0;
   for(unsigned j=0;j<seenCount;++j)if(seen[j].resource==source)
   {
    if(seen[j].type==D3D12_RESOURCE_BARRIER_TYPE_UAV){++sourceUav;continue;}
    forward+=seen[j].before==actual[i]&&seen[j].after==NPS;
    reverse+=seen[j].before==NPS&&seen[j].after==actual[i];
   }
   const bool changed=expectedCapture&&!(actual[i]&NPS);
   need(forward==unsigned(changed)&&reverse==unsigned(changed)&&sourceUav==unsigned(changed&&actual[i]==UA),"borrowed source state is exactly restored with a UAV dependency only when required");
   transitions+=forward+reverse;uavs+=sourceUav;
  }
  need(seenCount==transitions+uavs,"every observed borrowed material barrier belongs to the exact admitted state roundtrip");
  need(native.base->AddRef()==2&&native.base->Release()==1&&native.params->AddRef()==2&&native.params->Release()==1,"paired capture retains no borrowed base/Params COM owners");
  h.uav(native.check.Get());++native.dispatchCount;native.lastParam=0;h.barrier(title.tex[2].Get(),UA,NPS);return transitions;
 }
};
J frame(Host& h,Title& title,Writer& writer,UINT index,const States& states,bool enabled,bool applied,bool expectedReset,
 const std::filesystem::path& output,std::shared_ptr<NrdBridge::HistoryDomain>& history,void*& context)
{
 writer.native.start();writer.states(states);const auto failures=NrdBridge::gService->failures;const auto provider=FfxApiProxy::dispatches;
 const auto sourceTransitions=writer.dispatch(applied);auto& before=NrdBridge::gService->lists.at(h.list.Get());
 need(bool(before.pendingMaterial.snapshot)==applied,"optional capture presence matches actual known-state admission, independently of the requested toggle");
 std::weak_ptr<void> snapshot=before.pendingMaterial.snapshot;
 uint64_t pairBytes=0;
 if(applied)
 {
  auto* color=NrdBridge::NativeMaterialCapture::Resource(before.pendingMaterial.snapshot);auto* rough=NrdBridge::NativeMaterialCapture::RoughnessResource(before.pendingMaterial.snapshot);
  need(color&&rough&&color!=rough,"CaptureParams owns a distinct base/metal RGBA16F and raw-G R16F pair");
  for(auto* resource:{color,rough}){const auto desc=resource->GetDesc();pairBytes+=h.device->GetResourceAllocationInfo(0,1,&desc).SizeInBytes;}
  need(color->GetDesc().Format==DXGI_FORMAT_R16G16B16A16_FLOAT&&rough->GetDesc().Format==DXGI_FORMAT_R16_FLOAT,"both captured formats are exact native GPU contracts");
 }
 title.frame(index);const auto& state=NrdBridge::gService->lists.at(h.list.Get());
 need(FfxApiProxy::dispatches==provider+1&&NrdBridge::GetStatus().active,"every complete title chain reaches the actual signed provider, including optional white fallback");
 need(NrdBridge::GetStatus().nativeMaterialGuidesActive==applied&&state.parameters.nativeMaterialGuides==enabled,"material status reports current successful pair admission instead of silently publishing white as active");
 need(NrdBridge::gService->failures==failures,"unsupported COMMON/default-OFF captures spend no bridge failure budget");
 need(bool(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)==expectedReset,"true-material/white cue changes reset once while stable cues preserve signed RR history");
 const auto record=FfxApiProxy::records.back();
 if(!history){history=state.history;context=record.context;}else need(history==state.history&&context==record.context,"all submitted material state/cue variants preserve one physical RR context and causal domain");
 need(FfxApiProxy::lastDispatch.specularAlbedo.resource==state.inputs.specAlbedo&&FfxApiProxy::lastDispatch.diffuseAlbedo.resource==state.inputs.diffAlbedo,"actual signed SDK descriptors consume the exact non-substituted converted albedo resources");
 const std::array<Readback,2> guides{title.readback(state.inputs.specAlbedo,NPS),title.readback(state.inputs.diffAlbedo,NPS)};
 const auto convertedNormal=title.readback(state.inputs.normals,NPS);
 const std::array<Readback,2> signals{title.readback(state.inputs.spec,NPS),title.readback(state.inputs.diff,NPS)};
 std::optional<Readback> material,roughness;
 if(applied){material=title.readback(NrdBridge::NativeMaterialCapture::Resource(state.material.snapshot),D3D12_RESOURCE_STATE_COMMON);roughness=title.readback(NrdBridge::NativeMaterialCapture::RoughnessResource(state.material.snapshot),D3D12_RESOURCE_STATE_COMMON);}
 const auto base=title.readback(writer.native.base.Get(),states[0]),params=title.readback(writer.native.params.Get(),states[1]),normal=title.readback(title.tex[2].Get(),NPS);
 const auto writerCheck=writer.native.captureCheck();const auto captured=title.capture();h.submit();title.rrChecks(title.validate(captured));writer.native.validateCheck(writerCheck.Get());
 need(signals[0].signal()==title.raw[0]&&signals[1].signal()==title.raw[1],"capturing Params.G never changes noisy native RGB or hit-distance alpha");
 const auto baseBytes=materialBytes(base,4),paramBytes=materialBytes(params,4),normalBytes=materialBytes(normal,4),convertedBytes=materialBytes(convertedNormal,4);
 need(std::memcmp(baseBytes.data(),writer.native.baseWords.data(),baseBytes.size())==0&&paramBytes==writer.native.parameterBytes&&std::memcmp(normalBytes.data(),writer.native.normalWords.data(),normalBytes.size())==0,"all borrowed material/normal source bytes remain exact through capture/conversion/actual RR");
 const auto* originalWords=reinterpret_cast<const uint32_t*>(normalBytes.data());const auto* convertedWords=reinterpret_cast<const uint32_t*>(convertedBytes.data());
 size_t normalBExact=0;for(size_t p=0;p<normalBytes.size()/4;++p)normalBExact+=((originalWords[p]>>20)&1023)==((convertedWords[p]>>20)&1023);
 need(normalBExact==normalBytes.size()/4,"new material roughness affects analytic Qs only; every native normal.B word is unchanged");
 const auto prefix="frame"+std::to_string(index);materialSave(output/(prefix+"-spec-guide.bin"),materialBytes(guides[0],4));materialSave(output/(prefix+"-diff-guide.bin"),materialBytes(guides[1],4));
 materialSave(output/(prefix+"-base.bin"),baseBytes);materialSave(output/(prefix+"-params.bin"),paramBytes);materialSave(output/(prefix+"-normal.bin"),normalBytes);materialSave(output/(prefix+"-converted-normal.bin"),convertedBytes);
 if(material){materialSave(output/(prefix+"-snapshot.bin"),materialBytes(*material,8));materialSave(output/(prefix+"-roughness.bin"),materialBytes(*roughness,2));}
 need(!enabled||!applied||!snapshot.expired(),"recording/converted snapshot owner survives actual GPU execution until successful native Reset");
 h.reset();need(snapshot.expired(),"successful native Reset releases the exact old paired-snapshot lease after the fence");
 return {{"frame",index},{"source_states",states},{"applied",applied},{"reset",expectedReset},{"source_transitions",sourceTransitions},{"snapshot_pair_allocation_bytes",pairBytes},{"active",true}};
}
}
void ParamsHostAudit(const D3D12_RESOURCE_BARRIER& barrier) noexcept {ParamsHost::audit(barrier);}

int main(int argc,char** argv)try
{
 need(argc==3||(argc==4&&std::string(argv[3])=="--off"),"new material-Params host takes output, signed DLL and optional fresh OFF mode");
 const bool enabled=argc==3;const std::filesystem::path output=argv[1];std::filesystem::create_directories(output);std::cout.setf(std::ios::unitbuf);
 g_dllPath=output/"fixture.dll";Host h;requestedList=h.list.Get();
 need(!NrdBridgeNativeBirth::Ready()&&!NrdBridgeLifetime::ConcurrentReleasesEnabled(),"new full material host explicitly uses legacy metadata adapters without physical-birth coverage");
 Config::Instance()->FfxDenoiserNrdBridge.value=true;NrdBridge::ConfigureStartup(true);loadProvider(argv[2]);
 FrameSurvey::BeginCreationTracking(false);need(FrameSurvey::Install(h.device.Get(),h.list.Get(),false),"install actual metadata-only FrameSurvey");
 need(NrdBridge::Initialize(h.device.Get()),"initialize actual production coordinator");AttachRoots(h.list.Get());Wiring::Attach(h.list.Get());
 Title title(h,128,128,true);NrdBridge::RRSettings settings;settings.nativeMaterialGuides=enabled;settings.nativeTemporalMotion=false;std::string error;
 need(NrdBridge::ApplyRRSettings(settings,false,error),"apply explicit material-Params ON/OFF setting");ParamsHost::Writer writer(title);
 // The bounded witness learns a source pair only at its first actual writer.
 // Earlier unknown-address barriers cannot retroactively prove its state.
 need(NrdBridge::gService->window,"actual runtime-enabled Initialize opens the initial bounded discovery window before the cold writer");
 writer.native.start();writer.states({ParamsHost::NPS,ParamsHost::NPS});writer.dispatch(false);
 need(!enabled||!NrdBridge::gService->materialIdentities.Empty(),"actual cold writer discovers its live source pair inside the open window without fabricated cache insertion");
 need(!NrdBridge::gService->lists.at(h.list.Get()).pendingMaterial.snapshot,"first-ever material pair discovery is quiet and reads no unproved source state");
 const auto firstWriter=writer.native.captureCheck();
 title.frame(1);need(title.sentinel(title.finish()),"one real original title frame discovers the complete NRD chain before material comparisons");writer.native.validateCheck(firstWriter.Get());
 need(FfxApiProxy::dispatches==0&&NrdBridge::gService->nativeMaterialCapture.OwnedAuxiliaryBytes()==0,"first-writer/discovery phase allocates no capture pair and dispatches no signed RR work");
 const auto initialCreates=FfxApiProxy::creates;std::shared_ptr<NrdBridge::HistoryDomain> history;void* context=nullptr;bool previous=false;J rows=J::array();
 const std::array<ParamsHost::States,7> variants{{{ParamsHost::NPS,ParamsHost::NPS},{ParamsHost::PS,ParamsHost::PS},{D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COMMON},{ParamsHost::UA,ParamsHost::UA},
  {D3D12_RESOURCE_STATES(ParamsHost::PS|ParamsHost::NPS),D3D12_RESOURCE_STATES(ParamsHost::PS|ParamsHost::NPS)},{D3D12_RESOURCE_STATE_COMMON,ParamsHost::PS},{ParamsHost::PS,ParamsHost::NPS}}};
 for(UINT i=0;i<variants.size();++i)
 {
  const bool applied=enabled&&variants[i][0]!=D3D12_RESOURCE_STATE_COMMON&&variants[i][1]!=D3D12_RESOURCE_STATE_COMMON;
  std::cout<<"material Params frame="<<i+2<<" states="<<unsigned(variants[i][0])<<','<<unsigned(variants[i][1])<<" applied="<<applied<<std::endl;
  rows.push_back(ParamsHost::frame(h,title,writer,i+2,variants[i],enabled,applied,i==0||applied!=previous,output,history,context));previous=applied;
  need(FfxApiProxy::creates==initialCreates+1,"all material cue/source-state frames use exactly one actual signed context");
 }
 need(ParamsHost::unexpectedTitle==0,"no title resource outside the exact temporary material sources is ever transitioned internally");
 need(enabled||NrdBridge::gService->nativeMaterialCapture.OwnedAuxiliaryBytes()==0,"explicit OFF creates no paired capture allocation");
 const auto warmBytes=NrdBridge::gService->nativeMaterialCapture.OwnedAuxiliaryBytes();
 unsigned exactSourceTransitions=0;for(const auto& row:rows)exactSourceTransitions+=row.at("source_transitions").get<unsigned>();
 need(titleTransitions==exactSourceTransitions&&titleTransitions==(enabled?10u:0u),"entire host records only the ten admitted material roundtrip transitions, and OFF records zero borrowed transitions");
 history.reset();NrdBridge::Shutdown();RecordedComputeLease::Poll();need(FfxApiProxy::creates==FfxApiProxy::destroys&&FfxApiProxy::contextToType.empty(),"all actual signed contexts retire after their submitted GPU fences");
 Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();const auto debug=h.debugCounts();
 J result{{"enabled",enabled},{"frames",rows},{"native_checks",checks},{"debug_errors",debug[0]},{"debug_warnings",debug[1]},{"provider_dispatches",FfxApiProxy::dispatches},{"provider_contexts",FfxApiProxy::creates},{"warm_pair_bytes",warmBytes},{"unexpected_title_transitions",ParamsHost::unexpectedTitle},
  {"scope","actual coordinator/CaptureParams/6SRV conversion/signed RR/restore; native source/state/roughness admission; NativeBirth READY=false and title hash/SL creation adapters; no game quality/FPS claim"}};
 std::ofstream(output/"material-params-host-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS material_params_host checks="<<checks<<'\n';return 0;
}catch(const std::exception& e){std::cerr<<"material Params host failure: "<<e.what()<<std::endl;return 1;}
