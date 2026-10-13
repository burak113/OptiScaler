#pragma once
#include <d3d12.h>
#include <dxgi.h>
#include <mutex>
#include <string>
#include <span>
#include <vector>

struct NVSDK_NGX_Parameter;

// Debug-only recorder. Install from device creation ONLY when FrameSurvey=true.
// Existing hot-path detours select survey wrappers at startup; the off path
// contains no survey Dispatch/Draw/descriptor callbacks or allocations.
namespace FrameSurvey
{
struct Status
{
    bool installed = false, active = false;
    std::string phase = "off", message = "Set [FSR-RR] FrameSurvey=true and restart to enable.", folder;
};
// Shared creation registry; binding resolution is enabled only during a bounded bridge window.
struct BoundResource
{
    ID3D12Resource* resource = nullptr; // Borrowed: never retains a title resource.
    D3D12_RESOURCE_DESC description {};
    DXGI_FORMAT viewFormat = DXGI_FORMAT_UNKNOWN;
    D3D12_DESCRIPTOR_RANGE_TYPE kind = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    uint32_t descriptorOffset = UINT32_MAX, descriptorIndex = UINT32_MAX, subresource = 0;
};
using PipelineObserver = void (*)(ID3D12PipelineState*, const char* csSha256);
using ReleaseObserver = void (*)(void*);
void SetPipelineObserver(PipelineObserver) noexcept;
void SetReleaseObserver(ReleaseObserver) noexcept;
void SetBindingWindow(bool) noexcept;
bool BindingWindow() noexcept;
bool ResolveComputeTable(ID3D12GraphicsCommandList*, UINT rootParameter, std::vector<BoundResource>& out) noexcept;
class ScopedInternal
{
    bool previous_;
  public:
    ScopedInternal() noexcept;
    ~ScopedInternal();
    ScopedInternal(const ScopedInternal&) = delete;
    ScopedInternal& operator=(const ScopedInternal&) = delete;
};
bool Enabled() noexcept;
// Called at device hook time when FrameSurvey=true: keeps creation metadata from the title's load phase.
void BeginCreationTracking() noexcept;
// Comma-separated shader SHA-256 prefixes (FrameSurveyPassHashes); matching dispatches save their outputs.
void SetPassHashes(const std::string& list) noexcept;
bool Internal() noexcept;
bool Install(ID3D12Device*, ID3D12GraphicsCommandList*) noexcept;
void Shutdown() noexcept;
Status GetStatus();
bool Request(uint32_t renderWidth, uint32_t renderHeight) noexcept;
void Present(IDXGISwapChain*, UINT flags) noexcept;
void Evaluate(ID3D12GraphicsCommandList*, unsigned feature, const NVSDK_NGX_Parameter*) noexcept;
void TitleTag(ID3D12GraphicsCommandList*, const char* name, ID3D12Resource*, uint32_t state,
              uint32_t x, uint32_t y, uint32_t width, uint32_t height) noexcept;

void ResourceCreated(ID3D12Resource*, D3D12_RESOURCE_STATES, ID3D12Heap* heap = nullptr, uint64_t offset = 0) noexcept;
void RootCreated(ID3D12RootSignature*, const void* bytes, size_t length) noexcept;
void PipelineCreated(ID3D12PipelineState*, const D3D12_COMPUTE_PIPELINE_STATE_DESC&) noexcept;
void PipelineCreated(ID3D12PipelineState*, const D3D12_GRAPHICS_PIPELINE_STATE_DESC&) noexcept;
void PipelineCreated(ID3D12PipelineState*, const D3D12_PIPELINE_STATE_STREAM_DESC&) noexcept;
void Released(void*) noexcept;
void HeapCreated(ID3D12Device*, ID3D12DescriptorHeap*) noexcept;
void View(ID3D12Resource*, D3D12_CPU_DESCRIPTOR_HANDLE, const D3D12_SHADER_RESOURCE_VIEW_DESC*) noexcept;
void View(ID3D12Resource*, D3D12_CPU_DESCRIPTOR_HANDLE, const D3D12_UNORDERED_ACCESS_VIEW_DESC*) noexcept;
void View(ID3D12Resource*, D3D12_CPU_DESCRIPTOR_HANDLE, const D3D12_RENDER_TARGET_VIEW_DESC*) noexcept;
void CopyDescriptors(ID3D12Device*, UINT, const D3D12_CPU_DESCRIPTOR_HANDLE*, const UINT*,
                     UINT, const D3D12_CPU_DESCRIPTOR_HANDLE*, const UINT*, D3D12_DESCRIPTOR_HEAP_TYPE) noexcept;
void Reset(ID3D12GraphicsCommandList*, ID3D12PipelineState*) noexcept;
void Close(ID3D12GraphicsCommandList*, HRESULT) noexcept;
void SetPipeline(ID3D12GraphicsCommandList*, ID3D12PipelineState*) noexcept;
void RootBinding(ID3D12GraphicsCommandList*, bool graphics, ID3D12RootSignature*) noexcept;
void DescriptorHeaps(ID3D12GraphicsCommandList*, UINT, ID3D12DescriptorHeap* const*) noexcept;
void RootView(ID3D12GraphicsCommandList*, bool graphics, UINT index, UINT kind, D3D12_GPU_VIRTUAL_ADDRESS) noexcept;
void Table(ID3D12GraphicsCommandList*, bool graphics, UINT index, D3D12_GPU_DESCRIPTOR_HANDLE) noexcept;
void RenderTargets(ID3D12GraphicsCommandList*, UINT, const D3D12_CPU_DESCRIPTOR_HANDLE*, BOOL) noexcept;
void Barrier(ID3D12GraphicsCommandList*, UINT, const D3D12_RESOURCE_BARRIER*) noexcept;
void Event(ID3D12GraphicsCommandList*, UINT metadata, const void*, UINT size, int kind) noexcept;
void Pass(ID3D12GraphicsCommandList*, const char* kind, std::span<const uint64_t> arguments) noexcept;
void SnapshotWrites(ID3D12GraphicsCommandList*) noexcept;
void Submit(ID3D12CommandQueue*, UINT, ID3D12CommandList* const*) noexcept;
std::mutex& SubmissionMutex();
}
