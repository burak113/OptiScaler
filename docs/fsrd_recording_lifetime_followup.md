# FSRD recording-lifetime follow-up — 2026-09-30

The stain/wave objective remains open. A new GPU identity fixture reproduces
constant-buffer and SRV binding aliasing when three production-style slots
wrap before execution. This is a conditional integration hazard. Actual
game submission depth, a visible stain trigger and an accepted runtime
remedy have not been demonstrated.

ComputeState, FrameDescriptorHeap and their required helper implementations
are extracted from pinned production sources without changing them. The
main cases use the exact class; two copied split-index variants independently
isolate CB-slot and descriptor-slot reuse. A small identity shader reports
two CB values and one SRV value as integers. Every dispatch has its own
immediate GPU readback copy, so a shared final output overwrite cannot hide
the earliest observation.

Nine guarded child jobs complete40 identity shader dispatches and20 queue
submissions/signals/waits, including input uploads. Five controls—three
deferred calls within capacity, immutable storage for four/five calls, and
fence-before-reuse for four/five calls—retain every intended tuple. Three
slots with four deferred calls make logical call0 consume call3's CB/SRV.
With five calls, calls0/1 consume calls3/4's values. The split cases change
only the expected CB or SRV components. Seven rows change in total; five
have changed CB values and five have changed SRV values. All match the
preregistered last-writer prediction. Ordinary debug errors/warnings are
zero. All238 producer manifest entries,118 frozen fixture references and
eight original source references authenticate in the independent audit.

There is a material API boundary. The identity fixture explicitly compiles
Root Signature1.0, which permits changing referenced descriptor/data memory
before submission. The actual embedded production InputConv, FloorSeed
and Floor shaders are CPU-deserialized separately: each uses Root
Signature1.1 with range flags0, hence static descriptors. Reusing those
descriptors before their final execution completes would violate the
static promise; the fixture's exact integer alias results are not a defined
production1.1 outcome. These distinctions follow [Microsoft's root-signature
documentation](https://learn.microsoft.com/en-us/windows/win32/direct3d12/root-signature-version-1-1).
The inspected blobs establish their own actual flags, without assuming all
other production shaders use the same signature.

Preliminary independent arithmetic/source findings were recorded before
the GPU launch. The full source-review artifact was sealed afterwards and
the actual payload audit followed; there was no final prelaunch approval
artifact. Both unsuccessful preparation attempts are retained: a missing
standard include at compilation and using a raw root chunk where the CPU
inspector required a full shader container. Neither ran a GPU job. The
pre-GPU freeze, actual source/build bytes, commands, constants, input/output
readbacks, logs, guards and chronology remain preserved.

The source-gap review also identifies successfully evaluated command lists
that are subsequently discarded without execution. Native CPU previous
camera/jitter/history state commits during recording; successful composition
can advance its ping-pong history before the unseen title submits the list.
Prior standalone native runners execute and wait every frame and therefore
do not cover this scenario. A separate discarded-recording native diagnostic
is being prepared; it has added no native work to this report.

The follow-up corrects a narrower failure-path interpretation in the
preserved earlier review: when upscale returns false, the existing
composition guard calls FinishCompositionHistory(false), invalidates
composition history and does not flip its read index. Native CPU history
has already committed and outer error handling does not generally invalidate
it. An existing helper can conservatively invalidate native history before
that false return, at the cost of losing valid accumulation if the recorded
RR prefix eventually executes. This policy candidate does not repair
successful recordings later discarded or arbitrary execution ordering.
No production change has been made.

A general deferred-submission remedy needs immutable CB/descriptor packets
owned by recording epochs, retained until recording detachment and every
submission's queue fence completes. Existing trace tickets have incomplete
coverage/identity checks, a small registry limit and unsupported repeated
submission/multi-queue cases. They cannot be reused unchanged. Reset alone
is insufficient for release because a command list can be reset while old
GPU work is still executing; see [Microsoft's Reset documentation](https://learn.microsoft.com/en-us/windows/win32/api/d3d12/nf-d3d12-id3d12graphicscommandlist-reset).
The remedy design records these requirements and the distinction between
object death, reset/discard, queued work and already recorded dependents.

The separate covariance-design assessment proposes no output estimator:
spatial holdout does not establish native/source noise independence and the
constructed exact-cancellation control shows why decorrelating a correction
can introduce error. Its optional impulse sensitivity study remains deferred.

No native SDK context or RR call, game launch, quality score, runtime setting,
shader or DLL changes are added. Completed native totals remain382
contexts/20,080 RR calls. The [compact archive](evidence/fsrd_recording_lifetime_followup/manifest.json)
preserves the fixture, independent review, source-gap/correction, lifetime
remedy design and covariance assessment. There is still no current-alpha
game capture; the known MO2 capture directory remains at September28 data.
