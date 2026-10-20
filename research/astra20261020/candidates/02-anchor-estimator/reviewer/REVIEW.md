# Independent skeptical review

## Final verdict

**Keep as research.** The deployed estimator is an explicit abstainer: gain1
everywhere. It is a useful diagnostic and falsifier implementation, but has
zero correction dose and therefore no demonstrated denoising benefit. Its
provisional paired-log field is a comparison instrument; connecting it to RR
would again remove genuine coherent light changes. No GPU, fresh RR or game
result was executed by this reviewer.

**Reject the provisional field as an active correction.** An independent
positive-dose comparison reproduces worse antithetic null bias and worse
moderate real-light response than the frozen native control. Lower total
correction on the held-out capture cannot reverse those counterexamples.

This review was preregistered before the reviewer saw candidate code or an
improvement claim. `PREREGISTRATION.md` fixes the rejection controls and evidence
boundary. `independent_controls.py` imports only the unmodified baseline and
opens no captured fixture. Candidate constants were not tuned by this reviewer.

## Independent reproduction of known bad behavior

The baseline-only command exited 0 because its assertions **detected** the
known failures; that exit code is not quality acceptance for the baseline.

- The analytic equal-energy two-cell exchange loses exactly 20% of total energy
  under `min(reference/current,1)`. In general the lost energy is half the L1
  distance between the paired current/reference levels.
- A broader antithetic stripe pair passed through the frozen native formula
  loses 0.703125% energy for each sign, with frame ratio exactly 1.
- At armed `k=0`, genuine multiplicative steps 1.1, 1.25, 1.4 retain approximately
  .0009766,−.0009766,.2993164 of their requested change. The small negative
  1.25 response is half-storage rounding. Reciprocal downward changes retain 1.
- A frame ratio greater than 1 still allows local darkening; this is separately
  recorded by the executable controls.
- Coarse dynamic-centre identity does not imply full-resolution protection:
  the ideal bilinear example darkens half the 8 associated dynamic pixels,
  with minimum gain .9125. This is a CPU sampling example, not D3D parity.
- Replacing a safe identity fallback with the frozen one-sided estimator is an
  explicit mutant. The real-light safety assertion fails and the caught failure
  is recorded. The mutant is not presented as a passing quality measurement.

Full trajectories, seed-specific noise controls and support-only interventions
are in `preregistered_control_results.json`.

## Candidate findings and corrections

| Finding | Reproduction | Resolution and scope |
|---|---|---|
| REVIEW-001 | Uniform1.25/1 input; caller bounds[.6,.9] and NaN/negative coverage bypassed a strict global guard straddle. | Finite[0,1] coverage validation now rejects/abstains. External metadata cannot overwrite invalid-input status. This affected provisional diagnostics; deployed gain remained1. |
| REVIEW-002 | Nonfinite gain floor/cap generated NaN provisional gain; nonfinite dispersion generated invalid envelope fields; negative/zero tau was not rejected. | Configuration finite/range checks now raise `ValueError` before calculation. Frozen constants were unchanged. |
| REVIEW-003 | Source-shaped HLSL used a different dark/unsupported reason-bit condition and omitted the invalid-input bit. | Pseudocode classifications were aligned with the CPU. This is a source review, not compiler or GPU verification. |

The first two findings were reproduced against the live pre-fix source, reported
to the implementation owner, and independently regressed after the fixes. The
initial pre-fix source hash was not retained; the audited post-fix hash, exact
command, exit code and elapsed time are in `audit_receipt.json`. No failed run
was renamed a successful measurement.

## Executed independent candidate checks

```sh
python -m unittest discover -s research/astra20261020/candidates/02-anchor-estimator/reviewer -p test_independent_audit.py -v
```

The 12 independent tests passed. They cover new deterministic seeds 271828/314159,
nonmutation, observational twins, OFF/reset/empty history, a centre lacking its
own recall, duplicate edge taps, strict frame-interval ambiguity, the two API
regressions, dark and cap16 domains, maximum half, negative/nonfinite supported
input, alpha bit payloads including NaNs/signed zero, and bilinear dynamic leakage.
These tests exercise the CPU contract and do not certify native host scheduling.

## Independent held-out and matched-dose reproduction

After the coordinator explicitly released the holdout, the reviewer ran:

```sh
python research/astra20261020/candidates/02-anchor-estimator/reviewer/reproduce_holdout.py
```

The command verified all 11 frozen source hashes before opening any held-out
array and exited 0. It recomputes scalar energy and response metrics independently
of `metrics.py`; only the preregistered synthetic data generator is shared.
There was no further tuning. Full values, hashes, masks and trajectories are in
`holdout_reproduction.json`.

| Held-out scope | Frozen control correction dose | Provisional diagnostic dose | Deployed dose |
|---|---:|---:|---:|
| Native `2405579e`, frame 92, 641 original mask cells | 5.372434% | 0.106683% | 0% |
| Combined `2405579e`, 53 frames, 60,777 original mask samples | 3.002119% | 0.131649% | 0% |

The native holdout is one snapshot and supports no temporal conclusion. The
combined holdout has 46 adjacent original frame pairs; gaps were not filled or
looped. Both frozen CPU controls match the stored GPU gain to maximum absolute
error .00048828125, one half step in the relevant gain range. This comparison
is a historical calibration witness, not fresh GPU execution.

For the separately labeled synthetic decaying excess, independent matching gave
5.051897233% removed energy with the provisional strength 1 and frozen-control
strength .9753299952. The absolute dose residual is 8.19e-9. At those strengths:

| Independent falsifier | Frozen control | Provisional diagnostic | Interpretation |
|---|---:|---:|---|
| Equal-energy antithetic null false-positive dose | 3.184677% | 4.814200% | Diagnostic darkens more at matched labeled-excess removal. |
| True 1.1 step, 22-frame response area fraction | .036319 | .028422 | Diagnostic removes more of the genuine change. |
| True 1.25 step, same response metric | .309766 | .297213 | Diagnostic removes more of the genuine change. |
| True 1.4 step, same response metric | .516836 | .507092 | Diagnostic removes more of the genuine change. |

Response fractions describe the area of the genuine **change**, not a
whole-image brightness ratio. Deployed identity retains approximately 1, with
small differences due to input half rounding, and applies no correction. Its
positive-dose comparison is explicitly `null`.

## Metrology review

The experiment code uses unmodified masks and reports correction energy before
deriving dose. At the same realized one-sided null dose, global energy drift is
algebraically the negative dose; a claimed reduction of that same bias would be
a metric error. The useful conditional comparison is equal removal of the
separately labeled synthetic excess, followed by independent null/light tests.
Zero-dose deployed identity has no supported positive-dose comparison.

The local median/MAD envelope is correctly described as deterministic dispersion
plus half-rounding uncertainty, not a calibrated confidence interval. Distinct
coordinates do not imply independence. Coherent local changes can have zero MAD
and still be pure real illumination. A median statistic estimates typical log
change, not the energy-weighted level dominated by sparse bright cells.

The supplied native fixtures are seven isolated calibration snapshots. The
combined fixtures offer more chronological values but remain a separate signal
domain. Neither establishes native full-sequence RR quality. Stored-cell input
grain/flicker proxies and gain deltas cannot be called rendered RR flicker.

## Remaining acceptance boundaries

- Native Stats/Gain/Apply compilation, configuration-to-provider canary, actual
  atomics, lifetime/debug checks, fresh AMD RR and in-game observation remain
  local gates. No estimated GPU timings or image-quality wins are supplied.
- A future nonidentity candidate needs an independent physical-light witness
  and controlled moderate light interventions, not a caller-provided “excess”
  boolean inferred from the same arrays.
- A same-pose converged/controlled witness must separate the genuine light step
  from sampling-history excess; extra frames of the same ambiguous pair alone
  do not establish cause. Preserve chronology, support, exposure and physical
  units when collecting that witness.
