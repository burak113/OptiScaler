# Astra Pro job 04: geometric temporal transport and boundary-safe reconstruction

You are the implementation and research owner for this workstream. The user explicitly wants sustained, rigorous engineering with code, CPU experiments, and specialized subagents. A survey, a plausible shader, or a promising aggregate score is not a completed job. Find a mechanism, build the smallest experiment that separates competing explanations, implement the strongest falsifiable candidate, and have an independent skeptical agent try to break it. A well demonstrated negative result plus useful diagnostic code is a valid deliverable. Do not pad work with minimum hours, minimum experiment counts, or arbitrary complexity.

## Checkout, authority, and working boundary

Repository: https://github.com/burak113/OptiScaler . Open the actual tagged entry document at https://github.com/burak113/OptiScaler/blob/astra-handoff-20261020/research/astra20261020/START_HERE.md ; the repository default branch is not this handoff. Fetch tags and check out the immutable tag `astra-handoff-20261020`, then create your own branch `astra/04-geometry-transport`. Record the resolved tag commit. The audited production baseline is `87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`; the handoff tag may additionally contain the research package, so do not assume these two commit IDs are identical. Start from the tag, not an evolving branch or somebody else's candidate. Your eventual PR targets `sol/26-integration`; never enable auto-merge or merge a PR yourself.

First read [START_HERE](../START_HERE.md), [COMMON_PROTOCOL](../COMMON_PROTOCOL.md), and [RETURN_PROTOCOL](../RETURN_PROTOCOL.md), then inventory `research/astra20261020/portable/anchor`, `portable/colour`, and `fixtures/clips`. The CPU entry point is `python research/astra20261020/run_cpu.py`; run it before changes and preserve its output. Follow the package's actual dependency instructions. Inventory what data really exists, its units, masks, chronology, hashes, and provenance. Raw full captures, local project memory, the game, Windows-only GPU drivers, and AMD RR execution are not promised in this cloud package. A stored GPU result is a calibration witness, not a GPU you can rerun.

All your candidate code, tests, measurements, images, and proposed adapter belong under `research/astra20261020/candidates/04-geometry-transport/`. Jobs 01–07 must keep production files and the packaged baseline references unchanged: supply a narrowly scoped `adapter/PRODUCTION.patch` or exact adapter specification for job 08. Job 08 owns applying production changes in its integration branch after the dependency and local acceptance requirements are met. Preserve source line endings in patches, keep new experiments default-off, and protect the user's working baseline. Do not install a DLL into a game, edit secrets, or rewrite shared memory.

Use parallel subagents with explicit boundaries: at least a mechanism/representation investigator, an implementation/testing owner, and a skeptical independent reviewer. They may be the same number of available agents as your environment supports, but the skepticism must be independent of candidate tuning. Make the reviewer reproduce a known bad control before seeing your claimed win. Coordinate with other jobs through documented interfaces and artifacts; do not modify their folders or depend on their uncommitted files.

Known clip inventory: `fixtures/clips/bottle_track7.npz` contains frames180–186 in a moving 128x256 crop; `fixtures/clips/foliage23.npz` contains 87ee frames43–65 in a192x64 crop; `fixtures/clips/facade16.npz` contains f2ef frames34–49 in a96x96 crop. These are partial histories and omit albedo. Read their manifests and per-frame crop provenance: a moving crop is not camera/object motion, and these short windows cannot reconstruct unseen prior history. Inspect `fixtures/glass/` and its manifest if present for the aligned glass subset; do not assume all clips have all signal roles. Load NPZ with `allow_pickle=False`.

## Evidence and return contract

Use immutable BASE-derived masks and denominators; do not recompute the evaluation region from a modified candidate. Preserve chronological, unlooped sequences and report unsupported history/crop regions. Separate analytic truth, synthetic interventions, recorded GPU calibration, CPU model results, actual GPU execution, AMD RR output, and final game observation. None substitutes for another. Match crop, aspect, exposure, and frame timing in visual comparisons. Penalize grain, sparkles, and flicker explicitly rather than letting average blur metrics hide them. Never invent missing GPU, performance, build, or gameplay results.

Return `REPORT.md`, `RESULT.json`, `tests/`, exact runnable commands, candidate source, evidence and hashes, and `GPU_REQUEST.json` as prescribed by [RETURN_PROTOCOL](../RETURN_PROTOCOL.md). Include `BLOCKED_DATA_REQUEST.json` when necessary. Its content must identify the missing observation, hypotheses it distinguishes, exact requested tensors/metadata, units, frames and crop, provenance requirements, size estimate, and what useful work you completed without it; include the protocol's required fields. A data request must be surgical, not “upload everything.” Report rejection and uncertainty honestly.

Commit the reproducible work and open a PR to `sol/26-integration` if authenticated access is available. Otherwise return a ZIP containing the source, tests, evidence, commit IDs, binary patch or unified diff, and application instructions. Do not fabricate a PR link. Your recommendation must say ship as default-off A/B, keep as research, or reject, with the measured trade-off and the remaining local GPU/game gate. Write the final user-facing delivery summary in plain Turkish; technical documentation and source comments may remain English.

## Concrete problem and source map

Transport errors can masquerade as radiance-estimator errors. Coarse cell measurements, recalled keys, full-resolution Apply and crop-rescaled motion all have distinct coordinate systems and support. The native anchor stores absolute key depth, transposes camera matrices into a shared Desc convention, uses a six-key history, and must reset history on invalid previous camera, gaps, cuts and discarded/unsubmitted recording graphs. Do not mix a matrix convention fix with a statistical gain improvement.

Inspect `FSRDPostMotionAnchorConstants.h`, `FSRDNrdPostMotionAnchor_Dx12.h`, both native and combined anchor Stats/Gain shaders, shared Apply, and `FSRDNrdFlatAlbedoRecovery_Dx12.h` plus its History/Accumulate/Select shaders. Read actual fields and constructors; do not infer semantics from a filename. Job01 owns the shared numerical model, job02 the anchor estimator, job03 colour estimation, and job08 host integration.

The anchor export has already-recalled tensors but no raw six-slice key textures. It cannot validate a new capture-derived key selector. Some colour fixtures preserve original-render motion scaling within an ROI-as-screen harness; read their provenance. A crop is not a full screen and its unknown surroundings are not valid edge-clamped history.

## Competing hypotheses with independent predictions

1. Pixel-centre, jitter, UV/pixel, or matrix-transpose errors drive incorrect recall. Prediction: analytic rigid scenes show a deterministic signed phase/scale error independent of noise, even with perfect depth.
2. The coordinates are correct but geometric support is mixed. Prediction: thin/disoccluding objects fail according to cell phase and material coverage, while homogeneous planes remain correct. Changing a single depth threshold cannot solve all orientations.
3. Coarse cells are valid but bilinear gain reconstruction crosses a moving/invalid boundary. Prediction: centre-cell identity tests pass while full-resolution pixels still change; a support-aware reconstruction changes only the boundary band.
4. Specular virtual transport differs from surface transport. Prediction: a reflected feature moves differently from the surface even with correct surface MVs; usable hit distance changes the predicted virtual location. A motion reset or generic roughness inflation can hide the symptom while destroying detail.

Build a coordinate/support ledger before coding: source and destination extent, pixel centres, normalized coordinates, crop origin, jitter convention, motion direction, depth sign/convention, camera matrix handedness, validity support, and interpolation rule for every edge in the graph.

## Required executable model

Implement a standalone CPU transport/reconstruction harness with analytic ground truth, using explicit transforms rather than a black-box image warp. Include projection/unprojection, old/current camera pairs, surface and virtual-point motion, validity/support masks and a partial-observation domain. Matrix convention names must distinguish row/column vector mathematics from CPU memory storage.

Test constant and sloped planes, intersecting surfaces, thin foreground strips, moving objects against a static wall, camera translation and rotation, genuine disocclusion, and an object leaving/entering the captured crop. Include right/left-handed depth conventions and the exact native absolute key-depth behavior. Verify round trips and expected occlusion ordering analytically.

Sweep subpixel phase across the full cell, including phases that were absent from a tuned example. Use horizontal, vertical, diagonal and rotated boundaries, odd extents, 1-pixel features, render sizes not divisible by4/8, max allocations larger than active extents, DRS changes, non-square pixels/aspect changes where meaningful, and partial ROI histories. Unknown support must remain unknown. Do not obtain an apparently valid match by clamping an out-of-crop point onto the nearest observed texel.

Give depth, normal, hit-distance and colour guides separate roles. A guide used to decide correspondence must not be silently replaced by a colour-corrected or reconstructed quantity. Define what happens at invalid normals, zero depth, sky, missing hit distance, and mixed-coverage cells. State whether hit distance is a surface property or a usable reflection-distance observation in each source path.

Implement the strongest boundary-safe reconstruction candidate and, if justified, a transport confidence improvement. Its inactive/unsupported behavior must be explicit: identity, invalid history, partial weighting, or a documented fallback. Compare against ordinary bilinear, hard rejection/gain1, and at least one deliberately wrong coordinate model. A complex joint bilateral filter is not automatically safer if the coarse target has already mixed two surfaces.

## Metrics and acceptance

Use true correspondence error, depth/normal support purity, occlusion leakage, invalid-to-valid conversion rate, gain spill onto protected moving pixels, and detail/edge transfer. Report the worst phase/orientation as well as distribution summaries. Match the correction dose and separate estimator error from reconstruction error through controlled exact-gain and exact-support ablations.

Required negative tests include missing jitter, double jitter, reversed MV direction, render/ROI scaling confusion, transposed transform, signed-depth recall mismatch, allocation/active extent confusion, and out-of-domain clamp. Each must fail a relevant invariant; a test that passes every mutant is not evidence. Check both grid centres and full-resolution output pixels.

Run unlooped synthetic trajectories with reset, frame gap, DRS and option toggle. If you model history, separate “scheduled,” “submitted,” “completed,” and “valid” rather than assuming a CPU record implies a GPU write. Job08 owns the actual lifetime implementation; you must specify its mathematical publication contract.

Use the captured stored fields only for checks they support, such as whether the current confidence rule behaves as documented. Do not present synthetic key transport as a measured improvement on a capture whose original keys are unavailable. If raw keys or camera witnesses are necessary, deliver a precise blocked-data request and keep useful analytic tests and diagnostic visualizations.

## Handoff interface

Provide a documented support/coordinate API reusable by jobs02,03,06,07. Include data types, conventions and tests that consumers can import without Windows or a GPU. Keep production edits as a local adapter patch; do not change another job's estimator or native host.

Your local GPU request must include phase-sweep textures with exact expected support, actual native/combined path labels, current and previous transforms, crop/DRS cases, real sampler witnesses and a point proving that centre-cell safety does not automatically imply pixel safety. Ask for actual native route execution and fresh rendered controls before any game-quality claim.
