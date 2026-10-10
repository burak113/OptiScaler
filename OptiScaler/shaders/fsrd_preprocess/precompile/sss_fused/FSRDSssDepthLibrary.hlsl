#include "FSRDPreprocessCommon.hlsli"
#include "FSRDSkinConversion.hlsli"
Texture2D<float> InDepth : register(t1);
Texture2D<float> InTitleLinearDepth : register(t14);
bool SeedLibraryFlag(uint mask) { return (SkinDebug.w & mask) == mask; }
uint FusedSeedDepthBits(int pixelX,int pixelY)
{
    const int2 px=int2(pixelX,pixelY);
    // A title that publishes its own linear depth is authoritative: it knows which
    // linearisation it applied, and deriving it from hardware depth is the step that
    // has to guess that convention. This read is where the canonical signed depth is
    // produced - the floor filter, the packing shader and the denoiser's own depth
    // input all consume OutLinearDepth - so steering it steers the geometry of the
    // whole chain, and no consumer is left deriving its own.
    const bool useTitleDepth = SeedLibraryFlag(4096u);
    float inDepth = useTitleDepth
        ? InTitleLinearDepth[px + int2(InputBase5.xy)]
        : InDepth[px + int2(InputBase4.zw)];
    // InvProjMatrix is unjittered. Convert the current jittered raster
    // coordinate back to the matching unjittered projection ray.
    const float2 uv = (float2(px) + 0.5 - JitterOffsets.xy) * DstTexSize.zw;
    const float depthSign = SeedLibraryFlag(8u) ? -1.0f : 1.0f;
    float3 viewSpacePos = 0.0f;
    
    [branch]
    if (SeedLibraryFlag(2u) || useTitleDepth)
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
    
    return asuint(viewSpacePos.z);
}
