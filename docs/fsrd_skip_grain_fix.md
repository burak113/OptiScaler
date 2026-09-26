# Skip grain repair and perspective-screen composition

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

This follows the `composition_temporal` delivery. The reported game regression
was real: the full-screen handover scope costs more on ordinary materials, and
the earlier fast-path benchmark did not represent game guides well enough.
No Anchor, Correlation Mix, luma/chroma recovery or temporal decision feature is
removed in this fix. No new averaging pass, UI control or resource is introduced.

## Grain source

Conversion used `min(filteredFloor, rawColour)` on selected/zero-rough surfaces.
This put negative raw noise excursions back into Skip after the spatial filters.
Composition includes Skip in its RR reconstruction, so both its anchor and its
correlation statistics could see the same grain. More aggressive handover alone
cannot reliably remove that shared error.

The ceiling now has a bounded noise allowance. It requires agreement between
the seed IQR and reference uncertainty, protects repeated-colour strokes and
endpoints, and fades out for deep per-channel valleys. It changes the ceiling,
not the reference texture, and adds no neighbour radiance. Deep unsupported
excursions can remain: removing them unconditionally also fills dark text.

Explicit bias/responsivity routing and the demodulation closure remain intact.
Noisy Floor can exceed the raw sample by the allowed amount; FloorExcess reports
this positive difference and identity reconstruction accounts for it explicitly.
The fix is not a claim of exact energy conservation on those pixels.

## Performance work

The planar-tile certificate now recognizes affine reciprocal view depth. View
depth itself is generally not affine on a perspective-projected planar TV.
The previous certificate therefore sent tilted displays down the full weighted
scan despite their planar geometry. Reciprocal-depth fitting has a relative
2e-6 tolerance; material/normal/routing discontinuities retain the fallback.

The same nine blur-acceptance bits are tested together, and quiet-pair evaluation
takes the square root after finding the minimum squared difference. A CPU
property test compares the mask operation against all nine original tests on
20,000 masks at every offset. The actual GPU parity tests include perspective
depth, both depth signs and three exposure scales.

Two experiments were rejected: unrolling the full weighted regional scan, and
sharing separable weighted regional moments on arbitrary guides. Both were
slower in the actual GPU measurements. Neither is in the delivered shader.

The corrected benchmark supplies composition with actual quantized conversion
albedos, rather than a white albedo. It measures history reads/writes in both
variants and includes changing albedo, curved normals/depth and perspective
planes. All benchmark RR inputs are synthetic; AMD inference and the upscaler
are not measured. A stage-summed p95 is not the p95 of a complete frame.

## Quality evidence

`test_fsrd_skip_grain.py` executes the production seed, five spatial filters,
conversion and composition. It tests negative noise excursions, explicit excess
closure, clean and noisy dark strokes, independent ideal residual radiance, and
four frames of correlated RGB illumination grain on a reflected ramp.

Measured full-chain Skip variance fell from 0.0001395187 to 0.0000040990
(97.1% lower). Correlated illumination-grain temporal variance fell from
0.0000531788 to 0.0000026065 (95.1% lower). These are synthetic variance metrics,
not percentages of perceived grain removal in Cyberpunk. The noisy-letter
positive lift was 0.00594; a rejected intermediate version raised it to 0.04390.
Existing clean text and contrast-recovery acceptance thresholds were retained.

Game acceptance remains pending on the supplied TV scene. Compare SkipSignal
and None at the same camera/settings, including Detail Preservation=1 as shown
in the report. Anchor=4 and Correlation Mix=1 remain supported. Debug views
invalidate decision history; return to None to evaluate the temporal helper.

## Release measurements and validation

The final paired benchmark is `tools_tmp/skip_grain_optimization/release_benchmark`.
RX 9070, 1280x720, three trials per fixture, ten warm-up and 600 timed dispatches
per stage. Both variants include temporal helper reads/writes. Values below are
medians of trial medians, in milliseconds:

- Perspective screens: composition 4.1988 to 2.33296; stage sum 5.43044 to
  3.61032. Composition is 44.4% lower; the stage sum is 33.5% lower. Median trial
  composition p95 is 4.33128 to 2.37520.
- Varying ordinary albedo: composition 4.84848 to 4.59004; stage sum 5.67372 to
  5.41288. This fixture's complete stored outputs are unchanged.
- Curved screen guides: composition 4.50296 to 4.12372; stage sum 5.75452 to
  5.41544. The curved-guide fallback remains, so the gain is smaller.
- Frontal screens: composition 2.42848 to 2.33800; stage sum 3.63416 to 3.58040.

These do not establish a game-wide speedup or recovery of all the cost of the
previous full-screen scope expansion. The most relevant gain is the perspective
TV case. The current conversion includes the extra stroke-protection lookups.

`validation_final/summary.json` passed 676 checks and 1,251 GPU dispatches with
the D3D12 debug layer, mirror checks, four shader compilations, Release x64, and
verification that the DLL embeds the tested bytecode. Optional older reference
packages were absent and their historical comparisons were skipped; the paired
benchmark against the immediately preceding delivered shader did run.

DLL: `tools_tmp/skip_grain_optimization/delivery/dxgi.dll`.
SHA-256: `3ab979cef7215a0786835030dcdf0b7e4f11b52d1d24a0cbdd7017c07b8a577d`.
