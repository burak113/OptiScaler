# Fixed roughness diagnostic

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

Advanced Settings → Input Compatibility → **Fix Roughness** enables an exact,
global RR roughness override. **Fixed Roughness** accepts 0–1 (default 0.1).
The checkbox defaults off. It works with Floor enabled or disabled.

Persistence: `[FSR-RR] FixedRoughnessEnabled` and `FixedRoughness`. Runtime values
are finite-checked and clamped; non-finite values fall back to 0.1. Active value
changes and checkbox transitions invalidate RR history and Floor decision history.

The override is applied in input conversion after the selected-screen compatibility
roughness minimum. It leaves original roughness, Floor extraction, surface selection,
material IDs, albedos and RGB signal splitting unchanged. The existing specular
tracking calculation consumes the overridden roughness, as does RR. Consequently
this is not an isolation of AMD's neural network alone.

`InputRoughness` and `RawRoughness` continue to show original guides.
`EffectiveRoughness` shows the value sent to RR. `AppliedRoughness` remains the
selected-screen compatibility lift diagnostic, not the global override.

Production DXIL tests cover disabled-path equivalence, Floor on/off, endpoint and
intermediate values, invalid values, original/effective debug views, and preservation
of material IDs and signal splitting. These tests do not execute the AMD model or
establish that a fixed roughness improves the sea in CP2077.
