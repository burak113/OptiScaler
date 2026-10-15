"""Actual FrameSurvey POD publication/retirement with real Birth registry guards.

CPU-only metadata emulation: opaque addresses never reach COM. Native GUID and
physical Release forwarding are covered by the separate native helper fixtures.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_fsrd_frame_survey_game_scale as native

DRIVER = r'''
namespace NrdBridgeNativeBirth {
bool ObserveReleaseCoverage(IUnknown*) noexcept { if(Ready())std::terminate();return false; }
}
thread_local FrameSurvey::RetirementEffects* currentEffects=nullptr;
std::atomic<unsigned> notifications{0},ignoredOld{0},accepted{0};
NrdBridgeBirth::Token expected;
bool detach(void*,const NrdBridgeBirth::Token& old)noexcept{
 if(!currentEffects||!NrdBridgeBirth::InMetadataAction())return false;
 return FrameSurvey::DetachReleaseMetadata(old,*currentEffects);
}
bool identity(void*,const NrdBridgeBirth::Token&)noexcept{return true;}
void observe(const NrdBridgeBirth::Token& old)noexcept{
 if(NrdBridgeBirth::InMetadataScope())std::terminate();
 ++notifications;if(old==expected)++accepted;else++ignoredOld;
 // A different thread proves that Notify does not hold catalog or mirror locks.
 std::jthread check([]{std::scoped_lock both(FrameSurvey::gLifetimeMutex,FrameSurvey::gMirrorMutex);});check.join();
}
NrdBridgeBirth::Token born(void* object,uint64_t stamp){
 auto result=NrdBridgeBirth::ObserveInstance(object,stamp);need(bool(result),"actual registry observes explicit synthetic instance stamp");return result;
}
void retire(const NrdBridgeBirth::Token& old,FrameSurvey::RetirementEffects& effects){
 need(FrameSurvey::PrepareRetirementEffects(effects),"detached owner prepared outside every Birth guard");currentEffects=&effects;
 {NrdBridgeBirth::CurrentGuard guard(old);need(guard.Retire(),"actual current guard invokes pure FrameSurvey detach");}
 currentEffects=nullptr;
}
FrameSurvey::PreparedResource buffer(ID3D12Resource* object,uint64_t address){
 FrameSurvey::PreparedResource p;p.object=object;p.address=address;p.description.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
 p.description.Width=8192;p.description.Height=1;p.description.DepthOrArraySize=p.description.MipLevels=1;
 p.description.SampleDesc.Count=1;p.description.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;return p;
}
FrameSurvey::PreparedHeap heap(ID3D12DescriptorHeap* object,bool sampler=false){
 FrameSurvey::PreparedHeap p;p.object=object;p.cpu=sampler?0x500000:0x300000;p.gpu=sampler?0x600000:0x400000;
 p.increment=sampler?16:32;p.description.Type=sampler?D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER:D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
 p.description.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;p.description.NumDescriptors=1024;return p;
}
FrameSurvey::PreparedRoot root(ID3D12RootSignature* object){
 auto layout=std::make_shared<FrameSurvey::RootLayout>();layout->complete=true;layout->hash="synthetic_layout_only";
 layout->computeVisibleTables={1,2};layout->tables[1]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,0,UINT_MAX,0,0}};
 layout->tables[2]={{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,0,UINT_MAX,6,0}};
 return {object,layout};
}
int main(int argc,char** argv)try{
 need(argc==2,"output argument");SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);
 need(!NrdBridgeNativeBirth::Ready(),"native helper intentionally unconfigured: no opaque address may reach COM");
 FrameSurvey::BeginCreationTracking(false);FrameSurvey::SetBindingWindow(true);FrameSurvey::SetBirthReleaseObserver(&observe);
 need(NrdBridgeBirth::ConfigureActions({detach,identity,nullptr}),"actual process registry dispatcher configured");
 auto* a=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x10000));auto* t=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x20000));
 auto* h=reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(0x30000));auto* s=reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(0x40000));
 auto* r=reinterpret_cast<ID3D12RootSignature*>(uintptr_t(0x50000));auto* c=reinterpret_cast<ID3D12GraphicsCommandList*>(uintptr_t(0x60000));
 auto ab=born(a,101),tb=born(t,102),hb=born(h,103),sb=born(s,104),rb=born(r,105),cb=born(c,106);
 auto pa=buffer(a,0x100000);need(FrameSurvey::PublishResourceMetadata(pa,ab),"current buffer POD publication has no native getter");
 auto pt=pa;pt.object=t;pt.address=0;pt.description.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
 pt.description.Width=128;pt.description.Height=64;pt.description.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;pt.description.Layout=D3D12_TEXTURE_LAYOUT_UNKNOWN;
 need(FrameSurvey::PublishResourceMetadata(pt,tb),"texture POD publication");
 auto ph=heap(h),ps=heap(s,true);auto pr=root(r);
 need(FrameSurvey::PublishHeapMetadata(ph,hb)&&FrameSurvey::PublishHeapMetadata(ps,sb),"CBV and SAMPLER heap birth metadata publication");
 need(FrameSurvey::PublishRootMetadata(pr,rb),"unbounded raw root layout POD publication");
 D3D12_SHADER_RESOURCE_VIEW_DESC srv{};srv.Format=pt.description.Format;srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
 srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;srv.Texture2D.MipLevels=1;
 FrameSurvey::View(t,{ph.cpu},&srv);D3D12_CONSTANT_BUFFER_VIEW_DESC cv{pa.address,1536};FrameSurvey::View({ph.cpu+ph.increment},&cv);
 FrameSurvey::ComputeBindings bindings;bindings.root=r;bindings.heaps={h,s};bindings.tables={{1,{ph.gpu}},{2,{ph.gpu+ph.increment}}};
 bindings.receiverBirth=cb;bindings.rootBirth=rb;bindings.heapBirths={hb,sb};
 need(FrameSurvey::SeedComputeBindings(c,bindings),"sparse born seeding includes actual receiver/root and two heap nodes");
 const std::array<FrameSurvey::ComputeTableRequest,1> query{{{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,0,0,0}}};std::vector<FrameSurvey::BoundResource> textures;
 need(FrameSurvey::ResolveComputeBindings(c,1,query,textures)&&textures.size()==1&&textures[0].resource==t&&textures[0].resourceBirth==tb,"bounded unbounded-table proof returns exact resource birth");
 need(!FrameSurvey::ResolveComputeTable(c,1,textures),"original whole-table unbounded rejection remains unchanged");
 FrameSurvey::BoundConstantBuffer staged;FrameSurvey::BoundConstantBinding nativeBinding;
 need(FrameSurvey::ResolveComputeConstantBuffer(c,6,0,1216,staged)&&staged.resourceBirth==ab&&staged.descriptorHeapBirth==hb,"b6 root/table owner and heap births resolved");
 need(FrameSurvey::ValidateBorrowedConstantBuffer(staged),"current staged CBV born metadata validates");
 need(FrameSurvey::ResolveComputeConstantBinding(bindings,6,0,nativeBinding)&&nativeBinding.rootBirth==rb&&nativeBinding.descriptorHeapBirth==hb,"native volatile CB6 binding carries exact root/heap births");
 {
  NrdBridgeBirth::ScopedRelease release(ab);
  need(!FrameSurvey::ValidateBorrowedConstantBuffer(staged),"weak borrowed CBV rejects physical Release in flight");
  need(FrameSurvey::PublishResourceMetadata(pa,ab),"caller-strong POD publisher permits current same-instance pending Release");
 }
 FrameSurvey::RetirementEffects old;retire(ab,old);need(notifications.load()==0,"pure retirement never invokes observer under registry locks");
 need(!FrameSurvey::gResources.contains(a)&&!FrameSurvey::gViews.contains(ph.cpu+ph.increment),"actual retired buffer indexed slots removed");
 auto fresh=born(a,201);pa.address+=0x100000;need(FrameSurvey::PublishResourceMetadata(pa,fresh),"reused address new instance publication");
 cv.BufferLocation=pa.address;FrameSurvey::View({ph.cpu+ph.increment},&cv);expected=fresh;
 FrameSurvey::NotifyRelease(old);need(ignoredOld.load()==1&&accepted.load()==0&&FrameSurvey::gResources.at(a).birth==fresh,"late old notification cannot erase new address birth");
 need(!FrameSurvey::ValidateBorrowedConstantBuffer(staged),"old resource/VA generation remains rejected after address reuse");
 need(FrameSurvey::SeedComputeBindings(c,bindings),"persistent current tables seed without recopy");
 FrameSurvey::BoundConstantBuffer current;need(FrameSurvey::ResolveComputeConstantBuffer(c,6,0,1216,current)&&current.resourceBirth==fresh,"new b6 mapping resolves current resource");
 FrameSurvey::RetirementEffects oldHeap;retire(hb,oldHeap);need(!FrameSurvey::ValidateBorrowedConstantBuffer(current),"retired table heap invalidates staged CBV");
 auto newHeap=born(h,202);need(FrameSurvey::PublishHeapMetadata(ph,newHeap),"native heap address/range reuse gets another exact birth");
 bindings.heapBirths[0]=newHeap;FrameSurvey::View({ph.cpu+ph.increment},&cv);FrameSurvey::View(t,{ph.cpu},&srv);
 need(FrameSurvey::SeedComputeBindings(c,bindings),"new heap token seeds borrowed bindings");
 need(!FrameSurvey::ValidateComputeConstantBinding(bindings,6,0,nativeBinding),"same pointer/GPU slot never hides heap birth replacement");
 FrameSurvey::NotifyRelease(oldHeap);need(FrameSurvey::gHeaps.at(h).birth==newHeap,"old heap notification leaves new occupied-slot ownership");
 FrameSurvey::RetirementEffects oldRoot;retire(rb,oldRoot);auto newRoot=born(r,203);
 need(FrameSurvey::PublishRootMetadata(pr,newRoot),"root address reuse raw layout publication");bindings.rootBirth=newRoot;
 need(FrameSurvey::SeedComputeBindings(c,bindings)&&!FrameSurvey::ValidateComputeConstantBinding(bindings,6,0,nativeBinding),"same root pointer never hides root birth replacement");
 FrameSurvey::NotifyRelease(oldRoot);
 FrameSurvey::RetirementEffects oldReceiver;retire(cb,oldReceiver);auto newReceiver=born(c,204);bindings.receiverBirth=newReceiver;
 need(FrameSurvey::SeedComputeBindings(c,bindings),"new command-list address birth publishes fresh mirror");FrameSurvey::NotifyRelease(oldReceiver);
 need(FrameSurvey::gMirror.at(c).receiverBirth==newReceiver,"late old list cleanup preserves new mirror");
 need(!FrameSurvey::PublishResourceMetadata(pa,ab),"old creator token cannot publish over fresh resource");
 need(!FrameSurvey::SeedComputeBindings(c,FrameSurvey::ComputeBindings{r,{h,s},bindings.tables,{},cb,newRoot,{},bindings.heapBirths}),"old receiver token cannot republish a new mirror");
 need(FrameSurvey::MetadataHealthy()&&NrdBridgeBirth::Healthy(),"expected old-token denial does not poison global health");
 // Typed opaque CPU/GPU handle spaces may legitimately share numerical values.
 auto* overlapSampler=reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(0x70000));auto overlapBirth=born(overlapSampler,205);
 auto overlap=heap(overlapSampler,true);overlap.cpu=ph.cpu;overlap.gpu=ph.gpu;
 need(FrameSurvey::PublishHeapMetadata(overlap,overlapBirth),"same-numerical SAMPLER and resource heap metadata coexist");
 need(FrameSurvey::gCpuHeaps.size()==1&&FrameSurvey::gCpuHeaps.at(ph.cpu)==h,"SAMPLER identity never shadows resource-view CPU range");
 FrameSurvey::View(t,{ph.cpu},&srv);FrameSurvey::View({ph.cpu+ph.increment},&cv);
 need(FrameSurvey::gViews.at(ph.cpu).descriptorHeap==uint64_t(reinterpret_cast<uintptr_t>(h))&&FrameSurvey::gViews.at(ph.cpu+ph.increment).descriptorHeap==uint64_t(reinterpret_cast<uintptr_t>(h)),"SRV and CBV ownership still refers to the resource heap");
 auto overlapBindings=bindings;overlapBindings.heaps[1]=overlapSampler;overlapBindings.heapBirths[1]=overlapBirth;
 FrameSurvey::BoundConstantBuffer overlapCbv;
 need(FrameSurvey::SeedComputeBindings(c,overlapBindings)&&FrameSurvey::ResolveComputeConstantBuffer(c,6,0,1216,overlapCbv)&&overlapCbv.descriptorHeapBirth==newHeap,"b6 resolves with overlapping typed SAMPLER handles");
 need(FrameSurvey::ResolveComputeBindings(c,1,query,textures)&&textures.size()==1&&textures[0].resource==t,"bounded SRV proof ignores same-numerical SAMPLER GPU range");
 FrameSurvey::RetirementEffects samplerEffects;retire(overlapBirth,samplerEffects);
 need(!FrameSurvey::gHeaps.contains(overlapSampler)&&FrameSurvey::gHeaps.contains(h)&&FrameSurvey::gCpuHeaps.at(ph.cpu)==h&&FrameSurvey::gViews.contains(ph.cpu+ph.increment),"SAMPLER retirement removes only its exact object birth");
 need(FrameSurvey::ValidateBorrowedConstantBuffer(overlapCbv)&&FrameSurvey::SeedComputeBindings(c,bindings)&&FrameSurvey::ResolveComputeConstantBuffer(c,6,0,1216,current),"resource CBV survives SAMPLER-only retirement and fresh seeding");
 FrameSurvey::NotifyRelease(samplerEffects);
 // Failed metadata mutation under a guard is latched there and handled outside it.
 {NrdBridgeBirth::CurrentGuard guard(newReceiver);FrameSurvey::MetadataFailed("synthetic_deferred_fault");need(FrameSurvey::gDeferredMetadataFailure.load()!=nullptr,"fault notification deferred while metadata guard held");}
 FrameSurvey::FlushMetadataFailure();need(!FrameSurvey::MetadataHealthy()&&!FrameSurvey::gDeferredMetadataFailure.load(),"deferred fault drained outside metadata scope");
 FrameSurvey::Shutdown();need(FrameSurvey::gResources.empty()&&FrameSurvey::gMirror.empty(),"raw metadata/owner teardown complete");
 J report{{"checks",checks},{"source","actual_FrameSurvey_methods_with_actual_Birth_registry_metadata_emulation"},{"fake_objects_passed_to_COM",false},{"GPU_dispatches",0},{"native_GUID_protocol_tested",false}};
 std::ofstream(argv[1])<<report.dump(2)<<'\n';std::cout<<report.dump()<<'\n';return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
'''


def run(driver=DRIVER, report_name="birth-metadata-cpu.json", prelude="", *, descriptor_shards=32):
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    cpp = prelude + native.CPP[:native.CPP.index('// The exact production hook bodies')]
    cpp = cpp.replace('__TRACE__', (ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp').as_posix())
    assert descriptor_shards in (32,128)
    survey_path = ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp'
    metadata_original = (ROOT/'OptiScaler/resource_tracking/FrameSurveyConcurrentMetadata.h').read_text()
    metadata_compiled = metadata_original
    if descriptor_shards != 32:
        assert metadata_compiled.count('inline constexpr size_t DescriptorShards = 32;') == 1
        assert metadata_compiled.count('return size_t(slot >> 59);') == 1
        metadata_compiled = metadata_compiled.replace('inline constexpr size_t DescriptorShards = 32;', 'inline constexpr size_t DescriptorShards = 128;').replace('return size_t(slot >> 59);', 'return size_t(slot >> 57);')
        metadata_path = out/'FrameSurveyConcurrentMetadata.h'
        metadata_path.write_text(metadata_compiled, encoding='utf-8')
        survey_text = survey_path.read_text()
        assert survey_text.count('#include "FrameSurveyConcurrentMetadata.h"') == 1
        survey_text = survey_text.replace('#include "FrameSurveyConcurrentMetadata.h"', '#include "'+metadata_path.as_posix()+'"')
        survey_path = out/'FrameSurvey_heap_mask_fixture.cpp'
        survey_path.write_text(survey_text, encoding='utf-8')
    cpp = cpp.replace('__SURVEY__', survey_path.as_posix()) + driver
    stubs = out/'stubs'
    for name in ('proxies', 'inputs'):
        (stubs/name).mkdir(parents=True, exist_ok=True)
    (stubs/'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n#define LOG_INFO(...) ((void)0)\n#define LOG_ERROR(...) ((void)0)\n')
    (stubs/'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\nnamespace Util {inline std::filesystem::path DllPath(){return g_dllPath;}}\n')
    (stubs/'inputs/NVNGX_DLSS.h').write_text('#pragma once\n#include <nvsdk_ngx.h>\n')
    (stubs/'proxies/D3D12_Proxy.h').write_text('#pragma once\n#include <d3d12.h>\nnamespace D3d12Proxy {inline auto D3D12CreateVersionedRootSignatureDeserializer_(){return &D3D12CreateVersionedRootSignatureDeserializer;}inline auto D3D12SerializeVersionedRootSignature_(){return &D3D12SerializeVersionedRootSignature;}}\n')
    fixture, exe = out/'birth_metadata.cpp', out/'birth_metadata.exe'
    fixture.write_text(cpp, encoding='utf-8')
    compile_cpp(fixture, exe, ('d3d12.lib', 'dxgi.lib', 'dxguid.lib', 'd3dcompiler.lib', 'bcrypt.lib', 'user32.lib', 'psapi.lib', str(ROOT/'OptiScaler/library/detours/detours.lib')),
                (stubs, ROOT/'OptiScaler', ROOT/'OptiScaler/resource_tracking', ROOT/'OptiScaler/include', ROOT/'external/streamline', ROOT/'external/nlohmann', ROOT/'external/nvngx_dlss_sdk', ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
    result = subprocess.run([str(exe), str(out/'result.json')], capture_output=True, text=True, timeout=90, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    (out/'native.log').write_text(result.stdout+result.stderr)
    result.check_returncode()
    report = json.loads((out/'result.json').read_text())
    report['production_source_sha256'] = hashlib.sha256((ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').read_bytes()).hexdigest()
    report['source_commit'] = subprocess.check_output(['git', 'log', '-1', '--format=%H'], cwd=ROOT, text=True).strip()
    report['descriptor_shards'] = descriptor_shards
    report['metadata_header_source_sha256'] = hashlib.sha256(metadata_original.encode()).hexdigest()
    report['metadata_header_compiled_sha256'] = hashlib.sha256(metadata_compiled.encode()).hexdigest()
    directory = Path(os.environ.get('FSRD_TASK_REPORT_DIR', 'E:/FSRD/sol_batch/13a-lifetime'))
    directory.mkdir(parents=True, exist_ok=True)
    (directory/report_name).write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    run()
