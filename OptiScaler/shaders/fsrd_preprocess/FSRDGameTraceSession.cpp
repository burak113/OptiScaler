#include "pch.h"
#include "FSRDGameTraceSession.h"
#include "RRTraceFence.h"
#include "RRTraceAdditiveIO.h"
#include "Util.h"
#include <json.hpp>
#include <deque>
#include <map>
#include <mutex>
#include <new>
#include <sstream>
#include <algorithm>
#include <cmath>
#include <climits>
#include <atomic>
#include <condition_variable>
#include <thread>
#include <chrono>

namespace
{
using Json = nlohmann::json;
using Microsoft::WRL::ComPtr;
constexpr uint64_t MaximumPayloadBytes = 320ull << 20;
constexpr uint64_t MaximumExtendedPayloadBytes = 16ull << 30;
constexpr uint64_t MaximumReadbackBytes = 512ull << 20;
constexpr uint64_t MaximumFrameReadbackBytes = 128ull << 20;
constexpr uint64_t MaximumCpuBytes = 512ull << 20;
#if defined(FSRD_GAME_TRACE_TEST)
// Controlled host fixtures exercise backpressure without hundreds of MiB of
// artificial disk traffic. These controls are absent from production builds.
std::atomic<uint64_t> g_testCpuBudget {MaximumCpuBytes};
std::atomic<uint32_t> g_testDiskDelayMs {0};
std::atomic<bool> g_testFailStartManifestAllocation {false};
std::atomic<bool> g_testFailPendingDiagnosticsAllocation {false};
std::atomic<bool> g_testHoldCpuFreeze {false};
uint64_t CpuBudget() { return g_testCpuBudget.load(std::memory_order_relaxed); }
#else
constexpr uint64_t CpuBudget() { return MaximumCpuBytes; }
#endif
constexpr size_t MaximumPendingFrames = 3;
constexpr std::array<const char*, 10> Names {"U", "V", "Qs", "Qd", "Skip", "packed", "depth", "motion", "native_full1", "current_output"};
constexpr std::array<DXGI_FORMAT, 10> Formats {DXGI_FORMAT_R16G16B16A16_FLOAT, DXGI_FORMAT_R16G16B16A16_FLOAT,
    DXGI_FORMAT_R8G8B8A8_UNORM, DXGI_FORMAT_R8G8B8A8_UNORM, DXGI_FORMAT_R16G16B16A16_FLOAT,
    DXGI_FORMAT_R10G10B10A2_UNORM, DXGI_FORMAT_R32_FLOAT, DXGI_FORMAT_R16G16B16A16_FLOAT,
    DXGI_FORMAT_R16G16B16A16_FLOAT, DXGI_FORMAT_R16G16B16A16_FLOAT};
constexpr std::array<const char*,19> DiagnosticNames {"raw_color", "raw_normals", "raw_specular_albedo",
    "raw_diffuse_albedo", "rr_specular", "rr_diffuse", "floor", "floor_reference", "raw_bias_mask",
    "raw_specular_hit_distance", "raw_specular_direction_hit_distance", "raw_diffuse_hit_distance",
    "raw_responsivity", "raw_emissive", "raw_motion", "raw_depth", "raw_roughness",
    "raw_title_linear_depth", "raw_inspector"};

std::atomic<bool> g_captureActive {false};
std::atomic<bool> g_srRequested {false};
struct Session
{
    FSRDGameTraceSession::Status status;
    std::filesystem::path folder;
    uint32_t x = 0, y = 0, size = FSRDGameTraceSession::TileSize, rw = 0, rh = 0;
    FSRDGameTraceSession::SrMode srMode = FSRDGameTraceSession::SrMode::Off;
    std::string srContext; std::array<uint32_t,2> srExtent {}; uint32_t srFormat = 0;
    bool initialized = false, initializing = false, closing = false;
    uint64_t diskAvailable = 0, maximumPayload = MaximumPayloadBytes, cpuBytes = 0;
    uint32_t lineageLimit = FSRDGameTraceSession::FrameCount-1;
    bool claimed = false, stop = false;
    std::string reason, context, settingsHash;
    std::string mappingHash;
    std::array<std::array<uint32_t,2>,10> resourceExtents {};
    uint64_t lastEvaluation = 0, startTick = 0;
    uint32_t lastFrameIndex = 0;
    bool bound = false;
    uint64_t payloadReserved = 0, payloadWritten = 0;
    Json manifest;
};
std::string PathString(const std::filesystem::path& p)
{ const auto text = p.u8string(); return {text.begin(), text.end()}; }
Json ManifestSnapshot(Session& s)
{
    s.manifest["phase"] = s.status.phase;
    s.manifest["complete"] = s.status.phase == "complete";
    s.manifest["recorded_frames"] = s.status.recorded;
    s.manifest["committed_frames"] = s.status.captured;
    s.manifest["pending_gpu_frames"] = s.status.pending;
    s.manifest["private_staged_frames_count"] = s.status.staged;
    s.manifest["awaiting_verified_detach_frames"] = s.status.awaitingDetach;
    s.manifest["payload_reserved_bytes"] = s.payloadReserved;
    s.manifest["payload_written_bytes"] = s.payloadWritten;
    s.manifest["cpu_queued_bytes"] = s.cpuBytes;
    s.manifest["retained_readback_bytes"] = s.status.retainedReadbackBytes;
    s.manifest["estimated_payload_bytes"] = s.status.estimatedPayloadBytes;
    s.manifest["maximum_payload_bytes"] = s.maximumPayload;
    s.manifest["incomplete_reason"] = s.reason.empty() ? Json(nullptr) : Json(s.reason);
    s.manifest["cancel_requested"] = s.stop;
    return s.manifest;
}
void WriteManifest(const std::filesystem::path& folder, const Json& manifest)
{
    const auto temporary = folder / "capture.json.tmp";
    RRTraceAdditiveIO::WriteText(temporary, manifest.dump(2) + "\n");
    if (!MoveFileExW(temporary.c_str(), (folder / "capture.json").c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        throw std::runtime_error("GAME_TRACE manifest publication failed");
}
void Stop(Session& s, const std::string& reason)
{
    s.stop = true;
    if (s.reason.empty()) { s.reason = reason; s.manifest["errors"].push_back(reason); }
    s.status.phase = "draining";
    s.status.message = reason + "; draining completed recorded frames.";
}
struct Image
{
    ComPtr<ID3D12Resource> readback;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {};
    uint32_t sourceWidth = 0, sourceHeight = 0, bpp = 0;
    uint32_t width = FSRDGameTraceSession::TileSize, height = FSRDGameTraceSession::TileSize;
    uint32_t readbackCropX = 0, readbackCropY = 0;
    uint32_t cropX = 0, cropY = 0, format = 0, channels = 4;
};
struct Diagnostic
{
    Image image;
    Json metadata;
};
struct Frame
{
    std::shared_ptr<RRTraceFence::Ticket> ticket;
    ID3D12GraphicsCommandList* list = nullptr;
    std::array<Image, 10> images;
    std::array<Diagnostic,DiagnosticNames.size()> diagnostics;
    Image srImage; Json srMetadata; std::weak_ptr<Session> owner;
    uint64_t gpuBytes = 0; bool frozen = false, discarded = false, currentCopied = false;
    std::string settingsHash;
    std::vector<uint8_t> constants;
    std::vector<uint8_t> floorSeedConstants, floorFilterConstants;
    FSRDGameTraceSession::FrameInfo info;
    Json controls, settings;
    uint32_t ordinal = 0;
    uint64_t qpc = 0;
    bool started = false, native = false, sealed = false;
    Frame()
    {
        for (size_t i=0; i<diagnostics.size(); ++i)
            diagnostics[i].metadata = {{"name", DiagnosticNames[i]}, {"available", false},
                {"reason", "Diagnostic source not supplied"},
                {"bound", false}, {"active", false}, {"selected_by_flags",false}, {"inactive_reason","Diagnostic source not supplied"},
                {"conversion_flags", 0}, {"control", Json::object()},
                {"role", i<4 ? "original_caller_input" : (i<6 ? "sdk_output_lobe" : "converter_source_diagnostic")},
                {"stage", i<4 ? "pre_sdk_conversion" : (i<6 ? "post_sdk_pre_sr_capture" : "post_conversion_pre_sdk")}};
    }
    ~Frame()
    {
        if (!ticket) return;
        if (!started) ticket->CancelUnrecorded();
        ticket->Abandon();
        RRTraceFence::Forget(ticket);
    }
};
struct Control
{
    std::mutex mutex;
    std::condition_variable wake;
    std::shared_ptr<Session> current;
    // Frames retain actual readback allocations until real Reset/release proof.
    // This ledger survives owners and includes immutable-but-undetached frames.
    std::vector<std::shared_ptr<Frame>> retained;
    uint64_t gpuBytes = 0;
    uint64_t cpuBytes = 0;
};
Control& Global() { static auto* value = new Control; return *value; }
void ReapReadbacks(Control& control)
{
    std::erase_if(control.retained, [&](const auto& f) {
        if (f.use_count() != 1 || (!f->frozen && !f->discarded) || !f->ticket->Releasable()) return false;
        control.gpuBytes -= f->gpuBytes;
        return true;
    });
}
void AllocateReadback(ID3D12Device* device, Frame& frame, Image& image, uint64_t bytes)
{
    auto& control = Global(); // Caller owns control.mutex; never called by the snapshot callback.
    if (!bytes || bytes > MaximumFrameReadbackBytes-frame.gpuBytes || bytes > MaximumReadbackBytes-control.gpuBytes)
        throw std::runtime_error("GAME_TRACE retained readback memory budget exhausted");
    D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_READBACK;
    D3D12_RESOURCE_DESC buffer {}; buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    buffer.Width = bytes; buffer.Height = 1; buffer.DepthOrArraySize = buffer.MipLevels = 1;
    buffer.SampleDesc.Count = 1; buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    if (FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&buffer,
        D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&image.readback))))
        throw std::runtime_error("GAME_TRACE readback allocation failed");
    frame.gpuBytes += bytes; control.gpuBytes += bytes;
}
std::pair<uint32_t,uint32_t> DiagnosticFormat(DXGI_FORMAT format)
{
    switch (uint32_t(format))
    {
    case 2: return {16,4}; case 6: return {12,3};
    case 10: case 11: return {8,4}; case 16: return {8,2};
    case 24: case 28: case 87: return {4,4}; case 26: return {4,3};
    case 34: case 35: return {4,2}; case 39: case 40: case 41: return {4,1};
    case 44: case 45: case 46: return {4,1}; // Original depth plane0; stencil is not a converter input.
    case 54: case 56: return {2,1}; case 61: return {1,1};
    default: return {0,0};
    }
}
void CopyDiagnostics(ID3D12Device* device, ID3D12GraphicsCommandList* cmd, Frame& frame, Session& session,
    std::span<const FSRDGameTraceSession::DiagnosticSource> sources, size_t first, size_t end)
{
    for (size_t slot=first; slot<end; ++slot)
    {
        if (first == 0 && (slot == 4 || slot == 5)) continue; // SDK outputs belong to RecordNative.
        auto& diagnostic = frame.diagnostics[slot];
        const FSRDGameTraceSession::DiagnosticSource* source = nullptr;
        unsigned matches = 0;
        for (const auto& candidate : sources) if (candidate.name == DiagnosticNames[slot]) { source = &candidate; ++matches; }
        if (!matches) continue;
        try
        {
            if (matches != 1) throw std::runtime_error("Duplicate diagnostic name");
            diagnostic.metadata["bound"] = source->image.resource != nullptr;
            diagnostic.metadata["active"] = source->active;
            if (!source->active) diagnostic.metadata["inactive_reason"] = source->inactiveReason.empty()
                ? "Supplied diagnostic binding inactive." : source->inactiveReason;
            else diagnostic.metadata.erase("inactive_reason");
            diagnostic.metadata["source_state"] = uint32_t(source->image.state);
            const auto metadata = Json::parse(source->metadataJson);
            if (!metadata.is_object()) throw std::runtime_error("Diagnostic binding metadata is not an object");
            diagnostic.metadata.update(metadata);
            if (!metadata.contains("selected_by_flags")) diagnostic.metadata["selected_by_flags"] = source->active;
            diagnostic.metadata["source_base"] = {source->baseX,source->baseY};
            if (!source->active)
            {
                // Binding does not prove a readable state. The normal pipeline
                // need not transition unused title/inspector resources at all.
                diagnostic.metadata["available"] = false;
                diagnostic.metadata["reason"] = diagnostic.metadata["inactive_reason"];
                continue;
            }
            if (!source->image.resource) throw std::runtime_error("Diagnostic resource unavailable");
            auto desc = source->image.resource->GetDesc();
            const auto [bpp,channels] = DiagnosticFormat(desc.Format);
            uint64_t x = uint64_t(session.x)+source->baseX, y = uint64_t(session.y)+source->baseY;
            uint32_t width = session.size, height = session.size;
            if (source->motionAddressed)
            {
                if (!std::isfinite(source->motionWidth) || !std::isfinite(source->motionHeight) ||
                    !std::isfinite(source->jitterX) || !std::isfinite(source->jitterY) ||
                    source->motionWidth < 1 || source->motionHeight < 1 ||
                    source->motionWidth > INT_MAX || source->motionHeight > INT_MAX ||
                    std::floor(source->motionWidth) != source->motionWidth || std::floor(source->motionHeight) != source->motionHeight)
                    throw std::runtime_error("Invalid original motion addressing controls");
                auto bounds = [&](uint32_t origin, uint32_t render, float extent, float jitter)
                {
                    const int64_t maximum = int64_t(extent)-1;
                    if (!source->displayResolutionMotion)
                        return std::pair<int64_t,int64_t>{std::clamp<int64_t>(origin,0,maximum),
                            std::clamp<int64_t>(int64_t(origin)+session.size-1,0,maximum)};
                    // Conservative one-texel halo contains the shader's binary32
                    // floor addressing, without replacing/resampling its words.
                    const double low = std::floor(((double(origin)+0.5-double(jitter))/render)*extent)-1;
                    const double high = std::floor(((double(origin)+session.size-0.5-double(jitter))/render)*extent)+1;
                    return std::pair<int64_t,int64_t>{int64_t(std::clamp(low,0.0,double(maximum))),
                        int64_t(std::clamp(high,0.0,double(maximum)))};
                };
                const auto bx = bounds(session.x,session.rw,source->motionWidth,source->jitterX);
                const auto by = bounds(session.y,session.rh,source->motionHeight,source->jitterY);
                x = uint64_t(source->baseX)+bx.first; y = uint64_t(source->baseY)+by.first;
                width = uint32_t(bx.second-bx.first+1); height = uint32_t(by.second-by.first+1);
                diagnostic.metadata["mapping"]["render_roi_origin"] = {session.x,session.y};
            }
            if (!bpp) throw std::runtime_error("Unsupported original diagnostic DXGI format");
            if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.DepthOrArraySize != 1 ||
                desc.SampleDesc.Count != 1 || desc.Width > UINT_MAX || x+width > desc.Width || y+height > desc.Height)
                throw std::runtime_error("Diagnostic source extent/base does not contain the ROI");
            auto& image = diagnostic.image;
            image.sourceWidth = uint32_t(desc.Width); image.sourceHeight = desc.Height; image.bpp = bpp;
            image.width = width; image.height = height; image.cropX = uint32_t(x); image.cropY = uint32_t(y);
            image.format = uint32_t(desc.Format); image.channels = channels;
            uint64_t frameBytes = frame.constants.size()+frame.floorSeedConstants.size()+frame.floorFilterConstants.size();
            for (const auto& captured : frame.images)
                if (captured.readback) frameBytes += uint64_t(captured.width)*captured.height*captured.bpp;
            for (const auto& captured : frame.diagnostics)
                if (captured.metadata["available"].get<bool>())
                    frameBytes += uint64_t(captured.image.width)*captured.image.height*captured.image.bpp;
            const uint64_t requestedBytes = uint64_t(width)*height*bpp;
            if (frameBytes > session.maximumPayload-session.payloadReserved ||
                requestedBytes > session.maximumPayload-session.payloadReserved-frameBytes)
                throw std::runtime_error("GAME_TRACE diagnostic exceeds total payload quota");
            diagnostic.metadata.update({{"dxgi_format", uint32_t(desc.Format)}, {"source_extent", {desc.Width,desc.Height}},
                {"extent", {width,height}}, {"source_subresource", 0}, {"source_plane", 0},
                {"source_base", {source->baseX,source->baseY}}, {"crop_origin", {x,y}},
                {"bytes_per_pixel", bpp}, {"channels", channels}, {"storage", "original_little_endian_gpu_words"}});
            const bool wholeDepthPlane = (desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL) != 0 ||
                desc.Format == DXGI_FORMAT_D32_FLOAT || desc.Format == DXGI_FORMAT_D24_UNORM_S8_UINT;
            if (wholeDepthPlane)
            {
                // D3D12 forbids a boxed partial depth-stencil copy. Read the
                // whole plane, then crop original words only after fence/detach.
                image.readbackCropX = uint32_t(x); image.readbackCropY = uint32_t(y);
                diagnostic.metadata["copy_scope"] = "whole_depth_plane_then_cpu_word_crop";
            }
            else { desc.Width = width; desc.Height = height; desc.MipLevels = 1; }
            UINT64 bytes = 0;
            device->GetCopyableFootprints(&desc,0,1,0,&image.footprint,nullptr,nullptr,&bytes);
            diagnostic.metadata["copy_format"] = uint32_t(image.footprint.Footprint.Format);
            AllocateReadback(device,frame,image,bytes);
            frame.ticket->Retain(source->image.resource); frame.ticket->Retain(image.readback.Get());
            D3D12_RESOURCE_BARRIER barrier {}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barrier.Transition = {source->image.resource,0,source->image.state,D3D12_RESOURCE_STATE_COPY_SOURCE};
            const bool transition = source->image.state != D3D12_RESOURCE_STATE_COPY_SOURCE;
            frame.started = true;
            if (transition) cmd->ResourceBarrier(1,&barrier);
            D3D12_TEXTURE_COPY_LOCATION src {},dst {};
            src.pResource = source->image.resource; src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            dst.pResource = image.readback.Get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint = image.footprint;
            D3D12_BOX box {UINT(x),UINT(y),0,UINT(x+width),UINT(y+height),1};
            cmd->CopyTextureRegion(&dst,0,0,0,&src,wholeDepthPlane ? nullptr : &box);
            if (transition) { std::swap(barrier.Transition.StateBefore,barrier.Transition.StateAfter); cmd->ResourceBarrier(1,&barrier); }
            diagnostic.metadata["available"] = true; diagnostic.metadata.erase("reason");
        }
        catch (const std::exception& e)
        {
            diagnostic.metadata["available"] = false; diagnostic.metadata["reason"] = e.what();
            if (source && source->required && source->active)
                throw std::runtime_error(std::string("Required game-trace diagnostic ")+DiagnosticNames[slot]+": "+e.what());
            if (std::string_view(e.what()).find("payload quota") != std::string_view::npos) throw;
        }
    }
}
Json ProofMetadata(const RRTraceFence::Snapshot& snapshot, bool immutable = false)
{
    const auto& state = snapshot.state;
    return {{"identity_address_process_local", snapshot.identity}, {"ticket_generation", snapshot.generation},
        {"queue_address_process_local", snapshot.queue}, {"recorded", state.recorded}, {"submitted", state.submitted},
        {"detached", state.detached}, {"invalid", state.invalid}, {"abandoned", state.abandoned},
        {"signal_failed", state.signalFailed}, {"ambiguous_submission", state.ambiguousSubmission},
        {"pending_signals", state.pendingSignals}, {"fence_expected", state.expected}, {"fence_completed", snapshot.completed},
        {"signal_hresult", int64_t(snapshot.signalResult)},
        {"detach_kind",state.detached ? "successful_command_list_reset" : "not_observed"},
        {"waitable", state.CanWait() && SUCCEEDED(snapshot.signalResult) && snapshot.completed != UINT64_MAX},
        {"cpu_snapshot_immutable",immutable}, {"submission_gate_protected",immutable}};
}
Json TicketMetadata(const std::shared_ptr<RRTraceFence::Ticket>& ticket)
{ return ProofMetadata(RRTraceFence::Inspect(ticket)); }
void CopyImage(ID3D12Device* device, ID3D12GraphicsCommandList* cmd, Frame& frame,
               Session& session, FSRDGameTraceSession::Source source, size_t slot)
{
    if (!device || !cmd || !source.resource) throw std::runtime_error("GAME_TRACE missing resource");
    auto desc = source.resource->GetDesc();
    if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.Format != Formats[slot] ||
        desc.DepthOrArraySize != 1 || desc.SampleDesc.Count != 1 || desc.Width > UINT_MAX ||
        uint64_t(session.x) + session.size > desc.Width ||
        uint64_t(session.y) + session.size > desc.Height ||
        desc.Width < session.rw || desc.Height < session.rh)
        throw std::runtime_error(std::string("GAME_TRACE incompatible resource: ") + Names[slot]);
    const std::array<uint32_t,2> actualExtent {uint32_t(desc.Width), desc.Height};
    if (session.resourceExtents[slot][0] && session.resourceExtents[slot] != actualExtent)
        throw std::runtime_error(std::string("GAME_TRACE resource extent changed: ") + Names[slot]);
    session.resourceExtents[slot] = actualExtent;
    auto& image = frame.images[slot];
    if (image.readback) throw std::runtime_error("GAME_TRACE duplicate snapshot stage");
    image.sourceWidth = uint32_t(desc.Width); image.sourceHeight = desc.Height;
    image.bpp = desc.Format == DXGI_FORMAT_R16G16B16A16_FLOAT ? 8 : 4;
    image.width = image.height = session.size; image.cropX = session.x; image.cropY = session.y;
    image.format = uint32_t(desc.Format); image.channels = slot == FSRDGameTraceSession::Depth ? 1 : 4;
    desc.Width = desc.Height = session.size;
    desc.DepthOrArraySize = desc.MipLevels = 1;
    UINT64 bytes = 0;
    device->GetCopyableFootprints(&desc, 0, 1, 0, &image.footprint, nullptr, nullptr, &bytes);
    AllocateReadback(device,frame,image,bytes);
    // Retain before recording any GPU use. Abort never frees an executable list's storage.
    frame.ticket->Retain(source.resource); frame.ticket->Retain(image.readback.Get());
    D3D12_RESOURCE_BARRIER barrier {}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition = {source.resource, 0, source.state, D3D12_RESOURCE_STATE_COPY_SOURCE};
    const bool transition = source.state != D3D12_RESOURCE_STATE_COPY_SOURCE;
    frame.started = true;
    if (transition) cmd->ResourceBarrier(1, &barrier);
    D3D12_TEXTURE_COPY_LOCATION src {}, dst {};
    src.pResource = source.resource; src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX; src.SubresourceIndex = 0;
    dst.pResource = image.readback.Get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint = image.footprint;
    D3D12_BOX box {session.x, session.y, 0, session.x + session.size,
                  session.y + session.size, 1};
    cmd->CopyTextureRegion(&dst, 0, 0, 0, &src, &box);
    if (transition) { std::swap(barrier.Transition.StateBefore, barrier.Transition.StateAfter); cmd->ResourceBarrier(1, &barrier); }
}
void RequireUnsubmitted(Frame& f)
{
    std::scoped_lock lock(f.ticket->mutex);
    if (f.ticket->state.submitted || f.ticket->state.invalid)
        throw std::runtime_error("GAME_TRACE list submitted/discarded before frame was sealed");
}
}

namespace
{
const char* SrModeName(FSRDGameTraceSession::SrMode mode)
{
    switch (mode)
    {
    case FSRDGameTraceSession::SrMode::Off: return "off";
    case FSRDGameTraceSession::SrMode::MappedRoi: return "mapped_render_roi";
    case FSRDGameTraceSession::SrMode::FullOutput: return "full_logical_output";
    default: throw std::runtime_error("Invalid GAME_TRACE SR mode");
    }
}
uint64_t FramePayload(const Frame& f)
{
    uint64_t bytes = f.constants.size()+f.floorSeedConstants.size()+f.floorFilterConstants.size();
    for (const auto& image : f.images) if (image.readback) bytes += uint64_t(image.width)*image.height*image.bpp;
    for (const auto& diagnostic : f.diagnostics)
        if (diagnostic.image.readback && diagnostic.metadata.value("available",false))
            bytes += uint64_t(diagnostic.image.width)*diagnostic.image.height*diagnostic.image.bpp;
    if (f.srImage.readback) bytes += uint64_t(f.srImage.width)*f.srImage.height*f.srImage.bpp;
    return bytes;
}
void CopySr(ID3D12Device* device, ID3D12GraphicsCommandList* cmd, Frame& f, Session& s,
    FSRDGameTraceSession::Source source, const FSRDGameTraceSession::SrInfo& info)
{
    if (!source.resource || !info.width || !info.height || info.contextId.empty() || info.evaluationId != f.info.evaluationId)
        throw std::runtime_error("GAME_TRACE SR output lacks the same successful evaluation");
    auto desc = source.resource->GetDesc();
    const auto [bpp,channels] = DiagnosticFormat(desc.Format);
    if (!bpp || channels < 3 || desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
        desc.DepthOrArraySize != 1 || desc.SampleDesc.Count != 1 || desc.Width > UINT_MAX ||
        desc.Width < info.width || desc.Height < info.height || (desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL))
        throw std::runtime_error("GAME_TRACE unsupported SR color format or logical extent");
    const std::array<uint32_t,2> logical {info.width,info.height};
    if (!s.srContext.empty() && (s.srContext != info.contextId || s.srExtent != logical || s.srFormat != uint32_t(desc.Format)))
        throw std::runtime_error("GAME_TRACE SR context, format or logical extent changed");
    auto controls = Json::parse(info.controlsJson);
    for (const auto* key : {"jitter","motion_vector_scale","render_size","upscale_size"})
    {
        if (!controls.contains(key) || !controls[key].is_array() || controls[key].size() != 2)
            throw std::runtime_error("GAME_TRACE missing actual SR vector control");
        for (const auto& value : controls[key]) if (!value.is_number() || !std::isfinite(value.get<double>()))
            throw std::runtime_error("GAME_TRACE nonfinite actual SR vector control");
    }
    for (const auto* key : {"frame_time_delta","pre_exposure","camera_near","camera_far","camera_fov_vertical","view_space_to_meters","sharpness"})
        if (!controls.contains(key) || !controls[key].is_number() || !std::isfinite(controls[key].get<double>()))
            throw std::runtime_error("GAME_TRACE missing/nonfinite actual SR scalar control");
    if (!controls.contains("flags") || !controls["flags"].is_number_unsigned() ||
        !controls.contains("create_flags") || !controls["create_flags"].is_number_unsigned() ||
        !controls.contains("enable_sharpening") || !controls["enable_sharpening"].is_boolean() ||
        controls.value("reset",!info.reset) != info.reset ||
        controls["render_size"] != Json::array({s.rw,s.rh}) || controls["upscale_size"] != Json::array({info.width,info.height}))
        throw std::runtime_error("GAME_TRACE actual SR controls disagree with dispatch extent/reset");
    auto& image = f.srImage;
    if (image.readback) throw std::runtime_error("GAME_TRACE duplicate SR snapshot");
    image.sourceWidth = uint32_t(desc.Width); image.sourceHeight = desc.Height;
    image.format = uint32_t(desc.Format); image.bpp = bpp; image.channels = channels;
    image.width = info.width; image.height = info.height;
    if (s.srMode == FSRDGameTraceSession::SrMode::MappedRoi)
    {
        image.cropX = uint32_t(uint64_t(s.x)*info.width/s.rw);
        image.cropY = uint32_t(uint64_t(s.y)*info.height/s.rh);
        const uint32_t right = uint32_t((uint64_t(s.x+s.size)*info.width+s.rw-1)/s.rw);
        const uint32_t bottom = uint32_t((uint64_t(s.y+s.size)*info.height+s.rh-1)/s.rh);
        image.width = right-image.cropX; image.height = bottom-image.cropY;
    }
    desc.Width = image.width; desc.Height = image.height; desc.MipLevels = 1;
    UINT64 bytes = 0; device->GetCopyableFootprints(&desc,0,1,0,&image.footprint,nullptr,nullptr,&bytes);
    AllocateReadback(device,f,image,bytes);
    f.ticket->Retain(source.resource); f.ticket->Retain(image.readback.Get());
    D3D12_RESOURCE_BARRIER barrier {}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition = {source.resource,0,source.state,D3D12_RESOURCE_STATE_COPY_SOURCE};
    const bool transition = source.state != D3D12_RESOURCE_STATE_COPY_SOURCE;
    f.started = true;
    if (transition) cmd->ResourceBarrier(1,&barrier);
    D3D12_TEXTURE_COPY_LOCATION src {},dst {};
    src.pResource = source.resource; src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    dst.pResource = image.readback.Get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint = image.footprint;
    D3D12_BOX box {image.cropX,image.cropY,0,image.cropX+image.width,image.cropY+image.height,1};
    cmd->CopyTextureRegion(&dst,0,0,0,&src,&box);
    if (transition) { std::swap(barrier.Transition.StateBefore,barrier.Transition.StateAfter); cmd->ResourceBarrier(1,&barrier); }
    f.srMetadata = {{"available",true},{"mode",SrModeName(s.srMode)},
        {"stage","after_sr_before_rcas_output_scaling_overlay"},{"evaluation_id",info.evaluationId},
        {"context_id",info.contextId},{"context_identity_kind","actual_process_local_provider_and_owner"},
        {"logical_extent",logical},{"reset",info.reset},{"dispatch_controls",std::move(controls)}};
    s.srContext = info.contextId; s.srExtent = logical; s.srFormat = image.format;
}
struct CpuPayload
{
    std::string filename;
    std::vector<uint8_t> bytes;
    // image or diagnostic slot, or -1 for post_sr, -2/-3/-4 for constants.
    int kind = 0; size_t slot = 0;
};
struct CpuFrame
{
    std::shared_ptr<Session> session;
    uint32_t ordinal = 0;
    uint64_t bytes = 0;
    Json row;
    std::vector<CpuPayload> payloads;
};
Json ImageMetadata(const Image& image, const char* name)
{
    return {{"name",name},{"dxgi_format",image.format},{"source_extent",{image.sourceWidth,image.sourceHeight}},
        {"extent",{image.width,image.height}},{"crop_origin",{image.cropX,image.cropY}},
        {"channels",image.channels},{"bytes_per_pixel",image.bpp},{"storage","original_little_endian_gpu_words"}};
}
// This function is called ONLY under WithCompletedSnapshot. Storage was sized
// beforehand. It neither allocates nor hashes/writes/inspects another ticket.
bool CopyCpuWords(const Image& image, std::vector<uint8_t>& bytes) noexcept
{
    const SIZE_T rowBytes = SIZE_T(image.width)*image.bpp;
    const SIZE_T cropOffset = SIZE_T(image.readbackCropX)*image.bpp;
    const SIZE_T extent = image.footprint.Offset+SIZE_T(image.footprint.Footprint.RowPitch)*
        (image.readbackCropY+image.height-1)+cropOffset+rowBytes;
    D3D12_RANGE read {0,extent}; void* mapped = nullptr;
    if (FAILED(image.readback->Map(0,&read,&mapped))) return false;
    for (uint32_t y=0; y<image.height; ++y)
        memcpy(bytes.data()+SIZE_T(y)*rowBytes,static_cast<uint8_t*>(mapped)+image.footprint.Offset+
            SIZE_T(image.readbackCropY+y)*image.footprint.Footprint.RowPitch+cropOffset,rowBytes);
    D3D12_RANGE written {0,0}; image.readback->Unmap(0,&written);
    return true;
}
}

struct FSRDGameTraceSession::Impl
{
    std::shared_ptr<Session> session;
    std::deque<std::shared_ptr<Frame>> pending;
    std::deque<std::shared_ptr<CpuFrame>> cpuQueue;
    std::map<uint32_t,Json> staged;
    std::shared_ptr<Frame> current;
    ComPtr<ID3D12Device> device;
    std::thread snapshotWorker, diskWorker;
    bool shutdown = false, diskBusy = false;

    Impl()
    {
        snapshotWorker = std::thread([this] { SnapshotLoop(); });
        try { diskWorker = std::thread([this] { DiskLoop(); }); }
        catch (...) { { std::scoped_lock lock(Global().mutex); shutdown = true; } Global().wake.notify_all(); snapshotWorker.join(); throw; }
    }
    ~Impl()
    {
        { std::scoped_lock lock(Global().mutex); shutdown = true; }
        Global().wake.notify_all();
        if (snapshotWorker.joinable()) snapshotWorker.join();
        if (diskWorker.joinable()) diskWorker.join();
    }
    void UpdateProgress()
    {
        if (!session) return;
        auto& s = *session;
        s.status.pending = uint32_t(pending.size()); s.status.staged = uint32_t(staged.size());
        s.status.cpuQueuedBytes = s.cpuBytes; s.status.retainedReadbackBytes = Global().gpuBytes;
        s.status.awaitingDetach = 0;
        for (const auto& f : Global().retained)
            if (f->owner.lock() == session && f->sealed && !RRTraceFence::Inspect(f->ticket).state.detached)
                ++s.status.awaitingDetach;
        s.manifest["private_staged_frames"] = Json::array();
        for (const auto& [ordinal,row] : staged)
            s.manifest["private_staged_frames"].push_back({{"ordinal",ordinal},
                {"private_folder","frames/"+std::to_string(ordinal)+".pending"},{"frame",row}});
        if (s.status.active && !s.closing)
        {
            s.status.message = "Published "+std::to_string(s.status.captured)+"/128; recorded "+
                std::to_string(s.status.recorded)+"; GPU pending "+std::to_string(s.status.pending)+
                "; CPU queue "+std::to_string(s.cpuBytes>>20)+" MiB; retained readbacks "+
                std::to_string(Global().gpuBytes>>20)+" MiB.";
            if (!s.reason.empty()) s.status.message = s.reason+"; finalizing immutable frames. "+s.status.message;
        }
    }
    void SavePendingDiagnostics()
    {
        if (!session) return;
#if defined(FSRD_GAME_TRACE_TEST)
        if (g_testFailPendingDiagnosticsAllocation.exchange(false,std::memory_order_relaxed)) throw std::bad_alloc();
#endif
        Json rows = Json::array();
        for (const auto& f : pending)
            rows.push_back({{"ordinal",f->ordinal},{"evaluation_id",f->native ? Json(f->info.evaluationId) : Json(nullptr)},
                {"native_recorded",f->native},{"sealed",f->sealed},{"recording_qpc",f->qpc},{"ticket",TicketMetadata(f->ticket)}});
        session->manifest["uncommitted_frames_at_close"] = std::move(rows);
    }
    void Failure(const std::string& reason) noexcept
    {
        if (!session || !session->status.active || session->closing) return;
        try
        {
            SavePendingDiagnostics(); Stop(*session,reason);
        }
        catch (...)
        {
            session->stop = true;
            try { if (session->reason.empty()) session->reason = reason; session->status.phase = "draining"; }
            catch (...) {}
        }
        // Allocation failures in diagnostics must not strand executable frames
        // in the ledger. Release still requires the ticket's real Reset proof.
        for (auto& f : pending)
        {
            f->discarded = true;
            try { if (!f->started) f->ticket->CancelUnrecorded(); else f->ticket->Invalidate(); }
            catch (...) {}
        }
        current.reset(); pending.clear();
        try { UpdateProgress(); } catch (...) {}
        Global().wake.notify_all();
    }
    void InspectLineage()
    {
        if (!session || !session->status.active || session->closing) return;
        for (const auto& f : Global().retained)
        {
            if (f->owner.lock() != session || f->discarded) continue;
            if (f->ticket->Invalid())
            {
                // Earlier frozen words remain valid. Native history after a
                // repeated execution cannot be represented as consecutive RR.
                if (f->frozen) session->lineageLimit = std::min(session->lineageLimit,f->ordinal);
                else session->lineageLimit = f->ordinal ? std::min(session->lineageLimit,f->ordinal-1) : 0;
                Failure("Submission, Reset, repeated submission or device failure invalidated capture lineage");
                return;
            }
        }
    }
    void Seal(Frame& f)
    {
        auto& s = *session;
        for (const auto& image : f.images) if (!image.readback) throw std::runtime_error("GAME_TRACE missing pre-SR snapshot");
        for (const auto& d : f.diagnostics)
            if (d.metadata.value("active",false) && !d.metadata.value("available",false))
                throw std::runtime_error("GAME_TRACE active diagnostic unavailable: "+d.metadata["name"].get<std::string>());
        const uint64_t payload = FramePayload(f);
        if (!s.status.estimatedPayloadBytes)
        {
            s.status.estimatedPayloadBytes = payload*FrameCount;
            const uint64_t required = s.status.estimatedPayloadBytes+
                (s.maximumPayload == MaximumPayloadBytes ? (64ull<<20) : (256ull<<20));
            if (required > s.diskAvailable) throw std::runtime_error("GAME_TRACE destination has insufficient space for estimated 128-frame payload");
            if (s.maximumPayload != MaximumPayloadBytes)
                s.maximumPayload = std::min(MaximumExtendedPayloadBytes,s.status.estimatedPayloadBytes+s.status.estimatedPayloadBytes/20+(1ull<<20));
            if (s.status.estimatedPayloadBytes > s.maximumPayload) throw std::runtime_error("GAME_TRACE estimated sequence exceeds payload quota");
        }
        if (payload > s.maximumPayload-s.payloadReserved) throw std::runtime_error("GAME_TRACE total payload quota exceeded");
        { std::scoped_lock lock(f.ticket->mutex);
          if (f.ticket->state.submitted || f.ticket->state.invalid) throw std::runtime_error("GAME_TRACE frame submitted before sealing");
          f.ticket->state.recorded = true; }
        s.payloadReserved += payload; f.sealed = true; ++s.status.recorded;
        if (s.status.recorded == FrameCount) s.status.phase = "draining";
        UpdateProgress(); Global().wake.notify_all();
    }
    std::shared_ptr<CpuFrame> Freeze(const std::shared_ptr<Frame>& f, const std::shared_ptr<Session>& s)
    {
#if defined(FSRD_GAME_TRACE_TEST)
        while (g_testHoldCpuFreeze.load(std::memory_order_acquire)) g_testHoldCpuFreeze.wait(true);
#endif
        auto packet = std::make_shared<CpuFrame>(); packet->session = s; packet->ordinal = f->ordinal; packet->bytes = FramePayload(*f);
        std::vector<const Image*> images;
        auto addImage = [&](const Image& image, std::string filename, int kind, size_t slot) {
            packet->payloads.push_back({std::move(filename),std::vector<uint8_t>(size_t(image.width)*image.height*image.bpp),kind,slot});
            images.push_back(&image);
        };
        packet->payloads.reserve(33); images.reserve(30);
        for (size_t slot=0; slot<f->images.size(); ++slot) addImage(f->images[slot],std::string(Names[slot])+".bin",0,slot);
        for (size_t slot=0; slot<f->diagnostics.size(); ++slot)
            if (f->diagnostics[slot].metadata.value("available",false)) addImage(f->diagnostics[slot].image,std::string(DiagnosticNames[slot])+".bin",1,slot);
        if (f->srImage.readback) addImage(f->srImage,"post_sr.bin",-1,0);
        // Constants are CPU data already copied from this evaluation.
        packet->payloads.push_back({"conversion_constants.bin",f->constants,-2,0});
        if (!f->floorSeedConstants.empty()) packet->payloads.push_back({"floor_seed_constants.bin",f->floorSeedConstants,-3,0});
        if (!f->floorFilterConstants.empty()) packet->payloads.push_back({"floor_filter_constants.bin",f->floorFilterConstants,-4,0});
        RRTraceFence::Snapshot proof {}; bool copied = true;
        const bool protectedCopy = RRTraceFence::WithCompletedSnapshot(f->ticket,[&](const RRTraceFence::Snapshot& exactProof) {
            proof = exactProof;
            for (size_t i=0; i<images.size(); ++i) if (!CopyCpuWords(*images[i],packet->payloads[i].bytes)) { copied = false; break; }
        });
        if (!protectedCopy) return {};
        if (!copied) throw std::runtime_error("GAME_TRACE protected readback Map failed");
        auto& row = packet->row;
        row = {{"ordinal",f->ordinal},{"context_id",f->info.contextId},{"evaluation_id",f->info.evaluationId},
            {"native_frame_index",f->info.frameIndex},{"dispatch_flags",f->info.dispatchFlags},{"reset",f->info.reset},
            {"recording_qpc",f->qpc},{"controls",f->controls},{"settings",f->settings},{"native_full1",false},
            {"output_scope","actual_configured_composition_before_sr"},
            {"native_full1_filename_role","legacy_replay_alias_of_actual_configured_pre_sr_output"},
            {"gpu_submission_verified",true},{"gpu_completed",true},{"command_list_detached",proof.state.detached},
            {"cpu_snapshot_immutable",true},{"submission_gate_protected",true},
            {"reference",{{"available",false},{"kind","unavailable"}}},{"images",Json::array()}};
        row["settings_canonical_json"] = f->settings.dump(); row["settings_sha256"] = f->settingsHash;
        row["ticket_proof"] = ProofMetadata(proof,true);
        row["submission"] = {{"queue_address_process_local",proof.queue},{"fence_expected",proof.state.expected},
            {"fence_completed",proof.completed},{"signal_hresult",int64_t(proof.signalResult)},
            {"pending_signals",proof.state.pendingSignals},{"ambiguous_submission",proof.state.ambiguousSubmission}};
        for (size_t slot=0; slot<f->images.size(); ++slot) row["images"].push_back(ImageMetadata(f->images[slot],Names[slot]));
        row["diagnostics"] = Json::array(); uint32_t conversionFlags = 0;
        memcpy(&conversionFlags,f->constants.data()+364,sizeof(conversionFlags));
        for (const auto& d : f->diagnostics)
        {
            auto metadata = d.metadata; metadata["evaluation_id"] = f->info.evaluationId; metadata["conversion_flags"] = conversionFlags;
            if (metadata["control"].empty() && !f->diagnostics[0].metadata["control"].empty()) metadata["control"] = f->diagnostics[0].metadata["control"];
            row["diagnostics"].push_back(std::move(metadata));
        }
        row["post_sr"] = f->srImage.readback ? f->srMetadata : Json{{"available",false},{"reason","Not requested"}};
        if (f->srImage.readback) row["post_sr"].update(ImageMetadata(f->srImage,"post_sr"));
        row["floor_seed_constants"] = {{"available",!f->floorSeedConstants.empty()},{"stage","pre_floor_seed_dispatch"},{"abi_bytes",176}};
        row["floor_filter_constants"] = {{"available",!f->floorFilterConstants.empty()},{"stage","pre_floor_filter_dispatches"},
            {"record_bytes",32},{"pass_count",f->floorFilterConstants.size()/32}};
        return packet;
    }
    void SnapshotLoop() noexcept;
    void DiskLoop() noexcept;
    void Save(const std::shared_ptr<Session>& s)
    {
        Json manifest;
        { std::scoped_lock lock(Global().mutex); if (session == s) UpdateProgress(); manifest = ManifestSnapshot(*s); }
        WriteManifest(s->folder,manifest); // Never under global/ticket/registry locks.
    }
    void WritePacket(CpuFrame& packet)
    {
        const auto relative = "frames/"+std::to_string(packet.ordinal);
        const auto partial = packet.session->folder/(relative+".pending");
        if (!std::filesystem::create_directory(partial)) throw std::runtime_error("GAME_TRACE frame folder already exists");
        for (const auto& payload : packet.payloads)
        {
            RRTraceAdditiveIO::WriteFile(partial/payload.filename,payload.bytes);
            Json* metadata = nullptr;
            if (payload.kind == 0) metadata = &packet.row["images"][payload.slot];
            else if (payload.kind == 1) metadata = &packet.row["diagnostics"][payload.slot];
            else metadata = &packet.row[payload.kind == -1 ? "post_sr" : payload.kind == -2 ? "conversion_constants" :
                payload.kind == -3 ? "floor_seed_constants" : "floor_filter_constants"];
            metadata->update({{"file",relative+"/"+payload.filename},{"bytes",payload.bytes.size()},{"sha256",RRTraceAdditiveIO::Sha256(payload.bytes)}});
        }
        RRTraceAdditiveIO::WriteText(partial/"frame.json",packet.row.dump(2)+"\n");
    }
};

void FSRDGameTraceSession::Impl::SnapshotLoop() noexcept
{
    auto& control = Global();
    for (;;)
    {
        std::shared_ptr<Frame> frame; std::shared_ptr<Session> s; uint64_t reserved = 0;
        try
        {
            {
                std::unique_lock lock(control.mutex);
                ReapReadbacks(control);
                if (shutdown) return;
                if (session && session->stop && !pending.empty()) Failure(session->reason);
                InspectLineage();
                if (session && session->status.active && session->initialized && !session->closing)
                {
                    s = session;
                    for (const auto& candidate : pending)
                    {
                        if (!candidate->sealed || candidate->discarded) continue;
                        const auto proof = RRTraceFence::Inspect(candidate->ticket);
                        if (SUCCEEDED(proof.signalResult) && proof.state.CanSnapshot(proof.completed)) { frame = candidate; break; }
                    }
                    if (frame)
                    {
                        reserved = FramePayload(*frame);
                        if (control.cpuBytes > CpuBudget() || reserved > CpuBudget()-control.cpuBytes)
                        {
                            Failure("GAME_TRACE disk backlog reached the bounded CPU memory budget; no game-thread wait performed");
                            frame.reset(); reserved = 0;
                        }
                        else { s->cpuBytes += reserved; control.cpuBytes += reserved; UpdateProgress(); }
                    }
                }
                if (!frame)
                {
                    if (session && session->status.active && (!pending.empty() || !control.retained.empty()))
                        control.wake.wait_for(lock,std::chrono::milliseconds(2));
                    else if (!control.retained.empty())
                        control.wake.wait_for(lock,std::chrono::milliseconds(200));
                    else
                        control.wake.wait(lock,[&] { return shutdown || !control.retained.empty() ||
                            (session && session->status.active && !pending.empty()); });
                    continue;
                }
            }
            // Allocate immutable CPU storage before taking the submission gate.
            auto packet = Freeze(frame,s);
            {
                std::scoped_lock lock(control.mutex);
                if (packet && session == s && s->status.active && !frame->discarded && frame->ordinal <= s->lineageLimit)
                {
                    frame->frozen = true;
                    std::erase(pending,frame);
                    if (current == frame) current.reset();
                    cpuQueue.push_back(std::move(packet));
                }
                else { s->cpuBytes -= reserved; control.cpuBytes -= reserved; }
                reserved = 0; UpdateProgress();
            }
            frame.reset(); control.wake.notify_all();
        }
        catch (const std::exception& error)
        {
            std::scoped_lock lock(control.mutex);
            if (s && reserved) { s->cpuBytes -= reserved; control.cpuBytes -= reserved; }
            Failure(error.what());
        }
        catch (...)
        {
            std::scoped_lock lock(control.mutex);
            if (s && reserved) { s->cpuBytes -= reserved; control.cpuBytes -= reserved; }
            Failure("Unknown protected CPU snapshot failure");
        }
    }
}

void FSRDGameTraceSession::Impl::DiskLoop() noexcept
{
    auto& control = Global();
    for (;;)
    {
        std::shared_ptr<Session> s; std::shared_ptr<CpuFrame> packet;
        bool initialize = false, finish = false;
        try
        {
            {
                std::unique_lock lock(control.mutex);
                if (session && session->status.active)
                {
                    s = session;
                    if (!s->initialized && !s->initializing)
                    { s->initializing = true; initialize = true; }
                    else if (s->initialized && !cpuQueue.empty())
                    {
                        packet = cpuQueue.front(); cpuQueue.pop_front(); diskBusy = true;
                        if (packet->bytes > s->maximumPayload-s->payloadWritten)
                            throw std::runtime_error("GAME_TRACE cumulative disk payload quota exceeded");
                        // Charge before I/O; partial writes are never retried/refunded.
                        s->payloadWritten += packet->bytes;
                    }
                    else if (s->initialized && !diskBusy && pending.empty() && s->cpuBytes == 0 && !s->closing &&
                        (s->stop || s->status.recorded == FrameCount))
                    {
                        s->closing = true; finish = true; UpdateProgress();
                        s->status.phase = s->status.captured == FrameCount && s->reason.empty() ? "complete" :
                            (s->reason == "Stopped by user" ? "cancelled" : "incomplete");
                        s->status.message = (s->status.phase == "complete" ? "Saved 128 immutable, submitted, GPU-completed consecutive frames. " :
                            "Saved incomplete contiguous sequence: ")+std::to_string(s->status.captured)+"/128. "+s->reason;
                        Json retained = Json::array();
                        for (const auto& f : control.retained) if (f->owner.lock() == s)
                            retained.push_back({{"ordinal",f->ordinal},{"readback_bytes",f->gpuBytes},{"cpu_snapshot_immutable",f->frozen},
                                {"ticket",TicketMetadata(f->ticket)}});
                        s->manifest["retained_gpu_tickets_at_close"] = std::move(retained);
                    }
                }
                if (!initialize && !packet && !finish)
                {
                    if (shutdown && (!session || !session->status.active)) return;
                    control.wake.wait(lock,[&] { return shutdown || (session && session->status.active &&
                        ((!session->initialized && !session->initializing) ||
                        (session->initialized && (!cpuQueue.empty() || (!diskBusy && pending.empty() && session->cpuBytes == 0 &&
                            !session->closing && (session->stop || session->status.recorded == FrameCount)))))); });
                    continue;
                }
            }
            if (initialize)
            {
                std::filesystem::create_directories(s->folder.parent_path());
                const auto available = std::filesystem::space(s->folder.parent_path()).available;
                const uint64_t minimum = s->maximumPayload == MaximumPayloadBytes ? (384ull<<20) :
                    uint64_t(s->size)*s->size*64*FrameCount+(256ull<<20);
                if (available < minimum) throw std::runtime_error("GAME_TRACE destination disk space is below the initial bounded capture estimate");
                if (!std::filesystem::create_directory(s->folder)) throw std::runtime_error("GAME_TRACE folder collision");
                std::filesystem::create_directory(s->folder/"frames");
                {
                    std::scoped_lock lock(control.mutex); s->diskAvailable = available;
                    s->initialized = true; s->initializing = false;
                    if (!s->stop) s->status.phase = GetTickCount64() < s->startTick ? "armed" : "requested";
                }
                Save(s); control.wake.notify_all();
            }
            else if (packet)
            {
#if defined(FSRD_GAME_TRACE_TEST)
                std::this_thread::sleep_for(std::chrono::milliseconds(g_testDiskDelayMs.load(std::memory_order_relaxed)));
#endif
                WritePacket(*packet);
                {
                    std::scoped_lock lock(control.mutex); staged.emplace(packet->ordinal,std::move(packet->row));
                }
                // Only this worker mutates disk names. Never expose an ordinal
                // suffix while an earlier submitted frame remains missing.
                for (;;)
                {
                    uint32_t ordinal = 0; Json row;
                    {
                        std::scoped_lock lock(control.mutex); InspectLineage();
                        const auto found = staged.find(s->status.captured);
                        if (found == staged.end() || found->first > s->lineageLimit) break;
                        ordinal = found->first; row = found->second;
                    }
                    const auto relative = "frames/"+std::to_string(ordinal);
                    std::filesystem::rename(s->folder/(relative+".pending"),s->folder/relative);
                    {
                        std::scoped_lock lock(control.mutex);
                        s->manifest["frames"].push_back(std::move(row)); ++s->status.captured; staged.erase(ordinal);
                    }
                }
                {
                    std::scoped_lock lock(control.mutex);
                    const auto bytes = packet->bytes; packet.reset();
                    s->cpuBytes -= bytes; control.cpuBytes -= bytes; diskBusy = false; UpdateProgress();
                }
                packet.reset(); Save(s); control.wake.notify_all();
            }
            else if (finish)
            {
                Save(s);
                {
                    std::scoped_lock lock(control.mutex); s->status.active = false;
                    if (control.current == s) g_captureActive.store(false,std::memory_order_release);
                }
                control.wake.notify_all();
            }
        }
        catch (const std::exception& error)
        {
            {
                std::scoped_lock lock(control.mutex);
                if (packet) { const auto bytes = packet->bytes; packet.reset(); s->cpuBytes -= bytes; control.cpuBytes -= bytes; }
                diskBusy = false; Failure(error.what());
                if (s)
                {
                    for (const auto& queued : cpuQueue) { s->cpuBytes -= queued->bytes; control.cpuBytes -= queued->bytes; }
                    cpuQueue.clear(); s->closing = true; s->status.phase = "error"; s->status.message = error.what();
                }
            }
            if (s)
            {
                try { if (std::filesystem::exists(s->folder)) Save(s); } catch (...) {}
                std::scoped_lock lock(control.mutex); s->status.active = false;
                if (control.current == s) g_captureActive.store(false,std::memory_order_release);
            }
            control.wake.notify_all();
        }
        catch (...)
        {
            std::scoped_lock lock(control.mutex); Failure("Unknown GAME_TRACE worker I/O failure");
            if (s) { s->status.active = false; s->status.phase = "error"; if (control.current == s) g_captureActive.store(false,std::memory_order_release); }
        }
    }
}

FSRDGameTraceSession::FSRDGameTraceSession() : m_impl(std::make_unique<Impl>()) {}
FSRDGameTraceSession::~FSRDGameTraceSession()
{
    Abort("Capture owner ended before completion");
    // Join CPU-only workers before DLL code/resources can be unloaded. There is
    // no GPU/future-Reset wait. Uncertain readbacks remain in the global ledger.
    m_impl.reset();
}
bool FSRDGameTraceSession::RequestStart(uint32_t x, uint32_t y, uint32_t delaySeconds) noexcept
{ Request request; request.x = x; request.y = y; request.delaySeconds = delaySeconds; return RequestStart(request); }
bool FSRDGameTraceSession::RequestStart(const Request& request) noexcept
{
    auto& control = Global(); std::scoped_lock lock(control.mutex);
    std::shared_ptr<Session> attempted;
    const auto failedStart = [&](const char* reason) noexcept {
        g_captureActive.store(false,std::memory_order_release);
        auto s = attempted ? attempted : control.current;
        if (s)
        {
            s->status.active = false; control.current = s;
            try { s->status.phase = "error"; s->status.message = reason; } catch (...) {}
        }
        return false;
    };
    try
    {
        if (control.current && control.current->status.active) return false;
        ReapReadbacks(control);
        auto s = std::make_shared<Session>(); attempted = s;
        if (request.size != TileSize && request.size != 512) throw std::runtime_error("GAME_TRACE region must be 128 or 512 pixels");
        if (request.delaySeconds > 10) throw std::runtime_error("GAME_TRACE delay must be 0-10 seconds");
        const auto mode = SrModeName(request.srMode);
        s->x = request.x; s->y = request.y; s->size = request.size; s->srMode = request.srMode;
        s->maximumPayload = request.size == TileSize && request.srMode == SrMode::Off ? MaximumPayloadBytes : MaximumExtendedPayloadBytes;
        s->startTick = GetTickCount64()+uint64_t(request.delaySeconds)*1000;
        std::array<uint8_t,16> uuid {};
        if (BCryptGenRandom(nullptr,uuid.data(),ULONG(uuid.size()),BCRYPT_USE_SYSTEM_PREFERRED_RNG) < 0)
            throw std::runtime_error("GAME_TRACE UUID allocation failed");
        uuid[6] = (uuid[6]&15)|0x40; uuid[8] = (uuid[8]&63)|0x80;
        std::ostringstream id;
        for (size_t i=0;i<uuid.size();++i) { if (i==4 || i==6 || i==8 || i==10) id << '-'; id << std::hex << std::setw(2) << std::setfill('0') << unsigned(uuid[i]); }
        s->status.captureId = id.str();
        auto root = Util::DllPath().parent_path()/"GAME_TRACE";
        if (!request.outputRoot.empty())
        {
            root = std::filesystem::u8path(request.outputRoot);
            if (!root.is_absolute() || !root.has_root_directory()) throw std::runtime_error("GAME_TRACE output root must be an absolute path");
        }
        s->folder = root.lexically_normal()/s->status.captureId; s->status.folder = PathString(s->folder);
        s->status.active = true; s->status.phase = request.delaySeconds ? "armed" : "requested";
        s->status.message = "Waiting for the normal RR owner; destination is initialized by the disk worker.";
        LARGE_INTEGER frequency {}; QueryPerformanceFrequency(&frequency);
#if defined(FSRD_GAME_TRACE_TEST)
        if (g_testFailStartManifestAllocation.exchange(false,std::memory_order_relaxed)) throw std::bad_alloc();
#endif
        s->manifest = {{"schema","fsrd-game-trace-v5"},{"capture_uuid",s->status.captureId},{"source","live_game_gpu"},
            {"process_id",GetCurrentProcessId()},{"target_frames",FrameCount},{"qpc_frequency",frequency.QuadPart},
            {"capture_backend_build",__DATE__ " " __TIME__},{"start_delay_seconds",request.delaySeconds},
            {"output_scope","actual_configured_composition_before_sr"},{"post_sr_mode",mode},
            {"native_full1_filename_role","legacy_replay_alias_of_actual_configured_pre_sr_output"},{"neutral_full1_comparator",false},
            {"roi",{{"origin",{s->x,s->y}},{"extent",{s->size,s->size}},{"space","render_pixels_fixed"}}},
            {"reference",{{"available",false},{"kind","unavailable"},{"demodulation_zero_is_clean_truth",false}}},
            {"submission_policy","same actual command-list evaluation; submitted+successful signal+fence completed; immutable CPU words frozen under submission gate; resource release still requires successful Reset; publish contiguous ordinal prefix only"},
            {"history_replay_scope","cropped RR inputs cannot reconstruct off-ROI full-screen history; optional SR is observation only"},
            {"maximum_pending_frames",MaximumPendingFrames},{"maximum_retained_readback_bytes",MaximumReadbackBytes},
            {"maximum_frame_readback_bytes",MaximumFrameReadbackBytes},{"maximum_cpu_queue_bytes",CpuBudget()},
            {"capacity_wait_maximum_ms",0},{"io_mode","bounded_cpu_snapshot_and_disk_workers"},
            {"frames",Json::array()},{"errors",Json::array()}};
        control.current = s; g_srRequested.store(request.srMode != SrMode::Off,std::memory_order_release);
        g_captureActive.store(true,std::memory_order_release); control.wake.notify_all(); return true;
    }
    catch (const std::exception& error)
    {
        return failedStart(error.what());
    }
    catch (...) { return failedStart("Unknown GAME_TRACE startup failure"); }
}
void FSRDGameTraceSession::RequestStop() noexcept
{
    auto& control = Global(); std::scoped_lock lock(control.mutex);
    try
    {
        if (control.current && control.current->status.active)
        {
            Stop(*control.current,"Stopped by user");
            if (!control.current->claimed)
            {
                control.current->status.active = false; control.current->status.phase = "cancelled";
                control.current->status.message = "Stopped before the first normal RR owner.";
                g_captureActive.store(false,std::memory_order_release);
            }
        }
    } catch (...) {}
    control.wake.notify_all();
}
FSRDGameTraceSession::Status FSRDGameTraceSession::GetStatus()
{
    auto& control = Global(); std::scoped_lock lock(control.mutex);
    if (!control.current) return Status {};
    auto result = control.current->status; result.retainedReadbackBytes = control.gpuBytes;
    const auto now = GetTickCount64();
    if (result.recorded == 0 && result.active && now < control.current->startTick)
        result.delayRemainingMs = uint32_t(control.current->startTick-now);
    return result;
}
bool FSRDGameTraceSession::IsActive() noexcept
{ return g_captureActive.load(std::memory_order_acquire); }
bool FSRDGameTraceSession::WantsSrOutput() noexcept
{ return IsActive() && g_srRequested.load(std::memory_order_acquire); }

bool FSRDGameTraceSession::RecordSources(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
    const std::array<Source,SourceCount>& sources, uint32_t rw, uint32_t rh, std::span<const uint8_t> constants,
    std::span<const DiagnosticSource> diagnostics, std::span<const uint8_t> floorSeedConstants,
    std::span<const uint8_t> floorFilterConstants, bool submissionHooksAvailable) noexcept
{
    auto& control = Global(); std::scoped_lock lock(control.mutex);
    try
    {
        auto& impl = *m_impl; ReapReadbacks(control); impl.InspectLineage();
        if (impl.session && !impl.session->status.active)
        { impl.current.reset(); impl.pending.clear(); impl.cpuQueue.clear(); impl.staged.clear(); impl.session.reset(); }
        if (!impl.session)
        {
            if (!control.current || !control.current->status.active || control.current->claimed || control.current->stop) return false;
            impl.session = control.current; impl.session->claimed = true; impl.device = device;
            control.wake.notify_all();
        }
        auto& s = *impl.session;
        if (s.stop || s.closing || s.status.recorded >= FrameCount) return false;
        if (!device || !cmd || impl.device.Get() != device || !rw || !rh ||
            uint64_t(s.x)+s.size > rw || uint64_t(s.y)+s.size > rh || constants.size() != 416)
            throw std::runtime_error("Invalid fixed ROI/device/constants");
        if (!submissionHooksAvailable) throw std::runtime_error("Real queue submission/Reset hooks unavailable.");
        // Directory/space/manifest work runs only on the disk worker. This is
        // an unrecorded startup gap; the first admitted frame begins lineage.
        if (!s.initialized || GetTickCount64() < s.startTick) return false;
        if (impl.current && !impl.current->sealed) throw std::runtime_error("An evaluation ended without matched native/current/SR snapshots");
        if (impl.pending.size() >= MaximumPendingFrames)
            throw std::runtime_error("GAME_TRACE GPU backlog reached the bounded pending-frame limit; no game-thread wait performed");
        if ((!floorSeedConstants.empty() && floorSeedConstants.size() != 176) ||
            (!floorFilterConstants.empty() && floorFilterConstants.size() != 3*32 && floorFilterConstants.size() != 5*32))
            throw std::runtime_error("Invalid actual Floor seed/filter constant extent");
        const auto mapping = RRTraceAdditiveIO::Sha256(constants.subspan(256,96));
        if (!s.mappingHash.empty() && s.mappingHash != mapping) throw std::runtime_error("Conversion source mapping changed");
        s.mappingHash = mapping; s.manifest["conversion_mapping_sha256"] = mapping;
        if (s.rw && (s.rw != rw || s.rh != rh)) throw std::runtime_error("Render extent changed during capture");
        s.rw = rw; s.rh = rh; s.manifest["render_extent"] = {rw,rh};
        auto f = std::make_shared<Frame>(); f->ordinal = s.status.recorded; f->list = cmd; f->owner = impl.session;
        f->constants.assign(constants.begin(),constants.end());
        f->floorSeedConstants.assign(floorSeedConstants.begin(),floorSeedConstants.end());
        f->floorFilterConstants.assign(floorFilterConstants.begin(),floorFilterConstants.end());
        LARGE_INTEGER qpc {}; QueryPerformanceCounter(&qpc); f->qpc = uint64_t(qpc.QuadPart);
        f->ticket = RRTraceFence::Arm(device,cmd);
        impl.current = f; impl.pending.push_back(f); control.retained.push_back(f);
        for (size_t slot=0; slot<SourceCount; ++slot) CopyImage(device,cmd,*f,s,sources[slot],slot);
        CopyDiagnostics(device,cmd,*f,s,diagnostics,0,DiagnosticNames.size());
        s.status.phase = "capturing"; impl.UpdateProgress(); control.wake.notify_all(); return true;
    }
    catch (const std::exception& error) { m_impl->Failure(error.what()); return false; }
    catch (...) { m_impl->Failure("Unknown source snapshot failure"); return false; }
}
void FSRDGameTraceSession::RecordNative(ID3D12GraphicsCommandList* cmd, Source source, const FrameInfo& info,
    std::span<const DiagnosticSource> diagnostics) noexcept
{
    auto& control = Global(); std::scoped_lock lock(control.mutex);
    try
    {
        auto& impl = *m_impl;
        if (!impl.current || impl.current->sealed || !impl.session || impl.session->stop) return;
        auto& f = *impl.current; auto& s = *impl.session;
        if (cmd != f.list || f.native || info.contextId.empty()) throw std::runtime_error("Mismatched or unavailable actual native snapshot");
        RequireUnsubmitted(f);
        f.controls = Json::parse(info.controlsJson); f.settings = Json::parse(info.settingsJson);
        if (!f.controls.is_object() || !f.settings.is_object() || f.settings.empty()) throw std::runtime_error("Controls/settings must be actual nonempty JSON objects");
        for (const auto* key : {"view","projection","jitter","camera_delta","motion_vector_scale","depth_bounds","render_size"})
        {
            const std::string_view name(key);
            const size_t count = name == "view" || name == "projection" ? 16 : (name == "camera_delta" || name == "motion_vector_scale" ? 3 : 2);
            if (!f.controls.contains(key) || !f.controls[key].is_array() || f.controls[key].size() != count)
                throw std::runtime_error("Invalid actual control: "+std::string(key)+" (expected "+std::to_string(count)+" components)");
            for (const auto& value : f.controls[key]) if (!value.is_number() || !std::isfinite(value.get<double>()))
                throw std::runtime_error("Nonfinite actual control: "+std::string(key));
        }
        if (f.controls["render_size"] != Json::array({s.rw,s.rh})) throw std::runtime_error("Actual dispatch/source render extents differ");
        const auto serialized = f.settings.dump();
        const auto hash = RRTraceAdditiveIO::Sha256({reinterpret_cast<const uint8_t*>(serialized.data()),serialized.size()});
        if (s.bound && (s.context != info.contextId || s.lastEvaluation == UINT64_MAX || info.evaluationId != s.lastEvaluation+1 ||
            info.frameIndex != s.lastFrameIndex+1u || s.settingsHash != hash))
            throw std::runtime_error("Native context, consecutive evaluation order or settings changed");
        CopyImage(impl.device.Get(),cmd,f,s,source,8);
        CopyDiagnostics(impl.device.Get(),cmd,f,s,diagnostics,4,6);
        f.info = info; f.native = true; f.settingsHash = hash;
        s.context = info.contextId; s.settingsHash = hash; s.lastEvaluation = info.evaluationId; s.lastFrameIndex = info.frameIndex; s.bound = true;
        s.manifest["context_id"] = s.context; s.manifest["settings_sha256"] = hash;
        if (f.settings.contains("build_identity")) s.manifest["build_identity"] = f.settings["build_identity"];
    }
    catch (const std::exception& error) { m_impl->Failure(error.what()); }
    catch (...) { m_impl->Failure("Unknown native snapshot failure"); }
}
void FSRDGameTraceSession::CompleteFrame(ID3D12GraphicsCommandList* cmd, Source source) noexcept
{
    auto& control = Global(); std::scoped_lock lock(control.mutex);
    try
    {
        auto& impl = *m_impl;
        if (!impl.current || impl.current->sealed || !impl.session || impl.session->stop) return;
        auto& f = *impl.current;
        if (cmd != f.list || !f.native || f.currentCopied) throw std::runtime_error("Current output lacks unique matched native/source evaluation");
        RequireUnsubmitted(f); CopyImage(impl.device.Get(),cmd,f,*impl.session,source,9); f.currentCopied = true;
        if (impl.session->srMode == SrMode::Off) impl.Seal(f);
    }
    catch (const std::exception& error) { m_impl->Failure(error.what()); }
    catch (...) { m_impl->Failure("Unknown current snapshot failure"); }
}
void FSRDGameTraceSession::CompleteSrFrame(ID3D12GraphicsCommandList* cmd, Source source, const SrInfo& info) noexcept
{
    auto& control = Global(); std::scoped_lock lock(control.mutex);
    try
    {
        auto& impl = *m_impl;
        if (!impl.session || impl.session->srMode == SrMode::Off || impl.session->stop) return;
        if (!impl.current) return; // No frame admitted during initialization/delay.
        auto& f = *impl.current;
        if (cmd != f.list || !f.native || !f.currentCopied || f.sealed) throw std::runtime_error("SR output lacks the same unsubmitted pre-SR evaluation");
        RequireUnsubmitted(f); CopySr(impl.device.Get(),cmd,f,*impl.session,source,info); impl.Seal(f);
    }
    catch (const std::exception& error) { m_impl->Failure(error.what()); }
    catch (...) { m_impl->Failure("Unknown SR snapshot failure"); }
}
void FSRDGameTraceSession::Poll() noexcept
{
    auto& control = Global(); std::scoped_lock lock(control.mutex);
    try
    {
        ReapReadbacks(control); m_impl->InspectLineage();
        if (m_impl->session && m_impl->session->stop && !m_impl->pending.empty()) m_impl->Failure(m_impl->session->reason);
        m_impl->UpdateProgress(); control.wake.notify_all();
    }
    catch (const std::exception& error) { m_impl->Failure(error.what()); }
    catch (...) { m_impl->Failure("Unknown capture polling failure"); }
}
void FSRDGameTraceSession::Abort(const std::string& reason) noexcept
{
    auto& control = Global(); std::scoped_lock lock(control.mutex);
    if (!m_impl) return;
    if ((!m_impl->session || !m_impl->session->status.active) && control.current && control.current->status.active && !control.current->claimed)
    { m_impl->session = control.current; control.current->claimed = true; }
    m_impl->Failure(reason); control.wake.notify_all();
}
