# Zero-rough screen reconstruction — V11 joint-colour Anchor

## V11 additions

V11 keeps V10's spatial reference and direct Correlation Mix. It extends Anchor
with the full local RGB covariance: the candidate is bounded along correlated
colour directions as well as the original independent R/G/B limits. This rejects
coloured grain that fits inside separate channel ranges but disagrees with the
patch's colour relationships. The additional constraint fades out when Q and the
current reference disagree on structure; the original channel Anchor never fades
out. No new setting, pass, texture, history or constant-buffer layout is added.

The first unconditional covariance variant failed the small mixed-colour fixture
(RMS .06597 -> .07926); it was rejected. An adaptive dark SSIM variant improved
clean dim texture but returned correlated noise (normalized RMS .000612 -> .00361),
so its code was removed. A reduced NLM self-weight improved flat reference noise
1.2% but worsened glyph reference RMS 2.8%; it was removed too. Their noise,
palette-change and reference fixtures remain as nonregressions. Only the guarded
joint-colour Anchor is included in V11. Tests are actual production DXIL against
immutable V10; they use independent synthetic RR estimates, not the AMD model.

With equal Anchor=4/Mix=1, the new three-frame patterned grain fixtures reduce
RMS roughly 5–13% depending on palette. Full measurements, control tradeoffs and
the actual DLL hash belong in the versioned V11 handoff. No game acceptance,
temporal stability improvement or performance result is claimed.

The following V10/V9 sections describe the retained foundation and historical
measurements; the current complete algorithm is in fsrd_pipeline_contract.md.

## V10 background

Implementation contract: [fsrd_pipeline_contract.md](fsrd_pipeline_contract.md).
Previous candidates may be kept locally under `tools_tmp/floor_rewrite/zero_rough_v*/`;
they are not committed or implicitly loaded by tests. Explicit optional reference
packages and current-only validation are described in [fsrd_validation.md](fsrd_validation.md).
The user accepted V9 as their preferred build, with Anchor=4 and Mix=1, reporting
much less noise and near-perfect large/close screens. V10 targets small, distant,
mixed-colour screens and still awaits game comparison. Timing limits remain
suspended; there is no emissive input or multiscale blending.

## V10 additions

- **Colour-aware agreement.** V9's luminance-only SSIM sees almost no difference
  between a sharp and blurred isoluminant colour pattern. V10 also compares
  centred chromatic moments (`RGB-luminance`). Evidence comes from RR's own
  chromatic variance, regularized by fine-noise variance, so grain on neutral
  surfaces cannot simply disable the successful luminance rejection. The Mix
  multiplier and unconditional Anchor remain active at their actual strengths.
- **Centre-aware patch matching.** Eight similar background pixels in a 3x3 patch
  cannot entirely outvote its small letter corner. A relaxed noise-corrected
  centre distance supplies a floor to patch mismatch. This rejects false matches
  rather than inventing/sharpening colour; it can modestly reduce noise pooling.
- **Defaults 4/1.** Config, descriptor and non-finite fallback adopt the user's
  preferred Anchor=4, Mix=1. Stored values are preserved. No new controls.

At equal 4/1 settings against immutable V9, actual-DXIL synthetic tests show:

- Small isoluminant colour patterns, clean: RMS .07399 -> .04887 and
  .07712 -> .05165 (two RR blur levels). With sigma .02 noise: .06238 -> .05353
  and .06595 -> .05994. Improvements range about 9–34%, not full reconstruction.
- Small noisy glyph reference: mean ink error .03951 -> .03272 (17% reduction);
  whole-reference RMS .01864 -> .01567 (16% reduction).
- Mixed RGB/diagonal structures at three sizes improve 1.7%, 1.5%, and 17.3%.
- Large clean glyph reconstruction is effectively unchanged (.03045 -> .03042).
- Three-frame grain fixtures: flat RR unchanged; colour texture .040819 -> .040812;
  lettering .006462 -> .006610, a small 2.3% noise-error increase. This cost is
  reported rather than called a noise improvement. All meet the 10% regression cap.
- Already-sharp colour, HDR/dim inputs, disabled detail, explicit routing and
  ordinary material checks pass; the last three match V9 bit-for-bit.

Seed, Floor, conversion and resource layout remain identical to V9. No extra
passes, textures or temporal history. Additional moment arithmetic and the centre
match test add work; runtime cost has not been benchmarked. The implementation
cannot recover subpixel information absent from the current frame, or fully undo
blur while obeying an Anchor whose RR distribution contains no matching contrast.

The following sections preserve the V9 design and its original measurements;
its original defaults were Anchor=2/Mix=1. Current behaviour follows the V10
additions above and the up-to-date pipeline contract.

## Evidence and scope

The user confirmed V8 removed the small bright speckles. Its seed, spatial Floor,
conversion and volumetric pedestal are retained byte-for-byte. The remaining
large patches on the screen change even with a static camera. Fine grain remains
lower on the same screen. One image does not establish their exact rendering
source; the user observation rules out treating all the large patches as static art.

V8's Anchor was suppressed by enough centre-colour-compatible neighbours. Such
support also exists inside a noise blob. Its Correlation Mix was multiplied by
`(sigma / RR-error)^4`; a mismatch of four sigma left only 1/256 of the intended
rejection. The user asked for both controls to work, accepting additional blur.

## V9 implementation

1. Replace centre-colour range filtering with surface-bounded patch matching:
   an 11x11 search, 3x3 RGB comparisons, independent in-bounds samples and explicit
   routing exclusion. Matching source centre pixels contribute to the reference;
   no low-pass pilot colour or new temporal image is substituted.
2. Pool fine-noise estimates from the quiet quartile, avoiding dense letter
   corners setting the filter width. Calculate the candidate's independent-noise
   confidence from effective sample count, without relaxing Anchor or Mix.
3. Restore unconditional positive Anchor: clamp the candidate to the 5x5 RR
   mean +/- Anchor times its per-channel standard deviation. Zero disables it;
   lower positive values clean more strongly. Similar-colour support no longer
   disables the clamp and movement is no longer limited to a tiny sigma.
4. Restore direct correlation rejection: multiply transfer by `1 - Mix*agreement`.
   Remove the fourth-power sigma/error term. Zero disables only this additional
   rejection; ordinary noise-based RR agreement still applies.
5. DetailReference now displays the actual patch-filtered candidate before Anchor
   on zero roughness, including at zero Detail Preservation. DetailConfidence and
   DetailCorrection show the final confidence and applied correction respectively.

The original zero-rough classification precedes the automatic 0.1 roughness
published to RR while Floor is active. This compatibility policy is unchanged.
Zero roughness also includes mirrors: it is not proof that a surface is a screen.
There is no verified physical separation of emission and reflected lighting.

No new textures, root descriptors, INI variables or history resources. Constants
remain 64 bytes. Shared tile grows 16x16 -> 20x20; declared DXIL shared arrays grow
7,680 -> 12,000 bytes. Menu tooltips explain the controls' real blur tradeoff.

## Validation and honest tradeoffs

The tests dispatch production DXIL on RX 9070 with the standalone D3D12 debug
layer. RR is an independently defined clean/blurred/displaced synthetic estimate,
not the AMD model. Actual Floor and Skip are retained in the full-chain fixture.

- Fine-grain reference RMS: seed 0.03591 -> patch reference 0.01544.
- Moving noisy glyph RMS with Anchor/Mix off: V8 0.03097 -> V9 0.01856.
- Three changing coarse-noise fixtures, clean RR and default controls:
  V8 mean RMS 0.06816 -> V9 0.00641. This is not measured game flicker reduction.
- Real Floor/conversion/Skip plus ideal residual denoiser:
  V8 RMS 0.06972 -> V9 0.02676. Skip excess RMS is 0.02327; this remains a limit.
- Clean moving bitmap lettering: controls off retain 99.4% mean contrast.
  Defaults increase image RMS from 0.00694 (controls off) to 0.08434, while stale
  RR alone is 0.11541. This substantial softening is the actual cost of a strict
  anchor against blurred RR. The controls are functional, not a free improvement.
- The prior seed sparse-ray, volume and identity-closure regressions remain.

Pure maximum-texture-recovery tests now explicitly disable the two optional RR
constraints. Their prior thresholds remain unchanged. Noise rejection, identity
and original-reference comparisons still use defaults; a new suite independently
tests defaults and control sweeps. Passing the texture-only tests is not a claim
that defaults preserve 95% contrast against arbitrarily stale RR.

The reference filter still cannot perfectly separate an animated texture from
correlated illumination using a single composited frame. NLM's fine-noise model
does not describe correlated blobs; Anchor/Mix supply RR constraints. Noise shared
with Skip can survive both. User game tests must assess the remaining grain, text,
motion and mirrors. Timing limits are suspended; no performance acceptance is claimed.
