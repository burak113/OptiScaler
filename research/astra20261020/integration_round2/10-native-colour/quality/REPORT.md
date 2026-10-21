# Native colour: measured rejection and the cause of the step failure

## Decision

**No colour algorithm is approved by this work.** The default-off native pass
is safety/test infrastructure. The active frozen log estimator and all four
causal ablations remain rejected. Unknown support abstention, anchor job02's
gain-one path and the rejected glass Haar rule are not called improvements.

This directory contains new CPU experiments against the immutable
`astra-audit-20261020` base
`5fe436dd9a21cb9cc69dec371521a055c9af049d`. The original candidate, review scripts,
protocols and audit receipts were imported/read without executing their
output-writing entrypoints. [PROTOCOL.json](PROTOCOL.json) was saved before the
new holdout execution. It fixes seeds, variants, masks, dose targets, tolerances,
hard gates and reporting rules. The execution receipt hashes it before and after
execution and verifies the immutable candidate/audit files did not change.

These runs execute the **frozen `native_colour.py` algorithm**, not the new native
HLSL/pass. The new pass has a stricter donor-admission contract for explicit
authority/support codes. These results therefore characterize the inherited
estimator and its ablations, not direct execution or quality validation of the
new native pass. Its fail-closed admission is not credited with an algorithm win.

The five diagnostic variants are the original log model, its existing linear
representation, narrower raw-RR chroma support (radius 0.07), wider spatial
support (radius 5/sigma 3) and removal of the sample prior. These are interventions
to distinguish causes. They are not a parameter search or proposed new defaults.

## 1. Original failures were reproduced

The unchanged frozen soft2 comparison returned **exit 1** with its original
`rejected_halo_regression` verdict. Then the original response and all 32
low-contrast cases were recomputed by calling the unmodified benchmark/model
functions. Values agree with the retained local audit to an absolute tolerance
of `2e-8`. This is a fresh CPU reproduction, not reuse of the old claim.

| Original gate | Fresh result | Verdict |
|---|---:|---|
| Diffuse true-colour response within four frames | 0.8980511974843439 | Fails unchanged minimum 0.90 |
| Specular true-colour response within four frames | 0.9033311055054329 | Passes this one case |
| Low-contrast log contamination above original half storage envelope | 32/32 cases | Fails |
| Worst original low-contrast log contamination | 0.06265256305939788 | Retained counterexample |

The contamination number is RGB L1 change divided by the original raw lobe
luminance on the unchanged-side band. It is not a percentage of final-game
harm, whole-image error or a display-space colour difference.

See [reproduction.json](evidence/full/reproduction.json) and the captured
[soft2 stdout](evidence/full/soft2_stdout.json).

## 2. The true-step defect is immediate attenuation, not temporal lag

The original estimator is current-frame-only. On the frozen uniform step,
the weighted effective support is about `37.339237`; its sample prior gives

`confidence = (n_eff - 1) / (n_eff - 1 + 4) = 0.9008408`.

The estimator multiplies the desired log-chroma displacement by this confidence
even when the entire supported patch supplies the same clean, changed colour.
Its later input is identical, so waiting four frames cannot undo that attenuation.
Outputs at frames 8 and 11 are exactly the same original half words. The
coordinate transform and half input/output storage further affect the measured
response, accounting for why the lobe results are not exactly the confidence.

| Variant, full output | Diffuse response | Specular response |
|---|---:|---:|
| Original log | 0.89805120 | 0.90333111 |
| Linear representation | 0.90123830 | 0.90333111 |
| Narrow RR support | 0.89805120 | 0.90333111 |
| Wider spatial support | 0.95047931 | 0.95501274 |
| Remove sample prior | 0.99735656 | 0.99638998 |

Removing the prior does repair this isolated amplitude test, but it increases
the achieved correction. Matching the no-prior variant back to the original
achieved response gives **zero differing RGBA words** on the measured interior
for both lobes. Thus the apparent repair at full strength is not evidence of a
better estimator at the same correction dose. The independent boundary and noise
experiments still decide whether that extra correction is safe; here it is not.

The original 0.90 gate is unchanged. The small diffuse/specular difference is
not used to waive the failure. [step_mechanism.json](evidence/full/step_mechanism.json)
contains each measured response, support value and matching strength.

## 3. Full resolution and a different colour representation do not fix mixed support

The new frozen sweep contains **144 numeric cases**: two physical lobe levels,
three small chroma gaps, three boundary angles and eight boundary phases. All
geometry is identical across each boundary. The same numerical lobe observation
can arise from a material or an illumination boundary; those interpretations
are explicitly labelled and are not counted as independent cases. Candidate
code receives neither a truth partition nor a hidden semantic label.

Every case keeps the original raw/selected/authority masks and raw luminance
denominators. The old local FP16 storage envelope is reused without relaxation.
The complete output is also attenuated, only for evaluation, to achieved
opponent correction dose 0.8 when representable within absolute tolerance 0.003.
The half-store step is inside the matching search.

| Variant | Full-output failures / 144 | Worst full contamination | Cases reaching matched dose 0.8 | Matched-case failures | Worst matched contamination |
|---|---:|---:|---:|---:|---:|
| Original log | 144 | 0.06672091 | 96 | 96 | 0.05966102 |
| Linear | 144 | 0.06779661 | 48 | 48 | 0.06021155 |
| Narrow RR support | 48 | 0.01423729 | 96 | 0 | 0 |
| Wider spatial support | 144 | 0.07322034 | 120 | 120 | 0.06183889 |
| No sample prior | 144 | 0.07457627 | 120 | 120 | 0.06033898 |

**The zero in the narrow-support matched subset is not an acceptance result.**
Its 48 smallest-gap failures are unmatched at dose 0.8 and remain part of the
full-output verdict. Dropping them would turn a dose/quantization limitation
into a misleading clean-boundary claim. All missing matches and actual achieved
doses are retained in [boundary_holdout.json](evidence/full/boundary_holdout.json).

More precisely, those 48 cases are **gap 0.02 in both lobes, all three angles and
all eight phases**. The log and narrow-support outputs share the same 96-case
matched intersection at gaps 0.06/0.12: original log leaks in 96/96 and narrow
support in 0/96. In a missing diffuse case the full dose is 0.910136, while the
specified half-stored scalar search gets closest at 0.792970, outside 0.8±0.003.
This is a matching/quantization hole, not evidence of insufficient full correction.
The receipt label `quantized_target_unreachable` means that the specified matching
procedure did not attain the tolerance; it is not a mathematical impossibility
proof over every conceivable output. [paired_audit.json](evidence/analysis/paired_audit.json)
lists the exact missing groups, phases, reasons and paired intersections.

Linear and log representations leak with their shared support even after
matching the achieved interior correction. Wider support increases useful
effective sample count and true-step amplitude, but also mixes a larger area.
Narrow raw-RR support can reject a sufficiently separated clean edge; it cannot
certify that every smaller observed difference is noise or that a coherent RR
error is a true material partition.

## 4. Noisy RR chroma cannot supply the missing semantic evidence by itself

The executable twin-world construction supplies **byte-identical source, raw,
selected, depth, normal, roughness and authority arrays** to every variant.

In one world, the subtle raw discontinuity is genuine and the current stochastic
source observation has an opposing fluctuation. In the other, true lighting is
flat and raw contains a correlated estimation discontinuity. Keeping and removing
the apparent boundary are incompatible desired outputs, but every deterministic
variant produces exactly the same half output in both worlds.

On the diffuse witness, the truths differ by mean normalized RGB L2 distance
`0.05859156`. The triangle inequality requires error at least `0.02929578` in one
world for any common answer. The original log output has errors `0.05368229`
against the genuine-boundary truth and `0.00501739` against flat truth. The
narrow-RR variant produces the same answer on this witness. More aggressive
no-prior correction improves the flat world while increasing the wrong-world
error to `0.05937218`.

This is a concrete missing-observable result under the declared uncertainty,
not a theorem that no independent evidence can ever help. A valid native
donor-support certificate, calibrated independent physical observations or
additional justified temporal evidence could distinguish cases that these
arrays cannot. Geometry labels, native alpha and current RR chroma alone have
not supplied that evidence. Synthetic all-valid admission used by this suite
does not implement a real support producer.

[identifiability_twins.json](evidence/full/identifiability_twins.json) records
input hashes, exact-output checks and both incompatible truth errors.

## 5. Matched-dose noise, detail and uncertainty

The holdout uses eight seeds per lobe/noise stratum, four noise families and two
physical levels: **64 sequences of 12 chronological frames**. The lobe levels
reuse the underlying random factors and are not independent observations.
Families are independent lognormal noise, sparse source with heavy chromatic
variation, spatially and temporally correlated noise, and rare chromatic tails
with known arithmetic expectation. The source and RR generators are separate.

Each sequence has allocation 47×29 and active extent 40×24, opaque half-alpha
payloads/signed zero, protected original-selected words, an authority exclusion,
two-pixel colour lines, true glints, a real luminance step and a moving crop.
The crop is aligned analytically for temporal error measurement; crop translation
is never treated as a native motion vector or replayed history. No invalid
geometry is used to manufacture a quiet success.

Metrics subtract analytic truth before measuring noise. Quiet grain, aligned
temporal error, p99 error, actual correction dose, thin chroma projection, glint
chroma projection and glint luminance are kept separate. Masks are frozen from
baseline arrays/coordinates before running any variant; their hashes are checked
after every evaluation. No candidate output chooses a quiet mask or denominator.

For dose targets 0.5 and 0.8, one scalar attenuates a variant's entire sequence
correction. Truth selects this **evaluation-only null**, never a runtime
parameter or support label. There is no per-pixel fitting or extrapolation above
full output. Unreachable or negative-dose sequences remain unmatched. Paired
noise ratios use only disclosed common matched seeds, with per-seed values and
fixed-seed 2,048-resample bootstrap intervals; those intervals do not guarantee
performance on unobserved games or distributions.

For diffuse independent noise at achieved dose 0.8, the measured ratios below
compare each variant with the original log output at the **same achieved dose**.
Values below one mean less measured error. The brackets are paired bootstrap
95% intervals of the mean ratio.

| Variant | Common seeds / 8 | Spatial grain ratio | Crop-aligned temporal error ratio |
|---|---:|---:|---:|
| Linear | 8 | 1.04579 [1.04442, 1.04726] | 1.03419 [1.02754, 1.04087] |
| Narrow RR support | 7 | 1.63832 [1.61343, 1.66898] | 1.22062 [1.19945, 1.24333] |
| Wider support | 8 | 0.90439 [0.89858, 0.91073] | 0.68617 [0.66662, 0.70403] |
| No sample prior | 8 | 0.99905 [0.99827, 0.99980] | 0.99651 [0.99625, 0.99679] |

Wider support reduces these synthetic noise metrics, while failing every tested
full-output boundary. Narrow RR support trades cleaner sufficiently large
boundaries for substantially noisier correction here. Removing the prior has
nearly the same grain/flicker at the same dose, consistent with the step ablation.
None of these partial observations is a production quality acceptance.

The original log full-dose range is 0.84372–0.93439 for independent noise,
0.68285–0.80040 for sparse noise, 0.28197–1.05936 for correlated noise, and
0.78078–0.88146 for the rare-tail generator. Consequently the primary 0.8 target
matches only 1/8 sparse, 2/8 correlated and 6/8 rare-tail original sequences.
These missing pairs are not dropped from the reported full-dose evidence.
A one-pair bootstrap collapses to its one observation and is **not an informative
confidence interval**. The postprocessing audit lists every stratum with fewer
than three pairs rather than presenting those degenerate intervals as confidence.

The preregistered secondary dose 0.5 admits all eight sparse-noise seeds. At that
equal lower dose, narrow support has grain ratio 2.00863 [1.93251, 2.08718] and
temporal-error ratio 1.24718 [1.21803, 1.27886]; wider support has ratios 0.64133
[0.61503, 0.66456] and 0.62333 [0.59721, 0.64831]. These identify a support-size
trade-off. Lowering the dose does not repair the full-dose step/boundary gates.

The complete full-dose results and matched comparisons are in
[noise_holdout.json](evidence/full/noise_holdout.json). Their pair counts must
accompany any noise comparison. A lower noise value without its achieved dose,
unmatched count and detail response is not a quality win.

## 6. Mechanical controls and the remaining acceptance boundary

Eight metrology tests cover stored-half dose matching, preserved alpha/protected
words, baseline mask immutability, explicit unmatched-dose handling, world-aligned
crop error, nonempty separate detail/glint masks and the identical-observation
counterexample. Deliberate identity, frozen-frame and blur controls are detected:
zero correction does not reach dose 0.8, a frozen output has zero true-step
response, and the blur loses the thin stripe. A candidate-derived mask mutation
raises an actual assertion. The original soft2 subprocess also fails its actual
quality gate as expected. [HARNESS_NOTES.md](HARNESS_NOTES.md) discloses one
pre-holdout unit-fixture correction.

The separate thin sweep has 48 active-correction cases, covering widths 1/2/3
and eight phases in both lobes. The tested thin response remains above the 0.95
minimum, but this does not waive the failed boundaries. Four crops per variant
give zero interior word mismatches after excluding the complete support halo.
The existing raw-RR luminance step is retained to roughly `0.9994–1.0014` of its
original amplitude. A source-only luminance change with stale raw luma is not
reconstructed by this chroma-only design and is not called a passed recovery.
[detail_crop_steps.json](evidence/full/detail_crop_steps.json) retains the cases.

This quality work has **no GPU execution, native allocation/lifetime execution,
separate D16/S256 conversion-path proof, real RR replay, converged capture truth,
VRAM/time measurement or final-game acceptance**. The earlier RX9070 packing
canaries are historical, limited mechanical evidence. They do not validate this
new pass or overturn any quality rejection. The host/pass work owns its separate
ABI, constants, copies, safety checks, fixtures and native acceptance gates.

## Reproduce

From the repository root, using the pinned repository NumPy requirement:

```sh
python -B -m unittest discover -s research/astra20261020/integration_round2/10-native-colour/quality -p 'test_quality.py' -v
python -B research/astra20261020/integration_round2/10-native-colour/quality/run_quality.py --output /tmp/native-colour-quality --quality-gate
```

The first command returns 0 for passing metrology tests. The second returns
**1 for the expected quality rejection** after writing `execution.json` with
`mechanical_experiment_execution_pass=true`, `quality_accepted=false` and the
output/source hashes. A traceback or missing final execution receipt is an
execution failure and must not be mistaken for that expected negative verdict.
Omit `--quality-gate` to return 0 when experiment execution completes regardless
of its separately recorded quality rejection. `--section reproduce` reruns only
the original failure reproduction; `--section holdout` runs the new protocol.

The paired-membership/uncertainty audit is reproducible from saved data without
rerunning a candidate:

```sh
python -B research/astra20261020/integration_round2/10-native-colour/quality/summarize_evidence.py --input /tmp/native-colour-quality --output /tmp/native-colour-quality-analysis
```
