#include "pch.h"
#include "FSRDNrdRawSignals_Dx12.h"
#include "FSRDNrdSignalConstants_Dx12.h"
#include "misc/NrdBridgeOwned_Dx12.h"
#include "misc/NrdBridgeCaptureSlotBudget_Dx12.h"
#include "misc/RecordedComputeLease_Dx12.h"
#include "resource_tracking/ResTrack_Dx12.h"
#include "State.h"
#include "precompile/FSRDNrdRawCapture_Shader.h"
#include "precompile/FSRDNrdRawCaptureRoot_Shader.h"
#include "precompile/FSRDNrdRawDecode_Shader.h"
#include <array>
#include <atomic>
#include <mutex>
#include <stdexcept>
#include <utility>
#include <vector>

namespace NrdBridge
{
namespace
{
using Microsoft::WRL::ComPtr;
constexpr uint64_t kRawByteLimit = uint64_t(2) * 1024 * 1024 * 1024;
constexpr auto kRead = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
struct RawFamily
{
    NrdBridgeCaptureBudget::Family slots;
    std::atomic<uint64_t> bytes {0};
};
struct RawBytes
{
    std::shared_ptr<RawFamily> family;
    uint64_t bytes = 0;
    RawBytes() = default;
    RawBytes(const RawBytes&) = delete;
    RawBytes(RawBytes&& other) noexcept : family(std::move(other.family)), bytes(std::exchange(other.bytes,0)) {}
    ~RawBytes() { if (family) family->bytes.fetch_sub(bytes,std::memory_order_acq_rel); }
    bool Reserve(const std::shared_ptr<RawFamily>& value,uint64_t count) noexcept
    {
        if (!value || family || !count || count > kRawByteLimit) return false;
        auto total = value->bytes.load(std::memory_order_acquire);
        while (total <= kRawByteLimit-count)
            if (value->bytes.compare_exchange_weak(total,total+count,std::memory_order_acq_rel))
            { family=value;bytes=count;return true; }
        return false;
    }
};
void Check(HRESULT value,const char* message)
{
    if (FAILED(value)) throw std::runtime_error(std::string(message)+" (HRESULT "+std::to_string(value)+")");
}
void Transition(ID3D12GraphicsCommandList* list,ID3D12Resource* resource,
                D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after) noexcept
{
    D3D12_RESOURCE_BARRIER barrier {};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition={resource,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after};
    list->ResourceBarrier(1,&barrier);
}
void Pipeline(ID3D12Device* device,const void* code,size_t bytes,ComPtr<ID3D12RootSignature>& root,
              ComPtr<ID3D12PipelineState>& pso)
{
    Check(device->CreateRootSignature(0,code,bytes,IID_PPV_ARGS(&root)),"Raw noisy capture root creation failed");
    D3D12_COMPUTE_PIPELINE_STATE_DESC desc {};desc.pRootSignature=root.Get();desc.CS={code,bytes};
    Check(device->CreateComputePipelineState(&desc,IID_PPV_ARGS(&pso)),"Raw noisy capture pipeline creation failed");
}
struct RawSlot
{
    // Reservations die after all owned native objects, including GPU-leased retired slots.
    RawBytes bytePermit;
    NrdBridgeCaptureBudget::Permit slotPermit;
    RawSlot(RawBytes&& bytes,NrdBridgeCaptureBudget::Permit&& slots) noexcept
        :bytePermit(std::move(bytes)),slotPermit(std::move(slots)){}
    ComPtr<ID3D12Resource> resource;
    ComPtr<ID3D12DescriptorHeap> decodeViews;
    SignalFlagSnapshot flag;
    D3D12_GPU_VIRTUAL_ADDRESS rawAddress=0,flagAddress=0;
};
struct RawContext
{
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12RootSignature> tableRoot,directRoot,decodeRoot;
    ComPtr<ID3D12PipelineState> tablePso,directPso,decodePso;
    SignalFlagCapture captureFlag;
    std::shared_ptr<RawFamily> family;
    std::vector<std::shared_ptr<RawSlot>> slots;
    std::mutex mutex;
    std::atomic<bool> retired {false};
    uint32_t width=0,height=0,stride=0;
    std::shared_ptr<RawSlot> Acquire()
    {
        {
            std::lock_guard lock(mutex);
            if (retired.load(std::memory_order_acquire)) throw std::runtime_error("Raw noisy capture generation is retired");
            for (const auto& slot:slots) if(slot.use_count()==1)return slot;
        }
        auto familySlots=std::shared_ptr<NrdBridgeCaptureBudget::Family>(family,&family->slots);
        auto permit=NrdBridgeCaptureBudget::Permit::TryAcquire(familySlots);
        if(!permit)throw std::runtime_error("Raw noisy capture family has32 allocated snapshot slots");
        D3D12_RESOURCE_DESC raw {};raw.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
        raw.Width=1536+uint64_t(width)*height*16;raw.Height=raw.DepthOrArraySize=raw.MipLevels=1;
        raw.SampleDesc.Count=1;raw.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;raw.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        auto flag=raw;flag.Width=1536;
        const auto rawBytes=device->GetResourceAllocationInfo(0,1,&raw).SizeInBytes;
        const auto flagBytes=device->GetResourceAllocationInfo(0,1,&flag).SizeInBytes;
        if(!rawBytes||rawBytes==UINT64_MAX||!flagBytes||flagBytes==UINT64_MAX||rawBytes>kRawByteLimit||flagBytes>kRawByteLimit-rawBytes)
            throw std::runtime_error("Raw noisy snapshot allocation size is invalid");
        RawBytes bytes;
        if(!bytes.Reserve(family,rawBytes+flagBytes)||!permit.SetBytes(rawBytes+flagBytes))
            throw std::runtime_error("Raw noisy capture family exceeds2GiB of retained owned buffers");
        auto slot=MakeOwnedShared<RawSlot>(std::move(bytes),std::move(permit));
        D3D12_HEAP_PROPERTIES heap {};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        Check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&raw,D3D12_RESOURCE_STATE_COMMON,nullptr,
            IID_PPV_ARGS(&slot->resource)),"Raw noisy snapshot allocation failed");
        std::string error;if(!slot->flag.Initialize(device.Get(),error))throw std::runtime_error(error);
        slot->rawAddress=slot->resource->GetGPUVirtualAddress();slot->flagAddress=slot->flag.resource->GetGPUVirtualAddress();
        D3D12_DESCRIPTOR_HEAP_DESC views {};views.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        views.NumDescriptors=2;views.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        Check(device->CreateDescriptorHeap(&views,IID_PPV_ARGS(&slot->decodeViews)),"Raw decode view allocation failed");
        {
            std::lock_guard lock(mutex);
            if(retired.load(std::memory_order_acquire))throw std::runtime_error("Raw noisy capture generation was retired during preparation");
            slots.push_back(slot);
        }
        return slot;
    }
};
bool HeapMatches(ID3D12Device* device,ID3D12DescriptorHeap* heap,
                 const std::array<D3D12_GPU_DESCRIPTOR_HANDLE,2>& views,std::string& error)
{
    if(!device||!heap){error="Raw noisy source requires its native shader-visible heap";return false;}
    const auto desc=heap->GetDesc();
    if(desc.Type!=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV||!(desc.Flags&D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE)||!desc.NumDescriptors)
    {error="Raw noisy source heap type/visibility is invalid";return false;}
    ComPtr<ID3D12Device> actual;ComPtr<IUnknown> expectedIdentity,actualIdentity;
    if(FAILED(device->QueryInterface(IID_PPV_ARGS(&expectedIdentity)))||FAILED(heap->GetDevice(IID_PPV_ARGS(&actual)))||
       FAILED(actual.As(&actualIdentity))||expectedIdentity.Get()!=actualIdentity.Get())
    {error="Raw noisy native heap device differs from the bridge";return false;}
    const auto start=heap->GetGPUDescriptorHandleForHeapStart().ptr;
    const auto stride=device->GetDescriptorHandleIncrementSize(desc.Type);
    for(const auto view:views)
        if(!start||!stride||view.ptr<start||(view.ptr-start)%stride||(view.ptr-start)/stride>=desc.NumDescriptors)
        {error="Raw noisy native SRV handle is outside its heap";return false;}
    return true;
}
bool OutputMatches(ID3D12Resource* resource,RawContext& context)
{
    if(!resource)return false;const auto desc=resource->GetDesc();
    if(desc.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D||desc.Width!=context.width||desc.Height!=context.height||
       desc.DepthOrArraySize!=1||desc.MipLevels!=1||desc.SampleDesc.Count!=1||desc.Format!=DXGI_FORMAT_R16G16B16A16_FLOAT||
       !(desc.Flags&D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS))return false;
    ComPtr<ID3D12Device> actual;ComPtr<IUnknown> expectedIdentity,actualIdentity;
    return SUCCEEDED(context.device.As(&expectedIdentity))&&SUCCEEDED(resource->GetDevice(IID_PPV_ARGS(&actual)))&&
        SUCCEEDED(actual.As(&actualIdentity))&&actualIdentity.Get()==expectedIdentity.Get();
}
}
struct RawSignalSnapshotPass::Impl
{
    std::mutex mutex;
    std::shared_ptr<RawContext> context;
    std::shared_ptr<RawFamily> family;
};
struct RawSignalRecord
{
    std::shared_ptr<RawContext> context;
    std::shared_ptr<RawSlot> slot;
    std::weak_ptr<RawSignalSnapshotPass::Impl> wrapper;
    std::weak_ptr<RecordedComputeLease::Recording> nativeRecording;
    ID3D12GraphicsCommandList* recording=nullptr;
    uint64_t recordingId=0;
    uint32_t frameSL=UINT32_MAX,bridgeFrame=0;
    NativeRawProfile profile=NativeRawProfile::Unknown;
    mutable std::atomic<uint32_t> phase {0}; // captured,preparing,decoded
};
RawSignalSnapshotPass::RawSignalSnapshotPass()=default;
RawSignalSnapshotPass::~RawSignalSnapshotPass()=default;
bool RawSignalSnapshotPass::Initialize(ID3D12Device* device,uint32_t width,uint32_t height,std::string& error) noexcept
{
    if(!device||!width||!height||width>D3D12_REQ_TEXTURE2D_U_OR_V_DIMENSION||height>D3D12_REQ_TEXTURE2D_U_OR_V_DIMENSION||
       uint64_t(width)*height>(UINT32_MAX-1536)/16)
    {error="Raw noisy capture device/extent is invalid";return false;}
    try
    {
        FrameSurvey::ScopedInternal internal;ScopedSkipHeapCapture skip;
        if(!impl_)impl_=MakeOwnedShared<Impl>();auto owner=impl_;
        std::shared_ptr<RawFamily> family;
        {
            std::lock_guard lock(owner->mutex);
            if(owner->context&&owner->context->device.Get()==device&&owner->context->width==width&&owner->context->height==height)
            {error.clear();return true;}
            if(!owner->family)owner->family=MakeOwnedShared<RawFamily>();family=owner->family;
        }
        auto next=MakeOwnedShared<RawContext>();next->device=device;next->width=width;next->height=height;next->family=family;
        next->stride=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        Pipeline(device,FSRDNrdRawCapture_cso,sizeof(FSRDNrdRawCapture_cso),next->tableRoot,next->tablePso);
        Pipeline(device,FSRDNrdRawCaptureRoot_cso,sizeof(FSRDNrdRawCaptureRoot_cso),next->directRoot,next->directPso);
        Pipeline(device,FSRDNrdRawDecode_cso,sizeof(FSRDNrdRawDecode_cso),next->decodeRoot,next->decodePso);
        if(!next->captureFlag.Initialize(device,error,303)||!next->captureFlag.Initialize(device,error,36))return false;
        next->slots.reserve(NrdBridgeCaptureBudget::Family::Capacity);
        std::shared_ptr<RawContext> previous;std::vector<std::shared_ptr<RawSlot>> retiredSlots;
        {
            std::lock_guard lock(owner->mutex);previous=std::move(owner->context);
            if(previous){previous->retired.store(true,std::memory_order_release);std::lock_guard oldLock(previous->mutex);retiredSlots.swap(previous->slots);}
            owner->context=std::move(next);
        }
        retiredSlots.clear();previous.reset();error.clear();return true;
    }
    catch(const std::exception& exception){error=exception.what();return false;}
    catch(...){error="Raw noisy capture initialization allocation failed";return false;}
}
bool RawSignalSnapshotPass::Capture(ID3D12GraphicsCommandList* list,const RawSignalSource& source,uint32_t frameSL,
                                    uint32_t bridgeFrame,RawSignalLease& out,std::string& error) noexcept
{
    out.reset();if(!list||!impl_){error="Raw noisy capture is not initialized";return false;}
    try
    {
        auto owner=impl_;std::shared_ptr<RawContext> context;{std::lock_guard lock(owner->mutex);context=owner->context;}
        if(!context||source.width!=context->width||source.height!=context->height||frameSL==UINT32_MAX||
           source.profile!=NativeRawProfile::ReconDirect)
        {error="Raw noisy shader addressing profile/extent is unsupported";return false;}
        if(!HeapMatches(context->device.Get(),source.nativeHeap,{source.specSrv,source.diffSrv},error)||
           !HasNativeTitleSignalConstants(source.nativeConstants)||
           !ValidateTitleSignalConstants(source.nativeConstants,context->device.Get(),error))return false;
        if(source.nativeConstants.nativeHeap&&source.nativeConstants.nativeHeap!=source.nativeHeap)
        {error="Raw noisy source SRVs and CBV table require the same native heap";return false;}
        FrameSurvey::ScopedInternal internal;ScopedSkipHeapCapture skip;
        auto record=MakeOwnedShared<RawSignalRecord>();record->context=context;record->slot=context->Acquire();record->wrapper=owner;
        record->recording=list;record->frameSL=frameSL;record->bridgeFrame=bridgeFrame;record->profile=source.profile;
        if(!ResTrack_Dx12::RetainComputeDispatch(context->device.Get(),list,record))
        {error="Raw noisy snapshot GPU lifetime tracking unavailable";return false;}
        const auto native=RecordedComputeLease::Capture(list);
        if(!native||!native->id){error="Raw noisy snapshot native recording identity unavailable";return false;}
        record->nativeRecording=native;record->recordingId=native->id;
        Transition(list,record->slot->resource.Get(),D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        const bool table=source.nativeConstants.nativeHeap!=nullptr;
        list->SetPipelineState(table?context->tablePso.Get():context->directPso.Get());
        list->SetComputeRootSignature(table?context->tableRoot.Get():context->directRoot.Get());
        ID3D12DescriptorHeap* heaps[]={source.nativeHeap};list->SetDescriptorHeaps(1,heaps);
        const uint32_t extent[]={context->width,context->height};list->SetComputeRoot32BitConstants(0,2,extent,0);
        list->SetComputeRootDescriptorTable(1,source.specSrv);list->SetComputeRootDescriptorTable(2,source.diffSrv);
        if(table)list->SetComputeRootDescriptorTable(3,source.nativeConstants.cbvHandle);
        else list->SetComputeRootConstantBufferView(3,source.nativeConstants.address);
        list->SetComputeRootUnorderedAccessView(4,record->slot->rawAddress);
        list->Dispatch((context->width+7)/8,(context->height+7)/8,1);
        Transition(list,record->slot->resource.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COMMON);
        out=std::move(record);error.clear();return true;
    }
    catch(const std::exception& exception){error=exception.what();return false;}
    catch(...){error="Raw noisy snapshot allocation failed";return false;}
}
bool RawSignalSnapshotPass::Decode(ID3D12GraphicsCommandList* list,const RawSignalLease& record,
                                   const ConvertedResources& output,const TitleSignalConstants& constants,std::string& error) noexcept
{
    if(!list||!impl_||!record||record->wrapper.lock()!=impl_){error="Raw decode lease belongs to another helper";return false;}
    auto context=record->context;
    {
        std::lock_guard lock(impl_->mutex);
        if(impl_->context!=context){error="Raw decode generation is no longer current";return false;}
    }
    const auto native=record->nativeRecording.lock(),current=RecordedComputeLease::Capture(list);
    if(record->recording!=list||!native||!current||native!=current||native->id!=record->recordingId||
       output.width!=context->width||output.height!=context->height||output.spec==output.diff||
       !OutputMatches(output.spec,*context)||!OutputMatches(output.diff,*context)||
       !HasNativeTitleSignalConstants(constants)||!ValidateTitleSignalConstants(constants,context->device.Get(),error))
    {if(error.empty())error="Raw decode requires its same live native recording and owned output pair";return false;}
    uint32_t expected=0;if(!record->phase.compare_exchange_strong(expected,1,std::memory_order_acq_rel))
    {error="Raw noisy snapshot can be decoded only once";return false;}
    try
    {
        FrameSurvey::ScopedInternal internal;ScopedSkipHeapCapture skip;
        auto cpu=record->slot->decodeViews->GetCPUDescriptorHandleForHeapStart();
        for(auto* resource:{output.spec,output.diff})
        {
            D3D12_UNORDERED_ACCESS_VIEW_DESC desc {};desc.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;
            desc.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;context->device->CreateUnorderedAccessView(resource,nullptr,&desc,cpu);
            cpu.ptr+=context->stride;
        }
        // No allocation/provider work follows this point. The early same-recording
        // lease owns the slot, both flag profiles and all descriptor resources.
        context->captureFlag.Record(list,constants,record->slot->flag);
        Transition(list,record->slot->resource.Get(),D3D12_RESOURCE_STATE_COMMON,kRead);
        Transition(list,output.spec,kRead,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        Transition(list,output.diff,kRead,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        list->SetPipelineState(context->decodePso.Get());list->SetComputeRootSignature(context->decodeRoot.Get());
        ID3D12DescriptorHeap* heaps[]={record->slot->decodeViews.Get()};list->SetDescriptorHeaps(1,heaps);
        const uint32_t extent[]={context->width,context->height};list->SetComputeRoot32BitConstants(0,2,extent,0);
        list->SetComputeRootShaderResourceView(1,record->slot->rawAddress);
        list->SetComputeRootDescriptorTable(2,record->slot->decodeViews->GetGPUDescriptorHandleForHeapStart());
        list->SetComputeRootConstantBufferView(3,record->slot->flagAddress);
        list->Dispatch((context->width+7)/8,(context->height+7)/8,1);
        Transition(list,output.spec,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,kRead);
        Transition(list,output.diff,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,kRead);
        Transition(list,record->slot->resource.Get(),kRead,D3D12_RESOURCE_STATE_COMMON);
        record->slot->flag.Transition(list,false);record->phase.store(2,std::memory_order_release);
        error.clear();return true;
    }
    catch(const std::exception& exception){record->phase.store(0,std::memory_order_release);error=exception.what();return false;}
    catch(...){record->phase.store(0,std::memory_order_release);error="Raw noisy late decode preparation failed";return false;}
}
RawSignalSnapshot RawSignalSnapshotPass::GetSnapshot(const RawSignalLease& record) noexcept
{
    RawSignalSnapshot result;if(!record)return result;
    result.resource=record->slot->resource.Get();result.geometryConstants=record->slot->rawAddress;result.owner=std::shared_ptr<void>(record,const_cast<RawSignalRecord*>(record.get()));
    result.nativeRecording=record->nativeRecording;result.recording=record->recording;result.recordingId=record->recordingId;
    result.width=record->context->width;result.height=record->context->height;result.frameSL=record->frameSL;
    result.bridgeFrame=record->bridgeFrame;result.profile=record->profile;result.decoded=record->phase.load(std::memory_order_acquire)==2;
    if(result.decoded)
    {
        result.encodingFlag=record->slot->flag.resource.Get();
        result.decodedEncodingConstants.resource=result.encodingFlag;
        result.decodedEncodingConstants.address=record->slot->flagAddress;
        result.decodedEncodingConstants.wordIndex=303;
    }
    return result;
}
uint64_t RawSignalSnapshotPass::OwnedBytes() const noexcept
{
    return impl_&&impl_->family?impl_->family->bytes.load(std::memory_order_acquire):0;
}
uint32_t RawSignalSnapshotPass::OwnedSlots() const noexcept
{
    return impl_&&impl_->family?impl_->family->slots.allocatedSlots.load(std::memory_order_acquire):0;
}
}
