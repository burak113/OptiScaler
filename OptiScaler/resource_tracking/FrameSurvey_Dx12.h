#pragma once
#include <d3d12.h>
#include <dxgi.h>
#include <mutex>
#include <string>
#include <span>
#include <vector>
#include <utility>

struct NVSDK_NGX_Parameter;

// Recorder and borrowed NRD creation registry, selected by startup-only detours.
// With both FrameSurvey and the NRD bridge off, there are no new callbacks or allocations.
// Bridge root/table mirrors are confined to bounded validation windows.
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
struct BoundConstantBuffer
{
    ID3D12Resource* resource = nullptr; // Borrowed, valid while the caller holds the title lifetime borrow gate.
    D3D12_GPU_VIRTUAL_ADDRESS address = 0;
    uint64_t offset = 0, size = 0;
    uint64_t resourceGeneration = 0;
    ID3D12DescriptorHeap* descriptorHeap = nullptr; // Borrowed; table CBVs preserve their native volatile slot.
    D3D12_GPU_DESCRIPTOR_HANDLE descriptor {};
};
// Native Consumer binding only. Buffer identity/size metadata is diagnostic, never an admission requirement.
struct BoundConstantBinding
{
    ID3D12RootSignature* root = nullptr;
    UINT rootParameter = UINT_MAX;
    D3D12_GPU_VIRTUAL_ADDRESS address = 0; // Direct root CBV; table bindings deliberately have no inferred address.
    ID3D12DescriptorHeap* descriptorHeap = nullptr;
    D3D12_GPU_DESCRIPTOR_HANDLE descriptor {};
    uint64_t tableBase = 0;
};
struct ConstantBufferDiagnostic
{
    const char* reason = "unavailable";
    UINT rootParameter = UINT_MAX;
    bool table = false;
    uint64_t address = 0, declaredBytes = 0, remainingBytes = 0, resourceBase = 0;
    uint64_t tableBase = 0, descriptorCpu = 0, trackedBuffers = 0;
    unsigned intervalMatches = 0;
};
struct ComputeTableRequest
{
    D3D12_DESCRIPTOR_RANGE_TYPE kind = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    UINT descriptorOffset = UINT_MAX, shaderRegister = UINT_MAX, registerSpace = UINT_MAX;
};
struct ComputeRootView
{
    UINT parameter = UINT_MAX;
    D3D12_DESCRIPTOR_RANGE_TYPE kind = D3D12_DESCRIPTOR_RANGE_TYPE_CBV;
    D3D12_GPU_VIRTUAL_ADDRESS address = 0;
};
struct ComputeBindings
{
    ID3D12RootSignature* root = nullptr;
    std::vector<ID3D12DescriptorHeap*> heaps;
    std::vector<std::pair<UINT,D3D12_GPU_DESCRIPTOR_HANDLE>> tables;
    std::vector<ComputeRootView> views;
};
bool SeedComputeBindings(ID3D12GraphicsCommandList*, const ComputeBindings&) noexcept;
using PipelineObserver = void (*)(ID3D12PipelineState*, const char* csSha256);
using ReleaseObserver = void (*)(void*);
void SetPipelineObserver(PipelineObserver) noexcept;
void SetReleaseObserver(ReleaseObserver) noexcept;
void SetBindingWindow(bool) noexcept;
bool BindingWindow() noexcept;
bool MetadataHealthy() noexcept;
// Native observer failure latch; safe inside injection/recorder scopes, no lifecycle locks.
void MetadataHookFailed(const char* reason) noexcept;
// Proves the current compute table offset maps uniquely to the exact shader register/space.
bool ComputeTableBindingMatches(ID3D12GraphicsCommandList*, UINT rootParameter, D3D12_DESCRIPTOR_RANGE_TYPE kind,
                                UINT descriptorOffset, UINT shaderRegister, UINT registerSpace) noexcept;
bool ResolveComputeTable(ID3D12GraphicsCommandList*, UINT rootParameter, std::vector<BoundResource>& out) noexcept;
// At most eight exact requests; proves only those slots, including valid large/unbounded tables.
bool ResolveComputeBindings(ID3D12GraphicsCommandList*, UINT rootParameter,
                            std::span<const ComputeTableRequest>, std::vector<BoundResource>& out) noexcept;
// Resolves one current root/table CBV by its exact b-register and space, without retaining or mapping it.
bool ResolveComputeConstantBuffer(ID3D12GraphicsCommandList*, UINT shaderRegister, UINT registerSpace,
                                  uint64_t minimumBytes, BoundConstantBuffer& out, ConstantBufferDiagnostic* diagnostic = nullptr) noexcept;
// Resolve b-register from native root/table arguments without consulting resource or CBV creation records.
// The caller holds the title lifetime borrow gate. The explicit snapshot overload is window-independent.
bool ResolveComputeConstantBinding(ID3D12GraphicsCommandList*, UINT shaderRegister, UINT registerSpace,
                                   BoundConstantBinding&, ConstantBufferDiagnostic* diagnostic = nullptr) noexcept;
bool ResolveComputeConstantBinding(const ComputeBindings&, UINT shaderRegister, UINT registerSpace,
                                   BoundConstantBinding&, ConstantBufferDiagnostic* diagnostic = nullptr) noexcept;
bool ValidateComputeConstantBinding(const ComputeBindings&, UINT shaderRegister, UINT registerSpace,
                                    const BoundConstantBinding&) noexcept;
// Window-independent generation validation; the caller holds the physical title lifetime borrow gate.
bool ValidateBorrowedConstantBuffer(const BoundConstantBuffer&) noexcept;
class ScopedInternal
{
    bool previous_;
  public:
    ScopedInternal() noexcept;
    ~ScopedInternal();
    ScopedInternal(const ScopedInternal&) = delete;
    ScopedInternal& operator=(const ScopedInternal&) = delete;
};
// Ordinary upscaler/RR recording suppresses metadata while preserving title-reference Release protection.
class ScopedRecording
{
    ScopedInternal internal_;
  public:
    ScopedRecording() noexcept;
    ~ScopedRecording();
    ScopedRecording(const ScopedRecording&) = delete;
    ScopedRecording& operator=(const ScopedRecording&) = delete;
};
bool OwnedRelease() noexcept;
bool Enabled() noexcept;
// Called at device hook time for FrameSurvey or the NRD bridge, before title pipeline creation.
void BeginCreationTracking(bool recorder = true) noexcept;
// Comma-separated shader SHA-256 prefixes (FrameSurveyPassHashes); matching dispatches save their outputs.
void SetPassHashes(const std::string& list) noexcept;
bool Internal() noexcept;
bool Install(ID3D12Device*, ID3D12GraphicsCommandList*, bool recorder = true) noexcept;
void Shutdown() noexcept;
Status GetStatus();
bool Request(uint32_t renderWidth, uint32_t renderHeight) noexcept;
void Present(IDXGISwapChain*, UINT flags) noexcept;
void Evaluate(ID3D12GraphicsCommandList*, unsigned feature, const NVSDK_NGX_Parameter*) noexcept;
void TitleTag(ID3D12GraphicsCommandList*, const char* name, ID3D12Resource*, uint32_t state,
              uint32_t x, uint32_t y, uint32_t width, uint32_t height) noexcept;

void ResourceCreated(ID3D12Resource*, D3D12_RESOURCE_STATES, ID3D12Heap* heap = nullptr, uint64_t offset = 0) noexcept;
// Enhanced layouts are not legacy D3D12_RESOURCE_STATES; keep initial state unproven.
void ResourceCreatedWithLayout(ID3D12Resource*, D3D12_BARRIER_LAYOUT, ID3D12Heap* heap = nullptr, uint64_t offset = 0) noexcept;
void RootCreated(ID3D12RootSignature*, const void* bytes, size_t length) noexcept;
void PipelineCreated(ID3D12PipelineState*, const D3D12_COMPUTE_PIPELINE_STATE_DESC&) noexcept;
void PipelineCreated(ID3D12PipelineState*, const D3D12_GRAPHICS_PIPELINE_STATE_DESC&) noexcept;
void PipelineCreated(ID3D12PipelineState*, const D3D12_PIPELINE_STATE_STREAM_DESC&) noexcept;
void Released(void*) noexcept;
void HeapCreated(ID3D12Device*, ID3D12DescriptorHeap*) noexcept;
void View(D3D12_CPU_DESCRIPTOR_HANDLE, const D3D12_CONSTANT_BUFFER_VIEW_DESC*) noexcept;
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
