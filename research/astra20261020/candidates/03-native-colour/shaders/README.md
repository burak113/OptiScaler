# Source-shaped native shader proposal

`NativeColourPacked.hlsl` is a reviewable source proposal for the CPU model's
current-frame estimator. It has **not** been compiled or executed here. No CSO,
generated header or build integration is delivered as if already validated.

Proposed local compiler profile and command:

```text
dxc.exe -T cs_6_2 -E CSMain -HV 2021 -Ges -Gis -O3 NativeColourPacked.hlsl -Fo NativeColourPacked.cso
```

Use the project's audited DXC 1.8 toolchain first. Do not enable native 16-bit
arithmetic: all mean, guide, log and gain arithmetic remains float32. Resource
RGB is original half; its explicit final RTZ packing is in `HalfRtz`. Input
geometry SRVs are integer-loaded, with no hardware bilinear sampler involved.
The normal/roughness resource is the native `R10G10B10A2_UNORM` representation:
RG octahedral normal, B roughness. The CPU receives the corresponding decoded
unit XYZ normal and roughness. GPU UNORM decode, normalization, reduction order,
log/exp and fp32 arithmetic still require local parity measurement.

## Why integer-word staging

The contract requires every selected RGBA word on a protected pixel and **every
alpha word** to survive. Native alpha can contain hit distance, zero, signed zero
or another payload; it is not the combined pipeline's Skip channel. A typed
`float4` FP16 load/store round trip is not a universal proof of preserving NaN
payloads and signed zero. This proposal instead addresses original half words.

For **each lobe independently**, job 08 must implement these operations in the
existing retained recording/lease system after provider de-normalization and
all original selection/recovery passes but before title commit:

1. Preserve the original physical input, raw RR and selected texture references.
   Allocate three private raw buffers with `GetCopyableFootprints`-compatible
   `R16G16B16A16_FLOAT` footprints, retaining their row pitches and offsets.
2. Copy the three textures into their buffer footprints using `CopyTextureRegion`
   and appropriate resource transitions. This is a bit copy, not a shader-format
   conversion. Copy the full original selected footprint into a separate output
   buffer with the **same selected/output footprint layout** before dispatch.
3. Bind immutable source/raw/selected raw-buffer SRVs, original physical linear
   depth, corresponding normal/roughness SRV, and an explicit integer authority
   mask. Authority must be a validated host/provider policy; it must never come
   from native alpha. Selected/raw **RGBA word** equality is computed before any
   output write and includes all four half words.
4. Run `CSMain` once per lobe, then a UAV barrier. The shader writes only RGB words
   of eligible pixels, packs alpha with `selected.y & 0xffff0000`, and leaves all
   other output bytes from the initial selected copy. Inputs never alias output.
5. Copy the output buffer footprint to an owned native output texture; retain
   buffers, texture, descriptors and constants through command-list completion.
   Update both selected pointers and commit SRV descriptors together. Preserve
   existing selection if any prepare/allocation step fails.

All extents, pitches, offsets, formats, raw-buffer alignment, descriptor ranges
and capacities must be validated on the host. In particular, reject any texture
format other than this explicitly implemented FP16 format; the NumPy model also
supports float32 contracts for diagnostic purposes, but this shader does not
implement an R32 path. The byte-address arithmetic uses uint32, so every largest
offset plus accessed row/pixel must fit in 32 bits. A future direct integer view
could remove staging **only after** proving resource/view compatibility and
word-preservation with a local test; do not assume a typed view reinterpretation
is legal for the production allocation.

## Analytic cost, not measured performance

With radius 3, a compute thread visits at most 49 full-resolution taps. There is
one compute dispatch **per lobe**, no history texture and no coarse-grid pass.
It also requires copies: three texture-to-buffer copies, one selected-buffer
copy, and one buffer-to-texture copy per lobe. These cannot be described as a
free one-pass production operation.

Excluding footprint padding/alignment, descriptors and retained-flight copies,
the conservative unaliased scratch layout is four 8-byte-per-pixel packed buffers
plus one 8-byte-per-pixel output texture: **40 bytes per allocated pixel per
lobe**, or **80 bytes for D+S**. The proposed FP32 diagnostic UAV adds 16 bytes
per pixel per lobe, making the diagnostic build **112 bytes per pixel for D+S**.
The existing native input/raw/selected allocations are not included in that
increment. Actual allocated bytes must use `GetResourceAllocationInfo` and the
shared family budget, including retained resources. No GPU timing, resident VRAM
or final-game cost has been measured. This conservative diagnostic implementation
is a research vehicle, not a claimed performance-ready native feature.

## Explicit CPU/source-shape differences to test locally

The CPU produces diagnostic means and weights even for protected pixels, useful
for analysis; this shader returns early for protected pixels and reports their
eligibility only. The writable RGB contract is the same. CPU radius defaults to
3, source means are accumulated in dy-major/dx-minor order, and FP16 output is
explicit RTZ. CPU source validity is finite nonnegative RGB; alpha is ignored.

No statement of CPU/GPU equality follows from these matching expressions. Local
validation must compare synthetic constant closures, all-phase boundaries,
stochastic zero/tail support, a true ON canary, and bitwise alpha/protected NZR
results against the supplied CPU reference, then fresh AMD RR and final same-crop
game output. The separate `GPU_REQUEST.json` and adapter specification govern
that work. Keep the feature default-OFF and do not apply it to production as
part of this independent job.
