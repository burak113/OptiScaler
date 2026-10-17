// Standalone Windows/D3D12 fence smoke test. Calls the hook adapters explicitly;
// this does NOT test whether a particular game's wrapped queues are detoured.
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <array>
#include <iostream>
#include <cstring>
#include <stdexcept>
#include <future>
#include <chrono>
#include <atomic>
#include <cstdlib>
#include "../../fsrd_preprocess/RRTraceFence.h"
#include "../../fsrd_preprocess/RRTraceAdditiveIO.h"
using Microsoft::WRL::ComPtr;
static void need(bool ok,const char* what) { if (!ok) throw std::runtime_error(what); }
static void hr(HRESULT result,const char* what) { need(SUCCEEDED(result),what); }
// Detours IUnknown::Release of command-list vtables like the title hooks do and
// records any Release that runs while the RRTraceFence registry mutex is held.
namespace ReleaseProbe
{
using ReleaseFn = ULONG (STDMETHODCALLTYPE*)(IUnknown*);
struct Patch { void** vtable = nullptr; ReleaseFn original = nullptr; };
std::array<Patch,2> patches;
std::atomic<bool> armed {false};
std::atomic<unsigned> calls {0}, violations {0};
bool RegistryHeld()
{
    return std::async(std::launch::async,[] {
        auto& mutex = RRTraceFence::GetRegistry().mutex;
        if (!mutex.try_lock()) return true;
        mutex.unlock(); return false;
    }).get();
}
ULONG STDMETHODCALLTYPE Release(IUnknown* self)
{
    void** vtable = *reinterpret_cast<void***>(self);
    for (auto& patch:patches)
        if (patch.vtable == vtable)
        {
            if (armed.load()) { ++calls; if (RegistryHeld()) ++violations; }
            return patch.original(self);
        }
    std::abort();
}
void Swap(void** slot,void* value)
{
    DWORD old = 0; VirtualProtect(slot,sizeof(void*),PAGE_EXECUTE_READWRITE,&old);
    *slot = value; VirtualProtect(slot,sizeof(void*),old,&old);
}
void Install(IUnknown* object)
{
    void** vtable = *reinterpret_cast<void***>(object);
    for (auto& patch:patches) if (patch.vtable == vtable) return;
    for (auto& patch:patches)
        if (!patch.vtable)
        {
            patch = {vtable,reinterpret_cast<ReleaseFn>(vtable[2])};
            Swap(&vtable[2],reinterpret_cast<void*>(&Release)); return;
        }
    throw std::runtime_error("release probe slots exhausted");
}
void Uninstall()
{
    for (auto& patch:patches)
        if (patch.vtable) { Swap(&patch.vtable[2],reinterpret_cast<void*>(patch.original)); patch = {}; }
}
}
int main() try
{
    ComPtr<ID3D12Debug> debug;
    hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)),"debug interface");debug->EnableDebugLayer();
    ComPtr<IDXGIFactory4> factory;
    hr(CreateDXGIFactory2(0,IID_PPV_ARGS(&factory)),"DXGI factory");
    ComPtr<IDXGIAdapter> warp;
    hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)),"WARP adapter");
    ComPtr<ID3D12Device> device;
    hr(D3D12CreateDevice(warp.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)),"D3D12 device");
    ComPtr<ID3D12InfoQueue> info;hr(device.As(&info),"info queue");
    D3D12_COMMAND_QUEUE_DESC qdesc {};
    ComPtr<ID3D12CommandQueue> queue;
    hr(device->CreateCommandQueue(&qdesc,IID_PPV_ARGS(&queue)),"queue");
    ComPtr<ID3D12CommandAllocator> allocator;
    hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)),"allocator");
    ComPtr<ID3D12GraphicsCommandList> list;
    hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&list)),"command list");
    // Regression for the CP77 freeze at GAME_TRACE start: no interface may be
    // released under the registry mutex. Title Release hooks take the NRD
    // bridge lifetime gate, and a bridge commit holding that gate waits for
    // this mutex in Forget (ABBA). Covers Reset, submission and ticket reaping.
    {
        ComPtr<ID3D12CommandAllocator> probeAllocator;
        hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&probeAllocator)),"probe allocator");
        ComPtr<ID3D12GraphicsCommandList> probeList;
        hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,probeAllocator.Get(),nullptr,IID_PPV_ARGS(&probeList)),"probe list");
        {
            ComPtr<IUnknown> identity; hr(probeList.As(&identity),"probe identity");
            ReleaseProbe::Install(probeList.Get()); ReleaseProbe::Install(identity.Get());
        }
        ReleaseProbe::armed = true;
        auto first = RRTraceFence::Arm(device.Get(),probeList.Get()); first->Recorded();
        hr(probeList->Close(),"close probe");
        ID3D12CommandList* probeSubmitted[] = {probeList.Get()};
        auto probeSignals = RRTraceFence::BeforeSubmission(queue.Get(),1,probeSubmitted);
        queue->ExecuteCommandLists(1,probeSubmitted);
        RRTraceFence::AfterSubmission(queue.Get(),probeSignals); probeSignals.clear();
        HANDLE done = CreateEvent(nullptr,FALSE,FALSE,nullptr); need(done != nullptr,"probe event");
        hr(first->fence->SetEventOnCompletion(first->state.expected,done),"probe fence event");
        const auto waited = WaitForSingleObject(done,10000); CloseHandle(done); need(waited == WAIT_OBJECT_0,"probe GPU timeout");
        hr(probeList->Reset(probeAllocator.Get(),nullptr),"reset probe");
        RRTraceFence::ResetSucceeded(probeList.Get());
        need(first->Releasable(),"probe ticket releasable after fence and Reset");
        first->Abandon(); first.reset(); // The registry now owns the last reference.
        auto second = RRTraceFence::Arm(device.Get(),probeList.Get()); // Reaps `first`.
        second->Recorded(); hr(probeList->Close(),"close second probe");
        hr(probeList->Reset(probeAllocator.Get(),nullptr),"reset second probe");
        RRTraceFence::ResetSucceeded(probeList.Get());
        need(second->Releasable(),"discarded probe releasable"); RRTraceFence::Forget(second); second.reset();
        ReleaseProbe::armed = false;
        const unsigned probeCalls = ReleaseProbe::calls.load(), probeViolations = ReleaseProbe::violations.load();
        hr(probeList->Close(),"close probe for teardown");
        ReleaseProbe::Uninstall();
        std::cout << "release probe: " << probeCalls << " command-list releases, " << probeViolations << " under the registry mutex\n";
        need(probeCalls >= 4,"probe observed Reset, submission and reaping releases");
        need(probeViolations == 0,"no command-list Release while the RRTraceFence registry mutex is held");
    }
    auto buffer=[&](D3D12_HEAP_TYPE type,D3D12_RESOURCE_STATES state,UINT64 size=64) {
        D3D12_HEAP_PROPERTIES heap {};heap.Type=type;
        D3D12_RESOURCE_DESC desc {};desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width=size;desc.Height=1;desc.DepthOrArraySize=1;desc.MipLevels=1;
        desc.SampleDesc.Count=1;desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> out;
        hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,state,nullptr,IID_PPV_ARGS(&out)),"buffer");
        return out;
    };
    auto upload=buffer(D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
    auto readback=buffer(D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
    std::array<unsigned,16> pattern;
    for (unsigned i=0;i<pattern.size();++i)pattern[i]=0xa55a0000u+i;
    void* data=nullptr;const D3D12_RANGE empty {0,0};
    hr(upload->Map(0,&empty,&data),"upload map");memcpy(data,pattern.data(),64);upload->Unmap(0,nullptr);
    auto ticket=RRTraceFence::Arm(device.Get(),list.Get());ticket->Retain(upload.Get());ticket->Retain(readback.Get());
    list->CopyBufferRegion(readback.Get(),0,upload.Get(),0,64);
    // Exercise the production paired-copy helper: nonzero ROI, padded rows,
    // exact typed FP16 bytes, and a second full copy proving state restoration.
    D3D12_RESOURCE_DESC td {};td.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    td.Width=11;td.Height=7;td.DepthOrArraySize=1;td.MipLevels=1;td.SampleDesc.Count=1;
    td.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;
    D3D12_HEAP_PROPERTIES hp {};hp.Type=D3D12_HEAP_TYPE_DEFAULT;
    ComPtr<ID3D12Resource> texture;
    hr(device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&td,D3D12_RESOURCE_STATE_COPY_DEST,
        nullptr,IID_PPV_ARGS(&texture)),"paired source");
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT full {},roi {};UINT64 fullSize=0,roiSize=0;
    device->GetCopyableFootprints(&td,0,1,0,&full,nullptr,nullptr,&fullSize);
    auto rd=td;rd.Width=5;rd.Height=3;
    device->GetCopyableFootprints(&rd,0,1,0,&roi,nullptr,nullptr,&roiSize);
    auto pixels=buffer(D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ,fullSize);
    auto cropped=buffer(D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST,roiSize);
    auto unchanged=buffer(D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST,fullSize);
    std::array<uint16_t,11*7*4> expected;
    for (unsigned i=0;i<expected.size();++i) expected[i]=uint16_t(0x3000+i);
    hr(pixels->Map(0,&empty,&data),"paired upload");
    for (unsigned y=0;y<7;++y)
        memcpy(static_cast<char*>(data)+full.Offset+y*full.Footprint.RowPitch,expected.data()+y*44,88);
    pixels->Unmap(0,&empty);
    D3D12_TEXTURE_COPY_LOCATION source {},destination {};
    source.pResource=pixels.Get();source.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;source.PlacedFootprint=full;
    destination.pResource=texture.Get();destination.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    list->CopyTextureRegion(&destination,0,0,0,&source,nullptr);
    D3D12_RESOURCE_BARRIER barrier {};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition={texture.Get(),D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,D3D12_RESOURCE_STATE_COPY_DEST,
        D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE};
    list->ResourceBarrier(1,&barrier);
    for (auto* resource:{texture.Get(),pixels.Get(),cropped.Get(),unchanged.Get()}) ticket->Retain(resource);
    RRTraceAdditiveIO::CopyPreSrRoi(list.Get(),texture.Get(),cropped.Get(),roi,2,1,5,3);
    RRTraceAdditiveIO::CopyPreSrRoi(list.Get(),texture.Get(),unchanged.Get(),full,0,0,11,7);
    bool rejected=false;
    try { RRTraceAdditiveIO::CopyPreSrRoi(list.Get(),texture.Get(),cropped.Get(),roi,UINT_MAX,0,5,3); }
    catch (const std::exception&) { rejected=true; }
    need(rejected,"overflowing ROI rejected before recording");
    hr(list->Close(),"close");ticket->Recorded();
    need(!ticket->Ready(),"unsubmitted capture cannot be ready");
    ID3D12CommandList* submitted[]={list.Get()};
    auto signals=RRTraceFence::BeforeSubmission(queue.Get(),1,submitted);
    queue->ExecuteCommandLists(1,submitted);
    // Legal immediate command-list Reset between original execution and our
    // post-submit fence must not be classified as an unsubmitted discard.
    hr(list->Reset(allocator.Get(),nullptr),"immediate command-list Reset");
    RRTraceFence::ResetSucceeded(list.Get());
    need(!ticket->Ready() && !ticket->Releasable(),"pending Signal protects readback lifetime");
    RRTraceFence::AfterSubmission(queue.Get(),signals);
    HANDLE event=CreateEvent(nullptr,FALSE,FALSE,nullptr);need(event!=nullptr,"event");
    hr(ticket->fence->SetEventOnCompletion(1,event),"fence event");
    const auto wait=WaitForSingleObject(event,10000);CloseHandle(event);need(wait==WAIT_OBJECT_0,"GPU fence timeout");
    need(ticket->Ready(),"actual queue fence + Reset permits export");
    const D3D12_RANGE range {0,64};hr(readback->Map(0,&range,&data),"readback map after fence");
    const bool equal=memcmp(data,pattern.data(),64)==0;readback->Unmap(0,&empty);need(equal,"GPU copy data");
    const D3D12_RANGE cropRange {0,roi.Offset+SIZE_T(roi.Footprint.RowPitch)*2+5*8};
    need(cropRange.End<=roiSize,"partial-row map range fits allocation");
    hr(cropped->Map(0,&cropRange,&data),"paired ROI map");
    for (unsigned y=0;y<3;++y)
        need(memcmp(static_cast<char*>(data)+roi.Offset+y*roi.Footprint.RowPitch,
            expected.data()+((y+1)*11+2)*4,40)==0,"typed ROI row matches same-frame source");
    cropped->Unmap(0,&empty);
    hr(unchanged->Map(0,nullptr,&data),"paired unchanged map");
    for (unsigned y=0;y<7;++y)
        need(memcmp(static_cast<char*>(data)+full.Offset+y*full.Footprint.RowPitch,
            expected.data()+y*44,88)==0,"paired capture leaves output unchanged");
    unchanged->Unmap(0,&empty);
    RRTraceFence::Forget(ticket);
    // No submission at all: Reset discards recorded data, not a valid capture.
    auto discarded=RRTraceFence::Arm(device.Get(),list.Get());discarded->Recorded();
    hr(list->Close(),"close discard");hr(list->Reset(allocator.Get(),nullptr),"reset discard");
    RRTraceFence::ResetSucceeded(list.Get());
    need(discarded->Invalid() && !discarded->Ready() && discarded->Releasable(),"discard not published");
    RRTraceFence::Forget(discarded);

    // A completed recording can remain closed forever. Freeze its CPU bytes
    // under the submission gate without claiming Reset or releasing storage.
    auto frozenReadback=buffer(D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
    auto frozenTicket=RRTraceFence::Arm(device.Get(),list.Get());
    frozenTicket->Retain(upload.Get());frozenTicket->Retain(frozenReadback.Get());
    list->CopyBufferRegion(frozenReadback.Get(),0,upload.Get(),0,64);
    hr(list->Close(),"close snapshot");frozenTicket->Recorded();
    unsigned callbacks=0;
    need(!RRTraceFence::WithCompletedSnapshot(frozenTicket,[&](const auto&) { ++callbacks; }),
        "unsubmitted snapshot rejected");
    auto frozenSignals=RRTraceFence::BeforeSubmission(queue.Get(),1,submitted);
    queue->ExecuteCommandLists(1,submitted);
    need(!RRTraceFence::WithCompletedSnapshot(frozenTicket,[&](const auto&) { ++callbacks; }),
        "snapshot before successful post-submit signal rejected");
    RRTraceFence::AfterSubmission(queue.Get(),frozenSignals);
    const auto awaitFence=[&](UINT64 value) {
        HANDLE done=CreateEvent(nullptr,FALSE,FALSE,nullptr);need(done!=nullptr,"snapshot event");
        hr(frozenTicket->fence->SetEventOnCompletion(value,done),"snapshot fence event");
        const auto result=WaitForSingleObject(done,10000);CloseHandle(done);
        need(result==WAIT_OBJECT_0,"snapshot GPU timeout");
    };
    awaitFence(1);
    need(!frozenTicket->Ready()&&!frozenTicket->Releasable(),
        "completed executable recording is still retained");
    std::array<unsigned,16> laterPattern=pattern,immutable {};
    for(auto& word:laterPattern) word^=0x00ff00ffu;
    hr(upload->Map(0,&empty,&data),"next submission upload");
    memcpy(data,laterPattern.data(),64);upload->Unmap(0,nullptr);

    // Deliberately force a concurrent submission attempt while the copier
    // owns the gate. Only this test waits inside the callback to establish
    // the race; production callbacks only copy into preallocated storage.
    HANDLE attempt=CreateEvent(nullptr,TRUE,FALSE,nullptr);
    HANDLE attempting=CreateEvent(nullptr,TRUE,FALSE,nullptr);
    need(attempt&&attempting,"submission race events");
    auto repeat=std::async(std::launch::async,[&] {
        need(WaitForSingleObject(attempt,10000)==WAIT_OBJECT_0,"race attempt timeout");
        SetEvent(attempting);
        auto repeatedSignals=RRTraceFence::BeforeSubmission(queue.Get(),1,submitted);
        queue->ExecuteCommandLists(1,submitted);
        RRTraceFence::AfterSubmission(queue.Get(),repeatedSignals);
    });
    struct Unblock { HANDLE event;~Unblock(){if(event)SetEvent(event);} } unblock {attempt};
    RRTraceFence::Snapshot frozenProof {};
    const bool copied=RRTraceFence::WithCompletedSnapshot(frozenTicket,[&](const auto& proof) {
        ++callbacks;frozenProof=proof;
        SetEvent(attempt);
        need(WaitForSingleObject(attempting,10000)==WAIT_OBJECT_0,"concurrent intent started");
        need(repeat.wait_for(std::chrono::milliseconds(25))==std::future_status::timeout,
            "submission must not pass the held snapshot gate");
        void* bytes=nullptr;hr(frozenReadback->Map(0,&range,&bytes),"guarded CPU snapshot map");
        memcpy(immutable.data(),bytes,64);frozenReadback->Unmap(0,&empty);
    });
    SetEvent(attempt);repeat.get();
    // Disarm the exception cleanup before closing its event.
    unblock.event=nullptr;CloseHandle(attempt);CloseHandle(attempting);
    need(copied&&callbacks==1,"only one eligible snapshot callback ran");
    need(immutable==pattern&&!frozenProof.state.detached&&frozenProof.state.expected==1&&
        frozenProof.completed>=1&&!frozenProof.state.invalid,"immutable original submission and truthful proof");
    awaitFence(2);
    hr(frozenReadback->Map(0,&range,&data),"readback after actual repeated execution");
    const bool overwritten=memcmp(data,laterPattern.data(),64)==0;
    frozenReadback->Unmap(0,&empty);
    need(overwritten&&immutable==pattern,"later GPU overwrite cannot change frozen CPU payload");
    need(frozenTicket->Invalid()&&!frozenTicket->Releasable(),"repeated submission quarantines GPU resources");
    need(!RRTraceFence::WithCompletedSnapshot(frozenTicket,[&](const auto&) { ++callbacks; })&&callbacks==1,
        "ambiguous later submission cannot publish another snapshot");
    hr(list->Reset(allocator.Get(),nullptr),"reset after repeated submission");
    RRTraceFence::ResetSucceeded(list.Get());
    need(!frozenTicket->Releasable(),"CPU snapshot never bypasses ambiguous-submission quarantine");
    hr(list->Close(),"final close");

    // Allocation failure in A's intent append must quarantine the still
    // unvisited B before the original multi-list batch executes. In particular,
    // B's old completed fence plus an immediate Reset cannot free its storage.
    std::array<ComPtr<ID3D12CommandAllocator>,2> batchAllocators;
    std::array<ComPtr<ID3D12GraphicsCommandList>,2> batchLists;
    std::array<ComPtr<ID3D12Resource>,2> batchReadbacks;
    std::array<std::shared_ptr<RRTraceFence::Ticket>,2> batchTickets;
    ID3D12CommandList* batch[2] {};
    for(unsigned i=0;i<2;++i)
    {
        hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,
            IID_PPV_ARGS(&batchAllocators[i])),"batch allocator");
        hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,batchAllocators[i].Get(),
            nullptr,IID_PPV_ARGS(&batchLists[i])),"batch list");
        batchReadbacks[i]=buffer(D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
        batchTickets[i]=RRTraceFence::Arm(device.Get(),batchLists[i].Get());
        batchTickets[i]->Retain(upload.Get());batchTickets[i]->Retain(batchReadbacks[i].Get());
        batchLists[i]->CopyBufferRegion(batchReadbacks[i].Get(),0,upload.Get(),0,64);
        hr(batchLists[i]->Close(),"close batch");batchTickets[i]->Recorded();batch[i]=batchLists[i].Get();
    }
    auto batchSignals=RRTraceFence::BeforeSubmission(queue.Get(),2,batch);
    queue->ExecuteCommandLists(2,batch);RRTraceFence::AfterSubmission(queue.Get(),batchSignals);
    ComPtr<ID3D12Fence> progress,hold;
    hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&progress)),"batch progress fence");
    hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&hold)),"batch hold fence");
    const auto awaitProgress=[&](UINT64 value) {
        HANDLE done=CreateEvent(nullptr,FALSE,FALSE,nullptr);need(done!=nullptr,"batch event");
        hr(progress->SetEventOnCompletion(value,done),"batch progress event");
        const auto result=WaitForSingleObject(done,10000);CloseHandle(done);
        need(result==WAIT_OBJECT_0,"batch GPU timeout");
    };
    hr(queue->Signal(progress.Get(),1),"batch completion");awaitProgress(1);
    for(auto& t:batchTickets)
        need(RRTraceFence::WithCompletedSnapshot(t,[](const auto&) {}),"initial batch snapshot is eligible");
    unsigned failedAppends=0;
    RRTraceFence::RecordSubmissionIntents(queue.Get(),2,batch,[&](const auto&) {
        ++failedAppends;throw std::bad_alloc();
    });
    const auto unvisitedProof=RRTraceFence::Inspect(batchTickets[1]);
    need(failedAppends==1&&unvisitedProof.state.expected==1&&unvisitedProof.state.pendingSignals==0&&
        unvisitedProof.state.ambiguousSubmission,"unvisited batch member quarantined on append allocation failure");
    hr(queue->Wait(hold.Get(),1),"hold untracked batch on GPU");
    queue->ExecuteCommandLists(2,batch);
    for(unsigned i=0;i<2;++i)
    {
        hr(batchLists[i]->Reset(batchAllocators[i].Get(),nullptr),"immediate untracked batch Reset");
        RRTraceFence::ResetSucceeded(batchLists[i].Get());
        need(!RRTraceFence::WithCompletedSnapshot(batchTickets[i],[&](const auto&) { ++callbacks; })&&
            !batchTickets[i]->Releasable(),"old completed fence cannot publish or release untracked GPU work");
        hr(batchLists[i]->Close(),"close reset batch");
    }
    hr(queue->Signal(progress.Get(),2),"untracked batch completion");
    hr(hold->Signal(1),"release held GPU batch");awaitProgress(2);
    for(unsigned i=0;i<2;++i)
    {
        hr(batchReadbacks[i]->Map(0,&range,&data),"untracked batch readback after independent fence");
        const bool valid=memcmp(data,laterPattern.data(),64)==0;batchReadbacks[i]->Unmap(0,&empty);
        need(valid&&!batchTickets[i]->Releasable(),"actual untracked execution completes with storage quarantined");
    }
    need(info->GetNumStoredMessages()==0,"D3D12 debug layer must remain clean");
    need(RRTraceAdditiveIO::FloatArray(std::array<float,2>{.5f,-.25f})=="[0.5,-0.25]","finite metadata serialization");
    std::cout<<"PASS native queue-fence/reset, paired FP16 ROI/state, immutable snapshot with concurrent resubmission, and allocation-failed multi-list intent quarantine; no injected hooks or AMD model tested\n";
    return 0;
}
catch (const std::exception& error) { std::cerr<<"FAIL "<<error.what()<<'\n';return 1; }
