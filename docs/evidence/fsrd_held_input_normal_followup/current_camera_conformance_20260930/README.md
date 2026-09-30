# Current and previous camera: conversion-only conformance

This package is CPU-only. `results.json` binds the source hashes and four NPZs.
No earlier fixture/evidence, registered tests, or production shader was changed.

Current camera: world position `[.3,.1,-.2]`, world-to-view Y rotation `.17rad`.
Previous camera: world position `[.29,.1,-.2]`, Y rotation `.15rad`.
For row vectors, each view is `Translation(-camera_position) @ RotationY(angle)`.
Every consumed view, inverse-view, projection and inverse-projection matrix is
rounded to float32 before predictions. Matrix bytes are contiguous row-major;
default HLSL column-major plus `mul(matrix,column)` consumes the compatible
transpose. Quantized inverse matrices have recorded small closure errors.

An independent pinhole ray intersects the fixed world plane `Z=10`. The current
camera linear Z varies from8.94228768 to12.28143603. Both current and previous UVs
refer to the same world point. Primary MVXY is `previousUV-currentUV`; MVZ is the
previous-camera linear depth of that current surface minus current-camera depth.
There is no previous-depth lookup, reflection motion, temporal filtering or
clean radiance-quality target in this test.

The four arms are linear/hardware depth × world/view-space normal. Depth is R32;
normal and motion inputs are FP16; roughness is external R32 `.1`. World normal
is `[0,0,-1]`; view normal is its current-view transform, then upload quantization
and inverse-view transform are accounted for. Flags respectively34,2082,32,2080.
Hardware depth tests the defensive direct-input reconstruction branch, not the
production FloorSeed canonical-linear-depth pipeline or native RR depth input.

Root GPU specification: authenticate each NPZ and override dictionary from
`results.json`, run each arm at strength0 and1 using `kernel='auto'` and current
`directory=t.PRE`, and retain actual CB/in/out/job/stdout before cleanup.
This is eight conversion dispatches, zero native RR calls. Source auto selection
chooses `FSRDInputConv` at0 and `FSRDInputConvAdditive` at1.

Expected arrays in each NPZ:

- `expected_converter_motion_fp16`: XY includes the actual FP16 input rounding;
  B uses consumed matrices and R32 depth; A=1.
- `physical_mvz`: independent same-world-point previous-minus-current depth.
- `expected_converter_world_normal`: includes FP16 input-normal quantization.
- `expected_normal_R10_decoded` and `expected_world_normal_after_R10`: texture
  format and oct decoding references.
- `expected_specular_alpha_fp16`: per-pixel reconstructed current depth, because
  specularTracking is fully open at roughness `.1`; diffuse alpha is65504.

Frozen tolerances: all-pixel motion/physical MVZ and specular alpha use maximum
neighboring FP16 ulp +`1e-5`. Primary MVXY must equal consumed FP16 input exactly;
motion A must be1; diffuse A must be65504. Normal primary conformance compares
decoded world-normal angle against `[0,0,-1]`, maximum `.003rad`. Roughness uses
`1/1023+1e-4`, material ID0. Ideal `-Z` is an oct atlas corner; raw oct equality
across normal-space arms is not an acceptance requirement. Raw encoding can be
reported diagnostically with seam-aware interpretation.

`seam_notes.json` verifies from local HLSL algebra that all four exact oct corners
decode to `-Z`, and that world `+Y` is the midpoint of the top oct edge. Mirrored
points on that edge decode to equal Y/Z normals. This is a future controlled
input-equivalence lead; it is not a measured native invariance result, a cause of
old same-input context variability, or a game stain/wave solution.
