# Astra Pro job 08: independent host, ABI, lifetime and adversarial integration acceptance

You are the implementation and research owner for this workstream. The user explicitly wants sustained, rigorous engineering with code, CPU experiments, and specialized subagents. A survey, a plausible shader, or a promising aggregate score is not a completed job. Find a mechanism, build the smallest experiment that separates competing explanations, implement the strongest falsifiable candidate, and have an independent skeptical agent try to break it. A well demonstrated negative result plus useful diagnostic code is a valid deliverable. Do not pad work with minimum hours, minimum experiment counts, or arbitrary complexity.

## Checkout, authority, and working boundary

Repository: https://github.com/burak113/OptiScaler . Open the actual tagged entry document at https://github.com/burak113/OptiScaler/blob/astra-handoff-20261020/research/astra20261020/START_HERE.md ; the repository default branch is not this handoff. Fetch tags and check out the immutable tag `astra-handoff-20261020`, then create your own branch `astra/08-integration-acceptance`. Record the resolved tag commit. The audited production baseline is `87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`; the handoff tag may additionally contain the research package, so do not assume these two commit IDs are identical. Start from the tag, not an evolving branch or somebody else's candidate. Your eventual PR targets `sol/26-integration`; never enable auto-merge or merge a PR yourself.

First read [START_HERE](../START_HERE.md), [COMMON_PROTOCOL](../COMMON_PROTOCOL.md), and [RETURN_PROTOCOL](../RETURN_PROTOCOL.md), then inventory `research/astra20261020/portable/anchor`, `portable/colour`, and `fixtures/clips`. The CPU entry point is `python research/astra20261020/run_cpu.py`; run it before changes and preserve its output. Follow the package's actual dependency instructions. Inventory what data really exists, its units, masks, chronology, hashes, and provenance. Raw full captures, local project memory, the game, Windows-only GPU drivers, and AMD RR execution are not promised in this cloud package. A stored GPU result is a calibration witness, not a GPU you can rerun.

All your candidate code, tests, measurements, images, and proposed adapter belong under `research/astra20261020/candidates/08-integration-acceptance/`. Jobs 01–07 must keep production files and the packaged baseline references unchanged: supply a narrowly scoped `adapter/PRODUCTION.patch` or exact adapter specification for job 08. Job 08 owns applying production changes in its integration branch after the dependency and local acceptance requirements are met. Preserve source line endings in patches, keep new experiments default-off, and protect the user's working baseline. Do not install a DLL into a game, edit secrets, or rewrite shared memory.

Use parallel subagents with explicit boundaries: at least a mechanism/representation investigator, an implementation/testing owner, and a skeptical independent reviewer. They may be the same number of available agents as your environment supports, but the skepticism must be independent of candidate tuning. Make the reviewer reproduce a known bad control before seeing your claimed win. Coordinate with other jobs through documented interfaces and artifacts; do not modify their folders or depend on their uncommitted files.

Known clip inventory: `fixtures/clips/bottle_track7.npz` contains frames180–186 in a moving 128x256 crop; `fixtures/clips/foliage23.npz` contains 87ee frames43–65 in a192x64 crop; `fixtures/clips/facade16.npz` contains f2ef frames34–49 in a96x96 crop. These are partial histories and omit albedo. Read their manifests and per-frame crop provenance: a moving crop is not camera/object motion, and these short windows cannot reconstruct unseen prior history. Inspect `fixtures/glass/` and its manifest if present for the aligned glass subset; do not assume all clips have all signal roles. Load NPZ with `allow_pickle=False`.

## Evidence and return contract

Use immutable BASE-derived masks and denominators; do not recompute the evaluation region from a modified candidate. Preserve chronological, unlooped sequences and report unsupported history/crop regions. Separate analytic truth, synthetic interventions, recorded GPU calibration, CPU model results, actual GPU execution, AMD RR output, and final game observation. None substitutes for another. Match crop, aspect, exposure, and frame timing in visual comparisons. Penalize grain, sparkles, and flicker explicitly rather than letting average blur metrics hide them. Never invent missing GPU, performance, build, or gameplay results.

Return `REPORT.md`, `RESULT.json`, `tests/`, exact runnable commands, candidate source, evidence and hashes, and `GPU_REQUEST.json` as prescribed by [RETURN_PROTOCOL](../RETURN_PROTOCOL.md). Include `BLOCKED_DATA_REQUEST.json` when necessary. Its content must identify the missing observation, hypotheses it distinguishes, exact requested tensors/metadata, units, frames and crop, provenance requirements, size estimate, and what useful work you completed without it; include the protocol's required fields. A data request must be surgical, not “upload everything.” Report rejection and uncertainty honestly.

Commit the reproducible work and open a PR to `sol/26-integration` if authenticated access is available. Otherwise return a ZIP containing the source, tests, evidence, commit IDs, binary patch or unified diff, and application instructions. Do not fabricate a PR link. Your recommendation must say ship as default-off A/B, keep as research, or reject, with the measured trade-off and the remaining local GPU/game gate. Write the final user-facing delivery summary in plain Turkish; technical documentation and source comments may remain English.

## Role and dependency boundary

You are the independent integration and acceptance owner. Jobs01–07 investigate different mechanisms and return candidate code/CPU tests plus scoped adapter patches. You may build harnesses, audit the baseline and define acceptance now. You cannot claim final integration, final quality, or “all issues fixed” before the relevant candidate PRs/results arrive and the required local GPU/game verdicts exist. Missing dependencies are an explicit partial/blocked status, not permission to invent validation.

Create `astra/08-integration-acceptance` from the immutable handoff tag. Your candidate directory is `research/astra20261020/candidates/08-integration-acceptance/`. You alone own applying selected production adapters in your integration branch. Do not auto-merge contributor PRs. Pin each input PR/head SHA and reviewed patch; keep research candidates and rejected methods visible. The production PR still targets `sol/26-integration`.

Read the full package protocols and audit the real source paths, especially:
- `OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.cpp`, `FSRDNrdBridgeRR_Dx12.{h,cpp}`, `FSRDNrdPostMotionAnchor_Dx12.h`, `FSRDNrdFlatAlbedoRecovery_Dx12.h`, `FSRDNrdLobeRecovery_Dx12.h`, `FSRDNrdLightingGuard_Dx12.h`, and `FSRDRadianceScale_Dx12.h`.
- `FSRDGameTraceSession.{h,cpp}`, `FSRDGameTraceBridgeMetadata.h`, shared anchor/colour constant headers, actual HLSL, generated headers/CSOs, and `shader_tools/build_fsrd_shader.py`.
- `OptiScaler/misc/RecordedComputeLease_Dx12.h`, capture-slot budget/owned-resource helpers, native submission/retirement and resource tracking callers.
- Existing tests named `fsrd_native_post_motion_anchor`, `fsrd_nrd_anchor_shared_family`, `fsrd_nrd_game_trace_bridge`, `fsrd_nrd_native_transactions`, flat-albedo/owned-output fixtures, their Python drivers and shader artifact contracts. Verify exact filenames; Windows GPU drivers are not portable CPU tests.

## Baseline facts that acceptance must protect

The old combined preprocessor hooks did not reach the user's native RR-only path. Task26 connects native anchor, but native ColourTrack/PostFlick are not automatically present. A shader-only test or mock selected-sentinel helper cannot establish that an actual Config option changes provider/commit inputs in the native caller.

Native anchor corrects private physical input copies before optional turn filters/radiance scaling and provider work. Recovery/NZR must consume the same corrected physical pair. G3 lighting validation intentionally measures original physical game inputs so anchor's varying gain does not fool the detector. Captured physical input stage is labelled after anchor but before optional turn filters/scaling; do not claim exact final provider inputs when legacy turn filters are enabled unless separately captured.

Native output commit consumes both selected resource pointers and slot SRV descriptors. A pointer-only change can leave the provider/commit reading old resources. Leases must retain transformed resources and descriptor/constant owners through actual submit/fence/retirement. Prepare should complete fallible allocation/descriptors before irreversible provider/suppression work.

The native family gate in both coordinator paths must include effective anchor as well as the existing lobe condition. This prevents anchor-only HistoryDomains from each escaping into a private2GiB budget. Preserve initial all-OFF behavior and do not casually broaden unrelated Flat-only policy. Shared accounting includes retained old graphs/slots; an allocation number is not resident VRAM.

## Competing failure hypotheses and discriminators

1. A candidate is correct mathematically but disconnected or overwritten in a real native route. Test exact call order, producer/consumer resource identity and a nontrivial sentinel; a source-name search is insufficient.
2. Numeric/ABI disagreement corrupts the candidate. Distinguish struct layout, constant offsets, typed formats, root slots, dimensions, store semantics and sampler assumptions from algorithm quality using job01's contracts.
3. CPU history publication assumes GPU commands executed. Distinguish prepared, recorded, submitted, completed, reset, discarded and retired states; cancellation followed by reuse must not read unwritten history.
4. Aliased/shared resources outlive or overwrite the wrong snapshot. Distinguish owner retention from content immutability; a retained pointer can still hold a later frame. Trace timing and the native transaction lock matter.
5. A metric or fixture falsely accepts quality. Use known rejected candidates, raw-RR nulls, unchanged-pixel controls, phase-shifted boundaries, true-light interventions and the user's preserved baseline to calibrate acceptance.

An independent skeptical subagent must own adversarial cases and review claims without accepting an implementation author's summary as proof.

## Cloud CPU work you must implement

Build a reproducible acceptance registry and portable tests that run through the package CPU entry point or clearly documented candidate command. Verify source/CSO/header hashes and canonical generated-header payloads from the tagged artifacts; do not import historical hashes from another DXC version. Any optional Linux shader compile is a build result only, not GPU execution.

Implement useful ABI/graph checks: named resource roles and formats; active versus allocation dimensions; constant packing/alignment and overlap; descriptor counts/root slots; buffer size/reset coverage; required barriers and final states; physical/radiance scale domains; alpha preservation; option OFF/zero-strength transitions; and trace image planning/accounting. A source assertion that merely mirrors a new line of implementation is weak. Pair structural checks with executable dataflow/state-machine mutants that should fail, and clearly label the boundary between portable modeling and actual Windows/D3D ABI proof.

Model retained graph/slot accounting across multiple domains, replacement contexts, in-flight recordings, prepare failure, cancelled/never-submitted work and completion. Use overflow-safe arithmetic, the actual shared limits and adversarial allocation pressure. Do not allocate2GiB in cloud just to simulate a cap. Ensure pressure tests exercise admission/retirement logic rather than only a copied constant.

For trace contracts, test active-only gain publication, its own floor(render/8) extent/crop0 independent of main ROI, corrected physical input selection, precise stage metadata, hashes/lineage, per-image payload versus committed readback bytes and preflight before recording. Inactive anchor must add no gain image. Glass active mode/strength must change settings lineage while all-OFF metadata remains stable. Respect actual allowed ROI sizes and schemas.

Maintain an OFF/golden plan and mutation suite. Required mutants include forced option OFF despite requested ON, selected-pointer-only update, stale descriptors, missing owner retention, premature history publication, incomplete sums reset, lost high word, per-wrapper family escape, wrong dimensions/crop, omitted optional image budget, and wrong trace stage. State which are modeled in cloud and which require the local native GPU fixture.

## Candidate integration and quality acceptance

For every job, require a short mechanism claim, unique falsifier, baseline calibration, implementation and executable tests, changed source/ABI/state, fixed-mask result population, rejected alternatives, data limitations and GPU request. Do not merge an attractive candidate that fails the known bad-control calibration. Preserve D16/S256+G2/G3, NZR TemporalOFF, RRFallback/DiffuseRR/ReflectionHistory and Glass Blend.5 comparison unless a separate explicit experimental branch justifies a change.

Review cross-feature ordering, support/authority semantics and units. In particular, native lobe alpha is not combined Skip authority, protected NZR pixels must not be recoloured, and per-lobe luminance conservation is not final-game remodulation proof. Transport confidence and estimator confidence must not silently multiply away all correction and then claim reduced artifacts as a win.

Select only defensible candidates and apply minimal default-off production adapters in your branch. Keep independent toggles and exact OFF behavior. Build a compatibility matrix based on actual dependencies, not an exponential checkbox exercise. Review memory lifetime and budgets before requesting local GPU work.

## Local gate and final return

Produce a concrete `GPU_REQUEST.json` with source/patch hashes, exact builds/CSOs, native Config-to-provider/commit canaries, negative mutants, debug-layer expectations, reset/gap/DRS/discard/submission sequences, independent per-lobe scaling, shared-domain budget checks and correct trace witnesses. Quality requests must be fresh chronological AMD RR and same-crop game A/B, include moderate known light steps, shifted boundaries, moving bottle/foliage and protected glass/text controls, and use immutable BASE masks. Timings require warmed paired/reversed-order and sham controls; CPU/cloud cannot certify real GPU milliseconds or resident VRAM.

Return a dependency/status manifest for all jobs01–07 and separate statuses for code integrated, CPU passed, local native GPU mechanics passed, fresh AMD RR quality passed and user game verdict. If results or local verdicts are absent, stop the claim at the level actually reached and leave a precise runnable handoff. Your PR may contain a reviewable integration candidate without claiming acceptance. Never call an unexecuted test passed or a missing reviewer approved.
