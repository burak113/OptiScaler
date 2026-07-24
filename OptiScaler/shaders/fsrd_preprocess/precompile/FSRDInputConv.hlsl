// FSR-RR Conversion & Packing Shader
#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 10), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 7), visibility = SHADER_VISIBILITY_ALL), "

// Dispatch config
#define THREAD_GROUP_SIZE_X     8
#define THREAD_GROUP_SIZE_Y     8
#define NUM_THREADS             (THREAD_GROUP_SIZE_X * THREAD_GROUP_SIZE_Y)

static const uint2 s_ThreadGroupSize = uint2(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y);
static const float s_MissingDiffuseHitDistance = 65504.0f; // FP16 max: ray miss / unknown distance

// Flags
#define FLAGS_NON_GAMMA_ALBEDO          (1 << 0)
#define FLAGS_LINEAR_DEPTH              (1 << 1)

#define FLAGS_PACKED_ROUGHNESS          (1 << 2)
#define FLAGS_NEGATIVE_VIEW_DEPTH       (1 << 3)
#define FLAGS_HAS_SPEC_HIT_DISTANCE     (1 << 4)

// Debug Flags
#define FLAGS_DEBUG                     (1 << 16)
#define FLAGS_DEBUG_MODE_MASK           (0xFF << 16)

// Inputs
#define FLAGS_DEBUG_IN_SPEC_HIT_DIST    (1 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_MOTION           (2 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_NORMALS          (3 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_ROUGHNESS        (4 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_DIFF_ALBEDO      (5 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_SPEC_ALBEDO      (6 << 17 | FLAGS_DEBUG)

// Outputs
#define FLAGS_DEBUG_OUT_SIGNAL_SPLIT    (7 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_LINEAR_DEPTH    (8 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_MOTION          (9 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_NORMALS         (10 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_SPEC_ALBEDO     (11 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_DIFF_ALBEDO     (12 << 17 | FLAGS_DEBUG)

#define FLAGS_DEBUG_OUT_DEPTH_DELTA     (13 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_NORM_DEPTH          (14 << 17 | FLAGS_DEBUG)

#define FLAGS_DEBUG_ALBEDO_OVERSHOOT    (15 << 17 | FLAGS_DEBUG)

#define FLAGS_DEBUG_FLOOR_VARIANCE      (16 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_FLOOR_COLOR         (17 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_RAW_INDIRECT_SPEC   (18 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_EFFECTIVE_ROUGHNESS (19 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_RAW_ROUGHNESS       (20 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_EMISSIVE_MASK       (21 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_APPLIED_ROUGHNESS_FLOOR (22 << 17 | FLAGS_DEBUG)

// DLSS-RR Inputs
Texture2D<half3> InColor : register(t0); // RGB - NVSDK_NGX_Parameter_Color
Texture2D<float> InDepth : register(t1); // R - NVSDK_NGX_Parameter_Depth - hardware or linear - inverted or not
Texture2D<float3> InMotionVectors : register(t2); // RG - NVSDK_NGX_Parameter_MotionVectors
Texture2D<float4> InNormals : register(t3); // RGB: Normals, A: Roughness (Optional) - NVSDK_NGX_Parameter_GBuffer_Normals
Texture2D<float> InRoughness : register(t4); // R - May be packed in normals. NVSDK_NGX_Parameter_GBuffer_Roughness
Texture2D<float> InSpecHitDist : register(t5); // R - NVSDK_NGX_Parameter_DLSSD_SpecularHitDistance
Texture2D<half3> InDiffAlbedo : register(t6); // RGB - NVSDK_NGX_Parameter_GBuffer_DiffuseAlbedo
Texture2D<half3> InSpecAlbedo : register(t7); // RGB - NVSDK_NGX_Parameter_GBuffer_SpecularAlbedo
Texture2D<half> InBiasMask : register(t8);

Texture2D<half4> InFloorColor : register(t9);

// RR 1.2 typed signals. Resource order matches Conversion::SignalResources.
RWTexture2D<half4> OutIndirectSpecular : register(u0); // RGB: demodulated radiance, A: hit distance
RWTexture2D<half4> OutDirectDiffuse : register(u1);    // RGB: demodulated radiance, A: diffuse hit-distance fallback

// ffxDispatchDescDenoiser
RWTexture2D<half4> OutMotion : register(u2); // RG: PreviousUV - CurrentUV, B: PreviousLinearDepth - CurrentLinearDepth
RWTexture2D<half4> OutNormals : register(u3); // RG: Octahedrally encoded normals, B: Linear Roughness, A: Material Type (Optional)
RWTexture2D<half4> OutSpecAlbedo : register(u4); // RGB: Specular Albedo, A: dot(Normal, ViewDir)
RWTexture2D<half4> OutDiffAlbedo : register(u5); // RGB: Diffuse Albedo, A: Metalness (not provided)

RWTexture2D<half4> OutSkipSignal : register(u6);

cbuffer CB_Packing : register(b0)
{
    float4x4 InvViewMatrix; // DLSSD WorldToView^-1
    float4x4 InvProjMatrix; // DLSSD ViewToClip^-1
    float4x4 PrevViewMatrix; // DLSSD WorldToView from last frame
    
    float4 DstTexSize; // Resolution of inputs
    
    float NearPlane;
    float FarPlane;   
    
    float FloorIsolation;
    float RoughnessFloor;
    float RoughnessFloorDistance;

    uint Flags;
    float2 Padding;
};

bool IsSet(uint mask) { return (Flags & mask) == mask; }
uint GetDebugMode() { return (Flags & FLAGS_DEBUG_MODE_MASK); }

float3 GetViewSpacePos(const int2 px)
{
    float inDepth = InDepth[px];
    const float2 uv = (float2(px) + 0.5) * DstTexSize.zw;
    const float depthSign = IsSet(FLAGS_NEGATIVE_VIEW_DEPTH) ? -1.0f : 1.0f;
    float3 viewSpacePos;

    [branch]
    if (IsSet(FLAGS_LINEAR_DEPTH))
    {
        // InDepth is the signed-linear output of FloorSeed. Scale the complete
        // view ray so XY and Z describe one internally consistent position.
        inDepth = depthSign * clamp(abs(inDepth), NearPlane, FarPlane);
        viewSpacePos = InvProjectPosition(float3(uv, 1.0f), InvProjMatrix);
        const float safeRayZ = (viewSpacePos.z < 0.0f)
            ? min(viewSpacePos.z, -1e-6f)
            : max(viewSpacePos.z, 1e-6f);
        viewSpacePos *= inDepth / safeRayZ;
        viewSpacePos.z = inDepth;
    }
    else
    {
        // Retained as a defensive fallback for direct hardware-depth callers.
        viewSpacePos = InvProjectPosition(float3(uv, inDepth), InvProjMatrix);
        const float signedDepth = depthSign * clamp(abs(viewSpacePos.z), NearPlane, FarPlane);
        const float safeViewZ = (viewSpacePos.z < 0.0f)
            ? min(viewSpacePos.z, -1e-6f)
            : max(viewSpacePos.z, 1e-6f);
        viewSpacePos *= signedDepth / safeViewZ;
        viewSpacePos.z = signedDepth;
    }

    return viewSpacePos;
}

// Main Kernel
//
[RootSignature(MainRS)]
[numthreads(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y, 1)]
void CSMain(uint3 groupID : SV_GroupID, uint3 gtID : SV_GroupThreadID)
{
    const uint2 px = groupID.xy * s_ThreadGroupSize + gtID.xy;
    
    if (px.x >= DstTexSize.x || px.y >= DstTexSize.y)
        return;

    // Albedo / reflectance
    //
    // Zeroed albedos are unusable sentinels and must be skipped.
    // Depth values at the far plane indicate a skybox or other skippable content.
    //
    // DLSS-RR specular albedo is hemispherical specular reflectance at (NoV, roughness).
    // Diffuse albedo is the diffuse component of reflectance.     
    float3 specReflectance = GetSafeFP16(InSpecAlbedo[px].rgb);
    float3 diffAlbedo = GetSafeFP16(InDiffAlbedo[px].rgb);
    
    const float totalAlbedo = dot(specReflectance.rgb + diffAlbedo.rgb, 1.0f);
    const float isEmissive = (totalAlbedo > 5.9f);   
    diffAlbedo.rgb *= (1.0f - isEmissive);
    specReflectance.rgb = lerp(specReflectance.rgb, 0.1f, isEmissive);
    
    // Clamp albedo
    const float3 albedoOvershoot = max((specReflectance.rgb + diffAlbedo.rgb) - 1.0f, 0.0f);
    specReflectance.rgb = saturate(specReflectance.rgb - albedoOvershoot);
    diffAlbedo.rgb -= max((specReflectance.rgb + diffAlbedo.rgb) - 1.0f, 0.0f);
    specReflectance.rgb = max(specReflectance.rgb, 1e-4f);
    diffAlbedo.rgb = max(diffAlbedo.rgb, 1e-4f);
    
    // Denoiser input color and floor residual
    const float3 rawColor = GetSafeFP16(InColor[px].rgb);
    float4 floorColor = InFloorColor[px];  
    const float rawLuma = GetLuminance(rawColor);
    const float floorLuma = GetLuminance(floorColor.rgb);
    floorColor.a = floorLuma;

    // Floor color blending
    //
    // Diffuse dominant surfaces are relatively well behaved.
    const float avgSpecular = dot(specReflectance.rgb, 0.33f);
    const float diffuseDominance = smoothstep(0.08f, 0.0f, avgSpecular);
    const float similarityThreshold = lerp(0.5f, 0.2f, diffuseDominance);
    
    // Clamp floor to minimum and blend in raw values where similar to preserve microcontrast.
    const float floorSimilarity = GetRelativeSimilarity(floorLuma, rawLuma, similarityThreshold);
    floorColor.rgb = FloorIsolation * lerp(floorColor.rgb, rawColor, saturate(floorSimilarity));
    floorColor.rgb = min(rawColor, floorColor.rgb);
    const float3 denoiserColor = rawColor - floorColor.rgb;

    // Depth - full position needed for reprojected depth delta
    const float3 viewSpacePos = GetViewSpacePos(px);
    const float compressedDepth = log(abs(viewSpacePos.z) + 1.0f) / log(FarPlane + 1.0f);
    
    if (((compressedDepth < 0.99f) && totalAlbedo > 1e-2f) || IsSet(FLAGS_DEBUG))
    {        
        // Normals - FSR-RR requries world normals.
        //
        // [TODO!] DLSS-RR normals may be in view or world space. They will need to be transformed to account
        // for both configurations. Cyberpunk happens to use world normals, thankfully.
        float4 worldSurfaceNormal = InNormals[px];        
        const float2 octNormal = OctahedralEncode(worldSurfaceNormal.rgb);
        const float materialType = 0.0f;
    
        // DLSS-RR provides 3D normals
        // Linear roughness optionally included in the A channel, or in a separate single-channel 
        // buffer (InRoughness).
        const float rawRoughness = saturate(
            IsSet(FLAGS_PACKED_ROUGHNESS) ? worldSurfaceNormal.a : InRoughness[px]);
        const float inputRoughness = rawRoughness * (1.0f - isEmissive);
        const float appliedRoughnessFloor =
            saturate(RoughnessFloor) * step(abs(viewSpacePos.z), RoughnessFloorDistance);
        // Preserve the legacy emissive zero when the adjustment is disabled, but
        // allow a positive floor to stabilize emissive/smooth surfaces such as displays.
        const float roughness = max(inputRoughness, appliedRoughnessFloor);
        
        // Output: RG=OctNormal, B=Roughness, A=MaterialID
        OutNormals[px] = GetSafeFP16(float4(octNormal, roughness, materialType));
   
        // Motion Vectors & Depth Delta
        //
        // Find the current pixel in world space and calculate movement in view space
        const float3 worldSpacePos = mul(InvViewMatrix, float4(viewSpacePos, 1.0f)).xyz;
        float3 prevViewSpacePos = mul(PrevViewMatrix, float4(worldSpacePos, 1.0f)).xyz;
            
        // FSR-RR requires Linear Depth Delta in Blue channel
        const float2 motionIn = InMotionVectors[px].rg; // RG: Pixel Movement
        const float depthDelta = (prevViewSpacePos.z - viewSpacePos.z);
        const float3 motionOut = float3(motionIn, depthDelta);
        OutMotion[px] = half4(GetSafeSignedFP16(motionOut), 0.0f);

        const float3 specWeight = saturate(specReflectance.rgb);
        const float3 diffWeight = saturate(diffAlbedo.rgb);
        const float3 rcpTotalWeight = rcp(diffWeight + specWeight);
        const float3 specularColor = denoiserColor * (specWeight * rcpTotalWeight);
        const float3 diffuseColor = denoiserColor - specularColor;

        const half3 demodSpecular = GetSafeFP16(specularColor / specReflectance.rgb);
        const half3 demodDiffuse = GetSafeFP16(diffuseColor / diffAlbedo.rgb);

        // Anything that cannot survive modulation and FP16 clamping remains in the skip signal.
        const float3 remodColor = (demodSpecular * specReflectance.rgb) + (demodDiffuse * diffAlbedo.rgb);
        floorColor.rgb += max(0.0f, denoiserColor - remodColor);

        // RR 1.2 indirect-specular alpha carries the ray hit distance. FP16_MAX represents
        // a miss when DLSS-RR does not expose this optional input.
        const half hitDist = IsSet(FLAGS_HAS_SPEC_HIT_DISTANCE)
            ? half(clamp(InSpecHitDist[px], 0.0f, 65504.0f))
            : half(65504.0f);

        [branch]
        if (!IsSet(FLAGS_DEBUG))
        {
            OutIndirectSpecular[px] = half4(demodSpecular, hitDist);
            OutDirectDiffuse[px] = half4(demodDiffuse, s_MissingDiffuseHitDistance);
        }

        // May be for better perceptual encoding efficiency in some configurations
        [branch]
        if (!IsSet(FLAGS_NON_GAMMA_ALBEDO))
        {
            specReflectance = sqrt(specReflectance);
            diffAlbedo = sqrt(diffAlbedo);
        }
        
        OutSpecAlbedo[px] = half4(GetSafeFP16(specReflectance), 0.0f);
        OutDiffAlbedo[px] = half4(GetSafeFP16(diffAlbedo), 0.0f);
        OutSkipSignal[px] = half4(GetSafeFP16(floorColor));
        
        [branch]
        if (IsSet(FLAGS_DEBUG))
        {
            float3 debugColor = float3(0, 0, 0);
        
            switch (GetDebugMode())
            {
                // Inputs
                case FLAGS_DEBUG_IN_SPEC_HIT_DIST:
                    // A saturated magenta pixel is an encoded miss. Otherwise,
                    // logarithmic scaling keeps both nearby and distant hits
                    // visible without wrapping the color range.
                    debugColor = (hitDist >= 65500.0f)
                        ? float3(1.0f, 0.0f, 1.0f)
                        : TurboColormap(saturate(log2(max((float)hitDist, 0.0f) + 1.0f) / 16.0f));
                    break;
                
                case FLAGS_DEBUG_NORM_DEPTH:
                    debugColor = TurboColormap(compressedDepth);
                    break;
                
                case FLAGS_DEBUG_IN_MOTION:
                    debugColor = VisualizeMotionVec(motionIn * DstTexSize.xy, 0.1f);
                    break;
                
                case FLAGS_DEBUG_IN_NORMALS:
                    debugColor = worldSurfaceNormal.rgb * 0.5 + 0.5;
                    break;
                
                case FLAGS_DEBUG_IN_ROUGHNESS:
                    debugColor = inputRoughness;
                    break;
                
                case FLAGS_DEBUG_IN_DIFF_ALBEDO:
                    debugColor = InDiffAlbedo[px];
                    break;
                
                case FLAGS_DEBUG_IN_SPEC_ALBEDO:
                    debugColor = InSpecAlbedo[px];
                    break;
                // Outputs
                case FLAGS_DEBUG_OUT_SIGNAL_SPLIT:
                    debugColor = demodSpecular + demodDiffuse;
                    break;
                
                case FLAGS_DEBUG_OUT_LINEAR_DEPTH:
                    debugColor = TurboColormap(frac(abs(viewSpacePos.z) * 0.1));
                    break;
                
                case FLAGS_DEBUG_OUT_MOTION:
                    debugColor = VisualizeMotionVec(motionOut.xy * DstTexSize.xy, 0.1f);
                    break;

                case FLAGS_DEBUG_OUT_DEPTH_DELTA:
                    debugColor = VisualizeSignedDiff(motionOut.z, 5.0f);
                    break;
                
                case FLAGS_DEBUG_OUT_NORMALS:
                    debugColor = OctahedralDecode(octNormal) * 0.5 + 0.5;
                    break;

                case FLAGS_DEBUG_OUT_SPEC_ALBEDO:
                    debugColor = specReflectance.rgb;
                    break;
                
                case FLAGS_DEBUG_OUT_DIFF_ALBEDO:
                    debugColor = diffAlbedo.rgb;
                    break;

                case FLAGS_DEBUG_FLOOR_VARIANCE:
                    debugColor = TurboColormap(InFloorColor[px].a);
                    break;
                
                case FLAGS_DEBUG_FLOOR_COLOR:
                    debugColor = InFloorColor[px].rgb;
                    break;

                case FLAGS_DEBUG_RAW_INDIRECT_SPEC:
                    // Match the denoised indirect-specular debug view by
                    // remodulating the RR input into scene-radiance space.
                    debugColor = demodSpecular * specReflectance.rgb;
                    break;

                case FLAGS_DEBUG_EFFECTIVE_ROUGHNESS:
                    debugColor = roughness;
                    break;

                case FLAGS_DEBUG_RAW_ROUGHNESS:
                    debugColor = rawRoughness;
                    break;

                case FLAGS_DEBUG_EMISSIVE_MASK:
                    debugColor = isEmissive;
                    break;
                case FLAGS_DEBUG_APPLIED_ROUGHNESS_FLOOR:
                    debugColor = (RoughnessFloor > 0.0f)
                        ? TurboColormap(saturate(appliedRoughnessFloor / RoughnessFloor))
                        : 0.0f;
                    break;

                case FLAGS_DEBUG_ALBEDO_OVERSHOOT:
                    debugColor = albedoOvershoot;
                    break;
                
                default:
                    debugColor = demodSpecular + demodDiffuse;
                    break;
            }
        
            OutIndirectSpecular[px] = half4(debugColor, 1.0f);
        }
    }
    else // Skip
    {
        OutNormals[px] = 0.0f;
        OutSpecAlbedo[px] = 0.0f;
        OutDiffAlbedo[px] = 0.0f;
        OutIndirectSpecular[px] = half4(0.0f, 0.0f, 0.0f, 65504.0f);
        OutDirectDiffuse[px] = half4(0.0f, 0.0f, 0.0f, s_MissingDiffuseHitDistance);
        OutSkipSignal[px] = half4(rawColor, rawLuma);
    }
}
