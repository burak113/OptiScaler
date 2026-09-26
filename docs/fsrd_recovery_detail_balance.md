# Restore detail after the spatial/temporal noise guard

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

The user confirmed that the September 25 noise guard removed most grain, but
reported a large loss of detail recovery. Controlled production-DXIL ablations
identified the contrast cap as a cause: it limits recovery using
`saturate(16 * RR_variance / reference_variance)`. A heavily blurred RR result
therefore restricts the very detail that recovery should restore, even after
many frames of valid reference history.

The cap now relaxes toward one using the existing accumulated colour-history
support. Correlation checks, local noise rejection, spatial filtering, temporal
clipping, material/depth/normal checks and the recovery master remain in place.
No-history and rejected-history pixels retain the previous cap exactly. This
adds one scalar interpolation, no texture reads, pass, allocation or setting.
The separate Anchor algorithm is unchanged.

## Evidence

`test_fsrd_recovery_detail_contrast.py` exercises severe RR blur on fine and
diagonal patterns, camera translation, actual FloorSeed references and newly
revealed regions. Independent clean truth supplies the contrast/error metrics.
When supplied the frozen preceding shader, it also requires bit-identical
first-frame/disocclusion protection and at least a 20% reduction in detail MSE.
It is included in `validate_fsrd.py`.

The initial ablation, after accumulation, measured:

- Fine texture contrast: 60.5% -> 69.9% of ground truth.
- Diagonal texture contrast: 19.5% -> 75.6%.
- Moving fine texture contrast: 60.0% -> 68.3%.

These are synthetic signal-contrast ratios, not percentages of perceived game
sharpness. Specular recovery owns an 80% share in these fixtures.

The existing noise-return suite still passes its absolute budgets. Rejected
history, zero-alpha noise, correlated noise without history, smooth zero-alpha
noise and impulses retain identical aggregate errors. Static/moving fine-grain
errors remain around 5e-9. Shared-residual-noise MSE changes by approximately
0.09%, remaining below the original supplied RR error.

The cap only relaxes with accepted history. Newly revealed surfaces can still
take several frames to regain detail. If the game provides invalid motion or
changes the material guides continuously, this change will conservatively keep
the previous protection. Synthetic passes do not certify Cyberpunk image quality.

Frozen baseline, full GPU validation, benchmarks and delivery artifacts live in
`tools_tmp/recovery_detail_balance/`.

The final Release DLL passes 303 checks over 1,267 production-DXIL dispatches,
with the D3D12 debug layer enabled and zero validation errors. Its embedded
shader bytecode matches the tested CSOs. These include the previous recovery,
noise, history, luma/chroma and volumetric checks as well as 21 new detail checks.

Two RX 9070 timing runs at 1505x847, with baseline/current order reversed,
measured spatial/temporal composition at 1.09-1.12 -> 1.12-1.16 ms without
history and 1.42-1.45 -> 1.39-1.43 ms with history. The unchanged Anchor path
also varied by about 0.08 ms. There is no consistent history-path cost increase;
these measurements do not promise a particular in-game FPS result.
