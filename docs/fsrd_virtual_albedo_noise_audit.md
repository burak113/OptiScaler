# Virtual albedo: post-game noise audit (2026-09-21)

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

**Historical audit of the retired experimental build.** The findings below refer
to that build. Its sources and isolation probe are archived; see
[the retirement decision](fsrd_virtual_albedo_retirement.md).

The user reports blur and noise in the experimental build and confirms that
**CarrierAlbedo itself is noisy**. This establishes contamination before RR;
it does not establish that every output artifact has the same source. No game
frame was captured for numerical measurement during this audit.

## Verified routing

`DispatchCarrier` runs before `GetSignals`. It swaps both signals, both albedos,
Skip and DetailReference into the resources that `SetDescResources` binds to RR.
Composition reads the same albedos. For carrier-selected pixels:

```
A = quantize(clamp(reconstructed pattern, 0.008, 1))
S = FP16(clamp(C * specular_share / A, 0, 65504))
D = FP16(clamp(C * diffuse_share / A, 0, 65504))
K = max(C - (S + D) * A, 0)
result = A * RR(S) + A * RR(D) + K
```

DetailReference alpha is -1, so the old Floor detail/Anchor/Correlation correction
does not run here. Outside eligibility, the existing path is deliberately retained.
An explicitly disabled signal uses its input instead of RR output; the new audit
enables both direct diffuse and indirect specular, as separate typed signals in
one real RR dispatch. No extra transparency/particle overlay is added by this
composition. Post-upscaler sharpening and title presentation are outside this audit.

Actual production Pack/Composition DXIL tests show:

- Changing the incoming old Skip from 3 to 500 leaves all seven selected outputs
  bit-identical. Pack replaces it.
- Zero RR signals produce only the newly computed Skip.
- Zero RR signals **and** zero Skip produce exactly black, despite nonzero
  reference and enabled Detail Preservation/Anchor/Mix.

## The principal reconstruction weakness

The ZeroNoise base is not an invariant of the reconstructed image. Forward DCT
subtracts it from current/history observations; inverse DCT adds it back. When
the coefficient gain is near one, the two operations reconstruct the observations,
including their illumination noise. Four similar observations are insufficient
evidence that their shared structure is texture.

With a constant, perfectly clean 0.4 base and four identical noisy observations,
the production DCT gives observation RMSE 0.0554931 and candidate RMSE 0.0554499.
The candidate differs from the noisy observation by at most 0.000700593. Thus
almost all this noise survives even though the starting base has zero error.
This is an adversarial controlled input, not a claim of identical game frames.

There is a second re-entry path: when fewer than two complete observations survive
the 8x8 block validity test, the algorithm uses the existing DetailReference and
sets its coefficient gain to one. It does **not** retain only ZeroNoise there.
This can carry the spatial reference's remaining grain and blur into albedo.

Remodulation cannot make a noisy carrier clean by itself. Replacing both RR
irradiance outputs by their ideal constant sum of one still reproduces the noisy
albedo. With A close to C, C/A is nearly constant, leaving little of that grain
in the signal RR is asked to clean.

## Real AMD RR intervention

`probe_fsrd_carrier_isolation.py` uses the shipped Pack/Composition DXIL, both
signals together, actual UNORM/FP16 storage, and the real AMD RR DLL on RX 9070.
The current carrier sequences are reused only after verifying their producer
shader hashes. A known-clean carrier is a separately labelled synthetic oracle;
it is not available to the game algorithm. Five cases of 32 frames ran with zero
SDK and D3D12 errors/warnings.

- Fine independent noise: current-carrier output RMSE **0.0223532**, oracle-carrier
  output RMSE **0.00383267**. Flat-region temporal standard deviation changes
  **0.0114768 -> 0.000433934**, a 96.2% reduction in this synthetic case.
- Coarse correlated noise: current-carrier output RMSE **0.0741875**, oracle-carrier
  output RMSE **0.0293530**. Flat-region temporal standard deviation changes
  **0.0465588 -> 0.00668965**. Even the oracle leaves measurable RR error.
- Deliberately using the observed noisy image as albedo gives output RMSE
  **0.104964**, close to input RMSE **0.108838** despite both RR signals running.

These are error metrics, not percentages of defective game pixels. The oracle
comparison establishes a causal synthetic sensitivity to albedo quality, not
complete attribution of the user's game screenshot.

## Skip is small normally, but not guaranteed small

In these normal-range sequences, Skip RMS is approximately 0.00016-0.00018. It is
far below the measured output error. Removing Skip cannot fix the carrier noise.

There is nevertheless a genuine HDR escape path. With current C=12000 and a dark
carrier quantized to 2/255, both half signals saturate at 65504, and stored Skip is
10968: **91.4%** of the input bypasses RR. The earlier HDR closure test missed this
combination because it raised the carrier together with the radiance. This is a
representability limit, not evidence that this value occurs on the user's screen.
Simply dropping that remainder would destroy brightness; it needs explicit
range management rather than claiming zero bypass.

## Consequence for further work

The integration is connected, but the carrier reconstruction is not accepted as
a nearly noise-free albedo. Its previous RMSE improvements were insufficient as
an acceptance criterion. Required follow-ups are:

1. Separate a base-only RR control from detail reconstruction in the game so that
   clean-base quality, recovered-detail contamination and RR residual can be seen
   independently, with explicit eligibility/fallback diagnostics.
2. Replace the raw temporal-mean and spatial-reference escape paths with detail
   acceptance that also rejects persistent illumination; a shared four-frame
   coefficient alone must not establish clean texture. Unsupported detail must
   retain the base, accepting blur instead of silently restoring grain.
3. Audit carrier noise/temporal instability before RR, independently of final
   image error, and validate dark-carrier/HDR range management.

No production shader or DLL was changed during this audit. Raw evidence is in
`tools_tmp/floor_virtual_albedo/isolation_audit/results.json`; the test script is
under `OptiScaler/shaders/shader_tools/tests/probe_fsrd_carrier_isolation.py`.
