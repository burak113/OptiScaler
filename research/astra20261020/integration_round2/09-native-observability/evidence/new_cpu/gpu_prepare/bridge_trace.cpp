
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
thread_local uint64_t bridgeAllocations=0;
thread_local bool bridgeCountAllocations=false;
void* operator new(std::size_t bytes)
{
    if(bridgeCountAllocations)++bridgeAllocations;
    if (g_testFailHeapAllocation.load(std::memory_order_relaxed)) throw std::bad_alloc();
    if (void* value=std::malloc(bytes ? bytes : 1)) return value;
    throw std::bad_alloc();
}
void operator delete(void* value) noexcept { std::free(value); }
void operator delete(void* value,std::size_t) noexcept { std::free(value); }
#define FSRD_GAME_TRACE_TEST
#include "/workspace/scratch/29cea04d2981/OptiScaler/OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp"
#include "/workspace/scratch/29cea04d2981/OptiScaler/OptiScaler/include/fsr-rr/ffx_denoiser.h"
#include <ffx_upscale.h>
using Microsoft::WRL::ComPtr;
using Trace = FSRDGameTraceSession;
constexpr auto srv = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
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

#include "shaders/fsrd_preprocess/FSRDNrdLightingGuard_Dx12.h"
// Appended to the unchanged original Trace fixture Host. Controlled words only:
// real recorder/copies/fence/Map/publication; output lease/provider witness are
// explicit CPU adapters. No AMD SDK call, title detour or image-quality oracle.
unsigned bridgeChecks = 0;
std::atomic<uint32_t> observedOwnedStatus {0};
std::atomic<bool> observedStatusLocks {false};
std::weak_ptr<Frame> statusObserverFrame;
void ObserveOwnedStatus(const Trace::BridgeIdentity& identity,uint32_t status) noexcept
{
    bool clear=false;
    try
    {
        const auto frame=statusObserverFrame.lock();
        std::thread probe([&] {
            const auto deadline=GetTickCount64()+100;
            do {
                std::unique_lock global(Global().mutex,std::try_to_lock);
                std::unique_lock registry(RRTraceFence::GetRegistry().mutex,std::try_to_lock);
                if(global.owns_lock()&&registry.owns_lock()&&frame)
                {std::unique_lock ticket(frame->ticket->mutex,std::try_to_lock);if(ticket.owns_lock()){clear=true;break;}}
                Sleep(1);
            } while(GetTickCount64()<deadline);
        });
        probe.join();
        clear=clear&&identity.recordingId==20&&identity.streamlineFrame==100;
    }
    catch(...){clear=false;}
    observedStatusLocks.store(clear);observedOwnedStatus.store(status);
}
void check(bool value, const char* message) { ++bridgeChecks; need(value,message); }
struct OwnedBridgeFixture
{
    std::array<ComPtr<ID3D12Resource>,4> stages;
    std::array<ComPtr<ID3D12Resource>,7> inputs;
    ComPtr<ID3D12Resource> flag;
    std::array<ComPtr<ID3D12Resource>,2> title;
    std::array<ComPtr<ID3D12Resource>,2> anchorInputs;
    ComPtr<ID3D12Resource> anchorGain;
    explicit OwnedBridgeFixture(Host& h)
    {
        inputs = {h.textures[0],h.textures[1],h.textures[6],h.textures[7],h.textures[5],h.textures[2],h.textures[3]};
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC d {}; d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        d.Width = h.renderWidth; d.Height = h.renderHeight; d.DepthOrArraySize = d.MipLevels = 1;
        d.SampleDesc.Count = 1; d.Format = DXGI_FORMAT_R16G16B16A16_FLOAT; d.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        for (auto& resource : stages) hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,
            D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&resource)));
        for (auto& resource : title) hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,
            D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&resource)));
        d = ReadbackDesc(1536); d.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,D3D12_RESOURCE_STATE_COMMON,nullptr,IID_PPV_ARGS(&flag)));
    }
    void FillAnchor(Host& h)
    {
        // Controlled physical input/gain words, not a denoiser or quality oracle.
        if (!anchorGain)
        {
            D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_DEFAULT;
            auto d=inputs[0]->GetDesc();d.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
            for(auto& r:anchorInputs)hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,srv,nullptr,IID_PPV_ARGS(&r)));
            d.Width=std::max(1u,h.renderWidth/8u);d.Height=std::max(1u,h.renderHeight/8u);
            hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,srv,nullptr,IID_PPV_ARGS(&anchorGain)));
        }
        const std::array<ID3D12Resource*,3> targets {anchorInputs[0].Get(),anchorInputs[1].Get(),anchorGain.Get()};
        for(size_t i=0;i<targets.size();++i)
        {
            const auto d=targets[i]->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp {};UINT64 bytes=0;
            h.device->GetCopyableFootprints(&d,0,1,0,&fp,nullptr,nullptr,&bytes);
            D3D12_HEAP_PROPERTIES heap {};heap.Type=D3D12_HEAP_TYPE_UPLOAD;auto bd=ReadbackDesc(bytes);
            ComPtr<ID3D12Resource> upload;hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&bd,
                D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&upload)));
            void* mapped=nullptr;D3D12_RANGE empty {0,0};hr(upload->Map(0,&empty,&mapped));memset(mapped,0,size_t(bytes));
            const uint16_t base=i==0?0x3400u:i==1?0x3800u:0x3a00u;
            for(UINT y=0;y<d.Height;++y)for(UINT x=0;x<d.Width;++x)for(UINT c=0;c<4;++c)
            {
                const uint16_t word=i==2&&c!=0?0:uint16_t(base+x+y+c);
                memcpy(static_cast<uint8_t*>(mapped)+fp.Offset+y*fp.Footprint.RowPitch+(x*4+c)*2,&word,2);
            }
            upload->Unmap(0,nullptr);
            D3D12_RESOURCE_BARRIER b {};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            b.Transition={targets[i],0,srv,D3D12_RESOURCE_STATE_COPY_DEST};h.list->ResourceBarrier(1,&b);
            D3D12_TEXTURE_COPY_LOCATION src {},dst {};src.pResource=upload.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
            src.PlacedFootprint=fp;dst.pResource=targets[i];dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            h.list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);std::swap(b.Transition.StateBefore,b.Transition.StateAfter);
            h.list->ResourceBarrier(1,&b);h.uploads.push_back(std::move(upload));
        }
    }
    NrdBridge::ConvertedResources Converted(Host& h)
    {
        return {inputs[0].Get(),inputs[1].Get(),inputs[2].Get(),inputs[3].Get(),inputs[4].Get(),inputs[5].Get(),inputs[6].Get(),nullptr,
            h.renderWidth,h.renderHeight};
    }
    NrdBridge::RRRecordedOutputSnapshot Snapshot(Host& h,unsigned frame,bool separate=false)
    {
        NrdBridge::RRRecordedOutputSnapshot out;
        out.rawSpec=stages[0].Get(); out.rawDiff=stages[1].Get();
        out.selectedSpec=stages[separate ? 2 : 0].Get(); out.selectedDiff=stages[separate ? 3 : 1].Get();
        out.recording=h.list.Get(); out.frameSL=100+frame; out.frameIndex=500+frame;
        out.width=h.renderWidth; out.height=h.renderHeight; out.contextGeneration=7; out.recordingId=20+frame;
        out.providerVersionId=12; out.providerApiVersion=FFX_DENOISER_VERSION;
        out.providerSignalFlags=FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE|FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR;
        // Deliberately nonzero typed metadata adapter, not an actual SDK call.
        out.providerCheckerboardSignalFlags=out.providerSignalFlags;
        out.diffuseCheckerboardOrigin=frame&1u;out.specularCheckerboardOrigin=(frame+1u)&1u;
        const char name[]="CPU adapter; no actual provider"; memcpy(out.providerName.data(),name,sizeof(name));
        ffxDispatchDescDenoiser dispatch {};
        dispatch.renderSize={h.renderWidth,h.renderHeight}; dispatch.frameIndex=out.frameIndex;
        dispatch.flags=frame==0 ? FFX_DENOISER_DISPATCH_RESET : 0;
        dispatch.motionVectorScale={1,1,1}; dispatch.jitterOffsets={-0.0f,.25f};
        memcpy(out.providerControl.data(),reinterpret_cast<const uint8_t*>(&dispatch)+264,184);
        return out;
    }
    void Copy(Host& h,ID3D12Resource* src,D3D12_RESOURCE_STATES srcState,ID3D12Resource* dst)
    {
        D3D12_RESOURCE_BARRIER barriers[2] {};
        barriers[0].Type=barriers[1].Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barriers[0].Transition={src,0,srcState,D3D12_RESOURCE_STATE_COPY_SOURCE};
        barriers[1].Transition={dst,0,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_DEST};
        h.list->ResourceBarrier(2,barriers); h.list->CopyResource(dst,src);
        for (auto& barrier:barriers) std::swap(barrier.Transition.StateBefore,barrier.Transition.StateAfter);
        h.list->ResourceBarrier(2,barriers);
    }
    void FillStages(Host& h,uint32_t ownedStatus=0)
    {
        for (size_t i=0;i<stages.size();++i) Copy(h,inputs[i&1].Get(),srv,stages[i].Get());
        // Actual private flag GPU buffer; production Trace copies byte1212 only.
        D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_UPLOAD;
        auto d=ReadbackDesc(1536); ComPtr<ID3D12Resource> upload;
        hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&upload)));
        void* data=nullptr; D3D12_RANGE empty {0,0}; hr(upload->Map(0,&empty,&data)); memset(data,0,1536);
        memcpy(data,&ownedStatus,4); // Bridge-generated status; not a native CB operand.
        const uint32_t nativeFlag=1; memcpy(static_cast<uint8_t*>(data)+1212,&nativeFlag,4);
        // Controlled GPU-owned header adapter, not proof that a title PrePass executed.
        for(uint32_t offset: {448u,452u,456u,460u,472u,476u,516u,520u,576u,580u})
        {const uint32_t word=0x51000000u+offset;memcpy(static_cast<uint8_t*>(data)+offset,&word,4);}
        upload->Unmap(0,nullptr);
        D3D12_RESOURCE_BARRIER barrier {}; barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition={flag.Get(),0,D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COPY_DEST}; h.list->ResourceBarrier(1,&barrier);
        h.list->CopyBufferRegion(flag.Get(),0,upload.Get(),0,1536);
        std::swap(barrier.Transition.StateBefore,barrier.Transition.StateAfter);h.list->ResourceBarrier(1,&barrier);
        h.uploads.push_back(std::move(upload));
    }
};
Trace::BridgeIdentity Identity(unsigned frame=0,uint64_t domain=11)
{ return {domain,20+frame,1+frame,4,3,100+frame}; }
NrdBridge::FrameParameters Parameters(unsigned frame=0)
{
    NrdBridge::FrameParameters p;
    p.camera.view=p.camera.inverseView=p.camera.projection=DirectX::XMMatrixIdentity();
    p.camera.viewSource=p.camera.projectionSource=FSRDCamera::Source::StreamlineMatrix;
    p.streamlineFrame=100+frame;p.frameIndex=500+frame;p.reset=frame==0;p.previousValid=frame!=0;
    p.jitter={-0.0f,.25f}; p.previousJitter={.125f,-.25f};p.depthSign=-1.f;
    return p;
}
Trace::BridgeProviderBinaryIdentity Witness()
{
    // Deliberately unavailable: this fixture must NEVER qualify as signed SDK replay.
    return {R"({"schema_version":1,"attested":false,"failure":"CPU output adapter; no provider call"})"};
}
Trace::BridgeFrameToken Owned(Trace& trace,Host& h,const std::shared_ptr<OwnedBridgeFixture>& owner,
    unsigned frame=0,bool separate=false,Trace::BridgeIdentity id=Identity())
{
    auto output=owner->Snapshot(h,frame,separate); output.owner=owner;
    sl::Constants sl;
    sl.clipToPrevClip[0].x=-0.0f;
    return trace.RecordBridgeOwned(h.device.Get(),h.list.Get(),id,owner->Converted(h),owner,Parameters(frame),sl,100+frame,2,
        NrdBridge::RRSettingsState{},output,Witness());
}
Trace::BridgeControlHeader ControlHeader(const std::shared_ptr<OwnedBridgeFixture>& owner,unsigned frame,bool forcePrepass=false)
{
    Trace::BridgeControlHeader header;header.image={owner->flag.Get(),D3D12_RESOURCE_STATE_COMMON};header.owner=owner;
    header.recordingId=20+frame;header.streamlineFrame=100+frame;header.bridgeFrame=500+frame;
    const bool recon=frame==0&&!forcePrepass;
    header.profile=recon ? Trace::BridgeControlHeader::Profile::ReconA : Trace::BridgeControlHeader::Profile::PrePassB;
    header.wordCount=recon ? 4 : 8;header.hasStatus=!recon;header.statusByteOffset=0;
    header.statusObserver=ObserveOwnedStatus;
    const std::array<uint32_t,8> offsets=recon ? std::array<uint32_t,8>{448,452,456,460} :
        std::array<uint32_t,8>{456,460,472,476,516,520,576,580};
    for(size_t i=0;i<header.wordCount;++i)header.words[i]={offsets[i],offsets[i]};
    return header;
}
Trace::BridgeFrameToken Admit(Trace& trace,Host& h,const std::shared_ptr<OwnedBridgeFixture>& owner,unsigned frame=0,bool separate=false)
{
    Trace::BridgeFrameToken token;
    Await([&]{if(!token)token=Owned(trace,h,owner,frame,separate,Identity(frame));return bool(token)||!Trace::IsActive();},"bridge admission did not initialize");
    return token;
}
Trace::Request Request(const std::filesystem::path& root)
{
    Trace::Request request;request.capturePath=Trace::Request::CapturePath::NrdBridge;
    request.regionMode=Trace::Request::RegionMode::FullRender;request.outputRoot=root.string();return request;
}
void AnchorTraceChecks(const std::filesystem::path& root,Json& result)
{
    // A cropped odd render extent proves that the gain image keeps its own
    // complete 1/8 grid rather than inheriting the main image ROI/row pitch.
    Host h(137,0,0,131);auto owner=std::make_shared<OwnedBridgeFixture>(h);
    uint64_t inactiveReadback=0,inactivePayload=0;
    for(bool active:{false,true})
    {
        auto request=Request(root);request.regionMode=Trace::Request::RegionMode::Square;
        request.x=7;request.y=1;request.size=128;
        Trace trace;check(Trace::RequestStart(request),"anchor trace request");
        result[active?"anchor_active_capture":"anchor_inactive_capture"]=Trace::GetStatus().folder;
        h.Fill(0);owner->FillStages(h);if(active)owner->FillAnchor(h);
        auto output=owner->Snapshot(h,0);output.owner=owner;output.postMotionAnchorActive=active;
        if(active)
        {
            output.providerPhysicalSpec=owner->anchorInputs[0].Get();output.providerPhysicalDiff=owner->anchorInputs[1].Get();
            output.postMotionAnchorGain=owner->anchorGain.Get();
        }
        NrdBridge::RRSettingsState settings;settings.requested.postMotionAnchor=active;settings.requested.postMotionAnchorStrength=.75f;
        Trace::BridgeFrameToken token;
        Await([&]{if(!token)token=trace.RecordBridgeOwned(h.device.Get(),h.list.Get(),Identity(),owner->Converted(h),owner,
            Parameters(),sl::Constants{},100,2,settings,output,Witness());return bool(token)||!Trace::IsActive();},"anchor trace admission");
        check(bool(token),"anchor trace owned input rejected");auto frame=std::static_pointer_cast<Frame>(token);
        check(frame->bridgeOwnedResources[0]==(active?owner->anchorInputs[0].Get():owner->inputs[0].Get()),
            "trace spec input did not follow frozen corrected physical source");
        check(frame->bridgeOwnedResources[1]==(active?owner->anchorInputs[1].Get():owner->inputs[1].Get()),
            "trace diffuse input did not follow frozen corrected physical source");
        size_t gain=SIZE_MAX;for(size_t i=0;i<frame->surveyKeys.size();++i)if(frame->surveyKeys[i]=="post_motion_anchor_gain")gain=i;
        check((gain!=SIZE_MAX)==active,"inactive anchor allocated/published a gain image or active gain was omitted");
        check(frame->surveyImages.size()==(active?13u:12u),"optional gain changed mandatory bridge role allocations");
        uint64_t charged=0,payload=frame->constants.size()+36;
        for(const auto& image:frame->surveyImages){charged+=image.allocationBytes;payload+=uint64_t(image.width)*image.height*image.bpp;}
        check(frame->gpuBytes==charged,"anchor gain committed readback was not charged exactly once");
        check(Trace::GetStatus().estimatedFrameReadbackBytes==charged,"anchor gain was omitted from readback preflight");
        {std::scoped_lock lock(Global().mutex);check(Global().current->manifest["estimated_frame_payload_bytes"]==payload,
            "anchor gain was omitted from payload preflight");}
        const auto& meta=frame->bridgeMetadata["post_motion_anchor"];
        check(meta["active"]==active&&meta["gain_role"]==(active?"post_motion_anchor_gain":"none"),"anchor activity/gain-role metadata mismatch");
        check(meta["input_stage"]=="after_anchor_before_optional_turn_filters_and_radiance_scaling", "anchor input stage provenance lost");
        if(active)
        {
            const auto& image=frame->surveyImages[gain];check(image.width==17&&image.height==16&&image.cropX==0&&image.cropY==0,
                "gain diagnostic inherited image ROI instead of its own full odd-size grid");
            check(image.bpp==8&&image.channels==4&&image.format==DXGI_FORMAT_R16G16B16A16_FLOAT,"gain diagnostic format contract changed");
            check(charged==inactiveReadback+image.allocationBytes&&payload==inactivePayload+17u*16u*8u,
                "active-only gain preflight delta is not exactly its own image");
            bool retained=false;for(const auto& resource:frame->ticket->resources)retained|=resource.Get()==static_cast<IUnknown*>(owner->anchorGain.Get());
            check(retained,"gain readback did not retain its exact GPU resource");
        }
        else{inactiveReadback=charged;inactivePayload=payload;}
        result["anchor_preflight"][active?"active":"inactive"]={{"readback_bytes",charged},{"reserved_payload_bytes",payload}};
        check(trace.RecordBridgeControlHeader(token,h.list.Get(),Identity(),ControlHeader(owner,0)),"anchor trace control header");
        for(size_t i=0;i<2;++i)owner->Copy(h,owner->stages[i].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,owner->title[i].Get());
        output.outputCommitted=true;output.encodingFlag=owner->flag.Get();output.nativeEncodingCaptured=true;
        std::array<Trace::Source,2> targets {{{owner->title[0].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS},
            {owner->title[1].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS}}};
        NrdBridge::TitleSignalConstants native;native.address=owner->flag->GetGPUVirtualAddress();native.wordIndex=36;
        check(trace.CompleteBridgeFrame(token,h.list.Get(),Identity(),targets,output,native),"anchor trace commit rejected");
        h.Execute();Saved(1);h.Reset();token.reset();frame.reset();trace.Poll();Trace::RequestStop();Closed();Published(1);
    }
    h.NoGpuErrors();
}

// Appended to the existing real-WARP Host/OwnedBridgeFixture by the local runner.
// The actual production recorder/copy/fence/Map code executes; provider outputs,
// selection decisions and scale metadata below are explicit controlled adapters.
// No actual AMD SDK, native title hook, image-quality oracle or scale round trip.
uint16_t ObservationCanary(uint32_t x,uint32_t y,uint32_t channel,uint32_t lobe,uint32_t phase)
{
    static constexpr uint16_t alpha[] {0x7e01u,0x7c01u,0x8000u,0x0001u,0x0000u};
    if(channel==3) return alpha[(x+3*y+lobe+phase)%5u];
    return uint16_t(0x3000u+0x0100u*lobe+0x0800u*phase+(x+3*y+channel)%512u);
}
void UploadObservationCanary(Host& h,ID3D12Resource* texture,uint32_t lobe,uint32_t phase)
{
    const auto desc=texture->GetDesc();
    check(desc.Format==DXGI_FORMAT_R16G16B16A16_FLOAT,"canary source format");
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp {}; UINT64 bytes=0;
    h.device->GetCopyableFootprints(&desc,0,1,0,&fp,nullptr,nullptr,&bytes);
    D3D12_HEAP_PROPERTIES heap {};heap.Type=D3D12_HEAP_TYPE_UPLOAD;
    auto bd=ReadbackDesc(bytes);ComPtr<ID3D12Resource> upload;
    hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&bd,D3D12_RESOURCE_STATE_GENERIC_READ,
        nullptr,IID_PPV_ARGS(&upload)));
    void* mapped=nullptr;D3D12_RANGE empty {0,0};hr(upload->Map(0,&empty,&mapped));
    memset(mapped,0xcd,size_t(bytes));
    for(UINT y=0;y<desc.Height;++y)for(UINT x=0;x<desc.Width;++x)for(UINT c=0;c<4;++c)
    {
        const auto value=ObservationCanary(x,y,c,lobe,phase);
        memcpy(static_cast<uint8_t*>(mapped)+fp.Offset+y*fp.Footprint.RowPitch+(x*4+c)*2,&value,2);
    }
    upload->Unmap(0,nullptr);
    D3D12_RESOURCE_BARRIER barrier {};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition={texture,0,srv,D3D12_RESOURCE_STATE_COPY_DEST};h.list->ResourceBarrier(1,&barrier);
    D3D12_TEXTURE_COPY_LOCATION source {},destination {};
    source.pResource=upload.Get();source.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;source.PlacedFootprint=fp;
    destination.pResource=texture;destination.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    h.list->CopyTextureRegion(&destination,0,0,0,&source,nullptr);
    std::swap(barrier.Transition.StateBefore,barrier.Transition.StateAfter);h.list->ResourceBarrier(1,&barrier);
    // Preserve every upload until this recording actually completes; a second
    // Host::Fill would prematurely clear uploads of earlier recorded commands.
    h.uploads.push_back(std::move(upload));
}
void InitializeObservationSession(Trace& trace,Host& h,const std::shared_ptr<OwnedBridgeFixture>& owner)
{
    // First post-provider call only claims the owner and wakes the disk worker.
    // No early payload exists yet, so it must return before admission.
    auto output=owner->Snapshot(h,0);output.owner=owner;
    const auto initial=trace.RecordBridgeOwned(h.device.Get(),h.list.Get(),Identity(),owner->Converted(h),owner,
        Parameters(),sl::Constants{},100,2,{},output,Witness());
    check(!initial,"startup unexpectedly published an absent early observation");
    Await([] {std::scoped_lock lock(Global().mutex);return Global().current&&Global().current->initialized;},
        "native observation session did not initialize");
}
std::weak_ptr<void> EarlyObservation(Host& h,const NrdBridge::ConvertedResources& input)
{
    return Trace::RecordNativeObservationInputs(h.device.Get(),h.list.Get(),input,input,
        11,20,7,1,500,100,true);
}
int main(int argc,char** argv) try
{
    need(argc==2,"output directory required");const auto root=std::filesystem::path(argv[1]);
    g_dllPath=root/"test_OptiScaler.dll";
    Json result {{"scope","actual_production_recorder_WARP_copies_fences_Map; controlled_output_selection_scale_adapters"},
        {"actual_sdk_dispatches",0},{"scale_roundtrip_executed",false},{"quality_accepted",false}};
    Host h(137,0,0,131);auto owner=std::make_shared<OwnedBridgeFixture>(h);
    {
        Trace trace;g_testFailHeapAllocation.store(true);
        const auto off=Trace::RecordNativeObservationInputs(nullptr,nullptr,{}, {},0,0,0,0,0,0,false);
        g_testFailHeapAllocation.store(false);
        check(off.expired(),"OFF touched native resources or created an observation");
        check(!Trace::WantsNativeObservations(),"native observations enabled by default");
        result["off_no_allocation_or_native_access"]=true;
    }
    for(bool protectedPath:{false,true})
    {
        Trace trace;auto request=Request(root);request.nativeObservations=true;
        request.regionMode=Trace::Request::RegionMode::Square;request.x=7;request.y=1;request.size=128;
        check(Trace::RequestStart(request),"observation request");
        result[protectedPath?"protected_capture":"raw_capture"]=Trace::GetStatus().folder;
        InitializeObservationSession(trace,h,owner);
        h.Fill(0);const auto input=owner->Converted(h);
        for(uint32_t lobe=0;lobe<2;++lobe)UploadObservationCanary(h,owner->inputs[lobe].Get(),lobe,0);
        auto early=EarlyObservation(h,input);check(!early.expired(),"early input capture rejected");
        const auto earlyFrame=std::static_pointer_cast<Frame>(early.lock());
        check(earlyFrame&&earlyFrame->discarded&&!earlyFrame->sealed,"unadopted early input became publishable");
        check(earlyFrame->gpuBytes!=0,"early words lack charged readback storage");
        // This is an explicit synthetic overwrite, not a simulated scaling pass.
        // It makes a misplaced late physical-input snapshot observably wrong.
        for(uint32_t lobe=0;lobe<2;++lobe)UploadObservationCanary(h,owner->inputs[lobe].Get(),lobe,1);
        owner->FillStages(h);
        auto output=owner->Snapshot(h,0,protectedPath);output.owner=owner;
        output.nativeObservationInputs=early;output.resetEpoch=1;
        output.specularSelection=output.diffuseSelection=protectedPath?
            FSRDNrdObservation::SelectionPath::LobeRecovery:FSRDNrdObservation::SelectionPath::RawRR;
        output.recoveryActive=protectedPath;
        output.providerDiffuseRadianceScale=16;output.providerSpecularRadianceScale=256;output.providerRadianceScale=0;
        NrdBridge::RRSettingsState settings;settings.requested.radianceScale.enabled=true;
        auto token=trace.RecordBridgeOwned(h.device.Get(),h.list.Get(),Identity(),input,owner,Parameters(),
            sl::Constants{},100,2,settings,output,Witness());
        check(bool(token),"same-recording early observation not adopted");
        check(token.get()==earlyFrame.get(),"adoption duplicated the early frame/fence");
        const auto frame=std::static_pointer_cast<Frame>(token);
        uint64_t charged=0;for(const auto& image:frame->surveyImages)charged+=image.allocationBytes;
        check(frame->gpuBytes==charged,"early readbacks charged twice or omitted");
        for(size_t lobe=0;lobe<2;++lobe)
        {
            auto* selected=lobe==0?output.selectedSpec:output.selectedDiff;
            owner->Copy(h,selected,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,owner->title[lobe].Get());
        }
        output.outputCommitted=true;
        const std::array<Trace::Source,2> targets {{{owner->title[0].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS},
            {owner->title[1].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS}}};
        check(trace.CompleteBridgeFrame(token,h.list.Get(),Identity(),targets,output,{}),"late observation commit rejected");
        h.Execute();Saved(1);h.Reset();token.reset();trace.Poll();Trace::RequestStop();Closed();Published(1);
        h.NoGpuErrors();
    }
    {
        Trace trace;auto request=Request(root);request.nativeObservations=true;
        check(Trace::RequestStart(request),"stale epoch request");InitializeObservationSession(trace,h,owner);
        h.Fill(0);owner->FillStages(h);const auto input=owner->Converted(h);auto early=EarlyObservation(h,input);
        check(!early.expired(),"stale epoch setup");auto output=owner->Snapshot(h,0);output.owner=owner;
        output.nativeObservationInputs=early;output.resetEpoch=2;
        output.specularSelection=output.diffuseSelection=FSRDNrdObservation::SelectionPath::RawRR;
        const auto rejected=trace.RecordBridgeOwned(h.device.Get(),h.list.Get(),Identity(),input,owner,
            Parameters(),sl::Constants{},100,2,{},output,Witness());
        check(!rejected,"early observation adopted across reset epoch");
        h.Discard();trace.Poll();Trace::RequestStop();Closed();
        check(Trace::GetStatus().captured==0,"stale early frame reached publication");
        result["stale_epoch_rejected_before_publication"]=true;
    }
    h.NoGpuErrors();result["checks"]=bridgeChecks;result["debug_errors"]=0;result["debug_warnings"]=0;
    RRTraceAdditiveIO::WriteText(root/"review-native-observation-gpu.json",result.dump(2));
    std::cout<<result.dump(2)<<'\n';return 0;
}
catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
