// Shared radiance-domain A/B: no spatial/temporal filtering. Inputs occupy u0..3,
// corresponding outputs u4..7. DD/ID use the diffuse factor; DS/IS use specular.
// The caller restores RGB after the provider on success and failure paths.
#define MainRS \
    "RootFlags(0), RootConstants(num32BitConstants=8,b0), " \
    "DescriptorTable(UAV(u0,numDescriptors=8))"
RWTexture2D<float4> Signals[8] : register(u0);
cbuffer ScaleConstants : register(b0)
{
    uint2 RenderSize;
    uint SignalCount;
    uint RestoreOutputs;
    float4 Factors;
}
float4 ScaleRgb(float4 value, float factor)
{
    float3 rgb = value.rgb * factor;
    rgb = float3(rgb.x > 65504.0f ? 65504.0f : rgb.x,
                 rgb.y > 65504.0f ? 65504.0f : rgb.y,
                 rgb.z > 65504.0f ? 65504.0f : rgb.z);
    return float4(rgb, value.a);
}
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid.xy >= RenderSize)) return;
    [unroll] for (uint i=0; i<4; ++i)
    {
        if (i >= SignalCount) break;
        Signals[i][tid.xy] = ScaleRgb(Signals[i][tid.xy], Factors[i]);
        if (RestoreOutputs != 0)
            Signals[i+4][tid.xy] = ScaleRgb(Signals[i+4][tid.xy], Factors[i]);
    }
}
