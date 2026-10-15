// Separate-NRD recovery research math. No production shader includes this yet.
// Histories, geometry validation, pool/lease/reset/dispatch and DC projection
// are caller responsibilities. In particular this is not a complete denoiser.
#ifndef FSRD_NRD_RECOVERY_RESEARCH_SUPPORT
#define FSRD_NRD_RECOVERY_RESEARCH_SUPPORT

struct NrdRecoveryMoment
{
    float3 mean;
    float3 variance;
    float squaredWeights;
    float age;
};

NrdRecoveryMoment NrdUpdateRecoveryMoment(NrdRecoveryMoment previous,
                                         float3 observed, bool reuse, bool eligible,
                                         float response)
{
    NrdRecoveryMoment result;
    const float rate = max(rcp(previous.age + 1.0f), response);
    const float3 delta = observed - previous.mean;
    result.mean = reuse ? previous.mean + rate * delta : observed;
    result.variance = reuse
        ? (1.0f - rate) * (previous.variance + rate * delta * delta) : 0.0f;
    result.squaredWeights = reuse
        ? (1.0f - rate) * (1.0f - rate) * previous.squaredWeights + rate * rate : 1.0f;
    result.age = eligible ? min(previous.age + 1.0f, 1024.0f) : 0.0f;
    return result;
}

float3 NrdRecoveryMeanVariance(NrdRecoveryMoment value)
{
    return max(value.variance, 0.0f) * value.squaredWeights /
           max(1.0f - value.squaredWeights, 1e-6f);
}

bool NrdRecoveryMomentMature(NrdRecoveryMoment value, float minimumAge,
                            float minimumEffectiveCount)
{
    return value.age >= minimumAge &&
           isfinite(value.age) && isfinite(value.squaredWeights) &&
           value.squaredWeights > 0.0f && value.squaredWeights <= 1.0f &&
           rcp(max(value.squaredWeights, 1e-12f)) >= minimumEffectiveCount &&
           all(isfinite(value.mean)) && all(isfinite(value.variance));
}

// mean = {E[(inputBand-RRBand)*RRBand], E[RRBand^2], E[RRBand]}.
// Local powers/covariance are computed from luma, over compatible 3x3 pixels.
// The moment's sample unit is one FRAME/PATCH, not nine independent pixels.
// stableEnergy = compatible 3x3 average(mean.z^2).
// meanUncertainty = compatible 3x3 average(SEM2.z).
// No noisy RGB enters this function or its returned CURRENT-RR gain.
float NrdRecoverySupportedRRGain(NrdRecoveryMoment value, float currentCovariance,
                                 float currentEnergy, float stableEnergy,
                                 float meanUncertainty, float sigma,
                                 float maximumGain, float minimumAge,
                                 float minimumEffectiveCount)
{
    if (!NrdRecoveryMomentMature(value, minimumAge, minimumEffectiveCount) ||
        !isfinite(currentCovariance) || !isfinite(currentEnergy) ||
        !isfinite(stableEnergy) || !isfinite(meanUncertainty))
        return 0.0f;
    const float3 sem2 = NrdRecoveryMeanVariance(value);
    const float positiveCovariance = max(value.mean.x - sigma * sqrt(sem2.x), 0.0f);
    const float estimatedExcess = positiveCovariance / max(value.mean.y, 1e-20f);
    const float currentExcess = max(currentCovariance, 0.0f) / max(currentEnergy, 1e-20f);
    const float coherence = max(0.0f, 1.0f - sigma * sigma * meanUncertainty /
                                                   max(stableEnergy, 1e-20f));
    return min(min(estimatedExcess, currentExcess), max(maximumGain - 1.0f, 0.0f)) * coherence;
}

// Paired-residual alternative. Output is still a non-DC band correction;
// it must never be used as a whole-lighting/current-noisy replacement.
float3 NrdRecoverySupportedPairedBand(NrdRecoveryMoment value, float sigma,
                                     float minimumAge, float minimumEffectiveCount)
{
    if (!NrdRecoveryMomentMature(value, minimumAge, minimumEffectiveCount))
        return 0.0f;
    const float3 sem2 = NrdRecoveryMeanVariance(value);
    const float3 weight = max(0.0f, 1.0f - sigma * sigma * sem2 /
                                            max(value.mean * value.mean, 1e-20f));
    return value.mean * weight;
}

// The ordinary recovery path excludes exact roughness zero. That filter-skip
// control cannot be counted as evidence of successful denoising/recovery.
bool NrdOrdinaryRecoverySurface(float signedDepth, float roughness,
                                float hitDistance, float4 primaryMotion)
{
    return isfinite(signedDepth) && abs(signedDepth) > 1e-5f &&
           isfinite(roughness) && roughness > 0.0f &&
           isfinite(hitDistance) && hitDistance > 0.0f &&
           all(isfinite(primaryMotion)) && primaryMotion.w >= 0.5f;
}

#endif
