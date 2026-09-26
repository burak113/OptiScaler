# DemodRisk: white intersection diagnostic

This revision replaces the earlier RGB display with grayscale. Bright white
means added normalized signal structure and divisor risk agree in the same
RGB channel. Isolated green/turquoise or red/magenta evidence is no longer
displayed. Black means no strong joint evidence, not verified correctness.

The diagnostic uses the pre-split raw colour and independently evaluates the
albedo-only specular split/demodulation chain. It mirrors the emissive albedo
rewrite, overshoot handling, UNORM quantization, split ramp, separate specular
divisor floor. The current baseline evaluates full specular demodulation
independently of the slider. It does not
simulate Floor subtraction, signal routing, temporal reuse, or AMD RR itself.
In particular it is not a measurement of the final neural-denoiser input.

Spatial divisor ranges and normalized gradient increases are evaluated per
channel; constant chromatic differences between R/G/B are not spatial variation.
Channel contributions are weighted by input radiance and exclude absent signal.
A relative-energy increase must also have a nontrivial absolute increase in
mean-normalized gradients, limiting near-zero ratio false positives. Both
criteria must overlap in the same channel to contribute to white.

Far-plane centres are black; far-plane neighbours are replaced with the centre.
Changing the global slider does not change this baseline diagnostic. The footprint remains 5x5 with one- and
two-pixel gradient differences. Broad, flat blob interiors remain a blind spot;
geometry/material boundaries and stochastic input can still produce false
positives. This is a diagnostic hypothesis, not an automatic correction mask.

Only the debug branch changed. No recovery settings or normal rendering
algorithms were modified. Compilation and installation were requested without
validation: no tests, mirror verifier, GPU runs, benchmarks, or visual acceptance
were performed. Previous RGB diagnostic test expectations are superseded by
this display contract and have not been updated or run in this build.

## Boundary selectivity follow-up

The white intersection is now additionally gated by signed-gradient coherence
and by coherent boundary contrast added relative to the pre-split raw colour.
The same 5x5 samples are reused: random alternating excursions cancel in signed
X/Y sums whereas a consistently oriented transition contributes. The gate is
in [0,1] and only attenuates the previous mask; it does not add candidate pixels.
This is intended to reduce the grain/texture patches seen around the captured
sea boundaries. It is not temporal stabilization, a water-material classifier,
or proof of a demodulation defect. Thin paired edges, noisy genuine boundaries,
and small closed shapes can also be suppressed. No geometry veto was added:
the guide discontinuities themselves may coincide with the targeted sea blobs.
No extra texture fetches or history resources were added. This follow-up is
also compile/install only at the user's requested no-validation stage; its
in-game selectivity has not been confirmed.

## Current checkpoint

The no-validation statements above refer to the original diagnostic-only builds.
The 2026-09-26 release runs the updated grayscale diagnostic fixture as part of
the final suite; see [the checkpoint report](fsrd_floor_recovery_release_20260926.md).
Adaptive correction and DemodProtection have been removed. DemodRisk has no
effect on normal rendering and is not an automatically applied repair mask.
