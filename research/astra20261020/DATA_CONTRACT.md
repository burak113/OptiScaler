# Data contract and limits

NPZ files are loaded with `numpy.load(path, allow_pickle=False)`. Do not replace
raw data with an average to study heavy tails: averaging removes the observable.
Read the per-fixture manifest and array names before using it.

For chronological native clips, preserve these source formats:

- depth: float32.
- motion: float16 RGBA; RG are full-render UV displacements toward the previous
  frame, B is the captured signed previous-minus-current linear-depth delta.
- normal/roughness: uint32 R10G10B10A2 encoding. Normal is octahedral in RG,
  roughness in B, material code in A. Original and prepared guides can differ.
- input diffuse/specular, raw RR and selected RR: float16 RGBA. Input alpha is
  hit-distance data; do not filter or discard it. Selected RR is the existing
  recovery result, not a reference image.
- provider controls: 46 uint32 words, preserving original floating point bit
  patterns and frame indices. Decode according to the current source ABI.

Never assume a semantic material class: all original material IDs in the
published 2405 and 87ee captures were zero. A fixture crop is not a full frame.
For a changing crop origin, previous local sample position is:

`current_local_pixel + current_render_crop_origin + motion_RG * render_extent
 - previous_render_crop_origin`.

Mark history outside the previous crop invalid; clamping it manufactures
history. A partial sequence has no pre-start history. Do not loop the sequence
to manufacture steady state or reset the original controls/frame ID to zero.
RGB lobe sums should be computed in float32 from original half inputs; another
half store introduces a new quantization stage.

Anchor fixtures have already-recalled keys, not the raw six-slice key textures.
Their native policy frames ran actual native Stats/Gain shaders on an extracted
harness; they do not prove native bridge routing. Native ratios are bounded
estimates from stored FP16 fields because original 16.16 atomic sums are absent.

Colour fixture is frame 63 with prior history warmed on CPU through frames0–62.
It is not a full temporal GPU replay. A few original pre-UAV float32 guide low
bits are absent, so soft2's stored expected output cannot be demanded bit-exact.
The verification report records that difference.

Historical local receipts contain tests not runnable from this small package.
Sanitized `local-only:/...` paths are identifiers, not downloadable GitHub URLs.
SHA256 proves file identity, not correctness of the claim inside the file.
