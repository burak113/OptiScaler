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
#define FLAGS_ENABLE_SPEC_RAY_LENGTH    (1 << 3)
#define FLAGS_IS_RIGHT_HANDED           (1 << 4)

// Debug Flags
#define FLAGS_DEBUG               (1 << 16)
#define FLAGS_DEBUG_MODE_MASK     (0xFF << 16)

// Inputs
#define FLAGS_DEBUG_IN_SPEC_HIT_DIST  (1 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_DEPTH          (2 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_MOTION         (3 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_NORMALS        (4 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_ROUGHNESS      (5 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_DIFF_ALBEDO    (6 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_SPEC_ALBEDO    (7 << 17 | FLAGS_DEBUG)

// Outputs
#define FLAGS_DEBUG_OUT_FUSED_ALBEDO  (8 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_LINEAR_DEPTH  (9 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_MOTION        (10 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_NORMALS       (11 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_SPEC_ALBEDO   (12 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_DIFF_ALBEDO   (13 << 17 | FLAGS_DEBUG)

#define FLAGS_DEBUG_OUT_DEPTH_DELTA     (14 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_NORM_DOT_VIEW   (15 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_METALICITY      (16 << 17 | FLAGS_DEBUG)

#define FLAGS_DEBUG_EDGE_MASK       (17 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_COLOR_MASK      (18 << 17 | FLAGS_DEBUG)

// DLSS-RR Inputs
Texture2D<float4> InColor : register(t0); // RGB - NVSDK_NGX_Parameter_Color
Texture2D<float> InDepth : register(t1); // R - NVSDK_NGX_Parameter_Depth - hardware or linear - inverted or not
Texture2D<float3> InMotionVectors : register(t2); // RG - NVSDK_NGX_Parameter_MotionVectors
Texture2D<float4> InNormals : register(t3); // RGB: Normals, A: Roughness (Optional) - NVSDK_NGX_Parameter_GBuffer_Normals
Texture2D<float> InRoughness : register(t4); // R - May be packed in normals. NVSDK_NGX_Parameter_GBuffer_Roughness
Texture2D<float> InSpecHitDist : register(t5); // R - NVSDK_NGX_Parameter_DLSSD_SpecularHitDistance
Texture2D<float3> InDiffuseAlbedo : register(t6); // RGB - NVSDK_NGX_Parameter_GBuffer_DiffuseAlbedo
Texture2D<float3> InSpecularAlbedo : register(t7); // RGB - NVSDK_NGX_Parameter_GBuffer_SpecularAlbedo
Texture2D<float> InBiasMask : register(t8);

// FSR-RR
//
// ffxDispatchDescDenoiserInput1Signal
RWTexture2D<float4> OutRadiance : register(u0); // RGB: Combined noisy color A: Specular Ray Length
RWTexture2D<float4> OutFusedAlbedo : register(u1); // RGB: max(specularAlbedo, diffuseAlbedo) A: NoV 

// ffxDispatchDescDenoiser
RWTexture2D<float4> OutMotion : register(u2); // RG: Standard TSR motion vectors, B: Linear Depth Delta (CurrentLinearDepth - PrevLinearDepth)
RWTexture2D<float4> OutNormals : register(u3); // RG: Octahedrally encoded normals, B: Linear Roughness, A: Material Type (Optional)
RWTexture2D<float4> OutSpecAlbedo : register(u4); // RGB: Specular Albedo, A: dot(Normal, ViewDir)
RWTexture2D<float4> OutDiffAlbedo : register(u5); // RGB: Diffuse Albedo, A: Metalness (heuristic approximate)
RWTexture2D<float> OutLinearDepth : register(u6);

RWTexture2D<float4> OutSkipSignal : register(u7);

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
    const float3 ndcPos = float3(UVToNDC(uv), inDepth);
    float3 viewSpacePos = InvProjectPosition(ndcPos, InvProjMatrix);
    viewSpacePos.z = clamp(zSign * viewSpacePos.z, NearPlane, FarPlane);
    
    // Left handed view space
    OutLinearDepth[px] = viewSpacePos.z;
    
    // Color and albedo gradient analysis
    // Prepare rough color luma
    const float3 color = InColor[px].rgb;
    float4 specAlbedo = float4(InSpecularAlbedo[px] + 0.01f, 0.0f);
    float4 diffAlbedo = float4(InDiffuseAlbedo[px] + 0.01f, 0.0f);
    float4 fusedAlbedo = float4(max(specAlbedo.rgb, diffAlbedo.rgb), 0.0f);
    
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
    
        // DLSS-RR provides 3D normals with roughnes optionally included in the A channel, or
        // in a separate single-channel buffer (InRoughness).
        float roughness = IsSet(FLAGS_PACKED_ROUGHNESS) ? worldSurfaceNormal.a : InRoughness[px];
    
        // Output: RG=OctNormal, B=Roughness, A=MaterialID
        OutNormals[px] = float4(octNormal, roughness, materialType);
   
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
        OutMotion[px] = float4(motionOut, 0.0f);

        // Calculate NoV (Dot(Normal, View))
        //
        const float3 cameraPos = float3(InvViewMatrix._m03, InvViewMatrix._m13, InvViewMatrix._m23);
        // Line from camera to the clip pos
        const float3 viewDir = normalize(cameraPos - worldSpacePos);
        const float NoV = saturate(dot(worldSurfaceNormal.rgb, viewDir));

        // Secondary albedo packing
        //
        // FSR-RR expects metalness in diffuse alpha
        const float metalness = EstimateMetalness(diffAlbedo.rgb, specAlbedo.rgb);
        specAlbedo.a = NoV;
        diffAlbedo.a = metalness;  
        fusedAlbedo.a = NoV;
        
        // May be for better perceptual encoding efficiency in some configurations
        [branch]
        if (!IsSet(FLAGS_NON_GAMMA_ALBEDO))
        {
            specAlbedo = sqrt(specAlbedo);
            diffAlbedo = sqrt(diffAlbedo);
            fusedAlbedo = sqrt(fusedAlbedo);
        }
        
        // Primary radiance packing - Mode 1 Signal
        const float3 demodColor = color / fusedAlbedo.rgb;
        
        // FSR-RR expects NoV in specular alpha
        OutSpecAlbedo[px] = specAlbedo;
        OutDiffAlbedo[px] = diffAlbedo;
        OutFusedAlbedo[px] = fusedAlbedo;
        OutSkipSignal[px] = float4(color, 0.0f);

        // Experimental. Cannot be used if the input contains both diffuse and specular lighting.
        // Supporting specular motion tracking may require Mode 2 denoising.
        float hitDist = 0.0f;

        [branch]
        if (IsSet(FLAGS_ENABLE_SPEC_RAY_LENGTH))
            hitDist = InSpecHitDist[px];
    
        [branch]
        if (!IsSet(FLAGS_DEBUG))
        {
            OutRadiance[px] = float4(demodColor, hitDist);
        }
        else
        {
            float3 debugColor = float3(0, 0, 0);
            const uint debugMode = GetDebugMode();
        
            switch (debugMode)
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
                    debugColor = InDiffuseAlbedo[px];
                    break;
                
                case FLAGS_DEBUG_IN_SPEC_ALBEDO:
                    debugColor = InSpecularAlbedo[px];
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
                    debugColor = metalness;
                    break;
                
                case FLAGS_DEBUG_OUT_SPEC_ALBEDO:
                    debugColor = specAlbedo.rgb;
                    break;
                
                case FLAGS_DEBUG_OUT_DIFF_ALBEDO:
                    debugColor = diffAlbedo.rgb;
                    break;
                
                case FLAGS_DEBUG_EDGE_MASK:
                    debugColor = isEdge;
                    break;

                case FLAGS_DEBUG_COLOR_MASK:
                    debugColor = transparencyMask;
                    break;
                
                default:
                    debugColor = demodColor;
                    break;
            }
        
            OutRadiance[px] = float4(debugColor, 1.0f);
        }
    }
    else // Skip
    {
        OutNormals[px] = 0.0f;
        OutSpecAlbedo[px] = 0.0f;
        OutDiffAlbedo[px] = 0.0f;
        OutFusedAlbedo[px] = 0.0f;
        OutRadiance[px] = 0.0f;
        OutSkipSignal[px] = float4(color, 1.0f);
    }
}