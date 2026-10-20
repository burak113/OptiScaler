# Job 06: moving-bottle support, transport and history

## Decision

**Keep as research.** The completed candidate is a portable, read-only temporal
support tracer and a bit-preserving identity handoff. It is useful for separating
source support, geometric correspondence, specular correspondence and stage
retention when the necessary observations exist. The seven-frame real bottle
fixture does not identify a production-safe image correction. No reset, roughness
inflation, blur, motion edit or support rejection is proposed for the working
pipeline.

The central recorded finding is narrow and strong: **raw RR and selected output
are bit-identical for both lobes on 55,452 original moving-mask pixel observations**
over frames180–186. The full specular crops are not identical: 456 FP16 RGB words
at 152 pixels differ outside that mask. This localizes the absence of an additional
selected-stage difference on the observed moving support. It does not prove that
the input shape is right, that the provider history is right, or that final game
composition is right.

Evidence for these statements is in [recorded_analysis.json](evidence/recorded_analysis.json)
and the separately computed [review stage check](review/baseline_stage_scope.json).
The independent reviewer also recommends research only; see [REVIEW.md](review/REVIEW.md).

## Revisions, boundary and evidence types

The annotated tag object is `1f18416f5b99a0f78e147f362ac436ce2116ed22`.
It resolves to commit `5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`, from which
`astra/06-moving-bottle` was created. The production source baseline documented
by the handoff is separately `87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`.
The tested source revision and individual hashes are recorded in `RESULT.json`.
Every added file is under this candidate directory; production files and all
91 frozen package files remain unchanged. The PR targets `sol/26-integration`.

| Evidence | What ran here | Permitted conclusion |
|---|---|---|
| Frozen CPU reference tests | Four original suites, before and after candidate work | Reproduces packaged arithmetic and known failures |
| Recorded GPU tensors | Read-only CPU analysis of the supplied bytes | Stage equality, support proxies and observed correspondence residuals |
| Analytic scenes | New NumPy models with known trajectories and separately injected causes | Conditional causal separation and metric falsification |
| Independent blind review | Anonymous tensors, predictions sealed before label reveal | Independent broad-class diagnosis or justified abstention |
| Historical GPU receipts | Read as prior evidence only | No new execution claim |
| Actual AMD RR/native build/final game | **Not executed** | No game-quality, GPU-time or shipping claim |

The source and mechanism audit binds 19 native files to hashes and immutable
references: [MECHANISMS.md](analysis/MECHANISMS.md),
[SOURCE_AUDIT.json](analysis/SOURCE_AUDIT.json). The source's own trace contract
does not separately attest upstream exposure or exact material modulation.
“Physical/native” below means the bridge-restored signal domain, not an
independent calibration of final displayed light energy.

## Available data and fixed evaluation contract

| Fixture | Original frames | Width × height | History/semantic limitation |
|---|---:|---:|---|
| bottle_track7 | 180–186 | 128 × 256 | Moving crop; mask includes bottle, hand and arm; no true silhouette |
| foliage23 | 43–65 | 192 × 64 | Multiple geometry layers; not semantic foliage truth |
| facade16 | 34–49 | 96 × 96 | Small tile, not the old whole-ROI benchmark |
| glass_crop | 46–63 | 192 × 160 | Aligned radiance, unwarped geometry; 6,497-pixel fixture mask |
| Anchor/colour packages | As documented in their manifests | Shader fields/one calibrated colour frame | Not full original histories or a fresh RR replay |

The four package directories contain 56 inventoried files. Their hashes, sizes
and safe NPZ array inventories are in [inventory.json](evidence/inventory.json).
Every NPZ is opened with `allow_pickle=False`. No original tensor is averaged,
rewritten, normalized in storage or converted to invent a missing observation.
All recorded input arrays are hashed before/after analysis.

The bottle mask is fixed from original full-render speed **>12 pixels/frame**
with a two-pixel erosion. Its counts are
`[9275,9430,9560,9864,8730,5479,3114]`. The mask is not reconstructed from candidate
output and is not a bottle segmentation. Foliage/facade controls use a fixed
crop interior excluding two border pixels. The exact masks are retained in
[fixed_base_masks.npz](evidence/fixed_base_masks.npz).

The render extent is 1505×847. Bottle global crop X is688 and crop Y is
`[160,176,208,272,384,480,560]`. The portable API delegates to the frozen loader:

```text
previous_local = current_local + current_crop_origin
                 + motion_RG * full_render_extent - previous_crop_origin
```

No extra jitter is added. Motion is previous-minus-current full-render UV.
History outside the previous crop is unknown, never clamped. The first frame,
gaps and explicit reset/domain comparison breaks have no prior observation.
The reset flag is read from the real 46-word dispatch control suffix; invalidating
the diagnostic comparison does not reset AMD RR or NZR. DRS/convention changes
require explicit segments. Fractional render extents are rejected.

The scalar brightness-support thresholds are frozen physical/native luma values
`0,0.0001,0.001,0.01`; they do not label true geometry. The named-stage tracer
transports thresholded binary support as bilinear coverage and reports mixed
coverage separately. The radiance diagnostic also measures thresholding after
bilinear radiance transport. These operators do not commute and are explicitly
labelled in JSON and the visual viewer. Both use the same coordinate reference.

## Real bottle results

### Where an additional difference is absent

| Domain | Compared FP16 words | Different words |
|---|---:|---:|
| Moving mask, diffuse | 221,808 | 0 |
| Moving mask, specular | 221,808 | 0 |
| Entire crop sequence, diffuse | 917,504 | 0 |
| Entire crop sequence, specular | 917,504 | 456 |

The 456 differences are all RGB; alpha is unchanged. Per-frame specular counts
are `[210,144,90,0,12,0,0]`. The fixed mask covers 55,452 pixel observations, not
55,452 independent samples. The two masked lobes together cover443,616 FP16
word comparisons. Do not generalize these results to every pixel, unseen frames
or all internal history. The saved raw RR already contains unobserved pre-start
provider history.

### Current lighting is sparse, but sparsity is not a faulty silhouette

Within this mask, exactly zero RGB occurs in **27.5536% of diffuse input** and
**20.7026% of specular input** pixel observations. Raw RR is nonzero everywhere
on the same support at the zero threshold. The complete threshold sensitivity,
input hit-distance distributions and per-frame support disagreements are in the
recorded JSON. This demonstrates densification of sparse observations; it does
not establish that an upstream estimator delayed the physical object. Correct
stochastic samples can be zero. A history gate that treats every dark current
sample as absence would discard valid accumulation.

No measured real silhouette lag, true shape IoU or physical disocclusion leakage
is claimed: those fields are `null`. The missing independent shape/feature witness
cannot be replaced by a brightness threshold or the motion-derived mask.

### Wrong motion models are distinguishable, without certifying perfect motion

For frames181–186, the BASE moving support has46,177 pixel observations, all
inside previous crop support for original motion. A 1.5× motion diagnostic loses
1,349 of those observations. Scores on the full fixed denominator penalize that
loss; a second comparison uses the **same44,828-pixel intersection**, frozen
before either score is evaluated:

| Proxy on fixed common support | Original1× motion | Diagnostic1.5× motion |
|---|---:|---:|
| Mean original-normal angular disagreement | 23.8172° | 52.2186° |
| Median original-normal angular disagreement | 20.5603° | 46.2446° |
| Mean relative depth residual, clipped to1 | 0.078316 | 0.620114 |
| Mean symmetric specular-input luma error | 0.783090 | 0.794872 |

Original1× also has lower angular residual than the deliberate half-scale,
reversed-sign, crop-extent and missing-origin models. Missing the crop origin
makes11,678 BASE-mask observations unsupported; reversing motion makes25,329
unsupported. These are diagnostic interventions, not candidate image outputs.

Normal/depth self-alignment is still not exact flow truth. Real normal rotation,
mixed geometry, noisy/depth provenance, occlusion and bilinear interpolation
contribute residuals. Homogeneous planes offer weak correspondence witnesses.
These observations oppose an arbitrary1.5× fix; they do not eliminate every
surface-motion defect. The seven crops contain no G3 absolute-B65504 sentinel,
but that does not prove G3 inactivity outside them or earlier.

## Native mechanisms and unresolved alternatives

The detailed audit traces current native decode through owned D/S inputs,
G3, radiance scale, actual provider descriptors, raw RR, recovery selection,
encoded title commit and original Consumer. Internal staging is specular-first;
provider descriptors are DirectDiffuse then IndirectSpecular. Input alpha,
RR alpha and the title destination alpha have different ownership/meaning.
The commit preserves the title's existing alpha.

Two distinctions are material to this task:

1. **TemporalOFF leaves Reflection History possible.** Native reflection history
   is enabled by `reflectionHistory && !temporal`. Its shader extends a view ray
   with specular hit distance and reprojects by camera, assuming a static planar
   reflector. It reads no surface MV. A moving/curved bottle can violate that
   model; the current raw/selected equality does not demonstrate this path added
   the observed moving-mask tail. AMD's internal virtual path is a separate
   unknown mechanism.
2. **G3 depth rejection is not XY motion.** G3 preserves motion RG/A and can put
   a signed65504 rejection sentinel in B. The code separates this from geometry
   dz. Optional Anchor changes private D/S routing while G3 reads original source
   inputs; those domains must remain distinct.

| Hypothesis | Distinguishing observation | Current conclusion |
|---|---|---|
| Delayed/sparse source support | Raw source already disagrees with independent current object support while geometry agrees | Input sparsity observed; physical delay remains unidentifiable |
| Incorrect surface transport | Independent geometry/opaque control fails, oracle motion fixes that witness without altering raw support | Analytic falsifier works; no arbitrary MV change justified by the real crop |
| Different specular correspondence | Surface aligns but independently tracked reflection does not | Analytic separation works; real virtual truth missing |
| Provider history retention | Correct source/geometry, first additional tail in raw RR | Synthetic stage localization works; real prehistory/source truth insufficient |
| Selected NZR retention | First additional tail appears only in selected output | No incremental difference on the specified real moving mask; broader claim unresolved |
| Composition/exposure | Source-domain and final same-frame support disagree under known composition | Final output/remod/exposure evidence absent |

Each prediction, counterexample and minimum observation is expanded in
[MECHANISMS.md](analysis/MECHANISMS.md). A generic ghosting score cannot distinguish
these rows. A coupled provider/NZR reset is not an isolated history experiment.

## Synthetic implementation and falsification

`synthetic_scenes.py` supplies a thin bottle-like shape, changing orientation,
static wall/text, known object/camera motion, different apparent specular motion,
partial entry/exit, re-entry, sparse lighting and exact analytic geometry. It
separately injects source delay, MV bias, alternating jitter-like error, virtual
mismatch, provider tail, selected-stage tail and multiplicative level change.
These stage arrays are deliberately simple interventions, **not an AMD RR model**.

The experiment split was frozen before evaluation:

- Training: straight trajectory, Gaussian multiplicative noise, seeds100–107.
- Holdout: curved trajectory with re-entry, moving camera, Poisson plus salt noise,
  seeds900–907. Both trajectory and noise family differ.
- Nine cause/control families × two splits × eight seeds =144 condition/seed runs,
  each24 consecutive frames. These are not144 independent captured histories.
- Analytic threshold sensitivity:0.1,0.25,0.5, reported for diffuse and specular
  separately. Confidence intervals bootstrap independent seeds within each fixed
  scenario, not correlated pixels/frames or arbitrary trajectories.

Metrics report raw and level-matched IoU and occupancy lag, signed behind/ahead
energy, physical disocclusion leakage, residual flicker, gradient grain, p99
sparkles, static detail and light response. A required explicit physical
disocclusion mask is built from independent background/camera correspondence
and crop origins. If that witness is unavailable the metric is `null`.

The analytic classifier recovered its declared observable class in all144 runs.
That is a check on this constructed model with oracle witnesses, not real-capture
diagnostic accuracy. It explicitly refuses the recorded-capture domain and
requires independently declared synthetic geometry/support authority. Zero hit
distance leaves virtual correspondence unobservable; one-pixel geometry with no
conservative support, wrong guides and missing witnesses cause abstention.

The single-mechanism interventions are executable: oracle MV does not repair a
delayed input; oracle source support does not repair wrong MV; current-input-only
and raw/selected observation swapping localize different injected tails; the
virtual oracle changes only virtual correspondence. Stored downstream stages
are not falsely claimed to have been rerun after an input intervention.

### A negative metric result that must be retained

On the heldout specular case at threshold0.5, merely multiplying the selected
signal by0.65 improves unnormalized occupancy IoU and lowers residual RMS:

| Metric, eight-seed mean [95% bootstrap interval] | Original synthetic control |0.65× level-only diagnostic |
|---|---:|---:|
| Raw threshold IoU |0.51147 [0.50029,0.52224]|0.65851 [0.64594,0.67050]|
| Level-matched IoU |0.51282 [0.50045,0.52456]|0.51282 [0.50045,0.52456]|
| Level-matched occupancy lag |0.02997px [0.00785,0.05412]|0.02997px [0.00785,0.05412]|
| Level relative to analytic target |1.02980 [1.00822,1.05614]|0.66937 [0.65534,0.68649]|
| Residual temporal RMS |0.08018 [0.07792,0.08295]|0.07114 [0.07017,0.07219]|

This is not shape repair. The normalized structure/lag is identical and energy
is reduced35%. It directly falsifies selecting a remedy by a darker screenshot,
one occupancy score or residual RMS alone. Full measurements and confidence
intervals are in [synthetic_results.json](evidence/synthetic_results.json).

## Independent skeptical review

Three separate agents owned mechanism audit, implementation/testing, and
skeptical review. The reviewer first reproduced the known rejected colour
soft2 control (expected exit1; six of32 CPU edge phases worse), independent bad
coordinate models, and a level-versus-shape counterexample. Only then were
anonymous synthetic tensors provided. No claimed candidate win was supplied.

The reviewer's predictions were sealed at SHA256
`89285b452a6d77d81c27f8a4d9b16afb64dc94fbba9d26a9f6f3173e301f9406` before
the precommitted private key
`5c69f858b3364f9d2ae4d3215d6d902ac05708a93b76e373f3e81fd682d881a0`
was revealed. **Ten identified/qualified broad classes were consistent; four
appropriate abstentions; zero contradictory broad-class claims.** Five identified
cases used the heldout trajectory/noise. The identical cases13/14 are one
observational-equivalence check. Alternating motion error remains compatible
with jitter error or alternating MV bias; source misplacement does not uniquely
identify a real estimator.

Review caught and corrected the local-coordinate disocclusion error, omission
of wall/text from the initially measured composite, and undefined empty metric
reductions. The final interface also explicitly invalidates comparisons on
metadata breaks and rejects fractional render extents. The independent reviewer
ran the39-test corrected suite and then the two final metadata tests. Root ran
the integrated41-test suite. Receipts and exact executor attribution are in
[AUDIT_RUNS.json](review/AUDIT_RUNS.json), [AUDIT_VERDICT.json](review/AUDIT_VERDICT.json)
and [BLIND_SCORE.json](review/BLIND_SCORE.json).

## Preservation, verification and reproducibility

The only image candidate, `abstain_identity`, preserves every byte and owns its
CPU copy. It adds no frame of temporal delay and keeps no feedback/history. CPU
copy cost is not zero runtime and is not a measured native GPU cost. No shader,
CSO/header or host patch is claimed. The exact read-only adapter specification
is provided for job08; job04 interoperability is a documented compatibility gate,
not a claim that another conversation's uncommitted API was imported.

The recorded bottle/foliage/facade selected D/S and aligned glass D/S preservation
test compared **23,822,336 bytes with zero changes**. Static wall/text controls
retain exact bytes and a1.0 detail ratio. Fixed-support1.1×/1.25×/1.4× light changes
retain a1.0 candidate-to-baseline response ratio. These are preservation results,
not denoising gains. A complete chronological water control is not supplied;
the old water receipt remains historical and actual native water acceptance is
still local.

Executed here: Python3.12.14, NumPy2.3.5, Linux CPU. The required dependency was
already installed; no dependency installation is falsely reported. The initial
package validator passed91 files/141 safe NPZ arrays and the four baseline suites
passed. The final full runner passed41 candidate tests, required the crop-origin
mutant to fail with two assertions, generated all measurements and verified the
frozen package again. The final run took39.4002 seconds on this CPU environment;
this is not a performance claim about the native application.

```sh
python -B research/astra20261020/candidates/06-moving-bottle/run.py
python -B research/astra20261020/candidates/06-moving-bottle/review/analyze_blind.py
python -B research/astra20261020/candidates/06-moving-bottle/review/score_blind.py
```

The main runner exits0 only when required checks succeed and the deliberate
mutant exits1. Actual commands, exits, elapsed times and log hashes are retained
in [cpu_runs.json](evidence/cpu_runs.json). Traceback repository/runtime prefixes
are sanitized for portability; assertions and measurements are unchanged.
`SHA256SUMS` binds the delivered snapshot and excludes itself. Re-execution can
change timing/log hashes, as documented in the README.

The [local viewer](evidence/visuals/index.html) contains all seven chronological
frames, with matching crops/aspect and fixed BASE exposure per lobe. The two
rows are diffuse/specular; columns are current input, transported previous input,
raw RR, selected, and support overlap. Unknown history is coloured distinctly.
The original tensors are preserved. Recorded frame durations are absent, so
the viewer steps frames without inventing real-time playback. Final game output
is explicitly unavailable.

## Smallest remaining local gate

Start by inspecting/exporting the existing2405579e source capture. The surgical
request is frames168–207 in the original fixed strip, global origin(688,0),
128×847. Approach/motion/settle containment is not attested; if that window fails,
choose one documented consecutive window of at most48 frames and at most108,416
pixels per frame. Do not splice phases or loop history.

The exact roles include native input D/S and alpha, raw RR, selected, provider
MV/depth, original/provider normals, optional original pre-G3 MV, actual albedos,
encoded commit and complete per-frame lineage/settings/camera/timing metadata.
Hit distance already exists in the short fixture; the missing information is
longer chronology and independent reflection/shape authority. Obtain final
same-crop output separately with original frame mapping/exposure. Missing truth
must remain missing.

The maximum primary uncompressed payload is
128×847×48×100 bytes +2MiB metadata =522,493,952 bytes, under a512MiB cap;
aliases need not be duplicated. Final frames/video have a separate32MiB cap.
The request first uses existing observations and calls for a new bounded native
capture only when required roles were never recorded. See
[BLOCKED_DATA_REQUEST.json](BLOCKED_DATA_REQUEST.json).

For an actual diagnostic native A/B, preserve D16/S256, G2/G3, RR Fallback,
Diffuse RR, Reflection History, TemporalOFF, the working glass setting and
default-off experimental features. Verify frame/resource identity, fences,
D3D debug/lifetime/transition state and unchanged output words. Any reset branch
must be separately labelled; the usual wrapper reset couples provider and
recovery, so it cannot isolate provider history. GPU timing/memory and native
build results remain `null` until measured. Final acceptance requires a new
unlooped motion sequence and actual game observation, as specified in
[GPU_REQUEST.json](GPU_REQUEST.json).

The delivered code narrows the diagnosis and prevents several convincing false
fixes. It intentionally leaves the working image pipeline unchanged until the
missing observations can select a defensible mechanism.
