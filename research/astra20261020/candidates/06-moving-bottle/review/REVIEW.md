# Independent skeptical review

**Recommendation: keep as research.** The deliverable is a useful read-only
support tracer and a conservative, bit-preserving abstention path. It is not an
accepted moving-bottle image repair. No GPU, AMD RR, native build or final-game
execution was performed by this reviewer.

## Independence and order

The reviewer was separate from implementation and candidate tuning. Before
viewing candidate results, the reviewer reproduced the frozen rejected soft2
control, ran independent coordinate and brightness-versus-shape falsifiers, and
wrote `REVIEW_PLAN.md`. The candidate owner then supplied only anonymous public
blind tensors with a declared schema. The reviewer did not import candidate code
or inspect the scene generator while forming predictions.

`BLIND_PREDICTIONS.json` was sealed before label reveal, SHA256:

`89285b452a6d77d81c27f8a4d9b16afb64dc94fbba9d26a9f6f3173e301f9406`.

The previously committed private-label hash was verified after reveal:

`5c69f858b3364f9d2ae4d3215d6d902ac05708a93b76e373f3e81fd682d881a0`.

Only after sealing predictions did the reviewer inspect implementation and run
candidate-facing independent tests. `analyze_blind.py` contains the separate
NumPy measurement code; it does not call the candidate classifier or sampler.
It also reconstructs a rigid analytic object's screen correspondence from the
provided local identity fields, avoiding large cross-surface interpolation
errors when measuring the exact injected motion residual.

## Blind results, with the appropriate scope

Ten identified or qualified cases were consistent with their **broad observable
mechanism classes**; four cases correctly required abstention. No contradictory
broad-class claim was made. Five of the identified cases used the withheld
trajectory and noise family. The two byte-identical incomplete cases are one
observational-equivalence stress test, not independent samples.

| Case | Frozen independent conclusion | Revealed mechanism | Interpretation |
|---|---|---|---|
| 01 | Tail first appears only at selected | Selected-stage tail | Localizes the first observed stage difference |
| 02 | Sparse source, correct motion | Sparse source | 68% zero support is not evidence of wrong motion |
| 03 | Constant +2.5 px surface-MV residual | MV bias | Clean source and faulty geometric correspondence are separable |
| 04 | No detected support/transport error | Clean control | Conditional on the supplied analytic witnesses |
| 05 | Surface aligns; reflected-feature correspondence fails | Virtual mismatch | Requires the independent virtual witness supplied in this synthetic case |
| 06 | Misplaced/delayed source support before RR | Source delay | Does not identify an actual game's upstream estimator |
| 07 | Uniform 0.65 radiance multiplier, unchanged geometry | Level-only scaling | Darkening is not shape repair |
| 08 | Alternating -1.1/+1.1 px surface-motion residual | Jitter error | Jitter versus alternating MV bias remains ambiguous without convention metadata |
| 09 | Tail first appears at raw RR; selected is identical | Provider-stage tail | Synthetic stage localization, not proof of an AMD defect |
| 10 | Untrusted guide cannot establish motion error | Wrong guide | Abstain |
| 11 | Zero hit distance, otherwise clean supplied witnesses | Zero-hit control | Do not reconstruct physical virtual motion from zero hit distance |
| 12 | Independent support/correspondence absent | Missing geometry | Abstain |
| 13–14 | Identical available observations cannot separate latent causes | Equivalent-observation pair | Identical abstentions |

These results must not be summarized as “14 physical causes identified” or as a
game-quality success rate. The synthetic oracle silhouettes and identity fields
are exactly the observations missing from the real bottle fixture.

## Findings raised during review

### Corrected: disocclusion compared different local pixels

The initial metric formed `~mask[t] & mask[t-1]` in local crop coordinates. A crop
moving over a static object can satisfy that expression without any physical
disocclusion. The implementation now takes an explicit immutable disocclusion
mask. Analytic scenes build it with separately known background/camera
correspondence and both crop origins; absent such a witness, the reported metric
is `null`. The new test proves crop-only motion gives zero physical disocclusion
while the old local-index expression is nonzero. A moving-tail control gives
positive leakage on the corrected mask.

### Corrected: static-text evidence did not pass the text through the candidate

The scene generator included a wall/sign background, but the initial experiment
controls applied identity only to the foreground signal. The controls now pass
`background + selected` through the candidate and measure immutable sign-mask
bytes and horizontal detail energy. The candidate remains identity; this proves
preservation, not noise removal. Real facade and glass bytes are also covered by
the separate preservation runner.

### Corrected: empty metrics had undefined reduction behavior

An empty sequence or empty evaluation universe could reach an empty quantile or
indexing operation. These cases now raise `ValueError`. Missing independent
disocclusion data remains `null`, rather than silently measuring local mask
changes.

### Scoped correctly: real raw/selected equality is not whole-crop equality

The independently recomputed original-motion mask is speed greater than 12
full-render pixels per frame, eroded by two pixels. It includes the bottle and
hand/arm, and is not a semantic silhouette. Across frames 180–186 its counts are
9275, 9430, 9560, 9864, 8730, 5479 and 3114: **55,452 pixel observations**.

Both lobes match raw RR versus selected bit-for-bit on this fixed support.
However, the entire exported specular crop has **456 changed FP16 RGB words
(152 pixels)** outside that support; alpha does not change, and diffuse matches
throughout the full crops. `baseline_stage_scope.json` preserves the independent
per-frame counts. Consequently the data exclude an incremental selected-stage
difference on the specified moving support. They do not exclude an earlier
provider error, establish physical input shape, or validate final composition.

## Executed verification

Exact commands, exit codes, elapsed times and log hashes are in
`KNOWN_BAD.json` and `AUDIT_RUNS.json`.

- Frozen `soft2 --quality-gate`: expected exit **1**; six of 32 synthetic CPU
  edge phases worsen. This is an intentional rejection, not a test failure hidden
  as success or newly executed GPU evidence.
- Six independently authored coordinate/sampling/bit-preservation tests: pass.
- Entire post-correction candidate suite: **39 tests pass**.
- Final metadata hardening: two additional targeted tests pass. An explicit
  boolean comparison-break vector invalidates only the previous observation at
  reset/domain boundaries; it never resets the provider. Fractional render
  extents are rejected rather than truncated. The recorded visualization uses
  the captured provider reset flag and documents that warping binary support
  differs from thresholding interpolated radiance. The final integrated full
  runner is separately executed and attributed to the root implementation owner.
- Crop-origin omission mutation: expected exit **1**, with two meaningful
  assertion failures. The export retains the failure log. Only machine-specific
  traceback path prefixes were sanitized; original/output hashes and this
  transformation are recorded.

The independent tests cover full-render rather than crop motion scale, direction,
moving-origin cancellation, unequal previous extent, out-of-crop/nonfinite
samples, an analytic bilinear ramp, and exact FP16 signed-zero/subnormal/alpha
preservation. They are based on the public data contract, not copied from the
candidate's arithmetic.

## Remaining limitations and release boundary

The analytic classifier now explicitly rejects real-capture provenance: flags
asserted by a caller cannot create missing oracle support or correspondence.
Its thresholds are synthetic discriminators and are not approved game gates.
The image handoff always retains original pixels and carries no temporal state.

The recorded seven-frame crop contains previous RR history that is not exported.
Original/provider normal guides can differ; surface rotation, mixed pixels,
occlusion and G3 depth-B rejection sentinels limit geometric self-alignment.
Radiance self-alignment is particularly unsafe as a motion oracle. Low/zero hit
distance does not provide reflected-feature geometry. The absent final display,
remodulation and exposure metadata leave composition as a separate hypothesis.

The retained baseline water receipt is historical, not a new chronological water
test. Identity has no image transformation to introduce a water/glass regression,
but a native integration still needs its declared local acceptance gate. CPU
copy latency is not native GPU cost; no timing or image-quality win is claimed.

The proposed read-only adapter and bounded data request are appropriate next
steps. Do not enable a history reset, roughness change, wider blur, altered MV or
nontrivial support gate on the strength of this CPU package.
