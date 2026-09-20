#include "FSRDPreprocessCommon.hlsli"
#include "FSRDFloorCommon.hlsli"

#define MainRS \
    "RootFlags(0), CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 8)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1)), " \
    "StaticSampler(s0, filter = FILTER_MIN_MAG_MIP_LINEAR, " \
    "addressU = TEXTURE_ADDRESS_CLAMP, addressV = TEXTURE_ADDRESS_CLAMP, addressW = TEXTURE_ADDRESS_CLAMP)"

#define FLAGS_RAW_SOURCE_BLIT (1 << 0)
#define FLAGS_SCALE_SRC (1 << 1)
#define FLAGS_DIFFUSE_SIGNAL_INDIRECT (1 << 2)
#define FLAGS_SPECULAR_SIGNAL_INDIRECT (1 << 3)
#define FLAGS_DEBUG (1 << 16)
#define FLAGS_DEBUG_MODE_MASK (0xFF << 16)
#define FLAGS_DEBUG_DETAIL_CONFIDENCE (1 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_SKIP_SIGNAL (2 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_DENOISER_OUTPUT (3 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_DIRECT_SPECULAR (4 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_DIRECT_DIFFUSE (5 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_INDIRECT_DIFFUSE (6 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_DETAIL_CORRECTION (7 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_DETAIL_REFERENCE (8 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_INDIRECT_SPECULAR (12 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_RECONSTRUCTED_COLOR (13 << 17 | FLAGS_DEBUG)

Texture2D<half4> InIndirectSpecular : register(t0);
Texture2D<half4> InSpecularAlbedo : register(t1);
Texture2D<half4> InDirectDiffuse : register(t2);
Texture2D<half4> InDiffuseAlbedo : register(t3);
Texture2D<half4> InSkipSignal : register(t4);
Texture2D<half4> InNormals : register(t5);
Texture2D<half4> InDetailReference : register(t6);
Texture2D<float> InLinearDepth : register(t7);
RWTexture2D<half4> OutColor : register(u0);
SamplerState LinearSampler : register(s0);

cbuffer CB_Comp : register(b0)
{
    float4 DstTexSize;
    uint Flags;
    float DetailPreservation;
    float NoiseSuppression;
    float FloorHandoverAnchorClamp;
    float2 SourceUvScale;
    float2 SourceUvOffset;
    float FloorHandoverCorrelationMix;
    float3 _Padding0;
}

#define THREAD_GROUP_SIZE_X 8
#define THREAD_GROUP_SIZE_Y 8
#define NUM_THREADS 64
static const uint2 s_ThreadGroupSize = uint2(8,8);
// Search radius five plus a one-pixel patch halo. Every lane loads before the
// barrier, including lanes outside the logical extent of a partial group.
DEFINE_LDS_CONFIG(s_SM, 13);
DECLARE_LDS_ARRAY_2D(half3, g_RR, 13);
DECLARE_LDS_ARRAY_2D(half4, g_Reference, 13);
DECLARE_LDS_ARRAY_2D(float, g_Depth, 13);
DECLARE_LDS_ARRAY_2D(half3, g_Normal, 13);
DECLARE_LDS_ARRAY_2D(half3, g_Albedo, 13);

bool IsSet(uint mask) { return (Flags & mask) == mask; }
uint GetDebugMode() { return Flags & FLAGS_DEBUG_MODE_MASK; }
float3 Reconstruct(int2 p)
{
    return FloorRadiance(float3(InIndirectSpecular[p].rgb) * float3(InSpecularAlbedo[p].rgb) +
        float3(InDirectDiffuse[p].rgb) * float3(InDiffuseAlbedo[p].rgb) + float3(InSkipSignal[p].rgb));
}

// Rotate the symmetric RGB covariance and its orthonormal basis together.
// Fixed-size Jacobi sweeps avoid choosing a privileged luminance/chroma axis:
// equal-luminance coloured lettering is structure, just as grey lettering is.
void RotateAnchorCovariance(inout float3x3 c, inout float3x3 basis, uint a, uint b)
{
    const float off = c[a][b];
    if (abs(off) <= max(c[0][0]+c[1][1]+c[2][2],1e-20f)*1e-6f) return;
    const float tau = (c[b][b]-c[a][a])/(2.0f*off);
    const float t = (tau >= 0 ? 1.0f : -1.0f)/(abs(tau)+sqrt(1.0f+tau*tau));
    const float cosine = rsqrt(1.0f+t*t), sine = t*cosine;
    const float aa = c[a][a], bb = c[b][b];
    c[a][a] = aa-t*off;
    c[b][b] = bb+t*off;
    c[a][b] = c[b][a] = 0;
    [unroll]
    for (uint k=0; k<3; ++k)
    {
        if (k != a && k != b)
        {
            const float ka = c[k][a], kb = c[k][b];
            c[k][a] = c[a][k] = cosine*ka-sine*kb;
            c[k][b] = c[b][k] = sine*ka+cosine*kb;
        }
        const float va = basis[k][a], vb = basis[k][b];
        basis[k][a] = cosine*va-sine*vb;
        basis[k][b] = sine*va+cosine*vb;
    }
}

float3 AnchorColour(float3 candidate, float3 mean, float3 variance, float3 crossVariance, float anchor)
{
    float3x3 covariance = float3x3(
        variance.x,crossVariance.x,crossVariance.y,
        crossVariance.x,variance.y,crossVariance.z,
        crossVariance.y,crossVariance.z,variance.z);
    float3x3 basis = float3x3(1,0,0,0,1,0,0,0,1);
    [unroll]
    for (uint sweep=0; sweep<3; ++sweep)
    {
        RotateAnchorCovariance(covariance,basis,0,1);
        RotateAnchorCovariance(covariance,basis,0,2);
        RotateAnchorCovariance(covariance,basis,1,2);
    }
    const float3 extent = anchor*sqrt(max(float3(covariance[0][0],covariance[1][1],covariance[2][2]),0));
    const float3 local = mul(candidate-mean,basis);
    candidate = mean+mul(basis,clamp(local,-extent,extent));
    // Keep the original per-channel contract as well. Zero Anchor never calls
    // this function; constant RR therefore still has an exact constant anchor.
    const float3 tolerance = anchor*sqrt(variance);
    return clamp(candidate,max(mean-tolerance,0),mean+tolerance);
}

// Non-local means: compare small RGB patterns, not just two noisy centre
// colours. Subtract the expected independent-noise distance before weighting.
// This is a spatial estimator, not a claim that correlated illumination noise
// is independent: the RR anchor and correlation control handle that ambiguity.
float ReferencePatchWeight(int2 sm, int2 offset, int2 p, int2 bounds,
    float z, float2 gradient, float3 normal, float3 albedo, float variance)
{
    float distance = 0, support = 0;
    [unroll]
    for (int py=-1; py<=1; ++py)
    {
        [unroll]
        for (int px=-1; px<=1; ++px)
        {
            const int2 a = int2(px,py), b = offset+a;
            const int2 qa = sm+a, qb = sm+b;
            const float4 ra = g_Reference[qa.x][qa.y], rb = g_Reference[qb.x][qb.y];
            // Clamped duplicates outside the image are not independent evidence.
            if (ra.a < 0 || rb.a < 0 || any(p+a < 0) || any(p+a > bounds) ||
                any(p+b < 0) || any(p+b > bounds)) continue;
            const float wa = FloorSurfaceWeight(z,g_Depth[qa.x][qa.y],gradient,float2(a),
                normal,g_Normal[qa.x][qa.y],albedo,g_Albedo[qa.x][qa.y]);
            const float wb = FloorSurfaceWeight(z,g_Depth[qb.x][qb.y],gradient,float2(b),
                normal,g_Normal[qb.x][qb.y],albedo,g_Albedo[qb.x][qb.y]);
            const float w = min(wa,wb);
            const float3 delta = ra.rgb-rb.rgb;
            distance += w*dot(delta,delta)/3.0f;
            support += w;
        }
    }
    if (support < 3.0f) return 0.0f;
    distance = max(distance/support-2.0f*variance,0.0f);
    // A one-pixel corner can be outvoted by eight matching background pixels.
    // Retain its colour distinction while allowing the larger noise uncertainty
    // of a single sample. This only rejects a match, never invents/sharpens colour.
    const float3 centreDelta = float3(g_Reference[sm.x][sm.y].rgb)-
        float3(g_Reference[sm.x+offset.x][sm.y+offset.y].rgb);
    const float centreDistance = max(dot(centreDelta,centreDelta)/3.0f-4.0f*variance,0.0f);
    distance = max(distance,0.25f*centreDistance);
    return exp2(-distance/max(1.5f*variance,1e-12f));
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 groupID : SV_GroupID, uint3 gtID : SV_GroupThreadID)
{
    const int2 p = int2(groupID.xy * 8 + gtID.xy);
    const int2 bounds = int2(DstTexSize.xy)-1;
    const bool inBounds = all(p <= bounds);
    if (IsSet(FLAGS_RAW_SOURCE_BLIT))
    {
        if (!inBounds) return;
        const float2 uv = (float2(p)+0.5f)*DstTexSize.zw;
        OutColor[p] = IsSet(FLAGS_SCALE_SRC)
            ? InIndirectSpecular.SampleLevel(LinearSampler, uv*SourceUvScale+SourceUvOffset, 0)
            : InIndirectSpecular[p];
        return;
    }
    // Uniform fast path: no reference/guide reads or neighbourhood when detail is off.
    if (DetailPreservation <= 0.0f && !IsSet(FLAGS_DEBUG))
    {
        if (inBounds) OutColor[p] = half4(Reconstruct(p), 1);
        return;
    }
    const int2 origin = int2(groupID.xy*8)-int2(s_SM_HaloOffset);
    const uint tid = gtID.x + gtID.y*8;
    [unroll]
    for (uint i=0; i<s_SM_LoadsPerThread; ++i)
    {
        const uint flat = tid + i*64;
        if (flat < s_SM_ElementCount)
        {
            const int2 s = int2(flat%s_SM_Size.x, flat/s_SM_Size.x);
            const int2 q = clamp(origin+s, 0, bounds);
            g_RR[s.x][s.y] = Reconstruct(q);
            g_Reference[s.x][s.y] = InDetailReference[q];
            g_Depth[s.x][s.y] = InLinearDepth[q];
            g_Normal[s.x][s.y] = OctahedralDecode(InNormals[q].xy);
            g_Albedo[s.x][s.y] = InDiffuseAlbedo[q].rgb;
        }
    }
    GroupMemoryBarrierWithGroupSync();
    // The zero-rough domain is the only consumer of the structure statistic below, and in a
    // frame that is mostly ordinary material it is the ordinary path that runs: read the
    // classification first and skip the 9x9 statistic everywhere it cannot be used.
    if (!inBounds) return;
    const bool type1 = InNormals[p].a > 0.16f && InNormals[p].a < 0.5f;
    const int2 sm = int2(gtID.xy+s_SM_HaloOffset);
    const float3 rr = g_RR[sm.x][sm.y];
    const float4 reference = g_Reference[sm.x][sm.y];
    float3 filteredReference = reference.rgb;
    float confidence = 0.0f;
    float3 correction = 0.0f;
    if (reference.a >= 0.0f && (DetailPreservation > 0.0f || GetDebugMode() == FLAGS_DEBUG_DETAIL_REFERENCE))
    {
        const float z = g_Depth[sm.x][sm.y];
        const float2 gradient = float2(
            FloorDepthDerivative(g_Depth[sm.x-1][sm.y], z, g_Depth[sm.x+1][sm.y]),
            FloorDepthDerivative(g_Depth[sm.x][sm.y-1], z, g_Depth[sm.x][sm.y+1]));
        const float3 normal = g_Normal[sm.x][sm.y];
        const float3 albedo = g_Albedo[sm.x][sm.y];
        float3 lowRR = 0, lowReference = 0;
        float3 rrCenteredMean = 0, rrCenteredSquare = 0, rrCenteredCross = 0;
        float3 refCenteredMean = 0, refCenteredSquare = 0;
        float crossRGB = 0;
        float rrLumaMean = 0, refLumaMean = 0, rrLumaSquare = 0, refLumaSquare = 0, crossLuma = 0;
        float3 rrChromaMean = 0, refChromaMean = 0;
        float rrChromaSquare = 0, refChromaSquare = 0, crossChroma = 0;
        float noiseSquared = 0;
        float noiseKeys[25];
        uint noiseCount = 0;
        float3 referenceMin = reference.rgb, referenceMax = reference.rgb;
        float total = 0;
        float regionTotal = 0, regionDifference2 = 0;
        float3 regionMean = 0, regionSquare = 0;
        const float kernel[5] = {1,4,6,4,1};
        [unroll]
        for (int y=-2; y<=2; ++y)
        {
            [unroll]
            for (int x=-2; x<=2; ++x)
            {
                // Ordinary materials retain the small detail kernel. Only the
                // reference handover needs the wider split and RR statistics.
                if (!type1 && (abs(x) > 1 || abs(y) > 1)) continue;
                const int2 q = sm + int2(x,y);
                const float4 tapReference = g_Reference[q.x][q.y];
                const float surface = FloorSurfaceWeight(z, g_Depth[q.x][q.y], gradient,
                    float2(clamp(p+int2(x,y),0,bounds)-p), normal,
                    g_Normal[q.x][q.y], albedo, g_Albedo[q.x][q.y]);
                // An explicitly bypassed tap cannot lend content to detail at its neighbour.
                const float spatial = type1 ? kernel[x+2]*kernel[y+2] :
                    (x==0 ? 2.0f : 1.0f) * (y==0 ? 2.0f : 1.0f);
                const float w = (x==0 && y==0) ? spatial :
                    spatial*surface*(tapReference.a >= 0.0f ? 1.0f : 0.0f);
                const float3 tapRR = g_RR[q.x][q.y];
                if (type1)
                {
                    const bool independent = all(p+int2(x,y) >= 0) && all(p+int2(x,y) <= bounds);
                    const bool accepted = independent && surface > 0.1f && tapReference.a >= 0;
                    noiseKeys[(y+2)*5+x+2] = accepted ? tapReference.a : 1e20f;
                    noiseCount += accepted ? 1 : 0;

                }
                if (type1)
                {
                    const float3 centeredRR = tapRR-rr;
                    rrCenteredMean += w*centeredRR;
                    rrCenteredSquare += w*centeredRR*centeredRR;
                    rrCenteredCross += w*centeredRR.xxy*centeredRR.yzz;
                    const float3 centeredReference = tapReference.rgb-reference.rgb;
                    refCenteredMean += w*centeredReference;
                    refCenteredSquare += w*centeredReference*centeredReference;
                    crossRGB += w*dot(centeredRR,centeredReference);
                    const float lr = GetLuminance(centeredRR);
                    const float lp = GetLuminance(tapReference.rgb-reference.rgb);
                    rrLumaMean += w*lr; refLumaMean += w*lp;
                    rrLumaSquare += w*lr*lr; refLumaSquare += w*lp*lp;
                    crossLuma += w*lr*lp;
                    // Equal-luminance colour transitions are real structure too.
                    // Centre the moments before squaring, as for HDR luminance.
                    const float3 cr = centeredRR-lr;
                    const float3 cp = (tapReference.rgb-reference.rgb)-lp;
                    rrChromaMean += w*cr; refChromaMean += w*cp;
                    rrChromaSquare += w*dot(cr,cr)/3.0f;
                    refChromaSquare += w*dot(cp,cp)/3.0f;
                    crossChroma += w*dot(cr,cp)/3.0f;
                }
                lowRR += w*tapRR;
                lowReference += w*tapReference.rgb;
                if (type1)
                    noiseSquared += w*max(tapReference.a,0)*max(tapReference.a,0);
                total += w;
                if (w > 0.1f)
                {
                    referenceMin = min(referenceMin, tapReference.rgb);
                    referenceMax = max(referenceMax, tapReference.rgb);
                }
            }
        }
        lowRR /= max(total,1e-5f);
        lowReference /= max(total,1e-5f);
        const float3 highReference = reference.rgb - lowReference;
        const float3 highRR = rr - lowRR;
        const float signal = length(highReference);
        const float threshold = reference.a * lerp(1.0f,3.0f,NoiseSuppression);
        confidence = saturate((signal-threshold) / max(signal+threshold,1e-5f));
        // Only restore missing contrast with a consistent sign. Never replace an
        // already-sharp RR high band or add a second copy of the same detail.
        const float3 missing = sign(highReference) * max(abs(highReference)-max(sign(highReference)*highRR,0.0f),0.0f);
        const float strength = saturate(DetailPreservation * (type1 ? 3.0f : 1.0f));
        correction = strength * confidence * missing;
        if (type1)
        {
            [unroll]
            for (uint k=0; k<kSortNetworkSize; ++k)
            {
                const uint a = SortNetwork[2*k], b = SortNetwork[2*k+1];
                const float lo = min(noiseKeys[a],noiseKeys[b]);
                noiseKeys[b] = max(noiseKeys[a],noiseKeys[b]);
                noiseKeys[a] = lo;
            }
            // Curved/short lettering can occupy half this window. Estimate fine
            // grain from the quieter quartile so corners do not set the NLM
            // bandwidth or classify the glyph itself as noise. Coarse uncertainty
            // is handled separately by the unconditional RR controls below.
            // Tiny/unsupported patches retain the conservative RMS fallback.
            float patchNoise = sqrt(noiseSquared / total);
            [unroll]
            for (uint rank=0; rank<25; ++rank)
                if (noiseCount >= 9 && rank == (noiseCount-1)/4) patchNoise = noiseKeys[rank];
            float3 cleanReference = 0;
            float cleanReferenceWeight = 0;
            float cleanReferenceWeightSquared = 0;
            const float patchVariance = patchNoise*patchNoise*saturate(NoiseSuppression);
            // Regional RGB evidence is surface bounded. A different object must
            // not authorize copying noisy pixels here, and chromatic text matters
            // even when it has exactly the same luminance as its background.
            [loop]
            for (int ry=-5; ry<=5; ++ry)
            {
                [loop]
                for (int rx=-5; rx<=5; ++rx)
                {
                    const int2 offset = int2(rx,ry), q = sm+offset;
                    const float4 tap = g_Reference[q.x][q.y];
                    const bool independent = all(p+offset>=0) && all(p+offset<=bounds);
                    const float w = (tap.a >= 0 && independent) ?
                        FloorSurfaceWeight(z,g_Depth[q.x][q.y],gradient,float2(offset),
                            normal,g_Normal[q.x][q.y],albedo,g_Albedo[q.x][q.y]) : 0.0f;
                    const float3 centered = tap.rgb-reference.rgb;
                    const float3 difference = tap.rgb-float3(g_RR[q.x][q.y]);
                    // Keep confidence support independent of the search radius:
                    // a wider search must not dilute a small glyph's evidence.
                    if (abs(rx) <= 4 && abs(ry) <= 4)
                    {
                        regionTotal += w;
                        regionMean += w*centered;
                        regionSquare += w*centered*centered;
                        regionDifference2 += w*dot(difference,difference)/3.0f;
                    }
                    // Always retain the centre. No noisy-reference processing at
                    // zero suppression or zero measured noise. A matched patch
                    // contributes its original centre, not a blurred pilot pixel.
                    float match = 0;
                    if (rx == 0 && ry == 0) match = 1;
                    else if (w > 0.1f && patchVariance > 1e-12f)
                        match = ReferencePatchWeight(sm,offset,p,bounds,z,gradient,normal,albedo,patchVariance);
                    const float dw = w*match/(1.0f+0.0625f*dot(float2(offset),float2(offset)));
                    cleanReference += dw*tap.rgb;
                    cleanReferenceWeight += dw;
                    cleanReferenceWeightSquared += dw*dw;
                }
            }
            regionMean /= max(regionTotal,1e-5f);
            const float3 regionVariance = max(regionSquare/max(regionTotal,1e-5f)-regionMean*regionMean,0);
            const float amplitude = sqrt(dot(regionVariance,1.0f.xxx)/3.0f);
            const float regionNoise = patchNoise;
            regionMean += reference.rgb;
            // Confidence describes the filtered candidate, not the noisier input.
            // Effective sample count accounts for uneven NLM weights. This only
            // estimates independent fine grain; it never relaxes Anchor or Mix.
            const float effectiveSamples = max(Square(cleanReferenceWeight)/max(cleanReferenceWeightSquared,1e-8f),1.0f);
            const float candidateNoise = regionNoise*rsqrt(effectiveSamples);
            const float snr = amplitude/max(candidateNoise,1e-5f);
            const float structureWeight = step(max(length(regionMean)*1e-4f,1e-6f),amplitude) * smoothstep(1.20f,1.80f,snr) * max(
                smoothstep(0.22f,0.28f,amplitude/max(candidateNoise+GetLuminance(regionMean),1e-5f)),
                smoothstep(4.0f,8.0f,snr));
            // If the difference is explained by the measured noise, RR already
            // retained the current structure. Do not put that noise back into it.
            const float rrError = sqrt(regionDifference2/max(regionTotal,1e-5f));
            const float rrAgreement = 1.0f-smoothstep(0.8f,1.2f,
                rrError/max(regionNoise,1e-5f));
            float3 graft = cleanReferenceWeight > 1e-5f ? cleanReference/cleanReferenceWeight : reference.rgb;
            filteredReference = graft;
            const float3 meanDelta = rrCenteredMean/total;
            const float3 variance = max(rrCenteredSquare/total-meanDelta*meanDelta,0);
            const float3 refMeanDelta = refCenteredMean/total;
            const float refEnergy = dot(max(refCenteredSquare/total-refMeanDelta*refMeanDelta,0),1.0f.xxx);
            const float rrEnergy = dot(variance,1.0f.xxx);
            const float covarianceRGB = crossRGB/total-dot(meanDelta,refMeanDelta);
            // The reference controls restored on the current, surface-bounded
            // reconstruction. Both are inert at zero.
            if (FloorHandoverAnchorClamp > 0)
            {
                const float3 crossVariance = rrCenteredCross/total-meanDelta.xxy*meanDelta.yzz;
                // Like the reference DLL, a positive anchor always constrains
                // transferred colour. Repeated grain must not switch it off.
                // This intentionally trades some new-texture contrast for RR
                // stability; zero is the explicit opt-out, not a hidden gate.
                const float3 tolerance = FloorHandoverAnchorClamp*sqrt(variance);
                const float3 boxAnchor = clamp(graft,max(lowRR-tolerance,0),lowRR+tolerance);
                // The extra colour constraint is valid only if the two patches
                // agree on their structure. A stale RR palette cannot describe
                // new colours in an animated screen. The original box anchor
                // remains unconditional even when this additional test fails.
                const float paletteAgreement = saturate(covarianceRGB/max(sqrt(rrEnergy*refEnergy),1e-12f));
                const float colourAnchorWeight = smoothstep(0.65f,0.95f,paletteAgreement);
                graft = boxAnchor;
                if (colourAnchorWeight > 0)
                    graft = lerp(boxAnchor,AnchorColour(boxAnchor,lowRR,variance,crossVariance,
                        FloorHandoverAnchorClamp),colourAnchorWeight);
            }
            const float mr = rrLumaMean/total, mp = refLumaMean/total;
            const float vr = max(rrLumaSquare/total-mr*mr,0);
            const float vp = max(refLumaSquare/total-mp*mp,0);
            const float cov = crossLuma/total-mr*mp;
            const float lrMean = GetLuminance(lowRR), lpMean = GetLuminance(lowReference);
            const float lumaAgreement = saturate(((2*cov+1e-3f)/(vr+vp+1e-3f))*
                ((2*lrMean*lpMean+1e-2f)/(lrMean*lrMean+lpMean*lpMean+1e-2f)));
            const float3 mcr = rrChromaMean/total, mcp = refChromaMean/total;
            const float vcr = max(rrChromaSquare/total-dot(mcr,mcr)/3.0f,0.0f);
            const float vcp = max(refChromaSquare/total-dot(mcp,mcp)/3.0f,0.0f);
            const float ccp = crossChroma/total-dot(mcr,mcp)/3.0f;
            const float chromaStabilizer = max(4.0f*patchNoise*patchNoise,1e-6f);
            const float chromaAgreement = saturate((2.0f*ccp+chromaStabilizer)/
                max(vcr+vcp+chromaStabilizer,1e-6f));
            // Only colour structure supported by RR can dispute its luminance
            // agreement. Random colour grain over neutral/flat RR cannot do so.
            // The user's Mix is still applied directly to the resulting agreement.
            const float colourEvidence = vcr/(vcr+vr+chromaStabilizer);
            const float agreement = lerp(lumaAgreement,min(lumaAgreement,chromaAgreement),colourEvidence);
            // Direct reference-style correlation rejection. Do not attenuate
            // the user's mix by a fourth-power sigma/error term: coarse grain
            // can have a small high-frequency sigma and a very large RR error.
            confidence = structureWeight*(1.0f-rrAgreement)*
                (1.0f-saturate(FloorHandoverCorrelationMix)*agreement);
            correction = strength * confidence * (graft - rr);
        }
        else
        {
            correction = clamp(correction, -abs(highReference), abs(highReference));
        }
        // Missing negative contrast must not carve a dark ring below both RR and
        // the supported reference range (likewise for bright overshoot).
        correction = clamp(rr + correction, min(rr, referenceMin), max(rr, referenceMax)) - rr;
    }
    float3 output = FloorRadiance(rr + correction);
    if (IsSet(FLAGS_DEBUG))
    {
        const uint mode = GetDebugMode();
        switch (mode)
        {
        case FLAGS_DEBUG_DETAIL_CONFIDENCE: output = confidence.xxx; break;
        case FLAGS_DEBUG_SKIP_SIGNAL: output = InSkipSignal[p].rgb; break;
        // Historical meaning: demodulated RR signals, with no albedo or Skip added.
        case FLAGS_DEBUG_DENOISER_OUTPUT:
            output = float3(InIndirectSpecular[p].rgb) + float3(InDirectDiffuse[p].rgb); break;
        case FLAGS_DEBUG_RECONSTRUCTED_COLOR: output = rr; break;
        case FLAGS_DEBUG_DETAIL_REFERENCE: output = reference.a >= 0.0f ? filteredReference : 0.0f; break;
        case FLAGS_DEBUG_DETAIL_CORRECTION:
            output = saturate(0.5f + correction / max(GetLuminance(rr),1e-3f)); break;
        case FLAGS_DEBUG_DIRECT_SPECULAR:
        case FLAGS_DEBUG_INDIRECT_SPECULAR:
            output = (IsSet(FLAGS_SPECULAR_SIGNAL_INDIRECT) == (mode == FLAGS_DEBUG_INDIRECT_SPECULAR))
                ? float3(InIndirectSpecular[p].rgb)*float3(InSpecularAlbedo[p].rgb) : float3(1,0,1); break;
        case FLAGS_DEBUG_DIRECT_DIFFUSE:
        case FLAGS_DEBUG_INDIRECT_DIFFUSE:
            output = (IsSet(FLAGS_DIFFUSE_SIGNAL_INDIRECT) == (mode == FLAGS_DEBUG_INDIRECT_DIFFUSE))
                ? float3(InDirectDiffuse[p].rgb)*float3(InDiffuseAlbedo[p].rgb) : float3(1,0,1); break;
        }
    }
    OutColor[p] = half4(FloorRadiance(output),1);
}
