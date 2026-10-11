#include "FSRDFlatDetailBindings.hlsli"
groupshared uint2 Reference[10][10], Normal[10][10];
groupshared float Depth[10][10];
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 group : SV_GroupID, uint3 local : SV_GroupThreadID)
{
    const uint tile=group.x+65535u*group.y;
    if (tile>=InTiles.Load(0)) return;
    const int2 origin=FlatOrigin(tile);
    const uint lane=local.y*8+local.x;
    for (uint i=lane;i<100;i+=64)
    {
        const int2 q=origin+int2(i%10,i/10)-1;
        const bool valid=FlatPixel(q);
        Reference[i/10][i%10]=FlatPack(valid ? InReference[q] : float4(0,0,0,-1));
        Normal[i/10][i%10]=FlatPack(valid ? InNormals[q] : 0.0f);
        Depth[i/10][i%10]=valid ? InDepth[q] : 0.0f;
    }
    GroupMemoryBarrierWithGroupSync();
    const int2 p=origin+int2(local.xy),c=int2(local.xy)+1;
    if (!FlatPixel(p)) return;
    const float4 centre=FlatUnpack(Reference[c.y][c.x]);
    const float z=Depth[c.y][c.x];
    const float3 n=OctahedralDecode(FlatUnpack(Normal[c.y][c.x]).xy);
    const float2 gradient=float2(DepthDerivative(Depth[c.y][c.x-1],z,Depth[c.y][c.x+1]),
                                DepthDerivative(Depth[c.y-1][c.x],z,Depth[c.y+1][c.x]));
    float3 sum=0;
    float total=0,noise=0;
    [unroll] for (int y=-1;y<=1;++y) [unroll] for (int x=-1;x<=1;++x)
    {
        const int2 q=c+int2(x,y);
        const float4 v=FlatUnpack(Reference[q.y][q.x]);
        if (v.a<0) continue;
        const float surface=FlatSurfaceWeight(z,Depth[q.y][q.x],gradient,float2(x,y),n,
            OctahedralDecode(FlatUnpack(Normal[q.y][q.x]).xy));
        const float3 delta=v.rgb-centre.rgb;
        const float range=max(4.0f*(v.a*v.a+centre.a*centre.a),Epsilon*Epsilon);
        const float appearance=saturate(1.0f-dot(delta,delta)/(3.0f*range));
        const float w=surface*appearance*appearance*(x==0 ? 2.0f:1.0f)*(y==0 ? 2.0f:1.0f);
        sum+=w*v.rgb; total+=w; noise+=w*w*v.a*v.a;
    }
    const float sigma=sqrt(noise)/max(total,1e-6f);
    OutColor[p]=float4(SanitizeRadiance(sum/max(total,1e-6f)),sigma);
    OutStatistics[p]=float4(sigma,InStatistics[p].y,0,0);
}
