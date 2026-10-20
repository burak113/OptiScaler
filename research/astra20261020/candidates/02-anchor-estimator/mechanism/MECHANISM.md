# Mechanism investigation: what the anchor observations can establish

This is the mechanism subagent's **fresh CPU experiment**, not GPU execution or
an AMD RR/game result. The untouched tag is
`5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`; all experiments here use the frozen
`portable/anchor/anchor_reference.py` as the old estimator. Reproduce from the
repository root with:

```sh
python research/astra20261020/candidates/02-anchor-estimator/mechanism/investigate.py
```

The command writes `results.json`, with complete trajectories, immutable input
hashes, array inventories, analytic checks, seeds and scope labels. NumPy and
the standard library are sufficient. A first development invocation found a
syntax error in this new script; it was fixed before any numerical result was
produced. Subsequent invocations pass all included assertions. This is disclosed
as an implementation failure, not relabeled as a successful measurement.

## Evidence selection and the frozen holdout

Only the **22f9ca14** combined/native NPZ arrays were inspected for representation
choice. The native development fields are frames 41, 44 and 52, motion ages
0, 2 and 10. They are three observations with gaps, not a continuous ten-frame
replay. The combined development data contain 35 exported observations in true
ordinal order; temporal correlations below use only ordinal-adjacent pairs,
never interpolate gaps, and never reproject or loop histories.

`2405579e.npz` numerical arrays have not been opened by this investigator. The
published common manifest was read and contains historical summaries for all
captures; thus **new array analysis**, not prior public metadata, is held out.
The report does not present a retuned model evaluated on a secret benchmark.

Fixed masks are copied from the archives and verified against the original
static/valid fields. Candidate output never changes these denominators. All
NPZ reads use `allow_pickle=False`. The 22f9 anchor ROI is 512x512 at original
render origin (496,167), represented as 64x64 cells in a 1505x847 render. Its
ROI-host history omits out-of-ROI data and the original first prior camera.
The raw six-slice keys, original native pre-store atomics and rendered RR output
are unavailable in these grids.

## Independent hypotheses, predictions, and abandonment criteria

| Hypothesis | Independent prediction | Discriminating experiment | What would make us abandon the proposed explanation |
|---|---|---|---|
| Sparse tails and dependence destabilize estimated level | At fixed expected energy, four-tap sampling misses rare energy, correlated neighborhoods retain more local residual than independent ones, and energy/log-location summaries can disagree | Exhaust all 64 spike positions in one 8x8 cell; equal-energy independent vs block-correlated synthetic controls; development paired energy and log summaries | A proposed robust representation fails at matched known-excess removal, or independent truth shows the removed tail is genuine illumination/structure. Captured tail concentration alone never proves Monte Carlo causation. |
| Non-brightening rectification darkens an unbiased null | Any nonzero correction dose implies exactly equal negative energy drift; exchangeable paired noise gives a closed-form downward bias | Two-cell antithetic construction and large equal-energy blocks evaluated with the native baseline | The assumptions do not apply: inputs can be negative, gain can brighten, or denominator/support changes. Within the stated nonnegative fixed-support domain the identity is algebraic, not a tunable hypothesis. |
| Modest lighting and biased input are unidentifiable | Two causes with byte-identical statistics, recall and schedule produce identical decisions although the desired outputs differ | Construct true 1.1/1.25/1.4 illumination and input-excess twins, with downward controls as well | An added observation independently distinguishes illumination from noise/bias. A threshold on the existing ratio cannot falsify the impossibility construction. |
| Support and neighborhood mixing drive part of the effect | Changing only recall/static validity changes correction; invalid centres inherit neighboring correction despite unchanged levels | Fixed radiance 1.25/1.0, full/sparse/missing-centre/moving support; ideal full-resolution boundary interpolation | A corrected estimator's gain is invariant where support ought to matter, or same-support radiance interventions explain all changes. Current results establish a support effect but cannot assign all captured excess to support. |

These mechanisms coexist. None requires claiming that a captured residual is
pure ReSTIR/Monte Carlo noise.

## 1. Sampling and the choice of representation

Native `BoxCell` evaluates four bilinear taps at offsets (2,2), (6,2), (2,6),
(6,6) within each 8x8 cell. At these exact half-texel fractions it averages 16
selected texels, indices {1,2,5,6} on each axis, not all 64. It sums physical
diffuse and specular RGB luminance into **one scalar**. D/S alpha is excluded
from the estimate and passed through by Apply. A per-lobe estimator cannot be
inferred from this combined scalar without defining and exporting new domains.

An 8x8 static cell with one 64-unit spike always has true full-cell mean 1.
Across all possible spike positions the existing statistic is 0 in 48 positions
and 4 in 16 positions: expected mean 1, variance **3**, miss rate **75%**.
This is an analytic/synthetic sampling example, not a claim about any particular
captured spike. Spatial structure can keep the sample pattern persistently
misaligned. A downstream median cannot recover energy never observed.

The development native fields show a useful representation conflict:

| Frame | Immutable support /4096 | Current top 1% energy | Current concentration ESS | Ref/current stored energy ratio | Median log(current/ref) | Baseline changed cells outside immutable support |
|---|---:|---:|---:|---:|---:|---:|
| 41 | 2591 | 7.4245% | 1077.27 | 0.843094 | -0.201907 | 138 |
| 44 | 3199 | 4.2691% | 2062.66 | 0.893486 | +0.045607 | 191 |
| 52 | 3859 | 3.5456% | 2669.32 | 1.025612 | -0.063652 | 66 |

Here concentration ESS means `(sum level)^2 / sum(level^2)`. It is a measure of
how energy is distributed, **not an independent sample count** or a statistical
confidence interval. No valid paired levels are exactly zero in these three
native masks. Some are below one 16.16 count; zero handling still needs explicit
adversarial tests. None reaches physical cap 16, so these fixtures alone cannot
test cap behavior.

Frame 41 has current sum 95.5433 and recalled sum 80.5520 on the same mask, yet
the typical paired log ratio is negative. Its log-ratio MAD is 0.796055 and
paired current/recalled level correlation is 0.29621. Thus a robust paired log
median and an energy ratio answer **different questions and even different
directions**. Replacing the ratio by a median may protect typical level while
abandoning concentrated excess. A claim of better illumination discrimination
would not follow.

The nine gain-neighborhood taps overlap between cells; clamp-border duplicates
are not new samples. Current/recalled textures are already temporally processed
observations and are not independent ray samples. Treat quantization intervals
and deterministic support checks separately from any hypothesized noise model.

### Correlation controls

Synthetic 32-frame sequences, three predeclared seeds (1103,2909,5419), preserve
global energy separately at each frame and hold support fixed. The baseline
uses age zero throughout to isolate estimator behavior from the schedule.

| Control | Mean false-positive energy dose | Mean lag-1 correlation of frame dose |
|---|---:|---:|
| Independent spatial noise | 3.5031% | -0.0903 |
| 8x8 spatial blocks | 5.9586% | +0.1014 |
| Stationary AR(0.9) temporal noise | 3.5172% | +0.7723 |
| Sparse positive bursts | 0.7872% | +0.0546 |

The temporal model starts in its stationary Gaussian distribution; lower warmup
variance is not allowed to masquerade as a benefit. Temporal correlation keeps
similar marginal false-positive dose here while making its trajectory persistent.
The sparse-burst amplitude/distribution differs from the Gaussian controls;
its smaller number is **not** a superiority comparison at equal variance or
equal excess dose. Full synthetic trajectories and construction live in JSON
and source. None measures downstream RR flicker.

## 2. One-sided bias and what matched dose can mean

Let nonnegative current/reference levels be `X,Y`, with ideal uncapped gain
`min(Y/X,1)`. Output is `min(X,Y)`, so

```text
E[output] = (E[X] + E[Y] - E[abs(X-Y)])/2.
```

For exchangeable equal-mean observations this is
`E[X] - E[abs(X-Y)]/2`, strictly dark unless the observations agree. For the
antithetic pair `X=(1-a,1+a)`, `Y=(1+a,1-a)`, both global means are exactly 1
while output mean is `1-a`.

More generally, for *any* realized non-brightening gains on nonnegative input,
fixed support and unchanged denominator:

```text
drift = sum(X*g)/sum(X) - 1
      = -sum[X*(1-g)]/sum(X)
      = -correction_dose.
```

Caps, blend weights and robust estimators change where and how much dose occurs;
they do not escape this identity. In the native baseline's large-block
antithetic null, global current/reference energy is equal, and measured energy
drift is **-8.781738%**, exactly the realized dose **8.781738%**.

Consequently, "less global null darkening at equal realized null correction
energy" is algebraically impossible. The useful comparison **matches removal
on a labeled known-excess intervention**, then compares false-positive dose on
independent null/light controls. Alternatively, compare spatial allocation/local
error at fixed total dose. A weaker strength winning a null is not evidence of
better discrimination. Global frame ratio above one does not protect a local
bright tail, and a frame ratio equal to one does not cancel one-sided local loss.

## 3. Identifiability and an honest candidate boundary

The script constructs two worlds for each step: genuine current lighting
`a*reference` versus biased current input `a*reference` with unchanged true
lighting. Their visible statistics, recalled fields, valid/static support,
motion age and frame ratio are identical bytes. The correct outputs are
different. This includes 1.1, 1.25 and 1.4 steps and their reciprocal directions;
large 2/.5 controls alone would miss the baseline's moderate-step failures.

No estimator of only these observations can guarantee both exact true-light
preservation and correction of the indistinguishable excess. A probabilistic
mixture merely adds a prior; it must disclose and validate that prior. Waiting
for a decay shape does not solve this: real illumination can follow the same
shape, and the short native fixtures lack the intervening history.

The strongest defensible design is therefore an **abstaining diagnostic**:
maintain robust paired log-location, raw energy/tail/support diagnostics and
conservative quantization ranges; return identity without an independent cause
witness. A provisional forced interpretation can be measured for trade-offs,
but must never be labeled a causal solution or shipped through the default
native route. A witness must supply independent illumination-change information
and its uncertainty; it cannot be computed from the same input/ref ratio and
renamed confidence. If geometry/light changes are spatially varying, a single
global witness does not certify each cell.

The smallest observation capable of changing the conclusion is a matched,
controlled native D/S same-pose sequence with independently known moderate light
interventions, and a same-pose high-sample/independent-seed physical reference
for representative early and late frames. The observed moving-object/static
background control must remain in the sequence. Raw six-slot keys would help
transport diagnosis, but would not by themselves identify genuine lighting.

## 4. Support and full-resolution Apply

At fixed current/reference radiance 1.25/1.0, deleting only the centre's recall
leaves its native baseline gain **0.7998047**: neighboring recall is sufficient.
With only one supported tap, eight unsupported cells change and the examined
unsupported centre receives gain **0.92578125**. Setting the centre dynamic
returns grid gain 1, and removing all recall returns identity. Thus support
changes demonstrably affect the result independently of radiance distribution.

Even grid identity is not full-resolution protection. In an ideal bilinear
Apply with static gain .8 next to dynamic gain 1, four dynamic-side pixels per
row change; maximum loss is **8.75%**. This uses exact fractions and is a scalar
CPU interpolation witness. It does not pretend to execute the D3D sampler or
solve geometry transport (job 04). A candidate estimator must report this
boundary limitation separately from its own grid support policy.

## 5. Physical units, bounded ratios, and strict guards

The native atomics use truncated nonnegative cap16 increments at 65536 units,
emulated uint64 low/high sums in the 32-byte ABI. Below one count `2^-16`, current
denominator can be zero even for nonzero FP16 lighting. At high energy the cap
can make different levels identical. These are finite measurement limits,
not reasons to multiply physical inputs by 256. For current .1 and reference .08,
native ratio is approximately .8; forbidden physical scaling by 256 clips both
to 16 and fabricates ratio 1. The script includes dark half/16.16 thresholds and
finite-cap controls in the same physical units.

Actual native pre-store sums are absent. The stored estimates for the three
development frames have intervals and the baseline guard is constant across
each interval. That fact does not make the midpoint exact. A constructed
current 1/reference .7 case produces midpoint **.7001953125** and interval
**[.6996095656,.7006105006]**. At age 10 the strict reject predicate
`1-ratio > .3000000119` differs across endpoints. An implementation must preserve
the uncertainty and abstain or request exact sums; testing just the midpoint
would silently choose a branch not warranted by the export.

## Recommendation from this workstream

Keep the candidate as research unless independent light/transport observables
support a narrower correction policy. The established useful outputs are the
paired-observation diagnosis, exact bias/identifiability proofs, immutable-mask
support and interpolation witnesses, physical-unit threshold controls, and a
reproducible negative result. No GPU timing, shader compilation, runtime wiring,
AMD RR quality or final-game result has been executed by this investigator.
