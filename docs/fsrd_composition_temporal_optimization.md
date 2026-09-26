# Full-screen composition and bounded decision history

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

Historical report for the first `composition_temporal` delivery. The subsequent
game report exposed Skip grain and inadequate benchmark guide coverage; see
[the follow-up fix](fsrd_skip_grain_fix.md) for current behaviour and corrected
measurement methodology. In particular, the measurements below used a white
composition albedo rather than the real conversion output.

The requested scope is to retain Anchor, Correlation Mix, luminance recovery and
chromatic recovery while reducing composition to at most one third of the frozen
pre-change selected-surface benchmark. All eligible surfaces now use these four
features, regardless of RR material type. Explicitly routed pixels and disabled
Floor/detail remain excluded. Original albedos remain surface guides; there is no
virtual-albedo injection or new reference denoiser.

## Shared spatial work

The 5x5 binomial moments, full 9x9 regional moments, colour covariance Anchor,
correlation and luma/chroma recovery formulae are retained. The input to those
formulae is computed with less repetition:

- Each 3x3 forward-blur hypothesis is computed once in shared memory, in FP32.
  It remains evidence only; this blurred colour is never transferred.
- A per-centre 49-bit surface acceptance mask is built during the regional scan
  and reused by the blur hypotheses and directional colour-pair tests. It uses
  the original depth/normal/material/routing rules, including distinct border
  samples. Surface acceptance is not inferred transitively from neighbours.
- Quiet colour pairs are shared on complete valid support. Incomplete support
  uses the same centre-relative acceptance mask before evaluating each pair.
- Only sorting-network comparators that contribute to ranks 0 through 6 remain.
  The exact lower quartile and small-support fallback are unchanged.
- Uniform-material, constant-normal planar guide tiles use shared horizontal nine-tap moment sums followed by
  nine-row accumulation. All 81 samples remain; this is not sparse sampling or
  a smaller filter. Surface boundaries retain the weighted per-pixel scan.
  The planar-depth shortcut allows only FP32-scale depth error (2e-7 relative,
  with a 1e-6 absolute floor) and requires a shallow enough slope that the
  original depth prediction clamp cannot activate. Non-planar tiles use full
  weighted evaluation. FP32 summation order differs; stored output equivalence is numerical, not
  universally bit-identical.

## Temporal helpers

Two independent ping-pong resources store four FP16 decisions and packed UINT
metadata. They never store a previous output colour or signed correction for
transfer. The decisions are colour-Anchor support, correlation agreement,
chromatic support and luminance support. Anchor's unconditional RGB box,
current covariance, recovery gains, current candidates and range limits are
still calculated from the current frame.

Reprojection uses canonical previous-minus-current motion UV plus the previous
minus current raster jitter. Motion alpha now preserves validity; an invalid
motion vector cannot silently become reusable zero motion. Validation checks
signed depth with motion Z, oct-normal, roughness/material type, quantized
albedo and current reference colour. Reference colour stored in metadata is
compressed only for rejection; it never contributes radiance to the result.

At most half the previous decision is reused, bounded to within 0.125 of the
current decision. A current zero gate stays zero. Content change attenuates
reuse between 2.5% and 8% relative RGB difference. This gives a short effective
history (about three samples at maximum reuse), not full-image accumulation.
Rapid animation, exposure changes, unmatched reflections and disocclusion fall
back to current decisions. This heuristic can stabilize decisions; it does not
guarantee removal of grain already shared by Skip and RR.

History becomes readable only at the end of a successful normal frame including
upscale. Failure, bypass/debug, reset, size/source-origin changes and settings
that invalidate RR invalidate helper history. History targets are allocated on
demand and are independent of RR scratch. Composition now has a separate output
because its old Motion scratch target is needed for reprojection.

## Resource and validation contract

Composition uses 11 SRVs, 3 UAVs and an 80-byte cbuffer. Its additional inputs are
canonical motion, prior decisions and prior metadata. Additional outputs are
next decisions and metadata. The mirror validator reads the actual C++ output
resource ordering. Regenerate shader CSOs and embedded headers together.

The four history textures cost 48 bytes per allocated pixel. The separate
composition target adds 8: total incremental allocation is 56 bytes/pixel,
49.22 MiB at 1280x720 and 196.88 MiB at 2560x1440, excluding alignment. This is an
allocation calculation, not observed game VRAM. Shared shader storage is 17,924
bytes/group. No shader dispatch is added for the temporal helpers.

`test_fsrd_composition_temporal.py` executes real production DXIL with history
passed between GPU dispatches. It tests bounded reuse, invalid motion, reset,
animation cuts, guide changes, routing, offscreen movement, jitter and signed
motion-Z. It separately measures decision variance and reconstruction error;
decision variance is not a percentage estimate of game noise reduction.

The paired benchmark's `--temporal-helpers` flag measures history reads and
writes, using actual GPU-generated metadata. Reports include ordinary, mixed,
fully selected and sloped selected surfaces. These use synthetic RR inputs;
neither AMD RR inference nor the upscaler is included. A full-selected stress
result is not a whole-game frame-time claim. In-game animation, camera motion,
trails and visual quality still require user validation.

## Recorded performance

`tools_tmp/composition_temporal/final_benchmark` records three paired trials at
1280x720 on the RX 9070, with ten warm-up dispatches followed by 600 measured
dispatches per stage. Current composition includes temporal reads and writes.
The following are medians of the three trial medians, for composition alone:

- Full selected surfaces: 12.6777 ms before, 2.3974 ms after (81.1% lower;
  18.9% of the baseline). Median trial p95: 15.2366 to 2.67736 ms.
- Sloped selected surfaces: 16.4681 to 2.42728 ms (85.3% lower).
- Mixed surfaces: 3.23576 to 2.44728 ms (24.4% lower).
- Ordinary surfaces: 0.37672 to 2.41288 ms. This is a deliberate scope cost:
  the old shader skipped the expensive handover on these materials, whereas
  the requested full-screen version runs all four features on them.

Thus the one-third goal passes for full selected-surface stress tests; it is
not a universal reduction for every material distribution. Baseline timings
also vary between trials (full selected medians 12.15 to 16.25 ms), so these
numbers should not be substituted for an in-game comparison. The largest
selected-surface colour difference in this paired fixture was 0.00048828125.
This does not prove perceptual equivalence on arbitrary game content.

## Final validation and delivery

`tools_tmp/composition_temporal/validation_final/summary.json` passed with 614
checks and 1,154 GPU dispatches, the D3D12 debug layer enabled, all four shader
compilations, mirror checks and Release x64. The built DLL contains the exact
tested shader bytecode. Older optional reference-package comparisons were
skipped where their packages were unavailable; no historical A/B pass is claimed
for those suites. The frozen pre-change paired benchmark above did run.

The shared-statistics regression checks flat/sloped depth of either sign at
three exposure scales against the weighted fallback, plus 20,000 sorting
network inputs. The temporal fixture reduced decision variance from
1.5444541e-6 to 1.7565814e-7 (88.6%); its reconstruction RMSE changed from
0.028643634 to 0.028647879. This measures decision stability, not TV grain.

Delivery: `tools_tmp/composition_temporal/delivery/dxgi.dll`, SHA-256
`533bf7630c44c155e8bdc8a038922b6e9242023ffb276c3a36fe0d85c9ae20b9`.
Keep the current Anchor=4, Correlation Mix=1 and Detail Preservation=0.35 for the
first game comparison. No new UI option is needed. Debug/bypass views invalidate
history; return to normal output for the temporal helper to become active.
