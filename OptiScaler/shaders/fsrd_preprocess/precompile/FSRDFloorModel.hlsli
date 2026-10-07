#ifndef FSRD_FLOOR_MODEL
#define FSRD_FLOOR_MODEL

// A lighting slope can exceed FP16's range while every radiance sample remains
// representable. Independent logarithms retain each RGB channel's dynamic range.
// A=0 is the uninitialised/disabled model; valid zero slopes use the sentinel.
float4 EncodeFloorModel(float3 slope, float noiseRatio = 0.0f)
{
    const float3 safeSlope = max(slope, 0.0f);
    return float4(safeSlope.x > 0.0f ? log2(safeSlope.x) : -100.0f,
                  safeSlope.y > 0.0f ? log2(safeSlope.y) : -100.0f,
                  safeSlope.z > 0.0f ? log2(safeSlope.z) : -100.0f,
                  1.0f + clamp(noiseRatio, 0.0f, 0.9f));
}

float3 DecodeFloorModel(float4 model)
{
    if (model.a < 0.5f) return 0.0f;
    return float3(model.x > -99.0f ? exp2(model.x) : 0.0f,
                  model.y > -99.0f ? exp2(model.y) : 0.0f,
                  model.z > -99.0f ? exp2(model.z) : 0.0f);
}

// Constant-material lighting is modelled spatially rather than with an albedo
// slope. Its unused zero-slope payload carries separate lighting confidence.
float FloorPlaneConfidence(float4 model)
{
    return model.a >= 2.0f ? saturate(model.a - 2.0f) : 0.0f;
}

float FloorClippingNoiseRatio(float4 model)
{
    return model.a < 2.0f ? max(model.a - 1.0f, 0.0f) : 0.0f;
}

float4 EncodeFloorPlane(float confidence)
{
    return float4(-100.0f, -100.0f, -100.0f, 2.0f + saturate(confidence));
}

// Only a zero-slope model can carry this current-centre certificate. Keep alpha
// unchanged: spatial filtering, confidence and clipping still use the old model.
bool FloorCoherentLighting(float4 model)
{
    return model.a >= 0.5f && all(model.rgb == -101.0f);
}

// A locally projected mean is already spatially filtered. Its zero-slope
// payload prevents larger kernels from erasing curvature; it never selects raw
// colour or changes the existing residual/Skip consumer.
bool FloorLocalLightingProjection(float4 model)
{
    return model.a >= 0.5f && all(model.rgb == -102.0f);
}

#endif
