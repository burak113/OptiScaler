#ifndef FSRD_NRD_SIGNAL_ENCODING_HLSLI
#define FSRD_NRD_SIGNAL_ENCODING_HLSLI

uint NrdNearestHalfBits(float value)
{
    const uint bits = asuint(value);
    const uint sign = (bits >> 16u) & 0x8000u;
    const uint magnitude = bits & 0x7fffffffu;
    if (magnitude >= 0x7f800000u)
        return sign | 0x7c00u | ((magnitude & 0x7fffffu) ? 0x200u : 0u);
    if (magnitude >= 0x38800000u)
    {
        // Integer bias includes the retained mantissa parity for ties-to-even.
        const uint rounded = ((magnitude + 0xfffu + ((magnitude >> 13u) & 1u)) >> 13u) - 0x1c000u;
        return sign | min(rounded, 0x7c00u);
    }
    const uint exponent = magnitude >> 23u;
    if (exponent < 102u) return sign;
    const uint shift = 126u - exponent;
    const uint mantissa = (magnitude & 0x7fffffu) | 0x800000u;
    const uint retained = mantissa >> shift;
    const uint remainder = mantissa & ((1u << shift) - 1u);
    const uint halfway = 1u << (shift - 1u);
    return sign | (retained + ((remainder > halfway || (remainder == halfway && (retained & 1u))) ? 1u : 0u));
}

float3 EncodeNrdSignal(float3 rgb, uint encoding)
{
    if (encoding == 0u) return rgb;
    // Exact Consumer c3f6fb... decode: R=Y-Cg+Co, G=Y+Cg, B=Y-Cg-Co,
    // followed by nonnegative clamp. Solve that linear system for (Y,Co,Cg).
    // Factor64/specular exposure belongs to Consumer and is never folded here.
    precise float3 encoded = float3((rgb.r + 2.0f * rgb.g + rgb.b) * 0.25f,
                                   (rgb.r - rgb.b) * 0.5f,
                                   (-rgb.r + 2.0f * rgb.g - rgb.b) * 0.25f);
    // Compute IEEE nearest-even words explicitly. Typed R16 storage and the
    // legacy half intrinsic need not supply this rounding rule; widening is
    // exact and storage receives already representable half values.
    return f16tof32(uint3(NrdNearestHalfBits(encoded.x), NrdNearestHalfBits(encoded.y), NrdNearestHalfBits(encoded.z)));
}

#endif
