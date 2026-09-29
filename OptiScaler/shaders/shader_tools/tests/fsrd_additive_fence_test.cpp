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
#include "../../fsrd_preprocess/RRTraceFence.h"
using Microsoft::WRL::ComPtr;
static void need(bool ok,const char* what) { if (!ok) throw std::runtime_error(what); }
static void hr(HRESULT result,const char* what) { need(SUCCEEDED(result),what); }
int main() try
{
    ComPtr<IDXGIFactory4> factory;
    hr(CreateDXGIFactory2(0,IID_PPV_ARGS(&factory)),"DXGI factory");
    ComPtr<IDXGIAdapter> warp;
    hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)),"WARP adapter");
    ComPtr<ID3D12Device> device;
    hr(D3D12CreateDevice(warp.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)),"D3D12 device");
    D3D12_COMMAND_QUEUE_DESC qdesc {};
    ComPtr<ID3D12CommandQueue> queue;
    hr(device->CreateCommandQueue(&qdesc,IID_PPV_ARGS(&queue)),"queue");
    ComPtr<ID3D12CommandAllocator> allocator;
    hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)),"allocator");
    ComPtr<ID3D12GraphicsCommandList> list;
    hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&list)),"command list");
    auto buffer=[&](D3D12_HEAP_TYPE type,D3D12_RESOURCE_STATES state) {
        D3D12_HEAP_PROPERTIES heap {};heap.Type=type;
        D3D12_RESOURCE_DESC desc {};desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width=64;desc.Height=1;desc.DepthOrArraySize=1;desc.MipLevels=1;
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
    RRTraceFence::Forget(ticket);
    // No submission at all: Reset discards recorded data, not a valid capture.
    auto discarded=RRTraceFence::Arm(device.Get(),list.Get());discarded->Recorded();
    hr(list->Close(),"close discard");hr(list->Reset(allocator.Get(),nullptr),"reset discard");
    RRTraceFence::ResetSucceeded(list.Get());
    need(discarded->Invalid() && !discarded->Ready() && discarded->Releasable(),"discard not published");
    RRTraceFence::Forget(discarded);
    hr(list->Close(),"final close");
    std::cout<<"PASS native queue-fence/reset smoke; no injected hooks or AMD model tested\n";
    return 0;
}
catch (const std::exception& error) { std::cerr<<"FAIL "<<error.what()<<'\n';return 1; }
