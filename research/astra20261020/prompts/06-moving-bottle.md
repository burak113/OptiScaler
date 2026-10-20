# Astra Pro job 06: diagnosing a moving bottle through input support, motion and specular history

You are the implementation and research owner for this workstream. The user explicitly wants sustained, rigorous engineering with code, CPU experiments, and specialized subagents. A survey, a plausible shader, or a promising aggregate score is not a completed job. Find a mechanism, build the smallest experiment that separates competing explanations, implement the strongest falsifiable candidate, and have an independent skeptical agent try to break it. A well demonstrated negative result plus useful diagnostic code is a valid deliverable. Do not pad work with minimum hours, minimum experiment counts, or arbitrary complexity.

## Checkout, authority, and working boundary

Repository: https://github.com/burak113/OptiScaler . Open the actual tagged entry document at https://github.com/burak113/OptiScaler/blob/astra-handoff-20261020/research/astra20261020/START_HERE.md ; the repository default branch is not this handoff. Fetch tags and check out the immutable tag `astra-handoff-20261020`, then create your own branch `astra/06-moving-bottle`. Record the resolved tag commit. The audited production baseline is `87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`; the handoff tag may additionally contain the research package, so do not assume these two commit IDs are identical. Start from the tag, not an evolving branch or somebody else's candidate. Your eventual PR targets `sol/26-integration`; never enable auto-merge or merge a PR yourself.

First read [START_HERE](../START_HERE.md), [COMMON_PROTOCOL](../COMMON_PROTOCOL.md), and [RETURN_PROTOCOL](../RETURN_PROTOCOL.md), then inventory `research/astra20261020/portable/anchor`, `portable/colour`, and `fixtures/clips`. The CPU entry point is `python research/astra20261020/run_cpu.py`; run it before changes and preserve its output. Follow the package's actual dependency instructions. Inventory what data really exists, its units, masks, chronology, hashes, and provenance. Raw full captures, local project memory, the game, Windows-only GPU drivers, and AMD RR execution are not promised in this cloud package. A stored GPU result is a calibration witness, not a GPU you can rerun.

All your candidate code, tests, measurements, images, and proposed adapter belong under `research/astra20261020/candidates/06-moving-bottle/`. Jobs 01–07 must keep production files and the packaged baseline references unchanged: supply a narrowly scoped `adapter/PRODUCTION.patch` or exact adapter specification for job 08. Job 08 owns applying production changes in its integration branch after the dependency and local acceptance requirements are met. Preserve source line endings in patches, keep new experiments default-off, and protect the user's working baseline. Do not install a DLL into a game, edit secrets, or rewrite shared memory.

Use parallel subagents with explicit boundaries: at least a mechanism/representation investigator, an implementation/testing owner, and a skeptical independent reviewer. They may be the same number of available agents as your environment supports, but the skepticism must be independent of candidate tuning. Make the reviewer reproduce a known bad control before seeing your claimed win. Coordinate with other jobs through documented interfaces and artifacts; do not modify their folders or depend on their uncommitted files.

Known clip inventory: `fixtures/clips/bottle_track7.npz` contains frames180–186 in a moving 128x256 crop; `fixtures/clips/foliage23.npz` contains 87ee frames43–65 in a192x64 crop; `fixtures/clips/facade16.npz` contains f2ef frames34–49 in a96x96 crop. These are partial histories and omit albedo. Read their manifests and per-frame crop provenance: a moving crop is not camera/object motion, and these short windows cannot reconstruct unseen prior history. Inspect `fixtures/glass/` and its manifest if present for the aligned glass subset; do not assume all clips have all signal roles. Load NPZ with `allow_pickle=False`.

## Evidence and return contract

Use immutable BASE-derived masks and denominators; do not recompute the evaluation region from a modified candidate. Preserve chronological, unlooped sequences and report unsupported history/crop regions. Separate analytic truth, synthetic interventions, recorded GPU calibration, CPU model results, actual GPU execution, AMD RR output, and final game observation. None substitutes for another. Match crop, aspect, exposure, and frame timing in visual comparisons. Penalize grain, sparkles, and flicker explicitly rather than letting average blur metrics hide them. Never invent missing GPU, performance, build, or gameplay results.

Return `REPORT.md`, `RESULT.json`, `tests/`, exact runnable commands, candidate source, evidence and hashes, and `GPU_REQUEST.json` as prescribed by [RETURN_PROTOCOL](../RETURN_PROTOCOL.md). Include `BLOCKED_DATA_REQUEST.json` when necessary. Its content must identify the missing observation, hypotheses it distinguishes, exact requested tensors/metadata, units, frames and crop, provenance requirements, size estimate, and what useful work you completed without it; include the protocol's required fields. A data request must be surgical, not “upload everything.” Report rejection and uncertainty honestly.

Commit the reproducible work and open a PR to `sol/26-integration` if authenticated access is available. Otherwise return a ZIP containing the source, tests, evidence, commit IDs, binary patch or unified diff, and application instructions. Do not fabricate a PR link. Your recommendation must say ship as default-off A/B, keep as research, or reject, with the measured trade-off and the remaining local GPU/game gate. Write the final user-facing delivery summary in plain Turkish; technical documentation and source comments may remain English.

## Concrete problem and guardrails

The user observed a moving bottle/NPC artifact. Historical reset/roughness experiments did not establish a clean shape improvement. Do not assume a ghost is necessarily stale RR history or “fix” it with an arbitrary history reset, wider blur, roughness inflation, global history rejection, or a motion-vector edit that merely erases useful detail.

This job must distinguish whether the moving object is already wrong in source lighting/support, transported incorrectly, or retained incorrectly by a specular/history path. Its deliverable is discriminating diagnostic code plus the strongest conservative candidate supported by the available observations. A negative result that identifies an unobservable cause is useful; a confident story from an attractive screenshot is not.

Inspect actual native source and units: `FSRDNrdBridge_Dx12.cpp`, `FSRDNrdBridgeRR_Dx12.cpp`, geometry/material decode paths, `FSRDNrdLightingGuard_Dx12.h`, `FSRDRadianceScale_Dx12.h`, `FSRDNrdFlatAlbedoRecovery_Dx12.h`, `FSRDGameTraceSession.cpp` and `FSRDGameTraceBridgeMetadata.h`. Follow resource roles and lobe order from input to raw RR, selected NZR and encoded title commit. Preserve D16/S256, G2/G3, TemporalOFF and the user's working NZR controls.

Inventory `fixtures/clips` for actual bottle/NPC support. Some evidence may be video, already-produced results or cropped tensors; do not invent raw MVs, hit distance or pre-provider histories that are not included. A cropped object entering from outside the ROI has unknown prior support.

## Competing hypotheses and observations that distinguish them

1. The noisy input estimator carries delayed or spatially sparse object support. Prediction: a lagging shape/occupancy is visible in raw physical D/S input before RR, and geometric MVs can still be correct. Look for the object footprint and tail conditional on raw support, not just a brightness change.
2. Surface MVs, jitter inclusion, depth, camera transform or motion convention is wrong for the object. Prediction: an analytic foreground trajectory or a direct reprojection witness fails in both lighting-independent geometry and the lobe signal. Constant-colour opaque controls should also fail.
3. Surface motion is correct but specular virtual motion/history uses a different correspondence. Prediction: reflected features move differently from the surface while diffuse/silhouette transport is aligned; hit-distance-based virtual projection changes the prediction. Do not equate specular hit distance with an arbitrary generic depth.
4. Provider/internal or NZR history retains the wrong support despite correct current input and transport. Prediction: raw RR and selected output separate in where the tail first appears. Turning a particular stage into a diagnostic identity changes the artifact, but a blind reset can hide both genuine history failure and correct accumulation.
5. Final game composition or exposure makes a source-domain difference look like a shape lag. Prediction: pre-remod lobe occupancy and final display disagree systematically. Without exact final composition metadata, this remains a separate uncertainty.

For every hypothesis specify a unique prediction, an expected counterexample, and the minimum observation needed. At least one experiment must distinguish “correct motion but wrong source support” from “wrong motion with clean source support.” Do not let all hypotheses predict the same generic “more ghosting.”

## Required implementation

Build a portable temporal support tracer that accepts named stages and explicit coordinate conventions. On data that actually exists, generate synchronized overlays or animation frames for current raw support, transported previous support, raw RR, selected output and final clip if available. Keep overlays non-destructive and preserve the original evidence. Explain mask derivation and uncertainty at sparse/noisy pixels; BASE masks must be fixed before candidate evaluation.

Create analytic scenes with a thin bottle-like foreground object translating/rotating against a static wall, specular/reflected features with different apparent motion, disocclusion, partial crop entry/exit, and temporally intermittent current lighting. Include opaque and static-object controls, camera-only movement and combined camera/object movement. Provide known ground-truth trajectories and separately inject source-support delay, MV bias, jitter error, virtual-motion mismatch and stale-history tails.

Implement diagnostic interventions that alter exactly one mechanism at a time. They must be labelled diagnostics, not production fixes. Examples are an oracle support mask, an oracle MV, a current-input-only reference, frozen support with changing radiance, and swapping only raw-versus-selected observation. They must show which cause your metric can detect and which it confuses.

Then implement the most defensible candidate: perhaps support confidence, uncertainty-aware correspondence, or a narrowly justified handoff between current evidence and history. It may be a diagnostic abstention if no production-safe inference is possible. Define its required inputs, missing-data behavior, latency, state/reset semantics and preservation rules. Coordinate the coordinate/support API with job04; do not fork a second undocumented warp convention.

## Metrics and adversarial controls

Use silhouette/occupancy lag, signed tail energy behind/ahead of the true trajectory, object shape overlap, disocclusion leakage, temporal flicker/grain, retained detail and true-light response. Separate multiplicative level change from geometry displacement; a darker ghost is not necessarily a shorter or more accurate shape. Fix masks and exposure, and show chronological sequences rather than a best frame.

Do not select a support threshold using the candidate output and then celebrate a smaller artifact. Report threshold sensitivity and confidence intervals across independent noise seeds. Include fast/slow motion, one-pixel structures, low/no hit distance, wrong guide controls, mixed depth/normal boundaries and object re-entry. Show that the diagnostic detects a deliberately wrong MV and a deliberately delayed input, yet does not falsely blame motion in a correct-MV sparse-support case.

An independent skeptical subagent must inspect a blind set of injected causes and recover the diagnosis or explicitly report non-identifiability. Hold out both a trajectory and a noise family. Any proposed fix must preserve static text/sign detail and the working water/glass controls.

## Data request and local gate

If current assets cannot decide the real bottle mechanism, return `BLOCKED_DATA_REQUEST.json` with specific consecutive frames around approach/motion/settle, raw physical D/S, raw RR, selected RR, MVs and their units/jitter convention, depth/normal, hit distance and actual camera/control metadata; request final same-crop video separately. Explain why each item separates hypotheses and cap the requested region/time.

The local GPU request must use the actual native route and preserved settings, record stage snapshots at the correct time, and compare no-reset versus controlled diagnostic interventions. Do not ship an arbitrary reset. Final integration must demonstrate the candidate's declared mechanism on new unlooped motion, not only the synthetic bottle that you constructed.
