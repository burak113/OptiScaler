"""Focused full-native diagnostic recorder WARP host; manufactured GPU words.

Each invocation prepares, compiles, or runs, never all three. Root admits the
WARP invocation separately from hardware replay. Two 1505x847 RGBA16F diagnostic
heads are cropped to x688/128x847 by the unchanged production recorder. The
seven-input full-copy loop is extracted verbatim from the diagnostic helper,
but its SDK creation/dispatch and lifetime admission are deliberately NOT_RUN.
No game pixels, RR quality claim, production performance claim, or installation.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))
from fsrd_toolchain import compile_cpp

PRODUCT = ROOT/'OptiScaler/shaders/fsrd_preprocess'
HELPER = ROOT/'OptiScaler/upscalers/fsr31/FSRDFullContextReference_Dx12.h'

CPP = r'''
#include "fsrd_full_context_reference_pure.inc"
struct ReferenceHost : Host
{
    std::array<ComPtr<ID3D12Resource>,2> primaryHeads,referenceHeads;
    struct Storage { std::array<ComPtr<ID3D12Resource>,7> inputs; } storage;
    struct FrameLease { std::array<ComPtr<ID3D12Resource>,7> sources; } lease;
    ComPtr<ID3D12Resource> smallHead;
    std::vector<ComPtr<ID3D12Resource>> cloneReadbacks;
    std::vector<D3D12_PLACED_SUBRESOURCE_FOOTPRINT> cloneFootprints;
    const std::array<size_t,7> canonical {6,7,5,2,3,1,0};
    const std::array<uint32_t,7> ffxFormats {28,4,17,10,10,4,4};
    const std::array<const char*,7> roles {"linear_depth","motion_vectors","normals","specular_albedo",
        "diffuse_albedo","DirectDiffuse.input","IndirectSpecular.input"};
    const std::array<const char*,7> bindingRoles {"linear_depth","motion_vectors","normals","specular_albedo",
        "diffuse_albedo","chain.0.DirectDiffuse.input","chain.1.IndirectSpecular.input"};
    uint64_t allocatedTextureBytes=0,sourceCloneComparedBytes=0;
    ReferenceHost() : Host(1505,0,0,847)
    {
        D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        for (size_t i=0;i<7;++i)
        {
            auto d=textures[canonical[i]]->GetDesc();
            hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,srv,nullptr,
                IID_PPV_ARGS(&storage.inputs[i])));
        }
        auto d=textures[0]->GetDesc(); d.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        for (auto* heads : {&primaryHeads,&referenceHeads}) for (auto& image:*heads)
            hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                nullptr,IID_PPV_ARGS(&image)));
        d.Width=128;
        hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
            nullptr,IID_PPV_ARGS(&smallHead)));
        for (const auto& image:textures) Account(image.Get());
        for (const auto& image:storage.inputs) Account(image.Get());
        for (const auto& image:primaryHeads) Account(image.Get());
        for (const auto& image:referenceHeads) Account(image.Get());
        Account(smallHead.Get());
    }
    void Account(ID3D12Resource* image)
    { const auto d=image->GetDesc(); allocatedTextureBytes+=device->GetResourceAllocationInfo(0,1,&d).SizeInBytes; }
    static uint32_t Bpp(DXGI_FORMAT format)
    { return format==DXGI_FORMAT_R16G16B16A16_FLOAT ? 8u : format==DXGI_FORMAT_R8_UNORM ? 1u : 4u; }
    static uint8_t InputByte(size_t role,unsigned frame,unsigned x,unsigned y,unsigned byte)
    { return uint8_t((role*11+frame*5+x*3+y+byte*7)&255); }
    static uint16_t HeadWord(size_t head,unsigned frame,unsigned x,unsigned y,unsigned channel)
    { return uint16_t(0x2000+head*0x400+frame*64+x+y+channel); }
    void FillTexture(ID3D12Resource* image,D3D12_RESOURCE_STATES state,unsigned frame,size_t role,bool head)
    {
        const auto d=image->GetDesc(); D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp {}; UINT64 bytes=0;
        device->GetCopyableFootprints(&d,0,1,0,&fp,nullptr,nullptr,&bytes);
        D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_UPLOAD;
        D3D12_RESOURCE_DESC bd {}; bd.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
        bd.Width=bytes; bd.Height=1; bd.DepthOrArraySize=bd.MipLevels=1; bd.SampleDesc.Count=1;
        bd.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> upload;
        hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&bd,D3D12_RESOURCE_STATE_GENERIC_READ,
            nullptr,IID_PPV_ARGS(&upload)));
        void* data=nullptr; D3D12_RANGE empty {0,0}; hr(upload->Map(0,&empty,&data));
        memset(data,0,size_t(bytes)); const auto bpp=Bpp(d.Format);
        for (unsigned y=0;y<d.Height;++y) for (unsigned x=0;x<d.Width;++x)
            if (head) for (unsigned c=0;c<4;++c)
            {
                const uint16_t value=HeadWord(role,frame,x,y,c);
                memcpy(static_cast<uint8_t*>(data)+fp.Offset+y*fp.Footprint.RowPitch+x*8+c*2,&value,2);
            }
            else for (unsigned byte=0;byte<bpp;++byte)
                static_cast<uint8_t*>(data)[fp.Offset+y*fp.Footprint.RowPitch+x*bpp+byte]=InputByte(role,frame,x,y,byte);
        upload->Unmap(0,nullptr);
        auto b=Transition(image,state,D3D12_RESOURCE_STATE_COPY_DEST); list->ResourceBarrier(1,&b);
        D3D12_TEXTURE_COPY_LOCATION src {},dst {};
        src.pResource=upload.Get(); src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint=fp;
        dst.pResource=image; dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
        std::swap(b.Transition.StateBefore,b.Transition.StateAfter); list->ResourceBarrier(1,&b);
        uploads.push_back(std::move(upload));
    }
    static D3D12_RESOURCE_BARRIER Transition(ID3D12Resource* image,D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after)
    { D3D12_RESOURCE_BARRIER result {}; result.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
      result.Transition={image,0,before,after}; return result; }
    void FillFixture(unsigned frame)
    {
        uploads.clear();
        for (size_t i=0;i<textures.size();++i) FillTexture(textures[i].Get(),srv,frame,i,false);
        for (size_t i=0;i<2;++i)
        {
            FillTexture(primaryHeads[i].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,frame,i+2,true);
            FillTexture(referenceHeads[i].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,frame,i,true);
        }
    }
    void CopyInputsUsingProductLoop()
    {
        std::array<ID3D12Resource*,7> sources {},clones {};
        for (size_t i=0;i<7;++i)
        {
            lease.sources[i]=textures[canonical[i]];
            sources[i]=lease.sources[i].Get(); clones[i]=storage.inputs[i].Get();
        }
        FSRD::FullContextReference::RecordFullInputSnapshot(list.Get(),sources,clones);
    }
    void SnapshotClones()
    {
        cloneReadbacks.clear(); cloneFootprints.clear();
        for (const auto& image:storage.inputs)
        {
            const auto d=image->GetDesc(); D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp {}; UINT64 bytes=0;
            device->GetCopyableFootprints(&d,0,1,0,&fp,nullptr,nullptr,&bytes);
            D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_READBACK;
            D3D12_RESOURCE_DESC bd {}; bd.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER; bd.Width=bytes;
            bd.Height=1; bd.DepthOrArraySize=bd.MipLevels=1; bd.SampleDesc.Count=1;
            bd.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
            ComPtr<ID3D12Resource> readback;
            hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&bd,D3D12_RESOURCE_STATE_COPY_DEST,
                nullptr,IID_PPV_ARGS(&readback)));
            auto b=Transition(image.Get(),srv,D3D12_RESOURCE_STATE_COPY_SOURCE); list->ResourceBarrier(1,&b);
            D3D12_TEXTURE_COPY_LOCATION src {},dst {}; src.pResource=image.Get();
            src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX; dst.pResource=readback.Get();
            dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint=fp;
            list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
            std::swap(b.Transition.StateBefore,b.Transition.StateAfter); list->ResourceBarrier(1,&b);
            cloneReadbacks.push_back(std::move(readback)); cloneFootprints.push_back(fp);
        }
    }
    void CompareClones(unsigned frame)
    {
        for (size_t i=0;i<7;++i)
        {
            const auto d=storage.inputs[i]->GetDesc(); const auto bpp=Bpp(d.Format); auto fp=cloneFootprints[i];
            void* data=nullptr; const D3D12_RANGE range {0,size_t(cloneReadbacks[i]->GetDesc().Width)};
            hr(cloneReadbacks[i]->Map(0,&range,&data));
            for (unsigned y=0;y<d.Height;++y) for (unsigned x=0;x<d.Width;++x) for (unsigned c=0;c<bpp;++c)
            {
                const auto actual=static_cast<uint8_t*>(data)[fp.Offset+y*fp.Footprint.RowPitch+x*bpp+c];
                need(actual==InputByte(canonical[i],frame,x,y,c),"full-native immutable input clone word changed");
                ++sourceCloneComparedBytes;
            }
            D3D12_RANGE noWrite {0,0}; cloneReadbacks[i]->Unmap(0,&noWrite);
        }
    }
    Json Bindings() const
    {
        Json result=Json::array();
        for (size_t i=0;i<9;++i)
        {
            auto* resource=i<7 ? textures[canonical[i]].Get() : primaryHeads[i-7].Get();
            const auto d=resource->GetDesc();
            const char* role=i<7 ? bindingRoles[i] : i==7 ? "chain.0.DirectDiffuse.output" : "chain.1.IndirectSpecular.output";
            Json ffx={{"type",2},{"format",i<7 ? ffxFormats[i] : 4u},{"width_or_size",renderWidth},
                {"height_or_stride",renderHeight},{"depth_or_alignment",1},{"mip_count",1},{"flags",0},{"usage",2}};
            result.push_back({{"role",role},{"present",true},{"resource_address_process_local",Address(resource)},
                {"native_description",FSRD::FullContextReference::NativeDescription(d)},
                {"ffx_description",ffx},{"ffx_declared_state",i<7 ? 12 : 2}});
        }
        return result;
    }
    static uint64_t Address(const void* pointer) { return uint64_t(reinterpret_cast<uintptr_t>(pointer)); }
    Trace::FrameInfo ReferenceFrame(unsigned index)
    {
        auto info=Frame(index,index==1); info.dispatchFlags=2u|uint32_t(info.reset);
        auto controls=Json::parse(info.controlsJson);
        controls["rr_dispatch"]={{"schema","actual_RR_pre_SDK_dispatch_v1"},{"bindings",Bindings()},
            {"context_generation",uint64_t(8)},{"evaluation_id",info.evaluationId},{"native_frame_index",info.frameIndex},
            {"dispatch_flags",info.dispatchFlags},{"render_size",{renderWidth,renderHeight}},
            {"command_list",{{"address_process_local",Address(list.Get())},{"type",0}}}};
        info.controlsJson=controls.dump();
        Json contract={{"provider_id",uint64_t(4311875584)},{"provider_index",0},
            {"provider_name","FSR Ray Regeneration - 1.2.0"},
            {"provider_selection_provenance","manufactured_test_contract_not_an_observed_SDK_provider"},
            {"api_version",4202496},{"max_render_size",{renderWidth,renderHeight}},
            {"create_flags",0},{"signal_flags",34},{"checkerboard_signal_flags",0}};
        auto settings=Json::parse(info.settingsJson);
        settings["rr_create_contract"]=contract; settings["sdk_debug_depth_bounds"]={0.f,1024.f};
        settings["fixture_scope"]="manufactured_words_recorder_only_no_SDK_dispatch";
        info.settingsJson=settings.dump(); return info;
    }
    Json Boundary(const Trace::FrameInfo& info,unsigned index)
    {
        const auto controls=Json::parse(info.controlsJson),settings=Json::parse(info.settingsJson);
        ffxDispatchDescDenoiser primary {},reference {};
        primary.motionVectorScale={2.f,3.f,4.f}; primary.renderSize={renderWidth,renderHeight};
        auto assign=[&](auto& target,const char* key) {
            for (size_t i=0;i<controls[key].size();++i) { float value=controls[key][i].get<float>();
                memcpy(reinterpret_cast<uint8_t*>(&target)+4*i,&value,4); }
        };
        assign(primary.view,"view"); assign(primary.projection,"projection"); assign(primary.jitterOffsets,"jitter");
        assign(primary.cameraPositionDelta,"camera_delta"); assign(primary.linearDepthBounds,"depth_bounds");
        primary.frameIndex=info.frameIndex; primary.flags=info.dispatchFlags;
        ffxDispatchDescDenoiserDirectDiffuse diffuse {},originalDiffuse {};
        ffxDispatchDescDenoiserIndirectSpecular specular {},originalSpecular {};
        std::array<ID3D12Resource*,7> inputs {};
        for (size_t i=0;i<7;++i) inputs[i]=storage.inputs[i].Get();
        FSRD::FullContextReference::RebuildResetDispatch(primary,originalDiffuse,originalSpecular,inputs,
            referenceHeads[1].Get(),referenceHeads[0].Get(),reference,diffuse,specular);
        need(FSRD::FullContextReference::OnlyResetControlChanged(primary,reference),"product RESET-only helper changed controls");
        Json clones=Json::array(); auto bindings=Bindings();
        for (size_t i=0;i<7;++i)
        {
            auto d=storage.inputs[i]->GetDesc(); const auto allocation=device->GetResourceAllocationInfo(0,1,&d);
            clones.push_back({{"role",roles[i]},{"original_resource_address_process_local",Address(textures[canonical[i]].Get())},
                {"clone_resource_address_process_local",Address(storage.inputs[i].Get())},
                {"source_native_description",bindings[i]["native_description"]},
                {"clone_native_description",FSRD::FullContextReference::NativeDescription(d)},
                {"ffx_description",bindings[i]["ffx_description"]},{"ffx_declared_state",12},
                {"source_state",uint32_t(srv)},{"clone_entry_exit_state",uint32_t(srv)},
                {"copy_subresource",0},{"copy_mip",0},{"copy_array_slice",0},{"copy_plane",0},
                {"copy_extent",{renderWidth,renderHeight}},{"allocation_size_bytes",allocation.SizeInBytes},
                {"allocation_alignment_bytes",allocation.Alignment}});
        }
        return {{"wireformat","ffxDispatchDescDenoiser_native_ABI_suffix_264_184"},{"native_dispatch_bytes",448},
            {"controls_byte_count",184},{"controls_offset_in_dispatch",264},{"controls_flags_offset_in_segment",180},
            {"evaluation_id",info.evaluationId},{"frame_index",info.frameIndex},{"primary_dispatch_flags",info.dispatchFlags},
            {"dispatch_flags",info.dispatchFlags|1u},{"render_size",{renderWidth,renderHeight}},
            {"context_generation",uint64_t(3)},{"reference_evaluation_id",uint64_t(index+1)},
            {"primary_context_generation",uint64_t(8)},{"primary_pre_sdk_boundary",controls["rr_dispatch"]},
            {"command_list_address_process_local",Address(list.Get())},{"command_list_type",0},
            {"create_contract",settings["rr_create_contract"]},{"sdk_tuning",settings["sdk_tuning"]},
            {"sdk_debug_depth_bounds",settings["sdk_debug_depth_bounds"]},{"controls",controls},
            {"primary_control_words_hex",FSRD::FullContextReference::ControlWordsHex(primary)},
            {"diagnostic_control_words_hex",FSRD::FullContextReference::ControlWordsHex(reference)},{"clones",clones}};
    }
    std::vector<Trace::DiagnosticSource> Outputs(const Trace::FrameInfo& info,unsigned index)
    {
        std::vector<Trace::DiagnosticSource> result;
        result.push_back({"rr_specular",{primaryHeads[1].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS}});
        result.push_back({"rr_diffuse",{primaryHeads[0].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS}});
        const auto boundary=Boundary(info,index);
        for (size_t i=0;i<2;++i)
        {
            Trace::DiagnosticSource image;
            image.name=i==0 ? "rr_full_context_reset_specular" : "rr_full_context_reset_diffuse";
            image.image={referenceHeads[i].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
            image.required=true;
            image.metadataJson=Json{{"mode","full_native_reset_each_not_solution"},
                {"role","diagnostic_sdk_reset_each_lobe"},{"stage","post_diagnostic_sdk_pre_sr_capture"},
                {"lobe",i==0 ? "specular" : "diffuse"},{"reference_boundary",boundary}}.dump();
            result.push_back(std::move(image));
        }
        return result;
    }
};
int main(int argc,char** argv) try
{
    need(argc==2,"absolute F: scratch output required");
    const auto output=std::filesystem::path(argv[1]); g_dllPath=output/"test-only.dll";
    ReferenceHost host; Json captures=Json::object(),checks=Json::array();
    auto start=[&](const char* name) {
        Trace::Request request; request.x=688; request.regionMode=Trace::Request::RegionMode::FullHeightStrip;
        request.fullContextReference=true; request.outputRoot=(output/"captures").string();
        need(Trace::RequestStart(request),"diagnostic request rejected"); captures[name]=Trace::GetStatus().folder;
    };
    {
        Trace capture; start("published_two_heads");
        for (unsigned frame=0;frame<2;++frame)
        {
            host.FillFixture(frame); host.CopyInputsUsingProductLoop();
            // A later primary input write cannot change the earlier full clone.
            host.FillTexture(host.textures[0].Get(),srv,frame+7,0,false);
            host.SnapshotClones(); need(host.Admit(capture),"diagnostic sources not admitted");
            auto info=host.ReferenceFrame(frame); auto heads=host.Outputs(info,frame);
            capture.RecordNative(host.list.Get(),{host.textures[4].Get(),srv},info,heads);
            capture.CompleteFrame(host.list.Get(),{host.textures[4].Get(),srv});
            need(Trace::GetStatus().recorded==frame+1,"diagnostic ordinal missing before submission");
            need(Trace::GetStatus().captured==frame,"unexecuted command list published GPU pixels");
            host.Execute(); host.CompareClones(frame); capture.Poll(); Published(frame+1);
            need(Trace::GetStatus().awaitingDetach>=1,"fence completion forged command-list Reset detach");
            host.Reset(); capture.Poll();
        }
        Trace::RequestStop(); Closed();
        need(Trace::GetStatus().captured==2 && Trace::GetStatus().manifestPublished==2,"immutable published prefix lost");
        checks.push_back("two_full_native_heads_exact_strip_fence_publication_and_Reset");
        checks.push_back("seven_full_native_clones_survive_later_source_write_verbatim_product_copy_loop");
    }
    for (const std::string mode:{"missing_head","head_alias","primary_alias","wrong_extent","wrong_state",
                                 "different_head_boundary","native_non_RESET_mutation","wrong_command_list"})
    {
        Trace capture; start(mode.c_str()); host.FillFixture(0); need(host.Admit(capture),"negative fixture admission");
        auto info=host.ReferenceFrame(0); auto heads=host.Outputs(info,0);
        if (mode=="missing_head") heads.pop_back();
        if (mode=="head_alias") heads[3].image.resource=heads[2].image.resource;
        if (mode=="primary_alias") heads[2].image.resource=host.primaryHeads[0].Get();
        if (mode=="wrong_extent") heads[2].image.resource=host.smallHead.Get();
        if (mode=="wrong_state") heads[2].image.state=srv;
        if (mode=="different_head_boundary")
        { auto j=Json::parse(heads[3].metadataJson); j["reference_boundary"]["context_generation"]=uint64_t(4); heads[3].metadataJson=j.dump(); }
        if (mode=="native_non_RESET_mutation")
        { for (auto i:{2u,3u}) { auto j=Json::parse(heads[i].metadataJson); auto hex=j["reference_boundary"]["diagnostic_control_words_hex"].get<std::string>();
            hex[0]=hex[0]=='0' ? '1' : '0'; j["reference_boundary"]["diagnostic_control_words_hex"]=hex; heads[i].metadataJson=j.dump(); } }
        if (mode=="wrong_command_list")
        { for (auto i:{2u,3u}) { auto j=Json::parse(heads[i].metadataJson); j["reference_boundary"]["command_list_address_process_local"]=uint64_t(1); heads[i].metadataJson=j.dump(); } }
        const auto beforeNative=Trace::GetStatus().retainedReadbackBytes;
        capture.RecordNative(host.list.Get(),{host.textures[4].Get(),srv},info,heads);
        need(Trace::GetStatus().retainedReadbackBytes==beforeNative,"invalid boundary allocated primary/reference output readbacks");
        Closed();
        need(Trace::GetStatus().captured==0 && Trace::GetStatus().manifestPublished==0,"invalid reference head published");
        host.Execute(); host.Reset(); capture.Poll(); checks.push_back(mode+"_rejected_before_reference_readback");
    }
    for (const std::string mode:{"context_generation_change","reference_evaluation_gap"})
    {
        Trace capture; start(mode.c_str());
        for (unsigned frame=0;frame<2;++frame)
        {
            host.FillFixture(frame); need(host.Admit(capture),"lineage fixture admission");
            auto info=host.ReferenceFrame(frame); auto heads=host.Outputs(info,frame);
            if (frame) for (auto i:{2u,3u})
            { auto j=Json::parse(heads[i].metadataJson); j["reference_boundary"][mode=="context_generation_change" ? "context_generation" : "reference_evaluation_id"]=uint64_t(4);
                heads[i].metadataJson=j.dump(); }
            capture.RecordNative(host.list.Get(),{host.textures[4].Get(),srv},info,heads);
            if (!frame) capture.CompleteFrame(host.list.Get(),{host.textures[4].Get(),srv});
            host.Execute(); host.Reset(); capture.Poll();
            if (!frame) Published(1);
        }
        Closed(); need(Trace::GetStatus().captured==1 && Trace::GetStatus().manifestPublished==1,"lineage rejection lost/expanded immutable prefix");
        checks.push_back(mode+"_preserves_only_published_prefix");
    }
    {
        Trace capture; start("discarded_before_submission"); host.FillFixture(0); need(host.Admit(capture),"discard fixture admission");
        auto info=host.ReferenceFrame(0); auto heads=host.Outputs(info,0);
        capture.RecordNative(host.list.Get(),{host.textures[4].Get(),srv},info,heads);
        capture.CompleteFrame(host.list.Get(),{host.textures[4].Get(),srv}); host.Discard(); capture.Poll(); Closed();
        need(Trace::GetStatus().captured==0 && Trace::GetStatus().manifestPublished==0,"unsubmitted Reset exposed reference words");
        checks.push_back("unsubmitted_Reset_does_not_publish");
    }
    {
        Trace capture; start("insufficient_disk_preflight");
        need(!host.Sources(capture),"uninitialized diagnostic disk request recorded early");
        Await([] { std::scoped_lock lock(Global().mutex); return Global().current->initialized; },"disk fixture not initialized");
        const auto before=Trace::GetStatus().retainedReadbackBytes;
        uint64_t expectedRequired=0;
        {
            std::scoped_lock lock(Global().mutex); auto& s=*Global().current;
            ResolveRegion(s,1505,847);
            const auto core=CoreBytes(host.device.Get(),s,0,Names.size());
            const auto diagnostic=DiagnosticBytes(host.device.Get(),s,host.diagnostics,0,DiagnosticNames.size());
            const auto reference=FullContextReferenceBytes(host.device.Get(),s);
            need(reference.first==128ull*847*16,"real two-head payload planning changed");
            const uint64_t oldTarget=(592+core.first+diagnostic.first)*128;
            const uint64_t withReference=oldTarget+reference.first*128;
            s.diskAvailable=oldTarget+oldTarget/20+(1ull<<20)+(256ull<<20);
            expectedRequired=withReference+withReference/20+(1ull<<20)+(256ull<<20);
            need(s.diskAvailable<expectedRequired,"budget fixture does not isolate the added two heads");
        }
        need(!host.Sources(capture),"insufficient diagnostic disk copied GPU sources"); Closed();
        need(Trace::GetStatus().recorded==0 && Trace::GetStatus().retainedReadbackBytes==before &&
            Trace::GetStatus().message.find("128-frame destination preflight including 5% allowance requires "+
                std::to_string(expectedRequired)+" bytes")!=std::string::npos,
            "diagnostic budget rejection allocated readbacks or lacked byte diagnostic");
        checks.push_back("two_heads_included_in_destination_preflight_fail_closed");
    }
    host.NoGpuErrors();
    Json report={{"schema","fsrd-full-context-reference-warp-v1"},{"status","PASS"},{"adapter","WARP"},
        {"sdk_dispatches",0},{"render_extent",{1505,847}},{"readback_origin",{688,0}},
        {"readback_extent",{128,847}},{"published_positive_frames",2},{"checks",checks},
        {"native_texture_allocation_bytes",host.allocatedTextureBytes},
        {"full_native_clone_compared_bytes",host.sourceCloneComparedBytes},
        {"helper_runtime_coverage",{{"PrepareSnapshot","NOT_RUN"},{"SDK_context_and_provider_attestation","NOT_RUN"},
            {"FrameLease_and_ResTrack_admission","NOT_RUN"},{"seven_input_GPU_copy_loop","SOURCE_EXTRACTED_WARP"},
            {"RESET_descriptor_rebuild","SOURCE_EXTRACTED"}}},
        {"limitations","manufactured words/contracts; no real SDK dispatch, game pixels, IQ or performance claim"}};
    RRTraceAdditiveIO::WriteText(output/"captures.json",captures.dump(2));
    RRTraceAdditiveIO::WriteText(output/"native_warp_receipt.json",report.dump(2));
    std::cout<<report.dump(2)<<'\n'; return 0;
}
catch (const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
'''


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def source_files():
    sdk_api = ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'
    sdk_v2 = ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX'
    # The local RR compatibility header contains its own RR types. Pin the
    # SDK API headers it actually includes and the official RR ABI counterpart.
    return [Path(__file__).resolve(), HERE/'test_fsrd_game_trace_capture.py', HERE/'fsrd_real_capture_replay.py',
            HERE.parent/'fsrd_toolchain.py', PRODUCT/'FSRDGameTraceSession.cpp', PRODUCT/'FSRDGameTraceSession.h',
            PRODUCT/'RRTraceFence.h', PRODUCT/'RRTraceFenceState.h', PRODUCT/'RRTraceAdditiveIO.h', HELPER,
            ROOT/'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp', ROOT/'OptiScaler/include/fsr-rr/ffx_denoiser.h',
            sdk_api/'ffx_api.h', sdk_api/'ffx_api_types.h', sdk_api/'dx12/ffx_api_dx12.h', sdk_api/'ffx_upscale.h',
            ROOT/'external/nlohmann/json.hpp', sdk_v2/'denoisers/include/ffx_denoiser.h',
            sdk_v2/'api/include/ffx_api.h', sdk_v2/'api/include/ffx_api_types.h']


def fingerprint():
    return {str(path): digest(path) for path in source_files()}


def prepare(output):
    spec = importlib.util.spec_from_file_location('recorder_host_source_only', HERE/'test_fsrd_game_trace_capture.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    base = module.CPP[:module.CPP.index('void CpuChecks(')]
    # Native RR inputs require UAV-capable allocations; their actual state stays
    # PIXEL|NON_PIXEL until the verbatim product copy loop temporarily transitions.
    needle = 'd.SampleDesc.Count=1; d.Format=formats[i];'
    assert base.count(needle) == 1
    base = base.replace(needle, needle+' d.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;')
    helper = HELPER.read_text(encoding='utf-8-sig')
    namespace_start = helper.index('namespace FSRD::FullContextReference')
    namespace_end = helper.index('// Diagnostic only:', namespace_start)
    pure = helper[namespace_start:namespace_end]
    copy_start = helper.index('inline void RecordFullInputSnapshot(')
    barrier_start = helper.index('list->ResourceBarrier(UINT(barriers.size()), barriers.data());', copy_start)
    copy_end = helper.index('list->ResourceBarrier(UINT(barriers.size()), barriers.data());', barrier_start+1)
    copy_end += len('list->ResourceBarrier(UINT(barriers.size()), barriers.data());')
    copy_loop = helper[copy_start:copy_end]
    assert copy_loop.count('CopyTextureRegion(') == 1 and 'sources.size()' in copy_loop
    stubs = output/'stubs'; stubs.mkdir(exist_ok=True)
    (stubs/'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n')
    (stubs/'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\n'
                              'namespace Util { inline std::filesystem::path DllPath() { return g_dllPath; } }\n')
    feature = (ROOT/'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp').read_text(encoding='utf-8-sig')
    controls_start = feature.index('const auto array =', feature.index('if (FSRDGameTraceSession::IsActive())'))
    controls_end = feature.index('// Fingerprint applied semantic controls only.', controls_start)
    sr_start = feature.index('const CaptureJson controls {', feature.index('if (FSRDConvShader && FSRDGameTraceSession::WantsSrOutput())'))
    sr_end = feature.index("// FSR's output is UAV here.", sr_start)
    (stubs/'fsrd_game_trace_controls.inc').write_text(feature[controls_start:controls_end], encoding='utf-8')
    (stubs/'fsrd_game_trace_sr_controls.inc').write_text(feature[sr_start:sr_end], encoding='utf-8')
    (stubs/'fsrd_full_context_reference_pure.inc').write_text(pure, encoding='utf-8')
    source = output/'fsrd_full_context_reference_warp.cpp'
    source.write_text(base.replace('__RECORDER__', (PRODUCT/'FSRDGameTraceSession.cpp').as_posix()).replace(
        '__RR_HEADER__', (ROOT/'OptiScaler/include/fsr-rr/ffx_denoiser.h').as_posix())+CPP, encoding='utf-8')
    generated = [source, *sorted(stubs.iterdir())]
    receipt = dict(schema='fsrd-full-context-reference-warp-preparation-v1', status='PREPARED_ONLY', gpu_work=0,
                   builds=0, source_sha256=fingerprint(), generated_sha256={str(p): digest(p) for p in generated},
                   verbatim_product_copy_loop_sha256=hashlib.sha256(copy_loop.encode()).hexdigest(),
                   render_extent=[1505, 847], readback_origin=[688, 0], readback_extent=[128, 847],
                   positive_published_frames=2, sdk_dispatches=0)
    (output/'prepared_receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return receipt


def verify_prepared(output):
    receipt = json.loads((output/'prepared_receipt.json').read_text())
    if receipt['source_sha256'] != fingerprint():
        raise ValueError('Source changed after preparation; create a fresh prepared output before compile/run')
    if any(digest(path) != value for path, value in receipt['generated_sha256'].items()):
        raise ValueError('Prepared source/stub identity mismatch')
    return receipt


def authenticate(output):
    spec = importlib.util.spec_from_file_location('full_context_reader', HERE/'fsrd_real_capture_replay.py')
    reader = importlib.util.module_from_spec(spec); spec.loader.exec_module(reader)
    captures = json.loads((output/'captures.json').read_text())
    positive = Path(captures['published_two_heads'])
    manifest = json.loads((positive/'capture.json').read_text())
    if manifest['committed_frames'] != 2 or manifest['render_extent'] != [1505, 847] or \
            manifest['roi']['origin'] != [688, 0] or manifest['roi']['extent'] != [128, 847]:
        raise ValueError('Production recorder changed full-native/strip geometry or published prefix')
    if manifest.get('full_context_reference_requested') is not True:
        raise ValueError('Diagnostic opt-in missing from actual manifest')
    row, arrays = reader.inspect_capture(positive, payload=True)
    heads = ('rr_full_context_reset_specular', 'rr_full_context_reset_diffuse')
    compared_words = 0; payload_files = 0
    for ordinal, frame in enumerate(manifest['frames']):
        if not all(frame[key] is True for key in ('cpu_snapshot_immutable', 'submission_gate_protected',
                                                   'gpu_submission_verified', 'gpu_completed')):
            raise ValueError('Production queue/fence/immutable snapshot proof missing')
        active = [d for d in frame['diagnostics'] if d['name'] in heads]
        if len(active) != 2 or active[0]['source_resource_address_process_local'] == active[1]['source_resource_address_process_local']:
            raise ValueError('Two distinct native reference heads missing')
        for index, role in enumerate(heads):
            actual = arrays['image_original_words'][role][ordinal]
            if actual.shape != (847, 128, 4):
                raise ValueError('Reference output shape changed')
            for y in range(847):
                expected = b''.join(struct.pack('<H', 0x2000+index*0x400+ordinal*64+(x+688)+y+c)
                                    for x in range(128) for c in range(4))
                if actual[y].tobytes() != expected:
                    raise ValueError('Native head words or nonzero strip addressing/row pitch changed')
                compared_words += 128*4
        for info in frame['images']+frame['diagnostics']+[frame['conversion_constants'], frame['floor_seed_constants']]:
            if info.get('file'):
                path = positive/info['file']
                if path.stat().st_size != info['bytes'] or digest(path) != info['sha256']:
                    raise ValueError('Published production payload hash/byte count mismatch')
                payload_files += 1
    for name, path in captures.items():
        if name == 'published_two_heads':
            continue
        result = json.loads((Path(path)/'capture.json').read_text())
        expected_count = 1 if name in ('context_generation_change', 'reference_evaluation_gap') else 0
        if result['committed_frames'] != expected_count or len(result['frames']) != expected_count:
            raise ValueError('Rejected production capture published a private/invalid suffix: '+name)
    native = json.loads((output/'native_warp_receipt.json').read_text())
    native.update(published_payload_files_authenticated=payload_files,
                  reference_uint16_words_compared=compared_words,
                  production_manifest_sha256=digest(positive/'capture.json'),
                  production_reader_mode=row['full_context_reference_mode'],
                  production_reader_is_clean_truth=row['full_context_reference_is_clean_truth'],
                  prepared_receipt_sha256=digest(output/'prepared_receipt.json'),
                  executable_sha256=digest(output/'fsrd_full_context_reference_warp.exe'))
    (output/'warp_receipt.json').write_text(json.dumps(native, indent=2)+'\n')
    return native


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-only', action='store_true')
    mode.add_argument('--compile-only', action='store_true')
    mode.add_argument('--warp-only', action='store_true')
    parser.add_argument('--gpu-authorized', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.drive.upper() != 'F:':
        raise ValueError('All diagnostic host/generated data must stay on F:')
    if any(Path(os.environ.get(key, '')).drive.upper() != 'F:' for key in ('TEMP', 'TMP')):
        raise ValueError('TEMP and TMP must both point to F:')
    if args.gpu_authorized != args.warp_only:
        raise ValueError('Only a separately admitted --warp-only invocation takes --gpu-authorized')
    output.mkdir(parents=True, exist_ok=True)
    exe = output/'fsrd_full_context_reference_warp.exe'
    if args.prepare_only:
        if (output/'prepared_receipt.json').exists():
            raise ValueError('Prepared evidence exists; use a fresh output to preserve its fingerprint')
        report = prepare(output)
    elif args.compile_only:
        prepared = verify_prepared(output)
        if exe.exists():
            raise ValueError('Compiled evidence exists; use its verified executable or prepare a fresh output')
        compile_cpp(output/'fsrd_full_context_reference_warp.cpp', exe, ('d3d12.lib', 'dxgi.lib', 'bcrypt.lib'),
                    (output/'stubs', ROOT/'external/nlohmann', ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
        report = dict(status='COMPILED_ONLY', gpu_work=0, sdk_dispatches=0, executable_sha256=digest(exe),
                      source_sha256=prepared['source_sha256'], prepared_receipt_sha256=digest(output/'prepared_receipt.json'))
        (output/'build_receipt.json').write_text(json.dumps(report, indent=2)+'\n')
    else:
        verify_prepared(output)
        build = json.loads((output/'build_receipt.json').read_text())
        if build['executable_sha256'] != digest(exe) or build['prepared_receipt_sha256'] != digest(output/'prepared_receipt.json'):
            raise ValueError('Compiled host identity differs from its immutable receipt')
        if (output/'captures.json').exists() or (output/'native_warp_receipt.json').exists():
            raise ValueError('GPU evidence exists; prepare and compile a fresh output for another run')
        subprocess.run([str(exe), str(output)], check=True)
        report = authenticate(output)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
