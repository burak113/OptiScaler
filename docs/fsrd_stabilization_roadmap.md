# FSRD quality and simplification roadmap

29 September 2026 — proposed order of work. Reference: `codex/fsrd-stage8`, `395c3182`.
This document is neither an implementation nor completed quality acceptance. Its scope is the FSRD/FSR-RR module.

**Priority update:** The plan was to first close the stage work with its existing
results and produce an alpha focused on modulation/demodulation from the
`ffx-denoise-experimental` base. The first work package is now the
[Experimental Alpha plan](fsrd_experimental_alpha_plan.md). The general quality
sequence below describes work after the alpha and ongoing regression checks;
it is not an instruction to expand Stage/Joint development.

## Goal

Release a version whose default behavior is understandable and reproducibly
verified, without requiring users to rescue the image by trying many settings.
Priority order: albedo modulation and stains → skin noise → ghosting → cost
and simplification → controlled distribution. Ghosting and performance checks
are part of acceptance for every change from the first phase onward; their
main correction packages come later.

I propose pausing new visible features and new user settings throughout this
period. Instead of adding another option alongside an experiment that cannot
solve a problem, we will record its evidence and keep it in research tools.
Infrastructure required to fix a defect is outside this restriction.

## Current state: what do we know?

- Stage 5 research showed that a varying normalizer can carry a false albedo
  pattern into the output. Constant M did not solve all stains and detail loss.
- Stage 7 records that representation/guide/tuning changes are not a general
  solution to blur. Preserving real material texture and suppressing an
  incorrect guide pattern are separate acceptance conditions.
- Stage 8 StainGuard and DetailRecovery exist; they are disabled in the
  distribution INI. There are synthetic gains, but quality/performance
  acceptance in real games remains open.
- Stage 8 history validity depends on the fence and command list lifecycle.
  Synthetic gains should not count as game gains without measuring whether
  history actually matures in the game.
- The Stage 8 detail path requires 56 bytes/pixel of additional buffers per
  active frame; the document states approximately 464 MB/frame at 4K and a
  need for multiple buffers. At 512×288, the path with mature history consumed
  approximately 1.28–1.64 ms median GPU time. These measurements will not be
  extrapolated to 1080p/4K time; the actual targets will be measured.
- The root cause of skin noise has not been verified in this work. SSS, lobe
  representation, guide mismatch, and noise from recovery are currently
  candidates, not diagnoses.
- The commit, build, and defaults included in the transfer to the widely used
  project reported by the user have not yet been compared.

## 0. Brief preparation: freeze the version and comparison

**Work:** Identify commit/default differences between local development, the
distributed version, and the project receiving the integration. Record the
known reference version and a one-command rollback. Keep options that have
not passed in-game acceptance in the experimental area and disabled; do not
change a default merely because it is the newest branch.

Create a small mandatory scene set:

- The same small water island/stain; a stationary camera and slow camera motion.
- Real albedo texture, a dark surface, and colored/glossy material.
- Skin: a stationary close-up, face/expression motion, camera motion, low light,
  and bright light. Use examples covering a range of skin tones.
- Ghosting: a surface newly revealed behind a silhouette, a moving object,
  a reflection, a sudden lighting change, and a camera cut.
- A calm region without detail; a control for noise being carried back into
  the output.

The first task is to check how well the existing RRTrace tools meet the need
for consecutive recordings of the same scene. If something is missing, add
only the necessary frame sequence and stage output recording; do not build a
large new diagnostic system. Resolution/frame count should be limited, and
recordings should include a checksum and build/settings identity.

**Completion:** Each main defect has a reproducible scene, a version/settings
identity, and a before/after sequence that can be captured under the same
conditions. A single ROI frame or two screenshots from different times are
not presented as temporal replay.

## 1. First main task: albedo modulation and stains

**Purpose:** Suppress material patterns absent from the source while
preserving real texture, lighting, color, and wave detail.

1. Isolate the stage where the defect first appears: source color/guides →
   converted input → AMD output → composition → recovery → upscaler output.
2. Track source albedo, the guide supplied to the model, the division factor,
   and the remultiplication factor separately. Report the closure test and
   visual correctness separately.
3. Compare shared-signal and source/effective-guide representations on the
   same input sequence. Do not treat combined color as if real independent
   diffuse/specular lobes had been obtained from it.
4. Evaluate StainGuard with DetailRecovery disabled. Do not confuse stain
   removal with detail injection or stronger blur. Then measure the added
   benefit and harm from recovery separately.
5. Once a successful representation is selected, move unnecessary
   alternatives out of the default path; require separate evidence for a
   new general albedo/roughness heuristic.

**Acceptance:** Demonstrate together a reduction in the false island/stain;
preservation of real material and wave contrast; no increase in color/brightness
deviation; no increase in grain in calm regions; and no new trails in motion
controls. Keep evaluation against a clean synthetic target separate from
evaluation of game imagery. Fix numerical thresholds after reference
measurement and before tuning the candidate, then test them on an independent
test scene.

**Deliverable:** One recommended normalization/guide behavior, a list of known
failing scenes, and before/after sequences of the same scene. Merely blurring
the stain does not close this phase.

## 2. Second main task: skin noise

**Purpose:** Reduce colored grain and shimmer on faces while preserving pores,
wrinkles, fine hair/beard, and eye and lip boundaries.

1. Find whether noise grows in the raw input, RR output, or after recovery
   within the face ROI. Compare recovery enabled/disabled and outputs
   before/after RR.
2. If the game provides skin/SSS/material information, verify its contract.
   Without such information, do not build a universal skin mask from an RGB
   skin-color estimate.
3. Investigate small values in source albedo, lobe/hit-distance meaning, and
   consistency between the guides and SSS or another lighting layer, if
   present. Do not change diffuse/specular weights or global blur without
   a diagnosis.
4. Evaluate stationary and moving faces separately. If noise is being added
   back as detail, fix the relevant recovery/confidence decision.

**Acceptance:** Under the same conditions, colored grain and temporal
flicker decrease; face detail is not erased, no plastic appearance or color
shift is introduced, and trails do not lengthen during facial expression/head
motion. Improvement on a single selected skin tone is insufficient for
general acceptance.

**Deliverable:** A skin defect with its source demonstrated and a bounded
correction targeting it. If game-specific material information is required,
document that dependency explicitly.

## 3. Third main task: ghosting and history management

**Purpose:** Reduce the transfer of old imagery onto newly revealed surfaces
and delayed response to lighting/color changes, without producing grain by
continuously resetting history.

1. Find the history that first produces the trail: AMD RR, existing
   Floor/recovery decisions, Stage 8 color/statistics history, or SR.
   Isolate one layer at a time.
2. Verify the contracts for motion sign/scale, render/display size, jitter,
   viewport origin, dynamic resolution, and depth reprojection.
3. Test disocclusion, camera cuts, exposure/lighting changes, sudden material
   changes, and reflections moving differently from their surfaces separately.
4. Record reset reasons, accepted history age, the fraction of pixels marked
   invalid, and history unavailable because of GPU/command list conditions.
5. Evaluate tuning after correcting contracts and history validity. Lower
   stability or a reset every frame is not a general solution by itself.

**Acceptance:** Trail energy/length and the number of recovery frames decrease
for events with a known reference; the grain/flicker budget in a stationary
scene is not exceeded. Old frame content is not carried across camera cuts,
resizing, or setting changes. Do not assign a numerical ghosting score to an
unknown moving game scene as though a clean target existed.

**Deliverable:** One current contract for ownership and reset rules of each
history; recommended settings verified with stationary and moving content.

## 4. Cost and feature simplification

Separating expensive/experimental options from default use begins during
preparation. Permanent algorithm removal and optimization follow once the
comparisons above have established the winning behavior.

- Measure total GPU ms, p95 frame cost, peak VRAM, temporary buffers, and GPU
  waits by scene and target render size. Prioritize Stage 8.
- Set memory and time budgets for the target GPU/resolution profile in
  advance; do not grant acceptance based on an estimated 4K FPS extrapolated
  from a small synthetic resolution.
- Inventory each option's actual consumer, whether it affects the default,
  verified benefit, and maintenance cost.
- Leave a small number of verified controls in the user menu. Remove
  experimental presets, stage numbers, and invalid combinations from the
  normal user flow.
- Remove failed/duplicate algorithms from the production path; retain the
  necessary counterexamples and reproduction tools on the test side.
- Apply explicit migration/warning rules for old INI keys. Do not silently
  give a user's old setting a different meaning.
- Link scattered documentation to one current entry page; mark old
  experiments as dated archives. Leave no conflicting descriptions of
  defaults for the same behavior.

**Acceptance:** Verified image gains fit the specified GPU/VRAM budget;
disabled features have no heavy resource cost; clean-install and migration
tests from an old INI pass. Every option in the main menu has a purpose the
user can understand.

## 5. Controlled distribution and integration

- Clearly distinguish stable reference, candidate, and research versions.
- Verify the candidate's differences from the actual build/defaults in the
  project receiving the integration; do not equate a source merge with
  in-game quality acceptance.
- Start with limited candidate distribution. Standardize build, GPU, game,
  settings, scene, and short reproduction steps in bug reports.
- Run the albedo/skin/ghosting matrix in target games and on available target
  GPUs. Explicitly state which hardware is not covered.
- Transfer verified fixes through small, reversible changes. Include default
  changes, rollback to the previous version, and known issues in release notes.

**Acceptance:** Mandatory scene acceptance, cost budget, compatibility, and
rollback are all complete, beyond merely "it built/tests passed." A release
is not accepted by removing a failing mandatory scene from the report.

## First concrete work package

The first package will address only albedo/stains: version/default comparison;
recordings of a stationary small island, moving water, real material texture,
and a calm region; separate A/B comparisons for StainGuard and DetailRecovery;
and identification of the stage where the defect first appears. Skin and
ghosting examples enter the reference set at the same time; a new skin
algorithm is not mixed into this first package.

Progression to the next package depends on acceptance results, not the
calendar. If one difficult scene blocks the research, preserve the current
stable behavior, keep an open issue record, and advance independent work;
do not make an unverified candidate the default.

## Sources

- [Stage 7: representation and history experiments](https://github.com/burak113/OptiScaler/blob/395c3182c71dd4832d5f83a17452030c548a20da/docs/fsrd_stage7.md)
- [Stage 8: existing options, quality and cost limits](https://github.com/burak113/OptiScaler/blob/395c3182c71dd4832d5f83a17452030c548a20da/docs/fsrd_stage8.md)
- [Stage 8 validation summary](https://github.com/burak113/OptiScaler/blob/395c3182c71dd4832d5f83a17452030c548a20da/docs/fsrd_stage8_validation.json)
- [Stage 5 representation plan](https://github.com/burak113/OptiScaler/blob/395c3182c71dd4832d5f83a17452030c548a20da/docs/fsrd_stage5_plan_TR.md)
- [Existing recovery controls and history notes](fsrd_recovery_controls.md)

The source implementation and game settings were not changed while preparing
this roadmap; previous experiments were not counted as though they had been rerun.
