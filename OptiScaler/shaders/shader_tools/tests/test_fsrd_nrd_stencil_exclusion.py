"""Actual native plane-1 stencil SRV in the nine-image indirect B interval."""
from pathlib import Path
import json
import os
import test_fsrd_nrd_native_transactions as native
from test_fsrd_nrd_bridge_rr import bounded_run, DLL
from fsrd_toolchain import compile_cpp

SETUP = r'''
 {
  // Genuine two-plane D32S8 texture and integer plane-1 SRV, not emulated metadata.
  D3D12_RESOURCE_DESC sd{};sd.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;sd.Width=title.width;sd.Height=title.height;
  sd.DepthOrArraySize=sd.MipLevels=sd.SampleDesc.Count=1;sd.Format=DXGI_FORMAT_R32G8X24_TYPELESS;
  sd.Flags=D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL;
  D3D12_HEAP_PROPERTIES hp{};hp.Type=D3D12_HEAP_TYPE_DEFAULT;
  D3D12_CLEAR_VALUE clear{};clear.Format=DXGI_FORMAT_D32_FLOAT_S8X24_UINT;clear.DepthStencil={1.f,7};
  hr(h.device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&sd,D3D12_RESOURCE_STATE_DEPTH_WRITE,&clear,IID_PPV_ARGS(&stencil)));
  NativeFixtureResourceCreated(stencil.Get(),D3D12_RESOURCE_STATE_DEPTH_WRITE);
  D3D12_DESCRIPTOR_HEAP_DESC dh{};dh.Type=D3D12_DESCRIPTOR_HEAP_TYPE_DSV;dh.NumDescriptors=1;
  hr(h.device->CreateDescriptorHeap(&dh,IID_PPV_ARGS(&depthViews)));
  D3D12_DEPTH_STENCIL_VIEW_DESC dsv{};dsv.Format=clear.Format;dsv.ViewDimension=D3D12_DSV_DIMENSION_TEXTURE2D;
  const auto depth=depthViews->GetCPUDescriptorHandleForHeapStart();h.device->CreateDepthStencilView(stencil.Get(),&dsv,depth);
  h.list->ClearDepthStencilView(depth,D3D12_CLEAR_FLAG_DEPTH|D3D12_CLEAR_FLAG_STENCIL,1.f,7,0,nullptr);
  h.barrier(stencil.Get(),D3D12_RESOURCE_STATE_DEPTH_WRITE,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  D3D12_SHADER_RESOURCE_VIEW_DESC sv{};sv.Format=DXGI_FORMAT_X32_TYPELESS_G8X24_UINT;sv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
  sv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;sv.Texture2D.MipLevels=1;sv.Texture2D.PlaneSlice=1;
  h.device->CreateShaderResourceView(stencil.Get(),&sv,Cpu(108));FrameSurvey::View(stencil.Get(),Cpu(108),&sv);
  h.list->SetComputeRootSignature(root.Get());h.list->SetPipelineState(pipeline.Get());
  ID3D12DescriptorHeap* heaps[]={title.visible.Get(),title.sampler.Get()};h.list->SetDescriptorHeaps(2,heaps);
  h.list->SetComputeRootDescriptorTable(0,Gpu(96));h.list->SetComputeRootDescriptorTable(1,Gpu(109));
  FrameSurvey::ComputeBindings exact;need(D3D12Hooks::GetComputeBindingsForBridge(h.list.Get(),exact),"stencil fixture has current native root/heap bindings");
  const std::array<FrameSurvey::TextureTableRequest,1> request{{{UINT_MAX,{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,UINT_MAX,12,0}}}};
  std::vector<FrameSurvey::BoundResource> resources;std::vector<FrameSurvey::TextureBindingWitness> witnesses;
  FrameSurvey::TextureBindingDiagnostic diagnostic;
  need(!FrameSurvey::ResolveComputeTextureBindings(exact,request,resources,&witnesses,FrameSurvey::TextureBindingPurpose::SnapshotSupportedView,&diagnostic),"default snapshot resolution still rejects a plane-1 view");
  need(std::string_view(diagnostic.reason)=="snapshot_unsupported"&&diagnostic.request==0&&diagnostic.shaderRegister==12&&diagnostic.registerSpace==0&&diagnostic.parameter==0&&diagnostic.descriptorOffset==12&&diagnostic.descriptorCpu==Cpu(108).ptr&&diagnostic.viewFormat==sv.Format&&!diagnostic.snapshotSupported&&diagnostic.texture2D,"first-failure diagnostic identifies the exact native stencil slot");
  need(FrameSurvey::ResolveComputeTextureBindings(exact,request,resources,&witnesses,FrameSurvey::TextureBindingPurpose::ResourceExclusion,&diagnostic)&&resources.size()==1&&witnesses.size()==1&&resources[0].resource==stencil.Get()&&witnesses[0].resourceExclusion&&std::string_view(diagnostic.reason)=="resolved","whole-resource exclusion resolves the exact live plane-1 resource");
  need(FrameSurvey::ValidateTextureBindingWitnesses(witnesses),"plane-1 exclusion witness remains valid at submission");
  witnesses[0].resourceExclusion=false;
  need(!FrameSurvey::ValidateTextureBindingWitnesses(witnesses),"an exclusion witness cannot authorize an ordinary image snapshot");
 }
'''

def run():
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    exe, command, keywords = native.prepare(out)
    source = command[0]
    text = source.read_text()
    start = text.index('struct OpaqueWork {')
    end = text.index('\nvoid RootChecks', start)
    opaque = text[start:end]
    old = 'ComPtr<ID3D12CommandSignature> signature;ComPtr<ID3D12Resource> arguments;'
    assert opaque.count(old) == 1
    opaque = opaque.replace(old, old+'ComPtr<ID3D12Resource> stencil;ComPtr<ID3D12DescriptorHeap> depthViews;')
    assert opaque.count('Texture2D<float4> T12:register(t12);') == 1
    opaque = opaque.replace('Texture2D<float4> T12:register(t12);','Texture2D<uint2> T12:register(t12);')
    assert opaque.count('+T12[p].rgb;') == 1
    opaque = opaque.replace('+T12[p].rgb;', '+float3(T12[p],0);')
    check = 'const auto values=read.signal();'
    assert opaque.count(check) == 1
    opaque = opaque.replace(check, check+r'''
  for(UINT c=0;c<3;++c){const float source=PackedVector::XMConvertHalfToFloat(PackedVector::XMConvertFloatToHalf(PackedVector::XMConvertHalfToFloat(title.raw[0][c])*.5f));
   need(values[c]==PackedVector::XMConvertFloatToHalf(6.f*source+(c==1?7.f:0.f)),"the actual indirect shader reads stencil value7 through the integer plane-1 SRV");}
''')
    marker = '  const D3D12_INDIRECT_ARGUMENT_DESC argument{D3D12_INDIRECT_ARGUMENT_TYPE_DISPATCH};'
    assert opaque.count(marker) == 1
    opaque = opaque.replace(marker, SETUP+'\n'+marker)
    text = text[:start]+opaque+text[end:]
    source.write_text(text)
    manifest_path = out/'source-preparation.json'
    manifest = json.loads(manifest_path.read_text())
    manifest.update(parent_generated_cpp_sha256=manifest['generated_cpp_sha256'],
                    generated_cpp_sha256=native.sha(source),stencil_driver_sha256=native.sha(__file__),
                    stencil_fixture='Actual D32S8 plane1 integer SRV; strict snapshot and exclusion controls')
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    prior = os.environ.get('CL')
    os.environ['CL'] = ((prior+' ') if prior else '')+'/bigobj'
    try: compile_cpp(*command, **keywords)
    finally:
        if prior is None: os.environ.pop('CL', None)
        else: os.environ['CL'] = prior
    cases = {}
    for name, mode, dispatches in (('stencil-positive','--opaque',15),('stencil-mutation','--opaque-mutation',4)):
        directory=out/name;directory.mkdir(parents=True,exist_ok=True)
        _,peak,elapsed,log=bounded_run([str(exe),str(directory),str(DLL),mode],directory/'native_run')
        value=json.loads((directory/'native-transactions-result.json').read_text())
        assert value['debug_errors']==value['debug_warnings']==0
        assert value['provider_dispatches']==dispatches
        if name=='stencil-positive':
            assert len(value['frames'])==6 and all(v['native_filter_gpu_executions']==0 and v['opaque_original_gpu_executions']==1 for v in value['frames'])
        else:
            assert value['forwarded_submissions']==1 and value['repeated_denials']==0 and value['required_latch']==0 and value['quarantined_recordings']==0
        value.update(elapsed_seconds=elapsed,peak_resident_bytes=peak,native_log=str(log));cases[name]=value
    result=dict(cases=cases,native_checks=sum(v['native_checks'] for v in cases.values()),python_checks=6,
                source_sha256=native.sha(source),exe_sha256=native.sha(exe),driver_sha256=native.sha(__file__),
                scope='actual D32S8 plane1 integer SRV/native indirect/shader metadata/signedRR; explicit family and Release adapters, not exact game root blob')
    (out/'stencil-exclusion-result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':run()
