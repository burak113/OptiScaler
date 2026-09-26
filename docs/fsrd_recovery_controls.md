# Floor recovery controls

The main Floor section exposes Enable Floor and Floor Recovery. The latter is
a linear master gain for all enabled recovery paths. Zero performs ordinary
Floor/RR composition without recovery neighbourhoods or recovery history.
The existing selected-screen input routing is preserved: it does not restore a
noisy pedestal to Skip when the recovery gain reaches zero.

Advanced contains three independent enables and one algorithm selector per enable:

- Flat Albedo & Zero Rough Recovery retains the existing original-albedo
  classifier. Exact zero roughness is a hint inside that classifier, not a global
  mirror/water selector. Enabled by default, using Anchor.
- Specular Recovery restores the estimated specular share of missing detail.
  Disabled by default; Light Anchor Mix is its initial method.
- Diffuse Recovery restores the complementary diffuse share. Disabled by
  default; Light Anchor Mix is its initial method.

Flat recovery owns its selected pixels. Outside that selection, diffuse and
specular share the correction rather than each adding a complete correction.
The game currently supplies combined colour rather than separate raw lobe
radiance, so both methods use the combined reference and an albedo-derived
contribution estimate. These labels do not imply true isolated reflection or
diffuse buffers.

## Algorithms

Anchor / Correlation / Chroma / Luma retains the existing regional statistics,
colour covariance anchor, correlation rejection, and supported contrast recovery.
Anchor and Correlation Mix now live in Advanced. Luma Recovery and Chroma Recovery
scale their respective contrast extensions from zero to one; they do not disable
the base anchor correction. These four controls are shared by systems selecting
this algorithm. Mixed lobe choices evaluate the expensive anchor only once.

Light Anchor Mix replaces the former Spatial + Temporal method. It transfers
the current reference through compact RR anchoring, correlation, noise and
supported-range gates. Neighbourhood samples supply statistics; no colour
history or spatially averaged replacement reference is used. Metadata is still
written to support adjacent Anchor pixels. This avoids colour-history phase
averaging but can still attenuate uncertain detail. See the
[current checkpoint](fsrd_floor_recovery_release_20260926.md) for defaults,
limitations and final validation. Earlier spatial/temporal reports describe
retired algorithms and are not the current runtime contract.

Every algorithm/enable/gain or albedo-control change resets denoiser and recovery
history. Resizing and frame reset retain the existing reset mechanism.

## Graduated albedo controls

For each lobe, its effective normalization multiplier is `lerp(1, A, strength)`.
Input division and output multiplication use the same multiplier. One retains
the original modulation; zero uses unity. Original albedo guide RGB and signal
split are preserved. These sliders do not create replacement game albedos.

Reducing modulation also gradually routes that lobe's Floor pedestal through RR,
preventing Skip from retaining the selected lobe's bypassed artifact. The other
lobe retains its corresponding Floor share. Explicit game bias/responsivity
routing remains in force; there is no double addition of that radiance.

Fix Roughness, normalization A/B, signal-balance A/B, bypass isolation and bypass
Floor-routing options are retired. Their old INI values are ignored and removed
when saving. `FloorDetailPreservation` is migrated to
`FloorRecovery = clamp(3 * oldValue, 0, 1)` because the previous shader saturated
its effective strength at one third. New installations default to Floor Recovery 1.

## Validation boundaries

`test_fsrd_recovery_controls.py` executes the production conversion/composition
DXIL on D3D12. It checks matched arithmetic, unchanged guide RGB, zero recovery,
complementary lobe ownership, independent algorithm selection, linear strength,
known-target detail/noise error, history rejection, motion/jitter mapping and
clean coloured edges. Existing Floor, contrast and temporal suites cover the
retained algorithm. Full-strength fixtures now use 1 instead of the old 0.35.
`test_fsrd_light_anchor_mix.py`, `test_fsrd_animated_recovery.py` and
`test_fsrd_specular_noise_return.py` cover the current compact method. Historical
ST accumulation probes remain archived and are not part of the active suite.

These are synthetic shader tests with independently supplied RR outputs. They
do not execute AMD's neural denoiser or establish a fix for the Cyberpunk sea.
In-game detail, animation and disocclusion still require observation with the
new controls; synthetic timing is composition-only, not total Floor/RR time.

Adaptive Specular Demodulation and its effective-guide/flash-guard path are
removed. DemodRisk remains read-only; the two global albedo sliders remain.
