// Recovery v2 lobe recovery, pass 1 of 3: temporal lighting references (see FSRDRecoveryLobeCommon.hlsli).
//
// On ordinary surfaces each lobe reference holds, on the jitter-free raster, a value v and a sub-pixel luminance gradient g. This
// frame's sample of pixel p lies at p - Jitter, so the reference predicts it as v + (g . x) c (x = -Jitter,
// c = v / luma(v): the gradient carries luminance and keeps the value's colour). The prediction error e updates
// both: v += a e, g += 12 b luma(e) x (12 = 1 / variance of a jitter offset). a and b are 1 / sample count
// (a running mean) until they reach Response; the gradient is only fitted once the reference has GradientAge
// samples, before that it would turn the first frames' noise into false detail.
// Reprojection follows the motion vectors with the gradient: each bilinear history tap is moved to the
// reprojected position by its own gradient, so following motion does not blur the reference.
// - a history tap counts when its view Z is the expected previous depth within 3% plus this pixel's largest
//   depth step to a neighbour (one pixel of jitter moves a grazing surface's hit by that step), and its normal
//   is as close to this pixel's as the 3x3 neighbourhood's own normals are (rippled water changes its normals
//   between samples); the bilinear read renormalises the counted taps, and with less than half of its
//   footprint left the reference restarts from this frame;
// - the stored values are rounded stochastically to FP16, so a converged average does not stall;
// - pixels whose final colour is the current source (Skip alpha -1) never get a reference.
// The reference at this frame's samples is limited to the range of its eight neighbours (an isolated noise
// spike is no detail) and level 0 of the band pyramid is written for the down and band passes: reference - RR
// per lobe, the luma of the innovation e for the band noise, the flat albedo class (zero-roughness material, which
// RR is given a raised roughness for), the reference's maturity and its sum of squared weights.
#include "FSRDRecoveryLobeCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 15), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 7), visibility = SHADER_VISIBILITY_ALL), "

Texture2D<float4> InSpecularSignal : register(t0);       // RR's specular input, demodulated
Texture2D<float4> InDiffuseSignal : register(t1);        // RR's diffuse input, demodulated
Texture2D<float4> InSpecularDenoised : register(t2);     // RR's specular output
Texture2D<float4> InDiffuseDenoised : register(t3);      // RR's diffuse output
Texture2D<float4> InExtraDiffuseDenoised : register(t4); // second diffuse half (RECOVERY_FLAGS_EXTRA_DIFFUSE)
Texture2D<float4> InSpecularAlbedo : register(t5);       // the guides RR and the composition use
Texture2D<float4> InDiffuseAlbedo : register(t6);
Texture2D<float> InLinearDepth : register(t7);           // signed linear view-space depth
Texture2D<float4> InNormals : register(t8);              // XY: octahedral normal (UNORM), A: RR material type / 3
Texture2D<float4> InMotion : register(t9);               // XY: previous UV - current UV, Z: previous - current view Z, W: valid
Texture2D<float4> InSkipSignal : register(t10);          // A = -1: the final colour is the current source
Texture2D<float4> InPrevSpecular : register(t11);        // RGB: last frame's specular reference value
Texture2D<float4> InPrevDiffuse : register(t12);         // RGB: last frame's diffuse reference value
Texture2D<float4> InPrevGeometry : register(t13);        // X: view Z, YZ: octahedral normal, W: reference age
Texture2D<float4> InPrevGradient : register(t14);        // XY: specular luminance gradient, ZW: diffuse

RWTexture2D<float4> OutSpecular : register(u0);
RWTexture2D<float4> OutDiffuse : register(u1);
RWTexture2D<float4> OutGeometry : register(u2);
RWTexture2D<float4> OutLevelA : register(u3); // RGB: specular reference - RR, A: luma of the specular innovation
RWTexture2D<float4> OutLevelB : register(u4); // RGB: diffuse reference - RR, A: luma of the diffuse innovation
RWTexture2D<float4> OutLevelC : register(u5); // X/Y: flat albedo class (both lobes), Z: maturity, W: squared weights
RWTexture2D<float4> OutGradient : register(u6);

// 8x8 tile, reference computed over a one-pixel halo (10x10); depth, normals and guides over two (12x12).
groupshared float s_Depth[12][12];
groupshared float3 s_Normal[12][12];
groupshared float3 s_RefS[10][10];  // reference at this frame's samples
groupshared float3 s_RefD[10][10];
groupshared float2 s_Innovation[10][10];
groupshared float s_Age[10][10];

// Colour of a value: luminance 1, the value's chroma. The gradient is fitted to luminance and applied with it.
float3 GradientColour(float3 v)
{
    const float3 c = max(v, 0.0f);
    return c / max(GetLuminance(c), 1e-4f);
}

struct History
{
    float3 specular, diffuse;
    float4 gradient;
    float age;
    bool valid;
};

// Bilinear history read over the counted taps, each tap moved to the position by its own gradient.
History ReadHistory(float2 position, int2 size, float expectedZ, float depthTolerance, float3 normal, float normalThreshold)
{
    History h;
    h.specular = 0.0f;
    h.diffuse = 0.0f;
    h.gradient = 0.0f;
    h.age = 0.0f;
    float weight = 0.0f;
    const int2 base = int2(floor(position));
    const float2 f = position - float2(base);
    [unroll]
    for (int t = 0; t < 4; ++t)
    {
        const int2 offset = int2(t & 1, t >> 1);
        const int2 q = base + offset;
        if (any(q < 0) || any(q >= size))
            continue;
        const float4 previous = InPrevGeometry[q];
        if (!(abs(previous.x - expectedZ) <= depthTolerance) || !(dot(OctahedralDecode(previous.yz), normal) > normalThreshold))
            continue;
        const float w = (offset.x != 0 ? f.x : 1.0f - f.x) * (offset.y != 0 ? f.y : 1.0f - f.y);
        const float2 shift = position - float2(q);
        const float3 s = InPrevSpecular[q].rgb, d = InPrevDiffuse[q].rgb;
        const float4 g = InPrevGradient[q];
        h.specular += w * (s + dot(g.xy, shift) * GradientColour(s));
        h.diffuse += w * (d + dot(g.zw, shift) * GradientColour(d));
        h.gradient += w * g;
        h.age += w * previous.w;
        weight += w;
    }
    h.valid = weight >= 0.5f;
    if (weight > 0.0f)
    {
        const float inverse = 1.0f / weight;
        h.specular *= inverse;
        h.diffuse *= inverse;
        h.gradient *= inverse;
        h.age *= inverse;
    }
    return h;
}

// One lobe's reference update. Returns the reference at this frame's sample; value / gradient are updated in place.
float3 UpdateLobe(float3 sample, float2 x, float age, float a, float b, inout float3 value, inout float2 gradient,
                  out float innovation)
{
    const float3 predicted = value + dot(gradient, x) * GradientColour(value);
    const float3 e = sample - predicted;
    innovation = GetLuminance(e);
    value += a * e;
    gradient += (12.0f * b * innovation) * x;
    return value + dot(gradient, x) * GradientColour(value);
}

// Current-frame detail for changing displays. RR supplies a clean edge guide;
// the noisy lighting is averaged only across compatible pixels of that guide.


[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dtID : SV_DispatchThreadID, uint3 gtID : SV_GroupThreadID, uint3 gID : SV_GroupID)
{
    const int2 size = int2(DstTexSize.xy);
    const uint thread = gtID.y * 8 + gtID.x;
    const int2 origin = int2(gID.xy) * 8 - 2;
    for (uint i = thread; i < 144; i += 64)
    {
        const int2 q = clamp(origin + int2(i % 12, i / 12), int2(0, 0), size - 1);
        s_Depth[i / 12][i % 12] = InLinearDepth[q];
        s_Normal[i / 12][i % 12] = OctahedralDecode(InNormals[q].xy);
    }
    GroupMemoryBarrierWithGroupSync();

    const float2 x = -Jitter;
    const uint frameSeed = RecoveryHash(FrameIndex * 0x9e3779b9u);
    // The reference over the tile and its one-pixel halo; the history of the tile's own pixels is written here.
    for (uint j = thread; j < 100; j += 64)
    {
        const int2 local = int2(j % 10, j / 10);
        const int2 r = int2(gID.xy) * 8 - 1 + local;
        const int2 px = clamp(r, int2(0, 0), size - 1);
        const int2 c = local + 1; // position in the 12x12 arrays
        const bool own = all(local >= 1) && all(local <= 8) && all(r == px);

        const float viewZ = s_Depth[c.y][c.x];
        const float3 normal = s_Normal[c.y][c.x];
        const float4 motion = InMotion[px];
        const bool current = InSkipSignal[px].a == -1.0f || abs(InNormals[px].a - 1.0f / 3.0f) < 0.1f;
        const bool geometry = isfinite(viewZ) && abs(viewZ) > 1e-5f;

        History h;
        h.valid = false;
        h.age = 0.0f;
        [branch]
        if (IsSet(RECOVERY_FLAGS_HISTORY_VALID) && motion.w >= 0.5f && geometry && !current)
        {
            float slope = 0.0f, closest = 1.0f;
            [unroll]
            for (int dy = -1; dy <= 1; ++dy)
            {
                [unroll]
                for (int dx = -1; dx <= 1; ++dx)
                {
                    if (dx != 0 && dy != 0)
                        closest = min(closest, dot(s_Normal[c.y + dy][c.x + dx], normal));
                    else if (dx != 0 || dy != 0)
                    {
                        const float z = s_Depth[c.y + dy][c.x + dx];
                        slope = max(slope, isfinite(z) ? abs(z - viewZ) : 0.0f);
                        closest = min(closest, dot(s_Normal[c.y + dy][c.x + dx], normal));
                    }
                }
            }
            const float2 position = float2(px) + motion.xy * DstTexSize.xy;
            const float expectedZ = viewZ + motion.z;
            h = ReadHistory(position, size, expectedZ, 0.03f * max(abs(expectedZ), 1e-3f) + slope, normal,
                            min(0.95f, closest) - 0.05f);
        }

        const float3 specularInput = InSpecularSignal[px].rgb;
        const float3 diffuseInput = InDiffuseSignal[px].rgb * (IsSet(RECOVERY_FLAGS_EXTRA_DIFFUSE) ? 2.0f : 1.0f);
        float3 specularValue = specularInput, diffuseValue = diffuseInput;
        float4 gradient = 0.0f;
        float2 innovation = 0.0f;
        float3 specularReference = specularInput, diffuseReference = diffuseInput;
        float age = 1.0f;
        if (h.valid)
        {
            const float a = max(1.0f / (h.age + 1.0f), Response);
            const float b = h.age >= GradientAge ? a : 0.0f;
            specularValue = h.specular;
            diffuseValue = h.diffuse;
            gradient = h.gradient;
            float2 gs = gradient.xy, gd = gradient.zw;
            specularReference = UpdateLobe(specularInput, x, h.age, a, b, specularValue, gs, innovation.x);
            diffuseReference = UpdateLobe(diffuseInput, x, h.age, a, b, diffuseValue, gd, innovation.y);
            gradient = float4(gs, gd);
            age = min(h.age + 1.0f, 1024.0f);
        }
        const uint index = j;
        s_RefS[index / 10][index % 10] = current ? 0.0f : max(specularReference, 0.0f);
        s_RefD[index / 10][index % 10] = current ? 0.0f : max(diffuseReference, 0.0f);
        s_Innovation[index / 10][index % 10] = innovation;
        s_Age[index / 10][index % 10] = current ? 0.0f : age;
        if (own)
        {
            const uint seed = RecoveryHash(uint(px.x) + uint(px.y) * 65536u) ^ frameSeed;
            OutSpecular[px] = float4(StochasticHalf3(specularValue, seed), 0.0f);
            OutDiffuse[px] = float4(StochasticHalf3(diffuseValue, seed ^ 0x5bd1e995u), 0.0f);
            OutGeometry[px] = float4(geometry && !current ? viewZ : 0.0f, InNormals[px].xy, age);
            OutGradient[px] = all(isfinite(gradient))
                ? float4(StochasticHalf3(gradient.xyz, seed ^ 0x27d4eb2fu), StochasticHalf(gradient.w, float(RecoveryHash(seed ^ 0x165667b1u)) * (1.0f / 4294967296.0f)))
                : 0.0f;
        }
    }
    GroupMemoryBarrierWithGroupSync();

    const int2 px = int2(dtID.xy);
    if (any(px >= size))
        return;
    const int2 l = int2(gtID.xy) + 1;
    const bool current = InSkipSignal[px].a == -1.0f || abs(InNormals[px].a - 1.0f / 3.0f) < 0.1f;

    // Zero-roughness material (RR material type 1): screens, signs and text, all of whose visible detail is in the
    // lighting; RR denoised them at a raised roughness, so their sharpness is the flat albedo recovery's.
    const float2 flat = abs(InNormals[px].a - 1.0f / 3.0f) < 0.1f ? 1.0f : 0.0f;

    // The reference within the range of its eight neighbours: an isolated spike is noise, not detail.
    float3 lowS = 65504.0f, highS = -65504.0f, lowD = 65504.0f, highD = -65504.0f;
    [unroll]
    for (int ny = -1; ny <= 1; ++ny)
    {
        [unroll]
        for (int nx = -1; nx <= 1; ++nx)
        {
            if ((nx == 0 && ny == 0) || s_Age[l.y + ny][l.x + nx] == 0.0f)
                continue;
            const float3 s = s_RefS[l.y + ny][l.x + nx], d = s_RefD[l.y + ny][l.x + nx];
            lowS = min(lowS, s);
            highS = max(highS, s);
            lowD = min(lowD, d);
            highD = max(highD, d);
        }
    }
    const bool neighbours = all(lowS <= highS);
    const float3 specularReference = neighbours ? clamp(s_RefS[l.y][l.x], lowS, highS) : s_RefS[l.y][l.x];
    const float3 diffuseReference = neighbours ? clamp(s_RefD[l.y][l.x], lowD, highD) : s_RefD[l.y][l.x];
    const float age = s_Age[l.y][l.x];

    const float3 specularOutput = InSpecularDenoised[px].rgb;
    const float3 diffuseOutput = InDiffuseDenoised[px].rgb +
        (IsSet(RECOVERY_FLAGS_EXTRA_DIFFUSE) ? InExtraDiffuseDenoised[px].rgb : 0.0f);
    const float maturity = current ? 0.0f : smoothstep(0.5f * MatureAge, MatureAge, age);
    const float3 specularDifference = current ? 0.0f : specularReference - specularOutput;
    const float3 diffuseDifference = current ? 0.0f : diffuseReference - diffuseOutput;
    const float2 innovation = s_Innovation[l.y][l.x];
    OutLevelA[px] = float4(clamp(specularDifference, -65504.0f, 65504.0f), clamp(innovation.x, -65504.0f, 65504.0f));
    OutLevelB[px] = float4(clamp(diffuseDifference, -65504.0f, 65504.0f), clamp(innovation.y, -65504.0f, 65504.0f));
    OutLevelC[px] = float4(flat, maturity, ReferenceWeightSquares(max(age, 1.0f), Response));
}
