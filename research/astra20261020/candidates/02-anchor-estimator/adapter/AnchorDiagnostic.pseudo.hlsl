// Source-shaped specification, NOT compiled shader bytecode.
// Job02 v1: maps one-to-one to estimator.py; production application is identity.
// Exact helper definitions and proposed native integration are in ESTIMATOR_SPEC.md.
// Hypothetical local diagnostic wrapper target: cs_6_2, CSMain, -O3 -HV 2021.
// Do not replace an existing CSO or generated header with this pseudocode.

struct Pair
{
    uint physicalCell;              // unique coordinate, not clamped tap ordinal
    bool supported;                // static > .5, recall valid > .5, recall static > .5
    float current, recalled;       // physical D+S luma, never multiply by 256
    float currentLo, currentHi;     // union FP16 RTNE/RTZ preimage
    float recalledLo, recalledHi;
};

struct Diagnostic
{
    float appliedGain;             // ALWAYS 1 in v1
    float provisionalGain;         // comparison experiment, never feed RR
    float logLocation, logLower, logUpper, mad;
    float effectiveEnergySupport;  // (sum current)^2 / sum(current^2), not iid n_eff
    float maximumEnergyShare;
    uint uniquePositivePairs;
    uint reasons;                  // estimator.py Reason enum
    bool eligible;                // numeric eligibility only, not cause confidence
    bool abstain;                  // ALWAYS true in v1
};

Diagnostic EstimateAnchorDiagnostic(
    Pair taps[9], Pair centre,
    float frameRatioLo, float frameRatioHi, bool frameRatioBounded,
    float frameCoverage, float k, float strength, bool active, bool reset)
{
    Diagnostic result = zero;
    result.appliedGain = 1.0;
    result.provisionalGain = 1.0;
    result.abstain = true;
    result.reasons = MISSING_INDEPENDENT_CAUSE;

    // CPU Config constants were frozen before holdout access.
    const uint minimumUniquePairs = 5;
    const float dispersionMultiplier = 1.0;
    const float model = 0.18 * exp(-max(k, 0.0) / 10.0);
    const float reject = max(1.8 * model, 0.30);
    const float minimumGain = max(0.80, 1.0 - min(model + 0.05, 0.30));

    // Enumerate dy,dx in {-3,0,+3}, clamp each coordinate to grid extent.
    // Reject repeated physicalCell values; duplicates do not add evidence.
    // A pair is positive iff it is supported, all fields are finite, both
    // current/recalled are >=0 and both conservative lower endpoints are >0.
    // Preserve support flags separately even for numerically unusable darkness.
    unique = UniquePositivePairsInOriginalTapOrder(taps);
    n = unique.count;
    result.uniquePositivePairs = n;
    for (uint i = 0; i < n; ++i)
    {
        L[i] = log(unique[i].current / unique[i].recalled);
        Lo[i] = log(unique[i].currentLo / unique[i].recalledHi);
        Hi[i] = log(unique[i].currentHi / unique[i].recalledLo);
    }
    // LowerMedian sorts values and returns index floor((n-1)/2); n0 returns0.
    // This is an order statistic, not an interpolated even-sample median.
    result.logLocation = LowerMedian(L);
    for (uint i = 0; i < n; ++i) deviation[i] = abs(L[i] - result.logLocation);
    result.mad = LowerMedian(deviation);
    result.logLower = LowerMedian(Lo) - dispersionMultiplier * result.mad;
    result.logUpper = LowerMedian(Hi) + dispersionMultiplier * result.mad;
    result.effectiveEnergySupport = Square(SumCurrent(unique)) / SumCurrentSquared(unique);
    result.maximumEnergyShare = MaxCurrent(unique) / SumCurrent(unique);
    // Define both energy diagnostics as0 when their denominator is0.

    result.eligible = IsPositiveSupported(centre) && n >= minimumUniquePairs;
    if (!IsSupported(centre)) result.reasons |= CENTER_UNSUPPORTED;
    if (IsSupported(centre) && !IsPositiveSupported(centre))
        result.reasons |= DARK_OR_UNBOUNDED;
    // IsInvalidInput means a nonfinite Stats/Recalled component or negative
    // current/recalled level. An ordinary absent valid/static flag is not itself
    // INVALID_INPUT; it is CENTER_UNSUPPORTED.
    if (IsInvalidInput(centre)) result.reasons |= INVALID_INPUT;
    if (n < minimumUniquePairs) result.reasons |= SPARSE_SUPPORT;
    // A pair touching physical cap16 exposes a censored global ratio; the
    // diagnostic refuses to infer an uncapped correction from it.
    if (AnyEndpointAtLeast16(unique))
    { result.eligible = false; result.reasons |= CAP_DOMAIN; }
    if (!active) { result.eligible = false; result.reasons |= OFF; }
    if (reset) { result.eligible = false; result.reasons |= RESET; }

    if (!frameRatioBounded || !isfinite(frameRatioLo) || !isfinite(frameRatioHi) ||
        frameRatioLo < 0 || frameRatioHi < frameRatioLo ||
        !isfinite(frameCoverage) || frameCoverage < 0 || frameCoverage > 1)
    { result.eligible = false; result.reasons |= DARK_OR_UNBOUNDED; }
    else if (frameCoverage >= 0.15)
    {
        bool atLo = (1.0 - frameRatioLo) > reject;
        bool atHi = (1.0 - frameRatioHi) > reject;
        if (atLo != atHi)
        { result.eligible = false; result.reasons |= FRAME_GUARD_AMBIGUOUS; }
        else if (atLo)
        { result.eligible = false; result.reasons |= FRAME_CHANGE_REJECTED; }
    }
    bool localLo = (1.0 - exp(-result.logLower)) > reject;
    bool localHi = (1.0 - exp(-result.logUpper)) > reject;
    if (localLo != localHi)
    { result.eligible = false; result.reasons |= LOCAL_GUARD_AMBIGUOUS; }
    else if (localLo)
    { result.eligible = false; result.reasons |= LOCAL_CHANGE_REJECTED; }
    if (result.logLower <= 0.0)
    { result.eligible = false; result.reasons |= NO_POSITIVE_LOWER_BOUND; }

    if (result.eligible)
    {
        float provisional = clamp(exp(-result.logLower), minimumGain, 1.0);
        result.provisionalGain = StoreAsHalfRTNE(1.0 + saturate(strength) * (provisional - 1.0));
    }
    return result;                 // appliedGain still1 regardless of diagnostic
}

// Native shared Apply reference, unchanged semantics:
// gain = saturate(BilinearClamp(InGain, pixelCentre / renderExtent).x);
// outDiffuse.rgb = SanitizeRadiance(inDiffuse.rgb * gain);
// outSpecular.rgb = SanitizeRadiance(inSpecular.rgb * gain);
// outDiffuse.a = inDiffuse.a; outSpecular.a = inSpecular.a;
// v1 supplies only identity to this path; provisionalGain is a debug field.
