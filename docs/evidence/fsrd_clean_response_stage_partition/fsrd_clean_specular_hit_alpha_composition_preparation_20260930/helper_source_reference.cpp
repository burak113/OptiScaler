// Standalone shader integration runner, intentionally independent of the injected DLL.
// Build with the Windows SDK and MSVC; see run_fsrd_gpu_tests.py.
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;
void check(HRESULT hr, const char* what)
{
    if (FAILED(hr)) throw std::runtime_error(std::string(what) + " HRESULT=" + std::to_string(uint32_t(hr)));
}
std::vector<char> bytes(const std::string& path)
{
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("Cannot read " + path);
    return {std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>()};
}
struct Texture
{
    ComPtr<ID3D12Resource> resource, transfer;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {};
    UINT64 size = 0;
    UINT width = 0, height = 0;
    DXGI_FORMAT format;
    std::string path;
};
int pixelBytes(DXGI_FORMAT fmt)
{
    switch (fmt)
    {
    case DXGI_FORMAT_R32G32B32A32_FLOAT: return 16;
    case DXGI_FORMAT_R32G32B32A32_UINT: return 16;
    case DXGI_FORMAT_R16G16B16A16_FLOAT: return 8;
    case DXGI_FORMAT_R32_FLOAT:
    case DXGI_FORMAT_R10G10B10A2_UNORM:
    case DXGI_FORMAT_R8G8B8A8_UNORM: return 4;
    default: throw std::runtime_error("unsupported format");
    }
}
int executeJob(const char* path) try
{
    std::ifstream job(path);
    std::string shaderPath, cbPath;
    UINT width, height, srvCount, uavCount, repetitions;
    job >> std::quoted(shaderPath) >> std::quoted(cbPath) >> width >> height >> srvCount >> uavCount >> repetitions;
    if (!job || !width || !height || !repetitions) throw std::runtime_error("invalid job");
    // Optional worker mode retains only the device/queue between jobs. Every job
    // still creates and uploads its own resources and waits for GPU completion.
    // No texture contents or descriptors can accidentally carry over to a test.
    static ComPtr<ID3D12Debug> debug;
    static bool debugEnabled = false;
    static ComPtr<IDXGIFactory6> factory;
    static ComPtr<IDXGIAdapter1> adapter;
    static ComPtr<ID3D12Device> dev;
    static ComPtr<ID3D12InfoQueue> info;
    static ComPtr<ID3D12CommandQueue> queue;
    if (!dev)
    {
        debugEnabled = SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)));
        if (debugEnabled) debug->EnableDebugLayer();
        check(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)), "factory");
        check(factory->EnumAdapterByGpuPreference(0, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE, IID_PPV_ARGS(&adapter)), "adapter");
        check(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_12_0, IID_PPV_ARGS(&dev)), "device");
        dev.As(&info);
        D3D12_COMMAND_QUEUE_DESC qdesc {};
        check(dev->CreateCommandQueue(&qdesc, IID_PPV_ARGS(&queue)), "queue");
    }
    DXGI_ADAPTER_DESC1 adapterDesc {};
    adapter->GetDesc1(&adapterDesc);
    char adapterName[512] {};
    WideCharToMultiByte(CP_UTF8, 0, adapterDesc.Description, -1, adapterName,
                        sizeof(adapterName), nullptr, nullptr);
    std::cout << "adapter=" << adapterName << '\n';
    ComPtr<ID3D12CommandAllocator> allocator;
    check(dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)), "allocator");
    ComPtr<ID3D12GraphicsCommandList> cmd;
    check(dev->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr, IID_PPV_ARGS(&cmd)), "list");
    auto buffer = [&](UINT64 size, D3D12_HEAP_TYPE type) {
        D3D12_HEAP_PROPERTIES hp {}; hp.Type = type;
        D3D12_RESOURCE_DESC d {}; d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        d.Width = size; d.Height = 1; d.DepthOrArraySize = 1; d.MipLevels = 1;
        d.SampleDesc.Count = 1; d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> r;
        check(dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d,
            type == D3D12_HEAP_TYPE_UPLOAD ? D3D12_RESOURCE_STATE_GENERIC_READ : D3D12_RESOURCE_STATE_COPY_DEST,
            nullptr, IID_PPV_ARGS(&r)), "buffer");
        return r;
    };
    auto barrier = [&](ID3D12Resource* r, D3D12_RESOURCE_STATES a, D3D12_RESOURCE_STATES b) {
        D3D12_RESOURCE_BARRIER transition {}; transition.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        transition.Transition = {r, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, a, b};
        cmd->ResourceBarrier(1, &transition);
    };
    D3D12_DESCRIPTOR_HEAP_DESC hd {}; hd.NumDescriptors = srvCount + uavCount;
    hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ComPtr<ID3D12DescriptorHeap> heap;
    check(dev->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&heap)), "heap");
    const UINT increment = dev->GetDescriptorHandleIncrementSize(hd.Type);
    std::vector<Texture> textures(srvCount + uavCount);
    for (UINT i = 0; i < textures.size(); ++i)
    {
        auto& t = textures[i]; int format;
        job >> std::quoted(t.path) >> t.width >> t.height >> format;
        if (!job) throw std::runtime_error("invalid resource record");
        t.format = DXGI_FORMAT(format);
        const bool output = i >= srvCount;
        D3D12_RESOURCE_DESC d {}; d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        d.Width = t.width; d.Height = t.height; d.DepthOrArraySize = 1; d.MipLevels = 1;
        d.Format = t.format; d.SampleDesc.Count = 1;
        d.Flags = output ? D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS : D3D12_RESOURCE_FLAG_NONE;
        D3D12_HEAP_PROPERTIES hp {}; hp.Type = D3D12_HEAP_TYPE_DEFAULT;
        check(dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d,
            output ? D3D12_RESOURCE_STATE_UNORDERED_ACCESS : D3D12_RESOURCE_STATE_COPY_DEST,
            nullptr, IID_PPV_ARGS(&t.resource)), "texture");
        dev->GetCopyableFootprints(&d, 0, 1, 0, &t.footprint, nullptr, nullptr, &t.size);
        t.transfer = buffer(t.size, output ? D3D12_HEAP_TYPE_READBACK : D3D12_HEAP_TYPE_UPLOAD);
        auto handle = heap->GetCPUDescriptorHandleForHeapStart(); handle.ptr += SIZE_T(i) * increment;
        if (output)
        {
            D3D12_UNORDERED_ACCESS_VIEW_DESC u {}; u.Format = t.format; u.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
            dev->CreateUnorderedAccessView(t.resource.Get(), nullptr, &u, handle);
        }
        else
        {
            auto data = bytes(t.path);
            const size_t row = size_t(t.width) * pixelBytes(t.format);
            if (data.size() != row*t.height) throw std::runtime_error("input length mismatch: " + t.path);
            char* mapped = nullptr; D3D12_RANGE empty {0,0};
            check(t.transfer->Map(0, &empty, reinterpret_cast<void**>(&mapped)), "upload map");
            for (UINT y=0;y<t.height;++y) memcpy(mapped + t.footprint.Offset + y*t.footprint.Footprint.RowPitch, data.data()+y*row, row);
            t.transfer->Unmap(0,nullptr);
            D3D12_TEXTURE_COPY_LOCATION src {}; src.pResource = t.transfer.Get(); src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint = t.footprint;
            D3D12_TEXTURE_COPY_LOCATION dst {}; dst.pResource = t.resource.Get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
            barrier(t.resource.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
            D3D12_SHADER_RESOURCE_VIEW_DESC s {}; s.Format = t.format; s.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
            s.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING; s.Texture2D.MipLevels = 1;
            dev->CreateShaderResourceView(t.resource.Get(),&s,handle);
        }
    }
    auto shader = bytes(shaderPath), constants = bytes(cbPath);
    auto cb = buffer((constants.size()+255)&~size_t(255), D3D12_HEAP_TYPE_UPLOAD);
    void* mapped; D3D12_RANGE empty {0,0}; check(cb->Map(0,&empty,&mapped),"cb map");
    memcpy(mapped,constants.data(),constants.size()); cb->Unmap(0,nullptr);
    ComPtr<ID3D12RootSignature> signature;
    check(dev->CreateRootSignature(0,shader.data(),shader.size(),IID_PPV_ARGS(&signature)),"root signature");
    D3D12_COMPUTE_PIPELINE_STATE_DESC ps {}; ps.pRootSignature = signature.Get(); ps.CS = {shader.data(),shader.size()};
    ComPtr<ID3D12PipelineState> pso; check(dev->CreateComputePipelineState(&ps,IID_PPV_ARGS(&pso)),"PSO");
    D3D12_QUERY_HEAP_DESC queryDesc {}; queryDesc.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP; queryDesc.Count = repetitions*2;
    ComPtr<ID3D12QueryHeap> query; check(dev->CreateQueryHeap(&queryDesc,IID_PPV_ARGS(&query)),"query heap");
    auto timings = buffer(UINT64(repetitions)*16,D3D12_HEAP_TYPE_READBACK);
    cmd->SetPipelineState(pso.Get()); cmd->SetComputeRootSignature(signature.Get());
    ID3D12DescriptorHeap* heaps[] = {heap.Get()}; cmd->SetDescriptorHeaps(1,heaps);
    cmd->SetComputeRootConstantBufferView(0,cb->GetGPUVirtualAddress());
    auto gpu = heap->GetGPUDescriptorHandleForHeapStart(); cmd->SetComputeRootDescriptorTable(1,gpu);
    gpu.ptr += UINT64(srvCount)*increment; cmd->SetComputeRootDescriptorTable(2,gpu);
    for (UINT r=0;r<repetitions;++r)
    {
        cmd->EndQuery(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2*r);
        cmd->Dispatch((width+7)/8,(height+7)/8,1);
        cmd->EndQuery(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2*r+1);
        D3D12_RESOURCE_BARRIER u {}; u.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
        cmd->ResourceBarrier(1,&u);
    }
    cmd->ResolveQueryData(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,repetitions*2,timings.Get(),0);
    for (UINT i=srvCount;i<textures.size();++i)
    {
        auto& t=textures[i]; barrier(t.resource.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION src {}; src.pResource=t.resource.Get(); src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        D3D12_TEXTURE_COPY_LOCATION dst {}; dst.pResource=t.transfer.Get(); dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint=t.footprint;
        cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
    }
    check(cmd->Close(),"close"); ID3D12CommandList* lists[]={cmd.Get()}; queue->ExecuteCommandLists(1,lists);
    ComPtr<ID3D12Fence> fence; check(dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)),"fence");
    HANDLE event=CreateEventW(nullptr,FALSE,FALSE,nullptr); check(queue->Signal(fence.Get(),1),"signal");
    check(fence->SetEventOnCompletion(1,event),"event");
    if (WaitForSingleObject(event,60000)!=WAIT_OBJECT_0) throw std::runtime_error("GPU timeout");
    CloseHandle(event); check(dev->GetDeviceRemovedReason(),"device removed");
    UINT64 frequency; check(queue->GetTimestampFrequency(&frequency),"frequency");
    UINT64* times; check(timings->Map(0,nullptr,reinterpret_cast<void**>(&times)),"timing map");
    std::vector<double> elapsed;
    for (UINT r=std::min(10u,repetitions-1);r<repetitions;++r) elapsed.push_back(double(times[2*r+1]-times[2*r])*1000.0/frequency);
    timings->Unmap(0,nullptr); std::sort(elapsed.begin(),elapsed.end());
    std::cout << "gpu_ms_median=" << elapsed[elapsed.size()/2] << " gpu_ms_p95=" << elapsed[(elapsed.size()-1)*95/100]
              << " debug_layer=" << debugEnabled << '\n';
    for (UINT i=srvCount;i<textures.size();++i)
    {
        auto& t=textures[i]; char* data; check(t.transfer->Map(0,nullptr,reinterpret_cast<void**>(&data)),"readback map");
        std::ofstream f(t.path,std::ios::binary);
        for (UINT y=0;y<t.height;++y) f.write(data+t.footprint.Offset+y*t.footprint.Footprint.RowPitch,size_t(t.width)*pixelBytes(t.format));
        t.transfer->Unmap(0,nullptr);
    }
    unsigned errors=0, warnings=0;
    if (info) for (UINT64 i=0;i<info->GetNumStoredMessages();++i)
    {
        SIZE_T size=0; info->GetMessage(i,nullptr,&size); std::vector<char> storage(size);
        auto* msg=reinterpret_cast<D3D12_MESSAGE*>(storage.data()); info->GetMessage(i,msg,&size);
        if (msg->Severity <= D3D12_MESSAGE_SEVERITY_ERROR) {std::cerr << msg->pDescription << '\n'; ++errors;}
        else if (msg->Severity == D3D12_MESSAGE_SEVERITY_WARNING) {std::cerr << msg->pDescription << '\n'; ++warnings;}
    }
    std::cout << "validation_errors=" << errors << " validation_warnings=" << warnings << '\n';
    if (info) info->ClearStoredMessages();
    if (errors) throw std::runtime_error("D3D12 validation errors: " + std::to_string(errors));
    return 0;
}
catch (const std::exception& e) {std::cerr << e.what() << '\n'; return 1;}

int main(int argc, char** argv)
{
    if (argc != 2) {std::cerr << "usage: fsrd_gpu_runner job.txt | --server\n"; return 1;}
    if (std::string(argv[1]) != "--server") return executeJob(argv[1]);
    std::string path;
    while (std::getline(std::cin, path))
    {
        if (path.empty()) continue;
        int result = executeJob(path.c_str());
        std::cout << "job_complete=" << result << std::endl;
        if (result) return result;
    }
    return 0;
}
