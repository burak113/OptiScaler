"""Real D3D12 survey/readback fixture. No game or image-quality claims.

Uses the production recorder, metadata decoders and GPU copy commands. The
ResTrack event callbacks are driven explicitly by the fixture; this does not
assert that Cyberpunk has exercised every runtime detour.
"""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT/'tools/fsrd_frame_survey'))
from resource_limits import prepare, memory_guard, peak_bytes
prepare()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

CPP = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <d3dcompiler.h>
#include <psapi.h>
#include <wrl/client.h>
#include <iostream>
#include <fstream>
#include <stdexcept>
#include "__TRACE__"
#include "__SURVEY__"
using Microsoft::WRL::ComPtr;
using J=nlohmann::json;
unsigned checks=0;
void need(bool ok,const char* msg) { if (!ok) throw std::runtime_error(msg); ++checks; }
void hr(HRESULT value) { if (FAILED(value)) throw std::runtime_error("D3D12 HRESULT "+std::to_string(value)); }
template<class P> void await(P p,const char* msg) {
 auto end=GetTickCount64()+15000; while (!p() && GetTickCount64()<end) Sleep(2); need(p(),msg);
}
constexpr auto srv=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
struct Host {
 ComPtr<ID3D12Device> dev; ComPtr<ID3D12CommandQueue> queue; ComPtr<ID3D12CommandAllocator> alloc;
 ComPtr<ID3D12GraphicsCommandList> list; ComPtr<ID3D12Fence> fence; ComPtr<ID3D12InfoQueue> info;
 ComPtr<IDXGIFactory4> factory; ComPtr<IDXGISwapChain1> swap; HWND window=nullptr; uint64_t tick=0;
 std::vector<ComPtr<ID3D12Resource>> uploads;
 std::string adapter;
 Host() {
  ComPtr<ID3D12Debug> debug; if (SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)))) debug->EnableDebugLayer();
  hr(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
  ComPtr<IDXGIAdapter1> chosen;
  for (UINT i=0;;++i) { ComPtr<IDXGIAdapter1> a; if (factory->EnumAdapters1(i,&a)==DXGI_ERROR_NOT_FOUND) break;
   DXGI_ADAPTER_DESC1 d {}; hr(a->GetDesc1(&d));
   if (!(d.Flags&DXGI_ADAPTER_FLAG_SOFTWARE) && d.VendorId==0x1002) {
    chosen=a; adapter=FrameSurveyMetadata::DecodeMarker(1,d.Description,sizeof(d.Description)).first; break;
   }
  }
  need(bool(chosen),"AMD hardware adapter required for reported GPU timings");
  hr(D3D12CreateDevice(chosen.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&dev)));
  dev.As(&info);
  D3D12_COMMAND_QUEUE_DESC q {}; hr(dev->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)));
  hr(dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&alloc)));
  hr(dev->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,alloc.Get(),nullptr,IID_PPV_ARGS(&list)));
  hr(dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));
  WNDCLASSW wc {}; wc.lpfnWndProc=DefWindowProcW; wc.hInstance=GetModuleHandleW(nullptr); wc.lpszClassName=L"FSRDFrameSurveyFixture";
  RegisterClassW(&wc); window=CreateWindowW(wc.lpszClassName,L"Frame survey fixture",WS_POPUP,0,0,64,32,nullptr,nullptr,wc.hInstance,nullptr);
  need(window!=nullptr,"hidden fixture window");
  DXGI_SWAP_CHAIN_DESC1 sc {}; sc.Width=64; sc.Height=32; sc.Format=DXGI_FORMAT_R8G8B8A8_UNORM;
  sc.SampleDesc.Count=1; sc.BufferCount=2; sc.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT; sc.SwapEffect=DXGI_SWAP_EFFECT_FLIP_DISCARD;
  hr(factory->CreateSwapChainForHwnd(queue.Get(),window,&sc,nullptr,nullptr,&swap));
 }
 ~Host() { FrameSurvey::Shutdown(); if(window) DestroyWindow(window); }
 void barrier(ID3D12Resource* r,D3D12_RESOURCE_STATES from,D3D12_RESOURCE_STATES to) {
  D3D12_RESOURCE_BARRIER b {}; b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION; b.Transition={r,0,from,to};
  FrameSurvey::Barrier(list.Get(),1,&b); list->ResourceBarrier(1,&b);
 }
 ComPtr<ID3D12Resource> texture(UINT w,UINT h,D3D12_RESOURCE_STATES state) {
  D3D12_RESOURCE_DESC d {}; d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D; d.Width=w; d.Height=h;
  d.DepthOrArraySize=d.MipLevels=1; d.SampleDesc.Count=1; d.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;
  d.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
  D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_DEFAULT;
  ComPtr<ID3D12Resource> r; hr(dev->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,state,nullptr,IID_PPV_ARGS(&r)));
  FrameSurvey::ResourceCreated(r.Get(),state); return r;
 }
 void fill(ID3D12Resource* texture,D3D12_RESOURCE_STATES state,uint16_t word) {
  auto d=texture->GetDesc(); D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp {}; UINT64 bytes=0;
  dev->GetCopyableFootprints(&d,0,1,0,&fp,nullptr,nullptr,&bytes);
  auto bd=ReadbackDesc(bytes); D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_UPLOAD;
  ComPtr<ID3D12Resource> up; hr(dev->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&bd,D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&up)));
  void* data=nullptr; hr(up->Map(0,nullptr,&data));
  for(UINT y=0;y<d.Height;++y) { auto row=reinterpret_cast<uint16_t*>(static_cast<uint8_t*>(data)+SIZE_T(y)*fp.Footprint.RowPitch);
   for(UINT x=0;x<d.Width*4;++x) row[x]=word;
  }
  up->Unmap(0,nullptr); barrier(texture,state,D3D12_RESOURCE_STATE_COPY_DEST);
  D3D12_TEXTURE_COPY_LOCATION src {},dst {}; src.pResource=up.Get(); src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint=fp;
  dst.pResource=texture; dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
  list->CopyTextureRegion(&dst,0,0,0,&src,nullptr); barrier(texture,D3D12_RESOURCE_STATE_COPY_DEST,state);
  uploads.push_back(up);
 }
 void execute() {
  ID3D12CommandList* cmd=list.Get(); FrameSurvey::Submit(queue.Get(),1,&cmd);
  auto tickets=RRTraceFence::BeforeSubmission(queue.Get(),1,&cmd);
  queue->ExecuteCommandLists(1,&cmd); RRTraceFence::AfterSubmission(queue.Get(),tickets);
  hr(queue->Signal(fence.Get(),++tick));
  await([&] { return fence->GetCompletedValue()>=tick; },"fixture GPU completion");
 }
 void reset() {
  hr(alloc->Reset()); hr(list->Reset(alloc.Get(),nullptr)); RRTraceFence::ResetSucceeded(list.Get());
  FrameSurvey::Reset(list.Get(),nullptr); uploads.clear();
 }
 void errors() {
  if(!info) return;
  for(UINT64 i=0;i<info->GetNumStoredMessagesAllowedByRetrievalFilter();++i) {
   SIZE_T size=0; info->GetMessage(i,nullptr,&size); std::vector<uint8_t> bytes(size);
   auto* m=reinterpret_cast<D3D12_MESSAGE*>(bytes.data()); info->GetMessage(i,m,&size);
   if(m->Severity<=D3D12_MESSAGE_SEVERITY_ERROR) throw std::runtime_error(m->pDescription);
  }
  need(true,"no D3D12 debug-layer errors");
 }
};
// GetStatus() turns "complete" before the writer thread publishes the final manifest; wait for that file.
J readJson(const std::filesystem::path& p) {
 J value; const auto end=GetTickCount64()+15000;
 do { try { std::ifstream f(p); value=J::parse(f); if (value.value("complete",false)) break; } catch (...) {} Sleep(5); }
 while (GetTickCount64()<end);
 return value;
}
void reaped() { await([] { std::scoped_lock lock(Global().mutex); return Global().gpuBytes==0; },"readbacks released after actual Reset"); }
void metadataTests(Host& h) {
 need(FrameSurveyMetadata::DecodeMarker(0,"NRD",4).first=="NRD","ANSI marker");
 const wchar_t wide[]=L"NRD \u0131\u015f\u0131k";
 need(FrameSurveyMetadata::DecodeMarker(1,wide,sizeof(wide)).first=="NRD \xc4\xb1\xc5\x9f\xc4\xb1k","Unicode marker UTF8");
 std::array<uint64_t,8> pix {}; pix[2]=(8ull<<55)|(1ull<<54); memcpy(pix.data()+3,"REBLUR %u",10);
 need(FrameSurveyMetadata::DecodeMarker(2,pix.data(),sizeof(pix)).first=="REBLUR %u","PIX legacy format string");
 need(FrameSurveyMetadata::DecodeMarker(2,pix.data(),16).second=="PIX_truncated","truncated PIX safe");
 need(FrameSurveyMetadata::DecodeMarker(9,pix.data(),64).first.empty(),"unknown marker metadata refused");
 need(FrameSurveyMetadata::CandidateExtent(753,424,1505,847),"ceil half extent");
 need(FrameSurveyMetadata::CandidateExtent(376,211,1505,847),"floor quarter extent");
 need(!FrameSurveyMetadata::CandidateExtent(1000,500,1505,847),"unrelated texture excluded");
}
J frameTest(Host& h) {
 auto input=h.texture(64,32,srv), output=h.texture(64,32,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
 input->SetName(L"synthetic_input"); output->SetName(L"synthetic_output");
 h.fill(input.Get(),srv,0x3c00); hr(h.list->Close()); h.execute(); h.reset();
 D3D12_DESCRIPTOR_RANGE ranges[2]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,1,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,1,0,0,1}};
 D3D12_ROOT_PARAMETER param {}; param.ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
 param.DescriptorTable={2,ranges}; D3D12_ROOT_SIGNATURE_DESC rd {1,&param,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE};
 ComPtr<ID3DBlob> blob,error; hr(D3D12SerializeRootSignature(&rd,D3D_ROOT_SIGNATURE_VERSION_1,IID_PPV_ARGS_Helper(&blob),&error));
 ComPtr<ID3D12RootSignature> root; hr(h.dev->CreateRootSignature(0,blob->GetBufferPointer(),blob->GetBufferSize(),IID_PPV_ARGS(&root)));
 FrameSurvey::RootCreated(root.Get(),blob->GetBufferPointer(),blob->GetBufferSize());
 const char shader[]="Texture2D<float4> X:register(t0); RWTexture2D<float4> Y:register(u0); [numthreads(8,8,1)] void main(uint3 p:SV_DispatchThreadID){Y[p.xy]=X.Load(int3(p.xy,0));}";
 ComPtr<ID3DBlob> cs; hr(D3DCompile(shader,sizeof(shader),nullptr,nullptr,nullptr,"main","cs_5_0",0,0,&cs,&error));
 D3D12_COMPUTE_PIPELINE_STATE_DESC pd {}; pd.pRootSignature=root.Get(); pd.CS={cs->GetBufferPointer(),cs->GetBufferSize()};
 ComPtr<ID3D12PipelineState> pso; hr(h.dev->CreateComputePipelineState(&pd,IID_PPV_ARGS(&pso)));
 FrameSurvey::PipelineCreated(pso.Get(),pd);
 const auto md=FrameSurvey::ReadPipeline(pso.Get());
 need(md["shader_hashes"]["CS"]==RRTraceAdditiveIO::Sha256({static_cast<const uint8_t*>(cs->GetBufferPointer()),cs->GetBufferSize()}),"DXBC content SHA256");
 need(!md["root_hash"].get<std::string>().empty(),"root signature SHA256 stored");
 CD3DX12_PIPELINE_STATE_STREAM stream; stream.pRootSignature=root.Get(); stream.CS=pd.CS;
 D3D12_PIPELINE_STATE_STREAM_DESC sd {sizeof(stream),&stream}; FrameSurvey::PipelineCreated(pso.Get(),sd);
 need(FrameSurvey::ReadPipeline(pso.Get())["shader_hashes"]["CS"]==md["shader_hashes"]["CS"],"pipeline stream hashes bytecode, not pointers");
 FrameSurvey::PipelineCreated(pso.Get(),pd);
 D3D12_DESCRIPTOR_HEAP_DESC hd {}; hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; hd.NumDescriptors=4; hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
 ComPtr<ID3D12DescriptorHeap> heap; hr(h.dev->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&heap))); FrameSurvey::HeapCreated(h.dev.Get(),heap.Get());
 const auto inc=h.dev->GetDescriptorHandleIncrementSize(hd.Type); auto cpu=heap->GetCPUDescriptorHandleForHeapStart(); auto gpu=heap->GetGPUDescriptorHandleForHeapStart();
 D3D12_SHADER_RESOURCE_VIEW_DESC sv {}; sv.Format=DXGI_FORMAT_R16G16B16A16_FLOAT; sv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
 sv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING; sv.Texture2D.MipLevels=1;
 D3D12_UNORDERED_ACCESS_VIEW_DESC uv {}; uv.Format=sv.Format; uv.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
 D3D12_CPU_DESCRIPTOR_HANDLE sc {cpu.ptr+2*inc},uc {cpu.ptr+3*inc};
 h.dev->CreateShaderResourceView(input.Get(),&sv,sc); FrameSurvey::View(input.Get(),sc,&sv);
 h.dev->CreateUnorderedAccessView(output.Get(),nullptr,&uv,uc); FrameSurvey::View(output.Get(),uc,&uv);
 need(FrameSurvey::Request(64,32),"one-frame request");
 bool activated=false;
 await([&] { if(!activated) { FrameSurvey::Present(h.swap.Get(),0); activated=FrameSurvey::GetStatus().phase=="recording"; }
  return activated; },"Present activates frame after background destination init");
 FrameSurvey::Reset(h.list.Get(),nullptr);
 h.barrier(output.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,srv);
 h.barrier(output.Get(),srv,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
 ID3D12DescriptorHeap* heaps[]={heap.Get()}; h.list->SetDescriptorHeaps(1,heaps); FrameSurvey::DescriptorHeaps(h.list.Get(),1,heaps);
 h.list->SetComputeRootSignature(root.Get()); FrameSurvey::RootBinding(h.list.Get(),false,root.Get());
 D3D12_GPU_DESCRIPTOR_HANDLE base {gpu.ptr+2*inc}; h.list->SetComputeRootDescriptorTable(0,base); FrameSurvey::Table(h.list.Get(),false,0,base);
 h.list->SetPipelineState(pso.Get()); FrameSurvey::SetPipeline(h.list.Get(),pso.Get());
 const std::array<uint64_t,3> groups {8,4,1};
 FrameSurvey::Pass(h.list.Get(),"Dispatch",groups); h.list->Dispatch(8,4,1); FrameSurvey::SnapshotWrites(h.list.Get());
 h.fill(input.Get(),srv,0x4000);
 FrameSurvey::Pass(h.list.Get(),"Dispatch",groups); h.list->Dispatch(8,4,1); FrameSurvey::SnapshotWrites(h.list.Get());
 auto argDesc=ReadbackDesc(256); D3D12_HEAP_PROPERTIES argHeap {}; argHeap.Type=D3D12_HEAP_TYPE_UPLOAD;
 ComPtr<ID3D12Resource> arguments; hr(h.dev->CreateCommittedResource(&argHeap,D3D12_HEAP_FLAG_NONE,&argDesc,D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&arguments)));
 void* argWords=nullptr; hr(arguments->Map(0,nullptr,&argWords)); const uint32_t argumentWords[]={8,4,1};
 memcpy(argWords,argumentWords,sizeof(argumentWords)); arguments->Unmap(0,nullptr);
 D3D12_INDIRECT_ARGUMENT_DESC argumentType {}; argumentType.Type=D3D12_INDIRECT_ARGUMENT_TYPE_DISPATCH;
 D3D12_COMMAND_SIGNATURE_DESC signatureDesc {12,1,&argumentType,0}; ComPtr<ID3D12CommandSignature> signature;
 hr(h.dev->CreateCommandSignature(&signatureDesc,nullptr,IID_PPV_ARGS(&signature)));
 h.list->ExecuteIndirect(signature.Get(),1,arguments.Get(),0,nullptr,0);
 hr(h.list->Close()); FrameSurvey::Close(h.list.Get(),S_OK); h.execute(); FrameSurvey::Present(h.swap.Get(),0);
 await([] { return FrameSurvey::GetStatus().phase=="complete"; },"async one-frame publication");
 const auto folder=std::filesystem::u8path(FrameSurvey::GetStatus().folder); const auto manifest=readJson(folder/"capture.json");
 need(manifest["schema"]=="fsrd-frame-survey-v1","survey schema"); need(manifest["batches"].size()==1,"submission batch recorded");
 need(manifest["command_lists"][0]["passes"].size()>=2,"dispatch metadata recorded");
 bool outputFound=false;
 for(const auto& row:manifest["frames"]) for(const auto& image:row["images"]) {
  if(image["source_resource_address_process_local"].get<uint64_t>()!=uint64_t(reinterpret_cast<uintptr_t>(output.Get()))) continue;
  const auto path=folder/image["file"].get<std::string>(); std::ifstream f(path,std::ios::binary); std::vector<uint16_t> words(64*32*4);
  f.read(reinterpret_cast<char*>(words.data()),words.size()*2);
  need(std::all_of(words.begin(),words.end(),[](auto v){return v==0x4000;}),"last writer private snapshot contains second dispatch words"); outputFound=true;
 }
 need(outputFound,"root table base plus explicit descriptor range resolved UAV output");
 const auto& dispatch=manifest["command_lists"][0]["passes"][0];
 need(dispatch["writes"][0]["descriptor_index"]==3,"manifest records resolved heap descriptor index");
 const auto retained=[] { std::scoped_lock lock(Global().mutex); return Global().gpuBytes; }();
 need(retained>0,"executable list retains GPU readback until real Reset");
 h.reset(); reaped(); h.errors();
 return {{"capture",folder.string()},{"retained_before_reset_bytes",retained}};
}
// Cyberpunk shape: pipelines come from an ID3D12PipelineLibrary and the async compute list binds its root
// signature, heaps, table and pipeline before the recorded Present; only the dispatch falls inside the frame.
J earlyBindingTest(Host& h) {
 auto input=h.texture(64,32,srv), output=h.texture(64,32,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
 h.fill(input.Get(),srv,0x3c00); hr(h.list->Close()); h.execute(); h.reset();
 D3D12_DESCRIPTOR_RANGE ranges[2]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,1,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,1,0,0,1}};
 D3D12_ROOT_PARAMETER param {}; param.ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
 param.DescriptorTable={2,ranges}; D3D12_ROOT_SIGNATURE_DESC rd {1,&param,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE};
 ComPtr<ID3DBlob> blob,error; hr(D3D12SerializeRootSignature(&rd,D3D_ROOT_SIGNATURE_VERSION_1,IID_PPV_ARGS_Helper(&blob),&error));
 ComPtr<ID3D12RootSignature> root; hr(h.dev->CreateRootSignature(0,blob->GetBufferPointer(),blob->GetBufferSize(),IID_PPV_ARGS(&root)));
 FrameSurvey::RootCreated(root.Get(),blob->GetBufferPointer(),blob->GetBufferSize());
 const char shader[]="Texture2D<float4> X:register(t0); RWTexture2D<float4> Y:register(u0); [numthreads(8,8,1)] void main(uint3 p:SV_DispatchThreadID){Y[p.xy]=X.Load(int3(p.xy,0))*2;}";
 ComPtr<ID3DBlob> cs; hr(D3DCompile(shader,sizeof(shader),nullptr,nullptr,nullptr,"main","cs_5_0",0,0,&cs,&error));
 const auto csHash=RRTraceAdditiveIO::Sha256({static_cast<const uint8_t*>(cs->GetBufferPointer()),cs->GetBufferSize()});
 D3D12_COMPUTE_PIPELINE_STATE_DESC pd {}; pd.pRootSignature=root.Get(); pd.CS={cs->GetBufferPointer(),cs->GetBufferSize()};
 ComPtr<ID3D12Device1> dev1; hr(h.dev.As(&dev1));
 ComPtr<ID3D12PipelineLibrary> library; hr(dev1->CreatePipelineLibrary(nullptr,0,IID_PPV_ARGS(&library)));
 // The create callback is deliberately NOT reported: only the hooked library load can hash the pipeline.
 ComPtr<ID3D12PipelineState> created; hr(h.dev->CreateComputePipelineState(&pd,IID_PPV_ARGS(&created)));
 need(FrameSurvey::ReadPipeline(created.Get())["hash_known"]==false,"unreported creation has no hash");
 hr(library->StorePipeline(L"early",created.Get()));
 ComPtr<ID3D12PipelineState> pso; hr(library->LoadComputePipeline(L"early",&pd,IID_PPV_ARGS(&pso)));
 const auto md=FrameSurvey::ReadPipeline(pso.Get());
 need(md["hash_known"]==true && md["shader_hashes"]["CS"]==csHash,"pipeline library load hashed by the survey detour");
 need(!md["root_hash"].get<std::string>().empty(),"library load records the root signature hash");
 D3D12_DESCRIPTOR_HEAP_DESC hd {}; hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; hd.NumDescriptors=4; hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
 ComPtr<ID3D12DescriptorHeap> heap; hr(h.dev->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&heap))); FrameSurvey::HeapCreated(h.dev.Get(),heap.Get());
 const auto inc=h.dev->GetDescriptorHandleIncrementSize(hd.Type); auto cpu=heap->GetCPUDescriptorHandleForHeapStart(); auto gpu=heap->GetGPUDescriptorHandleForHeapStart();
 D3D12_SHADER_RESOURCE_VIEW_DESC sv {}; sv.Format=DXGI_FORMAT_R16G16B16A16_FLOAT; sv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
 sv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING; sv.Texture2D.MipLevels=1;
 D3D12_UNORDERED_ACCESS_VIEW_DESC uv {}; uv.Format=sv.Format; uv.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
 D3D12_CPU_DESCRIPTOR_HANDLE sc {cpu.ptr+2*inc},uc {cpu.ptr+3*inc};
 h.dev->CreateShaderResourceView(input.Get(),&sv,sc); FrameSurvey::View(input.Get(),sc,&sv);
 h.dev->CreateUnorderedAccessView(output.Get(),nullptr,&uv,uc); FrameSurvey::View(output.Get(),uc,&uv);
 // Bindings recorded on the already reset list, before the survey is armed.
 ID3D12DescriptorHeap* heaps[]={heap.Get()}; h.list->SetDescriptorHeaps(1,heaps); FrameSurvey::DescriptorHeaps(h.list.Get(),1,heaps);
 h.list->SetComputeRootSignature(root.Get()); FrameSurvey::RootBinding(h.list.Get(),false,root.Get());
 D3D12_GPU_DESCRIPTOR_HANDLE base {gpu.ptr+2*inc}; h.list->SetComputeRootDescriptorTable(0,base); FrameSurvey::Table(h.list.Get(),false,0,base);
 h.list->SetPipelineState(pso.Get()); FrameSurvey::SetPipeline(h.list.Get(),pso.Get());
 // Targeted pass (FrameSurveyPassHashes): its output must be saved right after it although the list
 // Reset and the output's UAV barrier happened before the recorded frame.
 FrameSurvey::SetPassHashes(csHash.substr(0,12)+", not-hex, 00");
 need(FrameSurvey::Request(64,32),"early-binding one-frame request");
 bool activated=false;
 await([&] { if(!activated) { FrameSurvey::Present(h.swap.Get(),0); activated=FrameSurvey::GetStatus().phase=="recording"; }
  return activated; },"early-binding frame activates");
 // Frame generation: a Present-to-Present interval may hold no title work; the targeted window stays open.
 FrameSurvey::Present(h.swap.Get(),0);
 need(FrameSurvey::GetStatus().phase=="recording","targeted window stays open until a listed pass is saved");
 const std::array<uint64_t,3> groups {8,4,1};
 FrameSurvey::Pass(h.list.Get(),"Dispatch",groups); h.list->Dispatch(8,4,1); FrameSurvey::SnapshotWrites(h.list.Get());
 hr(h.list->Close()); FrameSurvey::Close(h.list.Get(),S_OK); h.execute();
 // A list without an observed Reset cannot carry payloads; a second, fully observed list publishes the frame.
 h.reset(); h.barrier(output.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,srv); h.barrier(output.Get(),srv,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
 hr(h.list->Close()); FrameSurvey::Close(h.list.Get(),S_OK); h.execute(); FrameSurvey::Present(h.swap.Get(),0);
 for (auto end=GetTickCount64()+15000; GetTickCount64()<end && FrameSurvey::GetStatus().phase!="complete" && FrameSurvey::GetStatus().phase!="error";) Sleep(2);
 need(FrameSurvey::GetStatus().phase=="complete",("early-binding frame published: "+FrameSurvey::GetStatus().phase+" / "+FrameSurvey::GetStatus().message).c_str());
 const auto folder=std::filesystem::u8path(FrameSurvey::GetStatus().folder); const auto manifest=readJson(folder/"capture.json");
 need(manifest["coverage_gaps"].value("list_bindings_seeded_from_tracking",0)==1,"list without observed Reset seeded from tracked bindings");
 need(manifest["command_lists"].size()==2 && manifest["command_lists"][0]["reset_observed"]==false,"seeded list recorded before the observed list");
 const auto& pass=manifest["command_lists"][0]["passes"][0];
 need(pass["pso"]["hash_known"]==true && pass["pso"]["shader_hashes"]["CS"]==csHash,"pre-frame pipeline binding resolves the shader hash");
 need(!pass["root_signature_sha256"].get<std::string>().empty(),"pre-frame root signature layout resolved");
 need(pass["unresolved"].empty(),"no unresolved binding reasons");
 need(pass["reads"].size()==1 && pass["reads"][0]["descriptor_index"]==2,"pre-frame table resolves the SRV input");
 need(pass["writes"].size()==1 && pass["writes"][0]["descriptor_index"]==3,"pre-frame table resolves the UAV output");
 need(pass.value("targeted_snapshot",false),"pass marked as targeted");
 need(manifest["coverage_gaps"].value("targeted_snapshot_state_from_uav_binding",0)==1,"targeted snapshot used the UAV-binding state rule");
 bool targetedFound=false;
 for(const auto& row:manifest["frames"]) for(const auto& image:row["images"]) {
  if(image["source_resource_address_process_local"].get<uint64_t>()!=uint64_t(reinterpret_cast<uintptr_t>(output.Get()))) continue;
  if(image["name"].get<std::string>().rfind("p",0)!=0) continue; // the observed list's barrier snapshot
  need(image["name"].get<std::string>().rfind("p"+std::to_string(pass["local_pass"].get<uint64_t>())+"_r",0)==0,"targeted snapshot key names its pass");
  const auto path=folder/image["file"].get<std::string>(); std::ifstream f(path,std::ios::binary); std::vector<uint16_t> words(64*32*4);
  f.read(reinterpret_cast<char*>(words.data()),words.size()*2);
  need(std::all_of(words.begin(),words.end(),[](auto v){return v==0x4000;}),"targeted snapshot holds the dispatch result (2 x input)"); targetedFound=true;
 }
 need(targetedFound,"targeted output saved from a list reset before the frame");
 need(manifest["coverage_gaps"].value("regular_snapshot_skipped_targeted_mode",0)>=1,"targeted mode leaves the budget to listed passes");
 need(manifest["coverage_gaps"].value("targeted_mode_window_extended_presents",0)==1 && manifest.value("presents_in_window",0)==2,
  "window extended by exactly the Present without a targeted pass");
 FrameSurvey::SetPassHashes("");
 h.reset(); reaped(); h.errors();
 return {{"capture",folder.string()},{"library_load_hashed",true}};
}
J aliasTest(Host& h) {
 FSRDGameTraceSession capture; need(capture.StartSurvey(64,32),"alias survey starts");
 await([&]{return capture.SurveyStatus().phase=="requested";},"alias writer ready");
 auto d=CD3DX12_RESOURCE_DESC::Tex2D(DXGI_FORMAT_R16G16B16A16_FLOAT,64,32,1,1,1,0,D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
 D3D12_HEAP_DESC hd {}; hd.SizeInBytes=h.dev->GetResourceAllocationInfo(0,1,&d).SizeInBytes;
 hd.Properties.Type=D3D12_HEAP_TYPE_DEFAULT; hd.Flags=D3D12_HEAP_FLAG_ALLOW_ONLY_NON_RT_DS_TEXTURES;
 ComPtr<ID3D12Heap> heap; hr(h.dev->CreateHeap(&hd,IID_PPV_ARGS(&heap)));
 ComPtr<ID3D12Resource> a,b; hr(h.dev->CreatePlacedResource(heap.Get(),0,&d,srv,nullptr,IID_PPV_ARGS(&a)));
 hr(h.dev->CreatePlacedResource(heap.Get(),0,&d,srv,nullptr,IID_PPV_ARGS(&b)));
 D3D12_RESOURCE_BARRIER alias {}; alias.Type=D3D12_RESOURCE_BARRIER_TYPE_ALIASING; alias.Aliasing={nullptr,a.Get()};
 h.list->ResourceBarrier(1,&alias); h.fill(a.Get(),srv,0x3c00);
 auto token=capture.BeginSurveyBatch(h.dev.Get(),h.list.Get(),101);
 need(capture.SurveyTexture(token,"private_A",{a.Get(),srv}),"snapshot before alias reuse");
 alias.Aliasing={a.Get(),b.Get()}; h.list->ResourceBarrier(1,&alias); h.fill(b.Get(),srv,0x4200);
 hr(h.list->Close()); capture.SealSurveyBatch(token); h.execute(); capture.FinishSurvey("{}");
 await([&]{return capture.SurveyStatus().phase=="complete";},"alias snapshot published");
 const auto folder=std::filesystem::u8path(capture.SurveyStatus().folder);
 const auto manifest=readJson(folder/"capture.json"); const auto image=manifest["frames"][0]["images"][0];
 std::ifstream f(folder/image["file"].get<std::string>(),std::ios::binary); std::vector<uint16_t> words(64*32*4);
 f.read(reinterpret_cast<char*>(words.data()),words.size()*2);
 need(std::all_of(words.begin(),words.end(),[](auto v){return v==0x3c00;}),"private snapshot survives same-heap placed texture alias overwrite");
 h.reset(); token.reset(); reaped(); h.errors(); return {{"capture",folder.string()},{"same_heap_offset",0}};
}
J timing(Host& h,UINT w,UINT height) {
 auto texture=h.texture(w,height,srv); h.fill(texture.Get(),srv,0x3c00); hr(h.list->Close()); h.execute(); h.reset();
 FSRDGameTraceSession capture; need(capture.StartSurvey(w,height),"timing survey starts");
 await([&] { return capture.SurveyStatus().phase=="requested"; },"timing writer ready");
 auto token=capture.BeginSurveyBatch(h.dev.Get(),h.list.Get(),99); need(bool(token),"timing batch");
 constexpr UINT n=32; D3D12_QUERY_HEAP_DESC qd {}; qd.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP; qd.Count=2*n;
 ComPtr<ID3D12QueryHeap> queries; hr(h.dev->CreateQueryHeap(&qd,IID_PPV_ARGS(&queries)));
 const auto bd=ReadbackDesc(16*n); D3D12_HEAP_PROPERTIES hp {}; hp.Type=D3D12_HEAP_TYPE_READBACK;
 ComPtr<ID3D12Resource> times; hr(h.dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&bd,D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&times)));
 for(UINT i=0;i<n;++i) { h.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2*i);
  need(capture.SurveyTexture(token,"copy",{texture.Get(),srv}),"production survey snapshot copy");
  h.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2*i+1);
 }
 h.list->ResolveQueryData(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2*n,times.Get(),0);
 hr(h.list->Close()); capture.SealSurveyBatch(token); h.execute(); capture.FinishSurvey("{}");
 await([&] { return capture.SurveyStatus().phase=="complete"; },"timing capture published");
 UINT64 freq=0; hr(h.queue->GetTimestampFrequency(&freq)); void* data=nullptr; D3D12_RANGE range {0,16*n}; hr(times->Map(0,&range,&data));
 auto* words=static_cast<uint64_t*>(data); std::vector<double> us;
 for(UINT i=1;i<n;++i) us.push_back(double(words[2*i+1]-words[2*i])*1e6/freq); // omit cold first copy
 times->Unmap(0,nullptr); std::sort(us.begin(),us.end());
 double sum=0; for(auto v:us) sum+=v;
 J row={{"extent",{w,height}},{"format","RGBA16F"},{"pass","source transitions + production readback copy"},
  {"samples",us.size()},{"mean_us",sum/us.size()},{"median_us",us[us.size()/2]},{"p90_us",us[size_t(.9*(us.size()-1))]},
  {"timestamp_frequency",freq},{"scope","isolated synthetic hardware copy; excludes title denoiser, disk, CPU and capture observer effects"}};
 h.reset(); token.reset(); reaped(); h.errors(); return row;
}
int main(int argc,char** argv) try {
 need(argc==2,"scratch directory argument"); g_dllPath=std::filesystem::path(argv[1])/"fixture.dll";
 Host host; metadataTests(host); need(!FrameSurvey::Enabled(),"survey off before explicit install");
 need(FrameSurvey::Install(host.dev.Get(),host.list.Get()),"optional hooks install");
 J result={{"source","synthetic_D3D12_hardware_fixture_not_Cyberpunk"},{"adapter",host.adapter}};
 result["frame"]=frameTest(host); result["aliasing"]=aliasTest(host);
 result["early_binding"]=earlyBindingTest(host);
 result["timings"]={timing(host,1505,847),timing(host,2560,1440)};
 PROCESS_MEMORY_COUNTERS memory {}; need(GetProcessMemoryInfo(GetCurrentProcess(),&memory,sizeof(memory))!=0,"native peak working set measured");
 result["native_peak_working_set_bytes"]=memory.PeakWorkingSetSize;
 need(memory.PeakWorkingSetSize < (uint64_t(5)<<29),"native fixture stays within 2.5 GiB");
 result["checks_passed"]=checks;
 std::ofstream(std::filesystem::path(argv[1])/"host-result.json")<<result.dump(2)<<'\n'; std::cout<<result.dump()<<'\n'; return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
'''


def run():
    memory_guard()
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/frame_survey/host'))
    output.mkdir(parents=True, exist_ok=True)
    stubs = output/'stubs'
    (stubs/'proxies').mkdir(parents=True, exist_ok=True)
    (stubs/'inputs').mkdir(exist_ok=True)
    (stubs/'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n#define LOG_INFO(...) ((void)0)\n#define LOG_ERROR(...) ((void)0)\n')
    (stubs/'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\nnamespace Util { inline std::filesystem::path DllPath() { return g_dllPath; } }\n')
    (stubs/'inputs/NVNGX_DLSS.h').write_text('#pragma once\n#include <nvsdk_ngx.h>\n')
    (stubs/'proxies/D3D12_Proxy.h').write_text('#pragma once\n#include <d3d12.h>\nnamespace D3d12Proxy { inline auto D3D12CreateVersionedRootSignatureDeserializer_() { return &D3D12CreateVersionedRootSignatureDeserializer; } inline auto D3D12SerializeVersionedRootSignature_() { return &D3D12SerializeVersionedRootSignature; } }\n')
    text = CPP.replace('__TRACE__', (ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp').as_posix()).replace(
        '__SURVEY__', (ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').as_posix())
    # D3D12SerializeRootSignature takes ID3DBlob**, not IID_PPV_ARGS.
    text = text.replace('IID_PPV_ARGS_Helper(&blob)', '&blob')
    source = output/'fixture.cpp'
    source.write_text(text, encoding='utf-8')
    exe = output/'fixture.exe'
    detours = ROOT/'OptiScaler/library/detours/detours.lib'
    compile_cpp(source, exe, ('d3d12.lib', 'dxgi.lib', 'dxguid.lib', 'd3dcompiler.lib', 'bcrypt.lib', 'user32.lib', 'psapi.lib', str(detours)),
                (stubs, ROOT/'OptiScaler', ROOT/'OptiScaler/include', ROOT/'external/streamline', ROOT/'external/nlohmann', ROOT/'external/nvngx_dlss_sdk',
                 ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
    subprocess.run([str(exe), str(output)], check=True, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    row = json.loads((output/'host-result.json').read_text())
    sys.path.insert(0, str(ROOT/'tools/fsrd_frame_survey'))
    from survey import Survey
    captured = Survey(row['frame']['capture'])
    indirect = [p for p in captured.passes if p['kind'] == 'ExecuteIndirect']
    assert len(indirect) == 1
    decoded = captured.indirect_commands(indirect[0])
    assert decoded['available'] and decoded['actual_command_count'] == 1
    assert decoded['commands'][0][0]['thread_group_counts'] == [8, 4, 1]
    row['indirect_readback_decoded'] = decoded
    row['python_checks_passed'] = 3
    row['python_peak_working_set_bytes'] = peak_bytes()
    (output/'host-result.json').write_text(json.dumps(row, indent=2)+'\n')
    print(json.dumps({'checks_passed': row['checks_passed'], 'peak_working_set_bytes': peak_bytes()}))


if __name__ == '__main__':
    run()
