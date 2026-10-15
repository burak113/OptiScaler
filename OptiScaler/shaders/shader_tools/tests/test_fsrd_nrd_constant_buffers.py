"""Borrowed live b-register resolution on actual D3D12 roots/buffers and production seed/getter.

All roots and constant data are synthetic; no title bytecode is embedded.
"""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_fsrd_frame_survey as survey_fixture
import test_fsrd_nrd_register_bindings as register_fixture
from test_fsrd_nrd_root_restore import function
from fsrd_toolchain import compile_cpp

CPP = r'''
// The surveyed D3D12_Hooks state slice calls RootTrackerBirthsEnabled(), which reads the
// startup wrapper flag; define it before that slice exactly as the hooks translation unit does.
bool gNrdBridgeDeviceWrappers=true;
__STATE__
// Synthetic mirror of the production DescriptorHeap layout (birth fields included).
struct DescriptorHeap { UINT NumDescriptorHeaps=0; ID3D12DescriptorHeap* Heaps[2]={nullptr,nullptr};
 NrdBridgeBirth::Token receiverBirth; std::array<NrdBridgeBirth::Token,2> heapBirths; };
std::shared_mutex rootStatesMutex,descriptorHeapsMutex;
std::unordered_map<ID3D12GraphicsCommandList*,TrackedRootRows> rootStates;
std::unordered_map<ID3D12GraphicsCommandList*,DescriptorHeap> descriptorHeaps;
std::unordered_map<ID3D12GraphicsCommandList*,ID3D12RootSignature*> bridgeComputeRoots;
__GETTER__
unsigned cbvNativeCalls=0;
bool gNrdBridgeWrappers=true;
void nativeCBV(ID3D12Device* device,const D3D12_CONSTANT_BUFFER_VIEW_DESC* desc,D3D12_CPU_DESCRIPTOR_HANDLE handle) {
 ++cbvNativeCalls; device->CreateConstantBufferView(desc,handle);
}
auto o_CreateConstantBufferView=&nativeCBV;
// The surveyed CBV hook runs inside the production descriptor-admission gate and the
// untracked-required-submission latch; compile against their real headers.
#include "misc/NrdBridgeDescriptorAdmission_Dx12.h"
#include "misc/RecordedComputeLease_Dx12.h"
// The surveyed production translation units reference these bridge-facing entry
// points. The fixture keeps the NRD bridge startup dormant (the production state
// when NrdBridge::StartupEnabled() is false), so the stubs mirror that exact
// semantics instead of linking the full bridge coordinator.
namespace NrdBridge {
 inline bool StartupEnabled() noexcept { return false; }
 inline DispatchDisposition OriginalDispatchDisposition(ID3D12GraphicsCommandList*, DispatchKind) noexcept { return DispatchDisposition::Forward; }
 inline void InvalidateRecordingProof(ID3D12GraphicsCommandList*, const char*, const char*) noexcept {}
 inline bool PreserveIndirectRecording(ID3D12GraphicsCommandList*, ID3D12CommandSignature*) noexcept { return false; }
 inline const char* LobeRecoveryTierName(uint32_t) noexcept { return "fixture"; }
 inline const char* LobeRecoveryFallbackReasonName(uint32_t) noexcept { return "fixture"; }
}
namespace NrdBridgeNativeBirth { inline bool ObserveReleaseCoverage(IUnknown*) noexcept { return false; } }
void D3D12Hooks::OnBridgeOpaqueCommand(ID3D12GraphicsCommandList*, bool) noexcept {}
__CBVHOOK__
struct ConstantHost: RegisterHost {
 ComPtr<ID3D12DescriptorHeap> cpuHeap;
 std::vector<ComPtr<ID3D12Resource>> buffers;
 UINT stride=0;
 explicit ConstantHost(Host& h):RegisterHost(h) {
  D3D12_DESCRIPTOR_HEAP_DESC hd {}; hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; hd.NumDescriptors=32;
  hr(h.dev->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&cpuHeap))); FrameSurvey::HeapCreated(h.dev.Get(),cpuHeap.Get());
  stride=h.dev->GetDescriptorHandleIncrementSize(hd.Type);
 }
 ID3D12Resource* buffer(UINT64 size,D3D12_HEAP_TYPE type=D3D12_HEAP_TYPE_UPLOAD) {
  D3D12_HEAP_PROPERTIES hp {}; hp.Type=type;
  D3D12_RESOURCE_DESC d {}; d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER; d.Width=size; d.Height=1;
  d.DepthOrArraySize=1; d.MipLevels=1; d.SampleDesc.Count=1; d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
  ComPtr<ID3D12Resource> resource;
  auto state=type==D3D12_HEAP_TYPE_UPLOAD?D3D12_RESOURCE_STATE_GENERIC_READ:D3D12_RESOURCE_STATE_VERTEX_AND_CONSTANT_BUFFER;
  hr(host.dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,state,nullptr,IID_PPV_ARGS(&resource)));
  FrameSurvey::ResourceCreated(resource.Get(),state); buffers.push_back(resource); return resource.Get();
 }
 ID3D12RootSignature* root(bool table=false,UINT reg=6,UINT space=0,
   D3D12_SHADER_VISIBILITY visibility=D3D12_SHADER_VISIBILITY_ALL,
   std::vector<D3D12_DESCRIPTOR_RANGE> ranges={},bool track=true,bool constants=false,
   D3D12_ROOT_SIGNATURE_FLAGS flags=D3D12_ROOT_SIGNATURE_FLAG_NONE) {
  D3D12_ROOT_PARAMETER p[6] {};
  for(UINT i=0;i<6;++i) { p[i].ParameterType=D3D12_ROOT_PARAMETER_TYPE_SRV; p[i].Descriptor={100+i,0}; }
  D3D12_DESCRIPTOR_RANGE srvs {D3D12_DESCRIPTOR_RANGE_TYPE_SRV,8,0,0,0};
  D3D12_DESCRIPTOR_RANGE uavs {D3D12_DESCRIPTOR_RANGE_TYPE_UAV,2,0,0,0};
  p[1].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; p[1].DescriptorTable={1,&srvs};
  p[5].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; p[5].DescriptorTable={1,&uavs};
  if(table) {
   if(ranges.empty()) ranges={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,1,20,0,0},
     {D3D12_DESCRIPTOR_RANGE_TYPE_CBV,8,0,space,D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND}};
   p[3].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; p[3].DescriptorTable={UINT(ranges.size()),ranges.data()}; p[3].ShaderVisibility=visibility;
  } else if(constants) {
   p[0].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS; p[0].Constants={reg,space,1};
  } else {
   p[0].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV; p[0].Descriptor={reg,space}; p[0].ShaderVisibility=visibility;
  }
  D3D12_ROOT_SIGNATURE_DESC d {6,p,0,nullptr,flags};
  ComPtr<ID3DBlob> bytes,error; hr(D3D12SerializeRootSignature(&d,D3D_ROOT_SIGNATURE_VERSION_1,&bytes,&error));
  ComPtr<ID3D12RootSignature> result; hr(host.dev->CreateRootSignature(0,bytes->GetBufferPointer(),bytes->GetBufferSize(),IID_PPV_ARGS(&result)));
  if(track) FrameSurvey::RootCreated(result.Get(),bytes->GetBufferPointer(),bytes->GetBufferSize());
  roots.push_back(result); return result.Get();
 }
 D3D12_CPU_DESCRIPTOR_HANDLE cpu(UINT slot,bool visible=false) {
  auto h=(visible?heap:cpuHeap)->GetCPUDescriptorHandleForHeapStart(); h.ptr+=UINT64(slot)*stride; return h;
 }
 void write(UINT slot,ID3D12Resource* resource,UINT64 offset=0,UINT size=1536,bool visible=false) {
  D3D12_CONSTANT_BUFFER_VIEW_DESC desc {resource->GetGPUVirtualAddress()+offset,size};
  hkSurveyCreateConstantBufferView(host.dev.Get(),&desc,cpu(slot,visible));
 }
 void copy(UINT destination,bool visible,UINT source,bool sourceVisible=false) {
  auto d=cpu(destination,visible),s=cpu(source,sourceVisible);
  host.dev->CopyDescriptorsSimple(1,d,s,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  FrameSurvey::CopyDescriptors(host.dev.Get(),1,&d,nullptr,1,&s,nullptr,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 }
 void direct(ID3D12RootSignature* root,UINT64 address,bool native=true) {
  bind(root);
  if(native) host.list->SetComputeRootConstantBufferView(0,address);
  FrameSurvey::RootView(host.list.Get(),false,0,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,address);
 }
 void table(ID3D12RootSignature* root,UINT first=0) {
  bind(root); auto h=gpu; h.ptr+=UINT64(first)*stride;
  host.list->SetComputeRootDescriptorTable(3,h); FrameSurvey::Table(host.list.Get(),false,3,h);
 }
 bool resolve(FrameSurvey::BoundConstantBuffer& out,UINT reg=6,UINT space=0,UINT64 bytes=1216) {
  return FrameSurvey::ResolveComputeConstantBuffer(host.list.Get(),reg,space,bytes,out);
 }
 void trackSnapshot(ID3D12RootSignature* root,UINT64 va,bool table=false) {
  auto* list=host.list.Get(); bridgeComputeRoots[list]=root; descriptorHeaps[list]={1,{heap.Get(),nullptr}};
  auto& entries=rootStates[list]; entries.clear(); entries.resize(6);
  entries[1].type=RootEntryType::Table; entries[1].rootDescriptorTable=gpu;
  entries[5].type=RootEntryType::Table; entries[5].rootDescriptorTable=gpu;
  if(table) { entries[3].type=RootEntryType::Table; entries[3].rootDescriptorTable=gpu; }
  else { entries[0].type=RootEntryType::CBV; entries[0].bufferLocation=va; }
 }
};
J constantTests(Host& h) {
 ConstantHost f(h); FrameSurvey::BoundConstantBuffer out;
 auto* a=f.buffer(4096); auto* b=f.buffer(8192,D3D12_HEAP_TYPE_DEFAULT);
 const auto av=a->GetGPUVirtualAddress(),bv=b->GetGPUVirtualAddress();
 auto* direct=f.root(); f.direct(direct,av+256);
 need(f.resolve(out) && out.resource==a && out.address==av+256 && out.offset==256 && out.size==3840,"actual root b6 resolves exact borrowed buffer subrange");
 need(!f.resolve(out,7) && !out.resource && !f.resolve(out,6,1),"root b-register/space mismatch clears result");
 need(!f.resolve(out,6,0,0) && !f.resolve(out,6,0,65537),"zero and over-64KiB requested lengths fail");
 const ULONG refs=a->AddRef(); a->Release();
 for(UINT i=0;i<100;++i) need(f.resolve(out),"repeated exact b6 lookup remains current");
 const ULONG after=a->AddRef(); a->Release(); need(refs==after,"CBV resolver never AddRefs borrowed title buffers");
 FrameSurvey::RootView(h.list.Get(),false,0,D3D12_DESCRIPTOR_RANGE_TYPE_SRV,av+256);
 need(!f.resolve(out),"metadata-only wrong current root descriptor kind is rejected");
 f.direct(direct,av+3840); need(!f.resolve(out),"current root address near buffer end cannot expose requested field");
 f.direct(direct,bv+512); need(f.resolve(out) && out.resource==b && out.offset==512,"default-heap root CBV is resolved without mapping or excluding it");
 auto* shifted=f.root(false,7); f.direct(shifted,av);
 need(!f.resolve(out) && f.resolve(out,7),"root descriptor shader register is captured exactly");
 auto* space=f.root(false,6,2); f.direct(space,av);
 need(!f.resolve(out) && f.resolve(out,6,2),"root CBV nonzero register space is exact");
 auto* pixel=f.root(false,6,0,D3D12_SHADER_VISIBILITY_PIXEL); f.direct(pixel,av,false);
 need(!f.resolve(out),"metadata-only PIXEL root-CBV callback cannot prove a compute binding");
 auto* constants=f.root(false,6,0,D3D12_SHADER_VISIBILITY_ALL,{},true,true); f.bind(constants);
 need(!f.resolve(out),"root constants do not masquerade as a b6 buffer");
 auto* unknown=f.root(false,21,0,D3D12_SHADER_VISIBILITY_ALL,{},false); f.direct(unknown,av);
 need(!f.resolve(out,21),"unique actual root with missing creation metadata fails closed");
 f.direct(direct,av); FrameSurvey::RootBinding(h.list.Get(),false,shifted);
 need(!f.resolve(out,7),"root change clears stale direct-CBV argument");
 f.direct(direct,av); FrameSurvey::Reset(h.list.Get(),nullptr);
 need(!f.resolve(out),"Reset clears direct-CBV identity");
 f.trackSnapshot(direct,av+256); FrameSurvey::ComputeBindings snapshot;
 need(GetComputeBindingsForBridge(h.list.Get(),snapshot) && snapshot.views.size()==1 && snapshot.views[0].parameter==0 &&
   snapshot.views[0].kind==D3D12_DESCRIPTOR_RANGE_TYPE_CBV && snapshot.views[0].address==av+256,"production getter snapshots root CBV parameter/kind/VA exactly");
 need(FrameSurvey::SeedComputeBindings(h.list.Get(),snapshot) && f.resolve(out) && out.address==av+256,"window seed resolves current pre-window root CBV");
 auto& entries=rootStates[h.list.Get()]; entries[2].type=RootEntryType::SRV; entries[2].bufferLocation=av+512;
 entries[4].type=RootEntryType::UAV; entries[4].bufferLocation=bv+768;
 need(GetComputeBindingsForBridge(h.list.Get(),snapshot) && snapshot.views.size()==3 && snapshot.views[1].parameter==2 &&
   snapshot.views[1].kind==D3D12_DESCRIPTOR_RANGE_TYPE_SRV && snapshot.views[2].kind==D3D12_DESCRIPTOR_RANGE_TYPE_UAV,"production getter preserves all root-view kinds in parameter order");
 entries[0]={}; need(GetComputeBindingsForBridge(h.list.Get(),snapshot) && FrameSurvey::SeedComputeBindings(h.list.Get(),snapshot) && !f.resolve(out),"sparse same-root seed clears omitted old CBV instead of preserving stale VA");
 entries[0].type=RootEntryType::CBV; entries[0].bufferLocation=0;
 need(GetComputeBindingsForBridge(h.list.Get(),snapshot) && FrameSurvey::SeedComputeBindings(h.list.Get(),snapshot) && !f.resolve(out),"zero root CBV address is omitted and tombstones previous seeded state");
 f.direct(direct,av);
 { FrameSurvey::ScopedInternal internal; need(!f.resolve(out),"internal injection cannot resolve title CBV metadata"); }
 need(f.resolve(out),"internal scope leaves root CBV state intact");
 FrameSurvey::gMetadataHealthy.store(false); need(!f.resolve(out) && !out.resource,"unhealthy metadata rejects root CBV"); FrameSurvey::gMetadataHealthy.store(true);
 auto* large=f.buffer(131072); f.direct(direct,large->GetGPUVirtualAddress());
 need(f.resolve(out) && out.size==65536,"root-CBV accessible size is capped at D3D12's 64KiB span");
 auto& layout=FrameSurvey::gRootLayouts.at(direct); const auto savedDescriptors=layout.computeDescriptors;
 layout.computeDescriptors[2]={D3D12_DESCRIPTOR_RANGE_TYPE_CBV,6,0};
 need(!f.resolve(out),"metadata-only duplicate b6 root parameters fail uniqueness proof"); layout.computeDescriptors=savedDescriptors;
 f.direct(direct,av);
 auto& alias=FrameSurvey::gResources.at(b); const auto savedVA=alias.va;
 FrameSurvey::gBufferAddresses.Erase(alias.va,alias.id); alias.va=av;
 FrameSurvey::gBufferAddresses.Insert(alias.va,alias.desc.Width,alias.id,b);
 need(!f.resolve(out),"metadata-only overlapping live buffer VAs are ambiguous, not nearest-address guesses");
 FrameSurvey::gBufferAddresses.Erase(alias.va,alias.id); alias.va=savedVA;
 FrameSurvey::gBufferAddresses.Insert(alias.va,alias.desc.Width,alias.id,b);
 auto* table=f.root(true); f.table(table); f.write(0,a,512); f.copy(1,false,0); f.copy(7,true,1);
 need(f.resolve(out) && out.resource==a && out.address==av+512 && out.offset==512 && out.size==1536,"mixed APPEND table maps b6 through exact CBV descriptor/address/size");
 need(cbvNativeCalls==1,"actual new CBV callback forwards native creation exactly once");
 need(!f.resolve(out,5),"adjacent missing table CBV is not guessed from b6");
 FrameSurvey::SetBindingWindow(false); f.write(0,b,768); f.copy(1,false,0); f.copy(7,true,1);
 f.trackSnapshot(table,0,true); FrameSurvey::SetBindingWindow(true);
 need(GetComputeBindingsForBridge(h.list.Get(),snapshot) && FrameSurvey::SeedComputeBindings(h.list.Get(),snapshot) &&
   f.resolve(out) && out.resource==b && out.offset==768,"closed-window CPU chain and visible overwrite survive sparse production seed correctly");
 FrameSurvey::Released(a);
 need(f.resolve(out) && out.resource==b,"release of old CPU-handle owner cannot delete replacement CBV metadata");
 FrameSurvey::SetBindingWindow(false); FrameSurvey::SetBindingWindow(true);
 need(FrameSurvey::SeedComputeBindings(h.list.Get(),snapshot) && f.resolve(out) && out.resource==b,"persistent CBV table remains valid across windows without recopy");
 hkSurveyCreateConstantBufferView(h.dev.Get(),nullptr,f.cpu(7,true));
 need(!f.resolve(out) && !out.resource,"native null CBV overwrites/tombstones previously valid visible descriptor");
 f.write(7,b,768,1024,true); need(!f.resolve(out),"table CBV declared size smaller than field rejects even when buffer is large");
 D3D12_CONSTANT_BUFFER_VIEW_DESC bad {bv+768,0}; FrameSurvey::View(f.cpu(7,true),&bad);
 need(!f.resolve(out),"metadata-only zero-size CBV tombstones the old descriptor");
 f.write(7,b,768,1536,true); bad={bv+769,1536}; FrameSurvey::View(f.cpu(7,true),&bad);
 need(!f.resolve(out),"metadata-only misaligned CBV GPUVA tombstones the old descriptor");
 f.write(7,b,768,1536,true); bad={bv+768,1537}; FrameSurvey::View(f.cpu(7,true),&bad);
 need(!f.resolve(out),"metadata-only non-256-byte CBV size tombstones the old descriptor");
 f.write(7,b,768,1536,true); bad={bv+768,65536}; FrameSurvey::View(f.cpu(7,true),&bad);
 need(!f.resolve(out),"metadata-only CBV range beyond live buffer is rejected");
 f.write(7,b,768,1536,true); hkSurveyCreateConstantBufferView(h.dev.Get(),nullptr,f.cpu(2)); f.copy(7,true,2);
 need(!f.resolve(out),"unknown/null CPU source copy tombstones the old visible CBV");
 f.write(7,b,768,1536,true);
 FrameSurvey::Table(h.list.Get(),false,3,{f.gpu.ptr+1}); need(!f.resolve(out),"metadata-only unaligned current GPU descriptor-table base fails");
 FrameSurvey::Table(h.list.Get(),false,3,{f.gpu.ptr+127*f.stride}); need(!f.resolve(out),"table b6 descriptor outside live heap fails bounds");
 f.table(table); auto* tableSpace=f.root(true,6,3); f.table(tableSpace);
 need(!f.resolve(out) && f.resolve(out,6,3),"table CBV nonzero register space is preserved");
 auto* overlap=f.root(true,6,0,D3D12_SHADER_VISIBILITY_ALL,{{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,4,4,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,4,10,0,2}}); f.table(overlap);
 need(!f.resolve(out),"actual overlapping descriptor-table ranges cannot prove unique b6");
 auto* unbounded=f.root(true,6,0,D3D12_SHADER_VISIBILITY_ALL,{{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,UINT_MAX,0,0,0}}); f.table(unbounded);
 need(!f.resolve(out),"actual unbounded CBV table is never treated as a finite known b6 span");
 auto* tablePixel=f.root(true,6,0,D3D12_SHADER_VISIBILITY_PIXEL); f.bind(tablePixel); FrameSurvey::Table(h.list.Get(),false,3,f.gpu);
 need(!f.resolve(out),"metadata-only PIXEL CBV table cannot prove compute b6");
 f.table(table);
 const auto occupiedBefore=FrameSurvey::gHeaps.at(f.heap.Get()).views.size();
 FrameSurvey::HeapCreated(h.dev.Get(),f.heap.Get());
 need(FrameSurvey::gHeaps.at(f.heap.Get()).views.size()==occupiedBefore && f.resolve(out),"repeated native heap registration retains occupied current CBV proof");
 FrameSurvey::Released(b); need(!f.resolve(out),"buffer release invalidates all current copied CBV handles");
 auto* c=f.buffer(4096); f.write(7,c,0,1536,true);
 need(f.resolve(out) && out.resource==c,"new current CBV owner resolves after prior buffer release");
 const auto before=std::chrono::steady_clock::now();
 for(UINT i=0;i<200000;++i) if(!f.resolve(out)) throw std::runtime_error("measured CBV lookup unexpectedly failed");
 const double ns=double(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-before).count())/200000;
 const auto resourceRecords=FrameSurvey::gResources.size();
 std::vector<ID3D12Resource*> syntheticBuffers;
 for(UINT i=0;i<1000;++i) {
  auto* object=reinterpret_cast<ID3D12Resource*>(UINT64(0x100000000)+UINT64(i)*65536);
  FrameSurvey::Resource resource; resource.object=object; resource.id=100000+i;
  resource.desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER; resource.desc.Width=4096;
  resource.va=c->GetGPUVirtualAddress()+0x10000000+UINT64(i)*65536;
  FrameSurvey::gResources.emplace(object,resource);
  FrameSurvey::gBufferAddresses.Insert(resource.va,resource.desc.Width,resource.id,object); syntheticBuffers.push_back(object);
 }
 need(f.resolve(out) && out.resource==c,"1,000 synthetic cached-buffer records need no COM access during exact resolution");
 const auto stressBefore=std::chrono::steady_clock::now();
 for(UINT i=0;i<20000;++i) if(!f.resolve(out)) throw std::runtime_error("stress CBV lookup unexpectedly failed");
 const double stressNs=double(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-stressBefore).count())/20000;
 const auto stressRecords=FrameSurvey::gResources.size();
 for(auto* object:syntheticBuffers) FrameSurvey::gResources.erase(object);
 FrameSurvey::Released(table); need(!f.resolve(out),"root release invalidates current table CBV proof");
 f.direct(direct,c->GetGPUVirtualAddress()); FrameSurvey::Released(h.list.Get()); need(!f.resolve(out),"list release invalidates direct CBV proof");
 f.table(tableSpace);
 FrameSurvey::HeapCreated(h.dev.Get(),f.heap.Get()); const auto heapViews=FrameSurvey::gHeaps.at(f.heap.Get()).views;
 FrameSurvey::Released(f.heap.Get()); need(!f.resolve(out,6,3),"descriptor heap release invalidates table CBV proof");
 need(std::all_of(heapViews.begin(),heapViews.end(),[](auto handle){return !FrameSurvey::gViews.contains(handle);}),"release after repeated heap registration removes all occupied descriptors");
 need(std::all_of(FrameSurvey::gResources.begin(),FrameSurvey::gResources.end(),[&](const auto& row){
  return std::none_of(heapViews.begin(),heapViews.end(),[&](auto handle){return row.second.handles.contains(handle);});}),"release after repeated heap registration removes every resource reverse reference");
 gNrdBridgeDeviceWrappers=false; snapshot.views.push_back({0,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,av});
 need(!GetComputeBindingsForBridge(h.list.Get(),snapshot) && snapshot.views.empty(),"OFF getter publishes no root-view snapshot");
 hr(h.list->Close()); h.execute(); h.reset(); h.errors();
 return {{"checks_passed",checks},{"adapter",h.adapter},{"constant_buffer_callback_mean_ns",ns},{"measured_resource_records",resourceRecords},
  {"synthetic_buffer_stress_callback_mean_ns",stressNs},{"synthetic_buffer_stress_records",stressRecords},
  {"cbv_native_calls",cbvNativeCalls},{"scope","actual production root/table CBV resolver, seed, getter and creation callback; synthetic ambiguity/invalid-input metadata cases"},
  {"contains_title_binary",false}};
}
J diagnosticTests(Host& h) {
 FrameSurvey::Shutdown();gNrdBridgeDeviceWrappers=true;ConstantHost f(h);
 FrameSurvey::BoundConstantBuffer out;FrameSurvey::ConstantBufferDiagnostic diagnostic;
 ComPtr<ID3D12Resource> untracked;D3D12_HEAP_PROPERTIES hp{};hp.Type=D3D12_HEAP_TYPE_UPLOAD;
 auto desc=CD3DX12_RESOURCE_DESC::Buffer(1536);
 hr(h.dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&untracked)));
 auto* table=f.root(true);f.table(table);f.write(0,untracked.Get(),256,1280);f.copy(7,true,0);
 const auto raw=f.cpu(7,true).ptr,va=untracked->GetGPUVirtualAddress()+256;
 need(FrameSurvey::gViews.contains(raw)&&!FrameSurvey::gViews.at(raw).object&&FrameSurvey::gViews.at(raw).rootVa==va&&FrameSurvey::gViews.at(raw).constantBytes==1280,"untracked native CBV declaration preserves exact VA/size through descriptor copy without inventing an owner");
 need(!FrameSurvey::ResolveComputeConstantBuffer(h.list.Get(),6,0,1216,out,&diagnostic)&&!out.resource&&std::string(diagnostic.reason)=="CBV GPU address has no tracked buffer","missing creation produces specific untracked-VA failure and no borrowed resource");
 need(diagnostic.table&&diagnostic.rootParameter==3&&diagnostic.descriptorCpu==raw&&diagnostic.address==va&&diagnostic.declaredBytes==1280&&diagnostic.intervalMatches==0,"failure diagnostic contains exact mixed-table parameter, copied slot, VA and minimum-safe CBV size");
 FrameSurvey::ResourceCreatedWithLayout(untracked.Get(),D3D12_BARRIER_LAYOUT_UNDEFINED);
 need(!FrameSurvey::gResources.at(untracked.Get()).initialKnown,"enhanced layout observer never fabricates legacy COMMON state");
 need(!FrameSurvey::ResolveComputeConstantBuffer(h.list.Get(),6,0,1216,out,&diagnostic)&&!out.resource&&std::string(diagnostic.reason)=="Consumer CBV buffer was not tracked at descriptor creation","late resource metadata does not retroactively accept an unproven old CBV descriptor");
 f.write(0,untracked.Get(),256,1280);f.copy(7,true,0);
 need(FrameSurvey::ResolveComputeConstantBuffer(h.list.Get(),6,0,1216,out,&diagnostic)&&out.resource==untracked.Get()&&out.address==va&&out.size==1280&&out.resourceGeneration,"re-observed native descriptor resolves exact enhanced-created buffer generation without lowering1216 minimum");
 need(FrameSurvey::ValidateBorrowedConstantBuffer(out),"live copied native CBV token retains normal heap/owner/generation validation");
 f.write(7,untracked.Get(),256,1024,true);
 need(!FrameSurvey::ResolveComputeConstantBuffer(h.list.Get(),6,0,1216,out,&diagnostic)&&!out.resource&&diagnostic.declaredBytes==1024&&diagnostic.remainingBytes==1280&&std::string(diagnostic.reason)=="CBV byte range does not cover the requested field","too-short1024 descriptor remains rejected with exact declared/remaining bytes");
 f.write(7,untracked.Get(),256,1280,true);auto* alias=f.buffer(4096);auto& record=FrameSurvey::gResources.at(alias);const auto oldVA=record.va;
 FrameSurvey::gBufferAddresses.Erase(oldVA,record.id);record.va=untracked->GetGPUVirtualAddress();FrameSurvey::gBufferAddresses.Insert(record.va,record.desc.Width,record.id,alias);
 need(!FrameSurvey::ResolveComputeConstantBuffer(h.list.Get(),6,0,1216,out,&diagnostic)&&!out.resource&&diagnostic.intervalMatches==2&&std::string(diagnostic.reason)=="CBV GPU address overlaps live buffers","live overlapping buffers remain ambiguous and are distinguished from missing creation");
 FrameSurvey::gBufferAddresses.Erase(record.va,record.id);record.va=oldVA;FrameSurvey::gBufferAddresses.Insert(oldVA,record.desc.Width,record.id,alias);
 auto* unbounded=f.root(true,6,0,D3D12_SHADER_VISIBILITY_ALL,{{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,UINT_MAX,0,0,0}});f.table(unbounded);f.write(6,untracked.Get(),256,1280,true);
 need(FrameSurvey::ResolveComputeConstantBuffer(h.list.Get(),6,0,1216,out,&diagnostic)&&out.resource==untracked.Get()&&out.descriptor.ptr==f.gpu.ptr+6*f.stride,"actual unbounded CBV table resolves its genuinely populated unique b6 slot with1280 declared bytes");
 auto captured=out;FrameSurvey::Released(untracked.Get());
 need(!FrameSurvey::ValidateBorrowedConstantBuffer(captured),"unbounded native CBV token cannot survive resource generation removal");
 need(!FrameSurvey::ResolveComputeConstantBuffer(h.list.Get(),6,0,1216,out,&diagnostic)&&!out.resource&&std::string(diagnostic.reason)=="Consumer CBV descriptor slot is missing or stale","released CBV slot reports descriptor invalidation instead of guessing another buffer");
 FrameSurvey::Released(alias);hr(h.list->Close());h.execute();h.reset();h.errors();FrameSurvey::Shutdown();
 return {{"untracked_declaration_preserved",true},{"untracked_owner_not_accepted",true},{"enhanced_state_not_guessed",true},{"populated_unbounded_b6",true},{"minimum_bytes",1216},{"native_cbv_declared_bytes",1280}};
}
J nativeBindingTests(Host& h) {
 FrameSurvey::Shutdown();gNrdBridgeDeviceWrappers=true;ConstantHost f(h);
 ComPtr<ID3D12Resource> a,b;D3D12_HEAP_PROPERTIES hp{};hp.Type=D3D12_HEAP_TYPE_UPLOAD;
 const auto desc=CD3DX12_RESOURCE_DESC::Buffer(4096);
 hr(h.dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&a)));
 hr(h.dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&b)));
 const auto av=a->GetGPUVirtualAddress(),bv=b->GetGPUVirtualAddress();
 FrameSurvey::BoundConstantBinding out;FrameSurvey::BoundConstantBuffer strict;FrameSurvey::ConstantBufferDiagnostic diagnostic;
 auto resolve=[&](UINT reg=6,UINT space=0){return FrameSurvey::ResolveComputeConstantBinding(h.list.Get(),reg,space,out,&diagnostic);};
 auto* direct=f.root();f.direct(direct,av+256);
 need(FrameSurvey::gResources.empty()&&FrameSurvey::gViews.empty(),"native fixture starts with no source-buffer or descriptor records");
 need(!f.resolve(strict)&&!strict.resource,"strict registry API still rejects an unregistered root-CBV source");
 need(resolve()&&out.root==direct&&out.rootParameter==0&&out.address==av+256&&!out.descriptorHeap&&!out.descriptor.ptr,"native root b6 resolves exact GPUVA without registering or retaining its source");
 const auto rootBinding=out;
 need(!resolve(7)&&!out.root&&!out.address&&!resolve(6,1),"native root register/space mismatch clears every result field");
 FrameSurvey::RootView(h.list.Get(),false,0,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,av+1);
 need(!resolve(),"native root lookup rejects misaligned GPUVA without a source-buffer query");
 FrameSurvey::RootView(h.list.Get(),false,0,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,0);need(!resolve(),"native root lookup rejects zero GPUVA");
 FrameSurvey::RootView(h.list.Get(),false,0,D3D12_DESCRIPTOR_RANGE_TYPE_SRV,av+256);need(!resolve(),"native root lookup rejects a mismatched argument kind");
 f.direct(direct,av+256);f.trackSnapshot(direct,av+256);FrameSurvey::ComputeBindings snapshot;
 need(GetComputeBindingsForBridge(h.list.Get(),snapshot)&&FrameSurvey::ValidateComputeConstantBinding(snapshot,6,0,rootBinding),"production restore getter validates the exact unregistered root-CBV binding");
 auto noHeaps=snapshot;noHeaps.heaps.clear();
 need(FrameSurvey::ResolveComputeConstantBinding(noHeaps,6,0,out)&&out.address==av+256,"direct native root CBV does not require a descriptor heap");
 auto changed=snapshot;changed.views[0].address=bv;
 need(!FrameSurvey::ValidateComputeConstantBinding(changed,6,0,rootBinding),"rebound root GPUVA invalidates the previous native token");
 changed=snapshot;changed.views.push_back(changed.views[0]);
 need(!FrameSurvey::ResolveComputeConstantBinding(changed,6,0,out)&&!out.root,"duplicated native root-CBV arguments fail closed");
 auto* replacementRoot=f.root(false,6,0,D3D12_SHADER_VISIBILITY_ALL,{},true,false,D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT);
 need(replacementRoot!=direct,"different native root flags prove a distinct root object before stale-token rejection");changed=snapshot;changed.root=replacementRoot;
 need(!FrameSurvey::ValidateComputeConstantBinding(changed,6,0,rootBinding),"same-shaped replacement root does not validate a token from the old root");
 FrameSurvey::SetBindingWindow(false);
 need(!resolve(),"initial native cmd-list lookup closes with the binding window");
 need(FrameSurvey::ResolveComputeConstantBinding(snapshot,6,0,out)&&out.address==av+256&&FrameSurvey::ValidateComputeConstantBinding(snapshot,6,0,rootBinding),"explicit current getter snapshot remains valid after mirror-window closure");
 {FrameSurvey::ScopedInternal internal;
  need(!resolve()&&FrameSurvey::ResolveComputeConstantBinding(snapshot,6,0,out)&&out.address==av+256,"window-independent native snapshot is usable under the real internal injection scope");}
 FrameSurvey::SetBindingWindow(true);need(FrameSurvey::SeedComputeBindings(h.list.Get(),snapshot)&&resolve(),"native initial lookup recovers only from a fresh exact seed");
 auto* constants=f.root(false,6,0,D3D12_SHADER_VISIBILITY_ALL,{},true,true);f.bind(constants);need(!resolve(),"root constants do not become a native CBV address");
 auto* pixel=f.root(false,6,0,D3D12_SHADER_VISIBILITY_PIXEL);f.direct(pixel,av,false);need(!resolve(),"PIXEL-only root CBV is ineligible for native compute capture");
 auto* unknown=f.root(false,21,0,D3D12_SHADER_VISIBILITY_ALL,{},false);f.direct(unknown,av);need(!resolve(21),"missing native root layout is not guessed from a root argument");
 auto* table=f.root(true);f.table(table);
 D3D12_CONSTANT_BUFFER_VIEW_DESC native{av+256,1280};h.dev->CreateConstantBufferView(&native,f.cpu(7,true));
 need(FrameSurvey::gResources.empty()&&FrameSurvey::gViews.empty(),"native mixed table has no resource records and no CBV slot metadata");
 need(!f.resolve(strict)&&!strict.resource,"strict table API still rejects the same unregistered/unobserved CBV slot");
 need(resolve()&&out.root==table&&out.rootParameter==3&&!out.address&&out.descriptorHeap==f.heap.Get()&&out.descriptor.ptr==f.gpu.ptr+7*f.stride&&out.tableBase==f.gpu.ptr,"native mixed APPEND table resolves b6's exact slot without reading its descriptor owner or VA");
 const auto tableBinding=out;f.trackSnapshot(table,0,true);need(GetComputeBindingsForBridge(h.list.Get(),snapshot),"production getter captures the native mixed-table root and heap");
 need(FrameSurvey::ValidateComputeConstantBinding(snapshot,6,0,tableBinding),"native table token validates the exact current getter binding");
 native={bv+256,1280};h.dev->CreateConstantBufferView(&native,f.cpu(7,true));
 need(FrameSurvey::gViews.empty()&&FrameSurvey::ValidateComputeConstantBinding(snapshot,6,0,tableBinding),"volatile descriptor replacement preserves the slot token without inventing source identity");
 const ULONG refs=a->AddRef();a->Release();
 need(resolve()&&FrameSurvey::ValidateComputeConstantBinding(snapshot,6,0,tableBinding),"native resolver is still independent of replaced source-buffer identity");
 const ULONG after=a->AddRef();a->Release();need(refs==after,"native binding queries do not AddRef unregistered title buffers");
 changed=snapshot;changed.tables.erase(std::remove_if(changed.tables.begin(),changed.tables.end(),[](const auto& t){return t.first==3;}),changed.tables.end());
 need(!FrameSurvey::ValidateComputeConstantBinding(changed,6,0,tableBinding),"omitted current CBV table cannot validate an old native slot");
 changed=snapshot;for(auto& t:changed.tables)if(t.first==3)t.second.ptr+=f.stride;
 need(!FrameSurvey::ValidateComputeConstantBinding(changed,6,0,tableBinding),"changed current table base invalidates the exact old native slot");
 changed=snapshot;changed.heaps.clear();need(!FrameSurvey::ResolveComputeConstantBinding(changed,6,0,out),"native table lookup requires its currently bound shader-visible heap");
 changed=snapshot;changed.heaps={f.cpuHeap.Get()};need(!FrameSurvey::ResolveComputeConstantBinding(changed,6,0,out),"CPU-only heap cannot prove a native GPU table binding");
 changed=snapshot;changed.heaps={f.heap.Get(),f.heap.Get()};need(!FrameSurvey::ResolveComputeConstantBinding(changed,6,0,out),"duplicated matching native heaps are ambiguous");
 changed=snapshot;changed.heaps={f.heap.Get(),f.cpuHeap.Get(),f.heap.Get()};need(!FrameSurvey::ResolveComputeConstantBinding(changed,6,0,out),"more than two heaps is outside native command-list binding shape");
 FrameSurvey::Table(h.list.Get(),false,3,{f.gpu.ptr+1});need(!resolve(),"unaligned native table base fails before any descriptor or buffer read");
 FrameSurvey::Table(h.list.Get(),false,3,{f.gpu.ptr+126*f.stride});need(!resolve(),"native b6 slot beyond the current heap is rejected");
 auto* tableSpace=f.root(true,6,3);f.table(tableSpace);need(!resolve()&&resolve(6,3),"native table lookup preserves its exact nonzero register space");
 auto* tablePixel=f.root(true,6,0,D3D12_SHADER_VISIBILITY_PIXEL);f.bind(tablePixel);FrameSurvey::Table(h.list.Get(),false,3,f.gpu);need(!resolve(),"PIXEL-only native table is ineligible for compute capture");
 auto* overlap=f.root(true,6,0,D3D12_SHADER_VISIBILITY_ALL,{{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,4,4,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,4,10,0,2}});f.table(overlap);need(!resolve(),"overlapping native table ranges cannot uniquely map b6");
 auto* unbounded=f.root(true,6,0,D3D12_SHADER_VISIBILITY_ALL,{{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,UINT_MAX,0,0,0}});f.table(unbounded);h.dev->CreateConstantBufferView(&native,f.cpu(6,true));
 need(resolve()&&out.descriptor.ptr==f.gpu.ptr+6*f.stride,"unbounded native CBV range resolves its exact populated in-heap b6 slot without a registry scan");
 f.table(table);f.trackSnapshot(table,0,true);need(GetComputeBindingsForBridge(h.list.Get(),snapshot),"fresh mixed-table getter snapshot is available before native lifetime tests");
 FrameSurvey::gMetadataHealthy.store(false);need(!FrameSurvey::ResolveComputeConstantBinding(snapshot,6,0,out)&&!out.root&&!FrameSurvey::ValidateComputeConstantBinding(snapshot,6,0,tableBinding),"unhealthy root/heap metadata rejects native resolution and validation");FrameSurvey::gMetadataHealthy.store(true);
 FrameSurvey::Reset(h.list.Get(),nullptr);need(!resolve(),"scene/list Reset clears the initial native mirror binding");
 bridgeComputeRoots.erase(h.list.Get());rootStates.erase(h.list.Get());descriptorHeaps.erase(h.list.Get());
 need(!GetComputeBindingsForBridge(h.list.Get(),changed)&&!changed.root&&!FrameSurvey::ValidateComputeConstantBinding(changed,6,0,tableBinding),"fresh empty restore getter after Reset cannot republish the previous native binding");
 FrameSurvey::Released(table);need(!FrameSurvey::ValidateComputeConstantBinding(snapshot,6,0,tableBinding),"root metadata Release invalidates a retained native table token without touching its source");
 f.table(tableSpace);f.trackSnapshot(tableSpace,0,true);need(GetComputeBindingsForBridge(h.list.Get(),snapshot)&&FrameSurvey::ResolveComputeConstantBinding(snapshot,6,3,out),"replacement native root validates before heap metadata retirement");
 const auto beforeHeapRelease=out;FrameSurvey::Released(f.heap.Get());
 need(!FrameSurvey::ValidateComputeConstantBinding(snapshot,6,3,beforeHeapRelease),"heap metadata Release invalidates the exact native table token");
 need(FrameSurvey::gResources.empty()&&FrameSurvey::gViews.empty(),"all native-binding checks leave source resource and CBV registries empty");
 hr(h.list->Close());h.execute();h.reset();h.errors();FrameSurvey::Shutdown();
 return {{"source_resource_records",0},{"source_descriptor_records",0},{"root_gpuva",true},{"mixed_native_table",true},{"post_record_descriptor_identity_ignored",true},{"window_independent_snapshot",true},{"contains_title_binary",false}};
}
int main(int argc,char** argv) try {
 need(argc==2,"output path"); g_dllPath=std::filesystem::path(argv[1])/"fixture.dll";
 Host host; auto result=constantTests(host);const auto originalChecks=checks;
 result["original_checks_passed"]=originalChecks;result["activation_diagnostics"]=diagnosticTests(host);
 result["activation_diagnostic_checks"]=checks-originalChecks;const auto strictChecks=checks;
 result["strict_registry_checks_passed"]=strictChecks;result["native_bindings"]=nativeBindingTests(host);
 result["native_binding_checks_passed"]=checks-strictChecks;result["checks_passed"]=checks;
 std::ofstream(std::filesystem::path(argv[1])/"host-result.json")<<result.dump(2)<<'\n'; std::cout<<result.dump()<<'\n'; return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
'''

def run():
    output=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT','F:/FSRD/sol_batch/12a-discovery/tests/constant-buffers'))
    output.mkdir(parents=True,exist_ok=True)
    stubs=output/'stubs'
    for folder in ('proxies','inputs'):
        (stubs/folder).mkdir(parents=True,exist_ok=True)
    (stubs/'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n#include <shared_mutex>\n#define LOG_INFO(...) ((void)0)\n#define LOG_ERROR(...) ((void)0)\n')
    (stubs/'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\nnamespace Util { inline std::filesystem::path DllPath() { return g_dllPath; } }\n')
    (stubs/'inputs/NVNGX_DLSS.h').write_text('#pragma once\n#include <nvsdk_ngx.h>\n')
    (stubs/'proxies/D3D12_Proxy.h').write_text('#pragma once\n#include <d3d12.h>\nnamespace D3d12Proxy { inline auto D3D12CreateVersionedRootSignatureDeserializer_() { return &D3D12CreateVersionedRootSignatureDeserializer; } inline auto D3D12SerializeVersionedRootSignature_() { return &D3D12SerializeVersionedRootSignature; } }\n')
    hooks=(ROOT/'OptiScaler/hooks/D3D12_Hooks.cpp').read_text()
    state=hooks[hooks.index('enum class RootEntryType'):hooks.index('enum class SignatureEntryType')]
    getter=function(hooks,'bool D3D12Hooks::GetComputeBindingsForBridge(').replace('D3D12Hooks::','')
    restrack=(ROOT/'OptiScaler/resource_tracking/ResTrack_Dx12.cpp').read_text()
    cbvhook=function(restrack,'void ResTrack_Dx12::hkSurveyCreateConstantBufferView(').replace('ResTrack_Dx12::','')
    text=(survey_fixture.CPP.split('// GetStatus()')[0]+register_fixture.CPP.split('J registerTests')[0]+CPP)
    text=text.replace('__TRACE__',(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp').as_posix()).replace('__SURVEY__',(ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').as_posix())
    text=text.replace('__STATE__',state).replace('__GETTER__',getter).replace('__CBVHOOK__',cbvhook)
    source=output/'fixture.cpp'; source.write_text(text,encoding='utf-8'); exe=output/'fixture.exe'
    compile_cpp(source,exe,('d3d12.lib','dxgi.lib','dxguid.lib','d3dcompiler.lib','bcrypt.lib','user32.lib','psapi.lib',str(ROOT/'OptiScaler/library/detours/detours.lib')),
        (stubs,ROOT/'OptiScaler',ROOT/'OptiScaler/include',ROOT/'external/streamline', ROOT/'external/nlohmann',ROOT/'external/nvngx_dlss_sdk',ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
    subprocess.run([str(exe),str(output)],check=True,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    result=json.loads((output/'host-result.json').read_text()); report=Path(os.environ.get('FSRD_TASK_REPORT_DIR','E:/FSRD/sol_batch/12a-discovery')); report.mkdir(parents=True,exist_ok=True)
    (report/'constant-buffers-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':
    run()
