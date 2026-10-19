// Post-flick blotch fix (task 24 T2 c), experimental, default off) - step 1 of 2, HALF RESOLUTION.
// Keeps three things for the full-resolution apply pass:
//   lpCur   - this frame's low-pass band (rgb) and its wide level (a);
//   key     - the keyframe's band, level and depth. Refreshed from the current frame while the camera is settled
//             (Params.z), otherwise the previous key is kept, so it stays the last settled frame before a flick;
//   aux     - per-pixel age of valid history (game motion + depth agreement) and the current depth.
// The age marks the pixels where RR had no history: the post-flick blotch region.
// Cost: the band and its wide level both need a neighbourhood of the 2x2-boxed full-resolution values, so the group
// loads that neighbourhood once into groupshared memory (256 boxes for a 16x16 half-resolution tile, 4 full-resolution
// reads each) instead of 100 scattered full-resolution reads per pixel.
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), RootConstants(b0, num32BitConstants = 8), DescriptorTable(SRV(t0, numDescriptors = 6)), DescriptorTable(UAV(u0, numDescriptors = 4))"
Texture2D<float4> InColor : register(t0);      // the composite of this frame, full resolution
Texture2D<float4> InMotion : register(t1);     // xy previous-current UV (ROI UV), z previous-current linear depth
Texture2D<float> InDepth : register(t2);       // linear depth, full resolution
Texture2D<float2> InPrevAux : register(t3);    // x age, y depth (previous frame, half resolution)
Texture2D<float4> InPrevKey : register(t4);    // rgb keyframe band, a keyframe level (half resolution)
Texture2D<float2> InPrevKeyAux : register(t5); // x keyframe depth, y 1 when the key holds a frame
RWTexture2D<float4> OutCur : register(u0);     // rgb this frame's band, a its wide level
RWTexture2D<float4> OutKey : register(u1);     // rgb keyframe band, a keyframe level
RWTexture2D<float2> OutAux : register(u2);     // x age, y depth
RWTexture2D<float2> OutKeyAux : register(u3);  // x keyframe depth, y 1 when the key holds a frame
cbuffer CB_PostFlickPrepare : register(b0)
{
    float4 Size;    // full width, height, half width, half height
    float4 Params;  // x depth tolerance, y age cap, z refresh the keyframe (0/1), w previous history valid (0/1)
}
groupshared float3 sBox[16][16];
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID, uint3 group : SV_GroupID, uint index : SV_GroupIndex)
{
    const int2 half = int2(Size.z, Size.w);
    const int2 groupOrigin = int2(group.xy) * 8;
    for (uint slot = index; slot < 256u; slot += 64u)
    {
        const int2 t = int2(int(slot % 16u) - 4, int(slot / 16u) - 4);
        const int2 q = clamp(groupOrigin + t, int2(0, 0), half - 1);
        const int2 s = q * 2;
        sBox[slot % 16u][slot / 16u] = SanitizeRadiance(InColor[s].rgb + InColor[s + int2(1, 0)].rgb +
            InColor[s + int2(0, 1)].rgb + InColor[s + int2(1, 1)].rgb);
    }
    GroupMemoryBarrierWithGroupSync();
    const int2 h = int2(dispatch.xy);
    if (any(h >= half)) return;
    const int2 center = int2(dispatch.xy % 8u) + int2(4, 4);
    float3 sum = 0.0f;
    [unroll] for (int j = -2; j <= 2; ++j)
        [unroll] for (int i = -2; i <= 2; ++i)
            sum += sBox[center.x + i][center.y + j];
    const float3 low = sum * (1.0f / 100.0f);
    float3 wide = 0.0f;
    [unroll] for (int j = -4; j <= 4; ++j)
        [unroll] for (int i = -4; i <= 4; ++i)
            wide += sBox[center.x + i][center.y + j];
    const float level = max(GetLuminance(wide * (1.0f / 324.0f)), 1e-6f);
    // Age: the recursion the pre-blur probes used (motion + depth agreement), at half resolution.
    const int2 f = h * 2;
    const float4 motion = InMotion[f];
    const float depth = InDepth[f];
    float age = 0.0f;
    if (Params.w > 0.5f && all(isfinite(motion)) && isfinite(depth) && abs(depth) > 1e-5f)
    {
        const float2 pixels = motion.xy * float2(Size.x, Size.y);
        if (all(abs(pixels) < 4096.0f))
        {
            const int2 q = clamp(int2(round(float2(h) + pixels * 0.5f)), int2(0, 0), half - 1);
            const float2 prev = InPrevAux[q];
            const float expected = abs(depth + motion.z);
            if (prev.y > 0.0f && abs(prev.y - expected) <= Params.x * max(expected, 1e-3f))
                age = min(prev.x + 1.0f, Params.y);
        }
    }
    OutAux[h] = float2(age, abs(depth));
    OutCur[h] = float4(low, level);
    OutKey[h] = Params.z > 0.5f ? float4(low, level) : InPrevKey[h];
    // The keyframe carries its own depth so the apply pass can validate the recall against the surface it saw.
    OutKeyAux[h] = Params.z > 0.5f ? float2(abs(depth), 1.0f) : InPrevKeyAux[h];
}
