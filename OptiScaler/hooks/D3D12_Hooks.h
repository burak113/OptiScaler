#pragma once
#include "SysUtils.h"
#include <d3d12.h>
#include <misc/NrdBridgeBirth_Dx12.h>

namespace FrameSurvey { struct ComputeBindings; }
struct D3D12RootRestoreSnapshot;

class D3D12Hooks
{
  private:
    inline static std::mutex hookMutex;
    inline static std::mutex agilityMutex;

    static bool RestoreDescriptorHeaps(ID3D12GraphicsCommandList* cmdList, const D3D12RootRestoreSnapshot& snapshot);
    static bool RestorePipelineState(ID3D12GraphicsCommandList* cmdList, const D3D12RootRestoreSnapshot& snapshot);
    static bool RestoreComputeRootState(ID3D12GraphicsCommandList* cmdList, const D3D12RootRestoreSnapshot& snapshot);
    static bool RestoreGraphicsRootState(ID3D12GraphicsCommandList* cmdList, const D3D12RootRestoreSnapshot& snapshot);

  public:
    static void Hook();
    static void HookAgility(HMODULE module);
    static void HookDevice(ID3D12Device* device);
    static void Unhook();
    static void SetRootSignatureTracking(bool enable);
    static bool RootSignatureTrackingEnabled();
    static void OnBridgeCommandListReset(ID3D12GraphicsCommandList*, ID3D12PipelineState* initial);
    static void OnBridgeCommandListClearState(ID3D12GraphicsCommandList*, ID3D12PipelineState* initial) noexcept;
    static void OnBridgeSetPredication(ID3D12GraphicsCommandList*, bool enabled) noexcept;
    static void OnBridgeOpaqueCommand(ID3D12GraphicsCommandList*, bool bundle) noexcept;
    static bool BridgePredicationDisabled(ID3D12GraphicsCommandList*) noexcept;
    static void OnBridgeObjectReleased(const NrdBridgeBirth::Token&) noexcept;
    static bool CanRestoreRootSignature(ID3D12GraphicsCommandList* cmdList);
    // Same-thread reason from the immediately preceding compute restore check.
    static const char* ComputeRestoreFailureReason() noexcept;
    static bool GetComputeBindingsForBridge(ID3D12GraphicsCommandList*, FrameSurvey::ComputeBindings&) noexcept;
    static bool GetGraphicsBindingsForBridge(ID3D12GraphicsCommandList*, FrameSurvey::ComputeBindings&,
                                             ID3D12PipelineState*& currentPipeline) noexcept;
    static bool CanRestoreGraphicsRootSignature(ID3D12GraphicsCommandList*) noexcept;
    static bool RestoreGraphicsRootForBridge(ID3D12GraphicsCommandList*) noexcept;
    static void HookToCommandListLate(ID3D12GraphicsCommandList* commandList);
    static void RestoreRoot(ID3D12GraphicsCommandList* cmdList);
};
