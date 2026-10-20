# Astra Pro job 05: less glass specular grain while preserving the user's sharp Temporal-OFF NZR baseline

You are the implementation and research owner for this workstream. The user explicitly wants sustained, rigorous engineering with code, CPU experiments, and specialized subagents. A survey, a plausible shader, or a promising aggregate score is not a completed job. Find a mechanism, build the smallest experiment that separates competing explanations, implement the strongest falsifiable candidate, and have an independent skeptical agent try to break it. A well demonstrated negative result plus useful diagnostic code is a valid deliverable. Do not pad work with minimum hours, minimum experiment counts, or arbitrary complexity.

## Checkout, authority, and working boundary

Repository: https://github.com/burak113/OptiScaler . Open the actual tagged entry document at https://github.com/burak113/OptiScaler/blob/astra-handoff-20261020/research/astra20261020/START_HERE.md ; the repository default branch is not this handoff. Fetch tags and check out the immutable tag `astra-handoff-20261020`, then create your own branch `astra/05-glass-nzr`. Record the resolved tag commit. The audited production baseline is `87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`; the handoff tag may additionally contain the research package, so do not assume these two commit IDs are identical. Start from the tag, not an evolving branch or somebody else's candidate. Your eventual PR targets `sol/26-integration`; never enable auto-merge or merge a PR yourself.

First read [START_HERE](../START_HERE.md), [COMMON_PROTOCOL](../COMMON_PROTOCOL.md), and [RETURN_PROTOCOL](../RETURN_PROTOCOL.md), then inventory `research/astra20261020/portable/anchor`, `portable/colour`, and `fixtures/clips`. The CPU entry point is `python research/astra20261020/run_cpu.py`; run it before changes and preserve its output. Follow the package's actual dependency instructions. Inventory what data really exists, its units, masks, chronology, hashes, and provenance. Raw full captures, local project memory, the game, Windows-only GPU drivers, and AMD RR execution are not promised in this cloud package. A stored GPU result is a calibration witness, not a GPU you can rerun.

All your candidate code, tests, measurements, images, and proposed adapter belong under `research/astra20261020/candidates/05-glass-nzr/`. Jobs 01–07 must keep production files and the packaged baseline references unchanged: supply a narrowly scoped `adapter/PRODUCTION.patch` or exact adapter specification for job 08. Job 08 owns applying production changes in its integration branch after the dependency and local acceptance requirements are met. Preserve source line endings in patches, keep new experiments default-off, and protect the user's working baseline. Do not install a DLL into a game, edit secrets, or rewrite shared memory.

Use parallel subagents with explicit boundaries: at least a mechanism/representation investigator, an implementation/testing owner, and a skeptical independent reviewer. They may be the same number of available agents as your environment supports, but the skepticism must be independent of candidate tuning. Make the reviewer reproduce a known bad control before seeing your claimed win. Coordinate with other jobs through documented interfaces and artifacts; do not modify their folders or depend on their uncommitted files.

Known clip inventory: `fixtures/clips/bottle_track7.npz` contains frames180–186 in a moving 128x256 crop; `fixtures/clips/foliage23.npz` contains 87ee frames43–65 in a192x64 crop; `fixtures/clips/facade16.npz` contains f2ef frames34–49 in a96x96 crop. These are partial histories and omit albedo. Read their manifests and per-frame crop provenance: a moving crop is not camera/object motion, and these short windows cannot reconstruct unseen prior history. Inspect `fixtures/glass/` and its manifest if present for the aligned glass subset; do not assume all clips have all signal roles. Load NPZ with `allow_pickle=False`.

## Evidence and return contract

Use immutable BASE-derived masks and denominators; do not recompute the evaluation region from a modified candidate. Preserve chronological, unlooped sequences and report unsupported history/crop regions. Separate analytic truth, synthetic interventions, recorded GPU calibration, CPU model results, actual GPU execution, AMD RR output, and final game observation. None substitutes for another. Match crop, aspect, exposure, and frame timing in visual comparisons. Penalize grain, sparkles, and flicker explicitly rather than letting average blur metrics hide them. Never invent missing GPU, performance, build, or gameplay results.

Return `REPORT.md`, `RESULT.json`, `tests/`, exact runnable commands, candidate source, evidence and hashes, and `GPU_REQUEST.json` as prescribed by [RETURN_PROTOCOL](../RETURN_PROTOCOL.md). Include `BLOCKED_DATA_REQUEST.json` when necessary. Its content must identify the missing observation, hypotheses it distinguishes, exact requested tensors/metadata, units, frames and crop, provenance requirements, size estimate, and what useful work you completed without it; include the protocol's required fields. A data request must be surgical, not “upload everything.” Report rejection and uncertainty honestly.

Commit the reproducible work and open a PR to `sol/26-integration` if authenticated access is available. Otherwise return a ZIP containing the source, tests, evidence, commit IDs, binary patch or unified diff, and application instructions. Do not fabricate a PR link. Your recommendation must say ship as default-off A/B, keep as research, or reject, with the measured trade-off and the remaining local GPU/game gate. Write the final user-facing delivery summary in plain Turkish; technical documentation and source comments may remain English.

## Protected user verdict and exact scope

The user judges the game directly and prefers the existing NZR Temporal-OFF result for sharpness and lower perceived noise. Earlier “more correct” temporal accumulation lost this comparison. Preserve D16/S256 radiance scaling, G2/G3 behavior, TemporalOFF, RRFallback, DiffuseRR and ReflectionHistory. The working Glass A/B recommendation is Blend mode2 at strength.5; strength is the NZR fraction, not automatically the RR fraction. Confirm these semantics from the tagged source. Do not silently flip unrelated global defaults or tune the existing preset away.

The task is a mechanism-first improvement to specular glass grain/detail with a convincing CPU discriminator and a narrow default-off adapter. It is not permission to replace the user's working path with a generic temporal denoiser, blur away text, or call final-composite brightness conservation proven.

Source map: `FSRDNrdFlatAlbedoRecovery_Dx12.h`, `FSRDNrdBridgeRR_Dx12.cpp`, `precompile/FSRDNrdFlat{Prepare,History,Accumulate,ReferenceFilter,SelectPrep,SelectBlur,SelectApply,Polish}.hlsl`, the detail shaders/helpers and their actual binding headers. Confirm which files are reachable from the native path. Read `shader_tools/tests/fsrd_nrd_flat_albedo.cpp` and its Python driver for contracts, but do not assume the Windows GPU driver runs in cloud Linux.

The current native bridge's diffuse RR bypass, raw RR fallback, reflection history and vertical/glass policy interact. Protect each stage's authority and do not conflate them with the combined preprocessor.

## Competing hypotheses and unique tests

1. The robust reference fit or its sample support causes grain, rather than the input signal having unavoidable noise. Prediction: with fixed noise realisations, changing support/fit statistics changes speckle placement while raw mean/reference truth remains stable; hold the downstream selector constant.
2. Noisy selector/confidence boundaries cause flicker or spatial dots. Prediction: freezing the selector while preserving current RGB removes a specific component; freezing gains or replacing only confidence gives a different signature.
3. Detail restoration injects noise from a heavy-tailed or low-count residual. Prediction: the problem tracks count, variance and correlation, not all high frequencies equally. Text/sign detail and independent-noise sparkle must separate under a signal-plus-noise construction.
4. Reflection history has valid virtual transport but mixes wrong support at glass boundaries. Prediction: geometry-controlled phase/coverage changes matter even when a flat static-noise test looks good. An ordinary surface-MV fix should not be credited for reflected-feature motion.

Write these predictions before implementation and preserve the known user's comparison as a hard qualitative calibration requirement. A metric that ranks a visibly grainier historical control as better is not calibrated.

## Required implementation

Inventory which clips/tensors in the handoff actually contain glass, signs, puddle controls and chronology. A video can support a visual description but cannot supply numerical raw-lobe truth. If the relevant raw selected/raw RR/input histories are absent, implement the strongest analytic/synthetic test and diagnostic candidate, and request exact missing observations. Do not invent a raw mirror capture from a labelled crop.

Build a portable reference for only the necessary subset of the native NZR mechanism, traced to the real source, or a clearly bounded independent candidate. Preserve the existing baseline reference and all user-critical settings. Record what you did not port: provider denoising, native encoding, exact sampler hardware, unseen history or final remodulation. Use job01's contract when available and make versioned assumptions explicit.

Use many independently seeded noise realisations, chronological correlations and sparse heavy tails. A few reused noise frames or looped static inputs can make accumulation look unrealistically good. Construct known text/sign/line signals under noise, coloured reflections, thin bright glints, low-light mixed pixels, glass/opaque boundaries and a moving reflected feature. Include a true lighting/colour change so stability cannot be bought by stale history.

Implement the most defensible intervention at the cause: support-aware robust estimation, uncertainty-aware detail shrinkage, a better residual representation, or a confidence model. Keep low-band reflection energy separate from recoverable detail. Make the residual's noise/signal assumptions explicit and show a test that falsifies them. If you cannot distinguish signal from noise with available evidence, abstain locally and report the lost detail/noise trade-off.

Avoid arbitrary per-scene thresholds and semantic guesses. Do not change material IDs to label everything glass. Do not lower roughness or force RR fallback globally because one crop looks cleaner. Do not modify alpha/hit-distance as if it were disposable colour metadata.

## Calibration and acceptance

Score grain/sparkle tails and temporal flicker separately from blur, texture contrast, text legibility, low-band reflection energy and lag. Use fixed BASE masks, same crop/aspect/exposure, and separate raw-RR, NZR-selected, candidate and Blend.5 controls. The all-pixel identity percentage is misleading when most pixels are already unchanged. Report exactness and error on the actual NZR-changed specular RGB subset, protected diffuse pixels, edge bands and static texture regions.

Include null controls for “simply use raw RR,” “blur to lower high-frequency energy,” “freeze history,” and “reduce correction strength.” A candidate must explain why it beats the appropriate control at comparable detail/response, not only an inferior implementation. Test the existing flags and source selection semantics rather than assuming TemporalOFF means every temporal/reference ingredient is disabled.

The independent reviewer must try low-count startup, abrupt motion, DRS/history reset, newly visible glass, thin signs, crossed normals/depth, correlated noise and changed light. Report failure cases and the recommended A/B setting honestly. No CPU estimator score can establish the final AMD RR or game verdict.

## Return interface and local gate

Your candidate folder must include a per-lobe support/uncertainty interface, a source-shaped adapter patch and tests. Leave production scheduling, pointer/SRV selection, shared family budgets and traces to job08. Preserve the protected preset bit-for-bit when your option is OFF.

The GPU request must ask for actual native NZR+Glass execution at the preserved settings, raw and selected lobe captures with exact stage labels, fixed original masks, unlooped motion/settle and true-light changes, byte-preserved diffuse/alpha, and matched final-game visual A/B. Include Blend.5 and a sham/same-mode performance control; CPU cannot estimate full-game milliseconds or resident VRAM.
