# Screen-only reconstruction and full-signal RR

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

The user's TV A/B established that Detail Preservation=0 gives a black Skip and
clean ReconstructedColor, while positive detail left grain in both. The selected
screen's spatial pedestal was still travelling around RR. Conversion now removes
that pedestal at every detail value. Selected screens send full current radiance
through the existing diffuse/specular split, with roughness at least 0.1. Original
albedos remain unchanged apart from the existing RR compatibility/quantization
contract. No virtual albedo or new UI control is introduced.

On representable selected screens with no explicit title bypass, Skip is exactly
zero. True demodulation-divisor/saturation loss and title routing remain explicit
exceptions; FP16 positive rounding differences are not returned through Skip.
Detail Preservation changes only the post-RR restoration, not the screen's RR
input, Skip or roughness. Zero means no restoration. Positive detail retains the
existing Anchor, Correlation Mix, luma/chroma recovery and bounded temporal
decision equations.

Those reconstruction features now apply only to material type 1, the existing
original-albedo/surface classification. This means a supported surface whose
visible pattern is not represented by its albedos, not a missing/black albedo and
not every zero-rough pixel. Invalid guides, mirrors, albedo boundaries and title
routing retain their exclusions. This is a heuristic; tiny display regions can
remain unselected. HandoverEligibility red now reports the actual classification.

Ordinary materials retain FloorSeed, all five spatial filtering passes, the
residual/Skip split and RR remodulation. They receive no Anchor, Correlation Mix
or luma/chroma restoration. This restores the separation between spatial Floor
and special screen handover; it does not restore the old raw-colour correlation
blend or replace the rewritten spatial filter with historical shader code.

An 8x8 group with no selected screen skips composition neighbourhood loading and
statistics. Mixed groups still load their halo cooperatively; ordinary pixels
skip correction after all barriers. Debug views deliberately evaluate their
published data and do not use this group early-out. They are not timing proxies
for normal rendering. No texture, dispatch, constant layout or allocation is added.

Ordinary pixels invalidate decision history. A new GPU test caught an incomplete
native-half sentinel store on the local RX 9070: RGB was -1 while alpha retained
an unrelated value despite a four-channel constant store in DXIL. Writing through
a float4 UAV declaration fixed the observed result; the underlying RGBA16_FLOAT
resource is unchanged. This is an observed workaround, not a diagnosis of the
compiler/driver's internal cause. Metadata had already rejected that history.

## Validation contract

New production-DXIL tests require exactly zero screen Skip at detail 0/.35/1,
identical RR inputs across those settings, full-signal identity reconstruction,
the roughness floor, ordinary-pixel invariance under all handover controls,
working screen restoration/Anchor, invalid ordinary history, and normal/debug
parity on mixed and partial 8x8 groups. Existing low/normal/HDR grain tests now
require zero positive-detail screen Skip. Ordinary volumetry tests remain.

Previous tests that required handover on ordinary materials now assert its
absence. The synthetic RR fixture previously denoising a Floor-subtracted signal
now supplies the independently known full signal for selected screens. Its error
threshold is unchanged. A previous selected-screen volume-retention test now
asserts no hidden bypass: selected screens intentionally lose the independent
pedestal if RR erases their light. Nonselected volumetry remains protected.

Reports and the frozen pre-change shaders live in
`tools_tmp/screen_only_handover`. Synthetic RR fixtures do not establish AMD model
quality or game performance. The user's TV and animated signage remain the final
acceptance cases. Full-screen selected content still pays the reconstruction cost;
the empty-group optimization primarily helps ordinary geometry.

## Results for this build

Release x64, all four shader compiles, mirror validation and 717 checks across
1,278 D3D12 GPU dispatches pass with the debug layer. The DLL embeds the validated
shader bytes. Historical package tests without supplied snapshots are explicitly
skipped. A separate same-input comparison against this turn's frozen baseline
passes 18 checks / 18 dispatches: selected-screen image and active decision storage
are bit-identical at exposures .01/1/128 and Anchor/Mix 0/0, 4/1, 2/.5. Thus the
screen restoration equations have not been weakened to obtain the scope savings.

RX 9070, 1280x720, Detail Preservation=1, Anchor=4, Mix=1, temporal helpers active:
three paired trials with ten warm-ups and 600 timed dispatches per stage. Median
of trial composition medians, pre-change to current:

- Ordinary varying-albedo geometry: 4.56076 -> 0.06168 ms (98.65% less).
- Approximately 24% screen area / ordinary geometry: 3.78396 -> 0.61172 ms
  (83.83% less).
- Full-frame perspective screen: 2.09728 -> 2.10492 ms (0.36% more).

Corresponding median trial composition p95 values are 5.13904 -> 0.106 ms,
3.89996 -> 0.62016 ms and 2.14484 -> 2.1532 ms. Stage-summed medians are
5.38348 -> 0.88160 ms, 4.70000 -> 1.52512 ms and 3.41468 -> 3.38664 ms.
These exclude AMD RR inference and upscaling. Changed domain/routing intentionally
changes full-chain output; these are not claims of lossless full-chain optimization.
The full-screen display cost is essentially unchanged, so a close-up TV cannot
be promised the mixed-scene savings. In-game timings and grain acceptance remain
for the user's A/B.
