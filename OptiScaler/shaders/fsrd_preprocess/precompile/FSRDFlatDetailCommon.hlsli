#ifndef FSRD_FLAT_DETAIL_COMMON
#define FSRD_FLAT_DETAIL_COMMON
#include "FSRDPreprocessCommon.hlsli"
float3 SanitizeRadiance(float3 c)
{
    return float3(isfinite(c.x) ? clamp(c.x, 0.0f, 65500.0f) : 0.0f,
                  isfinite(c.y) ? clamp(c.y, 0.0f, 65500.0f) : 0.0f,
                  isfinite(c.z) ? clamp(c.z, 0.0f, 65500.0f) : 0.0f);
}
float DepthDerivative(float left, float center, float right)
{
    const float a = center - left, b = right - center;
    return isfinite(a) && isfinite(b) ? (abs(a) < abs(b) ? a : b) : 0.0f;
}
uint2 FlatPack(float4 v)
{
    const uint4 h = f32tof16(clamp(v, -65504.0f, 65504.0f));
    return uint2(h.x | (h.y << 16), h.z | (h.w << 16));
}
float4 FlatUnpack(uint2 v)
{
    return f16tof32(uint4(v.x & 65535u, v.x >> 16, v.y & 65535u, v.y >> 16));
}
float FlatSurfaceWeight(float z, float tapZ, float2 gradient, float2 offset, float3 n, float3 tapN)
{
    const float prediction = clamp(dot(gradient, offset), -0.25f * abs(z), 0.25f * abs(z));
    const float depth = saturate(1.0f - abs(z + prediction - tapZ) / max(0.01f * abs(z), 1e-3f));
    const float normal = saturate((dot(n, tapN) - 0.9f) * 10.0f);
    return isfinite(z) && isfinite(tapZ) && z * tapZ > 0.0f ? depth * depth * normal * normal : 0.0f;
}
#endif
