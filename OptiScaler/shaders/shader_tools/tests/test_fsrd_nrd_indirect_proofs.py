"""CPU-only actual FrameSurvey signature/stage/texture admission proofs.

Uses real production parsing, hashing, metadata publication, resolution and Birth
retirement. Native GUID preparation remains deliberately unconfigured: opaque
addresses only enter explicit POD publication; the sole COM fixture is an owned
CPU pipeline metadata sink and the existing CPU root-blob decoder. No GPU device
is created. Native descriptor/Execute serialization is a separate actual-header
regression; point-in-time witnesses alone do not serialize native writes.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_fsrd_nrd_graphics_bindings as graphics

ROOT = graphics.ROOT
CPP = r'''
namespace NrdBridge {
bool StartupEnabled()noexcept{return false;}
DispatchDisposition OriginalDispatchDisposition(ID3D12GraphicsCommandList*,DispatchKind)noexcept{return DispatchDisposition::Forward;}
void InvalidateRecordingProof(ID3D12GraphicsCommandList*,const char*)noexcept{}
bool PreserveIndirectRecording(ID3D12GraphicsCommandList*,ID3D12CommandSignature*)noexcept{return false;}
}
__ROOT_HELPERS__
struct CpuPipeline final:ID3D12PipelineState {
 unsigned stores=0;
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID,void** out)override{*out=nullptr;return E_NOINTERFACE;}
 ULONG STDMETHODCALLTYPE AddRef()override{throw std::runtime_error("metadata must not retain title pipeline");}
 ULONG STDMETHODCALLTYPE Release()override{throw std::runtime_error("metadata must not release title pipeline");}
 HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID,UINT*,void*)override{return E_NOTIMPL;}
 HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID,UINT,const void*)override{need(!NrdBridgeBirth::InMetadataScope(),"native metadata sink is outside every Birth guard");++stores;return S_OK;}
 HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID,const IUnknown*)override{return E_NOTIMPL;}
 HRESULT STDMETHODCALLTYPE SetName(LPCWSTR)override{return S_OK;}
 HRESULT STDMETHODCALLTYPE GetDevice(REFIID,void** out)override{*out=nullptr;throw std::runtime_error("no pipeline device query");}
 HRESULT STDMETHODCALLTYPE GetCachedBlob(ID3DBlob** out)override{*out=nullptr;return E_NOTIMPL;}
};
NrdBridgeBirth::Token pipelineBirth(CpuPipeline& pipeline,uint64_t stamp){
 // Explicit caller-strong metadata adapter. The actual native GUID/coverage
 // wrapper is covered elsewhere; no synthetic address may reach that wrapper.
 auto token=born(&pipeline,stamp);std::scoped_lock lock(FrameSurvey::gLifetimeMutex);
 FrameSurvey::gPipelineBirths[&pipeline]=token;return token;
}
int main(int argc,char** argv)try{
 need(argc==2,"report argument");FrameSurvey::BeginCreationTracking(false);
 need(!NrdBridgeNativeBirth::Ready(),"native GUID preparation remains unconfigured for POD fixtures");
 need(NrdBridgeBirth::ConfigureActions({detach,identity,nullptr}),"actual Birth retirement dispatcher configured");
 auto layout=decoded(D3D12_SHADER_VISIBILITY_ALL);
 auto* r=reinterpret_cast<ID3D12RootSignature*>(0x150000);auto rb=born(r,501);
 auto* h=reinterpret_cast<ID3D12DescriptorHeap*>(0x160000);auto hb=born(h,502);auto ph=heap(h);
 auto* a=reinterpret_cast<ID3D12Resource*>(0x170000);auto ab=born(a,503);
 auto* b=reinterpret_cast<ID3D12Resource*>(0x180000);auto bb=born(b,504);
 auto pa=buffer(a,0);pa.description.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;pa.description.Width=128;pa.description.Height=64;
 pa.description.MipLevels=2;pa.description.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;pa.description.Layout=D3D12_TEXTURE_LAYOUT_UNKNOWN;
 pa.description.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;auto pb=pa;pb.object=b;
 need(FrameSurvey::PublishResourceMetadata(pa,ab)&&FrameSurvey::PublishResourceMetadata(pb,bb)&&FrameSurvey::PublishHeapMetadata(ph,hb),"actual texture and heap metadata publication");
 const auto publish=[&](const FrameSurvey::RootLayout& value){return FrameSurvey::PublishRootMetadata({r,std::make_shared<FrameSurvey::RootLayout>(value)},rb);};
 need(publish(layout),"actual decoded ALL root cold register index publication");
 D3D12_SHADER_RESOURCE_VIEW_DESC srv{};srv.Format=pa.description.Format;srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
 srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;srv.Texture2D.MipLevels=1;
 D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};uav.Format=pa.description.Format;uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
 for(UINT i=0;i<14;++i)FrameSurvey::View(i&1?b:a,{ph.cpu+i*ph.increment},&srv);
 FrameSurvey::View(a,{ph.cpu+32*ph.increment},&uav);FrameSurvey::View(b,{ph.cpu+33*ph.increment},&uav);
 FrameSurvey::ComputeBindings bindings;bindings.root=r;bindings.rootBirth=rb;bindings.heaps={h};bindings.heapBirths={hb};
 bindings.tables={{1,{ph.gpu}},{2,{ph.gpu+32*ph.increment}}};
 std::vector<FrameSurvey::TextureTableRequest> rows;
 for(UINT i=0;i<7;++i)rows.push_back({UINT_MAX,{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,UINT_MAX,8+i,0}});
 rows.push_back({UINT_MAX,{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,UINT_MAX,0,0}});rows.push_back({UINT_MAX,{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,UINT_MAX,1,0}});
 std::vector<FrameSurvey::BoundResource> out;std::vector<FrameSurvey::TextureBindingWitness> proof;
 FrameSurvey::SetBindingWindow(false);
 need(FrameSurvey::ResolveComputeTextureBindings(bindings,rows,out,&proof)&&out.size()==9&&proof.size()==9,"all nine used CS textures resolve coherently with bridge window closed");
 need(out.front().resource==a&&out[1].resource==b&&out[7].resource==a&&out[8].resource==b,"coherent snapshot preserves mixed SRV/UAV request order");
 need(proof[0].rootParameter==1&&proof[0].descriptorOffset==0&&proof[7].rootParameter==2&&proof[8].descriptorOffset==1,"auto lookup derives actual native root parameters and table offsets");
 need((out.front().description.Flags&(D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET|D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL))==0,"same coherent resource description proves no RTV or DSV target alias");
 const auto staged=proof;
 need(FrameSurvey::ValidateTextureBindingWitnesses(staged),"current mixed-table exact witnesses validate");
 auto wrong=rows;wrong[0].binding.registerSpace=1;need(!FrameSurvey::ResolveComputeTextureBindings(bindings,wrong,out,&proof)&&out.empty()&&proof.empty(),"wrong register space yields no partial vectors");
 wrong=rows;wrong[0].rootParameter=1;need(!FrameSurvey::ResolveComputeTextureBindings(bindings,wrong,out),"mixed explicit and unspecified mapping rejects");
 wrong=rows;wrong[0].rootParameter=1;wrong[0].binding.descriptorOffset=0;need(FrameSurvey::ResolveComputeTextureBindings(bindings,wrong,out),"explicit mapping agrees with cold unique register index");
 wrong[0].binding.descriptorOffset=1;need(!FrameSurvey::ResolveComputeTextureBindings(bindings,wrong,out),"wrong explicit offset cannot masquerade as shader register");
 wrong=rows;wrong[1]=wrong[0];need(!FrameSurvey::ResolveComputeTextureBindings(bindings,wrong,out),"duplicate used register rejects");
 auto bindingWrong=bindings;bindingWrong.tables.push_back(bindingWrong.tables[0]);need(!FrameSurvey::ResolveComputeTextureBindings(bindingWrong,rows,out),"duplicate native table argument rejects");
 bindingWrong=bindings;bindingWrong.tables.erase(bindingWrong.tables.begin());need(!FrameSurvey::ResolveComputeTextureBindings(bindingWrong,rows,out),"missing native table is never evidence of shader absence");
 bindingWrong=bindings;bindingWrong.heapBirths.clear();need(!FrameSurvey::ResolveComputeTextureBindings(bindingWrong,rows,out),"missing heap birth rejects exact native proof");
 std::vector<FrameSurvey::TextureTableRequest> maximum;
 for(UINT i=0;i<14;++i)maximum.push_back({UINT_MAX,{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,UINT_MAX,8+i,0}});
 maximum.push_back(rows[7]);maximum.push_back(rows[8]);
 need(FrameSurvey::ResolveComputeTextureBindings(bindings,maximum,out,&proof)&&out.size()==16&&proof.size()==16,"sixteen exact used slots is accepted as one snapshot");
 maximum.push_back(rows[0]);need(!FrameSurvey::ResolveComputeTextureBindings(bindings,maximum,out,&proof)&&out.empty()&&proof.empty(),"seventeenth slot rejects before partial admission");
 need(!FrameSurvey::ResolveComputeTextureBindings(bindings,{},out)&&!FrameSurvey::ValidateTextureBindingWitnesses({}),"empty proof does not infer zero shader resources");
 std::vector<FrameSurvey::TextureBindingWitness> retained(324,staged.front());
 need(FrameSurvey::ValidateTextureBindingWitnesses(retained),"exact maximum 324 repeated identical retained slots validates");
 retained.push_back(staged.front());need(!FrameSurvey::ValidateTextureBindingWitnesses(retained),"retained witness overflow is rejected");
 need(!FrameSurvey::ResolveGraphicsTextureBindings(bindings,rows,out),"pixel proof never admits UAV requests");
 need(FrameSurvey::ResolveGraphicsTextureBindings(bindings,{rows.data(),7},out,&proof)&&proof.size()==7&&proof[0].pixel,"ALL root independently proves pixel-visible exact SRVs");
 auto pixel=decoded(D3D12_SHADER_VISIBILITY_PIXEL);need(publish(pixel),"pixel-only root published");
 need(!FrameSurvey::ResolveComputeTextureBindings(bindings,{rows.data(),7},out)&&FrameSurvey::ResolveGraphicsTextureBindings(bindings,{rows.data(),7},out),"pixel-only root rejects compute proof");
 need(publish(layout),"ALL root restored");
 auto ambiguous=layout;ambiguous.computeVisibleTables.insert(7);ambiguous.tables[7]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,0,1,8,0}};
 need(publish(ambiguous)&&!FrameSurvey::ResolveComputeTextureBindings(bindings,rows,out),"overlapping visible register mappings reject auto resolution");
 need(publish(layout),"unambiguous root restored");
 {NrdBridgeBirth::ScopedRelease pending(rb);need(!FrameSurvey::ResolveComputeTextureBindings(bindings,rows,out)&&!FrameSurvey::ValidateTextureBindingWitnesses(staged),"root physical release in flight rejects query and retained proof");}
 {NrdBridgeBirth::ScopedRelease pending(hb);need(!FrameSurvey::ValidateTextureBindingWitnesses(staged),"heap physical release in flight rejects retained proof");}
 {NrdBridgeBirth::ScopedRelease pending(ab);need(!FrameSurvey::ValidateTextureBindingWitnesses(staged),"resource physical release in flight rejects retained proof");}
 FrameSurvey::View(b,{ph.cpu+900*ph.increment},&srv);need(FrameSurvey::ValidateTextureBindingWitnesses(staged),"unrelated slot changes do not globally invalidate retained proof");
 FrameSurvey::View(b,{ph.cpu},&srv);need(!FrameSurvey::ValidateTextureBindingWitnesses(staged),"actual used descriptor mutation invalidates old resource identity");
 FrameSurvey::View(a,{ph.cpu},&srv);need(FrameSurvey::ValidateTextureBindingWitnesses(staged),"exact restored descriptor content is admissible");
 FrameSurvey::View(a,{ph.cpu},&uav);need(!FrameSurvey::ValidateTextureBindingWitnesses(staged),"changed descriptor type rejects");FrameSurvey::View(a,{ph.cpu},&srv);
 auto mip=srv;mip.Texture2D.MostDetailedMip=1;FrameSurvey::View(a,{ph.cpu},&mip);
 need(!FrameSurvey::ValidateTextureBindingWitnesses(staged),"changed actual subresource rejects");FrameSurvey::View(a,{ph.cpu},&srv);
 auto format=srv;format.Format=DXGI_FORMAT_R16G16B16A16_UNORM;FrameSurvey::View(a,{ph.cpu},&format);
 need(!FrameSurvey::ValidateTextureBindingWitnesses(staged),"changed typed view format rejects");FrameSurvey::View(a,{ph.cpu},&srv);
 auto array=srv;array.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2DARRAY;array.Texture2DArray={};array.Texture2DArray.MipLevels=1;array.Texture2DArray.ArraySize=1;
 FrameSurvey::View(a,{ph.cpu},&array);const std::array<FrameSurvey::ComputeTableRequest,1> oldQuery{{{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,0,8,0}}};
 need(FrameSurvey::ResolveComputeBindings(bindings,1,oldQuery,out),"old eight-slot snapshot API retains one-slice-array semantics");
 need(!FrameSurvey::ResolveComputeTextureBindings(bindings,rows,out)&&!FrameSurvey::ValidateTextureBindingWitnesses(staged),"new exact Texture2D proof rejects one-slice array view");
 FrameSurvey::View(a,{ph.cpu},static_cast<const D3D12_SHADER_RESOURCE_VIEW_DESC*>(nullptr));need(FrameSurvey::ValidateTextureBindingWitnesses(staged),"default single-slice Texture2D view dimension is proven from immutable description");
 // Multiple roots/heaps and repeated slots are valid in one retained batch.
 auto* r2=reinterpret_cast<ID3D12RootSignature*>(0x190000);auto rb2=born(r2,505);
 auto* h2=reinterpret_cast<ID3D12DescriptorHeap*>(0x1a0000);auto hb2=born(h2,506);auto ph2=heap(h2);ph2.cpu+=0x100000;ph2.gpu+=0x100000;
 need(FrameSurvey::PublishRootMetadata({r2,std::make_shared<FrameSurvey::RootLayout>(layout)},rb2)&&FrameSurvey::PublishHeapMetadata(ph2,hb2),"second root and independent heap publish");
 FrameSurvey::View(b,{ph2.cpu},&srv);auto other=bindings;other.root=r2;other.rootBirth=rb2;other.heaps={h2};other.heapBirths={hb2};other.tables={{1,{ph2.gpu}}};
 need(FrameSurvey::ResolveComputeTextureBindings(other,{rows.data(),1},out,&proof),"second coherent native root snapshot resolves");
 proof.insert(proof.end(),staged.begin(),staged.end());need(FrameSurvey::ValidateTextureBindingWitnesses(proof),"retained witness batch may span multiple roots and heaps");
 FrameSurvey::RetirementEffects deadResource;retire(ab,deadResource);auto freshA=born(a,507);need(FrameSurvey::PublishResourceMetadata(pa,freshA),"resource address reuse publishes a different exact birth");
 for(UINT i=0;i<14;i+=2)FrameSurvey::View(a,{ph.cpu+i*ph.increment},&srv);FrameSurvey::View(a,{ph.cpu+32*ph.increment},&uav);
 need(!FrameSurvey::ValidateTextureBindingWitnesses(staged)&&FrameSurvey::ResolveComputeTextureBindings(bindings,rows,out,&proof)&&proof[0].resourceBirth==freshA,"same descriptor and pointer cannot hide resource ABA");
 FrameSurvey::NotifyRelease(deadResource);need(FrameSurvey::ValidateTextureBindingWitnesses(proof),"late old resource notification preserves new birth proof");
 // Actual no-root-argument classifier and publication/retirement methods.
 D3D12_INDIRECT_ARGUMENT_DESC arguments[2]{};arguments[0].Type=D3D12_INDIRECT_ARGUMENT_TYPE_DISPATCH;
 D3D12_COMMAND_SIGNATURE_DESC sigDesc{12,1,arguments,0};
 need(FrameSurvey::ClassifyIndirectSignature(sigDesc,nullptr)==FrameSurvey::IndirectSignatureKind::Dispatch,"exact single DISPATCH stride12 classifier");
 arguments[0].Type=D3D12_INDIRECT_ARGUMENT_TYPE_DRAW_INDEXED;sigDesc.ByteStride=20;
 need(FrameSurvey::ClassifyIndirectSignature(sigDesc,nullptr)==FrameSurvey::IndirectSignatureKind::DrawIndexed,"exact single DRAW_INDEXED stride20 classifier");
 sigDesc.ByteStride=24;need(FrameSurvey::ClassifyIndirectSignature(sigDesc,nullptr)==FrameSurvey::IndirectSignatureKind::Unknown,"padded unsupported stride rejects");
 sigDesc.ByteStride=12;arguments[0].Type=D3D12_INDIRECT_ARGUMENT_TYPE_DISPATCH;
 need(FrameSurvey::ClassifyIndirectSignature(sigDesc,r)==FrameSurvey::IndirectSignatureKind::Unknown,"nonnull root signature rejects signature proof");
 sigDesc.NumArgumentDescs=2;arguments[1].Type=D3D12_INDIRECT_ARGUMENT_TYPE_CONSTANT_BUFFER_VIEW;
 need(FrameSurvey::ClassifyIndirectSignature(sigDesc,nullptr)==FrameSurvey::IndirectSignatureKind::Unknown,"mixed root-mutating signature rejects");
 sigDesc.NumArgumentDescs=0;need(FrameSurvey::ClassifyIndirectSignature(sigDesc,nullptr)==FrameSurvey::IndirectSignatureKind::Unknown,"empty signature rejects");
 sigDesc.NumArgumentDescs=1;sigDesc.pArgumentDescs=nullptr;need(FrameSurvey::ClassifyIndirectSignature(sigDesc,nullptr)==FrameSurvey::IndirectSignatureKind::Unknown,"missing signature argument metadata rejects");sigDesc.pArgumentDescs=arguments;
 auto* signature=reinterpret_cast<ID3D12CommandSignature*>(0x1b0000);auto sb=born(signature,508);
 need(FrameSurvey::PublishIndirectSignatureMetadata({signature,FrameSurvey::ClassifyIndirectSignature(sigDesc,nullptr),12,sb}),"actual caller-strong signature POD publication");
 FrameSurvey::IndirectSignatureInfo info;need(FrameSurvey::ResolveIndirectSignature(signature,info)&&info.kind==FrameSurvey::IndirectSignatureKind::Dispatch&&FrameSurvey::ValidateIndirectSignature(info),"O(1) current exact-live signature proof");
 auto staleSig=info;info.byteStride=20;need(!FrameSurvey::ValidateIndirectSignature(info),"signature stride witness tamper rejects");
 {NrdBridgeBirth::ScopedRelease pending(sb);need(!FrameSurvey::ValidateIndirectSignature(staleSig),"signature physical release in flight rejects");}
 FrameSurvey::RetirementEffects deadSig;retire(sb,deadSig);need(!FrameSurvey::ResolveIndirectSignature(signature,info),"actual retirement removes exact signature metadata");
 auto freshSig=born(signature,509);need(FrameSurvey::PublishIndirectSignatureMetadata({signature,FrameSurvey::IndirectSignatureKind::Dispatch,12,freshSig})&&!FrameSurvey::ValidateIndirectSignature(staleSig),"same-address signature ABA rejects old token");
 FrameSurvey::NotifyRelease(deadSig);need(FrameSurvey::ResolveIndirectSignature(signature,info)&&info.birth==freshSig,"late old signature notification preserves current map");
 // Full native descriptor/stream paths hash bytes once into fixed-size identities.
 const uint8_t csBytes[]{1,2,3,4},vsBytes[]{5,6,7},psBytes[]{8,9},hsBytes[]{10},dsBytes[]{11};
 CpuPipeline cs,gfx,tess,stream,bad;auto csb=pipelineBirth(cs,510),gb=pipelineBirth(gfx,511),tb=pipelineBirth(tess,512),stb=pipelineBirth(stream,513),badb=pipelineBirth(bad,514);
 D3D12_COMPUTE_PIPELINE_STATE_DESC compute{};compute.CS={csBytes,sizeof(csBytes)};FrameSurvey::PipelineCreated(&cs,compute);
 FrameSurvey::PipelineShaderIdentity ci;need(FrameSurvey::ResolvePipelineShaderIdentity(&cs,ci)&&ci.complete&&ci.presentStages==FrameSurvey::PipelineCS&&std::string(ci.compute.data())=="__CS_SHA__","actual legacy compute creation has full attested fixed CS hash");
 D3D12_GRAPHICS_PIPELINE_STATE_DESC graphic{};graphic.VS={vsBytes,sizeof(vsBytes)};graphic.PS={psBytes,sizeof(psBytes)};FrameSurvey::PipelineCreated(&gfx,graphic);
 FrameSurvey::PipelineShaderIdentity gi;need(FrameSurvey::ResolvePipelineShaderIdentity(&gfx,gi)&&gi.presentStages==(FrameSurvey::PipelineVS|FrameSurvey::PipelinePS)&&std::string(gi.vertex.data())=="__VS_SHA__"&&std::string(gi.pixel.data())=="__PS_SHA__","actual legacy graphics descriptor proves full VS/PS and absent HS/DS/GS");
 auto altered=gi;altered.pixel[0]=altered.pixel[0]=='0'?'1':'0';need(!FrameSurvey::ValidatePipelineShaderIdentity(altered),"full pixel hash mismatch rejects");
 altered=gi;altered.presentStages|=FrameSurvey::PipelineGS;need(!FrameSurvey::ValidatePipelineShaderIdentity(altered),"stage-presence mismatch rejects");
 graphic.HS={hsBytes,sizeof(hsBytes)};graphic.DS={dsBytes,sizeof(dsBytes)};FrameSurvey::PipelineCreated(&tess,graphic);
 FrameSurvey::PipelineShaderIdentity ti;need(FrameSurvey::ResolvePipelineShaderIdentity(&tess,ti)&&(ti.presentStages&(FrameSurvey::PipelineHS|FrameSurvey::PipelineDS))==(FrameSurvey::PipelineHS|FrameSurvey::PipelineDS),"extra native graphics stages are explicit and cannot pass an empty-stage profile");
 struct Stream {CD3DX12_PIPELINE_STATE_STREAM_VS vs;CD3DX12_PIPELINE_STATE_STREAM_PS ps;} streamData;
 streamData.vs=D3D12_SHADER_BYTECODE{vsBytes,sizeof(vsBytes)};streamData.ps=D3D12_SHADER_BYTECODE{psBytes,sizeof(psBytes)};
 D3D12_PIPELINE_STATE_STREAM_DESC streamDesc{sizeof(streamData),&streamData};FrameSurvey::PipelineCreated(&stream,streamDesc);
 FrameSurvey::PipelineShaderIdentity si;need(FrameSurvey::ResolvePipelineShaderIdentity(&stream,si)&&si.vertex==gi.vertex&&si.pixel==gi.pixel&&si.presentStages==gi.presentStages,"successful full stream parser proves identical stage set and bytecode hashes");
 alignas(void*) D3D12_PIPELINE_STATE_SUBOBJECT_TYPE unsupported=static_cast<D3D12_PIPELINE_STATE_SUBOBJECT_TYPE>(UINT_MAX);
 D3D12_PIPELINE_STATE_STREAM_DESC badStream{sizeof(unsupported),&unsupported};FrameSurvey::PipelineCreated(&bad,badStream);
 FrameSurvey::PipelineShaderIdentity bi;need(!FrameSurvey::ResolvePipelineShaderIdentity(&bad,bi),"incomplete unsupported stream never proves absent stages");
 {NrdBridgeBirth::ScopedRelease pending(gb);need(!FrameSurvey::ValidatePipelineShaderIdentity(gi),"pipeline physical release in flight rejects");}
 FrameSurvey::RetirementEffects deadPipeline;retire(gb,deadPipeline);need(!FrameSurvey::ValidatePipelineShaderIdentity(gi),"actual pipeline retirement invalidates fixed identity");
 auto newGb=pipelineBirth(gfx,515);graphic.HS={};graphic.DS={};FrameSurvey::PipelineCreated(&gfx,graphic);
 need(FrameSurvey::ResolvePipelineShaderIdentity(&gfx,bi)&&bi.pipelineBirth==newGb&&!FrameSurvey::ValidatePipelineShaderIdentity(gi),"interned address recycled into fresh pipeline birth cannot hide ABA");FrameSurvey::NotifyRelease(deadPipeline);
 need(FrameSurvey::MetadataHealthy()&&NrdBridgeBirth::Healthy(),"expected proof rejection never poisons registry health");
 FrameSurvey::Shutdown();need(FrameSurvey::gIndirectSignatures.empty()&&FrameSurvey::gPipelineMetadata.empty(),"shutdown clears new signature and fixed pipeline metadata maps");
 J report{{"checks",checks},{"GPU_devices",0},{"GPU_dispatches",0},{"native_GUID_preparation",false},{"coherent_slot_limit",16},{"retained_slot_limit",324},
 {"scope","actual full FrameSurvey/Birth/root decoder and shader hash/parser paths; explicit caller-strong POD birth adapters; native descriptor submission serialization covered separately"}};
 std::ofstream(argv[1])<<report.dump(2)<<'\n';std::cout<<report.dump()<<'\n';return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
'''


def prepare(output):
    root_helpers = graphics.DRIVER.split('struct BlobRoot:', 1)[1].split('int main(', 1)[0]
    driver = CPP.replace('__ROOT_HELPERS__', 'struct BlobRoot:'+root_helpers)
    for name, data in [('CS', bytes([1, 2, 3, 4])), ('VS', bytes([5, 6, 7])), ('PS', bytes([8, 9]))]:
        driver = driver.replace(f'__{name}_SHA__', hashlib.sha256(data).hexdigest())
    saved = graphics.DRIVER
    try:
        graphics.DRIVER = driver
        source, stubs, info = graphics.prepare(output)
    finally:
        graphics.DRIVER = saved
    renamed = output/'indirect_proofs.cpp'
    source.rename(renamed)
    info['frame_survey_header_sha256'] = hashlib.sha256((ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.h').read_bytes()).hexdigest()
    return renamed, stubs, info


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15a-motion/indirect-proofs'))
    source, stubs, info = prepare(output)
    if args.prepare_only:
        print(json.dumps(info))
        return
    exe = output/'indirect_proofs.exe'
    graphics.compile_cpp(source, exe, ('d3d12.lib', 'dxgi.lib', 'dxguid.lib', 'd3dcompiler.lib', 'bcrypt.lib', 'user32.lib', 'psapi.lib', str(ROOT/'OptiScaler/library/detours/detours.lib')),
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
