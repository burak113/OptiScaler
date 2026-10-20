# Job 08 adapter specification

Status: **research only; no native integration, compiled CSO/header, or GPU
execution is delivered**. `PRODUCTION.patch` only adds the standalone candidate
shader under the source tree's `precompile` directory. It is intentionally
unreachable. Applying that patch does not change a game's output or connect the
missing uncertainty source. This exact specification identifies the remaining
host work rather than inventing a sidecar or undocumented native resource.

## Pinned insertion point and OFF behavior

Pinned source: `5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`.
The protected path is `FlatAlbedoRecovery::DescribeFrame`, specular lobe,
`reflectionHistory && !temporal`, with `diffuseRR=true` and polish zero.
The source seam is `FSRDNrdFlatHybridApply.hlsl`, immediately after:

```hlsl
const float4 current = OutColor[p], decision = InMean[p];
const float3 base = SanitizeRadiance(InBase[p].rgb), rr = SanitizeRadiance(current.rgb);
float3 result = base + saturate(decision.x) * (decision.y * rr - base);
```

Call this result `S` and the original physical specular RR observation `R`.
The candidate operates on `C=S-R`. It does not change History, Seed, Refine,
Base, selector `(w,k)`, or provider input RGB. Do not read a final mode-2 output
and try to reconstruct `S` by dividing by 0.5: rounding and clipping make that
a different observation. Capture/stage the actual pre-Glass value.

The new host option defaults to false. When false, preserve the existing graph,
all protected settings, shader choice, SRV/output pointers, copies, barriers and
native commit exactly; **do not dispatch a pass that copies through**. Existing
shader/generated-header files remain untouched by job 05. The standalone
shader's `Enabled=0` branch is only a local arithmetic parity control and does
not establish native no-dispatch OFF equivalence.

ON is initially permitted only for that specular reflection path, polish zero,
existing Glass mode 2, validated current sidecar and original support. Other
paths or unavailable evidence keep the original output. Glass mode 1 is already
raw RR and gains nothing from this pass. Do not turn Temporal on, change the
floor, change G2/G3, disable DiffuseRR, relabel material IDs, or change the
existing Glass strength to arrange a favorable comparison.

## Required immutable inputs

All dimensions are the current native render extent, never an allocation
extent or the dimensions of an unrelated crop. Use the full-render (0,0) 2x2
block phase. For ROI-only local tests, the original render crop origin must be
even in both axes and include the complete 2x2 support; otherwise the current
prototype must abstain or a separately tested origin-aware version is required.

| Binding | Shader type / DXGI format | Required meaning |
| --- | --- | --- |
| t0 `InRawRR` | float4, original RGBA16F SRV | Physical specular raw RR before NZR and Glass. No synthetic provider rescale. RGB only is used by the transform. |
| t1 `InSelectedNZR` | float4, RGBA32F scratch | Actual pre-Glass `S`; stage before the original final FP16 store. Alpha carries the original raw/current alpha. Do not use Base alpha or history count. |
| t2 `InEligible` | uint, R32_UINT | Immutable original BASE eligibility for this pass. Require the original active specular recovery mask, fully vertical existing Glass gate, and the original pre-Glass RGB-changed subset. Do not recompute from candidate output. |
| t3 `InUncertainty` | float2, RG32F | x = `trace Cov(S-R)` in squared physical radiance; y = effective independent observations supporting that noise estimate. Includes S/R covariance. |
| t4 `InSupport` | int4, RGBA32_SINT | x = validity, y = justified spatial independence of the four correction-noise samples, z = nonnegative support surface ID, w = ABI version 1. |
| u0 `OutPreGlass` | float4, RGBA32F UAV | Distinct pre-Glass output, never aliases a read resource. Its alpha copies t1 alpha; the final native output must still take raw/current alpha. |

The surface ID is a private support partition validated from current original
geometry and transport. It is **not** an NRD material ID and does not imply
semantic glass. A phase-crossing glass/opaque block or ambiguous reflected
support must have different IDs or validity false. The implementation requires
all four pixels to be valid, independent, eligible, same-surface and above the
effective-count threshold. Incomplete odd rows/columns retain `S` exactly.

The host must verify the complete provenance before setting Enabled: current
frame ID, context/resource generation, producer shader revision, physical units,
exact raw/selected stage roles, dimensions, original crop origin/phase and
uncertainty-estimator version. The bool/version fields alone cannot prove
provenance. A DRS/reset/frame discontinuity invalidates a stale sidecar even
though this candidate carries no temporal RGB history itself.

`InHistory.a`, `InMoment.x` and their ratio are not an implementation of t3/t4.
They lack raw-selected covariance, independent effective support and the
cross-pixel noise assumption. A convenient local temporal variance of displayed
RGB is not automatically noise variance. No t3/t4 producer is supplied or
claimed in this job; unknown support is an intentional identity result.

## Constant-buffer ABI and defaults

`GlassConstants` is 32 bytes, with the ordinary D3D12 CBV upload aligned to 256
bytes by the eventual host. The candidate does not implement upload lifetimes.

| Byte offset | Type | Value / meaning |
| --- | --- | --- |
| 0 | uint2 | Size = actual current render width, height |
| 8 | uint | Enabled = 0 by default; 1 only after validated admission |
| 12 | uint | ContractVersion = 1 |
| 16 | float | NoiseScale = 1.0, preregistered; sensitivity is diagnostic |
| 20 | float | MinEffectiveCount = 8.0, preregistered; this is not a native count |
| 24 | uint2 | Reserved = (0,0) |

Finite nonnegative RGB up to 65504 is required in an accepted block. A negative,
overflowing or nonfinite reconstructed channel rejects the entire block. This
abstention keeps the low-band arithmetic distinct from a one-sided clamp.
The unchanged native sanitization still happens after Glass. CPU float32
rounding is modeled; exact D3D execution must be checked locally.

## Source-shaped staging that job 08 must implement and measure

On the validated ON branch only:

1. Preserve an immutable `R` reference through all new reads. Freeze pre-Glass
   `S` from the exact source arithmetic above into RGBA32F scratch, with raw
   alpha. Production HybridApply currently combines this calculation and the
   output store, so staging requires a split/variant with owned scratch; it is
   not a free extra expression in the existing in-place UAV pass.
2. Bind t0..t4, admit and retain all source/output resources in the same physical
   serialized family, transition to SRV/UAV states, and dispatch
   `ceil(width/8), ceil(height/8), 1` into a distinct output. There are no
   cross-thread writes or samplers in this standalone shader.
3. Feed corrected pre-Glass RGB into the exact existing Glass mode/gate/strength
   expression, retain raw/current alpha, then perform the original final
   sanitization and format store. Separate staging must not introduce a new
   FP16 quantization before this point. Keep original raw and selected stage
   labels available for trace.
4. Keep selected diffuse and every diffuse/alpha word unchanged; publish owned
   selected specular through the existing native commit lifetime. Restore
   resource states and barriers as required by the current scheduling owner.

The exact number of additional dispatches and allocations depends on how job
08 splits/fuses staging and the final Glass write. At minimum the standalone
experiment needs retained immutable inputs, a pre-Glass representation and a
distinct output. The sidecars also require storage. No bytes, resident VRAM,
full-game milliseconds, or no-new-pass claim is made for the integrated graph.
Compare the ON path with a same-layout/pass sham that uses gain 1, as well as the
existing no-pass OFF path. Report copy/staging/sidecar costs separately.

## Local compiler and parity gate

Intended profile: DXC 1.8, `cs_6_2`, entry `CSMain`, `-O3 -Gis
-force-rootsig-ver rootsig_1_0`. `-Gis` and `precise` constrain arithmetic
reassociation; they are not a completed CPU/GPU equivalence proof. No native16
arithmetic is requested. Compile explicitly into a fresh local test directory:

```sh
dxc -T cs_6_2 -E CSMain -O3 -Gis -force-rootsig-ver rootsig_1_0 research/astra20261020/candidates/05-glass-nzr/adapter/GlassNzrCorrection.hlsl -Fo GlassNzrCorrection.cso
```

Record the actual compiler version/hash, invocation, source/CSO hashes,
reflection/binding layout and disassembly. Generated CSO/header bytes are
pending local compilation and are deliberately excluded from this patch.

The arithmetic parity domain is a valid version-1 ABI with valid configuration.
The Python API raises for malformed shapes/configuration; the standalone shader
copies through on malformed constant values/version instead. Python's dataclass
has no packed native version field. Test these malformed-native-metadata cases
separately and require the host to reject them before scheduling; do not label
the API error behaviors equivalent.

Replay CPU-origin tensors at full precision into this one shader before a
native-quality run. Require exact OFF/unsupported/zero-variance passthrough at
the float32 stage, exact original alpha bits, and strict finite/range behavior.
For active arithmetic compare the error distribution, worst component and
near-threshold decisions; initial tolerance is four float32 ULPs or `2e-7`
times the block's maximum input RGB, whichever is larger. That tolerance is
provisional for the short scalar arithmetic and cannot hide a support/gain
branch disagreement. Then check the final native half store with exact alpha
words and at most one half ULP only where a float32 rounding difference is
independently explained. Any branch disagreement requires investigation.

The final mandatory gate remains actual native NZR plus AMD RR and matched
game A/B at the protected preset. CPU parity, block low-band conservation and
a recorded historical GPU witness cannot establish final composite brightness,
image-quality acceptance, game performance or the user's visual preference.

Source-only scope/applicability validation, before applying the proposal:

```sh
python research/astra20261020/candidates/05-glass-nzr/adapter/validate_adapter.py
```

This command confirms the additive patch's exact shader payload, unchanged
protected source bytes, and `git apply --check`. It is not shader compilation.
