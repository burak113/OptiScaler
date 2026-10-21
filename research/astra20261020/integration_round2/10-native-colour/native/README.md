# Native colour pass: reviewed research interface, default off

`NativeColourPass_Dx12.{h,cpp}` is a standalone D3D12 implementation. It is not
added to the production project and does not change any public setting. The
original colour estimator remains **rejected for image-quality adoption**.
The extra evidence gate is safety infrastructure, not a newly proven estimator.
The portable header is compiled and exercised on CPU; Windows adapter, HLSL and
native GPU/game acceptance have separate explicit gates.

## Exact input ABI

One `Inputs` describes exactly one diffuse or specular native lobe, in physical
linear RGB before title remodulation. Every texture has an identical immutable
`Identity`: frame, context generation, command-list recording ID, render extent,
crop origin, active extent, lobe, and provider scale. Diffuse accepts D16 and
specular S256. Resource allocation extents are read from individual resources;
they may differ, but each must contain the active top-left rectangle. Crop
coordinates describe where this rectangle originated in the full render.

| Binding | Format and meaning |
|---|---|
| source / t0 staging | RGBA16F words from an explicitly owned **pre-provider physical snapshot**; not an in-place scaled/restored approximation |
| rawRR / t1 staging | Canonical physical native RR after provider restoration, before selection |
| selected / t2 staging | Existing selected post-recovery/native result, immutable for this recording |
| depth / t3 | R32_FLOAT original signed linear depth; zero/nonfinite invalid |
| normalRoughness / t4 | R10G10B10A2_UNORM native octahedral normal RG and roughness B; A is never a class |
| authority / t5 | R32_UINT; exactly `1` authorizes the centre/donor, `0` and reserved values do not |
| support / t6 | R32_UINT; exactly `1` certifies the centre's **complete clipped radius-square footprint**, before candidate-dependent guide rejection |
| output / u0 staging | Private packed RGBA16F words, then copied to a private RGBA16F native texture |
| diagnostic / u1 | Private RGBA32F `(eligible, supported, confidence, effectiveSamples)` |

The support producer must establish a conservative footprint of compatible
causal material/illumination response and bind it to identity, estimator version,
radius and a nonzero producer version. A tag derived from noisy RR chroma, native
alpha, normal/roughness, current-cell material bits or raw/selected equality does
not satisfy this contract. Unknown global evidence declines preparation without
allocation. A texture's unknown/reserved code yields exact selected identity.
No production certificate producer is delivered by this pass. Synthetic
certificates are explicitly labelled `SyntheticFixture`; they do not establish
usable game support.

The physical source snapshot must be a distinct resource from both raw RR and
selected. Prepare occurs before provider/selection writes, so such an alias
would destroy the supposedly immutable original snapshot before Record. Raw RR
and selected may alias each other in the ordinary no-recovery route. The host
patch additionally excludes either lobe's provider-scaled converted inputs and
other mutable colour resources from the snapshot/observation resources.

Each active centre also requires original raw/selected **all-four-word equality**.
All four words are copied unchanged for protected pixels. Every output alpha word
is retained even when RGB changes, including signed zero and NaN payload bits.
Invalid sample/guide, zero correction, unknown evidence, missing support and
overflow all leave the already copied selected words unchanged. No temporal
history exists. Reset/resize declines the entire pass. Native scale conversion
is not performed here; the D16/S256 route is metadata that must separately pass
its physical-domain and storage round-trip tests. Half scaling may clip or lose
information; merely multiplying/dividing by a power of two is not blanket proof.

## Prepare, record, publication and lifetime

`Prepare` performs no GPU recording. It validates the actual stored float32
configuration, identity/provenance, list/device, texture formats/extents/states,
read aliases, copy footprints, uint32 addresses, descriptor spans and complete
buffer sizes. Only then does it reserve the entire resource budget and allocate.
Invalid `Config` never reaches a shader. OFF, missing research acknowledgment,
strength0, zero gain budget, reset/resize and unknown evidence need no native
objects and cause no allocation or work.

Place Prepare after existing selected pointers are known but before the public
RR owner and compute lease are retained, and before provider commands. Retain
`Prepared.owner` in that exact `DispatchLease`. Pass individual upstream producer,
slot or graph owners in each `Texture.owner`; retaining the enclosing
`DispatchLease` would create an ownership cycle and is forbidden by the ABI.
COM references alone do not prevent an upstream pool from recycling content.

The producer must independently retain any already-recorded snapshot, sidecar
or input-copy commands through GPU completion **even if this pass rejects or is
OFF**. Submitting a one-shot bridge request does not transfer the lifetime of
earlier commands to a pass that may never create a `Prepared.owner`; the request
itself is consumed. Acquire the producer's recording lease before recording its
copies, and keep that lease independently of optional colour admission.

After provider normalization guards restore physical raw RR and after recovery
and flat output finish, fetch the current recording ID and run `CanRecord` for
**both lobes**. If either fails, publish neither. Record performs no allocation,
native validation call, or fallible operation; an inconsistent/reused recording
returns false before any command. The caller serializes preparation/recording;
this class does not make concurrent command-list recording legal.

After both succeed, publish both selected pointers **and** update commit SRV
descriptors, in existing **specular then diffuse** order. The raw pointers remain
canonical raw RR. Any prepare failure leaves original selected pointers and
descriptors intact. Preserve existing bridge generation/commit/ticket checks.
`Prepared` and all input owners must remain held through the command list's actual
completion and any allowed re-execution. Recording once is enforced on CPU;
executing the closed list again has matching initial/final resource states.

## Commands, state and byte preservation

Per lobe the pass creates three packed input buffers, one packed output buffer,
one native output texture, one diagnostic texture, one upload buffer containing
full prefill bytes and a 256-byte constant allocation, plus two descriptor heaps.
The cbuffer is 112 bytes with documented offsets and zeroed remaining CBV bytes.
There are seven SRVs and two UAVs; the diagnostic clear additionally uses a CPU
descriptor in a nonshader-visible heap.

1. Initialize **every byte** of each source/raw/selected staging buffer from the
   retained `0xCD` upload prefill: prefix, every full row including final padding,
   and a 512-byte suffix. CopyTextureRegion alone would leave these bytes undefined.
2. Deduplicate original colour-resource transitions to COPY_SOURCE, copy each
   complete allocation into its independent footprint, and restore original
   states. Normal raw==selected aliasing is accepted; conflicting declared states
   for the same physical resource are rejected before recording.
3. Copy the **entire** selected staging buffer into output staging. Its selected
   and output footprint layout and capacity are identical. All buffers' sizes
   exceed the short D3D12 final-row footprint result where padding requires it.
4. Transition packed SRVs to NON_PIXEL_SHADER_RESOURCE and output to UAV.
   Deduplicate guide transitions to NON_PIXEL_SHADER_RESOURCE. Clear the complete
   diagnostic texture, add a UAV barrier, bind private descriptors/CBV and dispatch.
5. Barrier both written UAVs; restore guide states. Transition output buffer to
   COPY_SOURCE and native output UAV to COPY_DEST; copy its complete allocation.
6. Return native output and diagnostic to UAV, and all packed buffers to COPY_DEST.
   Original inputs return to their exact declared state. Padding/guards remain
   `0xCD`; inactive selected pixels and opaque alpha retain their original bits.

Supported declared input states are NPS, UAV (requiring ALLOW_UAV) and COPY_SOURCE.
The helper consumes compute bindings; as in existing bridge helpers, the next
provider/commit reader must bind its own root signature, descriptors and PSO.
No title resource is written and outputs never alias any supplied input.

## Budget arithmetic and disclosure

`Memory` reports actual `GetResourceAllocationInfo` sizes for all seven committed
resources, separately for default and upload heaps, plus an explicitly named
128 KiB **policy reservation** for two descriptor heaps. This reservation is not
a measured driver allocation size. Driver pipeline/root-signature/descriptor
metadata cannot be enumerated through that resource-allocation API and remains
unmeasured; the result is a resource budget, not total process VRAM.

The `Budget` owner and atomics must belong to a service-wide retained family. It
can map directly to `LobeRecovery::Family.graphBytes`, `.retainedPeakBytes` and
`.slots.allocatedSlots` with the existing 2 GiB/32-slot limits. One lobe consumes
one retained slot. Admission occurs before any native allocation; partial failure
releases every resource before retiring its byte/slot charge. Old generations,
both lobes, and in-flight uploads remain charged until their retained owners die.
There is no cache, hidden per-context budget bypass or automatic retry loop.

For equal allocation extents the unaligned resource logical payload is roughly
64 bytes per pixel per lobe: 32 bytes packed staging + 8 native output + 16
diagnostic + 8 upload prefill. D+S is therefore about 128 bytes per pixel before
padding/alignment, descriptors and multiple retained frames. This exceeds the
old unimplemented 80/112-byte estimate because complete upload prefill is now
owned and charged. No performance/residency improvement is claimed.

## Commands and acceptance

Portable validation and four deliberately broken-header controls:

```text
python research/astra20261020/integration_round2/10-native-colour/native/run_contract_tests.py --output <scratch-cpu-dir>
```

The runner uses `g++` on Linux and `cl` on Windows (from a Visual Studio developer
shell); `--cxx` selects another available compiler. Its current recorded run used
Linux `g++`. The Windows command branch is supplied for local execution.

Windows source compilation (Developer PowerShell, from this directory):

```text
dxc.exe -T cs_6_2 -E CSMain -HV 2021 -Ges -Gis -O3 NativeColourPacked.hlsl -Fo <scratch-dir>/NativeColourPacked.cso
cl.exe /nologo /std:c++17 /EHsc /W4 /c NativeColourPass_Dx12.cpp /Fo:<scratch-dir>/NativeColourPass_Dx12.obj
```

No `-enable-16bit-types`: arithmetic is FP32, explicit final half packing is RTZ.
The portable `g++` test does not compile Windows code. Run the root-level native
fixture/direct-host commands under the D3D12 debug layer, independently compare
complete word buffers and diagnostics, and retain actual compiler/shader/adapter
hashes. Accepting these mechanical results still requires external support
provenance, same-crop real capture replay, unsaturated/saturated D16/S256 contract
checks, retained-list lifecycle/memory pressure, and fresh in-game quality/time
measurements. None of these gates permits default enabling the rejected estimator.
