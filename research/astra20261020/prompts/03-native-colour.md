# Astra Pro job 03: a noise-aware native colour representation with safe boundaries

You are the implementation and research owner for this workstream. The user explicitly wants sustained, rigorous engineering with code, CPU experiments, and specialized subagents. A survey, a plausible shader, or a promising aggregate score is not a completed job. Find a mechanism, build the smallest experiment that separates competing explanations, implement the strongest falsifiable candidate, and have an independent skeptical agent try to break it. A well demonstrated negative result plus useful diagnostic code is a valid deliverable. Do not pad work with minimum hours, minimum experiment counts, or arbitrary complexity.

## Checkout, authority, and working boundary

Repository: https://github.com/burak113/OptiScaler . Open the actual tagged entry document at https://github.com/burak113/OptiScaler/blob/astra-handoff-20261020/research/astra20261020/START_HERE.md ; the repository default branch is not this handoff. Fetch tags and check out the immutable tag `astra-handoff-20261020`, then create your own branch `astra/03-native-colour`. Record the resolved tag commit. The audited production baseline is `87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`; the handoff tag may additionally contain the research package, so do not assume these two commit IDs are identical. Start from the tag, not an evolving branch or somebody else's candidate. Your eventual PR targets `sol/26-integration`; never enable auto-merge or merge a PR yourself.

First read [START_HERE](../START_HERE.md), [COMMON_PROTOCOL](../COMMON_PROTOCOL.md), and [RETURN_PROTOCOL](../RETURN_PROTOCOL.md), then inventory `research/astra20261020/portable/anchor`, `portable/colour`, and `fixtures/clips`. The CPU entry point is `python research/astra20261020/run_cpu.py`; run it before changes and preserve its output. Follow the package's actual dependency instructions. Inventory what data really exists, its units, masks, chronology, hashes, and provenance. Raw full captures, local project memory, the game, Windows-only GPU drivers, and AMD RR execution are not promised in this cloud package. A stored GPU result is a calibration witness, not a GPU you can rerun.

All your candidate code, tests, measurements, images, and proposed adapter belong under `research/astra20261020/candidates/03-native-colour/`. Jobs 01–07 must keep production files and the packaged baseline references unchanged: supply a narrowly scoped `adapter/PRODUCTION.patch` or exact adapter specification for job 08. Job 08 owns applying production changes in its integration branch after the dependency and local acceptance requirements are met. Preserve source line endings in patches, keep new experiments default-off, and protect the user's working baseline. Do not install a DLL into a game, edit secrets, or rewrite shared memory.

Use parallel subagents with explicit boundaries: at least a mechanism/representation investigator, an implementation/testing owner, and a skeptical independent reviewer. They may be the same number of available agents as your environment supports, but the skepticism must be independent of candidate tuning. Make the reviewer reproduce a known bad control before seeing your claimed win. Coordinate with other jobs through documented interfaces and artifacts; do not modify their folders or depend on their uncommitted files.

Known clip inventory: `fixtures/clips/bottle_track7.npz` contains frames180–186 in a moving 128x256 crop; `fixtures/clips/foliage23.npz` contains 87ee frames43–65 in a192x64 crop; `fixtures/clips/facade16.npz` contains f2ef frames34–49 in a96x96 crop. These are partial histories and omit albedo. Read their manifests and per-frame crop provenance: a moving crop is not camera/object motion, and these short windows cannot reconstruct unseen prior history. Inspect `fixtures/glass/` and its manifest if present for the aligned glass subset; do not assume all clips have all signal roles. Load NPZ with `allow_pickle=False`.

## Evidence and return contract

Use immutable BASE-derived masks and denominators; do not recompute the evaluation region from a modified candidate. Preserve chronological, unlooped sequences and report unsupported history/crop regions. Separate analytic truth, synthetic interventions, recorded GPU calibration, CPU model results, actual GPU execution, AMD RR output, and final game observation. None substitutes for another. Match crop, aspect, exposure, and frame timing in visual comparisons. Penalize grain, sparkles, and flicker explicitly rather than letting average blur metrics hide them. Never invent missing GPU, performance, build, or gameplay results.

Return `REPORT.md`, `RESULT.json`, `tests/`, exact runnable commands, candidate source, evidence and hashes, and `GPU_REQUEST.json` as prescribed by [RETURN_PROTOCOL](../RETURN_PROTOCOL.md). Include `BLOCKED_DATA_REQUEST.json` when necessary. Its content must identify the missing observation, hypotheses it distinguishes, exact requested tensors/metadata, units, frames and crop, provenance requirements, size estimate, and what useful work you completed without it; include the protocol's required fields. A data request must be surgical, not “upload everything.” Report rejection and uncertainty honestly.

Commit the reproducible work and open a PR to `sol/26-integration` if authenticated access is available. Otherwise return a ZIP containing the source, tests, evidence, commit IDs, binary patch or unified diff, and application instructions. Do not fabricate a PR link. Your recommendation must say ship as default-off A/B, keep as research, or reject, with the measured trade-off and the remaining local GPU/game gate. Write the final user-facing delivery summary in plain Turkish; technical documentation and source comments may remain English.

## Concrete problem

The user's pink/chroma trail is still unresolved. Existing combined-path ColourTrack was audited and repaired mechanically, but it is not connected to the native RR-only route. Do not report a combined preprocessor improvement as a native result. Native lighting arrives as separate diffuse/specular physical RGB lobes; capture inputs and raw RR outputs are pre-remodulation signals. The exact game's final albedo remodulation is not proven. Conserving luminance in each lobe does not prove conservation in the displayed composite.

Read `portable/colour/colour_portable.py`, `compare.py`, tests and fixture provenance before experimentation. B4 is the audited CPU baseline. C8/soft2 is explicitly a rejected candidate: favourable selected noise metrics did not survive shifted normal/depth boundary tests. The package contains a controlled frame63 witness with CPU chronological history and a GPU comparison, not a 64-frame GPU replay. Some expected soft2 weights used pre-UAV RGB bits absent from the exported fixture. Respect that uncertainty instead of tuning the last decimal.

Read `FSRDColourTrackConstants.h`, `precompile/FSRDColourTrack{Stats,Track,Apply}.hlsl`, `FSRDNrdBridgeRR_Dx12.cpp`, and `FSRDNrdFlatAlbedoRecovery_Dx12.h`. Native provider normalization and selected-output ordering matter as much as the estimator.

## Competing hypotheses

1. Linear RGB chroma ratios expose sparse heavy-tail estimator noise. A log/variance-stabilizing or low-band representation should reduce false colour gain at a fixed trail-correction strength; it should not require a noisy raw-pixel dark mask.
2. Mixed-material or mixed-normal cells corrupt the low-band target before upsampling. Prediction: changing only the upsampler cannot repair a target already blended across a boundary. Phase-shifted same-luma chroma edges will expose this even with clean guides.
3. A hard bilateral/validity gate makes gain1 discontinuities, adding grain and flicker. Prediction: the artifacts track gate crossings or low weight sums, not the underlying chroma. A confidence blend may help, but must also survive boundary leakage tests.
4. Recolouring the wrong domain or pixels causes the perceived change. Prediction: protecting NZR-selected pixels and treating D/S separately changes where the effect occurs; an aggregate lobe-sum test can hide damage. Incorrect alpha-as-authority semantics may silently disable a native lobe.

Write falsifiers before tuning. Keep representation, target estimation, temporal update, and reconstruction hypotheses distinguishable; do not vary everything at once and attribute the result to your favourite component.

## Protected contracts

Preserve the user's working NZR result. A proposed post-selection native colour apply must leave a lobe/pixel byte-identical when its original selected RGBA differs from raw RR, unless a separately proven reliable recovery mask is supplied. Derive this mask before your pass changes anything. A conservative exact raw-versus-selected gate may exclude other recovery; report eligible coverage instead of hiding it. Do not infer eligibility from rounded candidate output.

Native alpha is hit-distance/other signal data. It is not the combined pipeline's Skip/authority alpha. Binding a native diffuse input with alpha0 as the combined authority texture can make the entire lobe inert. Preserve each alpha word exactly and define authority explicitly. Existing native source ordering and descriptor selection must eventually be handled by job08; this job returns an adapter specification, not an improvised disconnected hook.

Do not add a raw-pixel dark guard simply to hide noisy gains. The audited version increased chroma noise. Do not assume that a smaller aggregate high-frequency score means better detail: pure blur can win that metric.

## Required implementation and experiment

Implement the strongest candidate supported by the evidence, with a CPU model and source-shaped shader/pseudocode. Consider a low-band opponent/log-chroma representation, robust normalized colour statistics with explicit sample support, and separate detail transport. Choose one or two tractable competitors with distinct predictions, then reject the weaker mechanism. Document transform inverses, zero/negative/very-dark handling, scale invariance, clipping, confidence and precision. Declare the target domain per lobe and the preservation property exactly.

Construct seeded, independent-noise sequences with chromatic outliers, repeated low-frequency bias, temporal correlation and occasional true colour changes. Include constant-colour closures; red/blue and green/magenta equal-luminance boundaries; same-depth/different-normal and same-normal/different-depth boundaries; mixed roughness; thin features; and moving boundaries through every relevant subcell phase. Include diagonal and rotated edges, not only a centred vertical edge.

Separate mixed-cell estimation leakage from upsampling leakage. Keep a clean target/dirty upsample ablation and a dirty target/ideal reconstruction ablation. Preserve the old B4 and rejected C8/soft2 cases as calibration controls. The independent reviewer must be able to reproduce the rejection of the known bad boundary method before scoring yours. Job01's observed-device sampler model can inform this test, but it must not be silently treated as a universal GPU sampler.

Evaluate chroma error and temporal chroma-HF on immutable BASE masks, low-band trail correction, luminance error in the explicitly stated domain, spatial edge transfer, detail contrast, and maximum boundary contamination across phases. Report per-lobe and protected/eligible pixel subsets. Use image panels with matched crop/exposure and time plots; leave final-game remodulation explicitly unknown.

If the packaged data cannot establish temporal improvement, make your candidate pass a synthetic truth suite and return an exact request for chronological raw D/S inputs, raw RR, selected RR, geometry and calibrated final output. Do not label the single frame witness a temporal validation.

## Return and integration interface

Define a small per-lobe interface: required inputs and units; writable outputs; alpha preservation; mask authority; active/max extent; history contents and reset conditions; memory footprint and pass count estimates clearly labelled analytic. No cloud GPU timing or VRAM number may be invented.

Your adapter patch must name a safe before-commit insertion point and how both selected pointers and SRV descriptors/retained owners will be updated, while leaving production application to job08. New native colour remains default-off. Ask local validation for an actual native ON canary, protected NZR byte checks, all-phase GPU boundary tests, unlooped fresh AMD RR quality, and final same-crop game observation. A rejected candidate with a better calibrated portable benchmark is preferable to another apparently successful leakage filter.
