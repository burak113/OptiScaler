#pragma once
#include "FSRDNrdBridgeRR_Dx12.h"
#include "FSRDNrdLobeRecovery_Dx12.h"
#include <vector>
#include "precompile/FSRDNrdFlatPrepare_Shader.h"
#include "precompile/FSRDFlatDetailClassify_Shader.h"
#include "precompile/FSRDFlatDetailSeed_Shader.h"
#include "precompile/FSRDFlatDetailRefine_Shader.h"
#include "precompile/FSRDFlatDetailBase_Shader.h"
#include "precompile/FSRDFlatDetailApply_Shader.h"
#include "precompile/FSRDNrdFlatAccumulate_Shader.h"
#include "precompile/FSRDNrdFlatReferenceFilter_Shader.h"

namespace NrdBridge
{
// The same family/32-slot/2-GiB admission as optional lobe recovery. Scratch and
// six-slice references belong to one physical, causally serialized RR context.
// All allocations and descriptor writes finish in Prepare, before any provider
// work or native suppression. Prepared must be GPU-leased before RecordInputs.
class FlatAlbedoRecovery
{
    using Resource = Microsoft::WRL::ComPtr<ID3D12Resource>;
    using Family = LobeRecovery::Family;
    static constexpr auto Read = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    static constexpr auto Write = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    static constexpr auto Half = DXGI_FORMAT_R16G16B16A16_FLOAT;
    static constexpr auto Normal = DXGI_FORMAT_R10G10B10A2_UNORM;
    static constexpr uint32_t MaxPasses = 17, MaxDescriptors = 256, ResetOffset = MaxPasses * 256;
    struct Charge
    {
        std::shared_ptr<Family> family;
        uint64_t bytes = 0;
        void Acquire(const std::shared_ptr<Family>& f,uint64_t n)
        {
            auto used = f->graphBytes.load(std::memory_order_acquire);
            if (!n || n > Family::GraphByteLimit) throw std::runtime_error("Flat recovery graph exceeds shared 2-GiB limit");
            while (used <= Family::GraphByteLimit-n)
                if (f->graphBytes.compare_exchange_weak(used,used+n,std::memory_order_acq_rel))
                {
                    family = f; bytes = n;
                    auto peak = f->retainedPeakBytes.load(std::memory_order_relaxed);
                    while (peak < used+n && !f->retainedPeakBytes.compare_exchange_weak(peak,used+n,std::memory_order_relaxed)) {}
                    return;
                }
            throw std::runtime_error("Flat recovery shared graph family exceeds 2-GiB limit");
        }
        ~Charge() { if (family) family->graphBytes.fetch_sub(bytes,std::memory_order_acq_rel); }
    };
    struct Pipeline
    {
        Microsoft::WRL::ComPtr<ID3D12RootSignature> root;
        Microsoft::WRL::ComPtr<ID3D12PipelineState> pso;
    };
    struct View { ID3D12Resource* resource = nullptr; };
    struct Pass
    {
        Pipeline* pipeline = nullptr;
        D3D12_GPU_VIRTUAL_ADDRESS constants = 0;
        D3D12_GPU_DESCRIPTOR_HANDLE srv {}, uav {};
        std::array<D3D12_RESOURCE_BARRIER,4> before {}, after {};
        uint32_t barriers = 0, x = 0, y = 0;
        bool indirect = false, classify = false;
    };
    struct Slot
    {
        NrdBridgeCaptureBudget::Permit permit;
        Resource constants;
        Microsoft::WRL::ComPtr<ID3D12DescriptorHeap> descriptors;
        uint8_t* mapped = nullptr;
        uint64_t bytes = 0;
        std::array<Pass,MaxPasses> passes {};
        uint32_t count = 0;
        explicit Slot(NrdBridgeCaptureBudget::Permit&& p) : permit(std::move(p)) {}
        ~Slot() { if (mapped) constants->Unmap(0,nullptr); }
    };
    struct Context;
    struct Recording
    {
        std::shared_ptr<Context> context;
        std::shared_ptr<Slot> slot;
        std::array<Resource,7> inputs;
        ID3D12GraphicsCommandList* list = nullptr;
        uint32_t frame = 0;
        uint32_t nextParity = 0;
        bool inputsRecorded = false, recorded = false;
    };
    struct Context
    {
        Charge charge; // Reservation outlives every resource, including unwind.
        Microsoft::WRL::ComPtr<ID3D12Device> device;
        std::shared_ptr<Family> family;
        uint32_t width = 0, height = 0, stride = 0, parity = 0, lastFrame = 0;
        bool temporal = false, valid = false;
        Resource rrNormals, masks[2], black, output[2], reference[2], statistics[2], base, mean, variance;
        Resource tiles, arguments;
        // Per lobe, ping-pong: linear running mean (rgb, count) and level history, depth, RR luma mean, luma moment.
        struct History { Resource mean[2], moment[2]; } history[2];
        Pipeline prepare, classify, seed, refine, basePass, apply, accumulate, referenceFilter;
        Microsoft::WRL::ComPtr<ID3D12CommandSignature> signature;
        std::array<std::shared_ptr<Slot>,NrdBridgeCaptureBudget::Family::Capacity> slots {};
        std::weak_ptr<Recording> pending;
    };
    std::shared_ptr<Context> context_;
    static void Check(HRESULT hr,const char* label) { if (FAILED(hr)) throw std::runtime_error(label); }
    static D3D12_RESOURCE_BARRIER Transition(ID3D12Resource* p,D3D12_RESOURCE_STATES a,D3D12_RESOURCE_STATES b) noexcept
    {
        D3D12_RESOURCE_BARRIER r {}; r.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        r.Transition = {p,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,a,b}; return r;
    }
    static D3D12_RESOURCE_DESC Texture(uint32_t w,uint32_t h,DXGI_FORMAT f,uint16_t layers = 1) noexcept
    {
        D3D12_RESOURCE_DESC d {}; d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        d.Width = w; d.Height = h; d.DepthOrArraySize = layers; d.MipLevels = 1; d.Format = f;
        d.SampleDesc.Count = 1; d.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS; return d;
    }
    static D3D12_RESOURCE_DESC Buffer(uint64_t bytes) noexcept
    {
        D3D12_RESOURCE_DESC d {}; d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        d.Width = bytes; d.Height = d.DepthOrArraySize = d.MipLevels = 1;
        d.SampleDesc.Count = 1; d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR; return d;
    }
    static void PipelineFrom(ID3D12Device* device,const void* data,size_t bytes,Pipeline& p)
    {
        Check(device->CreateRootSignature(0,data,bytes,IID_PPV_ARGS(&p.root)),"Flat recovery root creation failed");
        D3D12_COMPUTE_PIPELINE_STATE_DESC desc {}; desc.pRootSignature = p.root.Get(); desc.CS = {data,bytes};
        Check(device->CreateComputePipelineState(&desc,IID_PPV_ARGS(&p.pso)),"Flat recovery PSO creation failed");
    }
    static std::shared_ptr<Context> Create(ID3D12Device* device,const LobeRecoveryInputs& in,
        const FlatAlbedoSettings& settings,const std::shared_ptr<Family>& family)
    {
        auto c = MakeOwnedShared<Context>(); c->device = device; c->family = family;
        c->width = in.width; c->height = in.height; c->temporal = settings.temporal;
        c->stride = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        struct Plan { Resource* target; D3D12_RESOURCE_DESC desc; D3D12_RESOURCE_STATES state; };
        std::vector<Plan> plans;
        const auto tex = [&](Resource& target,DXGI_FORMAT f,uint32_t w = 0,uint32_t h = 0,uint16_t layers = 1,
                             D3D12_RESOURCE_STATES state = Read) {
            plans.push_back({&target,Texture(w ? w : in.width,h ? h : in.height,f,layers),state}); };
        tex(c->rrNormals,Normal); for (auto& t:c->masks) tex(t,Normal); tex(c->black,Half);
        for (auto& t:c->output) tex(t,Half,0,0,1,Write);
        for (auto& t:c->reference) tex(t,Half); for (auto& t:c->statistics) tex(t,Half);
        tex(c->base,Half); tex(c->mean,Half); tex(c->variance,Half);
        const auto buf = [&](Resource& target,uint64_t bytes,D3D12_RESOURCE_STATES state) {
            auto d = Buffer(bytes); d.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS; plans.push_back({&target,d,state}); };
        // Buffers use COMMON boundaries and explicit read/indirect transitions.
        // Modern D3D12 ignores other creation states for buffers and warns.
        buf(c->tiles,16+uint64_t((in.width+7)/8)*((in.height+7)/8)*8,D3D12_RESOURCE_STATE_COMMON);
        buf(c->arguments,12,D3D12_RESOURCE_STATE_COMMON);
        if (settings.temporal)
            for (auto& h:c->history) for (uint32_t i = 0;i < 2;++i)
            { tex(h.mean[i],Half); tex(h.moment[i],DXGI_FORMAT_R32G32B32A32_FLOAT); }
        uint64_t bytes = 0;
        for (const auto& p:plans)
        {
            const uint64_t n = device->GetResourceAllocationInfo(0,1,&p.desc).SizeInBytes;
            if (!n || n == UINT64_MAX || n > UINT64_MAX-bytes) throw std::runtime_error("Flat recovery allocation extent is invalid");
            bytes += n;
        }
        c->charge.Acquire(family,bytes);
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        for (const auto& p:plans) Check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&p.desc,p.state,
            nullptr,IID_PPV_ARGS(p.target->GetAddressOf())),"Flat recovery resource allocation failed");
#define FLAT_PIPE(member,name) PipelineFrom(device,name##_cso,sizeof(name##_cso),c->member)
        FLAT_PIPE(prepare,FSRDNrdFlatPrepare); FLAT_PIPE(classify,FSRDFlatDetailClassify);
        FLAT_PIPE(seed,FSRDFlatDetailSeed); FLAT_PIPE(refine,FSRDFlatDetailRefine);
        FLAT_PIPE(basePass,FSRDFlatDetailBase); FLAT_PIPE(apply,FSRDFlatDetailApply);
        if (settings.temporal) { FLAT_PIPE(accumulate,FSRDNrdFlatAccumulate); FLAT_PIPE(referenceFilter,FSRDNrdFlatReferenceFilter); }
#undef FLAT_PIPE
        D3D12_INDIRECT_ARGUMENT_DESC arg {}; arg.Type = D3D12_INDIRECT_ARGUMENT_TYPE_DISPATCH;
        D3D12_COMMAND_SIGNATURE_DESC sig {}; sig.ByteStride = 12; sig.NumArgumentDescs = 1; sig.pArgumentDescs = &arg;
        Check(device->CreateCommandSignature(&sig,nullptr,IID_PPV_ARGS(&c->signature)),"Flat recovery indirect signature creation failed");
        return c;
    }
    static NrdBridgeCaptureBudget::Permit Reserve(const std::shared_ptr<Family>& family)
    {
        auto permit = NrdBridgeCaptureBudget::Permit::TryAcquire(std::shared_ptr<NrdBridgeCaptureBudget::Family>(family,&family->slots));
        if (!permit) throw std::runtime_error("Flat recovery shared family has 32 retained recording slots");
        return permit;
    }
    static std::shared_ptr<Slot> Acquire(Context& c,NrdBridgeCaptureBudget::Permit permit = {})
    {
        for (const auto& slot:c.slots) if (slot && slot.use_count() == 1) return slot;
        auto reservation = permit ? std::move(permit) : Reserve(c.family);
        auto slot = MakeOwnedShared<Slot>(std::move(reservation)); auto desc = Buffer(ResetOffset+256);
        slot->bytes = c.device->GetResourceAllocationInfo(0,1,&desc).SizeInBytes;
        if (!slot->permit.SetBytes(slot->bytes)) throw std::runtime_error("Flat recovery constant extent is invalid");
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_UPLOAD;
        Check(c.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_GENERIC_READ,
            nullptr,IID_PPV_ARGS(&slot->constants)),"Flat recovery constants allocation failed");
        D3D12_RANGE empty {0,0}; Check(slot->constants->Map(0,&empty,reinterpret_cast<void**>(&slot->mapped)),"Flat recovery constant mapping failed");
        const uint32_t reset[] {0,0,0,0,0,1,1}; std::memcpy(slot->mapped+ResetOffset,reset,sizeof(reset));
        D3D12_DESCRIPTOR_HEAP_DESC hd {}; hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        hd.NumDescriptors = MaxDescriptors; hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        Check(c.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&slot->descriptors)),"Flat recovery descriptors allocation failed");
        for (auto& target:c.slots) if (!target) { target = slot; return slot; }
        throw std::runtime_error("Flat recovery context slot capacity exhausted");
    }
    static void Srv(ID3D12Device* device,View view,D3D12_CPU_DESCRIPTOR_HANDLE handle)
    {
        D3D12_SHADER_RESOURCE_VIEW_DESC d {}; d.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        auto desc = view.resource->GetDesc(); d.Format = desc.Format;
        if (desc.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER)
        { d.Format = DXGI_FORMAT_R32_TYPELESS; d.ViewDimension = D3D12_SRV_DIMENSION_BUFFER; d.Buffer.NumElements = uint32_t(desc.Width/4); d.Buffer.Flags = D3D12_BUFFER_SRV_FLAG_RAW; }
        else if (desc.DepthOrArraySize > 1)
        { d.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2DARRAY; d.Texture2DArray.MipLevels = 1; d.Texture2DArray.ArraySize = desc.DepthOrArraySize; }
        else { d.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D; d.Texture2D.MipLevels = 1; }
        device->CreateShaderResourceView(view.resource,&d,handle);
    }
    static void Uav(ID3D12Device* device,View view,D3D12_CPU_DESCRIPTOR_HANDLE handle)
    {
        D3D12_UNORDERED_ACCESS_VIEW_DESC d {};
        if (!view.resource)
        {
            d.Format = Half; d.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
            device->CreateUnorderedAccessView(nullptr,nullptr,&d,handle); return;
        }
        const auto desc = view.resource->GetDesc(); d.Format = desc.Format;
        if (desc.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER)
        { d.Format = DXGI_FORMAT_R32_TYPELESS; d.ViewDimension = D3D12_UAV_DIMENSION_BUFFER; d.Buffer.NumElements = uint32_t(desc.Width/4); d.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW; }
        else if (desc.DepthOrArraySize > 1)
        { d.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2DARRAY; d.Texture2DArray.ArraySize = desc.DepthOrArraySize; }
        else d.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
        device->CreateUnorderedAccessView(view.resource,nullptr,&d,handle);
    }
    template<class Constants,size_t N,size_t M> static void Describe(Context& c,Slot& slot,uint32_t& descriptor,
        Pipeline& pipeline,const Constants& constants,const std::array<View,N>& reads,const std::array<View,M>& writes,
        bool indirect = true,uint32_t w = 0,uint32_t h = 0,bool classify = false)
    {
        if (slot.count >= MaxPasses || descriptor+N+M > MaxDescriptors) throw std::runtime_error("Flat recovery pass capacity exhausted");
        const uint32_t index = slot.count++; auto& p = slot.passes[index]; p = {};
        p.pipeline = &pipeline; p.constants = slot.constants->GetGPUVirtualAddress()+uint64_t(index)*256;
        std::memcpy(slot.mapped+size_t(index)*256,&constants,sizeof(constants));
        p.x = ((w ? w:c.width)+7)/8; p.y = ((h ? h:c.height)+7)/8; p.indirect = indirect; p.classify = classify;
        auto cpu = slot.descriptors->GetCPUDescriptorHandleForHeapStart(); cpu.ptr += uint64_t(descriptor)*c.stride;
        p.srv = slot.descriptors->GetGPUDescriptorHandleForHeapStart(); p.srv.ptr += uint64_t(descriptor)*c.stride;
        for (auto v:reads) { Srv(c.device.Get(),v,cpu); cpu.ptr += c.stride; }
        p.uav = p.srv; p.uav.ptr += N*c.stride;
        for (auto v:writes)
        {
            Uav(c.device.Get(),v,cpu); cpu.ptr += c.stride;
            // Null output descriptors are never used by the corresponding kernel.
            if (v.resource)
            {
                auto state = v.resource->GetDesc().Dimension == D3D12_RESOURCE_DIMENSION_BUFFER ? D3D12_RESOURCE_STATE_COMMON : Read;
                p.before[p.barriers] = Transition(v.resource,state,Write);
                const auto after = v.resource == c.arguments.Get() ? D3D12_RESOURCE_STATE_INDIRECT_ARGUMENT : Read;
                p.after[p.barriers++] = Transition(v.resource,Write,after);
            }
        }
        descriptor += uint32_t(N+M);
    }
    struct alignas(16) DetailConstants
    {
        std::array<float,4> size;
        std::array<float,2> modulation {};
        float strength, anchor, mix, noise = 2, epsilon = 1e-4f;
        uint32_t radius = 3, pass = 0, debug = 0, flags = 0;
        float temporalDenoise;
    };
    // Running-mean reference (FSRDNrdFlatAccumulate). Mirror lobes are sparse 1spp signals whose
    // noise is independent from frame to frame, so a long linear mean is the best estimate (NRD's
    // approach): the cap is long at rest and under camera rotation. Camera translation moves a
    // reflection differently from the surface motion vectors (parallax), so it caps the history at
    // parallaxTolerance / (parallaxPixels / depth) frames, about one pixel of smear.
    struct alignas(16) AccumulateConstants
    {
        std::array<float,4> size;
        uint32_t historyValid = 0;
        float maxCount = 32, movingCount = 8, motionStart = 2, motionEnd = 16, fullCount = 8, epsilon = 1e-6f, changeStart = 0.35f;
        float parallaxPixels = 0, parallaxTolerance = 4;
        float reserved[2] {};
    };
    // Same-surface Gaussian over the running mean (FSRDNrdFlatReferenceFilter): sigma for a thin
    // mean (feeds the RR-based recovery), matureSigma for the mature mean that is the output.
    struct alignas(16) ReferenceFilterConstants
    {
        std::array<float,4> size;
        float sigma = 1.0f;
        uint32_t radius = 2;
        float matureSigma = 0.5f, reserved = 0;
    };
    static_assert(sizeof(ReferenceFilterConstants) == 32);
    // Bit 2: reference and RR are the same lighting; Base keeps the reference level.
    // Bit 3: the output follows a mature reference (count FullCount/2 -> FullCount), RR-based
    // detail recovery only covers thin histories (motion, parallax, disocclusion, light change),
    // at the level of the accumulator's parallax-free level history (moment x, bound as t8).
    static constexpr uint32_t SameLighting = 4, ReferenceTrust = 8;
    static_assert(sizeof(DetailConstants) == 64 && offsetof(DetailConstants,temporalDenoise) == 60);
    static_assert(sizeof(AccumulateConstants) == 64);
    static void DescribeFrame(Context& c,Recording& r,const LobeRecoveryInputs& in,const LobeRecoveryFrame& frame,
                              const FlatAlbedoSettings& settings)
    {
        auto& slot = *r.slot; slot.count = 0; uint32_t descriptor = 0;
        const std::array<float,4> size {float(in.width),float(in.height),1.f/in.width,1.f/in.height};
        const std::array<uint32_t,4> prep {in.width,in.height,settings.roughness,0};
        Describe(c,slot,descriptor,c.prepare,prep,std::array<View,4>{{{in.normals},{in.noisySpecular},{in.noisyDiffuse},{in.depth}}},
            std::array<View,4>{{{c.rrNormals.Get()},{c.masks[0].Get()},{c.masks[1].Get()},{c.black.Get()}}},false);
        const bool history = c.valid && !frame.reset && frame.frameIndex == uint32_t(c.lastFrame+1u);
        // Native bridge motion already includes the exact raster jitter delta; it is used as is.
        AccumulateConstants accumulate {size}; accumulate.historyValid = history ? 1u : 0u;
        accumulate.parallaxPixels = std::isfinite(frame.parallaxPixels) ? std::max(frame.parallaxPixels,0.0f) : 0.0f;
        r.nextParity = c.parity^1u;
        DetailConstants detail {size,{},settings.strength,settings.anchor,settings.mix};
        detail.temporalDenoise = settings.temporal ? settings.temporalDenoise : 0;
        detail.flags = SameLighting|ReferenceTrust;
        for (uint32_t lobe = 0;lobe < 2;++lobe)
        {
            const View mask {c.masks[lobe].Get()}, black {c.black.Get()}, depth {in.depth}, motion {in.motion};
            const View noisy {lobe == 0 ? in.noisySpecular : in.noisyDiffuse}, output {c.output[lobe].Get()};
            Describe(c,slot,descriptor,c.classify,size,std::array<View,2>{mask,black},
                std::array<View,2>{{{c.tiles.Get()},{c.arguments.Get()}}},false,0,0,true);
            // Independent demodulated lobe references: modulation=0, flags=0.
            // There is no recombination of specular/diffuse and no native NRD output.
            std::array<View,14> reads {noisy,black,black,black,black,mask,depth,black,black,{c.tiles.Get()},black,black,black,black};
            if (settings.temporal)
            {
                // Unbiased linear running mean of the raw lobe replaces the robust single-frame
                // seed: its plane fit and the log-domain slice mean both reject sparse highlights.
                auto& h = c.history[lobe];
                Describe(c,slot,descriptor,c.accumulate,accumulate,
                    std::array<View,7>{{noisy,mask,depth,motion,{h.mean[c.parity].Get()},{h.moment[c.parity].Get()},output}},
                    std::array<View,3>{{{h.mean[c.parity^1u].Get()},{h.moment[c.parity^1u].Get()},{c.reference[0].Get()}}},false);
                Describe(c,slot,descriptor,c.referenceFilter,ReferenceFilterConstants {size},
                    std::array<View,3>{{{c.reference[0].Get()},mask,depth}},std::array<View,1>{{{c.reference[1].Get()}}},false);
                reads[7] = {c.reference[1].Get()};
                reads[8] = {h.moment[c.parity^1u].Get()}; // level history for thin histories (Base, ReferenceTrust)
            }
            else
            {
                Describe(c,slot,descriptor,c.seed,detail,reads,
                    std::array<View,3>{{{c.reference[0].Get()},{c.statistics[0].Get()},{nullptr}}});
                reads[7] = {c.reference[0].Get()}; reads[8] = {c.statistics[0].Get()};
                Describe(c,slot,descriptor,c.refine,detail,reads,
                    std::array<View,3>{{{c.reference[1].Get()},{c.statistics[1].Get()},{nullptr}}});
                reads[7] = {c.reference[1].Get()}; reads[8] = {c.statistics[1].Get()};
            }
            reads[13] = output;
            Describe(c,slot,descriptor,c.basePass,detail,reads,
                std::array<View,3>{{{c.base.Get()},{c.mean.Get()},{c.variance.Get()}}});
            reads[13] = black; reads[10] = {c.base.Get()}; reads[11] = {c.mean.Get()}; reads[12] = {c.variance.Get()};
            Describe(c,slot,descriptor,c.apply,detail,reads,std::array<View,3>{output,{nullptr},{nullptr}});
        }
    }
    static void Run(ID3D12GraphicsCommandList* list,Context& c,Slot& slot,const Pass& p) noexcept
    {
        if (p.classify)
        {
            D3D12_RESOURCE_BARRIER before[] {Transition(c.tiles.Get(),D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COPY_DEST),
                Transition(c.arguments.Get(),D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COPY_DEST)};
            list->ResourceBarrier(2,before);
            list->CopyBufferRegion(c.tiles.Get(),0,slot.constants.Get(),ResetOffset,16);
            list->CopyBufferRegion(c.arguments.Get(),0,slot.constants.Get(),ResetOffset+16,12);
            before[0] = Transition(c.tiles.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_COMMON);
            before[1] = Transition(c.arguments.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_COMMON);
            list->ResourceBarrier(2,before);
        }
        if (p.barriers) list->ResourceBarrier(p.barriers,p.before.data());
        list->SetPipelineState(p.pipeline->pso.Get()); list->SetComputeRootSignature(p.pipeline->root.Get());
        list->SetComputeRootConstantBufferView(0,p.constants);
        list->SetComputeRootDescriptorTable(1,p.srv); list->SetComputeRootDescriptorTable(2,p.uav);
        if (p.indirect) list->ExecuteIndirect(c.signature.Get(),1,c.arguments.Get(),0,nullptr,0);
        else list->Dispatch(p.x,p.y,1);
        if (p.barriers) list->ResourceBarrier(p.barriers,p.after.data());
        if (p.pipeline == &c.apply)
        {
            // End each lobe at COMMON, including empty indirect tile lists.
            // Creation, warm recording and closed-list re-execution all agree.
            const D3D12_RESOURCE_BARRIER done[] {Transition(c.tiles.Get(),Read,D3D12_RESOURCE_STATE_COMMON),
                Transition(c.arguments.Get(),D3D12_RESOURCE_STATE_INDIRECT_ARGUMENT,D3D12_RESOURCE_STATE_COMMON)};
            list->ResourceBarrier(2,done);
        }
    }

  public:
    struct Prepared
    {
        std::shared_ptr<void> owner;
        ID3D12Resource *normals = nullptr, *specular = nullptr, *diffuse = nullptr;
      private:
        Recording* recording = nullptr;
        friend class FlatAlbedoRecovery;
    };
    bool Prepare(ID3D12Device* device,ID3D12GraphicsCommandList* list,const LobeRecoveryInputs& in,
                 const LobeRecoveryFrame& frame,const FlatAlbedoSettings& settings,const std::shared_ptr<Family>& family,
                 Prepared& out,std::string& error) noexcept
    {
        out = {}; error.clear(); bool cold = !context_;
        try
        {
            FrameSurvey::ScopedInternal internal; ScopedSkipHeapCapture skip;
            if (!device || !list || !family || !settings.enabled || !settings.roughness || settings.roughness > 1023 ||
                !in.width || !in.height || !in.noisySpecular || !in.noisyDiffuse || !in.normals || !in.depth ||
                !in.motion || !in.rrSpecular || !in.rrDiffuse) throw std::runtime_error("Flat recovery inputs/settings are incomplete");
            if (cold && GetTickCount64() < family->retryUntilTick.load(std::memory_order_acquire))
                throw std::runtime_error("Flat recovery cold allocation retry is cooling down");
            if (context_ && (context_->width != in.width || context_->height != in.height || context_->temporal != settings.temporal ||
                context_->family != family)) throw std::runtime_error("Flat recovery physical context identity changed");
            if (context_) if (auto pending = context_->pending.lock(); pending && !pending->recorded)
                throw std::runtime_error("Flat recovery has an unrecorded prepared predecessor");
            auto recording = MakeOwnedShared<Recording>(); auto c = context_;
            if (!c) { auto permit = Reserve(family); c = Create(device,in,settings,family); recording->slot = Acquire(*c,std::move(permit)); }
            else recording->slot = Acquire(*c);
            recording->context = c; recording->list = list; recording->frame = frame.frameIndex;
            const std::array<ID3D12Resource*,7> refs {in.noisySpecular,in.noisyDiffuse,in.depth,in.motion,in.normals,in.rrSpecular,in.rrDiffuse};
            for (size_t i=0;i<refs.size();++i) recording->inputs[i] = refs[i];
            DescribeFrame(*c,*recording,in,frame,settings);
            c->pending = recording; context_ = c;
            out.owner = recording; out.recording = recording.get();
            out.normals = c->rrNormals.Get(); out.specular = c->output[0].Get(); out.diffuse = c->output[1].Get(); return true;
        }
        catch (const std::exception& e) { try { error = e.what(); } catch (...) {} }
        catch (...) { try { error = "Flat recovery preparation allocation failed"; } catch (...) {} }
        if (context_) context_->valid = false;
        if (family && cold) family->retryUntilTick.store(GetTickCount64()+1000,std::memory_order_release);
        return false;
    }
    void RecordInputs(ID3D12GraphicsCommandList* list,const Prepared& p) noexcept
    {
        auto* r = p.recording;
        if (!r || r != p.owner.get() || r->inputsRecorded || list != r->list) return;
        auto& c = *r->context; auto& slot = *r->slot;
        ID3D12DescriptorHeap* heaps[] {slot.descriptors.Get()}; list->SetDescriptorHeaps(1,heaps);
        Run(list,c,slot,slot.passes[0]); r->inputsRecorded = true;
    }
    void RecordOutput(ID3D12GraphicsCommandList* list,const Prepared& p) noexcept
    {
        auto* r = p.recording;
        if (!r || r != p.owner.get() || !r->inputsRecorded || r->recorded || list != r->list) return;
        auto& c = *r->context; auto& slot = *r->slot;
        for (uint32_t i=0;i<2;++i)
        {
            auto* source = r->inputs[5+i].Get(); auto* target = c.output[i].Get();
            D3D12_RESOURCE_BARRIER before[] {Transition(source,Write,D3D12_RESOURCE_STATE_COPY_SOURCE),
                Transition(target,Write,D3D12_RESOURCE_STATE_COPY_DEST)};
            list->ResourceBarrier(2,before); list->CopyResource(target,source);
            before[0] = Transition(source,D3D12_RESOURCE_STATE_COPY_SOURCE,Write);
            before[1] = Transition(target,D3D12_RESOURCE_STATE_COPY_DEST,Read); list->ResourceBarrier(2,before);
        }
        ID3D12DescriptorHeap* heaps[] {slot.descriptors.Get()}; list->SetDescriptorHeaps(1,heaps);
        for (uint32_t i=1;i<slot.count;++i) Run(list,c,slot,slot.passes[i]);
        D3D12_RESOURCE_BARRIER after[] {Transition(c.output[0].Get(),Read,Write),Transition(c.output[1].Get(),Read,Write)};
        list->ResourceBarrier(2,after);
        if (c.temporal) c.parity = r->nextParity;
        c.lastFrame = r->frame; c.valid = c.temporal; r->recorded = true;
    }
    uint64_t OwnedTextureBytes() const noexcept { return context_ ? context_->charge.bytes : 0; }
    uint64_t OwnedAuxiliaryBytes() const noexcept
    {
        uint64_t bytes = 0; if (context_) for (const auto& slot:context_->slots) if (slot) bytes += slot->bytes; return bytes;
    }
};
}
