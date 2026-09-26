# Floor optimization without changing the estimator

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

2026-09-21. Baseline: the surface-selection build delivered before this optimization,
DLL SHA256 `d13af99a63173c24dc5c529fd75d24a07f21f7384fbda1080a5bce3fd7478278`.
Its sources and compiled shaders were frozen in
`tools_tmp/floor_optimization/baseline/precompile` before editing.

## Production changes

- Input conversion exits surface classification as soon as a valid same-surface
  albedo sample vetoes flatness. Subsequent samples cannot reverse that decision.
  Original zero-roughness candidates still validate geometry, both albedos and
  reference support, but skip the RGB plane moments they never consume.
- Later spatial passes load center depth, normal and albedo only after their
  existing quiet-region early exit. Five passes, their steps and weights remain.
- Composition loads the existing 20x20 shared tile only when a group contains a
  pixel eligible for the special handover. Ordinary-only groups populate the
  10x10 portion they consume, at identical shared-memory coordinates. All lanes,
  including out-of-bounds lanes in a partial group, participate in synchronization.
- The nine surface weights for the central NLM patch are calculated once, not
  once per candidate. Each search row additionally maintains a sliding three-column
  cache: adjacent candidate patches reuse six of nine surface comparisons. These
  caches are full-precision per-thread values and do not change any weight.

There is no reduced render resolution, new half precision, smaller search radius,
removed filter pass, temporal history or reduced quality setting. Anchor and
Correlation Mix keep their existing mathematics and ranges. No new GPU texture,
descriptor or per-frame allocation is introduced. Existing debug views remain.

An alternative moving the unrolled blur-evidence calculation into a compact loop
was measured and rejected: smaller DXIL did not produce faster GPU execution.

## Verification tools and interpretation

`validate_fsrd.py --lossless-baseline <frozen-precompile> --build` runs each GPU
fixture against both compiled shader versions with the same typed resources and
constant values. It requires every stored output to be exactly equal, in addition
to the existing independently specified correctness and quality checks. A different
result fails immediately; tolerances are not silently widened for optimization.

`tests/benchmark_fsrd_optimization.py` alternates baseline/current order, executes
Seed, five Floor passes, conversion and composition, and uses GPU timestamps.
The default is three trials with 610 repetitions per stage, discarding ten warmup
dispatches to retain 600 samples. Inputs cover ordinary textured materials, a
mixed scene with a flat-albedo screen, and a full-frame screen stress case.
Stage medians and stage p95 values are summed separately. The latter is **not**
the p95 of an entire frame. Upload, CPU work, actual AMD RR, the upscaler and the
game are excluded. These are repeated dispatch workloads, not frame-rate claims.

`tests/probe_fsrd_motion_noise.py` drives actual production shaders through eight
subpixel phases with independently changing grain and sparse colored rays. It
records error against an independently generated clean target for each phase,
temporal differences of those errors, pedestal excess and selected-surface coverage.
Clean and explicitly blurred RR mocks isolate Floor behavior; they do not model
the AMD network or prove that reported in-game motion noise has disappeared.

## Motion-noise investigation

The moving glyph screen reproduced sparse positive residuals: 54 pixel samples
exceeded 0.04 linear RGB error across eight frames; the maximum error was 0.4924.
The clean mock RR did not contain these rays. At the worst pixel, the seed/reference
contained the ray, patch filtering kept it, and handover confidence reached 0.846.
The local pedestal excess was much smaller (at most 0.0061 in this glyph case).
This identifies an actual ambiguity in detail transfer; it is not proof that every
in-game sparkle has that cause.

A separate candidate rejected an isolated positive reference/RR difference when
eight independent same-surface neighbours already agreed within the local noise
allowance. On the moving glyph it reduced those 54 samples to 15, and temporal
error from 0.01635 to 0.00813. The blurred-glyph reconstruction error was unchanged.
On the silhouette screen the sample count dropped from 27 to 8.

**The candidate was rejected.** An independently clean new one-pixel animated
colour with unchanged neighbours produced the same evidence. Its RGB error grew
from 0.1807 to 0.8384: the candidate discarded the feature. This violates the
requirement not to buy noise removal with lost detail. The candidate is confined
to `tools_tmp/floor_optimization/quality_candidate`, is not compiled into the
delivered DLL, and is not an optional production path. The clean counterexample
is retained as a regression gate in the motion probe.

The delivered optimization therefore preserves current noise behavior as well as
current detail. No claim is made that it fixes in-game motion sparkle. A safe next
quality experiment needs extra evidence (for example carefully validated temporal
agreement), plus animated-text/disocclusion tests; a stronger spatial rejection
alone cannot distinguish these two otherwise matching examples.

## Completed validation

Release x64, generated shaders, mirrors, INI checks and D3D12 tests passed on the
RX 9070. The standard suite ran **1,725 checks / 2,258 dispatches**, including
1,129 exact baseline/current comparisons in addition to the 596 quality and
correctness checks. Optional historical-version comparisons were explicitly
skipped; the frozen immediate pre-optimization baseline comparison did run.
Report: `tools_tmp/floor_optimization/validation_opt3/summary.json`.

Additional boundary/HDR/debug checks passed **108 exact comparisons / 216
dispatches**. The complete motion probe passed **425 checks / 836 dispatches**,
including 418 exact pre-optimization comparisons and the clean one-pixel
counterexample. Combined validation: **2,258 checks / 3,310 dispatch jobs**,
with 1,655 exact baseline/current comparisons. Benchmark repetitions are separate
from these counts. Reports are under `equivalence_final` and `motion_final` in
`tools_tmp/floor_optimization`.

## Long-run GPU timing

RX 9070, 1280x720, three alternating A/B trials, 10 warmup plus 600 measured
dispatches per stage in each trial. Reported values below are the median across
the three trials of the sums of stage medians:

- Ordinary materials: **1.57744 -> 1.14656 ms**, **27.32% less time**.
- Mixed scene (roughly 24% selected screen pixels): **12.31360 -> 9.00676 ms**,
  **26.86% less time**.
- All-screen stress case: **41.17714 -> 27.87988 ms**, **32.29% less time**.

The corresponding sums of stage p95 values improve by 27.34%, 27.43% and
32.02%. These are not whole-frame p95 values. All nine complete pipeline
comparisons produced exactly identical stored outputs. No D3D12 validation errors
were reported. The full-screen stress case is deliberately pathological and
does not estimate a normal game's Floor time or FPS.

`tools_tmp/floor_optimization/benchmark_final/summary.json` contains the aggregate
numbers; `results.json` contains every trial/stage and `manifest.json` pins the
tested shader hashes. GPU texture/descriptor/history allocation delta is zero;
new per-thread caches can change occupancy, which is reflected in the measurements.
