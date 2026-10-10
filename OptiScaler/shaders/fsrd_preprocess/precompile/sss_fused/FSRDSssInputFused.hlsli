// B-only contract: t0 and t1 are the original full-precision color/depth.
// Extra typed views preserve Prepare's float loads while conversion keeps half loads.
Texture2D<float4> InFusedDiffAlbedo : register(t21);
Texture2D<float4> InFusedSpecAlbedo : register(t22);
Texture2D<float> InFusedBias : register(t23);
RWTexture2D<float> OutFusedDepth : register(u10);
RWTexture2D<half4> OutFusedColor : register(u11);
RWTexture2D<float> OutFusedGuide : register(u12);
RWTexture2D<float4> OutFusedBounds : register(u13);
bool FusedRawFlag(uint mask) { return (SkinDebug.w & mask) == mask; }
uint FusedRawDepthBits(const int2 px)
{
    // A title that publishes its own linear depth is authoritative: it knows which
    // linearisation it applied, and deriving it from hardware depth is the step that
    // has to guess that convention. This read is where the canonical signed depth is
    // produced - the floor filter, the packing shader and the denoiser's own depth
    // input all consume OutLinearDepth - so steering it steers the geometry of the
    // whole chain, and no consumer is left deriving its own.
    const bool useTitleDepth = FusedRawFlag(4096u);
    float inDepth = useTitleDepth
        ? InTitleLinearDepth[px + int2(InputBase5.xy)]
        : InDepth[px + int2(InputBase4.zw)];
    // InvProjMatrix is unjittered. Convert the current jittered raster
    // coordinate back to the matching unjittered projection ray.
    const float2 uv = (float2(px) + 0.5 - JitterOffsets.xy) * DstTexSize.zw;
    const float depthSign = FusedRawFlag(8u) ? -1.0f : 1.0f;
    float3 viewSpacePos = 0.0f;
    
    [branch]
    if (FusedRawFlag(2u) || useTitleDepth)
    {
        inDepth = clamp(abs(inDepth), NearPlane, FarPlane);
        inDepth *= depthSign;
        // Mid-range NDC depth: the ray is rescaled to inDepth below, so the choice
        // is arbitrary except that it must avoid the inverse projection's w == 0
        // singularity, which sits at 1.0 for a standard-Z infinite far plane.
        viewSpacePos = InvProjectPosition(float3(uv, 0.5f), InvProjMatrix);
        const float safeRayZ = (viewSpacePos.z < 0.0f)
            ? min(viewSpacePos.z, -1e-6f)
            : max(viewSpacePos.z, 1e-6f);
        viewSpacePos *= inDepth / safeRayZ;
        viewSpacePos.z = inDepth;
    }
    else
    {
        viewSpacePos = InvProjectPosition(float3(uv, inDepth), InvProjMatrix);
        // Projection handedness, rather than depth direction, defines the RR sign.
        // Clamp the complete position to preserve a coherent view ray at the
        // near/far boundaries instead of replacing Z alone.
        const float signedDepth = depthSign * clamp(abs(viewSpacePos.z), NearPlane, FarPlane);
        const float safeViewZ = (viewSpacePos.z < 0.0f)
            ? min(viewSpacePos.z, -1e-6f)
            : max(viewSpacePos.z, 1e-6f);
        viewSpacePos *= signedDepth / safeViewZ;
        viewSpacePos.z = signedDepth;
    }
    
    return asuint(viewSpacePos.z);
}

uint FusedSeedDepthBits(int pixelX,int pixelY);

// Pure helpers make neighborhood reads independent of same-dispatch UAV writes.
float FusedDepthAt(int2 p);
void FusedPrepareAt(int2 p,out half4 color,out float guide)
{
    const float4 source=InFusedSource[p+int2(SkinOptions.xy)];
    guide=InSssGuide[p+int2(SkinDebug.yz)];
    if(SkinOptions.z==0u || guide==0.0f || !isfinite(guide))
    {
        color=half4(source);guide=0.0f;return;
    }
    const float d=abs(FusedDepthAt(p));
    const float albedo=dot(FloorRadiance(InFusedDiffAlbedo[p+int2(InputBase2.zw)].rgb)+
        FloorRadiance(InFusedSpecAlbedo[p+int2(InputBase3.xy)].rgb),1.0f);
    const float bias=FusedRawFlag(32768u)?saturate(InFusedBias[p+int2(InputBase3.zw)]*BiasMaskStrength):0.0f;
    const float skyLimit=min(FarPlane,65504.0f);
    bool sky=false;
    [branch] if(!(skyLimit>=1.0f && d<=0.5f*skyLimit))
        sky=log(d+1.0f)>=0.99f*log(skyLimit+1.0f);
    if(!isfinite(d) || d<=0.0f || bias!=0.0f || SoftAbove(albedo,5.9f,0.5f)!=0.0f || sky) guide=0.0f;
    color=half4(SkinOptions.z==1u && guide!=0.0f?SkinSeparate(FloorRadiance(source.rgb),guide):source.rgb,source.a);
}
static int2 FusedPixel=0;
static bool FusedReady=false;
static float FusedDepth=0.0f,FusedGuide=0.0f;
static half4 FusedColor=0.0h;
float FusedDepthAt(int2 p)
{
    [branch] if(FusedReady && all(p==FusedPixel)) return FusedDepth;
    return asfloat(FusedSeedDepthBits(p.x,p.y));
}
half3 FusedColorAt(int2 p)
{
    [branch] if(FusedReady && all(p==FusedPixel)) return FusedColor.rgb;
    half4 color;float guide;FusedPrepareAt(p,color,guide);return color.rgb;
}
float FusedGuideAt(int2 p)
{
    [branch] if(FusedReady && all(p==FusedPixel)) return FusedGuide;
    half4 color;float guide;FusedPrepareAt(p,color,guide);return guide;
}
