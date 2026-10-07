#include "FSRDPreprocessCommon.hlsli"
#include "FSRDFloorCommon.hlsli"
#include "FSRDFloorModel.hlsli"

#define MainRS \
    "RootFlags(0), CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 6)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 2))"
Texture2D<half4> InColor : register(t0);
Texture2D<float> InLinearDepth : register(t1);
Texture2D<half4> InDepthGradient : register(t2);
Texture2D<float3> InDiffAlbedo : register(t3);
Texture2D<half4> InDetailReference : register(t4);
Texture2D<half4> InFloorModel : register(t5);
RWTexture2D<half4> OutColor : register(u0);
RWTexture2D<half4> OutFloorModel : register(u1);
cbuffer CB_Analysis : register(b0)
{
    float4 DstTexSize;
    int StepSize;
    uint _Reserved0;
    uint2 AlbedoBase;
}



// Fit trusted constant-material lighting using 33 distinct surface-tested
// samples. Cubic reproduction avoids flattening broad lighting curvature.
bool FilterLightingCubic(int2 p, int2 bounds, float4 center, float z,
                          float4 guide, float3 n, float3 a, out float3 prediction,
                          out float planeConfidence)
{
    const bool horizontal = StepSize == 8;
    const int axis = horizontal ? p.x : p.y;
    const int axisBounds = horizontal ? bounds.x : bounds.y;
    prediction = center.rgb;
    planeConfidence = FloorPlaneConfidence(InFloorModel[p]);
    if (axisBounds < 32) return false;
    if (axisBounds - 4 < 32) return false;
    const int span = min(32 * 8, axisBounds - 4);
    const int first = clamp(axis - span / 2, 2, axisBounds - 2 - span);
    // The driver compiler unrolls constant-count loops despite [loop] and then
    // preloads every tap. A count it cannot fold keeps this rare fit rolled, so
    // its registers no longer set the occupancy of every Floor pixel.
    const uint taps = min(33u, asuint(DstTexSize.x));
    const float query = 2.0f * float(axis - first) / float(span) - 1.0f;
    float gram[16]; float3 rhs[4];
    [unroll] for (uint k=0;k<16;++k) gram[k]=0.0f;
    [unroll] for (uint k=0;k<4;++k) rhs[k]=0.0f;
    float weight=0.0f; float3 squares=0.0f;
    // Only rare lighting-plane pixels run this fit, but an unrolled 33-tap
    // weight array set the register budget of every Floor pixel. Keep the
    // loops rolled and recompute each tap weight where it is needed again.
    [loop]
    for (uint sample=0;sample<taps;++sample)
    {
        const int coordinate = first + (int(sample) * span + 16) / 32;
        const int2 q = horizontal ? int2(coordinate,p.y) : int2(p.x,coordinate);
        const float4 c=InColor[q],g=InDepthGradient[q];
        const float4 model=InFloorModel[q];
        const float3 tapA=FloorRadiance(InDiffAlbedo[q+int2(AlbedoBase)]);
        const float surface=FloorSurfaceWeight(z,InLinearDepth[q],guide.xy,float2(q-p),
            n,OctahedralDecode(g.zw),a,tapA);
        const float w=surface*(FloorPlaneConfidence(model)>=0.75f ? 1.0f : 0.0f);
        const float position=2.0f * float(coordinate - first) / float(span) - 1.0f;
        const float basis[4]={1.0f,position,position*position,
            position*position*position};
        [unroll] for(uint row=0;row<4;++row)
        {
            rhs[row]+=w*basis[row]*(c.rgb-center.rgb);
            [unroll] for(uint column=0;column<4;++column)
                gram[row*4+column]+=w*basis[row]*basis[column];
        }
        weight+=w; squares+=w*Square(c.rgb-center.rgb);
    }
    if(weight<6.0f) return false;
    float lower[16];
    [unroll] for(uint k=0;k<16;++k) lower[k]=0.0f;
    [unroll] for(uint row=0;row<4;++row)
    {
        [unroll] for(uint column=0;column<=row;++column)
        {
            float value=gram[row*4+column];
            [unroll] for(uint k=0;k<column;++k) value-=lower[row*4+k]*lower[column*4+k];
            if(row==column)
            {
                if(value<1e-5f*weight || !isfinite(value)) return false;
                lower[row*4+column]=sqrt(value);
            }
            else lower[row*4+column]=value/lower[column*4+column];
        }
    }
    const float queryBasis[4]={1.0f,query,query*query,query*query*query};
    float inverseColumn[4];float leverage=0.0f;
    [unroll] for(uint row=0;row<4;++row)
    {
        float value=queryBasis[row];
        [unroll] for(uint k=0;k<row;++k) value-=lower[row*4+k]*inverseColumn[k];
        inverseColumn[row]=value/lower[row*4+row];
        leverage+=inverseColumn[row]*inverseColumn[row];
    }
    if(leverage>0.7f) return false;
    // Leverage bounds variance; the equivalent signed weights also bound
    // amplification at asymmetric silhouettes and outside the cropped support.
    float queryWeights[4];
    [unroll] for(int row=3;row>=0;--row)
    {
        float value=inverseColumn[row];
        [unroll] for(int k=row+1;k<4;++k) value-=lower[k*4+row]*queryWeights[k];
        queryWeights[row]=value/lower[row*4+row];
    }
    float absoluteGain=0.0f, noiseGain=0.0f;
    [loop] for(uint sample=0;sample<taps;++sample)
    {
        const int coordinate=first+(int(sample)*span+16)/32;
        const int2 q = horizontal ? int2(coordinate,p.y) : int2(p.x,coordinate);
        const float4 g=InDepthGradient[q];
        const float3 tapA=FloorRadiance(InDiffAlbedo[q+int2(AlbedoBase)]);
        const float w=FloorSurfaceWeight(z,InLinearDepth[q],guide.xy,float2(q-p),
            n,OctahedralDecode(g.zw),a,tapA)*(FloorPlaneConfidence(InFloorModel[q])>=0.75f ? 1.0f : 0.0f);
        const float position=2.0f*float(coordinate-first)/float(span)-1.0f;
        const float basis[4]={1.0f,position,position*position,position*position*position};
        float equivalentWeight=0.0f;
        [unroll] for(uint k=0;k<4;++k) equivalentWeight+=queryWeights[k]*basis[k];
        equivalentWeight*=w;
        absoluteGain+=abs(equivalentWeight); noiseGain+=Square(equivalentWeight);
    }
    if(!isfinite(absoluteGain) || absoluteGain>3.0f || !isfinite(noiseGain) || noiseGain>0.7f)
        return false;
    float3 coefficients[4];
    [unroll] for(uint row=0;row<4;++row)
    {
        float3 value=rhs[row];
        [unroll] for(uint k=0;k<row;++k) value-=lower[row*4+k]*coefficients[k];
        coefficients[row]=value/lower[row*4+row];
    }
    [unroll] for(int row=3;row>=0;--row)
    {
        float3 value=coefficients[row];
        [unroll] for(int k=row+1;k<4;++k) value-=lower[k*4+row]*coefficients[k];
        coefficients[row]=value/lower[row*4+row];
    }
    precise float3 result=center.rgb;
    [unroll] for(uint k=0;k<4;++k) result+=queryBasis[k]*coefficients[k];

    if(!all(isfinite(result)) || any(result<0.0f)) return false;
    float3 explained=0.0f;
    [unroll] for(uint k=0;k<4;++k) explained+=coefficients[k]*rhs[k];
    const float3 residual=sqrt(max(squares-explained,0.0f)/max(weight-4.0f,1.0f));
    const float3 budget=max(max(3.25f*max(center.a,0.0f),max(center.rgb,result)*0.04f),1e-5f);
    // Geometry and albedo alone do not explain a light/chroma discontinuity.
    // Check both sampled residual and the query, which need not be a fitted tap.
    if(any(residual>budget) || any(abs(result-center.rgb)>budget)) return false;
    prediction=result;planeConfidence=1.0f;
    return true;
}

struct FloorTap
{
    float w; float surface; float3 recentered; float3 transport; float3 permission;
    float noiseRatio; float plane; float2 position;
};

// One surface/appearance-tested tap at q. The caller pairs taps symmetrically.
// surface is the geometric (depth/normal) weight; w carries material/appearance.
FloorTap EvaluateFloorTap(int2 p, int2 q, float spatial, float z, float4 guide, float3 n,
                          float3 a, float4 center, float lum, float range, float noise,
                          float3 centerModel, float3 modelPermission,
                          float centerNoiseRatio, float centerPlaneConfidence)
{
    FloorTap tap;
    const float4 c = InColor[q];
    const float4 g = InDepthGradient[q];
    const float3 tapA = FloorRadiance(InDiffAlbedo[q + int2(AlbedoBase)]);
    const float4 tapModelValue = InFloorModel[q];
    const float3 tapModel = DecodeFloorModel(tapModelValue);
    // A conditioned model transports the material colour explicitly. Its
    // coefficients may pool across textured albedo while geometry still gates
    // every tap. Constant-albedo/unsupported models retain the original gate.
    const float3 transportPermission = modelPermission *
        float3(tapModel.x > 0.0f, tapModel.y > 0.0f, tapModel.z > 0.0f);
    // Only geometry (depth/normal) is paired by the caller. The material gate
    // is texture, not a surface boundary, and stays a per-tap weight.
    const float surface = FloorSurfaceWeight(z, InLinearDepth[q], guide.xy, float2(q-p),
        n, OctahedralDecode(g.zw), a, a);
    const float material = FloorMaterialWeight(a, lerp(tapA, a, transportPermission));
    // Average affine coefficients together with their colour prediction. The
    // coefficient field evolves with this pass; no original reference noise
    // can be re-injected into a previously smoothed lighting estimate.
    const float3 recentered = FloorRadiance(c.rgb + tapModel * transportPermission * (a - tapA));
    const float tapRange = max(range, max(c.a, noise) * 3.25f);
    const float3 rgbRange = max(max(center.rgb, recentered) * 0.04f,
        max(max(c.a, noise) * 3.25f, 1e-5f));
    // The original uncertainty is luminance. Remove a common intensity
    // change before testing chroma, so proportional RGB lighting noise does
    // not receive a stricter gate in its brightest channel. Equal-luminance
    // colour boundaries still retain their complete RGB difference.
    const float tapLum = GetLuminance(recentered);
    const float3 chromaDifference = (recentered - center.rgb) -
        (recentered + center.rgb) * ((tapLum - lum) / max(tapLum + lum, 1e-5f));
    const float3 rgbDifference = abs(chromaDifference) / rgbRange;
    const float appearance = min(FloorRangeWeight(tapLum-lum, tapRange),
        Square(saturate(1.0f - Square(max(rgbDifference.x, max(rgbDifference.y, rgbDifference.z))))));
    tap.surface = surface;
    tap.w = material * appearance * spatial *
        (centerPlaneConfidence >= 0.75f && FloorPlaneConfidence(tapModelValue) == 0.0f ? 0.0f : 1.0f);
    tap.recentered = recentered;
    tap.transport = (tapModel - centerModel) * transportPermission;
    tap.permission = transportPermission;
    tap.noiseRatio = FloorClippingNoiseRatio(tapModelValue) - centerNoiseRatio;
    tap.plane = FloorPlaneConfidence(tapModelValue) - centerPlaneConfidence;
    tap.position = float2(q-p) / max(float(StepSize), 1.0f);
    return tap;
}

struct FloorSums
{
    float3 sum; float3 modelSum; float3 modelTotal; float total;
    float noiseRatioSum; float planeConfidenceSum;
    float2 positionMean; float3 positionMoment; float3 positionColorX, positionColorY;
};

// The four paired taps. Position moments serve only a lighting-plane centre,
// about one 8x8 tile in ten on game frames; the caller instantiates this walk
// with and without them, so other pixels skip that work entirely.
void AccumulateFloorPairs(const bool positions, int2 p, int2 bounds, bool diagonal, float z,
                          float4 guide, float3 n, float3 a, float4 center, float lum, float range,
                          float noise, float3 centerModel, float3 modelPermission,
                          float centerNoiseRatio, float centerPlaneConfidence,
                          float oneSidedTolerance, inout FloorSums acc)
{
    const int2 offsets[4] = {int2(-1,0),int2(1,0),int2(0,-1),int2(0,1)};
    [unroll]
    for (uint k=0; k<2; ++k)
    {
        const int2 o = offsets[2*k+1];
        const int2 direction = diagonal ? int2(o.x-o.y,o.x+o.y) : o;
        const float spatial = diagonal ? 0.25f : 0.5f;
        FloorTap pair[2];
        pair[0] = EvaluateFloorTap(p, clamp(p - StepSize * direction, 0, bounds), spatial, z, guide, n, a, center, lum,
            range, noise, centerModel, modelPermission, centerNoiseRatio, centerPlaneConfidence);
        pair[1] = EvaluateFloorTap(p, clamp(p + StepSize * direction, 0, bounds), spatial, z, guide, n, a, center, lum,
            range, noise, centerModel, modelPermission, centerNoiseRatio, centerPlaneConfidence);
        // The unpaired surplus of the stronger tap is kept only when that tap
        // agrees with the centre within the centre's own noise: on noisy input
        // its slope bias hides below the noise, on clean input the pair stays
        // exactly symmetric. Appearance and material stay per-tap weights.
        const float pairedSurface = min(pair[0].surface, pair[1].surface);
        // Accumulate each pair at once; holding all four taps raised the
        // register budget of every Floor pass.
        [unroll]
        for (uint side=0; side<2; ++side)
        {
            const FloorTap tap = pair[side];
            const float w = tap.w * (pairedSurface + (tap.surface - pairedSurface) *
                FloorRangeWeight(GetLuminance(tap.recentered) - lum, oneSidedTolerance));
            const float3 recentered = tap.recentered;
            acc.sum += (recentered - center.rgb)*w; acc.total += w;
            // Coefficients can pool only in channels already explained at this
            // pixel. Neighbouring material detail cannot grant authority to replace
            // an unrelated current channel whose covariance was rejected.
            // A rejected tap has no coefficient estimate; it is not a measured zero.
            // Pool only independently accepted coefficients in each colour channel.
            acc.modelSum += tap.transport*w;
            acc.modelTotal += w*tap.permission;
            acc.noiseRatioSum += tap.noiseRatio*w;
            acc.planeConfidenceSum += tap.plane*w;
            if (positions)
            {
                const float2 samplePosition = tap.position;
                acc.positionMean += w * samplePosition;
                acc.positionMoment += w * float3(Square(samplePosition.x), samplePosition.x * samplePosition.y,
                                                 Square(samplePosition.y));
                acc.positionColorX += w * (recentered - center.rgb) * samplePosition.x;
                acc.positionColorY += w * (recentered - center.rgb) * samplePosition.y;
            }
        }
    }
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    const int2 p = int2(id.xy), bounds = int2(DstTexSize.xy)-1;
    if (any(p > bounds)) return;
    const float4 center = InColor[p];
    if(FloorLocalLightingProjection(InFloorModel[p]))
    {
        OutColor[p]=half4(center);
        OutFloorModel[p]=InFloorModel[p];
        return;
    }
    const float lum = GetLuminance(center.rgb);
    const float noise = max(center.a, 0.0f);
    const float range = max(lum * 0.04f, noise * 3.25f);
    // No noisy evidence: only the small kernel is needed. All five dispatches have
    // the same contract, so later passes can return locally without another buffer.
    if (StepSize > 2 && noise < max(lum * 0.005f, 1e-5f))
    {
        OutColor[p] = half4(center);
        OutFloorModel[p] = InFloorModel[p];
        return;
    }
    const float z = InLinearDepth[p];
    const float4 guide = InDepthGradient[p];
    const float3 n = OctahedralDecode(guide.zw);
    const float3 a = FloorRadiance(InDiffAlbedo[p + int2(AlbedoBase)]);
    const float4 centerModelValue = InFloorModel[p];
    const float3 centerModel = DecodeFloorModel(centerModelValue);
    const float3 modelPermission = float3(centerModel.x > 0.0f, centerModel.y > 0.0f,
                                         centerModel.z > 0.0f);

    if ((StepSize == 8 || StepSize == 16) && FloorPlaneConfidence(centerModelValue) > 0.0f)
    {
        float3 prediction;float confidence;
        if(FilterLightingCubic(p,bounds,center,z,guide,n,a,prediction,confidence))
        {
            OutColor[p]=half4(FloorRadiance(prediction),center.a);
            const float4 filteredPlane=EncodeFloorPlane(confidence);
            OutFloorModel[p]=half4(FloorCoherentLighting(centerModelValue)
                ? float4(centerModelValue.rgb,filteredPlane.a) : filteredPlane);
            return;
        }
    }
    const bool constantModel = !any(centerModel > 0.0f);
    const float centerWeight = StepSize == 16 && constantModel
        ? (FloorPlaneConfidence(centerModelValue) > 0.0f ? 3.0f : 0.5f) : 1.0f;
    // Accumulate differences. Summing a constant HDR value with fractional
    // weights can land just below its exact FP16 representation and lose an ULP
    // on every pass. This form makes a constant field an exact fixed point.
    const float centerNoiseRatio = FloorClippingNoiseRatio(centerModelValue);
    const float centerPlaneConfidence = FloorPlaneConfidence(centerModelValue);
    // Alternate axial/diagonal support across scales. Four surface-tested taps
    // avoid reading both crosses at every scale while retaining both orientations.
    const bool diagonal = StepSize == 2 || StepSize == 8;
    // Opposite taps are evaluated as a pair and share their geometric weight: a
    // one-sided footprint at a silhouette would otherwise shift the estimate
    // along the lighting gradient. Paired taps reproduce a linear field.
    // The centre's statistical noise is the seed's model/derivative estimate,
    // which stays near zero on clean texture and ramps, unlike the IQR spread.
    const float residualNoise = InDetailReference[p].a;
    const float centreNoise = residualNoise >= 0.0f ? residualNoise : noise;
    const float oneSidedTolerance = max(3.25f * centreNoise, 0.005f * lum);
    FloorSums acc;
    acc.sum = 0.0f; acc.modelSum = 0.0f; acc.modelTotal = centerWeight; acc.total = centerWeight;
    acc.noiseRatioSum = 0.0f; acc.planeConfidenceSum = 0.0f;
    acc.positionMean = 0.0f; acc.positionMoment = 0.0f; acc.positionColorX = 0.0f; acc.positionColorY = 0.0f;
    [branch]
    if (centerPlaneConfidence > 0.0f)
        AccumulateFloorPairs(true, p, bounds, diagonal, z, guide, n, a, center, lum, range, noise,
            centerModel, modelPermission, centerNoiseRatio, centerPlaneConfidence, oneSidedTolerance, acc);
    else
        AccumulateFloorPairs(false, p, bounds, diagonal, z, guide, n, a, center, lum, range, noise,
            centerModel, modelPermission, centerNoiseRatio, centerPlaneConfidence, oneSidedTolerance, acc);
    const float3 sum = acc.sum, modelSum = acc.modelSum, modelTotal = acc.modelTotal;
    const float total = acc.total, noiseRatioSum = acc.noiseRatioSum, planeConfidenceSum = acc.planeConfidenceSum;
    const float2 positionMean = acc.positionMean;
    const float3 positionMoment = acc.positionMoment, positionColorX = acc.positionColorX, positionColorY = acc.positionColorY;
    // Alpha is the original local uncertainty, not a vanished confidence channel.
    const float noiseRatio = centerNoiseRatio + noiseRatioSum / total;
    float3 filtered = center.rgb + sum / total;
    // A clamped/asymmetric footprint must still reproduce a lighting ramp.
    // Fit its current filtered samples in position space instead of shifting
    // that ramp toward the footprint's centroid at the image boundary.
    if (centerPlaneConfidence > 0.0f)
    {
        const float2 meanPosition = positionMean / total;
        const float3 moments = positionMoment / total -
            float3(Square(meanPosition.x), meanPosition.x * meanPosition.y, Square(meanPosition.y));
        const float determinant = moments.x * moments.z - Square(moments.y);
        if (determinant > 1e-4f)
        {
            const float3 cx = positionColorX / total - (sum / total) * meanPosition.x;
            const float3 cy = positionColorY / total - (sum / total) * meanPosition.y;
            const float3 gx = (cx * moments.z - cy * moments.y) / determinant;
            const float3 gy = (cy * moments.x - cx * moments.y) / determinant;
            filtered -= gx * meanPosition.x + gy * meanPosition.y;
        }
    }
    OutColor[p] = half4(FloorRadiance(filtered), center.a);
    float4 filteredModel = EncodeFloorModel(max(centerModel + modelSum/modelTotal, 0.0f), noiseRatio);
    // Neighbours may refine an existing lighting model, but cannot grant its
    // complete-source permission to a centre rejected by the raw noise test.
    const float planeConfidence = centerPlaneConfidence > 0.0f
        ? centerPlaneConfidence + planeConfidenceSum / total : 0.0f;
    if (!any(centerModel + modelSum/modelTotal > 0.0f) && planeConfidence > 0.0f)
        filteredModel = EncodeFloorPlane(planeConfidence);
    if (centerModelValue.a >= 0.5f)
    {
        filteredModel.rgb = float3(modelSum.x == 0.0f ? centerModelValue.x : filteredModel.x,
                                   modelSum.y == 0.0f ? centerModelValue.y : filteredModel.y,
                                   modelSum.z == 0.0f ? centerModelValue.z : filteredModel.z);
    }
    OutFloorModel[p] = half4(filteredModel);
}
