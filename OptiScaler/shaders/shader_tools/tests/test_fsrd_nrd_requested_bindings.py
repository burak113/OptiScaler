"""Production bounded compute requests on actual large/unbounded D3D12 roots.

Includes real placed-buffer GPUVA reuse and window-independent generation checks.
No title bytecode, binary root blob or shader disassembly is shipped.
"""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_fsrd_frame_survey as survey_fixture
import test_fsrd_nrd_register_bindings as register_fixture
import test_fsrd_nrd_constant_buffers as constant_fixture
from test_fsrd_nrd_root_restore import function
from fsrd_toolchain import compile_cpp

CPP=r'''
#include "misc/NrdBridgeLifetime_Dx12.h"
struct RequestedHost:ConstantHost {
 explicit RequestedHost(Host& h):ConstantHost(h) {
  FrameSurvey::Released(heap.Get()); heap.Reset();
  D3D12_DESCRIPTOR_HEAP_DESC d {}; d.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
  d.NumDescriptors=8192; d.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
  hr(h.dev->CreateDescriptorHeap(&d,IID_PPV_ARGS(&heap))); FrameSurvey::HeapCreated(h.dev.Get(),heap.Get());
  gpu=heap->GetGPUDescriptorHandleForHeapStart();
 }
 void image(UINT slot,ID3D12Resource* resource,bool write=false) {
  if(write) {
   D3D12_UNORDERED_ACCESS_VIEW_DESC d {}; d.Format=DXGI_FORMAT_R16G16B16A16_FLOAT; d.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
   host.dev->CreateUnorderedAccessView(resource,nullptr,&d,cpu(slot,true)); FrameSurvey::View(resource,cpu(slot,true),&d);
  } else {
   D3D12_SHADER_RESOURCE_VIEW_DESC d {}; d.Format=DXGI_FORMAT_R16G16B16A16_FLOAT; d.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
   d.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING; d.Texture2D.MipLevels=1;
   host.dev->CreateShaderResourceView(resource,&d,cpu(slot,true)); FrameSurvey::View(resource,cpu(slot,true),&d);
  }
 }
 bool query(std::initializer_list<FrameSurvey::ComputeTableRequest> request,std::vector<FrameSurvey::BoundResource>& out,UINT param=1) {
  return FrameSurvey::ResolveComputeBindings(host.list.Get(),param,{request.begin(),request.size()},out);
 }
};
J requestedTests(Host& h) {
 RequestedHost f(h); std::vector<ComPtr<ID3D12Resource>> images;
 for(UINT i=0;i<8;++i) { images.push_back(h.texture(64,32,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE)); f.image(i,images.back().Get()); }
 auto* finite=f.RegisterHost::create({{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,8,0,0,0}}); f.bind(finite);
 std::vector<FrameSurvey::BoundResource> out;
 const auto spec=D3D12_DESCRIPTOR_RANGE_TYPE_SRV,uav=D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
 need(f.query({{spec,2,2,0},{spec,0,0,0},{spec,3,3,0},{spec,1,1,0}},out) && out.size()==4 &&
  out[0].descriptorOffset==2 && out[0].resource==images[2].Get() && out[1].descriptorOffset==0 && out[1].resource==images[0].Get(),"finite requested output preserves explicit request order and resource identity");
 need(f.query({{spec,0,0,0},{spec,1,1,0},{spec,2,2,0},{spec,3,3,0},{spec,4,4,0},{spec,5,5,0},{spec,6,6,0},{spec,7,7,0}},out) && out.size()==8,"exact maximum eight requested descriptors resolves");
 need(!f.query({},out) && out.empty(),"empty request is rejected without partial output");
 need(!f.query({{spec,0,0,0},{spec,1,1,0},{spec,2,2,0},{spec,3,3,0},{spec,4,4,0},{spec,5,5,0},{spec,6,6,0},{spec,7,7,0},{spec,8,8,0}},out) && out.empty(),"ninth request is rejected without walking table");
 need(!f.query({{spec,0,0,0},{spec,0,0,0}},out) && out.empty(),"duplicate requested descriptor/register rejected");
 need(!f.query({{spec,2,3,0}},out) && !f.query({{spec,2,2,1}},out) && !f.query({{uav,2,2,0}},out),"requested shader register, space and descriptor kind are exact");
 const auto beforeRefs=images[0]->AddRef(); images[0]->Release();
 for(UINT i=0;i<100;++i) need(f.query({{spec,0,0,0}},out),"repeated request is a metadata-only current lookup");
 const auto afterRefs=images[0]->AddRef(); images[0]->Release(); need(beforeRefs==afterRefs,"requested resolver never retains title textures");
 auto* large=f.RegisterHost::create({{spec,4096,0,0,0}}); f.bind(large);
 std::vector<FrameSurvey::BoundResource> whole;
 need(!FrameSurvey::ResolveComputeTable(h.list.Get(),1,whole),"unchanged whole-table API preserves finite 512 cap");
 need(f.query({{spec,0,0,0},{spec,1,1,0},{spec,2,2,0},{spec,3,3,0}},out) && out.size()==4,"actual 4096-descriptor range resolves only known four-slot prefix");
 need(!f.query({{spec,4000,4000,0}},out) && out.empty(),"unknown requested far slot is rejected, unrelated missing tail is not read");
 auto* unbounded=f.RegisterHost::create({{spec,UINT_MAX,0,0,0}}); f.bind(unbounded);
 need(!FrameSurvey::ComputeTableBindingMatches(h.list.Get(),1,spec,2,2,0),"unchanged finite whole-table proof still rejects unbounded table");
 need(f.query({{spec,0,0,0},{spec,1,1,0},{spec,2,2,0},{spec,3,3,0}},out) && out.size()==4,"actual unbounded SRV range safely proves finite t0 through t3 requests");
 need(!f.query({{spec,8192,8192,0}},out) && out.empty(),"unbounded declaration cannot extend a requested slot outside actual heap");
 auto* shifted=f.RegisterHost::create({{spec,UINT_MAX,7,3,4}}); f.bind(shifted);
 need(f.query({{spec,6,9,3}},out) && out[0].resource==images[6].Get(),"unbounded base register, nonzero space and explicit range offset are preserved");
 need(!f.query({{spec,6,2,0}},out),"unbounded range never guesses base-zero t2");
 auto* appended=f.RegisterHost::create({{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,2,20,0,0},{spec,UINT_MAX,0,0,D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND}}); f.bind(appended);
 need(f.query({{spec,2,0,0},{spec,3,1,0},{spec,4,2,0},{spec,5,3,0}},out) && out.size()==4,"unbounded APPEND start follows finite preceding CBV range");
 auto* outside=f.RegisterHost::create({{spec,4,0,0,0},{spec,2,20,0,10},{spec,2,30,0,10}}); f.bind(outside);
 need(f.query({{spec,0,0,0},{spec,2,2,0}},out),"unrelated descriptor alias outside requested prefix does not erase an exact prefix proof");
 auto* overlapping=f.RegisterHost::create({{spec,UINT_MAX,0,0,0},{spec,4,10,1,2}}); f.bind(overlapping);
 need(f.query({{spec,0,0,0}},out),"unbounded first slot can remain unique before later descriptor aliases");
 need(!f.query({{spec,2,2,0}},out) && out.empty(),"requested slot covered by two actual ranges is ambiguous even across register spaces");
 auto* pixel=f.RegisterHost::create({{spec,UINT_MAX,0,0,0}},D3D12_SHADER_VISIBILITY_PIXEL); f.bind(pixel,false);
 need(!f.query({{spec,0,0,0}},out),"metadata-only PIXEL table cannot prove compute requests");
 auto* unknown=f.RegisterHost::create({{spec,UINT_MAX,21,0,0}},D3D12_SHADER_VISIBILITY_ALL,false); f.bind(unknown);
 need(!f.query({{spec,0,21,0}},out),"unique actual untracked unbounded root is rejected");
 f.bind(finite); auto& ranges=FrameSurvey::gRootLayouts.at(finite).tables.at(1); const auto savedRanges=ranges;
 ranges.push_back({spec,12,2,0,0}); need(!f.query({{spec,0,0,0}},out),"metadata-only duplicate shader registers at different offsets reject exact request");
 ranges=savedRanges; ranges[0].offset=UINT_MAX-1; ranges[0].count=4;
 need(!f.query({{spec,0,0,0}},out),"metadata-only finite descriptor endpoint overflow is rejected");
 ranges=savedRanges; ranges[0].shaderRegister=UINT_MAX-1; ranges[0].count=4;
 need(!f.query({{spec,0,0,0}},out),"metadata-only finite register endpoint overflow is rejected");
 ranges=savedRanges; ranges[0].count=0; need(!f.query({{spec,0,0,0}},out),"metadata-only zero-count range is not a mapping proof"); ranges=savedRanges;
 FrameSurvey::Table(h.list.Get(),false,1,{f.gpu.ptr+1}); need(!f.query({{spec,0,0,0}},out),"metadata-only unaligned current table base rejects requests");
 f.bind(finite); auto* knownHeap=f.heap.Get(); FrameSurvey::DescriptorHeaps(h.list.Get(),0,nullptr);
 FrameSurvey::Table(h.list.Get(),false,1,f.gpu); need(!f.query({{spec,0,0,0}},out),"missing bound heap rejects requests");
 ID3D12DescriptorHeap* repeated[2]={knownHeap,knownHeap}; FrameSurvey::DescriptorHeaps(h.list.Get(),2,repeated); FrameSurvey::Table(h.list.Get(),false,1,f.gpu);
 need(!f.query({{spec,0,0,0}},out),"metadata-only ambiguous repeated heap candidates reject requests");
 f.bind(finite); FrameSurvey::View(nullptr,f.cpu(1,true),static_cast<const D3D12_SHADER_RESOURCE_VIEW_DESC*>(nullptr));
 need(!f.query({{spec,0,0,0},{spec,1,1,0}},out) && out.empty(),"missing second requested descriptor cannot leave partial first output"); f.image(1,images[1].Get());
 FrameSurvey::Reset(h.list.Get(),nullptr); need(!f.query({{spec,0,0,0}},out),"Reset clears requested-table identity");
 f.bind(unbounded); FrameSurvey::SetBindingWindow(false); need(!f.query({{spec,0,0,0}},out),"closed bridge window does no request resolution");
 FrameSurvey::SetBindingWindow(true); need(!f.query({{spec,0,0,0}},out),"opening window does not resurrect old table root");
 f.bind(unbounded); {FrameSurvey::ScopedInternal internal; need(!f.query({{spec,0,0,0}},out),"internal callbacks cannot resolve title requests");}
 FrameSurvey::gMetadataHealthy.store(false); need(!f.query({{spec,0,0,0}},out),"unhealthy registry rejects requested prefix"); FrameSurvey::gMetadataHealthy.store(true);
 auto* constants=f.root(true,6,0,D3D12_SHADER_VISIBILITY_ALL,{{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,UINT_MAX,0,0,0}});
 auto* buffer=f.buffer(4096); f.write(6,buffer,256,1536,true); f.table(constants);
 FrameSurvey::BoundConstantBuffer token;
 need(f.resolve(token) && token.resource==buffer && token.offset==256 && token.resourceGeneration!=0,"actual unbounded CBV range resolves uniquely mapped b6 and records generation");
 need(token.descriptorHeap==f.heap.Get() && token.descriptor.ptr==f.gpu.ptr+6*f.stride,"table CBV token preserves borrowed native heap and exact volatile GPU slot");
 need(f.query({{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,6,6,0}},out,3) && out[0].resource==buffer,"bounded request API also proves exact CBV slot metadata");
 need(FrameSurvey::ValidateBorrowedConstantBuffer(token),"current exact CBV generation token validates without COM");
 auto slotModified=token; slotModified.descriptor.ptr+=1;
 need(!FrameSurvey::ValidateBorrowedConstantBuffer(slotModified),"unaligned table token GPU descriptor is rejected");
 slotModified=token; slotModified.descriptorHeap=nullptr;
 need(!FrameSurvey::ValidateBorrowedConstantBuffer(slotModified),"native slot without its borrowed heap is rejected");
 auto* alternate=f.buffer(4096); f.write(6,alternate,256,1536,true);
 need(!FrameSurvey::ValidateBorrowedConstantBuffer(token),"same native slot overwritten with another buffer rejects the staged old token");
 f.write(6,buffer,512,1536,true);
 need(!FrameSurvey::ValidateBorrowedConstantBuffer(token),"same native slot with changed CBV address rejects old token");
 f.write(6,buffer,256,1280,true);
 need(!FrameSurvey::ValidateBorrowedConstantBuffer(token),"same native slot with changed CBV size rejects old token");
 f.write(6,buffer,256,1536,true);
 need(FrameSurvey::ValidateBorrowedConstantBuffer(token),"restoring exact native CBV slot restores provenance validation");
 hkSurveyCreateConstantBufferView(h.dev.Get(),nullptr,f.cpu(6,true));
 need(!FrameSurvey::ValidateBorrowedConstantBuffer(token),"native null overwrite tombstones staged table token provenance");
 f.write(6,buffer,256,1536,true);
 FrameSurvey::SetBindingWindow(false);
 need(FrameSurvey::ValidateBorrowedConstantBuffer(token),"generation validation remains available after window closes");
 { FrameSurvey::ScopedInternal internal; need(FrameSurvey::ValidateBorrowedConstantBuffer(token),"pure generation validation remains valid inside admitted internal injection"); }
 auto modified=token; ++modified.resourceGeneration; need(!FrameSurvey::ValidateBorrowedConstantBuffer(modified),"wrong CBV resource generation is rejected");
 modified=token; modified.offset+=256; need(!FrameSurvey::ValidateBorrowedConstantBuffer(modified),"token address and offset must describe same live bytes");
 modified=token; modified.size=65536; need(!FrameSurvey::ValidateBorrowedConstantBuffer(modified),"token size cannot exceed live buffer range");
 modified=token; modified.address+=1; need(!FrameSurvey::ValidateBorrowedConstantBuffer(modified),"misaligned token GPUVA fails validation");
 modified=token; modified.resource=nullptr; need(!FrameSurvey::ValidateBorrowedConstantBuffer(modified),"null token is never valid");
 FrameSurvey::gMetadataHealthy.store(false); need(!FrameSurvey::ValidateBorrowedConstantBuffer(token),"unhealthy registry cancels even closed-window token validation"); FrameSurvey::gMetadataHealthy.store(true);
 FrameSurvey::SetBindingWindow(true); f.table(constants);
 auto* constantsSpace=f.root(true,6,3,D3D12_SHADER_VISIBILITY_ALL,{{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,UINT_MAX,4,3,2}}); f.table(constantsSpace); f.write(4,buffer,256,1536,true);
 need(!f.resolve(token) && f.resolve(token,6,3) && token.resource==buffer,"unbounded CBV base/offset/space all map exactly");
 auto* cbvAlias=f.root(true,6,0,D3D12_SHADER_VISIBILITY_ALL,{{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,UINT_MAX,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,4,20,0,4}}); f.table(cbvAlias);
 need(!f.resolve(token),"actual unbounded CBV target aliasing another descriptor range is ambiguous");
 f.table(constants); f.write(6,buffer,256,1536,true); need(f.resolve(token),"restore actual exact unbounded b6");
 FrameSurvey::Released(buffer); need(!FrameSurvey::ValidateBorrowedConstantBuffer(token) && !f.resolve(token),"resource release invalidates unbounded CBV and prior generation token");
 // Execute the empty recording before physically deleting a buffer whose VA was set on the list.
 hr(h.list->Close()); h.execute(); h.reset();
 D3D12_HEAP_DESC heapDesc {}; heapDesc.SizeInBytes=65536; heapDesc.Properties.Type=D3D12_HEAP_TYPE_UPLOAD;
 heapDesc.Flags=D3D12_HEAP_FLAG_ALLOW_ONLY_BUFFERS;
 ComPtr<ID3D12Heap> placement; hr(h.dev->CreateHeap(&heapDesc,IID_PPV_ARGS(&placement)));
 D3D12_RESOURCE_DESC bd {}; bd.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER; bd.Width=4096; bd.Height=1;
 bd.DepthOrArraySize=bd.MipLevels=1; bd.SampleDesc.Count=1; bd.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
 ComPtr<ID3D12Resource> first; hr(h.dev->CreatePlacedResource(placement.Get(),0,&bd,D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&first)));
 FrameSurvey::ResourceCreated(first.Get(),D3D12_RESOURCE_STATE_GENERIC_READ);
 auto* root=f.root(); f.direct(root,first->GetGPUVirtualAddress()); FrameSurvey::BoundConstantBuffer oldToken;
 need(f.resolve(oldToken) && FrameSurvey::ValidateBorrowedConstantBuffer(oldToken),"actual placed buffer gets valid exact-generation token");
 hr(h.list->Close()); h.execute(); h.reset();
 {NrdBridgeLifetime::ScopedRelease release(true); FrameSurvey::Released(first.Get()); first.Reset();}
 need(!FrameSurvey::ValidateBorrowedConstantBuffer(oldToken),"physically released buffer token is rejected without touching dead COM pointer");
 ComPtr<ID3D12Resource> replacement; hr(h.dev->CreatePlacedResource(placement.Get(),0,&bd,D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&replacement)));
 FrameSurvey::ResourceCreated(replacement.Get(),D3D12_RESOURCE_STATE_GENERIC_READ); f.direct(root,replacement->GetGPUVirtualAddress());
 FrameSurvey::BoundConstantBuffer newToken;
 need(f.resolve(newToken) && newToken.address==oldToken.address && newToken.resourceGeneration!=oldToken.resourceGeneration,"genuine native replacement at same heap offset reuses GPUVA with a distinct resource generation");
 need(!newToken.descriptorHeap && !newToken.descriptor.ptr,"direct-root CBV token does not invent a descriptor heap or slot");
 need(!FrameSurvey::ValidateBorrowedConstantBuffer(oldToken) && FrameSurvey::ValidateBorrowedConstantBuffer(newToken),"same real GPUVA cannot resurrect old generation token");
 modified=newToken; modified.resourceGeneration=oldToken.resourceGeneration;
 need(!FrameSurvey::ValidateBorrowedConstantBuffer(modified),"current pointer/VA with stale generation still rejects possible COM-address reuse");
 const bool pointerReused=oldToken.resource==newToken.resource;
 const auto before=std::chrono::steady_clock::now();
 for(UINT i=0;i<200000;++i) if(!FrameSurvey::ValidateBorrowedConstantBuffer(newToken)) throw std::runtime_error("generation benchmark validation failed");
 const double validateNs=double(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-before).count())/200000;
 f.bind(unbounded); const auto prefixBefore=std::chrono::steady_clock::now();
 for(UINT i=0;i<100000;++i) if(!f.query({{spec,0,0,0},{spec,1,1,0},{spec,2,2,0},{spec,3,3,0}},out)) throw std::runtime_error("prefix benchmark resolution failed");
 const double prefixNs=double(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-prefixBefore).count())/100000;
 FrameSurvey::Released(unbounded); need(!f.query({{spec,0,0,0}},out),"released root cannot remain requested-prefix eligible");
 f.bind(finite); FrameSurvey::Released(images[0].Get()); need(!f.query({{spec,0,0,0}},out),"released texture invalidates exact requested slot");
 f.bind(large); FrameSurvey::Released(h.list.Get()); need(!f.query({{spec,2,2,0}},out),"released list has no requested binding identity");
 f.table(constants); f.write(6,replacement.Get(),0,1536,true); FrameSurvey::BoundConstantBuffer heapToken;
 need(f.resolve(heapToken) && FrameSurvey::ValidateBorrowedConstantBuffer(heapToken),"live native heap token is valid before heap release callback");
 FrameSurvey::Released(f.heap.Get());
 need(!FrameSurvey::ValidateBorrowedConstantBuffer(heapToken),"released descriptor heap rejects token before any COM use");
 hr(h.list->Close()); h.execute(); h.reset(); h.errors();
 return {{"checks_passed",checks},{"adapter",h.adapter},{"requested_prefix_callback_mean_ns",prefixNs},{"constant_generation_validation_mean_ns",validateNs},
  {"genuine_gpuva_reuse",true},{"native_com_pointer_reused",pointerReused},{"heap_descriptors",8192},{"maximum_requests",8},
  {"scope","production requested-slot resolver and CBV generation validation; actual4096/unbounded roots and native placed-resource GPUVA reuse; invalid metadata cases labelled"},
  {"contains_title_binary",false}};
}
int main(int argc,char** argv) try {
 need(argc==2,"output path"); g_dllPath=std::filesystem::path(argv[1])/"fixture.dll";
 Host host; auto result=requestedTests(host);
 std::ofstream(std::filesystem::path(argv[1])/"host-result.json")<<result.dump(2)<<'\n'; std::cout<<result.dump()<<'\n'; return 0;
} catch(const std::exception& e) {std::cerr<<e.what()<<'\n'; return 1;}
'''

def run():
    output=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT','F:/FSRD/sol_batch/12a-discovery/tests/requested-bindings'))
    output.mkdir(parents=True,exist_ok=True); stubs=output/'stubs'
    for folder in ('proxies','inputs'):
        (stubs/folder).mkdir(parents=True,exist_ok=True)
    (stubs/'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n#include <shared_mutex>\n#define LOG_INFO(...) ((void)0)\n#define LOG_ERROR(...) ((void)0)\n')
    (stubs/'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\nnamespace Util {inline std::filesystem::path DllPath(){return g_dllPath;}}\n')
    (stubs/'inputs/NVNGX_DLSS.h').write_text('#pragma once\n#include <nvsdk_ngx.h>\n')
    (stubs/'proxies/D3D12_Proxy.h').write_text('#pragma once\n#include <d3d12.h>\nnamespace D3d12Proxy {inline auto D3D12CreateVersionedRootSignatureDeserializer_(){return &D3D12CreateVersionedRootSignatureDeserializer;} inline auto D3D12SerializeVersionedRootSignature_(){return &D3D12SerializeVersionedRootSignature;}}\n')
    hooks=(ROOT/'OptiScaler/hooks/D3D12_Hooks.cpp').read_text()
    state=hooks[hooks.index('enum class RootEntryType'):hooks.index('enum class SignatureEntryType')]
    getter=function(hooks,'bool D3D12Hooks::GetComputeBindingsForBridge(').replace('D3D12Hooks::','')
    restrack=(ROOT/'OptiScaler/resource_tracking/ResTrack_Dx12.cpp').read_text()
    cbvhook=function(restrack,'void ResTrack_Dx12::hkSurveyCreateConstantBufferView(').replace('ResTrack_Dx12::','')
    text=survey_fixture.CPP.split('// GetStatus()')[0]+register_fixture.CPP.split('J registerTests')[0]+constant_fixture.CPP.split('J constantTests')[0]+CPP
    text=text.replace('__TRACE__',(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp').as_posix()).replace('__SURVEY__',(ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').as_posix())
    text=text.replace('__STATE__',state).replace('__GETTER__',getter).replace('__CBVHOOK__',cbvhook)
    source=output/'fixture.cpp'; source.write_text(text,encoding='utf-8'); exe=output/'fixture.exe'
    compile_cpp(source,exe,('d3d12.lib','dxgi.lib','dxguid.lib','d3dcompiler.lib','bcrypt.lib','user32.lib','psapi.lib',str(ROOT/'OptiScaler/library/detours/detours.lib')),
     (stubs,ROOT/'OptiScaler',ROOT/'OptiScaler/include',ROOT/'external/streamline', ROOT/'external/nlohmann',ROOT/'external/nvngx_dlss_sdk',ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
    subprocess.run([str(exe),str(output)],check=True,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    result=json.loads((output/'host-result.json').read_text()); report=Path('E:/FSRD/sol_batch/12a-discovery'); report.mkdir(parents=True,exist_ok=True)
    (report/'requested-bindings-result.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps(result))

if __name__=='__main__': run()
