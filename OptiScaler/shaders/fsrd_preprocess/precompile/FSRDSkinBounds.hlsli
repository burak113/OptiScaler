RWTexture2D<float4> OutSkinBounds : register(u10);
groupshared uint BoundsInvalid, BoundsMinDepth, BoundsMaxDepth;
groupshared uint BoundsMinU, BoundsMaxU, BoundsMinV, BoundsMaxV;
float4 PackBounds(float low,float high,float2 lo,float2 hi)
{
    return float4(low,high,asfloat(0x3f800000u|uint(lo.x)|(uint(hi.x)<<10u)),
        asfloat(0x3f900000u|uint(lo.y)|(uint(hi.y)<<10u)));
}
uint BoundsBits(float v) { return v==0.0f?0u:asuint(v); }
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 groupID:SV_GroupID,uint3 gtID:SV_GroupThreadID,uint lane:SV_GroupIndex)
{
    float2 storedUv;
    ProcessPixel(groupID,gtID,storedUv);
    const uint2 p=groupID.xy*8u+gtID.xy;
    const bool inside=all(p<uint2(DstTexSize.xy));
    const float d=inside?InDepth[p]:0.0f;
    const float g=inside?InSssGuide[p+SkinDebug.yz]:0.0f;
    // OutNormals stores half first, then R10 UNORM. Match both roundings.
    const float2 uv=round(saturate(storedUv)*1023.0f);
    const bool valid=inside && isfinite(d) && d>0.0f && isfinite(g) && g!=0.0f && all(isfinite(uv));
    // A complete 64-lane conversion group maps one metadata tile.
    // Equality is exact and includes the quantized normal codes; the general
    // reductions below remain responsible for every nonuniform surface.
    if (WaveGetLaneCount()==64u)
    {
        if (!WaveActiveAllTrue(valid))
        {
            if (WaveIsFirstLane()) OutSkinBounds[groupID.xy]=0.0f;
            return;
        }
        const float firstDepth=WaveReadLaneFirst(d);
        const float2 firstUv=WaveReadLaneFirst(uv);
        if (WaveActiveAllTrue(d==firstDepth && all(uv==firstUv)))
        {
            if (WaveIsFirstLane()) OutSkinBounds[groupID.xy]=PackBounds(firstDepth,firstDepth,firstUv,firstUv);
            return;
        }
    }
    const float low=WaveActiveMin(valid?d:3.402823e38f),high=WaveActiveMax(valid?d:0.0f);
    const float2 lowUv=WaveActiveMin(valid?uv:3.402823e38f),highUv=WaveActiveMax(valid?uv:0.0f);
    const bool allValid=WaveActiveAllTrue(valid);
    if (WaveGetLaneCount()==64u)
    {
        if (WaveIsFirstLane())
        {
            OutSkinBounds[groupID.xy]=allValid?PackBounds(low,high,lowUv,highUv):0;
        }
        return;
    }
    if (lane==0u)
    {
        BoundsInvalid=0u;BoundsMinDepth=BoundsMinU=BoundsMinV=0x7f7fffffu;
        BoundsMaxDepth=BoundsMaxU=BoundsMaxV=0u;
    }
    GroupMemoryBarrierWithGroupSync();
    if (WaveIsFirstLane())
    {
        if (!allValid) InterlockedOr(BoundsInvalid,1u);
        InterlockedMin(BoundsMinDepth,BoundsBits(low));InterlockedMax(BoundsMaxDepth,BoundsBits(high));
        InterlockedMin(BoundsMinU,BoundsBits(lowUv.x));InterlockedMax(BoundsMaxU,BoundsBits(highUv.x));
        InterlockedMin(BoundsMinV,BoundsBits(lowUv.y));InterlockedMax(BoundsMaxV,BoundsBits(highUv.y));
    }
    GroupMemoryBarrierWithGroupSync();
    if (lane==0u)
    {
        OutSkinBounds[groupID.xy]=BoundsInvalid==0u?PackBounds(asfloat(BoundsMinDepth),asfloat(BoundsMaxDepth),
            float2(asfloat(BoundsMinU),asfloat(BoundsMinV)),float2(asfloat(BoundsMaxU),asfloat(BoundsMaxV))):0;
    }
}
