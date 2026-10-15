// Actual class functions are generated above this native fixture. Only owned
// allocation forwards, a passive final-destruction observer, and one race trigger
// are adapters. Native resources, shader execution, and recording leases are real.
#include <json.hpp>
using Capture=NrdBridge::NativeMaterialCapture;
struct Sources {ComPtr<ID3D12Resource> base,params;};
static Sources SourcesFor(Fixture& fixture,UINT width,UINT height){
 std::vector<char> zero(size_t(width)*height*4);
 return {fixture.Texture(width,height,DXGI_FORMAT_R10G10B10A2_UNORM,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&zero),
         fixture.Texture(width,height,DXGI_FORMAT_R8G8B8A8_UNORM,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&zero)};
}
int main(int argc,char**argv)try{
 need(argc==2,"material budget fixture needs scratch output");SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);
 Fixture fixture(true);auto a=SourcesFor(fixture,32,16),b=SourcesFor(fixture,64,16),c=SourcesFor(fixture,96,16);
 fixture.Submit();fixture.Reset();Capture capture;std::string error;
 need(!capture.budget_&&capture.OwnedAuxiliaryBytes()==0,"construct/OFF has no family allocation");
 need(!capture.Initialize(nullptr,32,16,error)&&!capture.budget_,"invalid Initialize has no family allocation");
 need(capture.Initialize(fixture.device.Get(),32,16,error),error.c_str());WatchContext(capture);
 auto family=capture.budget_;need(family&&family->allocatedSlots==0,"feature Initialize lazily creates empty family only");
 std::array<Capture::SnapshotLease,32> held;
 for(auto& lease:held)need(capture.Capture(fixture.list.Get(),a.base.Get(),a.params.Get(),lease,error),error.c_str());
 const auto bytes32=capture.OwnedAuxiliaryBytes();need(family->allocatedSlots==32&&bytes32>0,"actual pending32fill shared family");
 auto old=capture.context_;need(capture.Initialize(fixture.device.Get(),64,16,error),error.c_str());WatchContext(capture);
 need(old->retired&&old->slots.empty()&&family==capture.context_->budget,"replacement retires full old cache and shares one family");
 need(capture.OwnedAuxiliaryBytes()==bytes32&&family->allocatedSlots==32,"current getter includes old pending allocations");
 Capture::SnapshotLease out;auto creates=snapshotCreates,dispatches=captureDispatches;
 need(!capture.Capture(fixture.list.Get(),b.base.Get(),b.params.Get(),out,error)&&!out,"33rd slot fails across resize");
 need(snapshotCreates==creates&&captureDispatches==dispatches,"family33fails before buffer creation or GPU commands");
 // A distinct WARP device is used ONLY for a cap-full zero-dispatch negative;
 // all actual shader execution in this fixture stays on the hardware device.
 ComPtr<IDXGIFactory4> factory;ComPtr<IDXGIAdapter> adapter;ComPtr<ID3D12Device> otherDevice;
 hr(CreateDXGIFactory2(0,IID_PPV_ARGS(&factory)));hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)));
 hr(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&otherDevice)));
 ComPtr<IUnknown> firstIdentity,otherIdentity;hr(fixture.device.As(&firstIdentity));hr(otherDevice.As(&otherIdentity));
 need(firstIdentity.Get()!=otherIdentity.Get(),"device replacement control requires genuinely different native identities");
 ComPtr<ID3D12CommandAllocator> otherAllocator;ComPtr<ID3D12GraphicsCommandList> otherList;
 hr(otherDevice->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&otherAllocator)));
 hr(otherDevice->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,otherAllocator.Get(),nullptr,IID_PPV_ARGS(&otherList)));
 Sources other;D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;D3D12_RESOURCE_DESC desc{};
 desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;desc.Width=32;desc.Height=16;desc.DepthOrArraySize=desc.MipLevels=desc.SampleDesc.Count=1;
 desc.Format=DXGI_FORMAT_R10G10B10A2_UNORM;hr(otherDevice->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,nullptr,IID_PPV_ARGS(&other.base)));
 desc.Format=DXGI_FORMAT_R8G8B8A8_UNORM;hr(otherDevice->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,nullptr,IID_PPV_ARGS(&other.params)));
 need(capture.Initialize(otherDevice.Get(),32,16,error),error.c_str());WatchContext(capture);
 need(!capture.Capture(otherList.Get(),other.base.Get(),other.params.Get(),out,error),"33rd slot on replacement device bypassed family cap");
 need(snapshotCreates==creates&&captureDispatches==dispatches&&capture.OwnedAuxiliaryBytes()==bytes32,"device replacement creates no private buffer/commands while old32remain allocated");
 need(capture.Initialize(fixture.device.Get(),64,16,error),error.c_str());WatchContext(capture);
 hr(otherList->Close());
 fixture.Submit();fixture.Reset();need(family->allocatedSlots==32,"completed Reset preserves external Snapshot leases");
 for(auto& lease:held)lease.reset();old.reset();need(family->allocatedSlots==0&&capture.OwnedAuxiliaryBytes()==0,"old snapshots release every retired slot without cache pinning");
 // Fill32 again, then retain only one snapshot while31slots are idle in cache.
 for(auto& lease:held)need(capture.Capture(fixture.list.Get(),b.base.Get(),b.params.Get(),lease,error),error.c_str());
 fixture.Submit();fixture.Reset();auto kept=std::move(held[0]);for(auto& lease:held)lease.reset();
 const auto keptBytes=kept->slot->bytes;need(family->allocatedSlots==32,"idle31remain allocated in current reusable cache");
 old=capture.context_;const auto finals=slotFinals;
 need(capture.Initialize(fixture.device.Get(),96,16,error),error.c_str());WatchContext(capture);
 need(family->allocatedSlots==1&&capture.OwnedAuxiliaryBytes()==keptBytes&&slotFinals==finals+31,"resize prunes31idle resources but preserves exactly one pending snapshot");
 kept.reset();old.reset();need(family->allocatedSlots==0&&capture.OwnedAuxiliaryBytes()==0,"later-idle old snapshot releases immediately");
 // A caller which copied the old context before replacement must record nothing.
 creates=snapshotCreates;dispatches=captureDispatches;
 beforeContextLock=[&]{need(capture.Initialize(fixture.device.Get(),32,16,error),error.c_str());WatchContext(capture);};
 need(!capture.Capture(fixture.list.Get(),c.base.Get(),c.params.Get(),out,error)&&!out,"late old-context capture fails closed");
 need(snapshotCreates==creates&&captureDispatches==dispatches&&family->allocatedSlots==0,"late old-context capture records no buffer/GPU work");
 // Native creation failures unwind candidate resources and permits after guards.
 failSnapshot=true;creates=snapshotCreates;dispatches=captureDispatches;
 need(!capture.Capture(fixture.list.Get(),a.base.Get(),a.params.Get(),out,error),"failed native private-buffer creation unexpectedly succeeded");
 need(snapshotCreates==creates+1&&captureDispatches==dispatches&&family->allocatedSlots==0&&capture.OwnedAuxiliaryBytes()==0,"failed buffer returns reservation before any command");
 throwSnapshot=true;need(!capture.Capture(fixture.list.Get(),a.base.Get(),a.params.Get(),out,error),"throwing buffer adapter unexpectedly succeeded");
 need(family->allocatedSlots==0&&capture.OwnedAuxiliaryBytes()==0,"exception candidate unwinds all reservation metadata");
 failHeap=true;creates=snapshotCreates;const auto beforeHeap=heapCreates;
 need(!capture.Capture(fixture.list.Get(),a.base.Get(),a.params.Get(),out,error),"failed descriptor creation unexpectedly succeeded");
 need(snapshotCreates==creates+1&&heapCreates==beforeHeap+1&&captureDispatches==dispatches&&family->allocatedSlots==0,"created native buffer dies and permit returns after descriptor failure");
 RecordedComputeLease::SetHooksAvailable(false,false);creates=snapshotCreates;
 need(!capture.Capture(fixture.list.Get(),a.base.Get(),a.params.Get(),out,error)&&!out,"failed recording retention unexpectedly succeeded");
 need(snapshotCreates==creates+1&&captureDispatches==dispatches&&family->allocatedSlots==1,"retention failure records no GPU work and leaves one valid cached allocation");
 RecordedComputeLease::SetHooksAvailable(true,true);creates=snapshotCreates;
 need(capture.Capture(fixture.list.Get(),a.base.Get(),a.params.Get(),out,error),error.c_str());
 need(snapshotCreates==creates,"successful recovery reuses failed-retention cached slot");
 fixture.Submit();fixture.Reset();out.reset();
 auto owner=capture.context_;std::shared_ptr<Capture::Slot> candidate;creates=snapshotCreates;
 allocationMeter=true;for(unsigned i=0;i<10000;++i){std::lock_guard guard(owner->mutex);Capture::Acquire(*owner,candidate);candidate.reset();}allocationMeter=false;
 need(warmAllocations==0&&snapshotCreates==creates&&family->allocatedSlots==1,"actual warm Acquire adds no C++/native allocation or new slot reservation");
 need(capture.Initialize(fixture.device.Get(),64,16,error),error.c_str());WatchContext(capture);owner.reset();
 need(family->allocatedSlots==0&&capture.OwnedAuxiliaryBytes()==0,"final idle cache retirement returns all family bytes");
 need(underLocks==0&&slotFinals>32,"actual Slot/COM destruction observers ran after helper/context locks");
 need(RecordedComputeLease::GetRegistry().recordings.empty()&&RecordedComputeLease::GetRegistry().submissions.empty(),"actual recording lease registry retires every test record");
 watchedCapture=nullptr;fixture.Validate();
 ComPtr<ID3D12InfoQueue> otherInfo;hr(otherDevice.As(&otherInfo));
 for(UINT64 index=0;index<otherInfo->GetNumStoredMessages();++index){SIZE_T size=0;hr(otherInfo->GetMessage(index,nullptr,&size));std::vector<char> bytes(size);
  auto* message=reinterpret_cast<D3D12_MESSAGE*>(bytes.data());hr(otherInfo->GetMessage(index,message,&size));
  need(message->Severity>D3D12_MESSAGE_SEVERITY_WARNING,"secondary zero-dispatch device debug layer warning/error");}
 nlohmann::json result{{"native_checks",checks},{"cap",32},{"native_private_creation_attempts",snapshotCreates},{"real_capture_dispatches",captureDispatches},
  {"slot_final_observers",slotFinals},{"under_helper_locks",underLocks},{"warm_acquire_cpp_allocations",warmAllocations},{"final_family_slots",family->allocatedSlots.load()},
  {"final_family_bytes",family->allocatedBytes.load()},{"debug_errors",0},{"debug_warnings",0},{"secondary_device_warp",true},{"secondary_device_dispatches",0},
  {"scope","Actual MaterialCapture functions/native buffers/heaps/shader/RecordedComputeLease; counted creation forwards/race trigger/passive final observer are explicit adapters. Warm meter excludes existing Snapshot/ledger allocations."}};
 std::ofstream(std::filesystem::path(argv[1])/"material-budget-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS material_budget checks="<<checks<<'\n';return 0;
}catch(const std::exception&e){std::cerr<<"FAIL material_budget "<<checks<<' '<<e.what()<<'\n';return 1;}
