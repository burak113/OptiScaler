# Astra Pro job 02: native anchor estimation under sparse heavy tails and genuine illumination change

You are the implementation and research owner for this workstream. The user explicitly wants sustained, rigorous engineering with code, CPU experiments, and specialized subagents. A survey, a plausible shader, or a promising aggregate score is not a completed job. Find a mechanism, build the smallest experiment that separates competing explanations, implement the strongest falsifiable candidate, and have an independent skeptical agent try to break it. A well demonstrated negative result plus useful diagnostic code is a valid deliverable. Do not pad work with minimum hours, minimum experiment counts, or arbitrary complexity.

## Checkout, authority, and working boundary

Repository: https://github.com/burak113/OptiScaler . Open the actual tagged entry document at https://github.com/burak113/OptiScaler/blob/astra-handoff-20261020/research/astra20261020/START_HERE.md ; the repository default branch is not this handoff. Fetch tags and check out the immutable tag `astra-handoff-20261020`, then create your own branch `astra/02-anchor-estimator`. Record the resolved tag commit. The audited production baseline is `87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`; the handoff tag may additionally contain the research package, so do not assume these two commit IDs are identical. Start from the tag, not an evolving branch or somebody else's candidate. Your eventual PR targets `sol/26-integration`; never enable auto-merge or merge a PR yourself.

First read [START_HERE](../START_HERE.md), [COMMON_PROTOCOL](../COMMON_PROTOCOL.md), and [RETURN_PROTOCOL](../RETURN_PROTOCOL.md), then inventory `research/astra20261020/portable/anchor`, `portable/colour`, and `fixtures/clips`. The CPU entry point is `python research/astra20261020/run_cpu.py`; run it before changes and preserve its output. Follow the package's actual dependency instructions. Inventory what data really exists, its units, masks, chronology, hashes, and provenance. Raw full captures, local project memory, the game, Windows-only GPU drivers, and AMD RR execution are not promised in this cloud package. A stored GPU result is a calibration witness, not a GPU you can rerun.

All your candidate code, tests, measurements, images, and proposed adapter belong under `research/astra20261020/candidates/02-anchor-estimator/`. Jobs 01–07 must keep production files and the packaged baseline references unchanged: supply a narrowly scoped `adapter/PRODUCTION.patch` or exact adapter specification for job 08. Job 08 owns applying production changes in its integration branch after the dependency and local acceptance requirements are met. Preserve source line endings in patches, keep new experiments default-off, and protect the user's working baseline. Do not install a DLL into a game, edit secrets, or rewrite shared memory.

Use parallel subagents with explicit boundaries: at least a mechanism/representation investigator, an implementation/testing owner, and a skeptical independent reviewer. They may be the same number of available agents as your environment supports, but the skepticism must be independent of candidate tuning. Make the reviewer reproduce a known bad control before seeing your claimed win. Coordinate with other jobs through documented interfaces and artifacts; do not modify their folders or depend on their uncommitted files.

Known clip inventory: `fixtures/clips/bottle_track7.npz` contains frames180–186 in a moving 128x256 crop; `fixtures/clips/foliage23.npz` contains 87ee frames43–65 in a192x64 crop; `fixtures/clips/facade16.npz` contains f2ef frames34–49 in a96x96 crop. These are partial histories and omit albedo. Read their manifests and per-frame crop provenance: a moving crop is not camera/object motion, and these short windows cannot reconstruct unseen prior history. Inspect `fixtures/glass/` and its manifest if present for the aligned glass subset; do not assume all clips have all signal roles. Load NPZ with `allow_pickle=False`.

## Evidence and return contract

Use immutable BASE-derived masks and denominators; do not recompute the evaluation region from a modified candidate. Preserve chronological, unlooped sequences and report unsupported history/crop regions. Separate analytic truth, synthetic interventions, recorded GPU calibration, CPU model results, actual GPU execution, AMD RR output, and final game observation. None substitutes for another. Match crop, aspect, exposure, and frame timing in visual comparisons. Penalize grain, sparkles, and flicker explicitly rather than letting average blur metrics hide them. Never invent missing GPU, performance, build, or gameplay results.

Return `REPORT.md`, `RESULT.json`, `tests/`, exact runnable commands, candidate source, evidence and hashes, and `GPU_REQUEST.json` as prescribed by [RETURN_PROTOCOL](../RETURN_PROTOCOL.md). Include `BLOCKED_DATA_REQUEST.json` when necessary. Its content must identify the missing observation, hypotheses it distinguishes, exact requested tensors/metadata, units, frames and crop, provenance requirements, size estimate, and what useful work you completed without it; include the protocol's required fields. A data request must be surgical, not “upload everything.” Report rejection and uncertainty honestly.

Commit the reproducible work and open a PR to `sol/26-integration` if authenticated access is available. Otherwise return a ZIP containing the source, tests, evidence, commit IDs, binary patch or unified diff, and application instructions. Do not fabricate a PR link. Your recommendation must say ship as default-off A/B, keep as research, or reject, with the measured trade-off and the remaining local GPU/game gate. Write the final user-facing delivery summary in plain Turkish; technical documentation and source comments may remain English.

## Concrete problem and protected behavior

Task 26 made the anchor reachable in the native NRD-to-RR route. The native adapter is `OptiScaler/shaders/fsrd_preprocess/FSRDNrdPostMotionAnchor_Dx12.h`; its production callers live in `FSRDNrdBridgeRR_Dx12.cpp`. The native Stats/Gain variants and shared Apply are under `precompile/`, with scheduling and six-key math in `FSRDPostMotionAnchorConstants.h`. This is an input correction, before radiance scaling/provider work; it is not a post-RR brightness filter.

Native physical lighting units must stay unchanged. Frame sums use emulated uint64 16.16 with a physical cap16 and a 32-byte sums ABI. Scaling the physical copies by256 to improve quantization is not acceptable: it moves the physical clipping threshold. Current native fallback is identity, with a static centre and neighborhood recall requirement. This does not require the centre's own recall and does not guarantee full-resolution dynamic pixels remain unchanged after bilinear Apply.

The audited native policy reduced selected post-motion excess but did not meet every quality target. It also removed part of genuine 1.1/1.25 light-step response and retained a one-sided darkening bias. Anchor therefore remains OFF in the recommendation. Improve the cause; do not rebrand a dose reduction as proof of better illumination discrimination.

## Data limitations you must respect

Start with `portable/anchor/README.md`, its manifest and tests. Packaged fields include current stats, already-recalled keys, actual gain, fixed masks, motion-window age and frame metadata. Raw six-slice key textures are absent. Combined counters can be exact exported 1/1024 sums; native 16.16 ratios in this package are bounded stored-field estimates. This dataset can test a gain estimator conditional on the recalled observations. It cannot establish a new key-selection or reprojection algorithm, or final AMD RR/game quality.

Keep separate current level, recalled level, valid/static support and coverage. The existing four bilinear taps in an 8x8 cell are not a full 64-texel mean. Noise, true lighting, disocclusion, and geometry are mixed in captured residuals. Preserve fixed original masks and chronological windows.

## Competing explanations and discriminating experiments

1. Heavy-tailed sparse samples corrupt the estimated current/reference level, and ordinary ratios amplify that error. Predict a measurable dependence on tail concentration, effective sample size and temporal correlation. Robust paired or transformed estimators should improve null bias at matched correction dose, not merely because they correct less.
2. The one-sided operation `min(reference/current,1)` creates darkening even when true frame energy is unchanged. Construct equal-global-energy and antithetic spatial noise cases; show the bias analytically and numerically. A frame ratio above1 is not sufficient evidence that local darkening is harmless.
3. Real modest illumination changes are observationally indistinguishable from post-motion input excess given only these tensors. Construct two causes with identical observations. An honest candidate must either use an additional observable, maintain an uncertainty interval and abstain, or admit the trade-off. Do not claim causal discrimination from a threshold that simply discards 1.1/1.25 steps.
4. Support/recall loss rather than radiance statistics drives the apparent correction. Predict dependence on invalid/new-view support and neighborhood mixing. Hold radiance fixed while changing support; hold support fixed while changing the distribution.

For each, state an independent prediction and an experiment that could make you abandon it. Have the skeptical agent design the real-light null before candidate tuning.

## Implement and compare candidates

Build at least the strongest mechanism-supported candidate, rather than a catalogue of methods. Plausible representations include paired log ratios with a noise model, robust ratio-of-sums with explicit support, a symmetric residual estimator with a confidence interval, or a shrinkage/mixture model for excess probability. Choose using discriminating evidence. Document breakdown conditions and the extra state/observations required. If none solves identifiability, implement the best conservative abstention/diagnostic design and make the unresolved observation request precise.

Required controls include exact identity, stationary independent noise, spatially correlated noise, temporal correlation, heavy-tail bursts, sparse support, unbalanced valid masks, moving/new-view cells, camera-cut/reset sequences, and true multiplicative changes in both directions. Include 1.1,1.25,1.4 steps; x2/.5 alone is inadequate. Test a genuine light step during motion and in the same pose. Include local moving objects against a static background whose level changes.

Evaluate bias and variance at matched correction dose, not only at a chosen strength. Report total early/late correction energy, trajectory, global and local energy drift, changed support, false-positive dose under no-excess nulls, true-step response area/latency, and the fraction of cells/pixels where you abstain. Keep gain-field effects separate from downstream rendered flicker. Explain one-sided clamping and output interpolation in the metrics.

Run scale tests in physical units across dark FP16/16.16 thresholds and finite cap16. Intervals from exported rounded fields must propagate through strict guards. Do not falsely label an uncertain native ratio exact. Preserve diffuse/specular alpha and do not import a composite-only estimator into a per-lobe unit domain without defining it.

## Adapter, scope and acceptance

Return source-shaped pseudocode or HLSL plus a CPU implementation with matching boundaries and constants. Keep a versioned result for the old estimator so every claimed gain can be compared against an untouched baseline. Propose only an estimator/confidence patch here; job 04 owns transport, job 01 owns numerical semantics, job 08 owns integration. Put all intended production edits in your own adapter patch.

Acceptance requires a falsifier suite that rejects the known bad one-sided control, explicit correction-dose trade-offs, no claim that ambiguous real lighting is solved, and reproducibility on the provided held-out fixtures. A visual panel must show fixed-mask fields and chronological gain trajectories with identical scales. A negative result is useful if it gives a tested diagnostic and identifies the additional observation that would change the conclusion.

Your GPU request should ask for actual native Stats/Gain/Apply plus fresh RR on unlooped inputs, the same fixed masks, moderate real-light interventions and moving-object controls. Require a native Config-to-provider canary and physical input witnesses after integration; a combined-host shader replay is not native wiring proof.
