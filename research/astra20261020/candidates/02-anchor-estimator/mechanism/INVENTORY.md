# Ancillary fixture inventory

This inventory is independent of candidate tuning. It adds descriptive raw-input
observations and exact crop/history constraints; it does not replace the frozen
anchor mechanism results or claim a new recall algorithm.

Run from the repository root:

```sh
python -B research/astra20261020/candidates/02-anchor-estimator/mechanism/inventory.py --include-bottle
```

The initial blinded execution passed in approximately 0.62 seconds; the final
all-clip inventory passed in approximately 0.81 seconds. `data_inventory.json`
contains archive SHA256, manifest/source provenance, each array's shape/type,
documented units/roles, per-frame history support, descriptive D/S statistics,
alpha hashes and missing observations. Bottle signal arrays remained unopened
until the root released the holdout **after** `evidence/FROZEN_SOURCE.json`
recorded the candidate-source freeze at 2026-10-20 18:09:57.852605 UTC. This final
inventory enables the existing descriptive computation with `--include-bottle`;
no estimator, threshold, selection, mask or metric changed. The freeze record
hash and disclosure are saved in JSON. Without that flag the script still reads
only bottle ZIP/NPY headers and provenance. Every numerical NPZ read uses
`allow_pickle=False`. No original data is modified.

## Actual chronological clips

All three clips preserve original **1505x847** render coordinates, original
provider frame/control words, camera word arrays, FP16 RGBA D/S signals,
float32 depth and packed uint32 original/prepared normal/roughness guides.

| Clip | Original frames | Width x height | Global render crop origin | Origin-aware in-crop bilinear history support after first frame |
|---|---|---|---|---|
| Bottle | 180–186 | 128x256 | (688,160), (688,176), (688,208), (688,272), (688,384), (688,480), (688,560) | 62.3657%–93.7592%, measured only after holdout release |
| Foliage | 43–65 | 192x64 | (752,423), fixed | 93.4733%–97.9655% |
| Facade | 34–49 | 96x96 | (688,359), fixed | 96.8967%–97.9275% |

The first frame of each clip has **zero available previous-image support**.
For every later frame the script verifies independently:

```text
previous_local = current_local + current_crop_origin
               + original_motion_RG * (1505,847) - previous_crop_origin.
```

Only finite positions satisfying `0<=x<width-1`, `0<=y<height-1` have complete
bilinear support. Outside-crop samples remain unavailable; the script does not
clamp or wrap them. Coordinate validity is not depth/normal/occlusion validity.
The percentages use the same full-crop denominator at every frame and include
the unsupported pixels in that denominator. They are availability diagnostics,
not an evaluation mask recomputed from a candidate.

The bottle crop moves to track content. Its origin delta is a coordinate change,
not evidence of physical camera/object motion. The original source strip is
128x847 at render origin (688,0); crop height256 and y origins must remain part
of any subsequent correspondence. A stationary-crop assumption would be wrong.

Bottle supported-pixel counts for frames181–186 are 30723, 28541, 24007, 20436,
20508 and 22750, each out of the unchanged 32768-pixel crop denominator.
The lower full-crop coverage does not contradict the README's narrower original
speed-mask assertion; that exact mask is absent, so its asserted coverage is
historical metadata rather than independently remeasured here.

There are **21 arrays in each clip, with no pixel quality-mask array**. The
bottle README mentions a speed>12/erode2 analysis mask, but that mask itself is
not a bundled field. No candidate-dependent substitute is invented here. The
descriptive radiance statistics use every original pixel of the published crop.

## Raw physical D/S sparsity and concentration

These numbers are computed from unchanged native input RGB, using float32 luma
without a new half-store step. The denominator is all pixels across the stated
clip. The per-frame equivalents and exact alpha hashes are in JSON.

| Clip/lobe | Original RGB exactly zero | Energy in brightest 1% of pixel-frame samples | Mean physical luma | Maximum physical luma |
|---|---:|---:|---:|---:|
| Bottle diffuse | 23.3970% | 36.5586% | 0.00686426 | 2.32404 |
| Bottle specular | 20.7419% | 34.3032% | 0.00436033 | 3.45457 |
| Foliage diffuse | 35.6566% | 32.9901% | 0.00664256 | 4.67578 |
| Foliage specular | 37.8761% | 53.3430% | 0.00276239 | 9.23438 |
| Facade diffuse | 14.5087% | 23.5672% | 0.00382020 | 1.29469 |
| Facade specular | 15.1944% | 30.6745% | 0.000594736 | 0.842418 |

These raw samples are substantially sparser and more concentrated than the
already-averaged/recalled anchor grids. Averaging the raw inputs first would
erase that observable. However, raw tails can contain true reflection structure,
real illumination, geometry/disocclusion and stochastic noise. No ground truth
or independence claim follows from a tail percentage. Concentration ESS in JSON
is a descriptive energy statistic, not a count of independent observations.

Input alpha contains hit distance and is retained as original FP16 bytes. The
inventory hashes its full and per-frame planes separately. The original lobe
arrays and alpha are never filtered. Raw/selected RR arrays exist separately
and retain history from before the clip; neither is converged ground truth.

## Portable colour fixture

`soft2_gpu_87ee63.npz` contains 15 arrays for one captured frame, 87ee frame63,
with a 512x512 ROI at (496,167) in the original render. Its 64x64 C8 previous
history was warmed on CPU through original frames0–62. Only frame63's stored
comparison was GPU-executed historically. This is neither 64-frame GPU temporal
proof nor B4-compatible history.

The data contain physical **D+S pre-remod RGB sums**, with no separate lobe alpha
and no exact final game remod factors/Skip. Some arrays are FP16-RTZ-expanded
float32; original pre-UAV low bits for the rejected soft2 guide are missing.
`motion_px` already uses original 1505x847 scaling; `motion_uv_roi` is a separately
rounded alternative and is not interchangeable. No pixel fixed mask is exported.

All files listed in the colour manifest are freshly hash-verified. Historical
GPU parity/rejection records remain historical evidence; this inventory does
not rerun GPU or change the rejected soft2 algorithm.

## Aligned glass subset

`glass_crop.npz` spans frames46–63 of 87ee, aligned to frame54. Its 192x160 crop
starts at source-ROI (50,180), hence global render origin **(546,347)**. The
frozen `common_mask` contains **6497** pixels and is freshly count/hash-verified.
The separate **8048**-pixel full-ROI result is not this fixture's denominator.

The twelve arrays include aligned raw RR specular RGB float32; selected old-NZR
specular reconstructed losslessly with uint32 XOR; aligned equal diffuse RGB;
original unwarped geometry/MV; camera words; and explicit aligned masks. Original
motion/depth/normal arrays must not be treated as if they had been warped into
the aligned radiance coordinates. Alignment uses reference-depth camera-only
reprojection without source-depth occlusion or dynamic-object compensation.

The glass subset contains no native pre-provider input lobe pair with alpha,
anchor current/recalled fields, or raw ring keys. It can reproduce its existing
fixed-support grain/detail trade-off, but cannot identify a new native anchor
estimator. No new glass quality metrics are computed by this inventory.

## What remains absent

The chronological clips omit albedo and are incomplete RR dispatch fixtures.
The package lacks raw native six-slice anchor keys, original native pre-store
16.16 atomic sums, unseen pre-window history, independently observed lighting
truth, and actual native/RR/final-game execution of this candidate. The clips
cannot be looped, clamped at crop boundaries or treated as a complete engine
replay to fill those gaps. The candidate's GPU/data requests must state the
precise missing observations rather than infer them from these descriptions.
