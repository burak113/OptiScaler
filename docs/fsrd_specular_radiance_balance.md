# Indirect specular radiance conditioning

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

## In-game outcome

The user tested the delivered DLL in the target Cyberpunk sea scene and reported
that it did **not** remove the blotches. The synthetic improvement below did not
transfer to that scene. This is not an accepted sea fix. Subsequent builds default
BalanceSpecularRadiance to false; an explicitly saved INI value remains respected.
The next diagnostic isolates diffuse and specular modulation separately, because
the previous successful-but-blurry A/B switches changed both lobes.

The two earlier albedo A/B switches removed broad synthetic blotches but also
removed most of the fine pattern contrast. This candidate keeps the original
stored diffuse/specular albedos. It does not infer a water material and does not
extend display recovery to the whole screen.

## Production change

Advanced → Input Compatibility → **Balance Specular Radiance** enables a constant
power-of-two conditioning factor on indirect specular only. The INI key is
`[FSR-RR] BalanceSpecularRadiance`; this trial build defaults it to true.
The older Normalize Albedo Sum and Bypass Albedo Modulation switches take
precedence when loaded from an existing INI. Enabling the new checkbox disables
both. For the intended comparison, both older switches and Fix Roughness must
be off, with Specular Signal set to Auto/Indirect.

For the specular contribution S and its stored albedo A, the input is
`S / (4 * max(A, divisorFloor))`. Composition multiplies the RR result by `4*A`.
The unrepresented residual uses the same multiplier before entering Skip.
Identity denoising therefore preserves radiance, including the divisor-floor
case. The diffuse signal, original signal split, albedo guides, roughness, hit
distance and material selection are unchanged. No extra texture, neighbour
lookup, dispatch or history buffer is added. Scale restoration happens before
Floor's Anchor/Correlation/Luma/Chroma recovery and its neighbourhood statistics.
Direct specular is bit-identical. Toggling the feature invalidates RR history.

This is empirical conditioning of the neural model's radiance domain, not proof
that the previous division/multiplication pair was algebraically incorrect.
A nonlinear denoiser need not be invariant to a signal-domain scale. It also
does not prove that Cyberpunk's guide buffers themselves are wrong.

## Candidate selection

`tests/probe_fsrd_albedo_gain.py` executes the real signed AMD denoiser on a
known clean moving/static pattern, noisy radiance, and independently imposed
broad guide patches. Both diffuse and specular lobes are supplied. Error is
measured against clean truth; blurring the output cannot count as noise removal.

Rejected candidates included per-channel normalization, modulation bypass,
local 9-tap guide normalization, smooth divisor toes, and capped guide boosts.
Local normalization looked good on fine patterns but lost substantial moving
low-frequency detail. Larger capped boosts also flattened bright patterns.
Those filters are not part of this DLL.

The final production-chain test used 64 frames at 192×128, seed 923, original
guides, production conversion DXIL for every frame, the real AMD RR DLL, and
production composition DXIL for the last frame. Measurements use the second
half of each sequence:

- Static: low-frequency error 0.043571 → 0.009267 (78.7% lower), total RMSE
  0.045974 → 0.011819; detail regression gain in the dark-guide region
  0.7492 → 0.9088, bright-guide region 1.0133 → 1.0137.
- Moving broad pattern: low-frequency error 0.044245 → 0.006654 (85.0% lower),
  total RMSE 0.046895 → 0.010021; detail gains 0.7442/1.0285 → 0.9153/1.0181.
- Temporal error-difference RMS is not uniformly better: static
  0.000718 → 0.000763; moving 0.006445 → 0.007457. These include errors from
  a deliberately moving texture without texture motion vectors. This candidate
  is not a verified general solution to shimmer/disocclusion.
- Separate CPU-factorization/real-RR tests cover colour, finer patterns and
  bright guides. Six tested scene types improved low-frequency error with the
  selected factor; no claim is made for every material or lighting condition.
- A longer 128-frame exposure stress run reduced HDR patch error by 44.5%,
  clean-input patch error by 87.4%, and moving-bright patch error by 60.9%.
  The dim fixture regressed slightly: RMSE 0.0003987 → 0.0004050 (1.6%),
  patch error 0.0002369 → 0.0002495 (5.3%), with essentially unchanged detail
  contrast. This prevents any claim of universal noise/error improvement.

These percentages describe synthetic image error, not a percentage of the
game's defects fixed. The tests do not include real sea buffers, disocclusion,
the game's postprocessing, upscaling, or frame generation. The integration
contracts separately exercise Floor enabled/disabled, HDR, black albedos,
emissives, Direct/Indirect and identity closure.

Release validation passed 905 GPU checks over 1867 dispatches, shader-layout
mirrors, INI checks and the Release x64 build. Two historical comparison suites
were skipped because their pinned reference packages were not supplied; they
are not counted as passes. The new dedicated scale contract contributes 118
checks over 120 dispatches.

On the RX 9070, alternating isolated GPU measurements at 1505×847 (three
A/B trials, 17 repetitions each) measured conversion 0.84356 → 0.84452 ms,
ordinary composition 0.22576 → 0.22680 ms, and full selected-surface composition
2.77824 → 2.75728 ms. Differences are within normal measurement variability;
no speedup is claimed. These are synthetic shader timings, not full game/RR
frame times. The selected-surface fixture is intentionally a worst-case coverage
comparison and does not mean the sea is sent through display recovery.

## Evidence and reproduction

Reports are under `tools_tmp/albedo_gain/`: `production_rr_verified/results.json`,
`specular/results.json`, `exposure_long/results.json`, rejected candidate directories, and
`validation_final/summary.json`. Each real RR case records D3D12/SDK diagnostics
and a preview with clean/noisy/result arrays. The probe records the AMD DLL hash.

```
python OptiScaler/shaders/shader_tools/tests/probe_fsrd_albedo_gain.py --output tools_tmp/new_rr_run --frames 64 --scenes static,moving_slow --variants baseline,spec4 --signals indirect --seed 923 --production
python OptiScaler/shaders/shader_tools/validate_fsrd.py --output tools_tmp/new_validation --build
```

In-game acceptance: compare the same sea viewpoint after history settles, then
pan across the shoreline. Check wave sharpness, stationary patches, dark water
grain, and newly revealed regions. Also recheck TV/billboard recovery and bright
reflections. The new switch allows immediate rollback without replacing the DLL.
