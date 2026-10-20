# Independent falsifier preregistration — job 02

This document and `independent_controls.py` were written by the skeptical review
agent before inspecting any candidate implementation or claimed result. The
reviewer may inspect the frozen production/reference implementation. This is an
executable rejection test of known bad controls, not a quality acceptance claim.

## Frozen evidence boundary

- Base: `astra-handoff-20261020`, commit
  `5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`.
- Development: capture `22f9ca14`; validation may use `87ee1fba`.
- Holdout: both `native_policy/2405579e.npz` and
  `combined/2405579e.npz`; no numerical inspection by this reviewer before the
  coordinator explicitly releases it. The untouched package calibration runner
  may validate all fixtures without tuning a candidate to its results.
- Synthetic seeds: `20261020`, `20261021`, `20261022` for rejection controls;
  an independent candidate audit will also use `271828` and `314159`.
- No raw key ring, pre-store native sums, ground truth, or new GPU execution is
  inferred from the packaged data. Ideal bilinear is a CPU interpolation model,
  not a D3D sampler parity claim.

## Controls fixed before tuning

1. **Exact identity / OFF / invalid/reset.** Matching finite valid levels and
   zero strength must not change RGB or alpha. Empty history, reset, invalid
   camera history, or an unavailable required observation must cause explicit
   abstention. Nonfinite inputs must not produce NaN/Infinity or a false claim
   of usable evidence. Fresh camera-cut history cannot inherit the previous
   correction confidence. Root harness owns host chronology; estimator tests
   must not pretend to reconstruct unobserved history.
2. **One-sided darkening.** An analytic two-cell exchange pair is a mandatory
   falsifier: with equal energy and `g=min(r/c,1)`, the output is
   `sum(min(r,c)) = sum(c) - 0.5*sum(abs(c-r))`. This is a strictly negative
   bias whenever levels differ. Larger spatially correlated fields must
   reproduce bias through the actual frozen native formula despite the frame
   ratio being exactly one. Stationary independent, spatially correlated,
   temporally correlated and sparse heavy-tail perturbations are separate
   controls. Frozen all-valid masks prevent moving denominators.
3. **Real-light null and observational twins.** Test upward factors
   `1.1, 1.25, 1.4` and their reciprocals; also `.5, 2` as large-change controls.
   At the exact same observable arrays, label A is genuine illumination and
   label B is an excess input. A deterministic estimator without an independent
   observable must produce bit-identical results for both; claims of causal
   discrimination fail. Under a declared conservative no-light-loss contract,
   any meaningful darkening of A fails even when the aggregate excess score
   improves. An abstainer is valid research but is not a nonzero-dose quality
   win. Full 22-frame response area, first-frame loss and time to 95% of the
   requested step are reported; no hidden latency denominator changes.
4. **Motion/light interaction.** Apply those light steps during an armed
   post-motion window and at the same pose. The latter is tested both under
   the real host's OFF scheduling and an explicitly armed estimator probe.
   A moving foreground region sits against a changing static background.
   Changing support with radiance held fixed separates support effects from
   radiance statistics. New-view cells, empty/sparse support and unbalanced
   valid masks are independent cases. Masks remain fixed from the control.
5. **Bilinear leakage.** Identity at a dynamic cell centre is insufficient:
   interpolate a lower-gain neighbor into full-resolution pixels assigned to
   that dynamic cell. Report affected fraction, minimum gain and energy dose.
   Do not claim pixel-level protection based only on coarse-grid identity.
6. **Matched correction dose.** Quantities are energy-weighted against the
   same unmodified input and mask. Compare candidate and scaled native control
   at overlapping positive dose, reporting dose residual and FP16 granularity.
   Report all early/late energy, local and global drift, correction support,
   variance, false-positive dose and abstention. A lower-strength comparison
   is not illumination discrimination. No overlapping positive dose means
   `null`/unsupported for that comparison, never an automatic win.
7. **Physical scale and intervals.** Include levels around half subnormals,
   16.16 resolution, rounding midpoints, strict guards and physical cap 16.
   A guard may be asserted only if every value in the rounded-field interval
   makes the same decision. Atomic ratios from rounded native fields remain
   bounded estimates. D/S alpha is unchanged and units are never multiplied
   by 256 to evade native quantization.

## Falsification and recommendation rules

- The frozen one-sided native control must be **rejected** for equal-energy
  null darkening and removal of moderate light changes. The executable checks
  intentionally pass when they detect these known failures.
- At least one explicit mutant must make a correctness/acceptance assertion
  fail. An expected caught assertion is recorded as a rejected mutant, not a
  passing measurement of the mutant's quality.
- Analytic equality uses float64 `1e-12` tolerance; frozen FP16 gain probes
  allow `5e-4` absolute gain tolerance. Rejection thresholds (`>1e-3` relative
  false-positive energy loss or `<0.95` true-step response) separate the large
  known failures from storage rounding; these are reviewer diagnostic gates,
  not established visual JNDs or production acceptance targets.
- An honest abstention design may be retained as research if tests pass and
  missing observables are requested precisely. It is not accepted as a useful
  image correction without nonzero-dose benefit and local native GPU/RR/game
  acceptance. A diagnostic-only candidate does not require invented wins.
- Reject a claim that contradicts any control, omits its scope, uses a changed
  evaluation mask, treats unsupported regions as successes, treats a stored
  GPU witness as a new execution, or presents ideal bilinear as GPU parity.

## Audit sequence

First run the baseline-only controls and record their file hashes. Then receive
the candidate and configuration freeze. Audit source and run adversarial inputs
independently without tuning candidate constants. Finally release the holdout,
report every relevant failure, and state whether the candidate is suitable for
default-off local A/B, research only, or rejection.
