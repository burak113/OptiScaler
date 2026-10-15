#ifndef NOMINMAX
#define NOMINMAX
#endif
#define main LegacyBridgeWrapperFixtureMain
#include "nrd_bridge_rr_fixture.cpp"
#undef main
#include "owned_consumer36_shader.h"

namespace
{
ULONG refs(ID3D12Resource* value){const auto n=value->AddRef();value->Release();return n-1;}
void word(ConsumerBuffer& target,uint32_t index,uint32_t bits)
{
    uint32_t* mapped=nullptr;hr(target.upload->Map(0,nullptr,reinterpret_cast<void**>(&mapped)));
    mapped[target.offset/4+index]=bits;target.upload->Unmap(0,nullptr);
}
void selectConsumerWord(Host& host,NativeTableConsumer& consumer,uint32_t index)
{
    if(index!=36)return;
    D3D12_COMPUTE_PIPELINE_STATE_DESC desc{};desc.pRootSignature=consumer.root.Get();
    desc.CS={OwnedConsumer36ShaderBytes,sizeof(OwnedConsumer36ShaderBytes)};
    hr(host.device->CreateComputePipelineState(&desc,IID_PPV_ARGS(&consumer.pso)));
}
ComPtr<ID3D12Resource> readEncodingFlag(Host& host,const RRRecordedOutputSnapshot& snapshot)
{
    need(snapshot.nativeEncodingCaptured && snapshot.encodingFlag && snapshot.encodingFlagState==D3D12_RESOURCE_STATE_COMMON,
         "late commit exposes only its actual owned GPU encoding capture in balancedCOMMON");
    auto target=buffer(host.device.Get(),4,D3D12_HEAP_TYPE_READBACK);
    barrier(host.list.Get(),snapshot.encodingFlag,D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COPY_SOURCE);
    host.list->CopyBufferRegion(target.Get(),0,snapshot.encodingFlag,1212,4);
    barrier(host.list.Get(),snapshot.encodingFlag,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_COMMON);
    return target;
}
uint32_t readWord(ID3D12Resource* resource)
{
    uint32_t* values=nullptr;hr(resource->Map(0,nullptr,reinterpret_cast<void**>(&values)));
    const auto result=values[0];resource->Unmap(0,nullptr);return result;
}
void earlyLate(Host& host)
{
    Scene scene(host,128,128,{},true);host.submit();host.reset();RRWrapper wrapper;std::string error;
    const auto specRefs=refs(scene.spec()),diffRefs=refs(scene.diff());uint32_t counter=0;uint64_t bytes=0,auxiliary=0;
    for(uint32_t index:{303u,36u})for(bool table:{false,true})for(uint32_t bits:{0u,1u,0x80000000u,0x7fc00000u})
    {
        FrameParameters frame;need(wrapper.PrepareFrame(camera(4000+counter,1.f),false,frame,error),error.c_str());
        ConsumerBuffer original(host),replacement(host);word(original,index,bits?0u:1u);word(original,index==303?36:303,bits?1u:0u);
        NativeTableConsumer consumer(host,scene.spec(),scene.diff(),128,128);selectConsumerWord(host,consumer,index);
        consumer.Overwrite(host.device.Get(),original.constants().address);
        ClearPair(host.list.Get(),scene.spec(),scene.diff(),{.125f,.25f,.5f,9.f},{1.25f,1.5f,1.75f,11.f});
        const uint16_t nativeAlpha=counter%3==0?uint16_t(0x7e55u):PackedVector::XMConvertFloatToHalf(9.f);
        seedNativeSpecular(host,scene,{0x7e31u,0x7c00u,0xfc00u,nativeAlpha});
        Readback beforeSpec(host,scene.spec()),beforeDiff(host,scene.diff());
        auto early=frame;early.outputEncoding=static_cast<SignalEncoding>(255);early.outputConstants.address=1;
        early.outputConstants.resource=reinterpret_cast<ID3D12Resource*>(uintptr_t(1));early.nativeSpecularBlend=1.f;
        RRRecordedOutputLease output;const auto calls=FfxApiProxy::dispatches;
        need(wrapper.RecordOwned(host.list.Get(),scene.resources,early,output,error),error.c_str());
        need(output && FfxApiProxy::dispatches==calls+1,"one owned DD/IS provider recording produces an opaque result");
        auto snapshot=wrapper.GetOwnedOutputSnapshot(output);
        need(snapshot.owner && snapshot.rawSpec && snapshot.rawDiff && snapshot.selectedSpec==snapshot.rawSpec && snapshot.selectedDiff==snapshot.rawDiff,
             "raw/selected snapshot contains owned RR stages only with recoveryOFF");
        need(!snapshot.outputCommitted && !snapshot.nativeEncodingCaptured && !snapshot.encodingFlag,
             "early result exposes no unrecorded/stale native encoding flag");
        const auto recording=RecordedComputeLease::Capture(host.list.Get());
        need(recording && snapshot.recordingId==recording->id && snapshot.recording==host.list.Get() &&
             snapshot.frameSL==frame.streamlineFrame && snapshot.frameIndex==frame.frameIndex && snapshot.contextGeneration==wrapper.ContextGeneration(),
             "opaque source freezes exact native recording/frame/context generation");
        need(std::memcmp(snapshot.providerControl.data(),reinterpret_cast<const uint8_t*>(&FfxApiProxy::lastDispatch)+264,184)==0,
             "trace snapshot contains actual provider control bytes including effective reset");
        need(snapshot.providerVersionId==(FfxApiProxy::real?4311875584ull:0x120ull) && snapshot.providerApiVersion==FFX_DENOISER_VERSION &&
             snapshot.providerSignalFlags==(FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE|FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR),
             "source snapshot identifies the actual selected AMD1.2 mode/version");
        if(counter==0){bytes=wrapper.OwnedStagingBytes();auxiliary=wrapper.OwnedAuxiliaryBytes();}
        need(wrapper.OwnedStagingBytes()==bytes && wrapper.OwnedAuxiliaryBytes()==auxiliary,"prewarmed deferred pool has no allocation growth");
        Readback untouchedSpec(host,scene.spec()),untouchedDiff(host,scene.diff());
        frame.outputEncoding=bits?SignalEncoding::Rgb:SignalEncoding::YCoCg;frame.nativeSpecularBlend=1.f;
        frame.outputConstants={};frame.outputConstants.wordIndex=index;
        if(table){frame.outputConstants.nativeHeap=consumer.heap.Get();frame.outputConstants.cbvHandle=consumer.Handle();}
        else frame.outputConstants.address=original.constants().address;
        need(wrapper.CommitOwned(host.list.Get(),output,scene.spec(),scene.diff(),frame,error),error.c_str());
        need(wrapper.OwnedStagingBytes()==bytes && wrapper.OwnedAuxiliaryBytes()==auxiliary,"late deferred commit allocates no capture/staging objects");
        snapshot=wrapper.GetOwnedOutputSnapshot(output);need(snapshot.outputCommitted,"only guarded pure output commit publishes completion");
        auto observed=readEncodingFlag(host,snapshot);consumer.Record(host);
        Readback finalSpec(host,scene.spec()),finalDiff(host,scene.diff()),selectedSpec(host,snapshot.selectedSpec),selectedDiff(host,snapshot.selectedDiff);
        word(replacement,index,bits);word(replacement,index==303?36:303,bits?0u:1u);
        if(table)consumer.Overwrite(host.device.Get(),replacement.constants().address);else word(original,index,bits);
        const auto generation=wrapper.ContextGeneration();
        need(!wrapper.CommitOwned(host.list.Get(),output,scene.spec(),scene.diff(),frame,error) && wrapper.ContextGeneration()==generation &&
             wrapper.GetOwnedOutputSnapshot(output).outputCommitted,"single-use rejection cannot retire an already valid committed generation");
        Readback decodedSpec(host,consumer.spec.Get()),decodedDiff(host,consumer.diff.Get());host.submit();host.reset();
        need(beforeSpec.values(128,128)==untouchedSpec.values(128,128) && beforeDiff.values(128,128)==untouchedDiff.values(128,128),
             "early provider stage does not mutate any title output bytes");
        nativeBlendReference(finalSpec,selectedSpec,beforeSpec,128,128,1.f,bits!=0);
        finalDiff.consumerRoundtrip(selectedDiff,128,128,bits!=0,11.f);
        nativeConsumerTitleIdentity(decodedSpec,finalSpec,128,128,bits!=0);nativeConsumerTitleIdentity(decodedDiff,finalDiff,128,128,bits!=0);
        need(consumer.Flag()==bits && readWord(observed.Get())==bits,"owned flag snapshot and original Consumer agree after legal late CBV overwrite");
        need(refs(scene.spec())==specRefs && refs(scene.diff())==diffRefs,"owned record/late commit never retain borrowed title outputs");
        descriptorChecks(early);++counter;
    }
    std::cout<<"owned_success cases="<<counter<<" profiles=2 binding_routes=2 live_flags=4 no_early_title_write=1 exact_rr_codec=1 opaque_alpha=1 single_use=1 staging_bytes="<<bytes<<" auxiliary_bytes="<<auxiliary<<'\n';
}
void rejectPaths(Host& host)
{
    Scene scene(host,128,128);host.submit();host.reset();std::string error;unsigned cases=0;
    for(unsigned reason=0;reason<5;++reason)
    {
        RRWrapper wrapper;FrameParameters frame;need(wrapper.PrepareFrame(camera(5000+reason,1.f),false,frame,error),error.c_str());
        ClearPair(host.list.Get(),scene.spec(),scene.diff(),{.125f,.25f,.5f,9.f},{1.25f,1.5f,1.75f,11.f});
        Readback beforeSpec(host,scene.spec()),beforeDiff(host,scene.diff());RRRecordedOutputLease output;
        const auto destroys=FfxApiProxy::destroys;
        need(wrapper.RecordOwned(host.list.Get(),scene.resources,frame,output,error),error.c_str());
        auto snapshot=wrapper.GetOwnedOutputSnapshot(output);CommitProbe denied;
        ComPtr<ID3D12CommandAllocator> otherAllocator;ComPtr<ID3D12GraphicsCommandList> otherList;
        ID3D12GraphicsCommandList* target=host.list.Get();auto late=frame;ID3D12Resource* spec=scene.spec();
        if(reason==0)++late.streamlineFrame;
        if(reason==1)++late.frameIndex;
        if(reason==2){hr(host.device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&otherAllocator)));
            hr(host.device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,otherAllocator.Get(),nullptr,IID_PPV_ARGS(&otherList)));target=otherList.Get();}
        if(reason==3)spec=snapshot.rawSpec;
        const OutputCommitGuard guard=reason==4?OutputCommitGuard{&denied,CommitProbe::Admit}:OutputCommitGuard{};
        need(!wrapper.CommitOwned(target,output,spec,scene.diff(),late,error,guard) && !error.empty(),"stale frame/index/cross-list/owned-alias/denied admission fails closed");
        if(otherList)hr(otherList->Close());
        need(!wrapper.GetSettingsState().ready && wrapper.OwnedStagingBytes()==0,"failed late commit retires exactly its private generation");
        if(reason==4)need(denied.calls==1&&denied.actions==0,"denied final admission records no title action");
        need(FfxApiProxy::destroys==destroys,"failed source context remains retained before actual GPU completion");
        Readback afterSpec(host,scene.spec()),afterDiff(host,scene.diff());host.submit();host.reset();
        need(beforeSpec.values(128,128)==afterSpec.values(128,128)&&beforeDiff.values(128,128)==afterDiff.values(128,128),"all rejected late paths preserve every title RGBA word");
        snapshot={};output.reset();RecordedComputeLease::Poll();need(FfxApiProxy::destroys==destroys+1,"retired source destroys after fence and final owned observer release");++cases;
    }
    std::cout<<"owned_reject cases="<<cases<<" cross_list_unsupported=1 guard_actions=0 exact_title_preservation=1 deferred_destroy=1\n";
}
void discardAndGeneration(Host& host)
{
    Scene scene(host,128,128);host.submit();host.reset();RRWrapper wrapper;FrameParameters frame;std::string error;
    need(wrapper.PrepareFrame(camera(6000,1.f),false,frame,error),error.c_str());RRRecordedOutputLease discarded;
    need(wrapper.RecordOwned(host.list.Get(),scene.resources,frame,discarded,error),error.c_str());
    const auto first=wrapper.GetOwnedOutputSnapshot(discarded);hr(host.list->Close());host.reset();
    need(!wrapper.CommitOwned(host.list.Get(),discarded,scene.spec(),scene.diff(),frame,error),"same list pointer after native Reset cannot reuse its old Recording token");
    need(!wrapper.GetSettingsState().ready,"unsubmitted Reset retires the affected private context");
    need(wrapper.PrepareFrame(camera(6001,1.f),false,frame,error)&&frame.reset&&!frame.previousValid,"fresh recovery resets SDK camera/history after discarded recording");
    RRRecordedOutputLease next;need(wrapper.RecordOwned(host.list.Get(),scene.resources,frame,next,error),error.c_str());
    const auto fresh=wrapper.GetOwnedOutputSnapshot(next);need(fresh.contextGeneration>first.contextGeneration&&fresh.recordingId!=first.recordingId,"reset recovery uses fresh physical context and native recording");
    wrapper.AbandonOwned(discarded);need(wrapper.GetSettingsState().ready&&wrapper.ContextGeneration()==fresh.contextGeneration,"late abandonment of old generation cannot retire a newer context");
    need(wrapper.CommitOwned(host.list.Get(),next,scene.spec(),scene.diff(),frame,error),error.c_str());
    Readback result(host,scene.spec()),source(host,fresh.selectedSpec);host.submit();host.reset();result.consumerRoundtrip(source,128,128,false,.75f);
    FrameParameters oldFrame;need(wrapper.PrepareFrame(camera(6002,1.f),false,oldFrame,error),error.c_str());
    RRRecordedOutputLease oldGeneration;need(wrapper.RecordOwned(host.list.Get(),scene.resources,oldFrame,oldGeneration,error),error.c_str());
    wrapper.DiscardRecordingHistory();FrameParameters current;
    need(wrapper.PrepareFrame(camera(6003,1.f),false,current,error)&&current.reset,"new physical generation follows explicit history discard");
    RRRecordedOutputLease newest;need(wrapper.RecordOwned(host.list.Get(),scene.resources,current,newest,error),error.c_str());
    const auto newestGeneration=wrapper.ContextGeneration();
    need(!wrapper.CommitOwned(host.list.Get(),oldGeneration,scene.spec(),scene.diff(),oldFrame,error)&&
         wrapper.GetSettingsState().ready&&wrapper.ContextGeneration()==newestGeneration,"stale uncommitted generation cannot retire a newer current context");
    need(wrapper.CommitOwned(host.list.Get(),newest,scene.spec(),scene.diff(),current,error),error.c_str());host.submit();host.reset();
    FrameParameters following;need(wrapper.PrepareFrame(camera(6004,1.f),false,following,error)&&following.previousValid&&!following.reset,
         "late old-generation denial does not corrupt newer private camera/frame history");
    std::cout<<"owned_discard native_reset_aba=1 fresh_context=1 old_generation_abandon_safe=1 debug_checked=1 stale_context_commit_rejected=1 newer_history_preserved=1\n";
}
void desiredSettings(Host& host)
{
    Scene scene(host,128,128);host.submit();host.reset();RRWrapper wrapper;std::string error;RRSettings active;active.overrideMask=1u;active.values[0]=.25f;
    need(wrapper.Configure(active,error),error.c_str());FrameParameters frame;need(wrapper.PrepareFrame(camera(7000,1.f),false,frame,error),error.c_str());
    RRRecordedOutputLease old;need(wrapper.RecordOwned(host.list.Get(),scene.resources,frame,old,error),error.c_str());
    const auto calls=FfxApiProxy::configures;const auto generation=wrapper.ContextGeneration();RRSettings desired=active;desired.values[0]=.75f;const bool desiredReset=true;
    // Model coordinator's deferred desired snapshot: no Configure/Reset is applied to an incomplete mandatory chain.
    need(wrapper.GetSettingsState().effective[0]==.25f && FfxApiProxy::configures==calls,"user desired request leaves captured provider settings immutable during early/late gap");
    need(wrapper.CommitOwned(host.list.Get(),old,scene.spec(),scene.diff(),frame,error),error.c_str());host.submit();host.reset();
    need(wrapper.Configure(desired,error),error.c_str());if(desiredReset)wrapper.ResetHistory();
    need(wrapper.PrepareFrame(camera(7001,1.f),false,frame,error)&&frame.reset,"deferred user settings/reset applies to next chain");
    RRRecordedOutputLease next;need(wrapper.RecordOwned(host.list.Get(),scene.resources,frame,next,error),error.c_str());
    need(wrapper.ContextGeneration()==generation&&wrapper.GetSettingsState().effective[0]==.75f&&FfxApiProxy::configures==calls+1,"next chain applies changed scalar without unnecessary context recreation");
    need(wrapper.CommitOwned(host.list.Get(),next,scene.spec(),scene.diff(),frame,error),error.c_str());host.submit();host.reset();
    std::cout<<"owned_desired old_commit_immutable=1 next_chain_apply=1 requested_reset=1\n";
}
void observerLifetime(Host& host)
{
    Scene scene(host,128,128);host.submit();host.reset();RRWrapper wrapper;FrameParameters frame;std::string error;RRRecordedOutputLease output;
    need(wrapper.PrepareFrame(camera(8000,1.f),false,frame,error)&&wrapper.RecordOwned(host.list.Get(),scene.resources,frame,output,error),error.c_str());
    need(wrapper.CommitOwned(host.list.Get(),output,scene.spec(),scene.diff(),frame,error),error.c_str());auto snapshot=wrapper.GetOwnedOutputSnapshot(output);
    const auto destroys=FfxApiProxy::destroys;output.reset();wrapper.DiscardRecordingHistory();
    need(FfxApiProxy::destroys==destroys,"owned observer and recording retain discarded context before submission");host.submit();host.reset();
    need(FfxApiProxy::destroys==destroys,"trace observer independently retains source after first GPU fence");
    need(ResTrack_Dx12::RetainComputeDispatch(host.device.Get(),host.list.Get(),snapshot.owner),"trace copy has its own GPU source lease");
    Readback traceSpec(host,snapshot.selectedSpec),traceDiff(host,snapshot.selectedDiff);host.submit();host.reset();
    const auto values=traceSpec.values(128,128);uint64_t finite=0;for(size_t p=0;p<size_t(128)*128;++p)for(unsigned c=0;c<3;++c)finite+=std::isfinite(PackedVector::XMConvertHalfToFloat(values[p*4+c]));
    need(finite==uint64_t(128)*128*3,"late owned trace copies remain finite after wrapper retirement");snapshot={};RecordedComputeLease::Poll();
    need(FfxApiProxy::destroys==destroys+1,"last trace observer releases exact context after all GPU work");
    std::cout<<"owned_observer after_wrapper_retirement=1 separate_copy_lease=1 exact_destroy=1\n";
}
void providerFailure(Host& host)
{
    Scene scene(host,128,128);host.submit();host.reset();RRWrapper wrapper;FrameParameters frame;std::string error;
    Readback beforeSpec(host,scene.spec()),beforeDiff(host,scene.diff());need(wrapper.PrepareFrame(camera(9000,1.f),false,frame,error),error.c_str());
    RRRecordedOutputLease output;const auto destroys=FfxApiProxy::destroys;FfxApiProxy::rejectDispatch=true;
    need(!wrapper.RecordOwned(host.list.Get(),scene.resources,frame,output,error)&&!output,"provider partial-write failure exposes no owned success handle");
    need(FfxApiProxy::lastSpecular.signal.output.resource!=scene.spec()&&FfxApiProxy::lastDiffuse.signal.output.resource!=scene.diff(),"failing provider received only private owned outputs");
    need(!wrapper.GetSettingsState().ready&&FfxApiProxy::destroys==destroys,"partial provider recording retires but remains GPU leased");
    Readback afterSpec(host,scene.spec()),afterDiff(host,scene.diff());host.submit();host.reset();FfxApiProxy::rejectDispatch=false;
    need(beforeSpec.values(128,128)==afterSpec.values(128,128)&&beforeDiff.values(128,128)==afterDiff.values(128,128),"actual GPU partial SDK writes never alter title outputs");
    need(FfxApiProxy::destroys==destroys+1,"failed private context destroys only after actual GPU completion");
    std::cout<<"owned_provider_failure actual_partial_writes=1 no_success_lease=1 exact_title_preservation=1\n";
}
}
int main(int argc,char** argv) try
{
    const std::string mode=argc>1?argv[1]:"--mock";need(mode=="--mock"||mode=="--real","owned fixture mode must be explicit mock or real");
    if(mode=="--real")loadReal();else {FfxApiProxy::recordPartialWrites=true;FfxApiProxy::mockSpec={1.5f,7.f,9.25f,99.f};FfxApiProxy::mockDiff={9.f,2.75f,.5f,98.f};}
    Host host;commitRootLayoutChecks();earlyLate(host);rejectPaths(host);discardAndGeneration(host);desiredSettings(host);observerLifetime(host);
    if(mode=="--mock")providerFailure(host);
    RecordedComputeLease::Poll();need(FfxApiProxy::live.empty()&&FfxApiProxy::creates==FfxApiProxy::destroys,"all owned contexts retire exactly after complete/destroyed fixture instances");
    need(FfxApiProxy::badCreateChains==0&&FfxApiProxy::badDefaults==0&&FfxApiProxy::badConfigureLayouts==0,"all original provider ABI/default checks remain strict");
    hr(host.list->Close());host.checkDebug();
    std::cout<<"PASS owned_checks="<<checks<<" mode="<<mode<<" creates="<<FfxApiProxy::creates<<" destroys="<<FfxApiProxy::destroys<<" dispatches="<<FfxApiProxy::dispatches<<" debug_errors=0 debug_warnings=0\n";return 0;
}
catch(const std::exception& e){std::cerr<<"FAIL owned_checks="<<checks<<": "<<e.what()<<'\n';return 1;}
