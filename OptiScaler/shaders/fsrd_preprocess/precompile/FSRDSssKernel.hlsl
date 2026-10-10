#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors=2)), DescriptorTable(UAV(u0, numDescriptors=1))"
Texture2D<float4> InBounds:register(t0);
Texture2D<float> InDepth:register(t1);
RWTexture2D<float4> OutKernel:register(u0);
cbuffer CB_SssBlur : register(b0)
{
    float4 DstTexSize;
    float SigmaScale;
    float RadiusMeters;
    float Strength;
    float Falloff;
    uint Vertical;
    uint Debug;
    uint2 Padding;
}
groupshared uint Invalid;
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 gid:SV_GroupID,uint lane:SV_GroupIndex)
{
    const uint tileWidth=32u;
    const uint columns=(uint(DstTexSize.x)+tileWidth-1u)/tileWidth;
    const uint bands=(columns+127u)/128u;
    const int2 base=int2((gid.x&127u)*66u,gid.y*bands+(gid.x>>7u));
    // Every owner writes its header. A valid header exposes only the
    // 2*count coefficients written below and the denominator at slot65.
    // Other slots deliberately retain arbitrary prior contents.
    const int2 p=int2(gid.xy)*32;
    const int2 extent=int2(DstTexSize.xy);
    const float4 center=InBounds[p>>3];
    const float z=center.x;
    const float sigmaPx=SigmaScale/max(z,1e-3f);
    const float reach=3.0f*sigmaPx,tolerance=6.0f*RadiusMeters+0.01f*z;
    if(Strength==0.0f || center.z!=1.0f || center.x!=center.y || !isfinite(z) || z<=0 ||
       !isfinite(reach) || reach<0 || reach>32 || !(tolerance>0))
    {
        if(lane==0u) OutKernel[base]=0;
        return;
    }
    const int count=int(ceil(reach));
    // Original sampling rejects coordinates outside the frame. Only the
    // in-frame support needs the exact-depth/nonzero-guide proof.
    const int2 origin=max(p-int2(count,count),0);
    const int2 last=min(p+int2(31+count,31+count),extent-1);
    const int2 lo=origin>>3,hi=last>>3;
    const uint nx=uint(hi.x-lo.x+1),num=nx*uint(hi.y-lo.y+1);
    bool valid=true;
    for(uint index=lane;index<num;index+=64u)
    {
        const float4 bounds=InBounds[lo+int2(index%nx,index/nx)];
        valid=valid && bounds.z==1.0f && bounds.x==z && bounds.y==z;
    }
    if(lane==0u) Invalid=0u;
    GroupMemoryBarrierWithGroupSync();
    if(!valid) InterlockedOr(Invalid,1u);
    GroupMemoryBarrierWithGroupSync();
    if(lane!=0u) return;
    if(Invalid!=0u) { OutKernel[base]=0;return; }
    const float3 scale=float3(1.0f,1.0f-0.6f*Falloff,1.0f-0.7f*Falloff);
    const float3 sigma=max(sigmaPx*scale,1e-3f);
    const float3 first=exp(-0.5f/(sigma*sigma)),step=first*first;
    float3 tap=first,ratio=first*step,weight=1.0f;
    [loop] for(int i=1;i<=count;++i)
    {
        const float3 w=tap;tap*=ratio;ratio*=step;
        const int2 delta=Vertical!=0u?int2(0,i):int2(i,0);
        const float dl=saturate(1.0f-abs(abs(InDepth[clamp(p-delta,0,extent-1)])-z)/tolerance);
        const float dr=saturate(1.0f-abs(abs(InDepth[clamp(p+delta,0,extent-1)])-z)/tolerance);
        const float3 left=w*dl,right=w*dr;
        OutKernel[base+int2(2*i-1,0)]=float4(left,0);
        OutKernel[base+int2(2*i,0)]=float4(right,0);
        weight+=left;weight+=right;
    }
    OutKernel[base+int2(65,0)]=float4(weight,0);
    OutKernel[base]=float4(1,count,z,0);
}
