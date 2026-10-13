#include "pch.h"
#include "FrameSurvey_Dx12.h"
#include "FrameSurveyMetadata.h"
#include "shaders/fsrd_preprocess/FSRDGameTraceSession.h"
#include "shaders/fsrd_preprocess/RRTraceAdditiveIO.h"
#include "proxies/D3D12_Proxy.h"
#include "inputs/NVNGX_DLSS.h"
#include <nvsdk_ngx_defs_dlssd.h>
#include "include/d3dx/d3dx12.h"
#include <detours/detours.h>
#include <json.hpp>
#include <map>
#include <set>
#include <unordered_map>
#include <atomic>
#include <cctype>

namespace FrameSurvey
{
namespace
{
using Json = nlohmann::json;
using Microsoft::WRL::ComPtr;
const GUID RootBlobId = {0xe971fb39,0x45a2,0x41ea,{0xa1,0x55,0x64,0xa8,0xc7,0xa4,0xfd,0x11}};
const GUID PipelineId = {0xeb65bd20,0x3531,0x41b0,{0xbc,0x65,0x40,0xd9,0xc2,0xbe,0x31,0x11}};
std::atomic<bool> gEnabled {false}, gRecording {false};
// Creation metadata (root layouts, shader hashes, heaps, views) is tracked from device creation when
// FrameSurvey=true. Install() runs later, after the title has created most of its pipelines.
std::atomic<bool> gTracking {false};
bool Tracking() noexcept { return gTracking.load(std::memory_order_relaxed) || gEnabled.load(std::memory_order_relaxed); }
// FrameSurveyPassHashes: lowercase shader SHA-256 prefixes whose outputs are saved right after the dispatch.
std::mutex gPassHashMutex;
std::vector<std::string> gPassHashes;
bool TargetsConfigured()
{
    std::scoped_lock lock(gPassHashMutex);
    return !gPassHashes.empty();
}
bool Targeted(const Json& pso)
{
    std::scoped_lock lock(gPassHashMutex);
    if (gPassHashes.empty() || !pso.is_object()) return false;
    const auto shaders = pso.find("shader_hashes");
    if (shaders == pso.end() || !shaders->is_object()) return false;
    for (const auto& [stage,hash] : shaders->items())
    {
        if (!hash.is_string()) continue;
        const auto& text = hash.get_ref<const std::string&>();
        for (const auto& prefix : gPassHashes) if (text.rfind(prefix,0) == 0) return true;
    }
    return false;
}
thread_local bool gInternal = false;
struct InternalScope { bool previous = gInternal; InternalScope() { gInternal = true; } ~InternalScope() { gInternal = previous; } };
// Resource lifetime lock NEVER acquires the recorder or GAME_TRACE locks.
// Resolve+AddRef under this lock pairs with final Release cleanup in ResTrack.
std::recursive_mutex gLifetimeMutex, gRecordMutex;
std::mutex gSubmissionMutex;
uint64_t gNextResource = 0, gNextList = 0, gNextPass = 0;
uint32_t gRenderWidth = 0, gRenderHeight = 0;
Status gStatus;
struct Resource
{
    uint64_t id = 0, heap = 0, offset = 0, va = 0;
    ID3D12Resource* object = nullptr;
    D3D12_RESOURCE_DESC desc {};
    D3D12_RESOURCE_STATES initial = D3D12_RESOURCE_STATE_COMMON;
    bool initialKnown = false;
    std::set<uint64_t> handles;
};
struct ViewInfo
{
    ID3D12Resource* object = nullptr;
    uint64_t resource = 0;
    uint32_t kind = 0, format = 0, subresource = 0;
    bool snapshotSupported = false;
    uint64_t descriptorCpu = 0, descriptorGpu = 0, descriptorHeap = 0, rootVa = 0;
    uint32_t descriptorIndex = UINT_MAX, rootIndex = UINT_MAX;
};
struct Heap
{
    ID3D12DescriptorHeap* object = nullptr;
    uint64_t cpu = 0, gpu = 0;
    uint32_t count = 0, increment = 0, type = 0;
};
std::unordered_map<ID3D12Resource*,Resource> gResources;
std::map<uint64_t,ID3D12Resource*> gAddresses;
std::unordered_map<uint64_t,ViewInfo> gViews;
std::unordered_map<ID3D12DescriptorHeap*,Heap> gHeaps;
struct Range { uint32_t kind = 0, offset = 0, count = 0; };
struct RootLayout { std::string hash; std::map<uint32_t,std::vector<Range>> tables; bool complete = false, directIndexed = false; };
struct RootState
{
    uint64_t identity = 0;
    RootLayout layout;
    std::map<uint32_t,uint64_t> tables;
    std::map<uint32_t,std::pair<uint32_t,uint64_t>> views;
};
struct List
{
    uint64_t id = 0;
    bool resetObserved = false, closed = false, inRenderPass = false;
    // The last pass matched FrameSurveyPassHashes: its outputs are saved right after it (per-pass keys).
    bool targeted = false;
    uint64_t lastPass = 0;
    Json pso = Json::object(), passes = Json::array();
    RootState compute, graphics;
    std::vector<ID3D12DescriptorHeap*> heaps;
    std::vector<ViewInfo> targets, writes;
    std::vector<std::string> events;
    std::string marker;
    std::map<std::pair<uint64_t,uint32_t>,D3D12_RESOURCE_STATES> states;
    std::set<std::pair<uint64_t,uint32_t>> splitTransitions;
    std::shared_ptr<void> payload;
    std::map<std::string,uint64_t> copied;
};
struct Service
{
    FSRDGameTraceSession trace;
    ComPtr<ID3D12Device> device;
    IDXGISwapChain* swapchain = nullptr;
    bool requested = false, recording = false;
    uint64_t startTick = 0, candidateBytes = 0;
    uint32_t constantReads = 0;
    // Targeted mode keeps the window open (up to 8 Presents) until a listed pass is saved: with frame
    // generation a Present-to-Present interval can hold only the interpolated frame's work.
    uint32_t targetedCopies = 0, presents = 0;
    Json manifest;
    std::map<uint64_t,Json> resources;
    std::unordered_map<ID3D12GraphicsCommandList*,List> lists;
    std::set<std::pair<uint64_t,uint32_t>> candidates;
};
std::unique_ptr<Service> gService;
ComPtr<ID3D12Device> gCreationDevice;
bool Recording() { return Enabled() && gRecording.load(std::memory_order_acquire) && !gInternal; }
void Fail(const char* reason) noexcept
{
    try
    {
        std::scoped_lock lock(gRecordMutex);
        gRecording.store(false,std::memory_order_release);
        gStatus.phase = "error"; gStatus.message = reason; gStatus.active = false;
        if (gService)
        {
            gService->recording = gService->requested = false;
            gService->trace.Abort(reason);
        }
        LOG_ERROR("[FRAME_SURVEY] {}",reason);
    } catch (...) {}
}
void Count(const char* reason)
{
    auto& value = gService->manifest["coverage_gaps"][reason];
    if (value.is_null()) value = uint64_t(0);
    value = value.get<uint64_t>()+1;
}
Resource& Register(ID3D12Resource* resource)
{
    auto& result = gResources[resource];
    if (!result.id)
    {
        result.id = ++gNextResource; result.object = resource; result.desc = resource->GetDesc();
        if (result.desc.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER)
        { result.va = resource->GetGPUVirtualAddress(); if (result.va) gAddresses[result.va] = resource; }
    }
    return result;
}
std::string DebugName(ID3D12Resource* object)
{
    UINT bytes = 0;
    if (SUCCEEDED(object->GetPrivateData(WKPDID_D3DDebugObjectNameW,&bytes,nullptr)) && bytes && bytes <= 8192)
    {
        std::vector<wchar_t> words((bytes+1)/2+1,L'\0');
        if (SUCCEEDED(object->GetPrivateData(WKPDID_D3DDebugObjectNameW,&bytes,words.data())))
            return FrameSurveyMetadata::DecodeMarker(1,words.data(),bytes).first;
    }
    bytes = 0;
    if (SUCCEEDED(object->GetPrivateData(WKPDID_D3DDebugObjectName,&bytes,nullptr)) && bytes && bytes <= 4096)
    {
        std::vector<char> words(bytes+1,0);
        if (SUCCEEDED(object->GetPrivateData(WKPDID_D3DDebugObjectName,&bytes,words.data())))
            return FrameSurveyMetadata::DecodeMarker(0,words.data(),bytes).first;
    }
    return {};
}
void Describe(const Resource& resource)
{
    if (gService->resources.contains(resource.id)) return;
    const auto& d = resource.desc;
    gService->resources[resource.id] = {{"id",resource.id},{"pointer",uint64_t(reinterpret_cast<uintptr_t>(resource.object))},
        {"debug_name",DebugName(resource.object)},{"dimension",uint32_t(d.Dimension)},
        {"width",d.Width},{"height",d.Height},{"array_size",d.DepthOrArraySize},{"mip_levels",d.MipLevels},
        {"format",uint32_t(d.Format)},{"flags",uint32_t(d.Flags)},{"samples",d.SampleDesc.Count},
        {"heap_pointer",resource.heap},{"heap_offset",resource.offset},{"gpu_va",resource.va},
        {"initial_state_known",resource.initialKnown},{"initial_state",uint32_t(resource.initial)}};
}
RootLayout ReadRoot(ID3D12RootSignature* root)
{
    RootLayout result; if (!root) return result;
    UINT length = 0;
    if (FAILED(root->GetPrivateData(RootBlobId,&length,nullptr)) || !length || length > (1u<<20)) return result;
    std::vector<uint8_t> blob(length);
    if (FAILED(root->GetPrivateData(RootBlobId,&length,blob.data()))) return result;
    ComPtr<ID3D12VersionedRootSignatureDeserializer> decoder;
    auto deserialize = D3d12Proxy::D3D12CreateVersionedRootSignatureDeserializer_();
    if (!deserialize || FAILED(deserialize(blob.data(),blob.size(),IID_PPV_ARGS(&decoder)))) return result;
    const D3D12_VERSIONED_ROOT_SIGNATURE_DESC* desc = nullptr;
    if (FAILED(decoder->GetRootSignatureDescAtVersion(D3D_ROOT_SIGNATURE_VERSION_1_1,&desc))) return result;
    ComPtr<ID3DBlob> canonical, errors;
    auto serialize = D3d12Proxy::D3D12SerializeVersionedRootSignature_();
    if (!serialize || FAILED(serialize(desc,&canonical,&errors))) return result;
    result.hash = RRTraceAdditiveIO::Sha256({static_cast<const uint8_t*>(canonical->GetBufferPointer()),canonical->GetBufferSize()});
    result.complete = true;
    // Numeric bits are available even when compiling with an older D3D12 SDK.
    result.directIndexed = (uint32_t(desc->Desc_1_1.Flags)&0x400) != 0;
    for (UINT i=0;i<desc->Desc_1_1.NumParameters;++i)
    {
        const auto& param = desc->Desc_1_1.pParameters[i];
        if (param.ParameterType != D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE) continue;
        uint64_t offset = 0;
        for (UINT j=0;j<param.DescriptorTable.NumDescriptorRanges;++j)
        {
            const auto& range = param.DescriptorTable.pDescriptorRanges[j];
            const uint64_t start = range.OffsetInDescriptorsFromTableStart == D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND ? offset :
                range.OffsetInDescriptorsFromTableStart;
            if (start > UINT_MAX) { result.complete = false; break; }
            result.tables[i].push_back({uint32_t(range.RangeType),uint32_t(start),range.NumDescriptors});
            offset = start+range.NumDescriptors;
        }
    }
    return result;
}
Json ReadPipeline(ID3D12PipelineState* pso)
{
    Json result = {{"pointer",uint64_t(reinterpret_cast<uintptr_t>(pso))},{"shader_hashes",Json::object()},
        {"hash_known",false}};
    if (!pso) return result;
    UINT length = 0;
    if (SUCCEEDED(pso->GetPrivateData(PipelineId,&length,nullptr)) && length && length < 65536)
    {
        std::string text(length,'\0');
        if (SUCCEEDED(pso->GetPrivateData(PipelineId,&length,text.data()))) result.update(Json::parse(text));
    }
    return result;
}
// Binding state of every command list, kept while tracking. Lists reset before the recorded Present
// (Cyberpunk records its async compute list early) otherwise have no root layout, tables or pipeline.
struct Mirror
{
    struct Root
    {
        ID3D12RootSignature* object = nullptr;
        std::map<uint32_t,uint64_t> tables;
        std::map<uint32_t,std::pair<uint32_t,uint64_t>> views;
    };
    ID3D12PipelineState* pso = nullptr;
    Root compute, graphics;
    std::vector<ID3D12DescriptorHeap*> heaps;
};
std::mutex gMirrorMutex;
std::unordered_map<ID3D12GraphicsCommandList*,Mirror> gMirror;
template<class Update> void Mirrored(ID3D12GraphicsCommandList* cmd, Update&& update) noexcept
{
    if (!Tracking() || gInternal || !cmd) return;
    try { std::scoped_lock lock(gMirrorMutex); update(gMirror[cmd]); } catch (...) {}
}
bool Seed(ID3D12GraphicsCommandList* cmd, List& list)
{
    Mirror mirror;
    {
        std::scoped_lock lock(gMirrorMutex);
        const auto found = gMirror.find(cmd);
        if (found == gMirror.end()) return false;
        mirror = found->second;
    }
    list.pso = ReadPipeline(mirror.pso);
    auto seed = [](RootState& state, const Mirror::Root& root) {
        if (!root.object) return;
        state.identity = uint64_t(reinterpret_cast<uintptr_t>(root.object)); state.layout = ReadRoot(root.object);
        state.tables = root.tables; state.views = root.views; };
    seed(list.compute,mirror.compute); seed(list.graphics,mirror.graphics);
    list.heaps = mirror.heaps;
    return true;
}
List& GetList(ID3D12GraphicsCommandList* cmd)
{
    auto& state = gService->lists[cmd];
    if (!state.id)
    {
        state.id = ++gNextList; Count("list_without_observed_reset");
        if (Seed(cmd,state)) Count("list_bindings_seeded_from_tracking");
    }
    return state;
}
void StoreView(ID3D12Resource* object, uint64_t handle, uint32_t kind, DXGI_FORMAT format,
    uint32_t mip, uint32_t slice, bool supported)
{
    if (!Tracking() || gInternal) return;
    std::scoped_lock lock(gLifetimeMutex);
    if (const auto found = gViews.find(handle); found != gViews.end() && found->second.object)
        if (const auto old = gResources.find(found->second.object); old != gResources.end()) old->second.handles.erase(handle);
    if (!object) { gViews.erase(handle); return; }
    auto& resource = Register(object); resource.handles.insert(handle);
    const auto sub = mip + slice*resource.desc.MipLevels;
    gViews[handle] = {object,resource.id,kind,uint32_t(format == DXGI_FORMAT_UNKNOWN ? resource.desc.Format : format),sub,supported};
    gViews[handle].descriptorCpu = handle;
}
std::vector<ViewInfo> Bindings(List& state, bool graphics, Json& unresolved)
{
    std::vector<ViewInfo> result;
    auto& root = graphics ? state.graphics : state.compute;
    if (!root.layout.complete) unresolved.push_back("root_signature_layout_unavailable");
    if (root.layout.directIndexed) unresolved.push_back("direct_heap_indexing_shader_usage_unknown");
    std::scoped_lock lock(gLifetimeMutex);
    for (const auto& [index,base] : root.tables)
    {
        const auto table = root.layout.tables.find(index);
        if (table == root.layout.tables.end()) continue;
        const Heap* heap = nullptr;
        for (auto* object : state.heaps)
        {
            const auto found = gHeaps.find(object);
            if (found == gHeaps.end()) continue;
            const auto& h = found->second;
            if (h.gpu && base >= h.gpu && base-h.gpu < uint64_t(h.count)*h.increment) { heap = &h; break; }
        }
        if (!heap || !heap->increment) { unresolved.push_back("descriptor_heap_unavailable"); continue; }
        const uint64_t first = (base-heap->gpu)/heap->increment;
        for (const auto& range : table->second)
        {
            if (range.kind != D3D12_DESCRIPTOR_RANGE_TYPE_SRV && range.kind != D3D12_DESCRIPTOR_RANGE_TYPE_UAV &&
                range.kind != D3D12_DESCRIPTOR_RANGE_TYPE_CBV) continue;
            if (first+range.offset >= heap->count) continue;
            uint64_t count = std::min<uint64_t>(range.count,heap->count-first-range.offset);
            // Unbounded/bindless ranges cannot reveal shader dynamic indexing.
            if (count > 512) { count = 512; unresolved.push_back("descriptor_range_capped_512"); }
            for (uint64_t i=0;i<count;++i)
            {
                const auto found = gViews.find(heap->cpu+(first+range.offset+i)*heap->increment);
                if (found == gViews.end()) continue;
                auto view = found->second;
                view.descriptorHeap = uint64_t(reinterpret_cast<uintptr_t>(heap->object));
                view.descriptorIndex = UINT(first+range.offset+i); view.rootIndex = index;
                view.descriptorCpu = heap->cpu+uint64_t(view.descriptorIndex)*heap->increment;
                view.descriptorGpu = heap->gpu+uint64_t(view.descriptorIndex)*heap->increment;
                // Range type is authoritative, not a guessed adjacent descriptor.
                if (view.kind == range.kind) result.push_back(view);
            }
        }
    }
    for (const auto& [index,view] : root.views)
    {
        const auto upper = gAddresses.upper_bound(view.second);
        if (upper == gAddresses.begin()) { unresolved.push_back("root_gpu_va_unresolved"); continue; }
        const auto found = gResources.find(std::prev(upper)->second);
        if (found == gResources.end() || view.second-found->second.va >= found->second.desc.Width)
        { unresolved.push_back("root_gpu_va_unresolved"); continue; }
        ViewInfo binding {found->first,found->second.id,view.first,uint32_t(found->second.desc.Format),0,false};
        binding.rootVa = view.second; binding.rootIndex = index; result.push_back(binding);
    }
    if (graphics) result.insert(result.end(),state.targets.begin(),state.targets.end());
    std::sort(result.begin(),result.end(),[](const auto& a,const auto& b) {
        return std::tie(a.resource,a.kind,a.subresource) < std::tie(b.resource,b.kind,b.subresource); });
    result.erase(std::unique(result.begin(),result.end(),[](const auto& a,const auto& b) {
        return a.resource == b.resource && a.kind == b.kind && a.subresource == b.subresource; }),result.end());
    return result;
}
bool CopyImage(ID3D12GraphicsCommandList* cmd, List& list, const ViewInfo& view,
    D3D12_RESOURCE_STATES state, const std::string& key, bool tagged, UINT x = 0, UINT y = 0, UINT w = 0, UINT h = 0)
{
    ComPtr<ID3D12Resource> source;
    D3D12_RESOURCE_DESC desc {};
    {
        std::scoped_lock lock(gLifetimeMutex);
        const auto found = gResources.find(view.object);
        if (found == gResources.end() || found->second.id != view.resource) { Count("released_descriptor_resource"); return false; }
        source = view.object; desc = found->second.desc; Describe(found->second);
    }
    const auto mip = view.subresource % desc.MipLevels;
    const uint32_t width = uint32_t(std::max<uint64_t>(1,desc.Width >> mip)), height = std::max(1u,desc.Height >> mip);
    // A targeted pass may sit in a list reset before the frame (async/early recording); its payload
    // still retires on that list's next Reset, like any other.
    if ((!list.resetObserved && !list.targeted) || list.inRenderPass)
    { Count("snapshot_recording_state_unavailable"); return false; }
    if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.SampleDesc.Count != 1 || !view.snapshotSupported) return false;
    if (!tagged && !FrameSurveyMetadata::CandidateExtent(width,height,gRenderWidth,gRenderHeight)) return false;
    // Targeted mode: the candidate budget belongs to the listed passes' outputs (one RGBA16F output is ~10 MiB
    // at 1505x847, the regular last-writer set alone fills most of the 192 MiB).
    if (!tagged && !list.targeted && TargetsConfigured()) { Count("regular_snapshot_skipped_targeted_mode"); return false; }
    const std::pair<uint64_t,uint32_t> identity {view.resource,view.subresource};
    if (list.splitTransitions.contains(identity)) { Count("pending_split_barrier_snapshot_skipped"); return false; }
    const bool fresh = !list.copied.contains(key);
    if (fresh && !tagged)
    {
        if (!gService->candidates.contains(identity) && gService->candidates.size() >= 96)
        { Count("candidate_count_cap"); return false; }
        // Reserve 64 MiB for the actual title tags. GAME_TRACE separately
        // enforces actual committed GPU allocations and CPU/disk payload limits.
        UINT bpp = 16;
        switch (uint32_t(desc.Format))
        {
        case 5: case 6: bpp = 12; break;
        case 9: case 10: case 11: case 15: case 16: bpp = 8; break;
        case 23: case 24: case 26: case 27: case 28: case 33: case 34: case 35:
        case 39: case 40: case 41: case 44: case 45: case 46: case 87: bpp = 4; break;
        case 53: case 54: case 56: bpp = 2; break; case 60: case 61: bpp = 1; break;
        }
        const uint64_t charge = uint64_t(width)*height*bpp;
        if (charge > (192ull<<20)-std::min<uint64_t>(192ull<<20,gService->candidateBytes))
        { Count("candidate_byte_cap"); return false; }
        gService->candidateBytes += charge;
    }
    InternalScope internal;
    if (!list.payload) list.payload = gService->trace.BeginSurveyBatch(gService->device.Get(),cmd,list.id);
    if (!list.payload) { Count("payload_batch_unavailable"); return false; }
    if (!gService->trace.SurveyTexture(list.payload,key,{source.Get(),state},view.subresource,x,y,w,h))
    { Count("unsupported_format_or_readback_budget"); return false; }
    if (!tagged) gService->candidates.insert(identity);
    if (list.targeted) ++gService->targetedCopies;
    list.copied[key] = list.lastPass;
    gService->manifest["snapshots"].push_back({{"key",key},{"list_id",list.id},{"resource",view.resource},
        {"subresource",view.subresource},{"writer_local_pass",list.lastPass},{"tagged",tagged},{"view_format",view.format},
        {"state_provenance",tagged ? "see_current_tag_metadata" : "observed_local_resource_barrier"}});
    return true;
}
bool CopyBuffer(ID3D12GraphicsCommandList* cmd, List& list, ID3D12Resource* object,
    const std::string& key, uint64_t offset, uint32_t bytes)
{
    if (!object || !bytes || (!list.resetObserved && !list.targeted) || list.inRenderPass) return false;
    ComPtr<ID3D12Resource> source;
    uint64_t id = 0;
    {
        std::scoped_lock lock(gLifetimeMutex); auto& resource = Register(object);
        if (resource.desc.Dimension != D3D12_RESOURCE_DIMENSION_BUFFER ||
            offset > resource.desc.Width || bytes > resource.desc.Width-offset) return false;
        source = object; id = resource.id; Describe(resource);
    }
    D3D12_HEAP_PROPERTIES heap {}; D3D12_HEAP_FLAGS flags {};
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COMMON;
    if (SUCCEEDED(source->GetHeapProperties(&heap,&flags)) && heap.Type == D3D12_HEAP_TYPE_UPLOAD)
        state = D3D12_RESOURCE_STATE_GENERIC_READ; // upload heaps have a fixed, proven state
    else
    {
        const auto observed = list.states.find({id,0});
        if (observed == list.states.end()) { Count("buffer_read_state_unproven"); return false; }
        state = observed->second;
    }
    if (list.splitTransitions.contains({id,0})) return false;
    InternalScope internal;
    if (!list.payload) list.payload = gService->trace.BeginSurveyBatch(gService->device.Get(),cmd,list.id);
    return list.payload && gService->trace.SurveyBuffer(list.payload,key,{source.Get(),state},offset,bytes);
}
}

ScopedInternal::ScopedInternal() noexcept : previous_(gInternal) { gInternal = true; }
ScopedInternal::~ScopedInternal() { gInternal = previous_; }
void SetPipelineObserver(PipelineObserver) noexcept {}
void SetReleaseObserver(ReleaseObserver) noexcept {}
void SetBindingWindow(bool) noexcept {}
bool BindingWindow() noexcept { return false; }
bool ResolveComputeTable(ID3D12GraphicsCommandList*, UINT, std::vector<BoundResource>& out) noexcept
{ out.clear(); return false; }
bool Enabled() noexcept { return gEnabled.load(std::memory_order_relaxed); }
void BeginCreationTracking() noexcept { gTracking.store(true,std::memory_order_release); }
void SetPassHashes(const std::string& list) noexcept
{
    try
    {
        std::vector<std::string> parsed; std::string token;
        auto flush = [&] {
            if (token.size() >= 8 && token.size() <= 64 && token.find_first_not_of("0123456789abcdef") == token.npos) parsed.push_back(token);
            token.clear(); };
        for (const char c : list)
        {
            if (c == ',' || c == ';' || c == ' ' || c == '\t') flush();
            else token.push_back(char(std::tolower(static_cast<unsigned char>(c))));
        }
        flush();
        std::scoped_lock lock(gPassHashMutex); gPassHashes = std::move(parsed);
    } catch (...) {}
}
bool Internal() noexcept { return gInternal; }
std::mutex& SubmissionMutex() { return gSubmissionMutex; }
void ResourceCreated(ID3D12Resource* object, D3D12_RESOURCE_STATES initial, ID3D12Heap* heap, uint64_t offset) noexcept
{
    if (!Tracking() || gInternal || !object) return;
    try
    {
        std::scoped_lock lock(gLifetimeMutex); auto& resource = Register(object);
        resource.initial = initial; resource.initialKnown = true;
        resource.heap = uint64_t(reinterpret_cast<uintptr_t>(heap)); resource.offset = offset;
    } catch (...) { Fail("Resource metadata allocation failed"); }
}
void RootCreated(ID3D12RootSignature* root, const void* bytes, size_t length) noexcept
{
    if (!Tracking() || gInternal || !root || !bytes || length > (1u<<20)) return;
    if (FAILED(root->SetPrivateData(RootBlobId,UINT(length),bytes))) Fail("Root signature metadata storage failed");
}
void PipelineCreated(ID3D12PipelineState* pso, const D3D12_COMPUTE_PIPELINE_STATE_DESC& desc) noexcept
{
    if (!Tracking() || gInternal || !pso) return;
    try
    {
        Json data = {{"shader_hashes",{{"CS",RRTraceAdditiveIO::Sha256({static_cast<const uint8_t*>(desc.CS.pShaderBytecode),desc.CS.BytecodeLength})}}},
            {"hash_known",desc.CS.BytecodeLength != 0},{"root_hash",ReadRoot(desc.pRootSignature).hash}};
        auto text = data.dump(); pso->SetPrivateData(PipelineId,UINT(text.size()),text.data());
    } catch (...) { Fail("Compute shader hash failed"); }
}
void PipelineCreated(ID3D12PipelineState* pso, const D3D12_GRAPHICS_PIPELINE_STATE_DESC& desc) noexcept
{
    if (!Tracking() || gInternal || !pso) return;
    try
    {
        Json hashes = Json::object();
        auto add = [&](const char* name,const D3D12_SHADER_BYTECODE& shader) {
            if (shader.BytecodeLength) hashes[name] = RRTraceAdditiveIO::Sha256({static_cast<const uint8_t*>(shader.pShaderBytecode),shader.BytecodeLength}); };
        add("VS",desc.VS); add("PS",desc.PS); add("GS",desc.GS); add("HS",desc.HS); add("DS",desc.DS);
        const auto text = Json{{"shader_hashes",hashes},{"hash_known",!hashes.empty()},{"root_hash",ReadRoot(desc.pRootSignature).hash}}.dump();
        pso->SetPrivateData(PipelineId,UINT(text.size()),text.data());
    } catch (...) { Fail("Graphics shader hash failed"); }
}
void PipelineCreated(ID3D12PipelineState* pso, const D3D12_PIPELINE_STATE_STREAM_DESC& desc) noexcept
{
    if (!Tracking() || gInternal || !pso) return;
    try
    {
        struct Parser : ID3DX12PipelineParserCallbacks
        {
            Json shaders = Json::object(); ID3D12RootSignature* root = nullptr;
            void RootSignatureCb(ID3D12RootSignature* value) override { root = value; }
            void Add(const char* name,const D3D12_SHADER_BYTECODE& value) {
                if (value.BytecodeLength) shaders[name] = RRTraceAdditiveIO::Sha256({static_cast<const uint8_t*>(value.pShaderBytecode),value.BytecodeLength}); }
            void CSCb(const D3D12_SHADER_BYTECODE& v) override { Add("CS",v); }
            void VSCb(const D3D12_SHADER_BYTECODE& v) override { Add("VS",v); }
            void PSCb(const D3D12_SHADER_BYTECODE& v) override { Add("PS",v); }
            void GSCb(const D3D12_SHADER_BYTECODE& v) override { Add("GS",v); }
            void HSCb(const D3D12_SHADER_BYTECODE& v) override { Add("HS",v); }
            void DSCb(const D3D12_SHADER_BYTECODE& v) override { Add("DS",v); }
        } parser;
        const auto result = D3DX12ParsePipelineStream(desc,&parser);
        // Hash pointed-to bytecode, NEVER process-local stream pointer bytes.
        const auto text = Json{{"shader_hashes",parser.shaders},{"hash_known",SUCCEEDED(result)&&!parser.shaders.empty()},
            {"stream_parse_hresult",int64_t(result)},{"root_hash",ReadRoot(parser.root).hash}}.dump();
        pso->SetPrivateData(PipelineId,UINT(text.size()),text.data());
    } catch (...) { Fail("Pipeline stream shader hash failed"); }
}
void Released(void* object) noexcept
{
    if (!Tracking() || !object) return;
    try
    {
        std::scoped_lock lock(gLifetimeMutex);
        auto* resource = reinterpret_cast<ID3D12Resource*>(object);
        if (const auto found = gResources.find(resource); found != gResources.end())
        {
            for (auto handle : found->second.handles) gViews.erase(handle);
            if (found->second.va) gAddresses.erase(found->second.va);
            gResources.erase(found);
        }
        auto* heap = reinterpret_cast<ID3D12DescriptorHeap*>(object);
        if (const auto found = gHeaps.find(heap); found != gHeaps.end())
        {
            for (UINT i=0;i<found->second.count;++i)
            {
                const auto handle = found->second.cpu+uint64_t(i)*found->second.increment;
                const auto view = gViews.find(handle);
                if (view != gViews.end())
                {
                    if (const auto r = gResources.find(view->second.object); r != gResources.end()) r->second.handles.erase(handle);
                    gViews.erase(view);
                }
            }
            gHeaps.erase(found);
        }
    } catch (...) {}
}
void HeapCreated(ID3D12Device* device, ID3D12DescriptorHeap* object) noexcept
{
    if (!Tracking() || gInternal || !object) return;
    try
    {
        const auto desc = object->GetDesc();
        if (desc.Type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV && desc.Type != D3D12_DESCRIPTOR_HEAP_TYPE_RTV) return;
        std::scoped_lock lock(gLifetimeMutex);
        const auto cpu = object->GetCPUDescriptorHandleForHeapStart().ptr;
        const auto gpu = (desc.Flags&D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE) ? object->GetGPUDescriptorHandleForHeapStart().ptr : 0;
        gHeaps[object] = {object,cpu,gpu,desc.NumDescriptors,device->GetDescriptorHandleIncrementSize(desc.Type),uint32_t(desc.Type)};
    } catch (...) { Fail("Descriptor heap metadata allocation failed"); }
}
void View(ID3D12Resource* resource, D3D12_CPU_DESCRIPTOR_HANDLE handle, const D3D12_SHADER_RESOURCE_VIEW_DESC* desc) noexcept
{
    try
    {
        UINT mip = 0, slice = 0; bool supported = !desc;
        if (desc && desc->ViewDimension == D3D12_SRV_DIMENSION_TEXTURE2D) { mip = desc->Texture2D.MostDetailedMip; supported = desc->Texture2D.PlaneSlice == 0; }
        if (desc && desc->ViewDimension == D3D12_SRV_DIMENSION_TEXTURE2DARRAY)
        { mip = desc->Texture2DArray.MostDetailedMip; slice = desc->Texture2DArray.FirstArraySlice; supported = desc->Texture2DArray.ArraySize == 1 && desc->Texture2DArray.PlaneSlice == 0; }
        StoreView(resource,handle.ptr,D3D12_DESCRIPTOR_RANGE_TYPE_SRV,desc ? desc->Format : DXGI_FORMAT_UNKNOWN,mip,slice,supported);
    } catch (...) { Fail("SRV metadata allocation failed"); }
}
void View(ID3D12Resource* resource, D3D12_CPU_DESCRIPTOR_HANDLE handle, const D3D12_UNORDERED_ACCESS_VIEW_DESC* desc) noexcept
{
    try
    {
        UINT mip = 0, slice = 0; bool supported = !desc;
        if (desc && desc->ViewDimension == D3D12_UAV_DIMENSION_TEXTURE2D) { mip = desc->Texture2D.MipSlice; supported = desc->Texture2D.PlaneSlice == 0; }
        if (desc && desc->ViewDimension == D3D12_UAV_DIMENSION_TEXTURE2DARRAY)
        { mip = desc->Texture2DArray.MipSlice; slice = desc->Texture2DArray.FirstArraySlice; supported = desc->Texture2DArray.ArraySize == 1 && desc->Texture2DArray.PlaneSlice == 0; }
        StoreView(resource,handle.ptr,D3D12_DESCRIPTOR_RANGE_TYPE_UAV,desc ? desc->Format : DXGI_FORMAT_UNKNOWN,mip,slice,supported);
    } catch (...) { Fail("UAV metadata allocation failed"); }
}
void View(ID3D12Resource* resource, D3D12_CPU_DESCRIPTOR_HANDLE handle, const D3D12_RENDER_TARGET_VIEW_DESC* desc) noexcept
{
    try
    {
        UINT mip = 0, slice = 0; bool supported = !desc;
        if (desc && desc->ViewDimension == D3D12_RTV_DIMENSION_TEXTURE2D) { mip = desc->Texture2D.MipSlice; supported = desc->Texture2D.PlaneSlice == 0; }
        if (desc && desc->ViewDimension == D3D12_RTV_DIMENSION_TEXTURE2DARRAY)
        { mip = desc->Texture2DArray.MipSlice; slice = desc->Texture2DArray.FirstArraySlice; supported = desc->Texture2DArray.ArraySize == 1 && desc->Texture2DArray.PlaneSlice == 0; }
        StoreView(resource,handle.ptr,4,desc ? desc->Format : DXGI_FORMAT_UNKNOWN,mip,slice,supported);
    } catch (...) { Fail("RTV metadata allocation failed"); }
}
void CopyDescriptors(ID3D12Device* device, UINT nd, const D3D12_CPU_DESCRIPTOR_HANDLE* dst, const UINT* dn,
    UINT ns, const D3D12_CPU_DESCRIPTOR_HANDLE* src, const UINT* sn, D3D12_DESCRIPTOR_HEAP_TYPE type) noexcept
{
    if (!Tracking() || gInternal || !dst || !src ||
        (type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV && type != D3D12_DESCRIPTOR_HEAP_TYPE_RTV)) return;
    try
    {
        std::scoped_lock lock(gLifetimeMutex); const auto stride = device->GetDescriptorHandleIncrementSize(type);
        UINT di = 0, si = 0, d = 0, s = 0;
        while (di<nd && si<ns)
        {
            if (d >= (dn ? dn[di] : 1)) { ++di; d = 0; continue; }
            if (s >= (sn ? sn[si] : 1)) { ++si; s = 0; continue; }
            const auto dh = dst[di].ptr+uint64_t(d++)*stride, sh = src[si].ptr+uint64_t(s++)*stride;
            if (const auto old = gViews.find(dh); old != gViews.end())
                if (const auto r = gResources.find(old->second.object); r != gResources.end()) r->second.handles.erase(dh);
            if (const auto v = gViews.find(sh); v != gViews.end())
            { auto copy = v->second; copy.descriptorCpu = dh; gViews[dh] = copy; gResources.at(copy.object).handles.insert(dh); }
            else gViews.erase(dh);
        }
    } catch (...) { Fail("Descriptor copy metadata allocation failed"); }
}

void Reset(ID3D12GraphicsCommandList* cmd, ID3D12PipelineState* initial) noexcept
{
    Mirrored(cmd,[&](Mirror& mirror) { mirror = {}; mirror.pso = initial; });
    if (!Recording()) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return;
        auto& list = gService->lists[cmd]; list = {};
        list.id = ++gNextList; list.resetObserved = true; list.pso = ReadPipeline(initial);
    } catch (...) { Fail("Command-list reset metadata failed"); }
}
void Close(ID3D12GraphicsCommandList* cmd, HRESULT result) noexcept
{
    if (!Recording()) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return;
        if (FAILED(result)) { Fail("Original command-list Close failed"); return; }
        auto& list = GetList(cmd); list.closed = true;
        if (list.payload) gService->trace.SealSurveyBatch(list.payload);
    } catch (...) { Fail("Command-list Close metadata failed"); }
}
void SetPipeline(ID3D12GraphicsCommandList* cmd, ID3D12PipelineState* pso) noexcept
{
    Mirrored(cmd,[&](Mirror& mirror) { mirror.pso = pso; });
    if (!Recording()) return;
    try { std::scoped_lock lock(gRecordMutex); if (!Recording()) return; GetList(cmd).pso = ReadPipeline(pso); }
    catch (...) { Fail("Pipeline binding metadata failed"); }
}
void RootBinding(ID3D12GraphicsCommandList* cmd, bool graphics, ID3D12RootSignature* root) noexcept
{
    Mirrored(cmd,[&](Mirror& mirror) {
        auto& state = graphics ? mirror.graphics : mirror.compute;
        if (state.object != root) { state = {}; state.object = root; } });
    if (!Recording()) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        auto& state = graphics ? list.graphics : list.compute;
        const uint64_t identity = uint64_t(reinterpret_cast<uintptr_t>(root));
        // Rebinding the same signature preserves root arguments (D3D12 contract).
        if (state.identity == identity) return;
        state = {}; state.identity = identity; state.layout = ReadRoot(root);
    } catch (...) { Fail("Root signature binding failed"); }
}
void DescriptorHeaps(ID3D12GraphicsCommandList* cmd, UINT count, ID3D12DescriptorHeap* const* heaps) noexcept
{
    Mirrored(cmd,[&](Mirror& mirror) {
        std::vector<ID3D12DescriptorHeap*> next;
        if (heaps) next.assign(heaps,heaps+count);
        if (next != mirror.heaps) { mirror.compute.tables.clear(); mirror.graphics.tables.clear(); }
        mirror.heaps = std::move(next); });
    if (!Recording()) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        std::vector<ID3D12DescriptorHeap*> next;
        if (heaps) next.assign(heaps,heaps+count);
        if (next != list.heaps) { list.compute.tables.clear(); list.graphics.tables.clear(); }
        list.heaps = std::move(next);
    } catch (...) { Fail("Descriptor heap binding failed"); }
}
void RootView(ID3D12GraphicsCommandList* cmd, bool graphics, UINT index, UINT kind, D3D12_GPU_VIRTUAL_ADDRESS va) noexcept
{
    Mirrored(cmd,[&](Mirror& mirror) { (graphics ? mirror.graphics : mirror.compute).views[index] = {kind,va}; });
    if (!Recording()) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        (graphics ? list.graphics : list.compute).views[index] = {kind,va};
    } catch (...) { Fail("Root GPU virtual address binding failed"); }
}
void Table(ID3D12GraphicsCommandList* cmd, bool graphics, UINT index, D3D12_GPU_DESCRIPTOR_HANDLE handle) noexcept
{
    Mirrored(cmd,[&](Mirror& mirror) { (graphics ? mirror.graphics : mirror.compute).tables[index] = handle.ptr; });
    if (!Recording()) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        (graphics ? list.graphics : list.compute).tables[index] = handle.ptr;
    } catch (...) { Fail("Root table binding metadata failed"); }
}
void RenderTargets(ID3D12GraphicsCommandList* cmd, UINT count, const D3D12_CPU_DESCRIPTOR_HANDLE* handles, BOOL contiguous) noexcept
{
    if (!Recording()) return;
    try
    {
        std::scoped_lock record(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd); list.targets.clear();
        std::scoped_lock lifetime(gLifetimeMutex);
        UINT stride = 0;
        if (contiguous && count && handles)
            for (const auto& [key,heap] : gHeaps)
                if (handles[0].ptr >= heap.cpu && handles[0].ptr-heap.cpu < uint64_t(heap.count)*heap.increment)
                { stride = heap.increment; break; }
        for (UINT i=0;handles && i<count;++i)
        {
            const auto handle = contiguous ? handles[0].ptr+uint64_t(i)*stride : handles[i].ptr;
            const auto found = gViews.find(handle); if (found != gViews.end()) list.targets.push_back(found->second);
            else Count("RTV_descriptor_unavailable");
        }
    } catch (...) { Fail("Render target binding metadata failed"); }
}
void Barrier(ID3D12GraphicsCommandList* cmd, UINT count, const D3D12_RESOURCE_BARRIER* barriers) noexcept
{
    if (!Recording() || !barriers) return;
    try
    {
        std::scoped_lock record(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        std::vector<std::pair<ViewInfo,D3D12_RESOURCE_STATES>> exits;
        {
        std::scoped_lock lifetime(gLifetimeMutex);
        for (UINT i=0;i<count;++i)
        {
            const auto& b = barriers[i];
            if (b.Type == D3D12_RESOURCE_BARRIER_TYPE_ALIASING)
            {
                gService->manifest["aliasing"].push_back({{"list_id",list.id},{"after_local_pass",gNextPass},
                    {"before",uint64_t(reinterpret_cast<uintptr_t>(b.Aliasing.pResourceBefore))},
                    {"after",uint64_t(reinterpret_cast<uintptr_t>(b.Aliasing.pResourceAfter))}});
                continue; // Snapshots were already copied before this alias barrier.
            }
            if (b.Type != D3D12_RESOURCE_BARRIER_TYPE_TRANSITION || !b.Transition.pResource) continue;
            auto& r = Register(b.Transition.pResource);
            const UINT first = b.Transition.Subresource == D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES ? 0 : b.Transition.Subresource;
            const UINT last = b.Transition.Subresource == D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES ?
                UINT(r.desc.MipLevels)*r.desc.DepthOrArraySize : first+1;
            for (UINT sub=first;sub<last;++sub)
            {
                const auto key = std::make_pair(r.id,sub);
                const auto writable = D3D12_RESOURCE_STATE_UNORDERED_ACCESS | D3D12_RESOURCE_STATE_RENDER_TARGET;
                const auto imageKey = "r"+std::to_string(r.id)+"s"+std::to_string(sub);
                if (b.Flags == D3D12_RESOURCE_BARRIER_FLAG_NONE && (b.Transition.StateBefore&writable) &&
                    !(b.Transition.StateAfter&writable) && (!list.copied.contains(imageKey) || list.copied[imageKey] != list.lastPass))
                {
                    ViewInfo view {r.object,r.id,6,uint32_t(r.desc.Format),sub,true};
                    for (auto handle : r.handles)
                        if (gViews.at(handle).snapshotSupported && gViews.at(handle).subresource == sub)
                        { view.format = gViews.at(handle).format; break; }
                    exits.push_back({view,b.Transition.StateBefore});
                }
                if (b.Flags&D3D12_RESOURCE_BARRIER_FLAG_BEGIN_ONLY) { list.splitTransitions.insert(key); list.states.erase(key); }
                else { list.states[key] = b.Transition.StateAfter; list.splitTransitions.erase(key); }
            }
        }
        } // release resource lifetime lock before allocating readback storage
        for (const auto& [view,state] : exits)
        {
            const auto key = "r"+std::to_string(view.resource)+"s"+std::to_string(view.subresource);
            if (CopyImage(cmd,list,view,state,key,false) && !list.passes.empty())
                list.passes.back()["write_state_exit_candidates"].push_back({{"resource",view.resource},
                    {"subresource",view.subresource},{"view_format",view.format},{"writer_identity_inferred",true}});
        }
    } catch (...) { Fail("Resource barrier metadata failed"); }
}
void Event(ID3D12GraphicsCommandList* cmd, UINT metadata, const void* data, UINT size, int kind) noexcept
{
    if (!Recording()) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        if (kind < 0) { if (!list.events.empty()) list.events.pop_back(); return; }
        const auto decoded = FrameSurveyMetadata::DecodeMarker(metadata,data,size);
        if (decoded.first.empty()) Count("marker_decode_unavailable");
        list.marker = decoded.first;
        if (kind > 0 && list.events.size() < 64) list.events.push_back(decoded.first);
        if (gService->manifest["markers"].size() < 8192)
        {
            std::string hex; const auto* bytes = static_cast<const uint8_t*>(data);
            for (UINT i=0;bytes && i<std::min(size,512u);++i)
            { hex.push_back("0123456789abcdef"[bytes[i]>>4]); hex.push_back("0123456789abcdef"[bytes[i]&15]); }
            gService->manifest["markers"].push_back({{"list_id",list.id},{"metadata",metadata},{"kind",kind},
                {"text",decoded.first},{"encoding",decoded.second},{"raw_hex",hex},{"raw_bytes",size},
                {"format_arguments_expanded",false}});
        }
    } catch (...) { Fail("Debug event metadata failed"); }
}
void Pass(ID3D12GraphicsCommandList* cmd, const char* kind, std::span<const uint64_t> args) noexcept
{
    if (!Recording()) return;
    try
    {
        std::scoped_lock record(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        if (gNextPass >= 16384) { Fail("One-frame pass cap reached (16384)"); return; }
        const bool graphics = std::string_view(kind).find("Draw") == 0 || std::string_view(kind) == "ExecuteBundle" || (std::string_view(kind) == "ExecuteIndirect" && args.size()>5 && args[5]);
        Json unresolved = Json::array(); auto bindings = Bindings(list,graphics,unresolved);
        list.writes.clear(); Json reads = Json::array(), writes = Json::array();
        {
            std::scoped_lock lifetime(gLifetimeMutex);
            for (const auto& binding : bindings)
            {
                const auto found = gResources.find(binding.object);
                if (found == gResources.end() || found->second.id != binding.resource) { unresolved.push_back("stale_resource"); continue; }
                Describe(found->second);
                const auto row = Json{{"resource",binding.resource},{"subresource",binding.subresource},
                    {"kind",binding.kind},{"view_format",binding.format},{"snapshot_supported",binding.snapshotSupported},
                    {"descriptor_cpu",binding.descriptorCpu},{"descriptor_gpu",binding.descriptorGpu},
                    {"descriptor_heap",binding.descriptorHeap},{"descriptor_index",binding.descriptorIndex},
                    {"root_parameter",binding.rootIndex},{"root_gpu_va",binding.rootVa}};
                if (binding.kind == D3D12_DESCRIPTOR_RANGE_TYPE_UAV || binding.kind == 4)
                { writes.push_back(row); list.writes.push_back(binding); }
                else reads.push_back(row);
            }
        }
        if (!unresolved.empty()) Count("pass_binding_resolution_incomplete");
        auto& root = graphics ? list.graphics : list.compute;
        const uint64_t id = ++gNextPass; list.lastPass = id;
        Json row = {{"local_pass",id},{"kind",kind},{"arguments",std::vector<uint64_t>(args.begin(),args.end())},{"pso",list.pso},
            {"root_signature_pointer",root.identity},{"root_signature_sha256",root.layout.hash},
            {"events",list.events},{"marker",list.marker},{"reads",reads},{"writes",writes},
            {"binding_semantics","potential_access_from_bound_views_not_shader_instruction_proof"},
            {"unresolved",unresolved}};
        if (std::string_view(kind) == "ExecuteBundle") Count("bundle_inherited_binding_usage_unknown");
        if (!list.pso.value("hash_known",false)) Count("pass_shader_hash_unavailable");
        list.targeted = Targeted(list.pso);
        if (list.targeted) { row["targeted_snapshot"] = true; Count("targeted_passes"); }
        list.passes.push_back(std::move(row));
        // Root CBV bytes aid NRD-version/encoding investigation. Size is unknown
        // for a root descriptor, so save a bounded 1 KiB prefix, explicitly labelled.
        for (const auto& [index,view] : root.views)
        {
            // Targeted passes get their own allowance: their constants decode the denoiser's settings.
            if (view.first != D3D12_DESCRIPTOR_RANGE_TYPE_CBV || gService->constantReads >= (list.targeted ? 192u : 64u)) continue;
            ComPtr<ID3D12Resource> object; uint64_t offset = 0; uint32_t bytes = 0;
            {
                std::scoped_lock lifetime(gLifetimeMutex); auto upper = gAddresses.upper_bound(view.second);
                if (upper == gAddresses.begin()) continue;
                const auto found = gResources.find(std::prev(upper)->second);
                if (found == gResources.end() || view.second-found->second.va >= found->second.desc.Width) continue;
                object = found->first; offset = view.second-found->second.va;
                bytes = UINT(std::min<uint64_t>(1024,found->second.desc.Width-offset));
            }
            const auto key = "cbv_p"+std::to_string(list.lastPass)+"i"+std::to_string(index);
            const bool copied = CopyBuffer(cmd,list,object.Get(),key,offset,bytes);
            ++gService->constantReads;
            list.passes.back()["root_constant_buffers"].push_back({{"root_parameter",index},{"snapshot_key",key},
                {"available",copied},{"bytes",bytes},{"prefix_only",true},{"gpu_va",view.second}});
        }
    } catch (...) { Fail("Pass metadata allocation failed"); }
}
void SnapshotWrites(ID3D12GraphicsCommandList* cmd) noexcept
{
    if (!Recording()) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        if (list.inRenderPass) { list.targeted = false; return; } // CopyTextureRegion is illegal inside a render pass.
        const std::string prefix = list.targeted ? "p"+std::to_string(list.lastPass)+"_" : std::string();
        for (const auto& view : list.writes)
        {
            const auto expected = view.kind == 4 ? D3D12_RESOURCE_STATE_RENDER_TARGET : D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
            auto state = expected;
            const auto found = list.states.find({view.resource,view.subresource});
            if (found != list.states.end()) state = found->second;
            // A texture written through a UAV by a dispatch must be in UNORDERED_ACCESS (no implicit promotion);
            // only targeted passes rely on that rule, their barrier may precede the recorded frame.
            else if (!list.targeted || view.kind != D3D12_DESCRIPTOR_RANGE_TYPE_UAV)
            { Count("bound_write_state_unproven_snapshot_skipped"); continue; }
            else Count("targeted_snapshot_state_from_uav_binding");
            if ((state&expected) == 0)
            { Count("bound_write_state_mismatch_snapshot_skipped"); continue; }
            CopyImage(cmd,list,view,state,
                prefix+"r"+std::to_string(view.resource)+"s"+std::to_string(view.subresource),false);
        }
        list.writes.clear(); list.targeted = false;
    } catch (...) { Fail("Last-writer texture snapshot failed"); }
}
void Submit(ID3D12CommandQueue* queue, UINT count, ID3D12CommandList* const* commands) noexcept
{
    if (!Recording() || !commands) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return; Json ids = Json::array();
        for (UINT i=0;i<count;++i)
        {
            auto* cmd = reinterpret_cast<ID3D12GraphicsCommandList*>(commands[i]);
            const auto found = gService->lists.find(cmd);
            if (found == gService->lists.end()) { Count("submitted_list_not_recorded"); ids.push_back(nullptr); continue; }
            const auto& list = found->second; ids.push_back(list.id);
            gService->manifest["command_lists"].push_back({{"id",list.id},{"pointer",uint64_t(reinterpret_cast<uintptr_t>(cmd))},
                {"type",uint32_t(commands[i]->GetType())},{"reset_observed",list.resetObserved},{"closed",list.closed},
                {"passes",list.passes}});
        }
        gService->manifest["batches"].push_back({{"submission",gService->manifest["batches"].size()},
            {"queue",uint64_t(reinterpret_cast<uintptr_t>(queue))},{"queue_type",uint32_t(queue->GetDesc().Type)},{"lists",ids}});
    } catch (...) { Fail("Submission metadata allocation failed"); }
}
Status GetStatus()
{
    std::scoped_lock lock(gRecordMutex); auto result = gStatus;
    if (gService)
    {
        const auto trace = gService->trace.SurveyStatus(); result.folder = trace.folder;
        result.active = gService->requested || gService->recording || trace.active;
        if (!gService->requested && !gService->recording) { result.phase = trace.phase; result.message = trace.message; }
    }
    return result;
}
bool Request(uint32_t width, uint32_t height) noexcept
{
    if (!Enabled()) return false;
    try
    {
        std::scoped_lock lock(gRecordMutex);
        if (!width) width = gRenderWidth; if (!height) height = gRenderHeight;
        if (!gService) gService = std::make_unique<Service>();
        if (gService->trace.SurveyStatus().active || gService->recording || gService->requested) return false;
        if (!gService->trace.StartSurvey(width,height))
        { gStatus.message = "Render size unavailable, GAME_TRACE busy, or earlier GPU resources await Reset."; return false; }
        gRenderWidth = width; gRenderHeight = height; gService->requested = true;
        gService->startTick = GetTickCount64(); gStatus.active = true;
        gStatus.phase = "armed"; gStatus.message = "Waiting for a real Present boundary; close the overlay.";
        LOG_INFO("[FRAME_SURVEY] armed {}x{}",width,height); return true;
    } catch (...) { Fail("Survey request failed"); return false; }
}
void Present(IDXGISwapChain* swapchain, UINT flags) noexcept
{
    if (!Enabled() || (flags&DXGI_PRESENT_TEST)) return;
    try
    {
        std::scoped_lock submission(gSubmissionMutex);
        std::scoped_lock lock(gRecordMutex);
        if (!gService) return;
        if (gService->recording)
        {
            if (gService->swapchain != swapchain) return;
            ++gService->presents;
            if (TargetsConfigured() && !gService->targetedCopies && gService->presents < 8)
            { Count("targeted_mode_window_extended_presents"); return; }
            gService->manifest["presents_in_window"] = gService->presents;
            gService->recording = false; gRecording.store(false,std::memory_order_release);
            gService->manifest["resources"] = Json::array();
            for (const auto& [id,resource] : gService->resources) gService->manifest["resources"].push_back(resource);
            gService->manifest["end_tick_ms"] = GetTickCount64();
            gService->trace.FinishSurvey(gService->manifest.dump());
            gService->lists.clear(); gService->resources.clear(); gService->manifest = Json::object();
            gStatus.phase = "draining"; gStatus.message = "Waiting for verified GPU snapshots and background disk writes.";
            LOG_INFO("[FRAME_SURVEY] frame recorded; draining asynchronously");
        }
        else if (gService->requested && gService->trace.SurveyStatus().phase == "requested")
        {
            ComPtr<ID3D12Device> device;
            if (FAILED(swapchain->GetDevice(IID_PPV_ARGS(&device)))) device = gCreationDevice;
            if (!device) { Fail("Present has no D3D12 creation device"); return; }
            gService->device = device; gService->swapchain = swapchain;
            gService->requested = false; gService->recording = true;
            gService->lists.clear(); gService->resources.clear(); gService->candidates.clear();
            gService->candidateBytes = 0; gNextPass = 0;
            gService->constantReads = 0; gService->targetedCopies = 0; gService->presents = 0;
            gService->manifest = {{"capture_start","previous_real_Present"},{"capture_end","next_real_Present"},
                {"start_tick_ms",GetTickCount64()},{"batches",Json::array()},{"command_lists",Json::array()},
                {"snapshots",Json::array()},{"tags",Json::array()},{"markers",Json::array()},
                {"aliasing",Json::array()},{"coverage_gaps",Json::object()},
                {"candidate_limit",96},{"candidate_budget_bytes",192ull<<20},{"tag_reserved_bytes",64ull<<20},
                {"ordering","serialized_execute_hook_entry_order; cross_queue_GPU_dependencies_are_not_reconstructed"},
                {"snapshot_scope","immediate_post_potential_write_or_proven_write_state_exit; last_observed_content_per_resource_subresource_per_list"},
                {"shader_hash_algorithm","SHA256_of_DXIL_or_DXBC_bytecode_per_stage"},
                {"root_signature_hash_algorithm","SHA256_of_canonical_serialized_version_1_1_root_signature"},
                {"encoding_identification","unknown_until_offline_evidence"}};
            gRecording.store(true,std::memory_order_release);
            gStatus.phase = "recording"; gStatus.message = "Surveying one frame.";
            LOG_INFO("[FRAME_SURVEY] started at Present");
        }
        else if (gService->requested && GetTickCount64()-gService->startTick > 10000)
            Fail("Survey destination did not become ready within 10 seconds");
        else if (gService->trace.SurveyStatus().active && GetTickCount64()-gService->startTick > 30000)
            Fail("Survey GPU/disk drain did not complete within 30 seconds; uncertain GPU storage remains quarantined until Reset");
    } catch (...) { Fail("Present frame boundary failed"); }
}
void Evaluate(ID3D12GraphicsCommandList* cmd, unsigned feature, const NVSDK_NGX_Parameter* params) noexcept
{
    if (!Enabled() || gInternal || !params || !cmd ||
        (feature != unsigned(NVSDK_NGX_Feature_SuperSampling) && feature != unsigned(NVSDK_NGX_Feature_RayReconstruction))) return;
    try
    {
        UINT width = 0, height = 0;
        params->Get(NVSDK_NGX_Parameter_DLSS_Render_Subrect_Dimensions_Width,&width);
        params->Get(NVSDK_NGX_Parameter_DLSS_Render_Subrect_Dimensions_Height,&height);
        if (!width) params->Get(NVSDK_NGX_Parameter_Width,&width);
        if (!height) params->Get(NVSDK_NGX_Parameter_Height,&height);
        std::scoped_lock lock(gRecordMutex);
        if (width && height)
        {
            if (Recording() && (width != gRenderWidth || height != gRenderHeight))
            { Fail("Render extent changed inside the surveyed frame"); return; }
            gRenderWidth = width; gRenderHeight = height;
        }
        if (!Recording()) return;
        auto& list = GetList(cmd);
        const bool rr = feature == unsigned(NVSDK_NGX_Feature_RayReconstruction);
        gService->manifest["evaluate_entries"].push_back({{"entry","NVSDK_NGX_D3D12_EvaluateFeature"},
            {"feature",feature},{"rr_feature",rr},{"list_id",list.id},{"after_local_pass",gNextPass},
            {"render_extent",{width,height}}});
        struct Tag { const char* name; const char* key; const char* bx; const char* by; };
        const Tag tags[] = {
            {"Color",NVSDK_NGX_Parameter_Color,NVSDK_NGX_Parameter_DLSS_Input_Color_Subrect_Base_X,NVSDK_NGX_Parameter_DLSS_Input_Color_Subrect_Base_Y},
            {"Depth",NVSDK_NGX_Parameter_Depth,NVSDK_NGX_Parameter_DLSS_Input_Depth_Subrect_Base_X,NVSDK_NGX_Parameter_DLSS_Input_Depth_Subrect_Base_Y},
            {"MotionVectors",NVSDK_NGX_Parameter_MotionVectors,NVSDK_NGX_Parameter_DLSS_Input_MV_SubrectBase_X,NVSDK_NGX_Parameter_DLSS_Input_MV_SubrectBase_Y},
            {"Normals",NVSDK_NGX_Parameter_GBuffer_Normals,NVSDK_NGX_Parameter_DLSS_Input_Normals_Subrect_Base_X,NVSDK_NGX_Parameter_DLSS_Input_Normals_Subrect_Base_Y},
            {"DiffuseAlbedo",NVSDK_NGX_Parameter_DiffuseAlbedo,NVSDK_NGX_Parameter_DLSS_Input_DiffuseAlbedo_Subrect_Base_X,NVSDK_NGX_Parameter_DLSS_Input_DiffuseAlbedo_Subrect_Base_Y},
            {"SpecularAlbedo",NVSDK_NGX_Parameter_SpecularAlbedo,NVSDK_NGX_Parameter_DLSS_Input_SpecularAlbedo_Subrect_Base_X,NVSDK_NGX_Parameter_DLSS_Input_SpecularAlbedo_Subrect_Base_Y}
        };
        for (const auto& tag : tags)
        {
            ID3D12Resource* object = nullptr; params->Get(tag.key,&object);
            UINT x = 0, y = 0; if (tag.bx) params->Get(tag.bx,&x); if (tag.by) params->Get(tag.by,&y);
            Json row = {{"name",tag.name},{"parameter",tag.key},{"bound",object != nullptr},{"list_id",list.id},{"base",{x,y}}};
            if (object)
            {
                ViewInfo view; D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COMMON; bool known = false;
                {
                    std::scoped_lock lifetime(gLifetimeMutex); auto& resource = Register(object); Describe(resource);
                    view = {object,resource.id,D3D12_DESCRIPTOR_RANGE_TYPE_SRV,uint32_t(resource.desc.Format),0,true};
                    row["resource"] = resource.id;
                    const auto observed = list.states.find({resource.id,0});
                    if (observed != list.states.end()) { known = true; state = observed->second; }
                }
                row["state_observed_in_current_list"] = known;
                // Never guess a title texture state merely because NGX tagged it.
                if (known)
                {
                    const std::string key = "tag_"+std::string(tag.name)+"_r"+std::to_string(view.resource);
                    row["snapshot_key"] = key;
                    row["snapshot_available"] = CopyImage(cmd,list,view,state,key,true,x,y,width,height);
                }
                else { row["snapshot_available"] = false; Count("tag_state_unavailable"); }
            }
            gService->manifest["tags"].push_back(std::move(row));
        }
    } catch (...) { Fail("NGX entry/tag capture failed"); }
}
void TitleTag(ID3D12GraphicsCommandList* cmd, const char* name, ID3D12Resource* object, uint32_t state,
    uint32_t x, uint32_t y, uint32_t width, uint32_t height) noexcept
{
    if (!Recording() || !cmd) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return;
        auto& list = GetList(cmd);
        Json row = {{"name",name},{"source","current_Streamline_tag_call"},{"bound",object != nullptr},
            {"list_id",list.id},{"base",{x,y}},{"extent",{width,height}},
            {"state_provenance","caller_declared_Streamline_tag; no_cached_pointer_reuse"},
            {"content_stage","tag_call_before_Streamline_evaluation; may_precede_later_title_writes"}};
        if (object)
        {
            ViewInfo view;
            {
                std::scoped_lock lifetime(gLifetimeMutex); auto& resource = Register(object); Describe(resource);
                view = {object,resource.id,D3D12_DESCRIPTOR_RANGE_TYPE_SRV,uint32_t(resource.desc.Format),0,true};
            }
            row["resource"] = view.resource;
            const std::string key = "sl_"+std::string(name)+"_r"+std::to_string(view.resource);
            row["snapshot_key"] = key;
            // Only shader-readable, COPY_SOURCE or COMMON declarations are
            // copied; writable/incomplete tag contracts remain metadata only.
            const bool readable = (state&(D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE |
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_COPY_SOURCE)) != 0 || state == 0;
            row["snapshot_available"] = readable && CopyImage(cmd,list,view,D3D12_RESOURCE_STATES(state),key,true,x,y,width,height);
            if (!row["snapshot_available"].get<bool>()) Count("Streamline_tag_snapshot_unavailable");
        }
        gService->manifest["tags"].push_back(std::move(row));
    } catch (...) { Fail("Current Streamline tag observation failed"); }
}

namespace
{
using IndirectFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*,ID3D12CommandSignature*,UINT,
    ID3D12Resource*,UINT64,ID3D12Resource*,UINT64);
using CopyResourceFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*,ID3D12Resource*,ID3D12Resource*);
using CopyTextureFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*,const D3D12_TEXTURE_COPY_LOCATION*,UINT,UINT,UINT,
    const D3D12_TEXTURE_COPY_LOCATION*,const D3D12_BOX*);
using RootViewFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*,UINT,D3D12_GPU_VIRTUAL_ADDRESS);
using SignatureFn = HRESULT(STDMETHODCALLTYPE*)(ID3D12Device*,const D3D12_COMMAND_SIGNATURE_DESC*,ID3D12RootSignature*,REFIID,void**);
using BeginRenderFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList4*,UINT,const D3D12_RENDER_PASS_RENDER_TARGET_DESC*,
    const D3D12_RENDER_PASS_DEPTH_STENCIL_DESC*,D3D12_RENDER_PASS_FLAGS);
using EndRenderFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList4*);
using RaysFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList4*,const D3D12_DISPATCH_RAYS_DESC*);
using RayPipelineFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList4*,ID3D12StateObject*);
IndirectFn oIndirect = nullptr;
CopyResourceFn oCopyResource = nullptr;
CopyTextureFn oCopyTexture = nullptr;
RootViewFn oGraphicsSrv = nullptr, oGraphicsUav = nullptr, oGraphicsCbv = nullptr;
SignatureFn oSignature = nullptr;
BeginRenderFn oBeginRender = nullptr;
EndRenderFn oEndRender = nullptr;
RaysFn oRays = nullptr;
RayPipelineFn oRayPipeline = nullptr;
// Cyberpunk loads most pipelines from an ID3D12PipelineLibrary (GamePipelineLibrary.cache), which bypasses
// the Create*PipelineState hooks; the Load* calls carry the same descriptions, so they are hashed here.
using CreateLibraryFn = HRESULT(STDMETHODCALLTYPE*)(ID3D12Device1*,const void*,SIZE_T,REFIID,void**);
using LoadGraphicsFn = HRESULT(STDMETHODCALLTYPE*)(ID3D12PipelineLibrary*,LPCWSTR,const D3D12_GRAPHICS_PIPELINE_STATE_DESC*,REFIID,void**);
using LoadComputeFn = HRESULT(STDMETHODCALLTYPE*)(ID3D12PipelineLibrary*,LPCWSTR,const D3D12_COMPUTE_PIPELINE_STATE_DESC*,REFIID,void**);
using LoadStreamFn = HRESULT(STDMETHODCALLTYPE*)(ID3D12PipelineLibrary1*,LPCWSTR,const D3D12_PIPELINE_STATE_STREAM_DESC*,REFIID,void**);
CreateLibraryFn oCreateLibrary = nullptr;
LoadGraphicsFn oLoadGraphics = nullptr;
LoadComputeFn oLoadCompute = nullptr;
LoadStreamFn oLoadStream = nullptr;
std::mutex gLibraryHookMutex;
HRESULT STDMETHODCALLTYPE LoadGraphics(ID3D12PipelineLibrary* library, LPCWSTR name, const D3D12_GRAPHICS_PIPELINE_STATE_DESC* desc,
    REFIID riid, void** pso)
{
    const auto result = oLoadGraphics(library,name,desc,riid,pso);
    if (SUCCEEDED(result) && desc && pso && *pso && riid == __uuidof(ID3D12PipelineState))
        PipelineCreated(static_cast<ID3D12PipelineState*>(*pso),*desc);
    return result;
}
HRESULT STDMETHODCALLTYPE LoadCompute(ID3D12PipelineLibrary* library, LPCWSTR name, const D3D12_COMPUTE_PIPELINE_STATE_DESC* desc,
    REFIID riid, void** pso)
{
    const auto result = oLoadCompute(library,name,desc,riid,pso);
    if (SUCCEEDED(result) && desc && pso && *pso && riid == __uuidof(ID3D12PipelineState))
        PipelineCreated(static_cast<ID3D12PipelineState*>(*pso),*desc);
    return result;
}
HRESULT STDMETHODCALLTYPE LoadStream(ID3D12PipelineLibrary1* library, LPCWSTR name, const D3D12_PIPELINE_STATE_STREAM_DESC* desc,
    REFIID riid, void** pso)
{
    const auto result = oLoadStream(library,name,desc,riid,pso);
    if (SUCCEEDED(result) && desc && pso && *pso && riid == __uuidof(ID3D12PipelineState))
        PipelineCreated(static_cast<ID3D12PipelineState*>(*pso),*desc);
    return result;
}
void HookLibrary(IUnknown* object) noexcept
{
    try
    {
        std::scoped_lock lock(gLibraryHookMutex);
        if (oLoadGraphics) return;
        ComPtr<ID3D12PipelineLibrary> library;
        if (FAILED(object->QueryInterface(IID_PPV_ARGS(&library)))) return;
        auto** table = *reinterpret_cast<void***>(library.Get());
        oLoadGraphics = reinterpret_cast<LoadGraphicsFn>(table[9]);
        oLoadCompute = reinterpret_cast<LoadComputeFn>(table[10]);
        ComPtr<ID3D12PipelineLibrary1> library1;
        if (SUCCEEDED(object->QueryInterface(IID_PPV_ARGS(&library1))))
            oLoadStream = reinterpret_cast<LoadStreamFn>((*reinterpret_cast<void***>(library1.Get()))[13]);
        LONG result = DetourTransactionBegin();
        if (result == NO_ERROR) result = DetourUpdateThread(GetCurrentThread());
        if (result == NO_ERROR) result = DetourAttach(reinterpret_cast<PVOID*>(&oLoadGraphics),reinterpret_cast<PVOID>(LoadGraphics));
        if (result == NO_ERROR) result = DetourAttach(reinterpret_cast<PVOID*>(&oLoadCompute),reinterpret_cast<PVOID>(LoadCompute));
        if (result == NO_ERROR && oLoadStream) result = DetourAttach(reinterpret_cast<PVOID*>(&oLoadStream),reinterpret_cast<PVOID>(LoadStream));
        if (result == NO_ERROR) result = DetourTransactionCommit(); else DetourTransactionAbort();
        if (result != NO_ERROR)
        {
            oLoadGraphics = nullptr; oLoadCompute = nullptr; oLoadStream = nullptr;
            LOG_ERROR("[FRAME_SURVEY] pipeline library load hooks failed: {:X}",result); return;
        }
        LOG_INFO("[FRAME_SURVEY] pipeline library loads hooked (stream {})",oLoadStream != nullptr);
    } catch (...) { LOG_ERROR("[FRAME_SURVEY] pipeline library hook exception"); }
}
HRESULT STDMETHODCALLTYPE CreateLibrary(ID3D12Device1* device, const void* blob, SIZE_T length, REFIID riid, void** library)
{
    const auto result = oCreateLibrary(device,blob,length,riid,library);
    if (SUCCEEDED(result) && library && *library && Tracking() && !gInternal) HookLibrary(static_cast<IUnknown*>(*library));
    return result;
}
const GUID SignatureId ={0xe971fb40,0x45a2,0x41ea,{0xa1,0x55,0x64,0xa8,0xc7,0xa4,0xfd,0x11}};
const GUID SignatureLayoutId = {0xe971fb41,0x45a2,0x41ea,{0xa1,0x55,0x64,0xa8,0xc7,0xa4,0xfd,0x11}};
void STDMETHODCALLTYPE Indirect(ID3D12GraphicsCommandList* cmd, ID3D12CommandSignature* signature, UINT count,
    ID3D12Resource* arguments, UINT64 argumentOffset, ID3D12Resource* counts, UINT64 countOffset)
{
    uint32_t graphics = 0; UINT bytes = sizeof(graphics);
    if (signature) signature->GetPrivateData(SignatureId,&bytes,&graphics);
    const std::array<uint64_t,6> args {count,uint64_t(reinterpret_cast<uintptr_t>(arguments)),argumentOffset,
        uint64_t(reinterpret_cast<uintptr_t>(counts)),countOffset,graphics};
    Json layout = Json::object();
    if (Recording())
    {
        try
        {
            std::scoped_lock lock(gRecordMutex);
            if (Recording())
            {
                UINT length = 0;
                if (signature && SUCCEEDED(signature->GetPrivateData(SignatureLayoutId,&length,nullptr)) && length && length < 65536)
                {
                    std::string text(length,'\0');
                    if (SUCCEEDED(signature->GetPrivateData(SignatureLayoutId,&length,text.data()))) layout = Json::parse(text);
                }
                auto& list = GetList(cmd);
                // ExecuteIndirect changes these addresses per GPU command and
                // resets the affected root arguments afterwards. Do not attribute
                // its accesses, or the next pass's accesses, to stale CPU bindings.
                for (const auto& arg : layout.value("arguments",Json::array()))
                    if (arg.value("type",0u) >= 6 && arg.value("type",0u) <= 8)
                    {
                        (graphics ? list.graphics : list.compute).views.erase(arg.value("root_parameter",UINT_MAX));
                        Count("indirect_dynamic_root_view_access_unresolved");
                    }
            }
        } catch (...) { Fail("Indirect root argument metadata failed"); }
    }
    Pass(cmd,"ExecuteIndirect",args);
    if (Recording())
    {
        try
        {
            std::scoped_lock lock(gRecordMutex);
            if (Recording())
            {
                auto& list = GetList(cmd);
                const uint32_t stride = layout.value("byte_stride",0u);
                const uint32_t bytes = UINT(std::min<uint64_t>(65536,uint64_t(stride)*count));
                const auto key = "indirect_p"+std::to_string(list.lastPass);
                const bool copied = stride && CopyBuffer(cmd,list,arguments,key,argumentOffset,bytes);
                const bool countCopied = !counts || CopyBuffer(cmd,list,counts,key+"_count",countOffset,4);
                list.passes.back()["indirect"] = {{"signature",layout},{"argument_key",key},{"arguments_available",copied},
                    {"count_key",key+"_count"},{"count_buffer_present",counts != nullptr},{"count_available",countCopied},
                    {"maximum_command_count",count},{"saved_argument_bytes",bytes},{"argument_snapshot_capped",uint64_t(stride)*count > 65536}};
                if (!copied || !countCopied) Count("indirect_argument_snapshot_unavailable");
            }
        } catch (...) { Fail("Indirect argument capture failed"); }
    }
    // The runtime can expand ExecuteIndirect into internal command lists.
    // Observe this public invocation once; helper recordings are not separate
    // title submissions and must not allocate unfenced survey payloads.
    { InternalScope forwarding; oIndirect(cmd,signature,count,arguments,argumentOffset,counts,countOffset); }
    SnapshotWrites(cmd);
}
void RecordCopy(ID3D12GraphicsCommandList* cmd, ID3D12Resource* dst, UINT subresource, ID3D12Resource* src)
{
    if (!Recording() || !dst) return;
    std::scoped_lock record(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
    ViewInfo write;
    {
        std::scoped_lock lifetime(gLifetimeMutex); auto& resource = Register(dst); Describe(resource);
        write = {dst,resource.id,5,uint32_t(resource.desc.Format),subresource,true};
        Json reads = Json::array();
        if (src) { auto& source = Register(src); Describe(source); reads.push_back({{"resource",source.id}}); }
        list.lastPass = ++gNextPass;
        list.passes.push_back({{"local_pass",list.lastPass},{"kind","Copy"},{"reads",reads},
            {"writes",Json::array({{{"resource",resource.id},{"subresource",subresource}}})},
            {"events",list.events},{"marker",list.marker}});
    }
    const auto observed = list.states.find({write.resource,subresource});
    if (observed == list.states.end() || observed->second != D3D12_RESOURCE_STATE_COPY_DEST)
    { Count("copy_destination_state_unproven_snapshot_skipped"); return; }
    CopyImage(cmd,list,write,D3D12_RESOURCE_STATE_COPY_DEST,
        "r"+std::to_string(write.resource)+"s"+std::to_string(subresource),false);
}
void STDMETHODCALLTYPE CopyResource(ID3D12GraphicsCommandList* cmd, ID3D12Resource* dst, ID3D12Resource* src)
{
    oCopyResource(cmd,dst,src);
    try { RecordCopy(cmd,dst,0,src); } catch (...) { Fail("Resource copy observation failed"); }
}
void STDMETHODCALLTYPE CopyTexture(ID3D12GraphicsCommandList* cmd, const D3D12_TEXTURE_COPY_LOCATION* dst, UINT x, UINT y, UINT z,
    const D3D12_TEXTURE_COPY_LOCATION* src, const D3D12_BOX* box)
{
    oCopyTexture(cmd,dst,x,y,z,src,box);
    if (!dst || dst->Type != D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX) return;
    try { RecordCopy(cmd,dst->pResource,dst->SubresourceIndex,src ? src->pResource : nullptr); }
    catch (...) { Fail("Texture copy observation failed"); }
}
void STDMETHODCALLTYPE GraphicsSrv(ID3D12GraphicsCommandList* cmd, UINT index, D3D12_GPU_VIRTUAL_ADDRESS va)
{ RootView(cmd,true,index,D3D12_DESCRIPTOR_RANGE_TYPE_SRV,va); oGraphicsSrv(cmd,index,va); }
void STDMETHODCALLTYPE GraphicsUav(ID3D12GraphicsCommandList* cmd, UINT index, D3D12_GPU_VIRTUAL_ADDRESS va)
{ RootView(cmd,true,index,D3D12_DESCRIPTOR_RANGE_TYPE_UAV,va); oGraphicsUav(cmd,index,va); }
void STDMETHODCALLTYPE GraphicsCbv(ID3D12GraphicsCommandList* cmd, UINT index, D3D12_GPU_VIRTUAL_ADDRESS va)
{ RootView(cmd,true,index,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,va); oGraphicsCbv(cmd,index,va); }
HRESULT STDMETHODCALLTYPE Signature(ID3D12Device* device, const D3D12_COMMAND_SIGNATURE_DESC* desc,
    ID3D12RootSignature* root, REFIID iid, void** output)
{
    const auto result = oSignature(device,desc,root,iid,output);
    if (SUCCEEDED(result) && desc && output && *output)
    {
        uint32_t graphics = 0;
        for (UINT i=0;i<desc->NumArgumentDescs;++i)
            if (desc->pArgumentDescs[i].Type == D3D12_INDIRECT_ARGUMENT_TYPE_DRAW ||
                desc->pArgumentDescs[i].Type == D3D12_INDIRECT_ARGUMENT_TYPE_DRAW_INDEXED) graphics = 1;
        static_cast<ID3D12CommandSignature*>(*output)->SetPrivateData(SignatureId,sizeof(graphics),&graphics);
        try
        {
            Json layout = {{"byte_stride",desc->ByteStride},{"arguments",Json::array()}};
            for (UINT i=0;i<desc->NumArgumentDescs;++i)
            {
                const auto& a = desc->pArgumentDescs[i]; Json row = {{"type",uint32_t(a.Type)}};
                if (a.Type == D3D12_INDIRECT_ARGUMENT_TYPE_CONSTANT)
                    row.update({{"root_parameter",a.Constant.RootParameterIndex},{"word_offset",a.Constant.DestOffsetIn32BitValues},
                        {"words",a.Constant.Num32BitValuesToSet}});
                else if (a.Type == D3D12_INDIRECT_ARGUMENT_TYPE_CONSTANT_BUFFER_VIEW) row["root_parameter"] = a.ConstantBufferView.RootParameterIndex;
                else if (a.Type == D3D12_INDIRECT_ARGUMENT_TYPE_SHADER_RESOURCE_VIEW) row["root_parameter"] = a.ShaderResourceView.RootParameterIndex;
                else if (a.Type == D3D12_INDIRECT_ARGUMENT_TYPE_UNORDERED_ACCESS_VIEW) row["root_parameter"] = a.UnorderedAccessView.RootParameterIndex;
                layout["arguments"].push_back(std::move(row));
            }
            const auto text = layout.dump();
            static_cast<ID3D12CommandSignature*>(*output)->SetPrivateData(SignatureLayoutId,UINT(text.size()),text.data());
        } catch (...) { Fail("Indirect signature metadata failed"); }
    }
    return result;
}
void STDMETHODCALLTYPE BeginRender(ID3D12GraphicsCommandList4* cmd, UINT count,
    const D3D12_RENDER_PASS_RENDER_TARGET_DESC* targets, const D3D12_RENDER_PASS_DEPTH_STENCIL_DESC* depth, D3D12_RENDER_PASS_FLAGS flags)
{
    if (Recording())
    {
        try
        {
            std::vector<D3D12_CPU_DESCRIPTOR_HANDLE> handles;
            for (UINT i=0;targets && i<count;++i) handles.push_back(targets[i].cpuDescriptor);
            RenderTargets(cmd,UINT(handles.size()),handles.data(),FALSE);
            std::scoped_lock lock(gRecordMutex);
            if (Recording())
            {
                auto& list = GetList(cmd); list.inRenderPass = true;
                for (size_t i=0;i<list.targets.size();++i)
                {
                    const auto found = std::find_if(targets,targets+count,[&](const auto& target) {
                        return target.cpuDescriptor.ptr == list.targets[i].descriptorCpu; });
                    if (found == targets+count || found->EndingAccess.Type != D3D12_RENDER_PASS_ENDING_ACCESS_TYPE_PRESERVE)
                    { list.targets[i].snapshotSupported = false; Count("render_pass_nonpreserved_target_snapshot_skipped"); }
                }
            }
        } catch (...) { Fail("Render pass observation failed"); }
    }
    oBeginRender(cmd,count,targets,depth,flags);
}
void STDMETHODCALLTYPE EndRender(ID3D12GraphicsCommandList4* cmd)
{
    oEndRender(cmd);
    if (Recording())
    {
        try { std::scoped_lock lock(gRecordMutex); if (Recording()) GetList(cmd).inRenderPass = false; }
        catch (...) { Fail("Render pass end observation failed"); }
        SnapshotWrites(cmd);
    }
}
void STDMETHODCALLTYPE RayPipeline(ID3D12GraphicsCommandList4* cmd, ID3D12StateObject* object)
{
    if (Recording())
    {
        try
        {
            std::scoped_lock lock(gRecordMutex);
            if (Recording()) GetList(cmd).pso = {{"pointer",uint64_t(reinterpret_cast<uintptr_t>(object))},
                {"kind","raytracing_state_object"},{"hash_known",false},{"shader_hashes",Json::object()}};
        } catch (...) { Fail("Raytracing state object observation failed"); }
    }
    oRayPipeline(cmd,object);
}
void STDMETHODCALLTYPE Rays(ID3D12GraphicsCommandList4* cmd, const D3D12_DISPATCH_RAYS_DESC* desc)
{
    if (desc)
    {
        const std::array<uint64_t,3> args {desc->Width,desc->Height,desc->Depth};
        Pass(cmd,"DispatchRays",args);
    }
    oRays(cmd,desc); SnapshotWrites(cmd);
}
}
bool Install(ID3D12Device* device, ID3D12GraphicsCommandList* list) noexcept
{
    if (Enabled()) return gStatus.installed;
    if (!device || !list) return false;
    try
    {
        auto** table = *reinterpret_cast<void***>(list);
        auto** dt = *reinterpret_cast<void***>(device);
        oIndirect = reinterpret_cast<IndirectFn>(table[59]);
        oCopyTexture = reinterpret_cast<CopyTextureFn>(table[16]);
        oCopyResource = reinterpret_cast<CopyResourceFn>(table[17]);
        oGraphicsCbv = reinterpret_cast<RootViewFn>(table[38]);
        oGraphicsSrv = reinterpret_cast<RootViewFn>(table[40]);
        oGraphicsUav = reinterpret_cast<RootViewFn>(table[42]);
        oSignature = reinterpret_cast<SignatureFn>(dt[41]);
        ComPtr<ID3D12Device1> device1;
        if (SUCCEEDED(device->QueryInterface(IID_PPV_ARGS(&device1))))
            oCreateLibrary = reinterpret_cast<CreateLibraryFn>((*reinterpret_cast<void***>(device1.Get()))[44]);
        ComPtr<ID3D12GraphicsCommandList4> list4;
        if (SUCCEEDED(list->QueryInterface(IID_PPV_ARGS(&list4))))
        {
            auto** rt = *reinterpret_cast<void***>(list4.Get());
            oBeginRender = reinterpret_cast<BeginRenderFn>(rt[68]);
            oEndRender = reinterpret_cast<EndRenderFn>(rt[69]);
            oRayPipeline = reinterpret_cast<RayPipelineFn>(rt[75]);
            oRays = reinterpret_cast<RaysFn>(rt[76]);
        }
        LONG result = DetourTransactionBegin();
        if (result == NO_ERROR) result = DetourUpdateThread(GetCurrentThread());
        auto attach = [&](auto& original,auto replacement) {
            if (result == NO_ERROR) result = DetourAttach(reinterpret_cast<PVOID*>(&original),reinterpret_cast<PVOID>(replacement)); };
        attach(oIndirect,Indirect); attach(oCopyResource,CopyResource); attach(oCopyTexture,CopyTexture);
        attach(oGraphicsCbv,GraphicsCbv); attach(oGraphicsSrv,GraphicsSrv); attach(oGraphicsUav,GraphicsUav); attach(oSignature,Signature);
        if (oCreateLibrary) attach(oCreateLibrary,CreateLibrary);
        if (list4) { attach(oBeginRender,BeginRender); attach(oEndRender,EndRender); attach(oRayPipeline,RayPipeline); attach(oRays,Rays); }
        if (result == NO_ERROR) result = DetourTransactionCommit(); else DetourTransactionAbort();
        if (result != NO_ERROR)
        {
            oIndirect = nullptr; oCopyResource = nullptr; oCopyTexture = nullptr;
            oGraphicsCbv = oGraphicsSrv = oGraphicsUav = nullptr; oSignature = nullptr; oCreateLibrary = nullptr;
            oBeginRender = nullptr; oEndRender = nullptr; oRayPipeline = nullptr; oRays = nullptr;
            Fail("Survey-only hook installation failed; no capture will be started"); return false;
        }
        gCreationDevice = device;
        gEnabled.store(true,std::memory_order_release); gStatus.installed = true;
        gStatus.phase = "idle"; gStatus.message = "Frame survey enabled at startup; request one frame.";
        LOG_INFO("[FRAME_SURVEY] debug hooks installed; no denoiser dispatch is replaced"); return true;
    } catch (...) { Fail("Survey hook installation exception"); return false; }
}
void Shutdown() noexcept
{
    gTracking.store(false,std::memory_order_release);
    if (!Enabled()) return;
    gEnabled.store(false,std::memory_order_release); gRecording.store(false,std::memory_order_release);
    try
    {
        std::unique_ptr<Service> owner;
        { std::scoped_lock lock(gRecordMutex); owner = std::move(gService); }
        if (owner) { owner->trace.Abort("FRAME_SURVEY device/owner shutdown"); owner.reset(); }
        DetourTransactionBegin(); DetourUpdateThread(GetCurrentThread());
        auto detach = [](auto& original,auto replacement) {
            if (original) DetourDetach(reinterpret_cast<PVOID*>(&original),reinterpret_cast<PVOID>(replacement)); };
        detach(oIndirect,Indirect); detach(oCopyResource,CopyResource); detach(oCopyTexture,CopyTexture);
        detach(oGraphicsCbv,GraphicsCbv); detach(oGraphicsSrv,GraphicsSrv); detach(oGraphicsUav,GraphicsUav); detach(oSignature,Signature);
        detach(oBeginRender,BeginRender); detach(oEndRender,EndRender); detach(oRayPipeline,RayPipeline); detach(oRays,Rays);
        detach(oCreateLibrary,CreateLibrary);
        {
            std::scoped_lock library(gLibraryHookMutex);
            detach(oLoadGraphics,LoadGraphics); detach(oLoadCompute,LoadCompute); detach(oLoadStream,LoadStream);
        }
        DetourTransactionCommit();
        oIndirect = nullptr; oCopyResource = nullptr; oCopyTexture = nullptr;
        oGraphicsCbv = oGraphicsSrv = oGraphicsUav = nullptr; oSignature = nullptr; oCreateLibrary = nullptr;
        oBeginRender = nullptr; oEndRender = nullptr; oRayPipeline = nullptr; oRays = nullptr;
        { std::scoped_lock library(gLibraryHookMutex); oLoadGraphics = nullptr; oLoadCompute = nullptr; oLoadStream = nullptr; }
        { std::scoped_lock mirror(gMirrorMutex); gMirror.clear(); }
        std::scoped_lock lock(gLifetimeMutex); gViews.clear(); gResources.clear(); gAddresses.clear(); gHeaps.clear();
        gCreationDevice.Reset(); gStatus.installed = false;
    } catch (...) {}
}
}
