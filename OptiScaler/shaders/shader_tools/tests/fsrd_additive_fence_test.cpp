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
#include "../../fsrd_preprocess/RRTraceAdditiveIO.h"
using Microsoft::WRL::ComPtr;
static void need(bool ok,const char* what) { if (!ok) throw std::runtime_error(what); }
static void hr(HRESULT result,const char* what) { need(SUCCEEDED(result),what); }
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
    hr(list->Close(),"final close");
    need(info->GetNumStoredMessages()==0,"D3D12 debug layer must remain clean");
    need(RRTraceAdditiveIO::FloatArray(std::array<float,2>{.5f,-.25f})=="[0.5,-0.25]","finite metadata serialization");
    std::cout<<"PASS native queue-fence/reset and paired FP16 ROI/state/nonmutation smoke; no injected hooks or AMD model tested\n";
    return 0;
}
catch (const std::exception& error) { std::cerr<<"FAIL "<<error.what()<<'\n';return 1; }
