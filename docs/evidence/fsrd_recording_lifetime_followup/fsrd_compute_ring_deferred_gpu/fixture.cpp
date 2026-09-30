// No OptiScaler runtime, SDK or game executes here. CPU slot overwrites occur
// before queue execution; every shader observation is independently copied.
#define NOMINMAX
#define _WINDOWS
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <DirectXMath.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <vector>
#include <array>
#include <span>
#include <string>
#include <stdexcept>
#include <cstring>
#include "production_extract.h"

struct Constants { UINT value,tag,pad0,pad1; };
static_assert(sizeof(Constants)==16);
struct Readback { ComPtr<ID3D12Resource> resource; D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{}; };

std::vector<byte> readBytes(const std::filesystem::path& p)
{
    std::ifstream in(p,std::ios::binary);if(!in)throw std::runtime_error("file open");
    in.seekg(0,std::ios::end);auto n=in.tellg();in.seekg(0);
    std::vector<byte> data(static_cast<size_t>(n));in.read(reinterpret_cast<char*>(data.data()),n);
    if(!in)throw std::runtime_error("file read");return data;
}
void writeBytes(const std::filesystem::path& p,const void* data,size_t n)
{
    std::ofstream out(p,std::ios::binary);out.write(reinterpret_cast<const char*>(data),n);
    if(!out)throw std::runtime_error("file write");
}
void transition(ID3D12GraphicsCommandList* cmd,ID3D12Resource* r,D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after)
{
    D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition={r,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after};cmd->ResourceBarrier(1,&b);
}
int main(int argc,char** argv) try
{
    std::cout<<std::unitbuf;
    if(argc!=3)throw std::runtime_error("usage fixture job.txt shader.cso");
    std::ifstream job(argv[1]);UINT dispatchCount,cbSlots,descriptorSlots,fenced,split;
    job>>dispatchCount>>cbSlots>>descriptorSlots>>fenced>>split;
    if(!job||dispatchCount<1||dispatchCount>5||!cbSlots||!descriptorSlots||cbSlots>5||descriptorSlots>5||fenced>1||split>1)
        throw std::runtime_error("invalid fixture job");
    if(!split&&cbSlots!=descriptorSlots)throw std::runtime_error("exact class slots must match");
    auto folder=std::filesystem::path(argv[1]).parent_path();
    std::vector<Constants> constants(dispatchCount);std::vector<UINT> inputValues(dispatchCount);
    for(UINT i=0;i<dispatchCount;++i){constants[i]={100+i,200+i,0,0};inputValues[i]=5000+i;}
    writeBytes(folder/"constants.bin",constants.data(),constants.size()*sizeof(Constants));
    writeBytes(folder/"inputs.bin",inputValues.data(),inputValues.size()*sizeof(UINT));
    auto shader=readBytes(argv[2]);
    ComPtr<ID3D12Debug> debug;ThrowIfFailed(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)),"normal debug layer required");debug->EnableDebugLayer();
    ComPtr<IDXGIFactory6> factory;ThrowIfFailed(CreateDXGIFactory2(0,IID_PPV_ARGS(&factory)),"factory");
    ComPtr<IDXGIAdapter1> adapter;ThrowIfFailed(factory->EnumAdapterByGpuPreference(0,DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,IID_PPV_ARGS(&adapter)),"adapter");
    DXGI_ADAPTER_DESC1 ad{};adapter->GetDesc1(&ad);char name[512]{};WideCharToMultiByte(CP_UTF8,0,ad.Description,-1,name,sizeof(name),nullptr,nullptr);
    LARGE_INTEGER driver{};adapter->CheckInterfaceSupport(__uuidof(IDXGIDevice),&driver);
    std::cout<<"adapter="<<name<<" driver="<<driver.QuadPart<<" debug_layer=1 gpu_validation=0\n";
    ComPtr<ID3D12Device> dev;ThrowIfFailed(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&dev)),"device");
    ComPtr<ID3D12InfoQueue> info;ThrowIfFailed(dev.As(&info),"infoqueue");
    ComPtr<ID3D12CommandQueue> queue;D3D12_COMMAND_QUEUE_DESC qd{};ThrowIfFailed(dev->CreateCommandQueue(&qd,IID_PPV_ARGS(&queue)),"queue");
    ComPtr<ID3D12CommandAllocator> alloc;ThrowIfFailed(dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&alloc)),"allocator");
    ComPtr<ID3D12GraphicsCommandList> cmd;ThrowIfFailed(dev->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,alloc.Get(),nullptr,IID_PPV_ARGS(&cmd)),"commandlist");
    ComPtr<ID3D12Fence> fence;ThrowIfFailed(dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)),"fence");
    HANDLE event=CreateEventW(nullptr,FALSE,FALSE,nullptr);if(!event)throw std::runtime_error("event");
    UINT64 fenceValue=0;UINT queueExecutes=0,fenceWaits=0;
    auto executeWait=[&]() {
        ThrowIfFailed(cmd->Close(),"close");ID3D12CommandList* lists[]={cmd.Get()};queue->ExecuteCommandLists(1,lists);++queueExecutes;
        ThrowIfFailed(queue->Signal(fence.Get(),++fenceValue),"signal");ThrowIfFailed(fence->SetEventOnCompletion(fenceValue,event),"fence event");
        if(WaitForSingleObject(event,60000)!=WAIT_OBJECT_0)throw std::runtime_error("GPU fence timeout");++fenceWaits;
        ThrowIfFailed(dev->GetDeviceRemovedReason(),"device removed");
    };
    auto reset=[&]() {ThrowIfFailed(alloc->Reset(),"reset allocator");ThrowIfFailed(cmd->Reset(alloc.Get(),nullptr),"reset list");};
    auto buffer=[&](UINT64 size,D3D12_HEAP_TYPE type) {
        D3D12_HEAP_PROPERTIES hp{};hp.Type=type;D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
        d.Width=size;d.Height=1;d.DepthOrArraySize=1;d.MipLevels=1;d.SampleDesc.Count=1;d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> r;ThrowIfFailed(dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,type==D3D12_HEAP_TYPE_UPLOAD?D3D12_RESOURCE_STATE_GENERIC_READ:D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&r)),"buffer");return r;
    };
    std::vector<ComPtr<ID3D12Resource>> inputs(dispatchCount),uploads(dispatchCount);std::vector<Readback> readbacks(dispatchCount);
    for(UINT i=0;i<dispatchCount;++i) {
        D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;d.Width=1;d.Height=1;d.DepthOrArraySize=1;d.MipLevels=1;d.Format=DXGI_FORMAT_R32_UINT;d.SampleDesc.Count=1;
        D3D12_HEAP_PROPERTIES hp{};hp.Type=D3D12_HEAP_TYPE_DEFAULT;
        ThrowIfFailed(dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&inputs[i])),"input texture");
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT64 size;dev->GetCopyableFootprints(&d,0,1,0,&fp,nullptr,nullptr,&size);uploads[i]=buffer(size,D3D12_HEAP_TYPE_UPLOAD);
        void* mapped;D3D12_RANGE empty{0,0};ThrowIfFailed(uploads[i]->Map(0,&empty,&mapped),"input map");memcpy(static_cast<byte*>(mapped)+fp.Offset,&inputValues[i],4);uploads[i]->Unmap(0,nullptr);
        D3D12_TEXTURE_COPY_LOCATION src{};src.pResource=uploads[i].Get();src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=fp;
        D3D12_TEXTURE_COPY_LOCATION dst{};dst.pResource=inputs[i].Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
        transition(cmd.Get(),inputs[i].Get(),D3D12_RESOURCE_STATE_COPY_DEST,kSrvState);
    }
    executeWait();reset(); // All distinct inputs immutable and ready before test recording.
    auto output=CreateTexture2D(dev.Get(),1,1,DXGI_FORMAT_R32G32B32A32_UINT,L"stable fixture output UAV",kUavState);
    auto outDesc=output->GetDesc();
    for(auto& r:readbacks) {UINT64 size;dev->GetCopyableFootprints(&outDesc,0,1,0,&r.footprint,nullptr,nullptr,&size);r.resource=buffer(size,D3D12_HEAP_TYPE_READBACK);}
    ComputeState exact;SplitComputeState factors;UINT allocationSlots=(std::max)(cbSlots,descriptorSlots);
    if(split) {factors.diagnosticCbSlots=cbSlots;factors.diagnosticDescriptorSlots=descriptorSlots;factors.Initialize(dev.Get(),shader,16,1,1,L"factor CB ring",allocationSlots);}
    else exact.Initialize(dev.Get(),shader,16,1,1,L"exact extracted CB ring",cbSlots);
    std::ofstream trace(folder/"recording_trace.txt");
    for(UINT i=0;i<dispatchCount;++i) {
        if(fenced&&i>0&&i%cbSlots==0) {executeWait();reset();trace<<"completed_before_slot_reuse "<<i<<" fence="<<fenceValue<<'\n';}
        auto in=std::to_array<ID3D12Resource*>({inputs[i].Get()});auto out=std::to_array<ID3D12Resource*>({output.Get()});
        trace<<"dispatch="<<i<<" cbSlot="<<i%cbSlots<<" descriptorSlot="<<i%descriptorSlots<<" cbValue="<<constants[i].value<<" cbTag="<<constants[i].tag<<" input="<<inputValues[i]<<" readback="<<i<<'\n';
        if(split)factors.Dispatch(cmd.Get(),GetAsByteSpan(constants[i]),in,out,{1,1},false);
        else exact.Dispatch(cmd.Get(),GetAsByteSpan(constants[i]),in,out,{1,1},false);
        // Stable output resource/view in every descriptor heap. Transition orders
        // shader write before a unique readback copy; it never edits CB/SRV memory.
        transition(cmd.Get(),output.Get(),kUavState,D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION src{};src.pResource=output.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        D3D12_TEXTURE_COPY_LOCATION dst{};dst.pResource=readbacks[i].resource.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dst.PlacedFootprint=readbacks[i].footprint;
        cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);transition(cmd.Get(),output.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,kUavState);
    }
    executeWait();trace<<"completed_final fence="<<fenceValue<<'\n';trace.close();
    std::vector<std::array<UINT,4>> actual(dispatchCount);
    for(UINT i=0;i<dispatchCount;++i) {
        void* mapped;ThrowIfFailed(readbacks[i].resource->Map(0,nullptr,&mapped),"readback map");memcpy(actual[i].data(),static_cast<byte*>(mapped)+readbacks[i].footprint.Offset,16);
        readbacks[i].resource->Unmap(0,nullptr);writeBytes(folder/("out"+std::to_string(i)+".bin"),actual[i].data(),16);
        std::cout<<"observation="<<i<<" cb="<<actual[i][0]<<" srv="<<actual[i][1]<<" cbTag="<<actual[i][2]<<" magic="<<actual[i][3]<<'\n';
    }
    writeBytes(folder/"outputs.bin",actual.data(),actual.size()*16);
    unsigned errors=0,warnings=0;std::ofstream messages(folder/"debug_messages.txt");
    for(UINT64 i=0;i<info->GetNumStoredMessages();++i) {
        SIZE_T n=0;info->GetMessage(i,nullptr,&n);std::vector<byte> bytes(n);auto* m=reinterpret_cast<D3D12_MESSAGE*>(bytes.data());info->GetMessage(i,m,&n);
        messages<<"severity="<<m->Severity<<" id="<<m->ID<<" description="<<m->pDescription<<'\n';
        if(m->Severity<=D3D12_MESSAGE_SEVERITY_ERROR)++errors;else if(m->Severity==D3D12_MESSAGE_SEVERITY_WARNING)++warnings;
    }
    messages.close();CloseHandle(event);
    std::cout<<"shader_dispatches="<<dispatchCount<<" queue_executes="<<queueExecutes<<" signals="<<fenceValue<<" fence_waits="<<fenceWaits<<" validation_errors="<<errors<<" validation_warnings="<<warnings<<" native_SDK_dispatches=0\n";
    // With forced root signature1.0, changes before submit have volatile
    // semantics. Retain every debug message and observation for the alias cases.
    return 0;
} catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
