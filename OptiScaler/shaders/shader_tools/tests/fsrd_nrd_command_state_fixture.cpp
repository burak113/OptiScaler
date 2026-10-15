// Appended to the activated Birth/root fixture. Native derived setters are
// explicit recording adapters; no fake object is used as a real D3D device/list.
void commandStateCases()
{
 FakeObject listObject,computeRootObject,graphicsRootObject,heapObject,computePsoObject,graphicsPsoObject;
 watched=listObject.as<ID3D12GraphicsCommandList>();
 root=computeRootObject.as<ID3D12RootSignature>();heap=heapObject.as<ID3D12DescriptorHeap>();
 pipeline=computePsoObject.as<ID3D12PipelineState>();
 auto* graphicsRoot=graphicsRootObject.as<ID3D12RootSignature>();
 auto* graphicsPso=graphicsPsoObject.as<ID3D12PipelineState>();
 gNrdBridgeDeviceWrappers=true;isNrdBridgeInjection=false;FrameSurvey::internalScope=false;blocked=Block::None;
 Config::Instance()->RestoreComputeSignature.current=true;
 Config::Instance()->RestoreGraphicSignature.current=false;
 Config::Instance()->ExtendedStateRestore.current=true;
 PublishCreatedRootParameters(root,__uuidof(ID3D12RootSignature),7);
 PublishCreatedRootParameters(graphicsRoot,__uuidof(ID3D12RootSignature),7);
 auto bind=[&]{
  hkSetComputeRootSignature(watched,root);hkSetDescriptorHeaps(watched,1,&heap);hkSetPipelineState(watched,pipeline);
  hkSetComputeRootDescriptorTable(watched,1,{101});hkSetComputeRootDescriptorTableLate(watched,5,{505});
  const uint32_t head[]={11,99,33,66},tail[]={77,88};
  hkSetComputeRoot32BitConstants(watched,2,4,head,0);hkSetComputeRoot32BitConstantsLate(watched,2,2,tail,5);
  hkSetComputeRootConstantBufferView(watched,3,0x8000);hkSetComputeRootShaderResourceView(watched,4,0x9000);
  hkSetComputeRootUnorderedAccessView(watched,6,0xa000);
  hkSetGraphicsRootSignature(watched,graphicsRoot);hkSetGraphicsRootSignatureLate(watched,graphicsRoot);
  hkSetGraphicsRootDescriptorTable(watched,1,{901});hkSetGraphicsRootDescriptorTableLate(watched,5,{905});
  const uint32_t gh[]={111,199,133,166},gt[]={177,188};
  hkSetGraphicsRoot32BitConstants(watched,2,4,gh,0);hkSetGraphicsRoot32BitConstantsLate(watched,2,2,gt,5);
  hkSetGraphicsRootConstantBufferView(watched,3,0x18000);hkSetGraphicsRootShaderResourceView(watched,4,0x19000);
  hkSetGraphicsRootUnorderedAccessView(watched,6,0x1a000);hkSetPipelineState(watched,graphicsPso);
 };
 bind();
 need(bridgeGraphicsStates.at(watched).root==graphicsRoot&&signatures.at(watched).ptr==graphicsRoot,
      "bridge captures early and late graphics root even when ordinary graphics restore setting is false");
 need(!D3D12Hooks::BridgePredicationDisabled(watched)&&!D3D12Hooks::CanRestoreRootSignature(watched)&&
      !D3D12Hooks::CanRestoreGraphicsRootSignature(watched),"unobserved predicate never admits compute or graphics injection");
 D3D12Hooks::OnBridgeSetPredication(watched,true);
 need(!D3D12Hooks::BridgePredicationDisabled(watched)&&!D3D12Hooks::CanRestoreRootSignature(watched)&&
      !D3D12Hooks::CanRestoreGraphicsRootSignature(watched),"active predicate rejects both injection families");
 D3D12Hooks::OnBridgeSetPredication(watched,false);
 {
  NrdBridgeLifetime::ScopedBorrow borrow;need(borrow.Acquired(),"physical borrow acquired for actual Born metadata readers");
  need(D3D12Hooks::BridgePredicationDisabled(watched)&&D3D12Hooks::CanRestoreRootSignature(watched)&&
       D3D12Hooks::CanRestoreGraphicsRootSignature(watched),"observed null predicate admits both exact root families");
  const auto reads=listObject.reads+computeRootObject.reads+graphicsRootObject.reads+heapObject.reads+graphicsPsoObject.reads;
  const auto installers=coverageCalls,factories=factoryCalls;
  FrameSurvey::ComputeBindings graphics;ID3D12PipelineState* current=nullptr;
  need(D3D12Hooks::GetGraphicsBindingsForBridge(watched,graphics,current)&&current==graphicsPso&&graphics.root==graphicsRoot,
       "graphics getter snapshots current graphics PSO and root independently of compute");
  need(graphics.receiverBirth==NrdBridgeBirth::Capture(watched)&&graphics.rootBirth==NrdBridgeBirth::Capture(graphicsRoot)&&
       graphics.pipelineBirth==NrdBridgeBirth::Capture(graphicsPso)&&graphics.heapBirths==std::vector<NrdBridgeBirth::Token>{NrdBridgeBirth::Capture(heap)},
       "graphics snapshot carries exact receiver root PSO and ordered heap births");
  need(graphics.tables.size()==2&&graphics.tables[0].first==1&&graphics.tables[0].second.ptr==901&&graphics.tables[1].first==5&&
       graphics.tables[1].second.ptr==905&&graphics.views.size()==3&&graphics.views[0].address==0x18000&&graphics.views[1].address==0x19000&&
       graphics.views[2].address==0x1a000,"graphics tables and root CBV SRV UAV retain their actual family values");
  need(reads==listObject.reads+computeRootObject.reads+graphicsRootObject.reads+heapObject.reads+graphicsPsoObject.reads&&
       installers==coverageCalls&&factories==factoryCalls,"graphics getter and preflight perform no native identity installer or payload work");
  Config::Instance()->RestoreComputeSignature.current=false;Config::Instance()->ExtendedStateRestore.current=false;
  need(!D3D12Hooks::CanRestoreGraphicsRootSignature(watched),"new graphics preflight enforces required configuration flags");
  isNrdBridgeInjection=true;calls.clear();need(D3D12Hooks::RestoreGraphicsRootForBridge(watched),"admitted graphics restore survives flag reload inside injection");
  isNrdBridgeInjection=false;Config::Instance()->RestoreComputeSignature.current=true;Config::Instance()->ExtendedStateRestore.current=true;
  need(calls.size()==18&&calls[0].name=="heaps"&&calls[1].name=="compute.signature"&&calls[1].words[0]==uintptr_t(root)&&
       calls[9].name=="graphics.signature"&&calls[9].words[0]==uintptr_t(graphicsRoot)&&calls.back().name=="pso"&&
       calls.back().words[0]==uintptr_t(graphicsPso),"dual-family restore replays heaps compute graphics and current graphics PSO last");
  need(calls[3].words==std::vector<uint64_t>{11,99,33,66}&&calls[4].offset==5&&calls[4].words==std::vector<uint64_t>{77,88}&&
       calls[11].words==std::vector<uint64_t>{111,199,133,166}&&calls[12].offset==5&&calls[12].words==std::vector<uint64_t>{177,188},
       "both independent sparse constant byte ranges and gaps survive dual-family replay");
  need(calls[5].words[0]==0x8000&&calls[6].words[0]==0x9000&&calls[8].words[0]==0xa000&&
       calls[13].words[0]==0x18000&&calls[14].words[0]==0x19000&&calls[16].words[0]==0x1a000,
       "both families retain exact root descriptor addresses in replay");
  auto hooks=s_SetGraphicsRootConstantBufferView;s_SetGraphicsRootConstantBufferView={};
  need(!D3D12Hooks::CanRestoreGraphicsRootSignature(watched),"missing graphics restore method denies before native recording");
  s_SetGraphicsRootConstantBufferView=hooks;
  const auto compute=bridgeComputeRoots.at(watched);bridgeComputeRoots.erase(watched);
  need(!D3D12Hooks::CanRestoreGraphicsRootSignature(watched),"missing secondary compute root is not guessed to be unbound");
  bridgeComputeRoots[watched]=compute;
 }
 // Direct and both possible decorator arrangements preserve the original call.
 calls.clear();hkSetGraphicsRootUnorderedAccessView(watched,6,0x1b000);
 need(calls.size()==1&&bridgeGraphicsStates.at(watched).rows[6].bufferLocation==0x1b000,
      "standalone early graphics UAV setter actually publishes the current address");
 auto early=s_SetGraphicsRootUnorderedAccessView.o_earlyHook,late=s_SetGraphicsRootUnorderedAccessView.o_lateHook;
 s_SetGraphicsRootUnorderedAccessView.o_lateHook=+[](ID3D12GraphicsCommandList* list,UINT p,D3D12_GPU_VIRTUAL_ADDRESS address){
  bridgeGraphicsStates.at(list).rows[p].bufferLocation=0xbeef;hkSetGraphicsRootUnorderedAccessView(list,p,address);};
 calls.clear();hkSetGraphicsRootUnorderedAccessViewLate(watched,6,0x1c000);
 need(calls.size()==1&&!lateInProgressSetGraphicsRootUnorderedAccessView&&bridgeGraphicsStates.at(watched).rows[6].bufferLocation==0xbeef,
      "late to early decorator forwards once and early nested path does not republish metadata");
 s_SetGraphicsRootUnorderedAccessView.o_lateHook=late;
 s_SetGraphicsRootUnorderedAccessView.o_earlyHook=+[](ID3D12GraphicsCommandList* list,UINT p,D3D12_GPU_VIRTUAL_ADDRESS address){hkSetGraphicsRootUnorderedAccessViewLate(list,p,address);};
 calls.clear();hkSetGraphicsRootUnorderedAccessView(watched,6,0x1d000);
 need(calls.size()==1&&!lateInProgressSetGraphicsRootUnorderedAccessView&&bridgeGraphicsStates.at(watched).rows[6].bufferLocation==0x1d000,
      "early to late decorator forwards once with current metadata and restored nested flag");
 s_SetGraphicsRootUnorderedAccessView.o_earlyHook=early;
 FrameSurvey::internalScope=true;
 D3D12Hooks::OnBridgeSetPredication(watched,true);D3D12Hooks::OnBridgeCommandListClearState(watched,nullptr);D3D12Hooks::OnBridgeOpaqueCommand(watched,true);
 FrameSurvey::internalScope=false;
 need(D3D12Hooks::BridgePredicationDisabled(watched)&&bridgeGraphicsStates.at(watched).root==graphicsRoot,
      "internal owned commands cannot overwrite title predicate or binding proof");
 isNrdBridgeInjection=true;D3D12Hooks::OnBridgeSetPredication(watched,true);D3D12Hooks::OnBridgeOpaqueCommand(watched,true);isNrdBridgeInjection=false;
 need(D3D12Hooks::BridgePredicationDisabled(watched)&&bridgeGraphicsStates.at(watched).root==graphicsRoot,
      "thread-local injection bypass preserves title state without global suppression");
 D3D12Hooks::OnBridgeSetPredication(watched,true);D3D12Hooks::OnBridgeCommandListClearState(watched,graphicsPso);
 need(D3D12Hooks::BridgePredicationDisabled(watched)&&!rootStates.contains(watched)&&!bridgeGraphicsStates.contains(watched)&&
      !descriptorHeaps.contains(watched)&&pipelineStates.at(watched).ptr==graphicsPso&&!D3D12Hooks::CanRestoreGraphicsRootSignature(watched),
      "ClearState disables predication seeds supplied PSO and discards both roots and heaps");
 bind();D3D12Hooks::OnBridgeOpaqueCommand(watched,false);
 need(D3D12Hooks::BridgePredicationDisabled(watched)&&!D3D12Hooks::CanRestoreRootSignature(watched)&&!pipelineStates.contains(watched),
      "opaque Indirect preserves disabled predicate but invalidates stale root and PSO proof");
 bind();need(D3D12Hooks::CanRestoreGraphicsRootSignature(watched),"explicit full family rebind can reestablish state after Indirect");
 D3D12Hooks::OnBridgeOpaqueCommand(watched,false);
 need(!rootStates.contains(watched)&&!bridgeGraphicsStates.contains(watched),"after-forward Indirect seal erases state republished by nested forwarding");
 bind();D3D12Hooks::OnBridgeOpaqueCommand(watched,true);
 need(!D3D12Hooks::BridgePredicationDisabled(watched)&&!D3D12Hooks::CanRestoreRootSignature(watched),
      "Bundle inherited predicate remains unknown and parent role cannot retain stale admission");
 bind();need(!D3D12Hooks::CanRestoreGraphicsRootSignature(watched),"root rebind alone cannot guess Bundle predicate state");
 D3D12Hooks::OnBridgeSetPredication(watched,false);
 need(D3D12Hooks::CanRestoreGraphicsRootSignature(watched),"observed null predicate recovers both-family admission after Bundle");
 const auto old=NrdBridgeBirth::Capture(watched);
 {
  NrdBridgeBirth::ScopedRelease pending(old);
  need(!D3D12Hooks::BridgePredicationDisabled(watched),"borrowed predicate read rejects an in-flight physical Release");
 }
 need(D3D12Hooks::BridgePredicationDisabled(watched),"same-birth nonfinal release completion restores metadata admission");
 {
  NrdBridgeBirth::ScopedRelease pending(old);listObject.reuse();D3D12Hooks::OnBridgeSetPredication(watched,false);
  const auto fresh=NrdBridgeBirth::Capture(watched);
  need(fresh&&fresh!=old&&fresh->InstanceStamp()!=old->InstanceStamp()&&bridgePredicates.at(watched).receiverBirth==fresh,
       "recycled native list gets a distinct predicate proof generation");
  D3D12Hooks::OnBridgeObjectReleased(old);
  need(D3D12Hooks::BridgePredicationDisabled(watched)&&bridgePredicates.at(watched).receiverBirth==fresh,
       "delayed old release cannot erase fresh known-disabled state at reused address");
 }
 auto fresh=NrdBridgeBirth::Capture(watched);retire(fresh);
 need(!D3D12Hooks::BridgePredicationDisabled(watched)&&!bridgePredicates.contains(watched),"exact final list release removes only its predicate proof");
 for(auto* object:{&computeRootObject,&graphicsRootObject,&heapObject,&computePsoObject,&graphicsPsoObject})
  if(const auto token=NrdBridgeBirth::Capture(object->as<ID3D12Object>()))retire(token);
 need(nativeUnderBirth==0&&nativeUnderTracker==0&&healthCalls==0&&NrdBridgeBirth::Healthy(),
      "new state and dual-family paths retain zero native getters or callbacks under metadata locks");
 Config::Instance()->RestoreGraphicSignature.current=true;
}
