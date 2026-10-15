// New helper proof; the complete existing RR regression remains unchanged.
#define FSRD_NRD_BRIDGE_RR_TEST_BACKEND
#include "nrd_bridge_rr_test_support.h"
#include "../../../misc/NrdBridgeNativeBirth_Dx12.h"
#include "../../../misc/NrdBridgeCaptureSlotBudget_Dx12.h"
#include "../../../misc/NrdBridgeOwned_Dx12.h"
#include "State.h"
ULONGLONG WINAPI LobeFixtureTick();
#define GetTickCount64 LobeFixtureTick
#include "../../fsrd_preprocess/FSRDNrdLobeRecovery_Dx12.h"
#undef GetTickCount64
// Include the helper first so future RR integration cannot bypass the scoped
// native-clock observer through an earlier pragma-once include.
#define main PreservedNrdRRRegressionMain
#include "nrd_bridge_rr_fixture.cpp"
#undef main
#include <json.hpp>
using J=nlohmann::json;
static uint64_t tickCalls=0,tickOffset=0;
ULONGLONG WINAPI LobeFixtureTick(){++tickCalls;return ::GetTickCount64()+tickOffset;}
static unsigned unexpectedCoverage=0;
bool NrdBridgeNativeBirth::ObserveReleaseCoverage(IUnknown*) noexcept {++unexpectedCoverage;return false;}
struct ForwardStats {unsigned live=0,released=0,earlyCharge=0,nonfinal=0;};
#include "lobe_native_forwarders.h"

namespace LobeFixture
{
constexpr auto UA=D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
constexpr auto NPS=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
// The forwarding list has a distinct proxy address and a native canonical
// IUnknown. Capture BEFORE the real successful Reset, exactly like the hook;
// the unchanged Host adapter only knows its native typed-list address.
static unsigned observedResets=0,distinctTypedCanonicalResets=0;
void reset(Host& host,LobeObservedList& list,size_t expectedLeases=SIZE_MAX)
{
 auto recording=RecordedComputeLease::Capture(&list);
 ComPtr<IUnknown> canonical;hr(list.QueryInterface(IID_PPV_ARGS(&canonical)));
 auto canonicalRecording=RecordedComputeLease::Capture(canonical.Get());
 auto typedRecording=RecordedComputeLease::Capture(host.list.Get());
 if(recording)
 {
  need(recording==canonicalRecording&&(!typedRecording||typedRecording==recording),"observed/canonical aliases resolve the same exact recording before native Reset");
  need(recording->identity==canonical.Get()&&static_cast<void*>(&list)!=static_cast<void*>(host.list.Get()),"proxy identity is distinct and its canonical identity is actual native IUnknown");
  size_t leases=0;{auto& registry=RecordedComputeLease::GetRegistry();std::lock_guard lock(registry.mutex);leases=recording->leases.size();}
  need(leases>0&&(expectedLeases==SIZE_MAX||leases==expectedLeases),"recording retains every expected immutable owner until real native Reset succeeds");
  if(static_cast<void*>(canonical.Get())!=static_cast<void*>(host.list.Get()))
  {need(!typedRecording,"unregistered native typed address cannot substitute for the tracked canonical/proxy aliases");++distinctTypedCanonicalResets;}
  if(expectedLeases!=SIZE_MAX)std::cerr<<"reset ownership before id="<<recording->id<<" leases="<<leases<<" typed="<<host.list.Get()<<" canonical="<<canonical.Get()<<" observed="<<&list<<'\n';
 }
 host.reset(); // If the native allocator/list Reset fails, retain the old ticket.
 RecordedComputeLease::Detach(recording);
 if(recording)
 {
  need(!RecordedComputeLease::Capture(&list)&&!RecordedComputeLease::Capture(canonical.Get())&&!RecordedComputeLease::Capture(host.list.Get()),"successful native Reset detaches all exact old recording aliases");
  ++observedResets;
 }
 // All strong tickets and their last owners die here, outside the registry lock.
}
LobeRecoveryInputs inputs(Scene& scene)
{
 return {scene.resources.spec,scene.resources.diff,scene.resources.linearDepth,scene.resources.motion,
  scene.resources.normals,scene.spec(),scene.diff(),scene.width,scene.height};
}
std::vector<uint8_t> file(const std::filesystem::path& path)
{
 std::ifstream in(path,std::ios::binary|std::ios::ate);need(bool(in),"parity input exists");
 const auto size=in.tellg();need(size>=0&&size<=16*1024*1024,"parity input is bounded");
 std::vector<uint8_t> bytes(static_cast<size_t>(size));in.seekg(0);in.read(reinterpret_cast<char*>(bytes.data()),bytes.size());
 need(in.gcount()==bytes.size(),"parity input has every sealed byte");return bytes;
}
struct Copy
{
 ComPtr<ID3D12Resource> readback;D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};uint32_t width,height,bpp;
 Copy(Host& host,ID3D12Resource* source,D3D12_RESOURCE_STATES state,unsigned bytesPerPixel):bpp(bytesPerPixel)
 {
  const auto desc=source->GetDesc();width=uint32_t(desc.Width);height=desc.Height;UINT64 total=0;
  host.device->GetCopyableFootprints(&desc,0,1,0,&footprint,nullptr,nullptr,&total);
  readback=buffer(host.device.Get(),total,D3D12_HEAP_TYPE_READBACK);
  barrier(host.list.Get(),source,state,D3D12_RESOURCE_STATE_COPY_SOURCE);
  D3D12_TEXTURE_COPY_LOCATION from{},to{};from.pResource=source;from.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
  to.pResource=readback.Get();to.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;to.PlacedFootprint=footprint;
  host.list->CopyTextureRegion(&to,0,0,0,&from,nullptr);barrier(host.list.Get(),source,D3D12_RESOURCE_STATE_COPY_SOURCE,state);
 }
 std::vector<uint8_t> bytes()
 {
  uint8_t* data=nullptr;hr(readback->Map(0,nullptr,reinterpret_cast<void**>(&data)));
  std::vector<uint8_t> result(size_t(width)*height*bpp);
  for(uint32_t y=0;y<height;++y)std::memcpy(result.data()+size_t(y)*width*bpp,
   data+footprint.Offset+size_t(y)*footprint.Footprint.RowPitch,size_t(width)*bpp);
  readback->Unmap(0,nullptr);return result;
 }
};
struct FrameInputs
{
 std::array<ComPtr<ID3D12Resource>,7> textures;
 std::array<ComPtr<ID3D12Resource>,7> uploads;
 LobeRecoveryInputs resources;
 FrameInputs(Host& host,const J& row,uint32_t width,uint32_t height)
 {
  constexpr std::array<const char*,7> names {"spec","diff","depth","motion","normals","rr_spec","rr_diff"};
  constexpr std::array<DXGI_FORMAT,7> formats {DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,
   DXGI_FORMAT_R32_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R10G10B10A2_UNORM,
   DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT};
  for(unsigned i=0;i<7;++i)
  {
   const auto data=file(row.at("inputs").at(names[i]).get<std::string>());const unsigned bpp=(i==2||i==4)?4:8;
   need(data.size()==size_t(width)*height*bpp,"every parity texture has the exact native footprint");
   D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;desc.Width=width;desc.Height=height;
   desc.DepthOrArraySize=desc.MipLevels=1;desc.SampleDesc.Count=1;desc.Format=formats[i];desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
   D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
   hr(host.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&textures[i])));
   D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};UINT64 total=0;
   host.device->GetCopyableFootprints(&desc,0,1,0,&footprint,nullptr,nullptr,&total);
   uploads[i]=buffer(host.device.Get(),total,D3D12_HEAP_TYPE_UPLOAD);void* mapped=nullptr;hr(uploads[i]->Map(0,nullptr,&mapped));
   for(uint32_t y=0;y<height;++y)std::memcpy(static_cast<uint8_t*>(mapped)+footprint.Offset+size_t(y)*footprint.Footprint.RowPitch,
    data.data()+size_t(y)*width*bpp,size_t(width)*bpp);
   uploads[i]->Unmap(0,nullptr);D3D12_TEXTURE_COPY_LOCATION from{},to{};
   from.pResource=uploads[i].Get();from.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;from.PlacedFootprint=footprint;
   to.pResource=textures[i].Get();to.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
   host.list->CopyTextureRegion(&to,0,0,0,&from,nullptr);barrier(host.list.Get(),textures[i].Get(),D3D12_RESOURCE_STATE_COPY_DEST,i<5?NPS:UA);
  }
  resources={textures[0].Get(),textures[1].Get(),textures[2].Get(),textures[3].Get(),textures[4].Get(),textures[5].Get(),textures[6].Get(),width,height};
 }
};
J parity(Host& host,LobeObservedList& list,const J& caseValue,LobeRecovery::Storage storage)
{
 auto family=MakeOwnedShared<LobeRecovery::Family>();LobeRecovery helper(storage);std::string error;
 const uint32_t width=caseValue.at("width"),height=caseValue.at("height");unsigned count=0;
 ID3D12Resource *stableSpec=nullptr,*stableDiff=nullptr;uint64_t warmTicks=0,textureBytes=0,auxiliaryBytes=0;
 for(const auto& row:caseValue.at("frames"))
 {
  FrameInputs data(host,row,width,height);LobeRecoveryFrame frame;frame.frameIndex=row.at("frame_index");frame.reset=row.at("reset");
  frame.jitterPixels=row.at("jitter_pixels").get<std::array<float,2>>();frame.jitterDeltaUv=row.at("jitter_delta_uv").get<std::array<float,2>>();
  LobeRecovery::Prepared prepared;const auto commands=list.commands;const auto recorded=helper.RecordedFrames();
  const bool ready=helper.Prepare(host.device.Get(),&list,data.resources,frame,family,prepared,error);need(ready,error.c_str());
  need(list.commands==commands&&helper.RecordedFrames()==recorded,"Prepare records zero GPU commands and never advances history");
  if(count==0){stableSpec=prepared.specular;stableDiff=prepared.diffuse;warmTicks=tickCalls;textureBytes=helper.OwnedTextureBytes();}
  else need(prepared.specular==stableSpec&&prepared.diffuse==stableDiff&&tickCalls==warmTicks,"warm context reuses one output pair and performs no retry clock query");
  need(ResTrack_Dx12::RetainComputeDispatch(host.device.Get(),&list,prepared.owner),"lease the complete immutable recovery preparation before Record");
  const auto dispatches=list.dispatches;helper.Record(&list,prepared);
  need(list.dispatches==dispatches+13&&helper.RecordedFrames()==recorded+1,"actual helper records exactly13 graph dispatches and one history advance");
  Copy spec(host,prepared.specular,UA,8),diff(host,prepared.diffuse,UA,8);
  std::array<std::unique_ptr<Copy>,7> original;
  for(unsigned i=0;i<7;++i)original[i]=std::make_unique<Copy>(host,data.textures[i].Get(),i<5?NPS:UA,(i==2||i==4)?4:8);
  auxiliaryBytes=helper.OwnedAuxiliaryBytes();host.submit();reset(host,list);
  need(spec.bytes()==file(row.at("outputs").at("spec").get<std::string>()),"complete helper specular array equals independently submitted13-pass graph bit for bit");
  need(diff.bytes()==file(row.at("outputs").at("diff").get<std::string>()),"complete helper diffuse array equals independently submitted13-pass graph bit for bit");
  constexpr std::array<const char*,7> names {"spec","diff","depth","motion","normals","rr_spec","rr_diff"};
  for(unsigned i=0;i<7;++i)need(original[i]->bytes()==file(row.at("inputs").at(names[i]).get<std::string>()),"recovery leaves every noisy/RR/guide byte unchanged");
  need(family->slots.allocatedSlots==1,"submitted/reset replay reuses one immutable descriptor/constant slot");++count;
 }
 return {{"name",caseValue.at("name")},{"frames",count},{"dispatches",count*13},{"graph_texture_bytes",textureBytes},{"constant_allocation_bytes",auxiliaryBytes}};
}
void failures(Host& host,LobeObservedList& list)
{
 Scene scene(host,64,64);host.submit();reset(host,list);const auto in=inputs(scene);LobeRecoveryFrame frame;std::string error;
 auto family=MakeOwnedShared<LobeRecovery::Family>();const auto noClock=tickCalls;
 {LobeRecovery off;need(off.OwnedTextureBytes()==0&&off.OwnedAuxiliaryBytes()==0&&off.RecordedFrames()==0&&tickCalls==noClock,"default construction performs zero allocation/clock/dispatch");}
 for(unsigned at:{1u,9u,55u,56u})
 {
  auto local=MakeOwnedShared<LobeRecovery::Family>();ForwardStats stats;
  ComPtr<LobeForwardDevice> device;device.Attach(new LobeForwardDevice(host.device.Get(),local,&stats));device->failCreateAt=at;device->wrapResources=true;
  LobeRecovery helper;LobeRecovery::Prepared prepared;const auto commands=list.commands;
  need(!helper.Prepare(device.Get(),&list,in,frame,local,prepared,error),"controlled actual native CreateCommittedResource E_OUTOFMEMORY is propagated");
  need(device->createCalls==at&&stats.released==at-1&&stats.live==0&&stats.earlyCharge==0&&stats.nonfinal==0,"all successfully created native resources physically release before the graph charge returns");
  need(!prepared.owner&&local->graphBytes==0&&local->slots.allocatedSlots==0&&local->slots.allocatedBytes==0&&helper.RecordedFrames()==0&&list.commands==commands,"allocation failure unwinds every graph/slot charge without GPU/history work");
  const auto calls=device->createCalls;need(!helper.Prepare(device.Get(),&list,in,frame,local,prepared,error)&&device->createCalls==calls,"cold failure cooldown prevents repeated native allocation attempts");
  tickOffset+=1001;
 }
 family->graphBytes=LobeRecovery::Family::GraphByteLimit;
 ComPtr<LobeForwardDevice> device;ForwardStats stats;device.Attach(new LobeForwardDevice(host.device.Get(),family,&stats));
 {LobeRecovery helper;LobeRecovery::Prepared prepared;const auto commands=list.commands;
  need(!helper.Prepare(device.Get(),&list,in,frame,family,prepared,error)&&device->createCalls==0&&list.commands==commands,"full2GiB family denies before native resource creation or GPU commands");
  need(family->slots.allocatedSlots==0&&family->graphBytes==LobeRecovery::Family::GraphByteLimit,"denied graph returns its in-progress slot reservation without consuming other family bytes");}
 family->graphBytes=0;tickOffset+=1001;
 Readback rawSpec(host,scene.spec()),rawDiff(host,scene.diff());host.submit();reset(host,list);
 rawSpec.exact({.125f,.25f,.5f,.75f},64,64);rawDiff.exact({1.25f,1.5f,1.75f,2.f},64,64);
 // Saturate immutable slots in one causal recording without cloning the graph.
 auto helper=std::make_unique<LobeRecovery>();std::array<LobeRecovery::Prepared,32> retained;
 for(unsigned i=0;i<32;++i){frame.frameIndex=i;frame.reset=i==0;
  const bool ready=helper->Prepare(host.device.Get(),&list,in,frame,family,retained[i],error);need(ready,error.c_str());
  need(ResTrack_Dx12::RetainComputeDispatch(host.device.Get(),&list,retained[i].owner),"retain each bounded graph descriptor recording");helper->Record(&list,retained[i]);}
 const auto bytes=family->graphBytes.load();LobeRecovery::Prepared denied;frame.frameIndex=32;
 need(!helper->Prepare(host.device.Get(),&list,in,frame,family,denied,error)&&helper->RecordedFrames()==32,"thirty-third outstanding slot is rejected without advancing its history");
 need(family->slots.allocatedSlots==32&&family->graphBytes==bytes,"thirty-two frame leases share one graph allocation");
 helper.reset();for(auto& lease:retained)lease={};
 {LobeRecovery fresh;const auto calls=device->createCalls;need(!fresh.Prepare(device.Get(),&list,in,frame,family,denied,error)&&device->createCalls==calls,"retired-context leases still consume the same stable family32-slot limit");}
 need(family->graphBytes==bytes,"GPU recording lease keeps the old graph alive after every caller owner is dropped");
 std::weak_ptr<RecordedComputeLease::Recording> retired;
 {auto ticket=RecordedComputeLease::Capture(&list);need(bool(ticket),"all32 outstanding graph owners have an exact observed-alias recording");
  {auto& registry=RecordedComputeLease::GetRegistry();std::lock_guard lock(registry.mutex);need(ticket->leases.size()==32,"the recorded proxy owns exactly32 graph preparations before fence/reset");}
  retired=ticket;}
 host.submit();reset(host,list,32);
 need(retired.expired(),"fence completion and successful native Reset release the final old recording ticket");
 if(family->graphBytes||family->slots.allocatedSlots||family->slots.allocatedBytes)
  std::cerr<<"reset cleanup graph_bytes="<<family->graphBytes<<" slots="<<family->slots.allocatedSlots<<" slot_bytes="<<family->slots.allocatedBytes<<std::endl;
 need(family->graphBytes==0&&family->slots.allocatedSlots==0&&family->slots.allocatedBytes==0,"fence completion and recording detach release all graph/slot storage");tickOffset+=1001;
}
void replay(Host& host,LobeObservedList& list)
{
 Scene scene(host,64,64);host.submit();reset(host,list);const auto in=inputs(scene);std::string error;
 auto family=MakeOwnedShared<LobeRecovery::Family>();LobeRecovery helper;
 for(unsigned frame=0;frame<2;++frame)
 {
  LobeRecoveryFrame parameters;parameters.frameIndex=frame;parameters.reset=frame==0;LobeRecovery::Prepared prepared;
  const bool ready=helper.Prepare(host.device.Get(),&list,in,parameters,family,prepared,error);need(ready,error.c_str());
  need(ResTrack_Dx12::RetainComputeDispatch(host.device.Get(),&list,prepared.owner),"lease cold/warm replay resources");
  helper.Record(&list,prepared);Readback spec(host,prepared.specular),diff(host,prepared.diffuse);host.submit();
  const auto firstSpec=spec.values(64,64),firstDiff=diff.values(64,64);
  ComPtr<IUnknown> identity;hr(host.list.As(&identity));auto submission=RecordedComputeLease::BeforeSubmission(host.queue.Get(),{identity.Get()});
  need(bool(submission),"closed replay keeps an actual recorded lease participant");
  ID3D12CommandList* commands[]={host.list.Get()};host.queue->ExecuteCommandLists(1,commands);RecordedComputeLease::AfterSubmission(submission);host.finish();
  need(spec.values(64,64)==firstSpec&&diff.values(64,64)==firstDiff,"cold and warm closed-list replay repeat exact GPU outputs with stable UAV/NPS boundary states");
  need(helper.RecordedFrames()==frame+1,"GPU list replay does not fabricate another CPU history advance");reset(host,list);
 }
}
}

namespace LobeReal
{
// These observations use the actual production DispatchLease already retained
// by the real ledger. They do not replace allocation, Record, Commit, or SDK work.
static PfnFfxDispatch nativeDispatch=nullptr;
static unsigned signedCalls=0,inspectionChecks=0,privateDispatches=0,commits=0;
static uint64_t changedSpecHalfWords=0,changedDiffHalfWords=0,matureChangedHalfWords=0,recoveredRgbHalfWords=0;
struct Probe
{
 LobeObservedList* list=nullptr;Scene* scene=nullptr;RRWrapper* wrapper=nullptr;
 bool recovery=false,deny=false,returnFailure=false,nativeDebug=false;
 uint64_t historyBefore=0;
 unsigned commandsBefore=0,afterProvider=0,providerCalls=0,guards=0,actions=0;
 ffxReturnCode_t nativeResult=FFX_API_RETURN_ERROR_RUNTIME_ERROR;
 const char* failure=nullptr;
 std::shared_ptr<DispatchLease> lease;
 void check(bool value,const char* reason) noexcept
 {++inspectionChecks;if(!value&&!failure)failure=reason;}
 static bool Admit(void* state,OutputCommitGuard::Action action,void* prepared) noexcept
 {
  auto& p=*static_cast<Probe*>(state);++p.guards;
  const auto publication=p.wrapper->GetSettingsState();
  p.check(!publication.lobeRecoveryActive&&!publication.lobeRecoveryFallback,"private preparation is not published as successful recovery/fallback before title admission");
  p.check(p.providerCalls==1&&p.nativeResult==FFX_API_RETURN_OK,"output admission follows exactly one successful actual signed SDK call");
  p.check(bool(p.lease),"the pre-provider strong DispatchLease survives through final admission");
  if(p.lease)
  {
   if(p.recovery)
   {
    p.check(p.lease->context->recovery&&p.lease->context->recovery->RecordedFrames()==p.historyBefore+1,"private history advances only after actual provider success and before title admission");
    p.check(p.list->dispatches==p.afterProvider+13,"all thirteen private graph dispatches precede title admission");
   }
   else p.check(!p.lease->recovery.owner&&!p.lease->context->recovery&&p.list->dispatches==p.afterProvider,"OFF, zero-strength, debug and optional fallback record zero private graph work");
  }
  if(p.deny)return false;
  const auto before=p.list->dispatches;action(prepared);++p.actions;
  p.check(p.list->dispatches==before+1,"admitted final action records exactly one actual title RGB commit");
  return true;
 }
};
static Probe* active=nullptr;
ffxReturnCode_t Dispatch(ffxContext* context,const ffxDispatchDescHeader* desc)
{
 need(active&&nativeDispatch,"signed provider facade has an explicit current observation and actual export");
 auto& p=*active;++p.providerCalls;
 const auto publication=p.wrapper->GetSettingsState();
 p.check(!publication.lobeRecoveryActive&&!publication.lobeRecoveryFallback,"real SDK observes no prematurely published current recovery/fallback status");
 auto recording=RecordedComputeLease::Capture(p.list);std::shared_ptr<void> owner;
 p.check(bool(recording),"actual production RR retains its complete lease before calling the provider");
 if(recording)
 {
  auto& registry=RecordedComputeLease::GetRegistry();std::lock_guard lock(registry.mutex);
  p.check(recording->leases.size()==1,"fresh native recording contains exactly the actual RR DispatchLease");
  if(recording->leases.size()==1)owner=recording->leases.front();
 }
 if(owner)p.lease=std::static_pointer_cast<DispatchLease>(owner);
 p.check(bool(p.lease),"the retained pre-provider owner is observable without a production test seam");
 if(p.lease)
 {
  const auto& lease=*p.lease;
  p.check(lease.context->handle==*context&&lease.slot&&lease.inputs[0].Get()==p.scene->resources.spec&&lease.inputs[1].Get()==p.scene->resources.diff,"the actual lease pins this exact provider context and owned noisy inputs");
  p.check(lease.slot->spec.Get()!=p.scene->spec()&&lease.slot->diff.Get()!=p.scene->diff(),"the actual provider always targets owned staging rather than title outputs");
  p.check(bool(lease.recovery.owner)==p.recovery,"recovery allocation and immutable preparation are complete before the actual provider");
  if(p.recovery)
  {
   p.check(lease.context->recovery&&lease.context->recovery->RecordedFrames()==p.historyBefore,"Prepare never advances private history before actual provider success");
   p.check(lease.recovery.specular&&lease.recovery.diffuse&&lease.recovery.specular!=lease.slot->spec.Get()&&lease.recovery.diffuse!=lease.slot->diff.Get()&&lease.recovery.specular!=p.scene->spec()&&lease.recovery.diffuse!=p.scene->diff(),"prepared recovery outputs are private and distinct from provider staging and title outputs");
  }
  else p.check(!lease.context->recovery,"every bypass releases its idle recovery context before SDK work");
 }
 if(!p.nativeDebug)p.check(p.list->commands==p.commandsBefore,"fallible recovery preparation emits zero GPU commands before actual provider work");
 ++signedCalls;p.nativeResult=nativeDispatch(context,desc);p.afterProvider=p.list->dispatches;
 if(p.returnFailure&&p.nativeResult==FFX_API_RETURN_OK)return FFX_API_RETURN_ERROR_RUNTIME_ERROR;
 return p.nativeResult;
}
struct ExportScope
{
 PfnFfxDispatch previous;
 ExportScope():previous(FfxApiProxy::dispatchFunction){nativeDispatch=previous;FfxApiProxy::dispatchFunction=Dispatch;}
 ~ExportScope(){active=nullptr;FfxApiProxy::dispatchFunction=previous;nativeDispatch=nullptr;}
};
struct ActiveScope
{
 explicit ActiveScope(Probe& probe){need(!active,"only one serialized actual provider observation is active");active=&probe;}
 ~ActiveScope(){active=nullptr;}
};
using GuideBytes=std::array<std::vector<uint8_t>,7>;
std::array<std::unique_ptr<LobeFixture::Copy>,7> copies(Host& host,Scene& scene)
{
 std::array<std::unique_ptr<LobeFixture::Copy>,7> result;
 for(unsigned i=0;i<7;++i)result[i]=std::make_unique<LobeFixture::Copy>(host,scene.textures[i].Get(),LobeFixture::NPS,(i==0||i==1||i==3)?8:4);
 return result;
}
GuideBytes originals(Host& host,LobeObservedList& list,Scene& scene)
{
 auto saved=copies(host,scene);host.submit();LobeFixture::reset(host,list);
 GuideBytes result;for(unsigned i=0;i<7;++i)result[i]=saved[i]->bytes();return result;
}
struct StepResult {std::weak_ptr<Context> context;std::weak_ptr<void> graph;};
StepResult step(Host& host,LobeObservedList& list,Scene& scene,RRWrapper& wrapper,uint32_t token,
 const GuideBytes& original,bool recovery,uint64_t historyBefore,bool expectedReset,
 bool fallback=false,bool deny=false,bool fail=false,int zeroLobe=-1)
{
 FrameParameters frame;std::string error;
 auto snapshot=camera(token,1.f);snapshot.constants.motionVectorsJittered=sl::Boolean::eFalse;
 need(wrapper.PrepareFrame(snapshot,false,frame,error),"prepare the exact actual RR frame for recovery integration");
 need(frame.reset==expectedReset,"optional recovery does not invent or suppress the caller's continuous RR reset policy");
 Probe probe;probe.list=&list;probe.scene=&scene;probe.wrapper=&wrapper;probe.recovery=recovery;probe.historyBefore=historyBefore;
 probe.deny=deny;probe.returnFailure=fail;probe.nativeDebug=wrapper.GetSettingsState().requested.nativeDebugView!=-1;probe.commandsBefore=list.commands;
 const auto calls=FfxApiProxy::dispatches,realCalls=signedCalls,destroys=FfxApiProxy::destroys;
 bool accepted=false;{ActiveScope observation(probe);accepted=wrapper.Dispatch(&list,scene.resources,scene.spec(),scene.diff(),frame,error,{&probe,Probe::Admit});}
 if(probe.failure||!accepted)std::cerr<<"real recovery observation SL="<<token<<" frame="<<frame.frameIndex<<" expectedRecovery="<<recovery<<" accepted="<<accepted<<" SDK="<<probe.providerCalls<<" guard="<<probe.guards<<" actions="<<probe.actions<<" afterSDK="<<probe.afterProvider<<" currentDispatch="<<list.dispatches<<" contextGeneration="<<wrapper.ContextGeneration()<<" error="<<error<<" failure="<<(probe.failure?probe.failure:"none")<<std::endl;
 need(!probe.failure,probe.failure?probe.failure:"actual recovery placement observation");
 need(probe.providerCalls==1&&signedCalls==realCalls+1&&FfxApiProxy::dispatches==calls+1&&probe.nativeResult==FFX_API_RETURN_OK,"every attempted frame actually calls the signed AMD export exactly once");
 need(accepted==!(deny||fail),"actual RR admission/failure result matches the explicit controlled outcome");
 need(bool(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)==expectedReset,"the actual signed descriptor preserves exact first/recovery-only RESET semantics");
 need(FfxApiProxy::lastCreate.signalFlags==(FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE|FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR)&&FfxApiProxy::lastDiffuse.header.type==FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE&&FfxApiProxy::lastSpecular.header.type==FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR,"recovery never changes the actual production DD/IS signal route");
 const auto state=wrapper.GetSettingsState();
 need(state.ready==accepted,"successful commits alone publish a live ready context after cancellation/provider error");
 need(state.lobeRecoveryActive==(accepted&&recovery)&&state.lobeRecoveryFallback==(accepted&&fallback),"only successful title admission publishes active/fallback status");
 need(probe.guards==(fail?0u:1u)&&probe.actions==(accepted?1u:0u),"provider failure skips final admission; denial records zero title commits");
 need(bool(probe.lease),"the actual leased provider resources remain strongly inspectable");
 if(fail)
 {
  need(probe.lease->context->recovery.has_value()==recovery&&(!recovery||probe.lease->context->recovery->RecordedFrames()==historyBefore)&&list.dispatches==probe.afterProvider,"SDK returned failure skips every private Record and history advance");
 }
 if(recovery&&!fail)privateDispatches+=13;
 commits+=probe.actions;
 need(scene.spec()->AddRef()==2&&scene.spec()->Release()==1&&scene.diff()->AddRef()==2&&scene.diff()->Release()==1,"neither the production RR lease nor recovery retains borrowed title outputs");
 StepResult result{probe.lease->context,probe.lease->recovery.owner};
 auto* chosenSpec=recovery?probe.lease->recovery.specular:probe.lease->slot->spec.Get();
 auto* chosenDiff=recovery?probe.lease->recovery.diffuse:probe.lease->slot->diff.Get();
 Readback titleSpec(host,scene.spec()),titleDiff(host,scene.diff());
 std::unique_ptr<Readback> selectedSpec,selectedDiff,rawSpec,rawDiff;
 if(accepted)
 {
  selectedSpec=std::make_unique<Readback>(host,chosenSpec);selectedDiff=std::make_unique<Readback>(host,chosenDiff);
  rawSpec=std::make_unique<Readback>(host,probe.lease->slot->spec.Get());rawDiff=std::make_unique<Readback>(host,probe.lease->slot->diff.Get());
 }
 auto unchanged=copies(host,scene);
 if(deny||fail)
 {
  need(!state.ready&&FfxApiProxy::destroys==destroys,"cancellation/provider error retires the context logically but its real GPU recording lease still owns it");
  probe.lease.reset();need(!result.context.expired()&&(!recovery||!result.graph.expired()),"the actual ledger retains canceled provider and prepared graph through GPU execution");
 }
 host.submit();LobeFixture::reset(host,list);
 for(unsigned i=0;i<7;++i)need(unchanged[i]->bytes()==original[i],"actual SDK/recovery/commit leaves all seven owned noisy and guide inputs byte-exact");
 if(!accepted)
 {
  titleSpec.exact({.125f,.25f,.5f,.75f},64,64);titleDiff.exact({1.25f,1.5f,1.75f,2.f},64,64);
  need(result.context.expired()&&result.graph.expired()&&FfxApiProxy::destroys==destroys+1,"fence and successful observed-alias Reset physically retire the canceled context and its speculative private history");
 }
 else
 {
  const auto ts=titleSpec.values(64,64),td=titleDiff.values(64,64),ss=selectedSpec->values(64,64),sd=selectedDiff->values(64,64);
  const auto rs=rawSpec->values(64,64),rd=rawDiff->values(64,64);
  size_t rgb=0,alpha=0,finite=0,zeroExact=0;
  for(size_t p=0;p<64u*64u;++p)
  {
   for(unsigned c=0;c<3;++c)
   {rgb+=ts[p*4+c]==ss[p*4+c];rgb+=td[p*4+c]==sd[p*4+c];finite+=std::isfinite(PackedVector::XMConvertHalfToFloat(ts[p*4+c]));finite+=std::isfinite(PackedVector::XMConvertHalfToFloat(td[p*4+c]));
    if(zeroLobe==0)zeroExact+=ss[p*4+c]==rs[p*4+c];if(zeroLobe==1)zeroExact+=sd[p*4+c]==rd[p*4+c];
    if(recovery)
    {const bool cs=ss[p*4+c]!=rs[p*4+c],cd=sd[p*4+c]!=rd[p*4+c];changedSpecHalfWords+=cs;changedDiffHalfWords+=cd;
     recoveredRgbHalfWords+=2;if(historyBefore>=8)matureChangedHalfWords+=unsigned(cs)+unsigned(cd);}}
   alpha+=ts[p*4+3]==PackedVector::XMConvertFloatToHalf(.75f);alpha+=td[p*4+3]==PackedVector::XMConvertFloatToHalf(2.f);
  }
  need(rgb==64u*64u*6u&&finite==rgb,"title RGB is finite and bit-exactly the selected actual raw/recovered RR pair");
  need(alpha==64u*64u*2u,"every actual title alpha word is preserved independently of undefined staged RR alpha");
  if(zeroLobe>=0)need(zeroExact==64u*64u*3u,"independently disabled lobe remains bit-exact raw signed RR, including mature history");
  if(probe.nativeDebug)need(wrapper.GetNativeDebugOutputSnapshot().resource&&wrapper.GetNativeDebugOutputSnapshot().owner,"native debug bypass still produces its real signed SDK diagnostic image");
 }
 return result;
}
void emptyFamily(const std::shared_ptr<RRRecoveryFamily>& family)
{
 need(family->budget.graphBytes==0&&family->budget.slots.allocatedSlots==0&&family->budget.slots.allocatedBytes==0,"all graph and immutable frame charges return after physical context/recording retirement");
}
J run(Host& host,LobeObservedList& list)
{
 loadReal();ExportScope exports;const auto creates=FfxApiProxy::creates,destroys=FfxApiProxy::destroys;
 auto family=CreateRRRecoveryFamily();need(bool(family),"create one explicit stable service-family analogue shared across replacement wrappers");
 J rows=J::array();uint32_t token=2000;
 const auto sequence=[&](const char* name,RRSettings settings,unsigned frames,bool recovery,int zeroLobe=-1,bool nullFamily=false)
 {
  std::cout<<"actual recovery case="<<name<<" frames="<<frames<<" private="<<recovery<<std::endl;
  Scene scene(host,64,64,{},true);const auto original=originals(host,list,scene);
  const auto before=FfxApiProxy::creates;const auto clock=tickCalls;auto wrapper=std::make_unique<RRWrapper>();std::string error;
  need(wrapper->Configure(settings,error),"configure a fresh actual signed RR integration history");wrapper->SetRecoveryFamily(nullFamily?std::shared_ptr<RRRecoveryFamily>{}:family);
  for(unsigned i=0;i<frames;++i)
  {
   step(host,list,scene,*wrapper,token++,original,recovery,i,i==0,nullFamily,false,false,zeroLobe);
   need(FfxApiProxy::creates==before+1&&wrapper->ContextGeneration()==1,"one continuous sequence uses one physical signed RR context, without hidden recreation");
   if(!recovery)need(tickCalls==clock&&family->budget.graphBytes==0&&family->budget.slots.allocatedSlots==0,"bypass performs zero recovery retry clocks, graph allocations, immutable slots or dispatches");
  }
  wrapper.reset();emptyFamily(family);rows.push_back({{"name",name},{"frames",frames},{"recovery",recovery},{"null_external_family",nullFamily},{"independent_zero_lobe",zeroLobe}});
 };
 RRSettings settings;sequence("default-off",settings,2,false);
 settings.lobeRecovery=true;settings.recoverySpecular=settings.recoveryDiffuse=0;sequence("both-zero",settings,2,false);
 settings.recoverySpecular=settings.recoveryDiffuse=1;sequence("recovery-on",settings,10,true);
 settings.recoverySpecular=0;sequence("specular-zero-mature",settings,16,true,0);
 settings.recoverySpecular=1;settings.recoveryDiffuse=0;sequence("diffuse-zero-mature",settings,16,true,1);
 settings.recoveryDiffuse=1;settings.nativeDebugView=0;sequence("native-debug-bypass",settings,1,false);
 settings.nativeDebugView=-1;sequence("null-external-family",settings,2,false,-1,true);
 // A full graph budget must neither fail RR nor reset/recreate its temporal context.
 {
  Scene scene(host,64,64,{},true);const auto original=originals(host,list,scene);auto wrapper=std::make_unique<RRWrapper>();std::string error;
  need(wrapper->Configure(settings,error),"configure optional graph-budget fallback");wrapper->SetRecoveryFamily(family);
  std::cout<<"actual recovery case=budget-fallback-same-RR-history frames=3"<<std::endl;
  family->budget.graphBytes=LobeRecovery::Family::GraphByteLimit;const auto before=FfxApiProxy::creates;
  step(host,list,scene,*wrapper,token++,original,false,0,true,true);
  step(host,list,scene,*wrapper,token++,original,false,0,false,true);
  need(family->budget.graphBytes==LobeRecovery::Family::GraphByteLimit&&family->budget.slots.allocatedSlots==0,"simulated other-context reservations are untouched and failed optional preparation leaks zero permits");
  family->budget.graphBytes=0;tickOffset+=1001;
  step(host,list,scene,*wrapper,token++,original,true,0,false);
  need(FfxApiProxy::creates==before+1&&wrapper->ContextGeneration()==1,"optional graph recovery after cooldown preserves the same actual RR history/context without RESET");
  wrapper.reset();emptyFamily(family);rows.push_back({{"name","budget-fallback-same-RR-history"},{"frames",3}});
 }
 for(unsigned kind=0;kind<3;++kind)
 {
  std::cout<<"actual recovery cancellation/error case="<<kind<<" attempts=2"<<std::endl;
  const bool deny=kind==0,nullFamily=kind==2;Scene scene(host,64,64,{},true);const auto original=originals(host,list,scene);
  auto wrapper=std::make_unique<RRWrapper>();std::string error;need(wrapper->Configure(settings,error),"configure canceled/failed actual signed RR recording");
  wrapper->SetRecoveryFamily(nullFamily?std::shared_ptr<RRRecoveryFamily>{}:family);const auto before=FfxApiProxy::creates;
  step(host,list,scene,*wrapper,token++,original,!nullFamily,0,true,false,deny,!deny);
  emptyFamily(family);
  step(host,list,scene,*wrapper,token++,original,!nullFamily,0,true,nullFamily);
  need(FfxApiProxy::creates==before+2&&wrapper->ContextGeneration()==2,"canceled/error predecessor recovers with exactly one fresh physical provider context and cold private history");
  wrapper.reset();emptyFamily(family);rows.push_back({{"name",deny?"guard-denial-after-private-record":nullFamily?"failed-optional-fallback-unpublished":"provider-returned-error-before-private-record"},{"attempts",2}});
 }
 need(signedCalls==58&&commits==55&&privateDispatches==46*13,"sealed integration performs58 actual signed calls,55 admitted commits and46 complete private graphs");
 need(FfxApiProxy::creates==creates+14&&FfxApiProxy::destroys==destroys+14&&FfxApiProxy::live.empty(),"all fourteen actual signed contexts have balanced physical creation/destruction after queue fences and Reset");
 need(FfxApiProxy::badDefaults==0,"optional graph experiments preserve all queried AMD scalar defaults");
 host.checkDebug();need(unexpectedCoverage==0&&!NrdBridgeNativeBirth::Ready(),"actual RR/recovery proof explicitly uses the unchanged legacy metadata adapter and no fake native coverage");
 std::cout<<"actual recovery changed half words spec="<<changedSpecHalfWords<<" diffuse="<<changedDiffHalfWords<<" mature="<<matureChangedHalfWords<<" observed="<<recoveredRgbHalfWords<<std::endl;
 return {{"changed_specular_rgb_half_words",changedSpecHalfWords},{"changed_diffuse_rgb_half_words",changedDiffHalfWords},{"changed_mature_rgb_half_words",matureChangedHalfWords},{"observed_recovered_rgb_half_words",recoveredRgbHalfWords},
  {"nonzero_effect_observed",matureChangedHalfWords>0},{"effect_scope",matureChangedHalfWords?"actual signed static toy has observable mature correction; integration, not quality":"host binding/conditional-state proof only; nonzero graph math is covered separately by independent complete-array parity"},
  {"native_checks",checks},{"inspection_checks",inspectionChecks},{"actual_signed_dispatches",signedCalls},{"successful_title_commits",commits},{"private_graph_dispatches",privateDispatches},{"physical_contexts",14},{"debug_errors",0},{"debug_warnings",0},{"cases",rows},
  {"scope","actual production RRWrapper, DispatchLease, LobeRecovery, Commit and actual signed AMD export; real native GPU outputs/lifetime; NativeBirth READY=false and legacy FrameSurvey application adapters; static synthetic admission/state proof, not game quality/FPS"}};
}
}

int main(int argc,char** argv)try
{
 std::cout.setf(std::ios::unitbuf);need(argc==3||argc==4,"helper fixture expects parity manifest, output folder and optional --real-provider");
 const std::filesystem::path output=argv[2];std::filesystem::create_directories(output);
 const auto data=LobeFixture::file(argv[1]);const auto manifest=J::parse(data.begin(),data.end());
 need(!NrdBridgeNativeBirth::Ready(),"standalone helper explicitly has unconfigured native-birth coverage");
 Host host;ComPtr<LobeObservedList> observed;observed.Attach(new LobeObservedList(host.list.Get()));
 if(argc==4)
 {
  need(std::string(argv[3])=="--real-provider","the additional native mode is explicitly actual signed-provider integration");
  const auto result=LobeReal::run(host,*observed.Get());std::ofstream(output/"lobe-recovery-rr-result.json")<<result.dump(2)<<'\n';
  std::cout<<"PASS lobe_recovery_real_rr checks="<<checks<<" signed_dispatches="<<LobeReal::signedCalls<<'\n';return 0;
 }
 LobeFixture::failures(host,*observed.Get());LobeFixture::replay(host,*observed.Get());
 const auto storage=manifest.at("storage")=="mixed"?LobeRecovery::Storage::MixedPrecision:LobeRecovery::Storage::FullPrecision;
 J rows=J::array();for(const auto& value:manifest.at("cases"))rows.push_back(LobeFixture::parity(host,*observed.Get(),value,storage));
 host.checkDebug();need(unexpectedCoverage==0,"no fake native coverage success was used");
 need(FfxApiProxy::dispatches==0,"helper parity consumes immutable previously signed-provider arrays and never fabricates a new SDK run");
 J result{{"native_checks",checks},{"observed_alias_resets",LobeFixture::observedResets},{"distinct_native_typed_canonical_resets",LobeFixture::distinctTypedCanonicalResets},{"debug_errors",0},{"debug_warnings",0},{"cases",rows},{"storage",manifest.at("storage")},
  {"scope","actual production recovery helper/real native commands and lease ledger; actual graph output parity; immutable signed-provider input provenance; proxy/legacy metadata adapters and controlled native allocation failures; no new RR/provider or game-quality/FPS claim"}};
 std::ofstream(output/"lobe-recovery-helper-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS lobe_recovery_helper checks="<<checks<<'\n';return 0;
}catch(const std::exception& e){std::cerr<<"lobe recovery fixture failure: "<<e.what()<<'\n';return 1;}
