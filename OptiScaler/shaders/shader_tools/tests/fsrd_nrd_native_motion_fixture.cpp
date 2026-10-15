// Built with the actual capture header and production precompiled motion shaders.
#include "native_fixture_context.h"
#include "native_motion_shaders.h"

static uint64_t rootClock(ID3D12CommandQueue* queue)
{ uint64_t frequency=0; hr(queue->GetTimestampFrequency(&frequency)); return frequency; }
template<class T> static ULONG refs(T* object)
{ const auto count=object->AddRef(); object->Release(); return count; }
static std::vector<char> bytes(const void* source,size_t count)
{ const auto* begin=static_cast<const char*>(source); return {begin,begin+count}; }
static void fill(ID3D12Resource* buffer,const std::vector<char>& data)
{ void* mapped=nullptr; D3D12_RANGE noRead{0,0};hr(buffer->Map(0,&noRead,&mapped));memcpy(mapped,data.data(),data.size());buffer->Unmap(0,nullptr); }
static void writeBuffer(Fixture& f,ID3D12Resource* source,const fs::path& path)
{
 auto readback=f.Buffer(256,D3D12_HEAP_TYPE_READBACK);
 Fixture::Transition(f.list.Get(),source,D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COPY_SOURCE);
 f.list->CopyBufferRegion(readback.Get(),0,source,0,256);
 Fixture::Transition(f.list.Get(),source,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_COMMON);
 f.Submit();void* mapped=nullptr;D3D12_RANGE read{0,256};hr(readback->Map(0,&read,&mapped));save(path,bytes(mapped,256));D3D12_RANGE none{0,0};readback->Unmap(0,&none);
}
struct MotionPipeline
{
 ComPtr<ID3D12RootSignature> root;ComPtr<ID3D12PipelineState> pso;bool native=false;
 MotionPipeline(ID3D12Device* device,bool n):native(n)
 {
  const auto* shader=n?NativeMotionBytes:BaselineMotionBytes;const auto length=n?sizeof(NativeMotionBytes):sizeof(BaselineMotionBytes);
  hr(device->CreateRootSignature(0,shader,length,IID_PPV_ARGS(&root)));
  D3D12_COMPUTE_PIPELINE_STATE_DESC desc{};desc.pRootSignature=root.Get();desc.CS={shader,length};hr(device->CreateComputePipelineState(&desc,IID_PPV_ARGS(&pso)));
 }
 void record(Fixture& f,ID3D12DescriptorHeap* descriptors,const std::vector<char>& constants,ID3D12Resource* shadow,uint32_t width,uint32_t height)
 {
  f.list->SetPipelineState(pso.Get());f.list->SetComputeRootSignature(root.Get());f.list->SetDescriptorHeaps(1,&descriptors);
  f.list->SetComputeRoot32BitConstants(0,32,constants.data(),0);auto gpu=descriptors->GetGPUDescriptorHandleForHeapStart();
  f.list->SetComputeRootDescriptorTable(1,gpu);gpu.ptr+=uint64_t(native?4:3)*f.device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  f.list->SetComputeRootDescriptorTable(2,gpu);
  if(native){Fixture::Transition(f.list.Get(),shadow,D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_VERTEX_AND_CONSTANT_BUFFER);f.list->SetComputeRootConstantBufferView(3,shadow->GetGPUVirtualAddress());}
  f.list->Dispatch((width+7)/8,(height+7)/8,1);
  if(native)Fixture::Transition(f.list.Get(),shadow,D3D12_RESOURCE_STATE_VERTEX_AND_CONSTANT_BUFFER,D3D12_RESOURCE_STATE_COMMON);
 }
};
struct CaseResources
{
 std::array<ComPtr<ID3D12Resource>,4> input;ComPtr<ID3D12Resource> output;
 ComPtr<ID3D12DescriptorHeap> descriptors,baselineDescriptors,sourceTable;
 ComPtr<ID3D12Resource> firstConstants,lastConstants;
 CaseResources(Fixture& f,const fs::path& path,uint32_t width,uint32_t height)
 {
  const char* names[]={"raw.bin","depth.bin","previous.bin","native_depth.bin"};
  for(size_t i=0;i<4;++i){const auto data=load(path/names[i]);input[i]=f.Texture(width,height,i?DXGI_FORMAT_R32_FLOAT:DXGI_FORMAT_R16G16B16A16_FLOAT,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&data);gNativeBorrowed.insert(input[i].Get());}
  output=f.Texture(width,height,DXGI_FORMAT_R16G16B16A16_FLOAT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  D3D12_DESCRIPTOR_HEAP_DESC heap{};heap.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;heap.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
  const UINT stride=f.device->GetDescriptorHandleIncrementSize(heap.Type);
  for(bool native:{false,true}){
   heap.NumDescriptors=native?5:4;auto& target=native?descriptors:baselineDescriptors;hr(f.device->CreateDescriptorHeap(&heap,IID_PPV_ARGS(&target)));
   auto cpu=target->GetCPUDescriptorHandleForHeapStart();
   for(UINT i=0;i<(native?4u:3u);++i){D3D12_SHADER_RESOURCE_VIEW_DESC srv{};srv.Format=input[i]->GetDesc().Format;srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;srv.Texture2D.MipLevels=1;f.device->CreateShaderResourceView(input[i].Get(),&srv,cpu);cpu.ptr+=stride;}
   D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};uav.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;f.device->CreateUnorderedAccessView(output.Get(),nullptr,&uav,cpu);
  }
  heap.NumDescriptors=1;hr(f.device->CreateDescriptorHeap(&heap,IID_PPV_ARGS(&sourceTable)));
  firstConstants=f.Buffer(512,D3D12_HEAP_TYPE_UPLOAD);lastConstants=f.Buffer(512,D3D12_HEAP_TYPE_UPLOAD);
  auto first=load(path/"title.bin");first[432]^=char(0x40);fill(firstConstants.Get(),first);fill(lastConstants.Get(),load(path/"title.bin"));
  gNativeBorrowed.insert(firstConstants.Get());gNativeBorrowed.insert(lastConstants.Get());
  D3D12_CONSTANT_BUFFER_VIEW_DESC cbv{firstConstants->GetGPUVirtualAddress(),512};f.device->CreateConstantBufferView(&cbv,sourceTable->GetCPUDescriptorHandleForHeapStart());
 }
 void finalSource(Fixture& f,bool table,const fs::path& path)
 {
  // Volatile native binding observes the data/descriptor written AFTER Capture.
  if(table){D3D12_CONSTANT_BUFFER_VIEW_DESC cbv{lastConstants->GetGPUVirtualAddress(),512};f.device->CreateConstantBufferView(&cbv,sourceTable->GetCPUDescriptorHandleForHeapStart());}
  else fill(firstConstants.Get(),load(path/"title.bin"));
 }
};
static void cases(const fs::path& directory)
{
 Fixture f(true);MotionPipeline native(f.device.Get(),true),baseline(f.device.Get(),false);
 NrdBridge::NativeTemporalCapture capture;std::string error;
 need(capture.OwnedAuxiliaryBytes()==0,"OFF default capture allocates no snapshot");need(capture.Initialize(f.device.Get(),error),error.c_str());
 need(capture.OwnedAuxiliaryBytes()==0,"pipeline initialization does not allocate a recording slot");
 std::ifstream manifest(directory/"cases.txt");uint32_t count,width,height;manifest>>count>>width>>height;need(count>10&&count<100,"meaningful bounded native cases");
 uint64_t warmBytes=0;
 for(uint32_t i=0;i<count;++i){
  std::string name;uint32_t corrupt;manifest>>name>>corrupt;need(bool(manifest),"native case manifest");const auto path=directory/name;
  for(bool table:{false,true}){
   CaseResources r(f,path,width,height);auto constants=load(path/"constants.bin");need(constants.size()==128,"unchanged32DWORD motion layout");
   FrameSurvey::BoundConstantBinding binding{};if(table){binding.descriptorHeap=r.sourceTable.Get();binding.descriptor=r.sourceTable->GetGPUDescriptorHandleForHeapStart();}
   else binding.address=r.firstConstants->GetGPUVirtualAddress();
   const auto firstRefs=refs(r.firstConstants.Get()),lastRefs=refs(r.lastConstants.Get());NrdBridge::NativeTemporalCapture::SnapshotLease lease;
   need(capture.Capture(f.list.Get(),binding,lease,error),error.c_str());auto* shadow=NrdBridge::NativeTemporalCapture::Resource(lease);
   need(shadow&&refs(r.firstConstants.Get())==firstRefs&&refs(r.lastConstants.Get())==lastRefs,"source buffers have no added COM owner");
   r.finalSource(f,table,path);
   if(corrupt){auto value=f.Buffer(4,D3D12_HEAP_TYPE_UPLOAD);const uint32_t zero=0;fill(value.Get(),bytes(&zero,4));Fixture::Transition(f.list.Get(),shadow,D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COPY_DEST);f.list->CopyBufferRegion(shadow,corrupt,value.Get(),0,4);Fixture::Transition(f.list.Get(),shadow,D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_COMMON);f.uploads.push_back(value);}
   native.record(f,r.descriptors.Get(),constants,shadow,width,height);auto result=f.Snapshot(r.output.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
   baseline.record(f,r.baselineDescriptors.Get(),constants,nullptr,width,height);auto camera=f.Snapshot(r.output.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
   auto visibleConstants=constants;reinterpret_cast<uint32_t*>(visibleConstants.data())[3]=0;
   baseline.record(f,r.baselineDescriptors.Get(),visibleConstants,nullptr,width,height);auto visible=f.Snapshot(r.output.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
   const auto suffix=table?"table":"root";writeBuffer(f,shadow,path/(std::string(suffix)+"-shadow.bin"));
   save(path/(std::string(suffix)+"-motion.bin"),result.Data());save(path/(std::string(suffix)+"-camera.bin"),camera.Data());save(path/(std::string(suffix)+"-visible.bin"),visible.Data());
   lease.reset();f.Reset();gNativeBorrowed.clear();
   if(!warmBytes)warmBytes=capture.OwnedAuxiliaryBytes();need(capture.OwnedAuxiliaryBytes()==warmBytes,"completed/reset native capture reuses the exact warm pool");
  }
 }
 // Cancel the CPU ticket and destroy its capture context before execution. The
 // actual RecordedComputeLease must retain the snapshot through GPU+Reset.
 const auto path=directory/"screen_positive";CaseResources canceled(f,path,width,height);auto owner=std::make_unique<NrdBridge::NativeTemporalCapture>();need(owner->Initialize(f.device.Get(),error),error.c_str());
 FrameSurvey::BoundConstantBinding binding{};binding.address=canceled.lastConstants->GetGPUVirtualAddress();NrdBridge::NativeTemporalCapture::SnapshotLease ticket;need(owner->Capture(f.list.Get(),binding,ticket,error),error.c_str());
 std::weak_ptr weak=ticket;auto* resource=NrdBridge::NativeTemporalCapture::Resource(ticket);ticket.reset();owner.reset();need(!weak.expired(),"canceled caller/context stays owned by recorded native GPU lease");
 writeBuffer(f,resource,directory/"canceled-shadow.bin");need(!weak.expired(),"GPU completion alone retains executable closed-list snapshot");f.Reset();need(weak.expired(),"successful real Reset after GPU completion releases canceled snapshot");
 f.Validate();std::cout<<"checks="<<checks<<" native_cases="<<count<<" routes=2 warm_bytes="<<warmBytes<<" capture_allocations="<<gNativeCaptureAllocations<<" audited_barriers="<<gNativeCaptureBarriers<<"\n";
}
static void timing(const fs::path& directory)
{
 Fixture f(false);MotionPipeline motion(f.device.Get(),true);NrdBridge::NativeTemporalCapture capture;std::string error;need(capture.Initialize(f.device.Get(),error),error.c_str());
 for(const auto size:std::array<std::array<uint32_t,2>,2>{{{1505,847},{2560,1440}}}){
  const auto path=directory/(std::to_string(size[0])+"x"+std::to_string(size[1]));CaseResources r(f,path,size[0],size[1]);const auto constants=load(path/"constants.bin");
  fill(r.firstConstants.Get(),load(path/"title.bin"));FrameSurvey::BoundConstantBinding binding{};binding.address=r.firstConstants->GetGPUVirtualAddress();
  D3D12_QUERY_HEAP_DESC desc{};desc.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;desc.Count=2;ComPtr<ID3D12QueryHeap> queries;hr(f.device->CreateQueryHeap(&desc,IID_PPV_ARGS(&queries)));auto readback=f.Buffer(16,D3D12_HEAP_TYPE_READBACK);
  std::vector<double> times;
  for(unsigned repeat=0;repeat<12;++repeat){NrdBridge::NativeTemporalCapture::SnapshotLease lease;f.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);need(capture.Capture(f.list.Get(),binding,lease,error),error.c_str());motion.record(f,r.descriptors.Get(),constants,NrdBridge::NativeTemporalCapture::Resource(lease),size[0],size[1]);f.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);f.list->ResolveQueryData(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,readback.Get(),0);f.Submit();void* mapped=nullptr;D3D12_RANGE read{0,16};hr(readback->Map(0,&read,&mapped));const auto* ticks=static_cast<const uint64_t*>(mapped);if(repeat>=2)times.push_back(double(ticks[1]-ticks[0])*1000.0/double(rootClock(f.queue.Get())));D3D12_RANGE none{0,0};readback->Unmap(0,&none);lease.reset();f.Reset();}
  std::sort(times.begin(),times.end());std::cout<<"timing "<<size[0]<<"x"<<size[1]<<" capture_plus_motion_median_ms="<<times[times.size()/2]<<" samples="<<times.size()<<"\n";
  gNativeBorrowed.clear();
 }
 f.Validate();
}
int main(int argc,char** argv)try
{need(argc==3,"mode and input directory");if(std::string(argv[1])=="cases")cases(argv[2]);else if(std::string(argv[1])=="timing")timing(argv[2]);else throw std::runtime_error("unknown native fixture mode");return 0;}
catch(const std::exception& error){std::cerr<<error.what()<<"\n";return 1;}
