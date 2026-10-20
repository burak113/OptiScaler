# Independent skeptical review

## Independence and preregistration

The reviewer read the immutable task protocol and shared Apply source before any
candidate reconstruction existed. The preregistration and first known-bad
reproduction are in `../evidence/reviewer_preregistration.json` (SHA256
`c02d9c368ec44cd77f7cfc7385fc9977bf7e530b819c996694744e5a2f7c9729`).
The registration records its UTC timestamp and that `reconstruction.py` did not
exist. The original hashed test source is preserved unmodified in
`../evidence/reviewer_preregistered_control.py`; the runnable test file later
gained API-level challenges. This reviewer did not select candidate thresholds or optimize the candidate.

## Known-bad control reproduced first

Two adjacent 8-pixel cells have exact gains `[0.6, 1.0]`. The right cell is a
protected moving surface. Its stored centre gain is exactly one. The shared
Apply convention samples a normalized full-resolution pixel centre with ideal
linear interpolation from the coarse gain texture. The eight protected full
pixels receive gains `[0.825, 0.875, 0.925, 0.975, 1, 1, 1, 1]`: four change,
maximum spill is **0.175**, and mean spill on the immutable protected support is
**0.05**. This is an analytic reconstruction failure, independent of estimator
noise. It is not a measured D3D sampler or game result. The deliberately large
0.4 correction makes the mechanism visible; spill scales linearly with dose.

`tests/test_negative_controls.py` independently reproduces this control and
eight coordinate-mutation families. Its initial run completed successfully:
8 tests, no failures. Tests pass because they reject or numerically distinguish
the wrong controls, not because the controls are accepted.

## Preregistered criteria

- Fixed baseline protected masks and denominators.
- Full-resolution protection, including unseen phases and orientations.
- Unknown crop support remains invalid; nearest-edge clamping is not evidence.
- Report correction dose separately and compare at a matched dose.
- A pure centre does not certify an estimator that mixed neighbouring surfaces.
- Geometry-derived support must be tested separately from oracle surface labels.
- Coplanar moving material cannot be distinguished using only depth and normals.
- Invalid normals, zero/nonfinite depth, sky and unknown hit-distance roles have
  explicit conservative behavior.
- Every required coordinate mutant violates its named invariant.
- CPU arithmetic and synthetic keys do not imply native routing or GPU quality.

## Source observation separated from quality inference

Native `FSRDNrdPostMotionAnchorStatsRecall.hlsl` defines the cell centre as
`cell*8+4`, then `ViewPosition` adds another 0.5 before NDC conversion.
`ProjectToPixels` returns edge-based pixels and `StaticCell` subtracts the
original centre. With an identity camera pair this arithmetic predicts a
`(+0.5,+0.5)` motion despite zero surface motion. This is a deterministic
source-level phase observation. It does **not** establish that this phase is the
dominant cause of the captured image failures, or justify combining its change
with an estimator tuning claim.

## Candidate review

The independent reviewer executed **28 checks** in two owned suites: 15 negative
control/API tests and 13 reconstruction challenges. Both commands returned zero.
Exact commands, elapsed times, source hashes, and log hashes are recorded in
`../evidence/reviewer_execution.json`. The reviewer did not execute Windows,
D3D12, DXC, AMD RR, or a game. The tested source is identified by hashes rather
than implying that later edits were already reviewed.

The public APIs pass the declared jitter-sign oracle, current-to-previous MV
direction, render-versus-ROI scaling, allocation-versus-active scaling,
column-vector transform and storage-layout distinction, left/right-handed
absolute native key depth, separate native half-pixel phase, and strict
nonzero-tap crop support checks. Each corresponding wrong input/coordinate
model has a nonzero error or a demonstrably fabricated validity result.

Reconstruction challenges cover an exact sloped plane, a one-pixel foreground
strip hidden inside an otherwise flat coarse cell, coplanar moving material
with a separate source eligibility mask, pure centre geometry with a foreign
estimator donor, NaN/Inf/zero guides, all-invalid gains, nonfinite donor weights,
odd extents, partial observations, OFF identity, and raw FP16 alpha bit patterns.
Partial-weight interpolation records less than one support mass at image edges;
it does not pretend that discarded out-of-domain contributors were observed.

### Defects found and repaired

The pre-fix reproductions remain in `../evidence/reviewer_defects.json`.

| ID | Independent reproduction | Repair and regression |
|---|---|---|
| R1 | Infinite plane tolerance certified a mixed cell; negative minimum weight produced 64 NaN outputs from zero supported mass. | Policy validation rejects nonfinite/negative tolerances, nonintegral/nonpositive cell size, and invalid minimum weight. The independent policy regression passes. |
| R2 | With one physical ring slot, reset after submission allowed a new logical epoch to reuse slot zero while old fence 1 remained incomplete. | Physical fence ownership survives logical reset. Independent regression requires scheduling to fail before fence completion, then succeed afterward without resurrecting old metadata. |
| R3 | A NaN numeric known-mask became `True`; infinite depth tolerance accepted depths 1 and 100. | Transport APIs require boolean support masks and finite geometric tolerances. Both independent fail-closed regressions pass. |

The authors repaired these defects; the reviewer supplied counterexamples and
regression assertions, not new tuning parameters. Invalid-query arithmetic was
also changed to avoid warning-producing Inf-times-zero operations while keeping
identity fallback.

### Explicit negative conclusions retained

1. **Geometry is not topology.** Parallel surfaces at depths 10 and 10.0005 are
   within the default plane tolerance. A cell spanning them can be certified as
   geometrically compatible. A dedicated counterexample remains in the suite.
   Claims of exact support purity apply only to the separated analytic cases.
2. **Coplanar motion needs independent provenance.** Removing the source motion
   eligibility mask from a coplanar moving strip causes it to receive a 0.6 gain.
   Depth and normals alone do not identify that protected material.
3. **False gain provenance cannot be repaired downstream.** Supplying a
   contaminated 0.6 gain with a falsely declared local certificate leaves a
   0.3 error against a 0.9 target. Certifying only the centre is insufficient;
   every actual nonzero statistical donor and its recalled support must be known.
4. **Sparse support has a quality cost.** Discarding contributors and
   renormalizing can reduce spatial averaging and change support over time.
   Correction dose, grain/error tails, and flicker must be reported separately.
   A lower spill statistic alone is not an accepted image-quality result.

### Evidence interpretation requirements

The sweep generator was inspected independently. Evaluation masks originate in
the analytic baseline scene, before variants are evaluated; the reconstruction
API receives no surface IDs. Nevertheless the synthetic eligibility mask is
known truth for the intervention, not a captured native motion classifier. The
gain intervention is exact at coarse centres, not an exact full-resolution
correction oracle. This distinction is necessary when interpreting boundary
errors and dose loss.

A common-dose comparison that includes a hard-reject variant can have zero dose
when that variant rejects all support. Such comparisons are trivial and must be
counted/disclosed. Unmatched temporal error proxies cannot establish denoising,
and spatial error standard deviation contains fallback bias as well as injected
noise. These concerns were reported to the experiment owner before final
interpretation.

## Independent recommendation

**Keep as research.** The transport harness, support contract, negative controls,
and corrected history-publication model are useful reusable diagnostics. The
conservative reconstruction has a defensible conditional safety mechanism, but
its required actual-estimator and temporal support certificates are absent from
the frozen native gain texture. The captured package lacks raw six-slice keys
and the camera/sampler witnesses needed to identify native recall changes.

No production quality claim is supported until the local request executes both
native and combined routes with fresh controls, actual sampler fractions,
phase/crop/DRS witnesses, all donor support, and actual RR/game output.


## Focused adapter and revised-metric follow-up

The reviewer inspected `../adapter/SupportCertifiedApply.hlsl` and the exact
adapter specification. The resource table agrees with source: five SRVs, three
UAVs, and a 48-byte constant buffer at the documented 16-byte packing boundaries.
The explicit four-tap accumulation, accepted-weight mass, normal/depth checks,
identity fallback, and active-extent mapping agree with the CPU reference at the
algorithm level. FP32 versus float64 hard-threshold differences remain a required
GPU witness. This is source inspection, **not successful shader compilation**.

The specification correctly states that the support-builder/host integration is
pending and cannot be replaced with a guessed certificate. A guide-resource
proposal without actual original/key support is not a deployable native fix.

One alpha wording issue was reported: a typed RGBA16_FLOAT load into float4 and
store on corrected pixels carries the alpha value unchanged, but cannot alone
prove preservation of every NaN payload, subnormal, or signed-zero bit pattern.
The CPU raw-bit preservation test is not proof of that GPU property. OFF and
unsupported shader paths skip writes. Actual alpha bit comparisons belong in
the requested local typed-UAV witness.

The revised phase code now includes all controls in the common-dose minimum,
asserts that attenuation never amplifies, adds a bilinear-versus-supported
pairwise dose comparison, and records zero-dose cases. These changes resolve
the earlier dose-accounting concerns at source level.

The reviewer re-executed only the materially changed temporal calculation.
`../evidence/reviewer_temporal_validation.json` records its experiment-source
hash and actual results. Three independent injected-noise seeds use the same
48-frame unlooped trajectory and fixed baseline masks. The masks have hash
`94b7abb69d260eae6927b8887ca627650ba8afb297f6098a0914d35ea853edd2`.

| Synthetic CPU metric | Bilinear | Supported | Interpretation |
|---|---|---|---|
| Protected spill peak across three seeds | 0.19506–0.20411 | 0 | Boundary safety under supplied eligibility and support. |
| Eligible correction dose | 0.95173–0.95537 | 0.96274–0.96707 | Supported preserves far more correction than hard identity (0.42444–0.42612). |
| Matched-dose eligible flicker RMS | 0.005313–0.005424 | 0.006251–0.006432 | Supported is **17.56–18.58% worse**. |
| Matched isolated gain-noise standard deviation | 0.002423–0.002529 | 0.002626–0.002803 | Supported is **8.40–10.84% worse**. |
| Noiseless support-change flicker RMS | 0.008942 | 0.011285 | Supported is **26.21% worse** even without injected gain noise. |

These are separately measured arithmetic/representation trade-offs, not actual
RR grain, fresh GPU, or game measurements. The negative flicker/noise results
reinforce **keep as research**. Safety on protected pixels is insufficient to
accept this reconstruction as a production quality improvement.
