#include "../../../gpu_time/FSRDStageTimings_Dx12.h"
#include <dxgi1_6.h>
#include <d3d12sdklayers.h>
#include <cassert>
#include <iostream>
#include <vector>
using Microsoft::WRL::ComPtr;
static void Check(HRESULT hr)
{
    if (FAILED(hr))
    {
        std::cerr << std::hex << hr << '\n';
        std::abort();
    }
}
int main()
{
    ComPtr<ID3D12Debug> debug;
    if (SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug))))
        debug->EnableDebugLayer();
    ComPtr<ID3D12Device> device;
    Check(D3D12CreateDevice(nullptr, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)));
    D3D12_COMMAND_QUEUE_DESC queueDesc {};
    queueDesc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue;
    Check(device->CreateCommandQueue(&queueDesc, IID_PPV_ARGS(&queue)));
    ComPtr<ID3D12CommandAllocator> allocator;
    Check(device->CreateCommandAllocator(queueDesc.Type, IID_PPV_ARGS(&allocator)));
    ComPtr<ID3D12GraphicsCommandList> list;
    Check(device->CreateCommandList(0, queueDesc.Type, allocator.Get(), nullptr, IID_PPV_ARGS(&list)));
    ComPtr<ID3D12Fence> fence;
    Check(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)));
    HANDLE event = CreateEvent(nullptr, FALSE, FALSE, nullptr);
    assert(event);
    uint64_t fenceValue = 0;
    auto wait = [&]
    {
        Check(queue->Signal(fence.Get(), ++fenceValue));
        Check(fence->SetEventOnCompletion(fenceValue, event));
        assert(WaitForSingleObject(event, 30000) == WAIT_OBJECT_0);
    };
    for (int mode = 0; mode < 4; ++mode)
    {
        FSRDStageTimings timer;
        std::shared_ptr<void> lease;
        std::function<void(ID3D12CommandQueue*)> submit;
        timer.BeginFrame(device.Get(), list.Get(), true,
                         [&](auto value, auto callback)
                         {
                             lease = value;
                             submit = std::move(callback);
                             return true;
                         });
        assert(lease);
        for (unsigned i = 0; i < FSRDStageTimings::Count; ++i)
        {
            FSRDStageTimings::Scope scope(&timer, static_cast<FSRDStageTimings::Stage>(i));
        }
        timer.FinishFrame(mode != 2);
        Check(list->Close());
        if (mode != 1)
        {
            ID3D12CommandList* lists[] { list.Get() };
            submit(queue.Get());
            queue->ExecuteCommandLists(1, lists);
            if (mode == 3)
            {
                wait();
                submit(queue.Get());
                queue->ExecuteCommandLists(1, lists);
            }
            assert(timer.GetSnapshot().validMask == 0); // Cannot publish while submitted or recorded.
            wait();
        }
        Check(allocator->Reset());
        Check(list->Reset(allocator.Get(), nullptr));
        submit = {};
        lease.reset(); // Every submission fence completed and recording reset/discarded.
        const auto snapshot = timer.GetSnapshot();
        if (mode == 0)
        {
            assert(snapshot.validMask == 63 && snapshot.sequence == 1);
            for (double ms : snapshot.milliseconds)
                assert(std::isfinite(ms) && ms >= 0 && ms < 1000);
        }
        else
            assert(snapshot.validMask == 0);
    }
    Check(list->Close());
    FSRDStageTimings denied;
    denied.BeginFrame(device.Get(), list.Get(), true, [](auto, auto) { return false; });
    assert(!denied.GetSnapshot().available && denied.GetSnapshot().validMask == 0);
    ComPtr<ID3D12InfoQueue> info;
    if (SUCCEEDED(device.As(&info)))
        for (uint64_t i = 0; i < info->GetNumStoredMessages(); ++i)
        {
            SIZE_T size = 0;
            info->GetMessage(i, nullptr, &size);
            std::vector<char> bytes(size);
            auto* message = reinterpret_cast<D3D12_MESSAGE*>(bytes.data());
            Check(info->GetMessage(i, message, &size));
            assert(message->Severity != D3D12_MESSAGE_SEVERITY_ERROR &&
                   message->Severity != D3D12_MESSAGE_SEVERITY_CORRUPTION);
        }
    CloseHandle(event);
    std::cout << "GPU timestamps: completed sample, discard, failure, resubmission, unavailable tracking passed\n";
}
