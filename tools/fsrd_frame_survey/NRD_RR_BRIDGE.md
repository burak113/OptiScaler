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
independently of the skipped native lighting filters.

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

Failed initial native admission records its exact `gate` and `reason`, including
restore configuration, missing setters/heaps/PSO/tables, unknown predication,
stale births, unknown root parameter counts, source/target tables and b6 mapping.
These diagnostics do not relax admission or enable a native denoiser fallback.

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

## Validation limits

Native helper tests exercise real D3D12 resources, GPU shaders and the signed AMD
provider where stated; CPU synchronization/metadata fixtures disclose their
native-API adapters. Synthetic quality tests are not a same-scene comparison of
combined color, native NRD and split inputs. Such a three-way game recording is
still needed before claiming a game-quality or FPS gain. Colored material guides
were worse than white guides in some controlled synthetic cases; enabling them
by default is not a claim that every reflection improves.
