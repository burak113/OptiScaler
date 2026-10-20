#pragma once
#include "FSRDNrdBridgeRR_Dx12.h"
#include "FSRDNrdLobeRecovery_Dx12.h"
#include "FSRDPostMotionAnchorConstants.h"
#include "precompile/FSRDNrdPostMotionAnchorStatsRecall_Shader.h"
#include "precompile/FSRDNrdPostMotionAnchorGain_Shader.h"
#include "precompile/FSRDPostMotionAnchorApply_Shader.h"
#include <stdexcept>

namespace NrdBridge
{
// Native-only input adapter. The lighting remains in PHYSICAL native units.
// Only the sums' integer representation changes: the native Stats/Gain variants
// use 16.16 low/high pairs, without moving the physical per-cell cap of 16.
// Prepare is fallible but records no commands. Retain Prepared in DispatchLease
// before RecordInputs, then use its pair for recovery/flat/provider readers.
class NativePostMotionAnchor
{
    using Resource = Microsoft::WRL::ComPtr<ID3D12Resource>;
    using Family = LobeRecovery::Family;
    static constexpr auto Read = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    static constexpr auto Write = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    static_assert(sizeof(PostMotionAnchorMath::StatsRecallConstants) <= 1024);
    static_assert(sizeof(PostMotionAnchorMath::GainConstants) <= 256);
    static_assert(sizeof(PostMotionAnchorMath::ApplyConstants) <= 256);
    struct Pipeline
    {
        Microsoft::WRL::ComPtr<ID3D12RootSignature> root;
        Microsoft::WRL::ComPtr<ID3D12PipelineState> pso;
    };
    struct Charge
    {
        std::shared_ptr<Family> family;
        uint64_t bytes = 0;
        void Acquire(const std::shared_ptr<Family>& f,uint64_t n)
        {
            auto used = f->graphBytes.load(std::memory_order_acquire);
            if (!n || n > Family::GraphByteLimit) throw std::runtime_error("Native anchor graph exceeds family byte limit");
            while (used <= Family::GraphByteLimit - n)
                if (f->graphBytes.compare_exchange_weak(used,used+n,std::memory_order_acq_rel))
                {
                    family = f; bytes = n;
                    auto peak = f->retainedPeakBytes.load(std::memory_order_relaxed);
                    while (peak < used+n && !f->retainedPeakBytes.compare_exchange_weak(peak,used+n,std::memory_order_relaxed)) {}
                    return;
                }
            throw std::runtime_error("Native anchor shared graph byte limit reached");
        }
        ~Charge() { if (family) family->graphBytes.fetch_sub(bytes,std::memory_order_acq_rel); }
    };
    struct Pass
    {
        Pipeline* pipeline = nullptr;
        D3D12_GPU_VIRTUAL_ADDRESS constants = 0;
        D3D12_GPU_DESCRIPTOR_HANDLE srv {}, uav {};
    };
    struct Slot
    {
        NrdBridgeCaptureBudget::Permit permit;
        Resource constants;
        Microsoft::WRL::ComPtr<ID3D12DescriptorHeap> descriptors;
        uint8_t* mapped = nullptr;
        Pass passes[3] {};
        uint64_t bytes = 0;
        explicit Slot(NrdBridgeCaptureBudget::Permit&& p) : permit(std::move(p)) {}
        ~Slot() { if (mapped) constants->Unmap(0,nullptr); }
    };
    struct Context;
    struct Recording
    {
        std::shared_ptr<Context> context;
        std::shared_ptr<Slot> slot;
        std::array<Resource,4> inputs;
        ID3D12GraphicsCommandList* list = nullptr;
        PostMotionAnchorMath::State nextState {};
        DirectX::XMFLOAT4X4 view {};
        uint32_t frame = 0;
        bool active = false, refresh = false, recorded = false;
    };
    struct Context
    {
        Charge charge;
        Microsoft::WRL::ComPtr<ID3D12Device> device;
        std::shared_ptr<Family> family;
        uint32_t width = 0, height = 0, stride = 0, lastFrame = 0;
        bool valid = false;
        Resource providerSpec, providerDiff, keyLevel, keyDepth, stats, recalled, gain, sums;
        Pipeline statsPass, gainPass, applyPass;
        PostMotionAnchorMath::State state {};
        DirectX::XMFLOAT4X4 previousView {};
        std::array<std::shared_ptr<Slot>,NrdBridgeCaptureBudget::Family::Capacity> slots {};
        std::weak_ptr<Recording> pending;
    };
    std::shared_ptr<Context> context_;
    static void Check(HRESULT hr,const char* reason) { if (FAILED(hr)) throw std::runtime_error(reason); }
    static D3D12_RESOURCE_BARRIER Transition(ID3D12Resource* r,D3D12_RESOURCE_STATES a,D3D12_RESOURCE_STATES b) noexcept
    {
        D3D12_RESOURCE_BARRIER t {}; t.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        t.Transition = {r,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,a,b}; return t;
    }
    static D3D12_RESOURCE_DESC Buffer(uint64_t bytes) noexcept
    {
        D3D12_RESOURCE_DESC d {}; d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        d.Width = bytes; d.Height = d.DepthOrArraySize = d.MipLevels = 1;
        d.SampleDesc.Count = 1; d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR; return d;
    }
    static D3D12_RESOURCE_DESC Texture(uint32_t width,uint32_t height,DXGI_FORMAT format,uint16_t slices = 1) noexcept
    {
        D3D12_RESOURCE_DESC d {}; d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        d.Width = width; d.Height = height; d.Format = format; d.DepthOrArraySize = slices;
        d.MipLevels = d.SampleDesc.Count = 1; d.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS; return d;
    }
    static void PipelineFrom(ID3D12Device* device,const void* data,size_t bytes,Pipeline& p)
    {
        Check(device->CreateRootSignature(0,data,bytes,IID_PPV_ARGS(&p.root)),"Native anchor root creation failed");
        D3D12_COMPUTE_PIPELINE_STATE_DESC d {}; d.pRootSignature = p.root.Get(); d.CS = {data,bytes};
        Check(device->CreateComputePipelineState(&d,IID_PPV_ARGS(&p.pso)),"Native anchor PSO creation failed");
    }
    static std::shared_ptr<Context> Create(ID3D12Device* device,const ConvertedResources& in,const std::shared_ptr<Family>& family)
    {
        auto c = MakeOwnedShared<Context>(); c->device = device; c->family = family;
        c->width = in.width; c->height = in.height;
        c->stride = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        const uint32_t x = std::max(in.width/8u,1u), y = std::max(in.height/8u,1u);
        struct Plan { Resource* target; D3D12_RESOURCE_DESC desc; D3D12_RESOURCE_STATES state; };
        std::array<Plan,8> plans {{
            {&c->providerSpec,Texture(in.width,in.height,DXGI_FORMAT_R16G16B16A16_FLOAT),Read},
            {&c->providerDiff,Texture(in.width,in.height,DXGI_FORMAT_R16G16B16A16_FLOAT),Read},
            {&c->keyLevel,Texture(x,y,DXGI_FORMAT_R16G16B16A16_FLOAT,PostMotionAnchorMath::kRingSize),Read},
            {&c->keyDepth,Texture(x,y,DXGI_FORMAT_R32_FLOAT,PostMotionAnchorMath::kRingSize),Read},
            {&c->stats,Texture(x,y,DXGI_FORMAT_R16G16B16A16_FLOAT),Read},
            {&c->recalled,Texture(x,y,DXGI_FORMAT_R16G16B16A16_FLOAT),Read},
            {&c->gain,Texture(x,y,DXGI_FORMAT_R16G16B16A16_FLOAT),Read},
            {&c->sums,Buffer(32),D3D12_RESOURCE_STATE_COMMON}}};
        plans.back().desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        uint64_t bytes = 0;
        for (const auto& p:plans)
        {
            const auto n = device->GetResourceAllocationInfo(0,1,&p.desc).SizeInBytes;
            if (!n || n == UINT64_MAX || n > UINT64_MAX-bytes) throw std::runtime_error("Native anchor allocation extent invalid");
            bytes += n;
        }
        c->charge.Acquire(family,bytes);
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        for (const auto& p:plans) Check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&p.desc,p.state,
            nullptr,IID_PPV_ARGS(p.target->GetAddressOf())),"Native anchor texture allocation failed");
        PipelineFrom(device,FSRDNrdPostMotionAnchorStatsRecall_cso,sizeof(FSRDNrdPostMotionAnchorStatsRecall_cso),c->statsPass);
        PipelineFrom(device,FSRDNrdPostMotionAnchorGain_cso,sizeof(FSRDNrdPostMotionAnchorGain_cso),c->gainPass);
        PipelineFrom(device,FSRDPostMotionAnchorApply_cso,sizeof(FSRDPostMotionAnchorApply_cso),c->applyPass);
        return c;
    }
    static NrdBridgeCaptureBudget::Permit Reserve(const std::shared_ptr<Family>& family)
    {
        auto p = NrdBridgeCaptureBudget::Permit::TryAcquire(std::shared_ptr<NrdBridgeCaptureBudget::Family>(family,&family->slots));
        if (!p) throw std::runtime_error("Native anchor family slot capacity reached"); return p;
    }
    static std::shared_ptr<Slot> Acquire(Context& c,NrdBridgeCaptureBudget::Permit reservation = {})
    {
        for (const auto& s:c.slots) if (s && s.use_count() == 1) return s;
        auto acquired = reservation ? std::move(reservation) : Reserve(c.family);
        auto s = MakeOwnedShared<Slot>(std::move(acquired)); auto d = Buffer(2048);
        s->bytes = c.device->GetResourceAllocationInfo(0,1,&d).SizeInBytes;
        if (!s->permit.SetBytes(s->bytes)) throw std::runtime_error("Native anchor constant extent invalid");
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_UPLOAD;
        Check(c.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,D3D12_RESOURCE_STATE_GENERIC_READ,
            nullptr,IID_PPV_ARGS(&s->constants)),"Native anchor constants allocation failed");
        D3D12_RANGE empty {0,0}; Check(s->constants->Map(0,&empty,reinterpret_cast<void**>(&s->mapped)),"Native anchor constants map failed");
        std::memset(s->mapped,0,2048); // bytes1536..1567 are the immutable sums reset.
        D3D12_DESCRIPTOR_HEAP_DESC hd {}; hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        hd.NumDescriptors = 18; hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        Check(c.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&s->descriptors)),"Native anchor descriptor allocation failed");
        for (auto& target:c.slots) if (!target) { target = s; return s; }
        throw std::runtime_error("Native anchor context slot capacity reached");
    }
    static void Srv(ID3D12Device* device,ID3D12Resource* resource,D3D12_CPU_DESCRIPTOR_HANDLE at)
    {
        const auto r = resource->GetDesc(); D3D12_SHADER_RESOURCE_VIEW_DESC d {};
        d.Format = r.Format; d.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        if (r.DepthOrArraySize > 1)
        { d.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2DARRAY; d.Texture2DArray.MipLevels = 1; d.Texture2DArray.ArraySize = r.DepthOrArraySize; }
        else { d.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D; d.Texture2D.MipLevels = 1; }
        device->CreateShaderResourceView(resource,&d,at);
    }
    static void Uav(ID3D12Device* device,ID3D12Resource* resource,D3D12_CPU_DESCRIPTOR_HANDLE at)
    {
        const auto r = resource->GetDesc(); D3D12_UNORDERED_ACCESS_VIEW_DESC d {}; d.Format = r.Format;
        if (r.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER)
        { d.Format = DXGI_FORMAT_R32_TYPELESS; d.ViewDimension = D3D12_UAV_DIMENSION_BUFFER; d.Buffer.NumElements = UINT(r.Width/4); d.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW; }
        else if (r.DepthOrArraySize > 1)
        { d.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2DARRAY; d.Texture2DArray.ArraySize = r.DepthOrArraySize; }
        else d.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
        device->CreateUnorderedAccessView(resource,nullptr,&d,at);
    }
    template<class Constants,size_t N,size_t M>
    static void Describe(Context& c,Slot& s,uint32_t index,uint32_t offset,uint32_t& descriptor,Pipeline& pipeline,
        const Constants& constants,const std::array<ID3D12Resource*,N>& reads,const std::array<ID3D12Resource*,M>& writes)
    {
        auto& p = s.passes[index]; p.pipeline = &pipeline;
        p.constants = s.constants->GetGPUVirtualAddress()+offset; std::memcpy(s.mapped+offset,&constants,sizeof(constants));
        auto cpu = s.descriptors->GetCPUDescriptorHandleForHeapStart(); cpu.ptr += uint64_t(descriptor)*c.stride;
        p.srv = s.descriptors->GetGPUDescriptorHandleForHeapStart(); p.srv.ptr += uint64_t(descriptor)*c.stride;
        for (auto* r:reads) { Srv(c.device.Get(),r,cpu); cpu.ptr += c.stride; ++descriptor; }
        p.uav = s.descriptors->GetGPUDescriptorHandleForHeapStart(); p.uav.ptr += uint64_t(descriptor)*c.stride;
        for (auto* r:writes) { Uav(c.device.Get(),r,cpu); cpu.ptr += c.stride; ++descriptor; }
    }
    static void Run(ID3D12GraphicsCommandList* list,const Pass& p,uint32_t width,uint32_t height) noexcept
    {
        list->SetPipelineState(p.pipeline->pso.Get()); list->SetComputeRootSignature(p.pipeline->root.Get());
        list->SetComputeRootConstantBufferView(0,p.constants);
        list->SetComputeRootDescriptorTable(1,p.srv); list->SetComputeRootDescriptorTable(2,p.uav);
        list->Dispatch((width+7)/8,(height+7)/8,1);
    }
  public:
    struct Prepared
    {
        std::shared_ptr<void> owner;
        ID3D12Resource *specular = nullptr, *diffuse = nullptr, *gain = nullptr;
        bool active = false, refresh = false;
      private:
        Recording* recording = nullptr;
        friend class NativePostMotionAnchor;
    };
    bool Prepare(ID3D12Device* device,ID3D12GraphicsCommandList* list,const ConvertedResources& in,
        const FrameParameters& frame,bool enabled,float strength,const std::shared_ptr<Family>& family,
        Prepared& out,std::string& error) noexcept
    {
        out = {}; error.clear();
        if (!enabled) { context_.reset(); return true; } // Old GPU owners retain their exact graph.
        try
        {
            FrameSurvey::ScopedInternal internal; ScopedSkipHeapCapture skip;
            if (!device || !list || !family || !in.spec || !in.diff || !in.motion || !in.linearDepth ||
                !in.width || !in.height || !frame.camera.Complete()) throw std::runtime_error("Native anchor inputs incomplete");
            if (!std::isfinite(strength) || strength < 0.0f || strength > 1.0f)
                throw std::runtime_error("Native anchor strength must be finite in [0,1]");
            for (uint32_t row = 0;row < 4;++row) for (uint32_t col = 0;col < 4;++col)
                if (!std::isfinite(frame.camera.view.r[row].m128_f32[col]) ||
                    !std::isfinite(frame.camera.projection.r[row].m128_f32[col]))
                    throw std::runtime_error("Native anchor camera is non-finite");
            // CopyResource is used only for an exact full resource, never an
            // active subrect of a larger maximum-render-size allocation.
            for (auto* signal:{in.spec,in.diff})
            {
                const auto d = signal->GetDesc();
                if (d.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || d.Width != in.width || d.Height != in.height ||
                    d.Format != DXGI_FORMAT_R16G16B16A16_FLOAT || d.DepthOrArraySize != 1 || d.MipLevels != 1 ||
                    d.SampleDesc.Count != 1) throw std::runtime_error("Native anchor requires exact-extent RGBA16F signals");
            }
            if (context_ && (context_->width != in.width || context_->height != in.height || context_->family != family ||
                context_->device.Get() != device)) context_.reset();
            if (context_) if (auto previous = context_->pending.lock(); previous && !previous->recorded)
                throw std::runtime_error("Native anchor has an unrecorded predecessor");
            auto r = MakeOwnedShared<Recording>(); auto c = context_;
            if (!c) { auto permit = Reserve(family); c = Create(device,in,family); r->slot = Acquire(*c,std::move(permit)); }
            else r->slot = Acquire(*c);
            r->context = c; r->list = list; r->frame = frame.frameIndex;
            const std::array<ID3D12Resource*,4> inputs {in.spec,in.diff,in.linearDepth,in.motion};
            for (size_t i = 0;i < inputs.size();++i) r->inputs[i] = inputs[i];
            r->nextState = c->state;
            const bool history = !frame.reset && frame.previousValid && c->valid && c->lastFrame+1u == frame.frameIndex;
            if (!history) r->nextState = {};
            DirectX::XMFLOAT4X4 projection {};
            DirectX::XMStoreFloat4x4(&r->view,DirectX::XMMatrixTranspose(frame.camera.view));
            DirectX::XMStoreFloat4x4(&projection,DirectX::XMMatrixTranspose(frame.camera.projection));
            const auto previousView = history ? c->previousView : r->view;
            PostMotionAnchorMath::StatsRecallConstants stats {}; PostMotionAnchorMath::GainConstants gain {};
            PostMotionAnchorMath::ApplyConstants apply {};
            r->active = PostMotionAnchorMath::BuildFrame(r->nextState,r->view,projection,previousView,true,
                std::clamp(strength,0.0f,1.0f),stats,gain);
            r->refresh = gain.Params4.x > .5f;
            gain.Params4.w = 1.0f; // Native guard: require this cell's static, locally recalled measurement.
            PostMotionAnchorMath::SetSize(stats,gain,apply,in.width,in.height);
            uint32_t descriptor = 0;
            Describe(*c,*r->slot,0,0,descriptor,c->statsPass,stats,
                std::array<ID3D12Resource*,6>{in.diff,in.spec,in.linearDepth,in.motion,c->keyLevel.Get(),c->keyDepth.Get()},
                std::array<ID3D12Resource*,3>{c->stats.Get(),c->recalled.Get(),c->sums.Get()});
            Describe(*c,*r->slot,1,1024,descriptor,c->gainPass,gain,
                std::array<ID3D12Resource*,2>{c->stats.Get(),c->recalled.Get()},
                std::array<ID3D12Resource*,4>{c->gain.Get(),c->keyLevel.Get(),c->keyDepth.Get(),c->sums.Get()});
            Describe(*c,*r->slot,2,1280,descriptor,c->applyPass,apply,
                std::array<ID3D12Resource*,1>{c->gain.Get()},
                std::array<ID3D12Resource*,2>{c->providerDiff.Get(),c->providerSpec.Get()});
            c->pending = r; context_ = c;
            out.owner = r; out.recording = r.get(); out.active = r->active; out.refresh = r->refresh; out.gain = c->gain.Get();
            out.specular = r->active ? c->providerSpec.Get() : in.spec;
            out.diffuse = r->active ? c->providerDiff.Get() : in.diff; return true;
        }
        catch (const std::exception& e) { try { error = e.what(); } catch (...) {} }
        catch (...) { try { error = "Native anchor preparation failed"; } catch (...) {} }
        context_.reset(); return false;
    }
    void RecordInputs(ID3D12GraphicsCommandList* list,const Prepared& prepared) noexcept
    {
        auto* r = prepared.recording;
        if (!r || r != prepared.owner.get() || r->recorded || list != r->list) return;
        auto& c = *r->context; auto& s = *r->slot;
        if (r->active || r->refresh)
        {
            ID3D12DescriptorHeap* heaps[] {s.descriptors.Get()}; list->SetDescriptorHeaps(1,heaps);
            const uint32_t x = std::max(c.width/8u,1u), y = std::max(c.height/8u,1u);
            // The buffer always returns COMMON; no guessed buffer decay state.
            auto reset = Transition(c.sums.Get(),D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COPY_DEST);
            list->ResourceBarrier(1,&reset); list->CopyBufferRegion(c.sums.Get(),0,s.constants.Get(),1536,32);
            std::array<D3D12_RESOURCE_BARRIER,3> before {
                Transition(c.stats.Get(),Read,Write),Transition(c.recalled.Get(),Read,Write),
                Transition(c.sums.Get(),D3D12_RESOURCE_STATE_COPY_DEST,Write)};
            list->ResourceBarrier(UINT(before.size()),before.data()); Run(list,s.passes[0],x,y);
            before[0] = Transition(c.stats.Get(),Write,Read); before[1] = Transition(c.recalled.Get(),Write,Read);
            before[2] = {}; before[2].Type = D3D12_RESOURCE_BARRIER_TYPE_UAV; before[2].UAV.pResource = c.sums.Get();
            list->ResourceBarrier(UINT(before.size()),before.data());
            before = {Transition(c.gain.Get(),Read,Write),Transition(c.keyLevel.Get(),Read,Write),Transition(c.keyDepth.Get(),Read,Write)};
            list->ResourceBarrier(UINT(before.size()),before.data()); Run(list,s.passes[1],x,y);
            for (auto& b:before) std::swap(b.Transition.StateBefore,b.Transition.StateAfter);
            list->ResourceBarrier(UINT(before.size()),before.data());
            reset = Transition(c.sums.Get(),Write,D3D12_RESOURCE_STATE_COMMON); list->ResourceBarrier(1,&reset);
            if (r->active)
            {
                for (uint32_t i = 0;i < 2;++i)
                {
                    auto* source = r->inputs[i].Get(); auto* destination = i ? c.providerDiff.Get() : c.providerSpec.Get();
                    D3D12_RESOURCE_BARRIER copy[] {Transition(source,Read,D3D12_RESOURCE_STATE_COPY_SOURCE),
                        Transition(destination,Read,D3D12_RESOURCE_STATE_COPY_DEST)};
                    list->ResourceBarrier(2,copy); list->CopyResource(destination,source);
                    copy[0] = Transition(source,D3D12_RESOURCE_STATE_COPY_SOURCE,Read);
                    copy[1] = Transition(destination,D3D12_RESOURCE_STATE_COPY_DEST,Write); list->ResourceBarrier(2,copy);
                }
                Run(list,s.passes[2],c.width,c.height);
                D3D12_RESOURCE_BARRIER restore[] {Transition(c.providerSpec.Get(),Write,Read),Transition(c.providerDiff.Get(),Write,Read)};
                list->ResourceBarrier(2,restore);
            }
        }
        c.state = r->nextState; c.previousView = r->view; c.lastFrame = r->frame; c.valid = true; r->recorded = true;
    }
    // Cancellation must abandon the entire physical graph: an unsubmitted key
    // copy cannot be made valid by a later CPU-only state reset. Old GPU owners
    // retain their old graph; the next successful run creates a fresh one.
    void DiscardRecordingHistory() noexcept { context_.reset(); }
    uint64_t OwnedTextureBytes() const noexcept { return context_ ? context_->charge.bytes : 0; }
    uint64_t OwnedAuxiliaryBytes() const noexcept
    { uint64_t bytes = 0; if (context_) for (const auto& s:context_->slots) if (s) bytes += s->bytes; return bytes; }
};
}
