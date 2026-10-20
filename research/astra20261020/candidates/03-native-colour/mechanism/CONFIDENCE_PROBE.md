# Frozen final confidence probe

This protocol is written before running `confidence_probe.py`. No parameter
search, native implementation edit or independent-review holdout is allowed.
Development seeds remain `17, 41, 73`.

## Question and falsifier

Can low-band sampling uncertainty suppress noisy colour gain while retaining
useful correction? The primary prediction to challenge is that uncertainty
confidence buys less grain mainly by suppressing legitimate correction when
the native source is sparse and heavy-tailed.

Freeze one smooth confidence rule. A stratum is worth independent follow-up
only if its null temporal chroma-HF p90 falls by at least 20%, its persistent
modest-bias correction dose remains at least 90% of the original log candidate,
and its true-change response dose also remains at least 90%. Report each noise
stratum separately; a moderate-noise pass cannot rescue a heavy-tail failure.
No strength renormalization or parameter sweep is performed. An attenuation
that loses dose is explicitly reported as such.

## Exact estimator

Preserve `native_colour.py`'s full-resolution accepted support, physical linear
RGB means, geometry/raw-RR colour weights, gain clip and support confidence.
Do not remove zeros, winsorize tails, change masks, or add a temporal history.

For each centre, collect paired six-vectors `z_i = (source_RGB_i, RR_RGB_i)` with
the existing weights `w_i`. Write `m = sum(w_i z_i)/sum(w_i)` and
`n_eff = sum(w_i)^2 / sum(w_i^2)`. The plug-in independent-sample covariance of
the paired weighted mean is

`Cov(m) = [sum(w_i z_i z_i^T)/sum(w_i) - m m^T] / (n_eff - 1)`.

This is the usual effective-sample-size approximation for i.i.d. samples with
unequal deterministic weights. It is not generally exact with heteroskedastic
samples or RR-conditioned weights. When `n_eff <= 1`, decline the correction.
Retain all off-diagonal RGB and paired source/RR covariance terms.

For the exact native opponent transform

`u = log(R + eps*Y) - log(G + eps*Y)`,
`v = log(B + eps*Y) - log(G + eps*Y)`,

the Jacobian row for numerator channel `k` is

`J_k = (e_k + eps*LUMA)/(RGB_k + eps*Y)
       - (e_G + eps*LUMA)/(RGB_G + eps*Y)`.

At the two observed means, let `A = [J_source, -J_RR]`. Estimate opponent-delta
variance as `V = max(trace(A Cov(m) A^T), 0)`. Tiny negative traces due to
floating-point cancellation are counted and clamped, not reinterpreted as
negative noise. The exact formula uses the **unclipped** observed delta `d`.

Use `q = dot(d,d) / (dot(d,d) + V)`, or zero when the denominator is zero. The
proposed amount is `existing_support_confidence * q`; all other transport and
eligibility rules remain the same. This rule deliberately uses noisy observed
signal power, so it is not expected to suppress every null correction. The
factor in front of `V` is fixed to one, not tuned.

## Fixed development scenes

Use 24-frame, 24x32 constant-geometry/luminance images, with a fixed three-pixel
interior exclusion matching the unchanged radius-three kernel. All selected
pixels equal raw RR and explicit authority is true. Use float32 RGBA to isolate
the variance mechanism from an additional FP16 store stage; alpha is retained.
Diffuse and specular are two physical scales of the same seeded realizations,
not independent captures.

For each seed and scale, generate independent pixel/frame samples in two
classes: moderate multiplicative noise with 15% zeros; sparse chromatic
heavy-tail noise with 60% zeros. Both have the exact intended RGB expectation
before finite precision, with explicit mean compensation for rare coloured
events. No observation class is declared an outlier and none is removed.
Moderate channel/common lognormal sigmas are fixed to `0.12/0.35`; sparse
sigmas are `0.30/0.50`. Each lognormal subtracts half its variance in log space.
Among sparse nonzero samples, 3% have the multiplier `(10,0.2,3)`; ordinary
samples use `(1 - 0.03*tail)/0.97`. Every surviving sample is also divided by its
nonzero probability. These choices preserve expected RGB without suppressing
the rare class's energy.

The three signal histories are: (1) null, clean RR has true chroma; (2) persistent
modest RR opponent bias `(0.12,-0.08)`; (3) a true opponent change
`(0.16,-0.12)` at frame12 with a synthetic raw-RR response of 20% per frame.
The third is a labelled synthetic lag model, not measured AMD RR behaviour.

Report fixed-mask truth error, correction dose along the true desired direction,
null residual chroma-HF, maximum/p99 chroma errors, mean confidence and mean
variance. Temporal residuals subtract each frame's analytic truth. Frame order
is chronological and never looped. A paired-source/RR identity control checks
that the covariance cross terms cancel rather than treating the two as
independent noise streams.

## Limits and outcome

The delta method can be badly calibrated with small/zero channel means, a few
large coloured samples, correlated source/RR estimators or guide-conditioned
sample selection. Spatial samples from real native estimators are not proved
independent. Even a synthetic pass does not authorize changing production,
claiming captured temporal improvement or adding native history. Preserve this
probe as separate research and report a failing stratum or lost dose directly.
