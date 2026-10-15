#pragma once
#include <d3d12.h>
#include <wrl/client.h>
#include <array>
#include <atomic>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include "misc/NrdBridgeCaptureSlotBudget_Dx12.h"
#include "misc/NrdBridgeOwned_Dx12.h"
#if !defined(FSRD_NRD_BRIDGE_RR_TEST_BACKEND)
#include "State.h"
#endif
#include "precompile/FSRDNrdLobeRecoveryReference_Shader.h"
#include "precompile/FSRDNrdLobeRecoveryDown_Shader.h"
#include "precompile/FSRDNrdLobeRecoveryBand_Shader.h"

namespace NrdBridge
{
// All seven inputs are bridge-owned. Guides/noisy lobes enter and leave in NPS;
// the provider's staged pair enters and leaves in UAV. No title view is accepted.
struct LobeRecoveryInputs
{
    ID3D12Resource *noisySpecular = nullptr, *noisyDiffuse = nullptr;
    ID3D12Resource *depth = nullptr, *motion = nullptr, *normals = nullptr;
    ID3D12Resource *rrSpecular = nullptr, *rrDiffuse = nullptr;
    uint32_t width = 0, height = 0;
};
struct LobeRecoveryFrame
{
    uint32_t frameIndex = 0;
    bool reset = true;
    std::array<float,2> strength {1,1};
    std::array<float,2> jitterPixels {};
    // Exactly the delta already added to RR's normalized primary motion.
    // Reference removes it once; the band-noise reprojection keeps RR motion.
    std::array<float,2> jitterDeltaUv {};
};

// One helper belongs to one continuous physical RR Context. The caller serializes
// Prepare/Record and GPU submissions with that Context's existing causal protocol.
// A failed/canceled RR recording retires the Context, including this helper.
// Prepare performs every fallible operation before the provider. DispatchLease
// MUST retain Prepared.owner before provider work; Record itself cannot retain,
// allocate, validate native objects, or write a borrowed title output.
class LobeRecovery
{
    using ComResource = Microsoft::WRL::ComPtr<ID3D12Resource>;
    static constexpr uint32_t Levels = 6, PassCount = 13, DescriptorCount = 192;
    static constexpr uint32_t HistoryFlag = 1, CoarsestFlag = 2, FinalFlag = 4;
    static constexpr auto ReadState = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    static constexpr auto WriteState = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    static constexpr auto FloatFormat = DXGI_FORMAT_R32G32B32A32_FLOAT;
    static constexpr auto GeometryFormat = DXGI_FORMAT_R32G32B32A32_UINT;

  public:
    enum class Storage : uint8_t { FullPrecision, MixedPrecision };
    struct Family
    {
        // Production supplies the same lazily-created Family from its stable
        // Service across replacement HistoryDomains/RRWrappers/physical Contexts.
        static constexpr uint64_t GraphByteLimit = uint64_t(2) * 1024 * 1024 * 1024;
        NrdBridgeCaptureBudget::Family slots;
        // Includes in-progress reservations and all retained old Contexts.
        std::atomic<uint64_t> graphBytes {0};
        // Monotone metadata-only diagnostics: retained high-water, cold cooldown
        // windows that were set, cold attempts denied while cooling down and
        // failed preparations. Only failure/cold paths touch them.
        std::atomic<uint64_t> retainedPeakBytes {0};
        std::atomic<uint32_t> coldCooldowns {0}, coldRetryDenials {0}, preparationFailures {0};
        std::atomic<uint64_t> retryUntilTick {0};
    };

  private:
    struct GraphCharge
    {
        std::shared_ptr<Family> family;
        uint64_t bytes = 0;
        bool Acquire(const std::shared_ptr<Family>& owner, uint64_t requested) noexcept
        {
            if (!owner || !requested || requested > Family::GraphByteLimit) return false;
            auto total = owner->graphBytes.load(std::memory_order_acquire);
            while (total <= Family::GraphByteLimit - requested)
                if (owner->graphBytes.compare_exchange_weak(total,total+requested,std::memory_order_acq_rel))
                {
                    const uint64_t updated = total+requested; // Retained high-water (old contexts inside).
                    auto peak = owner->retainedPeakBytes.load(std::memory_order_relaxed);
                    while (peak < updated && !owner->retainedPeakBytes.compare_exchange_weak(peak,updated,std::memory_order_relaxed)) {}
                    family = owner; bytes = requested; return true;
                }
            return false;
        }
        ~GraphCharge()
        {
            if (family) family->graphBytes.fetch_sub(bytes,std::memory_order_acq_rel);
        }
    };
    struct alignas(16) Constants
    {
        std::array<float,4> fullSize {}, levelSize {}, lobeStrength {1,1,4,.25f}, pixelJitters {};
        std::array<float,4> temporal {.03f,3,8,8}, surface {.02f,.95f,.025f,.75f};
        std::array<float,4> confidence {6,.0625f,0,0};
        std::array<uint32_t,4> control {};
    };
    static_assert(sizeof(Constants) == 128 && offsetof(Constants,pixelJitters) == 48 &&
        offsetof(Constants,control) == 112);
    struct Pipeline
    {
        Microsoft::WRL::ComPtr<ID3D12RootSignature> root;
        Microsoft::WRL::ComPtr<ID3D12PipelineState> pso;
    };
    struct Pass
    {
        Pipeline* pipeline = nullptr;
        D3D12_GPU_VIRTUAL_ADDRESS constants = 0;
        D3D12_GPU_DESCRIPTOR_HANDLE srv {}, uav {};
        std::array<D3D12_RESOURCE_BARRIER,7> toWrite {}, toRead {};
        uint32_t barriers = 0, width = 0, height = 0;
    };
    struct Slot
    {
        // Permit dies after its COM storage, including allocation-failure unwind.
        NrdBridgeCaptureBudget::Permit permit;
        ComResource constants;
        Microsoft::WRL::ComPtr<ID3D12DescriptorHeap> descriptors;
        uint8_t* mapped = nullptr;
        D3D12_GPU_VIRTUAL_ADDRESS address = 0;
        uint64_t bytes = 0;
        std::array<Pass,PassCount> passes {};
        explicit Slot(NrdBridgeCaptureBudget::Permit&& value) noexcept : permit(std::move(value)) {}
        ~Slot() { if (mapped) constants->Unmap(0,nullptr); }
    };
    struct Context;
    struct Recording
    {
        std::shared_ptr<Context> context;
        std::shared_ptr<Slot> slot;
        std::array<ComResource,7> inputs;
        ID3D12GraphicsCommandList* list = nullptr; // Recording-only borrow.
        uint32_t frame = 0, current = 0;
        bool recorded = false;
    };
    struct Context
    {
        // Declared first: the byte reservation outlives every native resource.
        GraphCharge charge;
        Microsoft::WRL::ComPtr<ID3D12Device> device;
        std::shared_ptr<Family> family;
        Pipeline reference, down, band;
        uint32_t width = 0, height = 0, stride = 0, previous = 1, lastFrame = 0;
        uint64_t recordedFrames = 0;
        bool historyValid = false;
        DXGI_FORMAT floatStorage = FloatFormat;
        std::array<std::array<ComResource,4>,2> history; // spec,diff,gradient,UINT geometry.
        std::array<std::array<ComResource,3>,Levels+1> pyramid;
        std::array<std::array<ComResource,Levels>,2> noise;
        std::array<std::array<ComResource,2>,Levels> correction;
        std::array<ComResource,2> output;
        std::array<std::shared_ptr<Slot>,NrdBridgeCaptureBudget::Family::Capacity> slots {};
        std::weak_ptr<Recording> pending;
    };
    std::shared_ptr<Context> context_;
    const Storage storage_;
    static void DelayColdRetry(Family& family,uint64_t now) noexcept
    {
        family.coldCooldowns.fetch_add(1,std::memory_order_relaxed);
        const uint64_t until = now>UINT64_MAX-1000 ? UINT64_MAX : now+1000;
        auto previous = family.retryUntilTick.load(std::memory_order_acquire);
        while (previous<until && !family.retryUntilTick.compare_exchange_weak(previous,until,std::memory_order_acq_rel)) {}
    }

    struct TexturePlan
    {
        ComResource* output = nullptr;
        D3D12_RESOURCE_DESC description {};
        D3D12_RESOURCE_STATES state = ReadState;
    };
    struct View { ID3D12Resource* resource = nullptr; DXGI_FORMAT format = FloatFormat; };
    static void Check(HRESULT code, const char* operation)
    {
        if (FAILED(code)) throw std::runtime_error(std::string(operation) + " (HRESULT " + std::to_string(code) + ")");
    }
    static void StoreError(std::string& error,const char* text) noexcept
    {
        try { error = text; } catch (...) { error.clear(); }
    }
    static bool SameDevice(ID3D12Device* device, ID3D12Device* other) noexcept
    {
        Microsoft::WRL::ComPtr<IUnknown> a,b;
        return device && other && SUCCEEDED(device->QueryInterface(IID_PPV_ARGS(&a))) &&
            SUCCEEDED(other->QueryInterface(IID_PPV_ARGS(&b))) && a.Get() == b.Get();
    }
    static D3D12_RESOURCE_DESC Texture(uint32_t width,uint32_t height,DXGI_FORMAT format) noexcept
    {
        D3D12_RESOURCE_DESC result {}; result.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        result.Width = width; result.Height = height; result.DepthOrArraySize = result.MipLevels = 1;
        result.SampleDesc.Count = 1; result.Format = format; result.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        return result;
    }
    static void BuildPipeline(ID3D12Device* device,const void* bytes,size_t size,Pipeline& out)
    {
        Check(device->CreateRootSignature(0,bytes,size,IID_PPV_ARGS(&out.root)),"Lobe recovery root creation failed");
        D3D12_COMPUTE_PIPELINE_STATE_DESC desc {}; desc.pRootSignature = out.root.Get(); desc.CS = {bytes,size};
        Check(device->CreateComputePipelineState(&desc,IID_PPV_ARGS(&out.pso)),"Lobe recovery pipeline creation failed");
    }
    static std::shared_ptr<Context> CreateContext(ID3D12Device* device,uint32_t width,uint32_t height,
                                                 const std::shared_ptr<Family>& family,Storage storage)
    {
        auto context = MakeOwnedShared<Context>(); context->device = device; context->family = family;
        context->width = width; context->height = height;
        context->floatStorage = storage==Storage::MixedPrecision ? DXGI_FORMAT_R16G16B16A16_FLOAT : FloatFormat;
        context->stride = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        if (!context->stride) throw std::runtime_error("Lobe recovery descriptor stride is zero");
        std::array<TexturePlan,55> plan {}; uint32_t count = 0;
        const auto append = [&](ComResource& out,uint32_t w,uint32_t h,DXGI_FORMAT format,
                                D3D12_RESOURCE_STATES state = ReadState) {
            auto& item = plan[count++]; item.output = &out; item.description = Texture(w,h,format); item.state = state;
        };
        for (auto& ping : context->history)
            for (uint32_t i=0;i<4;++i) append(ping[i],width,height,i==3 ? GeometryFormat : context->floatStorage);
        uint32_t w = width,h = height;
        for (uint32_t level=0;level<=Levels;++level)
        {
            for (auto& out : context->pyramid[level]) append(out,w,h,context->floatStorage);
            if (level<Levels)
            {
                for (auto& ping : context->noise) append(ping[level],w,h,FloatFormat);
                for (auto& out : context->correction[level]) append(out,w,h,context->floatStorage);
            }
            w = (w+1)/2; h = (h+1)/2;
        }
        // A closed list may be executed again after its fence. Every recorded
        // boundary must therefore have the same first-use and warm-use state.
        for (auto& out : context->output) append(out,width,height,DXGI_FORMAT_R16G16B16A16_FLOAT,WriteState);
        uint64_t bytes = 0;
        for (const auto& item : plan)
        {
            const auto allocation = device->GetResourceAllocationInfo(0,1,&item.description).SizeInBytes;
            if (!allocation || allocation == UINT64_MAX || allocation > UINT64_MAX-bytes)
                throw std::runtime_error("Lobe recovery allocation size is invalid");
            bytes += allocation;
        }
        if (!context->charge.Acquire(family,bytes)) throw std::runtime_error("Lobe recovery shared graph family exceeds2GiB");
        // No native allocation has occurred before the complete reservation.
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        for (auto& item : plan)
            Check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&item.description,item.state,nullptr,
                IID_PPV_ARGS(item.output->GetAddressOf())),"Lobe recovery graph texture allocation failed");
        BuildPipeline(device,FSRDNrdLobeRecoveryReference_cso,sizeof(FSRDNrdLobeRecoveryReference_cso),context->reference);
        BuildPipeline(device,FSRDNrdLobeRecoveryDown_cso,sizeof(FSRDNrdLobeRecoveryDown_cso),context->down);
        BuildPipeline(device,FSRDNrdLobeRecoveryBand_cso,sizeof(FSRDNrdLobeRecoveryBand_cso),context->band);
        return context;
    }
    static std::shared_ptr<Slot> NewSlot(Context& context,NrdBridgeCaptureBudget::Permit&& permit)
    {
        auto slot = MakeOwnedShared<Slot>(std::move(permit));
        D3D12_RESOURCE_DESC desc {}; desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = uint64_t(PassCount)*D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT;
        desc.Height = desc.DepthOrArraySize = desc.MipLevels = 1; desc.SampleDesc.Count = 1;
        desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        const auto allocation = context.device->GetResourceAllocationInfo(0,1,&desc).SizeInBytes;
        if (!slot->permit.SetBytes(allocation)) throw std::runtime_error("Lobe recovery frame allocation size is invalid");
        slot->bytes = allocation;
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_UPLOAD;
        Check(context.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_GENERIC_READ,
            nullptr,IID_PPV_ARGS(&slot->constants)),"Lobe recovery constants allocation failed");
        D3D12_RANGE read {0,0}; Check(slot->constants->Map(0,&read,reinterpret_cast<void**>(&slot->mapped)),"Lobe recovery constants mapping failed");
        slot->address = slot->constants->GetGPUVirtualAddress();
        D3D12_DESCRIPTOR_HEAP_DESC descriptors {}; descriptors.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        descriptors.NumDescriptors = DescriptorCount; descriptors.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        Check(context.device->CreateDescriptorHeap(&descriptors,IID_PPV_ARGS(&slot->descriptors)),"Lobe recovery frame descriptors allocation failed");
        for (auto& target : context.slots) if (!target) { target = slot; return slot; }
        throw std::runtime_error("Lobe recovery context slot capacity is exhausted");
    }
    static NrdBridgeCaptureBudget::Permit ReserveSlot(const std::shared_ptr<Family>& family)
    {
        auto slots = std::shared_ptr<NrdBridgeCaptureBudget::Family>(family,&family->slots);
        auto permit = NrdBridgeCaptureBudget::Permit::TryAcquire(slots);
        if (!permit) throw std::runtime_error("Lobe recovery family has32 retained recording slots");
        return permit;
    }
    static std::shared_ptr<Slot> AcquireSlot(Context& context)
    {
        for (const auto& slot : context.slots) if (slot && slot.use_count()==1) return slot;
        return NewSlot(context,ReserveSlot(context.family));
    }
    static bool Validate(ID3D12Device* device,ID3D12GraphicsCommandList* list,const LobeRecoveryInputs& in,
                         const LobeRecoveryFrame& frame,const std::shared_ptr<Family>& family,std::string& error)
    {
        if (!device || !list || !family || !in.width || !in.height ||
            in.width>D3D12_REQ_TEXTURE2D_U_OR_V_DIMENSION || in.height>D3D12_REQ_TEXTURE2D_U_OR_V_DIMENSION)
        { error = "Lobe recovery device/list/family/extent is invalid"; return false; }
        for (const auto& jitter : {frame.jitterPixels,frame.jitterDeltaUv})
            for (auto value : jitter) if (!std::isfinite(value)) { error = "Lobe recovery jitter is nonfinite"; return false; }
        for (auto value : frame.strength)
            if (!std::isfinite(value) || value<0 || value>1) { error = "Lobe recovery lobe strength is outside0..1"; return false; }
        const auto type = list->GetType();
        if (type!=D3D12_COMMAND_LIST_TYPE_DIRECT && type!=D3D12_COMMAND_LIST_TYPE_COMPUTE)
        { error = "Lobe recovery command list type is unsupported"; return false; }
        Microsoft::WRL::ComPtr<ID3D12Device> other;
        if (FAILED(list->GetDevice(IID_PPV_ARGS(&other))) || !SameDevice(device,other.Get()))
        { error = "Lobe recovery command list device differs"; return false; }
        const std::array<ID3D12Resource*,7> resources {in.noisySpecular,in.noisyDiffuse,in.depth,in.motion,in.normals,in.rrSpecular,in.rrDiffuse};
        constexpr std::array<DXGI_FORMAT,7> formats {DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,
            DXGI_FORMAT_R32_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R10G10B10A2_UNORM,
            DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT};
        for (size_t i=0;i<resources.size();++i)
        {
            if (!resources[i]) { error = "Lobe recovery input is null"; return false; }
            const auto desc = resources[i]->GetDesc();
            if (desc.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.Width!=in.width || desc.Height!=in.height ||
                desc.MipLevels!=1 || desc.DepthOrArraySize!=1 || desc.SampleDesc.Count!=1 || desc.Format!=formats[i] ||
                (desc.Flags&D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) || (i>=5 && !(desc.Flags&D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS)))
            { error = "Lobe recovery input format/extent/SRV contract differs"; return false; }
            other.Reset();
            if (FAILED(resources[i]->GetDevice(IID_PPV_ARGS(&other))) || !SameDevice(device,other.Get()))
            { error = "Lobe recovery input device differs"; return false; }
        }
        if (in.rrSpecular==in.rrDiffuse) { error = "Lobe recovery staged outputs alias"; return false; }
        for (size_t i=0;i<5;++i) if (resources[i]==in.rrSpecular || resources[i]==in.rrDiffuse)
        { error = "Lobe recovery provider output aliases a noisy signal/guide"; return false; }
        return true;
    }
    static void DescribePass(Context& context,Slot& slot,uint32_t passIndex,uint32_t& descriptor,
                             Pipeline& pipeline,Constants constants,const View* reads,uint32_t readCount,
                             const View* writes,uint32_t writeCount,uint32_t transientWrites)
    {
        auto& pass = slot.passes[passIndex]; pass = {}; pass.pipeline = &pipeline;
        pass.constants = slot.address+uint64_t(passIndex)*D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT;
        std::memcpy(slot.mapped+size_t(passIndex)*D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT,&constants,sizeof(constants));
        pass.width = uint32_t(constants.levelSize[0]); pass.height = uint32_t(constants.levelSize[1]);
        auto cpu = slot.descriptors->GetCPUDescriptorHandleForHeapStart(); cpu.ptr += uint64_t(descriptor)*context.stride;
        pass.srv = slot.descriptors->GetGPUDescriptorHandleForHeapStart(); pass.srv.ptr += uint64_t(descriptor)*context.stride;
        for (uint32_t i=0;i<readCount;++i)
        {
            D3D12_SHADER_RESOURCE_VIEW_DESC desc {}; desc.Format = reads[i].format;
            desc.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D; desc.Texture2D.MipLevels = 1;
            desc.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            context.device->CreateShaderResourceView(reads[i].resource,&desc,cpu); cpu.ptr += context.stride;
        }
        descriptor += readCount; pass.uav = pass.srv; pass.uav.ptr += uint64_t(readCount)*context.stride;
        for (uint32_t i=0;i<writeCount;++i)
        {
            D3D12_UNORDERED_ACCESS_VIEW_DESC desc {}; desc.Format = writes[i].format;
            desc.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
            context.device->CreateUnorderedAccessView(writes[i].resource,nullptr,&desc,cpu); cpu.ptr += context.stride;
        }
        descriptor += writeCount; pass.barriers = transientWrites;
        for (uint32_t i=0;i<transientWrites;++i)
        {
            auto& barrier = pass.toWrite[i]; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barrier.Transition = {writes[i].resource,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,ReadState,WriteState};
            pass.toRead[i] = barrier; pass.toRead[i].Transition.StateBefore = WriteState; pass.toRead[i].Transition.StateAfter = ReadState;
        }
    }
    static void Describe(Context& context,Recording& recording,const LobeRecoveryInputs& in,const LobeRecoveryFrame& frame)
    {
        auto& slot = *recording.slot;
        const uint32_t previous = context.previous,current = previous^1u;
        recording.current = current;
        const bool history = context.historyValid && !frame.reset && frame.frameIndex==uint32_t(context.lastFrame+1u);
        Constants base; base.fullSize = {float(in.width),float(in.height),1.f/in.width,1.f/in.height};
        base.levelSize = {float(in.width),float(in.height),float((in.width+1)/2),float((in.height+1)/2)};
        base.lobeStrength[0] = frame.strength[0]; base.lobeStrength[1] = frame.strength[1];
        base.pixelJitters = {frame.jitterPixels[0],frame.jitterPixels[1],frame.jitterDeltaUv[0],frame.jitterDeltaUv[1]};
        base.control = {history ? HistoryFlag : 0u,0,frame.frameIndex,0};
        const auto view = [&](const ComResource& value,DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN) {
            return View {value.Get(),format==DXGI_FORMAT_UNKNOWN ? context.floatStorage : format}; };
        const auto rrSpec = View {in.rrSpecular,DXGI_FORMAT_R16G16B16A16_FLOAT},rrDiff = View {in.rrDiffuse,DXGI_FORMAT_R16G16B16A16_FLOAT};
        const auto noisySpec = View {in.noisySpecular,DXGI_FORMAT_R16G16B16A16_FLOAT},noisyDiff = View {in.noisyDiffuse,DXGI_FORMAT_R16G16B16A16_FLOAT};
        const auto depth = View {in.depth,DXGI_FORMAT_R32_FLOAT},motion = View {in.motion,DXGI_FORMAT_R16G16B16A16_FLOAT},normal = View {in.normals,DXGI_FORMAT_R10G10B10A2_UNORM};
        uint32_t pass = 0,descriptor = 0;
        const std::array<View,11> referenceReads {noisySpec,noisyDiff,rrSpec,rrDiff,depth,normal,motion,
            view(context.history[previous][0]),view(context.history[previous][1]),view(context.history[previous][3],GeometryFormat),view(context.history[previous][2])};
        const std::array<View,7> referenceWrites {view(context.history[current][0]),view(context.history[current][1]),
            view(context.history[current][3],GeometryFormat),view(context.history[current][2]),view(context.pyramid[0][0]),view(context.pyramid[0][1]),view(context.pyramid[0][2])};
        DescribePass(context,slot,pass++,descriptor,context.reference,base,referenceReads.data(),11,referenceWrites.data(),7,7);
        std::array<std::array<uint32_t,2>,Levels+1> sizes {}; sizes[0] = {in.width,in.height};
        for (uint32_t level=1;level<=Levels;++level)
        {
            sizes[level] = {(sizes[level-1][0]+1)/2,(sizes[level-1][1]+1)/2};
            auto constants = base; constants.control[1] = level;
            constants.levelSize = {float(sizes[level][0]),float(sizes[level][1]),float(sizes[level-1][0]),float(sizes[level-1][1])};
            std::array<View,3> reads {},writes {};
            for (uint32_t i=0;i<3;++i) { reads[i] = view(context.pyramid[level-1][i]); writes[i] = view(context.pyramid[level][i]); }
            DescribePass(context,slot,pass++,descriptor,context.down,constants,reads.data(),3,writes.data(),3,3);
        }
        for (uint32_t reverse=0;reverse<Levels;++reverse)
        {
            const uint32_t level = Levels-1-reverse; const bool coarse = level==Levels-1,final = level==0;
            auto constants = base; constants.control[1] = level;
            constants.control[0] |= (coarse ? CoarsestFlag : 0u)|(final ? FinalFlag : 0u);
            constants.levelSize = {float(sizes[level][0]),float(sizes[level][1]),float(sizes[level+1][0]),float(sizes[level+1][1])};
            const std::array<View,18> reads {view(context.pyramid[level][0]),view(context.pyramid[level][1]),view(context.pyramid[level][2]),
                view(context.pyramid[level+1][0]),view(context.pyramid[level+1][1]),view(context.pyramid[level+1][2]),
                coarse ? View {nullptr,context.floatStorage} : view(context.correction[level+1][0]),
                coarse ? View {nullptr,context.floatStorage} : view(context.correction[level+1][1]),
                view(context.noise[previous][level],FloatFormat),motion,depth,normal,rrSpec,rrDiff,noisySpec,noisyDiff,
                view(context.history[previous][3],GeometryFormat),view(context.pyramid[0][2])};
            const std::array<View,5> writes {view(context.correction[level][0]),view(context.correction[level][1]),
                view(context.noise[current][level],FloatFormat),view(context.output[0],DXGI_FORMAT_R16G16B16A16_FLOAT),view(context.output[1],DXGI_FORMAT_R16G16B16A16_FLOAT)};
            DescribePass(context,slot,pass++,descriptor,context.band,constants,reads.data(),18,writes.data(),5,3);
        }
    }

  public:
    // D06/D07 control-model diagnostic snapshot of this helper and its family.
    // Names are proposed diagnostic vocabulary, not INI keys. Bytes are D3D
    // allocation extents this helper counts; provider-internal cost is unknown
    // and is reported as unknown by the calling service, never as zero.
    struct DiagnosticsSnapshot
    {
        uint64_t graphBytes = 0;            // This graph's reserved bytes.
        uint64_t familyGraphBytes = 0;      // Family total, including retained old graphs.
        uint64_t familyRetainedPeakBytes = 0;
        uint64_t ownedTextureBytes = 0, ownedAuxiliaryBytes = 0;
        uint32_t warmRetainedSlots = 0, familySlots = 0;
        uint32_t coldCooldowns = 0, coldRetryDenials = 0, preparationFailures = 0;
        uint64_t recordedFrames = 0;
    };
    DiagnosticsSnapshot SnapshotDiagnostics() const noexcept
    {
        DiagnosticsSnapshot result;
        if (context_)
        {
            result.graphBytes = context_->charge.bytes;
            uint32_t warm = 0;
            uint64_t auxiliary = 0;
            for (const auto& slot : context_->slots) if (slot) { ++warm; auxiliary += slot->bytes; }
            result.warmRetainedSlots = warm;
            result.ownedTextureBytes = context_->charge.bytes;
            result.ownedAuxiliaryBytes = auxiliary;
            result.recordedFrames = context_->recordedFrames;
        }
        if (context_ && context_->family) result = FamilyDiagnosticsSnapshot(*context_->family, result);
        return result;
    }
    // Family-level counters readable even when this helper has no context:
    // cold failures happen exactly there. Cheap metadata reads.
    static DiagnosticsSnapshot FamilyDiagnosticsSnapshot(const Family& family,
        DiagnosticsSnapshot result = {}) noexcept
    {
        result.familyGraphBytes = family.graphBytes.load(std::memory_order_relaxed);
        result.familyRetainedPeakBytes = family.retainedPeakBytes.load(std::memory_order_relaxed);
        result.familySlots = family.slots.allocatedSlots.load(std::memory_order_relaxed);
        result.coldCooldowns = family.coldCooldowns.load(std::memory_order_relaxed);
        result.coldRetryDenials = family.coldRetryDenials.load(std::memory_order_relaxed);
        result.preparationFailures = family.preparationFailures.load(std::memory_order_relaxed);
        return result;
    }
    struct Prepared
    {
        std::shared_ptr<void> owner;
        ID3D12Resource *specular = nullptr, *diffuse = nullptr;
        static constexpr D3D12_RESOURCE_STATES state = WriteState;
      private:
        Recording* recording_ = nullptr;
        friend class LobeRecovery;
    };
    explicit LobeRecovery(Storage storage = Storage::FullPrecision) noexcept : storage_(storage) {}
    LobeRecovery(const LobeRecovery&) = delete;
    LobeRecovery& operator=(const LobeRecovery&) = delete;

    bool Prepare(ID3D12Device* device,ID3D12GraphicsCommandList* list,const LobeRecoveryInputs& inputs,
                 const LobeRecoveryFrame& frame,const std::shared_ptr<Family>& family,Prepared& out,std::string& error) noexcept
    {
        // This helper takes no mutex; caller lifetime/injection guards may remain held.
        out = {}; error.clear();
        if (frame.strength[0]==0 && frame.strength[1]==0)
        { if (context_) context_->historyValid = false; return false; }
        uint64_t coldTick = 0; bool coldAttempt = false;
        const auto rejected = [&]() noexcept { if (context_) context_->historyValid = false; };
        try
        {
            FrameSurvey::ScopedInternal internal; ScopedSkipHeapCapture skip;
            if (!context_ && family)
            {
                coldTick = GetTickCount64();
                if (coldTick<family->retryUntilTick.load(std::memory_order_acquire))
                {
                    family->coldRetryDenials.fetch_add(1,std::memory_order_relaxed);
                    error = "Lobe recovery cold allocation retry is cooling down"; return false;
                }
            }
            if (!Validate(device,list,inputs,frame,family,error)) { rejected(); return false; }
            if (storage_!=Storage::FullPrecision && storage_!=Storage::MixedPrecision)
            { rejected(); error = "Lobe recovery storage mode is unsupported"; return false; }
            if (context_ && (context_->family!=family || context_->width!=inputs.width || context_->height!=inputs.height ||
                !SameDevice(device,context_->device.Get())))
            { rejected(); error = "Lobe recovery cannot change its physical RR context identity"; return false; }
            if (context_)
            {
                auto pending = context_->pending.lock();
                if (pending && !pending->recorded) { rejected(); error = "Lobe recovery has an unrecorded prepared predecessor"; return false; }
            }
            coldAttempt = !context_;
            auto recording = MakeOwnedShared<Recording>();
            auto context = context_;
            if (!context)
            {
                // Deny a full family before allocating another large graph.
                auto permit = ReserveSlot(family);
                context = CreateContext(device,inputs.width,inputs.height,family,storage_);
                recording->slot = NewSlot(*context,std::move(permit));
            }
            else recording->slot = AcquireSlot(*context);
            recording->context = context;
            recording->list = list; recording->frame = frame.frameIndex;
            const std::array<ID3D12Resource*,7> refs {inputs.noisySpecular,inputs.noisyDiffuse,inputs.depth,inputs.motion,inputs.normals,inputs.rrSpecular,inputs.rrDiffuse};
            for (size_t i=0;i<refs.size();++i) recording->inputs[i] = refs[i];
            Describe(*context,*recording,inputs,frame);
            context->pending = recording; context_ = context;
            out.owner = recording; out.recording_ = recording.get();
            out.specular = context->output[0].Get(); out.diffuse = context->output[1].Get();
            return true;
        }
        catch (const std::exception& exception)
        { rejected(); if (family) family->preparationFailures.fetch_add(1,std::memory_order_relaxed);
          if (coldAttempt) DelayColdRetry(*family,GetTickCount64()); StoreError(error,exception.what()); return false; }
        catch (...)
        { rejected(); if (family) family->preparationFailures.fetch_add(1,std::memory_order_relaxed);
          if (coldAttempt) DelayColdRetry(*family,GetTickCount64()); StoreError(error,"Lobe recovery preparation allocation failed"); return false; }
    }
    // Preconditions: this exact Prepared.owner is GPU-leased and the physical RR
    // provider succeeded. Record precedes title admission and touches only owned
    // resources. If later title admission fails, the caller retires the ENTIRE RR
    // Context/helper so this speculative history cannot seed another frame.
    // No other Prepare may interleave before Record. Title restore is the caller's.
    void Record(ID3D12GraphicsCommandList* list,const Prepared& prepared) noexcept
    {
        auto* recording = prepared.recording_;
        if (!recording || prepared.owner.get()!=recording || recording->recorded || list!=recording->list) return;
        auto& context = *recording->context; auto& slot = *recording->slot;
        std::array<D3D12_RESOURCE_BARRIER,4> before {};
        for (uint32_t i=0;i<2;++i)
        {
            before[i].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            before[i].Transition = {recording->inputs[5+i].Get(),D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,WriteState,ReadState};
            before[2+i].Type = D3D12_RESOURCE_BARRIER_TYPE_UAV; before[2+i].UAV.pResource = context.output[i].Get();
        }
        list->ResourceBarrier(4,before.data());
        ID3D12DescriptorHeap* heaps[] = {slot.descriptors.Get()}; list->SetDescriptorHeaps(1,heaps);
        for (const auto& pass : slot.passes)
        {
            list->ResourceBarrier(pass.barriers,pass.toWrite.data());
            list->SetPipelineState(pass.pipeline->pso.Get()); list->SetComputeRootSignature(pass.pipeline->root.Get());
            list->SetComputeRootConstantBufferView(0,pass.constants);
            list->SetComputeRootDescriptorTable(1,pass.srv); list->SetComputeRootDescriptorTable(2,pass.uav);
            list->Dispatch((pass.width+7)/8,(pass.height+7)/8,1);
            list->ResourceBarrier(pass.barriers,pass.toRead.data());
        }
        std::array<D3D12_RESOURCE_BARRIER,4> after {};
        for (uint32_t i=0;i<2;++i)
        {
            after[i] = before[i]; after[i].Transition.StateBefore = ReadState; after[i].Transition.StateAfter = WriteState;
            after[2+i].Type = D3D12_RESOURCE_BARRIER_TYPE_UAV; after[2+i].UAV.pResource = context.output[i].Get();
        }
        list->ResourceBarrier(4,after.data());
        context.previous = recording->current; context.lastFrame = recording->frame;
        context.historyValid = recording->recorded = true; ++context.recordedFrames;
    }
    uint64_t OwnedTextureBytes() const noexcept { return context_ ? context_->charge.bytes : 0; }
    uint64_t OwnedAuxiliaryBytes() const noexcept
    {
        uint64_t bytes = 0;
        if (context_) for (const auto& slot : context_->slots) if (slot) bytes += slot->bytes;
        return bytes;
    }
    uint64_t RecordedFrames() const noexcept { return context_ ? context_->recordedFrames : 0; }
};
}
