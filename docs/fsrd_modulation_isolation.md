# Per-lobe modulation diagnostic

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

Follow-up: [Floor bypass routing](fsrd_floor_bypass_routing.md) adds a separate
`Route Bypassed Lobes Through RR` switch, default on only during bypass. Disable
it to reproduce the Floor-on routing described by the original diagnostic below.
The Floor-off comparison is unaffected.

The constant indirect-specular radiance scale failed the user's target sea scene.
Do not extrapolate the earlier synthetic patch-error reductions to game quality.

Advanced → Input Compatibility → **Modulation Isolation (A/B)**:

- Off: original modulation, after selecting this combo (selection clears the older experiments).
- Bypass Diffuse Only: diffuse division and matching composition multiplication use 1.
- Bypass Specular Only: specular division and matching composition multiplication use 1.
- Bypass Both: identical to the earlier Bypass Albedo Modulation control.

Original RR albedo guides, diffuse/specular sharing, hit distances, roughness and
Floor selection remain unchanged. Residual closure uses the selected multiplier
as well. Mode changes reset RR history. All modes default off. INI key
`[FSR-RR] ModulationIsolation` accepts 0–3 (runtime clamps invalid values).
Isolation takes precedence over stale older A/B settings. Choosing an older
experiment clears isolation; choosing any isolation entry clears the older modes.

For the game test, keep Floor off, Fix Roughness off, Debug View None and
Specular Signal Auto. Select Diffuse Only and then Off once to clear a previously
saved experiment. Compare Off, Diffuse Only, Specular Only, Both at the same
camera position after history has settled. Report stationary blotch visibility
and wave sharpness independently for each mode. Do not change signal type,
exposure, camera or other settings during the comparison.

If only one lobe bypass removes patches, the next investigation can focus on its
factorization. If both single-lobe bypasses help, both contributions or the model's
cross-signal behaviour remain candidates. If only Both helps, independent-lobe
attribution is not justified. These interventions do not distinguish an input
division problem from output remodulation by themselves: both are changed as a
matched pair to avoid deliberately breaking image energy.

This is a diagnostic build. Blurring under bypass is expected to be possible,
and is not evidence of a final fix. No new filter, texture or dispatch is added.
