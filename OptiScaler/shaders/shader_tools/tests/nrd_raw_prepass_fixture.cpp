// Actual owned B capture/geometry/decode; no native NRD or provider dispatch.
#define main RawAStandaloneMain
#include "nrd_raw_signal_fixture.cpp"
#undef main
#include <thread>
namespace RawPrePassFixture
{
using namespace NrdBridge;
struct Source : RawFixture::Sources
{
    std::array<ComPtr<ID3D12Resource>,2> originalDummy;
    uint32_t sourceWidth=0,sourceHeight=0;
    Source(Fixture& fixture,const fs::path& path,uint32_t width,uint32_t height,uint32_t sw,uint32_t sh,bool table)
        :RawFixture::Sources(fixture,path,width,height,table),sourceWidth(sw),sourceHeight(sh)
    {
        auto cpu=heap->GetCPUDescriptorHandleForHeapStart();
        for(unsigned i=0;i<2;++i)
        {
            originalDummy[i]=textures[i];const auto data=load(path/(i?"raw_diff.bin":"raw_spec.bin"));
            textures[i]=fixture.Texture(sw,sh,DXGI_FORMAT_R16G16B16A16_FLOAT,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,&data);
            gNrdGuideInputs.insert(textures[i].Get());D3D12_SHADER_RESOURCE_VIEW_DESC view{};view.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;
            view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;view.Texture2D.MipLevels=1;
            fixture.device->CreateShaderResourceView(textures[i].Get(),&view,cpu);cpu.ptr+=stride;
        }
        source.profile=NativeRawProfile::PrePass;
    }
};
void Constants(ID3D12Resource* resource,int ox,int oy,uint32_t rw,uint32_t rh,uint32_t diff,uint32_t spec,uint32_t phase)
{
    uint32_t* data=nullptr;hr(resource->Map(0,nullptr,reinterpret_cast<void**>(&data)));memset(data,0,1536);
    data[112]=0x51a2c3d4;data[113]=0x12345678;data[114]=uint32_t(ox);data[115]=uint32_t(oy);
    data[118]=rw;data[119]=rh;data[129]=phase;const float range=65504;memcpy(data+130,&range,4);
    data[144]=diff;data[145]=spec;resource->Unmap(0,nullptr);
}
void Cases(Fixture& fixture,const fs::path& root,std::vector<std::shared_ptr<Source>>& retained)
{
    std::ifstream meta(root/"prepass-cases.txt");unsigned count,width,height;meta>>count>>width>>height;need(bool(meta)&&count<=96,"bounded independent B manifest");
    RawSignalSnapshotPass raw;ConversionPass conversion;std::string error;
    need(raw.OwnedBytes()==0&&raw.OwnedSlots()==0,"B helper OFF owns no allocations");
    need(raw.Initialize(fixture.device.Get(),width,height,error),error.c_str());need(conversion.Initialize(fixture.device.Get(),width,height,error),error.c_str());
    uint64_t warmBytes=0;
    for(unsigned i=0;i<count;++i)
    {
        std::string name;int ox,oy;uint32_t rw,rh,diffMode,specMode,phase,table,word,flag,material,sw,sh,status;
        meta>>name>>ox>>oy>>rw>>rh>>diffMode>>specMode>>phase>>table>>word>>flag>>material>>sw>>sh>>status;need(bool(meta),"B row complete");
        const auto path=root/name;auto source=std::make_shared<Source>(fixture,path,width,height,sw,sh,table!=0);retained.push_back(source);
        uint32_t unused;auto frame=ReadFrame(path,unused);frame.streamlineFrame=8000+i;frame.frameIndex=i;frame.nativeMaterialGuides=material!=0;frame.preserveNativeMaterialIDs=true;
        const auto specRefs=References(source->textures[0].Get()),diffRefs=References(source->textures[1].Get());
        const auto heapRefs=source->heap->AddRef();source->heap->Release();
        // Initial values deliberately differ from the executed native constants.
        Constants(source->original.Get(),0,0,width,height,2,2,phase^1);Constants(source->replacement.Get(),ox,oy,rw,rh,diffMode,specMode,phase);
        RawSignalLease lease;need(raw.Capture(fixture.list.Get(),source->source,frame.streamlineFrame,frame.frameIndex,lease,error),error.c_str());
        if(!i)warmBytes=raw.OwnedBytes();need(raw.OwnedSlots()==1&&raw.OwnedBytes()==warmBytes,"B warm capture reuses one prepared slot");
        ConversionInputs inputs;inputs.reconSpec=reinterpret_cast<ID3D12Resource*>(uintptr_t(1));inputs.reconDiff=reinterpret_cast<ID3D12Resource*>(uintptr_t(3));
        inputs.normals=source->textures[2].Get();inputs.viewDepth=source->textures[3].Get();
        if(material){inputs.nativeMaterial=source->textures[5].Get();if(material==2)inputs.nativeMaterialRoughness=source->textures[6].Get();}
        ConvertedResources output;need(conversion.DispatchGeometry(fixture.list.Get(),inputs,frame,lease,output,error),error.c_str());
        auto* positive=conversion.OwnedPositiveViewDepth(output,frame);need(positive!=nullptr,"B same-recording owned positive ViewZ");
        need(conversion.DispatchMotion(fixture.list.Get(),output,source->textures[4].Get(),frame,error),error.c_str());
        auto normal=fixture.Snapshot(output.normals,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),depth=fixture.Snapshot(output.linearDepth,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        auto positiveRead=fixture.Snapshot(positive,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),motion=fixture.Snapshot(output.motion,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        auto specAlbedo=fixture.Snapshot(output.specAlbedo,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),diffAlbedo=fixture.Snapshot(output.diffAlbedo,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        auto snapshot=RawSignalSnapshotPass::GetSnapshot(lease);need(snapshot.hasStatus&&snapshot.statusByteOffset==0,"B owned uniform status is explicit diagnostic metadata");
        auto packed=RawFixture::Snapshot(fixture,snapshot.resource);TitleSignalConstants constants;constants.wordIndex=word;
        RawFixture::Constants(source->encodingOriginal.Get(),0,0,word,flag?0u:1u);RawFixture::Constants(source->encodingReplacement.Get(),0,0,word,flag);
        if(table){source->EncodingCB(fixture,source->encodingOriginal.Get());constants.nativeHeap=source->encodingHeap.Get();constants.cbvHandle=source->encodingHeap->GetGPUDescriptorHandleForHeapStart();}
        else constants.address=source->encodingOriginal->GetGPUVirtualAddress();
        auto wrong=output;wrong.normals=nullptr;need(!raw.Decode(fixture.list.Get(),lease,wrong,constants,error),"B missing geometry fails before decode admission");
        need(raw.Decode(fixture.list.Get(),lease,output,constants,error),error.c_str());need(raw.OwnedBytes()==warmBytes,"B late decode allocates no capture resources");
        snapshot=RawSignalSnapshotPass::GetSnapshot(lease);need(snapshot.decoded&&snapshot.encodingFlag&&snapshot.decodedEncodingConstants.address,"B executed codec retained for pure commit");
        auto flagRead=RawFixture::Snapshot(fixture,snapshot.encodingFlag);need(!raw.Decode(fixture.list.Get(),lease,output,constants,error),"B raw decode remains single-use");
        auto spec=fixture.Snapshot(output.spec,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),diff=fixture.Snapshot(output.diff,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        auto sourceSpec=fixture.Snapshot(source->textures[0].Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),sourceDiff=fixture.Snapshot(source->textures[1].Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        if(table){source->SourceCB(fixture,source->replacement.Get());source->EncodingCB(fixture,source->encodingReplacement.Get());}
        else{Constants(source->original.Get(),ox,oy,rw,rh,diffMode,specMode,phase);RawFixture::Constants(source->encodingOriginal.Get(),0,0,word,flag);}
        need(References(source->textures[0].Get())==specRefs&&References(source->textures[1].Get())==diffRefs,"B retains no native raw input refs");
        const auto afterHeap=source->heap->AddRef();source->heap->Release();need(afterHeap==heapRefs,"B retains no native descriptor heap refs");
        fixture.Submit();fixture.Reset();auto rawData=packed.Data();uint32_t executedStatus;memcpy(&executedStatus,rawData.data(),4);need(executedStatus==status,"actual GPU B bounds/mode/UINTrect status matches independent case");
        need(lease->statusObservation->completedCount==1&&lease->statusObservation->mapCount==1,"mandatory B observer maps once after actual completion even with Trace OFF");
        need(lease->statusObservation->lastStatus==status,"mandatory observer sees exact executed owned status");
        need(FAILED(RecordedComputeLease::RequiredSubmissionFailure())==(status!=0),"GPU invalid B status latches fatal for future submissions");
        if(status)
        {
            need(fixture.fence->GetCompletedValue()>=fixture.fenceValue&&RecordedComputeLease::GetRegistry().recordings.empty()&&RecordedComputeLease::GetRegistry().submissions.empty(),"negative status fixture fully drained before test-only fatal reset");
            RecordedComputeLease::gUntrackedRequiredSubmissionFailure.store(S_OK,std::memory_order_release);
        }
        save(path/"raw_owned.bin",rawData);save(path/"out_spec.bin",spec.Data());save(path/"out_diff.bin",diff.Data());
        save(path/"out_nr.bin",normal.Data());save(path/"out_depth.bin",depth.Data());save(path/"positive_viewz.bin",positiveRead.Data());save(path/"out_motion.bin",motion.Data());
        save(path/"out_spec_albedo.bin",specAlbedo.Data());save(path/"out_diff_albedo.bin",diffAlbedo.Data());
        save(path/"source_spec_after.bin",sourceSpec.Data());save(path/"source_diff_after.bin",sourceDiff.Data());save(path/"encoding_flag.bin",flagRead.Data());
    }
    std::cout<<"prepass_cases="<<count<<" active_slots="<<raw.OwnedSlots()<<" active_bytes="<<raw.OwnedBytes()<<" provider_calls=0 native_nrd_calls=0\n";
}
void Tiny(Fixture& fixture,Source& source)
{
    RawSignalSnapshotPass raw;std::string error;need(raw.Initialize(fixture.device.Get(),1,1,error),error.c_str());
    auto one=source.source;one.width=one.height=1;Constants(source.original.Get(),0,0,1,1,0,1,0);
    if(one.nativeConstants.nativeHeap)source.SourceCB(fixture,source.original.Get());
    RawSignalLease lease;need(raw.Capture(fixture.list.Get(),one,9000,100,lease,error),error.c_str());
    auto snapshot=RawSignalSnapshotPass::GetSnapshot(lease);auto data=RawFixture::Snapshot(fixture,snapshot.resource);
    fixture.Submit();fixture.Reset();auto bytes=data.Data();uint32_t status;memcpy(&status,bytes.data(),4);
    need(status==16,"actual single-pixel checkerboard has explicit unsupported-width status");
    need(FAILED(RecordedComputeLease::RequiredSubmissionFailure()),"single-pixel unsupported GPU status also latches fatal without Trace");
    need(fixture.fence->GetCompletedValue()>=fixture.fenceValue&&RecordedComputeLease::GetRegistry().recordings.empty()&&RecordedComputeLease::GetRegistry().submissions.empty(),"tiny negative fully drained before test-only fatal reset");
    RecordedComputeLease::gUntrackedRequiredSubmissionFailure.store(S_OK,std::memory_order_release);
}
void ObserverControls(Fixture& fixture,Source& source)
{
    RawSignalSnapshotPass raw;std::string error;need(raw.Initialize(fixture.device.Get(),source.width,source.height,error),error.c_str());
    Constants(source.original.Get(),0,0,source.width,source.height,2,2,0);if(source.source.nativeConstants.nativeHeap)source.SourceCB(fixture,source.original.Get());
    RawSignalLease lease;need(raw.Capture(fixture.list.Get(),source.source,9100,101,lease,error),error.c_str());fixture.Submit();fixture.Reset();
    auto observation=lease->statusObservation;need(observation&&observation->mapCount==1&&observation->lastStatus==0,"observer controls use real already-fenced status0 readback");
    const auto maps=observation->mapCount;
    RecordedComputeLease::SubmissionInfo a{fixture.queue.Get(),1000001,lease->recordingId,1,false},c=a,d=a;
    c.submissionId=1000002;d.submissionId=1000003;
    need(observation->Before(a)&&observation->Before(c),"same recording tracks distinct overlapping submissions without allocation");
    observation->Complete(a);need(observation->mapCount==maps,"first completion never maps while another submission can write");
    HANDLE entered=CreateEvent(nullptr,TRUE,FALSE,nullptr),finished=CreateEvent(nullptr,TRUE,FALSE,nullptr);need(entered&&finished,"observer serialization test events");
    bool admitted=false;
    {
        std::unique_lock lock(observation->mutex);
        std::thread pending([&]{SetEvent(entered);admitted=observation->Before(d);SetEvent(finished);});
        const bool started=WaitForSingleObject(entered,1000)==WAIT_OBJECT_0;
        const bool blocked=started&&WaitForSingleObject(finished,5)==WAIT_TIMEOUT;lock.unlock();pending.join();
        need(started,"resubmission attempts observer mutex");need(blocked&&admitted,"beforeSubmit cannot start GPU overwrite while completion owns Map mutex");
    }
    CloseHandle(entered);CloseHandle(finished);observation->Complete(c);need(observation->mapCount==maps,"another live resubmission continues to pin readback");
    observation->Complete(d);need(observation->mapCount==maps+1,"only final concurrent completion maps actual status exactly once");
    auto outstanding=a;outstanding.submissionId=1000004;auto unknown=a;unknown.submissionId=1000999;
    need(observation->Before(outstanding),"failed callback balance outstanding submission admitted");
    observation->Failed(unknown);need(FAILED(RecordedComputeLease::RequiredSubmissionFailure()),"failure before its own admission conservatively latches fatal");
    bool stillPending=false;for(auto id:observation->active)stillPending|=id==outstanding.submissionId;need(stillPending,"failed callback never decrements a different submission");
    observation->Complete(outstanding);need(observation->mapCount==maps+1,"failed observation never maps uncertain storage");
    need(fixture.fence->GetCompletedValue()>=fixture.fenceValue&&RecordedComputeLease::GetRegistry().recordings.empty()&&RecordedComputeLease::GetRegistry().submissions.empty(),"observer negative controls leave no active GPU owners");
    // Deliberately leave the conservative fatal latch set: no further native submission follows.
    std::cout<<"status_observer trace_off=1 actual_fence=1 serialized_map=1 failed_id_balance=1\n";
}
}
int main(int argc,char** argv)
{
    try
    {
        need(argc==2,"B fixture expects sealed directory");Fixture fixture(true);std::vector<std::shared_ptr<RawPrePassFixture::Source>> sources;
        RawPrePassFixture::Cases(fixture,argv[1],sources);need(!sources.empty(),"B sources retained");RawPrePassFixture::Tiny(fixture,*sources.front());RawPrePassFixture::ObserverControls(fixture,*sources.front());
        need(fixture.fence->GetCompletedValue()>=fixture.fenceValue,"B all GPU work fenced");
        need(RecordedComputeLease::GetRegistry().recordings.empty()&&RecordedComputeLease::GetRegistry().submissions.empty(),"B no remaining recorded GPU owners");
        hr(fixture.list->Close());fixture.Validate();std::cout<<"PASS raw_prepass_native_checks="<<checks<<" provider_calls=0 native_nrd_calls=0\n";return 0;
    }
    catch(const std::exception& error){std::cerr<<"FAIL raw_prepass_native "<<error.what()<<'\n';return 1;}
}
