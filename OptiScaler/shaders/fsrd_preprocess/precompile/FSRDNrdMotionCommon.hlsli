#ifndef FSRD_NRD_MOTION_COMMON
#define FSRD_NRD_MOTION_COMMON
float4 ConvertNrdMotion(uint2 p, uint2 renderSize, float2 rawMotion, float depth, uint previousValid,
                       Texture2D<float> previousDepthTexture, float2 motionScale, float2 jitterDeltaUv,
                       uint cameraProjectedDepthDelta, float4x4 inverseProjection,
                       float4 previousViewDepthRow, float2 currentJitterUv)
{
    const float2 safeMotion = float2(isfinite(rawMotion.x) ? rawMotion.x : 0.0f,
                                    isfinite(rawMotion.y) ? rawMotion.y : 0.0f);
    const float2 motion = safeMotion * motionScale + jitterDeltaUv;
    const float2 previousPixel = float2(p) + 0.5f + motion * float2(renderSize);
    float deltaDepth = 0.0f;
    [branch] if (previousValid != 0u && cameraProjectedDepthDelta != 0u)
    {
        // Current texel stores the surface sampled at (pixel center - current jitter).
        // Jitter alters XY raster correspondence; it does not alter either camera's signed Z.
        const float2 uv = (float2(p) + 0.5f) / float2(renderSize) - currentJitterUv;
        const float2 ndc = float2(2.0f * uv.x - 1.0f, 2.0f * (1.0f - uv.y) - 1.0f);
        const float4 ray = mul(inverseProjection, float4(ndc, 0.5f, 1.0f));
        if (all(isfinite(ray.xyz)) && abs(ray.z) > 1e-8f)
        {
            const float3 currentViewPosition = ray.xyz * (depth / ray.z);
            const float previousDepth = dot(previousViewDepthRow, float4(currentViewPosition, 1.0f));
            const float candidate = previousDepth - depth;
            if (isfinite(candidate)) deltaDepth = clamp(candidate, -65504.0f, 65504.0f);
        }
        // Camera-only mode intentionally has no old-visibility/object-Z fallback.
    }
    else if (previousValid != 0u && all(isfinite(previousPixel)) &&
        all(previousPixel >= 0.0f) && all(previousPixel < float2(renderSize)))
    {
        const float previousDepth = previousDepthTexture[int2(floor(previousPixel))];
        if (isfinite(previousDepth)) deltaDepth = clamp(previousDepth - depth, -65504.0f, 65504.0f);
    }
    return float4(clamp(motion, -65504.0f, 65504.0f), deltaDepth, 1.0f);
}
#endif
