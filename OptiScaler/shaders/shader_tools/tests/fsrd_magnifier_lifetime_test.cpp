#include "dx12_shader_test_support.h"
#include "../../Shader_Dx12.cpp"
#include "../../magnifier/Magnifier_Common.cpp"
#include "../../magnifier/Magnifier_Dx12.cpp"
#include <iostream>

using Microsoft::WRL::ComPtr;
static void need(bool ok, const char* what) { if (!ok) throw std::runtime_error(what); }
static void hr(HRESULT result, const char* what) { need(SUCCEEDED(result), what); }

class TestMagnifier : public Magnifier_Dx12
{
  public:
    explicit TestMagnifier(ID3D12Device* device) : Magnifier_Dx12("Lease test", device) {}
    size_t SlotCount() const { return _dispatchSlots.size(); }
    std::weak_ptr<ShaderDispatchLease::Slot> Slot(size_t index) { return _dispatchSlots.at(index); }
    std::weak_ptr<ShaderDispatchLease::Intermediate> Owner() { return _recordedBuffer; }
    auto Params(UINT width, UINT height)
    {
        InternalMagnifierParams params {};
        FilloutStruct(static_cast<float>(width), static_cast<float>(height), params);
        return params;
    }
};

struct Runtime
{
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12InfoQueue> info;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12GraphicsCommandList> list;
    // A reset may occur while the GPU still uses an earlier allocator.
    std::vector<ComPtr<ID3D12CommandAllocator>> allocators;

    Runtime()
    {
        ComPtr<ID3D12Debug> debug;
        hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)), "debug interface");
        debug->EnableDebugLayer();
        ComPtr<IDXGIFactory4> factory;
        ComPtr<IDXGIAdapter> warp;
        hr(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)), "DXGI factory");
        hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)), "WARP adapter");
        hr(D3D12CreateDevice(warp.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)), "device");
        hr(device.As(&info), "info queue");
        D3D12_COMMAND_QUEUE_DESC desc {};
        hr(device->CreateCommandQueue(&desc, IID_PPV_ARGS(&queue)), "queue");
        NewList();
    }
    ID3D12CommandAllocator* NewAllocator()
    {
        ComPtr<ID3D12CommandAllocator> allocator;
        hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)), "allocator");
        allocators.push_back(allocator);
        return allocators.back().Get();
    }
    void NewList()
    {
        list.Reset();
        hr(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, NewAllocator(), nullptr,
                                     IID_PPV_ARGS(&list)), "list");
    }
    void Reset(ID3D12GraphicsCommandList* target = nullptr)
    {
        if (!target) target = list.Get();
        auto recording = RecordedComputeLease::Capture(target);
        hr(target->Reset(NewAllocator(), nullptr), "Reset");
        RecordedComputeLease::Detach(recording);
    }
    ComPtr<ID3D12Fence> Submit(bool tracked = true)
    {
        ComPtr<IUnknown> identity;
        hr(list.As(&identity), "list identity");
        auto intent = RecordedComputeLease::BeforeSubmission(queue.Get(), { identity.Get() });
        need(static_cast<bool>(intent) == tracked, "submission lease admission");
        ID3D12CommandList* lists[] { list.Get() };
        queue->ExecuteCommandLists(1, lists);
        if (intent)
        {
            RecordedComputeLease::AfterSubmission(intent);
            need(intent->signalPublished, "submission fence publication");
            return intent->fence;
        }
        ComPtr<ID3D12Fence> fence;
        hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "fence");
        hr(queue->Signal(fence.Get(), 1), "Signal");
        return fence;
    }
    void Wait(ID3D12Fence* fence)
    {
        HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        need(event != nullptr, "fence event");
        auto result = fence->SetEventOnCompletion(1, event);
        auto waited = SUCCEEDED(result) ? WaitForSingleObject(event, 30000) : WAIT_FAILED;
        CloseHandle(event);
        need(waited == WAIT_OBJECT_0, "GPU completion timeout");
        need(fence->GetCompletedValue() != UINT64_MAX, "device removed");
    }
    ComPtr<ID3D12Resource> Texture(UINT width, UINT height)
    {
        auto props = CD3DX12_HEAP_PROPERTIES(D3D12_HEAP_TYPE_DEFAULT);
        auto desc = CD3DX12_RESOURCE_DESC::Tex2D(DXGI_FORMAT_R32G32B32A32_FLOAT, width, height, 1, 1);
        desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS | D3D12_RESOURCE_FLAG_ALLOW_SIMULTANEOUS_ACCESS;
        ComPtr<ID3D12Resource> resource;
        hr(device->CreateCommittedResource(&props, D3D12_HEAP_FLAG_NONE, &desc, D3D12_RESOURCE_STATE_COMMON,
                                           nullptr, IID_PPV_ARGS(&resource)), "texture");
        return resource;
    }
    ComPtr<ID3D12Resource> Buffer(D3D12_HEAP_TYPE type, UINT64 size)
    {
        auto props = CD3DX12_HEAP_PROPERTIES(type);
        auto desc = CD3DX12_RESOURCE_DESC::Buffer(size);
        auto state = type == D3D12_HEAP_TYPE_UPLOAD ? D3D12_RESOURCE_STATE_GENERIC_READ : D3D12_RESOURCE_STATE_COPY_DEST;
        ComPtr<ID3D12Resource> resource;
        hr(device->CreateCommittedResource(&props, D3D12_HEAP_FLAG_NONE, &desc, state,
                                           nullptr, IID_PPV_ARGS(&resource)), "buffer");
        return resource;
    }
};

struct ImageCase
{
    ComPtr<ID3D12Resource> output, upload, readback;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {};
    std::vector<std::array<float, 4>> expected;
    std::weak_ptr<ShaderDispatchLease::Intermediate> owner;
    void Verify()
    {
        void* data = nullptr;
        hr(readback->Map(0, nullptr, &data), "readback Map");
        const auto* bytes = static_cast<const unsigned char*>(data) + footprint.Offset;
        bool matches = true;
        for (UINT y = 0; y < footprint.Footprint.Height; ++y)
            for (UINT x = 0; x < footprint.Footprint.Width; ++x)
                matches &= std::memcmp(bytes + y * footprint.Footprint.RowPitch + x * sizeof(expected[0]),
                                       expected[y * footprint.Footprint.Width + x].data(), sizeof(expected[0])) == 0;
        const D3D12_RANGE noWrite { 0, 0 };
        readback->Unmap(0, &noWrite);
        need(matches, "Magnifier dispatch consumed another evaluation's constants/descriptors/image");
    }
};

static void barrier(ID3D12GraphicsCommandList* list, ID3D12Resource* resource,
                    D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after)
{
    auto transition = CD3DX12_RESOURCE_BARRIER::Transition(resource, before, after);
    list->ResourceBarrier(1, &transition);
}

static ImageCase Record(Runtime& runtime, TestMagnifier& magnifier, UINT index, bool recorded = true)
{
    // First two evaluations share an extent; later evaluations also cover resizing.
    UINT width = index < 2 ? 41 : 41 + 4 * index, height = index < 2 ? 33 : 33 + 2 * index;
    Config::Instance()->MagnifierZoomFactor.value = 2 + index;
    Config::Instance()->MagnifierSize.value = 27.f + 4.f * index;
    auto params = magnifier.Params(width, height);
    ImageCase image;
    image.output = runtime.Texture(width, height);
    // COMMON also exercises the legacy three-argument API without its existing
    // ignored-initial-state warning for simultaneous-access textures.
    bool created = recorded ?
        magnifier.CreateBufferResource(runtime.device.Get(), image.output.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                                        runtime.list.Get()) :
        magnifier.CreateBufferResource(runtime.device.Get(), image.output.Get(), D3D12_RESOURCE_STATE_COMMON);
    need(created, "Magnifier intermediate admission");
    image.owner = magnifier.Owner();
    auto cleanup = magnifier.RecordedBufferCleanup(runtime.list.Get());
    auto desc = image.output->GetDesc();
    UINT64 bytes = 0;
    runtime.device->GetCopyableFootprints(&desc, 0, 1, 0, &image.footprint, nullptr, nullptr, &bytes);
    image.upload = runtime.Buffer(D3D12_HEAP_TYPE_UPLOAD, bytes);
    image.readback = runtime.Buffer(D3D12_HEAP_TYPE_READBACK, bytes);
    std::vector<std::array<float, 4>> source(width * height);
    for (UINT y = 0; y < height; ++y)
        for (UINT x = 0; x < width; ++x)
            source[y * width + x] = { 100.f * index + x, 200.f * index + y, index + 0.25f, 1.f };
    void* upload = nullptr;
    const D3D12_RANGE noRead { 0, 0 };
    hr(image.upload->Map(0, &noRead, &upload), "upload Map");
    for (UINT y = 0; y < height; ++y)
        std::memcpy(static_cast<unsigned char*>(upload) + image.footprint.Offset + y * image.footprint.Footprint.RowPitch,
                    source.data() + y * width, width * sizeof(source[0]));
    image.upload->Unmap(0, nullptr);

    magnifier.SetBufferState(runtime.list.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    magnifier.SetBufferState(runtime.list.Get(), D3D12_RESOURCE_STATE_COPY_DEST);
    CD3DX12_TEXTURE_COPY_LOCATION uploadLocation(image.upload.Get(), image.footprint);
    CD3DX12_TEXTURE_COPY_LOCATION inputLocation(magnifier.Buffer(), 0);
    runtime.list->CopyTextureRegion(&inputLocation, 0, 0, 0, &uploadLocation, nullptr);
    magnifier.SetBufferState(runtime.list.Get(), D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    barrier(runtime.list.Get(), image.output.Get(), D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    need(magnifier.Dispatch(runtime.list.Get(), magnifier.Buffer(), image.output.Get()), "Magnifier dispatch");
    barrier(runtime.list.Get(), image.output.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE);
    CD3DX12_TEXTURE_COPY_LOCATION outputLocation(image.output.Get(), 0);
    CD3DX12_TEXTURE_COPY_LOCATION readbackLocation(image.readback.Get(), image.footprint);
    runtime.list->CopyTextureRegion(&readbackLocation, 0, 0, 0, &outputLocation, nullptr);
    barrier(runtime.list.Get(), image.output.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_COMMON);
    if (cleanup) cleanup();

    image.expected = source;
    for (UINT y = 0; y < height; ++y)
        for (UINT x = 0; x < width; ++x)
        {
            float dx = x - params.CursorPosX, dy = y - params.CursorPosY;
            float distance = std::sqrt(dx * dx + dy * dy);
            if (distance > params.Radius) continue;
            if (distance > params.Radius - params.BorderThickness)
                image.expected[y * width + x] = { 0.f, 0.f, 0.f, 1.f };
            else
            {
                int sx = std::clamp(static_cast<int>(params.CursorPosX + std::floor(dx / params.ZoomFactor)), 0, int(width) - 1);
                int sy = std::clamp(static_cast<int>(params.CursorPosY + std::floor(dy / params.ZoomFactor)), 0, int(height) - 1);
                image.expected[y * width + x] = source[sy * width + sx];
            }
        }
    return image;
}

int main() try
{
    Runtime runtime;
    {
        TestMagnifier denied(runtime.device.Get());
        need(denied.IsInit(), "Magnifier initialization");
        denied.SetRecordedLifetimeEnabled(true);
        RecordedComputeLease::SetHooksAvailable(false, false);
        auto input = runtime.Texture(41, 33), output = runtime.Texture(41, 33);
        unsigned starts = GpuTime_Dx12::starts;
        need(!denied.CreateBufferResource(runtime.device.Get(), output.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS),
             "recorded setup requires a command list");
        need(!denied.CreateBufferResource(runtime.device.Get(), output.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                                          runtime.list.Get()), "missing hooks deny intermediate admission");
        need(!denied.Dispatch(runtime.list.Get(), input.Get(), output.Get()), "missing hooks deny dispatch");
        need(GpuTime_Dx12::starts == starts && !denied.Buffer(), "failed admission records no timestamps or buffer replacement");
    }
    RecordedComputeLease::SetHooksAvailable(true, true);
    {
        auto magnifier = std::make_unique<TestMagnifier>(runtime.device.Get());
        magnifier->SetRecordedLifetimeEnabled(true);
        std::vector<ImageCase> images;
        std::vector<std::weak_ptr<ShaderDispatchLease::Slot>> slots;
        for (UINT index = 0; index < 5; ++index)
        {
            images.push_back(Record(runtime, *magnifier, index));
            slots.push_back(magnifier->Slot(index));
        }
        need(magnifier->SlotCount() == 5, "deferred dispatches require independent slots");
        hr(runtime.list->Close(), "Close deferred recording");
        auto first = runtime.Submit();
        runtime.Wait(first.Get());
        for (auto& image : images) image.Verify();
        RecordedComputeLease::Poll();
        ComPtr<ID3D12Fence> gate;
        hr(runtime.device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&gate)), "queue gate");
        hr(runtime.queue->Wait(gate.Get(), 1), "block GPU execution");
        // Always unblock on a failing assertion too.
        struct Unblock { ID3D12Fence* gate; ~Unblock() { gate->Signal(1); } } unblock { gate.Get() };
        // Resubmission is legal only after the previous execution completes.
        auto second = runtime.Submit();
        magnifier.reset();
        for (auto& image : images) image.output.Reset();
        runtime.Reset();
        RecordedComputeLease::Poll();
        need(second->GetCompletedValue() == 0, "GPU work is still pending after Reset");
        for (const auto& image : images) need(!image.owner.expired(), "Reset/destruction must retain submitted intermediates");
        for (const auto& slot : slots) need(!slot.expired(), "Reset/destruction must retain submitted constants/descriptors");
        hr(gate->Signal(1), "unblock GPU");
        runtime.Wait(second.Get());
        for (auto& image : images) image.Verify();
        RecordedComputeLease::Poll();
        for (const auto& image : images) need(image.owner.expired(), "completed detached intermediates retire");
        for (const auto& slot : slots) need(slot.expired(), "completed detached dispatch slots retire");
        std::cout << "PASS: five deferred dispatches, resize, repeated submission, pending Reset/destruction and retirement\n";
    }
    {
        TestMagnifier magnifier(runtime.device.Get());
        magnifier.SetRecordedLifetimeEnabled(true);
        auto first = Record(runtime, magnifier, 0);
        hr(runtime.list->Close(), "Close first recording");
        runtime.Wait(runtime.Submit().Get());
        RecordedComputeLease::Poll();
        auto executableList = runtime.list;
        runtime.NewList();
        auto second = Record(runtime, magnifier, 1);
        need(magnifier.SlotCount() == 2, "GPU completion alone cannot recycle executable recording storage");
        hr(runtime.list->Close(), "Close second recording");
        runtime.Wait(runtime.Submit().Get());
        runtime.Reset(executableList.Get());
        hr(executableList->Close(), "Close discarded first recording");
        runtime.Reset();
        auto third = Record(runtime, magnifier, 2);
        need(magnifier.SlotCount() == 2, "slots recycle after both recording detach and GPU completion");
        hr(runtime.list->Close(), "Close third recording");
        runtime.Wait(runtime.Submit().Get());
        first.Verify(); second.Verify(); third.Verify();
        runtime.Reset();
        RecordedComputeLease::Poll();
        std::cout << "PASS: executable recording protection and safe slot reuse\n";
    }
    {
        TestMagnifier legacy(runtime.device.Get());
        auto image = Record(runtime, legacy, 0, false);
        hr(runtime.list->Close(), "Close legacy recording");
        runtime.Wait(runtime.Submit(false).Get());
        image.Verify();
        need(legacy.SlotCount() == 0, "legacy dispatch retains its existing path");
        runtime.Reset();
        std::cout << "PASS: legacy Magnifier output\n";
    }
    bool debugFailure = false;
    for (UINT64 index = 0; index < runtime.info->GetNumStoredMessages(); ++index)
    {
        SIZE_T size = 0;
        runtime.info->GetMessage(index, nullptr, &size);
        std::vector<unsigned char> bytes(size);
        auto* message = reinterpret_cast<D3D12_MESSAGE*>(bytes.data());
        hr(runtime.info->GetMessage(index, message, &size), "debug message");
        if (message->Severity <= D3D12_MESSAGE_SEVERITY_WARNING)
        {
            std::cerr << message->pDescription << '\n';
            debugFailure = true;
        }
    }
    need(!debugFailure, "D3D12 debug errors/warnings");
    std::cout << "PASS: admission failures and zero D3D12 debug errors/warnings\n";
    return 0;
}
catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
