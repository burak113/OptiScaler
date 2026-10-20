# Job 06 adapter specification: read-only temporal support diagnostics

Status: **research only; no production image modification proposed**.
Owner of any later native integration: job08 on `sol/26-integration` after the
local gate. This file is the exact adapter specification permitted in place of
`PRODUCTION.patch` for a diagnostic-abstention result. No new HLSL, CSO or
generated shader header is required or claimed. Compiler profile/entry/flags
are not applicable until a concrete GPU diagnostic implementation exists.

## Public interchange contract

Contract identifier: `fsrd.support_coordinates.v1`.

| Field | Type / extent | Meaning |
|---|---|---|
| `frame_index` | original int, strictly consecutive when previous history is used | Original capture order; preserve bridge and Streamline indices separately if available. |
| `render_extent` | int[2], width,height | Full original render extent, never crop extent or allocation extent. |
| `crop_origin_render` | int[2], x,y | Current crop origin in original full-render pixels. |
| `previous_crop_origin_render` | int[2], x,y, or absent | Prior original crop origin. Absent invalidates history. |
| `motion_uv` | float16 or float32/64[H,W,2] | Current-to-previous full-render UV displacement; camera motion and raster jitter delta already included. |
| `motion_depth_delta` | preserved float16[H,W] | Signed previous-minus-current linear view Z, with separate provenance/possible G3 sentinel; never used as hit distance. |
| `input_depth` | float32[H,W] | Signed linear view Z; preserve sign and near/far/validity metadata. |
| `input_normal_roughness` | uint32[H,W] | Actual provider R10G10B10A2; RG oct world normal, B linear roughness, A category. |
| `recovery_original_normal_roughness` | optional uint32[H,W] | Original guide before the flat/NZR roughness floor; explicit unknown when absent. |
| `stages` | mapping of role name to arrays | Named observations. Input and RR D/S are FP16 RGBA; never sum in half or discard alpha in storage. |
| `valid_mask` | bool[H,W] | Observation validity independent of candidate output; not an object class. |
| `baseline_masks` | mapping to immutable bool[H,W] | Fixed baseline evaluation supports and denominators, hashed before candidate evaluation. |
| `provider_controls` | uint32[46] | Exact native suffix of 448-byte dispatch, offset264, length184. Preserve bits. |
| `metadata` | typed JSON | Stage timing, source hashes, stage identity, units, settings, camera/jitter, reset, bounds, formats, crop/stride and known missing observations. |

The 46-word dispatch suffix layout is: float words 0:3 motion scale,
3:5 jitter pixels, 5:8 camera-position delta, 8:24 view, 24:40 projection,
40:42 linear-depth bounds; uint words42:44 render extent, word44 provider
frame index and word45 flags (bit0 reset, bit1 non-gamma albedo). Matrix words
in this suffix are the transpose returned by `GetRRMatrix`; separately exported
`view_u32`/`projection_u32` are bridge column-vector matrices stored row-major.
See `OptiScaler/upscalers/fsr31/FSRDRRInterop.h:11–17`. Do not interchange these
representations without that explicit transpose.

The initial CPU implementation exposes `support_tracer.CoordinateConvention`,
`previous_coordinates`, `sample_previous`, `trace_stages`, `diagnose`, and
`abstain_identity`; inspect their signatures in source for Python calling
syntax. This interchange is the semantic boundary. It does not assume access
to another job's uncommitted modules.

For current local integer pixel centre `p`, the only allowed surface warp is

```text
q_previous_local = p + current_crop_origin_render
                     + motion_uv * render_extent
                     - previous_crop_origin_render
```

The +0.5 centre offsets cancel. The packaged
`fixtures/clips/clip_loader.py:previous_coordinates` and `sample_previous`
are the reference for this convention. Float64 CPU bilinear arithmetic is a
diagnostic model, not bit parity with a D3D texture sampler. Bilinear support
requires finite coordinates, 0≤qx<previous_width−1 and
0≤qy<previous_height−1. Invalid samples carry an invalid mask/NaN internally;
JSON reports use `null` plus reason, never nonstandard NaN.

No clamping, wrapping, implicit resize, second jitter subtraction or
render-to-crop MV rescaling is permitted. Unknown convention must cause a
validation error/abstention, not a guessed conversion. A virtual/reflection
warp must be a differently named diagnostic with its independent assumptions;
do not overload surface `motion_uv`.

### Job04 compatibility gate

Job04 is asked to publish a reusable coordinate/support API; that deliverable
is not available in this handoff. No claim of actual cross-job collaboration
or imported job04 revision is made. Job08 may replace the local wrapper with
a committed job04 implementation only after matching:

1. changing crop origin exactly cancelling physical UV motion;
2. sign reversal, render/crop scale confusion and extra jitter mutants fail;
3. no valid history at startup, frame gap, reset or unavailable prior crop;
4. partial entry/exit never converts missing history into a valid edge sample;
5. fixed-mask denominator independent of candidate and MV mutant;
6. packed original/provider normal distinction and separate hit/dz units;
7. source arrays and alpha words remain bit-identical after diagnostics.

## Stage names and exact native snapshot positions

| Diagnostic role | Source and recording point | Limit |
|---|---|---|
| `input_specular`, `input_diffuse` | `RRWrapper::GetOwnedOutputSnapshot` providerPhysicalSpec/providerPhysicalDiff; copy in `RecordBridgeOwned` after RecordOwned completes recording and scale restoration, before commit | After Anchor, before optional turn processing; retain actual enable settings. |
| `input_motion` | snapshot providerMotion, else owned converted motion | Finalized provider MV, possibly G3 B rejection sentinel. |
| `surface_motion_original` | additional optional copy of `input.motion` before LightingGuard substitution | Needed only to separate original B prediction from G3; not in current clips. |
| `input_normal_roughness` | providerNormals, after FlatAlbedo preparation | Original roughness may differ. |
| `recovery_original_normal_roughness` | owned input.normals when flat recovery active | Existing trace already has this role. |
| `raw_rr_specular`, `raw_rr_diffuse` | snapshot rawSpec/rawDiff after provider and physical-unit restoration | Contains opaque prior provider history, not clean truth. |
| `selected_rr_specular`, `selected_rr_diffuse` | snapshot selectedSpec/selectedDiff after lobe and flat/NZR recovery | May alias raw; alias map must be retained. |
| `encoded_commit_specular`, `encoded_commit_diffuse` | `CompleteBridgeFrame`, after successful CommitOwned on the identical live transaction | Before original Consumer; destination alpha is title-owned. |
| `final_output` | separately requested title/upscaler capture keyed to the same frame | Explicitly unavailable unless independently captured. |

Existing integration entry points are
`FSRDNrdBridge_Dx12.cpp:2176–2189,2269–2287`,
`FSRDGameTraceSession.cpp:2016–2190,2302–2360` and
`FSRDGameTraceBridgeMetadata.h:25–138`. Reuse the owned readback/fence protocol:
retain physical resources until the actual execution fence completes; do not
infer completion from CPU command recording or a later wrapper's mutable state.
Do not retain borrowed title targets beyond the established live transaction.
Copy before reuse/overwrite; keep source/returned resource state transitions
and command-list ordering unchanged.

## Candidate behavior and missing-data policy

The conservative candidate is an observational classifier plus identity image
handoff. It emits supported diagnostic labels/evidence and an `abstain` status
when causal witnesses are absent or inconsistent. It does not alter RGB,
alpha, MVs, depth, roughness, provider controls, reset flags or chosen selected
output. The identity handoff preserves all original array words. The candidate
cannot claim a quality gain: preservation is its designed behavior.

No frame of rendering latency is added. Offline adjacent-frame analysis has a
one-previous-observation dependency and produces no runtime feedback. The
diagnostic state consists only of prior observation metadata and baseline mask
identity. At reset, gap, extent/convention change, unavailable crop, invalid
identity or discarded recording, invalidate comparison state; still preserve
the rendered frame. Do not reset the AMD provider or NZR to reset diagnostic
state. Scheduled/recorded/submitted/completed/valid are separate native states;
publish CPU evidence only after completion.

Absent final output, albedo, full settings, G3 maps, hit-distance provenance,
independent object trajectory or earlier history must be represented as
missing. Available input alpha may inform a hypothesis but cannot manufacture
a static planar reflector or a virtual-feature truth trajectory.

## Diagnostic interventions, never production fixes

Oracle source support and oracle MVs are synthetic-only controls. A current-
input-only view exposes accumulation cost but is not a denoising replacement.
Swapping raw/selected display observation affects the diagnostic view, not the
native committed image. Freeze support while changing radiance to test whether
the metrics confuse level with movement. An optional local controlled reset
belongs to a separately labelled diagnostic branch with matched warmup and
consecutive capture order; do not enable it in the working preset.

Any later local A/B must preserve D16/S256, G2/G3, RR Fallback, Diffuse RR,
Reflection History and Temporal OFF. Keep Anchor, PostFlick, ColourTrack and
old turn filters OFF. Keep the user's existing glass blend choice. Existing
settings may be varied one at a time only as explicitly labelled diagnostics,
recording exact effective settings and restoring the protected branch for the
paired reference. No automatic game installation or production activation is
part of this adapter.

## Local acceptance for an eventual integration

Readback-only mode first establishes unchanged native output words and correct
stage/frame identity on a fresh unlooped trajectory. Check D3D debug, transition
and lifetime errors, queue submission/fences, allocation/active extent, partial
crop boundaries and caller-declared native target state. Capture overhead and
resident allocation are measured locally; no CPU runtime is a GPU budget.

Only after a new native capture separates a mechanism may job08 evaluate a
production candidate. It must reduce shape lag/disocclusion leakage at matched
level without losing static text, glass/water reflections, true-light response,
or increasing grain/sparkles/flicker. The current diagnostic-only result has no
shader compiler or final game quality acceptance claim.
