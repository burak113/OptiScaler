# Frozen mechanism questions — native colour, job 03

This file was written before running the new representation experiments. It is
the investigator's predeclared design; results belong in `results.json` and
`INTERPRETATION.md`, not in a rewritten acceptance rule. The packaged baseline
has already been run by the root executor and remains unchanged.

## Scope and authority

The target is each native diffuse/specular **linear physical RGB lobe before
game albedo remodulation**. The captured native input is a noisy observation,
not converged truth. Alpha is a signal word, never authority. The independent
implementation owns exact selected-versus-raw eligibility, alpha preservation,
history, shader proposal and the full spatial/temporal suite. This experiment
owns the smaller question: does a change of colour coordinates itself remove
noise, or does it change the estimator's target?

Tuning/experiment seeds are fixed to `17, 41, 73`. No holdout reviewer seed is
used here. All generated inputs are synthetic and explicitly labelled. Captured
crop distribution summaries are observational only and have no quality label.

## Hypotheses and falsifiers before results

1. **Robust per-sample log chroma rejects false colour outliers without changing
   the radiance target.** Counterexample: sparse independent nonzero samples
   whose rare chromatic class carries legitimate radiance expectation. Hold the
   exact arithmetic RGB expectation fixed and increase sample support. Reject
   this universal claim if the population-limit robust target's normalized
   chroma error exceeds `0.015`; report finite-support variance separately.
   A lower error under an explicitly contaminated (biased) observation model
   does not identify that model in the real capture.
2. **Log transformation after the same arithmetic RGB mean stabilizes gain
   noise by itself.** Compare normalized linear ratio gains to log-chroma
   differences with the same regularization, support, gain interval and inverse.
   For positive finite test data, agreement within `5e-6` rejects the claim of
   an independent denoising mechanism. A log temporal average is a different
   estimator and must not be attributed only to coordinate choice.
3. **The ordering of representation and averaging is immaterial.** Compare
   `chroma(mean RGB)` with a coordinate-wise robust median of per-sample
   log-chroma. Zeros are missing chroma observations; they do not generate a
   dark-pixel apply gate. The sparse coloured-tail case falsifies interchange
   if their population targets differ by more than `0.015`.
4. **Target mixing and reconstruction mixing are the same defect.** Use a
   same-luminance two-colour boundary with a left-only correction through every
   phase of a four-pixel cell. Measure separately (a) an exact target followed
   by dirty interpolation and (b) a mixed target followed by oracle region
   assignment with no interpolation. The source of contamination remains
   attributable even when both could appear in the same final image.

## Declared transforms and numerical limits

Let `w = (0.2126, 0.7152, 0.0722)` and `Y = dot(w, RGB)`. For strictly positive
`Y`, the regularized colour is

`C(RGB) = (max(RGB, 0) / Y + eps) / (1 + eps)`, `eps = 2^-12`.

Its luminance is one. The log representation is the three redundant
coordinates `log(C)`, equivalent up to a common scalar to two opponent
coordinates `log(R/G), log(B/G)` of the regularized colour. Inversion first uses
`exp(logC)` and unit-luma normalization, then undoes the epsilon with
`C * (1 + eps) - eps`. Coordinate-wise robust statistics can leave the image of
the original transform; the diagnostic inverse clips negative reconstructed
channels to zero and normalizes again. Exact encoded colours need no such clip.
The constant relative epsilon makes this scale invariant for
finite nonnegative RGB above floating-point underflow. It regularizes exactly
zero channels; it does not manufacture information in an all-zero sample.

The compared gains are `clip(C(target)/C(raw), 0.75, 1.33)` and
`exp(clip(log(C(target))-log(C(raw)), log(0.75), log(1.33)))`.
Each reconstruction preserves the raw lobe luminance in real arithmetic.
Regularization means this reconstruction is not exact original chroma at a
zero channel, and gain clipping prevents arbitrary full correction. Neither
property proves anything about the game's unknown remodulated composite.

Nonfinite or negative RGB is invalid for the experiment, rather than silently
treated as a valid noise sample. All-zero samples contribute zero radiance to
arithmetic sums and are excluded from the per-sample chroma population. No
all-zero batch is scored as a successful colour estimate. Float64 is the
analytic experiment arithmetic; a separate float32 equivalence sweep makes
precision explicit. This is not an HLSL, FP16-store or D3D sampler parity test.

## Fixed experiments

* Independent-sample windows: 64, 256 and 4096 observations, 192 repetitions
  per seed, diffuse and specular scales. Compare a sparse mean-preserving
  coloured radiance tail with an explicitly contaminated colour-outlier model.
* Compare mean target error and temporal adjacent-window fluctuation under
  immutable true luminance denominators. Windows are generated independently;
  these fluctuations are not captured temporal motion or GPU history.
* Analytic population expectations and robust population medians are reported
  separately from finite Monte Carlo estimates.
* Positive RGB equivalence samples span ten orders of exposure. Identity,
  constant colour, negative/nonfinite rejection and zero-mass bookkeeping are
  checked explicitly.
* Isolated target/reconstruction ablations use exact synthetic region labels
  only as an oracle diagnostic. Those labels are not supplied to the candidate
  and are not proposed as available native data.

## Source observations motivating the control

`portable/colour/colour_portable.py` forms cell RGB means before `rawgain()`;
`compare.py` demonstrates 32 shifted-boundary cases. The packaged fixture's
`prev_history` is a C8 CPU-warmed state, not B4 state or full GPU chronology.
`FSRDColourTrackStats.hlsl` similarly loses subcell information in its 4x4 mean.
`FSRDColourTrackApply.hlsl` uses combined Skip authority and writes alpha one;
its direct native reuse is invalid. These are source observations, not a claim
that a new native shader has run.
