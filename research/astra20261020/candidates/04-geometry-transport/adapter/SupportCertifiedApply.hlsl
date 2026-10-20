// Research-only, DEFAULT OFF. Not compiled or installed by this CPU package.
// CPU reference: reconstruction.py::reconstruct / method="supported".
// This is the application half of a contract, not a substitute for producing
// trustworthy per-pixel eligibility and full-estimator-footprint certificates.
// All positions/normals must use the same declared basis and linear units.
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 5)), DescriptorTable(UAV(u0, numDescriptors = 3))"
Texture2D<float> Gain : register(t0);
Texture2D<float4> CellPointDepth : register(t1);
Texture2D<float4> CellNormalValid : register(t2);
Texture2D<float4> QueryPositionDepth : register(t3);
Texture2D<float4> QueryNormalEligibility : register(t4);
RWTexture2D<float4> InOutDiffuse : register(u0);
RWTexture2D<float4> InOutSpecular : register(u1);
RWTexture2D<float4> SupportDebug : register(u2);
cbuffer SupportConstants : register(b0)
{
    uint2 ActiveExtent;
    uint2 GridExtent;
    uint Cell;
    uint Enabled;
    float PlaneAbsolute;
    float PlaneRelative;
    float NormalCosine;
    float MinimumWeight;
    uint2 Reserved;
};

bool UnitNormal(float3 value, out float3 normal)
{
    const float length2 = dot(value,value);
    const bool valid = all(isfinite(value)) && isfinite(length2) && length2 > 1e-16f;
    normal = valid ? value * rsqrt(length2) : 0.0f;
    return valid;
}

[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const uint2 p = dispatch.xy;
    if (any(p >= ActiveExtent)) return;
    // Host must bind resources at least as large as their declared extents.
    // Do not substitute allocation extents for these active extents.
    SupportDebug[p] = float4(1,0,0,0);
    if (Enabled == 0u || Cell == 0u || any(GridExtent == 0u)) return;
    if (!isfinite(PlaneAbsolute) || !isfinite(PlaneRelative) ||
        !isfinite(NormalCosine) || !isfinite(MinimumWeight) ||
        PlaneAbsolute < 0 || PlaneRelative < 0 || NormalCosine <= 0 ||
        NormalCosine > 1 || MinimumWeight < 0 || MinimumWeight >= 1) return;

    const float4 qp = QueryPositionDepth.Load(int3(p,0));
    const float4 qn = QueryNormalEligibility.Load(int3(p,0));
    float3 normal;
    const bool eligible = all(isfinite(qp)) && isfinite(qn.w) && qn.w > 0.5f &&
                          abs(qp.w) > 1e-8f && UnitNormal(qn.xyz,normal);
    if (!eligible) return;
    const float2 gridPosition = (float2(p)+0.5f)/float(Cell)-0.5f;
    const int2 base = int2(floor(gridPosition));
    const float2 fraction = gridPosition-float2(base);
    float mass=0.0f, correction=0.0f, contributors=0.0f;
    [unroll] for (int dy=0;dy<2;++dy)
    {
        [unroll] for (int dx=0;dx<2;++dx)
        {
            const int2 q=base+int2(dx,dy);
            const float weight=(dx ? fraction.x : 1-fraction.x)*
                               (dy ? fraction.y : 1-fraction.y);
            // No CLAMP sampler. Missing taps retain missing support mass.
            if (any(q<0) || any(q>=int2(GridExtent))) continue;
            const float4 cp=CellPointDepth.Load(int3(q,0));
            const float4 cn=CellNormalValid.Load(int3(q,0));
            const float g=Gain.Load(int3(q,0));
            float3 cellNormal;
            if (!all(isfinite(cp)) || !isfinite(cn.w) || cn.w<=0.5f || cp.w<=0 ||
                !UnitNormal(cn.xyz,cellNormal) || !isfinite(g) || g<0 || g>1) continue;
            const float3 delta=qp.xyz-cp.xyz;
            const float tolerance=PlaneAbsolute+PlaneRelative*max(abs(qp.w),cp.w);
            if (dot(normal,cellNormal)<NormalCosine ||
                abs(dot(delta,normal))>tolerance || abs(dot(delta,cellNormal))>tolerance) continue;
            mass+=weight;
            correction+=weight*(1-g);
            contributors+=weight>MinimumWeight ? 1.0f : 0.0f;
        }
    }
    const float gain = mass>MinimumWeight ? 1-correction/mass : 1.0f;
    SupportDebug[p]=float4(gain,mass,contributors,1);
    // OFF/unsupported skips writes exactly. Changed pixels carry alpha VALUE
    // unchanged; typed FP16 load/store payload-bit parity requires a GPU witness.
    if (gain==1.0f) return;
    float4 diffuse=InOutDiffuse[p],specular=InOutSpecular[p];
    diffuse.rgb*=gain;
    specular.rgb*=gain;
    InOutDiffuse[p]=diffuse;
    InOutSpecular[p]=specular;
}
