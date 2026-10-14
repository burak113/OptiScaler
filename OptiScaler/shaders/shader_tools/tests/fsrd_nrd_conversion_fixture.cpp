// Compiled by test_fsrd_nrd_conversion.py with the production conversion .cpp.
// Only hook adapters and descriptor-allocation instrumentation are substituted.
#include "production_nrd_pass.cpp"
#include <DirectXPackedVector.h>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <source_location>

namespace FrameSurvey
{
ScopedInternal::ScopedInternal() noexcept : previous_(false) {}
ScopedInternal::~ScopedInternal() {}
}

namespace fs = std::filesystem;
using Microsoft::WRL::ComPtr;
static uint64_t checks = 0;
static void need(bool value, const char* message)
{ ++checks; if (!value) throw std::runtime_error(message); }
static void hr(HRESULT result, std::source_location location = std::source_location::current())
{
    ++checks;
    if (FAILED(result)) throw std::runtime_error("D3D12 fixture HRESULT=" + std::to_string(uint32_t(result)) +
        " line=" + std::to_string(location.line()));
}
static uint32_t bytesPerPixel(DXGI_FORMAT format)
{
    if (format == DXGI_FORMAT_R16G16B16A16_FLOAT) return 8;
    return 4;
}
static std::vector<char> load(const fs::path& path)
{
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    need(bool(stream), "input file missing");
    std::vector<char> data(size_t(stream.tellg())); stream.seekg(0);
    stream.read(data.data(), std::streamsize(data.size())); need(bool(stream), "input file truncated");
    return data;
}
static void save(const fs::path& path, const std::vector<char>& data)
{
    std::ofstream stream(path, std::ios::binary);
    stream.write(data.data(), std::streamsize(data.size())); need(bool(stream), "output file failed");
}

struct Readback
{
    ComPtr<ID3D12Resource> buffer;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {};
    uint64_t bytes = 0;
    uint32_t width = 0, height = 0, pixelBytes = 0;
    std::vector<char> Data() const
    {
        void* mapped = nullptr; D3D12_RANGE range {0, SIZE_T(bytes)}; hr(buffer->Map(0, &range, &mapped));
        std::vector<char> result(size_t(width) * height * pixelBytes);
        for (uint32_t y = 0; y < height; ++y)
            memcpy(result.data() + size_t(y) * width * pixelBytes,
                   static_cast<char*>(mapped) + footprint.Offset + size_t(y) * footprint.Footprint.RowPitch,
                   size_t(width) * pixelBytes);
        const D3D12_RANGE empty {0,0}; buffer->Unmap(0, &empty); return result;
    }
};

struct Fixture
{
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> list;
    ComPtr<ID3D12Fence> fence;
    ComPtr<IUnknown> listIdentity;
    ComPtr<ID3D12InfoQueue> info;
    std::vector<ComPtr<ID3D12Resource>> uploads;
    HANDLE event = nullptr;
    uint64_t fenceValue = 0;

    explicit Fixture(bool gpuValidation)
    {
        ComPtr<ID3D12Debug> debug; hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug))); debug->EnableDebugLayer();
        if (gpuValidation)
        {
            ComPtr<ID3D12Debug1> debug1; hr(debug.As(&debug1)); debug1->SetEnableGPUBasedValidation(TRUE);
        }
        ComPtr<IDXGIFactory6> factory; hr(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)));
        ComPtr<IDXGIAdapter1> adapter;
        hr(factory->EnumAdapterByGpuPreference(0, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE, IID_PPV_ARGS(&adapter)));
        DXGI_ADAPTER_DESC1 desc {}; hr(adapter->GetDesc1(&desc));
        std::wcout << L"adapter=" << desc.Description << L"\n";
        hr(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_12_0, IID_PPV_ARGS(&device)));
        hr(device.As(&info));
        D3D12_COMMAND_QUEUE_DESC q {}; q.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        hr(device->CreateCommandQueue(&q, IID_PPV_ARGS(&queue)));
        hr(device->CreateCommandAllocator(q.Type, IID_PPV_ARGS(&allocator)));
        hr(device->CreateCommandList(0, q.Type, allocator.Get(), nullptr, IID_PPV_ARGS(&list)));
        hr(list.As(&listIdentity)); hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)));
        event = CreateEvent(nullptr, FALSE, FALSE, nullptr); need(event != nullptr, "event creation failed");
        RecordedComputeLease::SetHooksAvailable(true, true);
    }
    ~Fixture() { if (event) CloseHandle(event); }
    ComPtr<ID3D12Resource> Buffer(uint64_t size, D3D12_HEAP_TYPE heapType)
    {
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = heapType;
        D3D12_RESOURCE_DESC desc {}; desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = size; desc.Height = 1; desc.DepthOrArraySize = desc.MipLevels = 1;
        desc.SampleDesc.Count = 1; desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> resource;
        hr(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
            heapType == D3D12_HEAP_TYPE_UPLOAD ? D3D12_RESOURCE_STATE_GENERIC_READ : D3D12_RESOURCE_STATE_COPY_DEST,
            nullptr, IID_PPV_ARGS(&resource)));
        return resource;
    }
    static void Transition(ID3D12GraphicsCommandList* list, ID3D12Resource* resource,
                           D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after)
    {
        D3D12_RESOURCE_BARRIER barrier {}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition = {resource, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, before, after};
        list->ResourceBarrier(1, &barrier);
    }
    ComPtr<ID3D12Resource> Texture(uint32_t width, uint32_t height, DXGI_FORMAT format,
                                 D3D12_RESOURCE_STATES target, const std::vector<char>* data = nullptr)
    {
        D3D12_RESOURCE_DESC desc {}; desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        desc.Width = width; desc.Height = height; desc.DepthOrArraySize = desc.MipLevels = 1;
        desc.SampleDesc.Count = 1; desc.Format = format;
        if (target == D3D12_RESOURCE_STATE_UNORDERED_ACCESS) desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        ComPtr<ID3D12Resource> resource;
        hr(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
            data ? D3D12_RESOURCE_STATE_COPY_DEST : target, nullptr, IID_PPV_ARGS(&resource)));
        if (data)
        {
            D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {}; UINT rows; uint64_t rowBytes, total;
            device->GetCopyableFootprints(&desc, 0, 1, 0, &footprint, &rows, &rowBytes, &total);
            need(data->size() == size_t(width) * height * bytesPerPixel(format), "input size mismatch");
            auto upload = Buffer(total, D3D12_HEAP_TYPE_UPLOAD);
            void* mapped = nullptr; const D3D12_RANGE empty {0,0}; hr(upload->Map(0, &empty, &mapped));
            for (uint32_t y = 0; y < height; ++y)
                memcpy(static_cast<char*>(mapped) + footprint.Offset + size_t(y) * footprint.Footprint.RowPitch,
                       data->data() + size_t(y) * rowBytes, size_t(rowBytes));
            upload->Unmap(0, nullptr);
            D3D12_TEXTURE_COPY_LOCATION src {}, dst {};
            src.pResource = upload.Get(); src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint = footprint;
            dst.pResource = resource.Get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
            Transition(list.Get(), resource.Get(), D3D12_RESOURCE_STATE_COPY_DEST, target);
            uploads.push_back(upload);
        }
        return resource;
    }
    Readback Snapshot(ID3D12Resource* source, D3D12_RESOURCE_STATES state)
    {
        Readback result; const auto desc = source->GetDesc(); result.width = uint32_t(desc.Width); result.height = desc.Height;
        result.pixelBytes = bytesPerPixel(desc.Format);
        device->GetCopyableFootprints(&desc, 0, 1, 0, &result.footprint, nullptr, nullptr, &result.bytes);
        result.buffer = Buffer(result.bytes, D3D12_HEAP_TYPE_READBACK);
        Transition(list.Get(), source, state, D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION src {}, dst {};
        src.pResource = source; src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        dst.pResource = result.buffer.Get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint = result.footprint;
        list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
        Transition(list.Get(), source, D3D12_RESOURCE_STATE_COPY_SOURCE, state);
        return result;
    }
    void Submit()
    {
        hr(list->Close()); ID3D12CommandList* lists[] = {list.Get()};
        auto lease = RecordedComputeLease::BeforeSubmission(queue.Get(), {listIdentity.Get()});
        queue->ExecuteCommandLists(1, lists); RecordedComputeLease::AfterSubmission(lease);
        hr(queue->Signal(fence.Get(), ++fenceValue)); hr(fence->SetEventOnCompletion(fenceValue, event));
        need(WaitForSingleObject(event, 30000) == WAIT_OBJECT_0, "GPU completion timeout");
        RecordedComputeLease::Poll();
    }
    void Reset()
    {
        auto recording = RecordedComputeLease::Capture(list.Get());
        hr(allocator->Reset()); hr(list->Reset(allocator.Get(), nullptr));
        RecordedComputeLease::Detach(recording); uploads.clear();
    }
    void Validate()
    {
        for (uint64_t i = 0; i < info->GetNumStoredMessages(); ++i)
        {
            SIZE_T length = 0; hr(info->GetMessage(i, nullptr, &length)); std::vector<char> buffer(length);
            auto* message = reinterpret_cast<D3D12_MESSAGE*>(buffer.data()); hr(info->GetMessage(i, message, &length));
            if (message->Severity <= D3D12_MESSAGE_SEVERITY_WARNING)
                throw std::runtime_error(message->pDescription);
        }
        std::cout << "debug_errors=0 debug_warnings=0\n";
    }
};

static ULONG References(ID3D12Resource* resource) { const auto value = resource->AddRef(); resource->Release(); return value; }
struct InputSet
{
    std::array<ComPtr<ID3D12Resource>, 5> textures;
    NrdBridge::ConversionInputs Inputs() const
    { return {textures[0].Get(), textures[1].Get(), textures[2].Get(), textures[3].Get(), textures[4].Get()}; }
    static InputSet Read(Fixture& fixture, const fs::path& path, uint32_t width, uint32_t height)
    {
        InputSet result;
        const char* names[] = {"spec.bin", "diff.bin", "nr.bin", "depth.bin", "motion.bin"};
        const DXGI_FORMAT formats[] = {DXGI_FORMAT_R16G16B16A16_FLOAT, DXGI_FORMAT_R16G16B16A16_FLOAT,
                                      DXGI_FORMAT_R10G10B10A2_UNORM, DXGI_FORMAT_R32_FLOAT, DXGI_FORMAT_R16G16B16A16_FLOAT};
        for (uint32_t i = 0; i < 5; ++i)
        {
            auto data = load(path / names[i]);
            result.textures[i] = fixture.Texture(width, height, formats[i], i < 2
                ? D3D12_RESOURCE_STATE_UNORDERED_ACCESS : D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, &data);
            (i < 2 ? gNrdReconInputs : gNrdGuideInputs).insert(result.textures[i].Get());
        }
        return result;
    }
};

static NrdBridge::FrameParameters ReadFrame(const fs::path& path, uint32_t& mode)
{
    std::ifstream stream(path / "frame.txt"); NrdBridge::FrameParameters result;
    uint32_t jittered, reset, previousValid;
    stream >> result.nearPlane >> result.farPlane >> result.depthSign >> result.motionScale.x >> result.motionScale.y
           >> result.jitter.x >> result.jitter.y >> result.previousJitter.x >> result.previousJitter.y
           >> jittered >> reset >> previousValid >> mode;
    result.motionVectorsJittered = jittered != 0; result.reset = reset != 0; result.previousValid = previousValid != 0;
    DirectX::XMFLOAT4X4 view, projection;
    for (auto& row : view.m) for (auto& value : row) stream >> value;
    for (auto& row : projection.m) for (auto& value : row) stream >> value;
    need(bool(stream), "frame parameters missing");
    result.camera.view = DirectX::XMLoadFloat4x4(&view);
    result.camera.inverseView = DirectX::XMMatrixInverse(nullptr, result.camera.view);
    result.camera.projection = DirectX::XMLoadFloat4x4(&projection);
    result.camera.viewSource = result.camera.projectionSource = FSRDCamera::Source::StreamlineMatrix;
    result.camera.isRightHanded = result.depthSign < 0;
    return result;
}

static void Sequence(const fs::path& root, bool gpuValidation, bool deferred = false)
{
    std::ifstream meta(root / "meta.txt"); uint32_t frames, width, height; meta >> frames >> width >> height;
    need(bool(meta) && frames <= 24, "invalid fixture sequence");
    Fixture fixture(gpuValidation);
    auto pass = std::make_unique<NrdBridge::ConversionPass>(); std::string error;
    need(pass->Initialize(fixture.device.Get(), width, height, error), error.c_str());
    need(pass->OwnedTextureBytes() >= uint64_t(width) * height * 44, "owned texture bytes are incomplete");
    std::vector<InputSet> inputs; std::vector<std::array<ComPtr<ID3D12Resource>, 2>> outputs;
    std::vector<std::array<Readback, 9>> snapshots;
    for (uint32_t frameIndex = 0; frameIndex < frames; ++frameIndex)
    {
        auto path = root / ("frame" + std::to_string(frameIndex));
        auto input = InputSet::Read(fixture, path, width, height);
        std::array<ULONG, 5> before {};
        for (uint32_t i = 0; i < 5; ++i) before[i] = References(input.textures[i].Get());
        uint32_t mode; auto frame = ReadFrame(path, mode);
        if (frameIndex == 0)
        {
            const auto auditedBefore = gNrdAuditedBarriers;
            NrdBridge::ConvertedResources rejected;
            auto missing = input.Inputs(); missing.reconSpec = nullptr;
            need(!pass->Dispatch(fixture.list.Get(), missing, frame, rejected, error) && !rejected.spec,
                 "missing Recon texture accepted");
            auto invalid = frame; invalid.camera.view = DirectX::XMMatrixSet(0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0);
            need(!pass->Dispatch(fixture.list.Get(), input.Inputs(), invalid, rejected, error), "singular view accepted");
            invalid = frame; invalid.camera.projection = invalid.camera.view = DirectX::XMMatrixSet(0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0);
            need(!pass->Dispatch(fixture.list.Get(), input.Inputs(), invalid, rejected, error), "singular projection accepted");
            invalid = frame; invalid.farPlane = 100000;
            need(!pass->Dispatch(fixture.list.Get(), input.Inputs(), invalid, rejected, error), "unrepresentable far plane accepted");
            invalid = frame; invalid.motionScale.x = std::numeric_limits<float>::quiet_NaN();
            need(!pass->Dispatch(fixture.list.Get(), input.Inputs(), invalid, rejected, error), "NaN motion scale accepted");
            need(!RecordedComputeLease::Capture(fixture.list.Get()) && gNrdAuditedBarriers == auditedBefore,
                 "invalid conversion recorded GPU work");
        }
        if (frameIndex == 4) pass->ResetHistory();
        NrdBridge::ConvertedResources resources;
        auto currentInputs = input.Inputs();
        if (deferred)
        {
            currentInputs.motion = nullptr;
            // At Recon the old/cached MV may be a live object in COPY_DEST. It must not be read.
            Fixture::Transition(fixture.list.Get(), input.textures[4].Get(),
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_DEST);
        }
        need(pass->Dispatch(fixture.list.Get(), currentInputs, frame, resources, error), error.c_str());
        if (deferred)
        {
            const auto before = gNrdAuditedBarriers;
            need(!pass->DispatchMotion(fixture.list.Get(), resources, nullptr, frame, error), "missing current Temporal MV accepted");
            auto stale = frame; ++stale.streamlineFrame;
            need(!pass->DispatchMotion(fixture.list.Get(), resources, input.textures[4].Get(), stale, error), "stale Temporal frame ticket accepted");
            need(!pass->DispatchMotion(fixture.list.Get(), resources, resources.motion, frame, error), "motion read/write alias accepted");
            stale = frame; stale.motionVectors3D = true;
            need(!pass->DispatchMotion(fixture.list.Get(), resources, input.textures[4].Get(), stale, error), "3D motion accepted");
            need(before == gNrdAuditedBarriers, "invalid deferred motion recorded GPU work");
            Fixture::Transition(fixture.list.Get(), input.textures[4].Get(),
                D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
            need(pass->DispatchMotion(fixture.list.Get(), resources, input.textures[4].Get(), frame, error), error.c_str());
            const auto finished = gNrdAuditedBarriers;
            need(!pass->DispatchMotion(fixture.list.Get(), resources, input.textures[4].Get(), frame, error), "duplicate Temporal motion ticket accepted");
            need(finished == gNrdAuditedBarriers, "duplicate deferred motion recorded GPU work");
        }
        for (uint32_t i = 0; i < 5; ++i)
            need(References(input.textures[i].Get()) == before[i], "conversion AddRef'd a title input");
        std::array<ComPtr<ID3D12Resource>, 2> output;
        for (auto& texture : output)
        {
            texture = fixture.Texture(width, height, DXGI_FORMAT_R16G16B16A16_FLOAT, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            gNrdTitleOutputs.insert(texture.Get());
        }
        const ULONG specRefs = References(output[0].Get()), diffRefs = References(output[1].Get());
        if (frameIndex == 0)
        {
            const auto auditedBefore = gNrdAuditedBarriers;
            need(!pass->WriteDebug(fixture.list.Get(), resources, output[0].Get(), output[0].Get(),
                                  NrdBridge::DebugMode::RawSignals, error), "aliased title outputs accepted");
            need(!pass->WriteDebug(fixture.list.Get(), resources, resources.spec, output[1].Get(),
                                  NrdBridge::DebugMode::RawSignals, error), "debug read/write alias accepted");
            need(!pass->WriteDebug(fixture.list.Get(), resources, output[0].Get(), output[1].Get(),
                                  NrdBridge::DebugMode::Off, error), "Off debug request dispatched");
            need(gNrdAuditedBarriers == auditedBefore, "invalid debug request recorded GPU work");
        }
        need(pass->WriteDebug(fixture.list.Get(), resources, output[0].Get(), output[1].Get(),
                             NrdBridge::DebugMode(mode), error), error.c_str());
        need(References(output[0].Get()) == specRefs && References(output[1].Get()) == diffRefs,
             "debug copy AddRef'd a title output");
        std::array<Readback, 9> snapshot;
        ID3D12Resource* own[] = {resources.spec, resources.diff, resources.linearDepth, resources.motion,
                                resources.normals, resources.specAlbedo, resources.diffAlbedo};
        for (uint32_t i = 0; i < 7; ++i)
            snapshot[i] = fixture.Snapshot(own[i], D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        for (uint32_t i = 0; i < 2; ++i)
            snapshot[7+i] = fixture.Snapshot(output[i].Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        inputs.push_back(std::move(input)); outputs.push_back(std::move(output)); snapshots.push_back(std::move(snapshot));
    }
    // Resize and destroy the entire public pass BEFORE Execute. The exact production
    // leases must still keep old textures, both PSOs, roots and every descriptor slot.
    need(pass->Initialize(fixture.device.Get(), 7, 5, error), error.c_str()); pass.reset();
    need(RecordedComputeLease::Capture(fixture.list.Get()) != nullptr, "production GPU lease not registered");
    fixture.Submit(); fixture.Reset();
    need(RecordedComputeLease::GetRegistry().recordings.empty() && RecordedComputeLease::GetRegistry().submissions.empty(),
         "GPU leases did not retire after fence and Reset");
    const char* names[] = {"out_spec.bin", "out_diff.bin", "out_depth.bin", "out_motion.bin", "out_nr.bin",
                          "out_spec_albedo.bin", "out_diff_albedo.bin", "debug_spec.bin", "debug_diff.bin"};
    for (uint32_t f = 0; f < frames; ++f)
        for (uint32_t i = 0; i < 9; ++i) save(root / ("frame" + std::to_string(f)) / names[i], snapshots[f][i].Data());
    // Fail before recording any work when the actual queue/list lease contract is unavailable.
    RecordedComputeLease::SetHooksAvailable(false, false);
    NrdBridge::ConversionPass denied; need(denied.Initialize(fixture.device.Get(), width, height, error), error.c_str());
    uint32_t mode; auto frame = ReadFrame(root / "frame0", mode); NrdBridge::ConvertedResources unused;
    need(!denied.Dispatch(fixture.list.Get(), inputs[0].Inputs(), frame, unused, error), "untracked dispatch was accepted");
    need(!unused.spec && !unused.diff && !RecordedComputeLease::Capture(fixture.list.Get()), "failed dispatch exposed outputs");
    RecordedComputeLease::SetHooksAvailable(true, true);
    hr(fixture.list->Close()); fixture.Validate();
    std::cout << "fixture_checks=" << checks << " descriptor_heaps=" << gNrdDescriptorAllocations
              << " audited_views=" << gNrdAuditedViews << " audited_barriers=" << gNrdAuditedBarriers << "\n";
}

static void Benchmark(const fs::path& root, bool deferred = false)
{
    std::ifstream meta(root / "meta.txt"); uint32_t frames, width, height; meta >> frames >> width >> height;
    Fixture fixture(false); auto input = InputSet::Read(fixture, root / "frame0", width, height);
    uint32_t mode; auto frame = ReadFrame(root / "frame0", mode);
    fixture.Submit(); fixture.Reset();
    NrdBridge::ConversionPass pass; std::string error;
    need(pass.Initialize(fixture.device.Get(), width, height, error), error.c_str());
    constexpr uint32_t repetitions = 16, warmBatches = 2, measuredBatches = 9;
    const uint32_t stamps = deferred ? 3u : 2u;
    D3D12_QUERY_HEAP_DESC queryDesc {}; queryDesc.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP; queryDesc.Count = repetitions * stamps;
    ComPtr<ID3D12QueryHeap> query; hr(fixture.device->CreateQueryHeap(&queryDesc, IID_PPV_ARGS(&query)));
    auto timestamps = fixture.Buffer(repetitions * stamps * sizeof(uint64_t), D3D12_HEAP_TYPE_READBACK);
    uint64_t frequency; hr(fixture.queue->GetTimestampFrequency(&frequency));
    std::vector<double> samples, reconSamples, motionSamples; uint32_t warmedHeaps = 0;
    for (uint32_t batch = 0; batch < warmBatches + measuredBatches; ++batch)
    {
        for (uint32_t i = 0; i < repetitions; ++i)
        {
            frame.reset = batch == 0 && i == 0; frame.previousValid = !frame.reset;
            fixture.list->EndQuery(query.Get(), D3D12_QUERY_TYPE_TIMESTAMP, i * stamps);
            NrdBridge::ConvertedResources output;
            auto currentInputs = input.Inputs(); if (deferred) currentInputs.motion = nullptr;
            need(pass.Dispatch(fixture.list.Get(), currentInputs, frame, output, error), error.c_str());
            fixture.list->EndQuery(query.Get(), D3D12_QUERY_TYPE_TIMESTAMP, i * stamps + 1);
            if (deferred)
            {
                need(pass.DispatchMotion(fixture.list.Get(), output, input.textures[4].Get(), frame, error), error.c_str());
                fixture.list->EndQuery(query.Get(), D3D12_QUERY_TYPE_TIMESTAMP, i * stamps + 2);
            }
        }
        fixture.list->ResolveQueryData(query.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0, repetitions * stamps, timestamps.Get(), 0);
        fixture.Submit(); fixture.Reset();
        if (batch == warmBatches - 1) warmedHeaps = gNrdDescriptorAllocations;
        if (batch >= warmBatches)
        {
            need(warmedHeaps == gNrdDescriptorAllocations, "descriptor heap allocated after warmup");
            uint64_t* values = nullptr; const D3D12_RANGE range {0, repetitions * stamps * sizeof(uint64_t)};
            hr(timestamps->Map(0, &range, reinterpret_cast<void**>(&values))); double total = 0, recon = 0, motion = 0;
            for (uint32_t i = 0; i < repetitions; ++i)
            {
                const auto start = values[i*stamps], middle = values[i*stamps+1], end = values[i*stamps+stamps-1];
                total += double(end-start); recon += double(middle-start); motion += double(end-middle);
            }
            const D3D12_RANGE empty {0,0}; timestamps->Unmap(0, &empty);
            const auto scale = 1000.0 / double(frequency) / repetitions;
            samples.push_back(total * scale); reconSamples.push_back(recon * scale); motionSamples.push_back(motion * scale);
        }
    }
    hr(fixture.list->Close()); fixture.Validate();
    std::cout << std::setprecision(10) << "gpu_ms=";
    for (size_t i = 0; i < samples.size(); ++i) std::cout << (i ? "," : "") << samples[i];
    if (deferred)
    {
        std::cout << "\nrecon_gpu_ms=";
        for (size_t i=0;i<reconSamples.size();++i) std::cout << (i ? "," : "") << reconSamples[i];
        std::cout << "\nmotion_gpu_ms=";
        for (size_t i=0;i<motionSamples.size();++i) std::cout << (i ? "," : "") << motionSamples[i];
    }
    std::cout << "\ntexture_bytes=" << pass.OwnedTextureBytes() << " descriptor_heaps=" << warmedHeaps
              << " descriptor_allocations_after_warmup=0\nfixture_checks=" << checks << "\n";
}

int main(int argc, char** argv) try
{
    need(argc == 3, "usage: fixture sequence|capture|benchmark path");
    std::string mode = argv[1]; const bool deferred = mode.starts_with("deferred-");
    if (deferred) mode.erase(0,9);
    if (mode == "benchmark") Benchmark(argv[2],deferred);
    else Sequence(argv[2], mode == "sequence",deferred);
    std::cout << "PASS: production NRD conversion, borrowed title resources, GPU retirement\n"; return 0;
}
catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
