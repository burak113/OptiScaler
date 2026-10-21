#include "NativeColourPass_Dx12.h"
#include <wrl/client.h>
#include <algorithm>
#include <cstring>
#include <stdexcept>
#include <utility>

namespace NativeColour
{
namespace
{
using Microsoft::WRL::ComPtr;
constexpr auto Read = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
constexpr auto Write = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
constexpr auto CopyIn = D3D12_RESOURCE_STATE_COPY_DEST;
constexpr auto CopyOut = D3D12_RESOURCE_STATE_COPY_SOURCE;
constexpr uint32_t DescriptorCount = 9;
constexpr uint64_t DescriptorPolicyReservation = 2*65536;
void Check(HRESULT hr) { if (FAILED(hr)) throw std::runtime_error("native colour allocation failed"); }
bool SameDevice(ID3D12Device* a, ID3D12Device* b) noexcept
{
    ComPtr<IUnknown> aa, bb;
    return a && b && SUCCEEDED(a->QueryInterface(IID_PPV_ARGS(&aa))) &&
        SUCCEEDED(b->QueryInterface(IID_PPV_ARGS(&bb))) && aa.Get() == bb.Get();
}
bool ValidState(D3D12_RESOURCE_STATES state) noexcept
{ return state == Read || state == Write || state == CopyOut; }
D3D12_RESOURCE_DESC Buffer(uint64_t bytes, bool uav = false) noexcept
{
    D3D12_RESOURCE_DESC x {};
    x.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER; x.Width=bytes;
    x.Height=x.DepthOrArraySize=x.MipLevels=x.SampleDesc.Count=1;
    x.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    x.Flags=uav ? D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS : D3D12_RESOURCE_FLAG_NONE;
    return x;
}
D3D12_RESOURCE_DESC TextureDesc(uint32_t w, uint32_t h, DXGI_FORMAT format) noexcept
{
    D3D12_RESOURCE_DESC x {};
    x.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D; x.Width=w; x.Height=h;
    x.DepthOrArraySize=x.MipLevels=x.SampleDesc.Count=1; x.Format=format;
    x.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
    return x;
}
D3D12_RESOURCE_BARRIER Transition(ID3D12Resource* r, D3D12_RESOURCE_STATES a,
                                  D3D12_RESOURCE_STATES b) noexcept
{
    D3D12_RESOURCE_BARRIER x {}; x.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    x.Transition.pResource=r; x.Transition.StateBefore=a; x.Transition.StateAfter=b;
    x.Transition.Subresource=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES; return x;
}
D3D12_RESOURCE_BARRIER Uav(ID3D12Resource* r) noexcept
{
    D3D12_RESOURCE_BARRIER x {}; x.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;
    x.UAV.pResource=r; return x;
}
void TransitionOne(ID3D12GraphicsCommandList* list, ID3D12Resource* r,
                   D3D12_RESOURCE_STATES a, D3D12_RESOURCE_STATES b) noexcept
{ if(a!=b) { const auto barrier=Transition(r,a,b); list->ResourceBarrier(1,&barrier); } }
struct Charge
{
    Budget budget;
    uint64_t amount = 0;
    bool Acquire(const Budget& b, uint64_t bytes) noexcept
    {
        if (!b.owner || !b.bytes || !b.peakBytes || b.bytes==b.peakBytes || !b.slots || !b.byteLimit ||
            !b.slotLimit || !bytes || bytes>b.byteLimit) return false;
        uint32_t count=b.slots->load(std::memory_order_acquire);
        for (;;) {
            if (count>=b.slotLimit) return false;
            if (b.slots->compare_exchange_weak(count,count+1,std::memory_order_acq_rel)) break;
        }
        uint64_t current=b.bytes->load(std::memory_order_acquire);
        for (;;) {
            if (current>b.byteLimit || bytes>b.byteLimit-current)
            { b.slots->fetch_sub(1,std::memory_order_acq_rel); return false; }
            if (b.bytes->compare_exchange_weak(current,current+bytes,std::memory_order_acq_rel)) break;
        }
        uint64_t peak=b.peakBytes->load(std::memory_order_relaxed);
        while (peak<current+bytes && !b.peakBytes->compare_exchange_weak(peak,current+bytes,std::memory_order_relaxed)) {}
        budget=b; amount=bytes; return true;
    }
    ~Charge()
    {
        if(amount) { budget.bytes->fetch_sub(amount,std::memory_order_acq_rel);
            budget.slots->fetch_sub(1,std::memory_order_acq_rel); }
    }
};
} // namespace

struct NativeColourPass::Recording
{
    Charge charge; // Declared first, destroyed AFTER every owned resource.
    std::array<std::shared_ptr<void>,7> inputOwners;
    std::array<ComPtr<ID3D12Resource>,7> inputs;
    std::array<ComPtr<ID3D12Resource>,4> packed;
    ComPtr<ID3D12Resource> output, diagnostic, upload;
    ComPtr<ID3D12DescriptorHeap> descriptors, clearDescriptors;
    ComPtr<ID3D12RootSignature> root;
    ComPtr<ID3D12PipelineState> pipeline;
    std::array<D3D12_PLACED_SUBRESOURCE_FOOTPRINT,4> footprints {};
    std::array<D3D12_RESOURCE_BARRIER,3> coloursToCopy {}, coloursRestore {};
    std::array<D3D12_RESOURCE_BARRIER,4> guidesToRead {}, guidesRestore {};
    uint32_t colourBarriers=0, guideBarriers=0;
    D3D12_GPU_DESCRIPTOR_HANDLE srv {}, uav {}, diagnosticGpu {};
    D3D12_CPU_DESCRIPTOR_HANDLE diagnosticCpu {};
    D3D12_GPU_VIRTUAL_ADDRESS constants=0;
    ID3D12GraphicsCommandList* list=nullptr; // Exact retained recording's borrow.
    Identity identity {};
    Memory memory {};
    bool recorded=false;
};

Decision NativeColourPass::Prepare(ID3D12Device* device, ID3D12GraphicsCommandList* list,
    const Inputs& in, const Config& cfg, const Budget& budget, D3D12_SHADER_BYTECODE shader,
    Prepared& prepared) noexcept
{
    // Do not overwrite a live prepared recording supplied by an erroneous caller.
    // Its owner may already be referenced by a retained DispatchLease.
    if (prepared.owner) return Decision::InvalidRecording;
    prepared={};
    const auto done=[&](Decision why) { prepared.decision=why; return why; };
    const Decision contract=Validate(cfg,in.frame,in.evidence);
    if (contract!=Decision::Ready) return done(contract);
    if (!device || !list || !shader.pShaderBytecode || !shader.BytecodeLength ||
        (list->GetType()!=D3D12_COMMAND_LIST_TYPE_DIRECT && list->GetType()!=D3D12_COMMAND_LIST_TYPE_COMPUTE))
        return done(Decision::InvalidNativeResource);
    if (!budget.owner || !budget.bytes || !budget.peakBytes || budget.bytes==budget.peakBytes || !budget.slots ||
        !budget.byteLimit || !budget.slotLimit) return done(Decision::MissingBudget);
    ComPtr<ID3D12Device> other;
    if (FAILED(list->GetDevice(IID_PPV_ARGS(&other))) || !SameDevice(device,other.Get()))
        return done(Decision::InvalidNativeResource);
    const std::array<const Texture*,7> input {&in.source,&in.rawRR,&in.selected,&in.depth,
        &in.normalRoughness,&in.authority,&in.support};
    constexpr std::array<DXGI_FORMAT,7> formats {DXGI_FORMAT_R16G16B16A16_FLOAT,
        DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R32_FLOAT,
        DXGI_FORMAT_R10G10B10A2_UNORM,DXGI_FORMAT_R32_UINT,DXGI_FORMAT_R32_UINT};
    // Prepare precedes provider/selection writes. A pre-provider source snapshot
    // cannot share their mutable resource even though this pass only reads it.
    // Canonical raw==selected remains the normal and supported no-recovery case.
    if(in.source.resource==in.rawRR.resource || in.source.resource==in.selected.resource)
        return done(Decision::InvalidNativeResource);
    std::array<D3D12_RESOURCE_DESC,7> descriptions {};
    for (size_t i=0;i<input.size();++i)
    {
        const auto& t=*input[i];
        if(!t.resource || !t.owner || !SameIdentity(t.identity,in.frame.identity) || !ValidState(t.state))
            return done(Decision::InvalidNativeResource);
        const auto d=t.resource->GetDesc(); descriptions[i]=d;
        if(d.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D || !d.Width || !d.Height ||
            d.Width>MaxTextureDimension || d.Height>MaxTextureDimension ||
            d.Width<in.frame.identity.activeWidth || d.Height<in.frame.identity.activeHeight ||
            d.DepthOrArraySize!=1 || d.MipLevels!=1 || d.SampleDesc.Count!=1 ||
            d.SampleDesc.Quality!=0 || d.Format!=formats[i] ||
            (i>=3 && (d.Flags&D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE)) ||
            (t.state==Write && !(d.Flags&D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS)))
            return done(Decision::InvalidNativeResource);
        other.Reset();
        if(FAILED(t.resource->GetDevice(IID_PPV_ARGS(&other))) || !SameDevice(device,other.Get()))
            return done(Decision::InvalidNativeResource);
        // Other read roles can alias, but an alias cannot have conflicting state.
        for(size_t j=0;j<i;++j)
            if(t.resource==input[j]->resource && t.state!=input[j]->state)
                return done(Decision::InvalidNativeResource);
    }
    try
    {
        auto r=std::make_shared<Recording>(); r->list=list; r->identity=in.frame.identity;
        for(size_t i=0;i<input.size();++i)
        { r->inputs[i]=input[i]->resource; r->inputOwners[i]=input[i]->owner; }
        for(size_t i=0;i<3;++i)
        {
            UINT rows=0; UINT64 rowBytes=0,total=0;
            device->GetCopyableFootprints(&descriptions[i],0,1,512,&r->footprints[i],&rows,&rowBytes,&total);
            const auto& p=r->footprints[i];
            if(p.Offset!=512 || p.Footprint.Format!=formats[i] || p.Footprint.Width!=descriptions[i].Width ||
                p.Footprint.Height!=descriptions[i].Height || p.Footprint.Depth!=1 || rows!=descriptions[i].Height ||
                rowBytes!=descriptions[i].Width*8 || total==UINT64_MAX)
                return done(Decision::InvalidLayout);
            // D3D12's returned total omits last-row padding. Reserve and initialize
            // the full pitched span plus prefix AND suffix guards instead.
            auto& l=r->memory.packed[i];
            l.width=p.Footprint.Width; l.height=p.Footprint.Height; l.rowPitch=p.Footprint.RowPitch;
            l.offset=p.Offset; l.bytes=p.Offset+uint64_t(l.rowPitch)*l.height+512;
            if(!ValidLayout(l,r->identity.activeWidth,r->identity.activeHeight) || total>l.bytes)
                return done(Decision::InvalidLayout);
        }
        r->footprints[3]=r->footprints[2]; r->memory.packed[3]=r->memory.packed[2];
        const uint64_t maxPacked=(std::max)({r->memory.packed[0].bytes,r->memory.packed[1].bytes,r->memory.packed[2].bytes});
        const uint64_t constantOffset=(maxPacked+255)&~uint64_t(255);
        r->memory.uploadLogicalBytes=constantOffset+ConstantAllocationBytes;
        std::array<D3D12_RESOURCE_DESC,7> plan {};
        for(size_t i=0;i<4;++i) plan[i]=Buffer(r->memory.packed[i].bytes,i==3);
        plan[4]=TextureDesc(r->memory.packed[2].width,r->memory.packed[2].height,DXGI_FORMAT_R16G16B16A16_FLOAT);
        plan[5]=TextureDesc(r->memory.packed[2].width,r->memory.packed[2].height,DXGI_FORMAT_R32G32B32A32_FLOAT);
        plan[6]=Buffer(r->memory.uploadLogicalBytes);
        for(size_t i=0;i<plan.size();++i)
        {
            const uint64_t allocation=device->GetResourceAllocationInfo(0,1,&plan[i]).SizeInBytes;
            if(!allocation || allocation==UINT64_MAX || allocation>UINT64_MAX-r->memory.budgetChargeBytes)
                return done(Decision::InvalidLayout);
            if(i==6) r->memory.uploadAllocationBytes+=allocation;
            else r->memory.defaultAllocationBytes+=allocation;
            r->memory.budgetChargeBytes+=allocation;
        }
        r->memory.descriptorReservationBytes=DescriptorPolicyReservation;
        if(r->memory.budgetChargeBytes>UINT64_MAX-DescriptorPolicyReservation) return done(Decision::InvalidLayout);
        r->memory.budgetChargeBytes+=DescriptorPolicyReservation;
        if(!r->charge.Acquire(budget,r->memory.budgetChargeBytes)) return done(Decision::BudgetExceeded);
        D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        for(size_t i=0;i<4;++i)
            Check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&plan[i],CopyIn,nullptr,IID_PPV_ARGS(&r->packed[i])));
        Check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&plan[4],Write,nullptr,IID_PPV_ARGS(&r->output)));
        Check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&plan[5],Write,nullptr,IID_PPV_ARGS(&r->diagnostic)));
        heap.Type=D3D12_HEAP_TYPE_UPLOAD;
        Check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&plan[6],D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&r->upload)));
        void* mapped=nullptr; const D3D12_RANGE readRange {0,0};
        Check(r->upload->Map(0,&readRange,&mapped));
        std::memset(mapped,0xcd,size_t(r->memory.uploadLogicalBytes));
        const auto constants=MakeConstants(cfg,in.frame,r->memory.packed);
        std::memset(static_cast<uint8_t*>(mapped)+constantOffset,0,ConstantAllocationBytes);
        std::memcpy(static_cast<uint8_t*>(mapped)+constantOffset,&constants,sizeof(constants));
        const D3D12_RANGE writtenRange {0,size_t(r->memory.uploadLogicalBytes)};
        r->upload->Unmap(0,&writtenRange);
        const auto baseAddress=r->upload->GetGPUVirtualAddress();
        if(!baseAddress || baseAddress>UINT64_MAX-constantOffset) return done(Decision::InvalidLayout);
        r->constants=baseAddress+constantOffset;
        if(r->constants%D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT)
            return done(Decision::InvalidLayout);
        Check(device->CreateRootSignature(0,shader.pShaderBytecode,shader.BytecodeLength,IID_PPV_ARGS(&r->root)));
        D3D12_COMPUTE_PIPELINE_STATE_DESC pso {}; pso.pRootSignature=r->root.Get(); pso.CS=shader;
        Check(device->CreateComputePipelineState(&pso,IID_PPV_ARGS(&r->pipeline)));
        D3D12_DESCRIPTOR_HEAP_DESC dh {}; dh.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        dh.NumDescriptors=DescriptorCount; dh.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        Check(device->CreateDescriptorHeap(&dh,IID_PPV_ARGS(&r->descriptors)));
        D3D12_DESCRIPTOR_HEAP_DESC clearHeap=dh;
        clearHeap.NumDescriptors=1; clearHeap.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
        Check(device->CreateDescriptorHeap(&clearHeap,IID_PPV_ARGS(&r->clearDescriptors)));
        const auto stride=device->GetDescriptorHandleIncrementSize(dh.Type);
        if(!stride) return done(Decision::InvalidNativeResource);
        const auto cpu=r->descriptors->GetCPUDescriptorHandleForHeapStart();
        const auto gpu=r->descriptors->GetGPUDescriptorHandleForHeapStart();
        for(size_t i=0;i<7;++i)
        {
            D3D12_SHADER_RESOURCE_VIEW_DESC v {}; v.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            if(i<3) { v.Format=DXGI_FORMAT_R32_TYPELESS; v.ViewDimension=D3D12_SRV_DIMENSION_BUFFER;
                v.Buffer.NumElements=UINT(r->memory.packed[i].bytes/4); v.Buffer.Flags=D3D12_BUFFER_SRV_FLAG_RAW; }
            else { v.Format=formats[i]; v.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D; v.Texture2D.MipLevels=1; }
            const D3D12_CPU_DESCRIPTOR_HANDLE h {cpu.ptr+i*stride};
            device->CreateShaderResourceView(i<3?r->packed[i].Get():r->inputs[i].Get(),&v,h);
        }
        D3D12_UNORDERED_ACCESS_VIEW_DESC bv {}; bv.Format=DXGI_FORMAT_R32_TYPELESS;
        bv.ViewDimension=D3D12_UAV_DIMENSION_BUFFER; bv.Buffer.NumElements=UINT(r->memory.packed[3].bytes/4);
        bv.Buffer.Flags=D3D12_BUFFER_UAV_FLAG_RAW;
        const D3D12_CPU_DESCRIPTOR_HANDLE bh {cpu.ptr+7*stride};
        device->CreateUnorderedAccessView(r->packed[3].Get(),nullptr,&bv,bh);
        D3D12_UNORDERED_ACCESS_VIEW_DESC dv {}; dv.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
        dv.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
        const D3D12_CPU_DESCRIPTOR_HANDLE shaderDiagnostic {cpu.ptr+8*stride};
        r->diagnosticCpu=r->clearDescriptors->GetCPUDescriptorHandleForHeapStart();
        r->diagnosticGpu={gpu.ptr+8*stride};
        device->CreateUnorderedAccessView(r->diagnostic.Get(),nullptr,&dv,shaderDiagnostic);
        device->CreateUnorderedAccessView(r->diagnostic.Get(),nullptr,&dv,r->diagnosticCpu);
        r->srv=gpu; r->uav={gpu.ptr+7*stride};
        for(size_t i=0;i<input.size();++i)
        {
            bool unique=true;
            for(size_t j=0;j<i;++j) if(input[i]->resource==input[j]->resource) unique=false;
            const auto destination=i<3?CopyOut:Read;
            if(!unique || input[i]->state==destination) continue;
            const auto go=Transition(input[i]->resource,input[i]->state,destination);
            const auto back=Transition(input[i]->resource,destination,input[i]->state);
            if(i<3) { r->coloursToCopy[r->colourBarriers]=go; r->coloursRestore[r->colourBarriers++]=back; }
            else { r->guidesToRead[r->guideBarriers]=go; r->guidesRestore[r->guideBarriers++]=back; }
        }
        prepared.output=r->output.Get(); prepared.diagnostic=r->diagnostic.Get();
        prepared.packedOutput=r->packed[3].Get(); prepared.memory=r->memory;
        prepared.owner=std::move(r); return done(Decision::Ready);
    }
    catch (...) { return done(Decision::AllocationFailed); }
}

bool NativeColourPass::CanRecord(ID3D12GraphicsCommandList* list, uint64_t recording,
                                 const Prepared& prepared) noexcept
{
    const auto& r=prepared.owner;
    return r && list && r->list==list && recording && r->identity.recording==recording && !r->recorded &&
        prepared.decision==Decision::Ready && prepared.output==r->output.Get() &&
        prepared.diagnostic==r->diagnostic.Get() && prepared.packedOutput==r->packed[3].Get();
}
bool NativeColourPass::Record(ID3D12GraphicsCommandList* list, uint64_t recording,
                              const Prepared& prepared) noexcept
{
    if(!CanRecord(list,recording,prepared)) return false;
    auto& r=*prepared.owner; r.recorded=true;
    for(size_t i=0;i<3;++i)
        list->CopyBufferRegion(r.packed[i].Get(),0,r.upload.Get(),0,r.memory.packed[i].bytes);
    if(r.colourBarriers) list->ResourceBarrier(r.colourBarriers,r.coloursToCopy.data());
    for(size_t i=0;i<3;++i)
    {
        D3D12_TEXTURE_COPY_LOCATION from {},to {};
        from.pResource=r.inputs[i].Get(); from.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        to.pResource=r.packed[i].Get(); to.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        to.PlacedFootprint=r.footprints[i];
        list->CopyTextureRegion(&to,0,0,0,&from,nullptr);
    }
    if(r.colourBarriers) list->ResourceBarrier(r.colourBarriers,r.coloursRestore.data());
    TransitionOne(list,r.packed[2].Get(),CopyIn,CopyOut);
    list->CopyBufferRegion(r.packed[3].Get(),0,r.packed[2].Get(),0,r.memory.packed[3].bytes);
    TransitionOne(list,r.packed[2].Get(),CopyOut,Read);
    TransitionOne(list,r.packed[0].Get(),CopyIn,Read); TransitionOne(list,r.packed[1].Get(),CopyIn,Read);
    TransitionOne(list,r.packed[3].Get(),CopyIn,Write);
    if(r.guideBarriers) list->ResourceBarrier(r.guideBarriers,r.guidesToRead.data());
    ID3D12DescriptorHeap* heaps [] {r.descriptors.Get()}; list->SetDescriptorHeaps(1,heaps);
    constexpr float zero[4] {0,0,0,0};
    list->ClearUnorderedAccessViewFloat(r.diagnosticGpu,r.diagnosticCpu,r.diagnostic.Get(),zero,0,nullptr);
    const auto clearBarrier=Uav(r.diagnostic.Get()); list->ResourceBarrier(1,&clearBarrier);
    list->SetComputeRootSignature(r.root.Get()); list->SetPipelineState(r.pipeline.Get());
    list->SetComputeRootConstantBufferView(0,r.constants);
    list->SetComputeRootDescriptorTable(1,r.srv); list->SetComputeRootDescriptorTable(2,r.uav);
    list->Dispatch((r.identity.activeWidth+7)/8,(r.identity.activeHeight+7)/8,1);
    const std::array<D3D12_RESOURCE_BARRIER,2> complete {Uav(r.packed[3].Get()),Uav(r.diagnostic.Get())};
    list->ResourceBarrier(UINT(complete.size()),complete.data());
    if(r.guideBarriers) list->ResourceBarrier(r.guideBarriers,r.guidesRestore.data());
    TransitionOne(list,r.packed[3].Get(),Write,CopyOut);
    TransitionOne(list,r.output.Get(),Write,CopyIn);
    D3D12_TEXTURE_COPY_LOCATION from {},to {};
    from.pResource=r.packed[3].Get(); from.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    from.PlacedFootprint=r.footprints[3];
    to.pResource=r.output.Get(); to.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    list->CopyTextureRegion(&to,0,0,0,&from,nullptr);
    TransitionOne(list,r.output.Get(),CopyIn,Write);
    TransitionOne(list,r.packed[3].Get(),CopyOut,CopyIn);
    for(size_t i=0;i<3;++i) TransitionOne(list,r.packed[i].Get(),Read,CopyIn);
    return true;
}
} // namespace NativeColour
