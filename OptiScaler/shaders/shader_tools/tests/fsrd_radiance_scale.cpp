// Actual shared production pass. The provider seam copies scaled signals; the
// separate captured-data experiment uses the real AMD provider. No installed hooks.
#define NOMINMAX
#define _WINDOWS
#define FSRD_RADIANCE_SCALE_TEST
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <vector>
#include <memory>
#include <iostream>
#include <stdexcept>
#include <cstring>
#include <algorithm>
#include <numeric>
struct ResTrack_Dx12
{
    inline static std::vector<std::shared_ptr<void>> retained;
    static bool RetainComputeDispatch(ID3D12Device*,ID3D12GraphicsCommandList*,const std::shared_ptr<void>& value)
    { retained.push_back(value); return true; }
};
#include "shaders/fsrd_preprocess/FSRDRadianceScale_Dx12.h"
using Microsoft::WRL::ComPtr;
uint64_t checks=0;
void Need(bool value,const char* message) { ++checks; if(!value) throw std::runtime_error(message); }
void Hr(HRESULT h,const char* message) { Need(SUCCEEDED(h),message); }
struct Texture
{
    ComPtr<ID3D12Resource> resource, upload, readback;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    uint64_t bytes=0;
    std::vector<uint16_t> original;
};
struct Host
{
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> list;
    ComPtr<ID3D12Fence> fence;
    ComPtr<ID3D12InfoQueue> info;
    HANDLE event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
    uint64_t next=0;
    Host()
    {
        ComPtr<ID3D12Debug> debug; Hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)),"debug interface");
        debug->EnableDebugLayer();
        ComPtr<IDXGIFactory6> factory; Hr(CreateDXGIFactory2(0,IID_PPV_ARGS(&factory)),"factory");
        ComPtr<IDXGIAdapter1> adapter;
        Hr(factory->EnumAdapterByGpuPreference(0,DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,IID_PPV_ARGS(&adapter)),"hardware adapter");
        Hr(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)),"device");
        D3D12_COMMAND_QUEUE_DESC q{}; Hr(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)),"queue");
        Hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)),"allocator");
        Hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&list)),"list");
        Hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)),"fence");
        Hr(device.As(&info),"info queue");
    }
    ~Host() { CloseHandle(event); }
    ComPtr<ID3D12Resource> Buffer(uint64_t size,D3D12_HEAP_TYPE heap)
    {
        D3D12_HEAP_PROPERTIES hp{}; hp.Type=heap;
        D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;d.Width=size;
        d.Height=1;d.DepthOrArraySize=1;d.MipLevels=1;d.SampleDesc.Count=1;d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> out;
        Hr(device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,
            heap==D3D12_HEAP_TYPE_UPLOAD?D3D12_RESOURCE_STATE_GENERIC_READ:D3D12_RESOURCE_STATE_COPY_DEST,
            nullptr,IID_PPV_ARGS(&out)),"buffer");return out;
    }
    void Barrier(ID3D12Resource* r,D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after)
    {
        D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition={r,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after};list->ResourceBarrier(1,&b);
    }
    Texture Make(uint32_t w,uint32_t h,bool input,D3D12_RESOURCE_STATES read,uint32_t seed)
    {
        Texture t;
        D3D12_HEAP_PROPERTIES hp{};hp.Type=D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;d.Width=w;d.Height=h;
        d.DepthOrArraySize=1;d.MipLevels=1;d.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;
        d.SampleDesc.Count=1;d.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        Hr(device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,input?D3D12_RESOURCE_STATE_COPY_DEST:
            D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&t.resource)),"texture");
        device->GetCopyableFootprints(&d,0,1,0,&t.footprint,nullptr,nullptr,&t.bytes);
        t.readback=Buffer(t.bytes,D3D12_HEAP_TYPE_READBACK);
        if(input)
        {
            t.upload=Buffer(t.bytes,D3D12_HEAP_TYPE_UPLOAD);t.original.resize(uint64_t(w)*h*4);
            for(uint64_t i=0;i<uint64_t(w)*h;++i)
            {
                t.original[4*i]=uint16_t(0x0400+((i+seed)%20)*128);
                t.original[4*i+1]=uint16_t(0x1800+((i+seed)%8)*64);
                t.original[4*i+2]=uint16_t(0x2400+((i+seed)%8)*64);
                const uint16_t alpha[]={0,0x8000,0xbc00,0x3c00,0x7bff};
                t.original[4*i+3]=alpha[(i+seed)%5];
            }
            uint8_t* mapped=nullptr;D3D12_RANGE empty{0,0};Hr(t.upload->Map(0,&empty,reinterpret_cast<void**>(&mapped)),"upload map");
            for(uint32_t y=0;y<h;++y)memcpy(mapped+t.footprint.Offset+y*t.footprint.Footprint.RowPitch,t.original.data()+uint64_t(y)*w*4,uint64_t(w)*8);
            t.upload->Unmap(0,nullptr);
            D3D12_TEXTURE_COPY_LOCATION src{},dst{};src.pResource=t.upload.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=t.footprint;
            dst.pResource=t.resource.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);Barrier(t.resource.Get(),D3D12_RESOURCE_STATE_COPY_DEST,read);
        }
        return t;
    }
    void Submit()
    {
        Hr(list->Close(),"close");ID3D12CommandList* lists[]={list.Get()};queue->ExecuteCommandLists(1,lists);
        Hr(queue->Signal(fence.Get(),++next),"signal");Hr(fence->SetEventOnCompletion(next,event),"set event");
        Need(WaitForSingleObject(event,30000)==WAIT_OBJECT_0,"GPU timeout");Hr(device->GetDeviceRemovedReason(),"device removed");
    }
    void Reset()
    {
        Hr(allocator->Reset(),"allocator reset");Hr(list->Reset(allocator.Get(),nullptr),"list reset");
        ResTrack_Dx12::retained.clear();
    }
    void Read(Texture& t,D3D12_RESOURCE_STATES state,uint32_t w,uint32_t h)
    {
        Barrier(t.resource.Get(),state,D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION src{},dst{};src.pResource=t.resource.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        dst.pResource=t.readback.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dst.PlacedFootprint=t.footprint;
        list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);Barrier(t.resource.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,state);
    }
    void Check(Texture& t,const std::vector<uint16_t>& expected,uint32_t w,uint32_t h)
    {
        uint8_t* mapped=nullptr;Hr(t.readback->Map(0,nullptr,reinterpret_cast<void**>(&mapped)),"read map");
        for(uint32_t y=0;y<h;++y)
        {
            const auto* row=reinterpret_cast<const uint16_t*>(mapped+t.footprint.Offset+y*t.footprint.Footprint.RowPitch);
            for(uint32_t x=0;x<w*4;++x) Need(row[x]==expected[uint64_t(y)*w*4+x],"half-word roundtrip mismatch");
        }
        t.readback->Unmap(0,nullptr);
    }
};
struct Signals
{
    std::vector<Texture> inputs,outputs;
    std::array<ffxDispatchDescDenoiserDirectDiffuse,4> packets{};
    ffxDispatchDescDenoiser dispatch{};
    D3D12_RESOURCE_STATES read;
    Signals(Host& host,uint32_t w,uint32_t h,uint32_t count,bool pixel):read(pixel?
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE:D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE)
    {
        inputs.reserve(count);outputs.reserve(count);
        const uint64_t types[]={FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE,
            FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR,FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE,
            FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR};
        dispatch.renderSize={w,h};dispatch.header.type=FFX_API_DISPATCH_DESC_TYPE_DENOISER;dispatch.commandList=host.list.Get();
        for(uint32_t i=0;i<count;++i)
        {
            inputs.push_back(host.Make(w,h,true,read,i));outputs.push_back(host.Make(w,h,false,read,i));
            packets[i].header.type=types[count==2&&i==1?3:i];
            packets[i].header.pNext=i+1<count?&packets[i+1].header:nullptr;
            packets[i].signal.input.resource=inputs[i].resource.Get();
            packets[i].signal.input.state=pixel?FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ:FFX_API_RESOURCE_STATE_COMPUTE_READ;
            packets[i].signal.output.resource=outputs[i].resource.Get();packets[i].signal.output.state=FFX_API_RESOURCE_STATE_UNORDERED_ACCESS;
        }
        dispatch.header.pNext=&packets[0].header;
    }
    void ProviderCopy(Host& host)
    {
        for(size_t i=0;i<inputs.size();++i)
        {
            host.Barrier(inputs[i].resource.Get(),read,D3D12_RESOURCE_STATE_COPY_SOURCE);
            host.Barrier(outputs[i].resource.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_DEST);
            host.list->CopyResource(outputs[i].resource.Get(),inputs[i].resource.Get());
            host.Barrier(inputs[i].resource.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,read);
            host.Barrier(outputs[i].resource.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        }
    }
};
void Timing(Host& host,FSRDRadianceScaleDx12& pass,uint32_t width,uint32_t height,uint32_t count)
{
    Signals signals(host,width,height,count,true);
    D3D12_QUERY_HEAP_DESC q{};q.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;q.Count=4;
    ComPtr<ID3D12QueryHeap> queries;Hr(host.device->CreateQueryHeap(&q,IID_PPV_ARGS(&queries)),"timestamp heap");
    auto readback=host.Buffer(32,D3D12_HEAP_TYPE_READBACK);
    uint64_t frequency=0;Hr(host.queue->GetTimestampFrequency(&frequency),"timestamp frequency");
    host.Submit();host.Reset();
    std::vector<double> up,down;
    for(unsigned iteration=0;iteration<12;++iteration)
    {
        std::string error;FSRDRadianceScaleDx12::Lease work;
        host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
        Need(pass.Before(host.device.Get(),host.list.Get(),signals.dispatch,{true,16,256},work,error),error.c_str());
        host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
        signals.ProviderCopy(host); // Provider-copy cost is outside both timestamp intervals.
        host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2);
        FSRDRadianceScaleDx12::Restore(work);
        host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,3);
        host.list->ResolveQueryData(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,4,readback.Get(),0);
        host.Submit();
        uint64_t* times=nullptr;Hr(readback->Map(0,nullptr,reinterpret_cast<void**>(&times)),"timestamp map");
        if(iteration>=4)
        {up.push_back(double(times[1]-times[0])*1000/double(frequency));down.push_back(double(times[3]-times[2])*1000/double(frequency));}
        readback->Unmap(0,nullptr);host.Reset();
    }
    const auto summary=[](std::vector<double> values)
    {std::sort(values.begin(),values.end());return std::array<double,2>{.5*(values[3]+values[4]),values.back()};};
    const auto a=summary(up),b=summary(down);
    std::cout<<"TIMING "<<width<<'x'<<height<<" signals="<<count<<" samples=8 warmup=4 up_median_ms="<<a[0]
        <<" restore_median_ms="<<b[0]<<" up_p95_ms="<<a[1]<<" restore_p95_ms="<<b[1]<<'\n';
}
int main() try
{
    SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);
    Host host;FSRDRadianceScaleDx12 pass;std::string error;
    for(uint32_t count:{1u,2u,4u}) for(bool pixel:{false,true}) for(uint32_t factor:{1u,16u,256u,4096u})
    {
        Signals signals(host,129,65,count,pixel);
        FSRDRadianceScaleDx12::Lease held;
        {
            FSRDRadianceScaleDx12::Scope scope;
            Need(pass.Before(host.device.Get(),host.list.Get(),signals.dispatch,{true,factor,256},scope.work,error),error.c_str());
            held=scope.work;signals.ProviderCopy(host);
        }
        FSRDRadianceScaleDx12::Restore(held); // Idempotent, including failure cleanup.
        for(size_t i=0;i<count;++i)
        {host.Read(signals.inputs[i],signals.read,129,65);host.Read(signals.outputs[i],D3D12_RESOURCE_STATE_UNORDERED_ACCESS,129,65);}
        host.Submit();
        for(size_t i=0;i<count;++i)
        {host.Check(signals.inputs[i],signals.inputs[i].original,129,65);host.Check(signals.outputs[i],signals.inputs[i].original,129,65);}
        host.Reset();
    }
    {
        Signals signals(host,9,7,2,true);FSRDRadianceScaleDx12::Lease work;
        Need(pass.Before(host.device.Get(),host.list.Get(),signals.dispatch,{},work,error)&&!work,"OFF has no scale job");
        Need(!pass.Before(host.device.Get(),host.list.Get(),signals.dispatch,{true,3,256},work,error),"non-power scale rejects");
        const auto output=signals.packets[0].signal.output;
        signals.packets[0].signal.output.resource=signals.inputs[0].resource.Get();
        Need(!pass.Before(host.device.Get(),host.list.Get(),signals.dispatch,{true,16,256},work,error),"aliased inputs reject");
        signals.packets[0].signal.output=output;
        const auto state=signals.packets[0].signal.input.state;signals.packets[0].signal.input.state=FFX_API_RESOURCE_STATE_COPY_DEST;
        Need(!pass.Before(host.device.Get(),host.list.Get(),signals.dispatch,{true,16,256},work,error),"bad read state rejects");
        signals.packets[0].signal.input.state=state;
        for(unsigned i=0;i<32;++i)
        {
            Need(pass.Before(host.device.Get(),host.list.Get(),signals.dispatch,{true,16,256},work,error),"32 retained slots admit");
            signals.ProviderCopy(host);FSRDRadianceScaleDx12::Restore(work);work.reset();
        }
        Need(!pass.Before(host.device.Get(),host.list.Get(),signals.dispatch,{true,16,256},work,error),"33rd unretired recording rejects");
        host.Submit();host.Reset();
        Need(pass.Before(host.device.Get(),host.list.Get(),signals.dispatch,{true,16,256},work,error),"retired slot can be reused");
        signals.ProviderCopy(host);FSRDRadianceScaleDx12::Restore(work);host.Submit();host.Reset();
    }
    for(const auto extent:{std::array<uint32_t,2>{1505,847},std::array<uint32_t,2>{2560,1440}})
        for(uint32_t count:{2u,4u}) Timing(host,pass,extent[0],extent[1],count);
    unsigned errors=0,warnings=0;
    for(uint64_t i=0;i<host.info->GetNumStoredMessagesAllowedByRetrievalFilter();++i)
    {
        SIZE_T n=0;host.info->GetMessage(i,nullptr,&n);std::vector<uint8_t> bytes(n);
        auto* m=reinterpret_cast<D3D12_MESSAGE*>(bytes.data());host.info->GetMessage(i,m,&n);
        if(m->Severity<=D3D12_MESSAGE_SEVERITY_ERROR){++errors;std::cerr<<m->pDescription<<'\n';}
        else if(m->Severity==D3D12_MESSAGE_SEVERITY_WARNING){++warnings;std::cerr<<m->pDescription<<'\n';}
    }
    Need(!errors&&!warnings,"D3D12 debug layer must stay clean");
    std::cout<<"PASS checks="<<checks<<" debug_errors="<<errors<<" debug_warnings="<<warnings<<'\n';
    return 0;
}
catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
