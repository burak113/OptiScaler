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
  auxiliaryBytes=helper.OwnedAuxiliaryBytes();host.submit();host.reset();
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
 Scene scene(host,64,64);host.submit();host.reset();const auto in=inputs(scene);LobeRecoveryFrame frame;std::string error;
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
 Readback rawSpec(host,scene.spec()),rawDiff(host,scene.diff());host.submit();host.reset();
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
 host.submit();host.reset();need(family->graphBytes==0&&family->slots.allocatedSlots==0&&family->slots.allocatedBytes==0,"fence completion and recording detach release all graph/slot storage");tickOffset+=1001;
}
}
int main(int argc,char** argv)try
{
 std::cout.setf(std::ios::unitbuf);need(argc==3,"helper fixture expects parity manifest and output folder");
 const std::filesystem::path output=argv[2];std::filesystem::create_directories(output);
 const auto data=LobeFixture::file(argv[1]);const auto manifest=J::parse(data.begin(),data.end());
 need(!NrdBridgeNativeBirth::Ready(),"standalone helper explicitly has unconfigured native-birth coverage");
 Host host;ComPtr<LobeObservedList> observed;observed.Attach(new LobeObservedList(host.list.Get()));LobeFixture::failures(host,*observed.Get());
 const auto storage=manifest.at("storage")=="mixed"?LobeRecovery::Storage::MixedPrecision:LobeRecovery::Storage::FullPrecision;
 J rows=J::array();for(const auto& value:manifest.at("cases"))rows.push_back(LobeFixture::parity(host,*observed.Get(),value,storage));
 host.checkDebug();need(unexpectedCoverage==0,"no fake native coverage success was used");
 need(FfxApiProxy::dispatches==0,"helper parity consumes immutable previously signed-provider arrays and never fabricates a new SDK run");
 J result{{"native_checks",checks},{"debug_errors",0},{"debug_warnings",0},{"cases",rows},{"storage",manifest.at("storage")},
  {"scope","actual production recovery helper/real native commands and lease ledger; actual graph output parity; immutable signed-provider input provenance; proxy/legacy metadata adapters and controlled native allocation failures; no new RR/provider or game-quality/FPS claim"}};
 std::ofstream(output/"lobe-recovery-helper-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS lobe_recovery_helper checks="<<checks<<'\n';return 0;
}catch(const std::exception& e){std::cerr<<"lobe recovery fixture failure: "<<e.what()<<'\n';return 1;}
