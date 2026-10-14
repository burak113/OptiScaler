#ifndef FSRD_NRD_SIGNAL_ENCODING_HLSLI
#define FSRD_NRD_SIGNAL_ENCODING_HLSLI

float3 EncodeNrdSignal(float3 rgb, uint encoding)
{
    if (encoding == 0u) return rgb;
    // Exact Consumer c3f6fb... decode: R=Y-Cg+Co, G=Y+Cg, B=Y-Cg-Co,
    // followed by nonnegative clamp. Solve that linear system for (Y,Co,Cg).
    // Factor64/specular exposure belongs to Consumer and is never folded here.
    return float3((rgb.r + 2.0f * rgb.g + rgb.b) * 0.25f,
                  (rgb.r - rgb.b) * 0.5f,
                  (-rgb.r + 2.0f * rgb.g - rgb.b) * 0.25f);
}

#endif
