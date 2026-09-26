# Floor recovery checkpoint and adaptive demodulation retirement

This is the current feature guide for the 2026-09-26 checkpoint. Earlier FSRD
reports describe experiments and intermediate builds; where they differ, this
document and the production shaders describe the supported implementation.

## Problem and outcome

Floor preserves the low-frequency signal, including volumetric contributions,
that can be lost when the combined game colour is converted into denoiser inputs.
Optional recovery restores supported detail from a current-frame reference.
The work since the previous checkpoint separates these responsibilities, adds
independent recovery controls, and replaces the experimental spatial/temporal
colour accumulation with a cheaper Light Anchor Mix method.

Adaptive Specular Demodulation is removed. In the user's Cyberpunk scene it
continued to produce white flashes when enabled, even after mask stabilization
and an output guard. Passing synthetic mask and reconstruction checks was not
sufficient evidence of acceptable behaviour with the game's actual RR history.
This checkpoint does not claim to solve the underlying sea-albedo artifact.

## Main menu and Advanced controls

The main Floor section contains only **Enable Floor** and **Floor Recovery**.
Floor Recovery is a linear master strength from zero to one. At zero the spatial
Floor contribution remains active, but detail recovery is disabled. Turning
Floor off disables that contribution as well.

Advanced contains three independently enabled recovery systems, each with its
own Noise Removal selector:

- **Flat Albedo & Zero Rough Recovery** uses the original-albedo surface
  classifier. It is enabled by default with the full Anchor method. A zero
  roughness value contributes to the classification; it is not a universal
  water or mirror material identifier.
- **Specular Recovery** restores the estimated specular share of the correction.
  It is disabled by default and initially selects Light Anchor Mix.
- **Diffuse Recovery** restores the complementary diffuse share. It is disabled
  by default and initially selects Light Anchor Mix.

Flat recovery owns its selected pixels. Elsewhere, enabled specular and diffuse
paths split the correction instead of each adding the whole correction. These
shares are estimated from albedo: the integration receives combined colour,
not independently traced raw diffuse and specular radiance. The controls should
not be interpreted as perfect physical lobe isolation.

Advanced also holds Handover Anchor, Handover Correlation Mix, Luma Recovery and
Chroma Recovery. Their respective algorithms use these shared controls; mixed
choices reuse the full Anchor computation instead of running it twice.

## Retained recovery algorithms

**Anchor / Correlation / Chroma / Luma** uses regional reference/RR statistics,
covariance-based colour anchoring, correlation rejection, and bounded luminance
and chroma contrast recovery. Temporal assistance stabilizes decisions rather
than accumulating the recovered colour. Previous decisions have bounded reuse
and deviation from the current decision; a current zero gate cannot be revived
by history. Reprojection checks motion, jitter, depth, normal, material,
roughness and content support. Failed frames, resets, interpretation changes,
debug transitions and control changes invalidate the relevant history.

**Light Anchor Mix** replaces the former Spatial + Temporal selection. The
current-frame reference is the colour source. Its compact neighbourhood and
wider taps provide statistics and noise evidence, not a spatially averaged
replacement colour. It does not accumulate previous-frame colour. RR statistics
anchor the candidate; correlation, residual-noise estimates and supported-range
limits constrain detail transfer. Luma/chroma extensions recover supported
contrast without adding it twice. Metadata is still written so adjacent full
Anchor pixels can validate their history.

This removes the former colour-history phase averaging on animated reflections.
It does not guarantee perfect sharpness: confidence gates and noise limits can
still attenuate real detail, and single-frame evidence cannot always distinguish
fine reflection structure from noise. Full Anchor generally costs more than
Light Anchor Mix. Synthetic dispatch timing is not an in-game frame-time promise.

## Signal flow and albedo controls

FloorSeed constructs the current reference and noise estimate. The spatial Floor
filter uses strides 1, 2, 4, 8 and 16. Conversion prepares RR signals and Skip;
composition remodulates the denoised signals, combines the retained Floor/Skip
contribution and applies enabled recovery. The reference and diagnostic views
expose these intermediate stages without implying that every reference sample
is noise-free.

**Specular Albedo Demodulation** and **Diffuse Albedo Modulation** remain global
zero-to-one sliders. For each lobe the effective multiplier is
`D = lerp(1, A, strength)`: zero uses unity and one uses the original albedo.
Input division retains the existing divisor floor; output multiplication uses
the corresponding effective multiplier. Original RR albedo guide RGB remains
available. These controls do not synthesize replacement albedo textures.

The sliders also affect how the corresponding Floor share is routed through RR
instead of retained in Skip. Therefore comparing zero and one is a complete
signal-path A/B, not an isolated test of division alone. The floor/clamping and
reconstruction-remainder rules also matter near zero albedo. Do not interpret
an improved zero-slider image as proof of an arithmetic error in one operation.

## Exactly what was retired

The adaptive checkbox and configuration field, mask/distance/stabilization
passes, dedicated protection histories, effective specular-albedo texture,
adaptive descriptor bindings, DemodProtection view and post-RR flash-guard pass
are removed. RR again receives the original specular-albedo resource at every
global slider value. No local adaptive demodulation decision runs in normal
rendering. This removes the experiment's extra dispatches and allocations; no
new denoiser or replacement automatic method is introduced.

**DemodRisk remains a diagnostic only.** Its grayscale view highlights joint
evidence of added normalized structure and divisor variation in the same
channel, with coherent-boundary gating. It uses pre-split raw colour and an
albedo-derived candidate chain. It does not model the entire Floor/RR pipeline,
classify water, or prove an artifact. Flat blob interiors can remain black;
genuine boundaries can produce false positives. No production correction
depends on this view. See [the diagnostic notes](fsrd_demod_risk_white.md).

Earlier Noise Suppression, Zero Noise, virtual albedo, Floor/RR surface routing,
fixed-roughness and normalization/bypass A/B options remain retired. Historical
reports and experimental probes are retained as records, not active features
or evidence that those experiments passed current game acceptance.

## Configuration and resource compatibility

Saving settings deletes the retired `AdaptiveSpecularDemodulation` INI key.
It is not loaded or applied. Existing global sliders and recovery settings are
preserved. The older `FloorDetailPreservation` key migrates to
`FloorRecovery = clamp(3 * oldValue, 0, 1)`; new configurations default to one.
The existing cleanup fixture now covers 29 retired keys and preserves unrelated
settings through a real SimpleIni load/save cycle.

Conversion binds 17 SRVs and 8 UAVs; composition binds 11 SRVs and 3 UAVs.
Constant-buffer layouts are unchanged by adaptive removal. C++ resource tables,
HLSL bindings, generated DXIL and embedded headers are checked together. The
GPU fixture loader retains optional legacy bindings solely for frozen historical
shader comparisons; those are not production resources.

## Validation and reproducibility

Run from the repository root using the documented Windows compiler/runtime:

```powershell
python -B OptiScaler/shaders/shader_tools/validate_fsrd.py --build --output tools_tmp/fsrd_release_validation
```

The output directory must be new or empty. The runner verifies mirrors,
recompiles all four shaders and checks byte identity, runs GPU and CPU contracts,
builds Release x64, and checks that the DLL embeds the validated shader blobs.
GPU dispatches require the D3D12 debug layer and zero reported validation errors
and warnings. Missing diagnostics fail validation rather than counting as zero.

Coverage includes composition accounting, current-colour contracts, surface
selection, recovery strength/ownership, clean detail and noise-return budgets,
motion/jitter/history rejection, animated recovery, diagnostics and INI cleanup.
Historical comparisons requiring an unavailable reference package are explicitly
skipped, never counted as passes. The final run results are recorded below.

These suites supply synthetic RR outputs; they do not execute the AMD neural
model or reproduce the user's Cyberpunk camera sequence. They validate the
shader integration and bounded fixtures. Sea appearance, motion noise, ghosting
and total gameplay cost still require same-scene in-game observation.

## Final results, 2026-09-26

- **883 GPU checks passed across 2,274 dispatches** on AMD Radeon RX 9070.
  Every recorded dispatch had the D3D12 debug layer enabled and reported zero
  validation errors and warnings.
- Mirror checks, reproducible shader generation, INI cleanup and reference
  integrity passed. Release x64 built successfully and contained all four
  validated shader blobs. DXC was 1.8.2502.11 from Windows SDK 10.0.26100.0.
- The first run correctly failed the stale RGB DemodRisk fixture. Its old
  green-only expectation contradicted the retained grayscale intersection view.
  The fixture now checks a known guide-only boundary, quiet constant interiors,
  rejected alternating guide grain, consistent factorization, constant gain,
  grayscale/bounded output and slider-independent baseline evidence. The
  production diagnostic arithmetic was not relaxed to make that test pass.
- An additional local removal A/B performed **27 exact stored-output comparisons
  across 54 dispatches** against the frozen pre-removal shaders with adaptive
  disabled. Conversion and composition matched at strengths 0, 0.5 and 1, with
  both recovery methods and 1x1, 17x13 and 48x32 images. This is bounded evidence
  for retained behaviour, not exhaustive equivalence. Frozen baseline artifacts
  are local evidence, not included in the portable release gate.
- Two reference-dependent suites (`small_colour_screen`, `colour_anchor`) were
  skipped because no reference package was supplied. Historical sub-comparisons
  in volume handover, speckle anchor and patch handover were also skipped. Their
  current-output checks still ran; no historical win is claimed.
- Python syntax checks passed for 60 shader-tool scripts, and the staged patch
  passed Git whitespace checks.

The compiler/linker build is not warning-free: it reports inheritance/conversion
warnings and the existing low-latency atomic/LIBCMT linker warnings. The legacy
post-build copy sequence also reports a missing auxiliary path. These do not
prevent the DLL from linking or passing shader embedding checks; the generated
full distribution directory is not certified as a complete redistributable
archive by this checkpoint. Delivery is the verified DLL with the game's
existing dependencies and configuration preserved.
