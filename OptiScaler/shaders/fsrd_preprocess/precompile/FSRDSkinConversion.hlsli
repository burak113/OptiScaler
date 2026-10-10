#include "FSRDSkinCommon.hlsli"
cbuffer CB_Packing : register(b0)
{
    float4x4 InvViewMatrix; // DLSSD WorldToView^-1
    float4x4 InvProjMatrix; // DLSSD ViewToClip^-1
    float4x4 PrevViewMatrix; // DLSSD WorldToView from last frame

    float4 DstTexSize; // Resolution of inputs
    float4 MotionInputSize; // XY: source extent - ZW: reciprocal extent
    float4 MotionTransform; // XY: raw source motion -> UV displacement
    float4 JitterOffsets; // XY: current pixels - ZW: previous pixels

    uint4 InputBase0; // XY: color, ZW: motion
    uint4 InputBase1; // XY: normals, ZW: roughness
    uint4 InputBase2; // XY: spec hit distance, ZW: diffuse albedo
    uint4 InputBase3; // XY: specular albedo, ZW: bias mask
    uint4 InputBase4; // XY: emissive, ZW: reserved
    uint4 InputBase5; // XY: reserved, ZW: specular hit-distance source

    float NearPlane;
    float FarPlane;   
    
    float FloorDetailPreservation;

    uint Flags;
    uint InspectorChannel;
    float InspectorScale;

    float DebugDepthMax;
    // 0 = absent, 1 = scalar in R, 2 = combined ray-direction resource, distance in A.
    uint DiffuseHitDistanceMode;

    float ResponsivityTrustThreshold;
    uint ResponsivityInvert;
    float BiasMaskStrength;
    float DemodDivisorFloor;
    float SpecularAlbedoDemodulation;
    float DiffuseAlbedoModulation;
    uint RecoveryMask;
    float AdditiveLightSplit; // Experimental local split, 0 = ordered baseline.
    uint4 SkinOptions; // XY: original color base; Z: skin mode; W: object depth/reflection flags
    uint4 SkinDebug; // X: debug view, YZW reserved
};

Texture2D<float> InSssGuide : register(t19);
Texture2D<half4> InOriginalColor : register(t20);
