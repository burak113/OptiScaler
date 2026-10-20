# Exact diagnostic adapter proposal — job 07

**Status: unintegrated, default-off research diagnostic.** This directory supplies an HLSL proposal and an exact host/interface specification. It changes no production file, AMD descriptor, native input, configuration preset, or game DLL. Job08 owns any future integration. The shader has **not** been compiled or executed here; `BUILD.json` records the pending local command. A portable C++ layout check is separate from HLSL, Windows and AMD execution.

## Scope and identity behavior

The pass observes original normal/depth/motion and writes only two new resources:

| Output | Exact format | Meaning |
|---|---|---|
| `Observation`, u0 | `DXGI_FORMAT_R32G32B32A32_FLOAT` | R angular dispersion; G relative depth span; B temporal angular innovation; A experimental cosine multiplier |
| `SupportFlags`, u1 | `DXGI_FORMAT_R16_UINT` | Eight independent observed-field support bits; upper eight bits zero |

No signal D/S, material guide, roughness, packed normal, depth, MV, input/output alpha or hit distance is an output. The fourth observation channel is a diagnostic number and a CPU-proxy experiment parameter, **not an AMD RR confidence input**. There is no proposal to route it into native categorical A, roughness B, motion B/W, existing depth validity or G3.

The runtime configuration field should be named `guideObservationEnabled`, initialized to false in a future private diagnostic configuration; do not add it to the recommended preset. When false, allocate no observation/history resources and record no job07 pass. Diagnostic unavailability leaves the existing render graph unchanged. In the isolated kernel OFF test, `Enabled=0` writes `(0,0,0,1)` and flags zero, with no SRV reads.

When a previous observation is unsupported, the pass retains any available current spatial moments but writes temporal innovation zero and multiplier one. A zero innovation without `TEMPORAL_SUPPORTED` is unknown evidence, not agreement. `TEMPORAL_SUPPORTED` means **numerical comparability of observed guides**, not valid physical-layer history. The source can have finite/clamped depth and matching normals while its raw depth class, hidden coverage or moving secondary layer makes physical history wrong. Those missing facts are not reconstructed here.

## Fixed shader ABI

`INTERFACE.json` is the machine-readable contract. `HOST_INTERFACE.h` contains the matching C++ constants and offset static assertions.

The root signature is exactly:

```text
RootFlags(0)
RootConstants(num32BitConstants=16,b0)
DescriptorTable(SRV(t0,numDescriptors=5))
DescriptorTable(UAV(u0,numDescriptors=2))
```

It costs 18 root DWORDs. Root parameter 0 holds 64 bytes/16 DWORDs; parameter 1 points to five contiguous SRVs; parameter 2 points to two contiguous UAVs. There are no CBVs, samplers, descriptor-table holes or unrelated descriptors in either range. Each table must be fully initialized even when chronology is disabled. Previous null SRV descriptors must still use the stated typed 2D formats; alternatively bind initialized private dummy textures. `Chronological=0` ensures previous resources are not read.

| DWORD / byte | Field | Type |
|---|---|---|
| 0–1 / 0 | CurrentExtent | uint32 width,height |
| 2–3 / 8 | PreviousExtent | uint32 width,height |
| 4–5 / 16 | RenderExtent | uint32 original full-render width,height |
| 6–7 / 24 | CurrentCropOrigin | float32 x,y in original render pixels |
| 8–9 / 32 | PreviousCropOrigin | float32 x,y in original render pixels |
| 10 / 40 | Enabled | uint32 0 or 1 |
| 11 / 44 | Chronological | uint32 host-admitted pair, 0 or 1 |
| 12 / 48 | CurrentPositiveLinearDepth | uint32 explicit convention proof |
| 13 / 52 | PreviousPositiveLinearDepth | uint32 explicit convention proof |
| 14 / 56 | DepthRelativeTolerance | float32, default .02, finite and nonnegative |
| 15 / 60 | Reserved | uint32 zero |

All five input SRVs have one mip and one array slice, SampleDesc.Count=1, matching current/previous extents and device. t0/t3 are `Texture2D<float4>` with **R10G10B10A2_UNORM** views. Do not create R32_UINT views of the existing typed resource. t1/t4 are R32_FLOAT depth. t2 is RGBA16_FLOAT motion, expanded to float32 by the typed read. Store flags to an actual R16_UINT texture; the HLSL element type is uint. Check the device's typed UAV store support for both output formats before preparing work. No compiled asset is supplied as proof of support.

Dispatch `ceil(CurrentExtent.x/8), ceil(CurrentExtent.y/8), 1` with 8×8×1 threads. Shader bounds checks protect the edge of odd-sized extents. Render/crop dimensions, finite origins, tolerance, format, device and all constants must be checked before any command-list mutation. Production crop origins are integer render coordinates represented exactly in float32. A one-pixel previous crop cannot supply four taps and is temporally unsupported; do not pad or wrap it to manufacture support.

## Arithmetic correspondence to the CPU reference

The reference is `src/foliage_guides.py:observe_guides`. For admitted inputs, the shader performs the same mathematical operation:

1. Recover the ten-bit oct coordinates with `round(UNORM.xy*1023)`, divide explicitly by 1023, unfold and normalize. Category is `round(UNORM.a*3)` and is used only for equality. Normal Z-fold signs match `FSRDPreprocessCommon.hlsli`. Roughness is not read or changed.
2. Accumulate the finite-positive-depth normals and depth min/max in a clipped 3×3 window. CPU slice orientation means loop delta `(dx,dy)` reads `p-(dx,dy)`; the shader keeps this accumulation order. At least three valid neighbors and a valid current point are required for spatial moments. No sky/category filter is applied to this spatial statistic.
3. Spatial R is `clamp(1-length(meanNormal),0,1)`. G is `(maxDepth-minDepth)/max(currentDepth,1e-20)`, nonnegative, with positive overflow saturated to FLT_MAX and nonfinite invalid results mapped to zero. This range handling does not upgrade physical support.
4. Compute previous local position in explicit order: `((float2(p)+currentOrigin)-previousOrigin)+motion.xy*float2(renderExtent)`. Motion RG remains previous-minus-current full-render UV. There is no crop scaling or extra jitter term. Check finite coordinates and `0<=q<previousExtent-1` **before integer conversion**.
5. Read four integer point taps in order `(0,0),(1,0),(0,1),(1,1)`. Compute continuous bilinear weights explicitly. All four prior depths and category codes participate in support, even at zero interpolation weight. There is no hardware sampler and no D3D fractional-sampler quantization assumption.
6. Predicted previous signed-linear value is `currentDepth+motion.z`; this version supports temporal comparison only when both conventions are explicitly positive-linear and the prediction is finite and positive. It never applies `abs(depth)` to admit a negative convention. Every prior tap must be finite, positive, category-equal and within `.02*max(abs(predicted),abs(prior),1e-6)` by default.
7. Sum weighted `clamp(1-dot(currentNormal,priorNormal),0,2)`. Only numerically supported pixels receive this value and `clamp(1-innovation,0,1)`; otherwise B=0 and A=1.

The NumPy reference computes coordinate differences/weights with its documented dtype behavior, including intermediate float64 weight construction before float32 angular accumulation. The shader uses ordered float32 arithmetic throughout; it is **not claimed bit-exact** before local parity. Recovering packed integers avoids relying on UNORM conversion precision, and `precise` plus `-Gis` prevents implicit contraction/reassociation in the written expressions. Local tests must include bin-boundary coordinates and near-threshold depth comparisons. First compare all flags and exact OFF outputs, then bound floating moment differences. Differences confined to a numerical threshold require an explicit reproduced counterexample and aligned implementation contract, not a silently loosened acceptance mask.

## Host hook, ownership and chronology

A future host adapter can be an independent `GuideObservation` helper owned by each RR physical history domain. The hook is in `RRWrapper::RecordOwnedImpl`, after current original bridge geometry/motion are fully prepared and format/device validation succeeds, and before the provider records work. Its source is the immutable `sourceInput` lineage: original normal before Flat Albedo, original bridge depth and pre-G3 motion. Do not substitute `flatAlbedo.normals`, `lightingGuard->Motion()` or candidate-corrected D/S. The observer does not bind D/S at all, and preserves Anchor/RR/NZR private input versus G3 original-input routing.

For replay of existing clips, `input_motion` is the captured provider-motion role. It may be passed to the same arithmetic as a **provider-capture observation**, but metadata must identify that authority. It is not a hidden copy of pre-G3 motion. Declare authority per role: normal may be owned/captured pre-Flat or captured provider-prepared, while motion may be owned pre-G3 or captured provider-selected. The glass array named `original_normal_roughness_u32` is the unwarped provider-prepared role, not pre-Flat normal. Both frames in a compared pair must have identical per-role authority. Never join live original-bridge history to provider-capture history.

Use this lifecycle, including on partial recording failures:

1. **Prepare only.** Validate options and metadata, allocate a unique frame work lease, two output UAV textures, descriptor heap and needed original-source snapshots. No existing render input changes before all optional allocations succeed. On failure return unavailable and keep the pre-existing render graph.
2. **Snapshot exact original inputs.** The conservative first implementation copies original normal, depth and motion to private resources of the same formats and selected ROI, using word-preserving `CopyTextureRegion`/full texture copy. For live ROI mode all three snapshots must use the same crop; Texture2D views do not supply arbitrary crop offsets. Transition known original states to COPY_SOURCE, copy, then restore the exact original states. Private snapshots transition from COPY_DEST to NON_PIXEL_SHADER_RESOURCE before dispatch. Preserve source generation/birth/recording identity and ownership through the actual submission fence. Retaining a COM pointer alone does not make a mutable source image an immutable history.
3. **Admit previous history.** Previous snapshot must belong to the same device, domain/context generation, source-authority/encoding/settings revision, full-render extent, and depth convention. SDK and Streamline indices must be consecutive under the established native frame-wrap/sentinel rule; a reset, gap, abandoned list, resource recreation or missing predecessor clears history. The CPU reference's `frame_id+1` rule is only its portable chronology check; the production admission is deliberately stricter. Crop origins may change if every origin is recorded; a new crop is not a motion vector.
4. **Record observation.** Bind current private snapshots and retained previous normal/depth snapshots. Transition only the two output resources to UAV, bind the exact root signature/tables, set all 16 constants, dispatch, and transition outputs to NON_PIXEL_SHADER_RESOURCE or the caller's explicitly known readback state. The transition publishes UAV writes before another pass reads them. Record timestamps only around this work, separately from copy/upload/readback and RR.
5. **Commit history conditionally.** Current normal/depth snapshots may become the next immutable predecessor only for the same accepted native recording/chronology. Same-queue command ordering plus the recorded work lease must prove the writes precede subsequent reads. Abandoned/discarded lists and failed submissions must invalidate this proposed history and must never expose unexecuted snapshots. Do not recycle or overwrite a snapshot while any GPU work or trace readback still retains it. Current motion can retire after its work fence; previous motion is not needed by the shader.
6. **Retire by fence.** Every frame work lease retains current/previous snapshots, output textures, descriptor heap and constants/metadata until its exact recording fence retires. Recreate/reset creates a new generation without destroying resources used by older in-flight work. Bound outstanding work and return optional-unavailable on capacity exhaustion. D3D debug/lifetime checks must exercise abandoned lists, overlapping recordings, reset, dimensions/format changes, and old-context destruction.

The first conservative design's raw image storage is 16 bytes/current pixel for original N/Z/MV snapshots, 18 bytes/current pixel for observation+flags, and 8 bytes/previous pixel for predecessor N/Z. Extra in-flight work adds its retained snapshots and outputs. This is an allocation formula, **not a measured resident-VRAM result**; actual allocation sizes need `GetResourceAllocationInfo`, staging/descriptor accounting and the existing shared family budget. The OFF path allocates none. Copies, resident/peak VRAM and execution time must be measured locally before proposing runtime use. Optimizing away a snapshot requires an explicit immutable-input lifetime proof.

## Job04 transport and job08 integration interface

Use `fsrd.job07.guide_observation.v1` metadata beside the two textures. Preserve source revision/settings hashes, source authority, domain/context generation, native recording and SDK/Streamline/capture indices, extent/origin, depth convention, actual reset, resource generation/birth and shader identity. Frame durations must remain unknown unless actually recorded. The current clips support per-frame, not per-second, temporal measurements.

Job04 may transport an observation for diagnostic inspection using its own separately reported transport-validity mask. The job07 flags continue to describe the **original** observation frame; they are not automatically true at a new location or in a new frame. Do not bilinearly interpolate categorical bitfields. Any transported floating map must carry the original flags plus the new transport mask and source provenance. Its absence or invalidity never becomes a negative history decision.

Job08 may add the default-off diagnostic helper and separate trace roles only after compilation/reflection/CPU parity and native lifetime checks. Add roles without renumbering the existing BridgeNames array; preserve each texture's real extent. Bind no job07 resource to AMD RR or recovery in this proposal. Keep all existing D16/S256, G2/G3, RR Fallback, Diffuse RR, Reflection History and NZR Temporal states unchanged. An eventual use of the cosine number as a history intervention is a **new candidate** with a new versioned contract and its own detail/grain/response gate.

## Required local checks

Compile with the exact command in `BUILD.json`, retain compiler version and source/CSO hashes, and inspect actual reflection for the 64-byte constants, five SRVs, two UAVs, no sampler and 8×8×1 group. Run DXIL validation and native descriptor/format checks. No stale generated shader header belongs in this delivery.

Run the standalone shader on the same frozen CPU fixtures with exact upload words. Include OFF, absent previous, first frame, frame gap/reset, extent/origin change, last row/column, 1×1 previous crop, zero-weight incompatible tap, category0 versus other two-bit values, negative/unproven depth convention, nonfinite or huge MV, predicted-depth overflow, span overflow and oct-fold normals. Require exact flags for well-separated comparisons, exact OFF/identity outputs, all input bytes unchanged, and explicitly bounded floating differences. A near-threshold mismatch blocks a parity claim until reconciled.

Then execute a native default-off/diagnostic-on comparison with original inputs fixed. Provider input/output byte identity is required for this observer-only hook; any difference indicates an integration bug, not a quality improvement. Record actual GPU passes, D3D debug/lifetime outcomes, private memory/copy costs and matched native trace/video. The historical facade/text controls remain mandatory before any later filtering candidate is considered. CPU results, mathematical support bits and a successful C++ struct compile do not replace these local observations.
