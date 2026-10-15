#pragma once
// Included only after the complete production coordinator and existing Title
// helpers. Legacy scenarios keep their original assertions and shader profile.
namespace NativeMotionCancellation
{
Wiring::DispatchFn original=nullptr;
bool armed=false,snapshotPresent=false,leaseSurvived=false;
unsigned calls=0;
std::weak_ptr<void> snapshot;
void Dispatch(ID3D12GraphicsCommandList* list,UINT x,UINT y,UINT z)
{
    if(armed&&!FrameSurvey::Internal()&&NrdBridge::gService)
    {
        const auto found=NrdBridge::gService->lists.find(list);
        if(found!=NrdBridge::gService->lists.end()&&found->second.role==Role::Temporal)
        {
            armed=false;++calls;snapshotPresent=bool(found->second.nativeMotionSnapshot);
            snapshot=found->second.nativeMotionSnapshot;
            NrdBridge::RequestHistoryReset();
            leaseSurvived=!snapshot.expired();
        }
    }
    original(list,x,y,z); // The original title Dispatch is forwarded exactly once.
}
}
void nativeConstantsWrite(ID3D12Resource* buffer,const std::vector<uint8_t>& bytes,bool stale)
{
    need(bytes.size()==1536,"native Temporal fixture has exactly1536 title CBV bytes");
    void* mapped=nullptr;hr(buffer->Map(0,nullptr,&mapped));std::memcpy(mapped,bytes.data(),bytes.size());
    if(stale)static_cast<float*>(mapped)[27*4+2]=-.25f;
    need(static_cast<UINT*>(mapped)[0]==55&&static_cast<UINT*>(mapped)[303]==0,"native Temporal packet preserves both original exact title CBV checksum and native Consumer RGB flag");
    buffer->Unmap(0,nullptr);
}
ComPtr<ID3D12Resource> nativeShadowReadback(Host& host,ID3D12Resource* shadow)
{
    auto target=host.buffer(256,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
    host.barrier(shadow,D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COPY_SOURCE);
    host.list->CopyBufferRegion(target.Get(),0,shadow,0,256);
    host.barrier(shadow,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_COMMON);
    return target;
}
void nativeMotionQualityCase(Host& h,Title& title,J& result,const std::filesystem::path& output,bool nativeEnabled)
{
    need(title.nativeProfile&&title.nativeViewDepth,"new native scenario uses a real original-title PrePass R32 producer and Temporal t4 reader");
    const auto input=output.parent_path()/"native_motion_input";
    const auto manifestBytes=qualityBytes(input/"sequence.json");const auto manifest=J::parse(manifestBytes);
    need(manifest["schema"]=="fsrd-world-native-motion-e2e-v1"&&manifest["width"]==128&&manifest["height"]==128&&manifest["submitted_frames"]==64,"native world-oracle input schema and64-frame temporal warmup");
    NrdBridge::RRSettings settings;settings.nativeTemporalMotion=nativeEnabled;std::string error;
    need(NrdBridge::ApplyRRSettings(settings,false,error),"apply native Temporal convention coherently before discovery");
    const unsigned initialCreates=FfxApiProxy::creates,initialCalls=FfxApiProxy::dispatches;
    const uint64_t initialBridged=NrdBridge::GetStatus().framesBridged;
    std::shared_ptr<NrdBridge::HistoryDomain> history;ffxContext context=nullptr;uint64_t warmedShadowBytes=0;
    J frames=J::array();std::vector<uint8_t> lastConstants;
    const std::array<std::pair<const char*,UINT>,5> slots{{{"spec",0},{"diff",1},{"normals",2},{"raw_view_z",3},{"native_motion",6}}};
    for(UINT index=0;index<64;++index)
    {
        const auto& frame=manifest["frames"][index];const auto directory=input/frame["directory"].get<std::string>();
        const UINT id=frame["frame"].get<UINT>();need(id==index+2,"native world-oracle frames are consecutive rendered evaluations");
        std::array<std::vector<uint8_t>,5> inputs;
        for(UINT n=0;n<slots.size();++n){const auto [name,slot]=slots[n];const UINT bpp=slot==2||slot==3?4:8;inputs[n]=qualityPayload(directory,frame["payloads"][name],size_t(title.width)*title.height*bpp);qualityUpload(title,slot,inputs[n],bpp);}
        const auto constants=qualityPayload(directory,frame["payloads"]["native_constants"],1536);
        const auto shadowBytes=qualityPayload(directory,frame["payloads"]["native_shadow"],256);
        const char* expectedKey=nativeEnabled?"expected_b":"expected_legacy_b";
        const auto expected=qualityPayload(directory,frame["payloads"][expectedKey],size_t(title.width)*title.height*4);
        nativeConstantsWrite(title.cb.Get(),constants,false);
        if(index==0)
        {
            title.begin(1);StreamlineHooks::snapshot=qualityCamera(frame,title.width,title.height,1);StreamlineHooks::snapshot.constants.reset=sl::Boolean::eFalse;
            title.pass(Role::PrepLast);title.pass(Role::Recon,8,true);h.uav(title.tex[4].Get());h.uav(title.tex[5].Get());title.tail();
            need(title.sentinel(title.finish())&&FfxApiProxy::dispatches==initialCalls,"native discovery prefix runs every original title shader and leaves NRD output untouched");
        }
        // Both real shader capture and original title Consumer see the final
        // execution-time bytes. Initial record-time scaleZ is deliberately wrong.
        nativeConstantsWrite(title.cb.Get(),constants,true);
        const unsigned beforeCalls=FfxApiProxy::dispatches,beforeRestores=restores;
        const uint64_t beforeBridged=NrdBridge::GetStatus().framesBridged;
        title.begin(id);StreamlineHooks::snapshot=qualityCamera(frame,title.width,title.height,id);
        title.pass(Role::PrepLast);title.pass(Role::Recon,8,true);h.uav(title.tex[4].Get());h.uav(title.tex[5].Get());title.tail();
        need(NrdBridge::GetStatus().active&&FfxApiProxy::dispatches==beforeCalls+1&&NrdBridge::GetStatus().framesBridged==beforeBridged+1,"every original-title native quality chain reaches one signed RR commit and Active");
        need(restores==beforeRestores+(nativeEnabled?4:3),"each Recon/before-Temporal-shadow/motion/RR injection restores complete original sparse compute state");
        const auto record=FfxApiProxy::records.back();const auto& state=NrdBridge::gService->lists.at(h.list.Get());
        need(state.parameters.nativeTemporalMotion==nativeEnabled,"Recon captures native convention exactly once for the frame ticket");
        if(!index){history=state.history;context=record.context;}else need(history==state.history&&context==record.context,"moving object/camera/jitter/fallback retains one physical RR context and history");
        need(FfxApiProxy::creates==initialCreates+1&&bool(record.flags&FFX_DENOISER_DISPATCH_RESET)==(index==0),"full native sequence creates one provider and only its first frame RESETs");
        ComPtr<ID3D12Resource> shadow;
        if(nativeEnabled)
        {
            auto* resource=NrdBridge::NativeTemporalCapture::Resource(state.nativeMotionSnapshot);
            need(resource&&state.motionReady,"production before-Temporal native shadow exists before deferred motion admission");shadow=nativeShadowReadback(h,resource);
            const auto bytes=state.history->nativeTemporalCapture.OwnedAuxiliaryBytes();if(!index)warmedShadowBytes=bytes;
            need(bytes==warmedShadowBytes&&bytes>0,"native shadow reuses its warmed owned slot without steady-state growth");
        }
        else need(!state.nativeMotionSnapshot&&state.history->nativeTemporalCapture.OwnedAuxiliaryBytes()==0,"native OFF allocates no shadow and records no native capture");
        const auto motion=motionCapture(title,record),nativeZ=title.readback(title.nativeViewDepth.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        const auto signedZ=title.readback(static_cast<ID3D12Resource*>(record.depth),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        const std::array<Readback,2> converted{title.readback(static_cast<ID3D12Resource*>(record.spec),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),title.readback(static_cast<ID3D12Resource*>(record.diff),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE)};
        const auto captured=title.capture();ComPtr<ID3D12Resource> replacement;
        if(title.tableConstants){replacement=h.upload(0,1536);nativeConstantsWrite(replacement.Get(),constants,false);title.bindConstants(replacement.Get(),56,false);}
        else nativeConstantsWrite(title.cb.Get(),constants,false);
        h.submit();const auto rgb=title.validate(captured);title.rrChecks(rgb);
        for(UINT signal=0;signal<2;++signal)need(converted[signal].signal()==title.raw[signal],"native mode preserves every current finite noisy native RGB and hit-alpha bit");
        if(nativeEnabled){void* mapped=nullptr;hr(shadow->Map(0,nullptr,&mapped));need(std::memcmp(mapped,shadowBytes.data(),256)==0,"actual direct/table GPU capture copies all256 selected native operand bytes from final execution-time binding");shadow->Unmap(0,nullptr);}
        void* nativeMap=nullptr;void* signedMap=nullptr;hr(nativeZ.resource->Map(0,nullptr,&nativeMap));hr(signedZ.resource->Map(0,nullptr,&signedMap));
        const auto gpuMotion=motion.signal();const auto* rawZ=reinterpret_cast<const float*>(inputs[3].data());const auto* rawMV=reinterpret_cast<const uint16_t*>(inputs[4].data());const auto* expectedB=reinterpret_cast<const float*>(expected.data());
        bool exactNativeZ=true,exactCurrentZ=true,exactXY=true,correctB=true;const auto& parameters=state.parameters;
        for(UINT y=0;y<title.height;++y)for(UINT x=0;x<title.width;++x)
        {
            const size_t pixel=size_t(y)*title.width+x,at=4*pixel;
            const float currentNative=reinterpret_cast<const float*>(static_cast<const uint8_t*>(nativeMap)+size_t(y)*nativeZ.footprint.Footprint.RowPitch)[x];
            const float currentSigned=reinterpret_cast<const float*>(static_cast<const uint8_t*>(signedMap)+size_t(y)*signedZ.footprint.Footprint.RowPitch)[x];
            exactNativeZ&=std::bit_cast<UINT>(currentNative)==std::bit_cast<UINT>(rawZ[pixel]);exactCurrentZ&=std::bit_cast<UINT>(currentSigned)==std::bit_cast<UINT>(-rawZ[pixel]);
            for(UINT c=0;c<2;++c){const float jitter=c?(parameters.previousJitter.y-parameters.jitter.y)/title.height:(parameters.previousJitter.x-parameters.jitter.x)/title.width;exactXY&=std::abs(PackedVector::XMConvertHalfToFloat(gpuMotion[at+c])-(PackedVector::XMConvertHalfToFloat(rawMV[at+c])+jitter))<.0002f;}
            if(x>=16&&x+16<title.width&&y>=16&&y+16<title.height)correctB&=std::abs(PackedVector::XMConvertHalfToFloat(gpuMotion[at+2])-expectedB[pixel])<.005f;
        }
        nativeZ.resource->Unmap(0,nullptr);signedZ.resource->Unmap(0,nullptr);
        need(exactNativeZ&&exactCurrentZ,"actual title PrePass t4 and bridge signed depth carry every current native source pixel");need(exactXY,"native full-B feature preserves the canonical XY and single jitter delta");
        need(correctB,"GPU motion B agrees with independent previous-world/object/camera oracle or explicit camera fallback");
        void* checksum=nullptr;hr(captured.read->Map(0,nullptr,&checksum));need(static_cast<const UINT*>(checksum)[4*16+12]==std::bit_cast<UINT>(5.f),"original Temporal GPU reads current native R32 t4 after shadow and motion root/heap/PSO restoration");captured.read->Unmap(0,nullptr);
        const std::string prefix="frame"+std::string(3-std::to_string(id).size(),'0')+std::to_string(id);J hashes;
        hashes["spec"]=qualitySave(output/(prefix+"-spec.bin"),rgb[0]);hashes["diff"]=qualitySave(output/(prefix+"-diff.bin"),rgb[1]);hashes["motion"]=qualitySave(output/(prefix+"-motion.bin"),gpuMotion);
        frames.push_back({{"frame",id},{"reset",index==0},{"native_enabled",nativeEnabled},{"camera_fallback",frame["fallback"]},{"late_binding",title.tableConstants?"volatile table replacement":"direct upload contents update"},{"output_sha256",hashes}});
        h.reset();lastConstants=constants;
    }
    need(FfxApiProxy::dispatches==initialCalls+64&&NrdBridge::GetStatus().framesBridged==initialBridged+64,"all64 continuous original-title quality chains bridge without cancellation or missed frame");
    if(nativeEnabled)
    {
        const unsigned calls=FfxApiProxy::dispatches,beforeRestores=restores;
        NativeMotionCancellation::original=Wiring::o_Dispatch;NativeMotionCancellation::armed=true;Wiring::o_Dispatch=&NativeMotionCancellation::Dispatch;
        nativeConstantsWrite(title.cb.Get(),lastConstants,false);title.frame(66);Wiring::o_Dispatch=NativeMotionCancellation::original;
        need(NativeMotionCancellation::calls==1&&NativeMotionCancellation::snapshotPresent&&NativeMotionCancellation::leaseSurvived,"normal original-Temporal dispatch gap cancels AFTER actual GPU capture while its recording lease remains alive");
        need(FfxApiProxy::dispatches==calls&&restores==beforeRestores+2,"canceled captured frame records only Recon/shadow and no motion/RR work");
        need(title.sentinel(title.finish()),"captured-then-canceled frame runs every original NRD shader and leaves exact native sentinel RGBA untouched");
        need(NativeMotionCancellation::snapshot.expired(),"submitted canceled shadow lease retires after real GPU completion and Reset");
        title.frame(67);need(FfxApiProxy::dispatches==calls+1&&(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET),"next native frame recovers with an explicit fresh RR RESET");title.rrChecks(title.finish());
        const unsigned modeCalls=FfxApiProxy::dispatches,modeRestores=restores;
        title.recon(68);settings.nativeTemporalMotion=false;need(NrdBridge::ApplyRRSettings(settings,false,error),"native OFF change is a coherent frame cancellation");title.tail();
        need(FfxApiProxy::dispatches==modeCalls&&restores==modeRestores+1&&title.sentinel(title.finish()),"native OFF during a frame cancels its pending work and preserves original title RGBA");
        title.frame(69);need(restores==modeRestores+4&&FfxApiProxy::dispatches==modeCalls+1&&(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET),"next OFF frame performs only three original bridge restores with RESET");title.rrChecks(title.finish());
        settings.nativeTemporalMotion=true;need(NrdBridge::ApplyRRSettings(settings,false,error),"native ON restores a coherent future frame convention");const unsigned onRestores=restores;title.frame(70);
        need(restores==onRestores+4&&FfxApiProxy::dispatches==modeCalls+2&&(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET),"native ON next frame recovers all four injections and a new history RESET");title.rrChecks(title.finish());
    }
    result["native_motion_quality"]={{"native_enabled",nativeEnabled},{"table_binding",title.tableConstants},{"submitted_quality_frames",64},{"source_manifest_sha256",RRTraceAdditiveIO::Sha256({manifestBytes.data(),manifestBytes.size()})},{"same_history_context",true},{"first_only_quality_reset",true},{"current_prepass_r32_t4_every_pixel",true},{"full_native_shadow_256_bytes",nativeEnabled},{"warmed_shadow_bytes",warmedShadowBytes},{"post_capture_cancel_recovered",nativeEnabled},{"frames",frames},{"scope",manifest["native_operand_scope"]},{"native_world_mode_tested",false}};
}
