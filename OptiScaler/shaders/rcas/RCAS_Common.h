#pragma once
#pragma once

#include "SysUtils.h"
#include <d3dcompiler.h>

struct RcasConstants
{
    float Sharpness;

    float MvScaleX;
    float MvScaleY;

    float CameraNear;
    float CameraFar;
};

static std::string daSharpenCode = R"(
#ifdef VK_MODE
cbuffer Params : register(b0, space0)
#else
cbuffer Params : register(b0)
#endif
{
    // Base sharpen amount
    float Sharpness;

    // Depth format
    int DepthIsLinear; // 0 = device/nonlinear, 1 = already linear
    int DepthIsReversed; // 0 = normal Z, 1 = reversed Z

    // Depth rejection
    float DepthScale;
    float DepthBias;

    // Nonlinear depth only.
    // These coefficients must be generated for the non-reversed depth convention.
    // If DepthIsReversed != 0, reversed handling is applied in shader.
    float DepthLinearA;
    float DepthLinearB;
    float DepthLinearC;

    // Motion adaptive
    int DynamicSharpenEnabled;
    int DisplaySizeMV;
    int Debug; // 0=off, 1=motion, 2=depth, 3=combined

    float MotionSharpness; // usually negative
    float MotionTextureScale; // explicit mapping from output pixel space to motion texel space
    float MvScaleX;
    float MvScaleY;
    float MotionThreshold;
    float MotionScaleLimit;

    // Depth mapping from output pixel space to depth texel space
    float DepthTextureScale;

    // Output control
    int ClampOutput;

    // Dimensions
    int DisplayWidth;
    int DisplayHeight;
    int MotionWidth;
    int MotionHeight;
    int DepthWidth;
    int DepthHeight;
};

#ifdef VK_MODE
[[vk::binding(1, 0)]]
#endif
Texture2D<float4> Source : register(t0);

#ifdef VK_MODE
[[vk::binding(2, 0)]]
#endif
Texture2D<float2> Motion : register(t1);

#ifdef VK_MODE
[[vk::binding(3, 0)]]
#endif
Texture2D<float> DepthTex : register(t2);

#ifdef VK_MODE
[[vk::binding(4, 0)]]
#endif
RWTexture2D<float4> Dest : register(u0);

static const float3 kLumaCoeff = float3(0.2126, 0.7152, 0.0722);

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

int2 ClampCoord(int2 p)
{
    return int2(clamp(p.x, 0, DisplayWidth - 1), clamp(p.y, 0, DisplayHeight - 1));
}

int2 ClampMotionCoord(int2 p)
{
    return int2(clamp(p.x, 0, MotionWidth - 1), clamp(p.y, 0, MotionHeight - 1));
}

int2 ClampDepthCoord(int2 p)
{
    return int2(clamp(p.x, 0, DepthWidth - 1), clamp(p.y, 0, DepthHeight - 1));
}

float3 SafeLoadColor(int2 p)
{
    return Source.Load(int3(ClampCoord(p), 0)).rgb;
}

float SafeLoadRawDepthAtCoord(int2 p)
{
    return DepthTex.Load(int3(ClampDepthCoord(p), 0)).r;
}

float2 SafeLoadMotion(int2 p)
{
    return Motion.Load(int3(ClampMotionCoord(p), 0)).rg;
}

float LinearizeDepth(float rawDepth)
{
    float z = rawDepth;

    if (DepthIsLinear > 0)
    {
        if (DepthIsReversed > 0)
            z = 1.0 - z;

        return z;
    }

    if (DepthIsReversed > 0)
    {
        float nearPlane = DepthLinearB - DepthLinearC;
        return DepthLinearA / max(nearPlane + z * DepthLinearC, 1e-6);
    }

    return DepthLinearA / max(DepthLinearB - z * DepthLinearC, 1e-6);
}

float SafeLoadDepthLinearFromOutputPixel(int2 pixelCoord)
{
    float2 df = (float2(pixelCoord) + 0.5) * DepthTextureScale;
    int2 depthCoord = int2(df);
    return LinearizeDepth(SafeLoadRawDepthAtCoord(depthCoord));
}

float DistanceSharpnessBoost(float linearDepth)
{
    // Works best if linearDepth is view-space-ish positive distance.
    // log2 keeps the boost gradual and avoids overboosting very far depth.
    float d = max(linearDepth, 1e-4);
    float boost = saturate((log2(d) - 4.0) * 0.15);

    // 1.0 near, up to 1.35 far
    return lerp(1.0, 1.35, boost);
}

float2 EstimateDepthGradientFromTaps(
    float centerDepth,
    float depthUp,
    float depthLeft,
    float depthRight,
    float depthDown)
{
    float gxF = depthRight - centerDepth;
    float gxB = centerDepth - depthLeft;
    float gyF = depthDown - centerDepth;
    float gyB = centerDepth - depthUp;

    // Prefer the smoother local derivative.
    float gx = abs(gxF) < abs(gxB) ? gxF : gxB;
    float gy = abs(gyF) < abs(gyB) ? gyF : gyB;

    float maxGrad = abs(centerDepth) * 0.05;
    return clamp(float2(gx, gy), -maxGrad, maxGrad);
}

float DepthWeightGrad(float centerDepth, float sampleDepth, float2 gradient, int2 offset)
{
    float predicted = centerDepth + dot(float2(offset), gradient);
    float residual = abs(sampleDepth - predicted);

    residual /= max(abs(centerDepth), 1e-4);

    // More dead-zone before rejection starts.
    residual = max(residual - DepthBias - 1e-5, 0.0);

    // Softer falloff.
    float w = saturate(1.0 - residual * DepthScale);

    // Do not fully collapse taps unless it is a strong depth break.
    return lerp(0.65, 1.0, w);
}

float ComputeAdaptiveSharpness(int2 pixelCoord)
{
    float setSharpness = Sharpness;

    if (DynamicSharpenEnabled > 0)
    {
        float2 mv;

        if (DisplaySizeMV > 0)
        {
            mv = SafeLoadMotion(pixelCoord);
        }
        else
        {
            float2 mvf = (float2(pixelCoord) + 0.5) * MotionTextureScale;
            int2 mvCoord = int2(mvf);
            mv = SafeLoadMotion(mvCoord);
        }

        float motion = max(abs(mv.x * MvScaleX), abs(mv.y * MvScaleY));
        float add = 0.0;

        if (motion > MotionThreshold)
        {
            float denom = max(MotionScaleLimit - MotionThreshold, 1e-6);
            add = ((motion - MotionThreshold) / denom) * MotionSharpness;
        }

        add = clamp(add, min(0.0, MotionSharpness), max(0.0, MotionSharpness));
        setSharpness += add;
    }

    return clamp(setSharpness, 0.0, 2.0);
}

float3 ApplyDebugTint(
    float3 color,
    float baseSharpness,
    float adaptiveSharpness,
    float edgeSharpness,
    float finalSharpness,
    float distanceBoost,
    int debugMode)
{
    float motionBoost = max(adaptiveSharpness - baseSharpness, 0.0);
    float motionReduce = max(baseSharpness - adaptiveSharpness, 0.0);

    // Blue means edge-based sharpen reduction only.
    float edgeReduce = max(adaptiveSharpness - edgeSharpness, 0.0);

    float distanceIncrease = max(distanceBoost - 1.0, 0.0);

    if (debugMode > 0)
    {
        color.r *= 1.0 + 12.0 * motionBoost;
        color.r += 0.35 * distanceIncrease;

        color.g *= 1.0 + 12.0 * motionReduce;
        color.b *= 1.0 + 12.0 * edgeReduce;
    }

    return color;
}

float ComputeEdgeFactorFromTaps(
    float centerLuma,
    float centerDepth,
    float2 depthGrad,
    float lumaUp,
    float lumaLeft,
    float lumaRight,
    float lumaDown,
    float depthUp,
    float depthLeft,
    float depthRight,
    float depthDown)
{
    float lumaSum = 0.0;
    lumaSum += abs(lumaUp - centerLuma);
    lumaSum += abs(lumaLeft - centerLuma);
    lumaSum += abs(lumaRight - centerLuma);
    lumaSum += abs(lumaDown - centerLuma);

    float depthEdge = 1.0;
    depthEdge = min(depthEdge, DepthWeightGrad(centerDepth, depthUp, depthGrad, int2(0, -1)));
    depthEdge = min(depthEdge, DepthWeightGrad(centerDepth, depthLeft, depthGrad, int2(-1, 0)));
    depthEdge = min(depthEdge, DepthWeightGrad(centerDepth, depthRight, depthGrad, int2(1, 0)));
    depthEdge = min(depthEdge, DepthWeightGrad(centerDepth, depthDown, depthGrad, int2(0, 1)));

    // Average visible brightness difference around this pixel.
    float lumaAvg = lumaSum * 0.25;

    // 0 = luma does not confirm the depth edge
    // 1 = luma strongly confirms the depth edge
    float lumaConfirm = saturate((lumaAvg - 0.02) * 18.0);

    // Luma is confirmation, not an edge source.
    // Even without luma confirmation, keep some depth protection.
    float depthTrust = lerp(0.15, 1.0, lumaConfirm);

    return lerp(1.0, depthEdge, depthTrust);
}

float ComputeLocalLumaRangeFromTaps(
    float centerLuma,
    float lumaUp,
    float lumaLeft,
    float lumaRight,
    float lumaDown)
{
    float lMin = centerLuma;
    float lMax = centerLuma;

    lMin = min(lMin, lumaUp);
    lMax = max(lMax, lumaUp);

    lMin = min(lMin, lumaLeft);
    lMax = max(lMax, lumaLeft);

    lMin = min(lMin, lumaRight);
    lMax = max(lMax, lumaRight);

    lMin = min(lMin, lumaDown);
    lMax = max(lMax, lumaDown);

    return lMax - lMin;
}

float Max3(float3 v)
{
    return max(v.r, max(v.g, v.b));
}

// -----------------------------------------------------------------------------
// Main
// -----------------------------------------------------------------------------

[numthreads(16, 16, 1)]
void CSMain(uint3 DTid : SV_DispatchThreadID)
{
    int2 p = int2(DTid.xy);

    if (p.x >= DisplayWidth || p.y >= DisplayHeight)
        return;

    float3 c = SafeLoadColor(p);
    float adaptiveSharpness = ComputeAdaptiveSharpness(p);

    if (adaptiveSharpness <= 0.0)
    {
        float3 outColor = c;

        if (Debug > 0)
            outColor = ApplyDebugTint(outColor, Sharpness, adaptiveSharpness, adaptiveSharpness, adaptiveSharpness, 1.0, Debug);

        if (ClampOutput > 0)
            outColor = saturate(outColor);

        Dest[p] = float4(outColor, 1.0);
        return;
    }

    // -------------------------------------------------------------------------
    // Shared center/cross data
    // -------------------------------------------------------------------------

    float centerDepth = SafeLoadDepthLinearFromOutputPixel(p);
    float centerLuma = dot(c, kLumaCoeff);

    int2 pUp = p + int2(0, -1);
    int2 pLeft = p + int2(-1, 0);
    int2 pRight = p + int2(1, 0);
    int2 pDown = p + int2(0, 1);

    // Cached cross-neighbor colors. These replace repeated loads in edge/luma/RCAS paths.
    float3 colorUp = SafeLoadColor(pUp);
    float3 colorLeft = SafeLoadColor(pLeft);
    float3 colorRight = SafeLoadColor(pRight);
    float3 colorDown = SafeLoadColor(pDown);

    // Cached cross-neighbor depths. These replace repeated depth loads and linearization.
    float depthUp = SafeLoadDepthLinearFromOutputPixel(pUp);
    float depthLeft = SafeLoadDepthLinearFromOutputPixel(pLeft);
    float depthRight = SafeLoadDepthLinearFromOutputPixel(pRight);
    float depthDown = SafeLoadDepthLinearFromOutputPixel(pDown);

    // Cached lumas derived from cached colors.
    float lumaUp = dot(colorUp, kLumaCoeff);
    float lumaLeft = dot(colorLeft, kLumaCoeff);
    float lumaRight = dot(colorRight, kLumaCoeff);
    float lumaDown = dot(colorDown, kLumaCoeff);

    // -------------------------------------------------------------------------
    // Adaptive sharpness / edge protection
    // -------------------------------------------------------------------------

    float2 depthGrad = EstimateDepthGradientFromTaps(centerDepth, depthUp, depthLeft, depthRight, depthDown);

    float edgeFactor = ComputeEdgeFactorFromTaps(centerLuma, centerDepth, depthGrad, lumaUp, lumaLeft, 
                                                 lumaRight, lumaDown, depthUp, depthLeft, depthRight, depthDown);

    float edgeSharpness = adaptiveSharpness * lerp(0.12, 1.0, edgeFactor);

    float distanceBoost = DistanceSharpnessBoost(centerDepth);
    float motionStability = saturate(adaptiveSharpness / max(Sharpness, 1e-4));
    distanceBoost = lerp(1.0, distanceBoost, motionStability);

    float boostedSharpness = edgeSharpness * distanceBoost;

    float lumaRange = ComputeLocalLumaRangeFromTaps(centerLuma, lumaUp, lumaLeft, lumaRight, lumaDown);

    float unstable = saturate((lumaRange - 0.12) * 4.0);
    unstable *= unstable;

    boostedSharpness *= lerp(1.0, 0.9, unstable);
    float finalSharpness = min(boostedSharpness, 2.0);

    // -------------------------------------------------------------------------
    // RCAS 4-neighbor pattern
    // -------------------------------------------------------------------------

    float3 e = c;

    // Keep original RCAS naming convention.
    float3 bRaw = colorUp;
    float3 dRaw = colorLeft;
    float3 fRaw = colorRight;
    float3 hRaw = colorDown;

    // Normalize RCAS into a local 0..1-ish range for HDR/pre-tonemap input.
    // Use original taps before depth rejection so the scale reflects the true local neighborhood.
    float localScale = Max3(e);
    localScale = max(localScale, Max3(bRaw));
    localScale = max(localScale, Max3(dRaw));
    localScale = max(localScale, Max3(fRaw));
    localScale = max(localScale, Max3(hRaw));
    // localScale = max(localScale, 1e-4);

    // Depth weights for cross taps.
    float wb = DepthWeightGrad(centerDepth, depthUp, depthGrad, int2(0, -1));
    float wd = DepthWeightGrad(centerDepth, depthLeft, depthGrad, int2(-1, 0));
    float wf = DepthWeightGrad(centerDepth, depthRight, depthGrad, int2(1, 0));
    float wh = DepthWeightGrad(centerDepth, depthDown, depthGrad, int2(0, 1));

    // Prevent RCAS from pulling color across depth discontinuities.
    // Unsafe neighbors are blended back toward center.
    float3 b = lerp(e, bRaw, wb);
    float3 d = lerp(e, dRaw, wd);
    float3 f = lerp(e, fRaw, wf);
    float3 h = lerp(e, hRaw, wh);

    localScale = max(localScale, 1.0);

    float3 en = max(e / localScale, 0.0);
    float3 bn = max(b / localScale, 0.0);
    float3 dn = max(d / localScale, 0.0);
    float3 fn = max(f / localScale, 0.0);
    float3 hn = max(h / localScale, 0.0);

    // RCAS min/max ring.
    float3 minRGB = min(min(bn, dn), min(fn, hn));
    float3 maxRGB = max(max(bn, dn), max(fn, hn));

    float2 peakC = float2(1.0, -4.0);

    // Limiter.
    float3 hitMin = minRGB / max(4.0 * maxRGB, 1e-5);
    float3 hitMax = (peakC.xxx - maxRGB) / max(4.0 * minRGB + peakC.yyy, -1e-5);

    float3 lobeRGB = max(-hitMin, hitMax);

    // RCAS is happier with roughly 0..1 range.
    // float rcasSharpness = saturate(finalSharpness);
    float rcasSharpness = saturate(finalSharpness * 0.85);

    float lobe = max(-0.1875, min(max(lobeRGB.r, max(lobeRGB.g, lobeRGB.b)), 0.0)) * rcasSharpness;
    float rcpL = rcp(4.0 * lobe + 1.0);

    float3 output = (((bn + dn + fn + hn) * lobe + en) * rcpL) * localScale;
    output = max(output, 0.0);

    if (Debug > 0)
        output = ApplyDebugTint(output, Sharpness, adaptiveSharpness, edgeSharpness, finalSharpness, distanceBoost, Debug);

    if (ClampOutput > 0)
        output = saturate(output);

    Dest[p] = float4(output, 1.0);
}
)";

static std::string dasDASharpenCode = R"(
#ifdef VK_MODE
cbuffer Params : register(b0, space0)
#else
cbuffer Params : register(b0)
#endif
{
    float Sharpness;

    int DepthIsLinear;
    int DepthIsReversed;

    float DepthScale;
    float DepthBias;

    float DepthLinearA;
    float DepthLinearB;
    float DepthLinearC;

    int DynamicSharpenEnabled;
    int DisplaySizeMV;
    int Debug;

    float MotionSharpness;
    float MotionTextureScale;
    float MvScaleX;
    float MvScaleY;
    float MotionThreshold;
    float MotionScaleLimit;

    float DepthTextureScale;

    int ClampOutput;

    int DisplayWidth;
    int DisplayHeight;
    int MotionWidth;
    int MotionHeight;
    int DepthWidth;
    int DepthHeight;
};

#ifdef VK_MODE
[[vk::binding(1, 0)]]
#endif
Texture2D<float4> Source : register(t0);

#ifdef VK_MODE
[[vk::binding(2, 0)]]
#endif
Texture2D<float2> Motion : register(t1);

#ifdef VK_MODE
[[vk::binding(3, 0)]]
#endif
Texture2D<float> DepthTex : register(t2);

#ifdef VK_MODE
[[vk::binding(4, 0)]]
#endif
RWTexture2D<float4> Dest : register(u0);

static const float3 kLumaCoeff = float3(0.2126, 0.7152, 0.0722);

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

float Luma(float3 c)
{
    return dot(c, kLumaCoeff);
}

float Max3(float3 v)
{
    return max(v.r, max(v.g, v.b));
}

int2 ClampCoord(int2 p)
{
    return int2(clamp(p.x, 0, DisplayWidth - 1), clamp(p.y, 0, DisplayHeight - 1));
}

int2 ClampMotionCoord(int2 p)
{
    return int2(clamp(p.x, 0, MotionWidth - 1), clamp(p.y, 0, MotionHeight - 1));
}

int2 ClampDepthCoord(int2 p)
{
    return int2(clamp(p.x, 0, DepthWidth - 1), clamp(p.y, 0, DepthHeight - 1));
}

float3 SafeLoadColor(int2 p)
{
    return Source.Load(int3(ClampCoord(p), 0)).rgb;
}

float SafeLoadRawDepthAtCoord(int2 p)
{
    return DepthTex.Load(int3(ClampDepthCoord(p), 0)).r;
}

float2 SafeLoadMotion(int2 p)
{
    return Motion.Load(int3(ClampMotionCoord(p), 0)).rg;
}

float LinearizeDepth(float rawDepth)
{
    float z = rawDepth;

    if (DepthIsLinear > 0)
    {
        if (DepthIsReversed > 0)
            z = 1.0 - z;

        return z;
    }

    if (DepthIsReversed > 0)
    {
        float nearPlane = DepthLinearB - DepthLinearC;
        return DepthLinearA / max(nearPlane + z * DepthLinearC, 1e-6);
    }

    return DepthLinearA / max(DepthLinearB - z * DepthLinearC, 1e-6);
}

float SafeLoadDepthLinearFromDepthCoord(int2 depthCoord)
{
    float2 df = (float2(pixelCoord) + 0.5) * DepthTextureScale;
    int2 depthCoord = int2(df);
    return LinearizeDepth(SafeLoadRawDepthAtCoord(depthCoord));
}

float2 EstimateDepthGradientFromTaps(float centerDepth, float depthUp, float depthLeft,
                                     float depthRight, float depthDown)
{
    float gxF = depthRight - centerDepth;
    float gxB = centerDepth - depthLeft;
    float gyF = depthDown - centerDepth;
    float gyB = centerDepth - depthUp;

    float gx = abs(gxF) < abs(gxB) ? gxF : gxB;
    float gy = abs(gyF) < abs(gyB) ? gyF : gyB;

    float maxGrad = max(abs(centerDepth) * 0.05, 1e-3);
    return clamp(float2(gx, gy), -maxGrad, maxGrad);
}

float DepthResidualGrad(float centerDepth, float sampleDepth, float2 gradient, int2 offset)
{
    float predicted = centerDepth + dot(float2(offset), gradient);
    float residual = abs(sampleDepth - predicted);

    residual /= max(abs(centerDepth), 1e-4);
    residual = max(residual - DepthBias, 0.0);

    return residual;
}

float DepthWeightFromResidual(float residual, float floorWeight)
{
    float w = saturate(1.0 - residual * DepthScale);
    return lerp(floorWeight, 1.0, w);
}

float ComputeTapHaloRisk(float centerLuma, float sampleLuma, float depthResidual)
{
    float depthBreak = smoothstep(0.0015, 0.018, depthResidual);

    float lumaDenom = max(max(abs(centerLuma), abs(sampleLuma)), 1e-4);
    float relativeLumaDiff = abs(sampleLuma - centerLuma) / lumaDenom;

    float lumaBreak = smoothstep(0.08, 0.45, relativeLumaDiff);
    float asymmetry = smoothstep(0.12, 0.65, relativeLumaDiff);

    float risk = depthBreak * lumaBreak * lerp(0.65, 1.0, asymmetry);

    return saturate(risk * risk * (3.0 - 2.0 * risk));
}

float DepthWeightGradAdaptive(float centerDepth, float sampleDepth, float2 gradient, int2 offset,
                              float centerLuma, float sampleLuma, out float haloRisk)
{
    float residual = DepthResidualGrad(centerDepth, sampleDepth, gradient, offset);

    haloRisk = ComputeTapHaloRisk(centerLuma, sampleLuma, residual);

    // Normal areas stay soft; high-risk silhouette taps get hard rejection.
    float floorWeight = lerp(0.45, 0.07, haloRisk);

    return DepthWeightFromResidual(residual, floorWeight);
}

// Expects positive view/world-space-like linear depth.
// If linear depth is normalized 0..1, this boost is effectively disabled.
float DistanceSharpnessBoost(float linearDepth)
{
    float d = max(linearDepth, 1e-4);
    float boost = saturate((log2(d) - 4.0) * 0.15);

    return lerp(1.0, 1.25, boost);
}

float ComputeAdaptiveSharpness(int2 pixelCoord)
{
    float setSharpness = Sharpness;

    if (DynamicSharpenEnabled > 0)
    {
        float2 mv;

        if (DisplaySizeMV > 0)
        {
            mv = SafeLoadMotion(pixelCoord);
        }
        else
        {
            float2 mvf = (float2(pixelCoord) + 0.5) * MotionTextureScale;
            int2 mvCoord = int2(mvf);
            mv = SafeLoadMotion(mvCoord);
        }

        float motion = max(abs(mv.x * MvScaleX), abs(mv.y * MvScaleY));

        float denom = max(MotionScaleLimit - MotionThreshold, 0.05);

        float add = (max(motion - MotionThreshold, 0.0) / denom) * MotionSharpness;
        add = clamp(add, min(0.0, MotionSharpness), max(0.0, MotionSharpness));

        setSharpness += add;
    }

    return clamp(setSharpness, 0.0, 2.0);
}

float3 ApplyDebugTint(float3 color, float baseSharpness, float adaptiveSharpness, float edgeSharpness,
                      float finalSharpness, float distanceBoost, int debugMode)
{
    float motionBoost = max(adaptiveSharpness - baseSharpness, 0.0);
    float motionReduce = max(baseSharpness - adaptiveSharpness, 0.0);
    float edgeReduce = max(adaptiveSharpness - edgeSharpness, 0.0);
    float distanceIncrease = max(distanceBoost - 1.0, 0.0);

    if (debugMode > 0)
    {
        color.r *= 1.0 + 12.0 * motionBoost;
        color.r += 0.35 * distanceIncrease;

        color.g *= 1.0 + 12.0 * motionReduce;
        color.b *= 1.0 + 12.0 * edgeReduce;
    }

    return color;
}

float ComputeEdgeFactorFromCrossWeights(float centerLuma, float lumaUp, float lumaLeft, float lumaRight, float lumaDown,
                                        float wUp, float wLeft, float wRight, float wDown)
{
    float lumaSum = 0.0;
    lumaSum += abs(lumaUp - centerLuma);
    lumaSum += abs(lumaLeft - centerLuma);
    lumaSum += abs(lumaRight - centerLuma);
    lumaSum += abs(lumaDown - centerLuma);

    float depthEdge = min(min(wUp, wLeft), min(wRight, wDown));

    float lumaAvg = lumaSum * 0.25;

    float lumaBase = max(max(abs(centerLuma), 0.25 * (abs(lumaUp) + abs(lumaLeft) + abs(lumaRight) + abs(lumaDown))), 1e-4);
    float relativeLumaAvg = lumaAvg / lumaBase;

    float lumaConfirm = saturate((relativeLumaAvg - 0.02) * 18.0);
    
    float depthTrust = lerp(0.40, 1.0, lumaConfirm);

    return lerp(1.0, depthEdge, depthTrust);
}

float3 ApplyLumaRatio(float3 color, float oldY, float newY)
{
    return color * (max(newY, 0.0) / max(oldY, 1e-6));
}
)"
                                      R"(
// -----------------------------------------------------------------------------
// Directional adaptive sharpen core
// -----------------------------------------------------------------------------

float3 ApplyDirectionalSharpen(float3 centerColor, float3 upColor, float3 leftColor, float3 rightColor, float3 downColor,
                               float3 upLeftColor, float3 upRightColor, float3 downLeftColor, float3 downRightColor,
                               float finalSharpness, float edgeFactor,
                               float haloRiskH, float haloRiskV, float haloRiskDA, float haloRiskDB)
{
    float localScale = Max3(centerColor);
    localScale = max(localScale, Max3(upColor));
    localScale = max(localScale, Max3(leftColor));
    localScale = max(localScale, Max3(rightColor));
    localScale = max(localScale, Max3(downColor));
    localScale = max(localScale, Max3(upLeftColor));
    localScale = max(localScale, Max3(upRightColor));
    localScale = max(localScale, Max3(downLeftColor));
    localScale = max(localScale, Max3(downRightColor));

    // Important: do not force localScale to >= 1.0.
    // This keeps the kernel exposure/local-range adaptive in SDR, HDR, and dark pre-tonemap areas.
    localScale = max(localScale, 1e-4);

    float3 c = max(centerColor / localScale, 0.0);
    float3 u = max(upColor / localScale, 0.0);
    float3 l = max(leftColor / localScale, 0.0);
    float3 r = max(rightColor / localScale, 0.0);
    float3 d = max(downColor / localScale, 0.0);

    float3 ul = max(upLeftColor / localScale, 0.0);
    float3 ur = max(upRightColor / localScale, 0.0);
    float3 dl = max(downLeftColor / localScale, 0.0);
    float3 dr = max(downRightColor / localScale, 0.0);

    float cY = max(Luma(c), 1e-6);
    float uY = max(Luma(u), 1e-6);
    float lY = max(Luma(l), 1e-6);
    float rY = max(Luma(r), 1e-6);
    float dY = max(Luma(d), 1e-6);

    float ulY = max(Luma(ul), 1e-6);
    float urY = max(Luma(ur), 1e-6);
    float dlY = max(Luma(dl), 1e-6);
    float drY = max(Luma(dr), 1e-6);

    // True 3x3 local range, matching the directional kernel and limiter.
    float minY = min(cY, min(min(uY, dY), min(lY, rY)));
    minY = min(minY, min(min(ulY, urY), min(dlY, drY)));

    float maxY = max(cY, max(max(uY, dY), max(lY, rY)));
    maxY = max(maxY, max(max(ulY, urY), max(dlY, drY)));

    float localRange3x3 = maxY - minY;
    float relativeRange = localRange3x3 / max(cY, 1e-4);

    // Direction candidates.
    float hY = (lY + rY) * 0.5;
    float vY = (uY + dY) * 0.5;
    float diagAY = (ulY + drY) * 0.5;
    float diagBY = (urY + dlY) * 0.5;

    float hDiff = abs(cY - hY);
    float vDiff = abs(cY - vY);
    float daDiff = abs(cY - diagAY);
    float dbDiff = abs(cY - diagBY);

    float bestDiff = hDiff;
    float secondDiff = max(max(vDiff, daDiff), dbDiff);
    float refY = hY;
    int selectedDir = 0; // 0=H, 1=V, 2=diagA, 3=diagB

    if (vDiff > bestDiff)
    {
        secondDiff = max(max(hDiff, daDiff), dbDiff);
        bestDiff = vDiff;
        refY = vY;
        selectedDir = 1;
    }

    if (daDiff > bestDiff)
    {
        secondDiff = max(max(hDiff, vDiff), dbDiff);
        bestDiff = daDiff;
        refY = diagAY;
        selectedDir = 2;
    }

    if (dbDiff > bestDiff)
    {
        secondDiff = max(max(hDiff, vDiff), daDiff);
        bestDiff = dbDiff;
        refY = diagBY;
        selectedDir = 3;
    }

    float selectedHaloRisk = haloRiskH;

    if (selectedDir == 1)
    {
        selectedHaloRisk = haloRiskV;
    }
    else if (selectedDir == 2)
    {
        selectedHaloRisk = haloRiskDA;
    }
    else if (selectedDir == 3)
    {
        selectedHaloRisk = haloRiskDB;
    }

    float maxHaloRisk = max(max(haloRiskH, haloRiskV), max(haloRiskDA, haloRiskDB));

    float directionSeparation = max(bestDiff - secondDiff, 0.0);

    float rawDirectionConfidence = saturate(directionSeparation / max(bestDiff, 1e-5));
    float directionConfidence = lerp(0.50, 1.0, rawDirectionConfidence);

    float ambiguityDamp = lerp(0.55, 1.0, smoothstep(0.22, 0.65, rawDirectionConfidence));

    // -------------------------------------------------------------------------
    // AA-ramp preservation
    // -------------------------------------------------------------------------

    float crossAvgY = (uY + dY + lY + rY) * 0.25;
    float isoDetail = (cY - crossAvgY) / max(crossAvgY, 1e-4);
    isoDetail = clamp(isoDetail, -4.0, 4.0);

    float rampRange = smoothstep(0.10, 0.45, relativeRange);
    float rampDirection = smoothstep(0.35, 0.85, directionConfidence);
    float rampDetail = smoothstep(0.025, 0.18, bestDiff);

    // Partial protection even if direction confidence is imperfect.
    float aaRampMask = rampRange * rampDetail * lerp(0.35, 1.0, rampDirection);

    float aaRampBlend = 0.30 * aaRampMask;
    refY = lerp(refY, crossAvgY, aaRampBlend);

    float detail = (cY - refY) / max(refY, 1e-4);
    detail = clamp(detail, -4.0, 4.0);

    float absDetail = abs(detail);
    float shapedDetail = sign(detail) * max(absDetail - 0.0010, 0.0);

    // Soft compression.
    shapedDetail = shapedDetail / (1.0 + 1.45 * abs(shapedDetail));

    // Tuned slightly stronger than previous version.
    shapedDetail = clamp(shapedDetail, -0.42, 0.42);

    // 3x3 range confidence. Since this now includes diagonals, it does not miss diagonal detail.
    float rangeConfidence = lerp(0.72, 1.0, smoothstep(0.0004, 0.018, relativeRange));
    float edgeConfidence = lerp(0.18, 1.0, edgeFactor);

    float aaStrengthDamp = lerp(1.0, 0.45, aaRampMask);

    float posGainAA = lerp(1.42, 1.00, aaRampMask);
    float negGainAA = lerp(0.72, 0.48, aaRampMask);
    float detailGain = shapedDetail >= 0.0 ? posGainAA : negGainAA;

    float unstablePattern = (1.0 - rawDirectionConfidence) * smoothstep(0.08, 0.35, relativeRange) * (1.0 - aaRampMask);

    float strength = finalSharpness * 2.1 * directionConfidence * rangeConfidence * edgeConfidence * 
                     aaStrengthDamp * ambiguityDamp * lerp(1.0, 0.65, unstablePattern);

    float nonDirectionalMask = 1.0 - directionConfidence;
    float edgeBlock = max(aaRampMask, maxHaloRisk);
    edgeBlock = saturate(edgeBlock * 1.35);

    float safeTextureMask = 1.0 - edgeBlock;

    // Shape the isotropic fallback too.
    float absIso = abs(isoDetail);
    float shapedIso = sign(isoDetail) * max(absIso - 0.0015, 0.0);
    shapedIso = shapedIso / (1.0 + 1.25 * abs(shapedIso));
    shapedIso = clamp(shapedIso, -0.12, 0.12);

    float stableIsoDetail = smoothstep(0.006, 0.030, max(absIso - 0.0015, 0.0));
    float isoBoost = lerp(1.0, 1.50, stableIsoDetail);

    float newY = cY + cY * shapedDetail * strength * detailGain;
    float isoGain = shapedIso >= 0.0 ? 1.0 : 0.45;

    newY += cY * shapedIso * isoGain * finalSharpness * 0.18 * isoBoost *
            nonDirectionalMask * safeTextureMask * lerp(1.0, 0.45, unstablePattern);

    // -------------------------------------------------------------------------
    // Halo-risk-aware limiter
    // -------------------------------------------------------------------------

    float rangeY = max(maxY - minY, cY * 0.01);

    float haloLimiter = saturate(selectedHaloRisk);

    float lowerExpand = lerp(0.42, 0.06, haloLimiter);
    float upperExpand = lerp(0.48, 0.10, haloLimiter);

    float limitMin = max(0.0, minY - rangeY * lowerExpand);
    float limitMax = maxY + rangeY * upperExpand;

    newY = clamp(newY, limitMin, limitMax);

    float3 outNorm = ApplyLumaRatio(c, cY, newY);

    return max(outNorm * localScale, 0.0);
}

// -----------------------------------------------------------------------------
// Main
// -----------------------------------------------------------------------------

[numthreads(16, 16, 1)]
void CSMain(uint3 DTid : SV_DispatchThreadID)
{
    int2 p = int2(DTid.xy);

    if (p.x >= DisplayWidth || p.y >= DisplayHeight)
        return;

    float3 centerColor = Source.Load(int3(p, 0)).rgb;
    float adaptiveSharpness = ComputeAdaptiveSharpness(p);

    if (adaptiveSharpness <= 0.0)
    {
        float3 outColor = max(centerColor, 0.0);

        if (Debug > 0)
            outColor = ApplyDebugTint(outColor, Sharpness, adaptiveSharpness, adaptiveSharpness, adaptiveSharpness, 1.0, Debug);

        if (ClampOutput > 0)
            outColor = saturate(outColor);

        Dest[p] = float4(outColor, 1.0);
        return;
    }

    float centerLuma = Luma(centerColor);

    int2 pUp = p + int2(0, -1);
    int2 pLeft = p + int2(-1, 0);
    int2 pRight = p + int2(1, 0);
    int2 pDown = p + int2(0, 1);

    int2 pUpLeft = p + int2(-1, -1);
    int2 pUpRight = p + int2(1, -1);
    int2 pDownLeft = p + int2(-1, 1);
    int2 pDownRight = p + int2(1, 1);

    // 9 color taps kept.
    float3 colorUpRaw = SafeLoadColor(pUp);
    float3 colorLeftRaw = SafeLoadColor(pLeft);
    float3 colorRightRaw = SafeLoadColor(pRight);
    float3 colorDownRaw = SafeLoadColor(pDown);

    float3 colorUpLeftRaw = SafeLoadColor(pUpLeft);
    float3 colorUpRightRaw = SafeLoadColor(pUpRight);
    float3 colorDownLeftRaw = SafeLoadColor(pDownLeft);
    float3 colorDownRightRaw = SafeLoadColor(pDownRight);

    float lumaUp = Luma(colorUpRaw);
    float lumaLeft = Luma(colorLeftRaw);
    float lumaRight = Luma(colorRightRaw);
    float lumaDown = Luma(colorDownRaw);

    float lumaUpLeft = Luma(colorUpLeftRaw);
    float lumaUpRight = Luma(colorUpRightRaw);
    float lumaDownLeft = Luma(colorDownLeftRaw);
    float lumaDownRight = Luma(colorDownRightRaw);

    // Only cross depth taps are loaded.
    // Compute output-pixel to depth-texel mapping once.
    // Offsetting baseDf by +/-DepthTextureScale is equivalent to mapping p + offset
    // through OutputToDepthCoord(). For downsampled depth, multiple output pixels may
    // intentionally map to the same depth texel after floor().
    float2 baseDf = (float2(p) + 0.5) * DepthTextureScale;

    int2 depthCenterCoord = int2(floor(baseDf));
    int2 depthUpCoord = int2(floor(baseDf + float2(0.0, -DepthTextureScale)));
    int2 depthLeftCoord = int2(floor(baseDf + float2(-DepthTextureScale, 0.0)));
    int2 depthRightCoord = int2(floor(baseDf + float2(DepthTextureScale, 0.0)));
    int2 depthDownCoord = int2(floor(baseDf + float2(0.0, DepthTextureScale)));

    float centerDepth = SafeLoadDepthLinearFromDepthCoord(depthCenterCoord);
    float depthUp = SafeLoadDepthLinearFromDepthCoord(depthUpCoord);
    float depthLeft = SafeLoadDepthLinearFromDepthCoord(depthLeftCoord);
    float depthRight = SafeLoadDepthLinearFromDepthCoord(depthRightCoord);
    float depthDown = SafeLoadDepthLinearFromDepthCoord(depthDownCoord);
    
    float2 depthGrad = EstimateDepthGradientFromTaps(centerDepth, depthUp, depthLeft, depthRight, depthDown);

    float haloUp;
    float haloLeft;
    float haloRight;
    float haloDown;

    float wUp = DepthWeightGradAdaptive(centerDepth, depthUp, depthGrad, int2(0, -1), centerLuma, lumaUp, haloUp);
    float wLeft = DepthWeightGradAdaptive(centerDepth, depthLeft, depthGrad, int2(-1, 0), centerLuma, lumaLeft, haloLeft);
    float wRight = DepthWeightGradAdaptive(centerDepth, depthRight, depthGrad, int2(1, 0), centerLuma, lumaRight, haloRight);
    float wDown = DepthWeightGradAdaptive(centerDepth, depthDown, depthGrad, int2(0, 1), centerLuma, lumaDown, haloDown);

    // Cross depth-aware neighbor rejection.
    float3 colorUp = lerp(centerColor, colorUpRaw, wUp);
    float3 colorLeft = lerp(centerColor, colorLeftRaw, wLeft);
    float3 colorRight = lerp(centerColor, colorRightRaw, wRight);
    float3 colorDown = lerp(centerColor, colorDownRaw, wDown);

    // Synthetic diagonal protection from adjacent cross weights.
    // No diagonal depth loads.
    float wUpLeft = min(wUp, wLeft);
    float wUpRight = min(wUp, wRight);
    float wDownLeft = min(wDown, wLeft);
    float wDownRight = min(wDown, wRight);

    float haloUpLeft = max(haloUp, haloLeft);
    float haloUpRight = max(haloUp, haloRight);
    float haloDownLeft = max(haloDown, haloLeft);
    float haloDownRight = max(haloDown, haloRight);

    // Optional luma contrast strengthening for diagonal synthetic rejection.
    // This helps when diagonal color contrast is obviously risky even without diagonal depth.
    float diagDenomUL = max(max(abs(centerLuma), abs(lumaUpLeft)), 1e-4);
    float diagDenomUR = max(max(abs(centerLuma), abs(lumaUpRight)), 1e-4);
    float diagDenomDL = max(max(abs(centerLuma), abs(lumaDownLeft)), 1e-4);
    float diagDenomDR = max(max(abs(centerLuma), abs(lumaDownRight)), 1e-4);

    float diagContrastUL = smoothstep(0.18, 0.65, abs(lumaUpLeft - centerLuma) / diagDenomUL);
    float diagContrastUR = smoothstep(0.18, 0.65, abs(lumaUpRight - centerLuma) / diagDenomUR);
    float diagContrastDL = smoothstep(0.18, 0.65, abs(lumaDownLeft - centerLuma) / diagDenomDL);
    float diagContrastDR = smoothstep(0.18, 0.65, abs(lumaDownRight - centerLuma) / diagDenomDR);

    wUpLeft = lerp(wUpLeft, min(wUpLeft, 0.4), diagContrastUL * haloUpLeft);
    wUpRight = lerp(wUpRight, min(wUpRight, 0.4), diagContrastUR * haloUpRight);
    wDownLeft = lerp(wDownLeft, min(wDownLeft, 0.4), diagContrastDL * haloDownLeft);
    wDownRight = lerp(wDownRight, min(wDownRight, 0.4), diagContrastDR * haloDownRight);

    float3 colorUpLeft = lerp(centerColor, colorUpLeftRaw, wUpLeft);
    float3 colorUpRight = lerp(centerColor, colorUpRightRaw, wUpRight);
    float3 colorDownLeft = lerp(centerColor, colorDownLeftRaw, wDownLeft);
    float3 colorDownRight = lerp(centerColor, colorDownRightRaw, wDownRight);

    float edgeFactor = ComputeEdgeFactorFromCrossWeights(centerLuma, lumaUp, lumaLeft, lumaRight, lumaDown,
                                                         wUp, wLeft, wRight, wDown);

    // Tuned edge reduction.
    float edgeSharpness = adaptiveSharpness * lerp(0.10, 1.0, edgeFactor);

    float distanceBoost = DistanceSharpnessBoost(centerDepth);
    float motionStability = saturate(adaptiveSharpness / max(Sharpness, 1e-4));
    distanceBoost = lerp(1.0, distanceBoost, motionStability);

    float boostedSharpness = edgeSharpness * distanceBoost;

    float crossMin = min(centerLuma, min(min(lumaUp, lumaDown), min(lumaLeft, lumaRight)));
    float crossMax = max(centerLuma, max(max(lumaUp, lumaDown), max(lumaLeft, lumaRight)));
    float lumaRange = crossMax - crossMin;

    float unstable = saturate((lumaRange - 0.16) * 3.0);
    unstable *= unstable;

    boostedSharpness *= lerp(1.0, 0.92, unstable);

    float finalSharpness = clamp(boostedSharpness, 0.0, 2.0);

    // Diagonal halo risks are conservative because diagonal depth is not sampled.
    // Each synthetic diagonal risk inherits from adjacent cross risks, so diagonal
    // directions may collapse toward the max cross halo risk. This is intentional:
    // it preserves halo safety while avoiding 4 extra depth loads.    
    float haloRiskH = max(haloLeft, haloRight);
    float haloRiskV = max(haloUp, haloDown);
    float haloRiskDA = max(haloUpLeft, haloDownRight);
    float haloRiskDB = max(haloUpRight, haloDownLeft);

    float3 output = ApplyDirectionalSharpen(centerColor, colorUp, colorLeft, colorRight, colorDown,
                                            colorUpLeft, colorUpRight, colorDownLeft, colorDownRight,
                                            finalSharpness, edgeFactor,
                                            haloRiskH, haloRiskV, haloRiskDA, haloRiskDB);

    if (Debug > 0)
    {
        output = ApplyDebugTint(output, Sharpness, adaptiveSharpness, edgeSharpness, finalSharpness, distanceBoost, Debug);
    }

    if (ClampOutput > 0)
        output = saturate(output);

    Dest[p] = float4(output, 1.0);
}
)";

static std::string rcasCode = R"(
// Based on this Reshade shader
// https://github.com/RdenBlaauwen/RCAS-for-ReShade

#ifdef VK_MODE
cbuffer Params : register(b0, space0)
#else
cbuffer Params : register(b0)
#endif
{
    float Sharpness;
    float Contrast;

    // Motion Vector Stuff
    int DynamicSharpenEnabled;
    int DisplaySizeMV;
    int Debug;

    float MotionSharpness;
    float MotionTextureScale;
    float MvScaleX;
    float MvScaleY;
    float Threshold;
    float ScaleLimit;
    int DisplayWidth;
    int DisplayHeight;
};

#ifdef VK_MODE
[[vk::binding(1, 0)]]
#endif
Texture2D<float3> Source : register(t0);

#ifdef VK_MODE
[[vk::binding(2, 0)]]
#endif
Texture2D<float2> Motion : register(t1);

#ifdef VK_MODE
[[vk::binding(3, 0)]]
#endif
RWTexture2D<float3> Dest : register(u0);

[numthreads(16, 16, 1)]
void CSMain(uint3 DTid : SV_DispatchThreadID)
{
    // Guard against oversized dispatch
    if ((int) DTid.x >= DisplayWidth || (int) DTid.y >= DisplayHeight)
        return;

    int2 pixel = int2(DTid.xy);
    int2 maxPixel = int2(DisplayWidth - 1, DisplayHeight - 1);

    float setSharpness = Sharpness;

    if (DynamicSharpenEnabled > 0)
    {
        float2 mv = float2(0.0, 0.0);
        float motion = 0.0;
        float add = 0.0;

        int2 mvCoord;
        if (DisplaySizeMV > 0)
        {
            mvCoord = pixel;
        }
        else
        {
            mvCoord = int2(pixel * MotionTextureScale);
        }

        // Clamp motion texture reads to valid range
        mvCoord.x = clamp(mvCoord.x, 0, maxPixel.x);
        mvCoord.y = clamp(mvCoord.y, 0, maxPixel.y);

        mv = Motion.Load(int3(mvCoord, 0)).rg;

        motion = max(abs(mv.x * MvScaleX), abs(mv.y * MvScaleY));

        if (motion > Threshold && ScaleLimit > Threshold)
        {
            add = ((motion - Threshold) / (ScaleLimit - Threshold)) * MotionSharpness;
        }

        if ((add > MotionSharpness && MotionSharpness > 0.0) ||
            (add < MotionSharpness && MotionSharpness < 0.0))
        {
            add = MotionSharpness;
        }

        setSharpness += add;
        setSharpness = clamp(setSharpness, 0.0, 1.0);
    }

    float3 e = Source.Load(int3(pixel, 0)).rgb;

    // Skip sharpening if set value == 0
    if (setSharpness == 0.0)
    {
        if (Debug > 0 && DynamicSharpenEnabled > 0 && Sharpness > 0.0)
            e.g *= 1.0 + (12.0 * Sharpness);

        Dest[pixel] = e;
        return;
    }

    // Clamp neighbor accesses at image borders
    int2 coordB = int2(pixel.x, max(pixel.y - 1, 0));
    int2 coordD = int2(max(pixel.x - 1, 0), pixel.y);
    int2 coordF = int2(min(pixel.x + 1, maxPixel.x), pixel.y);
    int2 coordH = int2(pixel.x, min(pixel.y + 1, maxPixel.y));

    float3 b = Source.Load(int3(coordB, 0)).rgb;
    float3 d = Source.Load(int3(coordD, 0)).rgb;
    float3 f = Source.Load(int3(coordF, 0)).rgb;
    float3 h = Source.Load(int3(coordH, 0)).rgb;

    // Only normalize HDR neighborhoods down; do not scale dark/LDR pixels up.
    float localScale = max(
        max(e.r, max(e.g, e.b)),
        max(
            max(b.r, max(b.g, b.b)),
            max(
                max(d.r, max(d.g, d.b)),
                max(
                    max(f.r, max(f.g, f.b)),
                    max(h.r, max(h.g, h.b))
                )
            )
        )
    );
    
    localScale = max(localScale, 1.0);

    float3 en = max(e / localScale, 0.0);
    float3 bn = max(b / localScale, 0.0);
    float3 dn = max(d / localScale, 0.0);
    float3 fn = max(f / localScale, 0.0);
    float3 hn = max(h / localScale, 0.0);

    // Min and max of normalized ring
    float3 minRGB = min(min(bn, dn), min(fn, hn));
    float3 maxRGB = max(max(bn, dn), max(fn, hn));    

    float2 peakC = float2(1.0, -4.0);

    // More numerically stable RCAS limiters
    float3 hitMin = minRGB / max(4.0 * maxRGB, 1e-5);
    float3 hitMax = (peakC.xxx - maxRGB) / max(4.0 * minRGB + peakC.yyy, -1e-5);

    float3 lobeRGB = max(-hitMin, hitMax);
    float lobe = max(-0.1875, min(max(lobeRGB.r, max(lobeRGB.g, lobeRGB.b)), 0.0)) * setSharpness;

    // Apply contrast adaptation only if Contrast != 0
    if (Contrast != 0.0)
    {
        float3 amp = saturate(min(minRGB, 2.0 - maxRGB) / max(maxRGB, 1e-5));
        amp = rsqrt(max(amp, 1e-5));

        float peak = -3.0 * Contrast + 8.0;
        float contrastFactor = 1.0 / max(amp.g * peak, 1.0);

        lobe *= lerp(1.0, contrastFactor, saturate(Contrast));
    }

    float rcpL = rcp(4.0 * lobe + 1.0);
    float3 output = (((bn + dn + fn + hn) * lobe + en) * rcpL) * localScale;
    output = max(output, 0.0);

    if (Debug > 0 && DynamicSharpenEnabled > 0)
    {
        if (Sharpness < setSharpness)
            output.r *= 1.0 + (12.0 * (setSharpness - Sharpness));
        else
            output.g *= 1.0 + (12.0 * (Sharpness - setSharpness));
    }

    Dest[pixel] = output;
}
)";

static ID3DBlob* RCAS_CompileShader(const char* shaderCode, const char* entryPoint, const char* target)
{
    ID3DBlob* shaderBlob = nullptr;
    ID3DBlob* errorBlob = nullptr;

    HRESULT hr = D3DCompile(shaderCode, strlen(shaderCode), nullptr, nullptr, nullptr, entryPoint, target,
                            D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &shaderBlob, &errorBlob);

    if (FAILED(hr))
    {
        LOG_ERROR("error while compiling shader");

        if (errorBlob)
        {
            LOG_ERROR("error while compiling shader : {0}", (char*) errorBlob->GetBufferPointer());
            errorBlob->Release();
        }

        if (shaderBlob)
            shaderBlob->Release();

        return nullptr;
    }

    if (errorBlob)
        errorBlob->Release();

    return shaderBlob;
}
