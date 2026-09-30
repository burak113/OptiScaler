The optional callback can support a future isolated immutable-constant-storage contrast, subject to provider invocation/ABI readiness. Its arguments are constant data and byte count; it has no userdata, context or effect ID. The returned struct contains resource+uint64 handle. In checked-in DX12 source, handle is a rootCBV GPU virtual address and resource is ignored; allocations are256-byte aligned.

The local callback registry is module-static and sticky: a null descriptor does not clear previous registration. Use fresh process per arm and retain allocator data/resources through allGPUfences, context teardown and provider unload. Make allocation/logging thread-safe; the five public headers do not guarantee caller thread, synchronous-only timing, ownership transfer, release notification or recoverable failure behavior. Source inline calls do not prove private signed-provider behavior.

Current FSRD production supplies backend+version descriptors and NULL host memCb. Repository production search found zero callback uses. Custom CB registration can leave all ordinary guides/flags and resource/heap callbacks unchanged; it does not replace private descriptor/SRV storage or upstream CPU constant staging.

If a matched batch difference disappears with verified immutable CB allocations, that supports an allocation-path contribution, not a sole default-ring root cause. Persistence does not exonerate upstream/uncovered constants or descriptor/history state. Zero callback invocation establishes no contrast. No game quality, stain cause or production-fix claim.

D3D12 address semantics: [SetComputeRootConstantBufferView](https://learn.microsoft.com/en-us/windows/win32/api/d3d12/nf-d3d12-id3d12graphicscommandlist-setcomputerootconstantbufferview). Resource lifetime/reuse: [Fence-Based Resource Management](https://learn.microsoft.com/en-us/windows/win32/direct3d12/fence-based-resource-management).

Read-only source review only:0implementation edits,0callback prototypes,0builds,0native/GPU jobs. Five API headers and provider match earlier frozen pins; all13reviewed source/provider pins match before/after.
