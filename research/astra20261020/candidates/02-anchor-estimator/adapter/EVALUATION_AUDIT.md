# Secondary evaluation audit

Executor: implementation/testing subagent, read-only inspection of the frozen
`experiments.py` and `metrics.py`, followed by independent arithmetic recomputation
from generated arrays. The independent skeptical review is separate in
`reviewer/`; this secondary check does not replace it.

## Findings

No correctness blocker was found in the implemented measurement definitions.
No frozen source or threshold was changed during this audit.

- The calibration matches removal on a **labeled synthetic excess**, then reuses
  those strengths on no-excess nulls. It does not claim that equal realized null
  removal can produce different global darkening.
- The target denominator is the total input energy over the full32-frame
  sequence, including inactive frames. It is not the injected excess alone,
  early-window energy alone, or a denominator recomputed from candidate support.
- The scalar excess multiplier is spatially uniform; baseline physical radiance
  is the fixed `texture()` field near1, not a perfectly flat unit radiance image.
- Captured evaluation uses original `fixed_mask` values and verifies their
  identity before and after evaluation. Candidate eligibility is reported rather
  than used to select a more favorable denominator.
- Temporal differences require consecutive original frame identifiers. Sparse
  native snapshots do not become a temporal replay, and sequence gaps are neither
  filled nor looped. Grain/flicker here are cell/input error proxies, not RR or
  final rendered image observations.
- Combined and native baselines use their respective original policies. The
  additional conditional estimator evaluation of combined fields is explicitly
  a separate stress exercise, not evidence of native routing or per-lobe quality.
- Genuine-light response uses the requested22 frames `[6,28)`. The analytic
  physical target remains float64 whereas current storage is FP16, so an identity
  response may differ very slightly from1 due to modeled storage quantization.
- The moving-object background response excludes the union of original moving
  object positions across all frames, creating one fixed background mask. The
  separate ideal-bilinear check retains original dynamic support. These moving
  object results are full-strength controls, not the dose-matched comparison.
- `global_energy_drift` is measured relative to current input energy. Analytic
  truth errors are separate fields; an input-relative reduction should not be
  described as truth-relative scene brightness error without that distinction.

## Independent arithmetic checks

I regenerated the known-excess sequence and the1.25x light-during-motion sequence,
evaluated the frozen strengths, and calculated sums directly without calling the
metric helper for the verification arithmetic. Assertions passed at `1e-14`
absolute tolerance.

| Quantity | Baseline | Provisional diagnostic |
|---|---:|---:|
| Frozen matched strength | 0.9753298759460449 | 1.0 |
| Full-sequence input-energy dose | 0.05051892579851056 | 0.05051897233257407 |
|1.25x during-motion22-frame response area | 0.3097656105240385 | 0.29721317762330457 |
| Antithetic no-excess removal at matched strengths | 0.03184677055105567 | 0.048141995018037655 |

Target dose is `0.05051897233257407`; residual matching error is approximately
`4.6534e-8`. The negative result is clear: the provisional diagnostic removes
more energy from the equal-energy null and preserves less of this real-light
step. These results must remain in the report. The deployed abstainer has zero
dose and cannot claim a nonzero-dose effectiveness win.

## Reproducibility note

The frozen `experiments.py --include-holdout` entry point checks that the freeze
receipt exists. The final task runner should additionally verify every recorded
source hash before releasing the holdout. This strengthening can live in the
outer runner without altering frozen estimator/evaluation files.

The synthetic sequences hold supplied recalled observations according to their
explicit construction; no unseen ring history, live key refresh, provider state,
D3D sampling or game behavior is reconstructed. GPU timing, actual shader parity,
AMD RR output and in-game visual acceptance remain unexecuted.
