// Exact production installer bodies below use a Detours recording adapter.
// The table is opaque pointer data; no derived COM method is called on it.
#define LOG_DEBUG(...) ((void)0)
struct InstallerEvent { PVOID* slot; PVOID detour; };
std::vector<InstallerEvent> attachedEvents,detachedEvents;
unsigned beginEvents=0,commitEvents=0,abortEvents=0;
unsigned failAttachAt=0,failDetachAt=0;LONG forcedCommit=NO_ERROR;
LONG DetourTransactionBegin(){++beginEvents;return NO_ERROR;}
LONG DetourUpdateThread(HANDLE){return NO_ERROR;}
LONG DetourTransactionCommit(){++commitEvents;return forcedCommit;}
LONG DetourTransactionAbort(){++abortEvents;return NO_ERROR;}
template<class T>LONG DetourAttach(PVOID* slot,T detour){attachedEvents.push_back({slot,reinterpret_cast<PVOID>(detour)});
 return failAttachAt&&attachedEvents.size()==failAttachAt?ERROR_ACCESS_DENIED:NO_ERROR;}
template<class T>LONG DetourDetach(PVOID* slot,T detour){detachedEvents.push_back({slot,reinterpret_cast<PVOID>(detour)});
 return failDetachAt&&detachedEvents.size()==failDetachAt?ERROR_ACCESS_DENIED:NO_ERROR;}
__INSTALLER_BODIES__

void graphicsInstallerCases()
{
 std::array<PVOID,64> entries{};
 entries[25]=reinterpret_cast<PVOID>(pso);entries[28]=reinterpret_cast<PVOID>(heaps);
 entries[29]=reinterpret_cast<PVOID>(signature);entries[30]=reinterpret_cast<PVOID>(graphicsSignature);
 entries[31]=entries[32]=reinterpret_cast<PVOID>(table);entries[33]=entries[34]=reinterpret_cast<PVOID>(one);
 entries[35]=entries[36]=reinterpret_cast<PVOID>(many);entries[37]=entries[38]=reinterpret_cast<PVOID>(cbv);
 entries[39]=entries[40]=reinterpret_cast<PVOID>(srv);entries[41]=entries[42]=reinterpret_cast<PVOID>(uav);
 struct OpaqueTable{PVOID* data;} object{entries.data()};
 auto* opaque=reinterpret_cast<ID3D12GraphicsCommandList*>(&object);
 auto reset=[&]{
  s_SetPipelineState={};s_SetDescriptorHeaps={};s_SetComputeRootSignature={};s_SetGraphicsRootSignature={};
  s_SetComputeRootDescriptorTable={};s_SetComputeRoot32BitConstant={};s_SetComputeRoot32BitConstants={};
  s_SetComputeRootConstantBufferView={};s_SetComputeRootShaderResourceView={};s_SetComputeRootUnorderedAccessView={};
  ClearBridgeGraphicsArgumentHooks(false);ClearBridgeGraphicsArgumentHooks(true);
  attachedEvents.clear();detachedEvents.clear();beginEvents=commitEvents=abortEvents=failAttachAt=failDetachAt=0;forcedCommit=NO_ERROR;
 };
 auto verify=[&](bool late){
  auto exact=[&](auto& hooks,auto expected){PVOID* slot=reinterpret_cast<PVOID*>(late?&hooks.o_lateHook:&hooks.o_earlyHook);
   unsigned found=0;for(auto event:attachedEvents)found+=event.slot==slot&&event.detour==reinterpret_cast<PVOID>(expected);
   need(found==1,"actual installer attaches each graphics argument slot exactly once to its matching decorator");};
  if(late){exact(s_SetGraphicsRootDescriptorTable,hkSetGraphicsRootDescriptorTableLate);exact(s_SetGraphicsRoot32BitConstant,hkSetGraphicsRoot32BitConstantLate);
   exact(s_SetGraphicsRoot32BitConstants,hkSetGraphicsRoot32BitConstantsLate);exact(s_SetGraphicsRootConstantBufferView,hkSetGraphicsRootConstantBufferViewLate);
   exact(s_SetGraphicsRootShaderResourceView,hkSetGraphicsRootShaderResourceViewLate);exact(s_SetGraphicsRootUnorderedAccessView,hkSetGraphicsRootUnorderedAccessViewLate);}
  else{exact(s_SetGraphicsRootDescriptorTable,hkSetGraphicsRootDescriptorTable);exact(s_SetGraphicsRoot32BitConstant,hkSetGraphicsRoot32BitConstant);
   exact(s_SetGraphicsRoot32BitConstants,hkSetGraphicsRoot32BitConstants);exact(s_SetGraphicsRootConstantBufferView,hkSetGraphicsRootConstantBufferView);
   exact(s_SetGraphicsRootShaderResourceView,hkSetGraphicsRootShaderResourceView);exact(s_SetGraphicsRootUnorderedAccessView,hkSetGraphicsRootUnorderedAccessView);}
 };
 reset();gNrdBridgeDeviceWrappers=false;
 Config::Instance()->RestoreComputeSignature.current=Config::Instance()->RestoreGraphicSignature.current=Config::Instance()->ExtendedStateRestore.current=false;
 D3D12Hooks::HookToCommandListLate(opaque);
 need(attachedEvents.empty()&&!s_SetGraphicsRootDescriptorTable.o_lateHook&&!s_SetGraphicsRootConstantBufferView.o_lateHook,
      "startup OFF retains existing no-graphics-argument-detour behavior");
 reset();gNrdBridgeDeviceWrappers=true;
 // Shared helper is the exact EARLY installer's read/attach operation; the
 // device/allocator creation around it is not emulated or claimed here.
 ReadBridgeGraphicsArgumentHooks(entries.data(),false);
 need(s_SetGraphicsRootDescriptorTable.o_earlyHook==table&&s_SetGraphicsRoot32BitConstant.o_earlyHook==one&&
      s_SetGraphicsRoot32BitConstants.o_earlyHook==many&&s_SetGraphicsRootConstantBufferView.o_earlyHook==cbv&&
      s_SetGraphicsRootShaderResourceView.o_earlyHook==srv&&s_SetGraphicsRootUnorderedAccessView.o_earlyHook==uav,
      "actual early reader maps all six SDK-verified native vtable addresses");
 need(AttachBridgeGraphicsArgumentHooks(false)==NO_ERROR&&attachedEvents.size()==6,"actual early shared helper registers all six hooks");verify(false);
 bridgeGraphicsEarlyAttached=true;UnhookBridgeGraphicsArguments();
 need(detachedEvents.size()==6&&!bridgeGraphicsEarlyAttached&&!s_SetGraphicsRootDescriptorTable.o_earlyHook,
      "early bridge graphics teardown clears only after successful transaction");
 reset();D3D12Hooks::HookToCommandListLate(opaque);
 need(attachedEvents.size()==16&&bridgeGraphicsLateAttached&&BridgeGraphicsRestoreHooksReady()&&commitEvents==1,
      "actual late installer is complete even when all legacy restore settings are false");verify(true);
 attachedEvents.clear();D3D12Hooks::HookToCommandListLate(opaque);need(attachedEvents.empty(),"already installed late path does not attach duplicate hooks");
 failDetachAt=1;UnhookBridgeGraphicsArguments();
 need(abortEvents==1&&bridgeGraphicsLateAttached&&s_SetGraphicsRootConstantBufferView.o_lateHook,
      "failed graphics detach abort preserves published original pointers and attachment state");
 failDetachAt=0;detachedEvents.clear();UnhookBridgeGraphicsArguments();
 need(detachedEvents.size()==6&&!bridgeGraphicsLateAttached&&!BridgeGraphicsRestoreHooksReady(),"successful late detach clears all six readiness inputs");
 reset();failAttachAt=11;D3D12Hooks::HookToCommandListLate(opaque);
 need(abortEvents==1&&commitEvents==0&&!bridgeGraphicsLateAttached&&!s_SetComputeRootSignature.o_lateHook&&
      !s_SetGraphicsRootConstantBufferView.o_lateHook&&!BridgeGraphicsRestoreHooksReady(),"new argument attach failure aborts whole transaction and clears partial readiness");
 reset();forcedCommit=ERROR_ACCESS_DENIED;D3D12Hooks::HookToCommandListLate(opaque);
 need(commitEvents==1&&!bridgeGraphicsLateAttached&&!s_SetGraphicsRootDescriptorTable.o_lateHook&&
      !s_SetGraphicsRootUnorderedAccessView.o_lateHook&&!BridgeGraphicsRestoreHooksReady(),"transaction commit failure cannot publish six raw pointers as a valid graphics path");
 reset();D3D12Hooks::HookToCommandListLate(opaque);
 need(BridgeGraphicsRestoreHooksReady(),"final valid actual installer leaves complete native setter addresses for state tests");
 // Supply explicit original early-forward recording seams as well; the real
 // early shared six-slot reader is still executed rather than manually wired.
 s_SetPipelineState.o_earlyHook=pso;s_SetDescriptorHeaps.o_earlyHook=heaps;
 s_SetComputeRootSignature.o_earlyHook=signature;s_SetGraphicsRootSignature.o_earlyHook=graphicsSignature;
 s_SetComputeRootDescriptorTable.o_earlyHook=table;s_SetComputeRoot32BitConstant.o_earlyHook=one;
 s_SetComputeRoot32BitConstants.o_earlyHook=many;s_SetComputeRootConstantBufferView.o_earlyHook=cbv;
 s_SetComputeRootShaderResourceView.o_earlyHook=srv;s_SetComputeRootUnorderedAccessView.o_earlyHook=uav;
 ReadBridgeGraphicsArgumentHooks(entries.data(),false);
 Config::Instance()->RestoreComputeSignature.current=Config::Instance()->RestoreGraphicSignature.current=Config::Instance()->ExtendedStateRestore.current=true;
}
