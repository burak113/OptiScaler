# Spatial volumetric retention and visibility continuity

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

**Rejected after game feedback.** The ridge recovery and quiet-end filtering
described below preserved spatially correlated noise as well as light. They have
been removed. Only the smooth support transition and screen history footprint
validation remain. See [correlated grain regression](fsrd_correlated_grain.md).
The measurements below document the rejected candidate, not current production.

This candidate follows the accepted screen-only handover build. Its frozen shader
baseline is `tools_tmp/volume_visibility/baseline/precompile`. The priority is
ordinary-surface Floor/Skip light preservation; selected screens still send the
full signal to RR and receive the existing Anchor, Correlation Mix, luma and
chroma recovery. No control or texture is added.

## Changes

The lower-quartile seed can erase a narrow sustained light even when independent
samples along it agree. Four directions now inspect offsets -2/-1/0/1/2. The
componentwise minimum, reduced by the measured noise margin, can raise the
quartile pedestal. Every independent sample must carry that common light;
isolated impulses and 2x2 clusters cannot supply it. Surface weights control the
contribution. This also retains narrow ordinary radiance structure: it is not
an emissive/volume semantic classifier.

The Floor filter previously treated local light contrast as uncertainty, then
spread it into nearby darker pixels. With complete guide support the base now
uses the smaller of IQR and the existing mixed-derivative noise estimator.
Directional continuation can reduce uncertainty further. All five strides can
leave quiet input unchanged, and pairwise appearance tolerance uses the smaller
endpoint tolerance. The four-neighbour surface-aware filter remains in place.

An independent visibility fixture exposed a hard five-effective-sample switch:
with fixed RGB, a small change in normal support jumped the seed from 0.06 to
0.30. The common-light fallback now transitions continuously between five and
nine effective samples. This removes that particular source of exposure flicker;
it does not prove that every in-game disocclusion artifact has the same cause.

Screen decision history previously sampled the nearest reprojected pixel.
It now validates every contributing bilinear tap before interpolating decisions.
Depth, normal, roughness, material class, albedo, colour, bounds and validity
must agree. A newly exposed footprint touching an old occluder rejects history.
Negative component sentinels remain independent. Only decision scalars are
blended: no previous RGB is accumulated by this change.

## Tests and rejected approaches

`test_fsrd_volume_visibility.py` executes production DXIL on D3D12. Analytical
light profiles, impulse/cluster noise, random grain, a colour ramp, a black
foreground silhouette, guide-support transitions and fractional reprojection
have independent expected properties. Optional `--baseline` runs the same inputs
through frozen prior shader bytecode. The normal validation runner includes the
standalone properties.

A threshold-based ridge classifier looked good on clean images but amplified
temporal variation when independent noise moved it through its confidence
threshold. It was rejected. The common lower-envelope estimator is tested with
eight independent frames at each of three noise amplitudes, including the
previously failing cases. Test results are estimates on these fixtures, not
percentages of game-wide visual quality.

`probe_fsrd_volume_temporal.py` is an offline preflight: production spatial GPU
outputs feed CPU prototypes with two/four effective history frames, neighbourhood
clipping and colour-change rejection. It deliberately separates surface motion
from volume motion and includes a disappearing light. It is not a GPU temporal
implementation and cannot establish its runtime cost or game behaviour.

## Delivery validation

The final generated shaders pass mirror verification, Release x64 and 755 checks
over 1,577 D3D12 dispatches with the debug layer. The DLL contains the validated
DXIL. Historical archive comparisons requiring packages not supplied to the
runner are explicitly skipped; this turn's frozen accepted DLL is independently
verified to contain every A/B baseline shader byte sequence.

The same-input GPU A/B reproduces a seed support step of 0.24005 in the baseline
and at most 0.00043 in the candidate. On the clean narrow vertical/horizontal
Gaussian fixture, peak light retention rises from about 0.13% to storage-precision
100%; the narrow 45-degree case retains about 82.6%. These are deliberately hard
synthetic lower-quartile cases, not average game improvements. At a 23-degree
angle and width 3 pixels, retention rises from 44.2% to 89.8%. The tested profiles
have no increased halo versus the baseline.

For the eight-frame narrow vertical light with independent RGB noise sigma
0.003/0.01/0.03, retained light is 97.2%/90.8%/72.1%. Output temporal standard
deviation is 0.00110/0.00386/0.02027 versus input 0.00282/0.00939/0.02818.
Random positive-grain RMSE is effectively unchanged (0.014300 versus 0.014288);
this change does not claim general-purpose stronger denoising.

The fractional screen-history fixture rejects an old occluder even when its
nearest tap matches. A decision checker sampled at offsets 0.49/0.51 pixels has
a maximum decision jump of 0.001465 versus 0.080078 with the old point sample.

The final temporal preflight reduces static error variation by about 38% with
two effective frames and 54% with four. However, four frames increase moving
volume RMSE by 2.34% and moving-background RMSE by 2.54%; the disappearing light
retains up to 0.00215 extra radiance in the first off frame. Even two frames add
0.00143 on that transition. Therefore **no Floor RGB history is shipped**. The
existing screen decision helper remains, with the footprint validation fix.

## Performance and package

RX 9070, 1280x720, Detail Preservation=1, Anchor=4, Mix=1, temporal helpers active,
0.37-pixel horizontal history offset: three alternating paired trials, ten
warm-ups and 600 timed dispatches per stage. Median of trial stage-summed medians:

- Ordinary geometry: 0.88388 -> 1.08360 ms (+22.60%); corresponding stage-summed
  p95 statistic 0.92640 -> 1.10828 ms.
- Mixed scene: 1.51880 -> 1.77320 ms (+16.75%); p95 sum 1.56772 -> 1.80180 ms.
- Full-screen selected surface: 3.34992 -> 3.77516 ms (+12.69%); p95 sum
  3.42368 -> 3.85108 ms.

Seed accounts for approximately 0.18-0.20 ms additional work. Composition changes
from 0.06156/0.60760/2.10316 to 0.06300/0.66776/2.33924 ms for those cases.
Fractional history reads are intentionally exercised; a zero-motion-only timing
would miss their cost. These sums are per-stage timing summaries, not actual
end-to-end frame p95. They exclude RR inference/upscaling. This is a quality
change with measurable cost, not a lossless optimization. VRAM allocation and
dispatch count are unchanged.

Reports: `tools_tmp/volume_visibility/validation_delivery/summary.json`,
`probe_final/volume_visibility/results.json`,
`temporal_final/volume_temporal_preflight/results.json`,
`benchmark/summary.json`. Package: `tools_tmp/volume_visibility/delivery/dxgi.dll`.
SHA-256: `8fd9441abd611c6742c9ab48d24f2e7fb91d25af1f43155dc48b1d2ab3c63422`.

Game acceptance should compare the same normal-surface light beam/volumetric
scene while stationary and during the camera pan that reveals new background.
Also check a dark TV and animated sign to ensure the established screen recovery
has not regressed. Prefer normal output and separate Floor/Skip observations;
debug selection resets history, so debug toggles are not temporal A/B evidence.

Very narrow oblique light, incomplete surface support and high noise remain
conservative. The pedestal is still an estimate of common light, not a recovered
physical volumetric component. True AMD RR inference and game acceptance are
outside these synthetic shader tests.
