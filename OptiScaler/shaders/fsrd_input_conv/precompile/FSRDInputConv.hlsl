// FSR-RR Conversion & Packing Shader
#define THREAD_GROUP_SIZE_X 8
#define THREAD_GROUP_SIZE_Y 8
#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 8), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 7), visibility = SHADER_VISIBILITY_ALL), " \
    "StaticSampler(s0, " \
        "filter = FILTER_MIN_MAG_MIP_LINEAR, " \
        "addressU = TEXTURE_ADDRESS_CLAMP, " \
        "addressV = TEXTURE_ADDRESS_CLAMP, " \
        "addressW = TEXTURE_ADDRESS_CLAMP, " \
        "visibility = SHADER_VISIBILITY_ALL)"

// Flags
#define FLAGS_NON_GAMMA_ALBEDO    (1 << 0)
#define FLAGS_INF_FAR_PLANE       (1 << 1)
#define FLAGS_PACKED_ROUGHNESS    (1 << 2)

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

#define FLAGS_DEBUG_OUT_DEPTH_DELTA   (14 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_NORM_DOT_VIEW   (15 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_METALICITY   (16 << 17 | FLAGS_DEBUG)

// DLSS-RR Inputs
Texture2D<float4> InColor : register(t0); // RGB - NVSDK_NGX_Parameter_Color
Texture2D<float> InDepth : register(t1); // R - NVSDK_NGX_Parameter_Depth - hardware or linear - inverted or not
Texture2D<float3> InMotionVectors : register(t2); // RG - NVSDK_NGX_Parameter_MotionVectors
Texture2D<float4> InNormals : register(t3); // RGB: Normals, A: Roughness (Optional) - NVSDK_NGX_Parameter_GBuffer_Normals
Texture2D<float> InRoughness : register(t4); // R - May be packed in normals. NVSDK_NGX_Parameter_GBuffer_Roughness
Texture2D<float> InSpecHitDist : register(t5); // R - NVSDK_NGX_Parameter_DLSSD_SpecularHitDistance
Texture2D<float3> InDiffuseAlbedo : register(t6); // RGB - NVSDK_NGX_Parameter_GBuffer_DiffuseAlbedo
Texture2D<float3> InSpecularAlbedo : register(t7); // RGB - NVSDK_NGX_Parameter_GBuffer_SpecularAlbedo

// FSR-RR
//
// ffxDispatchDescDenoiserInput1Signal
RWTexture2D<float4> OutRadiance : register(u0); // RGB: Combined noisy color A: Specular Ray Length
RWTexture2D<float4> OutFusedAlbedo : register(u1); // RGB: max(specularAlbedo, diffuseAlbedo) A: NoV 

// ffxDispatchDescDenoiser
RWTexture2D<float4> OutMotion : register(u2); // RG: Standard TSR motion vectors, B: Linear Depth Delta (CurrentLinearDepth - PrevLinearDepth)
RWTexture2D<float4> OutNormals : register(u3); // RG: Octahedrally encoded normals, B: Linear Roughness, A: Material Type (Optional)
RWTexture2D<float4> OutSpecAlbedo : register(u4); // RGB: Specular Albedo, A: saturate(dot(Normal, ViewDir))
RWTexture2D<float4> OutDiffAlbedo : register(u5); // RGB: Diffuse Albedo, A: Metalness (heuristic approximate)
RWTexture2D<float> OutLinearDepth : register(u6);

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

SamplerState LinearSampler : register(s0);

bool IsSet(uint mask) { return (Flags & mask) == mask; }
uint GetDebugMode() { return (Flags & FLAGS_DEBUG_MODE_MASK); }

// Octahedral Encoding from AMD FSR-RR manual
float2 OctahedralEncode(float3 N)
{
    N.xy /= abs(N.x) + abs(N.y) + abs(N.z);
    const float2 k = sign(N.xy);
    const float s = saturate(-N.z);
    N.xy = lerp(N.xy, (1.0 - abs(N.yx)) * k, s);
    return N.xy * 0.5 + 0.5;
}

// Octahedral Decoding (For debug)
float3 OctahedralDecode(float2 UV)
{
    UV = UV * 2.0f - 1.0f;
    float3 N = float3(UV, 1.0f - abs(UV.x) - abs(UV.y));
    float t = saturate(-N.z);
    float2 s = sign(N.xy);
    N.xy += s * t;
    return normalize(N);
}

float2 UVToNDC(float2 coord)
{
    coord.y = (1 - coord.y);
    coord.xy = 2 * coord.xy - 1;
    return coord;
}

float3 InvProjectPosition(float3 coord, float4x4 mat)
{
    coord.xy = UVToNDC(coord.xy);
    float4 projected = mul(mat, float4(coord, 1.0f));
    projected.xyz /= projected.w;
    
    return projected.xyz;
}

// Metalness Heuristic (Since unavailable in DLSS inputs)
float EstimateMetalness(float3 diffuse, float3 specular)
{
    const float lumDiff = dot(diffuse, float3(0.2126, 0.7152, 0.0722));
    const float lumSpec = dot(specular, float3(0.2126, 0.7152, 0.0722));
    const float maxSpec = max(max(specular.r, specular.g), specular.b);
    const float minSpec = min(min(specular.r, specular.g), specular.b);
    float chromaSpec = (maxSpec > 0.0) ? (maxSpec - minSpec) / maxSpec : 0.0;

    // Smoothly decrease metalness as diffuse luminance increases
    float diffFactor = smoothstep(0.02, 0.005, lumDiff); // Inverted: high when lumDiff low
    // Increase metalness with specular luminance and chromaticity
    float specFactor = smoothstep(0.04, 0.6, lumSpec) * smoothstep(0.0, 0.3, chromaSpec);

    return diffFactor * specFactor;
}

// Visualization Helpers

// High contrast color map for visualizing normalized scalars
// Blue = 0 -> Cyan -> Green -> Orange -> Red = 1
float3 TurboColormap(float x)
{
    const float4 kRedVec4 = float4(0.13572138, 4.61539260, -42.66032258, 132.13108234);
    const float4 kGreenVec4 = float4(0.09140261, 2.19418839, 4.84296658, -14.18503333);
    const float4 kBlueVec4 = float4(0.10667330, 12.64194608, -60.58204836, 110.36276771);
    const float2 kRedVec2 = float2(-152.94239396, 59.28637943);
    const float2 kGreenVec2 = float2(4.27729857, 2.82956604);
    const float2 kBlueVec2 = float2(-89.90310912, 27.34824973);

    x = saturate(x);
    float4 v4 = float4(1.0, x, x * x, x * x * x);
    float2 v2 = v4.zw * v4.z;

    return float3(
        dot(v4, kRedVec4) + dot(v2, kRedVec2),
        dot(v4, kGreenVec4) + dot(v2, kGreenVec2),
        dot(v4, kBlueVec4) + dot(v2, kBlueVec2)
    );
}

// Visualizes 2D vectors as HSV. 
// Right = red, up = cyan/greenish, 
// left = cyan/blue, down = yellow/orange
float3 VisualizeMotionVec(float2 motion, float scalar)
{
    float angle = atan2(motion.y, motion.x);
    float mag = length(motion) * scalar;
    
    // Rough HSV to RGB
    float3 rgb = saturate(abs(fmod(angle / 6.2831853 + float3(0.0, 4.0, 2.0) / 6.0, 1.0) * 6.0 - 3.0) - 1.0);
    return rgb * saturate(mag);
}

float3 VisualizeSignedDiff(float val, float scale)
{
    // Red for negative, green for positive, black for zero
    float v = val * scale;
    return float3(saturate(-v), saturate(v), 0.0f);
}

// Main Kernel
//
[RootSignature(MainRS)]
[numthreads(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    if (id.x >= RenderSize.x || id.y >= RenderSize.y)
        return;

    const int2 px = int2(id.xy);
    const float2 uv = (float2(id.xy) + 0.5) * RenderSizeInv;

    // Normals - FSR-RR requries world normals
    //
    // DLSS-RR normals may be in view or world space. They will need to be transformed to account
    // for both configurations.
    float4 worldSurfaceNormal = InNormals[px];    
    const float2 octNormal = OctahedralEncode(worldSurfaceNormal.rgb);
    const float materialType = 0.0f;
    
    // DLSS-RR provides 3D normals with roughnes optionally included in the A channel, or
    // in a separate single-channel buffer (InRoughness).
    const float roughness = IsSet(FLAGS_PACKED_ROUGHNESS) ? worldSurfaceNormal.a : InRoughness[px];

    // Output: RG=OctNormal, B=Roughness, A=MaterialID
    OutNormals[px] = float4(octNormal, roughness, materialType);
    
    // Depth delta calculation from denoiser prepass sample shader
    // Assuming hardware depth
    const float inDepth = InDepth[px];
    const float3 ndcPos = float3(UVToNDC(uv), inDepth);
    float3 viewSpacePos = InvProjectPosition(ndcPos, InvProjMatrix);

    // Left handed view space
    OutLinearDepth[px] = viewSpacePos.z;
   
    // Motion Vectors & Depth Delta
    //
    // Find the current pixel in world space and calculate movement in view space
    const float3 worldSpacePos = mul(InvViewMatrix, float4(viewSpacePos, 1.0f)).xyz;
    const float3 prevViewSpacePos = mul(PrevViewMatrix, float4(worldSpacePos, 1.0f)).xyz;
    const float depthDelta = (prevViewSpacePos.z - viewSpacePos.z);
    
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
    float4 specAlbedo = float4(InSpecularAlbedo[px], 0.0f);
    float4 diffAlbedo = float4(InDiffuseAlbedo[px], 0.0f);

    // FSR-RR expects metalness in diffuse alpha
    const float metalness = EstimateMetalness(diffAlbedo.rgb, specAlbedo.rgb);
    specAlbedo.a = NoV;
    diffAlbedo.a = metalness;
    
    float4 fusedAlbedo = float4(max(specAlbedo.rgb, diffAlbedo.rgb), NoV);
    
    // Used for better perceptual encoding efficiency with high bit depth sources
    // Unnecessary if the secondaries use 8-bit color, which they usually do.
    [branch]
    if (!IsSet(FLAGS_NON_GAMMA_ALBEDO))
    {
        specAlbedo = sqrt(specAlbedo);
        diffAlbedo = sqrt(diffAlbedo);
        fusedAlbedo = sqrt(fusedAlbedo);
    }
    
    // FSR-RR expects NoV in specular alpha
    OutSpecAlbedo[px] = specAlbedo;
    OutDiffAlbedo[px] = diffAlbedo;

    // Primary radiance packing - Mode 1 Signal
    const float3 color = InColor[px].rgb;
    // These are included with matrix transforms. Are they being rescaled?
    const float hitDist = InSpecHitDist[px];

    OutFusedAlbedo[px] = fusedAlbedo;
    
    [branch]
    if (!IsSet(FLAGS_DEBUG))
    {
        OutRadiance[px] = float4(color, hitDist);
    }
    // Debug
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
                debugColor = VisualizeMotionVec(motionIn * RenderSize, 1.0f);
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
                debugColor = VisualizeMotionVec(motionOut.xy * RenderSize, 1.0f);
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
                
            default:
                debugColor = color;
                break;
        }
        
        OutRadiance[px] = float4(debugColor, 1.0f);
    }
}