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
    
    float UseSqrtEncodingOnSecondaries; // If true, FFX_DENOISER_DISPATCH_NON_GAMMA_ALBEDO should NOT be set
    float NearPlane;
    float FarPlane;
    float UseInfiniteFarPlane;
    
    float IsRoughnessPacked; // Roughness = InNormals.A - NVSDK_NGX_Parameter_DLSS_Roughness_Mode (Init param)
};

SamplerState LinearSampler : register(s0);

// Octahedral Encoding from AMD FSR-RR manual
float2 OctahedralEncode(float3 N)
{
    N.xy /= abs(N.x) + abs(N.y) + abs(N.z);
    const float2 k = sign(N.xy);
    const float s = saturate(-N.z);
    N.xy = lerp(N.xy, (1.0 - abs(N.yx)) * k, s);
    return N.xy * 0.5 + 0.5;
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

// Main Kernel
[RootSignature(MainRS)]
[numthreads(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    if (id.x >= RenderSize.x || id.y >= RenderSize.y)
        return;

    const int2 px = int2(id.xy);
    const float2 uv = (float2(id.xy) + 0.5) * RenderSizeInv;

    // Depth delta calculation from denoiser prepass sample shader
    // Assuming hardware depth
    const float inDepth = InDepth[px];
    const float3 ndcPos = float3(UVToNDC(uv), inDepth);
    const float3 viewSpacePos = InvProjectPosition(ndcPos, InvProjMatrix);

    // Left handed view space
    OutLinearDepth[px] = viewSpacePos.z; // Divide by FarPlane for debug vis
   
    // Motion Vectors & Depth Delta
    //
    // Find the current pixel in world space and calculate movement in view space
    const float3 worldSpacePos = mul(InvViewMatrix, float4(viewSpacePos, 1.0f)).xyz;
    const float3 prevViewSpacePos = mul(PrevViewMatrix, float4(worldSpacePos, 1.0f)).xyz;
    const float depthDelta = (viewSpacePos.z - prevViewSpacePos.z);
    
    // FSR-RR requires Linear Depth Delta in Blue channel
    const float2 motionPixels = InMotionVectors[px].rg; // RG: Pixel Movement
    OutMotion[px] = float4(motionPixels, depthDelta, 0.0f);
    
    // Normals - FSR-RR requries world normals
    //
    // DLSS-RR normals may be in view or world space. They will need to be transformed to account
    // for both configurations.
    float4 normal = InNormals[px];
    const float2 octNormal = OctahedralEncode(normalize(normal.rgb));
    const float materialType = 0.0f;
    
    // DLSS-RR provides 3D normals with roughnes optionally included in the A channel, or
    // in a separate single-channel buffer (InRoughness).
    const float roughness = (IsRoughnessPacked > 0.1f) ? normal.a : InRoughness[px];

    // Output: RG=OctNormal, B=Roughness, A=MaterialID
    OutNormals[px] = float4(octNormal, roughness, materialType);

    // Calculate NoV (Dot(Normal, View))
    //
    const float3 cameraPos = float3(InvViewMatrix._m03, InvViewMatrix._m13, InvViewMatrix._m23);
    // Line from camera to the clip pos
    const float3 viewDir = normalize(cameraPos - worldSpacePos);
    const float NoV = saturate(dot(normal.rgb, viewDir));

    // Secondary albedo packing
    //
    float3 specAlbedo, diffAlbedo;
    
    // Used for better perceptual encoding efficiency with high bit depth sources
    // Unnecessary if the secondaries use 8-bit color, which they usually do.
    if (UseSqrtEncodingOnSecondaries > 0.1f)
    {
        specAlbedo = sqrt(InSpecularAlbedo[px]);
        diffAlbedo = sqrt(InDiffuseAlbedo[px]);
    }
    else
    {
        specAlbedo = InSpecularAlbedo[px];
        diffAlbedo = InDiffuseAlbedo[px];
    }
    
    // FSR-RR expects metalness in diffuse alpha
    const float metalness = EstimateMetalness(diffAlbedo, specAlbedo);

    // FSR-RR expects NoV in specular alpha
    OutSpecAlbedo[px] = float4(specAlbedo, NoV);
    OutDiffAlbedo[px] = float4(diffAlbedo, metalness);

    // Primary radiance packing - Mode 1 Signal
    const float3 color = InColor[px].rgb;
    // These are included with matrix transforms. Are they being rescaled?
    const float hitDist = InSpecHitDist[px];

    OutFusedAlbedo[px] = float4(max(specAlbedo, diffAlbedo), NoV);
    // Input alpha channel should contain specular ray length
    OutRadiance[px] = float4(color, hitDist);
}