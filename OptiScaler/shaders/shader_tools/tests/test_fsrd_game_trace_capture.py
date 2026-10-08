"""Exercise the production GAME_TRACE recorder with real WARP copy/queue/Reset.

The host supplies controlled GPU words, never game pixels or an IQ reference.
Only DLL-path discovery/PCH are substituted so every capture stays in test
scratch. The actual recorder, hashes, queue fences and publication run unchanged.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]

CPP = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <array>
#include <chrono>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <atomic>
#include <cstdlib>
#include <new>
std::atomic<bool> g_testFailHeapAllocation {false};
void* operator new(std::size_t bytes)
{
    if (g_testFailHeapAllocation.load(std::memory_order_relaxed)) throw std::bad_alloc();
    if (void* value=std::malloc(bytes ? bytes : 1)) return value;
    throw std::bad_alloc();
}
void operator delete(void* value) noexcept { std::free(value); }
void operator delete(void* value,std::size_t) noexcept { std::free(value); }
#define FSRD_GAME_TRACE_TEST
#include "__RECORDER__"
#include "__RR_HEADER__"
#include <ffx_upscale.h>
using Microsoft::WRL::ComPtr;
using Trace = FSRDGameTraceSession;
constexpr auto srv = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
void need(bool okay, const char* message) { if (!okay) throw std::runtime_error(message); }
void hr(HRESULT code) { need(SUCCEEDED(code), "D3D12 call failed"); }
template<class Predicate> void Await(Predicate predicate,const char* message)
{
    const auto end=GetTickCount64()+15000;
    while (!predicate() && GetTickCount64()<end) Sleep(1);
    need(predicate(),message);
}
void Closed() { Await([] { return !Trace::IsActive(); },"capture did not finish CPU draining"); }
void Saved(unsigned frames) { Await([&] { return Trace::GetStatus().captured==frames; },"immutable frame not saved"); }
void Published(unsigned frames) { Await([&] { return Trace::GetStatus().manifestPublished==frames; },"immutable manifest prefix not published"); }
struct Host
{
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> list;
    ComPtr<ID3D12Fence> fence;
    ComPtr<ID3D12InfoQueue> info;
    std::array<ComPtr<ID3D12Resource>,9> textures;
    std::vector<ComPtr<ID3D12Resource>> uploads;
    std::array<Trace::Source,Trace::SourceCount> sources;
    std::array<Trace::DiagnosticSource,13> diagnostics;
    std::array<uint8_t,416> constants {};
    std::array<uint8_t,176> seed {};
    uint64_t serial=0;
    uint32_t renderWidth=136,renderHeight=136;
    ComPtr<ID3D12Resource> srOutput;
    Host(uint32_t render=136,uint32_t srWidth=0,uint32_t srHeight=0,uint32_t height=0)
        : renderWidth(render),renderHeight(height ? height : render)
    {
        ComPtr<ID3D12Debug> debug; hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)));
        debug->EnableDebugLayer();
        ComPtr<IDXGIFactory4> factory; hr(CreateDXGIFactory2(0,IID_PPV_ARGS(&factory)));
        ComPtr<IDXGIAdapter> warp; hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)));
        hr(D3D12CreateDevice(warp.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)));
        hr(device.As(&info));
        D3D12_COMMAND_QUEUE_DESC q {}; hr(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)));
        hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)));
        hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&list)));
        hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));
        const std::array<DXGI_FORMAT,9> formats {DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,
            DXGI_FORMAT_R8G8B8A8_UNORM,DXGI_FORMAT_R8G8B8A8_UNORM,DXGI_FORMAT_R16G16B16A16_FLOAT,
            DXGI_FORMAT_R10G10B10A2_UNORM,DXGI_FORMAT_R32_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,
            DXGI_FORMAT_R8_UNORM};
        D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        for (size_t i=0;i<textures.size();++i)
        {
            D3D12_RESOURCE_DESC d {}; d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
            d.Width=renderWidth; d.Height=renderHeight; d.DepthOrArraySize=d.MipLevels=1; d.SampleDesc.Count=1; d.Format=formats[i];
            hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,srv,nullptr,IID_PPV_ARGS(&textures[i])));
        }
        if (srWidth)
        {
            D3D12_RESOURCE_DESC d {}; d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D; d.Width=srWidth; d.Height=srHeight;
            d.DepthOrArraySize=d.MipLevels=1; d.SampleDesc.Count=1; d.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;
            d.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
            hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&srOutput)));
        }
        for (size_t i=0;i<sources.size();++i) sources[i]={textures[i].Get(),srv};
        const std::array<const char*,13> names {"raw_color","raw_normals","raw_specular_albedo","raw_diffuse_albedo",
            "floor","floor_reference","raw_bias_mask","raw_specular_hit_distance","raw_motion","raw_depth",
            "raw_roughness","raw_title_linear_depth","raw_inspector"};
        const std::array<int,13> indices {0,1,2,3,0,1,8,6,7,6,-1,-1,-1};
        for (size_t i=0;i<diagnostics.size();++i)
        {
            auto& d=diagnostics[i]; d.name=names[i]; d.active=indices[i]>=0; d.required=d.active;
            d.inactiveReason="Fixture binding absent.";
            if (d.active) d.image={textures[indices[i]].Get(),srv};
        }
        auto& rawMotion=diagnostics[8]; rawMotion.motionAddressed=true;
        rawMotion.motionWidth=float(renderWidth); rawMotion.motionHeight=float(renderHeight);
        rawMotion.metadataJson=Json{{"mapping",{{"kind","converter_motion_source_bounding_rectangle"},
            {"display_resolution",false},{"render_extent",{renderWidth,renderHeight}},
            {"motion_input_extent",{renderWidth,renderHeight}}}}}.dump();
        auto word=[&](size_t offset,float value) { memcpy(constants.data()+offset,&value,4); };
        for (size_t i=0;i<4;++i) { word(i*20,1); word(64+i*20,1); word(128+i*20,1); }
        word(192,float(renderWidth)); word(196,float(renderHeight)); word(200,1.f/renderWidth); word(204,1.f/renderHeight);
        memcpy(seed.data(),constants.data()+64,64);
        memcpy(seed.data()+64,constants.data()+192,16);
    }
    void Fill(unsigned frame)
    {
        uploads.clear();
        for (size_t i=0;i<textures.size();++i)
        {
            const auto d=textures[i]->GetDesc();
            D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp {}; UINT64 bytes=0;
            device->GetCopyableFootprints(&d,0,1,0,&fp,nullptr,nullptr,&bytes);
            D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_UPLOAD;
            D3D12_RESOURCE_DESC bd {}; bd.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
            bd.Width=bytes; bd.Height=1; bd.DepthOrArraySize=bd.MipLevels=1; bd.SampleDesc.Count=1;
            bd.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
            ComPtr<ID3D12Resource> upload;
            hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&bd,D3D12_RESOURCE_STATE_GENERIC_READ,
                nullptr,IID_PPV_ARGS(&upload)));
            void* data=nullptr; const D3D12_RANGE empty {0,0}; hr(upload->Map(0,&empty,&data));
            memset(data,0,size_t(bytes));
            if (i==0 || i==7)
            {
                // HALF pattern varies by frame AND texel, proving exact nonzero
                // ROI addressing, row-pitch removal and genuine frame uniqueness.
                for (unsigned y=0;y<d.Height;++y)
                    for (unsigned x=0;x<d.Width;++x)
                        for (unsigned c=0;c<4;++c)
                        {
                            const uint16_t value=uint16_t(0x3000+frame+x+y+c);
                            memcpy(static_cast<uint8_t*>(data)+fp.Offset+y*fp.Footprint.RowPitch+(x*4+c)*2,&value,2);
                        }
            }
            upload->Unmap(0,nullptr);
            D3D12_RESOURCE_BARRIER b {}; b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            b.Transition={textures[i].Get(),0,srv,D3D12_RESOURCE_STATE_COPY_DEST}; list->ResourceBarrier(1,&b);
            D3D12_TEXTURE_COPY_LOCATION src {},dst {};
            src.pResource=upload.Get(); src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint=fp;
            dst.pResource=textures[i].Get(); dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
            std::swap(b.Transition.StateBefore,b.Transition.StateAfter); list->ResourceBarrier(1,&b);
            uploads.push_back(std::move(upload));
        }
    }
    Trace::FrameInfo Frame(unsigned index,bool reset=false,const char* context="fixture-generation-1",int setting=1)
    {
        Trace::FrameInfo frame {}; frame.contextId=context; frame.evaluationId=index+1;
        frame.frameIndex=1000+index; frame.reset=reset; frame.dispatchFlags=reset ? 1 : 0;
        // Feed the real RR descriptor through the production feature's exact
        // serializer. Handwritten JSON hid a 2D/3D motion-scale mismatch.
        ffxDispatchDescDenoiser denoiserDesc {};
        const std::array<float,16> view {1,0,0,0,0,1,0,0,0,0,1,0,float(index)*.01f,0,0,1};
        const std::array<float,16> projection {1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
        static_assert(sizeof(denoiserDesc.view) == sizeof(view));
        memcpy(&denoiserDesc.view,view.data(),sizeof(view));
        memcpy(&denoiserDesc.projection,projection.data(),sizeof(projection));
        denoiserDesc.jitterOffsets={float(index%4)*.125f,-.125f};
        denoiserDesc.cameraPositionDelta={float(index)*.01f,0,0};
        denoiserDesc.motionVectorScale={2.f,3.f,4.f};
        denoiserDesc.linearDepthBounds={.1f,1000.f};
        denoiserDesc.renderSize={renderWidth,renderHeight};
        const float capturePreExposure=1.f;
        const bool capturePreExposureProvided=true;
        const struct { bool MotionHistoryValid; } _convDesc {!reset};
        using CaptureJson = nlohmann::json;
#include "fsrd_game_trace_controls.inc"
        frame.controlsJson=controls.dump();
        frame.settingsJson=Json{{"sdk_tuning",{1,1,1000,3,1,.1f}},{"fixture_setting",setting}}.dump();
        return frame;
    }
    bool Sources(Trace& capture,uint32_t width=0,bool hooks=true)
    { return capture.RecordSources(device.Get(),list.Get(),sources,width ? width : renderWidth,renderHeight,constants,diagnostics,seed,{},hooks); }
    bool Admit(Trace& capture)
    {
        const auto end=GetTickCount64()+15000;
        while (!Sources(capture))
        {
            const auto status=Trace::GetStatus();
            if (!status.active || status.phase=="draining" || status.phase=="error" || GetTickCount64()>=end) return false;
            Sleep(1);
        }
        return true;
    }
    void Sr(Trace& capture,unsigned index,uint32_t width=768,uint32_t height=770,bool wrongEvaluation=false)
    {
        const auto d=srOutput->GetDesc(); D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp {}; UINT64 bytes=0;
        device->GetCopyableFootprints(&d,0,1,0,&fp,nullptr,nullptr,&bytes);
        D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_UPLOAD;
        D3D12_RESOURCE_DESC bd {}; bd.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER; bd.Width=bytes; bd.Height=1;
        bd.DepthOrArraySize=bd.MipLevels=1; bd.SampleDesc.Count=1; bd.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> upload; hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&bd,
            D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&upload)));
        void* data=nullptr; D3D12_RANGE empty {0,0}; hr(upload->Map(0,&empty,&data)); memset(data,0,size_t(bytes));
        for (unsigned y=0;y<d.Height;++y) for (unsigned x=0;x<d.Width;++x) for (unsigned channel=0;channel<4;++channel)
        { const uint16_t value=uint16_t(0x4200+index+x+y+channel); memcpy(static_cast<uint8_t*>(data)+fp.Offset+y*fp.Footprint.RowPitch+(x*4+channel)*2,&value,2); }
        upload->Unmap(0,nullptr);
        D3D12_RESOURCE_BARRIER barrier {}; barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition={srOutput.Get(),0,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_DEST}; list->ResourceBarrier(1,&barrier);
        D3D12_TEXTURE_COPY_LOCATION src {},dst {}; src.pResource=upload.Get(); src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint=fp;
        dst.pResource=srOutput.Get(); dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX; list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
        std::swap(barrier.Transition.StateBefore,barrier.Transition.StateAfter); list->ResourceBarrier(1,&barrier); uploads.push_back(std::move(upload));
        Trace::SrInfo info {}; info.width=width; info.height=height; info.evaluationId=index+1+(wrongEvaluation ? 1 : 0);
        info.contextId="SR-process-context-123-owner-456"; info.reset=index==1;
        ffxDispatchDescUpscale upscalerDesc {};
        upscalerDesc.jitterOffset={.25f,-.125f}; upscalerDesc.motionVectorScale={2.f,3.f};
        upscalerDesc.renderSize={renderWidth,renderHeight}; upscalerDesc.upscaleSize={width,height};
        upscalerDesc.frameTimeDelta=16.f; upscalerDesc.preExposure=1.f; upscalerDesc.reset=info.reset;
        upscalerDesc.cameraNear=.1f; upscalerDesc.cameraFar=1000.f; upscalerDesc.cameraFovAngleVertical=1.f;
        upscalerDesc.viewSpaceToMetersFactor=1.f;
        const struct { uint32_t flags=0; } _upscaleCtxDesc;
        using CaptureJson = nlohmann::json;
#include "fsrd_game_trace_sr_controls.inc"
        info.controlsJson=controls.dump();
        capture.CompleteSrFrame(list.Get(),{srOutput.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS},info);
    }
    void Record(Trace& capture,unsigned index,bool reset=false,const char* context="fixture-generation-1",int setting=1)
    {
        Fill(index); need(Admit(capture),"source recording unexpectedly rejected");
        const std::array<Trace::DiagnosticSource,2> lobes {{
            {"rr_specular",{textures[0].Get(),srv}},{"rr_diffuse",{textures[1].Get(),srv}}
        }};
        capture.RecordNative(list.Get(),{textures[0].Get(),srv},Frame(index,reset,context,setting),lobes);
        capture.CompleteFrame(list.Get(),{textures[0].Get(),srv});
    }
    void Execute(bool repeat=false,bool close=true)
    {
        if (close) hr(list->Close()); ID3D12CommandList* lists[]={list.Get()};
        auto submit=[&] {
            auto tickets=RRTraceFence::BeforeSubmission(queue.Get(),1,lists);
            queue->ExecuteCommandLists(1,lists); RRTraceFence::AfterSubmission(queue.Get(),tickets);
        };
        auto waitGpu=[&] {
            hr(queue->Signal(fence.Get(),++serial));
            HANDLE event=CreateEventW(nullptr,FALSE,FALSE,nullptr); need(event!=nullptr,"test fence event");
            hr(fence->SetEventOnCompletion(serial,event));
            const auto waited=WaitForSingleObject(event,10000); CloseHandle(event);
            need(waited==WAIT_OBJECT_0,"test GPU completion timed out");
        };
        submit(); waitGpu();
        // Re-execution of an un-reset, closed list is legal after its prior
        // execution completed. It still makes a capture lineage ambiguous.
        if (repeat) { submit(); waitGpu(); }
    }
    void Reset()
    { hr(allocator->Reset()); hr(list->Reset(allocator.Get(),nullptr)); RRTraceFence::ResetSucceeded(list.Get()); }
    void Discard() { hr(list->Close()); Reset(); }
    void NoGpuErrors()
    {
        for (uint64_t i=0;i<info->GetNumStoredMessages();++i)
        {
            SIZE_T bytes=0; hr(info->GetMessage(i,nullptr,&bytes)); std::vector<uint8_t> storage(bytes);
            auto* message=reinterpret_cast<D3D12_MESSAGE*>(storage.data()); hr(info->GetMessage(i,message,&bytes));
            if (message->Severity==D3D12_MESSAGE_SEVERITY_ERROR || message->Severity==D3D12_MESSAGE_SEVERITY_CORRUPTION || message->Severity==D3D12_MESSAGE_SEVERITY_WARNING)
                throw std::runtime_error(message->pDescription);
        }
    }
};
void CpuChecks(const std::filesystem::path& output)
{
    using RegionMode = Trace::Request::RegionMode;
    Session strip; strip.regionMode=RegionMode::FullHeightStrip; strip.x=688; strip.y=999;
    ResolveRegion(strip,1505,847);
    need(strip.x==688 && strip.y==0 && strip.width==128 && strip.height==847,"odd full-height strip geometry");
    bool resizeRejected=false;
    try { ResolveRegion(strip,1505,846); } catch (const std::exception&) { resizeRejected=true; }
    need(resizeRejected && strip.height==847,"resolved rectangle resized instead of rejecting");
    Session full; full.regionMode=RegionMode::FullRender; full.x=full.y=UINT32_MAX;
    ResolveRegion(full,1505,847);
    need(full.x==0 && full.y==0 && full.width==1505 && full.height==847,"odd full render geometry");
    Session invalid; invalid.regionMode=RegionMode::FullHeightStrip; invalid.x=1400;
    bool boundsRejected=false;
    try { ResolveRegion(invalid,1505,847); } catch (const std::exception&) { boundsRejected=true; }
    need(boundsRejected && invalid.x==1400,"out-of-bounds strip silently clamped");
    full.status.target=512; full.defaultPayloadQuota=false; full.maximumPayload=MaximumExtendedPayloadBytes;
    full.diskAvailable=UINT64_MAX;
    const uint64_t frameBytes=TightBytes(1505,847,137)+592;
    PreflightPayload(full,frameBytes,true);
    need(full.status.estimatedPayloadBytes==frameBytes*512 && full.maximumPayload==frameBytes*512*21/20+(1ull<<20),
         "full render estimate omitted actual target or rectangle");
    Session insufficient=full; insufficient.payloadEstimated=false; insufficient.diskAvailable=frameBytes*512;
    bool spaceRejected=false;
    try { PreflightPayload(insufficient,frameBytes); }
    catch (const std::exception& error)
    { spaceRejected=std::string(error.what()).find("512-frame destination preflight including 5% allowance requires")!=std::string::npos; }
    need(spaceRejected,"target preflight silently omitted allowance or required byte diagnostic");
    Session publication; publication.status.manifestPublished=publication.status.captured=1;
    MarkDurableFrame(publication,1000);
    need(publication.publicationDeadline==1250 && !ManifestDue(publication,1249),"idle publication deadline missing");
    MarkDurableFrame(publication,1100); MarkDurableFrame(publication,1200);
    need(publication.publicationDeadline==1250 && ManifestDue(publication,1250),"new rows postponed the original publication deadline");
    for (unsigned index=0;index<5;++index) MarkDurableFrame(publication,1201+index);
    need(ManifestDue(publication,1205),"batch8 did not force publication before deadline");
    Session forced; Stop(forced,"Stopped by user");
    need(ManifestDue(forced,0),"stop did not force metadata publication with an empty prefix");
    const auto firstRevision=forced.forcePublicationRevision;
    Stop(forced,"Stopped by user"); Stop(forced,"Repeated identical observation");
    need(forced.forcePublicationRevision==firstRevision,"repeated stop forced growing manifest rewrites");
    {
        Trace capture; Trace::Request request; request.outputRoot=(output/"cpu-allocation-only").string();
        need(Trace::RequestStart(request),"persistent abort request");
        g_testFailHeapAllocation.store(true);
        capture.Abort("A long allocation-free abort reason must enter noexcept cleanup without constructing a string.");
        g_testFailHeapAllocation.store(false);
        Closed();
        need(!Trace::IsActive() && !Trace::GetStatus().active && Trace::GetStatus().cpuQueuedBytes==0,
             "persistent allocation failure escaped abort cleanup");
    }
    for (uint32_t target : {128u,256u,512u})
    {
        Trace::Request request; request.frameCount=target;
        request.outputRoot=(output/"cpu-counter-only").string();
        need(Trace::RequestStart(request),"allowed target request rejected");
        need(Trace::GetStatus().target==target,"status target stayed128");
        {
            std::scoped_lock lock(Global().mutex);
            need(Global().current->lineageLimit==target-1 && Global().current->manifest["target_frames"]==target,
                 "long-target lineage or manifest stayed128");
        }
        Trace::RequestStop();
        // Exercise actual source-admission and disk-finish boundaries using
        // synthetic counters only. These folders contain no GPU payload/proof,
        // are excluded from captures.json, and are never reader/IQ fixtures.
        for (bool atTarget : {false,true})
        {
            Trace capture;
            need(Trace::RequestStart(request),"counter boundary request rejected");
            {
                std::scoped_lock lock(Global().mutex);
                auto& s=*Global().current;
                s.status.recorded=atTarget ? target : target-1;
                s.status.captured=s.status.recorded;
                s.manifest["synthetic_counter_only_fixture"]=true;
                for (uint32_t ordinal=0;ordinal<s.status.captured;++ordinal)
                    s.manifest["frames"].push_back({{"ordinal",ordinal},{"synthetic_counter_only",true}});
            }
            std::array<Trace::Source,Trace::SourceCount> noSources {};
            need(!capture.RecordSources(nullptr,nullptr,noSources,1505,847,{}),"counter-only request recorded GPU work");
            Closed(); const auto status=Trace::GetStatus();
            if (atTarget)
                need(status.phase=="complete" && status.manifestPublished==target &&
                     status.message.find("/"+std::to_string(target)+".")!=std::string::npos,
                     "actual target did not terminate the disk worker");
            else
                need(status.phase=="incomplete" && status.message.find("Invalid fixed ROI/device/constants")!=std::string::npos,
                     "pre-target source admission stopped at an earlier hardcoded limit");
        }
    }
    Trace::Request invalidTarget; invalidTarget.frameCount=129;
    need(!Trace::RequestStart(invalidTarget) && !Trace::IsActive(),"unsupported target accepted");
}
int main(int argc,char** argv) try
{
    need(argc==2 || (argc==3 && std::string(argv[2])=="--cpu-only"),"test output directory is required");
    g_dllPath=std::filesystem::path(argv[1])/"test_OptiScaler.dll";
    // A recoverable allocation failure after the request became active must
    // clear both UI and fast-path state, so the next request can be retried.
    g_testFailStartManifestAllocation.store(true);
    need(!Trace::RequestStart(3,5),"manifest allocation failure accepted");
    need(!Trace::IsActive() && !Trace::GetStatus().active && Trace::GetStatus().phase=="error",
         "failed request retained active state");
    g_testFailHeapAllocation.store(true);
    const bool allocationFailureAdmitted=Trace::RequestStart(3,5);
    g_testFailHeapAllocation.store(false);
    need(!allocationFailureAdmitted && !Trace::IsActive() && !Trace::GetStatus().active,
         "persistent session allocation failure admitted or retained an active request");
    need(Trace::RequestStart(3,5),"allocation failure prevented request retry");
    Trace::RequestStop();
    CpuChecks(std::filesystem::path(argv[1]));
    if (argc==3) { std::cout<<"GAME_TRACE CPU geometry, target, budget and startup checks PASS\n"; return 0; }
    Host host; Json results=Json::object();
    auto snapshot=[&](const char* name) { const auto status=Trace::GetStatus(); results[name]=status.folder; };
    {
        Trace capture; need(Trace::RequestStart(3,5),"full request"); snapshot("complete");
        for (unsigned frame=0;frame<128;++frame)
        {
            host.Record(capture,frame,frame==63);
            need(Trace::GetStatus().recorded==frame+1,"recorded ordinal count");
            host.Execute(); capture.Poll();
            Published(frame+1);
            need(Trace::GetStatus().awaitingDetach>=1,"immutable publication forged Reset detach");
            host.Reset(); capture.Poll();
            need(Trace::GetStatus().captured==frame+1,"observed Reset lost immutable frame");
        }
        Closed(); need(Trace::GetStatus().phase=="complete","128-frame completion");
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"batched manifest request"); snapshot("manifest_batch_idle_stop");
        host.Record(capture,0); host.Execute(); Published(1); host.Reset(); capture.Poll();
        const auto initialWrites=Trace::GetStatus().manifestWrites;
        const auto started=GetTickCount64();
        for (unsigned index=1;index<=8;++index)
        {
            host.Record(capture,index); host.Execute(); Saved(index+1); host.Reset(); capture.Poll();
        }
        Published(9);
        need(Trace::GetStatus().manifestWrites-initialWrites<8,"batch8 still wrote every completed frame");
        need(GetTickCount64()-started<15000,"batch prefix publication did not finish");
        host.Record(capture,9); host.Execute(); Saved(10); host.Reset(); capture.Poll();
        Published(10); // No more GPU work: the original idle deadline must flush.
        host.Record(capture,10); host.Execute(); Saved(11); host.Reset(); capture.Poll();
        Trace::RequestStop(); Closed();
        need(Trace::GetStatus().manifestPublished==11 && Trace::GetStatus().captured==11,
             "stop/final did not publish the durable contiguous suffix");
        need(Trace::GetStatus().manifestWrites<=7,"controlled batching/idle/stop case wrote excessive manifests");
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"manifest replace failure request"); snapshot("manifest_replace_failure");
        host.Record(capture,0); host.Execute(); Published(1); host.Reset(); capture.Poll();
        g_testFailManifestPublication.store(true);
        host.Record(capture,1); host.Execute(); Saved(2); host.Reset(); capture.Poll();
        Trace::RequestStop(); Closed();
        need(Trace::GetStatus().phase=="error" && Trace::GetStatus().captured==2 && Trace::GetStatus().manifestPublished==1,
             "failed atomic manifest replace forged publication or lost saved prefix");
        g_testFailManifestPublication.store(false);
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"lineage cutoff during publication request"); snapshot("lineage_cutoff_during_publish");
        host.Record(capture,0); host.Execute(); Published(1); host.Reset(); capture.Poll();
        struct CommitHold
        {
            CommitHold() { g_testHoldFrameCommit.store(true); }
            void Release() { g_testHoldFrameCommit.store(false); g_testHoldFrameCommit.notify_all(); }
            ~CommitHold() { Release(); }
        } hold;
        host.Record(capture,1); host.Execute(); host.Reset();
        Await([] { return g_testFrameCommitHeld.load(std::memory_order_acquire); },"writer did not pause between rename and prefix commit");
        { std::scoped_lock lock(Global().mutex); Global().current->lineageLimit=0; }
        capture.Abort("Injected lineage cutoff during folder publication.");
        need(Trace::GetStatus().captured==1 && Trace::GetStatus().manifestPublished==1,"held rename exposed a private suffix");
        hold.Release(); Closed();
        need(Trace::GetStatus().captured==1 && Trace::GetStatus().manifestPublished==1 && Trace::GetStatus().staged==1,
             "cutoff race committed an excluded ordinal or lost forensic metadata");
        need(std::filesystem::is_directory(std::filesystem::path(Trace::GetStatus().folder)/"frames/1.pending") &&
             !std::filesystem::exists(std::filesystem::path(Trace::GetStatus().folder)/"frames/1"),"cutoff suffix was not quarantined");
        capture.Poll();
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"frame rename failure request"); snapshot("frame_rename_failure");
        host.Record(capture,0);
        std::filesystem::create_directory(std::filesystem::path(Trace::GetStatus().folder)/"frames/0");
        host.Execute(); host.Reset(); Closed();
        need(Trace::GetStatus().captured==0 && Trace::GetStatus().manifestPublished==0 && Trace::GetStatus().staged==1,
             "rename failure published or lost its private row");
        capture.Poll();
    }
    {
        Trace capture; Trace::Request request; request.frameCount=512;
        request.regionMode=Trace::Request::RegionMode::FullHeightStrip;
        need(Trace::RequestStart(request),"preflight disk rejection request"); snapshot("preflight_disk_budget");
        need(!host.Sources(capture),"uninitialized disk request recorded early");
        Await([] { std::scoped_lock lock(Global().mutex); return Global().current->initialized; },"disk preflight fixture did not initialize");
        const auto before=Trace::GetStatus().retainedReadbackBytes;
        { std::scoped_lock lock(Global().mutex); Global().current->diskAvailable=1; }
        need(!host.Sources(capture),"insufficient-space request copied/truncated"); Closed();
        need(Trace::GetStatus().recorded==0 && Trace::GetStatus().retainedReadbackBytes==before &&
             Trace::GetStatus().message.find("512-frame destination preflight including 5% allowance requires")!=std::string::npos,
             "disk preflight failed after GPU allocation or omitted explicit required bytes");
    }
    {
        const auto previousReadbackBytes=Trace::GetStatus().retainedReadbackBytes;
        Trace capture; need(Trace::RequestStart(3,5),"diagnostics allocation failure request");
        snapshot("failure_diagnostics_allocation");
        struct FreezeHold
        {
            FreezeHold() { g_testHoldCpuFreeze.store(true); }
            void Release() { g_testHoldCpuFreeze.store(false); g_testHoldCpuFreeze.notify_all(); }
            ~FreezeHold() { Release(); }
        } hold;
        host.Record(capture,0); host.Execute();
        Await([] { return Trace::GetStatus().cpuQueuedBytes>0 && Trace::GetStatus().pending==1; },
              "snapshot did not reserve CPU storage before the injected failure");
        g_testFailPendingDiagnosticsAllocation.store(true);
        capture.Abort("Injected pending diagnostics allocation failure.");
        need(Trace::IsActive() && Trace::GetStatus().pending==0 && Trace::GetStatus().cpuQueuedBytes>0,
             "close ignored the in-progress CPU snapshot reservation");
        uint64_t forcedRevision=0;
        { std::scoped_lock lock(Global().mutex); forcedRevision=Global().current->forcePublicationRevision; }
        for (unsigned repeat=0;repeat<25;++repeat) { Trace::RequestStop(); capture.Poll(); }
        {
            std::scoped_lock lock(Global().mutex);
            need(Global().current->forcePublicationRevision==forcedRevision,"repeated stop while reserved starved CPU draining");
        }
        hold.Release(); Closed();
        need(Trace::GetStatus().captured==0 && Trace::GetStatus().cpuQueuedBytes==0,
             "failed in-progress snapshot published or retained its CPU reservation");
        host.Reset(); capture.Poll();
        need(Trace::GetStatus().retainedReadbackBytes==previousReadbackBytes,
             "diagnostics allocation failure stranded Reset-detached readbacks");
    }
    {
        const auto previousReadbackBytes=Trace::GetStatus().retainedReadbackBytes;
        Trace capture; need(Trace::RequestStart(3,5),"persistent allocation abort request"); snapshot("persistent_allocation_abort");
        struct FreezeHold
        {
            FreezeHold() { g_testHoldCpuFreeze.store(true); }
            void Release() { g_testHoldCpuFreeze.store(false); g_testHoldCpuFreeze.notify_all(); }
            ~FreezeHold() { Release(); }
        } hold;
        host.Record(capture,0); host.Execute();
        Await([] { return Trace::GetStatus().cpuQueuedBytes>0 && Trace::GetStatus().pending==1; },"persistent abort did not hold a CPU reservation");
        g_testFailHeapAllocation.store(true);
        capture.Abort("Persistent allocation failure during an in-progress reserved immutable snapshot.");
        g_testFailHeapAllocation.store(false);
        need(Trace::IsActive() && Trace::GetStatus().pending==0 && Trace::GetStatus().cpuQueuedBytes>0,
             "persistent allocation abort stranded pending frames or ignored the reservation");
        hold.Release(); Closed();
        need(Trace::GetStatus().captured==0 && Trace::GetStatus().cpuQueuedBytes==0,"persistent abort published or leaked its reservation");
        host.Reset(); capture.Poll();
        need(Trace::GetStatus().retainedReadbackBytes==previousReadbackBytes,"persistent abort released early or stranded verified Reset readbacks");
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"invalid scale request"); snapshot("invalid_motion_scale");
        host.Fill(0); need(host.Admit(capture),"invalid scale sources");
        auto frame=host.Frame(0);
        auto controls=Json::parse(frame.controlsJson);
        controls["motion_vector_scale"]=Json::array({1.f,1.f});
        frame.controlsJson=controls.dump();
        capture.RecordNative(host.list.Get(),{host.textures[0].Get(),srv},frame);
        Closed(); need(Trace::GetStatus().captured==0,"2D RR scale accepted");
        need(Trace::GetStatus().message.find("Invalid actual control: motion_vector_scale (expected 3 components)")!=std::string::npos,
             "invalid scale diagnostic lost expected dimensions");
        host.Execute(); host.Reset(); capture.Poll();
    }
    {
        Trace capture; need(Trace::RequestStart(3,5,2),"armed request"); snapshot("armed_owner_end");
        const auto started=GetTickCount64(); need(!host.Sources(capture),"armed delay recorded early");
        need(GetTickCount64()-started<1000 && Trace::GetStatus().pending==0,"arming blocked or allocated readbacks");
        need(Trace::GetStatus().delayRemainingMs>0,"armed countdown disappeared after ownership binding");
    }
    need(!Trace::IsActive() && Trace::GetStatus().phase=="incomplete","armed owner teardown did not close request");
    {
        Trace capture; need(Trace::RequestStart(3,5,2),"unclaimed arm request"); snapshot("unclaimed_owner_end");
    }
    need(!Trace::IsActive(),"unclaimed arm survived immediate owner teardown");
    { Trace nextOwner; need(!host.Sources(nextOwner),"next owner adopted a cancelled unclaimed arm"); }
    {
        Trace capture; need(Trace::RequestStart(3,5),"cancel request"); snapshot("cancelled");
        for (unsigned i=0;i<2;++i) { host.Record(capture,i); host.Execute(); Published(i+1); host.Reset(); capture.Poll(); }
        Trace::RequestStop(); capture.Poll(); Closed();
        need(!Trace::IsActive() && Trace::GetStatus().phase=="cancelled" && Trace::GetStatus().captured==2,"cancel lost prefix");
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"failed-render request"); snapshot("failed_render");
        host.Record(capture,0); capture.Abort("Normal evaluation failed after composition.");
        host.Execute(); host.Reset(); capture.Poll();
        Closed(); need(Trace::GetStatus().captured==0,"failed rendering exported a false successful frame");
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"invalid reset request"); snapshot("discarded");
        host.Record(capture,0); host.Discard(); capture.Poll();
        Closed(); need(Trace::GetStatus().captured==0,"unsubmitted Reset exported frame");
    }
    for (int change=0;change<3;++change)
    {
        Trace capture; need(Trace::RequestStart(3,5),"lineage-change request");
        snapshot(change==0 ? "context_changed" : change==1 ? "settings_changed" : "resize");
        host.Record(capture,0); host.Execute(); Published(1); host.Reset(); capture.Poll();
        if (change==2) { need(!host.Sources(capture,138),"resize accepted"); }
        else host.Record(capture,1,false,change==0 ? "fixture-generation-2" : "fixture-generation-1",change==1 ? 2 : 1);
        Closed(); need(Trace::GetStatus().captured==1,"lineage change lost prefix or stayed active");
        host.Discard();
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"missing hooks request"); snapshot("missing_hooks");
        need(!host.Sources(capture,136,false),"missing hooks recorded unproved GPU work"); Closed();
        need(Trace::GetStatus().message.find("hooks unavailable")!=std::string::npos,"missing hooks rejection unclear");
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"capacity request"); snapshot("capacity");
        std::vector<ComPtr<ID3D12CommandAllocator>> heldAllocators;
        std::vector<ComPtr<ID3D12GraphicsCommandList>> heldLists;
        for (unsigned i=0;i<3;++i)
        {
            host.Record(capture,i); hr(host.list->Close());
            heldAllocators.push_back(host.allocator); heldLists.push_back(host.list);
            host.allocator.Reset(); host.list.Reset();
            hr(host.device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&host.allocator)));
            hr(host.device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,host.allocator.Get(),nullptr,IID_PPV_ARGS(&host.list)));
        }
        const auto started=GetTickCount64(); need(!host.Sources(capture),"unsubmitted capacity overflow accepted");
        need(GetTickCount64()-started<100,"capacity admission waited"); Closed();
        need(Trace::GetStatus().captured==0,"capacity fabricated completion");
        for (size_t i=0;i<heldLists.size();++i)
        {
            hr(heldAllocators[i]->Reset()); hr(heldLists[i]->Reset(heldAllocators[i].Get(),nullptr));
            RRTraceFence::ResetSucceeded(heldLists[i].Get());
        }
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"retired-list request"); snapshot("retired_list");
        host.Record(capture,0); host.Execute(); Published(1);
        auto retiredList=host.list; auto retiredAllocator=host.allocator;
        host.list.Reset(); host.allocator.Reset();
        hr(host.device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&host.allocator)));
        hr(host.device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,host.allocator.Get(),nullptr,IID_PPV_ARGS(&host.list)));
        host.Record(capture,1); host.Execute(); Published(2); host.Reset(); capture.Poll();
        need(Trace::GetStatus().awaitingDetach==1,"retired list lost release ledger");
        Trace::RequestStop(); Closed();
        need(Trace::GetStatus().captured==2 && Trace::GetStatus().retainedReadbackBytes>0,"immutable retired frame lost or released early");
        hr(retiredAllocator->Reset()); hr(retiredList->Reset(retiredAllocator.Get(),nullptr)); RRTraceFence::ResetSucceeded(retiredList.Get());
        capture.Poll();
    }
    for (int mode=1;mode<=2;++mode)
    {
        Host extended(520,792,788); Trace capture; Trace::Request request;
        request.x=3; request.y=5; request.size=512; request.srMode=mode==1 ? Trace::SrMode::MappedRoi : Trace::SrMode::FullOutput;
        request.outputRoot=(std::filesystem::path(argv[1])/"user path with spaces").string();
        need(Trace::RequestStart(request),"extended request"); snapshot(mode==1 ? "mapped_sr_512" : "full_sr_512");
        for (unsigned index=0;index<2;++index)
        {
            extended.Record(capture,index);
            need(Trace::GetStatus().recorded==index,"pre-SR snapshot sealed requested-SR frame early");
            extended.Sr(capture,index); need(Trace::GetStatus().recorded==index+1,"same-evaluation SR did not seal");
            extended.Execute(); Published(index+1); extended.Reset(); capture.Poll();
            need(Trace::GetStatus().cpuQueuedBytes<=MaximumCpuBytes && Trace::GetStatus().retainedReadbackBytes<=MaximumReadbackBytes,"capture memory budget exceeded");
        }
        Trace::RequestStop(); Closed(); need(Trace::GetStatus().captured==2,"extended capture prefix lost");
        extended.NoGpuErrors();
    }
    for (unsigned mode=0;mode<4;++mode)
    {
        Host rectangle(1505,mode==0 ? 2284 : 0,mode==0 ? 1298 : 0,847);
        Trace capture; Trace::Request request;
        request.x=688; request.y=UINT32_MAX;
        request.regionMode=mode==2 ? Trace::Request::RegionMode::FullRender : Trace::Request::RegionMode::FullHeightStrip;
        request.size=mode==1 ? 512 : 128;
        request.frameCount=mode==0 ? 512 : (mode==1 ? 256 : 128);
        request.srMode=mode==0 ? Trace::SrMode::MappedRoi : Trace::SrMode::Off;
        if (mode==3)
        {
            auto& motion=rectangle.diagnostics[8]; motion.displayResolutionMotion=true;
            motion.jitterX=.25f; motion.jitterY=-.125f;
            auto metadata=Json::parse(motion.metadataJson); metadata["mapping"]["display_resolution"]=true;
            metadata["mapping"]["current_jitter"]={motion.jitterX,motion.jitterY}; motion.metadataJson=metadata.dump();
        }
        const char* name=mode==0 ? "strip_128_mapped_sr_512_frames" :
            (mode==1 ? "strip_512_256_frames" : (mode==2 ? "full_render_1505x847" : "strip_display_motion"));
        need(Trace::RequestStart(request),"rectangular request"); snapshot(name);
        const unsigned frames=mode==0 ? 2 : 1;
        for (unsigned index=0;index<frames;++index)
        {
            rectangle.Record(capture,index);
            if (mode==0) rectangle.Sr(capture,index,2258,1271);
            need(Trace::GetStatus().recorded==index+1 && Trace::GetStatus().target==request.frameCount,
                 "rectangular or long target frame did not seal");
            rectangle.Execute(); Published(index+1); rectangle.Reset(); capture.Poll();
            need(Trace::GetStatus().estimatedFrameReadbackBytes<=MaximumFrameReadbackBytes &&
                 Trace::GetStatus().cpuQueuedBytes<=MaximumCpuBytes && Trace::GetStatus().retainedReadbackBytes<=MaximumReadbackBytes,
                 "rectangular capture exceeded a bounded memory budget");
        }
        need(Trace::IsActive(),"long/partial rectangular request stopped at a smaller target");
        Trace::RequestStop(); Closed(); need(Trace::GetStatus().captured==frames,"rectangular prefix lost");
        rectangle.NoGpuErrors();
    }
    {
        Host rectangle(1505,0,0,847); Trace capture; Trace::Request request;
        request.x=688; request.regionMode=Trace::Request::RegionMode::FullHeightStrip;
        need(Trace::RequestStart(request),"rectangular resize request"); snapshot("strip_resize");
        rectangle.Record(capture,0); rectangle.Execute(); Published(1); rectangle.Reset(); capture.Poll();
        need(!rectangle.Sources(capture,1504),"rectangle silently resized after admission");
        Closed(); need(Trace::GetStatus().captured==1 && Trace::GetStatus().message.find("Render extent changed")!=std::string::npos,
                       "rectangular resize lost the valid prefix or reason");
        rectangle.NoGpuErrors();
    }
    {
        Host extended(520,792,788); Trace capture; Trace::Request request;
        request.x=3; request.y=5; request.size=512; request.srMode=Trace::SrMode::MappedRoi;
        need(Trace::RequestStart(request),"wrong-SR-evaluation request"); snapshot("wrong_sr_evaluation");
        extended.Record(capture,0); extended.Sr(capture,0,768,770,true); Closed();
        need(Trace::GetStatus().captured==0 && Trace::GetStatus().recorded==0,"wrong SR evaluation exported/sealed");
        extended.Execute(); extended.Reset(); capture.Poll(); extended.NoGpuErrors();
    }
    {
        Host extended(520,792,788); Trace capture; Trace::Request request;
        request.x=3; request.y=5; request.size=512; request.srMode=Trace::SrMode::MappedRoi;
        need(Trace::RequestStart(request),"SR failure request"); snapshot("sr_failure");
        extended.Record(capture,0);
        need(Trace::GetStatus().recorded==0,"unmatched SR frame sealed");
        capture.Abort("SR dispatch failed before requested same-evaluation output"); Closed();
        need(Trace::GetStatus().captured==0,"failed SR exported fallback/pre-SR as post-SR");
        extended.Execute(); extended.Reset(); capture.Poll(); extended.NoGpuErrors();
    }
    {
        Host extended(520,792,788); Trace capture; Trace::Request request;
        request.x=3; request.y=5; request.size=512; request.srMode=Trace::SrMode::MappedRoi;
        need(Trace::RequestStart(request),"SR resize request"); snapshot("sr_resize");
        extended.Record(capture,0); extended.Sr(capture,0); extended.Execute(); Published(1); extended.Reset(); capture.Poll();
        extended.Record(capture,1); extended.Sr(capture,1,760,770); Closed();
        need(Trace::GetStatus().captured==1 && Trace::GetStatus().recorded==1,"SR resize sealed or lost prior prefix");
        extended.Execute(); extended.Reset(); capture.Poll(); extended.NoGpuErrors();
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"worker disk failure request"); snapshot("disk_failure");
        host.Record(capture,0);
        std::filesystem::create_directory(std::filesystem::path(Trace::GetStatus().folder)/"frames/0.pending");
        host.Execute(); host.Reset(); Closed();
        need(Trace::GetStatus().captured==0 && Trace::GetStatus().phase=="error","partial disk commit was retried/published");
        capture.Poll();
    }
    {
        Trace capture; Trace::Request request; request.outputRoot="relative-invalid";
        need(!Trace::RequestStart(request) && !Trace::IsActive(),"relative destination accepted");
    }
    {
        const uint64_t frameBytes=uint64_t(128)*128*137+592;
        g_testCpuBudget.store(frameBytes*2); g_testDiskDelayMs.store(250);
        Trace capture; need(Trace::RequestStart(3,5),"CPU backlog request"); snapshot("cpu_backlog");
        for (unsigned index=0;index<3 && Trace::IsActive();++index)
        {
            host.Record(capture,index); host.Execute(); host.Reset();
            Await([] { return Trace::GetStatus().pending==0 || !Trace::IsActive(); },"CPU backlog did not freeze/close pending frame");
        }
        Closed(); need(Trace::GetStatus().captured<3,"slow disk bypassed bounded CPU queue");
        need(Trace::GetStatus().message.find("CPU memory budget")!=std::string::npos,"CPU backpressure reason missing");
        g_testCpuBudget.store(MaximumCpuBytes); g_testDiskDelayMs.store(0); capture.Poll();
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"repeat-after-freeze request"); snapshot("repeated_after_freeze");
        host.Record(capture,0); host.Execute(); Published(1);
        host.Execute(false,false); capture.Poll(); Closed();
        uint64_t invalidRevision=0;
        { std::scoped_lock lock(Global().mutex); invalidRevision=Global().current->forcePublicationRevision; }
        for (unsigned repeat=0;repeat<25;++repeat) capture.Poll();
        { std::scoped_lock lock(Global().mutex); need(Global().current->forcePublicationRevision==invalidRevision,"same frozen invalid ticket forced repeated manifest publications"); }
        need(Trace::GetStatus().captured==1,"late repeat destroyed valid immutable prefix");
        need(Trace::GetStatus().message.find("lineage")!=std::string::npos,"late repeat did not stop future lineage");
        host.Reset(); capture.Poll();
    }
    {
        // Last: an ambiguous repeated submission is deliberately never recycled.
        Trace capture; need(Trace::RequestStart(3,5),"repeat submission request"); snapshot("repeated_submission");
        host.Record(capture,0); host.Execute(true); host.Reset(); capture.Poll();
        Closed(); need(Trace::GetStatus().captured==0,"repeated submission exported a frame");
    }
    host.NoGpuErrors();
    RRTraceAdditiveIO::WriteText(std::filesystem::path(argv[1])/"captures.json",results.dump(2));
    std::cout<<"GAME_TRACE production WARP capture lifecycle PASS\n";
    return 0;
}
catch (const std::exception& error) { std::cerr<<error.what()<<'\n'; return 1; }
'''


def run():
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', ROOT / 'tools_tmp/fsrd_game_trace_capture')).resolve()
    output.mkdir(parents=True, exist_ok=True)
    stubs = output / 'stubs'
    stubs.mkdir(exist_ok=True)
    (stubs / 'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n')
    (stubs / 'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\n'
                                'namespace Util { inline std::filesystem::path DllPath() { return g_dllPath; } }\n')
    recorder = ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp'
    feature = (ROOT / 'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp').read_text(encoding='utf-8-sig')
    controls_start = feature.index('const auto array =', feature.index('if (FSRDGameTraceSession::IsActive())'))
    controls_end = feature.index('// Fingerprint applied semantic controls only.', controls_start)
    (stubs / 'fsrd_game_trace_controls.inc').write_text(feature[controls_start:controls_end], encoding='utf-8')
    sr_start = feature.index('const CaptureJson controls {', feature.index('if (FSRDConvShader && FSRDGameTraceSession::WantsSrOutput())'))
    sr_end = feature.index("// FSR's output is UAV here.", sr_start)
    (stubs / 'fsrd_game_trace_sr_controls.inc').write_text(feature[sr_start:sr_end], encoding='utf-8')
    source = output / 'fsrd_game_trace_capture.cpp'
    source.write_text(CPP.replace('__RECORDER__', recorder.as_posix()).replace(
        '__RR_HEADER__', (ROOT / 'OptiScaler/include/fsr-rr/ffx_denoiser.h').as_posix()))
    exe = output / 'fsrd_game_trace_capture.exe'
    compile_cpp(source, exe, ('d3d12.lib', 'dxgi.lib', 'bcrypt.lib'),
                (stubs, ROOT / 'external/nlohmann', ROOT / 'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
    subprocess.run([str(exe), str(output)], check=True)
    captures = json.loads((output / 'captures.json').read_text())
    capture = Path(captures['complete'])
    manifest = json.loads((capture / 'capture.json').read_text())
    assert manifest['schema'] == 'fsrd-game-trace-v5'
    assert manifest['complete'] and manifest['committed_frames'] == 128
    assert manifest['neutral_full1_comparator'] is False
    assert manifest['output_scope'] == 'actual_configured_composition_before_sr'
    assert [f['ordinal'] for f in manifest['frames']] == list(range(128))
    assert [f['ordinal'] for f in manifest['frames'] if f['reset']] == [63]
    assert all(f['native_full1'] is False and f['cpu_snapshot_immutable'] and f['submission_gate_protected'] for f in manifest['frames'])
    assert any(f['command_list_detached'] is False for f in manifest['frames'])
    assert all(f['gpu_submission_verified'] and f['gpu_completed'] for f in manifest['frames'])
    assert all(f['controls']['motion_vector_scale'] == [2, 3, 4] for f in manifest['frames'])
    for frame in manifest['frames']:
        for row in frame['images'] + frame['diagnostics'] + [frame['conversion_constants'], frame['floor_seed_constants']]:
            if 'file' not in row:
                continue
            blob = (capture / row['file']).read_bytes()
            assert len(blob) == row['bytes'] and hashlib.sha256(blob).hexdigest() == row['sha256']
    from fsrd_real_capture_replay import inspect_capture
    provenance, data = inspect_capture(capture, payload=True)
    assert provenance['payload_unique_raw_frames'] == 128
    assert provenance['original_reset_frames'] == [63]
    assert provenance['maximum_camera_delta'] > 0
    # Inspect authenticated, unchanged HALF words at the nonzero ROI origin.
    expected = 0x3000 + 127 + 3 + 5
    assert int(data['raw_color'][-1, 0, 0, 0].view('uint16')) == expected
    assert int(data['native_full1'][-1, 0, 0, 0].view('uint16')) == expected
    del data
    for name, folder in captures.items():
        if name == 'complete':
            continue
        partial = json.loads((Path(folder) / 'capture.json').read_text())
        assert partial['complete'] is False, name
        assert [f['ordinal'] for f in partial['frames']] == list(range(len(partial['frames']))), name
    assert json.loads((Path(captures['cancelled']) / 'capture.json').read_text())['committed_frames'] == 2
    assert json.loads((Path(captures['failed_render']) / 'capture.json').read_text())['committed_frames'] == 0
    for name in ('mapped_sr_512', 'full_sr_512'):
        folder = Path(captures[name])
        provenance, arrays = inspect_capture(folder, payload=True)
        extended = json.loads((folder/'capture.json').read_text())
        assert extended['roi']['extent'] == [512, 512]
        assert extended['maximum_payload_bytes'] > (320 << 20)
        assert extended['capacity_wait_maximum_ms'] == 0
        assert extended['committed_frames'] == 2
        for frame in extended['frames']:
            post = frame['post_sr']
            assert post['source_extent'] == [792, 788] and post['logical_extent'] == [768, 770]
            assert post['evaluation_id'] == frame['evaluation_id']
            assert post['reset'] == (frame['ordinal'] == 1)
            blob = (folder/post['file']).read_bytes()
            assert hashlib.sha256(blob).hexdigest() == post['sha256']
            first = int.from_bytes(blob[:2], 'little')
            assert first == 0x4200 + frame['ordinal'] + sum(post['crop_origin'])
            if name == 'mapped_sr_512':
                assert post['crop_origin'] == [4, 7] and post['extent'] == [757, 759]
            else:
                assert post['crop_origin'] == [0, 0] and post['extent'] == [768, 770]
        del arrays
    rectangles = {
        'strip_128_mapped_sr_512_frames': ('full_height_strip', [688, 0], [128, 847], 512, 2),
        'strip_512_256_frames': ('full_height_strip', [688, 0], [512, 847], 256, 1),
        'full_render_1505x847': ('full_render', [0, 0], [1505, 847], 128, 1),
        'strip_display_motion': ('full_height_strip', [688, 0], [128, 847], 128, 1),
    }
    for name, (mode, origin, extent, target, count) in rectangles.items():
        folder = Path(captures[name])
        rectangular = json.loads((folder/'capture.json').read_text())
        provenance = inspect_capture(folder, payload=False)
        assert provenance['region_mode'] == mode
        assert rectangular['region_mode'] == mode and rectangular['target_frames'] == target
        assert rectangular['roi']['origin'] == origin and rectangular['roi']['extent'] == extent
        assert rectangular['roi']['geometry_resolved'] is True and rectangular['render_extent'] == [1505, 847]
        assert rectangular['committed_frames'] == rectangular['manifest_published_frames'] == count
        assert rectangular['maximum_frame_readback_bytes'] == 256 << 20
        assert rectangular['readback_accounting'] == 'committed_buffer_allocation_size'
        for frame in rectangular['frames']:
            charged = 0
            payload_bytes = 0
            for row in frame['images'] + frame['diagnostics'] + [frame['post_sr'], frame['conversion_constants'], frame['floor_seed_constants']]:
                if 'file' not in row:
                    continue
                blob = (folder/row['file']).read_bytes()
                assert len(blob) == row['bytes'] and hashlib.sha256(blob).hexdigest() == row['sha256']
                payload_bytes += len(blob)
                if 'copy_footprint' in row:
                    footprint = row['copy_footprint']
                    assert footprint['committed_buffer_bytes'] >= footprint['requested_buffer_bytes'] >= row['bytes']
                    assert footprint['committed_buffer_bytes'] % (64 << 10) == 0
                    charged += footprint['committed_buffer_bytes']
                    assert row['source_resource_address_process_local'] > 0
                    assert row['source_state_provenance'] == 'caller_declared_copy_contract_not_runtime_observed'
                    assert row['source_native_resource_desc']['width'] == row['source_extent'][0]
                    assert row['source_native_resource_desc']['height'] == row['source_extent'][1]
                if row.get('name') in ('U', 'native_full1', 'current_output', 'raw_color', 'raw_motion'):
                    crop_x, crop_y = row['crop_origin']
                    width, height = row['extent']
                    assert int.from_bytes(blob[:2], 'little') == 0x3000 + frame['ordinal'] + crop_x + crop_y
                    assert int.from_bytes(blob[-2:], 'little') == 0x3000 + frame['ordinal'] + crop_x + crop_y + width - 1 + height - 1 + 3
            assert charged == rectangular['estimated_frame_readback_bytes'] <= 256 << 20
            assert payload_bytes == rectangular['estimated_frame_payload_bytes']
            assert rectangular['estimated_payload_bytes'] == payload_bytes * target
            assert rectangular['maximum_payload_bytes'] == payload_bytes * target + payload_bytes * target // 20 + (1 << 20)
            for row in frame['images']:
                assert row['extent'] == extent and row['crop_origin'] == origin and row['source_extent'] == [1505, 847]
            motion = next(row for row in frame['diagnostics'] if row['name'] == 'raw_motion')
            assert motion['mapping']['render_roi_extent'] == extent
            if name == 'strip_display_motion':
                assert motion['crop_origin'] == [687, 0] and motion['extent'] == [130, 847]
            else:
                assert motion['crop_origin'] == origin and motion['extent'] == extent
            if name == 'strip_128_mapped_sr_512_frames':
                post = frame['post_sr']
                assert post['source_extent'] == [2284, 1298] and post['logical_extent'] == [2258, 1271]
                left = origin[0] * 2258 // 1505
                right = ((origin[0] + extent[0]) * 2258 + 1504) // 1505
                assert post['crop_origin'] == [left, 0] and post['extent'] == [right - left, 1271]
        del blob
    resized = json.loads((Path(captures['strip_resize'])/'capture.json').read_text())
    assert resized['committed_frames'] == 1 and resized['roi']['extent'] == [128, 847]
    assert 'Render extent changed' in resized['incomplete_reason']
    batched = json.loads((Path(captures['manifest_batch_idle_stop'])/'capture.json').read_text())
    assert batched['committed_frames'] == batched['manifest_published_frames'] == 11
    assert batched['manifest_publication']['batch_frames'] == 8 and batched['manifest_publication']['maximum_delay_ms'] == 250
    assert batched['manifest_publication']['successful_writes_before_this_publication'] < 7
    publication_failure = json.loads((Path(captures['manifest_replace_failure'])/'capture.json').read_text())
    assert publication_failure['committed_frames'] == publication_failure['manifest_published_frames'] == 1
    assert len(publication_failure['frames']) == 1
    assert (Path(captures['manifest_replace_failure'])/'frames/1/frame.json').is_file()
    cutoff = json.loads((Path(captures['lineage_cutoff_during_publish'])/'capture.json').read_text())
    assert cutoff['committed_frames'] == cutoff['manifest_published_frames'] == 1
    assert cutoff['private_staged_frames'][0]['ordinal'] == 1
    assert cutoff['private_staged_frames'][0]['frame']['cpu_snapshot_immutable'] is True
    assert (Path(captures['lineage_cutoff_during_publish'])/'frames/1.pending/frame.json').is_file()
    rename_failure = json.loads((Path(captures['frame_rename_failure'])/'capture.json').read_text())
    assert rename_failure['committed_frames'] == rename_failure['manifest_published_frames'] == 0
    assert rename_failure['private_staged_frames'][0]['frame']['ordinal'] == 0
    assert rename_failure['private_staged_frames'][0]['frame']['cpu_snapshot_immutable'] is True
    preflight_failure = json.loads((Path(captures['preflight_disk_budget'])/'capture.json').read_text())
    assert preflight_failure['committed_frames'] == 0 and preflight_failure['recorded_frames'] == 0
    assert '512-frame destination preflight including 5% allowance requires' in preflight_failure['incomplete_reason']
    retired = json.loads((Path(captures['retired_list'])/'capture.json').read_text())
    assert retired['committed_frames'] == 2
    assert retired['frames'][0]['ticket_proof']['detached'] is False
    assert any(not row['ticket']['detached'] for row in retired['retained_gpu_tickets_at_close'])
    report = {'schema': 'fsrd-game-trace-capture-host-test-v1', 'status': 'PASS',
              'frames': 128, 'mid_capture_reset': 63, 'reader_schema': manifest['schema'],
              'gpu_backend': 'WARP', 'debug_layer_errors': 0, 'debug_layer_warnings': 0,
              'cpu_snapshot_bytes_limit': 512 << 20, 'retained_readback_bytes_limit': 512 << 20,
              'frame_committed_readback_bytes_limit': 256 << 20,
              'rectangular_cases': sorted(rectangles), 'targets_cpu_checked': [128, 256, 512],
              'manifest_batch_frames': 8, 'manifest_deadline_ms': 250,
              'batch_case_manifest_writes': batched['manifest_publication']['successful_writes_before_this_publication'] + 1,
              'cases': sorted(captures), 'capture': str(capture),
              'limitation': 'Controlled GPU words; no game capture or image-quality claim.'}
    (output / 'game_trace_capture_report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    run()
