#include "FSRDPreprocessCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 2)), DescriptorTable(UAV(u0, numDescriptors = 1))"
#define FLAGS_LINEAR_DEPTH (1 << 0)
#define FLAGS_NEGATIVE_VIEW_DEPTH (1 << 1)
#define FLAGS_TITLE_LINEAR_DEPTH (1 << 2)
Texture2D<float> InDepth : register(t0);
Texture2D<float> InTitleLinearDepth : register(t1);
RWTexture2D<float> OutLinearDepth : register(u0);
cbuffer CB_Geometry : register(b0)
{
    float4x4 InvProjMatrix;
    float4 RenderSize;
    float NearPlane;
    float FarPlane;
    uint Flags;
    uint _Padding;
    float2 CurrentJitter;
    uint2 DepthBase;
    uint2 TitleDepthBase;
    uint2 _Padding2;
}
bool IsSet(uint mask) { return (Flags & mask) == mask; }
float3 GetViewSpacePos(const int2 px)
{
    // A title that publishes its own linear depth is authoritative: it knows which
    // linearisation it applied, and deriving it from hardware depth is the step that
    // has to guess that convention. This read is where the canonical signed depth is
    // produced - the floor filter, the packing shader and the denoiser's own depth
    // input all consume OutLinearDepth - so steering it steers the geometry of the
    // whole chain, and no consumer is left deriving its own.
    const bool useTitleDepth = IsSet(FLAGS_TITLE_LINEAR_DEPTH);
    float inDepth = useTitleDepth
        ? InTitleLinearDepth[px + int2(TitleDepthBase)]
        : InDepth[px + int2(DepthBase)];
    // InvProjMatrix is unjittered. Convert the current jittered raster
    // coordinate back to the matching unjittered projection ray.
    const float2 uv = (float2(px) + 0.5 - CurrentJitter) * RenderSize.zw;
    const float depthSign = IsSet(FLAGS_NEGATIVE_VIEW_DEPTH) ? -1.0f : 1.0f;
    float3 viewSpacePos = 0.0f;
    
    [branch]
    if (IsSet(FLAGS_LINEAR_DEPTH) || useTitleDepth)
    {
        inDepth = clamp(abs(inDepth), NearPlane, FarPlane);
        inDepth *= depthSign;
        // Mid-range NDC depth: the ray is rescaled to inDepth below, so the choice
        // is arbitrary except that it must avoid the inverse projection's w == 0
        // singularity, which sits at 1.0 for a standard-Z infinite far plane.
        viewSpacePos = InvProjectPosition(float3(uv, 0.5f), InvProjMatrix);
        const float safeRayZ = (viewSpacePos.z < 0.0f)
            ? min(viewSpacePos.z, -1e-6f)
            : max(viewSpacePos.z, 1e-6f);
        viewSpacePos *= inDepth / safeRayZ;
        viewSpacePos.z = inDepth;
    }
    else
    {
        viewSpacePos = InvProjectPosition(float3(uv, inDepth), InvProjMatrix);
        // Projection handedness, rather than depth direction, defines the RR sign.
        // Clamp the complete position to preserve a coherent view ray at the
        // near/far boundaries instead of replacing Z alone.
        const float signedDepth = depthSign * clamp(abs(viewSpacePos.z), NearPlane, FarPlane);
        const float safeViewZ = (viewSpacePos.z < 0.0f)
            ? min(viewSpacePos.z, -1e-6f)
            : max(viewSpacePos.z, 1e-6f);
        viewSpacePos *= signedDepth / safeViewZ;
        viewSpacePos.z = signedDepth;
    }
    
    return viewSpacePos;
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    if (any(id.xy >= uint2(RenderSize.xy))) return;
    OutLinearDepth[id.xy] = GetViewSpacePos(int2(id.xy)).z;
}
