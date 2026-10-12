// Compare (split) view: draws variant A on the left and variant B on the right of a
// vertical divider, in one frame, so two pipeline variants can be judged side by side.
//
// This shader only selects between two already-computed images; it never runs the
// denoiser and never touches a history. In the production path it is dispatched only
// after the canonical SR pass, into a display-only composite (never into the canonical
// composition the upscaler consumes), so an inactive view costs nothing and the SR
// history never sees the split.
//
// When the destination (output) size differs from the source (render) size, both A and B
// are resampled with the same bilinear filter (COMPARE_RESAMPLE); otherwise the texel is
// read directly, which is exact.
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 2)), DescriptorTable(UAV(u0, numDescriptors = 1)), StaticSampler(s0, filter = FILTER_MIN_MAG_MIP_LINEAR, addressU = TEXTURE_ADDRESS_CLAMP, addressV = TEXTURE_ADDRESS_CLAMP, addressW = TEXTURE_ADDRESS_CLAMP)"

Texture2D<half4> InA : register(t0);
Texture2D<half4> InB : register(t1);
RWTexture2D<half4> OutColor : register(u0);
SamplerState LinearSampler : register(s0);

cbuffer CB_Compare : register(b0)
{
    float4 DstTexSize; // XY size, ZW 1/size
    uint Flags;
    uint DividerPx;    // divider column in pixels (clamped to [0, width])
    uint _Pad0;
    uint _Pad1;
}

#define COMPARE_SWAP     (1u << 0) // left/right variants exchange places
#define COMPARE_DIVIDER  (1u << 1) // draw the divider line
#define COMPARE_LABELS   (1u << 2) // draw the small "A" / "B" labels
#define COMPARE_RESAMPLE (1u << 3) // bilinear-resample A and B (unequal source/output size)

// 5x7 bitmap glyphs, one 7-bit column mask per column, bit 0 = top row.
static const uint kGlyphA[5] = { 0x7Eu, 0x09u, 0x09u, 0x09u, 0x7Eu };
static const uint kGlyphB[5] = { 0x7Fu, 0x49u, 0x49u, 0x49u, 0x36u };

bool GlyphPixel(const uint columns[5], int2 local, int scale)
{
    if (any(local < 0))
        return false;
    const int col = local.x / scale, row = local.y / scale;
    if (col >= 5 || row >= 7)
        return false;
    return ((columns[col] >> row) & 1u) != 0u;
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    const int2 p = int2(id.xy);
    const int width = int(DstTexSize.x);
    if (any(p >= int2(DstTexSize.xy)))
        return;

    const bool swap = (Flags & COMPARE_SWAP) != 0u;
    const uint divider = min(DividerPx, uint(width));
    const bool left = uint(p.x) < divider;
    // Swap exchanges which texture is the left half without moving the divider.
    const bool useA = swap ? !left : left;
    half4 colour;
    if ((Flags & COMPARE_RESAMPLE) != 0u)
    {
        // Normalized coordinates are resolution independent, so the same uv maps the whole
        // source; both halves therefore receive an identical bilinear filter.
        const float2 uv = (float2(p) + 0.5f) * DstTexSize.zw;
        colour = useA ? InA.SampleLevel(LinearSampler, uv, 0) : InB.SampleLevel(LinearSampler, uv, 0);
    }
    else
        colour = useA ? InA[p] : InB[p];

    // Two-pixel bright seam on columns [divider-1, divider].
    if ((Flags & COMPARE_DIVIDER) != 0u && p.x >= int(divider) - 1 && p.x <= int(divider))
        colour = half4(4.0f, 4.0f, 4.0f, 1.0f);

    if ((Flags & COMPARE_LABELS) != 0u)
    {
        const int scale = max(1, int(DstTexSize.x / 320.0f));
        const int labelY = 3 * scale;
        const int leftLabelX = 3 * scale;
        const int rightLabelX = int(divider) + 3 * scale;
        const uint leftGlyph[5] = { swap ? kGlyphB[0] : kGlyphA[0], swap ? kGlyphB[1] : kGlyphA[1],
                                    swap ? kGlyphB[2] : kGlyphA[2], swap ? kGlyphB[3] : kGlyphA[3],
                                    swap ? kGlyphB[4] : kGlyphA[4] };
        const uint rightGlyph[5] = { swap ? kGlyphA[0] : kGlyphB[0], swap ? kGlyphA[1] : kGlyphB[1],
                                     swap ? kGlyphA[2] : kGlyphB[2], swap ? kGlyphA[3] : kGlyphB[3],
                                     swap ? kGlyphA[4] : kGlyphB[4] };
        if (GlyphPixel(leftGlyph, p - int2(leftLabelX, labelY), scale) ||
            GlyphPixel(rightGlyph, p - int2(rightLabelX, labelY), scale))
            colour = half4(4.0f, 4.0f, 4.0f, 1.0f);
    }

    OutColor[p] = colour;
}
