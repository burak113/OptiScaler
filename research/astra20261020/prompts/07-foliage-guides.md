# Astra Pro job 07: mixed-coverage foliage guides without false material semantics

You are the implementation and research owner for this workstream. The user explicitly wants sustained, rigorous engineering with code, CPU experiments, and specialized subagents. A survey, a plausible shader, or a promising aggregate score is not a completed job. Find a mechanism, build the smallest experiment that separates competing explanations, implement the strongest falsifiable candidate, and have an independent skeptical agent try to break it. A well demonstrated negative result plus useful diagnostic code is a valid deliverable. Do not pad work with minimum hours, minimum experiment counts, or arbitrary complexity.

## Checkout, authority, and working boundary

Repository: https://github.com/burak113/OptiScaler . Open the actual tagged entry document at https://github.com/burak113/OptiScaler/blob/astra-handoff-20261020/research/astra20261020/START_HERE.md ; the repository default branch is not this handoff. Fetch tags and check out the immutable tag `astra-handoff-20261020`, then create your own branch `astra/07-foliage-guides`. Record the resolved tag commit. The audited production baseline is `87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`; the handoff tag may additionally contain the research package, so do not assume these two commit IDs are identical. Start from the tag, not an evolving branch or somebody else's candidate. Your eventual PR targets `sol/26-integration`; never enable auto-merge or merge a PR yourself.

First read [START_HERE](../START_HERE.md), [COMMON_PROTOCOL](../COMMON_PROTOCOL.md), and [RETURN_PROTOCOL](../RETURN_PROTOCOL.md), then inventory `research/astra20261020/portable/anchor`, `portable/colour`, and `fixtures/clips`. The CPU entry point is `python research/astra20261020/run_cpu.py`; run it before changes and preserve its output. Follow the package's actual dependency instructions. Inventory what data really exists, its units, masks, chronology, hashes, and provenance. Raw full captures, local project memory, the game, Windows-only GPU drivers, and AMD RR execution are not promised in this cloud package. A stored GPU result is a calibration witness, not a GPU you can rerun.

All your candidate code, tests, measurements, images, and proposed adapter belong under `research/astra20261020/candidates/07-foliage-guides/`. Jobs 01–07 must keep production files and the packaged baseline references unchanged: supply a narrowly scoped `adapter/PRODUCTION.patch` or exact adapter specification for job 08. Job 08 owns applying production changes in its integration branch after the dependency and local acceptance requirements are met. Preserve source line endings in patches, keep new experiments default-off, and protect the user's working baseline. Do not install a DLL into a game, edit secrets, or rewrite shared memory.

Use parallel subagents with explicit boundaries: at least a mechanism/representation investigator, an implementation/testing owner, and a skeptical independent reviewer. They may be the same number of available agents as your environment supports, but the skepticism must be independent of candidate tuning. Make the reviewer reproduce a known bad control before seeing your claimed win. Coordinate with other jobs through documented interfaces and artifacts; do not modify their folders or depend on their uncommitted files.

Known clip inventory: `fixtures/clips/bottle_track7.npz` contains frames180–186 in a moving 128x256 crop; `fixtures/clips/foliage23.npz` contains 87ee frames43–65 in a192x64 crop; `fixtures/clips/facade16.npz` contains f2ef frames34–49 in a96x96 crop. These are partial histories and omit albedo. Read their manifests and per-frame crop provenance: a moving crop is not camera/object motion, and these short windows cannot reconstruct unseen prior history. Inspect `fixtures/glass/` and its manifest if present for the aligned glass subset; do not assume all clips have all signal roles. Load NPZ with `allow_pickle=False`.

## Evidence and return contract

Use immutable BASE-derived masks and denominators; do not recompute the evaluation region from a modified candidate. Preserve chronological, unlooped sequences and report unsupported history/crop regions. Separate analytic truth, synthetic interventions, recorded GPU calibration, CPU model results, actual GPU execution, AMD RR output, and final game observation. None substitutes for another. Match crop, aspect, exposure, and frame timing in visual comparisons. Penalize grain, sparkles, and flicker explicitly rather than letting average blur metrics hide them. Never invent missing GPU, performance, build, or gameplay results.

Return `REPORT.md`, `RESULT.json`, `tests/`, exact runnable commands, candidate source, evidence and hashes, and `GPU_REQUEST.json` as prescribed by [RETURN_PROTOCOL](../RETURN_PROTOCOL.md). Include `BLOCKED_DATA_REQUEST.json` when necessary. Its content must identify the missing observation, hypotheses it distinguishes, exact requested tensors/metadata, units, frames and crop, provenance requirements, size estimate, and what useful work you completed without it; include the protocol's required fields. A data request must be surgical, not “upload everything.” Report rejection and uncertainty honestly.

Commit the reproducible work and open a PR to `sol/26-integration` if authenticated access is available. Otherwise return a ZIP containing the source, tests, evidence, commit IDs, binary patch or unified diff, and application instructions. Do not fabricate a PR link. Your recommendation must say ship as default-off A/B, keep as research, or reject, with the measured trade-off and the remaining local GPU/game gate. Write the final user-facing delivery summary in plain Turkish; technical documentation and source comments may remain English.

## Concrete problem and protected controls

Foliage may present several surfaces/coverage states within a pixel or coarse cell, while the denoiser receives a single normal, depth, material guide and motion. Treat this representational mismatch as a hypothesis to test. It is not permission to flatten normals, label vegetation with a fake material ID, or borrow semantic meaning that the native encoding has not proven.

Earlier normal-guide modifications lost substantial detail in facade controls. That failure is a mandatory calibration case, not a reason to lower the standard until a foliage crop wins. The user's working D16/S256+G2/G3 and NZR settings remain protected. A foliage method must survive rigid facade/window/text controls, sky boundaries, moving people/bottle and glass/reflections where data permits.

Read the native geometry/material pipeline reachable from `FSRDNrdBridge_Dx12.cpp`, including `precompile/FSRDNrdBridgeGeometryMaterial*.hlsl`, `FSRDNrdBridgeMaterial*.hlsl`, `FSRDNrdMaterialGuides.hlsli`, `FSRDNrdMaterialQuantization.hlsli`, and actual callers. Inspect `FSRDNrdBridgeRR_Dx12.cpp`, `FSRDNrdLightingGuard_Dx12.h` and the trace schema. Do not infer material ID semantics from a visually convenient integer range; trace encoding and preservation flags first.

## Inventory and evidence boundary

List what `fixtures/clips` and the portable data actually provide: rendered videos, source guides, lobe inputs, output tensors, timestamps, camera metadata, semantic labels or none. Keep label provenance explicit. If no raw foliage guide sequence is included, you can build a rigorous mixed-coverage benchmark and a diagnostic candidate, but cannot claim a captured foliage improvement.

Create immutable BASE-derived masks before looking at candidate results. For real clips these may be manual fixed regions plus uncertainty bands; for synthetic scenes use known geometry/coverage truth. Never derive a “foliage mask” from a candidate-smoothed normal or modified material ID and then evaluate only those pixels.

## Competing hypotheses

1. Coverage mixture/jitter changes which surface dominates the guide, while lighting integrates several surfaces. Prediction: guide variation correlates with known coverage mixtures and subpixel phase even with fixed underlying surfaces; a single deterministic normal is insufficient.
2. Guide decoding or quantization is wrong. Prediction: homogeneous known-normal surfaces show systematic disagreement independent of foliage coverage. Correcting numerical contracts should fix these controls before any temporal smoothing.
3. Geometry guides are valid but current lighting is sparse/heavy-tailed or strongly correlated. Prediction: guide stabilization does little when the same guide is paired with a different lighting distribution, and changing lighting statistics alters flicker without changing coverage.
4. MVs transport only one layer or coverage state. Prediction: analytically correct per-layer motion still disagrees with a single-layer composite; ordinary history clamping may hide the ambiguity while smearing the facade control.
5. The perceived benefit is just detail destruction. Prediction: a normal-flattening or blur control wins a coarse flicker metric while failing texture/edge-transfer tests. Your scoring must reject that control.

State falsifiers and the extra observation each hypothesis needs. Keep decode, representation, transport and estimator effects distinguishable.

## Required implementation

Build a CPU generator of layered thin geometry with known visibility/coverage: leaves or cards crossing a textured background, alpha-tested/stochastic coverage variants where justified, subpixel jitter, camera/object motion, and per-layer normals/depth/material/motion. Generate both physically interpretable aggregated lighting and several plausible single-guide observations. Mark these constructions synthetic; do not assert the game uses a particular coverage rule without evidence.

Sweep leaf thickness, orientation, overlap, coverage fraction, guide quantization, motion difference and noise temporal correlation. Include static and moving rigid facades with fine texture, window frames, sky gaps and near/far depth boundaries. Build cases with identical aggregated guides but different underlying mixtures to expose identifiability limits.

Implement the strongest mechanism-supported candidate or diagnostic representation. Possible directions are guide uncertainty/coherence moments, mixture-support confidence, a conservative confidence downgrade limited to unreliable evidence, or a representation that keeps dominant geometry and residual coverage distinct. Define the observable used; do not hallucinate access to per-sample game data. If a production API cannot convey the needed quantity, return a narrow input-side adapter plan or a diagnostic, not a fake semantic channel.

Keep material IDs, roughness, normal/depth and hit-distance meanings unchanged unless source evidence proves a valid transformation. Preserve alpha and raw signal units. No global normal flattening, sky tagging or arbitrary hard material class should be smuggled into an “uncertainty” candidate.

## Metrics, ablations and falsifiers

Report grain/sparkle/flicker, coverage/edge fidelity, detail contrast, false history support, leakage across layers, and motion/true-light response. Use fixed masks and weights that visibly penalize sparkle and texture loss; do not let a smoother output erase the error denominator. Evaluate phase/orientation worst cases and held-out trajectories/noise seeds, not only a stable centred leaf.

Required ablations include exact/perfect guides, single dominant guide, deliberately misdecoded normals, flattened normals, fixed versus moving coverage, independent versus correlated lighting noise, and oracle per-layer motion. Freeze one variable family at a time. The independent reviewer must reproduce the facade detail failure of a blunt guide-smoothing control before judging your candidate.

Where package data supports a recorded comparison, show original BASE/candidate crops with identical aspect/exposure and clear stage labels. Report whether a guide-domain metric is only a proxy for output. A CPU mixture benchmark is not AMD RR output, and a rendered clip without raw guides cannot verify your causal model.

## Handoff and local GPU gate

Provide a small interface for guide uncertainty/support that job04 can transport and job08 can integrate, with no modification to other workstreams. Keep the production adapter scoped to your candidate folder and default-off. Include fallback identity/unchanged behavior when confidence is unsupported.

If blocked, request exact chronological raw guides, unmodified physical D/S, raw and selected RR, camera/MV conventions, relevant material encoding witnesses and fixed-view/known-motion controls. Explain how the request distinguishes mixed coverage from a decoding or lighting problem. Local acceptance must include actual native GPU execution, fixed original masks, the historical facade/text controls and final visual video. Do not call foliage solved before these pass.
