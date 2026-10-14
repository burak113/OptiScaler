#ifndef FSRD_NRD_MOTION_COMMON
#define FSRD_NRD_MOTION_COMMON
float4 ConvertNrdMotion(uint2 p, uint2 renderSize, float2 rawMotion, float depth, uint previousValid,
                       Texture2D<float> previousDepthTexture, float2 motionScale, float2 jitterDeltaUv)
{
    const float2 safeMotion = float2(isfinite(rawMotion.x) ? rawMotion.x : 0.0f,
                                    isfinite(rawMotion.y) ? rawMotion.y : 0.0f);
    const float2 motion = safeMotion * motionScale + jitterDeltaUv;
    const float2 previousPixel = float2(p) + 0.5f + motion * float2(renderSize);
    float deltaDepth = 0.0f;
    if (previousValid != 0u && all(isfinite(previousPixel)) &&
        all(previousPixel >= 0.0f) && all(previousPixel < float2(renderSize)))
    {
        const float previousDepth = previousDepthTexture[int2(floor(previousPixel))];
        if (isfinite(previousDepth)) deltaDepth = clamp(previousDepth - depth, -65504.0f, 65504.0f);
    }
    return float4(clamp(motion, -65504.0f, 65504.0f), deltaDepth, 1.0f);
}
#endif
