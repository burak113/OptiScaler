#include "pch.h"
#include "FSRDGameTraceSession.h"
#include "RRTraceFence.h"
#include "RRTraceAdditiveIO.h"
#include "Util.h"
#include <json.hpp>
#include <deque>
#include <map>
#include <mutex>
#include <sstream>
#include <algorithm>
#include <cmath>
#include <climits>
#include <atomic>

namespace
{
using Json = nlohmann::json;
using Microsoft::WRL::ComPtr;
constexpr uint64_t MaximumPayloadBytes = 320ull << 20;
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
struct Session
{
    FSRDGameTraceSession::Status status;
    std::filesystem::path folder;
    uint32_t x = 0, y = 0, rw = 0, rh = 0;
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
struct Control { std::mutex mutex; std::shared_ptr<Session> current; };
Control& Global() { static auto* value = new Control; return *value; }
std::string PathString(const std::filesystem::path& p)
{ const auto text = p.u8string(); return {text.begin(), text.end()}; }
void SaveManifest(Session& s)
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
    s.manifest["incomplete_reason"] = s.reason.empty() ? Json(nullptr) : Json(s.reason);
    s.manifest["cancel_requested"] = s.stop;
    const auto temporary = s.folder / "capture.json.tmp";
    RRTraceAdditiveIO::WriteText(temporary, s.manifest.dump(2) + "\n");
    if (!MoveFileExW(temporary.c_str(), (s.folder / "capture.json").c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
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
            uint32_t width = FSRDGameTraceSession::TileSize, height = FSRDGameTraceSession::TileSize;
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
                            std::clamp<int64_t>(int64_t(origin)+FSRDGameTraceSession::TileSize-1,0,maximum)};
                    // Conservative one-texel halo contains the shader's binary32
                    // floor addressing, without replacing/resampling its words.
                    const double low = std::floor(((double(origin)+0.5-double(jitter))/render)*extent)-1;
                    const double high = std::floor(((double(origin)+FSRDGameTraceSession::TileSize-0.5-double(jitter))/render)*extent)+1;
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
            image.width = width; image.height = height;
            uint64_t frameBytes = frame.constants.size()+frame.floorSeedConstants.size()+frame.floorFilterConstants.size();
            for (const auto& captured : frame.images)
                if (captured.readback) frameBytes += uint64_t(captured.width)*captured.height*captured.bpp;
            for (const auto& captured : frame.diagnostics)
                if (captured.metadata["available"].get<bool>())
                    frameBytes += uint64_t(captured.image.width)*captured.image.height*captured.image.bpp;
            const uint64_t requestedBytes = uint64_t(width)*height*bpp;
            if (frameBytes > MaximumPayloadBytes-session.payloadReserved ||
                requestedBytes > MaximumPayloadBytes-session.payloadReserved-frameBytes)
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
            D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_READBACK;
            D3D12_RESOURCE_DESC buffer {}; buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
            buffer.Width = bytes; buffer.Height = 1; buffer.DepthOrArraySize = buffer.MipLevels = 1;
            buffer.SampleDesc.Count = 1; buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
            if (!bytes || bytes > MaximumPayloadBytes || FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&buffer,
                D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&image.readback))))
                throw std::runtime_error("Diagnostic readback allocation failed");
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
Json TicketMetadata(const std::shared_ptr<RRTraceFence::Ticket>& ticket)
{
    const auto snapshot = RRTraceFence::Inspect(ticket); const auto& state = snapshot.state;
    return {{"identity_address_process_local", snapshot.identity}, {"ticket_generation", snapshot.generation},
        {"queue_address_process_local", snapshot.queue}, {"recorded", state.recorded}, {"submitted", state.submitted},
        {"detached", state.detached}, {"invalid", state.invalid}, {"abandoned", state.abandoned},
        {"signal_failed", state.signalFailed}, {"ambiguous_submission", state.ambiguousSubmission},
        {"pending_signals", state.pendingSignals}, {"fence_expected", state.expected}, {"fence_completed", snapshot.completed},
        {"signal_hresult", int64_t(snapshot.signalResult)},
        {"detach_kind",state.detached ? "successful_command_list_reset" : "not_observed"},
        {"waitable", state.CanWait() && SUCCEEDED(snapshot.signalResult) && snapshot.completed != UINT64_MAX}};
}
void CopyImage(ID3D12Device* device, ID3D12GraphicsCommandList* cmd, Frame& frame,
               Session& session, FSRDGameTraceSession::Source source, size_t slot)
{
    if (!device || !cmd || !source.resource) throw std::runtime_error("GAME_TRACE missing resource");
    auto desc = source.resource->GetDesc();
    if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.Format != Formats[slot] ||
        desc.DepthOrArraySize != 1 || desc.SampleDesc.Count != 1 || desc.Width > UINT_MAX ||
        uint64_t(session.x) + FSRDGameTraceSession::TileSize > desc.Width ||
        uint64_t(session.y) + FSRDGameTraceSession::TileSize > desc.Height ||
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
    desc.Width = desc.Height = FSRDGameTraceSession::TileSize;
    desc.DepthOrArraySize = desc.MipLevels = 1;
    UINT64 bytes = 0;
    device->GetCopyableFootprints(&desc, 0, 1, 0, &image.footprint, nullptr, nullptr, &bytes);
    D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_READBACK;
    D3D12_RESOURCE_DESC buffer {}; buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    buffer.Width = bytes; buffer.Height = 1; buffer.DepthOrArraySize = buffer.MipLevels = 1;
    buffer.SampleDesc.Count = 1; buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer,
        D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&image.readback))))
        throw std::runtime_error("GAME_TRACE readback allocation failed");
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
    D3D12_BOX box {session.x, session.y, 0, session.x + FSRDGameTraceSession::TileSize,
                  session.y + FSRDGameTraceSession::TileSize, 1};
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

struct FSRDGameTraceSession::Impl
{
    std::shared_ptr<Session> session;
    std::deque<std::shared_ptr<Frame>> pending;
    // Disk-only, proof-qualified snapshots. They are not accepted frames until
    // every preceding ordinal can also be published.
    std::map<uint32_t,Json> staged;
    std::shared_ptr<Frame> current;
    ComPtr<ID3D12Device> device;
    void UpdateProgress()
    {
        if (!session) return;
        auto& s = *session;
        s.status.pending = uint32_t(pending.size()); s.status.staged = uint32_t(staged.size());
        s.status.awaitingDetach = 0;
        for (const auto& frame : pending)
            if (frame->sealed && !RRTraceFence::Inspect(frame->ticket).state.detached) ++s.status.awaitingDetach;
        s.manifest["private_staged_frames"] = Json::array();
        for (const auto& [ordinal,row] : staged)
            s.manifest["private_staged_frames"].push_back({{"ordinal",ordinal},
                {"private_folder", "frames/"+std::to_string(ordinal)+".pending"}, {"frame",row}});
        if (s.status.active)
        {
            s.status.message = "Published " + std::to_string(s.status.captured) + "/128; recorded " +
                std::to_string(s.status.recorded) + "; GPU pending " + std::to_string(s.status.pending) +
                "; private staged " + std::to_string(s.status.staged) + "; awaiting verified detach " +
                std::to_string(s.status.awaitingDetach) + ".";
            if (!s.reason.empty())
                s.status.message = s.reason + "; finalizing recorded frames. " + s.status.message;
        }
    }
    void SavePendingDiagnostics()
    {
        if (!session) return;
        UpdateProgress();
        Json rows = Json::array();
        for (const auto& f : pending)
            rows.push_back({{"ordinal",f->ordinal}, {"evaluation_id",f->native ? Json(f->info.evaluationId) : Json(nullptr)},
                {"native_recorded",f->native}, {"sealed",f->sealed}, {"recording_qpc",f->qpc},
                {"ticket",TicketMetadata(f->ticket)}});
        session->manifest["uncommitted_frames_at_close"] = std::move(rows);

    }
    void DiscardCurrent()
    {
        if (!current || current->sealed) return;
        current->ticket->Invalidate();
        if (!pending.empty() && pending.back() == current) pending.pop_back();
        current.reset();
    }
    void Finish()
    {
        if (!session) return;
        auto& s = *session;
        UpdateProgress();
        s.status.active = false; g_captureActive.store(false, std::memory_order_release);
        if (s.status.captured == FrameCount) s.reason.clear();
        s.status.phase = s.status.captured == FrameCount ? "complete" : (s.reason == "Stopped by user" ? "cancelled" : "incomplete");
        if (s.status.phase == "complete")
            s.status.message = "Saved 128 submitted, GPU-completed consecutive frames.";
        else if (s.status.phase == "cancelled")
            s.status.message = "Capture cancelled by user; saved partial sequence: " +
                std::to_string(s.status.captured) + "/128 frames.";
        else
            s.status.message = "Capture failed; saved partial sequence: " +
                std::to_string(s.status.captured) + "/128 frames. Reason: " + s.reason;
        SaveManifest(s);
    }
    void Stage(Frame& f)
    {
        auto& s = *session;
        if (!f.sealed || !f.ticket->Ready() || f.ordinal >= FrameCount || staged.contains(f.ordinal))
            throw std::runtime_error("GAME_TRACE private staging lacks unique sealed fence/detach proof");
        const auto relative = std::string("frames/") + std::to_string(f.ordinal);
        const auto partial = s.folder / (relative + ".pending");
        if (!std::filesystem::create_directory(partial)) throw std::runtime_error("GAME_TRACE frame folder already exists");
        Json row {{"ordinal", f.ordinal}, {"context_id", f.info.contextId}, {"evaluation_id", f.info.evaluationId},
            {"native_frame_index", f.info.frameIndex}, {"dispatch_flags", f.info.dispatchFlags}, {"reset", f.info.reset},
            {"recording_qpc", f.qpc}, {"controls", f.controls}, {"settings", f.settings}, {"native_full1", false},
            {"output_scope", "actual_configured_composition_before_sr"},
            {"native_full1_filename_role", "legacy_replay_alias_of_actual_configured_pre_sr_output"},
            {"gpu_submission_verified", true}, {"gpu_completed", true}, {"command_list_detached", true},
            {"reference", {{"available", false}, {"kind", "unavailable"}}}, {"images", Json::array()}};
        row["settings_canonical_json"] = f.settings.dump();
        row["settings_sha256"] = s.settingsHash;
        row["ticket_proof"] = TicketMetadata(f.ticket);
        auto writePayload = [&](const std::filesystem::path& path, std::span<const uint8_t> bytes)
        {
            if (bytes.size() > MaximumPayloadBytes-s.payloadWritten)
                throw std::runtime_error("GAME_TRACE cumulative private/published payload quota exceeded");
            // Charge before I/O; partial write failure never reclaims a budget
            // or retries a private snapshot.
            s.payloadWritten += bytes.size(); RRTraceAdditiveIO::WriteFile(path,bytes);
        };
        { std::scoped_lock ticketLock(f.ticket->mutex);
          std::ostringstream queue; queue << std::hex << reinterpret_cast<uintptr_t>(f.ticket->queue.Get());
          row["submission"] = {{"queue_address_process_local", queue.str()}, {"fence_expected", f.ticket->state.expected},
              {"fence_completed", f.ticket->completion}, {"signal_hresult", int64_t(f.ticket->signalResult)},
              {"pending_signals", f.ticket->state.pendingSignals}, {"ambiguous_submission", f.ticket->state.ambiguousSubmission}}; }
        for (size_t slot = 0; slot < f.images.size(); ++slot)
        {
            auto& image = f.images[slot];
            if (!image.readback) throw std::runtime_error("GAME_TRACE missing sealed snapshot");
            const size_t rowBytes = size_t(TileSize) * image.bpp;
            std::vector<uint8_t> bytes(rowBytes * TileSize);
            void* mapped = nullptr;
            const SIZE_T extent = image.footprint.Offset + SIZE_T(image.footprint.Footprint.RowPitch) * (TileSize - 1) + rowBytes;
            D3D12_RANGE read {0, extent};
            if (FAILED(image.readback->Map(0, &read, &mapped))) throw std::runtime_error("GAME_TRACE readback map failed");
            for (uint32_t y = 0; y < TileSize; ++y)
                memcpy(bytes.data() + y * rowBytes, static_cast<uint8_t*>(mapped) + image.footprint.Offset + size_t(y) * image.footprint.Footprint.RowPitch, rowBytes);
            D3D12_RANGE written {0,0}; image.readback->Unmap(0, &written);
            const auto filename = std::string(Names[slot]) + ".bin";
            writePayload(partial / filename, bytes);
            row["images"].push_back({{"name", Names[slot]}, {"file", relative + "/" + filename},
                {"bytes", bytes.size()}, {"sha256", RRTraceAdditiveIO::Sha256(bytes)}, {"dxgi_format", uint32_t(Formats[slot])},
                {"source_extent", {image.sourceWidth, image.sourceHeight}}, {"extent", {TileSize, TileSize}},
                {"crop_origin", {s.x, s.y}}, {"channels", 4}, {"bytes_per_pixel", image.bpp}, {"storage", "original_little_endian_gpu_words"}});
        }
        // Depth is R32 (one channel), not RGBA despite shared image schema.
        row["images"][Depth]["channels"] = 1;
        row["diagnostics"] = Json::array();
        for (auto& diagnostic : f.diagnostics)
        {
            auto record = diagnostic.metadata;
            record["evaluation_id"] = f.info.evaluationId;
            // Actual converter flags apply to every diagnostic, including SDK lobes.
            uint32_t converterFlags = 0; memcpy(&converterFlags,f.constants.data()+364,sizeof(converterFlags));
            record["conversion_flags"] = converterFlags;
            if (record["control"].empty() && !f.diagnostics[0].metadata["control"].empty())
                record["control"] = f.diagnostics[0].metadata["control"];
            if (record["available"].get<bool>())
            {
                auto& image = diagnostic.image;
                const size_t rowBytes = size_t(image.width)*image.bpp;
                std::vector<uint8_t> bytes(rowBytes*image.height);
                void* mapped = nullptr;
                const SIZE_T cropOffset = SIZE_T(image.readbackCropX)*image.bpp;
                const SIZE_T extent = image.footprint.Offset+SIZE_T(image.footprint.Footprint.RowPitch)*(image.readbackCropY+image.height-1)+cropOffset+rowBytes;
                D3D12_RANGE read {0,extent};
                if (FAILED(image.readback->Map(0,&read,&mapped))) throw std::runtime_error("GAME_TRACE diagnostic map failed");
                for (uint32_t y=0; y<image.height; ++y)
                    memcpy(bytes.data()+y*rowBytes,static_cast<uint8_t*>(mapped)+image.footprint.Offset+
                        size_t(image.readbackCropY+y)*image.footprint.Footprint.RowPitch+cropOffset,rowBytes);
                D3D12_RANGE written {0,0}; image.readback->Unmap(0,&written);
                const auto filename = record["name"].get<std::string>()+".bin";
                writePayload(partial/filename,bytes);
                record["file"] = relative+"/"+filename; record["bytes"] = bytes.size(); record["sha256"] = RRTraceAdditiveIO::Sha256(bytes);
            }
            row["diagnostics"].push_back(std::move(record));
        }
        writePayload(partial / "conversion_constants.bin", f.constants);
        row["conversion_constants"] = {{"file", relative + "/conversion_constants.bin"}, {"bytes", f.constants.size()},
                                       {"sha256", RRTraceAdditiveIO::Sha256(f.constants)}};
        row["floor_seed_constants"] = {{"available",!f.floorSeedConstants.empty()},
            {"stage","pre_floor_seed_dispatch"},{"abi_bytes",176}};
        if (!f.floorSeedConstants.empty())
        {
            writePayload(partial/"floor_seed_constants.bin",f.floorSeedConstants);
            row["floor_seed_constants"].update({{"file",relative+"/floor_seed_constants.bin"},
                {"bytes",f.floorSeedConstants.size()},{"sha256",RRTraceAdditiveIO::Sha256(f.floorSeedConstants)}});
        }
        else row["floor_seed_constants"]["reason"] = "Actual FloorSeed constants not supplied.";
        row["floor_filter_constants"] = {{"available",!f.floorFilterConstants.empty()},
            {"stage","pre_floor_filter_dispatches"},{"record_bytes",32},{"pass_count",f.floorFilterConstants.size()/32}};
        if (!f.floorFilterConstants.empty())
        {
            writePayload(partial/"floor_filter_constants.bin",f.floorFilterConstants);
            row["floor_filter_constants"].update({{"file",relative+"/floor_filter_constants.bin"},
                {"bytes",f.floorFilterConstants.size()},{"sha256",RRTraceAdditiveIO::Sha256(f.floorFilterConstants)}});
        }
        else row["floor_filter_constants"]["reason"] = "No actual Floor filter passes recorded (disabled or not supplied).";
        RRTraceAdditiveIO::WriteText(partial / "frame.json", row.dump(2) + "\n");
        staged.emplace(f.ordinal,std::move(row));
    }
    void PublishPrefix()
    {
        auto& s = *session;
        for (;;)
        {
            auto found = staged.find(s.status.captured);
            if (found == staged.end()) break;
            const auto relative = std::string("frames/")+std::to_string(found->first);
            std::filesystem::rename(s.folder/(relative+".pending"),s.folder/relative);
            s.manifest["frames"].push_back(found->second);
            ++s.status.captured; staged.erase(found);
        }
        UpdateProgress();
        SaveManifest(s);
    }
    void PollLocked()
    {
        if (!session || !session->status.active) return;
        auto& s = *session;
        if (s.stop) DiscardCurrent();
        // A held closed list must not pin already detached younger readbacks.
        // Keep their complete immutable payload privately; no suffix is exported.
        for (auto it = pending.begin(); it != pending.end();)
        {
            auto frame = *it;
            if (frame->ticket->Invalid())
            {
                SavePendingDiagnostics();
                Stop(s, "Submission, Reset, repeated submission or device failure invalidated a frame");
                for (auto& p : pending) p->ticket->Invalidate();
                current.reset(); pending.clear(); Finish(); return;
            }
            if (!frame->sealed || !frame->ticket->Ready()) { ++it; continue; }
            Stage(*frame);
            it = pending.erase(it);
            if (current == frame) current.reset();
        }
        PublishPrefix();
        if (pending.empty() && (s.stop || s.status.recorded == FrameCount)) Finish();
    }
    void Failure(const std::string& reason) noexcept
    {
        if (!session) return;
        try
        {
            SavePendingDiagnostics();
            Stop(*session, reason); DiscardCurrent();
            // Publication/recording failure closes at the committed prefix.
            // Never retry a partial disk commit or export a suffix after a gap.
            for (auto& p : pending) p->ticket->Invalidate();
            current.reset(); pending.clear(); Finish();
        }
        catch (...) { session->status.active = false; g_captureActive.store(false, std::memory_order_release); session->status.phase = "error"; session->status.message = "GAME_TRACE error: " + reason; }
    }
};

FSRDGameTraceSession::FSRDGameTraceSession() : m_impl(std::make_unique<Impl>()) {}
FSRDGameTraceSession::~FSRDGameTraceSession()
{
    Abort("Capture owner ended before completion");
    auto& global = Global(); std::scoped_lock lock(global.mutex);
    // No worker can poll after the owner dies. Keep uncertain GPU storage in
    // RRTraceFence's registry, but close the public session as incomplete now.
    if (m_impl->session && m_impl->session->status.active)
    {
        m_impl->current.reset(); m_impl->pending.clear();
        try { m_impl->Finish(); }
        catch (...) { m_impl->session->status.active = false; g_captureActive.store(false, std::memory_order_release); m_impl->session->status.phase = "error"; }
    }
}
bool FSRDGameTraceSession::RequestStart(uint32_t x, uint32_t y, uint32_t delaySeconds) noexcept
{
    auto& global = Global(); std::scoped_lock lock(global.mutex);
    std::shared_ptr<Session> attempted;
    try
    {
        if (global.current && global.current->status.active) return false;
        auto s = std::make_shared<Session>(); attempted = s; s->x = x; s->y = y;
        if (delaySeconds > 10) throw std::runtime_error("Capture start delay must be 0-10 seconds");
        s->startTick = GetTickCount64() + uint64_t(delaySeconds)*1000;
        std::array<uint8_t,16> uuid {};
        if (BCryptGenRandom(nullptr, uuid.data(), ULONG(uuid.size()), BCRYPT_USE_SYSTEM_PREFERRED_RNG) < 0)
            throw std::runtime_error("GAME_TRACE capture UUID allocation failed");
        uuid[6] = (uuid[6] & 15) | 0x40; uuid[8] = (uuid[8] & 63) | 0x80;
        std::ostringstream id;
        for (size_t i=0; i<uuid.size(); ++i) { if (i==4 || i==6 || i==8 || i==10) id << '-'; id << std::hex << std::setw(2) << std::setfill('0') << unsigned(uuid[i]); }
        s->status.captureId = id.str();
        s->folder = Util::DllPath().parent_path() / "GAME_TRACE" / s->status.captureId;
        s->status.folder = PathString(s->folder);
        std::filesystem::create_directories(s->folder.parent_path());
        if (std::filesystem::space(s->folder.parent_path()).available < (384ull << 20))
            throw std::runtime_error("GAME_TRACE disk quota: at least 384 MiB free space required");
        if (!std::filesystem::create_directory(s->folder)) throw std::runtime_error("GAME_TRACE folder collision");
        std::filesystem::create_directory(s->folder / "frames");
        s->status.folder = PathString(s->folder); s->status.active = true; s->status.phase = delaySeconds ? "armed" : "requested";
        s->status.message = delaySeconds ? "Armed; close the menu before capture starts."
            : "Waiting for the next normal RR game frame.";
        LARGE_INTEGER frequency {}; QueryPerformanceFrequency(&frequency);
        s->manifest = {{"schema", "fsrd-game-trace-v4"}, {"capture_uuid", s->status.captureId}, {"source", "live_game_gpu"},
            {"process_id", GetCurrentProcessId()}, {"target_frames", FrameCount}, {"qpc_frequency", frequency.QuadPart},
            {"capture_backend_build", __DATE__ " " __TIME__}, {"start_delay_seconds",delaySeconds},
            {"output_scope","actual_configured_composition_before_sr"},
            {"native_full1_filename_role","legacy_replay_alias_of_actual_configured_pre_sr_output"},
            {"neutral_full1_comparator",false},
            {"roi", {{"origin", {x,y}}, {"extent", {TileSize,TileSize}}, {"space", "render_pixels_fixed"}}},
            {"reference", {{"available", false}, {"kind", "unavailable"}, {"demodulation_zero_is_clean_truth", false}}},
            {"submission_policy", "same actual command-list evaluation; submitted+fence-completed+observed successful Reset detach before private staging; publish contiguous original ordinal prefix only"},
            {"maximum_pending_frames", 3}, {"frames", Json::array()}, {"errors", Json::array()}};
        s->manifest["maximum_payload_bytes"] = MaximumPayloadBytes;
        s->manifest["capacity_wait_maximum_ms"] = 100;
        SaveManifest(*s); global.current = s; g_captureActive.store(true, std::memory_order_release); return true;
    }
    catch (const std::exception& e)
    {
        auto s = attempted ? attempted : std::make_shared<Session>(); s->status.active = false; s->status.phase = "error"; s->status.message = e.what(); global.current = s; g_captureActive.store(false, std::memory_order_release); return false;
    }
    catch (...) { return false; }
}
void FSRDGameTraceSession::RequestStop() noexcept
{
    auto& global = Global(); std::scoped_lock lock(global.mutex);
    try
    {
        if (!global.current || !global.current->status.active) return;
        auto& s = *global.current; Stop(s, "Stopped by user");
        if (!s.claimed) { s.status.active = false; s.status.phase = "cancelled"; s.status.message = "Stopped before the first frame."; g_captureActive.store(false, std::memory_order_release); }
        SaveManifest(s);
    } catch (...) {}
}
FSRDGameTraceSession::Status FSRDGameTraceSession::GetStatus()
{
    auto& global = Global(); std::scoped_lock lock(global.mutex);
    if (!global.current) return Status {};
    auto result = global.current->status;
    const auto now = GetTickCount64();
    if (result.recorded == 0 && result.active && now < global.current->startTick)
        result.delayRemainingMs = uint32_t(global.current->startTick-now);
    return result;
}
bool FSRDGameTraceSession::IsActive() noexcept
{ return g_captureActive.load(std::memory_order_acquire); }
bool FSRDGameTraceSession::RecordSources(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
    const std::array<Source,SourceCount>& sources, uint32_t rw, uint32_t rh, std::span<const uint8_t> constants,
    std::span<const DiagnosticSource> diagnostics, std::span<const uint8_t> floorSeedConstants,
    std::span<const uint8_t> floorFilterConstants, bool submissionHooksAvailable) noexcept
{
    auto& global = Global(); std::unique_lock lock(global.mutex);
    try
    {
        auto& impl = *m_impl; impl.PollLocked();
        if (impl.session && !impl.session->status.active)
        {
            // Finish saved the old session's private lineage. Do not carry its
            // ordinal rows into a new UUID; its on-disk .pending files stay intact.
            impl.current.reset(); impl.pending.clear(); impl.staged.clear(); impl.session.reset();
        }
        if (!impl.session)
        {
            if (!global.current || !global.current->status.active || global.current->claimed || global.current->stop) return false;
            impl.session = global.current; impl.session->claimed = true; impl.device = device;
        }
        auto& s = *impl.session;
        if (s.stop || s.status.recorded >= FrameCount) return false;
        // Bind the request to this real normal-rendering owner before the
        // optional countdown expires. Backend teardown then cancels the arm.
        if (!device || !cmd || impl.device.Get() != device || !rw || !rh ||
            uint64_t(s.x)+TileSize > rw || uint64_t(s.y)+TileSize > rh || constants.size() != 416)
            throw std::runtime_error("Invalid fixed ROI/device/constants");
        if (!submissionHooksAvailable) throw std::runtime_error("Real queue submission/Reset hooks unavailable.");
        if (GetTickCount64() < s.startTick) return false;
        if (impl.current && !impl.current->sealed) throw std::runtime_error("An evaluation ended without a matched native/current snapshot");
        if (impl.pending.size() >= 3)
        {
            // Stage-ready frames were drained above. Choose any pending frame
            // already eligible for a fence wait; never wait for future Reset.
            std::shared_ptr<Frame> waitable;
            for (const auto& frame : impl.pending)
            {
                const auto snapshot = RRTraceFence::Inspect(frame->ticket);
                if (frame->sealed && snapshot.state.CanWait() && SUCCEEDED(snapshot.signalResult) && snapshot.completed != UINT64_MAX)
                { waitable = frame; break; }
            }
            auto waitingSession = impl.session;
            if (!waitable) throw std::runtime_error("Capture capacity: no submitted+detached pending ticket with a published successful signal");
            lock.unlock();
            const auto result = waitable->ticket->WaitBounded(100);
            lock.lock();
            if (impl.session != waitingSession || !waitingSession->status.active) return false;
            waitingSession->manifest["last_capacity_wait_result"] = int(result);
            impl.PollLocked();
            if (waitingSession->stop || !waitingSession->status.active) return false;
            if (impl.pending.size() >= 3)
                throw std::runtime_error(result == RRTraceFence::Ticket::WaitResult::NotWaitable
                    ? "Capture capacity: selected pending ticket lost submitted+detached signal proof"
                    : "Capture capacity: bounded 100 ms fence wait did not free a pending frame");
        }
        if (!device || !cmd || impl.device.Get() != device || !rw || !rh ||
            uint64_t(s.x)+TileSize > rw || uint64_t(s.y)+TileSize > rh || constants.size() != 416)
            throw std::runtime_error("Invalid fixed ROI/device/constants");
        if ((!floorSeedConstants.empty() && floorSeedConstants.size() != 176) ||
            (!floorFilterConstants.empty() && floorFilterConstants.size() != 3*32 && floorFilterConstants.size() != 5*32))
            throw std::runtime_error("Invalid actual Floor seed/filter constant extent");
        // Only source-address mapping bytes are invariant. View/projection,
        // motion/jitter and near/far are camera data and remain per-frame.
        const auto mapping = RRTraceAdditiveIO::Sha256(constants.subspan(256,96));
        if (!s.mappingHash.empty() && s.mappingHash != mapping) throw std::runtime_error("Conversion source mapping changed");
        s.mappingHash = mapping; s.manifest["conversion_mapping_sha256"] = mapping;
        if (s.rw && (s.rw != rw || s.rh != rh)) throw std::runtime_error("Render extent changed during capture");
        s.rw = rw; s.rh = rh; s.manifest["render_extent"] = {rw,rh};
        auto f = std::make_shared<Frame>(); f->ordinal = s.status.recorded; f->list = cmd;
        f->constants.assign(constants.begin(), constants.end());
        f->floorSeedConstants.assign(floorSeedConstants.begin(),floorSeedConstants.end());
        f->floorFilterConstants.assign(floorFilterConstants.begin(),floorFilterConstants.end());
        LARGE_INTEGER qpc {}; QueryPerformanceCounter(&qpc); f->qpc = uint64_t(qpc.QuadPart);
        f->ticket = RRTraceFence::Arm(device,cmd);
        impl.current = f; impl.pending.push_back(f);
        for (size_t slot=0; slot<SourceCount; ++slot) CopyImage(device,cmd,*f,s,sources[slot],slot);
        CopyDiagnostics(device,cmd,*f,s,diagnostics,0,DiagnosticNames.size());
        s.status.phase = "capturing"; impl.UpdateProgress();
        return true;
    }
    catch (const std::exception& e) { if (!lock.owns_lock()) lock.lock(); m_impl->Failure(e.what()); return false; }
    catch (...) { if (!lock.owns_lock()) lock.lock(); m_impl->Failure("Unknown source snapshot failure"); return false; }
}
void FSRDGameTraceSession::RecordNative(ID3D12GraphicsCommandList* cmd, Source source, const FrameInfo& info,
    std::span<const DiagnosticSource> diagnostics) noexcept
{
    auto& global = Global(); std::scoped_lock lock(global.mutex);
    try
    {
        auto& impl = *m_impl; if (!impl.current || impl.current->sealed || !impl.session || impl.session->stop) return;
        auto& f = *impl.current; auto& s = *impl.session;
        if (cmd != f.list || f.native || info.contextId.empty()) throw std::runtime_error("Mismatched or unavailable actual native Full1 snapshot");
        RequireUnsubmitted(f);
        f.controls = Json::parse(info.controlsJson); f.settings = Json::parse(info.settingsJson);
        if (!f.controls.is_object() || !f.settings.is_object() || f.settings.empty()) throw std::runtime_error("Controls/settings must be actual nonempty JSON objects");
        for (const auto& key : {"view", "projection", "jitter", "camera_delta", "motion_vector_scale", "depth_bounds", "render_size"})
        {
            const size_t count = (std::string_view(key) == "view" || std::string_view(key) == "projection") ? 16 : (std::string_view(key) == "camera_delta" ? 3 : 2);
            if (!f.controls.contains(key) || !f.controls[key].is_array() || f.controls[key].size() != count)
                throw std::runtime_error(std::string("Missing actual control: ") + key);
            for (const auto& v : f.controls[key]) if (!v.is_number() || !std::isfinite(v.get<double>()))
                throw std::runtime_error(std::string("Nonfinite actual control: ") + key);
        }
        if (f.controls["render_size"][0] != s.rw || f.controls["render_size"][1] != s.rh)
            throw std::runtime_error("Actual dispatch/source render extents differ");
        const auto serialized = f.settings.dump();
        const auto hash = RRTraceAdditiveIO::Sha256({reinterpret_cast<const uint8_t*>(serialized.data()),serialized.size()});
        if (s.bound && (s.context != info.contextId || s.lastEvaluation == UINT64_MAX || info.evaluationId != s.lastEvaluation+1 ||
            info.frameIndex != s.lastFrameIndex+1u || s.settingsHash != hash))
            throw std::runtime_error("Native context, consecutive evaluation order or settings changed");
        CopyImage(impl.device.Get(),cmd,f,s,source,8);
        CopyDiagnostics(impl.device.Get(),cmd,f,s,diagnostics,4,6);
        f.info = info; f.native = true;
        s.context = info.contextId; s.settingsHash = hash; s.lastEvaluation = info.evaluationId; s.lastFrameIndex = info.frameIndex; s.bound = true;
        s.manifest["context_id"] = s.context; s.manifest["settings_sha256"] = s.settingsHash;
        if (f.settings.contains("build_identity")) s.manifest["build_identity"] = f.settings["build_identity"];
    }
    catch (const std::exception& e) { m_impl->Failure(e.what()); }
    catch (...) { m_impl->Failure("Unknown native snapshot failure"); }
}
void FSRDGameTraceSession::CompleteFrame(ID3D12GraphicsCommandList* cmd, Source source) noexcept
{
    auto& global = Global(); std::scoped_lock lock(global.mutex);
    try
    {
        auto& impl = *m_impl; if (!impl.current || impl.current->sealed || !impl.session || impl.session->stop) return;
        auto& f = *impl.current;
        if (cmd != f.list || !f.native) throw std::runtime_error("Current output has no matched native/source evaluation");
        RequireUnsubmitted(f);
        CopyImage(impl.device.Get(),cmd,f,*impl.session,source,9);
        for (const auto& diagnostic : f.diagnostics)
            if (diagnostic.metadata["active"].get<bool>() && !diagnostic.metadata["available"].get<bool>())
                throw std::runtime_error("GAME_TRACE active diagnostic unavailable: "+diagnostic.metadata["name"].get<std::string>());
        { std::scoped_lock ticketLock(f.ticket->mutex); if (f.ticket->state.submitted || f.ticket->state.invalid) throw std::runtime_error("Frame submitted before sealing"); f.ticket->state.recorded = true; }
        uint64_t payload = f.constants.size()+f.floorSeedConstants.size()+f.floorFilterConstants.size();
        for (const auto& image : f.images) payload += uint64_t(TileSize)*TileSize*image.bpp;
        for (const auto& diagnostic : f.diagnostics)
            if (diagnostic.metadata["available"].get<bool>()) payload += uint64_t(diagnostic.image.width)*diagnostic.image.height*diagnostic.image.bpp;
        if (payload > MaximumPayloadBytes-impl.session->payloadReserved)
            throw std::runtime_error("GAME_TRACE total GPU/private/published payload quota exceeded");
        impl.session->payloadReserved += payload;
        f.sealed = true; ++impl.session->status.recorded;
        if (impl.session->status.recorded == FrameCount) impl.session->status.phase = "draining";
        impl.UpdateProgress();
    }
    catch (const std::exception& e) { m_impl->Failure(e.what()); }
    catch (...) { m_impl->Failure("Unknown current snapshot failure"); }
}
void FSRDGameTraceSession::Poll() noexcept
{
    auto& global = Global(); std::scoped_lock lock(global.mutex);
    try { m_impl->PollLocked(); }
    catch (const std::exception& e) { m_impl->Failure(e.what()); }
    catch (...) { m_impl->Failure("Unknown capture publication failure"); }
}
void FSRDGameTraceSession::Abort(const std::string& reason) noexcept
{
    auto& global = Global(); std::scoped_lock lock(global.mutex);
    // A menu request can precede the first normal evaluation. Teardown must
    // close that unclaimed arm too, so another backend cannot adopt it later.
    // It has no recorded commands, tickets or GPU payload to drain.
    if (m_impl && (!m_impl->session || !m_impl->session->status.active) &&
        global.current && global.current->status.active && !global.current->claimed)
    {
        m_impl->current.reset(); m_impl->pending.clear(); m_impl->staged.clear();
        m_impl->session = global.current; global.current->claimed = true;
    }
    if (m_impl && m_impl->session && m_impl->session->status.active) m_impl->Failure(reason);
}
