# Coordinate, support, and publication ledger

Task 04; immutable handoff `astra-handoff-20261020` resolves to
`5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`. The audited production source is
`87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`. This document was assembled from
the actual source before constructing the reconstruction candidate. It describes
the frozen implementation; proposed contracts are explicitly marked. No source
file outside this task directory is changed.

## 1. Names that must remain distinct

| Name | Meaning and units | Forbidden substitution |
|---|---|---|
| `render_extent_xy` | Active render width/height in pixels, including the original full render for cropped capture MVs | Texture allocation extent or crop extent |
| `allocation_extent_xy` | Actual texture dimensions used to normalize an SRV sample | Active extent unless equal by contract |
| `crop_origin_xy` | Global original-render pixel coordinate of local array origin | Camera translation or object motion |
| `pixel_index_xy` | Integer texel-centre indexing: texel `(i,j)` has coordinate `(i,j)` | Pixel-edge coordinate without adding `0.5` |
| `pixel_edge_xy` | Image-edge units: texel centre is `(i+0.5,j+0.5)` | Integer texel index without subtracting `0.5` |
| `texture_uv` | `pixel_edge_xy / allocation_extent_xy` for hardware texture sampling | `pixel_edge_xy / active_extent_xy` when allocations differ |
| `render_uv` | `render_pixel_edge_xy / render_extent_xy` | UV into a crop-as-screen texture |
| `view_z_signed` | Signed linear view-space Z, negative in a right-handed forward-visible convention | Device-Z, Euclidean ray distance, or positive key depth |
| `key_depth_abs` | `abs(view_z_signed)` captured by native Anchor Gain | Combined Anchor's signed stored depth |
| `hit_distance` | Original input alpha; usable virtual reflected-ray distance only in paths that establish that interpretation | Surface depth or a general object-correspondence certificate |
| `normal_world` | Decoded, normalized world-space geometric guide from original packed normal/roughness | Colour-corrected radiance, a semantic material class, or a reconstructed normal |
| `history_known` | Actual observation, frame identity, submission ordering, and source support established | Edge-clamped substitute or CPU-scheduled write |

The CPU transport API uses pixel-edge coordinates and column-vector mathematics.
Capture-loader integer-centre coordinates are converted exactly once at the API
boundary. In the capture correspondence formula the `+0.5` terms cancel.

## 2. Matrix mathematics versus memory layout

The bridge's mathematical matrices are column-vector transforms:
`view_point = V_col @ world_point`, `clip = P_col @ view_point`.
`FSRDCameraMatrices.h:62–71` explicitly converts Streamline's stored row-vector
matrices by transposition; `:140–160` constructs the inverse view with world basis
vectors in columns. `LobeRecoveryFrame` states `m[row][column]` for column vectors
at `FSRDNrdLobeRecovery_Dx12.h:47–49`.

The Anchor shared `Desc` representation stores the **transpose** of that
mathematical matrix. Native host `Prepare` transposes the bridge matrices
(`FSRDNrdPostMotionAnchor_Dx12.h:262–265`); `LoadDesc` transposes them back
(`FSRDPostMotionAnchorConstants.h:128–131`). This is not an extra change of
handedness or a camera transform. Constants uploaded as four `float4` rows are
consumed by `dot(row, v)`, which implements column-vector multiplication.

The exact transforms derived by `BuildFrame` are:

```
current_view_to_previous_view_col = V_previous_col @ inverse(V_current_col)
current_view_to_key_clip_col = P_key_col @ V_key_col @ inverse(V_current_col)
```

The static-cell test uses **current** projection rows after the previous-view
transform. It does not receive previous projection rows. Key recall does use
the key's own projection. Those are different contracts. Matrix storage must be
named independently, e.g. `desc_transposed_storage` versus `view_col`; a bare
boolean named `transpose` is inadequate provenance.

The perspective reconstruction assumes `clip.w = P[3,2] * view.z` and the
ordinary off-axis X/Y terms (`P00`, `P11`, `P02`, `P12`). It is not an arbitrary
orthographic/invertible-projection unprojector. `FSRDCameraMatrices.h:74–82`
defines the sign of `P[3,2]` as the handedness signal, independently of reversed
device depth. A general CPU unprojector must not silently claim broader native
shader parity.

## 3. Native and combined Anchor graph

`W,H` below are active full-resolution extents. Frozen coarse extents are
`Gx=max(1,floor(W/8))`, `Gy=max(1,floor(H/8))`.

| Edge | Coordinate mapping and stored representation | Validity/interpolation | Source |
|---|---|---|---|
| Full D/S/depth/MV → Stats cell | Four taps at edge coordinates `8*c+(2,2),(6,2),(2,6),(6,6)`; divide separately by each source allocation. These are means of 16 selected texels, not all 64 pixels. Mean tap centre is `8*c+4`. | Hardware bilinear + clamp; same sparse positions for level, depth, and XY motion. No normal or hit-distance support test. | Native Stats `35–58`; combined Stats `49–72` |
| D/S → cell level | `dot(D.rgb+S.rgb, (0.2126,0.7152,0.0722))`; input alpha unused by measurement. Native remains physical linear units. | Stored Stats RGBA16F contains `(level, signed_mean_depth, static, 0)`. Mean depth can be a nonexistent surface at a boundary. | Native Stats `50–57,101–107`; native host `129–133` |
| Cell mean depth → current view point | `z=abs(depth)*sign(P32)`. Caller supplies `centre=8*c+4`, while `ViewPosition` computes NDC from `centre+0.5`. | Require finite, nonzero depth in static test; perspective form. | Native Stats `60–64,72–84,104–106` |
| Current view → previous screen for static test | `P_current @ V_previous @ inverse(V_current)`. Project returns edge coordinates; subtracts caller's `centre`. Compare with `mean_MV.xy*(W,H)`. | Accept squared residual `<=16` pixels². Current projection stands in for previous projection. MV alpha is ignored. | Native Stats `72–84`; shared constants `220–227` |
| Current view → key clip | Per-physical-slot `P_key @ V_key @ inverse(V_current)`; priority order is separate `KeySlice`. | Six physical slots, eight ABI entries; skip slots at sentinel 6, invalid slot flag, nonfinite clip or `clip.w<=1e-6`. | Shared constants `193–253`; native Stats `120–129` |
| Key clip → key texture UV | `q=((ndc.x+1)*W/2,(1-ndc.y)*H/2)`, `uv=q/(W,H)` into coarse grid. | Reject UV `<0` or `>1`, then hardware bilinear **clamp** at edges. No per-tap support certificate. | Native Stats `130–137` |
| Key depth → recall match | `expected=abs(clip.w/keyP32)`; relative tolerance `0.02*max(expected,1e-3)`. | Accept average sampled depth agreement. A bilinearly mixed depth is not an occlusion proof. | Native Stats `133–136`; constants `kDepthTolerance` |
| Stats → native ring write | Pre-gain cell level and `abs(cell.depth)`; every reused slot cell overwritten. | Static cells retained, other cells write 0 level and 0 depth. Ring depth R32F is fed from already stored Stats FP16. | Native Gain `36–42`; native host `129–132` |
| Stats → combined ring write | Pre-gain cell level and **signed** `cell.depth`. | Same overwrite policy. Recall still compares with absolute expected depth. A negative signed-depth source is therefore incompatible without a path-specific fix. | Combined Gain `44–51`; combined Stats `156–159` |
| Recalled/Stats → coarse gain | Nine integer cell taps `p+(dx,dy)*step`, default `step=3`; support spans ±24 full pixels before cell footprints. `weight=recalled.valid*recalled.static`. | Address-clamped integer taps; no same-depth/normal test among donors. Native fallback gain1. Native extra guard requires centre static and neighbourhood coverage, not centre recall. | Native Gain `44–57,75–81`; constants `kTapStepCells` |
| Gain → full-resolution pixels | `(p+0.5)/(W,H)` sampled into `Gx,Gy` gain texture. Same scalar gain multiplies D/S RGB. | Hardware bilinear clamp. No full-resolution motion, depth, normal, mask, or gain-support check. Alpha copied unchanged. | Shared Apply `21–33` |
| Native corrected pair → RR/NZR | Apply edits owned exact-extent private D/S copies; original inputs retained for independent routes. | CopyResource only on exact-extent single-slice RGBA16F. Optional path fallback retains original pair. | Native host `240–247,280–286,316–329`; RR wrapper `1296–1317,1397` |

### Source-derived phase deductions, to be tested separately

1. With identical camera matrices, constant depth, and zero MV, the frozen static
   prediction is `(+0.5,+0.5)` pixels because `ViewPosition` adds the half pixel
   to an already centred cell position and `ProjectToPixels` does not subtract
   it. Its norm is about `0.7071` pixels, below the 4-pixel static gate. The same
   half-pixel translation changes the key sampling location. This is an exact
   arithmetic deduction, not a measured game defect.
2. For odd extents, coarse cell physical centres remain `8*c+4`, whereas
   normalized texture centres correspond to `(c+0.5)*W/Gx`. These are unequal
   unless `W=8*Gx`; similarly in Y. The final partial strip has no independently
   measured cell. An adapter must either publish an explicit cell layout or
   reconstruct in fixed-cell coordinates with a documented tail fallback.
3. The source comment saying a projection change can make the static gate only
   stricter is not a theorem. A wrong camera prediction can also cancel a moving
   object's residual. Keep actual previous projection and jitter policy in the
   transport contract, or declare the comparison unsupported across a change.

## 4. Native motion conversion and jitter

`FSRDNrdMotionCommon.hlsli:17–61` produces canonical XY as
`safe_raw_motion*MotionScale + JitterDeltaUv`. The depth-delta camera fallback
unprojects the current sample at `(p+0.5)/render_extent - CurrentJitterUv`,
predicts the current surface's previous-camera signed Z, and computes
`previous_z-current_z`. It does **not** use the previously visible occluder's
depth except in an explicitly labelled legacy rollback. The native temporal
path can replace B only when its exact surface/depth/rectangle provenance checks
pass (`:73–133`).

The canonical motion texture W is always `1.0` (`:6–16,61`). It is not confidence
and cannot distinguish native, camera-only, or unknown B. Unknown B is exactly
zero; zero is also a legitimate true delta. A consumer cannot infer depth-motion
provenance from that numeric value alone.

Native FlatAccumulate consumes canonical XY **as is**: its host explicitly says
the raster jitter delta is already included (`FlatAlbedoRecovery:413–416`). The
Anchor static test has no explicit jitter field and the shared constants do not
record a per-key jitter. Native reflection History also has no explicit jitter
fields. Whether supplied projection matrices already contain those terms must
be witnessed for the actual route; do not add or remove jitter twice to force an
agreement. An exact analytic harness should encode the jitter convention in its
camera/MV types and test both missing and double application as mutants.

## 5. FlatAlbedoRecovery: distinct transport and reconstruction routes

| Edge | Coordinates and support | Limit/implication | Source |
|---|---|---|---|
| Original normals/depth → recovery mask | Full active integer loads. Original normal/roughness guides select eligible lobe pixels; mask RGB contains normal. | Mask eligibility is not a complete temporal correspondence proof. Preserve original guide authority. | Flat host `410–412`; FlatAccumulate `13,49–58` |
| Canonical MV → temporal mean | `previous_index=p+MV.xy*(W,H)`, signed expected depth `z+MV.z`. | History requires previous frame, finite canonical motion, W>=0.5, bounded displacement. W check does not provide semantic validity. | FlatAccumulate `71–83` |
| Temporal sample taps → mean/moments | Four integer bilinear taps with each stored signed previous depth within 3% of expected; require weight>=0.999. | Out-of-domain taps are rejected, never clamped for acceptance. If all nonzero cubic taps pass, Catmull-Rom is clamped to bilinear footprint range. | FlatAccumulate `48–59,84–111` |
| Mean → cap/restart | RR luma change reduces retained count; motion speed and camera-parallax bound cap accumulation. | This is a statistical response policy, not more accurate correspondence. Do not count blur from resetting history as transport success. | FlatAccumulate `112–135` |
| Surface point + alpha hit → virtual point | `view_virtual=view_surface*(1+hit/length(view_surface))`, followed by actual previous `P*V*inv(Vcur)`. | Valid for a usable reflected-ray distance and static planar virtual feature model. Hit distance is not surface Z. Surface motion and virtual motion differ under translation. | FlatHistory `91–103`; host `429–437` |
| Hit field → virtual history support | Current hit is lower median of valid positive hits in a 3x3 recovery neighbourhood; previous tap accepts positive hit within `0.1*hit+0.5` default. | No previous surface depth/normal/world-plane test in this pass. Median can cross a mixed-coverage boundary; matching hit alone is not visibility. | FlatHistory `27–60,68–73`; host `338` |
| Virtual taps → mean/moment | Bilinear valid-tap weight>0.5; optional 16-tap Catmull-Rom only if all taps valid, clamped to bilinear colour range. | Cubic out-of-range load indices are clamped, but `all16` must pass the unclamped validity test before cubic result is used. Missing hit restarts at raw count1. | FlatHistory `104–139` |
| Base/RR → SelectPrep | Full-resolution 3x3 hole-fill colour median and RR maximum; recovery mask+finite depth eligibility. | No pairwise depth/normal support in the neighbourhood. Colour-based collapse decisions do not establish geometric correspondence. | FlatSelectPrep `23–72` |
| SelectPrep → SelectBlur | Two full-resolution separable sigma4/radius12 passes, mask-normalized level ratio; mirror boundary addressing. | Recovery mask only; geometry boundaries can be crossed within recovery pixels. Mirror is image extension, not observed ROI history. | FlatSelectBlur `17–52` |
| Select decision → final pixel | Grow fallback weight up to two pixels into the darker mask; combine Base and RR, preserve alpha. | This is spatial policy, not motion reprojection. Geometry-aware transport changes must be assessed separately. | FlatSelectApply `6–49` |

Original depth governs surface location/occlusion; original decoded normals
govern orientation compatibility; hit distance governs virtual location only
when its source path establishes reflection-distance semantics; radiance is the
quantity transported or corrected. None substitutes for another. Invalid normal,
nonfinite/zero depth, sky classification, mixed coverage, missing hit, or unknown
depth-motion provenance requires explicit identity or invalid-history handling.
In particular the Anchor has no normal/sky guide and only checks nonzero finite
mean depth: it must not be described as a general surface-certified estimator.

## 6. Capture/partial-domain ledger

| Fixture | Available support/history | Allowed conclusion |
|---|---|---|
| `portable/anchor` | Stored Stats, recalled fields, gain, fixed masks; combined133 and native-policy7 calibration frames. No raw six-slice ring. | Reproduce stored gain policy/coverage behaviour. Cannot rerun capture-derived key selection or prove native routing. |
| `portable/colour` | 512×512 crop at original-render origin496,167 in1505×847; CPU warmup0–62 and one actual GPU frame63. Original UV scales by original render. | Controlled arithmetic and sampler calibration. Cannot rename it a full temporal GPU replay. |
| `bottle_track7` | Frames180–186, moving128×256 crop. Global X688; Y160,176,208,272,384,480,560. | Consecutive observed-domain checks; first frame has no previous fixture image. Crop origin change must be removed before interpreting motion. |
| `foliage23` | Frames43–65,192×64 crop, global origin752,423. Multiple depth/coverage layers. | Fixed-support geometric alignment diagnostics, not semantic foliage classification or converged truth. |
| `facade16` | Frames34–49,96×96 crop, global origin688,359. | Detail control within this small tile; not the original entire-ROI calibrated mask. |
| `glass_crop` | Frames46–63,192×160 initial crop, original unwarped fields plus aligned outputs/masks. Alignment uses reference-depth camera-only warp. | Source arrays can test observed geometry; aligned fields do not prove disocclusion or dynamic compensation. |

All NPZ reads use `allow_pickle=False`. Clips preserve original FP16 RGBA lobe
inputs/outputs, R32F signed depth, packed uint32 normal/roughness, 46 uint32
provider words and camera float-bit words. Original input alpha is retained.
No albedo or converged ground truth is bundled. The motion formula is:

```
previous_local_index = current_local_index + current_crop_origin
                       + canonical_motion_uv * original_render_extent
                       - previous_crop_origin
```

The fixture bilinear support contract is finite `0<=qx<crop_width-1` and
`0<=qy<crop_height-1`. Reject unknown support. Never clamp/wrap it, never loop the
first frame against the last, and never treat saved RR's pre-fixture history as
a CPU history one has reconstructed.

## 7. Proposed support interface for jobs02/03/06/07

The implementation API is documented alongside the runnable source. The
following semantic obligations apply regardless of final Python dataclass names:

1. A domain carries active extent, allocation extent, global crop origin,
   observed-mask identity, frame ID and generation. A sample returns value and
   known/valid support separately. Unsupported finite coordinate is still
   unknown; it does not become valid because a nearest pixel exists.
2. A camera carries `V_col`, `P_col`, current/previous extents, depth convention,
   jitter offset and the declared fact of whether it is already in projection
   or canonical MV. Storage transposition is an explicit adapter only.
3. A correspondence returns projected position, expected signed/absolute depth
   by explicit mode, source-domain validity and per-tap support, with no colour
   dependence. For synthetic truth the object identity can be supplied as an
   oracle; it must never be passed off as a real available material ID.
4. A coarse gain certificate describes the **entire measurement support** used
   by that gain, including any estimator donor cells. Frozen Anchor's nine
   sparse donors at24-pixel spacing mean certifying only its centre 8×8 cell
   is insufficient. A scalar gain already mixed across surfaces cannot be
   unmixed by a later bilateral filter.
5. Exact-support analytic experiments and a real implementable geometric
   certificate are different ablations. A proposed certificate may use all
   original per-pixel depth/normal/motion observations to test a local plane,
   normal coherence and static eligibility. It must invalidate missing or
   conflicting samples. Average depth and average normal alone do not certify
   an unseen1-pixel strip. Pure geometry still cannot certify distinct coplanar
   materials, hidden motion below tolerance, or view-dependent lighting.
6. Reconstruction checks full-resolution recipient eligibility **and** donor
   certificate compatibility. Unsupported, moving, unknown or mixed recipient
   falls back to identity. No extrapolated correction is allowed into unknown
   crop support. Retained donor weights and correction dose must be exported
   so suppression cannot masquerade as a quality improvement.
7. Same-surface depth can vary on a sloped plane. A plane prediction/residual is
   more informative than the range of depth alone; compare with the exact
   normal and analytical intersection model. Strict fallback is legitimate but
   its lost correction coverage must be reported.
8. Numeric tolerances, float16 stores, nonfinite behaviour and boundary operators
   are explicit. Ideal NumPy bilinear is not a D3D sampler; GPU parity requires
   recording actual sampled guide values and fractional-coordinate witnesses.

### Precision and alpha limits

Geometric certification cannot distinguish genuinely coplanar but different
objects/materials without another authoritative guide. Parallel surfaces closer
than the configured plane-residual tolerance may also be indistinguishable. With
a relative tolerance of `1e-4`, offsets below `1e-4*depthscale` are an explicit
ambiguity class, not proof of correspondence. Synthetic object IDs may expose
this limitation but are not available from the captures' zero material IDs.

The frozen Apply's `float4(..., original.a)` preserves alpha mathematically; a
typed FP16 load/store is not a guarantee for every arbitrary16-bit NaN payload.
GPU acceptance requires raw16-bit equality for legal finite nonnegative native
hit-distance alpha. Signed-zero, subnormal and NaN words are separate adversarial
diagnostics. Candidate OFF/unsupported no-write paths require exact entire RGBA
bytes independently of numerical value.

## 8. Mathematical history publication contract (job08 implementation gate)

The native host prepares fallible allocations/descriptors without recording,
records Stats then Gain/key writes then Apply, and updates CPU state in
`RecordInputs` (`NativePostMotionAnchor:223–286,292–332`). The wrapper leases the
graph before recording (`BridgeRR:1464–1470`). `DiscardRecordingHistory` discards
the physical context, because a CPU metadata reset cannot make an unsubmitted
key write exist (`NativePostMotionAnchor:334–337`, `BridgeRR:1821–1838`). Flat
history similarly advances parity at record time (`FlatAlbedoRecovery:631–633`)
and depends on wrapper generation abandonment on discard.

For the portable model define four states:

| State | Meaning | May become a recall source? |
|---|---|---|
| Scheduled | Constants, camera and destination slot planned; no committed queue work | No |
| Submitted | All producing commands and required barriers submitted in an ordered graph; buffers leased | Only a consumer with an explicit GPU execution dependency may reference it |
| Completed | Completion witness/fence confirms writes executed | Yes, if semantic support and generation remain valid |
| Valid | Submitted-with-dependency or completed, plus correct slot camera, frame continuity, support, domain and options | Yes |

Keep semantic `valid` independent of lifecycle state. A completed write can be
semantically invalid; a scheduled write can never be semantically published.
The conservative standalone CPU model publishes only completion. Production
can publish an ordered submitted dependency without blocking the CPU, but must
not conflate merely recording a command list with submission. Reset/cut,
invalid previous camera, frame gap, extent/DRS change, option toggle, discarded
recording or physical generation replacement invalidates the relevant ring and
history domain. Existing GPU leases retain the old generation until safe; no
new consumer may reinterpret old data under new camera metadata.

## Immutable source links

- [Shared Anchor constants](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/FSRDPostMotionAnchorConstants.h)
- [Native Anchor host](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/FSRDNrdPostMotionAnchor_Dx12.h)
- [Native Stats/Recall](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdPostMotionAnchorStatsRecall.hlsl)
- [Native Gain](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdPostMotionAnchorGain.hlsl)
- [Combined Stats/Recall](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDPostMotionAnchorStatsRecall.hlsl)
- [Combined Gain](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDPostMotionAnchorGain.hlsl)
- [Shared Apply](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDPostMotionAnchorApply.hlsl)
- [Flat recovery host](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/FSRDNrdFlatAlbedoRecovery_Dx12.h)
- [Camera conventions](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/upscalers/fsr31/FSRDCameraMatrices.h)
- [Canonical native motion](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdMotionCommon.hlsli)
- [RR wrapper routing/lifetime](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp)
- [Clip contract](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/research/astra20261020/fixtures/clips/README.md)
