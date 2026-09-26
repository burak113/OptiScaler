# Spatial/temporal recovery: noise-return guard

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

The September 25 change responds to Screenshot (837): specular recovery adds
coarse grain to walls and floors, especially during camera movement. The previous
synthetic tests established improvement relative to a noisy reference. They did
not adequately require recovery to preserve an already denoised RR result when
the reference noise estimate was missing or too small.

## Failure reproduced

The previous production composition shader fails all five new absolute
noise-return cases: independent grain, rejected history, zero noise-estimate
alpha, correlated grain, and positive impulses. Zero alpha was treated as clean
input. A large reference-to-RR difference also passed the delta limiter more
easily, even when that difference was noise.

These are synthetic reproductions of failure modes, not a replay of the game
frame. No AMD neural-denoiser execution or in-game acceptance is implied.

## Change

The spatial/temporal algorithm keeps its existing geometry-bounded spatial
filter, wider correlated-noise estimate, reprojection validation and history
clipping. The existing 3x3 footprint additionally measures:

- RGB covariance and variance of the RR result and the reference, to reject
  unsupported detail and excessive contrast amplification from a flat RR patch.
- Three residual modes of a local quadratic fit, to distinguish fine random
  variation from smooth curved structure. This also prevents correlation from
  accepting noise shared by RR and the reference.
- Independently measured quiet structure, so zero alpha alone no longer
  authorizes unfiltered transfer, while clean straight edges remain recoverable.

Validated history progressively relaxes the spatial evidence requirement. History
rejection immediately removes that accumulated support. It does not reuse an old
final image or introduce another temporal buffer. Reprojection, animation and
disocclusion rejection remain in force.

This adds nine RR reconstructions to the existing local footprint, with no new
dispatch, texture, allocation, constant-buffer field or user setting. It applies
to all recovery paths assigned the spatial/temporal algorithm. The separate
Anchor/Correlation algorithm and the recovery-zero path are unchanged.

## Validation and limits

`test_fsrd_specular_noise_return.py` adds absolute MSE and 99th-percentile error
budgets against known clean truth, including zero/underestimated alpha, camera
translation, invalid motion, outliers and correlated grain. It also checks that
shared residual noise is not amplified and useful detail can still be recovered.
This suite is registered in `validate_fsrd.py`.

The guard deliberately favors RR when the reference lacks supporting evidence.
It can therefore recover less detail from genuinely difficult, noisy regions.
It does not remove all noise already present in RR. Smooth coherent lighting
noise can remain ambiguous with real detail. Specular recovery still uses a
combined reference with estimated RGB lobe shares, not an isolated raw specular
radiance buffer. A successful synthetic suite is not proof that Screenshot (837)
is fixed in Cyberpunk.

Reports and the candidate DLL are under
`tools_tmp/spec_recovery_guard/`; the frozen previous shader is in `baseline/`.

## Measured cost

RX 9070, 1505x847 synthetic full-frame workload, D3D12 GPU timestamps, reversed
baseline/current execution order for confirmation:

- Spatial/temporal without history: 0.936 -> 1.090 ms.
- Spatial/temporal with valid history: 1.180 -> 1.426 ms.
- Anchor only: 2.893 -> 2.923 ms; output remains bit-identical.
- Recovery disabled: 0.06048 -> 0.06036 ms; output remains bit-identical.
- Mixed Anchor and spatial/temporal: 3.866 -> 4.011 ms.

This is an additional 0.15-0.25 ms for the tested spatial/temporal workloads,
not a performance optimization or an in-game FPS prediction. Timings measure
composition only, not the entire Floor/RR/upscale pipeline.

## Final quality results

The final production shader passes 282 checks across 1,047 GPU dispatches with
the D3D12 debug layer enabled and zero validation errors. Release DLL shader
embedding is checked byte-for-byte against the tested CSOs.

The new clean-RR noise-return fixtures stay within their absolute error budgets,
including zero-alpha smooth noise without usable history. Shared residual-noise
MSE is 0.0001967 versus 0.0002242 in the supplied RR result (no amplification).
The noisy-detail fixture improves damaged RR MSE from 0.0008638 to 0.0002206.

This is not a universal quality improvement over the previous production shader.
In the existing correlated-noise suite, static/reveal MSE increases about 3%,
and the real-seed case about 6%; its flicker metric increases about 11%.
Integer and subpixel camera-pan flicker improve about 8% and 18%, respectively.
The perfectly clean broad-correction fixture changes from near-exact recovery
to MSE 0.00000779, remaining below its 0.00003 budget. These regressions are
recorded rather than relabeled as improvements: the guard trades some uncertain
recovery for protection of the RR result. The game screenshot still requires
an in-game A/B assessment.
