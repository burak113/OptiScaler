// FSR-RR Conversion & Packing Shader
#include "FSRDPreprocessCommon.hlsli"

#define THREAD_GROUP_SIZE_X 8
#define THREAD_GROUP_SIZE_Y 8
#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 9), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 8), visibility = SHADER_VISIBILITY_ALL), "

// Flags
#define FLAGS_NON_GAMMA_ALBEDO          (1 << 0)
#define FLAGS_INF_FAR_PLANE             (1 << 1)
#define FLAGS_PACKED_ROUGHNESS          (1 << 2)
#define FLAGS_MODE_2_SIGNAL             (1 << 3)
#define FLAGS_IS_RIGHT_HANDED           (1 << 4)

// Debug Flags
#define FLAGS_DEBUG                     (1 << 16)
#define FLAGS_DEBUG_MODE_MASK           (0xFF << 16)

// Inputs
#define FLAGS_DEBUG_IN_SPEC_HIT_DIST    (1 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_DEPTH            (2 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_MOTION           (3 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_NORMALS          (4 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_ROUGHNESS        (5 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_DIFF_ALBEDO      (6 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_SPEC_ALBEDO      (7 << 17 | FLAGS_DEBUG)

// Outputs
#define FLAGS_DEBUG_OUT_FUSED_ALBEDO    (8 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_LINEAR_DEPTH    (9 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_MOTION          (10 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_NORMALS         (11 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_SPEC_ALBEDO     (12 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_DIFF_ALBEDO     (13 << 17 | FLAGS_DEBUG)

#define FLAGS_DEBUG_OUT_DEPTH_DELTA     (14 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_NORM_DOT_VIEW   (15 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_METALICITY      (16 << 17 | FLAGS_DEBUG)

#define FLAGS_DEBUG_COLOR_MASK          (17 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_ALBEDO_OVERSHOOT    (18 << 17 | FLAGS_DEBUG)

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

// FSR-RR - ffxDispatchDescDenoiserInput1Signal or ffxDispatchDescDenoiserInput2Signals
//
// Mode 1: RGB: Noisy fused lighting
// Mode 2: RGB: Noisy specular lighting A: Specular Ray Length
RWTexture2D<half4> OutSignal1 : register(u0); 

// Mode 1: RGB Fused Albedo: max(specularAlbedo, diffuseAlbedo) A: NoV
// Mode 2: RGB: Noisy diffuse lighting for Mode 2
RWTexture2D<half4> OutSignal2 : register(u1);

// ffxDispatchDescDenoiser
RWTexture2D<half4> OutMotion : register(u2); // RG: Standard TSR motion vectors, B: Linear Depth Delta (CurrentLinearDepth - PrevLinearDepth)
RWTexture2D<half4> OutNormals : register(u3); // RG: Octahedrally encoded normals, B: Linear Roughness, A: Material Type (Optional)
RWTexture2D<half4> OutSpecAlbedo : register(u4); // RGB: Specular Albedo, A: dot(Normal, ViewDir)
RWTexture2D<half4> OutDiffAlbedo : register(u5); // RGB: Diffuse Albedo, A: Metalness (heuristic approximate)
RWTexture2D<float> OutLinearDepth : register(u6);

RWTexture2D<half4> OutSkipSignal : register(u7);

cbuffer CB_Packing : register(b0)
{
    float4x4 InvViewMatrix; // DLSSD WorldToView^-1
    float4x4 InvProjMatrix; // DLSSD ViewToClip^-1
    float4x4 InvViewProjMatrix; // DLSSD (WorldToView x ViewToClip)^-1
    float4x4 PrevViewMatrix; // DLSSD WorldToView from last frame
    
    float2 RenderSize; // Resolution of inputs
    float2 RenderSizeInv; // 1.0 / Resolution
    
    float NearPlane;
    float FarPlane;
    
    uint Flags;
};

bool IsSet(uint mask) { return (Flags & mask) == mask; }
uint GetDebugMode() { return (Flags & FLAGS_DEBUG_MODE_MASK); }

float AnalyzeEdges(const int2 px, const float3 centerColor)
{
    // Load luma for 3x3 area - find avg and extrema
    float lum[3][3];
    const float lumCenter = dot(centerColor, 1.0f);
    float minLum = min(1e7f, lumCenter);
    float maxLum = max(1e-7f, lumCenter);
    lum[1][1] = lumCenter;

    // This really needs to be replaced with LDS
    [unroll]
    for (int y = -1; y <= 1; ++y)
    {
        [unroll]
        for (int x = -1; x <= 1; ++x)
        {
            if (x != 0 || y != 0)
            {
                const float currentLum = dot(InColor[px + int2(x, y)].rgb, 1.0f);
                minLum = min(minLum, currentLum);
                maxLum = max(maxLum, currentLum);
                lum[x + 1][y + 1] = currentLum;
            }
        }
    }

    // Sobel filter edge detection
    float2 gradient = 0.0f;  
    gradient.x = -(lum[0][0] + (2.0f * lum[0][1]) + lum[0][2])
                 +(lum[2][0] + (2.0f * lum[2][1]) + lum[2][2]);
    
    gradient.y = -(lum[0][0] + (2.0f * lum[1][0]) + lum[2][0])
                 +(lum[0][2] + (2.0f * lum[1][2]) + lum[2][2]);
    
    const float localContrast = maxLum - minLum;
    const float linearity = saturate(length(gradient) * rcp(localContrast * 4.0f + 1e-2f));

    return float(linearity > 0.8f);
}

// Main Kernel
//
[RootSignature(MainRS)]
[numthreads(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y, 1)]
void CSMain(uint3 id : SV_DispatchThreadID, uint3 gID : SV_GroupThreadID)
{
    if (id.x >= RenderSize.x || id.y >= RenderSize.y)
        return;

    const int2 px = int2(id.xy);
    const float2 uv = (float2(id.xy) + 0.5) * RenderSizeInv;
    const float zSign = IsSet(FLAGS_IS_RIGHT_HANDED) ? -1.0f : 1.0f;

    // Depth delta calculation from denoiser prepass sample shader
    // Assuming hardware depth
    const float inDepth = InDepth[px];
    float3 viewSpacePos = InvProjectPosition(float3(uv, inDepth), InvProjMatrix);
    viewSpacePos.z = clamp(zSign * viewSpacePos.z, NearPlane, FarPlane);
    
    // Left handed view space
    OutLinearDepth[px] = viewSpacePos.z;
    
    // Color and albedo gradient analysis
    // Prepare rough color luma
    const float3 color = GetSafeFP16(InColor[px].rgb);
    
    const float isEdge = AnalyzeEdges(px, color);
    const float transparencyBias = InBiasMask[px];
    const float transparencyMask = (isEdge * transparencyBias);
    
    // If a sample is at the far plane, it's probably a miss
    if (((abs(viewSpacePos.z - FarPlane) > 1e-2f) && (transparencyMask < 0.9f)) || IsSet(FLAGS_DEBUG))
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
        const float roughness = IsSet(FLAGS_PACKED_ROUGHNESS) ? worldSurfaceNormal.a : InRoughness[px];
    
        // Output: RG=OctNormal, B=Roughness, A=MaterialID
        OutNormals[px] = GetSafeFP16(float4(octNormal, roughness, materialType));
   
        // Motion Vectors & Depth Delta
        //
        // Find the current pixel in world space and calculate movement in view space
        const float3 worldSpacePos = mul(InvViewMatrix, float4(viewSpacePos, 1.0f)).xyz;
        float3 prevViewSpacePos = mul(PrevViewMatrix, float4(worldSpacePos, 1.0f)).xyz;
        prevViewSpacePos.z *= zSign;
        
        const float depthDelta = (viewSpacePos.z - prevViewSpacePos.z);
    
        // FSR-RR requires Linear Depth Delta in Blue channel
        const float2 motionIn = InMotionVectors[px].rg; // RG: Pixel Movement
        const float3 motionOut = float3(motionIn, depthDelta);
        OutMotion[px] = half4(motionOut, 0.0f);

        // Calculate NoV (Dot(Normal, View))
        //
        const float3 cameraPos = float3(InvViewMatrix._m03, InvViewMatrix._m13, InvViewMatrix._m23);
        // Line from camera to the clip pos
        const float3 toCameraDir = normalize(cameraPos - worldSpacePos);
        const float NoV = saturate(dot(worldSurfaceNormal.rgb, toCameraDir));

        // Secondary albedo packing
        //
        // FSR-RR expects metalness in diffuse alpha.
        // DLSS-RR specular albedo is hemispherical specular reflectance at (NoV, roughness).
        // Diffuse albedo is the diffuse component of reflectance.
        //
        // Zero albedo is physically implausible - investigate
        float4 specReflectance = float4(InSpecAlbedo[px], NoV);
        float4 diffAlbedo = float4(InDiffAlbedo[px], 0.0f);
                
        // Total albedo near or greater than 1 violate conservation of energy
        // May be sentinel value or bug
        const float3 albedoOvershoot = max((specReflectance.rgb + diffAlbedo.rgb) - 1.0f, 0.0f);
        specReflectance.rgb = saturate(specReflectance.rgb - albedoOvershoot);
        diffAlbedo.rgb -= max((specReflectance.rgb + diffAlbedo.rgb) - 1.0f, 0.0f);
        
        specReflectance.rgb = max(specReflectance.rgb, 1e-3f);
        diffAlbedo.rgb = max(diffAlbedo.rgb, 1e-3f);

        float hitDist = hitDist = 0.0f;
        float3 demodColor = 0.0f;
        float4 fusedAlbedo = 0.0f;
        
        [branch]
        if (IsSet(FLAGS_MODE_2_SIGNAL)) // Primary radiance packing - Mode 2 Signal
        {          
            const float3 specWeight = saturate(specReflectance.rgb);
            const float3 diffWeight = saturate(diffAlbedo.rgb);
            const float3 rcpTotalWeight = rcp(diffWeight + specWeight);

            const float3 specularColor = color * (specWeight * rcpTotalWeight);
            const float3 diffuseColor = color - specularColor;

            const float3 demodSpecular = specularColor / specReflectance.rgb;
            const float3 demodDiffuse = diffuseColor / diffAlbedo.rgb;

            // Mask out specular tracking if the surface isn't smooth enough
            hitDist = InSpecHitDist[px] * (roughness < 0.2f);
            
            [branch]
            if (!IsSet(FLAGS_DEBUG))
            {
                OutSignal1[px] = GetSafeFP16(float4(demodSpecular, hitDist));
                OutSignal2[px] = GetSafeFP16(float4(demodDiffuse, 0.0f));
            }
            else
                demodColor = demodDiffuse + demodSpecular;
        }
        else // Primary radiance packing - Mode 1 Signal
        {           
            fusedAlbedo = float4(max(specReflectance.rgb, diffAlbedo.rgb), NoV);
            demodColor = color / fusedAlbedo.rgb;
            
            [branch]
            if (!IsSet(FLAGS_NON_GAMMA_ALBEDO))
                fusedAlbedo = sqrt(fusedAlbedo);
            
            [branch]
            if (!IsSet(FLAGS_DEBUG))
            {
                OutSignal1[px] = GetSafeFP16(float4(demodColor, hitDist));
                OutSignal2[px] = GetSafeFP16(fusedAlbedo);
            }
        }
        
        // May be for better perceptual encoding efficiency in some configurations
        [branch]
        if (!IsSet(FLAGS_NON_GAMMA_ALBEDO))
        {
            specReflectance = sqrt(specReflectance);
            diffAlbedo = sqrt(diffAlbedo);
        }
        
        // FSR-RR expects NoV in specular alpha
        OutSpecAlbedo[px] = GetSafeFP16(specReflectance);
        OutDiffAlbedo[px] = GetSafeFP16(diffAlbedo);
        OutSkipSignal[px] = GetSafeFP16(float4(color, 0.0f));
        
        [branch]
        if (IsSet(FLAGS_DEBUG))
        {
            float3 debugColor = float3(0, 0, 0);
        
            switch (GetDebugMode())
            {
                // Inputs
                case FLAGS_DEBUG_IN_SPEC_HIT_DIST:
                    debugColor = TurboColormap(frac(hitDist * 0.1f));
                    break;
                
                case FLAGS_DEBUG_IN_DEPTH:
                    debugColor = TurboColormap(frac(inDepth * 10.0)); // Hardware depth bands
                    break;
                
                case FLAGS_DEBUG_IN_MOTION:
                    debugColor = VisualizeMotionVec(motionIn * RenderSize, 0.1f);
                    break;
                
                case FLAGS_DEBUG_IN_NORMALS:
                    debugColor = worldSurfaceNormal.rgb * 0.5 + 0.5;
                    break;
                
                case FLAGS_DEBUG_IN_ROUGHNESS:
                    debugColor = roughness;
                    break;
                
                case FLAGS_DEBUG_IN_DIFF_ALBEDO:
                    debugColor = InDiffAlbedo[px];
                    break;
                
                case FLAGS_DEBUG_IN_SPEC_ALBEDO:
                    debugColor = InSpecAlbedo[px];
                    break;
                // Outputs
                case FLAGS_DEBUG_OUT_FUSED_ALBEDO:
                    debugColor = fusedAlbedo.rgb;
                    break;
                
                case FLAGS_DEBUG_OUT_LINEAR_DEPTH:
                    debugColor = TurboColormap(frac(viewSpacePos.z * 0.1));
                    break;
                
                case FLAGS_DEBUG_OUT_MOTION:
                    debugColor = VisualizeMotionVec(motionOut.xy * RenderSize, 0.1f);
                    break;

                case FLAGS_DEBUG_OUT_DEPTH_DELTA:
                    debugColor = VisualizeSignedDiff(motionOut.z, 5.0f);
                    break;
                
                case FLAGS_DEBUG_OUT_NORMALS:
                    debugColor = OctahedralDecode(octNormal) * 0.5 + 0.5;
                    break;
            
                case FLAGS_DEBUG_OUT_NORM_DOT_VIEW:
                    debugColor = float3(-NoV, NoV, 0.0f);
                    break;
            
                case FLAGS_DEBUG_OUT_METALICITY:
                    debugColor = 0.0f;
                    break;
                
                case FLAGS_DEBUG_OUT_SPEC_ALBEDO:
                    debugColor = specReflectance.rgb;
                    break;
                
                case FLAGS_DEBUG_OUT_DIFF_ALBEDO:
                    debugColor = diffAlbedo.rgb;
                    break;

                case FLAGS_DEBUG_COLOR_MASK:
                    debugColor = transparencyMask > 0.5f;
                    break;
                
                case FLAGS_DEBUG_ALBEDO_OVERSHOOT:
                    debugColor = albedoOvershoot;
                    break;
                
                default:
                    debugColor = demodColor;
                    break;
            }
        
            OutSignal1[px] = half4(debugColor, 1.0f);
        }
    }
    else // Skip
    {
        OutNormals[px] = 0.0f;
        OutSpecAlbedo[px] = 0.0f;
        OutDiffAlbedo[px] = 0.0f;
        OutSignal1[px] = 0.0f;
        OutSignal2[px] = 0.0f;
        OutSkipSignal[px] = half4(color, 1.0f);
    }
}