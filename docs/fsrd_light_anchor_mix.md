# Light Anchor Mix (Specular/Diffuse Noise Removal)

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

The Spatial + Temporal recovery method is replaced by the Light Anchor Mix, a
heavily optimized form of the Anchor/Correlation/Chroma/Luma method. The change
answers the standing complaint that recent builds looked increasingly blurry:
the Spatial+Temporal filter reconstructed detail by averaging the reference
over a 3x3 neighbourhood, four radius-three colour pairs and up to sixteen
accumulated history frames. Each correction round (coarse noise pairs, noise
guards, contrast-cap relaxation, temporal evidence, broad-band split,
responsive caps) added more averaging or more history, and animated radiance
kept being phase-averaged into blur. None of it produced the sharpness of the
Anchor method the user preferred in same-scene screenshots.

## Principle

The current-frame reference is the only detail source. It is never averaged
with neighbours or previous frames. This removes colour-history phase averaging;
it does not guarantee unchanged sharpness because noise gates and clamps can
still attenuate legitimate detail. The colour source follows the current frame
and has no colour-history warm-up. The neighbourhood
supplies statistics only:

- **Anchor.** The transferred colour is clamped into RR's local mean and
  variance (per channel; the full covariance rotation remains with the
  handover Anchor algorithm). Grain, coarse excursions and impulses RR does
  not carry collapse back toward RR's value. The clamp relaxes toward the
  reference's own noise-free structure variance only when RR's local pattern
  corroborates it (attenuation evidence), never for unexplained variance.
- **Correlation mix.** A reference that locally agrees with RR adds grain, not
  structure, and the transfer scales down by the user's mix. Reference
  contrast persistently above RR beyond the measured noise is treated as
  attenuation, not disagreement, so blurred RR does not block its own
  recovery. A patch that measures clean - quiet seed alpha plus five of eight
  quiet colour pairs - opts out entirely: clean edges and lettering transfer
  unclamped at full weight.
- **Chroma / luma.** Contrast extensions amplify RR's own local colour and
  luminance pattern when the correlation shows RR attenuated it, bounded by
  the anchored candidate and by whatever transfer headroom the base already
  consumed. They cannot add contrast on top of an exact transfer.
- **Noise floors.** Seed alpha is authoritative when it measures noise. Two
  single-frame witnesses catch an alpha that lies: the quadratic-residual
  floor (grain is nothing but residual; straight edges and linear gradients
  cancel) and, for smooth excursions the 3x3 cannot see, a wide-tap floor on
  quiet patches (iid grain at >3px scale, exempting RR-corroborated content).

Retained from Spatial+Temporal as statistical safeguards: surface-bounded
statistics (depth/normal/material weights), the residual-noise limiter that
keeps reference grain out of an already clean RR result, the supported-range
clamp, and gate-only radius-three reference taps (the retired wide pairs could
contribute colour; these cannot). No history is read; filter pixels still
store valid metadata colour so neighbouring Anchor reprojection can
cross-validate. No new textures, passes, constant-buffer fields or settings;
the "Spatial + Temporal" menu entry is now "Light Anchor Mix".

## Validation

Full suite: 873 GPU checks across 2268 dispatches passed with the D3D12 debug
layer enabled. The absolute noise-return budgets of the specular suite are
unchanged and pass (zero-alpha grain, coarse grain, impulses, shared
RR/reference noise). The ST-machinery suites (coarse-noise accumulation,
broad-band split, temporal evidence tags) are retired; the animated-recovery
suite now also proves the filter is history-blind under every corruption.

Recalibrated for the new algorithm, with rationale in the suites: contrast
budgets on severe-blur fixtures (the old values required the removed temporal
accumulation; a 5px diagonal pattern's curvature also feeds the residual noise
floor, the only single-frame witness of an alpha lie). Phase-sensitive wave
contrast measures 0.67 identically at every animation speed - no phase lag by
construction - against the old strong recovery's 0.71-0.83 with phase error.

Timing (RX 9070, 1505x847, composition dispatch only, both orders confirmed):
Light method with valid history 0.95 ms versus 1.52-1.60 ms before (-38 to
-40%); without history 0.95 versus 1.13 ms (-16%); history now costs nothing.
Mixed tiles 3.82-4.08 versus 3.99-4.08 ms. Anchor-only and disabled cases are
unchanged. These are synthetic stage timings, not in-game measurements; AMD RR
is not executed by the fixtures and Cyberpunk acceptance remains a same-scene
A/B for the user.

## Pedestal sparkle stain (same-day follow-up, REVERTED)

An in-game residual bright stain on dark water was traced to the Skip signal:
the spatial floor's robust base pooled dense specular sparkle as if it were
volumetry, and the Floor passes smeared that elevation into a broad patch plus
a halo. A synthetic reproduction confirmed the mechanism (85% glint coverage:
lane pedestal 0.234, edge halo 0.089 over a 0.015 dark-water pedestal), and a
seed gap-split plus an asymmetric Floor window reduced it (0.103 / 0.035) with
878 checks green.

In-game testing REJECTED the fix: the darker pedestal handed more content to
RR and small dark noise covered the scene. Both shader changes were reverted
the same day; the historical suite is test_fsrd_floor_glint_pedestal.py. The
user's decisive in-game finding stands: setting Specular Albedo Demodulation
to 0 removes the stain, which implicates the specular conversion/routing path but does not establish
one arithmetic operation as the sole cause. DemodDivisorFloor
remains the existing clamp knob for that path.

## DemodRisk diagnostic view (follow-up)

The RGB prototype described in earlier versions of this report was superseded
by the [white boundary diagnostic](fsrd_demod_risk_white.md). It is read-only in
the current checkpoint. Slider A/B also changes Floor routing, so the observed
improvement does not isolate a single division operation or establish NVIDIA's
internal treatment of these particular game inputs.
