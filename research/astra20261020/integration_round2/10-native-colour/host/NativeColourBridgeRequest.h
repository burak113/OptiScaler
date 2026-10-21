#pragma once
// Job11 integration seam. There is intentionally no live request producer.
#include "../native/NativeColourPass_Dx12.h"
#include <array>
#include <vector>

namespace NativeColour
{
struct LobeRequest
{
    // Source must be an independently owned, already-recorded physical copy
    // BEFORE provider scaling, with exact producer lineage in evidence.
    // Its producer must independently retain all owners for those earlier copy
    // commands, even when this one-shot colour request is OFF or rejected.
    // A request reference or an existing recording ID alone is not that lease.
    Texture source, authority, support;
    Evidence evidence {};
};
struct BridgeRequest
{
    Config config {}; // enabled=false AND acknowledgeRejectedResearch=false
    uint32_t streamlineFrame = UINT32_MAX;
    // Strong producer/pool owner, not a COM-reference-only surrogate; this owns
    // the converted inputs below and prevents reuse during the retained dispatch.
    std::shared_ptr<void> convertedOwner;
    ID3D12Resource* convertedSpec = nullptr;
    ID3D12Resource* convertedDiff = nullptr;
    ID3D12Resource* convertedDepth = nullptr;
    ID3D12Resource* convertedNormals = nullptr;
    // Public order is Diffuse then Specular. Host commit descriptors use S,D.
    std::array<LobeRequest,2> lobes {};
    // Compile the delivered shader with the documented flags; no guessed/stale
    // CSO is embedded. Blob lifetime only needs to cover Prepare/PSO creation.
    std::shared_ptr<const std::vector<uint8_t>> shader;
};
}
