# Recover detail missing from the RR result

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

The previous noise guard (including the September 25 contrast-cap relaxation)
still suppressed detail that did not correlate with the already blurred RR
image. Requiring RR to confirm a pattern that RR removed is not sufficient.

Spatial/Temporal recovery now also measures the reference independently across
validated frames. On pixels with only Spatial/Temporal recovery, the existing
decision-history texture stores a raw-reference mean and temporal variance.
The negative alpha tag distinguishes these statistics from Anchor decisions;
tagged values cannot be reused as Anchor decisions. Mixed Anchor/ST pixels
retain the previous conservative path because Anchor owns the decision slots.
This is a per-pixel restriction, not a full-tile or full-screen restriction.

Variation across frames is compared with variation within the current
geometry-bounded local and wider footprints. A stable detailed pattern may
recover even if RR has no contrast there. Randomly changing illumination has
high temporal variation and remains subject to the previous noise guard.
Evidence ramps between four and eight accepted frames. Missing/invalid motion,
disocclusion, changed normals/materials and rejected colour history invalidate
the evidence. No-history behaviour is unchanged.

The temporal mean is independent of the already spatially blurred history.
At fractional pixel motion its accumulation weight is reduced to avoid repeated
bilinear resampling erasing detail. The estimated mean noise also accounts for
this shorter accumulation, rather than pretending all sixteen frames survive.
Temporal standard deviation is encoded with extra scale in the FP16 alpha
channel to avoid quantizing small variances to zero. Unrepresentable HDR
statistics are rejected. No extra texture, rendering pass or UI setting is added.

Floor Recovery strength, the volumetric base and Anchor/Correlation/Luma/Chroma
controls retain their existing roles. This change targets Spatial/Temporal
recovery; it does not replace the separate Anchor algorithm.

## Validation scope

The new `test_fsrd_temporal_detail_evidence.py` uses known clean truth, actual
composition DXIL and sequential GPU histories. It covers detail entirely absent
from RR, tile patterns, fractional camera motion, chromatic detail, already sharp
RR plus a noisy reference, and rejection of mature history on depth/motion/
animation changes. Its optional historical comparison uses the old strong
Spatial/Temporal shader, before the later noise guards.

These are synthetic composition tests, not execution of AMD's neural denoiser
and not in-game visual acceptance. Motion vectors that do not track a reflection
or repeated changes to its guides can still prevent independent recovery from
accumulating. Newly visible regions intentionally retain the conservative guard.
Persistent noise that looks stable over the observed frames is a remaining risk.

Frozen baselines, experiments, validation and delivery artifacts:
`tools_tmp/recovery_temporal_evidence/`.

## Release results

The final production shader passed 335 checks over 1,591 GPU dispatches across
nine suites, with D3D12 validation enabled and zero errors. The Release DLL
embeds the tested shader bytecode. Tests include the existing recovery controls,
Anchor temporal decisions, luma/chroma recovery, volumetric visibility, coarse
noise, specular noise return, and weak-detail contrast suites.

Measured contrast relative to known clean truth, new versus old strong recovery:

- Detail absent from RR: 77.57% versus 78.24%.
- Small tiles: 79.55% versus 80.08%.
- Fractional camera motion: 73.74% versus 70.89%.
- Chromatic pattern: 81.67% versus 81.71%.

These are synthetic signal ratios with an 80% specular share, not percentages
of perceived game sharpness. When RR is already sharp, the noisy-reference
fractional-motion case has MSE 0.0000742 versus the old strong shader's 0.001240.
It still loses some contrast (95.5% retained); this is not a universally lossless
detail reconstruction.

Against the immediately preceding quieter build, the original noise-return
fixture's shared-noise MSE increases by 0.38%, remaining below the supplied RR
error. Independent static grain MSE increases from 4.95e-9 to 5.02e-8, still far
below the unchanged absolute budget. Rejected-history, zero-alpha, coarse
rejected-history, smooth zero-alpha and impulse errors are unchanged. Restoring
detail is therefore not literally noise-identical to the previous build.

Two order-reversed RX 9070 composition benchmarks at 1505x847 measured:

- ST without history: previous 1.09-1.16 ms, new 1.22 ms.
- ST with valid history: previous 1.42-1.50 ms, new 1.57 ms.
- Anchor: previous 2.91-2.93 ms, new 2.95-2.96 ms.
- Mixed full-frame Anchor/ST: previous 3.93-4.01 ms, new 4.08-4.10 ms.

The independent evidence costs approximately 0.07-0.15 ms with valid history
in these synthetic runs. There is no additional allocation or pass, but there
is additional arithmetic. These timings do not promise a particular game FPS.
