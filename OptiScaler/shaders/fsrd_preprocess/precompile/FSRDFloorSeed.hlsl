#include "FSRDPreprocessCommon.hlsli"
#include "FSRDFloorCommon.hlsli"
#include "FSRDFloorModel.hlsli"

// The coherent-lighting witness and local polynomial projection were retired:
// on captured game frames neither fired, while together they cost about 3 ms
// at 1440p. The macro remains only so the lighting contract can still build its
// control; both builds are now identical.
#ifndef FSRD_FLOOR_REFERENCE_TEST_CONTROL
#define FSRD_FLOOR_REFERENCE_TEST_CONTROL 0
#endif

// Optional clean-lighting producers, built as their own PSO variant
// (FSRDFloorSeedCleanLighting) so the default Seed pays nothing for them: the
// coherent-lighting witness (-101) and the local lighting projection (-102).
// They only fire on noise-free content, where a clean lighting pattern on one
// constant material would otherwise be handed to RR as residual and erased.
#ifndef FSRD_FLOOR_CLEAN_LIGHTING
#define FSRD_FLOOR_CLEAN_LIGHTING 0
#endif

// Separate semantic control for the sparse supported-background contract.
// This never changes the two existing reference/projection test producers.
#ifndef FSRD_FLOOR_SPARSE_TEST_CONTROL
#define FSRD_FLOOR_SPARSE_TEST_CONTROL 0
#endif

#define MainRS \
    "RootFlags(0), CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 5)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 5))"

#define FLAGS_LINEAR_DEPTH (1 << 0)
#define FLAGS_NEGATIVE_VIEW_DEPTH (1 << 1)
#define FLAGS_TITLE_LINEAR_DEPTH (1 << 2)
#define THREAD_GROUP_SIZE_X 8
#define THREAD_GROUP_SIZE_Y 8
#define NUM_THREADS 64
static const uint2 s_ThreadGroupSize = uint2(8, 8);
DEFINE_LDS_CONFIG(s_SM, 5);
DECLARE_LDS_ARRAY_2D(uint2, g_ColorP, 5);
DECLARE_LDS_ARRAY_2D(float, g_Depth, 5);
DECLARE_LDS_ARRAY_2D(uint2, g_NormalP, 5);
DECLARE_LDS_ARRAY_2D(uint2, g_AlbedoP, 5);


// The robust fit walks its 25 per-thread weights several times. Kept in LDS,
// the window loops stay rolled; unrolled register arrays spilled to scratch.
// Four 8-bit weights per word: as 16-bit values the 25 per-thread weights
// pushed the group's LDS past the budget of a fifth wave per SIMD.
groupshared uint g_ModelWeight[7][64];
#if FSRD_FLOOR_CLEAN_LIGHTING
// Pool geometry-only rectangular supports. Colour never selects which samples
// enter these two covariance matrices.
// Each wave reduces its own sums; the per-wave partials (at most 16 waves of
// 19 values) borrow the model-weight words, which the weights walk only
// writes after this witness has finished. Full-size reduction arrays cost
// the variant two waves of occupancy.
groupshared uint g_CoherentLighting;
#define CoherentPartial(wave, value) g_ModelWeight[((wave) * 19u + (value)) / 64u][((wave) * 19u + (value)) % 64u]
#endif
#define ModelWeight(tap) (float((g_ModelWeight[(tap) / 4][flatID] >> (8 * ((tap) % 4))) & 0xffu) * (1.0f / 255.0f))


Texture2D<float3> InColor : register(t0);
Texture2D<float3> InNormals : register(t1);
Texture2D<float> InDepth : register(t2);
Texture2D<float> InTitleLinearDepth : register(t3);
Texture2D<float3> InDiffAlbedo : register(t4);
RWTexture2D<half4> OutColor : register(u0);
RWTexture2D<float> OutLinearDepth : register(u1);
RWTexture2D<half4> OutDepthGradient : register(u2);
RWTexture2D<half4> OutDetailReference : register(u3);
RWTexture2D<half4> OutFloorModel : register(u4);

cbuffer CB_Median : register(b0)
{
    float4x4 InvProjMatrix; // DLSSD ViewToClip^-1
    float4 RenderSize;

    float NearPlane;
    float FarPlane;
    
    uint Flags;
    
    float _Padding;

    float2 CurrentJitter;
    float2 _JitterPadding;

    uint4 InputBase; // XY: color origin, ZW: depth origin

    // Origin of the title's normals, which the orientation guide is read from.
    uint2 NormalBase;
    float2 _NormalPadding;

    // Origin of the title's published linear depth, when it provides one.
    uint2 TitleDepthBase;
    float2 _TitleDepthPadding;
    uint2 AlbedoBase;
    uint _Reserved0;
    uint FloorEnabled;
}

bool IsSet(uint mask) { return (Flags & mask) == mask; }

float3 GetViewSpacePos(const int2 px)
{
    // A title that publishes its own linear depth is authoritative: it knows which
    // linearisation it applied, and deriving it from hardware depth is the step that
    // has to guess that convention. This read is where the canonical signed depth is
    // produced - the floor filter, the packing shader and the denoiser's own depth
    // input all consume OutLinearDepth - so steering it steers the geometry of the
    // whole chain, and no consumer is left deriving its own.
    const bool useTitleDepth = IsSet(FLAGS_TITLE_LINEAR_DEPTH);
    float inDepth = useTitleDepth
        ? InTitleLinearDepth[px + int2(TitleDepthBase)]
        : InDepth[px + int2(InputBase.zw)];
    // InvProjMatrix is unjittered. Convert the current jittered raster
    // coordinate back to the matching unjittered projection ray.
    const float2 uv = (float2(px) + 0.5 - CurrentJitter) * RenderSize.zw;
    const float depthSign = IsSet(FLAGS_NEGATIVE_VIEW_DEPTH) ? -1.0f : 1.0f;
    float3 viewSpacePos = 0.0f;
    
    [branch]
    if (IsSet(FLAGS_LINEAR_DEPTH) || useTitleDepth)
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
    
    return viewSpacePos;
}


// Half3 LDS elements compile to separate 16-bit loads. Packing each RGB triple
// into one 64-bit word makes every neighbourhood read a single LDS access.
uint2 PackHalf3(float3 v)
{
    const uint3 h = f32tof16(v);
    return uint2(h.x | (h.y << 16), h.z);
}
half3 UnpackHalf3(uint2 v)
{
    return half3(f16tof32(uint3(v.x & 0xffffu, v.x >> 16, v.y)));
}

float ShadeKey(float3 colour, float3 material)
{
    return GetLuminance(colour / max(material, 0.02f));
}

float LoadShadeKey(int2 p)
{
    return asfloat((g_ColorP[p.x][p.y].y & 0xffff0000u) | (g_AlbedoP[p.x][p.y].y >> 16));
}

float2 DepthGradient(int2 p)
{
    return float2(FloorDepthDerivative(g_Depth[p.x-1][p.y], g_Depth[p.x][p.y], g_Depth[p.x+1][p.y]),
                  FloorDepthDerivative(g_Depth[p.x][p.y-1], g_Depth[p.x][p.y], g_Depth[p.x][p.y+1]));
}



// keys[index] for a per-lane index: a binary tree of selects on the index bits
// costs 24 selects, where comparing every rank cost 25 compares and 25 selects.
float SelectRank(float keys[25], uint index)
{
    float level[25];
    [unroll] for (uint k = 0; k < 25; ++k) level[k] = keys[k];
    uint width = 25;
    [unroll]
    for (uint bit = 0; bit < 5; ++bit)
    {
        const bool odd = (index >> bit) & 1u;
        [unroll]
        for (uint k = 0; k < 13; ++k)
        {
            if (2 * k + 1 < width) level[k] = odd ? level[2 * k + 1] : level[2 * k];
            else if (2 * k < width) level[k] = level[2 * k];
        }
        width = (width + 1) / 2;
    }
    return level[0];
}

// A float3 sorting network is three independent scalar networks. Sorting one
// colour channel at a time keeps 25 instead of 75 keys live (bit-identical).
void SortedQuartiles(inout float keys[25], uint count, out float median,
                     out float lower, out float upper)
{
    [unroll]
    for (uint k = 0; k < kSortNetworkSize; ++k)
    {
        const uint a = SortNetwork[2*k], b = SortNetwork[2*k+1];
        const float key = keys[a];
        keys[a] = min(key, keys[b]);
        keys[b] = max(key, keys[b]);
    }
    median = SelectRank(keys, count/2);
    lower = SelectRank(keys, (count-1)/4);
    upper = SelectRank(keys, (3*(count-1))/4);
}

#if FSRD_FLOOR_CLEAN_LIGHTING
float CoherentSecondInvariant(float3 diagonal, float3 cross)
{
    return diagonal.x*diagonal.y + diagonal.x*diagonal.z + diagonal.y*diagonal.z - dot(cross,cross);
}

float CoherentDeterminant(float3 diagonal, float3 cross)
{
    return diagonal.x*diagonal.y*diagonal.z + 2.0f*cross.x*cross.y*cross.z -
        diagonal.x*cross.z*cross.z - diagonal.y*cross.y*cross.y - diagonal.z*cross.x*cross.x;
}

bool CoherentLightingEvidence(float3 diagonal1, float3 cross1, float3 diagonal2,
                              float3 cross2, float3 maximum)
{
    const float ratio = 6.52f;
    const float energy1 = dot(diagonal1,1.0f), energy2 = dot(diagonal2,1.0f);
    if (!(energy2 > ratio*energy1) || !isfinite(energy2)) return false;
    const float inverseEnergy = rcp(max(energy2,1e-30f));
    const float3 normalDiagonal2 = diagonal2*inverseEnergy;
    const float3 normalCross2 = cross2*inverseEnergy;
    const float rank = CoherentSecondInvariant(normalDiagonal2,normalCross2);
    const float3 ulp = exp2(max(floor(log2(max(maximum,exp2(-14.0f))))-10.0f,-24.0f));
    // A nine-tap tensor difference has coefficient L1=16. Round-to-nearest
    // half storage bounds each derivative error by 8 ULPs, hence 64 sum ULP^2.
    const float roundingEnergy = 64.0f*dot(ulp,ulp);
    if (rank < 0.02f || rank*energy2 <= roundingEnergy+1e-4f*energy2) return false;
    const float delta = (2.0f*sqrt(energy2*roundingEnergy)+roundingEnergy +
        ratio*(2.0f*sqrt(energy1*roundingEnergy)+roundingEnergy) +
        1e-4f*(energy2+ratio*energy1))*inverseEnergy;
    const float3 bDiagonal = (diagonal2-ratio*diagonal1)*inverseEnergy;
    const float3 bCross = (cross2-ratio*cross1)*inverseEnergy;
    const float3 minus = bDiagonal-delta;
    // Positive trace and either positive S2 or negative determinant certify
    // at least two coherent colour directions beyond quantization uncertainty.
    const float margin = 1e-6f;
    const bool twoDirections = dot(minus,1.0f)>margin &&
        (CoherentSecondInvariant(minus,bCross)>margin || CoherentDeterminant(minus,bCross)<-margin);
    const float3 plus = bDiagonal+delta;
    const float3 minors = float3(plus.x*plus.y-bCross.x*bCross.x,
        plus.x*plus.z-bCross.y*bCross.y,plus.y*plus.z-bCross.z*bCross.z);
    // Every principal minor must be positive. A noisy third colour direction
    // cannot borrow the certificate of the two coherent lighting directions.
    return twoDirections && all(plus>margin) && all(minors>margin) &&
        CoherentDeterminant(plus,bCross)>margin;
}

// Total-degree-three orthogonal projection on the complete 5x5 rectangle.
// Discrete Legendre norms are fixed, so no content-dependent weights select
// the samples. The centre predictor is the degree-two Savitzky-Golay kernel:
// h(x,y)=27/175-(x*x+y*y)/35, sum(h)=1, sum(h*h)=27/175.
// Cubic terms are used only for the independent sampled-residual veto.
bool LocalLightingProjection(int2 sm, int2 px, int2 bounds, float3 albedo,
                             float3 center, out float3 query)
{
    query=center;
    if(any(px<2) || any(px>bounds-2) || any(albedo<0.02f) || any(albedo>1.0f)) return false;
    const float inverseNorm[10]={1.0f/25.0f,1.0f/50.0f,1.0f/50.0f,
        1.0f/70.0f,1.0f/100.0f,1.0f/70.0f,1.0f/72.0f,
        1.0f/140.0f,1.0f/140.0f,1.0f/72.0f};
    float3 coefficient[10];
    [unroll] for(uint k=0;k<10;++k) coefficient[k]=0.0f;
    float3 maximum=center;
    // Rare and clean-content only: an opaque count keeps both walks rolled,
    // so this variant does not raise the register budget of every pixel.
    const uint taps=min(25u,asuint(RenderSize.x));
    [loop] for(uint tap=0;tap<taps;++tap)
    {
        const int x=int(tap%5)-2, y=int(tap/5)-2;
        const int2 q=sm+int2(x,y);
        if(any(float3(UnpackHalf3(g_AlbedoP[q.x][q.y]))!=albedo)) return false;
        const float3 colour=float3(UnpackHalf3(g_ColorP[q.x][q.y]));
        maximum=max(maximum,colour);
        const float xx=float(x*x)-2.0f,yy=float(y*y)-2.0f;
        const float basis[10]={1.0f,float(x),float(y),xx,float(x*y),yy,
            float(x*x*x)-3.4f*x,xx*y,x*yy,float(y*y*y)-3.4f*y};
        [unroll] for(uint k=0;k<10;++k)
            coefficient[k]+=basis[k]*(colour-center);
    }
    [unroll] for(uint k=0;k<10;++k) coefficient[k]*=inverseNorm[k];
    query=center+coefficient[0]-2.0f*coefficient[3]-2.0f*coefficient[5];
    // A signed polynomial predictor may cross a sampled extremum by a fraction
    // of an ULP. Rejecting that centre would reintroduce the wide-kernel bias.
    // The centre belongs to the residual veto below, which already bounds the
    // prediction relative to its actual stored RGB by four local FP16 ULPs.
    if(!all(isfinite(query)) || any(query<0.0f)) return false;
    const float3 ulp=exp2(max(floor(log2(max(maximum,exp2(-14.0f))))-10.0f,-24.0f));
    const float3 budget=4.0f*ulp;
    [loop] for(uint tap=0;tap<taps;++tap)
    {
        const int x=int(tap%5)-2, y=int(tap/5)-2;
        const float xx=float(x*x)-2.0f,yy=float(y*y)-2.0f;
        const float basis[10]={1.0f,float(x),float(y),xx,float(x*y),yy,
            float(x*x*x)-3.4f*x,xx*y,x*yy,float(y*y*y)-3.4f*y};
        float3 predicted=center;
        [unroll] for(uint k=0;k<10;++k) predicted+=basis[k]*coefficient[k];
        if(any(abs(float3(UnpackHalf3(g_ColorP[sm.x+x][sm.y+y]))-predicted)>budget)) return false;
    }
    return true;
}
#endif

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 groupID : SV_GroupID, uint3 gtID : SV_GroupThreadID)
{
    const int2 origin = int2(groupID.xy * 8) - 2;
    const uint flatID = gtID.x + gtID.y * 8;
    const int2 bounds = int2(RenderSize.xy) - 1;
    // Depth is required even when Floor is disabled. Avoid every colour/guide load
    // and all sorting in that mode, without putting an early return before a barrier.
    [unroll]
    for (uint i = 0; i < s_SM_LoadsPerThread; ++i)
    {
        const uint flat = flatID + i * 64;
        if (flat < s_SM_ElementCount)
        {
            const int2 sm = int2(flat % s_SM_Size.x, flat / s_SM_Size.x);
            const int2 p = clamp(origin + sm, 0, bounds);
            g_Depth[sm.x][sm.y] = GetViewSpacePos(p).z;
            if (FloorEnabled != 0u)
            {
                uint2 colour = PackHalf3(FloorRadiance(InColor[p + int2(InputBase.xy)]));
                uint2 material = PackHalf3(FloorRadiance(InDiffAlbedo[p + int2(AlbedoBase)]));
                // The illumination-ratio key is a property of the texel, not of the
                // window: form it once here from the stored FP16 values. Its FP32
                // bits fill the unused upper halves of the two packed words.
                const uint shade = asuint(ShadeKey(UnpackHalf3(colour), UnpackHalf3(material)));
                colour.y |= shade & 0xffff0000u;
                material.y |= shade << 16;
                g_ColorP[sm.x][sm.y] = colour;
                g_NormalP[sm.x][sm.y] = PackHalf3(FloorNormal(InNormals[p + int2(NormalBase)]));
                g_AlbedoP[sm.x][sm.y] = material;
            }
        }
    }
    GroupMemoryBarrierWithGroupSync();
    const int2 px = int2(groupID.xy * 8 + gtID.xy);
#if FSRD_FLOOR_CLEAN_LIGHTING
    if (FloorEnabled != 0u && FSRD_FLOOR_REFERENCE_TEST_CONTROL == 0)
    {
        const int2 sample = int2(gtID.xy)+2;
        const bool rectangular = all(px>=2) && all(px<=bounds-2);
        bool accepted = rectangular;
        float3 d1=0.0f,d2=0.0f,maximum=0.0f;
        if (rectangular)
        {
            const float centreZ=g_Depth[sample.x][sample.y];
            const float2 gradient=DepthGradient(sample);
            const float3 normal=UnpackHalf3(g_NormalP[sample.x][sample.y]);
            const float3 albedo=UnpackHalf3(g_AlbedoP[sample.x][sample.y]);
            accepted = all(albedo>=0.02f) && all(albedo<=1.0f);
            [unroll] for(int y=-2;y<=2;++y) [unroll] for(int x=-2;x<=2;++x)
            {
                const int2 q=sample+int2(x,y);
                const float3 tapAlbedo=UnpackHalf3(g_AlbedoP[q.x][q.y]);
                const float weight=FloorSurfaceWeight(centreZ,g_Depth[q.x][q.y],gradient,
                    float2(x,y),normal,UnpackHalf3(g_NormalP[q.x][q.y]),albedo,tapAlbedo);
                accepted = accepted && weight>=0.75f && all(tapAlbedo==albedo);
                maximum=max(maximum,float3(UnpackHalf3(g_ColorP[q.x][q.y])));
            }
            [unroll] for(int y=-1;y<=1;++y) [unroll] for(int x=-1;x<=1;++x)
            {
                const float coefficient=(x==0 ? -2.0f : 1.0f)*(y==0 ? -2.0f : 1.0f);
                d1+=coefficient*float3(UnpackHalf3(g_ColorP[sample.x+x][sample.y+y]));
                d2+=coefficient*float3(UnpackHalf3(g_ColorP[sample.x+2*x][sample.y+2*y]));
            }
        }
        const float keep=accepted ? 1.0f : 0.0f;
        float values[19];
        {
            const float4 d1Sum=WaveActiveSum(float4(d1*d1*keep,keep));
            const float4 d2Sum=WaveActiveSum(float4(d2*d2*keep,0.0f));
            const float3 cross1Sum=WaveActiveSum(float3(d1.x*d1.y,d1.x*d1.z,d1.y*d1.z)*keep);
            const float4 cross2Sum=WaveActiveSum(float4(float3(d2.x*d2.y,d2.x*d2.z,d2.y*d2.z)*keep,
                Square(dot(d2,d2))*keep));
            const float3 maximumAll=WaveActiveMax(maximum*keep);
            values[0]=d1Sum.x; values[1]=d1Sum.y; values[2]=d1Sum.z; values[3]=d1Sum.w;
            values[4]=d2Sum.x; values[5]=d2Sum.y; values[6]=d2Sum.z;
            values[7]=cross1Sum.x; values[8]=cross1Sum.y; values[9]=cross1Sum.z;
            values[10]=cross2Sum.x; values[11]=cross2Sum.y; values[12]=cross2Sum.z; values[13]=cross2Sum.w;
            values[14]=maximumAll.x; values[15]=maximumAll.y; values[16]=maximumAll.z;
            values[17]=0.0f; values[18]=0.0f;
        }
        const uint lanes=WaveGetLaneCount();
        if(WaveIsFirstLane())
        {
            [unroll] for(uint v=0;v<17;++v) CoherentPartial(flatID/lanes,v)=asuint(values[v]);
        }
        GroupMemoryBarrierWithGroupSync();
        if(flatID==0u)
        {
            float total[17];
            [unroll] for(uint v=0;v<17;++v) total[v]=asfloat(CoherentPartial(0u,v));
            for(uint wave=1;wave<(64u+lanes-1u)/lanes;++wave)
            {
                [unroll] for(uint v=0;v<14;++v) total[v]+=asfloat(CoherentPartial(wave,v));
                [unroll] for(uint v=14;v<17;++v) total[v]=max(total[v],asfloat(CoherentPartial(wave,v)));
            }
            const int2 first=max(int2(groupID.xy*8),2);
            const int2 last=min(int2(groupID.xy*8)+8,bounds-1);
            const int2 extent=max(last-first,0);
            const int expected=extent.x*extent.y;
            const float count=total[3];
            // Any rejected geometry/material sample invalidates the complete
            // rectangular witness, instead of creating colour-selected holes.
            const float inverseCount=rcp(max(count,1.0f));
            // Two isolated coloured blocks must not imitate broad structure.
            const float energy=total[4]+total[5]+total[6];
            const bool broadSupport=Square(energy)>=0.5f*count*total[13];
            g_CoherentLighting=count>=32.0f && count==float(expected) && broadSupport &&
                CoherentLightingEvidence(float3(total[0],total[1],total[2])*inverseCount,
                    float3(total[7],total[8],total[9])*inverseCount,float3(total[4],total[5],total[6])*inverseCount,
                    float3(total[10],total[11],total[12])*inverseCount,float3(total[14],total[15],total[16])) ? 1u : 0u;
        }
        GroupMemoryBarrierWithGroupSync();
    }
#endif
    if (any(px > bounds)) return;
    const int2 sm = int2(gtID.xy) + 2;
    const float z = g_Depth[sm.x][sm.y];
    OutLinearDepth[px] = z;
    if (FloorEnabled == 0u)
    {
        OutColor[px] = 0;
        OutDepthGradient[px] = 0;
        OutDetailReference[px] = 0;
        OutFloorModel[px] = 0;
        return;
    }
    const float2 gradient = DepthGradient(sm);
    const float3 normal = UnpackHalf3(g_NormalP[sm.x][sm.y]);
    const float3 albedo = UnpackHalf3(g_AlbedoP[sm.x][sm.y]);
    const float3 centerRGB = UnpackHalf3(g_ColorP[sm.x][sm.y]).rgb;
    const float4 center = float4(centerRGB, GetLuminance(centerRGB));
    float keys[25];
    half weights[25];
    uint count = 0;
    float surfaceSupport = 0;
    float3 innerMin = 65500.0f, innerMax = 0;
    float3 ringMin = 65500.0f, ringMax = 0;
    uint innerCount = 0, ringCount = 0, matchingNeighbours = 0;
    float3 channelInnerSupport = 0, channelRingSupport = 0;
    float3 geometryAlbedoMinimum = albedo;
    uint packedModelWeight = 0;
    GroupMemoryBarrier();
    [unroll]
    for (uint j = 0; j < 25; ++j)
    {
        const int2 off = int2(j % 5, j / 5) - 2;
        const int2 q = sm + off;
        // Depth/normal support is shared by both gates: the material gate only
        // multiplies it, so evaluate the geometry once per tap.
        const float3 tapAlbedo = float3(UnpackHalf3(g_AlbedoP[q.x][q.y]));
        const float geometry = FloorSurfaceWeight(z, g_Depth[q.x][q.y], gradient,
            float2(clamp(px + off, 0, bounds) - px), normal, UnpackHalf3(g_NormalP[q.x][q.y]),
            albedo, albedo);
        const float w = geometry * FloorMaterialWeight(albedo, tapAlbedo);
        // Always retain the centre, including far-plane/degenerate geometry.
        // Replicated border texels are not independent evidence for a noisy centre.
        const bool inside = all(px + off >= 0) && all(px + off <= bounds);
        weights[j] = j == 12 ? 1.0f : (inside ? w : 0.0f);
        // Material colour varies within one surface. The affine lighting model
        // uses geometry support; the conservative pedestal keeps its material gate.
        const uint modelByte = j == 12 ? 255u : (inside ? uint(round(saturate(geometry) * 255.0f)) : 0u);
        const float modelW = float(modelByte) * (1.0f / 255.0f);
        packedModelWeight |= modelByte << (8 * (j % 4));
        if (j % 4 == 3 || j == 24)
        {
            g_ModelWeight[j / 4][flatID] = packedModelWeight;
            packedModelWeight = 0;
        }
        const bool accepted = weights[j] > 0.1f;
        keys[j] = accepted ? GetLuminance(float3(UnpackHalf3(g_ColorP[q.x][q.y]).rgb)) : 1e20f;
        count += accepted ? 1 : 0;
        surfaceSupport += accepted ? float(weights[j]) : 0.0f;
    }
    GroupMemoryBarrier();
    [unroll]
    for (uint k = 0; k < kSortNetworkSize; ++k)
    {
        const uint a = SortNetwork[2*k], b = SortNetwork[2*k+1];
        const float ka = keys[a];
        keys[a] = min(ka, keys[b]);
        keys[b] = max(ka, keys[b]);
    }
    // Static indexing avoids spilling a dynamically indexed private array.
    float median = 0, q25 = 0, q75 = 0;
    GroupMemoryBarrier();
    [unroll]
    for (uint rank = 0; rank < 25; ++rank)
    {
        median = rank == count/2 ? keys[rank] : median;
        q25 = rank == (count-1)/4 ? keys[rank] : q25;
        q75 = rank == (3*(count-1))/4 ? keys[rank] : q75;
    }
    const float sigma = max((q75 - q25) * 0.7413f, 0.0f);
    const float range = max(3.0f * sigma, max(median * 0.025f, 1e-5f));

    // A one-pixel stroke has two supporting neighbours in one direction; an
    // isolated impulse does not. Test RGB as well, so chromatic fireflies cannot
    // borrow confidence from an unrelated luminance match.
    const int2 axes[4] = { int2(1,0), int2(0,1), int2(1,1), int2(1,-1) };
    float support = 0;
    float directionalNoise = sigma;
    GroupMemoryBarrier();
    [unroll]
    for (uint a = 0; a < 4; ++a)
    {
        const int2 lo = sm - axes[a], hi = sm + axes[a];
        const uint li = (2-axes[a].y)*5 + 2-axes[a].x;
        const uint ri = (2+axes[a].y)*5 + 2+axes[a].x;
        const float tolerance = max(0.08f * max(center.a, median), 1e-5f);
        const float3 curvature = center.rgb -
            0.5f * (float3(UnpackHalf3(g_ColorP[lo.x][lo.y]).rgb) + float3(UnpackHalf3(g_ColorP[hi.x][hi.y]).rgb));
        const float pairWeight = min(weights[li], weights[ri]);
        const float agreement = Square(saturate(1.0f -
            dot(curvature, curvature) / (tolerance * tolerance)));
        support = max(support, agreement * pairWeight);
        // IQR measures contrast as well as noise. A valid axis along a clean edge
        // or ramp has no curvature: do not classify its contrast as uncertainty.
        const float axisNoise = 0.9428f * length(curvature);
        directionalNoise = min(directionalNoise, lerp(sigma, axisNoise, pairWeight));
    }
    float3 base = 0, reference = 0;
    float baseWeight = 0, refWeight = 0;
    const float target = lerp(median, center.a, support);
    // Few samples cannot establish a stable median colour population. Retain
    // only the lower quartile there; well-supported grain can pool a lower half.
    const float baseCeiling = count >= 9 ? median : q25;
    GroupMemoryBarrier();
    GroupMemoryBarrier();
    [unroll]
    for (uint t = 0; t < 25; ++t)
    {
        const int2 q = sm + int2(t % 5, t / 5) - 2;
        const float3 rgb = UnpackHalf3(g_ColorP[q.x][q.y]).rgb;
        const float4 c = float4(rgb, GetLuminance(rgb));
        const float w = weights[t] > 0.1f ? weights[t] : 0.0f;
        // The colour envelope of the accepted neighbours is only consumed after
        // the pedestal, so it is gathered here rather than in the weights walk,
        // where the luminance keys already hold the peak register budget.
        if (weights[t] > 0.1f && t != 12)
        {
            if (dot(rgb-center.rgb, rgb-center.rgb) <= Square(max(0.08f*length(center.rgb),1e-5f)))
                matchingNeighbours++;
            if (all(abs(int2(t % 5, t / 5) - 2) <= 1))
            {
                innerMin = min(innerMin, rgb); innerMax = max(innerMax, rgb); innerCount++;
            }
            else
            {
                ringMin = min(ringMin, rgb); ringMax = max(ringMax, rgb); ringCount++;
            }
        }
        // Wide IQR weights admitted colourful bright rays into the pedestal,
        // then a luminance-only cap kept their chroma. Exclude the positive tail,
        // but keep the lower half rather than too few samples of ordinary grain.
        const float wb = c.a <= baseCeiling + max(0.01f*baseCeiling,1e-6f)
            ? w * FloorRangeWeight(c.a - q25, range) : 0.0f;
        const float wr = w * FloorRangeWeight(c.a - target,
            lerp(range, max(0.08f * max(target, median), 1e-5f), support));
        base += c.rgb * wb; baseWeight += wb;
        reference += c.rgb * wr; refWeight += wr;
    }
    // q25 is an accepted sample, so the base always has nonzero support. Reuse
    // that robust RGB estimate if an interpolated reference target has no support.
    base /= max(baseWeight, 1e-6f);
    reference = refWeight > 1e-6f ? reference / refWeight : base;
    // A volume/transparent layer does not follow the background's surface guide.
    // Missing surface support cannot mean missing light. Use the common lower RGB
    // level of independent quadrant means as a conservative non-surface pedestal.
    // A bright impulse affects at most one block and cannot raise their common floor.
    float3 commonBase = 65500.0f;
    float quietNoise = sigma;
    uint blocks = 0;
    [branch]
    if (surfaceSupport < 9.0f)
    {
    GroupMemoryBarrier();
    [unroll]
    for (uint quadrant = 0; quadrant < 4; ++quadrant)
    {
        const int2 direction = int2((quadrant & 1) ? 1 : -1, (quadrant & 2) ? 1 : -1);
        float3 blockMinimum = 65500.0f;
        float3 blockSecond = 65500.0f;
        float blockCount = 0;
        [unroll]
        for (int by = 1; by <= 2; ++by)
        {
            [unroll]
            for (int bx = 1; bx <= 2; ++bx)
            {
                const int2 off = direction * int2(bx, by);
                if (all(px + off >= 0) && all(px + off <= bounds))
                {
                    const int2 q = sm + off;
                    const float3 rgb = UnpackHalf3(g_ColorP[q.x][q.y]).rgb;
                    blockSecond = min(blockSecond, max(blockMinimum, rgb));
                    blockMinimum = min(blockMinimum, rgb);
                    blockCount += 1;
                }
            }
        }
        if (blockCount > 0)
        {
            // Keep the lower half, not all but one: two independent bright
            // rays in each surviving border quadrant must not raise Skip.
            const float3 blockBase = blockCount >= 3
                ? 0.5f*(blockMinimum+blockSecond) : blockMinimum;
            commonBase = min(commonBase, blockBase);
            blocks++;
        }
    }
    }
    // Independent edge pairs estimate local noise without labelling the central
    // glyph's curvature as noise. A flat supported patch supplies a zero estimate.
    GroupMemoryBarrier();
    [unroll]
    for (uint corner = 0; corner < 4; ++corner)
    {
        const int2 off = int2((corner & 1) ? 2 : -2, (corner & 2) ? 2 : -2);
        const int2 nearOff = int2(off.x / 2, off.y);
        if (min(weights[(off.y+2)*5+off.x+2], weights[(nearOff.y+2)*5+nearOff.x+2]) > 0.1f)
        {
            const int2 a = sm + off, b = sm + nearOff;
            const float3 delta = float3(UnpackHalf3(g_ColorP[a.x][a.y])) - float3(UnpackHalf3(g_ColorP[b.x][b.y]));
            quietNoise = min(quietNoise, sqrt(dot(delta,delta) / 6.0f));
        }
    }
    // The pedestal cannot brighten a foreground silhouette. It is not a detail
    // reference and never authorizes handover across a surface boundary.
    commonBase = blocks >= 2 ? min(commonBase, center.rgb) : 0;
    const float surfaceConfidence = saturate((surfaceSupport - 1.0f) * 0.25f);
    const float baseLuma = GetLuminance(base);
    base *= baseLuma > 0 ? min(1.0f, q25 / baseLuma) : 0;
    // A handful of coincidentally matching guides can still select two bright
    // ray samples. Partial support cannot lift above the independent common level.
    if (surfaceSupport < 9.0f)
    {
        const float3 conservative = lerp(commonBase, min(base,commonBase), surfaceConfidence);
        // An established current surface does not inherit the colour of rejected
        // background quadrants. Their common pedestal remains useful when the
        // guides cannot describe a volume, but not after independent same-surface
        // samples already establish the visible surface's lower population.
        base = lerp(conservative, base, smoothstep(3.5f,7.5f,surfaceSupport));
    }
    // Reference rank semantics: a bounded, supported centre keeps its exact RGB.
    // Averaging every accepted sample erased antialiased curves even when no sample
    // was an outlier. Unlike the old luma/chroma rescale, rejected pixels keep the
    // robust RGB reconstruction. Requiring outer-ring support also rejects a 2x2
    // impulse cluster which the old full-window range could accept circularly.
    const float3 innerMargin = 0.5f * max(innerMax-innerMin, 1e-5f);
    const float3 ringMargin = 0.5f * max(ringMax-ringMin, 1e-5f);
    const bool rankAccepted = innerCount >= 2 && ringCount >= 2 &&
        all(center.rgb >= innerMin-innerMargin) && all(center.rgb <= innerMax+innerMargin) &&
        all(center.rgb >= ringMin-ringMargin) && all(center.rgb <= ringMax+ringMargin);
    // Pool nine mixed derivatives: the median rejects isolated text corners.
    // Each 3x3 stencil cancels colour ramps and axis-aligned strokes. Require the
    // whole independent same-surface patch before using its noise statistic.
    // The 3x3 mixed derivative is separable: second differences along x per
    // row first, then along y, so only one row of partial sums stays live.
    float noiseKeys[9];
    float noiseSupport = 1;
    GroupMemoryBarrier();
    [unroll]
    for (uint w = 0; w < 25; ++w) noiseSupport = min(noiseSupport, weights[w]);
    float3 rowDifference[3][3];
    GroupMemoryBarrier();
    [unroll]
    for (int row = -2; row <= 2; ++row)
    {
        float3 colour[5];
        [unroll]
        for (int x = -2; x <= 2; ++x) colour[x+2] = float3(UnpackHalf3(g_ColorP[sm.x+x][sm.y+row]).rgb);
        [unroll]
        for (int nx = -1; nx <= 1; ++nx)
        {
            const float3 second = colour[nx+1] - 2.0f*colour[nx+2] + colour[nx+3];
            [unroll]
            for (int ny = -1; ny <= 1; ++ny)
            {
                const int sy = row - ny;
                if (sy >= -1 && sy <= 1)
                {
                    const float3 term = (sy == 0 ? -2.0f : 1.0f) * second;
                    rowDifference[ny+1][nx+1] = sy == -1 ? term : rowDifference[ny+1][nx+1] + term;
                }
            }
        }
    }
    GroupMemoryBarrier();
    [unroll]
    for (int ny = -1; ny <= 1; ++ny)
        [unroll]
        for (int nx = -1; nx <= 1; ++nx)
            noiseKeys[(ny+1)*3+nx+1] = dot(rowDifference[ny+1][nx+1], rowDifference[ny+1][nx+1]);
    GroupMemoryBarrier();
    [unroll]
    for (int phase = 0; phase < 9; ++phase)
    {
        [unroll]
        for (int pair = 0; pair < 4; ++pair)
        {
            const int a = 2*pair + (phase & 1), b = a+1;
            const float lo = min(noiseKeys[a],noiseKeys[b]);
            noiseKeys[b] = max(noiseKeys[a],noiseKeys[b]);
            noiseKeys[a] = lo;
        }
    }
    const float measuredNoise = sqrt(noiseKeys[4]/108.0f)*1.4826f;
    const float sigmaReference = lerp(min(quietNoise, directionalNoise), measuredNoise, noiseSupport);
    // A rank-rejected centre is replaced only when it sits far outside the envelope its own
    // supported neighbours span - that is what an impulse looks like. A centre that merely
    // sits at a local extremum of smooth content overshoots that envelope by a fraction of
    // it, and keeping the robust estimate there would print a smoothed copy of the current
    // frame: the cleaned reference has to be a fixed point on supported clean input, not
    // just on straight edges and flat fields.
    // The outer ring is the envelope to judge against, not the 3x3: an impulse cluster
    // inflates the inner one with its own samples, so a 2x2 cluster would look bounded.
    const float3 envelope = ringMax - ringMin;
    const float3 overshoot = max(ringMin - center.rgb, center.rgb - ringMax);
    const float3 outlier = saturate(overshoot / max(envelope, 1e-5f) - 1.0f);
    const float3 robust = reference; // Impulse rejection only; no reference-to-base smoothing.
    reference = rankAccepted ? center.rgb : lerp(center.rgb, robust, outlier);
    // Extrema in two noisy rings are not independent proof of structure. A
    // positive sparse ray must have local colour or directional continuation.
    // Straight 1px strokes and supported corners retain their exact reference.
    const bool sparsePositiveOutlier = matchingNeighbours < 2 && support < 0.1f &&
        center.a > median + max(3.0f*sigma, max(0.08f*median,1e-5f));
    if (sparsePositiveOutlier)
        reference = robust;

    // Fit same-surface colour to the independent material guide and transport
    // only the explained channels. Constant albedo supplies no material slope;
    // stochastic evidence below separately authorizes a spatial lighting model.
    // Unsupported colour retains the conservative pedestal and current reference.
    // Reject coloured ray impulses in illumination space before fitting. A bright
    // material texel has the same colour/albedo ratio as its neighbours; a ray does
    // not. Per-channel quartiles prevent a chromatic impulse from borrowing a luma
    // match, and centred moments remain well conditioned on bright HDR surfaces.
    // One luminance-ratio population trims impulses for the first fit; the
    // per-channel Tukey refit below still rejects chromatic outliers. Three
    // per-channel sorts here cost more than the rest of the first pass.
    float shadeKeys[25];
    // Geometry support is counted from the stored weights here, not in the
    // weights walk, where every live register sets the shader's occupancy.
    uint modelCount = 0;
    float modelSupport = 0;
    GroupMemoryBarrier();
    GroupMemoryBarrier();
    [unroll]
    for (uint sample = 0; sample < 25; ++sample)
    {
        const int2 q = sm + int2(sample % 5, sample / 5) - 2;
        const bool valid = ModelWeight(sample) > 0.1f;
        modelCount += valid ? 1 : 0;
        modelSupport += valid ? ModelWeight(sample) : 0.0f;
        shadeKeys[sample] = valid ? LoadShadeKey(q) : 1e20f;
    }
    float shadeMedian, shadeLower, shadeUpper;
    SortedQuartiles(shadeKeys, modelCount, shadeMedian, shadeLower, shadeUpper);
    const float shadeRange = max(3.0f * 0.7413f * (shadeUpper - shadeLower), max(shadeMedian * 0.08f, 1e-5f));
    // An isolated material-guide discontinuity is not independent evidence for
    // texture. If its radiance also disagrees with the supported illumination
    // population, keep the common pedestal and the rejected-reference contract.
    // Ordinary noisy texels with material support still use the robust model.
    const bool isolatedUnexplainedCenter = surfaceSupport < 2.5f &&
        abs(LoadShadeKey(sm) - shadeMedian) > shadeRange;
    float3 meanColor = 0, meanAlbedo = 0;
    float3 guideMean = 0, guideMoment = 0;
    float3 colorMoment = 0, albedoMoment = 0, crossMoment = 0;
    float momentWeight = 0;
    float momentWeightSquare = 0;
    const float3 ratioCentre = max(albedo, 0.02f);
    GroupMemoryBarrier();
    GroupMemoryBarrier();
    [loop]
    for (uint sample = 0; sample < 25; ++sample)
    {
        // The initial model only seeds the refit's residuals: the 13-tap
        // diamond is enough for it, and the refit below walks all 25 taps.
        const int2 diamond = int2(sample % 5, sample / 5) - 2;
        if (abs(diamond.x) + abs(diamond.y) > 2) continue;
        const int2 q = sm + int2(sample % 5, sample / 5) - 2;
        const float3 rgb = float3(UnpackHalf3(g_ColorP[q.x][q.y]));
        const float3 material = float3(UnpackHalf3(g_AlbedoP[q.x][q.y]));
        const float shadeError = abs(LoadShadeKey(q) - shadeMedian) / shadeRange;
        const float fitW = (ModelWeight(sample) > 0.1f ? ModelWeight(sample) : 0.0f) *
            Square(saturate(1.0f - shadeError));
        const float3 c = rgb - centerRGB;
        const float3 a = material - albedo;
        meanColor += fitW * c;
        meanAlbedo += fitW * a;
        colorMoment += fitW * c * c;
        albedoMoment += fitW * a * a;
        crossMoment += fitW * c * a;
        momentWeight += fitW;
        momentWeightSquare += fitW * fitW;
    }
    const float invMomentWeight = rcp(max(momentWeight, 1e-6f));
    meanColor *= invMomentWeight;
    meanAlbedo *= invMomentWeight;
    const float3 colorVariance = max(colorMoment * invMomentWeight - meanColor * meanColor, 0.0f);
    const float3 albedoVariance = max(albedoMoment * invMomentWeight - meanAlbedo * meanAlbedo, 0.0f);
    const float3 covariance = crossMoment * invMomentWeight - meanColor * meanAlbedo;
    const float effectiveSupport = momentWeight * momentWeight / max(momentWeightSquare, 1e-6f);
    float3 fitAlbedo = max(albedo + meanAlbedo, 1e-4f);
    float3 fitColor = max(centerRGB + meanColor, 0.0f);
    const float3 priorSlope = fitColor / fitAlbedo;
    // Sparse, almost equal albedos cannot support free extrapolation. A
    // through-origin prior retains C=L*A exactly on newly exposed strips.
    const float albedoCondition = dot(albedoVariance, 1.0f) / max(dot(albedo, albedo), 0.001f);
    const float sparseCondition = 1.0f - smoothstep(0.001f, 0.01f, albedoCondition);
    const float ridgeScale = 1e-4f + 0.01f * max(4.0f - effectiveSupport, 0.0f) * sparseCondition;
    const float3 varianceFloor = max(albedo * albedo * ridgeScale, 1e-12f);
    float3 slope = max(covariance + varianceFloor * priorSlope, 0.0f) /
        (albedoVariance + varianceFloor);
    // Ratio trimming rejects impulses, but its noise distribution depends on
    // albedo. Refit from residuals of that safe initial model with a robust scale
    // computed from every geometry-supported sample, not its selected population.
    // Without it, woven material texture lost ~3% of its detail through RR.
    const float3 residualMedian = 0.0f;
    const float3 residualRange = 4.685f * max(2.0f * sqrt(max(colorVariance - 2.0f * slope * covariance +
        slope * slope * albedoVariance, 0.0f)), max(fitColor * 0.0025f, 1e-6f));
    const float3 initialMeanColor = meanColor, initialMeanAlbedo = meanAlbedo, initialSlope = slope;
    meanColor = 0; meanAlbedo = 0; albedoMoment = 0; crossMoment = 0; colorMoment = 0;
    momentWeight = 0; momentWeightSquare = 0;
    GroupMemoryBarrier();
    [loop]
    for (uint sample = 0; sample < 25; ++sample)
    {
        const int2 q = sm + int2(sample % 5, sample / 5) - 2;
        const float3 c = float3(UnpackHalf3(g_ColorP[q.x][q.y])) - centerRGB;
        const float3 a = float3(UnpackHalf3(g_AlbedoP[q.x][q.y])) - albedo;
        const float3 e = abs((c - initialMeanColor) - initialSlope * (a - initialMeanAlbedo) - residualMedian) /
            residualRange;
        const float u = max(e.x, max(e.y, e.z));
        const float fitW = (ModelWeight(sample) > 0.1f ? ModelWeight(sample) : 0.0f) *
            Square(saturate(1.0f - u*u));
        // Exact-colour agreement and the guide minimum ride on this walk.
        if (sample != 12 && ModelWeight(sample) > 0.1f)
        {
            geometryAlbedoMinimum = min(geometryAlbedoMinimum, float3(UnpackHalf3(g_AlbedoP[q.x][q.y])));
            const float3 agreement = float3(abs(c.x) <= max(centerRGB.x * 1e-4f, 1e-6f),
                abs(c.y) <= max(centerRGB.y * 1e-4f, 1e-6f), abs(c.z) <= max(centerRGB.z * 1e-4f, 1e-6f));
            const int2 off = int2(sample % 5, sample / 5) - 2;
            if (all(abs(off) <= 1)) channelInnerSupport += agreement;
            else channelRingSupport += agreement;
        }
        const float geometryW = ModelWeight(sample) > 0.1f ? ModelWeight(sample) : 0.0f;
        guideMean += geometryW * a;
        guideMoment += geometryW * a * a;
        colorMoment += fitW * c * c;
        meanColor += fitW * c; meanAlbedo += fitW * a;
        albedoMoment += fitW * a * a; crossMoment += fitW * c * a;
        momentWeight += fitW; momentWeightSquare += fitW * fitW;
    }
    const float invRefitWeight = rcp(max(momentWeight, 1e-6f));
    meanColor *= invRefitWeight; meanAlbedo *= invRefitWeight;
    fitAlbedo = max(albedo + meanAlbedo, 1e-4f);
    fitColor = max(centerRGB + meanColor, 0.0f);
    const float3 refitVariance = max(albedoMoment * invRefitWeight - meanAlbedo * meanAlbedo, 0.0f);
    const float3 refitCovariance = crossMoment * invRefitWeight - meanColor * meanAlbedo;
    const float refitSupport = momentWeight * momentWeight / max(momentWeightSquare, 1e-6f);
    const float3 refitRidge = max(albedo * albedo *
        (1e-4f + 0.01f * max(4.0f - refitSupport, 0.0f) * sparseCondition), 1e-12f);
    slope = max(refitCovariance + refitRidge * fitColor / fitAlbedo, 0.0f) /
        (refitVariance + refitRidge);
    const float3 colorSquare = colorMoment;
    // Conditioning comes from the material guide, rather than a stochastic R^2
    // test. A constant albedo cannot authorize an affine texture reconstruction.
    const float3 independentGuideMean = guideMean / max(modelSupport - 1.0f, 1e-6f);
    const float3 independentGuideVariance = max(guideMoment / max(modelSupport - 1.0f, 1e-6f) -
        independentGuideMean * independentGuideMean, 0.0f);
    guideMean /= max(modelSupport, 1e-6f);
    const float3 guideVariance = max(guideMoment / max(modelSupport, 1e-6f) - guideMean * guideMean, 0.0f);
    const float materialEnergy = dot(guideVariance, 1.0f);
    const float guideEnergy = max(dot(albedo, albedo), 0.001f);
    const float3 channelCondition = guideVariance / max(albedo * albedo, 1e-12f);
    const float materialCondition = max(channelCondition.x, max(channelCondition.y, channelCondition.z));
    const float3 independentCondition = independentGuideVariance / max(albedo * albedo, 1e-12f);
    const float independentMaterialCondition = max(independentCondition.x, max(independentCondition.y, independentCondition.z));
    // On a constant material, fit the additive lighting as a spatial plane.
    // A robust average selected by noisy sample values biases a lighting ramp;
    // centred position moments retain its value at the current pixel instead.
    // Only a constant-material, fully supported centre can use that plane; on
    // game frames about one 8x8 tile in ten has one, so its position moments
    // are gathered by a second walk instead of riding on the moment pass.
    float2 positionMean = 0;
    float3 positionMoment = 0;
    float3 positionColorX = 0, positionColorY = 0;
    [branch]
    if (materialCondition < 0.00000025f && surfaceSupport >= 9.0f)
    {
        // The driver unrolls constant-count loops despite [loop]; an opaque
        // count keeps this rare walk rolled and out of the instruction cache.
        const uint windowTaps = min(25u, asuint(RenderSize.x));
        GroupMemoryBarrier();
        [loop]
        for (uint sample = 0; sample < windowTaps; ++sample)
        {
            const int2 q = sm + int2(sample % 5, sample / 5) - 2;
            const float3 rgb = float3(UnpackHalf3(g_ColorP[q.x][q.y]));
            const float3 material = float3(UnpackHalf3(g_AlbedoP[q.x][q.y]));
            const float3 c = rgb - centerRGB;
            const float3 e = abs((c - initialMeanColor) - initialSlope * (material - albedo - initialMeanAlbedo) -
                residualMedian) / residualRange;
            const float u = max(e.x, max(e.y, e.z));
            const float fitW = (ModelWeight(sample) > 0.1f ? ModelWeight(sample) : 0.0f) *
                Square(saturate(1.0f - u*u));
            const float2 offset = float2(int2(sample % 5, sample / 5) - 2);
            positionMean += fitW * offset;
            positionMoment += fitW * float3(offset.x * offset.x, offset.x * offset.y, offset.y * offset.y);
            positionColorX += fitW * c * offset.x;
            positionColorY += fitW * c * offset.y;
        }
    }
    positionMean *= invRefitWeight;
    positionMoment = positionMoment * invRefitWeight -
        float3(positionMean.x * positionMean.x, positionMean.x * positionMean.y,
               positionMean.y * positionMean.y);
    const float3 positionCovarianceX = positionColorX * invRefitWeight - meanColor * positionMean.x;
    const float3 positionCovarianceY = positionColorY * invRefitWeight - meanColor * positionMean.y;
    const float positionDeterminant = positionMoment.x * positionMoment.z - Square(positionMoment.y);
    const float inversePositionDeterminant = rcp(max(positionDeterminant, 1e-4f));
    const float3 planeX = (positionCovarianceX * positionMoment.z -
                          positionCovarianceY * positionMoment.y) * inversePositionDeterminant;
    const float3 planeY = (positionCovarianceY * positionMoment.x -
                          positionCovarianceX * positionMoment.y) * inversePositionDeterminant;
    const float3 planePrediction = max(fitColor - planeX * positionMean.x - planeY * positionMean.y, 0.0f);
    // The two affine parameters need actual retained samples. Geometry alone
    // cannot authorize a model whose robust fit kept only one or two values.
    // Bound extrapolation too: a rejected centre far from the retained guide
    // population must keep the conservative estimate instead of a fitted ray.
    const float3 predictionLeverage = invRefitWeight + meanAlbedo * meanAlbedo /
        max(momentWeight * (refitVariance + refitRidge), 1e-12f);
    const float textureConfidence =
        smoothstep(0.00000025f, 0.000002f, materialCondition) *
        smoothstep(1.5f, 2.5f, modelSupport) *
        smoothstep(2.0f, 3.0f, refitSupport) *
        (isolatedUnexplainedCenter && independentMaterialCondition < 0.000002f
            ? 0.0f : 1.0f);
    // Evidence in one colour channel cannot explain a different channel's
    // lighting boundary. Negative/absent covariance retains that channel's
    // conservative material-gated estimate and its original reference.
    const float3 candidateChannelConfidence = textureConfidence *
        smoothstep(0.00000025f, 0.000002f, channelCondition) *
        float3(refitCovariance.x > 0.0f && predictionLeverage.x <= 2.0f,
               refitCovariance.y > 0.0f && predictionLeverage.y <= 2.0f,
               refitCovariance.z > 0.0f && predictionLeverage.z <= 2.0f);
    // A positive stored coefficient authorizes the complete filtered source.
    // Keep that permission consistent with the colour prediction: a partially
    // anchored pedestal cannot be advertised as a complete material estimate.
    // A guide value outside the retained population (a silhouette texel, a new
    // material at a reveal) makes affine extrapolation unstable, but C=L*A still
    // holds there. Fall back to the through-origin ratio of the same robust
    // population and accept it only when the current observation agrees within
    // its local residual noise; unexplained colour keeps the conservative path.
    // meanColor is still the normalized centred colour mean here.
    const float3 colorSum = meanColor * momentWeight;
    // The proportional model reuses the albedo moments, centred on the query
    // albedo (the fallback requires it to be at least 0.02).
    const float3 ratioOffset = meanAlbedo * momentWeight;
    const float3 ratioOffsetSquare = albedoMoment, ratioCross = crossMoment;
    const float3 ratioColor = centerRGB * momentWeight + colorSum;
    const float3 ratioAlbedo = ratioCentre * momentWeight + ratioOffset;
    const float3 ratioSlope = ratioColor / max(ratioAlbedo, 1e-6f);
    const float3 ratioLevel = max(ratioColor * invRefitWeight, 1e-6f);
    // The proportional model must explain the population better than a
    // constant colour does. Radiance that is constant, or falls as albedo
    // rises, is lighting the guide does not describe; it keeps the old path.
    // Sum w*(d + c - s*r)^2 with d = centre - s*centreAlbedo, in closed form.
    const float3 ratioOffsetAtCentre = centerRGB - ratioSlope * ratioCentre;
    const float3 ratioResidual = max(momentWeight * ratioOffsetAtCentre * ratioOffsetAtCentre +
        2.0f * ratioOffsetAtCentre * (colorSum - ratioSlope * ratioOffset) +
        colorSquare - 2.0f * ratioSlope * ratioCross + ratioSlope * ratioSlope * ratioOffsetSquare, 0.0f);
    const float3 constantResidual = max(colorSquare - colorSum * colorSum * invRefitWeight, 0.0f);
    const float3 ratioPredicted = ratioSlope * max(albedo, 0.02f);
    const float3 ratioNoise = sqrt(max(ratioResidual * invRefitWeight *
        refitSupport / max(refitSupport - 1.0f, 1.0f), 0.0f));
    // Radiance noise scales with the signal; a brighter guide extrapolates it.
    const float3 ratioTolerance = max(4.5f * ratioNoise / ratioLevel * max(centerRGB, ratioPredicted),
        0.04f * max(centerRGB, ratioPredicted));
    const float3 ratioExplains = float3(ratioResidual.x < constantResidual.x,
        ratioResidual.y < constantResidual.y, ratioResidual.z < constantResidual.z);
    const float3 ratioChannel = textureConfidence >= 0.5f && refitSupport >= 3.0f && all(albedo >= 0.02f)
        ? ratioExplains * float3(candidateChannelConfidence.x < 0.5f && abs(centerRGB.x - ratioPredicted.x) <= ratioTolerance.x,
                 candidateChannelConfidence.y < 0.5f && abs(centerRGB.y - ratioPredicted.y) <= ratioTolerance.y,
                 candidateChannelConfidence.z < 0.5f && abs(centerRGB.z - ratioPredicted.z) <= ratioTolerance.z)
        : 0.0f;
    slope = lerp(slope, ratioSlope, ratioChannel);
    const float3 channelConfidence = max(float3(candidateChannelConfidence.x >= 0.5f,
                                            candidateChannelConfidence.y >= 0.5f,
                                            candidateChannelConfidence.z >= 0.5f), ratioChannel);
    const float modelConfidence = max(channelConfidence.x, max(channelConfidence.y, channelConfidence.z));
    const float3 quietChannel = float3(
        channelInnerSupport.x >= 2.0f && channelRingSupport.x >= 2.0f,
        channelInnerSupport.y >= 2.0f && channelRingSupport.y >= 2.0f,
        channelInnerSupport.z >= 2.0f && channelRingSupport.z >= 2.0f);
    base = lerp(base, centerRGB, quietChannel * (1.0f - channelConfidence));
    const float3 predicted = lerp(max(centerRGB + meanColor - slope * meanAlbedo, 0.0f), ratioPredicted, ratioChannel);
    const float3 residualVariance = max(colorSquare - momentWeight * meanColor * meanColor -
        2.0f * slope * (crossMoment - momentWeight * meanColor * meanAlbedo) +
        slope * slope * (albedoMoment - momentWeight * meanAlbedo * meanAlbedo), 0.0f);
    const float3 residualNoiseRGB = sqrt(max(residualVariance * invRefitWeight *
        refitSupport / max(refitSupport - 2.0f, 1.0f), 0.0f));
    const float residualNoise = sqrt(dot(residualNoiseRGB * residualNoiseRGB, channelConfidence) /
        max(dot(channelConfidence, 1.0f), 1.0f));
    const float grainEvidence = smoothstep(0.25f, 0.75f, sigmaReference / max(sigma, 1e-5f));
    // A sparse positive tail can inflate IQR without supplying stochastic
    // lighting on both sides of the median. It cannot authorize a lighting plane.
    const float noiseBalance = min(max(median - q25, 0.0f), max(q75 - median, 0.0f)) /
        max(q75 - q25, 1e-5f);
    const float planeConfidence = materialCondition < 0.00000025f &&
        surfaceSupport >= 9.0f && positionDeterminant > 0.01f
            ? grainEvidence * noiseSupport * smoothstep(0.025f, 0.075f, noiseBalance) : 0.0f;
    // A full-rank plane already estimates the complete current lighting field.
    // Its uncertainty is confidence, not a downward random offset in radiance.
    base = lerp(base, planePrediction, planeConfidence);
    // Filter the complete material model. Splitting its slope between Floor and
    // RR attenuates texture twice: after material transport, the stochastic
    // residual carries no additional trustworthy material detail.
    const float3 transportSlope = slope;
    const float3 modelBase = predicted;
    base = lerp(base, modelBase, channelConfidence);
    reference = lerp(reference, predicted, channelConfidence);
#if FSRD_FLOOR_SPARSE_TEST_CONTROL == 0
    // Sparse visible geometry can have little material-colour support. Rejected
    // quadrants may belong to a different surface and cannot erase its radiance.
    // Retain a conservative current-surface lower illumination population only
    // in channels without an accepted model. This is a pedestal, not new slope,
    // plane, reference, or complete-source authority. A rejected bright
    // centre still has this supported lower background: its impulse flags
    // must not switch that background off at a single-ULP colour boundary.
    // The lower rank and current-colour cap remain conservative, and the
    // original centre/reference/model impulse exclusions still apply.
    if (modelCount >= 3u && modelSupport >= 2.5f && modelSupport < 9.0f &&
        surfaceSupport < 9.0f && planeConfidence == 0.0f)
    {
        const float3 queryAlbedo = max(albedo, 0.02f);
        // A lower-ratio sample can amplify negative grain when its material
        // guide is small. Bound that guide-only gain independently per channel.
        const float3 ratioGain = queryAlbedo / max(geometryAlbedoMinimum, 0.02f);
        // A guide-only confidence goes continuously to zero at the gain and
        // dark-guide limits. A single FP16 guide ULP cannot toggle the whole
        // supported background. Keep the physical white-guide endpoint fully
        // supported, with a short confidence fade above it.
        const float3 guideConfidence = smoothstep(0.02f, 0.04f, geometryAlbedoMinimum) *
            (1.0f - smoothstep(1.0f, 1.02f, albedo)) *
            (1.0f - smoothstep(1.75f, 2.0f, ratioGain));
        // A marginal ninth tap must not remove the lower background.
        // Fade by weighted geometry support as the full 3x3 population is met.
        const float geometryConfidence = 1.0f - smoothstep(7.5f, 9.0f, modelSupport);
        const float3 permission = float3(channelConfidence.x == 0.0f,
            channelConfidence.y == 0.0f, channelConfidence.z == 0.0f) *
            guideConfidence * geometryConfidence;
        // With sparse weighted geometry support, one quiet lower anchor is
        // enough to reject a positive cluster. A quartile requires two such
        // anchors at counts five through eight and could copy four bright rays.
        // The per-channel lower illumination ratio is needed only here.
        float3 shadeMinimum = 1e20f;
        const uint windowTaps = min(25u, asuint(RenderSize.x));
        GroupMemoryBarrier();
        [loop]
        for (uint tap = 0; tap < windowTaps; ++tap)
        {
            const int2 q = sm + int2(tap % 5, tap / 5) - 2;
            if (ModelWeight(tap) > 0.1f)
                shadeMinimum = min(shadeMinimum, float3(UnpackHalf3(g_ColorP[q.x][q.y])) /
                    max(float3(UnpackHalf3(g_AlbedoP[q.x][q.y])), 0.02f));
        }
        const float3 sparsePedestal = min(shadeMinimum * queryAlbedo, centerRGB);
        base = max(base, sparsePedestal * permission);
    }
#endif
    // Each filter pass transports its current colour using the evolving slope.
    // The immutable reference remains independent evidence for the source split.
    OutColor[px] = half4(FloorRadiance(base), min(sigma, 65500.0f));
    OutDetailReference[px] = half4(FloorRadiance(reference),
        surfaceSupport >= 2.5f || (modelConfidence > 0.5f && modelSupport >= 2.5f)
            ? min(lerp(sigmaReference, residualNoise, modelConfidence), 65500.0f) : -1.0f);
    // Only the legacy zero-slope model uses this small clipping correction.
    // Lighting-plane models carry their separate permission in the alpha tag.
    const float clippingNoise = sigmaReference * grainEvidence;
    const float noiseRatio = (1.0f - modelConfidence) * clippingNoise /
        max(GetLuminance(base), 1e-5f);
    const float4 floorModel = planeConfidence > 0.0f && modelConfidence == 0.0f
        ? EncodeFloorPlane(planeConfidence) : EncodeFloorModel(transportSlope * channelConfidence, noiseRatio);
    OutFloorModel[px] = half4(floorModel);
    OutDepthGradient[px] = half4(GetSafeSignedFP16(gradient), OctahedralEncode(normal));
#if FSRD_FLOOR_CLEAN_LIGHTING
    // A projected clean lighting mean is already spatially filtered: its tag
    // keeps the wider Floor passes from flattening the curvature it retains.
    // It runs after every other output is stored, so it adds no live state to
    // the main path. The complete window must lie on one supported surface;
    // noiseSupport is already the smallest of its 25 surface weights.
    [branch]
    if (FSRD_FLOOR_REFERENCE_TEST_CONTROL == 0 && g_CoherentLighting == 0u && noiseSupport >= 0.75f &&
        modelConfidence == 0.0f && planeConfidence == 0.0f && !sparsePositiveOutlier)
    {
        GroupMemoryBarrier();
        float3 localLighting;
        if (LocalLightingProjection(sm, px, bounds, albedo, centerRGB, localLighting))
        {
            OutColor[px] = half4(FloorRadiance(localLighting), min(sigma, 65500.0f));
            OutFloorModel[px] = half4(-102.0f, -102.0f, -102.0f, floorModel.a);
        }
    }
    // A complete guide-only witness with broad derivative participation can
    // distinguish coherent extrema from the rank envelope's false rejection.
    // Sparse positive impulses and independent material models remain excluded.
    // Keep the cleaned reference authoritative for native signal selection.
    // Only conversion's final current-source output may consume this tag.
    if (FSRD_FLOOR_REFERENCE_TEST_CONTROL == 0 && g_CoherentLighting != 0u && all(px >= 2) &&
        all(px <= bounds - 2) && surfaceSupport >= 9.0f && modelConfidence == 0.0f && !sparsePositiveOutlier)
        OutFloorModel[px] = half4(-101.0f, -101.0f, -101.0f, floorModel.a);
#endif
}
