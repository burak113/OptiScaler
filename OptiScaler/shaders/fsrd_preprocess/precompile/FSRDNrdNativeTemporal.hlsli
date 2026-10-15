#ifndef FSRD_NRD_NATIVE_TEMPORAL
#define FSRD_NRD_NATIVE_TEMPORAL
// Selected operands from the full-hash-attested title Temporal b6, not an SDK ABI.
// Every member begins at the byte offset documented by NativeTemporalCapture.
static const uint NrdNativeTemporalSignature = 0x4e544d31u;
static const uint NrdNativeTemporalVersion = 1u;
struct NrdNativeTemporalData
{
    float4 previousClipX;
    float4 previousClipY;
    float4 previousClipW;
    float4 previousViewDepthRow;
    float4 currentRight;
    float4 currentUp;
    float4 currentForward;
    float4 previousRight;
    float4 previousUp;
    float4 previousForward;
    float4 cameraDelta;
    float4 motionScale;
    int2 sourceOrigin;
    uint2 rectSize;
    float2 inverseRectSize;
    float2 previousRectSize;
    uint motionSpace;
    float orthographic;
    uint signature;
    uint version;
    uint4 reserved;
};
#endif
