# Experimental Floor virtual albedo (2026-09-21)

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

**Historical experiment, now retired.** The runtime integration described below
has been removed. Sources and tests are archived; see
[the retirement decision and current path](fsrd_virtual_albedo_retirement.md).

This build integrates the previously offline Zero Noise / detail-consensus
experiment into the real conversion → AMD RR → composition path. It is opt-in:
Advanced Settings → Experimental Floor → **Floor Virtual Albedo (experimental)**.
INI: `[FSR-RR] FloorVirtualAlbedo=false` by default. Enable Floor must be on and
Detail Preservation above zero, because the existing reference-validity channel
also carries explicit routing exclusion. The normal Floor path remains the default.

## Runtime signal contract

1. Eligibility comes from the original zero-rough material tag and a valid,
   non-routed Floor reference. This remains a domain-specific experiment; a flat
   albedo alone does not identify an animated screen, nor is zero roughness a
   universal screen classifier. Bias/responsivity-routed content is excluded.
2. Snapshot raw colour, matching pilot, signed canonical depth/oct-normal,
   validated raster motion/depth delta, and material guide in independent resources.
   A small spatial average cleans only the matching pilot, not the observed RGB.
3. Reproject through canonical motion with previous/current jitter restored to
   raster coordinates. Invalid title motion is explicitly invalid, never zero.
   Search ±4 pixels around that prediction using dense 9×9 RGB patches per 8×8
   block; validate geometry, material, DC and texture agreement. At most the last
   three committed observations can support the current frame.
4. Zero Noise supplies the heavily smoothed base inside the selected domain.
   The existing cleaned DetailReference supplies startup/rejection fallback.
   Four overlapping 8×8 DCT tilings estimate signed detail and its uncertainty
   across aligned observations. Uncertain coefficients shrink; a shared RGB gain
   prevents per-channel colour selection. The previously tested temporal-noise
   dependence guard is enabled. No observation means no raw-detail bypass.
5. Average the reconstructed tilings, clamp the virtual carrier to 0.008–1, and
   quantize to the exact RGBA8 UNORM value that RR and composition will read.
   Split full current radiance using the original per-channel albedo ratio, then
   divide both signals by the same carrier. Retain signal hit-distance metadata.
   Skip contains only the positive FP16 demodulation remainder here.
6. AMD RR processes those signals with the generated carrier. Composition
   remodulates with exactly that carrier and adds the remainder. The selected
   reference is marked ineligible for the old handover: neither Floor nor
   Anchor/Correlation Mix adds the same radiance again. Outside selected pixels,
   the six packed resources are copied unchanged and the existing Floor applies.

The carrier is a statistical reconstruction, **not recovered physical albedo or
emissive**. The base does not prove the complete absence of light contributions.
Persistent noise indistinguishable from texture can remain. HDR values above the
carrier range move into the signal; this can limit recovered bright-text contrast.

## History and ownership

Four observation slots are independent of RR scratch. Allocate only on first
activation, retain while disabled, and retire resources across the descriptor
rotation on allocation-size changes. Approximate additional texture storage at
1920×1080 is 680 MiB, plus padding/driver allocations. Performance is unoptimized.

Settings that reset RR also invalidate this history. Logical size, subrect origins,
motion size/transform/convention, resets, debug-mode changes, missing frames and
failed frames reject it. A pending observation is committed only after successful
RR and composition/upscale (or a successful composition-debug presentation).
Bypassed/internal-debug frames do not commit. Debug views need several frames to
settle after switching; they use the existing pre-upscaler presentation.

## Views and test procedure

- **CarrierPattern:** reconstructed RGB before UNORM quantization, black outside
  the selected domain; black when the experiment is disabled.
- **CarrierAlbedo:** the actual diffuse albedo supplied to RR, including original
  albedo outside the selected domain.
- **FloorZeroNoise / FloorZeroNoiseRemoved:** remain available with the experiment
  enabled and inspect the original pre-carrier seed.
- **None:** normal RR composition and upscaling, for the actual in-game A/B.

Start with the user's existing 0.75 noise / 0.35 detail / Anchor 4 / Mix 1 settings.
Toggle only Floor Virtual Albedo for comparison. Inspect a nearby screen, small
distant text, camera movement and a full advertisement change. The old handover
controls still affect the normal path; they are intentionally not applied a second
time to carrier-selected pixels. No game DLL is automatically replaced.

## Validation and limits

Release x64 builds. The new DXIL contract suite checks finite output, signed motion,
subrect and display-resolution MV addressing, jitter, invalid motion, geometry and
material rejection, translated content, texture cuts, tiny/odd extents, exact copies
outside the domain, FP16/UNORM identity closure and actual composition with no
duplicate Floor. A native test exercises the same runtime history ownership class.
The normal Floor suite passes 47 checks / 101 GPU dispatches. INI save/reload retains
the new toggle and unrelated settings. Mirror checks cover new CB layouts, resource
orders and table counts. Existing five shader bytecodes remain unchanged.

The GPU registration quality replay uses the actual new prepare/register/DCT DXIL
and real AMD RR on RX 9070. Six datasets × 32 frames × two candidates × two signal
types = 768 AMD RR dispatches, with zero SDK/D3D12 validation errors or warnings.
It compares against the spatial DetailReference virtual-carrier experiment, not
against the full old in-game Floor/handover image. Indirect-specular RMSE reductions:
fine static 38.3%, fine untracked animation 37.0%, coarse static 17.2%, texture cut
29.8%, clean static 76.5%, correlated coarse noise 27.5%. Direct diffuse agrees
closely. On fine animated stripes, contrast ratios are 0.970–0.982 instead of
0.704–0.968 for the spatial reference. Clean contrast is 0.997.

Coarse-noise contrast remains a tradeoff: aggregate contrast drops from 0.981 to
0.920 for independent coarse noise and 0.978 to 0.893 for correlated coarse noise.
Texture-cut quiet-region metrics are not a stable ROI after texture replacement;
they must not be presented as temporal-ghosting acceptance. Motion matching is
integer and bounded; fast/nonrigid animation can fall back to a blurrier spatial
reference. Synthetic success does not establish CP77/007 quality, capture latency,
or absence of in-game D3D12 hazards. Game acceptance belongs to the user's A/B.

Raw reports: `tools_tmp/floor_virtual_albedo/quality_v3/results.json`,
`contracts_final/results.json`, `core_regression/results.json`, and build logs.
Earlier `quality` and `quality_v2` runs document rejected integration iterations.
