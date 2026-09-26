# Virtual albedo retired; return to spatial Floor

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

2026-09-21. The user rejected the virtual-albedo direction after testing: extra
cost, insufficient sharpness, and illumination noise visible in CarrierAlbedo.
The [causal audit](fsrd_virtual_albedo_noise_audit.md) reproduced contamination
before RR and documented an additional dark-carrier/HDR Skip escape path.

## Current production behavior

The established Floor -> conversion -> AMD RR -> Anchor/Correlation composition
path remains. This is the normal algorithm that ran with the experimental toggle
off, including the later small-text, colour and luminance recovery fixes. It is
not a rollback of those earlier improvements or a reset of unrelated work.

Removed from production:

- Virtual-albedo menu option and configuration field.
- Seven carrier shaders, constant buffers and all carrier-only resource/history
  management, swaps, dispatches, commit/reset hooks and unused frame index.
- CarrierPattern and CarrierAlbedo views and project/build/mirror registrations.

`FloorVirtualAlbedo` is no longer read or written as a setting. Normal INI save
removes that retired key while retaining Anchor, Correlation Mix and unrelated
keys. No game INI is rewritten by the development tools.

The title's original diffuse/specular albedos still fulfill their ordinary
demodulation, RR guide and remodulation roles. No synthetic material is generated.
Existing geometry/albedo guidance and `AlbedoStructureAvailability` remain.
FloorZeroNoise remains an isolated debug estimator, executed only for its debug
views; it is not added to the regular frame.

The five surviving shader binaries are required to match the pre-retirement
normal path byte for byte. This provides an exact shader baseline for later work,
not a claim that the established algorithm is free of all game artifacts.

## Follow-up: surface evidence, not replacement material

Implemented at the user's subsequent request: [surface selection](fsrd_surface_selection.md).
The existing diagnostic menu is retained; no new experimental toggle or material carrier
was introduced. The following describes the evidence and limitations motivating that change.

Use the lack of texture structure in the game's albedo as supporting evidence
for a radiance-only texture. Do not classify every flat or bright albedo as a
screen. The next isolated experiment should compare:

1. Valid original diffuse and specular albedo structure within a geometry-consistent
   neighborhood. Missing/invalid data is unknown, not proof of a screen.
2. Coherent colour/text structure in current radiance that the albedo does not
   describe, with a noise allowance so grain is not counted as texture evidence.
3. Surface continuity and confidence. Original zero roughness can remain a useful
   CP77 hint, but must not be a universal permission by itself.

Expose confidence and rejection reasons as diagnostics first. Compare against
ordinary painted walls, mirrors, moving reflections, particles and smooth
illumination; all can combine flat albedo with varied radiance. Do not expand
handover eligibility until false positives and missed small panels are measured.
Any future temporal support should be justified for this decision separately
from the rejected full virtual-material reconstruction.

Anchor=4 and Correlation Mix=1 remain the user's comparison baseline. This
retirement does not introduce the new classifier, change RR's supplied albedo,
or claim that noise/blur has been solved. Its purpose is to remove an unsuccessful
runtime branch and resume work from the preferred established algorithm.

## Reproducibility

Before removal, runtime sources, shader artifacts, integration tests and their
bindings were saved in a verified ZIP under
`tools_tmp/floor_virtual_albedo_retired/source_before_retirement_20260921_204253.zip`.
The manifest is `tools_tmp/floor_virtual_albedo_retired/retirement.json`.
Earlier DLL packages and synthetic results remain under `tools_tmp/floor_virtual_albedo`.
The independent offline DCT experiment keeps its kernel in its test HLSL and no
longer depends on a production carrier include.

The return package checks INI cleanup, production DXIL GPU contracts, Anchor and
Correlation behavior, ZeroNoise debug isolation, shader mirrors and Release x64.
Its packaging gate verifies all surviving shader bytes are embedded and all
retired carrier shader bytes are absent. Fresh results and the DLL are in the
timestamped directory under `tools_tmp/floor_virtual_albedo_retired`.
