// Versioned multi-pass test protocol. The production shaders and embedded root
// signatures are used unchanged; this file supplies only D3D12 orchestration.
#include <cmath>
#include <set>

int executeChain(std::istream& job)
{
    UINT repetitions, warmup, resourceCount, passCount;
    job >> repetitions >> warmup >> resourceCount >> passCount;
    if (!job || !repetitions || warmup >= repetitions || !resourceCount || !passCount)
        throw std::runtime_error("invalid chain header");
    struct Resource
    {
        std::string name, input, output;
        UINT kind, width, height, layers, format, writable;
        ComPtr<ID3D12Resource> gpu, upload, readback;
        std::vector<D3D12_PLACED_SUBRESOURCE_FOOTPRINT> footprints;
        UINT64 transferSize = 0;
        D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COPY_DEST;
    };
    struct Pass
    {
        std::string name, shader, constants;
        UINT mode, x, y, z, offset;
        int argument;
        std::vector<int> srvs, uavs;
        ComPtr<ID3D12RootSignature> root;
        ComPtr<ID3D12PipelineState> pipeline;
        ComPtr<ID3D12Resource> cb;
        ComPtr<ID3D12DescriptorHeap> heap;
    };
    std::vector<Resource> resources(resourceCount);
    for (auto& r : resources)
    {
        job >> std::quoted(r.name) >> r.kind >> r.width >> r.height >> r.layers >> r.format >> r.writable
            >> std::quoted(r.input) >> std::quoted(r.output);
        if (!job || !r.width || !r.height || !r.layers || (r.kind != 0 && r.kind != 2 && r.kind != 3))
            throw std::runtime_error("invalid chain resource");
    }
    std::vector<Pass> passes(passCount);
    std::set<int> indirectResources;
    for (auto& p : passes)
    {
        UINT srvs, uavs;
        job >> std::quoted(p.name) >> std::quoted(p.shader) >> std::quoted(p.constants)
            >> p.mode >> p.x >> p.y >> p.z >> p.argument >> p.offset >> srvs >> uavs;
        p.srvs.resize(srvs); p.uavs.resize(uavs);
        for (auto& index : p.srvs) job >> index;
        for (auto& index : p.uavs) job >> index;
        if (!job || p.mode > 2 || (p.mode == 1 && (p.argument < 0 || UINT(p.argument) >= resourceCount)))
            throw std::runtime_error("invalid chain pass");
        if (p.mode == 1) indirectResources.insert(p.argument);
        std::set<int> reads;
        for (int index : p.srvs)
        {
            if (index < -3 || index >= int(resourceCount)) throw std::runtime_error("invalid chain SRV");
            if (index >= 0) reads.insert(index);
        }
        for (int index : p.uavs)
        {
            if (index < -3 || index >= int(resourceCount)) throw std::runtime_error("invalid chain UAV");
            if (index >= 0 && (!resources[index].writable || reads.count(index)))
                throw std::runtime_error("chain resource simultaneously SRV/UAV or not writable");
        }
    }
    static ComPtr<ID3D12Device> device;
    static ComPtr<IDXGIAdapter1> adapter;
    static ComPtr<ID3D12CommandQueue> queue;
    static ComPtr<ID3D12InfoQueue> info;
    static bool debugEnabled = false;
    if (!device)
    {
        ComPtr<ID3D12Debug> debug;
        debugEnabled = SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)));
        if (debugEnabled) debug->EnableDebugLayer();
        ComPtr<IDXGIFactory6> factory;
        check(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)), "chain factory");
        check(factory->EnumAdapterByGpuPreference(0, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,
                                                  IID_PPV_ARGS(&adapter)), "chain adapter");
        check(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_12_0, IID_PPV_ARGS(&device)), "chain device");
        device.As(&info);
        D3D12_COMMAND_QUEUE_DESC desc {};
        check(device->CreateCommandQueue(&desc, IID_PPV_ARGS(&queue)), "chain queue");
    }
    if (info) info->ClearStoredMessages();
    DXGI_ADAPTER_DESC1 adapterDesc {};
    adapter->GetDesc1(&adapterDesc);
    char adapterName[512] {};
    WideCharToMultiByte(CP_UTF8, 0, adapterDesc.Description, -1, adapterName, sizeof(adapterName), nullptr, nullptr);
    std::cout << "adapter=" << adapterName << '\n';
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> cmd;
    check(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)), "chain allocator");
    check(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr,
                                    IID_PPV_ARGS(&cmd)), "chain command list");
    const auto staging = [&](UINT64 size, D3D12_HEAP_TYPE type) {
        D3D12_HEAP_PROPERTIES hp {}; hp.Type = type;
        D3D12_RESOURCE_DESC desc {}; desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = std::max<UINT64>(size, 256); desc.Height = 1; desc.DepthOrArraySize = 1;
        desc.MipLevels = 1; desc.SampleDesc.Count = 1; desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> result;
        check(device->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &desc,
              type == D3D12_HEAP_TYPE_UPLOAD ? D3D12_RESOURCE_STATE_GENERIC_READ : D3D12_RESOURCE_STATE_COPY_DEST,
              nullptr, IID_PPV_ARGS(&result)), "chain staging buffer");
        return result;
    };
    const auto transition = [&](Resource& r, D3D12_RESOURCE_STATES target) {
        if (r.state == target) return;
        D3D12_RESOURCE_BARRIER b {}; b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition = {r.gpu.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, r.state, target};
        cmd->ResourceBarrier(1, &b); r.state = target;
    };
    const auto uploadResource = [&](Resource& r, UINT maxBytes) {
        transition(r, D3D12_RESOURCE_STATE_COPY_DEST);
        if (r.kind == 0)
            cmd->CopyBufferRegion(r.gpu.Get(), 0, r.upload.Get(), 0, maxBytes ? std::min(maxBytes, r.width) : r.width);
        else for (UINT slice = 0; slice < r.layers; ++slice)
        {
            D3D12_TEXTURE_COPY_LOCATION src {}; src.pResource = r.upload.Get();
            src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint = r.footprints[slice];
            D3D12_TEXTURE_COPY_LOCATION dst {}; dst.pResource = r.gpu.Get();
            dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX; dst.SubresourceIndex = slice;
            cmd->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
        }
    };
    UINT64 allocatedBytes = 0;
    for (auto& r : resources)
    {
        D3D12_RESOURCE_DESC desc {};
        desc.Dimension = r.kind == 0 ? D3D12_RESOURCE_DIMENSION_BUFFER : D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        desc.Width = r.width; desc.Height = r.height; desc.DepthOrArraySize = UINT16(r.layers);
        desc.MipLevels = 1; desc.SampleDesc.Count = 1;
        desc.Format = r.kind == 0 ? DXGI_FORMAT_UNKNOWN : DXGI_FORMAT(r.format);
        desc.Layout = r.kind == 0 ? D3D12_TEXTURE_LAYOUT_ROW_MAJOR : D3D12_TEXTURE_LAYOUT_UNKNOWN;
        desc.Flags = r.writable ? D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS : D3D12_RESOURCE_FLAG_NONE;
        D3D12_HEAP_PROPERTIES hp {}; hp.Type = D3D12_HEAP_TYPE_DEFAULT;
        if (r.kind == 0) r.state = D3D12_RESOURCE_STATE_COMMON;
        check(device->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &desc, r.state,
                                              nullptr, IID_PPV_ARGS(&r.gpu)), "chain resource");
        UINT64 packedSize = r.width;
        if (r.kind == 0) r.transferSize = r.width;
        else
        {
            packedSize = UINT64(r.width) * r.height * r.layers * pixelBytes(DXGI_FORMAT(r.format));
            r.footprints.resize(r.layers);
            device->GetCopyableFootprints(&desc, 0, r.layers, 0, r.footprints.data(), nullptr, nullptr, &r.transferSize);
        }
        allocatedBytes += device->GetResourceAllocationInfo(0, 1, &desc).SizeInBytes;
        r.upload = staging(r.transferSize, D3D12_HEAP_TYPE_UPLOAD);
        if (r.output != "-") r.readback = staging(r.transferSize, D3D12_HEAP_TYPE_READBACK);
        auto data = r.input == "-" ? std::vector<char>(size_t(packedSize), 0) : bytes(r.input);
        if (data.size() != packedSize) throw std::runtime_error("chain input size mismatch: " + r.name);
        char* mapped; D3D12_RANGE empty {0, 0};
        check(r.upload->Map(0, &empty, reinterpret_cast<void**>(&mapped)), "chain upload map");
        if (r.kind == 0) memcpy(mapped, data.data(), data.size());
        else
        {
            const size_t row = size_t(r.width) * pixelBytes(DXGI_FORMAT(r.format));
            for (UINT slice = 0; slice < r.layers; ++slice)
                for (UINT y = 0; y < r.height; ++y)
                    memcpy(mapped + r.footprints[slice].Offset + UINT64(y) * r.footprints[slice].Footprint.RowPitch,
                           data.data() + (size_t(slice) * r.height + y) * row, row);
        }
        r.upload->Unmap(0, nullptr);
        uploadResource(r, 0);
    }
    const UINT increment = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    struct Pipeline { ComPtr<ID3D12RootSignature> root; ComPtr<ID3D12PipelineState> pso; };
    static std::map<std::vector<char>, Pipeline> pipelineCache;
    for (auto& p : passes)
    {
        if (p.mode == 2) continue; // Explicit production-style reset upload.
        auto code = bytes(p.shader);
        auto found = pipelineCache.find(code);
        if (found == pipelineCache.end())
        {
            Pipeline value;
            check(device->CreateRootSignature(0, code.data(), code.size(), IID_PPV_ARGS(&value.root)), "chain root signature");
            D3D12_COMPUTE_PIPELINE_STATE_DESC desc {};
            desc.pRootSignature = value.root.Get(); desc.CS = {code.data(), code.size()};
            check(device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&value.pso)), "chain pipeline");
            found = pipelineCache.emplace(std::move(code), std::move(value)).first;
        }
        p.root = found->second.root; p.pipeline = found->second.pso;
        const auto constants = bytes(p.constants);
        p.cb = staging((constants.size() + 255) & ~size_t(255), D3D12_HEAP_TYPE_UPLOAD);
        void* mapped; D3D12_RANGE empty {0, 0};
        check(p.cb->Map(0, &empty, &mapped), "chain CB map");
        memcpy(mapped, constants.data(), constants.size()); p.cb->Unmap(0, nullptr);
        D3D12_DESCRIPTOR_HEAP_DESC hd {}; hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        hd.NumDescriptors = UINT(p.srvs.size() + p.uavs.size()); hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        check(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&p.heap)), "chain descriptors");
        for (UINT i = 0; i < hd.NumDescriptors; ++i)
        {
            const bool output = i >= p.srvs.size();
            const int index = output ? p.uavs[i - p.srvs.size()] : p.srvs[i];
            const Resource* r = index >= 0 ? &resources[index] : nullptr;
            const UINT kind = r ? r->kind : (index == -2 ? 0 : (index == -3 ? 3 : 2));
            const DXGI_FORMAT fmt = r ? DXGI_FORMAT(r->format) : DXGI_FORMAT_R16G16B16A16_FLOAT;
            auto cpu = p.heap->GetCPUDescriptorHandleForHeapStart(); cpu.ptr += SIZE_T(i) * increment;
            // Always value-initialize these union-bearing descriptors. In particular,
            // Buffer flags/stride must never inherit Texture2DArray fields.
            if (output)
            {
                D3D12_UNORDERED_ACCESS_VIEW_DESC view {};
                view.Format = kind == 0 ? DXGI_FORMAT_R32_TYPELESS : fmt;
                if (kind == 0)
                {
                    view.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
                    view.Buffer.NumElements = r ? r->width / 4 : 4; view.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW;
                }
                else if (kind == 3)
                {
                    view.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2DARRAY;
                    view.Texture2DArray.ArraySize = r ? r->layers : 6;
                }
                else view.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
                device->CreateUnorderedAccessView(r ? r->gpu.Get() : nullptr, nullptr, &view, cpu);
            }
            else
            {
                D3D12_SHADER_RESOURCE_VIEW_DESC view {};
                view.Format = kind == 0 ? DXGI_FORMAT_R32_TYPELESS : fmt;
                view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
                if (kind == 0)
                {
                    view.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
                    view.Buffer.NumElements = r ? r->width / 4 : 4; view.Buffer.Flags = D3D12_BUFFER_SRV_FLAG_RAW;
                }
                else if (kind == 3)
                {
                    view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2DARRAY;
                    view.Texture2DArray.MipLevels = 1; view.Texture2DArray.ArraySize = r ? r->layers : 6;
                }
                else { view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D; view.Texture2D.MipLevels = 1; }
                device->CreateShaderResourceView(r ? r->gpu.Get() : nullptr, &view, cpu);
            }
        }
    }
    D3D12_INDIRECT_ARGUMENT_DESC argument {}; argument.Type = D3D12_INDIRECT_ARGUMENT_TYPE_DISPATCH;
    D3D12_COMMAND_SIGNATURE_DESC signatureDesc {sizeof(D3D12_DISPATCH_ARGUMENTS), 1, &argument, 0};
    ComPtr<ID3D12CommandSignature> signature;
    check(device->CreateCommandSignature(&signatureDesc, nullptr, IID_PPV_ARGS(&signature)), "chain indirect signature");
    const UINT queriesPerRepeat = 2 * (passCount + 1);
    D3D12_QUERY_HEAP_DESC queryDesc {}; queryDesc.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP;
    queryDesc.Count = queriesPerRepeat * repetitions;
    ComPtr<ID3D12QueryHeap> query;
    check(device->CreateQueryHeap(&queryDesc, IID_PPV_ARGS(&query)), "chain timestamps");
    auto queryReadback = staging(UINT64(queryDesc.Count) * 8, D3D12_HEAP_TYPE_READBACK);
    for (UINT repetition = 0; repetition < repetitions; ++repetition)
    {
        const UINT first = repetition * queriesPerRepeat;
        cmd->EndQuery(query.Get(), D3D12_QUERY_TYPE_TIMESTAMP, first);
        for (UINT index = 0; index < passCount; ++index)
        {
            auto& p = passes[index];
            const UINT start = first + 2 + 2 * index;
            cmd->EndQuery(query.Get(), D3D12_QUERY_TYPE_TIMESTAMP, start);
            if (p.mode == 2)
            {
                for (int resource : p.uavs) if (resource >= 0) uploadResource(resources[resource], p.x);
            }
            else
            {
                for (int resource : p.srvs) if (resource >= 0) transition(resources[resource], kOutputReadState);
                for (int resource : p.uavs) if (resource >= 0) transition(resources[resource], D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
                if (p.mode == 1) transition(resources[p.argument], D3D12_RESOURCE_STATE_INDIRECT_ARGUMENT);
                cmd->SetPipelineState(p.pipeline.Get()); cmd->SetComputeRootSignature(p.root.Get());
                ID3D12DescriptorHeap* heaps[] {p.heap.Get()}; cmd->SetDescriptorHeaps(1, heaps);
                cmd->SetComputeRootConstantBufferView(0, p.cb->GetGPUVirtualAddress());
                auto gpu = p.heap->GetGPUDescriptorHandleForHeapStart(); cmd->SetComputeRootDescriptorTable(1, gpu);
                gpu.ptr += UINT64(p.srvs.size()) * increment; cmd->SetComputeRootDescriptorTable(2, gpu);
                if (p.mode == 1) cmd->ExecuteIndirect(signature.Get(), 1, resources[p.argument].gpu.Get(), p.offset, nullptr, 0);
                else cmd->Dispatch(p.x, p.y, p.z);
                // A transition orders UAV->SRV reads; this barrier also orders
                // consecutive UAV writers and partial Texture2DArray stores.
                D3D12_RESOURCE_BARRIER barrier {}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
                cmd->ResourceBarrier(1, &barrier);
                for (int resource : p.uavs) if (resource >= 0)
                    transition(resources[resource], indirectResources.count(resource) ?
                               D3D12_RESOURCE_STATE_INDIRECT_ARGUMENT : kOutputReadState);
            }
            cmd->EndQuery(query.Get(), D3D12_QUERY_TYPE_TIMESTAMP, start + 1);
        }
        cmd->EndQuery(query.Get(), D3D12_QUERY_TYPE_TIMESTAMP, first + 1);
    }
    cmd->ResolveQueryData(query.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0, queryDesc.Count, queryReadback.Get(), 0);
    for (auto& r : resources) if (r.readback)
    {
        transition(r, D3D12_RESOURCE_STATE_COPY_SOURCE);
        if (r.kind == 0) cmd->CopyBufferRegion(r.readback.Get(), 0, r.gpu.Get(), 0, r.width);
        else for (UINT slice = 0; slice < r.layers; ++slice)
        {
            D3D12_TEXTURE_COPY_LOCATION src {}; src.pResource = r.gpu.Get();
            src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX; src.SubresourceIndex = slice;
            D3D12_TEXTURE_COPY_LOCATION dst {}; dst.pResource = r.readback.Get();
            dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint = r.footprints[slice];
            cmd->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
        }
    }
    check(cmd->Close(), "chain close");
    ID3D12CommandList* lists[] {cmd.Get()}; queue->ExecuteCommandLists(1, lists);
    ComPtr<ID3D12Fence> fence;
    check(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "chain fence");
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    check(queue->Signal(fence.Get(), 1), "chain signal");
    check(fence->SetEventOnCompletion(1, event), "chain event");
    const auto wait = WaitForSingleObject(event, 60000); CloseHandle(event);
    if (wait != WAIT_OBJECT_0) throw std::runtime_error("chain GPU timeout");
    check(device->GetDeviceRemovedReason(), "chain device removed");
    UINT64 frequency; check(queue->GetTimestampFrequency(&frequency), "chain timestamp frequency");
    UINT64* timestamps;
    check(queryReadback->Map(0, nullptr, reinterpret_cast<void**>(&timestamps)), "chain timestamp map");
    std::cout << std::setprecision(10);
    const auto report = [&](const std::string& name, UINT pair) {
        std::vector<double> measured;
        std::cout << "chain_samples " << std::quoted(name);
        for (UINT repetition = 0; repetition < repetitions; ++repetition)
        {
            const UINT start = repetition * queriesPerRepeat + pair;
            const double ms = double(timestamps[start + 1] - timestamps[start]) * 1000.0 / frequency;
            std::cout << ' ' << ms;
            if (repetition >= warmup) measured.push_back(ms);
        }
        std::cout << '\n'; std::sort(measured.begin(), measured.end());
        double sum = 0; for (double value : measured) sum += value;
        const double mean = sum / measured.size(); double variance = 0;
        for (double value : measured) variance += (value - mean) * (value - mean);
        const auto percentile = [&](double fraction) {
            const double location = fraction * (measured.size() - 1);
            const size_t low = size_t(location), high = std::min(low + 1, measured.size() - 1);
            return measured[low] + (measured[high] - measured[low]) * (location - low);
        };
        std::cout << "chain_timing " << std::quoted(name) << " median=" << percentile(0.5)
                  << " p95=" << percentile(0.95) << " min=" << measured.front()
                  << " max=" << measured.back() << " mean=" << mean << " stddev=" << sqrt(variance/measured.size())
                  << " samples=" << measured.size() << " warmup=" << warmup << '\n';
    };
    report("__chain__", 0);
    for (UINT index = 0; index < passCount; ++index) report(passes[index].name, 2 + 2 * index);
    queryReadback->Unmap(0, nullptr);
    for (auto& r : resources) if (r.readback)
    {
        char* mapped; check(r.readback->Map(0, nullptr, reinterpret_cast<void**>(&mapped)), "chain readback map");
        std::ofstream output(r.output, std::ios::binary);
        if (r.kind == 0) output.write(mapped, r.width);
        else
        {
            const size_t row = size_t(r.width) * pixelBytes(DXGI_FORMAT(r.format));
            for (UINT slice = 0; slice < r.layers; ++slice) for (UINT y = 0; y < r.height; ++y)
                output.write(mapped + r.footprints[slice].Offset + UINT64(y) * r.footprints[slice].Footprint.RowPitch, row);
        }
        if (!output) throw std::runtime_error("chain readback write failed: " + r.output);
        r.readback->Unmap(0, nullptr);
    }
    UINT errors = 0, warnings = 0;
    if (info) for (UINT64 i = 0; i < info->GetNumStoredMessages(); ++i)
    {
        SIZE_T size = 0; info->GetMessage(i, nullptr, &size); std::vector<char> storage(size);
        auto* message = reinterpret_cast<D3D12_MESSAGE*>(storage.data()); info->GetMessage(i, message, &size);
        if (message->Severity <= D3D12_MESSAGE_SEVERITY_ERROR) { std::cerr << message->pDescription << '\n'; ++errors; }
        else if (message->Severity == D3D12_MESSAGE_SEVERITY_WARNING) { std::cerr << message->pDescription << '\n'; ++warnings; }
    }
    std::cout << "chain_resources=" << resourceCount << " chain_passes=" << passCount
              << " allocated_gpu_bytes=" << allocatedBytes << " timestamp_frequency=" << frequency
              << " debug_layer=" << debugEnabled << " validation_errors=" << errors
              << " validation_warnings=" << warnings << '\n';
    if (info) info->ClearStoredMessages();
    if (errors) throw std::runtime_error("chain D3D12 validation errors: " + std::to_string(errors));
    return 0;
}
