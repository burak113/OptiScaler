// Real D3D12 helper tests, using unchanged production Pass and RawSignals logic.
#define main LegacyConversionFixtureMain
#include "fsrd_nrd_conversion_fixture.cpp"
#undef main
#include "production_nrd_raw.cpp"

namespace RawFixture
{
using namespace NrdBridge;
struct BufferReadback
{
    ComPtr<ID3D12Resource> resource;size_t bytes=0;
    std::vector<char> Data() const
    {
        void* value=nullptr;D3D12_RANGE read{0,bytes};hr(resource->Map(0,&read,&value));
        std::vector<char> data(bytes);memcpy(data.data(),value,bytes);D3D12_RANGE empty{0,0};resource->Unmap(0,&empty);return data;
    }
};
BufferReadback Snapshot(Fixture& fixture,ID3D12Resource* source)
{
    BufferReadback out;out.bytes=size_t(source->GetDesc().Width);out.resource=fixture.Buffer(out.bytes,D3D12_HEAP_TYPE_READBACK);
    Fixture::Transition(fixture.list.Get(),source,D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COPY_SOURCE);
    fixture.list->CopyBufferRegion(out.resource.Get(),0,source,0,out.bytes);
    Fixture::Transition(fixture.list.Get(),source,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_COMMON);return out;
}
void Constants(ID3D12Resource* resource,int x,int y,uint32_t word,uint32_t flag)
{
    uint32_t* data=nullptr;hr(resource->Map(0,nullptr,reinterpret_cast<void**>(&data)));memset(data,0,1536);
    data[112]=0x51a2c3d4;data[113]=0x12345678;data[114]=uint32_t(x);data[115]=uint32_t(y);data[word]=flag;
    resource->Unmap(0,nullptr);
}
ComPtr<ID3D12Resource> TextureR16(Fixture& fixture,uint32_t width,uint32_t height,const std::vector<char>& data)
{
    need(data.size()==size_t(width)*height*2,"R16 source byte count");
    D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;desc.Width=width;desc.Height=height;
    desc.DepthOrArraySize=desc.MipLevels=1;desc.SampleDesc.Count=1;desc.Format=DXGI_FORMAT_R16_FLOAT;
    D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;ComPtr<ID3D12Resource> out;
    hr(fixture.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&out)));
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};UINT rows;uint64_t rowBytes,total;
    fixture.device->GetCopyableFootprints(&desc,0,1,0,&footprint,&rows,&rowBytes,&total);auto upload=fixture.Buffer(total,D3D12_HEAP_TYPE_UPLOAD);
    void* mapped=nullptr;hr(upload->Map(0,nullptr,&mapped));
    for(uint32_t y=0;y<height;++y)memcpy(static_cast<char*>(mapped)+size_t(y)*footprint.Footprint.RowPitch,data.data()+size_t(y)*width*2,width*2);
    upload->Unmap(0,nullptr);D3D12_TEXTURE_COPY_LOCATION from{},to{};from.pResource=upload.Get();from.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    from.PlacedFootprint=footprint;to.pResource=out.Get();to.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    fixture.list->CopyTextureRegion(&to,0,0,0,&from,nullptr);Fixture::Transition(fixture.list.Get(),out.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_COMMON);
    fixture.uploads.push_back(upload);return out;
}
struct Sources
{
    std::array<ComPtr<ID3D12Resource>,7> textures;
    ComPtr<ID3D12DescriptorHeap> heap,encodingHeap;
    ComPtr<ID3D12Resource> original,replacement,encodingOriginal,encodingReplacement;
    uint32_t stride=0,width=0,height=0;
    RawSignalSource source;
    Sources(Fixture& fixture,const fs::path& path,uint32_t w,uint32_t h,bool table):width(w),height(h)
    {
        const char* names[]={"spec.bin","diff.bin","nr.bin","depth.bin","motion.bin","material.bin"};
        const DXGI_FORMAT formats[]={DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R10G10B10A2_UNORM,
            DXGI_FORMAT_R32_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT};
        for(unsigned i=0;i<6;++i)
        {
            const auto data=load(path/names[i]);textures[i]=fixture.Texture(w,h,formats[i],i==5?D3D12_RESOURCE_STATE_COMMON:D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&data);
            (i==5?gNrdOwnedMaterials:gNrdGuideInputs).insert(textures[i].Get());
        }
        textures[6]=TextureR16(fixture,w,h,load(path/"material_roughness.bin"));gNrdOwnedMaterials.insert(textures[6].Get());
        D3D12_DESCRIPTOR_HEAP_DESC desc{};desc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;desc.NumDescriptors=3;desc.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        hr(fixture.device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&heap)));desc.NumDescriptors=1;hr(fixture.device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&encodingHeap)));
        stride=fixture.device->GetDescriptorHandleIncrementSize(desc.Type);auto cpu=heap->GetCPUDescriptorHandleForHeapStart();
        for(unsigned i=0;i<2;++i)
        {
            D3D12_SHADER_RESOURCE_VIEW_DESC view{};view.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
            view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;view.Texture2D.MipLevels=1;
            fixture.device->CreateShaderResourceView(textures[i].Get(),&view,cpu);cpu.ptr+=stride;
        }
        original=fixture.Buffer(1536,D3D12_HEAP_TYPE_UPLOAD);replacement=fixture.Buffer(1536,D3D12_HEAP_TYPE_UPLOAD);
        encodingOriginal=fixture.Buffer(1536,D3D12_HEAP_TYPE_UPLOAD);encodingReplacement=fixture.Buffer(1536,D3D12_HEAP_TYPE_UPLOAD);
        Constants(original.Get(),0,0,303,0);Constants(replacement.Get(),0,0,303,0);
        source.nativeHeap=heap.Get();source.specSrv=heap->GetGPUDescriptorHandleForHeapStart();source.diffSrv=source.specSrv;source.diffSrv.ptr+=stride;
        source.width=w;source.height=h;source.profile=NativeRawProfile::ReconDirect;
        if(table)
        {
            source.nativeConstants.nativeHeap=heap.Get();source.nativeConstants.cbvHandle=source.specSrv;source.nativeConstants.cbvHandle.ptr+=uint64_t(2)*stride;
            SourceCB(fixture,original.Get());
        }
        else source.nativeConstants.address=original->GetGPUVirtualAddress();
    }
    void SourceCB(Fixture& fixture,ID3D12Resource* resource)
    {
        auto cpu=heap->GetCPUDescriptorHandleForHeapStart();cpu.ptr+=uint64_t(2)*stride;
        D3D12_CONSTANT_BUFFER_VIEW_DESC desc{resource->GetGPUVirtualAddress(),768};fixture.device->CreateConstantBufferView(&desc,cpu);
    }
    void EncodingCB(Fixture& fixture,ID3D12Resource* resource)
    {
        D3D12_CONSTANT_BUFFER_VIEW_DESC desc{resource->GetGPUVirtualAddress(),1536};
        fixture.device->CreateConstantBufferView(&desc,encodingHeap->GetCPUDescriptorHandleForHeapStart());
    }
};
void Cases(Fixture& fixture,const fs::path& root,std::vector<std::shared_ptr<Sources>>& retained)
{
    std::ifstream meta(root/"cases.txt");unsigned count,width,height;meta>>count>>width>>height;need(bool(meta)&&count<=32,"bounded raw case manifest");
    RawSignalSnapshotPass raw;ConversionPass conversion;std::string error;
    need(raw.OwnedBytes()==0&&raw.OwnedSlots()==0,"raw helper OFF owns no resources");
    need(raw.Initialize(fixture.device.Get(),width,height,error),error.c_str());need(conversion.Initialize(fixture.device.Get(),width,height,error),error.c_str());
    uint64_t warmBytes=0;
    for(unsigned i=0;i<count;++i)
    {
        std::string name;int ox,oy;uint32_t word,flag,table,material;meta>>name>>ox>>oy>>word>>flag>>table>>material;need(bool(meta),"case row complete");
        const auto path=root/name;auto source=std::make_shared<Sources>(fixture,path,width,height,table!=0);retained.push_back(source);
        uint32_t unusedMode;auto frame=ReadFrame(path,unusedMode);frame.streamlineFrame=4000+i;frame.frameIndex=i;frame.nativeMaterialGuides=material!=0;frame.preserveNativeMaterialIDs=true;
        const auto specRefs=References(source->textures[0].Get()),diffRefs=References(source->textures[1].Get());
        const auto heapRefs=source->heap->AddRef();source->heap->Release();
        RawSignalLease lease,denied;
        if(i==0)
        {
            const auto before=raw.OwnedBytes();auto bad=source->source;bad.profile=NativeRawProfile::Unknown;
            need(!raw.Capture(fixture.list.Get(),bad,frame.streamlineFrame,frame.frameIndex,denied,error)&&!denied&&raw.OwnedBytes()==before,"unknown profile rejected before allocation/work");
            bad=source->source;bad.nativeConstants={};need(!raw.Capture(fixture.list.Get(),bad,frame.streamlineFrame,frame.frameIndex,denied,error)&&!denied,"missing native source constants fail closed");
            bad=source->source;++bad.specSrv.ptr;need(!raw.Capture(fixture.list.Get(),bad,frame.streamlineFrame,frame.frameIndex,denied,error)&&!denied,"misaligned source SRV fails closed");
        }
        need(raw.Capture(fixture.list.Get(),source->source,frame.streamlineFrame,frame.frameIndex,lease,error),error.c_str());
        if(!i)warmBytes=raw.OwnedBytes();need(raw.OwnedSlots()==1&&raw.OwnedBytes()==warmBytes,"completed raw pool reuses one immutable slot without warm growth");
        ConversionInputs inputs;inputs.reconSpec=reinterpret_cast<ID3D12Resource*>(uintptr_t(1));inputs.reconDiff=reinterpret_cast<ID3D12Resource*>(uintptr_t(3));
        inputs.normals=source->textures[2].Get();inputs.viewDepth=source->textures[3].Get();
        if(material){inputs.nativeMaterial=source->textures[5].Get();if(material==2)inputs.nativeMaterialRoughness=source->textures[6].Get();}
        ConvertedResources output;
        auto wrong=frame;++wrong.streamlineFrame;need(!conversion.DispatchGeometry(fixture.list.Get(),inputs,wrong,lease,output,error),"wrong-frame geometry rejected");
        need(conversion.DispatchGeometry(fixture.list.Get(),inputs,frame,lease,output,error),error.c_str());
        auto* positive=conversion.OwnedPositiveViewDepth(output,frame);need(positive!=nullptr,"same-frame owned native positive ViewZ available");
        need(conversion.OwnedPositiveViewDepth(output,wrong)==nullptr,"wrong-frame owned positive ViewZ unavailable");
        auto nativeDepth=fixture.Snapshot(positive,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        auto depth=fixture.Snapshot(output.linearDepth,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        auto normal=fixture.Snapshot(output.normals,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        auto specAlbedo=fixture.Snapshot(output.specAlbedo,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        auto diffAlbedo=fixture.Snapshot(output.diffAlbedo,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        need(conversion.DispatchMotion(fixture.list.Get(),output,source->textures[4].Get(),frame,error),error.c_str());
        auto motion=fixture.Snapshot(output.motion,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        auto snapshot=RawSignalSnapshotPass::GetSnapshot(lease);auto packed=Snapshot(fixture,snapshot.resource);
        TitleSignalConstants constants;constants.wordIndex=word;
        Constants(source->encodingOriginal.Get(),0,0,word,flag?0u:1u);Constants(source->encodingReplacement.Get(),0,0,word,flag);
        if(table){source->EncodingCB(fixture,source->encodingOriginal.Get());constants.nativeHeap=source->encodingHeap.Get();constants.cbvHandle=source->encodingHeap->GetGPUDescriptorHandleForHeapStart();}
        else constants.address=source->encodingOriginal->GetGPUVirtualAddress();
        need(raw.Decode(fixture.list.Get(),lease,output,constants,error),error.c_str());
        need(raw.OwnedBytes()==warmBytes,"late raw decode allocates no additional capture resources");
        snapshot=RawSignalSnapshotPass::GetSnapshot(lease);need(snapshot.decoded&&snapshot.encodingFlag&&snapshot.decodedEncodingConstants.address,"decoded immutable owned flag exported");
        auto flagReadback=Snapshot(fixture,snapshot.encodingFlag);
        need(!raw.Decode(fixture.list.Get(),lease,output,constants,error),"raw decode is single use");
        auto spec=fixture.Snapshot(output.spec,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),diff=fixture.Snapshot(output.diff,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        auto originalSpec=fixture.Snapshot(source->textures[0].Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),originalDiff=fixture.Snapshot(source->textures[1].Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        // Legal native CB updates/volatile descriptor replacement after ALL recording.
        if(table){Constants(source->replacement.Get(),ox,oy,303,0);source->SourceCB(fixture,source->replacement.Get());source->EncodingCB(fixture,source->encodingReplacement.Get());}
        else{Constants(source->original.Get(),ox,oy,303,0);Constants(source->encodingOriginal.Get(),0,0,word,flag);}
        need(References(source->textures[0].Get())==specRefs&&References(source->textures[1].Get())==diffRefs,"raw capture/geometry retain no native lighting references");
        const auto afterHeap=source->heap->AddRef();source->heap->Release();need(afterHeap==heapRefs,"raw helper retains no native descriptor heap reference");
        fixture.Submit();fixture.Reset();
        save(path/"raw_owned.bin",packed.Data());save(path/"out_spec.bin",spec.Data());save(path/"out_diff.bin",diff.Data());
        save(path/"out_depth.bin",depth.Data());save(path/"positive_viewz.bin",nativeDepth.Data());save(path/"out_nr.bin",normal.Data());
        save(path/"out_spec_albedo.bin",specAlbedo.Data());save(path/"out_diff_albedo.bin",diffAlbedo.Data());save(path/"out_motion.bin",motion.Data());
        save(path/"source_spec_after.bin",originalSpec.Data());save(path/"source_diff_after.bin",originalDiff.Data());save(path/"encoding_flag.bin",flagReadback.Data());
    }
    std::cout<<"raw_cases="<<count<<" active_slots="<<raw.OwnedSlots()<<" active_bytes="<<raw.OwnedBytes()<<" no_provider_calls=1\n";
}
void ByteLimit()
{
    auto family=MakeOwnedShared<RawFamily>();
    {
        RawBytes held;need(held.Reserve(family,kRawByteLimit),"actual byte permit admits exactly2GiB metadata");
        need(family->bytes.load()==kRawByteLimit,"actual byte budget records exact boundary");
        RawBytes denied;need(!denied.Reserve(family,1),"actual byte permit rejects first byte beyond2GiB");
        RawBytes moved(std::move(held));need(!held.family&&moved.bytes==kRawByteLimit,"byte permit move cannot double release");
    }
    need(family->bytes.load()==0,"actual permit destruction rolls back all bytes");
    RawBytes overflow;need(!overflow.Reserve(family,UINT64_MAX)&&family->bytes.load()==0,"overflow cannot enter retained budget");
    std::cout<<"raw_byte_limit actual_metadata=1 boundary2GiB=1 large_gpu_allocation=0\n";
}
void Family(Fixture& fixture,const RawSignalSource& source)
{
    auto helper=std::make_unique<RawSignalSnapshotPass>();std::string error;need(helper->Initialize(fixture.device.Get(),source.width,source.height,error),error.c_str());
    std::vector<RawSignalLease> leases(32);for(unsigned i=0;i<32;++i)need(helper->Capture(fixture.list.Get(),source,5000+i,i,leases[i],error),error.c_str());
    const auto bytes=helper->OwnedBytes();need(helper->OwnedSlots()==32&&bytes<=uint64_t(2)*1024*1024*1024,"raw family owns at most32slots/2GiB");RawSignalLease rejected;
    need(!helper->Capture(fixture.list.Get(),source,6000,40,rejected,error)&&!rejected&&helper->OwnedBytes()==bytes,"33rd raw snapshot rejected without allocation");
    fixture.Submit();fixture.Reset();need(RecordedComputeLease::GetRegistry().recordings.empty()&&RecordedComputeLease::GetRegistry().submissions.empty(),"completed family fence and no active recorded GPU owners");
    need(helper->Initialize(fixture.device.Get(),64,64,error),error.c_str());auto smaller=source;smaller.width=smaller.height=64;
    need(!helper->Capture(fixture.list.Get(),smaller,6001,41,rejected,error)&&helper->OwnedSlots()==32,"retired contexts still account against same32slot family");
    leases.back().reset();need(helper->OwnedSlots()==31&&helper->OwnedBytes()<bytes,"only destroyed retired snapshot releases family permit");
    RawSignalLease next;need(helper->Capture(fixture.list.Get(),smaller,6002,42,next,error),error.c_str());need(helper->OwnedSlots()==32,"released old permit admits new size");
    fixture.Submit();fixture.Reset();
    auto observer=RawSignalSnapshotPass::GetSnapshot(leases.front());std::weak_ptr<void> lifetime=observer.owner;
    auto copy=Snapshot(fixture,observer.resource);need(ResTrack_Dx12::RetainComputeDispatch(fixture.device.Get(),fixture.list.Get(),observer.owner),"observer copy retains the complete raw owner");
    helper.reset();leases.clear();next.reset();observer.owner.reset();need(!lifetime.expired(),"owned raw source lives beyond helper retirement until observer fence");
    fixture.Submit();fixture.Reset();need(lifetime.expired()&&!copy.Data().empty(),"observer GPU completion finally releases raw context and slot");
    std::cout<<"raw_family capacity=32 retired_generations_counted=1 deferred_observer_release=1\n";
}
}
int main(int argc,char** argv)
{
    try
    {
        need(argc==2,"raw fixture expects its sealed input/output directory");Fixture fixture(true);std::vector<std::shared_ptr<RawFixture::Sources>> sources;
        RawFixture::ByteLimit();RawFixture::Cases(fixture,argv[1],sources);need(!sources.empty(),"native source retained for family tests");RawFixture::Family(fixture,sources.back()->source);
        need(fixture.fence->GetCompletedValue()>=fixture.fenceValue,"all helper GPU work completed");
        need(RecordedComputeLease::GetRegistry().recordings.empty()&&RecordedComputeLease::GetRegistry().submissions.empty(),"all recorded owners retired before fixture destruction");
        hr(fixture.list->Close());fixture.Validate();std::cout<<"PASS raw_native_checks="<<checks<<" provider_calls=0 native_nrd_calls=0\n";return 0;
    }
    catch(const std::exception& error){std::cerr<<"FAIL raw_native "<<error.what()<<'\n';return 1;}
}
