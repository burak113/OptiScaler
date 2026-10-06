// Offline-only historical experiment; not compiled into OptiScaler.
// Historical coefficient reconstruction. Signed FP32 intermediates.
#define RS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0,numDescriptors=6)), DescriptorTable(UAV(u0,numDescriptors=2))"
Texture2D<float4> T0 : register(t0);
Texture2D<float4> T1 : register(t1);
Texture2D<float4> T2 : register(t2);
Texture2D<float4> T3 : register(t3);
Texture2D<float4> Base : register(t4);
Texture2D<float4> T5 : register(t5);
RWTexture2D<float4> Out0 : register(u0);
RWTexture2D<float4> Out1 : register(u1);
cbuffer Experiment : register(b0)
{
    uint2 Size;
    uint2 GridSize;
    int2 Shift;
    float Rejection;
    uint SpatialOnly;
};
groupshared float3 A[256];
groupshared float3 B[256];
groupshared uint Alive[256];
groupshared uint Valid[4];
groupshared uint TotalValid;
float Basis(uint f,uint x)
{
    return (f==0 ? 0.353553390593274f : 0.5f)*cos(3.141592653589793f*(float(x)+.5f)*float(f)/8.0f);
}
float4 ReadFrame(uint f,int2 p)
{
    if(f==0)return T0[p];
    if(f==1)return T1[p];
    if(f==2)return T2[p];
    return T3[p];
}
[RootSignature(RS)]
[numthreads(8,8,1)]
void Forward(uint3 id:SV_DispatchThreadID,uint3 local:SV_GroupThreadID)
{
    uint lane=local.y*8+local.x;
    int2 p=clamp(int2(id.xy)+Shift,0,int2(Size)-1);
    float3 baseline=Base[p].rgb;
    [unroll] for(uint f=0;f<4;++f)
    {
        float4 v=ReadFrame(f,p);
        A[f*64+lane]=v.rgb-baseline;
        Alive[f*64+lane]=(v.a>=0 && all(isfinite(v))) ? 1 : 0;
    }
    GroupMemoryBarrierWithGroupSync();
    if(lane<4)
    {
        uint accepted=1;
        [unroll] for(uint i=0;i<64;++i) accepted &= Alive[lane*64+i];
        Valid[lane]=accepted;
    }
    GroupMemoryBarrierWithGroupSync();
    if(lane==0)TotalValid=Valid[0]+Valid[1]+Valid[2]+Valid[3];
    GroupMemoryBarrierWithGroupSync();
    // Raw RGB may recover fine letters already removed by FloorSeed, but only
    // with a second accepted observation. The startup/rejection path uses the
    // cleaned reference, retaining its isolated-firefly protection.
    if(TotalValid<2)A[lane]=T5[p].rgb-baseline;
    GroupMemoryBarrierWithGroupSync();
    [unroll] for(uint f=0;f<4;++f)
    {
        float3 v=0;
        [unroll] for(uint x=0;x<8;++x) v+=Basis(local.x,x)*A[f*64+local.y*8+x];
        B[f*64+lane]=v;
    }
    GroupMemoryBarrierWithGroupSync();
    float3 sum=0, square=0;
    float3 coefficients[4];
    uint count=0;
    [unroll] for(uint f=0;f<4;++f)
    {
        float3 v=0;
        [unroll] for(uint y=0;y<8;++y) v+=Basis(local.y,y)*B[f*64+y*8+local.x];
        coefficients[f]=v;
        sum+=Valid[f] ? v : 0;
        square+=Valid[f] ? v*v : 0;
        count+=Valid[f];
    }
    float3 mean=sum/max(float(count),1);
    float3 variance=max(square-sum*mean,0)/max(float(count*(count-1)),1);
    Out0[id.xy]=float4(mean,count);
    // Adjacent temporal increments cancel constant structure. Their covariance
    // estimates dependence of the noise observations without a clean target.
    float covariance=0;
    if(count==4)
        covariance=(dot(coefficients[0]-coefficients[1],coefficients[1]-coefficients[2])+
                    dot(coefficients[1]-coefficients[2],coefficients[2]-coefficients[3]))/6.0f;
    Out1[id.xy]=float4(variance,covariance);
}
[RootSignature(RS)]
[numthreads(8,8,1)]
void Filter(uint3 id:SV_DispatchThreadID)
{
    int2 p=id.xy;
    float4 centre=T0[p];
    float3 variance=0;
    float3 samples[25];
    uint n=0;
    float covarianceSum=0, varianceSum=0;
    uint dependentSamples=0;
    [loop] for(int y=-2;y<=2;++y)
    [loop] for(int x=-2;x<=2;++x)
    {
        int2 q=p+int2(x,y)*8;
        if(any(q<0)||any(q>=int2(GridSize)))continue;
        float4 v=T1[q];
        float4 coefficient=T0[q];
        if(centre.a>=2 && coefficient.a>=2 && (SpatialOnly&1)==0)
        {
            variance+=v.rgb;
            n++;
            if(centre.a==4 && coefficient.a==4)
            {
                covarianceSum+=v.a;
                varianceSum+=dot(v.rgb,float3(1,1,1))/3;
                dependentSamples++;
            }
        }
        else if(centre.a<2 || (SpatialOnly&1)!=0)
        {
            samples[n++]=abs(T0[q].rgb);
        }
    }
    if(centre.a<2 || (SpatialOnly&1)!=0)
    {
        // Conservative single-observation fallback; repeated spatial detail can
        // inflate this uncertainty. It is measured separately, not hidden.
        [loop] for(uint a=1;a<n;++a)
        {
            float3 v=samples[a];
            [loop] for(uint b=0;b<a;++b)
            {
                float3 lo=min(v,samples[b]);
                v=max(v,samples[b]);samples[b]=lo;
            }
            samples[a]=v;
        }
        float3 sigma=n ? samples[n/2]/.67448975f : 0;
        variance=sigma*sigma;
    }
    else
    {
        variance/=max(float(n),1);
        // A local flash must not dilute its own uncertainty across 25 blocks.
        // For one outlier among four observations, k=2 cancels that coefficient.
        variance=max(variance,.5f*T1[p].rgb);
    }
    float correlation=0;
    if((SpatialOnly&2)!=0 && dependentSamples>=9 && varianceSum>1e-10f)
    {
        // For four AR(1) observations, -cov(delta_i,delta_i+1)/Var(mean)
        // equals 48*(1-rho)/(2*rho^2+6*rho+12), where Var(mean) here is the
        // ordinary sample-variance estimate that incorrectly assumes independence.
        // This is an observed-noise model, not a universal physical separation.
        float ratio=clamp(-covarianceSum/varianceSum,0.0f,4.0f);
        float b=6*ratio+48;
        float rho=2*(48-12*ratio)/(b+sqrt(b*b+8*ratio*(48-12*ratio)));
        correlation=min(saturate((rho-.25f)/.75f),.9f);
        float sumCov=4+6*correlation+4*correlation*correlation+2*correlation*correlation*correlation;
        variance*=3*sumCov/max(16-sumCov,1e-4f);
    }
    float power=dot(centre.rgb,centre.rgb)/3;
    float uncertainty=dot(variance,float3(1,1,1))/3;
    // RGB shares one permission, preventing channel-by-channel hue selection.
    float gain=saturate(1-Rejection*uncertainty/max(power,1e-16f));
    // No independent observation: retain the supplied, already cleaned spatial
    // reference. A second spectral shrink destroyed clean glyphs at startup and
    // texture cuts. Keep that failed shrink only in the explicit spatial ablation.
    if(centre.a==1 && (SpatialOnly&1)==0)gain=1;
    if(centre.a==0)gain=0;
    Out0[p]=float4(centre.rgb*gain,centre.a);
    Out1[p]=float4(gain,uncertainty,power,correlation);
}
[RootSignature(RS)]
[numthreads(8,8,1)]
void Inverse(uint3 id:SV_DispatchThreadID,uint3 local:SV_GroupThreadID)
{
    uint lane=local.y*8+local.x;
    A[lane]=T0[id.xy].rgb;
    GroupMemoryBarrierWithGroupSync();
    float3 v=0;
    [unroll] for(uint x=0;x<8;++x)v+=Basis(x,local.x)*A[local.y*8+x];
    B[lane]=v;
    GroupMemoryBarrierWithGroupSync();
    v=0;
    [unroll] for(uint y=0;y<8;++y)v+=Basis(y,local.y)*B[y*8+local.x];
    int2 p=clamp(int2(id.xy)+Shift,0,int2(Size)-1);
    // Signed detail survives until the final radiance clamp.
    Out0[id.xy]=float4(clamp(Base[p].rgb+v,0,65500),1);
    Out1[id.xy]=float4(v,1);
}
