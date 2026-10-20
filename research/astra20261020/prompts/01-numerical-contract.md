# Astra Pro job 01: portable CPU/HLSL numerical and sampling contracts

You are the implementation and research owner for this workstream. The user explicitly wants sustained, rigorous engineering with code, CPU experiments, and specialized subagents. A survey, a plausible shader, or a promising aggregate score is not a completed job. Find a mechanism, build the smallest experiment that separates competing explanations, implement the strongest falsifiable candidate, and have an independent skeptical agent try to break it. A well demonstrated negative result plus useful diagnostic code is a valid deliverable. Do not pad work with minimum hours, minimum experiment counts, or arbitrary complexity.

## Checkout, authority, and working boundary

Repository: https://github.com/burak113/OptiScaler . Open the actual tagged entry document at https://github.com/burak113/OptiScaler/blob/astra-handoff-20261020/research/astra20261020/START_HERE.md ; the repository default branch is not this handoff. Fetch tags and check out the immutable tag `astra-handoff-20261020`, then create your own branch `astra/01-numerical-contract`. Record the resolved tag commit. The audited production baseline is `87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`; the handoff tag may additionally contain the research package, so do not assume these two commit IDs are identical. Start from the tag, not an evolving branch or somebody else's candidate. Your eventual PR targets `sol/26-integration`; never enable auto-merge or merge a PR yourself.

First read [START_HERE](../START_HERE.md), [COMMON_PROTOCOL](../COMMON_PROTOCOL.md), and [RETURN_PROTOCOL](../RETURN_PROTOCOL.md), then inventory `research/astra20261020/portable/anchor`, `portable/colour`, and `fixtures/clips`. The CPU entry point is `python research/astra20261020/run_cpu.py`; run it before changes and preserve its output. Follow the package's actual dependency instructions. Inventory what data really exists, its units, masks, chronology, hashes, and provenance. Raw full captures, local project memory, the game, Windows-only GPU drivers, and AMD RR execution are not promised in this cloud package. A stored GPU result is a calibration witness, not a GPU you can rerun.

All your candidate code, tests, measurements, images, and proposed adapter belong under `research/astra20261020/candidates/01-numerical-contract/`. Jobs 01–07 must keep production files and the packaged baseline references unchanged: supply a narrowly scoped `adapter/PRODUCTION.patch` or exact adapter specification for job 08. Job 08 owns applying production changes in its integration branch after the dependency and local acceptance requirements are met. Preserve source line endings in patches, keep new experiments default-off, and protect the user's working baseline. Do not install a DLL into a game, edit secrets, or rewrite shared memory.

Use parallel subagents with explicit boundaries: at least a mechanism/representation investigator, an implementation/testing owner, and a skeptical independent reviewer. They may be the same number of available agents as your environment supports, but the skepticism must be independent of candidate tuning. Make the reviewer reproduce a known bad control before seeing your claimed win. Coordinate with other jobs through documented interfaces and artifacts; do not modify their folders or depend on their uncommitted files.

Known clip inventory: `fixtures/clips/bottle_track7.npz` contains frames180–186 in a moving 128x256 crop; `fixtures/clips/foliage23.npz` contains 87ee frames43–65 in a192x64 crop; `fixtures/clips/facade16.npz` contains f2ef frames34–49 in a96x96 crop. These are partial histories and omit albedo. Read their manifests and per-frame crop provenance: a moving crop is not camera/object motion, and these short windows cannot reconstruct unseen prior history. Inspect `fixtures/glass/` and its manifest if present for the aligned glass subset; do not assume all clips have all signal roles. Load NPZ with `allow_pickle=False`.

## Evidence and return contract

Use immutable BASE-derived masks and denominators; do not recompute the evaluation region from a modified candidate. Preserve chronological, unlooped sequences and report unsupported history/crop regions. Separate analytic truth, synthetic interventions, recorded GPU calibration, CPU model results, actual GPU execution, AMD RR output, and final game observation. None substitutes for another. Match crop, aspect, exposure, and frame timing in visual comparisons. Penalize grain, sparkles, and flicker explicitly rather than letting average blur metrics hide them. Never invent missing GPU, performance, build, or gameplay results.

Return `REPORT.md`, `RESULT.json`, `tests/`, exact runnable commands, candidate source, evidence and hashes, and `GPU_REQUEST.json` as prescribed by [RETURN_PROTOCOL](../RETURN_PROTOCOL.md). Include `BLOCKED_DATA_REQUEST.json` when necessary. Its content must identify the missing observation, hypotheses it distinguishes, exact requested tensors/metadata, units, frames and crop, provenance requirements, size estimate, and what useful work you completed without it; include the protocol's required fields. A data request must be surgical, not “upload everything.” Report rejection and uncertainty honestly.

Commit the reproducible work and open a PR to `sol/26-integration` if authenticated access is available. Otherwise return a ZIP containing the source, tests, evidence, commit IDs, binary patch or unified diff, and application instructions. Do not fabricate a PR link. Your recommendation must say ship as default-off A/B, keep as research, or reject, with the measured trade-off and the remaining local GPU/game gate. Write the final user-facing delivery summary in plain Turkish; technical documentation and source comments may remain English.

## Concrete problem

The existing portable models are useful but not universally GPU-equivalent. The colour package explicitly preserves an ideal continuous CPU bilinear sampler. A recorded GPU comparison found that a 1/256 interpolation-fraction model changed strict depth-validity decisions and reproduced decisions that ideal bilinear missed; this is an audited-device observation, not a universal graphics API guarantee. Some fixture RGB values are already RTZ FP16-expanded, while an older expected output used pre-UAV float32 low bits that were not exported. The anchor package stores real GPU grid fields, but its native 16.16 frame ratios are bounded estimates from stored FP16 cells, not exported exact pre-store atomics.

Your job is to turn these caveats into an executable numerical contract and uncertainty envelope. Do not simply tighten a tolerance until the current fixture passes.

Read the production sources before modeling them: `OptiScaler/shaders/fsrd_preprocess/FSRDColourTrackConstants.h`, `FSRDPostMotionAnchorConstants.h`, `precompile/FSRDColourTrack{Stats,Track,Apply}.hlsl`, `precompile/FSRD{,Nrd}PostMotionAnchor{StatsRecall,Gain}.hlsl`, and `precompile/FSRDPostMotionAnchorApply.hlsl`. Brace notation here is a file family to inventory, not a literal filename. Also inspect `shader_tools/build_fsrd_shader.py` and the artifact-contract test; record actual compiler/CSO/header hashes from this tag instead of copying old hashes from historical reports.

## Competing hypotheses to retain

1. Storage conversion, rather than estimator math, causes the important discrepancy. Prediction: injecting the correct typed-UAV conversion at each actual store boundary changes downstream decisions, while a float64 implementation of the same formula does not fix them. Falsify it with a case whose decisions remain wrong under all documented rounding envelopes.
2. Sampler fraction precision and pixel-centre conventions explain the discrepancy. Prediction: the error moves with subpixel phase and is concentrated near hard validity thresholds; a sampler-free integer-load version removes that phase pattern. A constant-field or texel-centre case must remain invariant.
3. Guide encoding is the dominant source. Prediction: old normal packing loses information after FP16 storage, whereas every code of the audited 11-bit packing survives the store; guide decisions track angular/quantization error rather than only RGB error.
4. Missing pre-store bits make exact output reconstruction unidentifiable. Prediction: two pre-store inputs consistent with the exported rounded tensor lead to distinct valid results. Produce this witness instead of falsely declaring one rounded CPU output “the GPU truth.”

Write predictions and falsifiers before tuning. Let the adversary choose boundary inputs.

## Required implementation

Build a small standalone Python/NumPy contract library inside your candidate folder, with named, tested operations for storage, arithmetic staging, integer conversion, normal encoding, texture loads, normalized-UV sampling, and coordinate transforms. Keep “ideal mathematical,” “documented HLSL/API,” and “observed-device emulation” modes separate. Do not silently alter the frozen portable reference to make it look exact.

Test RTZ versus round-to-nearest-even FP16, including positive and negative values, signed zero, subnormals, halfway cases, finite saturation, and the source's actual treatment of NaN/Inf. Do not assume all shader conversions or all hardware stores use the same rule; establish which source boundary and witness support each model. Quantize only where the actual graph stores or casts. Record whether intermediate expressions are float32, half, integer, or a compiler-dependent fused expression.

Verify the audited packing `qx in [0,63], qy in [0,31], code=qx*32+qy`: all 2048 integer codes must round-trip through FP16 exactly. Check decoded normals, octahedral fold/hemisphere boundaries, degenerate vectors, and distinct encodings that happen to decode similarly. Preserve old broken packing as a negative control.

Implement point, integer Load, and bilinear sampling with explicit pixel-centre and normalized-UV conventions, dimensions, active extent versus allocation extent, addressing policy, and selectable fraction quantization. Test 1x1, odd extents, max allocation larger than active render, quarter/eighth-resolution fields, partial crops, and all edge/corner cases. Do not turn absent off-crop observations into valid samples by clamping.

Model emulated uint64 16.16 sums exactly: low-word addition, carry, high-word composition, count support, cap16 physical units, and full 32-byte reset. Compare exact integer totals, float reconstruction, and bounds caused by absent pre-store bits. Include natural and adversarial multiple wraps; do not only test tiny non-overflow totals.

## Calibration and adversarial acceptance

Run the packaged baseline first. Reproduce its documented numerical gaps as passing diagnostic tests: explain which comparisons are exact, bounded, or non-identifiable. Compare intermediate stats/history/gain/validity separately; an output-only tolerance can conceal a wrong branch. A test that should reject an impossible exact reconstruction must actually reject it.

Use exhaustive small discrete spaces where practical and seeded property tests elsewhere. Required metamorphic checks include constant-field sampling identity, integer-translation equivalence away from boundaries, exact pack/unpack closure, independent lobe/channel handling, reset clearing every byte, and unchanged behavior when an inactive option's unused values change. Deliberately wrong UV scaling, nearest sampling, old normal packing, missing high word, and premature rounding should each fail a relevant invariant.

Use the same executable inputs to compare ideal, source-shaped, and observed-device modes. Report max/percentile error and changed decision count on a fixed population; do not report only an attractive mean. Keep a machine-readable list of unresolved hardware assumptions.

## Handoff boundary

Provide a reusable contract API for jobs 02–04 and 08, with examples and a version/hash. Do not force them to wait before they build their own discriminating experiments; they must record which contract version they use. Your adapter patch should be limited to justified numerical/encoding fixes, each tied to a falsifier. No new denoising policy belongs in this job.

The local GPU request must contain exact source-shaped microcases, typed resource formats, shader/host call order, expected intermediate bytes or uncertainty intervals, and a negative mutant. A CPU pass is necessary evidence for a candidate, not proof of DXC code generation, a sampler implementation, or the game's final image.
