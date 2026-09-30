# FSRD response calibration follow-up — 2026-09-30

The image-quality goal remains open. The earlier native response studies and
their failures are retained at commit `d8120900`. This continuation tests new
ideas against those failures; it does not replace acceptance with build success.

## Fixed exploratory models

Two new offline packages read the existing 36 native scene sequences without
modifying their reports, controls or arrays. They use only observable pilot,
pilot response, baseline and controls for estimation; clean references enter
scores/contours only. They are posthoc evaluations, not fresh AMD calls or an
independent acceptance set.

The normalized-transfer package uses a 16-observation causal history of
`(P - T(P))/P` or `P/T(P)`, remultiplied by the current pilot/baseline. Division
requires every RGB channel of the current pixel to exceed `1e-4`; invalid
history samples are excluded per pixel. Reset/jitter/inactive controls cut
epochs, and invalid corrections return exact whole-RGB baseline without
clipping. Scale-equivariant flat-light tests pass. Native moving-light transfer
is not stationary: averaged gain retains phase error about 1.65 radians.
Current ratio preserves moving light but does not improve general acceptance.

The conditional complex-spectrum package regresses the response delta on
current/past pilot spectra. A fixed ridge of four nominal source coefficient
variances stabilizes low-variation frequencies. A second variant admits a
linear age term at a fixed nominal four-standard-error threshold. It predicts
an explicit coefficient ramp and tracks rotating illumination better than an
unconditional mean. The additive-enabled prior holdout still fails stationary
material/wave noise, reset noise, and some early/lighting transitions. Residuals
are correlated, so the nominal thresholds are not confidence claims.

## Next native hypothesis, registered before execution

The next pilot will retain the old causal spectral correspondence, at most 16
current/past observations, and the past-only nominal three-RMS innovation test.
Current DC remains separate. The abrupt four-RMS frequency mask will become a
continuous shared-RGB weight:

```
weight = max(0, 1 - (4 * nominal_selected_coefficient_sigma / max_rgb_amplitude)^2)
```

The selected coefficient and its sigma use the current observation on an
innovation, otherwise the current-inclusive causal mean. DC weight is one.
This tests whether support switching is responsible for temporal noise while
preserving strong wave/material coefficients. Shrinkage can attenuate weak real
detail, and dense/correlated spectra can invalidate the nominal noise scale;
these are required counterexamples, not excluded scenes. No threshold will be
tuned after the native results are read.

The planned fresh native matrix uses split strength 1, Gaussian sigma 0.012,
64 frames at 128x80, seed 920531, and the existing thirteen scenes:
fake diffuse/specular, material, stationary/moving wave, strong/weak checker,
flat lighting step, persistent shared bias, guide-correlated noise, textured
lighting step, disocclusion and reset. Source/null/pilot use three separate
contexts per scene, identical consumed guide RGB, geometry, ray alpha,
reset/jitter, provider and tuning. Oracle truth is not a pilot input. Frozen
full/mature, contour, RGB, temporal, phase, contrast and representability gates
remain unchanged. This seed separates source-noise samples from development;
the scene families are familiar, so it is not unseen-content game acceptance.

Before the next native ablation, a source-pilot-only comparison on the old
additive holdout showed that increasing the corresponding soft history from
16 to 64 reduced mature material pilot temporal deviation from `0.000408` to
`0.000166`, and wave from `0.000278` to `0.000136`. Moving-light pilots were
bit-identical, but weak coefficients after lighting/disocclusion transitions
became less accurate. These are pilot scores, not new native outputs. The next
complete thirteen-scene native matrix will therefore repeat seed 920531 with
history 64, all other controls/gates unchanged, fresh source/null/pilot contexts,
and a new evidence directory. Transition families remain mandatory.

The source-only DC-conditioned ablation is kept separately: it applies the
nominal three-RMS innovation criterion to the global mean and leaves all
non-DC coefficients unchanged. Its CPU tests include deliberate subthreshold
lighting lag. A native matrix is not yet assigned to it because the latest
attribution does not support DC as the dominant noise cause.

Production shaders, settings and the installed game DLL are unchanged by these
test prototypes. Game validation and a runtime cost/lifetime implementation
remain required for final acceptance.

## New attribution and the completed sixteen-observation native run

The follow-up attribution separates DC and non-DC pilot variance. In the old
additive holdout, material pilot DC RMS was `0.000108`, non-DC RMS `0.000877`,
and native pilot-response non-DC RMS only `0.000067`. For wave these were
`0.000108`, `0.000577`, and `0.000105`. DC accounted for roughly 1.5–3.4% of
pilot variance. The expected retained-coefficient noise for a fixed support
already matches the observed material/wave fluctuation. Support switching is
an additional effect; smoothing the support alone cannot remove the noise
remaining inside retained coefficients. These nominal IID calculations do
not establish a game confidence bound. The archived attribution v2 fixes a
RGB-sum versus RGB-mean variance unit error and checks Parseval equality.

The fresh sixteen-observation run completed 39 independent native contexts,
2,496 RR dispatches, thirteen 64-frame scenes, with zero reported SDK/D3D
validation errors or warnings. An independent second-agent audit regenerated
all thirteen FP16 pilots bit-exactly from their saved source snapshots and
checked consumed-input, dispatch-control, tuning, provider and runner hashes.
Eight of thirteen scenes passed both frozen full/mature effectiveness gates.
Material and wave still failed mature temporal noise; reset failed temporal
noise in both windows; persistent shared bias failed error, broad tone and
early-frame gates; textured lighting failed full contrast and effectiveness.
This is a failed research candidate, not image-quality acceptance.

Absolute detail checks remain separate from the relative baseline gates.
Weak material passed those relative gates but its native full-window minimum
gain was `0.86136` (mean `0.94418`), mature minimum `0.93384` (mean `0.95221`).
It therefore does not restore detail within five percent on every frame.
Lighting gain reached `1.20418` at frame 33. Moving-wave maximum phase error
was `0.03397` radians. Invalid-radiance fallback was unused in all thirteen
scenes; representability alone does not resolve these failures.

Textured lighting also had observed source/null RMS `0.01750357`. Every
consumed input and applied-control hash matched, but both native lobe output
hashes differed. The successful native helper retained manifests and deleted
the raw native/null payloads, so the first divergent frame cannot be recovered
from this run. No location or cause is inferred. The already registered
history-64 run now saves composed null-repeat arrays for fresh contexts and
reports each scene's evidence directory; selected scenes use a secondary disk
to preserve evidence while storage is constrained. The earlier report is
unchanged. The new null sample will be a diagnostic observation, not a
replacement that erases the earlier divergence.

## Factorized pilot feasibility

A separate CPU-only experiment fits a low-dimensional guide-linked image and
spectrally filters the signed residual. Two fixed blends, history-bounded and
full after two observations, were scored on thirteen authenticated old
additive sequences plus explicit adversaries. Clean reference never enters
the estimator; no new native response is substituted from an older pilot.
The full blend reduced mature material pilot temporal deviation from
`0.000408` to `0.000153`, but weak material mature minimum gain was `0.693`
and mean `0.926`. The bounded blend also failed absolute detail. Correlated
persistent guide/source spatial noise increased pilot RMSE by about 82% for
the full blend. Wave had no guide-linked component and received no benefit.
This model remains a failed feasibility experiment; covariance rank and low
temporal variance do not prove material fidelity or unbiased radiance.

The two new pilot CPU suites are registered in `validate_fsrd.py`. The combined
response, protocol, statistical-resolve, RRTrace and new pilot checks passed
100 tests. Production code/shader binaries have not changed, so this does not
represent another production build or complete release gate.

## Captured-geometry follow-up, registered before execution

After the complete thirteen-scene history-64 matrix, run one fresh
`recorded_wave` sequence on the authenticated historical 256x256 geometry at
`frame_33098_stage6_3_2898562/capture.json`. Use 96 frames, history 64, split 1,
bounded uniform source noise sigma 0.012, and seed 932061. Source, null and
pilot are new native contexts with the captured camera, fixed captured jitter,
ray alpha and consumed guides. Save null-repeat arrays and assess both the
whole field and the exact water ROI, y25:85/x5:85, with the existing gates.
No oracle or old pilot response is reused, and signed invalid-radiance
corrections return whole-RGB baseline. This checks synthetic wave radiance on
real geometry. The historical Joint capture supplies no independent alpha
game truth or temporal scene sequence; neither this run nor a passing ROI
will establish game-quality acceptance.

## Completed long-history and captured-geometry evidence

The history-64 thirteen-scene matrix completed another 39 contexts / 2,496
native dispatches. Independent audit verified source/pilot FP16 equality,
all seven consumed input hashes, applied controls, process/log identities and
zero ordinary SDK/D3D errors or warnings. Eleven scenes passed both frozen
relative effectiveness gates. Reset still failed full-window temporal noise;
shared persistent bias failed both windows. Absolute weak-detail minimum gain
remained `0.86136` full and `0.92121` mature, despite relative acceptance.

Long history reduced candidate temporal noise relative to the sixteen-frame
candidate, not relative to the native baseline. Mature material STD was
`0.00023449` versus baseline `0.00016565`; wave `0.00023619` versus
`0.00016195`; reset `0.00030146` versus `0.00020944`. The frozen gate's
`1e-4` additive tolerance allows these increases. Passing that gate is not
evidence that native noise was reduced or the requested visual problem solved.

The 96-frame captured-geometry run completed three contexts / 288 dispatches.
Whole-field and exact water ROI relative gates passed. Water gain stayed
`0.96042–1.00907` full and `1.00249–1.00665` mature. Early water-halo phase
reached `0.11651` radians, exceeding the independent absolute `0.05` detail
limit; mature phase maximum was `0.01713`. Mature candidate water STD was
`0.00024595` versus baseline `0.00022009` (+11.75%), while full-window STD
improved from `0.00148876` to `0.00054983`. Null water RMS was `0.00020041`
full / `0.00017784` mature. Invalid correction fallback was unused. These
failures and the historical-Joint/synthetic-radiance scope remain explicit.

## Native context stability and a one-control follow-up

The long64 lighting source/null pair was bit-identical, but its source baseline
differed from the old16 source baseline with RMS `0.01756393`. The seven
inputs, applied controls, provider and runner source were equal. PE section
audit proved the two runner executables differed only in COFF/debug timestamps;
instruction, import and other payload bytes were identical after normalizing
those two metadata fields. This does not explain the native output difference.

Four additional contexts then used the exact same existing long64 runner
binary and consumed source inputs. All pairwise native-lobe RMS values were
nonzero (`0.00098163–0.00969765`, RGBA including both lobes). Full original
FP16 lobe bytes were reconstructed and hash-checked against the helper's
native output identity before retention. Composed frames 0,1,31,32,33,34,63
are retained as well. This proves observed native context variability under
the pinned experiment; it does not identify a provider bug or establish a
population variance bound. The caller review found no concrete applicable
initialization, upload, state, fence or control error. Ordinary debug-layer
success does not imply GPU-based validation was enabled.

Before the next execution, register one diagnostic control: four more contexts
with the same runner, seven inputs, camera, tuning and jitter, adding only the
SDK's RESET bit at the known synthetic lighting transition, frame 32. Compare
all applied dispatch bytes to enforce this single difference. This tests
pre-transition history sensitivity. It does not select a production reset
policy, explain startup randomness or justify discarding earlier divergence.

The new physical-coefficient history pilot also remains CPU feasibility. Its
single preregistered nominal three-SE innovation rule averages physical guide
coefficients before shrinkage, cuts history on rank/control changes and uses
exact raw/inactive output with insufficient guide history. Mature weak gain
improved to `0.96799–1.02903`, but full minimum remained `0.69318`; slow
amplitude drift reached mature gain `0.92484`, and correlated persistent
guide/source bias still failed. No new native response or runtime implementation
was claimed for this prototype.

The scientific [native history comparison](evidence/fsrd_response_followup_figures/native_history_comparison.png)
shows native noise, absolute weak/lighting gain and the stationary wave profile.
Its source report/array hashes are retained in the adjacent provenance file.

The RESET diagnostic completed four contexts / 256 dispatches. Independent
audit checked all unchanged texture hashes and found exactly one changed
applied byte: frame32's flags changed from 2 to 3. Frames32–34 matched exactly
across all six pairs. Subsequent native RGB variation remained, although its
observed pairwise range was smaller than in the earlier four no-reset samples.
Post32 selected-composed pair RMS was `0.00004817–0.00005247` versus
`0.00023210–0.00111700` before this control. RESET also materially changed
the source operator: selected output RMS versus the old long64 anchor was
`0.0676554` for run0. A lower repeat spread cannot justify that image change.
No reset-policy quality acceptance or caller-bug claim follows.

A two-frame source conversion inspection confirmed specular input alpha is
zero and direct diffuse input alpha is `65504` in this rough synthetic
lighting fixture. The shader's roughness/emissive/bias tracking ramp controls
the specular alpha; zero is not evidence of a missing required fixture field.
The SDK header documents ray channels but supplies no positivity restriction.
The second agent's earlier inference from output alpha to input alpha was
withdrawn in a retained erratum before this direct measurement. This
inspection used two conversion dispatches and no new native RR contexts.

The [compact follow-up archive](evidence/fsrd_response_followup/manifest.json)
contains 928 copied report/source/contract files, exact-byte hashes and paths
to the retained large arrays. This package adds 89 completed native contexts
and 5,792 RR dispatches. With the previous package's 195 / 8,016, completed
research totals are 284 contexts / 13,808 RR dispatches; earlier failed partial
runs remain separately recorded. These counts describe execution evidence,
not accepted visual cases. The task remains open: absolute weak detail,
startup phase/noise, persistent shared bias, native context variability,
surface correspondence, runtime cost and real-game validation are unresolved.
