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
#include <map>
#include <tuple>
#include <stdexcept>
#include <sstream>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;
constexpr D3D12_RESOURCE_STATES kOutputReadState =
    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
void check(HRESULT hr, const char* what)
{
    if (FAILED(hr)) throw std::runtime_error(std::string(what) + " HRESULT=" + std::to_string(uint32_t(hr)));
}
std::vector<char> bytes(const std::string& path)
{
    // One block read: a character iterator dominated worker jobs with many inputs.
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    if (!f) throw std::runtime_error("Cannot read " + path);
    std::vector<char> data(size_t(f.tellg()));
    f.seekg(0);
    if (!data.empty() && !f.read(data.data(), std::streamsize(data.size())))
        throw std::runtime_error("Cannot read " + path);
    return data;
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
    case DXGI_FORMAT_R32G32_FLOAT: return 8;
    case DXGI_FORMAT_R32_FLOAT:
    case DXGI_FORMAT_R16G16_FLOAT:
    case DXGI_FORMAT_R10G10B10A2_UNORM:
    case DXGI_FORMAT_R8G8B8A8_UNORM: return 4;
    case DXGI_FORMAT_R8_UNORM: return 1;
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
    // Optional two-pass parameters on the same header line. Original one-pass
    // job records remain valid. Both passes bind the SAME output textures.
    std::string secondShaderPath, extra;
    bool initializeSentinel = false;
    std::getline(job, extra);
    std::istringstream options(extra);
    options >> std::quoted(secondShaderPath) >> initializeSentinel;
    const bool graphRequested = !secondShaderPath.empty() || initializeSentinel;
    // Optional worker mode retains the device/queue, compiled pipelines and a pool of
    // textures between jobs. Every job re-uploads all of its inputs, clears all of its
    // outputs to zero (what a newly created committed resource reads as), records its
    // own descriptors and waits for GPU completion, so no content carries over.
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
    // Creating and releasing committed resources dominated a worker job. Pooled textures
    // carry the state the previous job left them in; inputs end in shader-read state and
    // outputs in copy-source state after their readback.
    struct Pooled { ComPtr<ID3D12Resource> resource, transfer; D3D12_RESOURCE_STATES state; UINT64 bytes; };
    using PoolKey = std::tuple<UINT, UINT, int, bool>;
    static std::multimap<PoolKey, Pooled> pool;
    static UINT64 pooledBytes = 0;
    std::vector<Texture> textures(srvCount + uavCount);
    std::vector<Pooled> taken(textures.size());
    D3D12_DESCRIPTOR_HEAP_DESC zeroDesc = hd; zeroDesc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
    ComPtr<ID3D12DescriptorHeap> zeroHeap;
    if (uavCount) check(dev->CreateDescriptorHeap(&zeroDesc, IID_PPV_ARGS(&zeroHeap)), "zero heap");
    ID3D12DescriptorHeap* jobHeaps[] = {heap.Get()};
    cmd->SetDescriptorHeaps(1, jobHeaps);
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
        dev->GetCopyableFootprints(&d, 0, 1, 0, &t.footprint, nullptr, nullptr, &t.size);
        auto& slot = taken[i];
        const auto found = pool.find(PoolKey(t.width, t.height, format, output));
        if (found != pool.end())
        {
            slot = found->second;
            pooledBytes -= slot.bytes;
            pool.erase(found);
        }
        else
        {
            const D3D12_RESOURCE_STATES created = output ? D3D12_RESOURCE_STATE_UNORDERED_ACCESS : D3D12_RESOURCE_STATE_COPY_DEST;
            D3D12_HEAP_PROPERTIES hp {}; hp.Type = D3D12_HEAP_TYPE_DEFAULT;
            check(dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d, created,
                nullptr, IID_PPV_ARGS(&slot.resource)), "texture");
            slot.transfer = buffer(t.size, output ? D3D12_HEAP_TYPE_READBACK : D3D12_HEAP_TYPE_UPLOAD);
            slot.state = created;
            slot.bytes = 2 * t.size;
        }
        t.resource = slot.resource;
        t.transfer = slot.transfer;
        auto handle = heap->GetCPUDescriptorHandleForHeapStart(); handle.ptr += SIZE_T(i) * increment;
        if (output)
        {
            D3D12_UNORDERED_ACCESS_VIEW_DESC u {}; u.Format = t.format; u.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
            dev->CreateUnorderedAccessView(t.resource.Get(), nullptr, &u, handle);
            auto cpu = zeroHeap->GetCPUDescriptorHandleForHeapStart(); cpu.ptr += SIZE_T(i) * increment;
            dev->CreateUnorderedAccessView(t.resource.Get(), nullptr, &u, cpu);
            if (slot.state != D3D12_RESOURCE_STATE_UNORDERED_ACCESS)
                barrier(t.resource.Get(), slot.state, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            auto gpu = heap->GetGPUDescriptorHandleForHeapStart(); gpu.ptr += UINT64(i) * increment;
            if (t.format == DXGI_FORMAT_R32G32B32A32_UINT)
            {
                const UINT zero[] = {0, 0, 0, 0};
                cmd->ClearUnorderedAccessViewUint(gpu, cpu, t.resource.Get(), zero, 0, nullptr);
            }
            else
            {
                const float zero[] = {0, 0, 0, 0};
                cmd->ClearUnorderedAccessViewFloat(gpu, cpu, t.resource.Get(), zero, 0, nullptr);
            }
            D3D12_RESOURCE_BARRIER cleared {}; cleared.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
            cleared.UAV.pResource = t.resource.Get();
            cmd->ResourceBarrier(1, &cleared);
            if (graphRequested)
                barrier(t.resource.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, kOutputReadState);
        }
        else
        {
            const size_t row = size_t(t.width) * pixelBytes(t.format);
            auto data = t.path == "__NULL__" ? std::vector<char>(row*t.height, 0) : bytes(t.path);
            if (data.size() != row*t.height) throw std::runtime_error("input length mismatch: " + t.path);
            char* mapped = nullptr; D3D12_RANGE empty {0,0};
            check(t.transfer->Map(0, &empty, reinterpret_cast<void**>(&mapped)), "upload map");
            for (UINT y=0;y<t.height;++y) memcpy(mapped + t.footprint.Offset + y*t.footprint.Footprint.RowPitch, data.data()+y*row, row);
            t.transfer->Unmap(0,nullptr);
            if (slot.state != D3D12_RESOURCE_STATE_COPY_DEST)
                barrier(t.resource.Get(), slot.state, D3D12_RESOURCE_STATE_COPY_DEST);
            D3D12_TEXTURE_COPY_LOCATION src {}; src.pResource = t.transfer.Get(); src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint = t.footprint;
            D3D12_TEXTURE_COPY_LOCATION dst {}; dst.pResource = t.resource.Get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
            barrier(t.resource.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
            D3D12_SHADER_RESOURCE_VIEW_DESC s {}; s.Format = t.format; s.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
            s.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING; s.Texture2D.MipLevels = 1;
            dev->CreateShaderResourceView(t.path == "__NULL__" ? nullptr : t.resource.Get(),&s,handle);
        }
    }
    auto shader = bytes(shaderPath), constants = bytes(cbPath);
    auto cb = buffer((constants.size()+255)&~size_t(255), D3D12_HEAP_TYPE_UPLOAD);
    void* mapped; D3D12_RANGE empty {0,0}; check(cb->Map(0,&empty,&mapped),"cb map");
    memcpy(mapped,constants.data(),constants.size()); cb->Unmap(0,nullptr);
    // Worker mode compiles each distinct DXIL blob once. The key is the blob itself, not
    // its path, so a shader rebuilt in place between jobs can never reuse a stale pipeline.
    struct Pipeline { ComPtr<ID3D12RootSignature> signature; ComPtr<ID3D12PipelineState> pso; };
    static std::map<std::string, Pipeline> pipelines;
    const auto pipeline = [&](const std::vector<char>& blob, ID3D12RootSignature* sharedSignature) -> Pipeline& {
        std::string key(blob.begin(), blob.end());
        key += std::to_string(reinterpret_cast<uintptr_t>(sharedSignature));
        auto& entry = pipelines[key];
        if (!entry.pso)
        {
            if (sharedSignature) entry.signature = sharedSignature;
            else check(dev->CreateRootSignature(0, blob.data(), blob.size(), IID_PPV_ARGS(&entry.signature)), "root signature");
            D3D12_COMPUTE_PIPELINE_STATE_DESC desc {}; desc.pRootSignature = entry.signature.Get();
            desc.CS = {blob.data(), blob.size()};
            check(dev->CreateComputePipelineState(&desc, IID_PPV_ARGS(&entry.pso)), sharedSignature ? "second PSO" : "PSO");
        }
        return entry;
    };
    const Pipeline& first = pipeline(shader, nullptr);
    ComPtr<ID3D12RootSignature> signature = first.signature;
    ComPtr<ID3D12PipelineState> pso = first.pso;
    // Mirror two independent ComputeState leases: two heaps/CBV uploads with
    // identical descriptors/constants, retained until the common fence completes.
    ComPtr<ID3D12PipelineState> secondPso;
    ComPtr<ID3D12DescriptorHeap> secondHeap;
    ComPtr<ID3D12Resource> secondCb;
    if (!secondShaderPath.empty())
    {
        // Production binds the generic composition root signature to both passes.
        secondPso = pipeline(bytes(secondShaderPath), signature.Get()).pso;
        check(dev->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&secondHeap)), "second heap");
        for (UINT i=0; i<textures.size(); ++i)
        {
            auto target = secondHeap->GetCPUDescriptorHandleForHeapStart();
            target.ptr += SIZE_T(i) * increment;
            auto& texture = textures[i];
            if (i >= srvCount)
            {
                D3D12_UNORDERED_ACCESS_VIEW_DESC view {};
                view.Format = texture.format;
                view.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
                dev->CreateUnorderedAccessView(texture.resource.Get(), nullptr, &view, target);
            }
            else
            {
                D3D12_SHADER_RESOURCE_VIEW_DESC view {};
                view.Format = texture.format;
                view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
                view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
                view.Texture2D.MipLevels = 1;
                dev->CreateShaderResourceView(texture.resource.Get(), &view, target);
            }
        }
        secondCb = buffer((constants.size()+255)&~size_t(255), D3D12_HEAP_TYPE_UPLOAD);
        check(secondCb->Map(0, &empty, &mapped), "second CB map");
        memcpy(mapped, constants.data(), constants.size());
        secondCb->Unmap(0, nullptr);
    }
    ComPtr<ID3D12DescriptorHeap> clearHeap;
    if (initializeSentinel)
    {
        // Clear's CPU descriptor lives in a non-shader-visible heap. Its GPU
        // descriptor remains in the bound heap used by both dispatches.
        auto clearDescription = hd;
        clearDescription.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
        check(dev->CreateDescriptorHeap(&clearDescription, IID_PPV_ARGS(&clearHeap)), "clear heap");
        ID3D12DescriptorHeap* clearHeaps[] = {heap.Get()};
        cmd->SetDescriptorHeaps(1, clearHeaps);
        for (UINT i=srvCount; i<textures.size(); ++i)
        {
            auto& texture = textures[i];
            auto cpu = clearHeap->GetCPUDescriptorHandleForHeapStart();
            auto gpu = heap->GetGPUDescriptorHandleForHeapStart();
            cpu.ptr += SIZE_T(i) * increment;
            gpu.ptr += UINT64(i) * increment;
            D3D12_UNORDERED_ACCESS_VIEW_DESC clearView {};
            clearView.Format = texture.format;
            clearView.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
            dev->CreateUnorderedAccessView(texture.resource.Get(), nullptr, &clearView, cpu);
            barrier(texture.resource.Get(), kOutputReadState, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            if (texture.format == DXGI_FORMAT_R32G32B32A32_UINT)
            {
                const UINT sentinel[] = {0xdeadbeef,0xdeadbeef,0xdeadbeef,0xdeadbeef};
                cmd->ClearUnorderedAccessViewUint(gpu, cpu, texture.resource.Get(), sentinel, 0, nullptr);
            }
            else
            {
                const float sentinel[] = {-8192.f,-8192.f,-8192.f,-8192.f};
                cmd->ClearUnorderedAccessViewFloat(gpu, cpu, texture.resource.Get(), sentinel, 0, nullptr);
            }
            barrier(texture.resource.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, kOutputReadState);
        }
    }
    D3D12_QUERY_HEAP_DESC queryDesc {}; queryDesc.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP; queryDesc.Count = repetitions*2;
    ComPtr<ID3D12QueryHeap> query; check(dev->CreateQueryHeap(&queryDesc,IID_PPV_ARGS(&query)),"query heap");
    auto timings = buffer(UINT64(repetitions)*16,D3D12_HEAP_TYPE_READBACK);
    if (graphRequested)
    {
        const auto dispatch = [&](ID3D12PipelineState* pipeline, ID3D12DescriptorHeap* descriptors,
                                  ID3D12Resource* upload) {
            for (UINT i=srvCount; i<textures.size(); ++i)
                barrier(textures[i].resource.Get(), kOutputReadState, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            cmd->SetPipelineState(pipeline);
            cmd->SetComputeRootSignature(signature.Get());
            ID3D12DescriptorHeap* heaps[] = {descriptors};
            cmd->SetDescriptorHeaps(1, heaps);
            cmd->SetComputeRootConstantBufferView(0, upload->GetGPUVirtualAddress());
            auto gpu = descriptors->GetGPUDescriptorHandleForHeapStart();
            cmd->SetComputeRootDescriptorTable(1, gpu);
            gpu.ptr += UINT64(srvCount) * increment;
            cmd->SetComputeRootDescriptorTable(2, gpu);
            cmd->Dispatch((width+7)/8, (height+7)/8, 1);
            for (UINT i=srvCount; i<textures.size(); ++i)
                barrier(textures[i].resource.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, kOutputReadState);
        };
        for (UINT r=0;r<repetitions;++r)
        {
            // One interval covers BOTH dispatches and all production-style output
            // transitions/root/heap/CBV bindings. Never sum separate stage medians.
            cmd->EndQuery(query.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 2*r);
            dispatch(pso.Get(), heap.Get(), cb.Get());
            if (secondPso) dispatch(secondPso.Get(), secondHeap.Get(), secondCb.Get());
            cmd->EndQuery(query.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 2*r+1);
        }
        std::cout << "graph_dispatches=" << (secondPso ? 2 : 1) << " sentinel_initialized=" << initializeSentinel << '\n';
    }
    else
    {
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
    }
    cmd->ResolveQueryData(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,repetitions*2,timings.Get(),0);
    for (UINT i=srvCount;i<textures.size();++i)
    {
        auto& t=textures[i]; barrier(t.resource.Get(), graphRequested ? kOutputReadState :
            D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE);
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
    // The GPU has finished with every resource; return them for the next job.
    for (UINT i=0;i<textures.size();++i)
    {
        auto& slot = taken[i];
        slot.state = i >= srvCount ? D3D12_RESOURCE_STATE_COPY_SOURCE : D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        pooledBytes += slot.bytes;
        pool.emplace(PoolKey(textures[i].width, textures[i].height, int(textures[i].format), i >= srvCount), std::move(slot));
    }
    // Suites sweep many sizes, including HDR fixtures of hundreds of MB; bound the pool.
    if (pooledBytes > (UINT64(1) << 30)) { pool.clear(); pooledBytes = 0; }
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
