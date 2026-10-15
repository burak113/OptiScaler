#ifndef FSRD_NRD_MOTION_COMMON
#define FSRD_NRD_MOTION_COMMON
#ifdef FSRD_NRD_NATIVE_MOTION
#include "FSRDNrdNativeTemporal.hlsli"
#endif
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
#ifdef FSRD_NRD_NATIVE_MOTION
float3 ReconstructNativeNrdPosition(float2 uv, float positiveDepth, float3 right, float3 up,
                                    float3 forward, float orthographic)
{
    const float2 n = 2.0f * uv - 1.0f;
    // Exact title Temporal branches, including its downward screen Y convention.
    return orthographic == 0.0f ? (n.x * right - n.y * up + forward) * positiveDepth
                                : n.x * right - n.y * up + forward * positiveDepth;
}

bool TryNativeNrdDepthDelta(uint2 p, uint2 renderSize, float3 rawMotion, float signedDepth,
                            float nativeViewDepth, uint previousValid,
                            NrdNativeTemporalData native, out float deltaDepth)
{
    deltaDepth = 0.0f;
    if (previousValid == 0u || native.signature != NrdNativeTemporalSignature ||
        native.version != NrdNativeTemporalVersion || any(native.sourceOrigin != int2(0, 0)) ||
        any(native.rectSize != renderSize) || any(native.previousRectSize != float2(renderSize)) ||
        !all(isfinite(native.inverseRectSize)) || any(native.inverseRectSize <= 0.0f) ||
        // Four float ulps allow a rounded uploaded reciprocal; no geometric
        // previous-basis identity or depth equivalence is assumed here.
        any(abs(native.inverseRectSize * float2(renderSize) - 1.0f) > 4.76837158203125e-7f) ||
        !isfinite(native.orthographic) || !all(isfinite(native.motionScale.xyz)) ||
        !all(isfinite(native.previousViewDepthRow)) || !all(isfinite(rawMotion)) ||
        !isfinite(signedDepth) || !isfinite(nativeViewDepth) || nativeViewDepth <= 0.0f ||
        // R32 PrePass writes max(abs(rawZ),1e-6); conversion writes signed
        // clamp(abs(rawZ),near,far). Exact equality admits only the same finite,
        // unclipped current surface. CPU provenance separately attests the views.
        abs(signedDepth) != nativeViewDepth) return false;

    const float2 uv = (float2(p) + 0.5f) * native.inverseRectSize;
    const float3 motion = rawMotion * native.motionScale.xyz;
    if (!all(isfinite(motion))) return false;
    float3 previousPosition;
    if (native.motionSpace != 0u || native.motionScale.z == 0.0f)
    {
        if (!all(isfinite(native.currentRight.xyz)) || !all(isfinite(native.currentUp.xyz)) ||
            !all(isfinite(native.currentForward.xyz))) return false;
        previousPosition = ReconstructNativeNrdPosition(uv, nativeViewDepth,
            native.currentRight.xyz, native.currentUp.xyz, native.currentForward.xyz, native.orthographic);
        if (native.motionSpace != 0u)
        {
            previousPosition += motion;
            if (!all(isfinite(native.previousClipX)) || !all(isfinite(native.previousClipY)) ||
                !all(isfinite(native.previousClipW))) return false;
            const float4 position = float4(previousPosition, 1.0f);
            const float clipW = dot(native.previousClipW, position);
            if (!isfinite(clipW) || clipW <= 0.0f) return false;
            const float2 previousUv = float2(0.5f, 0.5f) +
                float2(0.5f * dot(native.previousClipX, position),
                      -0.5f * dot(native.previousClipY, position)) / clipW;
            if (!all(isfinite(previousUv))) return false;
        }
    }
    else
    {
        if (!all(isfinite(native.previousRight.xyz)) || !all(isfinite(native.previousUp.xyz)) ||
            !all(isfinite(native.previousForward.xyz)) || !all(isfinite(native.cameraDelta.xyz))) return false;
        const float2 previousUv = uv + motion.xy;
        const float previousInputDepth = nativeViewDepth + motion.z;
        if (!all(isfinite(previousUv)) || !isfinite(previousInputDepth)) return false;
        previousPosition = ReconstructNativeNrdPosition(previousUv, previousInputDepth,
            native.previousRight.xyz, native.previousUp.xyz, native.previousForward.xyz, native.orthographic)
            + native.cameraDelta.xyz;
    }
    if (!all(isfinite(previousPosition))) return false;
    const float previousViewDepth = dot(native.previousViewDepthRow, float4(previousPosition, 1.0f));
    const float candidate = (signedDepth < 0.0f ? -1.0f : 1.0f) * (previousViewDepth - nativeViewDepth);
    if (!isfinite(previousViewDepth) || previousViewDepth <= 0.0f || !isfinite(candidate)) return false;
    deltaDepth = clamp(candidate, -65504.0f, 65504.0f);
    return true;
}
#endif
#endif
