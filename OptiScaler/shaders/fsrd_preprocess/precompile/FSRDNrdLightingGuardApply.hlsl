// Positive change: one frame only where bilinear sub-block support exceeds .2 inside the confirmed tile.
// Negative change: two frames with one 32-pixel tile of surrounding support.
// The second pass reads a completed tile map; no cross-group UAV read/write race or Bayer phase.
#include "FSRDNrdLightingGuard_Common.hlsli"
[RootSignature(RS_APPLY)]
[numthreads(8,8,1)]
void CSMain(uint3 id:SV_DispatchThreadID)
{
    uint2 p=id.xy;if(p.x>=Width||p.y>=Height)return;
    int2 tile=int2(p/32),extent=int2((Width+31)/32,(Height+31)/32);
    uint active=0;
    [branch] if(CurrentTile.Load(int3(tile,0))&(1u<<17))
    {
        int2 cells=extent*4;
        float2 q=clamp((float2(p)+.5)/8-.5,0,float2(cells-1));
        int2 a=int2(floor(q)),b=min(a+1,cells-1);float2 f=q-a;
        // Interpolate each lobe first; taking the max before interpolation expands support.
        precise float2 top=CurrentChange.Load(int3(a,0))+f.x*(CurrentChange.Load(int3(b.x,a.y,0))-CurrentChange.Load(int3(a,0)));
        precise float2 bottom=CurrentChange.Load(int3(a.x,b.y,0))+f.x*(CurrentChange.Load(int3(b,0))-CurrentChange.Load(int3(a.x,b.y,0)));
        precise float2 value=top+f.y*(bottom-top);
        active=max(value.x,value.y)>.2;
    }
    [unroll] for(int y=-1;y<=1;y++) [unroll] for(int x=-1;x<=1;x++)
    {
        int2 q=tile+int2(x,y);
        if(all(q>=0)&&all(q<extent))active|=CurrentTile.Load(int3(q,0))&(1u<<16);
    }
    float4 m=InMotion.Load(int3(p,0));
    [branch] if(active)
    {
        float z=InDepth.Load(int3(p,0)),az=abs(z);
        float sentinel=(z<0?-65504.0:65504.0);
        // Warp's one-sided test uses current far to bound every accepted previous tap.
        // This finite half value is selected only when its actual float32 prediction exceeds
        // the normal-independent threshold bound with margin. No universal .5*z assumption.
        float threshold=Disocclusion*max(1,10*az*ProjectionToViewY*min(Width,Height)/Height);
        float margin=abs(z+sentinel)-MaxPreviousDepth;
        // Different compiler multiply/divide order can differ by several ULP at extreme controls.
        float allowance=max(.01,threshold*1e-5);
        if(isfinite(z)&&isfinite(threshold)&&az>0&&az<500&&margin>threshold+allowance)m.z=sentinel;
    }
    OutMotion[p]=m;
}
