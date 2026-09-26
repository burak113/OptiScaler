# Screen routing at zero detail and composition memory layout

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

The reported defect was real: zero Detail Preservation muted the composition
correction but still subtracted Floor before RR and added it back through Skip.
The display could therefore retain grain even when detail transfer was disabled.

On a surface selected from the original albedos/geometry, Detail Preservation=0
now uses zero spatial Floor, full current radiance through the normal RR split,
and the existing minimum roughness of 0.1. This value is the integration's
compatibility setting, not a proven universal threshold inside AMD's model.
There is no virtual albedo or new user setting.

Skip also previously closed positive FP16 rounding differences. On the new
RR-only route it retains only real demodulation-divisor or saturation loss,
calculated before FP16 rounding. A representable screen with no title bypass
has exactly zero Skip. Bias/responsivity exceptions and unrepresentable colour
channels retain their explicit energy routing; they cannot be described as
fully denoised by RR. Identity reconstruction remains within storage precision.

At positive detail, the volumetric pedestal and all existing Anchor,
Correlation Mix, luminance/chroma recovery and temporal decision logic remain.
Removing that pedestal unconditionally would restore the earlier regression
where RR could erase volumetric light. This change does not claim that remaining
grain at positive detail or grain inside the AMD result has been eliminated.

Composition's shared arrays now use row-first addressing with padding. Adjacent
X lanes no longer stride an entire tile; the tile's guide flags are cached
after their barrier. Sample counts, filter weights, statistics, sorting,
Anchor/Mix equations and recovery thresholds are unchanged. There is no new
texture, history allocation or GPU pass. Local shared storage increases slightly
for padding; global VRAM allocation is unchanged.

Several loop-unrolling variants were measured and rejected. One also changed a
stored output by one FP16 step. They are not in the delivered shader. A WaveSize
experiment was rejected at compilation because the existing shader target does
not support it; its subsequent stale-artifact benchmark is not validation.

Validation and paired performance results are recorded under
`tools_tmp/screen_rr_cleanup`. The `composition_equivalence` fixture combines the
new conversion with the previous composition shader to test only the memory
optimization for bit identity. It is not a historical production build.

New production-DXIL regression cases cover low/normal/HDR exposures, exact-zero
Skip, roughness lift, full-signal RR input, disabled detail, independent clean RR
output, and unchanged volumetry on an ordinary surface. Synthetic RR inputs do
not establish in-game AMD denoising quality. The supplied TV scene remains the
game acceptance case, especially at Detail Preservation=0 and 1.

## Paired GPU timing

RX 9070, 1280x720, Detail Preservation=1, Anchor=4, Mix=1, with temporal
decision reads/writes. Three trials each use ten warm-up and 600 measured
dispatches. Median of trial composition medians, old to new:

- Ordinary varying albedo: 4.56756 to 4.19464 ms (8.16% lower).
- Curved screen guides: 4.05128 to 3.84684 ms (5.05% lower).
- Perspective screens: 2.33984 to 2.09852 ms (10.31% lower).
- Frontal screens: 2.32972 to 2.09440 ms (10.10% lower).

All stored outputs in these positive-detail A/B runs are bit-identical. The
composition p95 values also decrease in each fixture. Stage-summed medians
decrease from 5.38920 to 5.01976, 5.34128 to 5.18120, 3.60740 to 3.41888 and
3.58344 to 3.38548 ms, respectively. These sums exclude AMD RR and upscaling;
a sum of stage p95 values is not a whole-frame p95.

At detail=0 on the perspective fixture, composition is 0.03728 ms. The stage
sum is 1.34704 ms versus 1.30840 previously; full-signal conversion is slightly
more expensive. The two modes intentionally have different routing, so their
output differences are recorded rather than treated as optimization equivalence.

The measured improvement is incremental. It does not satisfy the earlier
threefold composition-speed target or prove that the reported in-game 4-to-11
ms increase has been eliminated. Further substantial gains need a different
way of computing the full-screen statistics while retaining quality.

## Final validation

`validation_final/summary.json` passes 1,950 checks and 2,516 real D3D12 shader
dispatches with the debug layer. Counts include the opt-in bit-identity runs
against the previous composition. All four shaders, mirror checks and Release
x64 pass; the validator also checks that the DLL embeds the validated bytecode.
Historical package comparisons that were not supplied remain explicit skips.
The first validation caught a tiny HDR rounding remainder in the new Skip-loss
formula; the corrected formula subtracts equal divisors before division and the
final low/normal/HDR tests require exact zero, not a relaxed tolerance.
