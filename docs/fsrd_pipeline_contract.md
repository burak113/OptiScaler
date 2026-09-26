# FSR-RR Floor pipeline contract

> Current checkpoint: [Floor recovery and adaptive retirement](fsrd_floor_recovery_release_20260926.md).
> Dated sections below retain earlier implementation and validation history;
> the checkpoint supersedes retired options and algorithms.

This describes the albedo-guided surface reconstruction candidate, not completed game
acceptance. Reference: commit `3da4808e`. The user supplies 007 First Light and Cyberpunk
2077 captures/timings. Floor and its reference remain spatial. Short, validated
temporal **decision** helpers are implemented in composition; no previous image or
correction radiance is accumulated. See [composition optimization](fsrd_composition_temporal_optimization.md)
for its resource and lifecycle contract. The latest scope and routing override
is [screen-only handover](fsrd_screen_only_handover.md). The latest spatial volume and
visibility changes are described in [volume visibility](fsrd_volume_visibility.md).
Its light-ridge/quiet-filter experiment was subsequently rejected for coarse
grain; [correlated grain regression](fsrd_correlated_grain.md) is the latest override.
In-game acceptance remains outstanding.

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
Up to five effective surface samples use this conservative pedestal. Between five and
nine samples, a smooth transition restores the surface estimate. This removes a hard
five-sample brightness jump when a surface becomes visible.
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
to directional curvature and supported outer-pair differences. The spatial base/filter
uses IQR uncertainty; low mixed derivatives do not certify noise-free light.
Fewer than 2.5 effective
surface samples invalidate detail (alpha=-1), and conversion preserves this rejection.
It does not reconstruct RGB from the noisy centre's chroma. Seed also writes canonical depth
and a depth-gradient/oct-normal guide.

The experimental five-sample ridge lift is removed. Large correlated noisy
patches can agree along a direction and still be stochastic illumination, so
spatial continuity alone does not authorize an elevated RR-bypassing pedestal.

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
weights. Later scales return locally on essentially noise-free pixels. Pairwise range
uses the larger of the centre tolerance and the neighbour's noise tolerance, retaining the accepted smoothing
of uncertain patches. Alpha retains seed
noise, not instability. There is no final DetailBoost.

With Floor disabled, seed prepares depth without colour filtering/sorting, filters are skipped,
conversion uses F=0 and composition skips detail. The Noise Suppression control and
its reference-denoising stages are removed; the essential spatial base remains. Its range
tolerance is max(4% of local luminance, 3.25 times the seed noise estimate).

## Surface selection from original albedo

Virtual albedo is retired. Conversion reads the original diffuse/specular albedo to select
surfaces for the existing type-1 Anchor/Correlation path. It never encodes a Floor pattern
in either albedo. Normal RR demodulation, compatibility normalization, quantization and
remodulation still use the title's material inputs.

Selection uses an in-bounds 5x5 patch with signed depth, one-sided slope prediction, normal
and original roughness agreement. Both albedos must be finite, nonnegative and within their
reflectance range. Diffuse luminance must be at least 0.02 and at least one quarter of
specular luminance; pure mirrors/specular-dominant materials are excluded. Every accepted
same-geometry material sample is compared in RGB, separately for both albedos, within
`max(2/255, 4% of center channel)`. An albedo boundary cannot be discarded merely because it
disagrees. At least nine valid independent reference samples are required.

Original exact-zero roughness remains a CP77 hint **after** those tests; it no longer
selects all mirrors, invalid guides or textured albedos. Nonzero roughness requires at
least twelve samples and colour structure unexplained by a best-fitting RGB plane.
The residual mean RGB energy must exceed both nine times the reference noise energy and
a 3% relative RMS contrast floor. Thus constant fields, linear illumination ramps and
ordinary independent grain do not qualify in the synthetic fixtures. Equal-luminance
colour structure does qualify. Bias-routed pixels cannot select the special domain.

This is a conservative heuristic, not emission detection. Curved lighting, cast shadows
and mixed diffuse/reflected texture can resemble an unrepresented screen pattern. Selection
has no temporal state, and animation can change patch evidence. Very small or noisy patches
can be rejected. See [surface-selection notes](fsrd_surface_selection.md).

Selected surfaces are treated differently from ordinary materials:

- **Selected screens always send their full radiance through RR.** Their
  spatial pedestal is zero, the full current signal is split/demodulated for RR,
  and the selected-domain roughness floor of 0.1 remains enabled. Positive FP16
  rounding errors are not reintroduced through Skip. Genuine divisor/saturation
  loss and explicit title routing are still preserved. With representable
  albedos and no explicit routing, Skip is exactly zero. Ordinary surfaces keep
  their volumetric pedestal. This is distinct from disabling Floor entirely,
  which also disables surface selection and the local roughness intervention.
- **At positive Detail Preservation only the selected screens receive detail correction.**
  Anchor, Correlation Mix, luma/chroma recovery and temporal decision helpers
  are limited to this domain. Ordinary surfaces retain the spatial filter and
  RR-plus-Skip reconstruction without these corrections. On unselected original
  zero-rough pixels conversion uses `Fz = min(F,C+allowance)` componentwise.
  The allowance is three times the smaller of seed IQR sigma and reference sigma,
  gated by their agreement. It is zero where an immediate independent neighbour
  repeats the centre's colour within storage-scale tolerance: a dark stroke or
  endpoint must not be filled by a corner's mixed derivative.
  Per-channel deficits of 20% through 50% of the estimated Floor fade this
  relaxation out. This protects noisy dark lettering that cannot pass an
  exact-colour match; deep noise excursions can therefore remain deliberately.
  Clean-input identity tests still reconstruct C within storage tolerance. Noisy
  inputs can now have a nonzero, explicitly reported Floor excess; identity RR
  reconstructs `C+max(Fz-C,0)`, not exact C in those channels.
  A selected screen has Fz=0 instead. This deliberately gives RR responsibility
  for its entire light signal: composited volume on a selected screen is no
  longer independently preserved if RR erases it. Ordinary-surface volumetry stays
  protected. The user's TV A/B showed clean RR reconstruction without the pedestal.
- A hard raw ceiling reprinted negative noise excursions into Skip after filtering.
  The bounded uncertainty allowance removes this path where the noise evidence
  supports it, without averaging the current texture. Explicit bias/responsivity
  routing and demodulation closure retain their existing contracts.
- **RR receives a minimum roughness of 0.1 in the selected domain** (see Controls).
  Values already above 0.1 are unchanged. This is a compatibility measure, not an
  assertion about why the AMD model denoises a particular material.
- With Floor disabled, classification is skipped and the previous RR-only roughness
  and material encoding are preserved exactly; detail is disabled.

## Single signal split

For finite nonnegative raw colour C, spatial base F and applied title bias weight b:

```
Fz = 0 for selected handover surfaces
Fz = min(F,C+allowance) for unselected original zero roughness, otherwise F
R = (1-b) * max(C-Fz, 0)
Sbase = (1-b) * Fz + b * C
E = max(Fz-C, 0)
R = Rspec + Rdiff
T = specular radiance routed by responsivity
P = remod(demod(Rspec-T)) + remod(demod(Rdiff))
U = real divisor/saturation loss for selected screens, otherwise max(R-P-T, 0)
Skip = Sbase + T + U
Output = remod(RRspec) + remod(RRdiff) + Skip + DetailCorrection
```

Floor is counted once, inside Skip. With identity RR and zero detail the ideal result is
`C + (1-b)*E`, subject to FP16/UNORM rounding/clamping. `E` is identically zero in the
selected domain, so the identity result there is `C` within storage precision.
Unselected zero-rough surfaces can have bounded excess under the noise allowance. This is **not exact energy
conservation** when F exceeds C on ordinary materials. FloorExcess shows E. The diagnostic
crossing counter means any channel crosses, not that all residual channels are zero.

Albedos are quantized to actual RGBA8 storage levels before demodulation and closure.
DemodDivisorFloor bounds the divisor, separately from the RR material classification.
Dark/invalid albedo follows the same split; unrepresentable residual goes in U instead of
selecting a raw-colour bypass. Existing far-plane skip stays explicit and disallows detail.
Bias routes current-frame colour; responsivity routes its affected specular share once.
Nonzero applied routing invalidates detail reference (alpha=-1). Absent masks do not route.
The selected surface sets RR material type 1; independent detail/noise/routing checks still apply.

## Detail correction

Composition reconstructs Q from RR signals and Skip. A surface-aware binomial kernel
computes low bands of Q and the reference with the same surface-aware 5x5
(1,4,6,4,1) kernel on selected surfaces without an albedo pattern. Routed neighbours contribute no
detail. Their high bands are Hq and Hr. Selected materials use the same Anchor,
Correlation Mix and luminance/chromatic recovery, with two independent decisions:

1. Does the reference contain supported structure? Full 9x9 RGB variance is
   weighted by depth, normal and albedo agreement, excludes out-of-bounds
   duplicates and routed/ineligible samples, and is compared with the quiet quartile
   of local noise estimates from the 5x5 patch. RGB supports equal-luminance
   coloured text. Relative contrast OR high signal-to-noise qualifies structure,
   so clean low-contrast text is not rejected merely for being dim. Centered
   moments and a precision floor keep constant fields from false structure.
2. Has RR already kept the structure? Regional RMS difference from the current
   reference is compared with estimated noise. Differences explained by noise
   retain RR; larger mismatches permit reconstruction. This is approximate,
   not proof of matching texture motion.

Reference denoising is retired at the user's request. The 11x11 non-local search,
3x3 patch comparisons and effective-sample-count adjustment are removed.
The same-surface quiet-pair cap remains solely for confidence: without it, dense
clean glyph corners inflate sigma and prevent contrast recovery. It does not filter RGB. The selected surface's candidate is now the seed reference itself;
`DetailReference` equals `DetailSeed` at storage precision before Anchor.
The 9x9 surface-weighted moments remain solely for Anchor/Mix and contrast confidence.
The noise estimate still rejects unsupported transfers, but does not average reference RGB.
Fine grain formerly removed by NLM can consequently return; removal is a performance/scope
decision, not a claim of equal image quality. The former noisy-glyph denoising thresholds
are recorded as withdrawn expectations, rather than weakened into passing tests.

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
disables both constraints. Mix remains active; reference filtering is retired. Q includes
Skip; selected screens now remove the spatial pedestal from Skip. Explicit
game routing and real unrepresentable energy remain exceptions.

The attempted dark-scene SSIM rescaling and NLM self-weight reduction are **not
shipped**: the former returned correlated dark noise, the latter increased glyph
reference error. Correlation stabilizers remain V10's values; patch filtering is now retired.

The final quality candidate adds a **forward blur evidence** check instead of
globally rescaling those stabilizers. A 3x3 binomial reference probe is evaluated
at accepted positions of the 5x5 comparison window. Every probe stencil must be
in bounds, non-routed and on the same depth/normal/albedo surface. At least half
the original kernel weight must have complete stencils. The probe is only an
explanation of RR blur; its filtered colour is never transferred.

Let `Er` and `Eb` be weighted mean-channel squared errors to Q for the original
reference and its probe, `N=patchVariance`, `U=max(meanChannel(lowReference^2),1e-12)`.
Define `M=max(Er-8*N,0)`, `B=max(Eb-.28*N,0)` and
`H=smoothstep(.60,.85,1-B/max(M,1e-6*U))*smoothstep(1e-4*U,1e-3*U,M)`.
The conservative noise margin is necessary because the lower-quartile noise
estimate is not a guarantee of true variance. Insufficient support sets H=0. Effective agreement is `K=Koriginal*(1-H)` everywhere below,
including the extra colour/luminance budget. This permits a verified blurred
match to use the sharp seed reference without expanding either Anchor.
No history, new texture, extra dispatch, root constant or user knob is added.

Let G be the seed-derived, optionally anchored reference, Q the remodulated RR plus Skip,
S the structure weight, A the noise-based RR agreement, K the SSIM-style agreement,
m the correlation mix. The base correction is
`strength * S * (1-A) * (1-m*K) * (G-Q)`.
Strong supported current content can replace stale interiors as well as edges;
flat regions retain Q. This is estimated selective reconstruction, **not physical
emission/reflection separation**. Accepting G can replace low-frequency lighting
differences too; the input does not expose verified separated layers.

The chromatic-recovery extension handles a different failure: Q can retain sharp
luminance while attenuating the same colour pattern. Luminance agreement and
`E=Vcr/(Vcr+Vr+T)` then suppress almost all restoration. The extension keeps the
base correction and both Anchor operations intact. It uses the existing moments:
`P=smoothstep(.80,.95,saturate(Ccp/max(sqrt(Vcr*Vcp),1e-12))) * Vcr/(Vcr+T)` and
`g=min(max(Ccp-Vcr-2*patchVariance,0)/max(Vcr,1e-6),2)`.
The predicted missing colour is `D=g*(highQ-luminance(highQ))`, so its luminance is
zero. Independent reference noise has no expected positive covariance gain over
an already-correct Q, although finite samples are not a perfect separator.

A single scalar ray limit in [0,1] keeps D inside the per-channel interval between
zero and `G-Q`; opposite-sign components stop the ray. It never expands G's
Anchor bounds or performs independent RGB clipping of this extra direction.
The additional correction is `strength*S*(1-A)*m*K*P*rayLimit*D`. Base and extra
corrections share the unit budget `(1-m*K) + m*K`; the result remains between Q
and G in each channel. It is zero when Mix/detail is zero, outside the selected handover domain or for routed content.
No resources, passes, history, root constants or quality controls are added.

Final composition also restores **supported luminance contrast**. SSIM's high
agreement is not proof that Q retains the reference's contrast, even when the
reference and Anchor views are sharp. The additional luminance path retains all
base decisions and the chromatic correction above. FP32 centred luminance moments
over the existing surface/routing-bounded 9x9 support corroborate the local 5x5
moments. Their samples overlap; they are not treated as independent observations.

Let `e=max(referenceMean9/max(QMean9,1e-6),1)`. Local and broad missing covariance
are `max(Cov-e*Vq-2*patchVariance,0)`; their variance-normalized gains are combined
with a minimum and capped at 2. This discounts uniform illumination/exposure gain
instead of labelling it as lost contrast. The broad affine-fit residual is
`R=max(Vp-Cov^2/max(Vq,1e-12),0)` and the loss evidence is missing broad covariance
divided by `max(sqrt(Vq*R),1e-12)`. Its permission is `smoothstep(1,2,evidence)`;
there is no division by sample count that would falsely shrink correlated grain.
Alignment permission is `smoothstep(.85,.97,min(rho5,rho9))`, multiplied by
`Vq5/(Vq5+4*patchVariance+1e-6)`. Missing luminance is predicted from Q relative to
its broad mean, not from the unexplained reference residual or mean brightness.

The chromatic candidate has already consumed part of the rejected-transfer budget.
The luminance ray is limited to the remaining interval in every RGB channel before
being multiplied by the same `strength*S*(1-A)*m*K` budget. The sum stays between
Q and G per channel; Anchor is not expanded. Both restoration terms use the same
domain/detail/Mix disable rules and noise-confidence tests. This is a heuristic contrast estimator,
not a physical separation of animated emission and reflected illumination.

`DetailPreservation` sets strength to `min(3*DetailPreservation,1)` on selected surfaces only.
The surface, noise and routing gates remain in force.
A supported reference envelope extended to include Q prevents bright overshoot/dark rings.
Zero detail leaves Q unchanged at output storage precision. The experimental TV
quadratic residual-grain correction and its diagnostic are removed along with Noise
Suppression. The base, chromatic and luminance terms remain; signed corrections stay FP32.
Final radiance is finite, nonnegative and FP16-bounded.

The material-type restriction in composition is removed. Uniform/planar guide
tiles share regional moment calculations; surface boundaries retain the full
weighted scan. Planarity includes affine reciprocal view depth, as needed for
perspective-projected TV planes, with a 2e-6 relative fit tolerance. Blur acceptance
tests the same nine bits together; quiet-pair selection takes one square root
after its minimum rather than one per direction. Blur probes and quiet-pair evidence reuse shared work. Temporal
helpers stabilize bounded decision weights only, with motion/depth/material and
current-content validation; they never expand the current Anchor interval.

## Resources and mirrors

Seed has 5 SRVs and 4 UAVs: base/sigma, R32 depth, gradient/oct-normal scratch and cleaned
reference/sigma. Filter has 4 SRVs and 1 UAV. Its colour buffers are reused by RR only after
conversion consumes Floor.

Conversion has 17 SRVs and 8 UAVs. t0..t8 are colour, canonical depth, motion, normals, roughness,
hit distance, diffuse/specular albedo and bias. t9 Floor; t10 inspector; t11 emissive; t12/t13
optional ray lengths; t14 raw title depth; t15 responsivity; t16 seed reference. Its final UAV
contains the reference with routing eligibility applied.

Composition has 11 SRVs and 3 UAVs: the existing eight inputs plus canonical
motion, previous decisions and previous metadata. Outputs are a dedicated
composition image, next decisions and next metadata. Motion is no longer reused
as output scratch. Disabled RR signals still bind their packed input signals.
The shared tile is 16x16 for an 8x8 group and four-pixel halo.

Four independent ping-pong history targets cost 48 bytes per allocated pixel;
the separate output adds 8 bytes/pixel. Together this is 49.22 MiB at 1280x720,
excluding alignment. History is allocated when detail is active, and committed
only at successful normal-frame completion. Reset, failure, debug/bypass,
configuration, dimensions or source-origin changes invalidate it.

Constant buffer sizes: Seed 176, Filter 32, Conversion 416, Composition 96 bytes.
Composition uses padded shared tiles. Temporal support adds no dispatch.
Groups without a selected screen return before neighbourhood loads/statistics;
ordinary pixels in mixed groups skip correction after the shared barriers.
Ordinary history is invalidated, so a later classification change cannot reuse it.
Subpixel reprojection bilinearly combines decision scalars only after every
contributing history tap passes depth, normal, material, albedo and colour checks.
A footprint touching a rejected tap falls back to current-frame decisions.

For current ST-only recovery, tagged decision-history RGB stores the independent
full reference mean and alpha its temporal deviation. Metadata.w stores the
slower broad reference band. Full reference colour, rather than that broad band,
is used for radiance acceptance. Both bands share the validated bilinear surface
reprojection; neither can survive a rejected footprint. Anchor and mixed
Anchor/ST pixels retain the original decision/filtered-colour layout. See
`fsrd_animated_recovery.md` for the radiance-animation regression and validation.
Invalid decision components remain invalid independently. FP16 motion errors
smaller than 0.001 pixel around integer coordinates snap to the integer footprint.
Performance has not been accepted in-game.
The verifier checks layouts, flags, debug reachability, SRV/UAV order, root-table counts and
albedo precision. Regenerate affected DXIL and embedded headers together.

## Controls and diagnostics

The experimental Floor RR Routing selector and Floor Zero Noise debug pass
have been retired at the user's request. `FloorRRRouting` is ignored and deleted
on normal settings save. Skip alpha is again diagnostic luminance only. There
are four production shaders; the extra Zero Noise PSO and shader artifacts are
removed. Existing surface identification and the selected-material roughness
compatibility treatment remain part of the normal Floor path.

Floor controls in [FSR-RR] are `FloorEnabled=true`,
`FloorDetailPreservation=0.35`, `FloorHandoverAnchorClamp=4.0` and
`FloorHandoverCorrelationMix=1.0`. The last two were restored at the user's request.
V10 adopts the user's preferred 4/1 setting as the default. Stored INI values are
not overwritten; CPU non-finite fallback and descriptor defaults also use 4.
Scalars are finite-clamped to [0,1], except anchor [0,8], before dispatch; non-finite
values use defaults. Changes invalidate RR history. The restored INI values are read and
preserved; 20 retired keys are removed on a normal save.
The manual Roughness Addition control is **removed**: `RoughnessFloor` no longer exists in the
config, the menu or the constant buffer, and its INI key is deleted on a normal save together
with the other retired names. The selected domain's RR roughness is now the packing shader's
own compatibility constant (`s_ZeroRoughRRRoughness = 0.1`), applied only while Floor is
enabled; with Floor disabled the title's roughness is published untouched. 0.1 is the value the
current comparisons were made with, not an established optimum and not an AMD threshold.
DemodDivisorFloor is independent and retained. Other legacy Floor controls, CorrelationBias and
ZeroRoughHandover are not read/migrated.

Advanced views show actual FloorColor, FloorResidual, FloorNoise, FloorExcess, DetailReference,
DetailConfidence and DetailCorrection, alongside RR diagnostics. Correction displays signed
data around grey 0.5 scaled by reconstructed luminance. Noise uses Turbo display mapping.
`DetailReference` displays the seed candidate before Anchor, also when detail strength is zero.
`FloorNoiseSuppression` is ignored and deleted on normal settings save; no replacement slider is present.
`DetailConfidence` includes the actual direct correlation term for the base transfer;
it is not the total permission of the chromatic extension. `DetailCorrection`
includes both corrections and the effects of Anchor, strength and the final envelope.
`ChromaRecovery` (composition mode 22) shows only the additional chromatic correction
before that envelope, encoded as `saturate(.5 + extra/max(luminance(Q),1e-3))`.
Neutral grey means zero; saturation limits its display range, not production radiance.
`LumaRecovery` (composition mode 23) uses the same encoding for the added luminance.
Both signed diagnostics must be included when reconstructing the final blend from
Anchor and the three base permission channels. `DetailCorrection` includes all terms.
`AppliedRoughness` (mode 22, formerly AppliedRoughnessFloor) visualises the actual automatic
increase, `max(0.1 - originalRoughness, 0)` on selected surfaces, zero elsewhere.
`MaterialType` / `RRMaterialType` and the red channel of `HandoverEligibility` show the
actual type-1 selection. No history-rejection view exists because this candidate has no detail history.

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

The post-checkpoint diagnostic modes expose the unfiltered seed reference, box/colour
Anchor candidates, independent handover permissions, limiter effects and pre-upscaler
composition. They observe the existing algorithm; no new quality gate or temporal
history is introduced. Their meanings, presentation differences and offline replay
are documented in [fsrd_floor_diagnostics.md](fsrd_floor_diagnostics.md).

Historical note (the NLM filter and its control are now retired): the subsequent
NLM detail fix capped corner-inflated zero-rough noise estimates using
surface-bounded quiet RGB pairs. It preserves explicit high uncertainty and the
Noise Suppression=0 path. Seed/base/conversion are unchanged. See
[fsrd_floor_nlm_recovery.md](fsrd_floor_nlm_recovery.md) for the estimator, measured
detail/noise tradeoff, historical test changes and game-acceptance limitations.

The following [chromatic-recovery change](fsrd_floor_chroma_recovery.md) preserves
that reference filter and adds only RR-supported missing colour contrast. Its
current-only tests separate luminance and colour error; optional A/B uses the
immediately preceding delivered NLM shader rather than only older V9/V10 builds.

The subsequent [final-composition contrast fix](fsrd_floor_composition_recovery.md)
addresses sharp reference/Anchor views followed by a blurred final blend. Its tests
separate pure illumination gain from blur and include additive/multiplicative coarse
grain. The initial contrast-only prototype failed those noise tests and is not shipped.

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
- **The bounded noisy ceiling is heuristic.** Repeated colours veto relaxation
  to protect thin text. Unsupported noise can therefore survive; allowing Floor
  above a noisy raw sample also creates measured positive excess. The full-chain
  grain and clean-stroke tests cover this tradeoff, but game validation is required.
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
- **Temporal helpers stabilize decisions only.** They are not a solution for
  radiance noise already shared by Skip and RR. Primary surface motion cannot
  track all reflections or animated texture changes; the content check rejects
  clear changes, but game validation is still required. The earlier unsuccessful
  full-correction-history experiment is not the production algorithm.

Game acceptance still requires both titles' static/pan/object/text/reflection/
particle captures, flat-region noise/flicker measurements, clean-edge contrast
and checks for new trails/halos. Performance optimization follows quality for
this iteration, per the user's instruction. No game acceptance or successful
temporal A/B is claimed by the standalone GPU tests.
## Virtual albedo experiment retired

The virtual albedo runtime, menu toggle, carrier views and history resources
were removed after in-game blur/noise feedback. The established spatial Floor
and Anchor/Correlation composition remain. `FloorVirtualAlbedo` is ignored and deleted on normal INI save.
Albedo structure remains a diagnostic surface cue, not a generated RR material.
See [the retirement decision](fsrd_virtual_albedo_retirement.md) and
[the archived noise audit](fsrd_virtual_albedo_noise_audit.md).
