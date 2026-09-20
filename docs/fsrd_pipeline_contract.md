# FSR-RR Floor pipeline contract

This describes the zero-rough screen reconstruction candidate, not completed game
acceptance. Reference: commit `3da4808e`. The user supplies 007 First Light and Cyberpunk
2077 captures/timings. Temporal detail accumulation is **not implemented or accepted** in
this candidate. Its four-frame A/B remains outstanding. There are no dormant temporal
settings, history buffers or placeholder history-rejection views.

## Frame and surface contract

Title inputs -> FloorSeed -> five spatial Floor passes -> conversion -> AMD RR -> composition
-> upscaler. Floor stays spatial; there is one production algorithm.

`FSRDFloorCommon.hlsli` owns finite radiance sanitation, normal normalization, material
agreement and signed view-depth surface tests. Minimum one-sided depth derivatives avoid
extrapolating across silhouettes. Surface weights reject depth/normal/diffuse-albedo boundaries.
Dark albedo never grants permission to restore raw colour.

Seed clamps its 5x5 neighbourhood to the logical subrect and reads each resource's own origin.
It sorts surface-supported luminances, retaining the centre for statistics in degenerate geometry. Lower
quartile, median, interquartile noise estimation and RGB reductions use FP32 arithmetic;
radiance/normal/material shared storage and colour outputs use FP16. Base RGB comes from
supported samples in the lower half of the luminance distribution, weighted toward the lower
quartile and capped to that quartile's luminance. Excluding the positive tail prevents coloured
ray samples from contaminating RGB even when a luminance-only cap would pass them. With fewer
than nine accepted samples, only the lower quartile is pooled: a small median population is
too easily contaminated. Unique in-bounds
surface support blends the surface estimate with a non-surface common-light pedestal, rather
than with zero. When support is insufficient, componentwise minima of independent 2x2 quadrant
trimmed means estimate this pedestal, bounded by the centre's colour to avoid lifting silhouettes.
Each block of at least three samples averages its two componentwise minima; smaller blocks
keep only their minimum. Two bright rays per border quadrant therefore cannot raise its mean.
Partial surface support
may lower this pedestal but cannot lift it with a few coincidentally matching bright samples.
The centre is excluded from those blocks: an isolated bright sample cannot raise the pedestal.
This explicitly protects volume/transparency layers which need not follow background geometry;
the pedestal is never used to grant detail eligibility. Replicated border samples cannot count
as independent surface support. The cleaned reference keeps a rank-accepted centre's exact RGB
when supported inner neighbours and the independent outer ring both contain it within half-range
margins. Outer-ring agreement rejects small impulse clusters. A further positive-impulse test
requires colour continuation from at least two independent accepted neighbours in the 5x5
patch or a coherent directional pair when the centre exceeds median + max(3*sigma, 8% of
median). This prevents unrelated extrema in two noisy rings from authorizing raw bright rays.
The full 5x5 support preserves endpoints of one-pixel strokes with two forward neighbours.
Detail uncertainty uses the
median of nine 3x3 mixed RGB derivatives in the supported 5x5 patch. Mixed derivatives cancel
colour ramps and axis-aligned edges; their median rejects isolated glyph corners. The 1.4826
scaling calibrates scalar Gaussian median absolute deviation (conservative for independent RGB).
The complete stencil must be in bounds and on the same surface. Otherwise it falls back
to directional curvature and supported outer-pair differences. Base/filter IQR noise
is unchanged. Fewer than 2.5 effective
surface samples invalidate detail (alpha=-1), and conversion preserves this rejection.
It does not reconstruct RGB from the noisy centre's chroma. Seed also writes canonical depth
and a depth-gradient/oct-normal guide.

A rank-rejected centre is replaced by the robust estimate only in proportion to how far it
sits outside the **outer ring's** envelope: `outlier = saturate(overshoot / envelope - 1)`.
An impulse sits far outside it and is replaced; a centre that is merely the local extremum of
smooth content overshoots by a fraction of the envelope and keeps its own magnitude. The ring
is the envelope rather than the 3x3 because a 2x2 impulse cluster inflates the inner one with
its own samples. This is what makes the cleaned reference a fixed point on supported clean
input: without it, 2-D extrema of a smooth texture were replaced by a smoothed copy and the
reference deviated from the current frame by up to 24% of its contrast before RR was ever
involved.

Five filter dispatches retain strides 1/2/4/8/16. Axial support at 1/4/16 alternates with diagonal
support at 2/8: four neighbours plus centre, using common surface and noise-adaptive range
weights. Later scales return locally on essentially noise-free pixels. Alpha retains seed
noise, not instability. There is no final DetailBoost.

With Floor disabled, seed prepares depth without colour filtering/sorting, filters are skipped,
conversion uses F=0 and composition skips detail. Noise suppression zero still runs RR and the
conservative seed.

## Zero-rough domain

The zero-rough domain (title roughness that quantizes to exact zero, classified before any
remapping) is the screen and mirror domain this Floor exists for, and it is treated
differently from the ordinary-material one:

- **The spatial light pedestal remains active.** In this domain conversion uses
  `Fz = min(F,C)` componentwise. It cannot brighten a dark glyph above its
  current-frame value, and identity RR reconstructs C rather than max(C,F).
  V6 withheld the pedestal on supported surfaces and lost flat volumetry when
  RR erased it. Surface support cannot identify composited volume light.
- The cap uses current radiance only as an upper bound, not as a raw blend.
  It can inherit downward noisy excursions; this remains a limitation to monitor.
- **RR receives an automatic roughness in that domain** (see Controls), so it filters pixels
  the title declares perfectly smooth instead of treating them as mirrors.

## Single signal split

For finite nonnegative raw colour C, spatial base F and applied title bias weight b:

```
Fz = min(F,C) for original zero roughness, otherwise F
R = (1-b) * max(C-Fz, 0)
Sbase = (1-b) * Fz + b * C
E = max(Fz-C, 0)
R = Rspec + Rdiff
T = specular radiance routed by responsivity
P = remod(demod(Rspec-T)) + remod(demod(Rdiff))
U = max(R-P-T, 0)
Skip = Sbase + T + U
Output = remod(RRspec) + remod(RRdiff) + Skip + DetailCorrection
```

Floor is counted once, inside Skip. With identity RR and zero detail the ideal result is
`C + (1-b)*E`, subject to FP16/UNORM rounding/clamping. `E` is identically zero in the
zero-rough domain, so the identity result there is exactly `C`. This is **not exact energy
conservation** when F exceeds C on ordinary materials. FloorExcess shows E. The diagnostic
crossing counter means any channel crosses, not that all residual channels are zero.

Albedos are quantized to actual RGBA8 storage levels before demodulation and closure.
DemodDivisorFloor bounds the divisor, separately from the RR material classification.
Dark/invalid albedo follows the same split; unrepresentable residual goes in U instead of
selecting a raw-colour bypass. Existing far-plane skip stays explicit and disallows detail.
Bias routes current-frame colour; responsivity routes its affected specular share once.
Nonzero applied routing invalidates detail reference (alpha=-1). Absent masks do not route.
Exact-zero roughness classifies RR material; it never grants detail eligibility by itself.

## Detail correction

Composition reconstructs Q from RR signals and Skip. A surface-aware binomial kernel
computes low bands of Q and the cleaned reference with identical taps/weights: 3x3 for ordinary
materials, the reference handover's 5x5 (1,4,6,4,1) split for RR type-1. Routed
neighbours contribute no detail. Their high bands are Hq and Hr.

For ordinary materials confidence shrinks Hr according to magnitude and seed noise; correction
restores only missing same-sign contrast, as before.

Type-1 uses current-frame reconstruction with two independent decisions:

1. Does the reference contain supported structure? Full 9x9 RGB variance is
   weighted by depth, normal and albedo agreement, excludes out-of-bounds
   duplicates and routed/ineligible samples, and is compared with the quiet quartile
   of independent noise estimates from the 5x5 patch. RGB supports equal-luminance
   coloured text. Relative contrast OR high signal-to-noise qualifies structure,
   so clean low-contrast text is not rejected merely for being dim. Centered
   moments and a precision floor keep constant fields from false structure.
2. Has RR already kept the structure? Regional RMS difference from the current
   reference is compared with estimated noise. Differences explained by noise
   retain RR; larger mismatches permit reconstruction. This is approximate,
   not proof of matching texture motion.

A surface-aware non-local-means filter cleans the transfer reference. An 11x11
search compares 3x3 RGB patches, validating both sides against the centre surface
and routing eligibility. Out-of-bounds duplicates do not count as evidence. At
least three weighted matching positions are required. Patch distance subtracts
the expected independent-noise contribution, then exponentially decays with a
bandwidth set by the quiet-quartile noise and NoiseSuppression. Matched original
centre colours are accumulated with a mild spatial falloff. The centre always
remains available, and zero noise or suppression is identity for this filter.
V10 also gives the centre colour a minimum share of the match decision: the
noise-corrected patch distance cannot fall below one quarter of the centre's
RGB squared distance after subtracting `4*patchVariance`. This prevents eight
background samples from outvoting a small letter corner. It only rejects
incompatible candidates; it does not sharpen or generate new pixel values.
The quiet quartile prevents several letter corners from inflating the bandwidth.
Effective sample count `(sum(w))^2/sum(w^2)` reduces the estimated candidate's
fine-grain uncertainty when evaluating structure confidence. It never weakens
Anchor or Correlation Mix. This estimate assumes independent fine grain, so it
cannot alone identify broad correlated lighting noise.

Two restored reference handover controls then apply only in this domain:

- `FloorHandoverAnchorClamp` always bounds the transfer candidate against the
  surface-weighted 5x5 RR mean plus/minus a multiple of its RGB standard deviation.
  Repeated similar colours do not disable it and movement is not sigma-limited.
  Like the original reference control, it can soften genuine new animated content
  absent from RR. Zero disables it; smaller positive values mean a tighter bound.
  V11 additionally constrains correlated RGB directions where Q and reference
  agree on structure, as described below. The original channel bounds remain active.
- `FloorHandoverCorrelationMix` uses modified SSIM-style agreement directly.
  V10 includes both luminance and colour structure, as described below. The V8 fourth-power
  noise/error multiplier is removed: large noise residuals must not make the
  control ineffective. Higher mix retains more structurally agreeing RR, including
  some of its blur. Zero disables this extra term; noise-based RR agreement remains.

V9 evaluated agreement in luminance alone; equally bright colours could become
indistinguishable even when RR erased their pattern. V10 additionally accumulates
centred moments of `RGB-luminance` over the same surface-aware 5x5 support. Let
`Vcr`/`Vcp` be mean-channel chromatic variance of Q/reference, `Ccp` their covariance,
`Vr` the luminance variance of Q and `T=max(4*patchNoise^2,1e-6)`. Colour agreement
is `Kc=saturate((2*Ccp+T)/(Vcr+Vcp+T))`; evidence is `E=Vcr/(Vcr+Vr+T)`.
Combined agreement is `lerp(Kl,min(Kl,Kc),E)`, where Kl is V9's luminance agreement.
Only colour variation already supported by RR can dispute its luminance agreement;
flat/neutral RR keeps V9's rejection even if the reference contains coloured grain.
The unconditional channel clamp and Mix's direct multiplier remain active. The V10
colour extension affects the similarity measurement, not the user's control strength.

V11 adds **joint-colour anchoring**. Independent RGB bounds can admit a colour that
never occurs in Q (for example coloured grain between two grey letter tones).
FP32 centred cross-channel moments form Q's symmetric 3x3 covariance over the
same surface/routing-bounded 5x5 patch. Three Jacobi sweeps find an approximate
orthonormal colour basis; the already channel-clamped candidate is limited to
`mean +/- Anchor*sqrt(eigenvariance)` in that basis, then channel-clamped again.
Negative numerical eigenvalues are clamped to zero. This can change colour without
averaging neighbouring glyph pixels; it is still a constraint, not emission extraction.

An unconditional colour-basis clamp was rejected for blurring small changing RGB
patterns. The final additional clamp is blended with weight
`smoothstep(0.65,0.95,saturate(Cqr/sqrt(Vq*Vr)))`, where Vq/Vr are the traces of
Q/reference covariance and Cqr is centred RGB cross-covariance. The denominator has
a 1e-12 FP32 floor. Low agreement retains the original unconditional channel Anchor,
so a stale palette is not forcibly treated as the new frame's palette. Anchor=0
disables both constraints. Mix and reference filtering are unchanged. Q includes
Skip; noise shared with Skip is not independent evidence and can still survive.

The attempted dark-scene SSIM rescaling and NLM self-weight reduction are **not
shipped**: the former returned correlated dark noise, the latter increased glyph
reference error. Correlation stabilizers and patch weights remain V10's values.

Let G be the patch-filtered, optionally anchored reference, Q the remodulated RR plus Skip,
S the structure weight, A the noise-based RR agreement, K the SSIM-style agreement,
m the correlation mix. Correction is
`strength * S * (1-A) * (1-m*K) * (G-Q)`.
Strong supported current content can replace stale interiors as well as edges;
flat regions retain Q. This is estimated selective reconstruction, **not physical
emission/reflection separation**. Accepting G can replace low-frequency lighting
differences too; the input does not expose verified separated layers.

`DetailPreservation` still sets strength: ordinary materials use its value; type-1 uses
`min(3*DetailPreservation,1)`. The same surface, noise and routing gates apply to both.
A supported reference envelope extended to include Q prevents bright overshoot/dark rings.
Zero confidence/detail leaves Q unchanged at output storage precision. Signed correction stays
FP32 until reconstruction. Final radiance is finite, nonnegative and FP16-bounded. RR is never
replaced by a blurred full image.

The structure weight is only computed inside the type-1 branch: in a frame that is mostly
ordinary material the ordinary path is what runs, and the statistic is skipped entirely.

## Resources and mirrors

Seed has 5 SRVs and 4 UAVs: base/sigma, R32 depth, gradient/oct-normal scratch and cleaned
reference/sigma. Filter has 4 SRVs and 1 UAV. Its colour buffers are reused by RR only after
conversion consumes Floor.

Conversion has 17 SRVs and 8 UAVs. t0..t8 are colour, canonical depth, motion, normals, roughness,
hit distance, diffuse/specular albedo and bias. t9 Floor; t10 inspector; t11 emissive; t12/t13
optional ray lengths; t14 raw title depth; t15 responsivity; t16 seed reference. Its final UAV
contains the reference with routing eligibility applied.

Composition has 8 SRVs and 1 UAV: specular signal/albedo, diffuse signal/albedo, Skip, packed
normals, eligible reference and depth. No raw-colour SRV. Disabled RR signals bind current
packed inputs rather than stale RR output. Motion is composition scratch only after RR;
seed/conversion overwrite it next frame before RR consumption. The block carries a six-pixel
halo (20x20 shared): radius five search plus radius one patch comparison. The structure
statistic remains 9x9, independent of search radius.

One extra RGBA16 texture costs 8 bytes per allocated render pixel excluding alignment:
7.03 MiB at 1280x720, 15.82 MiB at 1920x1080, 63.28 MiB at 3840x2160. This is an allocation
calculation, not game VRAM measurement. No additional temporal resources are allocated.
Constant buffer sizes: Seed 176, Filter 32, Conversion 416, Composition 64 bytes.
Composition's declared DXIL groupshared arrays total 12,000 bytes per group
(7,680 in V8; the earlier document's 9,216 estimate was incorrect);
no extra texture is allocated. Ordinary materials skip patch matching, though they
share the larger initial tile load. Performance has not been accepted in-game.
The verifier checks layouts, flags, debug reachability, SRV/UAV order, root-table counts and
albedo precision. Regenerate affected DXIL and embedded headers together.

## Controls and diagnostics

Floor controls in [FSR-RR] are `FloorEnabled=true`, `FloorNoiseSuppression=0.75`,
`FloorDetailPreservation=0.35`, `FloorHandoverAnchorClamp=4.0` and
`FloorHandoverCorrelationMix=1.0`. The last two were restored at the user's request.
V10 adopts the user's preferred 4/1 setting as the default. Stored INI values are
not overwritten; CPU non-finite fallback and descriptor defaults also use 4.
Scalars are finite-clamped to [0,1], except anchor [0,8], before dispatch; non-finite
values use defaults. Changes invalidate RR history. The restored INI values are read and
preserved; 17 other retired keys are removed on a normal save.
The manual Roughness Addition control is **removed**: `RoughnessFloor` no longer exists in the
config, the menu or the constant buffer, and its INI key is deleted on a normal save together
with the other retired names. The zero-rough domain's RR roughness is now the packing shader's
own compatibility constant (`s_ZeroRoughRRRoughness = 0.1`), applied only while Floor is
enabled; with Floor disabled the title's roughness is published untouched. 0.1 is the value the
current comparisons were made with, not an established optimum and not an AMD threshold.
DemodDivisorFloor is independent and retained. Other legacy Floor controls, CorrelationBias and
ZeroRoughHandover are not read/migrated.

Advanced views show actual FloorColor, FloorResidual, FloorNoise, FloorExcess, DetailReference,
DetailConfidence and DetailCorrection, alongside RR diagnostics. Correction displays signed
data around grey 0.5 scaled by reconstructed luminance. Noise uses Turbo display mapping.
In V9, `DetailReference` displays the actual patch-filtered candidate before Anchor
on zero-rough pixels (the seed reference on ordinary pixels), also when detail strength
is zero. It no longer displays the unfiltered seed reference on zero roughness.
`DetailConfidence` includes the actual direct correlation term. `DetailCorrection`
includes the effects of Anchor, strength, confidence and the final envelope.
`AppliedRoughness` (mode 22, formerly AppliedRoughnessFloor) visualises the automatic
zero-rough value. No history-rejection view exists because this candidate has no detail history.

`DenoiserOutput` retains the reference build's meaning: the sum of demodulated RR signals,
without albedo or Skip. `ReconstructedColor` shows remodulated RR plus Skip before detail.
The first spatial candidate incorrectly used the latter meaning for DenoiserOutput; those
captures cannot directly establish an RR quality difference from brightness alone.

## Retained title/RR contracts

Camera matrices must be finite/invertible. Earlier 007 First Light investigation found invalid
NGX WorldToView and used the validated Streamline fallback. Missing specular ray length retains
the primary-depth fallback for indirect dispatch, an RR compatibility approximation.
Canonical motion remains unjittered PreviousUV-CurrentUV with corresponding-surface depth delta.
Source motion resolution, jitter and subrect conventions remain in conversion. Reflected-motion
disagreement routing stays removed: it previously routed raw noise under camera movement.

## Validation and outstanding acceptance

The portable entry point rebuilds/verifies all four shader artifacts, runs current
GPU contracts and INI checks, and builds Release x64. Toolchain prerequisites,
optional SHA-256-pinned historical references and result semantics are documented
in [fsrd_validation.md](fsrd_validation.md).

```
python OptiScaler/shaders/shader_tools/validate_fsrd.py --build
```

Historical A/B is skipped explicitly when reference packages are not supplied.
Current Anchor/Mix, colour/HDR, routing, boundary and volumetric contracts still run.
Synthetic timing benchmarks are separate from correctness and game acceptance.

Tests execute production DXIL in a standalone D3D12 runner with debug validation and typed
readback: DC/HDR, fireflies/clusters, 1px strokes, surface boundaries, subrect/tiny/odd dimensions,
finite values, dark albedo, split closure and detail invariants. They do not exercise the
injected DLL's game resource lifecycle or AMD RR.

`test_fsrd_zero_rough_screen.py` is the acceptance suite for this design: identity closure in
the zero-rough domain for dark and bright text, RGB texture, HDR, dim radiance, mirrors,
non-zero subrect and odd sizes; dark/bright symmetry; stale blurred and displaced RR unable to
move current text, with no bright halo; grain added independently over a known clean screen
layer and graded against both the clean layer and the clean illumination; a volume over an
incompatible guide keeping its light; and already-sharp RR reproduced within the 5% contrast
ceiling.

The CP2077 regression fixtures exercise unsupported bright samples, broad clean edges with
blurred RR, type-1 detail rejection/disable, conversion closure and both output debug
meanings. They are synthetic mechanisms suggested by user captures, not a replay of the game's
G-buffer. The user reported improved 007 quality but CP2077 Skip noise and advertisement blur
with the first candidate. V2 removed speckles but failed to preserve volumetry and the reference
handover. V3 tests additionally erase the RR residual deliberately to verify volume survives
through actual packing/Skip/composition, and compare displaced strokes and curved antialiased
glyphs against the original compiled rank/handover shaders. A photograph cannot identify the
game's underlying G-buffer, so these remain mechanism tests. The user found V3 still blurred
CP2077 advertisements and returned some speckles. V4 fixtures verify the original type-1
classification through roughness floors 0/.001/.0015/.002/.1, strongly blurred strokes, white
noise rejection, and randomly distributed ray-noise clusters over the volume pedestal.
The reported approximately .0015 RR transition is a user observation, not an SDK threshold
established by these tests (the fixtures do not execute AMD RR).
V7 review corrected a test that computed stale/blurred RR without submitting it,
and a dark-stroke contrast assertion with the wrong direction. Coherent-guide
volume retention is now an assertion. Review fixtures cover low-contrast and
equal-luminance text, cross-surface confidence leakage, already-sharp RR grain
reuse, moving noisy glyphs, an active noise control and resource-border fidelity.
V8 adds archived V2/V3/V7 comparisons for randomly distributed coloured positive rays,
including fragmented guides and resource borders, and independent checks for each restored
handover control. Production test constants explicitly use the real control defaults.
V9 adds patch-filter diagnostics, bitmap lettering with fine and correlated grain,
three independently changing coarse-noise frames, direct control sweeps, and a
real Floor/conversion/Skip case with an ideal synthetic residual denoiser. Pure
current-texture recovery tests explicitly set Anchor/Mix to zero; their previous
error thresholds are unchanged. Default-control noise rejection and identity
tests retain actual defaults. The patch suite separately records the default
controls' cost on clean animated text, rather than silently suppressing controls
to preserve old full-recovery results. These are spatial fixtures, not a temporal
stability measurement or an execution of AMD RR.
V10 compares against the immutable V9 at equal Anchor=4/Mix=1: isoluminant small
colour textures, noisy bitmap glyphs, mixed RGB/diagonal structure at three sizes,
large glyphs, independently changing coarse grain, HDR and already-sharp inputs.
Ordinary material, explicit routing and disabled detail must remain bit-identical
to V9 in their fixtures. The historical patch suite explicitly retains Anchor=2
where it tests V9's original control tradeoff; default-based helpers now use 4.
See the versioned handoffs for measured results.
V11 compares directly with archived V10 at equal 4/1 controls on neutral, warm and
isoluminant patterned panels with three independent coarse/fine-noise realizations,
changed RGB palettes, shifted patterns, five exposure levels, held-out fine noise,
dark correlated noise and real Skip. Reference output, inactive/ordinary paths and
depth/normal/albedo/routing boundaries are separately guarded. The older V10 test
isolates its Mix comparison with Anchor=0, because V11 independently extends Anchor.

Benchmark uses production internal formats, an external FP16/R32 fixture, identity RR,
1280x720, three trials and 600 timed repetitions per stage after ten discarded warmups.
Results are sums of per-stage medians/p95, **not whole-chain frame timings**. Title formats,
synchronization and engine load can change results.
The user explicitly suspended the duration limit for this quality iteration.
V7 timing is historical; V8/V9/V10/V11 timing has not been remeasured. Neither the former 1.50x synthetic allowance nor the
original in-game budget is claimed to be met.

## Known liabilities

- **Current colour is a composited signal.** Noise and real animated content can
  overlap in colour, scale and frequency. There is no verified independent
  emission/reflection input, so perfect separation is not guaranteed.
- **The zero-rough base cap can carry dark noisy excursions into Skip.** It avoids
  filling dark text while preserving volumetry; the final agreement/range filter
  reduces noise where supported, but this still needs game validation.
- **Q includes Skip.** Noise shared by Skip and the reference is not independent RR
  evidence; neither correlation nor anchoring guarantees its removal. The V9
  full-chain fixture measures remaining error instead of setting Skip to zero.
- **Active Anchor/Mix can soften animated text.** Both now honour their requested
  strength without the old support/sigma exceptions. Tight positive Anchor bounds
  are especially restrictive when RR erased current texture. Zero disables each
  additional control; larger positive Anchor values loosen its range.
- **A screen whose texture is genuinely buried under the grain is not resolvable from one
  frame.** The gate is deliberately biased to keep the current frame where its content is a
  meaningful fraction of the local light, so a dark area whose grain is comparable to its
  content keeps that grain.
- **Temporal support is not implemented.** A surface motion vector does not describe animated
  texture motion, and zero surface motion cannot authorize history reuse.

Game acceptance still requires both titles' static/pan/object/text/reflection/
particle captures, flat-region noise/flicker measurements, clean-edge contrast
and checks for new trails/halos. Performance optimization follows quality for
this iteration, per the user's instruction. No game acceptance or successful
temporal A/B is claimed by the standalone GPU tests.
