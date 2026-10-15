#ifndef FSRD_NRD_MATERIAL_QUANTIZATION_HLSLI
#define FSRD_NRD_MATERIAL_QUANTIZATION_HLSLI

// Material cues are finite, nonnegative and at most 65504. D3D float-format
// stores and f32tof16 permit/require RTZ rather than nearest-even. Quantize
// explicitly to an exactly representable half before that final conversion.
float NrdRoundMaterialComponentHalfNearestEven(float value)
{
    if (value < 0.00006103515625f) // 2^-14: half subnormal spacing is 2^-24.
        return round(value * 16777216.0f) * (1.0f / 16777216.0f);
    const uint bits = asuint(value);
    return asfloat((bits + 0xfffu + ((bits >> 13u) & 1u)) & 0xffffe000u);
}

float4 NrdRoundMaterialHalfNearestEven(float4 value)
{
    return float4(NrdRoundMaterialComponentHalfNearestEven(value.x),
                  NrdRoundMaterialComponentHalfNearestEven(value.y),
                  NrdRoundMaterialComponentHalfNearestEven(value.z),
                  NrdRoundMaterialComponentHalfNearestEven(value.w));
}
#endif
