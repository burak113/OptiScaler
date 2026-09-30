# FSRD continuous-harmonic pilot and native controls — 2026-09-30

The stain/wave objective remains open. A source-only continuous-frequency
pilot improves several mature source sequences, but its paired native
correction fails the complete detail/noise criteria. Specular-albedo alpha
controls also expose fresh-context variation with identical native inputs.
No production shader, game DLL, setting or accepted runtime fix changes here.

## Frozen source candidate

The candidate fits at most two continuous plane harmonics on a fixed training
pixel mask, accepts them using a fixed validation mask, retains their physical
frequency basis for the epoch, and processes the signed residual through the
previous significant-phase pilot using a nonnegative carrier. Current linear
coefficients are fit again before causal phase/innovation averaging. First8
pilot frames are exact raw source and inactive; coefficient/residual histories
restart on activation and metadata cuts. The native final output therefore
remains its baseline during those inactive frames.

Prototype, constants, scorer and inputs were frozen before scores. Causality,
rank-one Nyquist handling, physical-basis/OLS/profile-gradient algebra,
conditional covariance, epoch cuts and exact invalid-source fallback were
checked. Independent physical algebra errors stay at floating-point precision;
this is implementation verification, not quality or statistical confidence.

All13 authenticated source families and22 adversaries complete. Mature source
temporal STD falls from0.000371846 to0.000112928 on material,0.000253643 to
0.000112485 on wave, and0.001742697 to0.000121095 on moving light. Six mature
families improve their registered relative source gates. All13 complete
sequences fail the source-relative gate; weak material also fails absolute
detail over the full sequence. Dense detail, near-Nyquist/late weak features,
phase acceleration/drift, disocclusion, colored/AR noise and shared persistent
bias remain counterexamples. No threshold or model changes followed these scores.

The validation noise estimate includes validation pixels, and slot2 reuses the
same validation partition adaptively. Linear covariance is conditional on the
selected frequency; selection/frequency uncertainty and residual/carrier
dependence are omitted. The independently audited local oracle calculation in
the preceding assumption package shows that a common fitted-frequency error
can persist across averaging. That atom-only variance can cancel against the
residual in the full reconstructed pilot and is not a final-error lower bound.

## Fresh paired native measurement

Six128×80×64-frame fixtures each use fresh observed, identical observed-null,
and matching new-pilot contexts:18 contexts/1,152 RR dispatches. Production
conversion and composition run unchanged with all actual GPU job payloads
retained. The preregistered candidate is `harmonic_dc_current_safe`; all six
registered plain/history/current-DC and safe variants remain in the reports.
Truth is used only by the scorer, never the pilot or correction operator.

Mature actual mean-pixel residual temporal STD ratios to the native baseline
for the selected candidate are material1.039025, wave1.205342, moving light
0.029226, weak material1.979684, lighting step0.188345 and reset0.722191.
Only three of six improve actual STD. All six pass the tolerant mature relative
gate, which permits an absolute `+1e-4` STD allowance; it cannot establish
actual noise nonincrease. Full absolute per-frame gain/phase passes0/6;
mature absolute detail passes5/6, with weak material failing. The apparent
source improvements therefore do not establish a general native correction.

The saved-array covariance identity separates baseline error, actual pilot
correction, current-DC constraint and RGB fallback, including their covariance.
Wave mature spatial-DC temporal variance rises from1.491319e-9 to14.035767e-9;
weak material rises from0.875397e-9 to14.012566e-9. Restoring the current observed
mean retains its DC fluctuations. The history64 DC control reduces several
static-case STDs but fails lighting step, whose mature STD ratio is1.622598.
This descriptive decomposition includes deterministic appearance error and
does not assign causal noise percentages. Mean-pixel STD differs from the
square root of mean variance; material improves the latter while worsening
the former by3.9%.

All observed/null serialized input bytes and184-byte applied dispatch controls
match. Nonetheless composed null RMS is nonzero on weak material, lighting
step and reset; lighting step is0.001369848. These measurements are retained
without averaging or removing the variation. Source/pilot geometry, guide RGB
and signal ray-distance alpha match. Specular-albedo diagnostic alpha can
differ, so the older `all_nonradiance_counterfactual_inputs_exact` Boolean
must be read as that narrower checked contract, not full guide RGBA equality.

The initial attempt launched no native child because available physical RAM
was445,657,088 bytes below the unchanged1GiB guard. Its128 actual conversion
jobs remain retained. The retry completed all three material contexts and
saved their metrics before the root driver's stdout lookup of a nonexistent
`absolute_detail_pass` key failed. The wave/other-five continuation only fixes
that display key; no estimator, score, parameters or completed context replay
changes. Independent audit validates all18 completed contexts and1,920
conversion/composition jobs, plus the128 conversion-only jobs.

## Specular-albedo diagnostic-alpha control

Eight new fresh contexts independently use original, zero, one and observed-
source specular-albedo alpha for material and wave. Only input3 RGBA8 alpha
changes; RGB, all other native input bytes, format/upload counts and applied
controls match. Three additional fresh contexts repeat the original wave
inputs exactly. This adds11 contexts/704 RR dispatches, with no conversion,
composition or truth-based quality selection.

Material's four raw diffuse/specular RGBA outputs and the earlier original
response match bit-exactly. This supports no alpha effect for this material
input and pinned provider; it is not a universal ignored-alpha SDK contract.

Wave's zero/one raw outputs match each other. Its observed-source alpha already
equals its original alpha, so those two jobs have identical seven input byte
trajectories, yet their output RGB RMS differs by0.000515743 diffuse and
0.000529975 specular. The three additional original repeats match each other.
Across eight retained wave contexts, including the earlier original,28 pairs
include15 identical-input pairs;9 of those have nonexact raw outputs. Maximum
identical-input lobe RGB RMS is0.000529977. Alpha causation cannot be identified
from these wave comparisons. Sparse FP16 differences also remain
in some comparisons; neither scale is erased or treated as a quality fix.

The first alpha driver incorrectly required64 specular-guide uploads. Material
completed, then wave's legitimate single-upload trajectory failed that Python
assertion before its launch. A wave-only continuation preserves the original
single-upload layout. The supplemental cross-comparison initially failed its
local guard-module import before saving any result; its import path was fixed
without changing native evidence. Both root preparation errors are recorded.

## Provenance and remaining work

All native contexts use runner B SHA3427689a4764380f885545c353250277e4d71944d3310c8a17b3cbba0f3c21d2
and denoiser SHA48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3.
Applied flags are NON_GAMMA_ALBEDO2 plus RESET1, not a linear-depth flag.
Debug-layer/SDK ordinary error and warning counts are zero. The unchanged
owned-child guard limits240seconds,2GiB child working set and1GiB host free RAM.
No unrelated process, game install or independent task is modified.

[The compact manifest](evidence/fsrd_continuous_harmonic_followup/manifest.json)
retains scripts, registrations, reports, actual CB/control/job/log bytes and
SHA/size pins for every full GPU/native texture and sequence array preserved
at its original F-drive path. CPU/source evidence and synthetic paired-native
evidence remain separate. There is no new current-alpha game capture or game
quality verification. The branch is exactly `ffxD-experimental-alpha` on F.

This package adds29 completed contexts/1,856 RR dispatches, bringing the
completed totals to370/19,312, including the previously documented64-dispatch
completion whose Python metadata step failed. The low-memory nonlaunch adds
zero. All2,048 actual GPU jobs from the harmonic attempt/retry/continuation
remain retained. The next narrow candidate tests a source-only RGB mean
innovation cut for final DC history on these same matching pilot responses.
It cannot by itself repair startup, weak or dense spatial detail, or identify
shared source bias; those failures remain required checks.
