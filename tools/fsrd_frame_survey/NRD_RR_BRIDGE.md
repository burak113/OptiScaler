# Cyberpunk split lighting → AMD Ray Regeneration

This bridge replaces the title's native NRD lighting denoising with AMD RR. The
title still produces its raw diffuse/specular signals, material data and camera
data and performs its own final lighting composition. Neither native NRD filtered
lighting nor native NRD temporal history is an RR correction or fallback.

## Signal contract

The two native lighting transactions have independent RR histories. The bridge
captures A before Recon and B before PrePass, while their exact source bindings
are still valid. Private GPU buffers retain the required constants and raw
samples. Depth, normals, material guides and optional surface motion are prepared
independently of the skipped native lighting filters. Motion Z defaults to a
camera-only previous-surface estimate (static geometry; object motion is not
reconstructed) with an explicit finite `0` for an unknown row; the pre-fix
previous-visible-depth sample remains only as an explicit A/B rollback setting.

The final compute Consumer reads b6/space0 word303; the final pixel compositor
reads word36. Small shaders read those exact live GPU bindings and select RGB or
YCoCg for the owned inputs and final RR output. Resource-address lookup remains
diagnostic. The game keeps its factor64, exposure and material composition.

Native finite alpha is preserved, including signed zero. The native multiplication
by1000 was a reconstruction weight that cancels during normalization; it is not a
hit-distance unit conversion. Nonfinite values are sanitized explicitly.

This describes the raw RR **input** alpha. Final commit preserves the title
target's opaque alpha; its current initialization after native elision is not
proved. Both attested retained consumers read only RGB from these targets. That
opaque channel is not an RR history/input or a current hit-distance claim.

For B, PrePass b6 register36.xy selects full-resolution mode2 or checkerboard0/1.
Register32.y supplies the local parity phase, register28.zw the signed origin and
register29.zw the **integer** rectangle dimensions. Known traced pixels retain
their decoded RGBA. Only missing checkerboard pixels receive an input
reconstruction from traced neighbors using independent depth/normal guidance.
This is followed by RR for both lobes; native PrePass filtering is not executed.

The old game captures do not contain the live selector operands, so actual
checkerboard activation in the user's scene is **not established**. Game_Trace
records the owned native operands so a subsequent user recording can answer it.
An actual signed AMD provider experiment rejected the proposed full-resolution
negative-alpha shortcut: inactive poisoned RGB leaked into the output. That
shortcut is not used.

A separate signed-provider control compared the new reconstruction with native
SDK packed checkerboard input. The two are approximate alternatives: in that toy
scene the reconstructed input had higher RGB error and slightly lower chroma
error. This is a preserved negative result, not evidence of a quality gain.

## Submission and lifetime

A mandatory recording token is retained before the first native dispatch is
omitted. Incomplete or invalid transactions deny the original queue submission;
they do not resume native denoising. After native history is superseded, switching
back to native NRD requires restarting the game.

Exact retained slot/resource/heap births, generations, formats and subresources
are checked again before submission. Intervening indirect/draw work requires
known complete shader identities, a pure indirect signature and bounded checks
that its actually used image bindings do not touch pending lighting targets.
Unknown actual work fails closed. Unknown PSO assignment alone is not work.
The native omission contract is pinned to the supported complete shader hashes;
unclassified work outside a pending interval is not a general game-version proof.

An intervening image binding needs a whole-resource exclusion proof, not an image
snapshot. A native plane-1 stencil SRV can therefore retain its exact live
resource identity even though the current copy/readback path does not support
that plane. This purpose is explicit in each retained witness. Source capture,
commit and ordinary snapshot resolution keep their stricter supported-view
requirement. Both purposes retain root/table mapping, heap/resource births,
generation, format, subresource and current descriptor-slot validation. An
unknown binding or a descriptor changed before submission still rejects the
required transaction. Only the statically used slots of an attested intervening
shader are queried; no new resource/heap scan or native denoiser work is added.

Before a required RR interval, an attested execution-only indirect signature
preserves the CPU root/heap/PSO snapshot even for an unclassified shader. These
bindings are inherited by the call; only state specified by a command signature
is changed/reset ([Microsoft's indirect drawing contract](https://learn.microsoft.com/en-us/windows/win32/direct3d12/indirect-drawing)).
Discarding this unchanged snapshot before the first Recon prevented hot RR
activation when the title reused its bound heaps. The common pre-Recon path
validates immutable signature metadata without taking the injection mutex.
Pending RR outputs still require the complete shader/resource exclusion proof;
unknown or state-changing signatures retain their invalidation behavior.
Known native denoiser/Consumer roles invoked indirectly are explicitly denied
while RR is requested: the supported native profile requires direct Dispatch for
its raw capture, filter omission and late commit. Binding inheritance alone does
not authorize an indirect native denoiser invocation.

The game's B targets have RTV as well as UAV creation flags. Intervening graphics
work therefore checks the actual bound render targets, rather than rejecting a
target merely because it is renderable. At most eight bind-time RTV identities
are captured independently of the short root/table window. Only distinct output
sets consume a retained proof slot; repeated actor draws into the same targets do
not exhaust the bounded proof. Actual B overlap, missing output metadata and
depth-capable pending targets still deny admission. Exact resource births and
generations are validated again before submission. CPU RTV descriptor slots may
be reused after binding: their contents have already been copied into the command
list ([Microsoft's non-shader-visible descriptor contract](https://learn.microsoft.com/en-us/windows/win32/direct3d12/non-shader-visible-descriptor-heaps)).
Reset/ClearState discard the previous output state, and list retirement detaches
only that exact list birth. No global resource or heap traversal is added.

Failed initial native admission records its exact `gate` and `reason`, including
restore configuration, missing setters/heaps/PSO/tables, unknown predication,
stale births, unknown root parameter counts, source/target tables and b6 mapping.
These diagnostics do not relax admission or enable a native denoiser fallback.
Invalidated pending work also records the first cause, chain mask and complete
available shader identities. Submission rejection distinguishes missing output,
retained texture/constant/pipeline/signature/output proof, and unpublished history
ordering. Fence callback failures include their phase and exact recording IDs.
An intervening texture-binding rejection also records its first resolver reason,
profile, SRV/UAV register and space, root parameter, descriptor offset/address,
view format and supported-copy/dimension flags. This distinguishes a missing or
stale binding from a valid native plane that only lacks snapshot support.

The descriptor admission protocol joins each native descriptor mutation with its
metadata publication. Writers use fixed sharded atomic counters. A participating
queue closes the gate, drains those fixed counters, validates witnesses and keeps
the gate closed through the real Execute call. The frequent path does not scan
all resources or heaps. Retiring a populated heap detaches its registry indexes
before draining affected descriptor edges.

## Tuning and recording

The CP77 NRD bridge menu exposes RR controls and an input map independently of
the selected upscaler. Native material guides default on; independent native
surface motion and separate lobe recovery remain experiments. Recovery never
uses native NRD filtered lighting. Obsolete native specular blending is removed.

The single `[NRD_BRIDGE] perf` row samples the first100 gameplay Consumer intervals,
including inactive bridge hook costs, and separates lock/admission wait. CPU
recording intervals are not GPU timings or displayed/FG FPS. The stage row
reports overlapping CPU spans and must not be summed into frame time.

Game_Trace is explicitly user armed. It captures the exact owned RR inputs,
actual dispatch settings, raw/selected RR output, committed output and typed
native control words. Its bridge-generated GPU status is separate from native
operands. Trace-off does not perform capture copies or payload readback. Required
GPU status checking is independent of whether Trace is armed.

Full temporal replay requires a complete full-render consecutive prefix starting
with an actual SDK RESET. ROI, missing inputs or an incomplete history prefix are
inspect-only. Replay requires an explicitly selected trusted local provider whose
file identity/hash matches the recorded entrypoint module. Captures never select
an executable DLL path. This attests that module on disk, not its transitive
dependencies or loaded-memory contents.

## Temporal coordinate contract

Every consumer of the owned motion texture (`u5` of the conversion, one grid at
the current internal render size) is listed with the units, direction, jitter
content, resolution and reset behavior it actually sees. Sizes below are the
current render resolution unless stated. The provider's own internal use of its
XY input is **not** established by this table; it is the subject of the jitter
experiment plan at the end.

| Consumer | Grid / units | Direction and jitter content | Resolution | Reset behavior |
|---|---|---|---|---|
| AMD RR provider (`motionVectors`) | UV fraction of the render size; the texture is bound unchanged and the SDK jitter offsets are passed separately | current sample -> previous sample. `raw * motionScale + (previousJitter-currentJitter)/size` when the title field is **not** jittered; the raw field alone when it is (the field already is a raster displacement). One jitter delta, never two | current internal render grid | XY is not zeroed; the reset is the provider RESET flag plus `B=0` on frames without a coherent previous camera row |
| Provider B (same texture, `.z`) | signed previousLinearDepth - currentLinearDepth in the RR camera depth bounds | native same-surface (native path), camera-only static-surface, or legacy rollback. `unknown` means exactly `0` (finite no-op), never a guessed delta | current grid | `0` on reset/without previous row |
| Provider W (`.w`) | constant `1.0` | no validity/confidence meaning is attached; never used as a confidence mask | current grid | unchanged by reset |
| Bridge previous-depth lookup (legacy rollback only) | `floor(pixel + 0.5 + XY*size)` in the previous frame's grid | samples the bridge-owned R32F signed depth of the previous frame (the previously VISIBLE surface, which can be an old occluder) | previous frame at the same render size | not sampled when the previous row is invalid |
| Recovery Reference (`FSRDNrdLobeRecoveryReference` t6) | `p + (XY - pixelJitters.zw) * size`; canonical (jitter-free) reference grid | jitter delta removed here on purpose; `pixelJitters.zw = (previousJitter-currentJitter)/size` is supplied by the host and is independent of the source-field convention | current render grid | history flag off -> current-frame reference only |
| Recovery Accumulate (`FSRDRecoveryLobeAccumulate` t9) | `p + XY * size`; raster grid (jitter included) | expected previous Z is `z + mv.z`; gate `mv.w >= 0.5` (always true here) plus geometry/validity | current render grid | `RECOVERY_FLAGS_HISTORY_VALID` off |
| Recovery Band (`FSRDRecoveryLobeBand` t8) | `(centre + XY*size)/scale - 0.5` at each level | same raster displacement rescaled to the level grid; gate `mv.w >= 0.5` | levels are ceil-halves of the render size | history flag off |

`pixelJitters.xy` is the current jitter in render pixels ("pixel p samples
p - Jitter"), so the Reference and Band remain on different grids even though
they read the same texture - that is deliberate and not a defect to fix in one
consumer only. The unjittered source must keep adding exactly one jitter delta;
the jittered source must not be displaced twice. Both are pinned by the CPU
oracle vector (T04: static physical motion, one 0.5 px jitter difference) and by
the conversion fixture's GPU T04 frames, and the occluder counterexample is
pinned separately (legacy B self-verifies with a zero residual against the old
visible surface; the camera-only default does not).

### Jitter experiment plan (not yet run)

Two questions must be answered with the same raw sequence:

1. **Source consistency.** Is the title field actually a raster displacement when
   `motionVectorsJittered` is set, and a jitter-free field when it is not? The
   recording must show the flag and the field together; changing only the flag
   would break this question while answering the next one with inconsistent data.
2. **Signed-provider raw output.** With a consistent source, how does the signed
   provider's raw output change when the bridge feeds `XY` with the jitter delta
   versus a jitter-free `XY`? Both variants need identical history starts.

Conditions: Recovery off, one fixed guide policy (white or native, not both), the
same provider binary hash and a fresh SDK RESET; fixed camera; a subpixel line
pattern; a slow pan. The repeat-noise baseline on a static-pattern segment is
measured separately so a jitter-frequency error is not confused with repeat
noise. The decision combines the provider comparison with this coordinate table;
changing a shader line alone is not accepted as evidence. Until then the current
jitter/grid behavior is intentionally unchanged.

## Validation limits

Native helper tests exercise real D3D12 resources, GPU shaders and the signed AMD
provider where stated; CPU synchronization/metadata fixtures disclose their
native-API adapters. Synthetic quality tests are not a same-scene comparison of
combined color, native NRD and split inputs. Such a three-way game recording is
still needed before claiming a game-quality or FPS gain. Colored material guides
were worse than white guides in some controlled synthetic cases; enabling them
by default is not a claim that every reflection improves.
