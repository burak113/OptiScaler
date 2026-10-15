#ifndef FSRD_NRD_MATERIAL_GUIDES_HLSLI
#define FSRD_NRD_MATERIAL_GUIDES_HLSLI

// Native A==1 (integer material ID3) is emitted for title model q==1. Its late
// compositor may replace BaseColor with white using a different CB6. That
// branch is unavailable at Recon, so retain white guides for this category.
bool NrdNativeMaterialKnown(float4 baseMetal, float nativeCategory)
{
    const bool knownCategory = nativeCategory == 0.0f || nativeCategory == (1.0f / 3.0f) ||
                               nativeCategory == (2.0f / 3.0f);
    return knownCategory && all(isfinite(baseMetal)) && all(baseMetal >= 0.0f) && all(baseMetal <= 1.0f);
}

float3 NrdDiffuseMaterialGuide(float4 baseMetal, float nativeCategory)
{
    if (!NrdNativeMaterialKnown(baseMetal,nativeCategory)) return 1.0f;
    return baseMetal.rgb * (1.0f - baseMetal.a);
}

// Pinned AMD denoising.md5.5.2, Ray Tracing Gems Chapter32 approximation.
// This is an explicit GGX guide approximation, not the title's late-compositor
// LUT/CB6-dependent multiplier. RR receives linear albedo (NON_GAMMA_ALBEDO).
float3 NrdApproximateGgxMaterialAlbedo(float3 F0, float alpha, float NoV)
{
    NoV = abs(NoV);
    const float4 x = float4(1.0f,NoV,NoV*NoV,NoV*NoV*NoV);
    const float4 y = float4(1.0f,alpha,alpha*alpha,alpha*alpha*alpha);
    const float2x2 M1 = float2x2(0.99044f,-1.28514f,1.29678f,-0.755907f);
    const float3x3 M2 = float3x3(1.0f,2.92338f,59.4188f,20.3225f,-27.0302f,222.592f,
                               121.563f,626.13f,316.627f);
    const float2x2 M3 = float2x2(0.0365463f,3.32707f,9.0632f,-9.04756f);
    const float3x3 M4 = float3x3(1.0f,3.59685f,-1.36772f,9.04401f,-16.3174f,9.22949f,
                               5.56589f,19.7886f,-20.2123f);
    float bias = dot(mul(M1,x.xy),y.xy) * rcp(dot(mul(M2,x.xyw),y.xyw));
    const float scale = dot(mul(M3,x.xy),y.xy) * rcp(dot(mul(M4,x.xzw),y.xyw));
    bias *= saturate(F0.g * 50.0f);
    return mad(F0,max(0.0f,scale),max(0.0f,bias));
}

float3 NrdSpecularMaterialGuide(float4 baseMetal, float nativeCategory, float roughness, float NoV)
{
    if (!NrdNativeMaterialKnown(baseMetal,nativeCategory) || !isfinite(roughness) ||
        !isfinite(NoV) || roughness < 0.0f || roughness > 1.0f || abs(NoV) > 1.0f) return 1.0f;
    const float3 F0 = lerp(float3(0.04f,0.04f,0.04f),baseMetal.rgb,baseMetal.a);
    const float3 guide = NrdApproximateGgxMaterialAlbedo(F0,roughness*roughness,NoV);
    return all(isfinite(guide)) && all(guide >= 0.0f) ? guide : 1.0f;
}
#endif
