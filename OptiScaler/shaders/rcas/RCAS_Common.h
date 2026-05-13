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
    // If DepthIsReversed != 0, reversal is applied in shader first:
    // linearDepth = DepthLinearA / max(DepthLinearB - z * DepthLinearC, 1e-6)
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

static const int2 kCrossOffsets[4] =
{
    int2(0, -1),
    int2(-1, 0),
    int2(1, 0),
    int2(0, 1)
};

static const int2 kDiagOffsets[4] =
{
    int2(-1, -1),
    int2(1, -1),
    int2(-1, 1),
    int2(1, 1)
};

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

int2 ClampCoord(int2 p)
{
    return int2(
        clamp(p.x, 0, DisplayWidth - 1),
        clamp(p.y, 0, DisplayHeight - 1)
    );
}

int2 ClampMotionCoord(int2 p)
{
    return int2(
        clamp(p.x, 0, MotionWidth - 1),
        clamp(p.y, 0, MotionHeight - 1)
    );
}

int2 ClampDepthCoord(int2 p)
{
    return int2(
        clamp(p.x, 0, DepthWidth - 1),
        clamp(p.y, 0, DepthHeight - 1)
    );
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

    if (DepthIsReversed > 0)
        z = 1.0 - z;

    if (DepthIsLinear > 0)
        return z;

    return DepthLinearA / max(DepthLinearB - z * DepthLinearC, 1e-6);
}

float SafeLoadDepthLinearFromOutputPixel(int2 pixelCoord)
{
    float2 df = (float2(pixelCoord) + 0.5) * DepthTextureScale;
    int2 depthCoord = int2(df);
    return LinearizeDepth(SafeLoadRawDepthAtCoord(depthCoord));
}

// Cheap bounded S-curve approximation.
float3 FastSCurve(float3 x)
{
    return x / (1.0 + abs(x));
}

float3 RemapFunction(float3 x, float3 center, float amount)
{
    float3 d = (x - center) * 4.2;
    float3 curve = amount * 0.35 * FastSCurve(d);
    return x + curve;
}

float DepthWeight(float centerDepth, float sampleDepth)
{
    float dz = abs(sampleDepth - centerDepth);
    dz = max(dz - DepthBias, 0.0);
    return saturate(1.0 - dz * DepthScale);
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
    float finalSharpness,
    int debugMode)
{
    float motionBoost = max(adaptiveSharpness - baseSharpness, 0.0);
    float motionReduce = max(baseSharpness - adaptiveSharpness, 0.0);
    float depthReduce = max(adaptiveSharpness - finalSharpness, 0.0);

    if (debugMode > 0)
    {
        color.r *= 1.0 + 12.0 * motionBoost;
        color.g *= 1.0 + 12.0 * motionReduce;
        color.b *= 1.0 + 12.0 * depthReduce;
    }

    return color;
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
            outColor = ApplyDebugTint(outColor, Sharpness, adaptiveSharpness, adaptiveSharpness, Debug);

        if (ClampOutput > 0)
            outColor = saturate(outColor);

        Dest[p] = float4(outColor, 1.0);
        return;
    }

    float centerDepth = SafeLoadDepthLinearFromOutputPixel(p);

    float crossDepths[4];
    float crossDepthWeightSum = 0.0;

    [unroll]
    for (int i = 0; i < 4; ++i)
    {
        crossDepths[i] = SafeLoadDepthLinearFromOutputPixel(p + kCrossOffsets[i]);
        crossDepthWeightSum += DepthWeight(centerDepth, crossDepths[i]);
    }

    float depthEdgeFactor = saturate(crossDepthWeightSum * 0.25);
    float finalSharpness = adaptiveSharpness * lerp(0.35, 1.0, depthEdgeFactor);

    float4 G1 = float4(c, 1.0) * 4.0;
    float4 L0 = float4(c, 1.0) * 4.0;

    [unroll]
    for (int j = 0; j < 4; ++j)
    {
        int2 q = p + kCrossOffsets[j];

        float3 tap = SafeLoadColor(q);
        float depthW = DepthWeight(centerDepth, crossDepths[j]);
        float w = 1.5 * depthW;

        G1 += float4(tap, 1.0) * w;
        L0 += float4(RemapFunction(tap, c, finalSharpness), 1.0) * w;
    }

    [unroll]
    for (int k = 0; k < 4; ++k)
    {
        int2 q = p + kDiagOffsets[k];

        float3 tap = SafeLoadColor(q);
        float tapDepth = SafeLoadDepthLinearFromOutputPixel(q);
        float w = DepthWeight(centerDepth, tapDepth);

        G1 += float4(tap, 1.0) * w;
        L0 += float4(RemapFunction(tap, c, finalSharpness), 1.0) * w;
    }

    // w starts at 4.0 and only accumulates non-negative weights.
    G1.rgb /= G1.w;
    L0.rgb /= L0.w;

    float3 output = (c - L0.rgb) + G1.rgb;

    if (Debug > 0)
        output = ApplyDebugTint(output, Sharpness, adaptiveSharpness, finalSharpness, Debug);

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
        setSharpness = clamp(setSharpness, 0.0, 1.3);
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

    // Min and max of ring
    float3 minRGB = min(min(b, d), min(f, h));
    float3 maxRGB = max(max(b, d), max(f, h));

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
    float3 output = ((b + d + f + h) * lobe + e) * rcpL;

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
