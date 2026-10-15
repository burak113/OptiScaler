// Actual research capture class/CSO; native-root restoration is the caller's job.
#include "raw_fixture_context.h"
#include "sentinel_shader.h"
#include <unordered_set>

template<class T> static ULONG refs(T* value)
{ const auto count=value->AddRef();value->Release();return count; }
static std::vector<char> bytes(const void* source,size_t count)
{const auto* first=static_cast<const char*>(source);return {first,first+count};}
static ComPtr<ID3D12Resource> uavBuffer(Fixture& f,uint64_t count)
{
 D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;desc.Width=count;
 desc.Height=desc.DepthOrArraySize=desc.MipLevels=1;desc.SampleDesc.Count=1;desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
 D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;ComPtr<ID3D12Resource> result;
 hr(f.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_COMMON,nullptr,IID_PPV_ARGS(&result)));
 Fixture::Transition(f.list.Get(),result.Get(),D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);return result;
}
static void fill(ID3D12Resource* resource,const void* data,size_t count)
{void* mapped=nullptr;D3D12_RANGE none{0,0};hr(resource->Map(0,&none,&mapped));memcpy(mapped,data,count);resource->Unmap(0,nullptr);}
static ComPtr<ID3D12Resource> readBuffer(Fixture& f,ID3D12Resource* source,uint64_t count,D3D12_RESOURCE_STATES state)
{
 auto result=f.Buffer(count,D3D12_HEAP_TYPE_READBACK);Fixture::Transition(f.list.Get(),source,state,D3D12_RESOURCE_STATE_COPY_SOURCE);
 f.list->CopyBufferRegion(result.Get(),0,source,0,count);Fixture::Transition(f.list.Get(),source,D3D12_RESOURCE_STATE_COPY_SOURCE,state);return result;
}
static std::vector<char> read(ID3D12Resource* resource,size_t count)
{void* mapped=nullptr;D3D12_RANGE range{0,count};hr(resource->Map(0,&range,&mapped));auto result=bytes(mapped,count);D3D12_RANGE none{0,0};resource->Unmap(0,&none);return result;}
struct NativeFixture
{
 Fixture& f;uint32_t width=0,height=0;uint64_t count=0;UINT stride=0;
 ComPtr<ID3D12Resource> source,other,nr,marker,constants;
 ComPtr<ID3D12DescriptorHeap> heap;ComPtr<ID3D12RootSignature> root;ComPtr<ID3D12PipelineState> pso;
 explicit NativeFixture(Fixture& owner,const fs::path& path):f(owner)
 {
  std::ifstream size(path/"size.txt");size>>width>>height;need(bool(size)&&width&&height,"input extent");count=uint64_t(width)*height*4;
  auto first=load(path/"normal.bin"),second=load(path/"other.bin");
  source=f.Texture(width,height,DXGI_FORMAT_R8G8B8A8_UNORM,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&first);
  other=f.Texture(width,height,DXGI_FORMAT_R8G8B8A8_UNORM,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&second);
  gRawBorrowed.insert(source.Get());gRawBorrowed.insert(other.Get());
  nr=f.Texture(width,height,DXGI_FORMAT_R10G10B10A2_UNORM,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);marker=uavBuffer(f,count);
  constants=f.Buffer(256,D3D12_HEAP_TYPE_UPLOAD);std::array<uint32_t,64> magic{};magic[0]=0x13579bdf;fill(constants.Get(),magic.data(),256);
  D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;hd.NumDescriptors=11;
  hr(f.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&heap)));stride=f.device->GetDescriptorHandleIncrementSize(hd.Type);
  auto cpu=heap->GetCPUDescriptorHandleForHeapStart();
  D3D12_SHADER_RESOURCE_VIEW_DESC srv{};srv.Format=DXGI_FORMAT_R8G8B8A8_UNORM;srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;srv.Texture2D.MipLevels=1;
  for(UINT i=0;i<6;++i){f.device->CreateShaderResourceView(i==5?source.Get():nullptr,&srv,cpu);cpu.ptr+=stride;}
  D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};uav.Format=DXGI_FORMAT_R10G10B10A2_UNORM;uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
  for(UINT i=0;i<5;++i){f.device->CreateUnorderedAccessView(i==4?nr.Get():nullptr,nullptr,&uav,cpu);cpu.ptr+=stride;}
  hr(f.device->CreateRootSignature(0,SentinelShader,sizeof(SentinelShader),IID_PPV_ARGS(&root)));
  D3D12_COMPUTE_PIPELINE_STATE_DESC pd{};pd.pRootSignature=root.Get();pd.CS={SentinelShader,sizeof(SentinelShader)};hr(f.device->CreateComputePipelineState(&pd,IID_PPV_ARGS(&pso)));
 }
 void overwrite()
 {
  D3D12_SHADER_RESOURCE_VIEW_DESC srv{};srv.Format=DXGI_FORMAT_R8G8B8A8_UNORM;srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;srv.Texture2D.MipLevels=1;
  auto cpu=heap->GetCPUDescriptorHandleForHeapStart();cpu.ptr+=5*stride;f.device->CreateShaderResourceView(other.Get(),&srv,cpu);
 }
 NrdBridge::NativeRawRoughnessBinding binding() const
 {
  NrdBridge::NativeRawRoughnessBinding b{};b.nativeHeap=heap.Get();b.descriptor=heap->GetGPUDescriptorHandleForHeapStart();b.descriptor.ptr+=uint64_t(5)*stride;
  b.shaderSha256="3e09f2e0d948f77869a0628524c14463e1fdb06fcfb78aa60fc102c78fb0d5ed";
  b.rootSha256="bcb5f3454f596992f694f54ddb53e0f6b0ac7a9d976e8a49d1fc9ddab6a6eb70";
  b.rootParameter=1;b.descriptorOffset=5;b.shaderRegister=5;b.registerSpace=0;b.viewFormat=DXGI_FORMAT_R8G8B8A8_UNORM;b.subresource=0;b.description=source->GetDesc();return b;
 }
 void restore()
 {
  f.list->SetPipelineState(pso.Get());f.list->SetComputeRootSignature(root.Get());ID3D12DescriptorHeap* heaps[]={heap.Get()};f.list->SetDescriptorHeaps(1,heaps);
  f.list->SetComputeRoot32BitConstant(0,0x12345,0);f.list->SetComputeRootDescriptorTable(1,heap->GetGPUDescriptorHandleForHeapStart());
  f.list->SetComputeRootConstantBufferView(2,constants->GetGPUVirtualAddress());f.list->SetComputeRootUnorderedAccessView(3,marker->GetGPUVirtualAddress());f.list->SetComputeRoot32BitConstant(4,0x45678,0);
  auto table=heap->GetGPUDescriptorHandleForHeapStart();table.ptr+=uint64_t(6)*stride;f.list->SetComputeRootDescriptorTable(5,table);
 }
 void dispatch(){f.list->Dispatch((width+7)/8,(height+7)/8,1);}
};
using Capture=NrdBridge::NativeRawRoughnessCapture;
static void noWork(Fixture& f,Capture& capture,const NrdBridge::NativeRawRoughnessBinding& binding,const char* reason)
{
 const auto commands=gRawCommands,allocations=gRawAllocations;const auto owned=capture.OwnedAuxiliaryBytes();Capture::SnapshotLease lease;std::string error;
 need(!capture.Capture(f.list.Get(),binding,lease,error),reason);need(!lease&&!error.empty(),"rejection clears ticket with an error");
 need(gRawCommands==commands&&gRawAllocations==allocations&&capture.OwnedAuxiliaryBytes()==owned,"bad metadata records no GPU work and allocates no private slot");
}
static void cases(const fs::path& directory)
{
 Fixture f(true);std::string error;Capture capture;
 need(capture.OwnedAuxiliaryBytes()==0,"OFF/cold object has no allocations");
 need(!capture.Initialize(nullptr,1,1,error)&&!capture.Initialize(f.device.Get(),0,1,error)&&!capture.Initialize(f.device.Get(),16385,1,error),"invalid initialization is rejected");
 for(const auto name:{"codes","positive"}){
  uint64_t warm=0,allocations=0;ID3D12Resource* warmSlot=nullptr;
  for(bool late:{false,true}){
   const auto path=directory/name;NativeFixture r(f,path);need(capture.Initialize(f.device.Get(),r.width,r.height,error),error.c_str());
   if(!late)need(capture.OwnedAuxiliaryBytes()==0,"new extent has no snapshot before capture");
   r.restore();const auto sourceRefs=refs(r.source.Get()),otherRefs=refs(r.other.Get()),heapRefs=refs(r.heap.Get());Capture::SnapshotLease lease;
   need(capture.Capture(f.list.Get(),r.binding(),lease,error),error.c_str());auto* raw=Capture::Resource(lease);
   need(raw&&Capture::Width(lease)==r.width&&Capture::Height(lease)==r.height,"private buffer and exact extent exposed");
   need(raw->GetDesc().Dimension==D3D12_RESOURCE_DIMENSION_BUFFER&&raw->GetDesc().Width==r.count,"exact four-byte-per-pixel snapshot");
   need(refs(r.source.Get())==sourceRefs&&refs(r.other.Get())==otherRefs&&refs(r.heap.Get())==heapRefs,"capture owns neither source texture nor native heap");
   if(late){need(raw==warmSlot&&gRawAllocations==allocations&&capture.OwnedAuxiliaryBytes()==warm,"completed slot reuses buffer with no allocation");r.overwrite();}
   r.restore();r.dispatch();auto rb=readBuffer(f,raw,r.count,D3D12_RESOURCE_STATE_COMMON);
   auto markers=readBuffer(f,r.marker.Get(),r.count,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
   auto normals=f.Snapshot(r.nr.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS),source=f.Snapshot(r.source.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),other=f.Snapshot(r.other.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
   f.Submit();const std::string route=late?"late":"normal";
   save(path/(route+"-raw.bin"),read(rb.Get(),size_t(r.count)));save(path/(route+"-marker.bin"),read(markers.Get(),size_t(r.count)));save(path/(route+"-native.bin"),normals.Data());
   save(path/"source-after.bin",source.Data());save(path/"other-after.bin",other.Data());
   warm=capture.OwnedAuxiliaryBytes();allocations=gRawAllocations;warmSlot=raw;lease.reset();f.Reset();gRawBorrowed.clear();
  }
 }
 NativeFixture r(f,directory/"codes");Capture negative;auto b=r.binding();noWork(f,negative,b,"uninitialized capture fails");need(negative.Initialize(f.device.Get(),r.width,r.height,error),error.c_str());
 Capture::SnapshotLease absent;const auto nullCommands=gRawCommands;
 need(!negative.Capture(nullptr,b,absent,error)&&!absent&&gRawCommands==nullCommands,"null command list records no work");
 need(!Capture::Resource(absent)&&!Capture::Width(absent)&&!Capture::Height(absent),"empty ticket exposes no private resource/extent");
 using Mutator=std::function<void(NrdBridge::NativeRawRoughnessBinding&)>;
 const std::vector<Mutator> invalid={[](auto& v){v.nativeHeap=nullptr;},[](auto& v){v.descriptor.ptr=0;},[](auto& v){v.shaderSha256="unknown";},[](auto& v){v.rootSha256="unknown";},
  [](auto& v){v.rootParameter=0;},[](auto& v){v.descriptorOffset=4;},[](auto& v){v.shaderRegister=4;},[](auto& v){v.registerSpace=1;},[](auto& v){v.kind=D3D12_DESCRIPTOR_RANGE_TYPE_UAV;},
  [](auto& v){v.viewFormat=DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;},[](auto& v){v.subresource=1;},[](auto& v){v.description.MipLevels=2;},[](auto& v){v.description.DepthOrArraySize=2;},
  [](auto& v){v.description.SampleDesc.Count=2;},[](auto& v){++v.description.Width;},[](auto& v){++v.description.Height;},[](auto& v){v.description.Format=DXGI_FORMAT_R10G10B10A2_UNORM;},
  [](auto& v){v.description.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE3D;},[](auto& v){v.description.Flags|=D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE;},[](auto& v){++v.descriptor.ptr;},
  [](auto& v){v.descriptor.ptr=1;},[](auto& v){v.descriptor.ptr=UINT64_MAX;}};
 for(const auto& mutate:invalid){auto bad=b;mutate(bad);noWork(f,negative,bad,"invalid exact t5/profile/view/descriptor rejected");}
 for(const auto type:{D3D12_DESCRIPTOR_HEAP_TYPE_RTV,D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV}){
  D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=type;hd.NumDescriptors=1;hd.Flags=type==D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER?D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE:D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
  ComPtr<ID3D12DescriptorHeap> heap;hr(f.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&heap)));auto bad=b;bad.nativeHeap=heap.Get();noWork(f,negative,bad,"wrong heap type or visibility rejected");
 }
 // D3D12CreateDevice returns the same device for the same adapter. Select a
 // different adapter explicitly so this is a real device-identity negative.
 ComPtr<IDXGIFactory4> factory;hr(CreateDXGIFactory2(0,IID_PPV_ARGS(&factory)));ComPtr<IDXGIAdapter> warp;hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)));
 ComPtr<ID3D12Device> different;hr(D3D12CreateDevice(warp.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&different)));
 ComPtr<IUnknown> expectedIdentity,differentIdentity;hr(f.device.As(&expectedIdentity));hr(different.As(&differentIdentity));need(expectedIdentity.Get()!=differentIdentity.Get(),"foreign-device test has genuinely different canonical devices");
 D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;hd.NumDescriptors=1;hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
 ComPtr<ID3D12DescriptorHeap> foreign;hr(different->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&foreign)));auto bad=b;bad.nativeHeap=foreign.Get();bad.descriptor=foreign->GetGPUDescriptorHandleForHeapStart();noWork(f,negative,bad,"foreign-device native heap rejected");
 r.restore();RecordedComputeLease::SetHooksAvailable(false,false);const auto before=gRawCommands;Capture::SnapshotLease failed;
 need(!negative.Capture(f.list.Get(),b,failed,error)&&!failed&&gRawCommands==before,"failed actual recording lease records zero GPU commands");
 const auto allocated=gRawAllocations;RecordedComputeLease::SetHooksAvailable(true,true);need(negative.Capture(f.list.Get(),b,failed,error),error.c_str());need(gRawAllocations==allocated,"failed-lease cold slot is safely reused");
 r.restore();r.dispatch();f.Submit();failed.reset();f.Reset();gRawBorrowed.clear();
 // Warming32 buffers does not pin31 idle buffers behind one old-generation
 // snapshot after resize. Count only private metadata construction/destruction.
 const auto beforeResize=gRawLiveSlots;
 {
  Capture resize;NativeFixture old(f,directory/"codes");need(resize.Initialize(f.device.Get(),old.width,old.height,error),error.c_str());
  for(unsigned i=0;i<32;++i){Capture::SnapshotLease warm;need(resize.Capture(f.list.Get(),old.binding(),warm,error),error.c_str());}
  f.Submit();f.Reset();need(gRawLiveSlots==beforeResize+32,"warm32 buffers remain reusable");
  const auto familyBytes=resize.OwnedAuxiliaryBytes();need(familyBytes&&familyBytes%32==0,"family charges all32 allocated warm buffers");const auto oldBytes=familyBytes/32;
  Capture::SnapshotLease pending;need(resize.Capture(f.list.Get(),old.binding(),pending,error),error.c_str());pending.reset();
  NativeFixture fresh(f,directory/"positive");need(resize.Initialize(f.device.Get(),fresh.width,fresh.height,error),error.c_str());
  need(gRawLiveSlots==beforeResize+1,"resize retires idle31 private buffers outside locks");
  need(resize.OwnedAuxiliaryBytes()==oldBytes,"current helper includes the retained old-generation buffer bytes");
  Capture::SnapshotLease current;need(resize.Capture(f.list.Get(),fresh.binding(),current,error),error.c_str());
  const auto currentDesc=Capture::Resource(current)->GetDesc();const auto currentBytes=f.device->GetResourceAllocationInfo(0,1,&currentDesc).SizeInBytes;
  need(resize.OwnedAuxiliaryBytes()==oldBytes+currentBytes,"family includes both extent generations");current.reset();
  f.Submit();f.Reset();need(gRawLiveSlots==beforeResize+1&&resize.OwnedAuxiliaryBytes()==currentBytes,"completed old generation releases its last buffer and exact bytes");gRawBorrowed.clear();
 }
 need(gRawLiveSlots==beforeResize,"new generation idle buffer dies with its owner");
 // Keep32 distinct snapshots on one actual recording. The33rd cannot issue GPU
 // work; dropping every CPU ticket/context must preserve all32 through GPU+Reset.
 auto owner=std::make_unique<Capture>();NativeFixture retained(f,directory/"codes");need(owner->Initialize(f.device.Get(),retained.width,retained.height,error),error.c_str());
 retained.restore();const auto retainedSourceRefs=refs(retained.source.Get()),retainedHeapRefs=refs(retained.heap.Get());
 std::vector<std::weak_ptr<void>> weak;std::unordered_set<ID3D12Resource*> unique;ID3D12Resource* first=nullptr;
 for(unsigned i=0;i<32;++i){Capture::SnapshotLease ticket;need(owner->Capture(f.list.Get(),retained.binding(),ticket,error),error.c_str());auto* raw=Capture::Resource(ticket);if(!i)first=raw;need(unique.insert(raw).second,"in-flight slot is never overwritten");weak.emplace_back(ticket);}
 noWork(f,*owner,retained.binding(),"33rd unretired slot rejected");
 need(refs(retained.source.Get())==retainedSourceRefs&&refs(retained.heap.Get())==retainedHeapRefs,"32 retained snapshots add no title COM owner");
 NativeFixture resized(f,directory/"positive");need(owner->Initialize(f.device.Get(),resized.width,resized.height,error),error.c_str());
 noWork(f,*owner,resized.binding(),"new extent cannot bypass total32 allocated-buffer family budget");
 owner.reset();for(const auto& w:weak)need(!w.expired(),"cancel retains snapshot before submit");
 retained.restore();auto canceled=readBuffer(f,first,retained.count,D3D12_RESOURCE_STATE_COMMON);f.Submit();save(directory/"canceled-raw.bin",read(canceled.Get(),size_t(retained.count)));
 for(const auto& w:weak)need(!w.expired(),"GPU completion retains still-executable closed recording");f.Reset();for(const auto& w:weak)need(w.expired(),"successful Reset retires the actual private lease");
 gRawBorrowed.clear();f.Validate();std::cout<<"checks="<<checks<<" invalid_profile_cases="<<invalid.size()<<" max_slots=32 capture_allocations="<<gRawAllocations<<" audited_barriers="<<gRawBarriers<<" native_heap_sets="<<gRawHeapSets<<"\n";
}
static void timing(const fs::path& directory)
{
 Fixture f(false);std::string error;
 for(const auto name:{"1505x847","2560x1440"}){
  NativeFixture r(f,directory/name);Capture capture;need(capture.Initialize(f.device.Get(),r.width,r.height,error),error.c_str());
  D3D12_QUERY_HEAP_DESC q{};q.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;q.Count=2;ComPtr<ID3D12QueryHeap> queries;hr(f.device->CreateQueryHeap(&q,IID_PPV_ARGS(&queries)));
  auto readback=f.Buffer(16,D3D12_HEAP_TYPE_READBACK);uint64_t frequency=0;hr(f.queue->GetTimestampFrequency(&frequency));std::vector<double> times;uint64_t warmAllocations=0,warmBytes=0;
  for(unsigned repeat=0;repeat<14;++repeat){
   r.restore();Capture::SnapshotLease lease;f.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);need(capture.Capture(f.list.Get(),r.binding(),lease,error),error.c_str());f.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
   f.list->ResolveQueryData(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,readback.Get(),0);f.Submit();const auto tickBytes=read(readback.Get(),16);uint64_t ticks[2];memcpy(ticks,tickBytes.data(),16);
   if(repeat>=2){times.push_back(double(ticks[1]-ticks[0])*1000.0/double(frequency));need(gRawAllocations==warmAllocations&&capture.OwnedAuxiliaryBytes()==warmBytes,"timed warm capture performs no buffer/heap allocation");}
   else{warmAllocations=gRawAllocations;warmBytes=capture.OwnedAuxiliaryBytes();}
   lease.reset();f.Reset();
  }
  std::sort(times.begin(),times.end());double sum=0;for(auto t:times)sum+=t;
  std::cout<<std::setprecision(9)<<"timing "<<name<<" raw_capture_median_ms="<<times[times.size()/2]<<" mean_ms="<<sum/times.size()<<" min_ms="<<times.front()<<" max_ms="<<times.back()<<" samples="<<times.size()<<" owned_bytes="<<warmBytes<<"\n";
  gRawBorrowed.clear();
 }
 f.Validate();std::cout<<"timing_checks="<<checks<<"\n";
}
int main(int argc,char** argv)try
{need(argc==3,"mode and data directory");if(std::string(argv[1])=="cases")cases(argv[2]);else if(std::string(argv[1])=="timing")timing(argv[2]);else throw std::runtime_error("unknown mode");return 0;}
catch(const std::exception& error){std::cerr<<error.what()<<"\n";return 1;}
