# Animated radiance recovery

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

Screenshots 843 (Anchor) and 844 (Spatial+Temporal) show the latter losing water
detail. Composition ablations reproduced a related regression when geometry and
its motion vectors remain stationary while the reflected radiance moves.

The previous ST path increased colour history to 15/16 and allowed raw reference
moments the same history weight at integer coordinates. The subpixel safeguard
only noticed camera motion, not animated/reflected radiance. Even with valid
surface reprojection, this averages different phases of a moving wave.

In the slow animated known-truth fixture, previous contrast is 58.35%, old strong
recovery 75.81%, and a diagnostic 50% history cap 83.30%. Disabling spatial
smoothing alone gives 58.63%; forcing recovery confidence to one gives 58.74%.
Disabling all history also fails (56.72%). These ablations identify radiance
history as the dominant loss here rather than simply an oversized spatial kernel.
The synthetic Anchor fixture is not a faithful model of the game's Anchor result;
it is not used to claim superiority over Anchor in Cyberpunk.

## Change

Current spatial coherence, agreement with RR and missing RR contrast select a
responsive detail-history cap between 15/16 and 0.02. Unsupported radiance and
already-strong RR contrast retain the longer accumulation. The minimum temporal
support scale adapts with the cap; noise sample count follows the actual weight.

The broad component uses the already-read surface-aware radius-three footprint
(centre weight four, eight neighbours weight one). It has a separate slower
history cap, between 15/16 and 0.65. Its temporal innovation is subtracted from
the fast full-reference update, avoiding the broad noise increase of simply
shortening all radiance history. Rejected surface taps contribute the centre,
not another surface's radiance. This is a separation of temporal bandwidths,
not an unfiltered detail bypass or an increase in the recovery slider.

No allocation, dispatch or history-neighbour fetch is added. ST-only metadata.w
now contains the packed broad reference; tagged decision-history RGB contains
the full independent reference mean. History radiance acceptance tests that full
mean. Both states use the same validated centre reprojection, including every
nonzero bilinear tap's geometry, material and albedo checks. Alpha remains the
tagged temporal uncertainty estimate; the band-split update is not claimed to
be an exact independent-sample variance estimator. Anchor and mixed Anchor/ST metadata semantics stay
unchanged. Newly rejected history contributes neither colour band.

A broad lighting change can outlive the current local pattern. The full
reference state and displayed candidate are therefore bounded to current spatial
support, including its noise allowance, before that state can feed another frame.
The packed broad state retains the existing 11/11/10 precision; small static
colour error is measured in the stable-bias fixture, rather than assumed zero.

Short accumulation must not inherit long-history noise confidence. For accepted
history without independently proven temporal detail, the residual noise gate
is bounded by measured fine noise, weighted
by the lack of spatial coherence. This addresses underestimated seed alpha.
Surface rejection, Anchor decisions, passes, bindings, recovery weights and
albedo conversion are unchanged. Tests explicitly corrupt the cached broad
history, including a fractional footprint's non-nearest tap, to ensure geometry
rejection prevents it from contributing colour.

Unconditionally shortening history failed the shared-noise budget and was not
selected. Tightening radiance history acceptance to seed-alpha noise alone also
lost detail during subpixel camera motion and was not selected. Fetching eight
neighbouring histories preserved sharpness and noise but increased the active
composition case from about 1.5–1.7 ms to 3.5–4.0 ms; it was replaced with the
cached broad state above. These are synthetic 1505x847 RX 9070 timings.

The new GPU suite covers static detail, two radiance animation speeds, combined
fractional camera/radiance movement, and the actual FloorSeed reference. Specular
demodulation is enabled to match the submitted screenshots. It measures error and
phase-sensitive contrast against clean truth and compares the old frozen shader.
Existing absolute noise budgets and sharpness checks remain required. The
correlated-noise fixture additionally compares error energy and temporal RMS
to the immediately preceding build. The budgets are +10% error energy and +15%
temporal RMS, not a claim of identical noise in every case. The separate broad
noise test retains its tighter existing +4% energy/flicker budget.

All measurements are synthetic composition-DXIL results. AMD RR is not executed
by these fixtures; Cyberpunk visual acceptance still needs the same-scene A/B.

## Final validation

The Release DLL embeds the verified production shaders. All 385 checks across
2,120 GPU dispatches passed with the D3D12 debug layer enabled and no validation
errors. Results and hashes are recorded in
`tools_tmp/recovery_wave_detail/delivery/validation.json`.

With specular demodulation enabled, phase-sensitive contrast is 0.829 for slow
waves versus 0.758 in the older strong recovery, 0.707 versus 0.746 for fast
waves (94.7%), and 0.758 versus 0.784 with fractional camera movement (96.7%).
The real FloorSeed variant reaches 0.829 versus the older 0.735. These are
synthetic contrast ratios, not percentages of image quality in Cyberpunk.

Relative to the immediately preceding installed build, correlated-noise error
energy stays within +2%; temporal error RMS increases by 6.3–10.0% across those
fixtures. Thus this is not a claim of unchanged noise. The separate broad-noise
case has essentially unchanged error energy and lower temporal flicker. All
existing absolute noise-return and disocclusion budgets still pass. Quantized
broad history leaves stable-bias MSE around 3.9e-6 in its dedicated fixture.

RX 9070, 1505x847, reverse-order confirmation: composition with active history
costs 1.86 ms versus 1.53 ms previously; fractional supported motion costs
1.94 ms versus 1.66 ms. The extra cost is about 0.28–0.33 ms for these fully
selected synthetic cases. Without history it is 1.17 versus 1.14 ms. Anchor
and mixed results remain around 2.9 and 4.0 ms. This is composition timing,
not the complete in-game upscaler time shown in screenshots.

For visual acceptance, keep the same sea scene, resolution, demodulation and
Floor Recovery settings, then compare Specular Recovery's Spatial + Temporal
against Anchor. Check stationary waves, a slow pan and newly revealed water;
these game results have not been verified by the synthetic harness.
