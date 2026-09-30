# FSRD external-output initialization diagnostic — 2026-09-30

The stain/wave objective remains open. Twelve fresh native contexts test the
external output-texture lifecycle on the frozen wave pilot. All RGB output
bits match; output alpha retains a caller-supplied sentinel. This separates
an alpha-storage observation from a demonstrated color effect and adds no
accepted runtime change or game-quality result.

An isolated copied runner C supports six preregistered modes, each twice in
forward/reverse order: legacy lifecycle; descriptor-heap binding/UAV barriers
without clear; zero clear on first frame or every frame; sentinel clear on
first frame or every frame. All nonlegacy modes share the same heaps, binding
and barriers, so that control remains separate from the clear operation.
Sentinel RGBA is exactly `[257,513,769,17]` in FP16. All seven serialized
inputs, formats/upload counts, provider and184-byte applied controls match.
The production runner and shader sources remain unchanged.

The12×64-frame contexts complete768 RR dispatches with ordinary debug-layer
and SDK errors/warnings zero under the unchanged owned-child resource guard.
Every repeat pair matches. All diffuse/specular RGB bits across all12 contexts
match, and new C mode0 matches the earlier runner-B raw lobes for this input.
The finite RGB output contains none of the three sentinel RGB components.

In all four sentinel contexts, both output lobes keep alpha17 at every pixel
through all64 frames:5,242,880 scalar matches. Non-sentinel output alpha stays
zero. Thus the earlier observed alpha0 cannot be interpreted as a confirmed
provider write of zero. Destination alpha is retained empirically; without
instrumenting the opaque kernel, absence of a write and a same-value store
cannot be distinguished. The output does not copy the input signal's hit
distance in this test. The public header's `output: Preserved` wording alone
does not settle the intended destination/input-alpha contract.

The measured ordinary composition path consumes native lobe RGB and explicitly
writes final alpha1. The separate raw-source-blit shader path copies RGBA and
has different input binding semantics. This diagnostic does not claim every
possible consumer ignores alpha. In this wave case, external zero/sentinel
initialization has no observed RGB effect and does not explain the earlier
identical-input RGB variation. It neither rules out an internal state problem
nor establishes general native determinism from two repeats per mode.

[The compact archive](evidence/fsrd_native_output_initialization/manifest.json)
retains131 files including the isolated source/build command, registrations,
guarded jobs, applied controls, reports and logs;112 full payload/build binary
files remain retained at their SHA/size-pinned F-drive paths. The new runner
SHA is9c9e15c2c0eb1f4f8a59cf67d105eef3db05377b8c296869e6e253b9a0786496.
The [independent audit](evidence/fsrd_native_output_initialization_audit/compact_v2.json)
is complete: all66 pairs/132 lobes, six repeat pairs, raw input/control
bytes, guards, logs,131 archive copies,112 external payloads and136
committed files authenticate. Its canonical V2 report preserves the initial
audit attempt's source-newline mismatch and qualifies provider-version query
unavailability, byte-pinned source versus machine-code equivalence, and the
coincidental equality of zero-valued specular input/output alpha. The audit
adds no native or GPU work. Additional
[RGB bit verification](evidence/fsrd_native_output_initialization_rgb_bit_proof.json)
uses the raw16-bit channel storage, not only numeric RMS equality.

No conversion/composition GPU jobs or quality scores are added. Completed
native totals become382 contexts/20,080 RR calls, including the earlier
64-dispatch completion with a Python metadata failure. There is still no
current-alpha game capture. The source-phase physical correction-history
candidate remains a separate saved-response CPU experiment; this output
initialization control does not change P, T(P), or its acceptance criteria.
