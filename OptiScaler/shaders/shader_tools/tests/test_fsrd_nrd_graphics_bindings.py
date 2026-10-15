"""CPU-only proof of exact pixel/compute snapshot binding metadata.

The actual FrameSurvey source and Birth registry run on explicit POD resources.
Only a stack-owned fake root reaches COM: real D3D12 CPU root serialization and
deserialization exercise shader visibility. No GPU device or dispatch is created.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(os.environ.get('FSRD_NRD_PRODUCTION_ROOT', Path(__file__).resolve().parents[4]))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from fsrd_toolchain import compile_cpp
import test_fsrd_frame_survey_birth_metadata as metadata

PRELUDE = r'''
#define NOMINMAX
#include <d3d12.h>
#include <cstring>
// Explicit adapter for the unexercised opaque-command observer in this metadata
// translation unit. The separate actual-hook fixture verifies that observer.
class D3D12Hooks {public:static void OnBridgeOpaqueCommand(ID3D12GraphicsCommandList*,bool)noexcept{}};
'''

DRIVER = r'''
namespace NrdBridge {
bool StartupEnabled()noexcept{return false;}
DispatchDisposition OriginalDispatchDisposition(ID3D12GraphicsCommandList*,DispatchKind)noexcept{return DispatchDisposition::Forward;}
void InvalidateRecordingProof(ID3D12GraphicsCommandList*,const char*)noexcept{}
}
struct BlobRoot:ID3D12RootSignature {
 std::vector<uint8_t> bytes;unsigned queries=0;
 explicit BlobRoot(ID3DBlob* blob):bytes(static_cast<const uint8_t*>(blob->GetBufferPointer()),static_cast<const uint8_t*>(blob->GetBufferPointer())+blob->GetBufferSize()){}
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID,void** out)override{*out=nullptr;return E_NOINTERFACE;}
 ULONG STDMETHODCALLTYPE AddRef()override{return 2;}ULONG STDMETHODCALLTYPE Release()override{return 1;}
 HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID id,UINT* size,void* out)override{
  ++queries;if(id!=FrameSurvey::RootBlobId||!size)return E_INVALIDARG;
  if(!out){*size=UINT(bytes.size());return S_OK;}if(*size<bytes.size())return E_INVALIDARG;
  std::memcpy(out,bytes.data(),bytes.size());*size=UINT(bytes.size());return S_OK;
 }
 HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID,UINT,const void*)override{return E_NOTIMPL;}
 HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID,const IUnknown*)override{return E_NOTIMPL;}
 HRESULT STDMETHODCALLTYPE SetName(LPCWSTR)override{return S_OK;}
 HRESULT STDMETHODCALLTYPE GetDevice(REFIID,void** out)override{*out=nullptr;throw std::runtime_error("root decoder must not inspect device");}
};
FrameSurvey::RootLayout decoded(D3D12_SHADER_VISIBILITY visibility,D3D12_ROOT_SIGNATURE_FLAGS flags=D3D12_ROOT_SIGNATURE_FLAG_NONE){
 D3D12_DESCRIPTOR_RANGE reads{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,UINT_MAX,8,0,0};
 D3D12_DESCRIPTOR_RANGE writes{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,2,0,0,0};
 D3D12_ROOT_PARAMETER parameters[3]{};
 parameters[0].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV;parameters[0].Descriptor={6,0};parameters[0].ShaderVisibility=visibility;
 parameters[1].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;parameters[1].DescriptorTable={1,&reads};parameters[1].ShaderVisibility=visibility;
 parameters[2].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;parameters[2].DescriptorTable={1,&writes};parameters[2].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;
 D3D12_ROOT_SIGNATURE_DESC description{3,parameters,0,nullptr,flags};ComPtr<ID3DBlob> blob,errors;
 hr(D3D12SerializeRootSignature(&description,D3D_ROOT_SIGNATURE_VERSION_1,&blob,&errors));BlobRoot source(blob.Get());
 auto result=FrameSurvey::ReadRoot(&source);need(result.complete&&source.queries==2,"actual CPU decoder reads only the exact stack-owned root blob");return result;
}
int main(int argc,char** argv)try{
 need(argc==2,"report argument");FrameSurvey::BeginCreationTracking(false);
 need(!NrdBridgeNativeBirth::Ready(),"opaque metadata nodes never enter native COM preparation");
 need(NrdBridgeBirth::ConfigureActions({detach,identity,nullptr}),"actual Birth dispatcher configured");
 auto pixel=decoded(D3D12_SHADER_VISIBILITY_PIXEL),all=decoded(D3D12_SHADER_VISIBILITY_ALL),vertex=decoded(D3D12_SHADER_VISIBILITY_VERTEX);
 auto denied=decoded(D3D12_SHADER_VISIBILITY_PIXEL,D3D12_ROOT_SIGNATURE_FLAG_DENY_PIXEL_SHADER_ROOT_ACCESS);
 need(pixel.pixelVisibleTables.contains(1)&&pixel.pixelDescriptors.contains(0)&&!pixel.computeVisibleTables.contains(1)&&!pixel.computeDescriptors.contains(0),"actual PIXEL root remains distinct from compute ALL visibility");
 need(all.pixelVisibleTables.contains(1)&&all.computeVisibleTables.contains(1)&&all.pixelDescriptors.contains(0)&&all.computeDescriptors.contains(0),"ALL root is visible to both exact resolver families");
 need(!vertex.pixelVisibleTables.contains(1)&&!vertex.pixelDescriptors.contains(0)&&!denied.pixelVisibleTables.contains(1)&&!denied.pixelDescriptors.contains(0),"VERTEX-only and DENY_PIXEL layouts cannot prove pixel consumers");
 auto* r=reinterpret_cast<ID3D12RootSignature*>(0x50000);auto rb=born(r,101);
 auto* h=reinterpret_cast<ID3D12DescriptorHeap*>(0x60000);auto hb=born(h,102);auto ph=heap(h);
 auto* a=reinterpret_cast<ID3D12Resource*>(0x70000);auto ab=born(a,103);
 auto* b=reinterpret_cast<ID3D12Resource*>(0x80000);auto bb=born(b,104);
 auto pa=buffer(a,0);pa.description.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;pa.description.Width=128;pa.description.Height=64;
 pa.description.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;pa.description.Layout=D3D12_TEXTURE_LAYOUT_UNKNOWN;pa.description.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
 auto pb=pa;pb.object=b;
 need(FrameSurvey::PublishResourceMetadata(pa,ab)&&FrameSurvey::PublishResourceMetadata(pb,bb)&&FrameSurvey::PublishHeapMetadata(ph,hb),"actual resources and heap publish exact metadata births");
 const auto publish=[&](const FrameSurvey::RootLayout& layout){return FrameSurvey::PublishRootMetadata({r,std::make_shared<FrameSurvey::RootLayout>(layout)},rb);};
 need(publish(pixel),"decoded pixel root metadata published");
 D3D12_SHADER_RESOURCE_VIEW_DESC srv{};srv.Format=pa.description.Format;srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;srv.Texture2D.MipLevels=1;
 FrameSurvey::View(a,{ph.cpu+3*ph.increment},&srv);FrameSurvey::View(b,{ph.cpu+4*ph.increment},&srv);
 D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};uav.Format=pa.description.Format;uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
 FrameSurvey::View(a,{ph.cpu+8*ph.increment},&uav);FrameSurvey::View(b,{ph.cpu+9*ph.increment},&uav);
 FrameSurvey::ComputeBindings bindings;bindings.root=r;bindings.rootBirth=rb;bindings.heaps={h};bindings.heapBirths={hb};
 bindings.tables={{1,{ph.gpu}},{2,{ph.gpu+8*ph.increment}}};bindings.views={{0,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,0x100000}};
 const std::array<FrameSurvey::ComputeTableRequest,2> reads{{{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,3,11,0},{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,4,12,0}}};
 const std::array<FrameSurvey::ComputeTableRequest,2> writes{{{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,1,1,0}}};
 FrameSurvey::SetBindingWindow(false);std::vector<FrameSurvey::BoundResource> out;
 need(FrameSurvey::ResolveGraphicsBindings(bindings,1,reads,out)&&out.size()==2&&out[0].resource==a&&out[1].resource==b,"pixel t11/t12 exact requested resources resolve with bridge window closed");
 need(!FrameSurvey::ResolveComputeBindings(bindings,1,reads,out)&&out.empty(),"pixel-only texture table never proves compute input");
 need(FrameSurvey::ResolveComputeBindings(bindings,2,writes,out)&&out.size()==2&&out[0].resource==a&&out[1].resource==b,"explicit compute u0/u1 revalidation resolves after window closed");
 need(!FrameSurvey::ResolveGraphicsBindings(bindings,2,writes,out)&&out.empty(),"pixel consumer resolver rejects UAV requests");
 FrameSurvey::BoundConstantBinding cbv;need(FrameSurvey::ResolveGraphicsConstantBinding(bindings,6,0,cbv)&&cbv.address==0x100000&&!cbv.descriptorHeap,"pixel root b6 source-free VA needs no buffer registry owner");
 need(!FrameSurvey::ResolveComputeConstantBinding(bindings,6,0,cbv),"pixel-only root b6 cannot masquerade as compute visibility");
 FrameSurvey::ResolveGraphicsConstantBinding(bindings,6,0,cbv);const auto staged=cbv;
 auto wrong=bindings;wrong.views[0].address+=256;need(!FrameSurvey::ValidateGraphicsConstantBinding(wrong,6,0,staged),"changed live root VA rejects staged pixel flag binding");
 wrong=bindings;wrong.views.push_back(wrong.views[0]);need(!FrameSurvey::ResolveGraphicsConstantBinding(wrong,6,0,cbv),"duplicate root CBV arguments fail closed");
 wrong=bindings;wrong.tables.push_back(wrong.tables[0]);need(!FrameSurvey::ResolveGraphicsBindings(wrong,1,reads,out)&&out.empty(),"duplicate texture table arguments reject without partial output");
 auto request=reads;request[1].shaderRegister=11;need(!FrameSurvey::ResolveGraphicsBindings(bindings,1,request,out),"mismatched second SRV register cannot validate final targets");
 request=reads;request[1].registerSpace=1;need(!FrameSurvey::ResolveGraphicsBindings(bindings,1,request,out),"exact register space is required");
 request=reads;request[1]=request[0];need(!FrameSurvey::ResolveGraphicsBindings(bindings,1,request,out),"duplicate requested slot rejects");
 need(publish(vertex)&&!FrameSurvey::ResolveGraphicsBindings(bindings,1,reads,out)&&!FrameSurvey::ResolveGraphicsConstantBinding(bindings,6,0,cbv),"vertex-only decoded root rejects both pixel source proofs");
 need(publish(denied)&&!FrameSurvey::ResolveGraphicsBindings(bindings,1,reads,out),"deny-pixel flag remains authoritative at query");
 need(publish(all)&&FrameSurvey::ResolveGraphicsBindings(bindings,1,reads,out)&&FrameSurvey::ResolveComputeBindings(bindings,1,reads,out),"same ALL layout independently resolves both shader families");
 {FrameSurvey::ScopedInternal injection;need(FrameSurvey::ResolveComputeBindings(bindings,2,writes,out)&&FrameSurvey::ValidateGraphicsConstantBinding(bindings,6,0,staged),"explicit exact snapshots remain usable inside final injection guard");}
 // Source-free table b6 does not inspect descriptor contents or source buffers.
 auto tableLayout=pixel;tableLayout.pixelDescriptors.clear();tableLayout.tables[0]={{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,0,UINT_MAX,6,0}};tableLayout.pixelVisibleTables.insert(0);
 need(publish(tableLayout),"pixel CBV table layout published");auto table=bindings;table.views.clear();table.tables.push_back({0,{ph.gpu+20*ph.increment}});
 need(FrameSurvey::ResolveGraphicsConstantBinding(table,6,0,cbv)&&!cbv.address&&cbv.descriptorHeap==h&&cbv.descriptor.ptr==ph.gpu+20*ph.increment,"unrecorded volatile table b6 needs exact native heap/handle only");
 wrong=table;wrong.tables.back().second.ptr+=1;need(!FrameSurvey::ResolveGraphicsConstantBinding(wrong,6,0,cbv),"unaligned native CBV table fails");
 need(publish(pixel),"pixel root restored");
 std::array<FrameSurvey::ComputeTableRequest,9> many{};
 for(UINT i=0;i<9;++i){FrameSurvey::View(i&1?b:a,{ph.cpu+(32+i)*ph.increment},&srv);many[i]={D3D12_DESCRIPTOR_RANGE_TYPE_SRV,32+i,40+i,0};}
 need(FrameSurvey::ResolveGraphicsBindings(bindings,1,{many.data(),8},out)&&out.size()==8&&out.front().resource==a&&out.back().resource==b,"exact maximum eight explicit pixel requests preserve order");
 need(!FrameSurvey::ResolveGraphicsBindings(bindings,1,many,out)&&out.empty()&&!FrameSurvey::ResolveComputeBindings(bindings,2,{},out),"ninth and empty explicit requests fail without partial output");
 {NrdBridgeBirth::ScopedRelease pending(rb);need(!FrameSurvey::ResolveGraphicsBindings(bindings,1,reads,out)&&!FrameSurvey::ResolveGraphicsConstantBinding(bindings,6,0,cbv),"physical root release in flight rejects pixel metadata and CBV");}
 {NrdBridgeBirth::ScopedRelease pending(hb);need(!FrameSurvey::ResolveComputeBindings(bindings,2,writes,out)&&!FrameSurvey::ResolveGraphicsBindings(bindings,1,reads,out),"physical heap release in flight rejects both explicit table families");}
 FrameSurvey::View(b,{ph.cpu+3*ph.increment},&srv);
 need(FrameSurvey::ResolveGraphicsBindings(bindings,1,reads,out)&&out[0].resource==b,"current volatile SRV overwrite is observed, never stale output identity");
 FrameSurvey::View(b,{ph.cpu+8*ph.increment},&uav);need(FrameSurvey::ResolveComputeBindings(bindings,2,writes,out)&&out[0].resource==b,"post-wait compute UAV overwrite is re-resolved");
 FrameSurvey::RetirementEffects dead;retire(bb,dead);need(!FrameSurvey::ResolveGraphicsBindings(bindings,1,reads,out)&&out.empty()&&!FrameSurvey::ResolveComputeBindings(bindings,2,writes,out),"retired texture cannot survive either explicit resource resolver");FrameSurvey::NotifyRelease(dead);
 need(FrameSurvey::MetadataHealthy()&&NrdBridgeBirth::Healthy(),"expected binding rejection preserves global health");FrameSurvey::Shutdown();
 J report{{"checks",checks},{"GPU_devices",0},{"GPU_dispatches",0},{"scope","actual CPU root decoder and full FrameSurvey/Birth metadata; only stack BlobRoot reaches COM"}};
 std::ofstream(argv[1])<<report.dump(2)<<'\n';std::cout<<report.dump()<<'\n';return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
'''


def prepare(output):
    prefix = metadata.native.CPP.split('// The exact production hook bodies', 1)[0]
    helpers = metadata.DRIVER.split('int main(', 1)[0]
    source = PRELUDE+prefix.replace('__TRACE__', (ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp').as_posix())
    source = source.replace('__SURVEY__', (ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').as_posix())+helpers+DRIVER
    output.mkdir(parents=True, exist_ok=True)
    stubs = output/'stubs'
    files = {'pch.h': '#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n#define LOG_INFO(...) ((void)0)\n#define LOG_ERROR(...) ((void)0)\n',
             'Util.h': '#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;namespace Util {inline auto DllPath(){return g_dllPath;}}\n',
             'inputs/NVNGX_DLSS.h': '#pragma once\n#include <nvsdk_ngx.h>\n',
             'proxies/D3D12_Proxy.h': '#pragma once\n#include <d3d12.h>\nnamespace D3d12Proxy {inline auto D3D12CreateVersionedRootSignatureDeserializer_(){return &D3D12CreateVersionedRootSignatureDeserializer;}inline auto D3D12SerializeVersionedRootSignature_(){return &D3D12SerializeVersionedRootSignature;}}\n'}
    for name, text in files.items():
        path = stubs/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    path = output/'graphics_bindings.cpp'
    path.write_text(source)
    info = {'production_root': str(ROOT), 'production_source_sha256': hashlib.sha256((ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').read_bytes()).hexdigest()}
    (output/'source.json').write_text(json.dumps(info, indent=2)+'\n')
    return path, stubs, info


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15a-motion/graphics-bindings'))
    source, stubs, info = prepare(output)
    if args.prepare_only:
        print(json.dumps(info))
        return
    exe = output/'graphics_bindings.exe'
    compile_cpp(source, exe, ('d3d12.lib', 'dxgi.lib', 'dxguid.lib', 'd3dcompiler.lib', 'bcrypt.lib', 'user32.lib', 'psapi.lib', str(ROOT/'OptiScaler/library/detours/detours.lib')),
                (stubs, ROOT/'OptiScaler', ROOT/'OptiScaler/resource_tracking', ROOT/'OptiScaler/include', ROOT/'external/streamline', ROOT/'external/nlohmann', ROOT/'external/nvngx_dlss_sdk', ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
    process = subprocess.run([str(exe), str(output/'result.json')], capture_output=True, text=True, timeout=90,
                             creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    (output/'native.log').write_text(process.stdout+process.stderr)
    process.check_returncode()
    result = json.loads((output/'result.json').read_text())
    result.update(info)
    (output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    run()
