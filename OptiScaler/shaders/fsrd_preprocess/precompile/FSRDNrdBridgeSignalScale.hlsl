// Scales owned bridge lighting RGB in place by a power of two around the RR
// dispatch. CP77 NRD-domain radiance is ~1e-4, where the AMD provider clamps
// its output to an absolute floor (~1e-5) that greys dark specular. Scaling
// by 2^k is exact in fp16 (no rounding) unless a value would overflow, so the
// inverse pass restores the inputs bit-for-bit. Alpha (hit distance) is untouched.
#define MainRS \
    "RootFlags(0), " \
    "RootConstants(num32BitConstants = 4, b0), " \
    "DescriptorTable(UAV(u0, numDescriptors = 4))"

RWTexture2D<float4> Signals[4] : register(u0);
cbuffer ScaleConstants : register(b0) { uint2 RenderSize; float Scale; uint SignalCount; }

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid.xy >= RenderSize)) return;
    [unroll] for (uint i = 0; i < 4; ++i)
    {
        if (i >= SignalCount) break;
        const float4 value = Signals[i][tid.xy];
        float3 scaled = value.rgb * Scale;
        // Saturate at the half maximum instead of storing inf; NaN stays NaN.
        scaled = float3(scaled.x > 65504.0f ? 65504.0f : scaled.x,
                        scaled.y > 65504.0f ? 65504.0f : scaled.y,
                        scaled.z > 65504.0f ? 65504.0f : scaled.z);
        Signals[i][tid.xy] = float4(scaled, value.a);
    }
}
